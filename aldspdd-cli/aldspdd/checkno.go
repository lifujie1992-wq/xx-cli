package aldspdd

import (
	"fmt"

	"aldspdd-cli/browser"
)

// SupplierAccount 是一个货源账号（搜索时的 idNo）。
type SupplierAccount struct {
	Val  int    `json:"val"`
	Text string `json:"text"`
}

// LoadAccounts 取全部货源账号。
func LoadAccounts(c *browser.Client) ([]SupplierAccount, error) {
	code := wrapJS(`
  const j=await __post("/api/AcprSerivces/GetSupplierAccounts",{});
  return JSON.stringify(j.data.data||[]);
`)
	var out []SupplierAccount
	if err := c.EvalJSON(code, &out); err != nil {
		return nil, fmt.Errorf("加载货源账号失败: %w", err)
	}
	return out, nil
}

// SearchHit 是某货源编号在某账号下的搜索结果。
type SearchHit struct {
	AccountID    int          `json:"accountId"`
	AccountName  string       `json:"accountName"`
	Found        int          `json:"found"`        // 搜索返回条数
	ExactMatch   bool         `json:"exactMatch"`   // 是否含 productNo===keyword
	Items        []SearchItem `json:"items"`        // 原始返回条目
}

type SearchItem struct {
	ProductNo    string  `json:"productNo"`
	ProductTitle string  `json:"productTitle"`
	ProductType  int     `json:"productType"`
	ProductCost  float64 `json:"productCost"`
}

// CheckNoResult 是 check-no 命令的结果。
type CheckNoResult struct {
	No       string      `json:"no"`              // 查询的货源编号
	Alive    bool        `json:"alive"`           // 任一账号下精确命中即为在
	Hits     []SearchHit `json:"hits"`            // 各账号的搜索结果
	UsedBy   []Usage     `json:"usedBy,omitempty"` // --locate：你方哪些商品/SKU 在用它
	MapBuilt string      `json:"mapBuiltAt,omitempty"` // 反查映射的构建时间
}

// SearchSupplierNo 在指定账号下搜索一个货源编号。
func SearchSupplierNo(c *browser.Client, accountID int, no string) (*SearchHit, error) {
	code := wrapJS(fmt.Sprintf(`
  const acc=%d, no=%q;
  const sr=await __post("/api/AcprSerivces/GetSupplierProductList",{idNo:acc,keyword:no,pageIndex:1,pageSize:20});
  const arr=(sr.data&&sr.data.data&&sr.data.data.items)||[];
  return JSON.stringify({accountId:acc, found:arr.length, exactMatch:arr.some(x=>String(x.productNo)===String(no)), items:arr});
`, accountID, no))
	var hit SearchHit
	if err := c.EvalJSON(code, &hit); err != nil {
		return nil, fmt.Errorf("搜索编号 %s 失败: %w", no, err)
	}
	return &hit, nil
}

// Locate 给结果附上「你方哪些商品/SKU 在用该编号」。
// 优先用缓存映射；缓存缺失时按 scope 现建一份。
func (r *CheckNoResult) Locate(c *browser.Client, scope string, refresh bool) error {
	var um *UsageMap
	if !refresh {
		cached, err := LoadUsageMap()
		if err != nil {
			return err
		}
		um = cached
	}
	if um == nil {
		built, err := BuildUsageMap(c, scope)
		if err != nil {
			return err
		}
		um = built
	}
	r.MapBuilt = um.BuiltAt
	r.UsedBy = um.Map[r.No]
	return nil
}

// CheckNo 查单个货源编号是否还在。accountID>0 时只查该账号；否则遍历全部货源账号。
func CheckNo(c *browser.Client, no string, accountID int) (*CheckNoResult, error) {
	if err := c.FindTab("aldspdd.agiso.com", true); err != nil {
		if err := c.Navigate(GoodsURL); err != nil {
			return nil, fmt.Errorf("无法定位 Agiso 标签页: %w", err)
		}
	}

	var accounts []SupplierAccount
	if accountID > 0 {
		accounts = []SupplierAccount{{Val: accountID, Text: ""}}
	} else {
		all, err := LoadAccounts(c)
		if err != nil {
			return nil, err
		}
		accounts = all
	}

	res := &CheckNoResult{No: no}
	for _, acc := range accounts {
		hit, err := SearchSupplierNo(c, acc.Val, no)
		if err != nil {
			return nil, err
		}
		hit.AccountName = acc.Text
		res.Hits = append(res.Hits, *hit)
		if hit.ExactMatch {
			res.Alive = true
		}
	}
	return res, nil
}
