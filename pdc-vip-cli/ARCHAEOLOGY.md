# Site Archaeology — VIP PDC 创建商品 / 商品分类

唯品会供应商平台 `pdc-portal.vip.com` 创建商品流程里「商品分类」三级级联选择器的元素与接口定位记录。已登录态（示例服饰有限公司 / userId YOUR_VENDOR_ID）。2026-06。

## 核心教训：真正的页面在跨域 iframe 里

入口 URL 是套壳的微前端，**双 hash**：

```
https://vis.vip.com/index.php#/app-i/pdc-admin/admin#/product/add?vendorType=1&t=<ts>
```

- 浏览器只把第一个 `#` 后当 fragment，外壳 `vis.vip.com` 加载一堆 `name=xxx` 的隐藏 iframe（`pdc_multi`、`pdc-admin`…）。
- 真正的创建商品表单在 `name="pdc-admin"` 的 iframe，src 是**另一个域** `https://pdc-portal.vip.com/admin#/product/add?vendorType=1`（1216×578）。
- `vis.vip.com` ≠ `pdc-portal.vip.com` → 跨域，顶层 `evaluate` 读不进 `contentDocument`。

→ **直接把 tab 导航到 iframe 的 src**（`pdc-portal.vip.com/admin#/product/add?vendorType=1`），它能独立渲染（cookie 同域共享），分类选择器就成了顶层文档，可直接操作。

## Feature: 商品分类（三级级联选择）

**页面：** `https://pdc-portal.vip.com/admin#/product/add?vendorType=1`（SPA，Vue 3，Element-UI 弹窗 `.chose-prod-category-modal`）

### 元素定位（稳定选择器，无坐标）

| 对象 | 选择器 |
|---|---|
| 弹窗 | `.el-dialog.chose-prod-category-modal` |
| 三级搜索框 | `.chose-category-content input`（placeholder「请输入三级分类名称」） |
| 级联三列 | `.chose-category-content ul.category-ul`（**固定 3 个 ul**，对应一级/二级/三级） |
| 列内选项 | `ul.category-ul > li`，选中态 `li.active` |
| 已选回显 | `.chosed-category`（文本「选择的分类：女装 > … > …」） |
| 下一步 | `.chose-prod-category-modal .el-button`（文本「下一步，创建商品」，选完叶子才 enable） |

**交互模型：** 点 col0 的 li → col1 填充二级 → 点 col1 → col2 填充三级 → 点 col2 叶子 → `.chosed-category` 回显完整路径、「下一步」可点。纯客户端展开，点击**不发网络请求**（整棵树在进页面时一次性拉好）。li 无 id/data 属性，只能按 `innerText` 文本定位。

```js
// 逐级下钻：点文本匹配的 li
const col = i => document.querySelectorAll('.chose-category-content ul.category-ul')[i];
[...col(0).children].find(li=>li.innerText.trim()==='女装').click();
[...col(1).children].find(li=>li.innerText.includes('连衣裙')).click();
[...col(2).children].find(li=>li.innerText.trim()==='连衣裙').click();
// 读结果：document.querySelector('.chosed-category').innerText
```

### 分类数据接口（IDs 来源）

整棵分类树进页面时一次拉取：

**`POST https://pdc-portal.vip.com/product/getCategorys`**
- Auth：cookie，无需额外 header
- Body：`{}`（空对象即可）
- 响应：

```jsonc
{ "code":200, "msg":null, "result":[
  { "categoryId":311, "name":"女装", "children":[
    { "categoryId":312, "name":"女上装", "children":[
      { "categoryId":316, "name":"女式大衣", "children":null, "type":0, "status":0 },
      { "categoryId":320, "name":"女式卫衣_停用", "children":null, "type":0, "status":1 }
    ]}
  ]}
]}
```

字段：`categoryId`(数字ID) / `name` / `children`(叶子为 null) / `type`(0) / **`status`(0=启用, 1=停用)**。

**坑：UI 过滤掉 `status:1`（停用）项。** 接口里女装下有 6 个二级，UI 只显示 4 个：

| 二级 categoryId | 名称 | UI 可见 |
|---|---|---|
| 312 | 女上装 | ✅ |
| 330 | 女下装 | ✅ |
| 1095 | 裙装_停用 | ❌ status=1 |
| 384263 | 连衣裙/连体裤 | ✅ |
| 384862 | 女式礼服套装 | ✅ |
| 698 | 服饰配件_停用 | ❌ status=1 |

> 名字里带 `_停用` 且 `status:1` 的要在客户端剔除，别直接拿接口列表喂给用户。

### 本次走通的路径（含 ID）

```
女装(311) → 连衣裙/连体裤(384263) → 连衣裙(391033)
```

（连衣裙/连体裤 下三级：女式连体裤 391032、连衣裙 391033）

### 复刻调用（evaluate，已验证）

```js
const r = await fetch('https://pdc-portal.vip.com/product/getCategorys',
  {method:'POST', headers:{'content-type':'application/json'}, credentials:'include', body:'{}'});
const tree = (await r.json()).result;   // 完整三级分类树
```

## 同时观察到的相邻接口（创建商品页加载时）

`GET /user/getCurrentUserInfo` · `POST /product/getEditPageConfigInfo` · `POST /product/getOperateCategory` · `POST /size/querySizeTpType` · `POST /product/getCustomValueOtherWhiteAttrIds`。

---

# Feature: 创建商品 - 步骤2「商品基础信息」

选完叶子点「下一步，创建商品」→ 弹窗关闭，进入同页面的下一步（**SPA 内切换，URL 不变**，仍是 `pdc-portal.vip.com/admin#/product/add?vendorType=1`）。顶部出现「商品分类 女装 > 连衣裙/连体裤 > 连衣裙 修改分类」。右侧固定锚点导航 7 步：**商品分类 / 基础信息 / 商品属性 / 销售属性 / 商品图片 / 辅助信息 / 售后信息**。

## 表单字段（`.el-form-item` 映射）

| 字段 | 必填 | 控件 | 备注 |
|---|---|---|---|
| 商品名称 | ✅ | input(0/30) | 上方按类目动态渲染「命名规则」chip：最突出卖点+年份+适用季节+风格(必填)+…+品类词(必填) |
| 副标题 | ✕ | input(0/8) | |
| 品牌 | ✅ | el-select | 选项来自 `/product/getOperateBrandSn` |
| 款号 | ✅ | input(0/30) | |
| 商品类别 | ✅ | el-select | 来自 `/common/getProductType` |
| 商品特征 | ✕ | checkbox 组 | 基础款 / 大件 / 贵重品 / 美妆 |
| 产地 / 重量(g) / 毛重(g) / 长宽高(mm) / 质保期限(天) | ✕ | input | 折叠在「更多详细信息」里 |

→ 必填核心 4 项：**商品名称、款号、品牌、商品类别**（前两个用文本里的字面 `*`，后两个用 `.el-form-item.is-required` class）。

## 步骤2 加载的接口（全部按 categoryId 驱动，两套后端）

`pdc-portal.vip.com`:
- `POST /product/queryCategoryAttributes` — 类目属性（驱动「商品属性」步骤）
- `POST /product/getTitleRuleConfigByCategoryId` — 标题命名规则（驱动名称 chip；body 形状未试出，待挖）
- `POST /size/getSizeClassPropsByCategoryIdList` · `POST /size/getSizeClassPropsByCategoryId` · `POST /size/getUnits` — 尺码属性/单位
- `POST /common/getProductType` · `POST /product/getOperateBrandSn` — 商品类别 / 品牌下拉
- `POST /product/checkIsSupportSalesServiceByCatId` · `POST /product/checkSaleServiceIsRequired?vendorType=1` — 售后服务是否支持/必填
- `POST /product/getSwitch` · `GET /canDisableSku?recover=false&vendorType=1` · `GET /product/getVcBlacklist` · `GET /common/getAccessoryList`

`mp-product.vip.com`（第二后端，`/api/vc/*`）:
- `POST /api/vc/productCategory/getCategoryAttribute` — 类目属性（另一份）
- `POST /api/vc/product/getProductFeatures` — 商品特征（基础款/大件/贵重品/美妆）
- `POST /api/vc/productTemplate/queryTemplate` — 「保存为新模板」用的模板列表
- `POST /api/vc/common/getConfigInfo` · `POST /api/vc/product/common/selectOption` · `POST /api/product/checkProduct4VC`

> 关键认知：**类目是整个创建流程的轴**。选定 categoryId 后，名称规则、属性项、尺码表、品牌、售后是否必填全部由它派生。做 CLI 自动建商品时，第一步定 categoryId，后面所有字段约束都从上面这批接口拿。

---

# Feature: 读取完整商品详情（创建/编辑流程的"答案"）

编辑页 `#/product/edit?vendorType=1&vendorProductId=<vpId>` 加载时拉一个接口返回**整个商品的全部字段+选中值**。这是逆向「创建商品」提交体的最佳参照——填好一个商品再读它，就知道每个字段该传什么。

## 接口（关键：参数在 query string，不是 body）

```
POST https://pdc-portal.vip.com/product/queryVendorProductByVpIdForVc?vendorProductId=<vpId>&vendorType=1
Body: {}        Auth: cookie
```

**踩坑实录（参数定位过程）：**
- body 里放 `{vpId/vendorProductId/...}` 任意字段 → `code:500 "ID非法"`（controller 用 `@RequestParam` 读 query，body JSON 被无视，ID 永远是 null）。
- query `?vpId=<ID>` → 仍 `ID非法`（字段名不对）。
- query `?vendorProductId=<ID>` → 报错**变了**：`是否买断供应商入参非法` —— ID 过了，缺第二参。
- query `?vendorProductId=<ID>&vendorType=1` → **200 OK**。`vendorType=1` 就是它说的「是否买断」判定。

→ 教训：业务码 500 但 HTTP 200 说明鉴权 OK、是入参问题；**错误文案变化 = 参数定位的指南针**，盯着它逐个补参。

## 完整商品 schema（result，实测 ~23KB）

顶层标量：

| 字段 | 例值 | 说明 |
|---|---|---|
| vendorProductId | "1900000000000000001" | 19 位，**字符串**（超 JS 安全整数） |
| title / subTitle / sn | 设计感…上衣 / … / DEMOSN001 | 名称/副标题/款号 |
| productType / productTypeName | 0 / 普通商品 | 商品类别 |
| brandId / brandCnName / brandEnName | YOUR_BRAND_ID / 示例品牌 / DEMO_BRAND | 品牌 |
| vendorId | YOUR_VENDOR_ID | 商家ID |
| **categoryId** | **314** | 叶子类目（女式T恤；注意 ≠ 一级 311） |
| areaOutput / currency | 中国 / CNY | 产地 |
| weight/grossWeight/lengthAttr/width/height | 0 | 重量(g)/毛重/长宽高(mm) |
| notAirlines/fragileThings/bulky/valuable/beauty | false | 商品特征 5 个布尔（不可空运/易碎/大件/贵重/美妆） |
| status | "11" | 商品状态 |
| sizeTableId | 100000000 | 关联尺码表ID |

### `descProps[]` —— 商品属性（含选中值，**最核心**）

每项：`{ attributeId, attributeName, dataType, optionValue:[{optionId, literal, optionName}] }`
- **dataType=2**：枚举/多选 → 选 `optionId`（optionName 是显示名）
- **dataType=0**：自由文本 → optionId=0，值在 `literal`

本商品 19 个属性实例：

| attributeId | 属性 | dt | 选中值(optionId:名) |
|---|---|---|---|
| 153 | 面料 | 2 | 44569:涤纶/聚酯纤维, 1931:粘纤 |
| 69 | 版型 | 2 | 18058:常规 |
| 85 | 衣长 | 2 | 18275:常规 |
| 70 | 厚薄 | 2 | 412:常规 |
| 71 | 弹性 | 2 | 416:微弹 |
| 595 | 功能 | 2 | 17507:无 |
| 159 | 肩型 | 2 | 1495:常规肩 |
| 83 | 袖长 | 2 | 599:短袖 |
| 82 | 袖型 | 2 | 20977:常规 |
| 77 | 领型 | 2 | 488:翻领 |
| 727 | 图案 | 2 | 18955:拼色 |
| 3366 | 主风格 | 2 | 65073:都市休闲 |
| 3365 | 主款式 | 2 | 64188:拼色T恤 |
| 2266 | 适用性别 | 2 | 31612:女士 |
| 73 | 适用季节 | 2 | 452:夏 |
| 3115 | 详细材质信息-旧 | 0 | "面料：粘纤82.9% 聚酯纤维17.1%" |
| 2006 | 生产/经销/进口厂家 | 0 | "示例服饰有限公司" |
| 2973 | 厂家地址 | 0 | "浙江省杭州市" |
| 3443 | 执行标准-旧 | 0 | "GB/T22849-2024" |

> 可选项全集来自 `/product/queryCategoryAttributes`（按 categoryId）；这里 descProps 只含**已选**的。

### `itemSkuAttr[]` —— 销售属性 / SKU（颜色 × 尺码）

```jsonc
[{ "colourAttrId":134, "colourName":"黑色", "colourOptionId":1657,
   "colourGSN":"DEMOSN001A",          // 颜色货号
   "colourImages":[ 9 张 ], "squareImages":[…],
   "sizeAttr":[ {"sizeOptionId":3958,"barcode":"DEMOSN001H13"},
                {"sizeOptionId":3959,"barcode":"DEMOSN001H14"},
                {"sizeOptionId":3960,"barcode":"DEMOSN001H15"} ] }]
```
颜色是一级 SKU 维度（每色一组图 + 货号），尺码是二级（每个 sizeOptionId 一条码 barcode）。

### 图片 / 辅助 / 售后 / 尺码表

- `itemImages[9]` + `squareImages[7]`：`{imageUrl, imageIndex, imageSize:"420x531", imageType:"jpg"}`，图存 `a.vpimg4.com/upload/merchandise/pdcvis/<vendorId>/...`
- `itemDetailModules[]`（辅助信息）：副标题 / 增值税特殊管理 / 是否有防盗扣 / **洗涤说明**(长文本) —— `{name,value}`
- `salesService{}`（售后）：warrantyPeriod/warrantyNature/repairDescription/salesContact/afterSalesPhone/returnFreightStandard… 本商品全 null（代销无质保）
- `sizeTableTemplateDetailVo{}`：尺码表模板（含 `sizeTableJson` / 渲染好的 `html`）
- `qas[4]`：商品问答 `{question,answer,reqKey}`

## 复刻调用（evaluate，已验证返回 200）

```js
const r = await fetch(
  'https://pdc-portal.vip.com/product/queryVendorProductByVpIdForVc?vendorProductId=1900000000000000001&vendorType=1',
  {method:'POST', headers:{'content-type':'application/json'}, credentials:'include', body:'{}'});
const product = (await r.json()).result;   // 完整商品对象
```

> 建 CLI 蓝图：`categories`(挖树) → `attrs <categoryId>`(可选项全集) → `get <vpId>`(读样板) → 以样板的 descProps/itemSkuAttr 结构反推创建提交体。

---

# Feature: 保存 / 提交审核（写接口 + 完整提交体）

## 非破坏式抓提交体的手法（重要）

不能真点保存去改用户的真实商品。手法：**注入 fetch/XHR hook，捕获写请求的 body 后 reject/abort，让请求永远到不了服务器**——既拿到完整 payload，又零落库。

```js
const isBlock=u=>/\/product\/(saveProductV2|publishProductV3)/.test(u)||(/\/product\/saveProduct/.test(u)&&!/editPreCheck/.test(u));
const of=window.fetch;
window.fetch=function(u,o){const url=typeof u==='string'?u:u&&u.url;
  if(url&&isBlock(url)){window.__submits.push({url,body:String(o&&o.body)});return Promise.reject(new Error('blocked'))}
  return of.apply(this,arguments)};
// XHR 同理：open 存 url，send 命中则 push(body) 后 this.abort()
```

坑：hook 是 evaluate 注入的，**整文档重载就没了**；但保存是用户点击触发（非 on-load），所以「重载→等加载完→注入 hook→点保存」时间上来得及（详情 read 接口在加载时已跑完，不影响）。

## 写端点（从 JS 包 `update-product.*.js` grep 出）

| 端点 | 用途 |
|---|---|
| `POST /product/saveProduct?editPreCheck&vendorType=1` | 点保存先发：**SKU 预检**（body 只含 itemSkuAttr 数组，校验条码/SKU，不落库） |
| `POST /product/saveProductV2` | **整品保存（草稿）** ← 主提交体在这 |
| `POST /product/publishProductV3` | 保存并提交审核（结构同 saveProductV2） |
| `POST /publishProduct/queryVendorProductByVpId` · `/queryVendorSkuByBarcode` | 保存前的查询/查重（读） |

保存流程：`保存` 按钮 → `saveProduct?editPreCheck`(SKU 预检) → 过 → `saveProductV2`(整品)。

## 提交体格式：`saveProductV2`

**Content-Type: `application/x-www-form-urlencoded`**（不是 JSON！），两个字段：

```
productVo=<URL编码的整品JSON>&vendorType=1
```

`productVo` 解码后 **47 个 key**，整体镜像详情响应，但有 3 处关键差异：

### 差异 1：属性字段叫 `specProps`（读时是 `descProps`），且**含全部类目属性**（含没填的）

本商品 specProps **33 项**（vs 详情只回 19 个已填）。每项：

```jsonc
// 枚举属性 dataType=2
{ "attributeId":153, "attributeName":"面料", "dataType":2, "multiValue":1,
  "values":[ {"optionId":44569,"optionName":"涤纶/聚酯纤维"}, {"optionId":1931,"optionName":"粘纤"} ] }
// 自由文本 dataType=0
{ "attributeId":2006, "attributeName":"生产/经销/进口厂家", "dataType":0, "multiValue":0,
  "values":[ {"literal":"示例服饰有限公司"} ] }
// 未填 dataType=6（图片型属性 详细材质信息-新）
{ "attributeId":3959, "dataType":6, "multiValue":0, "values":[] }
```

→ `dataType`: 2=枚举(values 用 `{optionId,optionName}`)，0=文本(`{literal}`)，6=图片型。`multiValue`:1 可多选。**没填的属性也要带上（values:[]）**。

### 差异 2：SKU `itemSkuAttr[].sizeAttr` 用 `name` + `attributeId`，不用 sizeOptionId

```jsonc
{ "colourAttrId":134, "colourOptionId":1657, "colourGSN":"DEMOSN001A",
  "colourImages":[…], "squareImages":[…],
  "sizeAttr":[ {"attributeId":453, "name":"M", "barCode":"DEMOSN001H13", "vendorSkuId":"1544812333415673856", "skuType":0},
               {"attributeId":453, "name":"L", "barCode":"DEMOSN001H14", "vendorSkuId":"...877", "skuType":0},
               {"attributeId":453, "name":"XL","barCode":"DEMOSN001H15", "vendorSkuId":"...884", "skuType":0} ] }
```
颜色维度 `colourAttrId=134`，尺码维度 `attributeId=453`，每个尺码一条 `vendorSkuId`（19位字符串）+ `barCode`。

### 差异 3：图片项

```jsonc
{ "imageSize":"750x1252", "imageUrl":"http://a.vpimg4.com/upload/merchandise/pdcvis/YOUR_VENDOR_ID/...jpg",
  "itemId":"", "imageIndex":601, "imageFlag":0 }
```
`itemImages`(详情图 8 张) + `squareImages`(方图 7 张)。`imageIndex` 是排序权重。

### 其余字段
标量同详情：title/subTitle/sn/brandId/categoryId/areaOutput/weight…、商品特征布尔、`sizeTableId`/`sizeRecommendTableId`、`itemDetailModules`(辅助)、`salesService`(售后)、`qas`(问答 `qasOperationMode:1`)、`templateIds`。

> **建 CLI 终极蓝图**：以一个已存在商品 `get <vpId>` 读出来的对象为模板 → 改 title/sn/categoryId/specProps.values/itemSkuAttr → 转成 `specProps` 命名 → URL 编码塞进 `productVo` → `POST saveProductV2`（form-urlencoded）。先 `?editPreCheck` 过 SKU 预检。

## 第三个表单字段：`checkTipsConfirm`（501 警告确认，实测关键）

`saveProductV2` 的 POST data 其实是**三个**字段（从 JS：`data:{productVo:JSON.stringify(...),vendorType:this.vendorType,checkTipsConfirm:!!...}`）：

```
productVo=<URL编码JSON>&vendorType=1&checkTipsConfirm=false
```

**两阶段保存（实测）：**
1. `checkTipsConfirm=false` 提交 → 后端跑内容校验，若有**非阻断警告**返回：
   ```jsonc
   {"code":200,"result":{"checkResultCode":501,"result":false,
     "errorList":[{"checkResultCode":501,"errorMsgList":[
       "【商品属性-详细材质信息-新】"详细材质信息-旧" 即将被…代替…",
       "【商品属性-执行标准-新】"执行标准-旧" 即将被…代替…",
       "【商品辅助信息-洗涤说明】包含不合规的词汇或表述"最高"，请删除或修改"]}]}}
   ```
   `result:false` = **未落库**。UI 此时弹窗列出这些警告 +「已知悉，确定修改」按钮（JS：`save&&[501].includes(checkResultCode)?渲染按钮`）。
2. 点确认 → `checkTipsConfirm=true` 重提交 → 越过警告，真正落库：
   ```jsonc
   {"code":200,"result":{"checkResultCode":200,"result":true,
     "vendorProductId":"1900000000000000004",
     "vendorReturnList":[{"barcode":"DEMOSN002H53","vendorSkuId":"1543686433508831236","operationMode":0}, …]}}
   ```
   `result:true` + `vendorReturnList`（每个 SKU 的 barcode→vendorSkuId 映射）= 成功。

> 教训：`checkResultCode` 既是预检码也是结果码——**501=有警告待确认，200=成功**。少传 `checkTipsConfirm` 这个字段，含「旧→新属性迁移」或违规词的商品永远存不进去，且不会报硬错（HTTP 200、业务 result:false），极易误判成"没反应"。

**已实测**：`pdc-cli create -f <vo>.json --commit --confirm-tips` 对一件 status=11 草稿原样重存，返回 `result:true`，写入链路端到端打通。
