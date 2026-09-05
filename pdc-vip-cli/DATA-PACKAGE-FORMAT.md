# 新建商品数据包格式（productVo）

`pdc-cli create -f <文件>.json [--commit --confirm-tips]` 接收一份 **productVo JSON**。下面是你整理数据包时要填/不要填的字段。想要一份真实可跑的样板，用 `pdc-cli get <已有商品vpId>` 读出来照着改即可。

## 一、你要填的字段

| 字段 | 说明 | 例 |
|---|---|---|
| `title` | 商品名称，≤30 字 | "撞色翻领羊绒衫女秋冬针织通勤百搭高级感上衣" |
| `subTitle` | 副标题，≤8 字，可空 | "" |
| `sn` | **款号，全店唯一** | "DEMOSN001Y1" |
| `categoryId` | 叶子类目 ID（`pdc-cli categories --tree` 查） | 201088 |
| `brandId` | 品牌 ID | YOUR_BRAND_ID |
| `productType` | 商品类别，0=普通商品 | 0 |
| `areaOutput` | 产地 | "中国" |
| `weight/grossWeight/lengthAttr/width/height` | 重量(g)/毛重/长宽高(mm)，可填 0/"0" | "0" |
| `fragileThings/bulky/valuable/beauty/notAirlines` | 商品特征布尔 | false |

### `specProps[]` — 商品属性（**按类目变**，最关键）

每个属性一项；**类目的必填属性集和可选项 ID 因类目而异**：

```jsonc
// 枚举属性（dataType=2）：从该类目的可选项里挑 optionId
{ "attributeId":2371, "attributeName":"羊绒含量范围", "dataType":2, "multiValue":0,
  "values":[ {"optionId":32807, "optionName":"30%-59%"} ] }
// 自由文本（dataType=0）：填 literal
{ "attributeId":2006, "attributeName":"生产/经销/进口厂家", "dataType":0, "multiValue":0,
  "values":[ {"literal":"示例服饰有限公司"} ] }
```

> 某类目要哪些属性 + 每个属性的合法 optionId，来自接口
> `POST mp-product.vip.com/api/vc/productCategory/getCategoryAttribute`
> body `{"categoryId":<id>,"reqContext":{"platformInfo":{...}}}`，返回数组
> `[{attributeId,name,dataType,requiredType,optionFormat:{attrOptsList:[{name,optionId}]}}]`。
> （`requiredType=1` 为必填。pdc-cli 后续可加 `attrs <categoryId>` 命令直接拉这张表。）

### `itemSkuAttr[]` — 销售属性（颜色 × 尺码）

```jsonc
[{ "colourAttrId":134, "colourName":"黑色", "colourOptionId":1657,
   "colourGSN":"<sn>A",                 // 颜色货号，建议 = 款号+字母
   "colourImages":[…图URL…], "squareImages":[…],
   "sizeAttr":[
     {"attributeId":453, "name":"M", "barCode":"<sn>H13", "marketPrice":"469", "skuType":0},
     {"attributeId":453, "name":"L", "barCode":"<sn>H14", "marketPrice":"469", "skuType":0},
     {"attributeId":453, "name":"XL","barCode":"<sn>H15", "marketPrice":"469", "skuType":0} ] }]
```
- 颜色维度 `colourAttrId`+`colourOptionId`（也是类目属性，从 getCategoryAttribute 取）。
- 尺码维度 `attributeId`（453=常规尺码）+ `name`（M/L/XL…）。
- `barCode` **全局唯一**，建议 = 款号 + 后缀。

### 图片（URL 必须是已上传到唯品图床的地址）

```jsonc
"itemImages":  [ {"imageUrl":"http://a.vpimg4.com/upload/merchandise/pdcvis/<vendorId>/…jpg","imageSize":"750x1252","imageIndex":601,"imageFlag":0,"itemId":""} ],
"squareImages":[ … 方图 … ]
```
> ⚠️ 图片必须先上传到唯品图床拿到 URL；本工具不负责上传。可复用已有商品的图 URL。

### 其余可选
`itemDetailModules[]`（辅助信息：洗涤说明等 `{name,value}`）、`salesService{}`（售后，可全 null）、`qas[]`（商品问答）。

## 二、不要填（留空/置 null，服务端分配）

| 字段 | 处理 |
|---|---|
| `vendorProductId` | `""`（空=新建；非空=更新该商品） |
| `itemSkuAttr[].sizeAttr[].vendorSkuId` | `""` |
| `itemSkuAttr[].sizeAttr[].sizeDetailId` | 删除 |
| `sizeTableId` / `sizeRecommendTableId` | 暂置 `null`（绑定旧商品尺码表会报 503；尺码表非必填类目可不传） |

## 三、提交流程

```bash
pdc-cli create -f data.json                      # dry-run：摘要 + 非破坏 SKU 预检
pdc-cli create -f data.json --commit             # 写库；若返回 501 内容警告会列出
pdc-cli create -f data.json --commit --confirm-tips   # 确认忽略 501 警告强制保存
```
成功返回 `result:true` + `vendorReturnList`（每个 barcode→新 vendorSkuId）。商品进「草稿资料」(status=11 未提交审核)。

## 四、踩过的坑（已在工具里处理）

1. **保存是 form-urlencoded**：`productVo=<JSON>&vendorType=1&checkTipsConfirm=<bool>`，不是 JSON body。
2. **501 = 内容警告**（旧→新属性迁移、违规词如"最高"），首次 `result:false` 不落库，需 `checkTipsConfirm=true` 确认。
3. **503 = 尺码表映射失败**：克隆别人的 `sizeTableId` 会带来对不上的 sizeDetailId，新品先把尺码表置 null。
4. **specProps 因类目而异**：换类目必须换属性集（女式T恤 vs 女式羊绒衫 的必填属性/可选项都不同）。
