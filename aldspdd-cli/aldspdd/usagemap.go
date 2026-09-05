package aldspdd

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"aldspdd-cli/browser"
)

// Usage 是某货源编号被「你方」哪个商品/SKU 使用。
type Usage struct {
	GoodsID   string `json:"goodsId"`
	GoodsName string `json:"goodsName"`
	SkuID     string `json:"skuId"`
	Sku       string `json:"sku"`
	AccountID int    `json:"acc"`
}

// UsageMap：货源编号 -> 使用它的你方商品/SKU 列表。
type UsageMap struct {
	BuiltAt string             `json:"builtAt"`
	Scope   string             `json:"scope"`
	Goods   int                `json:"goods"`
	Map     map[string][]Usage `json:"map"`
}

func cachePath() (string, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(home, ".aldspdd-cli", "usage-map.json"), nil
}

// binding 是单商品的货源绑定（不含搜索，纯详情，构建映射用，比 ScanProduct 快）。
type binding struct {
	SkuID string `json:"skuId"`
	Sku   string `json:"sku"`
	No    string `json:"no"`
	Acc   int    `json:"acc"`
}

func productBindings(c *browser.Client, goodsID string, hasSku bool) ([]binding, error) {
	code := wrapJS(fmt.Sprintf(`
  const goodsId=%q, hasSku=%v;
  const entries=[];
  if(hasSku){
    const sl=await __get("/api/AldsInfo/GetAldsSkuList/"+goodsId);
    for(const s of (sl.data.data||[])){
      const d=(await __get("/api/AldsInfo/GetSkuAldsInfo/"+goodsId+"/"+s.skuId)).data.data;
      entries.push({skuId:s.skuId, sku:s.specName||"", no:d.supplierProductNo||"", acc:d.supplierAccountId||0});
    }
  }else{
    const d=(await __get("/api/AldsInfo/GetGoodsAldsInfo/"+goodsId)).data.data;
    entries.push({skuId:"", sku:"(整体)", no:d.supplierProductNo||"", acc:d.supplierAccountId||0});
  }
  return JSON.stringify(entries);
`, goodsID, hasSku))
	var out []binding
	if err := c.EvalJSON(code, &out); err != nil {
		return nil, fmt.Errorf("读取商品 %s 绑定失败: %w", goodsID, err)
	}
	return out, nil
}

// BuildUsageMap 扫描指定范围商品，构建「货源编号 -> 你方商品/SKU」映射并写入缓存。
func BuildUsageMap(c *browser.Client, scope string) (*UsageMap, error) {
	if err := c.FindTab("aldspdd.agiso.com", true); err != nil {
		if err := c.Navigate(GoodsURL); err != nil {
			return nil, fmt.Errorf("无法定位 Agiso 标签页: %w", err)
		}
	}
	goods, err := LoadGoods(c, scope)
	if err != nil {
		return nil, err
	}
	m := map[string][]Usage{}
	for i, g := range goods {
		fmt.Fprintf(os.Stderr, "[%d/%d] 建映射 %s %s ...\n", i+1, len(goods), g.GoodsID, truncate(g.GoodsName, 18))
		bs, err := productBindings(c, g.GoodsID, g.HasSku)
		if err != nil {
			return nil, err
		}
		for _, b := range bs {
			if b.No == "" {
				continue
			}
			m[b.No] = append(m[b.No], Usage{
				GoodsID:   g.GoodsID,
				GoodsName: g.GoodsName,
				SkuID:     b.SkuID,
				Sku:       b.Sku,
				AccountID: b.Acc,
			})
		}
	}
	um := &UsageMap{
		BuiltAt: time.Now().Format("2006-01-02 15:04:05"),
		Scope:   scope,
		Goods:   len(goods),
		Map:     m,
	}
	if err := saveUsageMap(um); err != nil {
		return nil, err
	}
	return um, nil
}

func saveUsageMap(um *UsageMap) error {
	p, err := cachePath()
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		return err
	}
	data, err := json.MarshalIndent(um, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(p, data, 0o644)
}

// LoadUsageMap 读缓存映射；不存在返回 (nil, nil)。
func LoadUsageMap() (*UsageMap, error) {
	p, err := cachePath()
	if err != nil {
		return nil, err
	}
	data, err := os.ReadFile(p)
	if os.IsNotExist(err) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var um UsageMap
	if err := json.Unmarshal(data, &um); err != nil {
		return nil, fmt.Errorf("缓存映射解析失败: %w", err)
	}
	return &um, nil
}
