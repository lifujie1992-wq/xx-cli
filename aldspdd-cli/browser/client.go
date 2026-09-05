package browser

import (
	"encoding/json"
	"fmt"
	"net/http"
	"time"
)

const DefaultDaemonURL = "http://127.0.0.1:10088"

// Client 是 OpenBridge 守护进程的轻量 HTTP 客户端。
// 所有对 Agiso 的调用都通过浏览器内的 evaluate 执行，
// 复用用户真实登录态（cookie + localStorage 里的 TOKEN），不在 Go 侧持有任何凭证。
type Client struct {
	baseURL string
	session string
	http    *http.Client
}

func NewClient(session string) *Client {
	return &Client{
		baseURL: openBridgeURL(),
		session: session,
		http:    &http.Client{Timeout: 120 * time.Second},
	}
}

func (c *Client) Call(action string, args map[string]any) (json.RawMessage, error) {
	return c.callOpenBridge(action, args)
}

func (c *Client) FindTab(url string, active bool) error {
	_, err := c.Call("find_tab", map[string]any{"url": url, "active": active})
	return err
}

func (c *Client) Navigate(url string) error {
	_, err := c.Call("navigate", map[string]any{"url": url, "newTab": true})
	return err
}

// Evaluate 在页面上下文里执行 JS，返回其求值结果。
// JS 不能用顶层 return —— 用 async IIFE：(async()=>{ ... return x })()
func (c *Client) Evaluate(code string) (json.RawMessage, error) {
	return c.Call("evaluate", map[string]any{"code": code})
}

// EvalJSON 执行返回 JSON 字符串的 JS，并反序列化到 out。
// 约定页面侧 JS 返回 JSON.stringify(...)，evaluate 的结果形如 {"type":"string","value":"..."}。
func (c *Client) EvalJSON(code string, out any) error {
	raw, err := c.Evaluate(code)
	if err != nil {
		return err
	}
	var wrap struct {
		Type  string `json:"type"`
		Value string `json:"value"`
	}
	if err := json.Unmarshal(raw, &wrap); err != nil {
		return fmt.Errorf("unexpected evaluate result: %w", err)
	}
	if wrap.Value == "" {
		return fmt.Errorf("empty evaluate value")
	}
	if err := json.Unmarshal([]byte(wrap.Value), out); err != nil {
		return fmt.Errorf("decode page JSON: %w (raw: %.200s)", err, wrap.Value)
	}
	return nil
}
