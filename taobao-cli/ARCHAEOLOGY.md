# Site Archaeology — 淘宝搜索 + zzb 插件

针对 `s.taobao.com/search`（已登录态）+ zzb 插件注入工具栏的元素定位记录。2026-06。

## 核心教训：AX snapshot 只给可交互角色 @e 引用

kimi-webbridge 的 `snapshot` 只对**语义可交互角色**分配稳定 `@e` 引用：

| 元素 | snapshot 里的形态 | 有 @e ref？ |
|---|---|---|
| 全选 | `radio "全选(0/50)"` | ✅ `@e19` 这类 |
| 下一页 / 上一页 | `button "下一页，当前第N页"` | ✅ |
| 筛选导出 | `link "筛选导出(N)"` | ✅ |
| **包邮 / 48小时内发** chip | `StaticText "包邮"`（淘宝用 div 做样式块） | ❌ 无 ref |
| **复制** 按钮 | `StaticText "复制"`（zzb 用 span 做） | ❌ 无 ref |

→ 对无 ref 的 div/span，**不要用坐标**（淘宝每次渲染高度会变，`包邮` chip 在 y264 / y348 之间漂），而要用**稳定身份**：精确文本 + class。

## Feature: `search`（包邮+48h + 价格/销量过滤 + 翻页）

**URL:** `GET https://s.taobao.com/search?q=<urlencode(关键字)>&search_type=item&tab=all`

**Auth:** 复用浏览器登录 cookie，无需额外登录。

**Delivery:** SSR + 懒加载。需滚动触发卡片图片/详情加载，再读 DOM。

### 元素定位（稳定选择器，无坐标）

| 动作 | 选择器 / JS |
|---|---|
| 点 `包邮` | `div[class*=filterItem]` 且 `innerText.trim()==="包邮"`（面板关闭时唯一；商品卡的「包邮」是 StaticText，不带 filterItem class，不会误选） |
| 打开全部筛选面板 | `div[class*=rightButton]` 且文本含「筛选」 |
| 点 `48小时内发` | 面板内 `div[class*=filterItem]` 文本==`48小时内发`（取最后一个，排除排序栏快捷区残留） |
| 关闭面板 | 可见的 `[class*=closeIcon]` |
| 全选 | `[role=radio]` / 文本以「全选」开头的 span/label，点其内部 `input` |
| 复制（插件） | `span.zzb_search_copy_btn` |
| 下一页 | `button`，`aria-label` 或文本含「下一页」 |
| 总页数 | `.next-pagination-display` 文本 `N/M`，取 M |

### 两个坑

1. **筛选生效校验**：`包邮` 单独可能不让总页数掉到 100 以下（包邮商品太多），且快捷 chip 不计入「筛选」角标。可靠信号是 **包邮 + 48h 两者都应用后总页数 < 100**（如 `有机核桃仁` → 24）。校验失败就**整页重载重试**——重载是干净复位，避免「已选 chip 被再次点击 toggle 关掉」。

2. **价格/销量来源**：插件「复制」（顶层 `span.zzb_search_copy_btn`）只复制 `标题 [tab] [tab] 链接` 三列，**不含价格/销量**。带价格/销量的全字段导出在 zzb「筛选导出」弹层里，而那是 `tool.zzbtool.com` 的**跨域 iframe**（`contentDocument` 被同源策略挡死，无法点入/读取）。所以价格/销量改从商品卡原生文本读：价格 `¥X.YY`、销量 `N人付款 / N万+人付款`（`万`×10000）。按宝贝ID与插件复制行匹配，仅用于过滤。

### 抓插件复制原文的手法

点「复制」前先 hook 剪贴板写入，即可拿到插件复制的**原文**（它自己的标题/链接），无需读系统剪贴板：

```js
window.__cap=null;
const oe=document.execCommand.bind(document);
document.execCommand=function(c){
  if(String(c).toLowerCase()==="copy"){
    const el=document.activeElement;
    window.__cap=(el&&"value"in el&&el.value)?el.value:window.getSelection().toString();
  }
  return oe.apply(document,arguments);
};
if(navigator.clipboard?.writeText){
  const ow=navigator.clipboard.writeText.bind(navigator.clipboard);
  navigator.clipboard.writeText=function(t){window.__cap=t;return ow(t);};
}
// 点「复制」后读 window.__cap
```

### 卡片提取 evaluate（价格/销量/包邮/48h，按 id）

```js
const as=[...document.querySelectorAll('a[href*="id="]')];
const o={};
for(const a of as){
  const m=a.href.match(/[?&]id=(\d+)/); if(!m) continue;
  const id=m[1]; if(o[id]) continue;
  let card=a,f=null;
  for(let i=0;i<9&&card;i++){
    const t=card.innerText||'';
    if(/人(付款|收货)/.test(t)&&/¥/.test(t)&&t.length>=30&&t.length<=600){f=card;break;}
    card=card.parentElement;
  }
  if(!f) continue;
  const txt=f.innerText;
  const pm=txt.match(/¥\s*\n?\s*(\d+)\s*\n?\s*(\.\d+)?/);
  const sm=txt.match(/([\d.]+)\s*(万)?\s*\+?\s*人(付款|收货)/);
  let s=null; if(sm){s=parseFloat(sm[1]); if(sm[2])s*=10000; s=Math.round(s);}
  o[id]={price:pm?parseFloat(pm[1]+(pm[2]||'')):null, sales:s,
         baoyou:/包邮/.test(txt), fh48:/48小时内发|48小时发/.test(txt)};
}
return JSON.stringify(o);
```
