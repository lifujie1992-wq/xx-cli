package aldspdd

import (
	"fmt"

	"aldspdd-cli/browser"
)

// GoodsURL 是商品设置页，find_tab / navigate 用它定位标签页。
const GoodsURL = "https://aldspdd.agiso.com/#/alds/goods"

// jsPrelude 定义页面侧通用 fetch 助手：
//   - 从 localStorage 取 TOKEN，拼 Authorization: Bearer 头
//   - get / post 两个助手，credentials:include 复用 cookie
//
// 注意：OpenBridge 的 evaluate 共享同一全局作用域，顶层 const 会跨调用冲突，
// 因此 prelude 必须放进 IIFE 内（函数作用域）。用 wrapJS 统一包装。
const jsPrelude = `
const __tok=localStorage.getItem("TOKEN");
const __H={Accept:"application/json",Authorization:"Bearer "+__tok};
const __get=async u=>{const r=await fetch(u,{credentials:"include",headers:__H});return r.json();};
const __post=async(u,b)=>{const r=await fetch(u,{credentials:"include",method:"POST",headers:{...__H,"Content-Type":"application/json"},body:JSON.stringify(b)});return r.json();};
`

// wrapJS 把「返回 JSON.stringify(...) 的函数体」包成一个自执行 async 函数，
// prelude 与所有变量都在函数作用域内，避免跨 evaluate 的全局重复声明。
func wrapJS(body string) string {
	return "(async()=>{" + jsPrelude + body + "})()"
}

// Goods 是商品列表里的一项。
type Goods struct {
	GoodsID   string `json:"goodsId"`
	GoodsName string `json:"goodsName"`
	HasSku    bool   `json:"hasSku"`
	Price     string `json:"price"`
}

// 商品列表范围。页面三个标签页对应不同接口：
//
//	onsale     出售中     → LoadAldsGoodsListByApi?isOnsale=true
//	offsale    已下架     → LoadAldsGoodsListByApi?isOnsale=false
//	configured 已设置发货 → LoadAldsGoodsList（含已下架的历史配置，会更多）
const (
	ScopeOnsale     = "onsale"
	ScopeOffsale    = "offsale"
	ScopeConfigured = "configured"
)

func goodsListURL(scope string) string {
	switch scope {
	case ScopeConfigured:
		return "/api/UnAldsInfo/LoadAldsGoodsList?pageSize=50&page="
	case ScopeOffsale:
		return "/api/UnAldsInfo/LoadAldsGoodsListByApi?isOnsale=false&pageSize=50&page="
	default: // ScopeOnsale
		return "/api/UnAldsInfo/LoadAldsGoodsListByApi?isOnsale=true&pageSize=50&page="
	}
}

// LoadGoods 按 scope 拉取商品列表（分页直到取完）。默认 onsale = 出售中。
func LoadGoods(c *browser.Client, scope string) ([]Goods, error) {
	code := wrapJS(fmt.Sprintf(`
  const base=%q;
  let all=[],page=1,pages=1;
  do{
    const j=await __get(base+page);
    const d=j.data.data; pages=d.totalPages;
    all=all.concat(d.items.map(x=>({goodsId:x.goodsId,goodsName:x.goodsName,hasSku:x.hasSku,price:x.price})));
    page++;
  }while(page<=pages);
  return JSON.stringify(all);
`, goodsListURL(scope)))
	var out []Goods
	if err := c.EvalJSON(code, &out); err != nil {
		return nil, fmt.Errorf("加载商品列表失败: %w", err)
	}
	return out, nil
}

// Entry 是一个商品（或其某个 SKU）绑定的货源信息及校验结果。
type Entry struct {
	Sku       string `json:"sku"`    // SKU 规格名；整体设置时为 "(整体)"
	SkuID     string `json:"skuId"`  // SKU id（整体时为空）
	AccountID int    `json:"acc"`    // 货源账号 id（搜索的 idNo）
	ProductNo string `json:"no"`     // 货源编号（搜索的 keyword）
	SpType    int    `json:"spType"` // 6 = 自有货源
	Status    string `json:"status"` // ok / dead_empty / dead_mismatch / skip / error
	Found     int    `json:"found"`  // 搜索返回条数
	Note      string `json:"note"`   // 错误或备注
}

// Dead 报告：某商品下失效的货源条目。
type Dead struct {
	GoodsID   string  `json:"goodsId"`
	GoodsName string  `json:"goodsName"`
	Price     string  `json:"price"`
	Entries   []Entry `json:"deadEntries"`
}

// ScanProduct 在浏览器内一次性扫描单个商品：
// 取它每个 SKU（或整体）的货源编号，逐个调用搜索接口判断货源是否还在。
// 返回该商品全部条目（含 ok / dead / skip / error 状态）。
func ScanProduct(c *browser.Client, goodsID string, hasSku bool) ([]Entry, error) {
	code := wrapJS(fmt.Sprintf(`
  const goodsId=%q, hasSku=%v;
  const entries=[];
  try{
    if(hasSku){
      const sl=await __get("/api/AldsInfo/GetAldsSkuList/"+goodsId);
      for(const s of (sl.data.data||[])){
        try{
          const d=(await __get("/api/AldsInfo/GetSkuAldsInfo/"+goodsId+"/"+s.skuId)).data.data;
          entries.push({sku:s.specName||"",skuId:s.skuId,acc:d.supplierAccountId||0,no:d.supplierProductNo||"",spType:d.spType||0,status:"",found:0,note:""});
        }catch(e){entries.push({sku:s.specName||"",skuId:s.skuId,acc:0,no:"",spType:0,status:"error",found:0,note:String(e)});}
      }
    }else{
      const d=(await __get("/api/AldsInfo/GetGoodsAldsInfo/"+goodsId)).data.data;
      entries.push({sku:"(整体)",skuId:"",acc:d.supplierAccountId||0,no:d.supplierProductNo||"",spType:d.spType||0,status:"",found:0,note:""});
    }
  }catch(e){return JSON.stringify([{sku:"",skuId:"",acc:0,no:"",spType:0,status:"error",found:0,note:"load detail: "+String(e)}]);}

  for(const e of entries){
    if(e.status==="error") continue;
    if(e.spType!==6 || !e.no){ e.status="skip"; continue; }
    try{
      const sr=await __post("/api/AcprSerivces/GetSupplierProductList",{idNo:e.acc,keyword:e.no,pageIndex:1,pageSize:20});
      const arr=(sr.data&&sr.data.data&&sr.data.data.items)||[];
      e.found=arr.length;
      if(arr.some(x=>String(x.productNo)===String(e.no))) e.status="ok";
      else if(arr.length===0) e.status="dead_empty";
      else e.status="dead_mismatch";
    }catch(err){ e.status="error"; e.note=String(err); }
  }
  return JSON.stringify(entries);
`, goodsID, hasSku))

	var out []Entry
	if err := c.EvalJSON(code, &out); err != nil {
		return nil, fmt.Errorf("扫描商品 %s 失败: %w", goodsID, err)
	}
	return out, nil
}
