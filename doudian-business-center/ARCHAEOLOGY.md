# Site Archaeology — 抖店商机中心

抖店后台 `fxg.jinritemai.com` 的「商机中心」页面定位记录。入口：

```text
https://fxg.jinritemai.com/ffa/bu/NewBusinessCenter
```

本次使用真实 Chrome 登录态 + x-cli/kimi-webbridge 考古，店铺为「示例店铺」。截图证据：

```text
/var/folders/b0/0lx5k3_d19b69ts3z3jz00yh0000gn/T/kimi-webbridge-screenshots/screenshot_20260704_010223.515.png
```

## 核心教训：浏览器上下文里不必手写风控参数

页面请求 URL 会自动带 `msToken` / `a_bogus` / `verifyFp` / `fp`，但在页面内直接：

```js
fetch('/api/commop/business_chance_center/...', {
  method: 'POST',
  credentials: 'include',
  headers: { 'content-type': 'application/json' },
  body: JSON.stringify(payload),
})
```

可以正常返回数据。也就是说 CLI 不要在本地硬拼 `a_bogus`；通过 kimi-webbridge 的 `evaluate` 在浏览器会话里发请求即可复用 cookie/风控环境。

另一个坑：Kimi WebBridge 的 network detail 只稳定拿到响应体，不一定暴露 POST body。要抓真实请求体，可在页面里临时 hook：

```js
window.__bcCaptured = [];
const origOpen = XMLHttpRequest.prototype.open;
const origSend = XMLHttpRequest.prototype.send;
XMLHttpRequest.prototype.open = function(method, url) {
  this.__bcMethod = method;
  this.__bcUrl = url;
  return origOpen.apply(this, arguments);
};
XMLHttpRequest.prototype.send = function(body) {
  if (String(this.__bcUrl || '').includes('business_chance_center')) {
    window.__bcCaptured.push({ method: this.__bcMethod, url: this.__bcUrl, body });
  }
  return origSend.apply(this, arguments);
};
```

## 页面结构

可访问性树确认页面中文名就是「商机中心」。主要区域：

- 顶部：抖店导航、全局搜索、消息/工具图标、店铺头像。
- 左侧：商品/店铺/用户/资金/应用菜单；「商品 > 商机中心」为当前入口。
- 概览卡：近30天报名记录 `6`、已获权益商品 `0`、我的收藏 `740`、未获权益商品 `5`、近30天曝光次数 `1,037`。
- 三个榜单卡：抖音热搜榜、机会类目榜、本店用户爱买榜。
- 主列表 tab：`追抖音热词` / `跟潜力爆品`。
- 主列表工具：全选、批量收藏、批量复制商机、晓风批量截流、多店全自动商机提报。
- 筛选：类目、推荐理由、权益、排序规则、仅展示有代发货源的商机、卡片/列表视图。
- 卡片动作：收藏、发相似品、找货源/暂无货源。
- 分页：`共1752/1753 个词`，页码 1..84，默认约 20/21 条每页。

## 稳定选择器

| 对象 | 选择器 / 定位方式 |
|---|---|
| 页面根 | `#root` |
| 商机列表容器 | `#clue-list-container`（业务代码里使用） |
| 顶部商机搜索框 | `.auxo-input-search input.auxo-input` |
| 顶部商机搜索按钮 | `.auxo-input-search-button` |
| 排序按钮 | `button` 文本：`为你推荐` / `成交高` / `增速快` / `竞争小` |
| 推荐理由按钮 | `button` 文本：`全网热卖` / `热度高` / `成交增速快` / `应季爆发` / `高扶持甄选品` / `中小商易爆单` |
| 类目筛选 input | `input[placeholder="请选择行业类目"]` |
| 有代发货源 checkbox | 文本含 `仅展示有代发货源的商机` 的 checkbox |
| 卡片/列表切换 | `button` 文本：`卡片` / `列表` |

Auxo 组件大量使用 hash class，优先用文本 + 角色/相邻结构定位，不要依赖具体 hash class。

## 关键接口

基础前缀：

```text
/api/commop/business_chance_center
```

### 顶部统计

```http
GET /api/commop/business_chance_center/clue/my/statistics
```

实测返回：

```jsonc
{
  "data": {
    "all_submit_recordLatest30_cnt": 6,
    "has_obtain_profit_product_cnt": 0,
    "all_auto_submit_record_latestCnt": 740,
    "offline_latest30_submit_approved_cnt": 5,
    "offline_latest30_submit_approved_gmv": 50.7,
    "offline_latest30_submit_approved_exposure_cnt": 1037
  },
  "code": 0
}
```

### 店铺信息

```http
POST /api/commop/business_chance_center/shop_info
Body: {}
```

关键字段：`shop_id`、`name`、`shop_glevel`、`main_category_cid_new`、`gmv30dtop_leaf_cid_path`、`shelftop_leaf_cid_path`、`categories`。

实测：

```jsonc
{
  "shop_id": 123456789,
  "name": "示例店铺",
  "shop_glevel": "G1",
  "main_category_cid_new": 1000000957
}
```

### 筛选项

```http
GET /api/commop/business_chance_center/shop_full_category/list?clue_type_new=11&source_channel_code=
POST /api/commop/business_chance_center/clue_label/query
POST /api/commop/business_chance_center/profit/list
POST /api/commop/business_chance_center/category/qualified/get
```

常用 body：

```js
{ clue_type_new: 11 }
```

返回形状：

- `shop_full_category/list`：类目级联树，节点 `{ value, label, children, main_category, industry_id }`。
- `clue_label/query`：推荐理由标签，实测 4 个：全网热卖、热度高、成交增速快、平台缺货等。
- `profit/list`：权益列表，实测 6 个，含 `profit_id`、`profit_name`、`profit_description`。
- `category/qualified/get`：可经营类目树，节点 `{ id, name, first_cid, second_cid, third_cid, fourth_cid, level, parent_id, is_leaf, enable }`。

## 商机列表：`追抖音热词`

```http
POST /api/commop/business_chance_center/clue/common/real_time_list
```

默认请求体（已验证，可省略 `_lid`）：

```json
{
  "condition": {
    "hit_clue_label_ext": true,
    "show_new_supply_link": true,
    "include_hot_sales_products": true,
    "sort": {
      "sort_direction": 1,
      "sort_field": "MATCH_DEGREE"
    }
  },
  "clue_type": "",
  "clue_type_new": 11,
  "page": {
    "current": 1,
    "page_size": 20
  },
  "terminal_type": 0,
  "source": "business_center"
}
```

验证结果：HTTP 200，`code:0`，`total:1753`，首项「半拖运动鞋」。

关键词搜索加在 `condition.clue_info`：

```jsonc
{
  "condition": {
    "clue_info": "男士老爹鞋",
    "hit_clue_label_ext": true,
    "show_new_supply_link": true,
    "include_hot_sales_products": true,
    "sort": { "sort_direction": 1, "sort_field": "MATCH_DEGREE" }
  },
  "clue_type": "",
  "clue_type_new": 11,
  "page": { "current": 1, "page_size": 5 },
  "terminal_type": 0,
  "source": "business_center"
}
```

验证结果：`total:500`，首项「男士真皮老爹鞋」。`query` / `keyword` / `search_word` 不生效。

### 列表响应结构

```jsonc
{
  "data": [
    {
      "clue_detail": {
        "clue_id": 30330107,
        "name": "半拖运动鞋",
        "first_cid": 1000000957,
        "first_name": "鞋靴",
        "second_cid": 1000000961,
        "second_name": "女鞋",
        "third_cid": 1000007623,
        "third_name": "拖鞋",
        "category_path": ["鞋靴", "女鞋", "拖鞋"],
        "product_pic_url": "...",
        "clue_label_list": [{ "label_id": 31, "label_name": "热度高" }],
        "profit_info_list": [{ "profit_id": 1, "profit_name": "搜索扶持" }]
      },
      "query_clue_card_info": {
        "search_popularity": 850,
        "demand_supply_rate": 0.32,
        "goods_supply_platform_list": [1]
      },
      "clue_indicator": {
        "search_pv_cnt_range": "小于50",
        "pay_amount_ind_range": "¥10万-¥25万",
        "pay_amount_ind_30d_rate": 121.0475
      },
      "hot_sale_products": [
        { "prod_id": "...", "prod_name": "...", "prod_saled": 924 }
      ],
      "clue_collect_info": { "collect_status": 2, "collect_tips": "" }
    }
  ],
  "total": 1753,
  "code": 0
}
```

### 排序枚举

`sort_direction`: `1 = DESC`，`0 = ASC`。

词线索（`clue_type_new=11`）排序：

| UI | sort_field | direction |
|---|---|---|
| 为你推荐 | `MATCH_DEGREE` | 1 |
| 成交高 | `TRADING_AMOUNT` | 1 |
| 增速快 | `PAY_AMOUNT_RATE` | 1 |
| 竞争小 | `DEMAND_SUPPLY_RATE` | 1 |

机会商品（`clue_type_new=9`）的「竞争小」使用：

```json
{ "sort_field": "ONLINE_PRODUCT_NUMS", "sort_direction": 0 }
```

### 筛选字段转换

业务 bundle 中的筛选转换函数：

- `category: [first, second, third, fourth]` -> `condition.categories: [{ first_cid | second_cid | third_cid | fourth_cid }]`
- `clue_info` -> 搜索词；如果内容是逗号分隔 ID，会转成 `clue_id_list`
- `tag_id_list` -> 推荐理由标签
- `profit_id_list` -> 权益
- `price_range: [min, max]` -> `price_lowest/min*100`、`price_highest/max*100`
- `only_show_goods_supply_exists: true` -> 仅展示有代发货源
- `recently_created: true` -> 最近上新

## 榜单卡片

首页先请求：

```http
POST /api/commop/business_chance_center/rank_card
Body: { "terminal_type": 0 }
```

实测返回 3 张卡片：

```jsonc
[
  {
    "rank_card_type": 0,
    "filter_param": {
      "category": {
        "first_cid": 1000000957,
        "second_cid": 1000000962,
        "third_cid": 1000007614,
        "fourth_cid": 0,
        "leaf_cid": 1000007614
      },
      "peer_shop_id": null,
      "industry_id": 16
    }
  },
  {
    "rank_card_type": 3,
    "filter_param": {
      "category": { "first_cid": 1000000957, "second_cid": null },
      "peer_shop_id": null,
      "industry_id": null
    }
  },
  {
    "rank_card_type": 1,
    "filter_param": {
      "category": { "first_cid": 1000000957, "second_cid": null },
      "peer_shop_id": null,
      "industry_id": 16
    }
  }
]
```

### 抖音热搜榜

```http
POST /api/commop/business_chance_center/clue/rank
```

验证 body：

```json
{
  "rank_type": 4,
  "recently_day_type": 2,
  "category_path": {
    "first_cid": 1000000957,
    "second_cid": 1000000962
  },
  "page": {
    "current": 1,
    "page_size": 3
  }
}
```

验证结果：`rank_name: "热搜榜"`，`total:200`，首项「人字拖」。

枚举：

- `RankType.HotSearchPVRank = 4`
- `DayType._7D = 2`

### 本店用户爱买榜

```http
POST /api/commop/business_chance_center/user_select/top_product
```

验证 body：

```json
{
  "common_req": {
    "first_cid": 1000000957,
    "day_type": 2,
    "peer_shop_ids": [],
    "scene": "pc"
  },
  "cate_id": 1000000957,
  "cate_level": 1,
  "select_type": 3,
  "sort_type": 1,
  "req_source": 1,
  "page": 1,
  "page_size": 7
}
```

验证结果首项：「男士新款百搭休闲老爹鞋软底增高潮流2026年流行洋气鞋子」。

相关枚举：

- `ShopUserCateTradeSortType.Platform = 3`
- `ShopUserCateTradeSortIndicator.TradingAmount = 1`

### 机会类目榜

业务代码调用 `ProductChanceMarketDigCateList`，请求体形态：

```jsonc
{
  "activity_id": "",
  "begin_date": "",
  "end_date": "",
  "date_type": 21,
  "content_type": 1,
  "cate_tag_list": 2,
  "first_cate_id": "<rank_card.filter_param.category.first_cid>",
  "source_biz_type": "dou_dian_pc",
  "page_size": 10,
  "page_no": 1,
  "is_asc": false,
  "sort_field": "pay_amt_incr_rate"
}
```

本次只从页面响应确认 UI 内容，未单独复现该 compass 接口。

## ClueTypeNew 枚举

```text
1  SearchBoosted
2  SearchLack
3  HotSearch
4  HotTrend
5  HighGrowthTrend
6  PotentialCompetitive
7  SearchSupportWord
8  TrendCate
9  Product
10 All
11 WordAll
12 ProductAndWord
13 HotProductOfSeller
14 UserBuy
15 MarketTrend
16 PeerShopAnalysis
99 BuSelection
100 Calendar
```

当前「追抖音热词」默认使用 `WordAll = 11`。

## 可复现 evaluate 调用

读取默认商机列表：

```js
const body = {
  condition: {
    hit_clue_label_ext: true,
    show_new_supply_link: true,
    include_hot_sales_products: true,
    sort: { sort_direction: 1, sort_field: 'MATCH_DEGREE' },
  },
  clue_type: '',
  clue_type_new: 11,
  page: { current: 1, page_size: 20 },
  terminal_type: 0,
  source: 'business_center',
};
const r = await fetch('/api/commop/business_chance_center/clue/common/real_time_list', {
  method: 'POST',
  credentials: 'include',
  headers: { 'content-type': 'application/json' },
  body: JSON.stringify(body),
});
return await r.json();
```

读取关键词商机：

```js
body.condition.clue_info = '男士老爹鞋';
body.page.page_size = 5;
```

读取热搜榜：

```js
const r = await fetch('/api/commop/business_chance_center/clue/rank', {
  method: 'POST',
  credentials: 'include',
  headers: { 'content-type': 'application/json' },
  body: JSON.stringify({
    rank_type: 4,
    recently_day_type: 2,
    category_path: { first_cid: 1000000957, second_cid: 1000000962 },
    page: { current: 1, page_size: 3 },
  }),
});
return await r.json();
```

## 未触碰的副作用

以下按钮会改变收藏、提报、发布或跳转状态，本次只做定位，没有点击执行：

- 收藏 / 批量收藏
- 批量复制商机
- 发相似品
- 找货源
- 晓风批量截流
- 多店全自动商机提报
- 发布商品 / 提交
