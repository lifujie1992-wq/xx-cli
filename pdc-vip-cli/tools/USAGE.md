# 怎么用：款式文件夹 → 唯品会上架

**性质：脚本 + AI 混合。** 不是纯脚本，也不是纯 AI。能用规则确定算出来的（解析表格、归类图片、拼提交体、调接口）交给脚本，确定且免费；需要"看懂、判断、清洗"的（脏标题、缺失的类目和属性、真假颜色）交给 AI。

## 三段角色（谁负责什么）

| 段 | 工具 | 性质 | 干什么 |
|---|---|---|---|
| ① 解析 | `tools/kuanshi_to_standard.py` | **纯脚本** | 读 xlsx、SKU 网格、价格库存、归类去重图片、清颜色杂字、附 OCR 文本 |
| ② 推理 | **AI**（Claude / 一个 LLM 步骤） | **必须 AI** | 清洗商品名、推断类目、推断属性、甄别真假颜色 → 补成完整「标准 json」|
| ③ 映射+上架 | `pdc-cli` + 类目接口 | **脚本(+一点 AI 配类目)** | 标准 json → VIP productVo（类目/属性换 ID、图片换 URL）→ `create` 提交 |

> 为什么 ② 必须 AI：42 款里 41 款表格的类目/属性整列是空的，部分"商品名"是 OCR 垃圾（"已拼977件…"）。这些没有规则能算，必须靠理解上下文来判断——这正是 AI 干的活。脚本只能把"能确定的"摆出来。

## 实际操作流程

### 第 1 步：解析（你自己跑脚本，0 成本）

```bash
cd ~/xx-cli/pdc-vip-cli
# 单款：
python3 tools/kuanshi_to_standard.py /path/to/款式_01
# 整批（输出到文件）：
python3 tools/kuanshi_to_standard.py /path/to/智能分组结果 /tmp/standard_all.json
```

得到「标准 json 骨架」：结构、SKU、价格、图片都齐了，但脏/缺的字段带着 `_reason_input`（原始标题 + OCR 文本 + `needs_category/needs_attributes/needs_clean_name` 标记）。

### 第 2 步：推理补全（交给 AI）

把骨架交给 AI（就是对我说"把 /tmp/standard_all.json 推理补全"），AI 按 `STANDARD-PRODUCT-SCHEMA.md` 的规则：
- 标记 `needs_clean_name` 的 → 从 OCR 提真实卖点，去年份/营销词，≤30 字
- 标记 `needs_category` 的 → 判品类（洞洞鞋/凉鞋/拖鞋…），归一化 `大类 > 子类`
- 标记 `needs_attributes` 的 → 按品类补属性（鞋→鞋面材质/闭合方式/季节）
- 颜色里挑出"假颜色"（开车/涉水溯溪是功能变体）

产出完整「标准 json」（样例见 `example.款式_02.standard.json`）。
> 这步是按款扇出的 AI 活：42 款就是 42 次推理。量大时可让我"用 workflow"并行跑。

### 第 3 步：映射成 VIP productVo + 上架（脚本为主）

```bash
# 类目/属性查 ID（脚本）
pdc-cli categories --tree | grep 洞洞      # 找 VIP 类目 ID（鞋在 271 下）
# AI 把标准 json 的 category_path / attributes / colors / sizes 换成 VIP 的 categoryId / optionId
# （复用已考古的 getCategoryAttribute 目录）
# 生成 productVo.json 后：
pdc-cli create -f productVo.json                 # dry-run（不写库）
pdc-cli create -f productVo.json --commit --confirm-tips   # 真正建草稿
```

## 现状（哪些通了）

| 环节 | 状态 |
|---|---|
| ① 解析脚本 | ✅ 已建，42 款跑通 |
| ② AI 推理规则 | ✅ 规则+样例已定，按款执行 |
| ③ 类目/属性 → ID | ✅ 接口已考古，可复用 |
| ③ create 上架 | ✅ 已端到端实测（建过真实草稿） |
| 图片本地文件 → 唯品图床 URL | ✅ 已打通：`pdc-cli upload-image <本地图>`，走唯品自己的 `/file/uploadImage`，**无需第三方图床/注册** |

## 一句话总结

> **你跑一个脚本把文件夹拆成结构化骨架 → 让 AI 把脏的/缺的字段推理补全 → 再跑脚本（含自动上传本地图换 URL）换成 VIP 格式并提交。** 脚本保证又快又准又免费，AI 只在"需要看懂内容做判断"的地方介入。整条链已全部打通，无第三方依赖。
