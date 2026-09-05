package taobao

import (
	"encoding/csv"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"

	"taobao-cli/browser"
)

// Item is one product row. Title + Link come verbatim from the zzb plugin's
// "复制" output; Price/Sales are read from the card and used as filter criteria.
type Item struct {
	Page  int     `json:"page"`
	Title string  `json:"title"`
	Price float64 `json:"price"`
	Sales int     `json:"sales"`
	ID    string  `json:"id"`
	Link  string  `json:"link"`
}

// Result is the full outcome of a search run.
type Result struct {
	Keyword       string  `json:"keyword"`
	Baoyou        bool    `json:"baoyou"`
	Ship48        bool    `json:"ship48"`
	MinPrice      float64 `json:"min_price"`
	MinSales      int     `json:"min_sales"`
	Pages         int     `json:"pages"`
	FilterApplied bool    `json:"page_filter_confirmed"`
	TotalPages    int     `json:"total_pages_after_filter"`
	Scraped       int     `json:"scraped_deduped"`
	Kept          int     `json:"kept"`
	CSVPath       string  `json:"csv_path"`
	Items         []Item  `json:"items"`
}

const session = "taobao-cli"

// ---- JS payloads (stable text/class/aria selectors only — no coordinates) ----
//
// AX-snapshot @e refs exist only for interactive roles (全选=radio, 下一页=button,
// 筛选导出=link). The 包邮 / 48小时内发 / 复制 controls are styled div/span with no
// role, so they have no ref — we target them by exact text / stable class instead.
// See ARCHAEOLOGY.md.

const jsTotalPages = `(()=>{const e=[...document.querySelectorAll(".next-pagination-display,[class*=pagination]")].map(x=>(x.innerText||"").replace(/\s+/g,"")).find(t=>/^\d+\/\d+$/.test(t));const m=(e||"").match(/^(\d+)\/(\d+)$/);return JSON.stringify({total:m?+m[2]:null});})()`

const jsClickBaoyou = `(()=>{const c=[...document.querySelectorAll("div[class*=filterItem]")].filter(e=>(e.innerText||"").trim()==="包邮");if(!c.length)return "NF";c[0].click();return "ok";})()`

const jsOpenPanel = `(()=>{const b=[...document.querySelectorAll("div[class*=rightButton]")].find(e=>(e.innerText||"").includes("筛选"));if(b){b.click();return "ok";}return "NF";})()`

const jsClickFh48 = `(()=>{const c=[...document.querySelectorAll("div[class*=filterItem]")].filter(e=>(e.innerText||"").trim()==="48小时内发");if(!c.length)return "NF";c[c.length-1].click();return "ok";})()`

const jsClosePanel = `(()=>{const x=[...document.querySelectorAll("[class*=closeIcon]")].find(e=>e.getBoundingClientRect().width>0);if(x){x.click();return "ok";}return "none";})()`

const jsInstallHook = `(()=>{window.__cap=null;const oe=document.execCommand.bind(document);document.execCommand=function(c){if(String(c).toLowerCase()==="copy"){const el=document.activeElement;try{window.__cap=(el&&"value"in el&&el.value)?el.value:(window.getSelection().toString());}catch(e){}}return oe.apply(document,arguments);};try{if(navigator.clipboard&&navigator.clipboard.writeText){const ow=navigator.clipboard.writeText.bind(navigator.clipboard);navigator.clipboard.writeText=function(t){window.__cap=t;return ow(t);};}}catch(e){}return "h";})()`

const jsSelectAll = `(()=>{const e=[...document.querySelectorAll('[role=radio],span,label')].find(x=>/^全选/.test((x.innerText||"").trim()));if(!e)return "NF";const box=(e.closest("label")||e).querySelector("input")||e;box.click();return (e.innerText||"").trim();})()`

const jsClickCopy = `(()=>{const b=document.querySelector("span.zzb_search_copy_btn");if(!b)return "NF";b.click();return "ok";})()`

const jsReadCap = `(()=>{return window.__cap||"";})()`

const jsClickNext = `(()=>{const b=[...document.querySelectorAll("button")].find(x=>/下一页/.test(x.getAttribute("aria-label")||x.innerText||""));if(!b)return "NF";if(b.disabled)return "disabled";b.click();return "ok";})()`

// Per-card price/sales/包邮/48h, keyed by item id.
const jsCards = `(()=>{const as=[...document.querySelectorAll('a[href*="id="]')];const o={};for(const a of as){const m=a.href.match(/[?&]id=(\d+)/);if(!m)continue;const id=m[1];if(o[id])continue;let card=a,f=null;for(let i=0;i<9&&card;i++){const t=card.innerText||'';if(/人(付款|收货)/.test(t)&&/¥/.test(t)&&t.length>=30&&t.length<=600){f=card;break;}card=card.parentElement;}if(!f)continue;const txt=f.innerText;const pm=txt.match(/¥\s*\n?\s*(\d+)\s*\n?\s*(\.\d+)?/);const sm=txt.match(/([\d.]+)\s*(万)?\s*\+?\s*人(付款|收货)/);let s=null;if(sm){s=parseFloat(sm[1]);if(sm[2])s*=10000;s=Math.round(s);}o[id]={price:pm?parseFloat(pm[1]+(pm[2]||'')):null,sales:s,baoyou:/包邮/.test(txt),fh48:/48小时内发|48小时发/.test(txt)};}return JSON.stringify(o);})()`

type card struct {
	Price  *float64 `json:"price"`
	Sales  *int     `json:"sales"`
	Baoyou bool     `json:"baoyou"`
	Fh48   bool     `json:"fh48"`
}

func sleep(ms int) { time.Sleep(time.Duration(ms) * time.Millisecond) }

func scrollLoad(c *browser.Client, ys []int) {
	for _, y := range ys {
		c.Evaluate(fmt.Sprintf("window.scrollTo(0,%d);'ok'", y))
		sleep(500)
	}
}

func totalPages(c *browser.Client) int {
	var r struct {
		Total *int `json:"total"`
	}
	if err := c.EvaluateJSON(jsTotalPages, &r); err != nil || r.Total == nil {
		return -1
	}
	return *r.Total
}

// applyFilters applies the requested 包邮 / 48小时内发 page filters. When 48h is
// requested, success is confirmed by the total page count dropping below 100 (the
// unfiltered cap) and retried by reloading — reload is a clean reset that avoids
// re-clicking an already-on chip back off. 包邮 alone has no reliable page-count
// signal (most items are 包邮), so it's applied best-effort. Per-row card flags
// (see Run) enforce correctness regardless of whether the page filter took.
func applyFilters(c *browser.Client, searchURL string, baoyou, ship48 bool) (bool, int) {
	if !baoyou && !ship48 {
		c.Navigate(searchURL, true)
		sleep(4000)
		scrollLoad(c, []int{1000, 2000, 0})
		return false, totalPages(c)
	}
	for attempt := 1; attempt <= 3; attempt++ {
		c.Navigate(searchURL, attempt == 1)
		sleep(4000)
		scrollLoad(c, []int{1000, 2000, 0})
		if baoyou {
			c.EvaluateString(jsClickBaoyou)
			sleep(2800)
		}
		if ship48 {
			c.EvaluateString(jsOpenPanel)
			sleep(1600)
			c.EvaluateString(jsClickFh48)
			sleep(2600)
			c.EvaluateString(jsClosePanel)
			sleep(1800)
		}
		t := totalPages(c)
		if ship48 {
			if t > 0 && t < 100 { // 48h is restrictive enough to verify
				return true, t
			}
			continue // retry by reload
		}
		return true, t // 包邮-only: best-effort, accept first pass
	}
	return false, totalPages(c)
}

var idRe = regexp.MustCompile(`id=(\d+)`)

// Run executes the full flow: search, apply 包邮+48h, then for each page select
// all, capture the plugin's copy output, filter by price/sales, dedupe, and write CSV.
func Run(c *browser.Client, keyword string, baoyou, ship48 bool, minPrice float64, minSales, pages int, csvDir string) (*Result, error) {
	searchURL := "https://s.taobao.com/search?q=" + url.QueryEscape(keyword) + "&search_type=item&tab=all"

	applied, total := applyFilters(c, searchURL, baoyou, ship48)

	seen := map[string]bool{}
	var items []Item
	scraped := 0

	for p := 1; p <= pages; p++ {
		scrollLoad(c, []int{1000, 2200, 3400, 4600, 5800, 3000, 0})
		c.EvaluateString(jsInstallHook)
		c.EvaluateString(jsSelectAll)
		sleep(1000)
		c.EvaluateString(jsClickCopy)
		sleep(1400)

		cap, err := c.EvaluateString(jsReadCap)
		if err != nil {
			return nil, fmt.Errorf("read clipboard capture on page %d: %w", p, err)
		}
		cards := map[string]card{}
		if err := c.EvaluateJSON(jsCards, &cards); err != nil {
			return nil, fmt.Errorf("scrape cards on page %d: %w", p, err)
		}

		for _, line := range strings.Split(cap, "\n") {
			line = strings.TrimSpace(line)
			if line == "" {
				continue
			}
			cols := strings.Split(line, "\t")
			title := strings.TrimSpace(cols[0])
			link := strings.TrimSpace(cols[len(cols)-1])
			m := idRe.FindStringSubmatch(link)
			if m == nil {
				continue
			}
			id := m[1]
			cd, ok := cards[id]
			if !ok || cd.Price == nil || cd.Sales == nil {
				continue
			}
			if *cd.Price < minPrice || *cd.Sales < minSales {
				continue
			}
			// Per-row safety net: enforce 包邮/48h from the card's own badges,
			// so correctness holds even if the page-level filter didn't take.
			if baoyou && !cd.Baoyou {
				continue
			}
			if ship48 && !cd.Fh48 {
				continue
			}
			scraped++
			if seen[id] {
				continue
			}
			seen[id] = true
			items = append(items, Item{Page: p, Title: title, Price: *cd.Price, Sales: *cd.Sales, ID: id, Link: link})
		}

		if p < pages {
			r, _ := c.EvaluateString(jsClickNext)
			if r != "ok" {
				break // no more pages
			}
			sleep(3200)
		}
	}

	csvPath, err := writeCSV(csvDir, keyword, baoyou, ship48, minPrice, minSales, pages, items)
	if err != nil {
		return nil, err
	}

	return &Result{
		Keyword:       keyword,
		Baoyou:        baoyou,
		Ship48:        ship48,
		MinPrice:      minPrice,
		MinSales:      minSales,
		Pages:         pages,
		FilterApplied: applied,
		TotalPages:    total,
		Scraped:       len(seen),
		Kept:          len(items),
		CSVPath:       csvPath,
		Items:         items,
	}, nil
}

func writeCSV(dir, keyword string, baoyou, ship48 bool, minPrice float64, minSales, pages int, items []Item) (string, error) {
	if dir == "" {
		home, _ := os.UserHomeDir()
		dir = home
	}
	tag := ""
	if baoyou {
		tag += "包邮"
	}
	if ship48 {
		tag += "48h"
	}
	if tag == "" {
		tag = "全部"
	}
	name := fmt.Sprintf("%s_%s_价格%s_销量%d_%d页.csv",
		keyword, tag, strconv.FormatFloat(minPrice, 'g', -1, 64), minSales, pages)
	path := filepath.Join(dir, name)

	f, err := os.Create(path)
	if err != nil {
		return "", fmt.Errorf("create csv: %w", err)
	}
	defer f.Close()
	f.WriteString("\xEF\xBB\xBF") // UTF-8 BOM so Excel/WPS open it without garbling

	w := csv.NewWriter(f)
	defer w.Flush()
	w.Write([]string{"页码", "标题(插件复制原文)", "价格", "销量", "宝贝ID", "链接"})
	for _, it := range items {
		w.Write([]string{
			strconv.Itoa(it.Page),
			it.Title,
			strconv.FormatFloat(it.Price, 'g', -1, 64),
			strconv.Itoa(it.Sales),
			"\t" + it.ID, // leading tab keeps Excel from sci-notating the long id
			it.Link,
		})
	}
	return path, nil
}
