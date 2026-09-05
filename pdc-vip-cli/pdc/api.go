// Package pdc wraps the VIP PDC (pdc-portal.vip.com)供应商创建商品 backend.
//
// All calls run as `fetch()` inside the user's logged-in Chrome tab (via the
// OpenBridge daemon), so cookies/auth come for free. We only ever need the
// tab to be on the pdc-portal.vip.com origin (same-origin fetch).
//
// Endpoint archaeology lives in ../ARCHAEOLOGY.md.
package pdc

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"pdc-cli/browser"
)

const origin = "https://pdc-portal.vip.com"

// addPage is a lightweight authenticated page on the right origin; navigating
// here gives us same-origin fetch + live cookies without side effects.
const addPage = origin + "/admin#/product/add?vendorType=1"

// EnsureReady makes sure the active tab is on the pdc-portal.vip.com origin so
// that our same-origin fetch() calls inherit the login session. If the tab is
// elsewhere (or no tab yet), it navigates to the create-product page and waits
// for the origin to settle.
func EnsureReady(c *browser.Client) error {
	cur, err := c.EvaluateString("location.origin")
	if err == nil && cur == origin {
		return nil
	}
	if err := c.Navigate(addPage, err != nil); err != nil {
		return fmt.Errorf("navigate to pdc-portal: %w", err)
	}
	for i := 0; i < 20; i++ {
		time.Sleep(400 * time.Millisecond)
		if cur, err := c.EvaluateString("location.origin"); err == nil && cur == origin {
			return nil
		}
	}
	return fmt.Errorf("tab never reached %s — is Chrome logged in to VIP 供应商平台?", origin)
}

// apiPost runs `POST {origin}{path}` inside the page with the given JSON body
// and returns the raw response text. The body is base64-embedded to dodge all
// JS/JSON quote-escaping issues.
func (a *API) apiPost(path, jsonBody string) (string, error) {
	return a.apiPostRaw(path, "application/json", jsonBody)
}

// apiPostRaw is the general form: arbitrary content-type + raw body string.
func (a *API) apiPostRaw(path, contentType, rawBody string) (string, error) {
	return a.fetchAbs(origin+path, contentType, rawBody)
}

// fetchAbs POSTs to an absolute URL (used for the second backend
// mp-product.vip.com). Same-origin policy is fine: the pdc-portal page is
// allowed to call mp-product with credentials.
func (a *API) fetchAbs(u, contentType, rawBody string) (string, error) {
	b64 := base64.StdEncoding.EncodeToString([]byte(rawBody))
	code := fmt.Sprintf(
		`(async()=>{try{const r=await fetch(%q,{method:"POST",headers:{"content-type":%q},credentials:"include",body:atob(%q)});return await r.text()}catch(e){return JSON.stringify({__fetchError:String(e&&e.message||e)})}})()`,
		u, contentType, b64,
	)
	return a.c.EvaluateString(code)
}

// API is a thin handle bound to a browser client.
type API struct{ c *browser.Client }

func New(c *browser.Client) *API { return &API{c: c} }

// envelope is the common VIP response wrapper.
type envelope struct {
	Code   int             `json:"code"`
	Msg    string          `json:"msg"`
	Result json.RawMessage `json:"result"`
}

func decodeEnvelope(raw string, dest any) error {
	if strings.Contains(raw, "__fetchError") {
		return fmt.Errorf("browser fetch failed: %s", raw)
	}
	var env envelope
	if err := json.Unmarshal([]byte(raw), &env); err != nil {
		head := raw
		if len(head) > 200 {
			head = head[:200]
		}
		return fmt.Errorf("decode response (%s): %w", head, err)
	}
	if env.Code != 200 {
		return fmt.Errorf("api code=%d msg=%q", env.Code, env.Msg)
	}
	if dest == nil {
		return nil
	}
	return json.Unmarshal(env.Result, dest)
}

// ----- login-status -----

// User identifies the logged-in vendor account.
// (getCurrentUserInfo returns {user, vendorCode}.)
type User struct {
	User       string `json:"user"`
	VendorCode string `json:"vendorCode"`
}

// LoggedIn reports whether a real account came back.
func (u User) LoggedIn() bool { return u.User != "" }

func (a *API) CurrentUser() (*User, error) {
	// getCurrentUserInfo is a GET; reuse apiPost shape via a GET fetch.
	code := `(async()=>{try{const r=await fetch("` + origin + `/user/getCurrentUserInfo",{credentials:"include"});return await r.text()}catch(e){return JSON.stringify({__fetchError:String(e)})}})()`
	raw, err := a.c.EvaluateString(code)
	if err != nil {
		return nil, err
	}
	var u User
	if err := decodeEnvelope(raw, &u); err != nil {
		return nil, err
	}
	return &u, nil
}

// ----- categories -----

// Category is one node of the 3-level 商品分类 tree.
type Category struct {
	CategoryID int        `json:"categoryId"`
	Name       string     `json:"name"`
	Type       int        `json:"type"`
	Status     int        `json:"status"` // 0=启用 1=停用
	Children   []Category `json:"children"`
}

// Disabled reports whether this category is 停用 (status==1).
func (c Category) Disabled() bool { return c.Status == 1 }

// Categories returns the full 商品分类 tree the vendor is allowed to use.
// When includeDisabled is false, 停用 (status==1) nodes are pruned.
func (a *API) Categories(includeDisabled bool) ([]Category, error) {
	raw, err := a.apiPost("/product/getCategorys", "{}")
	if err != nil {
		return nil, err
	}
	var roots []Category
	if err := decodeEnvelope(raw, &roots); err != nil {
		return nil, err
	}
	if includeDisabled {
		return roots, nil
	}
	return pruneDisabled(roots), nil
}

func pruneDisabled(in []Category) []Category {
	var out []Category
	for _, c := range in {
		if c.Disabled() {
			continue
		}
		c.Children = pruneDisabled(c.Children)
		out = append(out, c)
	}
	return out
}

// ----- category config -----

// ----- category attribute catalog (attributeId + options) -----

const mpProduct = "https://mp-product.vip.com"

// AttrOption is one选项 of an enum attribute.
type AttrOption struct {
	OptionID int    `json:"optionId"`
	Name     string `json:"name"`
}

// AttrDef is one类目属性 with its option universe.
type AttrDef struct {
	AttributeID  int    `json:"attributeId"`
	Name         string `json:"name"`
	DataType     int    `json:"dataType"`     // 2=枚举 0=文本 6=图片型…
	RequiredType int    `json:"requiredType"` // 1=必填
	OptionFormat struct {
		AttrOptsList []AttrOption `json:"attrOptsList"`
		ChoiceType   int          `json:"choiceType"` // 2=可多选
	} `json:"optionFormat"`
}

// Required reports whether this attribute must be filled.
func (d AttrDef) Required() bool { return d.RequiredType == 1 }

// AttributeCatalog fetches the full attribute+option catalog for a leaf category
// from the second backend (mp-product.vip.com/api/vc/productCategory/getCategoryAttribute).
// This is what an agent needs to map cleaned attribute values → optionId.
func (a *API) AttributeCatalog(categoryID int) ([]AttrDef, error) {
	body := fmt.Sprintf(
		`{"categoryId":%d,"reqContext":{"platformInfo":{"platform":1},"appId":"pdc-portal.vip.com"}}`,
		categoryID)
	raw, err := a.fetchAbs(mpProduct+"/api/vc/productCategory/getCategoryAttribute",
		"application/json", body)
	if err != nil {
		return nil, err
	}
	if strings.Contains(raw, "__fetchError") {
		return nil, fmt.Errorf("browser fetch failed: %s", raw)
	}
	var env struct {
		Data   []AttrDef `json:"data"`
		Result []AttrDef `json:"result"`
	}
	if err := json.Unmarshal([]byte(raw), &env); err != nil {
		return nil, fmt.Errorf("decode attr catalog (%s): %w", trunc(raw, 200), err)
	}
	if len(env.Data) > 0 {
		return env.Data, nil
	}
	return env.Result, nil
}

// CategoryConfig is the category-level switch set from queryCategoryAttributes
// (drives which sections/uploads are required for a given leaf category).
func (a *API) CategoryConfig(categoryID int) (map[string]any, error) {
	raw, err := a.apiPost("/product/queryCategoryAttributes",
		fmt.Sprintf(`{"categoryId":%d}`, categoryID))
	if err != nil {
		return nil, err
	}
	var cfg map[string]any
	if err := decodeEnvelope(raw, &cfg); err != nil {
		return nil, err
	}
	return cfg, nil
}

// ----- product detail -----

// Product is returned verbatim (the full ~23KB object). We keep it as a generic
// map so every field survives round-tripping; callers print or transform it.
func (a *API) Product(vendorProductID string, vendorType int) (map[string]any, error) {
	path := fmt.Sprintf("/product/queryVendorProductByVpIdForVc?vendorProductId=%s&vendorType=%d",
		vendorProductID, vendorType)
	raw, err := a.apiPost(path, "{}")
	if err != nil {
		return nil, err
	}
	var p map[string]any
	if err := decodeEnvelope(raw, &p); err != nil {
		return nil, err
	}
	return p, nil
}

// ----- write path (create / save) -----

// SkuPreCheck runs the NON-DESTRUCTIVE SKU pre-check that the page fires before
// a real save (POST /product/saveProduct?editPreCheck). Body is the itemSkuAttr
// array. Returns (ok, message). It does not persist anything.
func (a *API) SkuPreCheck(itemSkuAttr any, vendorType int) (bool, string, error) {
	body, err := json.Marshal(itemSkuAttr)
	if err != nil {
		return false, "", fmt.Errorf("marshal itemSkuAttr: %w", err)
	}
	raw, err := a.apiPost(
		fmt.Sprintf("/product/saveProduct?editPreCheck&vendorType=%d", vendorType),
		string(body))
	if err != nil {
		return false, "", err
	}
	var env envelope
	if err := json.Unmarshal([]byte(raw), &env); err != nil {
		return false, raw, nil // surface raw if it isn't the usual envelope
	}
	return env.Code == 200, strings.TrimSpace(env.Code200Msg()), nil
}

// SaveProduct PERSISTS the product as a draft (POST /product/saveProductV2,
// application/x-www-form-urlencoded, fields productVo=<json>&vendorType=N&
// checkTipsConfirm=<bool>). This is a real write. Returns a parsed SaveResult.
//
// confirmTips mirrors the UI's「已知悉，确定修改」button: when the backend returns
// checkResultCode 501 (non-blocking content warnings — 旧→新 属性迁移、违规词等),
// the first save is rejected (result=false). Re-submitting with checkTipsConfirm=true
// acknowledges the warnings and persists anyway.
func (a *API) SaveProduct(productVo json.RawMessage, vendorType int, confirmTips bool) (*SaveResult, error) {
	form := url.Values{}
	form.Set("productVo", string(productVo))
	form.Set("vendorType", strconv.Itoa(vendorType))
	form.Set("checkTipsConfirm", strconv.FormatBool(confirmTips))
	raw, err := a.apiPostRaw("/product/saveProductV2",
		"application/x-www-form-urlencoded", form.Encode())
	if err != nil {
		return nil, err
	}
	var env struct {
		Code   int        `json:"code"`
		Msg    string     `json:"msg"`
		Result SaveResult `json:"result"`
	}
	if err := json.Unmarshal([]byte(raw), &env); err != nil {
		return nil, fmt.Errorf("decode save response (%s): %w", trunc(raw, 200), err)
	}
	if env.Code != 200 {
		return nil, fmt.Errorf("save api code=%d msg=%q", env.Code, env.Msg)
	}
	env.Result.Raw = raw
	return &env.Result, nil
}

// SaveResult is the business-layer outcome of saveProductV2.
type SaveResult struct {
	Result          bool `json:"result"`          // true = persisted
	CheckResultCode int  `json:"checkResultCode"` // 501 = content warnings need confirm
	ErrorList       []struct {
		CheckResultCode int      `json:"checkResultCode"`
		ErrorMsgList    []string `json:"errorMsgList"`
	} `json:"errorList"`
	Raw string `json:"-"`
}

// Warnings flattens all errorMsgList entries.
func (s SaveResult) Warnings() []string {
	var out []string
	for _, e := range s.ErrorList {
		out = append(out, e.ErrorMsgList...)
	}
	return out
}

// NeedsConfirm reports the 501 "acknowledge warnings to persist" state.
func (s SaveResult) NeedsConfirm() bool { return !s.Result && s.CheckResultCode == 501 }

func trunc(s string, n int) string {
	if len(s) > n {
		return s[:n]
	}
	return s
}

// Code200Msg returns a human message regardless of success/fail.
func (e envelope) Code200Msg() string {
	if e.Code == 200 {
		return "ok"
	}
	return fmt.Sprintf("code=%d msg=%s", e.Code, e.Msg)
}

// ----- image upload (local file -> VIP image CDN url) -----

var imageMime = map[string]string{
	".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
	".webp": "image/webp", ".gif": "image/gif",
}

// UploadImage pushes a local image file to VIP's own image server
// (POST /file/uploadImage, multipart: file+bizType+vendorType) and returns the
// hosted a.vpimg*.com URL to drop into productVo.itemImages/squareImages.
// No third-party host needed — VIP stores it and returns the URL.
func (a *API) UploadImage(localPath, bizType string, vendorType int) (string, error) {
	data, err := os.ReadFile(localPath)
	if err != nil {
		return "", fmt.Errorf("读取图片 %s: %w", localPath, err)
	}
	ext := strings.ToLower(filepath.Ext(localPath))
	mime := imageMime[ext]
	if mime == "" {
		mime = "image/jpeg"
	}
	if bizType == "" {
		bizType = "skuSuitDetailImage"
	}
	b64 := base64.StdEncoding.EncodeToString(data)
	name := filepath.Base(localPath)
	code := fmt.Sprintf(
		`(async()=>{try{const b64=%q;const bin=atob(b64);const u=new Uint8Array(bin.length);for(let i=0;i<bin.length;i++)u[i]=bin.charCodeAt(i);`+
			`const blob=new Blob([u],{type:%q});const fd=new FormData();fd.append("file",blob,%q);fd.append("bizType",%q);fd.append("vendorType",%q);`+
			`const r=await fetch("%s/file/uploadImage",{method:"POST",body:fd,credentials:"include"});return await r.text()}catch(e){return JSON.stringify({code:-1,msg:String(e&&e.message||e)})}})()`,
		b64, mime, name, bizType, strconv.Itoa(vendorType), origin)
	raw, err := a.c.EvaluateString(code)
	if err != nil {
		return "", err
	}
	var env struct {
		Code   int    `json:"code"`
		Msg    string `json:"msg"`
		Result string `json:"result"`
	}
	if err := json.Unmarshal([]byte(raw), &env); err != nil {
		return "", fmt.Errorf("decode upload response (%s): %w", trunc(raw, 160), err)
	}
	if env.Code != 200 || env.Result == "" {
		return "", fmt.Errorf("上传失败 code=%d msg=%q", env.Code, env.Msg)
	}
	return env.Result, nil
}
