# Site Archaeology — 拼多多商家后台「订单申诉 / 售后申诉」

页面：`https://mms.pinduoduo.com/orders/appeals/aftersale/order`（标题「订单申诉」，活动 Tab `activeIndex=0`）。
登录态：商家后台 cookie。考古时间 2026-06，经 kimi-webbridge（daemon `http://127.0.0.1:10086`，session `pdd-appeal`）在已登录的真实 Chrome 里完成。
前端 chunk：`mms-static.pddpic.com/orders/static/js/appeals.<hash>.chunk.js`（React + webpack 微前端，应用名 `orders`）。

---

## 核心结论（先看这条）

- **可申诉订单列表只需 cookie 鉴权，不需要 `anti-content` 风控头。** 在页面内用原生 `fetch`（`credentials:"include"`）直接 POST 即返回 200 + 真实数据；缺参时只报 `参数校验失败`，从不报风控/验证码。→ CLI 用 kimi-webbridge 的 `evaluate` 在页面上下文复刻 fetch 即可，无需逆向签名。
- **列表的判别参数是 `subAppealQueryType`（数字枚举），分页用 `pageIndex`/`pageSize`（注意不是 `pageNumber`）。**
- bridge 的 `network detail` **只回响应体、不回请求体/请求头**（CDP `getResponseBody`）。且导航 / `network stop` 后 body 会被回收 → 抓包要「不导航、不 stop，立即取 detail」。请求体只能从 JS 源码逆向或直接 `evaluate` 复刻试探得到。
- 页面应用在加载时保存了原始 `fetch`/`XMLHttpRequest` 引用，**事后 monkey-patch `window.fetch` / `XHR.prototype` 抓不到 app 自身请求**。要抓 app 请求体只能在脚本注入早于 bundle 时机（本 bridge 不支持），所以走「源码逆向 + evaluate 复刻验证」这条路。

---

## Feature: 可申诉订单列表（已实测跑通）

**`POST https://mms.pinduoduo.com/auncel/mms/appeal/queryCanAppealInfoList`**

- Auth：cookie，`content-type: application/json`，无需额外 header。
- 请求体（最小可用）：

```json
{ "pageIndex": 1, "pageSize": 10, "subAppealQueryType": 2, "needCheckAppeal": true }
```

- 可选字段（来自源码 `appeals.chunk.js` 调用处）：`orderSnList`、`ticketSn`、`uid`（买家 uid，传 `-1` 视为不限）、`needCheckAppealSubTypes`（数组，按 queryType 取 `g[subAppealQueryType]`）、`fold`、日期过滤 `startRefundTime`/`endRefundTime`、`filterNoAppealMarkAndLowPass`、`filterNearOverdueOrder` 等。
- 响应包络：`{ success, errorCode(1000000=成功), errorMsg, result:{ total, queryCanAppealInfoDetails:[item] } }`。

### `subAppealQueryType` 枚举（实测有效值；与 `queryParams` 的 `appealType` 同值）

| 值 | 含义 | 实测 total |
|---|---|---|
| 1 | 维权申诉（RIGHT_APPEAL） | 15 |
| 2 | 极速退款申诉（SpeedRefund） | 37 |
| 5 | 订单赔偿申诉（OrderAppeal） | 0 |
| 6 | 消费者负向体验申诉（CONSUMER_NEGATIVE_EXPERIENCE_APPEAL） | 14 |
| 7 | 极速换货申诉（SpeedExchange） | 2 |

其它值（0/3/4/8…）返回 `查询申诉类型入参错误`。

### `queryCanAppealInfoDetails[]` item 字段（源码 JSON-Schema + 实测样本）

`afterSalesId`(int 售后单号), `afterSalesStatus`(int), `orderSn`(订单号), `afterSalesType`(int), `ticketSn`,
`penaltyTabTypeDesc`(问题类型描述), `violationContent`, `playMoneyAmount`, `penaltyTime`, `penaltyAppealExpireRemainTime`,
`compensateAmount`, `refundAmount`(分), `receiveAmount`(分), `canCargoAppealAmount`(可申诉货款), `canFreightAppealAmount`(可申诉运费),
`refundTime`, `exchangeTime`, `expireRemainTime`(申诉剩余时间 ms), `sellerAfterSalesShippingStatus` + `...Desc`(如「已发货」),
`thumbUrl`, `goodsName`, `goodsNumber`, `goodsSpec`, `reasonCode`(退款原因码,如 88=不想要了) + `reasonDesc`,
`expressSignStatus`, `hideAppealEntrance`(bool),
`subAppealForbiddenReasonCodeMap` / `subAppealForbiddenReasonDescMap`（{子申诉类型: 禁止原因码/描述}，如 `{"5":2000,"6":-1}` 表示未发货极速退款不满足、已发货允许），
`priority`, `preCheckAgreeResult`, `reverseLogisticOnWay`, `consoOrder`,
`batchCanCargoAppeal`, `batchCanFreightAppeal`, `showPreAuditApply`, `temporaryNoAppeal`, `lowPassRate`,
`negPreAuditInfo:{ negPreAudit, preAuditId }`。

### 实测样本（subAppealQueryType=2，total=37）

```json
{ "afterSalesId": 10000000000001, "afterSalesStatus": 5, "orderSn": "260101-000000000000001",
  "afterSalesType": 2, "refundAmount": 5000, "receiveAmount": 5000, "refundTime": 1779164908602,
  "expireRemainTime": 221113549, "sellerAfterSalesShippingStatusDesc": "已发货",
  "goodsName": "示例商品名称", "goodsSpec": "M",
  "reasonCode": 88, "reasonDesc": "不想要了",
  "subAppealForbiddenReasonCodeMap": {"5":2000,"6":-1},
  "subAppealForbiddenReasonDescMap": {"5":"未发货极速退款申诉条件不满足","6":"允许"} }
```

### 验证用 evaluate（kimi-webbridge）

```bash
curl -s -X POST http://127.0.0.1:10086/command -H 'Content-Type: application/json' -d '{
 "action":"evaluate","session":"pdd-appeal",
 "args":{"code":"(async()=>{const r=await fetch(\"/auncel/mms/appeal/queryCanAppealInfoList\",{method:\"POST\",headers:{\"content-type\":\"application/json\"},credentials:\"include\",body:JSON.stringify({pageIndex:1,pageSize:10,subAppealQueryType:2,needCheckAppeal:true})});return await r.text();})();"}
}'
```

---

## Feature: 申诉 Tab / 子类型树（已实测）

**`POST https://mms.pinduoduo.com/auncel/mms/appeal/queryParams`**  body `{}`，返回 Tab→子类型映射：

```
appealType 1 维权申诉   : [1]纠纷退款率申诉 [2]货款申诉 [3]运费申诉
appealType 5 订单赔偿申诉: [11,21]赔付单申诉 [12]商家服务态度违规申诉
appealType 2 极速退款申诉: [5]未发货-极速退款申诉 [6]已发货-极速退款申诉
appealType 7 极速换货申诉: [20]已发货-极速换货申诉
```

结构：`result.appealVOList[]{ appealType, appealTypeDesc, subAppealVOS[]{ appealSubTypes[], appealSubTypeDesc } }`。

---

## 其余相关接口（页面加载时触发，未逐一逆向请求体）

只读 / 统计：
- `POST /auncel/mms/appeal/queryAppealStatisticInfo` — 顶部角标计数。**需参数（待挖）**，空体报 `参数校验失败`。
- `POST /auncel/mms/appeal/queryAppealAmountStatisticInfo` — 可申诉金额统计。同上需参数。
- `POST /auncel/mms/appeal/queryCanAppealBatchApplyList` — 可批量申诉列表。
- `POST /auncel/app/appeal/queryAppealRightsInfo` — 申诉权益/优赔特权。
- `POST /auncel/mms/appeal/queryList` — 「申诉记录」列表（已提交的申诉）。
- `GET/POST /auncel/mms/appeal/detail/orderSn` — 单订单申诉详情。
- `POST /auncel/mms/appeal/queryIntelligentAnalysisInfo` — 智能分析。
- `POST /auncel/mms/appeal/canAppealListMark` — 列表标记。
- 预审(优赔)：`/cambridge/api/preaudit/appeal/list`、`queryCompensatedAmount`、`compensatedList`、`goldMallCheck`、`enhanceGoldMallBenefitGray`。

写操作（**高风险，未触发**，仅登记）：
- `POST /cambridge/api/appeal/order/afterSaleAppeal/submit` — 提交售后申诉。
- `POST /cambridge/api/appeal/order/batchSubmit` — 批量提交。
- `POST /cambridge/api/preaudit/appeal/submit` — 提交预审申诉。
- `POST /auncel/appeal/batchMerchantApply` — 批量商家申请。
- `POST /auncel/appeal/appendPicture` — 追加举证图片。
- `/cambridge/api/merchant/neg/pre/audit/appeal/apply`（含 `apply/check`、`study/exempt/apply`）— 负向体验预审申诉。

---

## 给后续 CLI 的建议（pdd-appeal-cli）

1. 鉴权：复用 Chrome 登录态，全程 `evaluate` 内 `fetch(..., {credentials:"include"})`，不要尝试自己拼 cookie/anti-content。
2. 首批只读命令：
   - `login-status` — `POST /janus/api/checkLogin`
   - `tabs` — `queryParams`（输出申诉类型树）
   - `list --type <1|2|5|6|7> [--page N] [--size M]` — `queryCanAppealInfoList`
   - `detail --order <orderSn>` — `detail/orderSn`
3. 写操作（submit / batchSubmit / appendPicture）默认 dry-run，`--commit` 才真正提交；参考 pdc-vip-cli 的 create 约定。
4. 抓包要诀：start → 在页面内 `evaluate` 触发 → **不 stop、不导航** → `network list` 取 requestId → 立即 `network detail`（只能拿响应体；请求体走源码逆向或 evaluate 试探）。

---

## 更新 2026-06(CloakBrowser 实战补充)

- **售后详情真实路由**:`GET https://mms.pinduoduo.com/aftersales-ssr/detail?id=<afterSalesId>&orderSn=<sn>`(列表「售后详情」按钮经 `window.open` 跳此)。整页截图即可当运费申诉真实凭证(退款单/物流单号/协商时间线/聊天记录)。注意 `id=` 是 afterSalesId;`/aftersales/detail`、`/order/aftersales/detail` 都会 302/404。
- **提交链路**:运费申诉表单填 `申诉原因(级联:退货运费→消费者无理由退货)+ 满额金额 + 申诉说明 + 必填凭证图`,点「提交申诉」,成功出现「申诉提交成功」绿勾弹窗;提交后该单从 `queryCanAppealInfoList` 掉出。已实测成功提交订单 260522-500799936140172(运费 ¥4.78)。
- **驱动通道**:CloakBrowser 隐身 Chrome,CDP 9223,Playwright `connect_over_cdp`。cookie 鉴权,无需 anti-content。
- **上传**:Playwright `set_input_files` 可直接给 `display:none` 的 file input 塞文件(kimi-webbridge 走 CDP `setFileInputFiles` 会报 `Not allowed`,需 DataTransfer 绕;Playwright 无此问题)。
- **级联下拉**:每次 CDP 连接断开会触发 blur 关菜单 → 「开下拉→点退货运费(真实点击展开子菜单)→点无理由」必须同一 Playwright 进程内完成。
