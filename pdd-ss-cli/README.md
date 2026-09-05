# pdd-ss-cli

拼多多商家「售后申诉」CLI —— 经 **CloakBrowser(蓝色隐身 Chrome,CDP 9223)** + Playwright 驱动,复用真实登录态,不走 API token、不碰 kimi-webbridge/真实 Chrome。

目前主打**运费申诉**(维权申诉下「退货运费 / 消费者无理由退货」),自动抓真实售后详情页当凭证,通过率最高。

## 前置

1. CloakBrowser 跑着并开 CDP:`--remote-debugging-port=9223 --remote-allow-origins=*`(参考 [[reference_kwaishop_cloakbrowser]] 的 `cloak_serve.py`)。
2. 在隐身 Chrome 窗口里登录过 `mms.pinduoduo.com` 商家后台(会话过期需手动扫码一次,持久 profile 之后保持)。
3. `/usr/bin/python3` 装了 `playwright`(已验证可用)。

## 命令

```bash
./pdd-ss-cli login-status                 # 确认隐身 Chrome 的 PDD 登录态
./pdd-ss-cli list --type 1 --freight      # 列维权申诉里可发运费申诉的订单
./pdd-ss-cli evidence <orderSn> [-o 图]   # 抓该单售后详情整页截图(真实凭证)
./pdd-ss-cli appeal <orderSn>             # 运费申诉 dry-run:抓证据+填表+停在提交前
./pdd-ss-cli appeal <orderSn> --commit    # 真正提交
```

申诉类型(`--type`,subAppealQueryType):`1`维权申诉 `2`极速退款申诉 `5`订单赔偿申诉 `6`消费者负向体验申诉 `7`极速换货申诉。

### 消费者负向体验罚款「发起复议」(半自动)

```bash
./pdd-ss-cli neg-list                 # 列负向体验罚款记录(订单/ticketSn/金额/问题类型)
./pdd-ss-cli neg-appeal <orderSn|ticketSn>   # 开复议表单+预选原因+填描述+开工单详情供审,停在提交前
```

这类是**客诉工单**(`afterSalesId`=null,只有 ticketSn),且是**复议=最后一次机会**,凭证须真实/相关/与首次申诉不同,乱传图有「虚假凭证」处罚风险。所以 `neg-appeal` **不自动提交**:它把表单填到「复议原因=商品无问题，消费者误解」+复议描述+预上传一张工单详情参考图,同时另开该单工单详情页(含案情/聊天)供你核对,然后停下。**你需亲自:核对案情成立 → 把凭证替换为能证明「消费者误解」的聊天截图 → 手动点「提交复议」。** 默认原因/描述见脚本 `NEG_REASON`/`NEG_DESC`。

`appeal` 默认 **dry-run**(填完停在「提交申诉」前,截图到 `/tmp/pdd_ss_appeal_<sn>.png`),加 `--commit` 才真提交。提交成功会校验「申诉提交成功」提示。

输出统一 JSON:`{"ok":true,"data":...}` 或 `{"ok":false,"error":{...}}`。

## appeal 做了什么

1. 接口查该单 `afterSalesId` + 校验运费申诉是否允许(`subAppealForbiddenReasonDescMap["3"]=="允许"`)。
2. 打开 `/aftersales-ssr/detail?id=<afterSalesId>&orderSn=<sn>` 整页截图当**真实凭证**(退款单/物流/协商/聊天记录)。
3. 列表切到「维权申诉」→ 点该单「发起申诉」。
4. **单进程内**连贯填:级联选「退货运费→消费者无理由退货」、填满额金额、写申诉说明、`set_input_files` 传凭证图。
5. dry-run 截图停下;`--commit` 点「提交申诉」并校验成功。

## 已知限制 / 坑(见 ARCHAEOLOGY.md)

- **默认可申诉视图只有 6 条**;不在其中的订单(如某些到期较晚的)点不到「发起申诉」,`appeal` 会报 `row_not_visible`,需人工定位或换默认视图内订单。
- 级联下拉:每次 CDP 调用断连会 blur 关菜单,所以「开下拉→点退货运费→点无理由」必须在**单进程**里做(CLI 已如此)。
- 售后详情真实路由是 `/aftersales-ssr/detail?id=<afterSalesId>&orderSn=...`(不是 `/aftersales/detail`,那个会 302 到工作台)。
- 运费申诉「最多可申诉X元」文案无 `¥` 且可能含换行,金额正则已按去空白处理。

## 待办

- `appeal --kind cargo` 货款申诉(reason 级联不同,未逆向)。
- 直接走 submit 接口(`/cambridge/api/appeal/order/afterSaleAppeal/submit`)免 UI —— 需逆向提交体 + 凭证图床上传接口(`/auncel/appeal/appendPicture`)。
- `row_not_visible` 时自动改底层查询过滤把目标单调进视图。

接口与字段全量逆向见 [`ARCHAEOLOGY.md`](./ARCHAEOLOGY.md)。
