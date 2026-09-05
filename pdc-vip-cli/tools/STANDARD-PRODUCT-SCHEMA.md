# 标准商品 JSON（款式文件夹 → 标准 json）

用户提供「**表格 + 图片**」的款式文件夹（商品类型不限：鞋/服装/配饰…），自动推理整理成下面的标准 JSON，作为后续建品（VIP productVo）的统一中间格式。

## 两层管线

```
款式文件夹                 tools/kuanshi_to_standard.py            推理层(LLM)                标准商品JSON
(xlsx + 4类图片  ──机械解析──►  骨架 + _reason_input  ──补类目/属性/清洗名──►  完整标准记录
 + OCR json)                  (结构/SKU/图片已就位)    (从名+OCR+图片推断)
```

- **机械层**（脚本，已实现）：解析 xlsx（属性列**动态读表头**，不写死任何品类）、归类去重图片、清洗颜色 OCR 杂字、附带 OCR 文本。
- **推理层**（LLM，按 `_reason_input` 标记触发）：源表 41/42 缺类目与属性、部分商品名是 OCR 噪声（"已拼977件…"），必须靠推理补全。

## Schema

```jsonc
{
  "product_id": "款式_02",
  "source_folder": "…/款式_02",
  "source": "商品数据-7129.xlsx",      // 或 MISSING_XLSX

  "name": "厚底洞洞鞋男防滑透气司机沙滩鞋",   // 推理层清洗后（≤30字，去年份/营销词/平台话术）
  "name_raw": "厚底洞洞鞋男款外穿夏季2026新款防滑防臭透气司机开车沙滩鞋男款",

  "category_path": "男鞋 > 洞洞鞋",        // 推理层归一化品类（来源为空时从名/OCR/图推断）
  "category_confidence": "high|medium|low",

  "attributes": {                          // 键随品类变；推理层补全，标注来源
    "鞋面材质": "EVA",
    "闭合方式": "套脚",
    "适用季节": "夏季"
  },

  "colors": [                              // 清洗后；区分"真颜色"与"款式/功能变体"
    {"name": "白色", "kind": "color"},
    {"name": "开车", "kind": "variant"},    // 非颜色（功能款），建实物时按销售属性变体处理
    {"name": "涉水溯溪", "kind": "variant"}
  ],
  "sizes": ["35","37","39","40","42","44"],

  "skus": [                               // 颜色×尺码网格，含价格/库存/编码
    {"color":"白色","size":"35","code":"7129-白色-35","pin_price":"220","single_price":"230","ref_price":"240","stock":"400"}
  ],
  "price": {"pin": 220, "single": 230, "ref": 240},   // 概览（多色不同价时取代表值，明细在 skus）

  "service": {"ship_time":"24小时发货及揽收","promise":"7天无理由退货，假一赔十","extra":""},

  "images": {                             // 真实本地路径，按子目录归类、去重
    "main":   ["…/商品主图/IMG_0001.JPG"],
    "detail": ["…/商品详情页图/…"],
    "color":  ["…/颜色图/…"],
    "info":   ["…/商品信息/…PNG"]
  },

  "_reason_input": {                      // 机械层产出，供推理层；完成后可删
    "raw_title": "…", "ocr_text": "…",
    "needs_category": true, "needs_attributes": true, "needs_clean_name": false
  }
}
```

## 推理层规则

1. **清洗商品名**（`needs_clean_name` 或名含 已拼/预计/券后/¥ 等）：从 `name_raw`/`ocr_text` 提取真实卖点，去掉年份、"新款""外穿"等填充与平台话术，≤30 字，保留品类词+关键卖点。
2. **推断品类**（`needs_category`）：从名/OCR/主图判断（洞洞鞋/凉鞋/拖鞋/单鞋/网鞋…），归一化为 `大类 > 子类`。低置信度标 `low` 待人工确认。
3. **推断属性**（`needs_attributes`）：按品类该有的属性（鞋→鞋面材质/闭合方式/适用季节；服装→面料/版型/领型…）从名/OCR/图推断；拿不准留空并标注。
4. **颜色甄别**：PDD「颜色分类」常混入款式/功能变体（如"开车""涉水溯溪"）和材质后缀（"绒面""米色绒面"）。拆出真颜色 + 标 `kind`。
5. **绝不臆造价格/库存/SKU 编码**——这些机械层已从表格取到，推理层只读不改。

## 与 VIP 建品的衔接（下一阶段）

标准 JSON → VIP productVo 还需：① `category_path` → VIP categoryId（`pdc-cli categories` + 语义匹配，鞋在 `271:鞋` 下）；② attributes/colors/sizes → VIP 各属性 optionId（`getCategoryAttribute`）；③ 本地图片 **上传到唯品图床** 换 URL（上传接口待考古）。前两步可复用已有链路，第三步是唯一未打通的硬环节。
```
