package aldspdd

import (
	"fmt"
	"os"

	"aldspdd-cli/browser"
)

// CheckSupplyResult 是 check-supply 命令的完整结果。
type CheckSupplyResult struct {
	Scope         string `json:"scope"`         // 扫描范围：onsale/offsale/configured
	TotalGoods    int    `json:"totalGoods"`    // 该范围商品数
	ScannedGoods  int    `json:"scannedGoods"`  // 实际扫描成功的商品数
	CheckedNo     int    `json:"checkedNo"`     // 校验过的货源编号数（spType=6）
	DeadCount     int    `json:"deadCount"`     // 失效货源编号数
	DeadGoods     int    `json:"deadGoods"`     // 含失效货源的商品数
	OkCount       int      `json:"okCount"`     // 货源正常的编号数
	Dead          []Dead   `json:"dead"`        // 失效明细（按商品聚合）
	All           []Dead   `json:"all,omitempty"` // --all 时：每个商品的全部条目（含 ok/dead/skip）
	ScanErrors    []string `json:"scanErrors"`  // 扫描中出错的商品（不影响其余）
}

// CheckSupply 扫描指定范围的商品，找出绑定的货源编号已经搜不到（货源下架/删除）的商品。
// scope 见 Scope* 常量，默认 onsale=出售中。limit > 0 时只扫前 limit 个商品。
func CheckSupply(c *browser.Client, scope string, limit int, includeAll bool) (*CheckSupplyResult, error) {
	// 接管当前标签页
	if err := c.FindTab("aldspdd.agiso.com", true); err != nil {
		if err := c.Navigate(GoodsURL); err != nil {
			return nil, fmt.Errorf("无法定位 Agiso 标签页: %w", err)
		}
	}

	goods, err := LoadGoods(c, scope)
	if err != nil {
		return nil, err
	}
	if limit > 0 && limit < len(goods) {
		goods = goods[:limit]
	}

	res := &CheckSupplyResult{Scope: scope, TotalGoods: len(goods)}
	for i, g := range goods {
		fmt.Fprintf(os.Stderr, "[%d/%d] 扫描 %s %s ...\n", i+1, len(goods), g.GoodsID, truncate(g.GoodsName, 20))
		entries, err := ScanProduct(c, g.GoodsID, g.HasSku)
		if err != nil {
			res.ScanErrors = append(res.ScanErrors, fmt.Sprintf("%s: %v", g.GoodsID, err))
			continue
		}
		res.ScannedGoods++
		var dead []Entry
		for _, e := range entries {
			if e.SpType == 6 && e.ProductNo != "" && e.Status != "skip" {
				res.CheckedNo++
			}
			switch e.Status {
			case "ok":
				res.OkCount++
			case "dead_empty", "dead_mismatch":
				dead = append(dead, e)
			}
		}
		if includeAll {
			res.All = append(res.All, Dead{
				GoodsID:   g.GoodsID,
				GoodsName: g.GoodsName,
				Price:     g.Price,
				Entries:   entries,
			})
		}
		if len(dead) > 0 {
			res.DeadCount += len(dead)
			res.DeadGoods++
			res.Dead = append(res.Dead, Dead{
				GoodsID:   g.GoodsID,
				GoodsName: g.GoodsName,
				Price:     g.Price,
				Entries:   dead,
			})
		}
	}
	return res, nil
}

func truncate(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[:n]) + "…"
}
