# sphxd-cli — 1688 → 视频号小店 批量搬家

驱动「智能店长」(sphxd.jiancent.com，链接复制) 把 1688 商品批量搬到视频号小店，
并按规则清洗：统一类目、标题删词、删除「购买须知/买家须知」描述图。

走真实 Chrome 登录态（OpenBridge），不走官方 API。

## 依赖

- OpenBridge 守护进程在跑（`curl -s http://127.0.0.1:10088/health`），
  且 Chrome 已登录 sphxd.jiancent.com、1688 已授权。
- `tesseract`（含 `chi_sim`）—— 描述图 OCR 判断须知图。
- `python3` + `openpyxl`。

## 文件

| 文件 | 作用 |
|---|---|
| `extract_links.py` | 从 xlsx 提取**未标黄**的【宝贝链接】→ `data/links.json` |
| `ocrjudge.py` | 下载描述图 + tesseract OCR + 关键词判定是否「须知图」 |
| `sphxd_move.py` | 主流程：抓取 / 设类目 / 标题删词 / 描述图清理 / 搬家 |
| `data/links.json` | 待搬链接（每 50 个一批） |
| `data/done.json` | **已复制记录表（核心依赖，跑前必读）**：统一为 1688 链接口径的"已搬过"清单。`grab` 每次自动读它，按链接（offer id 归一化）从 links 里排除已搬的，绝不重搬；`move --confirm` 成功后自动把本批追加进来。**入口用链接去重**，所以这张表也是链接，不用 offer id/标题。 |

> **去重口径＝链接。** 不知道某批搬没搬时，看 `data/done.json`——它是唯一权威的"已复制"账本。来源可统一汇入：① sphxd 复制历史接口扫出的已搬（`sourceItemId`→表格映射成链接）；② 一批已上架的成品标题（用 xlsx【商品标题】列映射成链接）。都转成链接后并入 done.json。

## 流程（每批 ≤ 50 个链接）

1. **填链接 → 开始批量抓取商品**
2. **批量设小店分类** = `手机通讯>手机配件>手机壳/保护套`（应用所有）
3. **标题删词**：删除 `一件代发/代发/工厂直销/厂家直销/源头工厂/1688`
   （词表见 `sphxd_move.py` 的 `TITLE_BAD_WORDS`）
4. **描述图清理**：逐商品 OCR，删掉含「购买须知/买家须知」等售后话术的图
   （判定词见 `ocrjudge.py` 的 `STRONG_KEYWORDS`）
5. **下一步：开始搬家**（不可逆，需 `--confirm`）

## 用法

```bash
# 0) 一次性：从 xlsx 提取链接
python3 extract_links.py

# 1) 打开页面（确保在 链接复制 tab），然后按批跑
python3 sphxd_move.py grab --batch 0        # 第 0 批 50 个 → 抓取
python3 sphxd_move.py process --batch 0      # 设类目 + 标题删词 + 描述图清理
#   人工核对后再：
python3 sphxd_move.py move --confirm         # 开始搬家（真实上架！）

# 单步调试
python3 sphxd_move.py category
python3 sphxd_move.py titles
python3 sphxd_move.py descimg
```

## 注意

- **提审限制**：页面顶部「提审商品数每天限制 150 次」。318 个商品需分多天/分批，
  注意 `move` 前确认当天剩余额度，否则搬家会失败。
- `grab` 会跳过重复链接（"跳过复制 N 个"），实际入列数可能 < 50。
- OCR 判定保守：下载/识别失败的图**默认不删**，避免误删产品图。
- 关键机制备忘：网站用 Element UI(Vue)；描述图删除走「启用批量→勾选→批量删除→确定」；
  本机 tesseract 必须用 cwd+相对文件名（绝对路径会报 file not found）。
