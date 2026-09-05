package aldspdd

import (
	"fmt"

	"aldspdd-cli/browser"
)

type LoginStatus struct {
	LoggedIn   bool   `json:"logged_in"`
	GoodsCount int    `json:"goodsCount"`
	Note       string `json:"note"`
}

// CheckLogin 接管已打开的商品页，确认 TOKEN 有效、商品列表接口可访问。
func CheckLogin(c *browser.Client) (*LoginStatus, error) {
	// 优先接管用户当前正在看的标签页；找不到再退化为新开。
	if err := c.FindTab("aldspdd.agiso.com", true); err != nil {
		if err := c.Navigate(GoodsURL); err != nil {
			return nil, fmt.Errorf("无法定位 Agiso 标签页: %w", err)
		}
	}

	code := wrapJS(`
  if(!__tok) return JSON.stringify({logged_in:false,goodsCount:0,note:"localStorage 无 TOKEN，请在 Chrome 登录 aldspdd.agiso.com"});
  try{
    const j=await __get("/api/UnAldsInfo/LoadAldsGoodsList?pageSize=1&page=1");
    if(j.statusCode!==200) return JSON.stringify({logged_in:false,goodsCount:0,note:"接口返回 "+j.statusCode+"，登录态可能失效"});
    return JSON.stringify({logged_in:true,goodsCount:j.data.data.totalCount,note:""});
  }catch(e){return JSON.stringify({logged_in:false,goodsCount:0,note:String(e)});}
`)

	var st LoginStatus
	if err := c.EvalJSON(code, &st); err != nil {
		return nil, err
	}
	return &st, nil
}
