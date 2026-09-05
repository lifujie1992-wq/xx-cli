package woda

import (
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
	"time"

	"woda-aftersale-cli/browser"
)

const TargetURL = "https://douyins.woda.com/#/AfterSaleTrades"

type RefundOnlyOrder struct {
	Index             string   `json:"index"`
	RemainTime        string   `json:"remain_time"`
	Shop              string   `json:"shop"`
	AftersaleID       string   `json:"aftersale_id"`
	OrderID           string   `json:"order_id"`
	ItemCount         string   `json:"item_count"`
	Product           string   `json:"product"`
	Sku               string   `json:"sku"`
	Amount            string   `json:"amount"`
	AftersaleType     string   `json:"aftersale_type"`
	AftersaleStatus   string   `json:"aftersale_status"`
	Reason            string   `json:"reason"`
	ReasonDetail      string   `json:"reason_detail"`
	ReturnLogistics   string   `json:"return_logistics"`
	ShippingLogistics string   `json:"shipping_logistics"`
	AvailableActions  []string `json:"available_actions"`
	ApplyTime         string   `json:"apply_time"`
	Raw               string   `json:"raw"`
}

type ListResult struct {
	PageTitle          string            `json:"page_title"`
	URL                string            `json:"url"`
	ExpectedTabCount   int               `json:"expected_tab_count"`
	VisibleRefundCount int               `json:"visible_refund_count"`
	Orders             []RefundOnlyOrder `json:"orders"`
	Note               string            `json:"note,omitempty"`
}

func ListRefundOnly(client *browser.Client, limit int, noNavigate bool) (*ListResult, error) {
	if limit <= 0 {
		limit = 50
	}
	if !noNavigate {
		if err := client.Navigate(TargetURL); err != nil {
			return nil, err
		}
		if err := waitForSPAReady(client); err != nil {
			return nil, err
		}
		if err := clickRefundOnlyTab(client); err != nil {
			return nil, err
		}
	}
	js := fmt.Sprintf(`JSON.stringify((()=>{
  const text = el => (el && (el.innerText || el.textContent || '') || '').trim().replace(/\s+/g, ' ');
  const digits = s => (String(s||'').match(/\d+/g)||[]).join('');
  const getCopy = (cell, title) => {
    const el = [...cell.querySelectorAll('[title]')].find(x => (x.getAttribute('title') || '') === title);
    return digits(text(el));
  };
  const parseLogistics = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const parseRow = row => {
    const cells = [...row.querySelectorAll('.td')];
    const idCell = cells[3];
    const status = (text(cells[8]) || '').split(' ');
    const reason = (text(cells[9]) || '').split(' ');
    const expandSection = row.querySelector('.vtrade-expand');
    const shortTitle = expandSection ? expandSection.querySelector('.shortTitle') : null;
    const titleText = shortTitle ? (shortTitle.innerText || shortTitle.textContent || '') : '';
    const titleParts = titleText.split('\n').map(x => x.trim()).filter(Boolean);
    let product = titleParts[0] || '';
    let sku = titleParts.slice(1).join(' / ');
    if (!product) {
      const cell5Text = cells[5] ? (cells[5].innerText || cells[5].textContent || '') : '';
      const fb = cell5Text.split('\n').map(x => x.trim()).filter(Boolean);
      product = fb[0] || '';
      sku = fb.slice(1).join(' / ');
    }
    const actions = [...row.querySelectorAll('span.text-btn, button')].map(el => text(el)).filter(Boolean)
      .filter(x => !x.startsWith('复制') && !/^\d+$/.test(x));
    const raw = text(row);
    const timeMatch = raw.match(/20\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}/);
    return {
      index: text(cells[1]),
      remain_time: text(cells[2]),
      shop: (idCell && idCell.childNodes[1] && idCell.childNodes[1].nodeValue || '').trim() || (text(idCell).split(' ')[0] || ''),
      aftersale_id: getCopy(idCell, '售后单号') || ((text(idCell).match(/\b\d{15,}\b/)||[])[0] || ''),
      order_id: getCopy(idCell, '订单号') || ((text(idCell).match(/\b\d{15,}\b/g)||[])[1] || ''),
      item_count: text(cells[4]),
      product,
      sku,
      amount: text(cells[6]).replace(/^售后退款：\s*/, ''),
      aftersale_type: status[0] || '',
      aftersale_status: status.slice(1).join(' '),
      reason: reason[0] || '',
      reason_detail: reason.slice(1).join(' '),
      return_logistics: parseLogistics(text(cells[10])),
      shipping_logistics: parseLogistics(text(cells[11])),
      available_actions: [...new Set(actions)],
      apply_time: timeMatch ? timeMatch[0] : '',
      raw
    };
  };
  let expected = 0;
  const refundTab = [...document.querySelectorAll('.after-sale-query-modal .item, .after-sale-query-modal div')]
    .map(el => text(el)).find(t => /^仅退款\s*\(\d+\)/.test(t));
  if (refundTab) expected = Number((refundTab.match(/\((\d+)\)/)||[])[1] || 0);
  const rows = [...document.querySelectorAll('.vtrade-row.rowMain')]
    .filter(row => [...row.querySelectorAll('.td')].some(td => text(td).startsWith('仅退款')))
    .slice(0, %d)
    .map(parseRow);
  return {
    page_title: document.title,
    url: location.href,
    expected_tab_count: expected,
    visible_refund_count: rows.length,
    orders: rows,
    note: expected > rows.length ? '页面可能有虚拟滚动或分页；当前只返回已渲染在 DOM 中的仅退款订单。' : ''
  };
})())`, limit)

	raw, err := client.Evaluate(js)
	if err != nil {
		return nil, err
	}
	var jsonString string
	if err := json.Unmarshal(raw, &jsonString); err != nil {
		return nil, fmt.Errorf("decode evaluate string: %w; raw=%s", err, string(raw))
	}
	var result ListResult
	if err := json.Unmarshal([]byte(jsonString), &result); err != nil {
		return nil, fmt.Errorf("decode order list: %w", err)
	}
	if !strings.Contains(result.URL, "AfterSaleTrades") {
		return nil, fmt.Errorf("unexpected page url %q; expected %s", result.URL, TargetURL)
	}
	return &result, nil
}

func waitForSPAReady(client *browser.Client) error {
	for i := 0; i < 30; i++ {
		raw, err := client.Evaluate(`(function(){
			var tabs = document.querySelectorAll('.after-sale-query-modal .item');
			var rows = document.querySelectorAll('.vtrade-row.rowMain');
			return JSON.stringify({tabs: tabs.length, rows: rows.length});
		})()`)
		if err != nil {
			return fmt.Errorf("wait for SPA: %w", err)
		}
		var check struct {
			Tabs int `json:"tabs"`
			Rows int `json:"rows"`
		}
		var s string
		if err := json.Unmarshal(raw, &s); err != nil {
			return fmt.Errorf("wait for SPA decode: %w; raw=%s", err, string(raw))
		}
		if err := json.Unmarshal([]byte(s), &check); err != nil {
			return fmt.Errorf("wait for SPA parse: %w", err)
		}
		if check.Tabs > 0 || check.Rows > 0 {
			return nil
		}
		time.Sleep(500 * time.Millisecond)
	}
	return fmt.Errorf("page did not render expected elements within 15s")
}

func clickRefundOnlyTab(client *browser.Client) error {
	_, err := client.Evaluate(`(function(){
		var items = document.querySelectorAll('.after-sale-query-modal .item');
		for (var i = 0; i < items.length; i++) {
			if (/^仅退款/.test(items[i].innerText || '')) {
				items[i].click();
				return 'clicked';
			}
		}
		return 'not found';
	})()`)
	if err != nil {
		return fmt.Errorf("click refund-only tab: %w", err)
	}
	time.Sleep(800 * time.Millisecond)
	return nil
}

func ParseLimit(s string) (int, error) {
	if strings.TrimSpace(s) == "" {
		return 50, nil
	}
	v, err := strconv.Atoi(s)
	if err != nil || v <= 0 {
		return 0, fmt.Errorf("limit must be a positive integer")
	}
	return v, nil
}
