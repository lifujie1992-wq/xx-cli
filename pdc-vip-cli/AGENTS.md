# AGENTS.md — 唯品会 PDC 自动上货工具包（给任意 AI agent 的运行手册）

本工具包把「一个商品素材文件夹（表格 + 图片）」自动整理并上架到唯品会供应商平台。
**你（agent）是流水线中间的"质检/工艺"环节**：脚本负责确定性的解析/上传/提交，你负责需要理解内容才能做的推理判断。读完本文件即可独立操作，无需依赖特定厂商的 agent。

---

## 0. 前置条件（操作员一次性配好）

1. **OpenBridge 守护进程在跑**，且 Chrome 已**登录唯品会供应商平台**（<https://vis.vip.com>）。
   - 校验：`curl -s http://127.0.0.1:10088/health`（确认 `ok:true`、`connectedSessions` 非空，并在扩展面板启用 `browser_evaluate`）
   - 所有写操作（建品/传图）都走这个登录态，**不用 API key、不用第三方服务**。
2. **构建 CLI**：`cd <本目录> && go build -o pdc-cli .`（需 Go 1.25+）。
3. **Python**：`python3` + `openpyxl`（`pip install openpyxl`），给解析脚本用。
4. 自检：`./pdc-cli login-status` 应打印当前商家账号。

> ⚠️ 账号只能上**有权限的类目**。先 `./pdc-cli categories --tree` 看账号有哪些类目；把商品映射到这些类目里，别映射到无权限类目（会失败）。

---

## 1. 流水线总览

```
素材文件夹            [脚本]            [你·agent]              [脚本]
(表格+图片)  ──解析──►  标准json骨架  ──推理补全──►  完整标准json  ──映射+上传+提交──► 唯品草稿
```

| 步 | 谁 | 命令/动作 |
|---|---|---|
| ① 解析 | 脚本 | `python3 tools/kuanshi_to_standard.py <文件夹> out.json` |
| ② 推理 | **你** | 按 §3 规则补全 `name/category_path/attributes/colors` |
| ③ 映射 | 你+脚本 | `pdc-cli categories` 选类目ID；`pdc-cli attrs <id>` 把属性/颜色/尺码文本→optionId |
| ④ 传图 | 脚本 | `pdc-cli upload-image <本地图>...` → 图床URL |
| ⑤ 组装 | 你 | 按 `DATA-PACKAGE-FORMAT.md` 拼 `productVo.json` |
| ⑥ 提交 | 脚本 | `pdc-cli create -f productVo.json` (dry-run) → `--commit --confirm-tips` |

---

## 2. 第①步：解析（脚本，确定性）

```bash
python3 tools/kuanshi_to_standard.py /path/to/某文件夹 /tmp/standard.json   # 单款或整批
```
产出每款一条「标准json骨架」：`name/source_category/attributes/skus/colors/sizes/images` +
`_reason_input{raw_title, ocr_text, needs_category, needs_attributes, needs_clean_name}`。
脚本对品类**零假设**（属性列从表头动态读），鞋/服装/配饰通用。

## 3. 第②步：推理补全（你的核心职责）

源数据常缺类目/属性、商品名常是 OCR 噪声。按 `tools/STANDARD-PRODUCT-SCHEMA.md` 规则，对每条记录：

1. **`needs_clean_name`=true 或名含 已拼/预计/券后/¥** → 从 `raw_title`/`ocr_text` 提真实卖点，去年份、营销词、平台话术，**≤30 字**。
2. **`needs_category`=true** → 从名/OCR/主图判断品类，写 `category_path`（如 `女上装 > 女式羊绒衫`）+ `category_confidence`。
3. **`needs_attributes`=true** → 先 `pdc-cli categories` 定 categoryId，再 `pdc-cli attrs <id> --table --required` 看该类目要哪些属性，从名/OCR/图推断每个属性的值。
4. **颜色甄别**：PDD「颜色分类」常混入功能/款式变体（如"开车""涉水溯溪"）和材质后缀。拆出真颜色，标 `kind:color|variant`。
5. **绝不臆造**价格/库存/SKU编码——这些脚本已从表格取到，只读不改。

## 4. 第③步：映射到 VIP ID（你 + 脚本）

```bash
./pdc-cli categories --tree | grep <关键词>     # 语义匹配出 categoryId（账号有权限的）
./pdc-cli attrs <categoryId> --table --required # 拿属性目录：每个 attributeId + 合法 optionId
```
把你推理出的属性值/颜色/尺码**文本**，对照 `attrs` 输出匹配成 `optionId`。
- 枚举属性(dataType=2)：`values:[{optionId, optionName}]`
- 文本属性(dataType=0)：`values:[{literal}]`
- 颜色维度、尺码维度也是类目属性，同样从 `attrs` 取 `colourAttrId/colourOptionId`、尺码 `attributeId/optionId`。

## 5. 第④步：上传图片（脚本）

```bash
./pdc-cli upload-image 主图1.jpg 主图2.jpg   # 返回 ["http://a.vpimg*.com/...", ...]
```
本地图 → 唯品图床 URL。把 URL 填进 productVo 的 `itemImages`（详情长图）、`squareImages`（方图）、SKU 的 `colourImages`。

## 6. 第⑤⑥步：组装 productVo 并提交

按 `DATA-PACKAGE-FORMAT.md` 拼 `productVo.json`。要点：
- `vendorProductId:""`（空=新建）；SKU 的 `vendorSkuId:""`、删 `sizeDetailId`；`sizeTableId/sizeRecommendTableId:null`（除非建了尺码表）。
- `sn`/`barCode`/`colourGSN` **全局唯一**。

```bash
./pdc-cli create -f productVo.json                         # dry-run：摘要 + 非破坏 SKU 预检
./pdc-cli create -f productVo.json --commit --confirm-tips # 真正建草稿（confirm-tips 越过501内容警告）
```
成功返回 `result:true` + `vendorReturnList`。商品进后台「草稿资料」(status=11)。可用 `./pdc-cli get <vpId>` 复查。

---

## 7. 坑（已在工具里处理，但你要懂）

1. 保存是 **form-urlencoded**：`productVo=<JSON>&vendorType=1&checkTipsConfirm=<bool>`，不是 JSON body（pdc-cli 已封装）。
2. **501** = 内容警告（旧→新属性迁移、违规词如"最高"），首次 `result:false`，加 `--confirm-tips` 确认。
3. **503** = 尺码表映射失败（克隆别人 sizeTableId 带来对不上的 sizeDetailId）→ 新品把尺码表置 null。
4. **specProps 因类目而异**：换类目必须重取 `attrs` 重填，别照搬别的类目的 attributeId/optionId。
5. **类目权限**：只上账号有权限的类目（`categories` 能看到不代表能上，提交报错就是没权限）。

## 8. 命令速查

```
pdc-cli login-status                  当前商家
pdc-cli categories [--tree|--all]     类目树（默认剔停用）
pdc-cli attrs <id> [--table --required] 类目属性目录(attributeId+optionId)
pdc-cli config <id>                   类目配置开关(是否需尺码表/美妆…)
pdc-cli get <vpId>                    读完整商品(样板)
pdc-cli upload-image <图>...          本地图→图床URL
pdc-cli create -f vo.json [--commit --confirm-tips]  建品
```

参考：`README.md`（CLI 总览）、`DATA-PACKAGE-FORMAT.md`（productVo 字段）、`tools/STANDARD-PRODUCT-SCHEMA.md`（标准json+推理规则）、`tools/USAGE.md`（三段式说明）、`ARCHAEOLOGY.md`（接口逆向记录）。
