#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
款式文件夹 -> 标准商品 JSON（第一阶段：归一化清洗，与 VIP 无关）

输入：一个 款式_NN 文件夹（含 商品数据-*.xlsx + 颜色图/商品主图/商品详情页图/商品信息）
      或一个包含多个 款式_NN 的父目录。
输出：每款一份「标准商品 JSON」，结构见 README / STANDARD-PRODUCT-SCHEMA。

设计：
- xlsx 是干净的上货模板，是结构化数据的首选来源。
- 没有 xlsx 时回退到同目录的 product_extraction_results.json（OCR 抽取，较脏）。
- 图片用真实本地文件（按子目录归类 + 去重），不用 OCR JSON 里别人机器的路径。
- 清洗：颜色名去掉 OCR 前缀杂字（©、<、“ 等）；SKU 编码同样清洗。
- 不做 VIP 类目/属性映射、不上传图片——那是第二阶段。
"""
import sys, os, re, json, glob

IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".JPG", ".JPEG", ".PNG", ".WEBP")
# 子目录 -> 标准 json 里的图片分组键
IMG_DIRS = {
    "商品主图": "main",
    "商品详情页图": "detail",
    "颜色图": "color",
    "商品信息": "info",
}


def clean_text(s):
    if s is None:
        return ""
    return str(s).strip()


def clean_color(name):
    """去掉 OCR 前缀杂字：©、<、“、”、空格、连字符等，保留中英数字主体。"""
    s = clean_text(name)
    s = re.sub(r'^[^\w一-鿿]+', '', s)        # 去前导非字词符号
    s = s.replace('©', '').replace('“', '').replace('”', '').replace('"', '')
    return s.strip()


def parse_xlsx(path):
    """解析上货模板 xlsx -> dict。属性列按表头动态读取（不同类目属性不同）。"""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    rows = [[clean_text(c) for c in r] for r in ws.iter_rows(values_only=True)]
    if len(rows) < 3:
        return None
    band = rows[0]   # 大分区：品类/商品名称/商品属性/商品规格/价格与库存/服务与承诺
    head = rows[1]   # 字段名

    def col(name):
        return head.index(name) if name in head else -1

    # 商品属性区：从 band 里 "商品属性" 起到 "商品规格" 前的那些字段名
    def band_range(label):
        if label not in band:
            return (-1, -1)
        start = band.index(label)
        nxt = len(band)
        for j in range(start + 1, len(band)):
            if band[j]:
                nxt = j
                break
        return (start, nxt)

    a0, a1 = band_range("商品属性")
    attr_cols = [(head[j], j) for j in range(a0, a1) if a0 >= 0 and j < len(head) and head[j]]

    c_color, c_size = col("颜色"), col("尺码")
    c_code, c_pin, c_single, c_ref, c_stock = (
        col("商品编码"), col("拼单价"), col("单买价"), col("商品参考价"), col("库存"))
    c_name = col("商品名称")
    c_cat = 0  # 品类名称恒在 A 列
    c_ship, c_promise, c_service = col("承诺发货时间"), col("承诺"), col("服务")

    data_rows = rows[2:]

    def first_nonempty(idx):
        for r in data_rows:
            if idx >= 0 and idx < len(r) and r[idx]:
                return r[idx]
        return ""

    out = {
        "name": first_nonempty(c_name),
        "source_category": first_nonempty(c_cat),
        "attributes": {h: first_nonempty(j) for h, j in attr_cols},
        "service": {
            "ship_time": first_nonempty(c_ship),
            "promise": first_nonempty(c_promise),
            "extra": first_nonempty(c_service),
        },
        "skus": [],
    }
    for r in data_rows:
        def g(i):
            return r[i] if 0 <= i < len(r) else ""
        color, size = clean_color(g(c_color)), g(c_size)
        if not color and not size:
            continue
        out["skus"].append({
            "color": color,
            "size": size,
            "code": clean_color(g(c_code)),
            "pin_price": g(c_pin),
            "single_price": g(c_single),
            "ref_price": g(c_ref),
            "stock": g(c_stock),
        })
    out["colors"] = list(dict.fromkeys(s["color"] for s in out["skus"] if s["color"]))
    out["sizes"] = list(dict.fromkeys(s["size"] for s in out["skus"] if s["size"]))
    return out


def collect_images(folder):
    """按子目录归类真实图片，按文件名去重（IMG_0005 2.JPG 与 IMG_0005.JPG 视为重复）。"""
    imgs = {v: [] for v in IMG_DIRS.values()}
    for sub, key in IMG_DIRS.items():
        d = os.path.join(folder, sub)
        if not os.path.isdir(d):
            continue
        seen = set()
        for f in sorted(os.listdir(d)):
            if not f.endswith(IMG_EXT):
                continue
            base = re.sub(r'\s+\d+(\.\w+)$', r'\1', f)   # "IMG_0005 2.JPG" -> "IMG_0005.JPG"
            if base in seen:
                continue
            seen.add(base)
            imgs[key].append(os.path.join(d, f))
    return imgs


def load_ocr_index(folder):
    """从父目录的 product_extraction_results.json 按 product_id 建 OCR 文本索引。"""
    parent = os.path.dirname(folder.rstrip("/"))
    idx = {}
    for cand in (os.path.join(folder, "product_extraction_results.json"),
                 os.path.join(parent, "product_extraction_results.json")):
        if os.path.isfile(cand):
            try:
                for e in json.load(open(cand)):
                    idx[e.get("product_id")] = e
            except Exception:
                pass
            break
    return idx


def parse_folder(folder, ocr_idx=None):
    pid = os.path.basename(folder.rstrip("/"))
    xlsx = glob.glob(os.path.join(folder, "商品数据-*.xlsx")) or glob.glob(os.path.join(folder, "*.xlsx"))
    rec = {"product_id": pid, "source_folder": folder}
    if xlsx:
        parsed = parse_xlsx(xlsx[0])
        if parsed:
            rec.update(parsed)
            rec["source"] = os.path.basename(xlsx[0])
    if "name" not in rec:
        rec["source"] = "MISSING_XLSX"   # 推理层可回退 OCR / 视觉
    rec["images"] = collect_images(folder)
    # 给推理层准备的原料：OCR 文本 + 完整度标记
    if ocr_idx is None:
        ocr_idx = load_ocr_index(folder)
    e = ocr_idx.get(pid, {})
    rec["_reason_input"] = {
        "raw_title": e.get("title", ""),
        "ocr_text": e.get("ocr_text", ""),
        "needs_category": not rec.get("source_category"),
        "needs_attributes": not any((rec.get("attributes") or {}).values()),
        "needs_clean_name": _looks_dirty(rec.get("name", "")),
    }
    return rec


def _looks_dirty(name):
    """商品名是否像 OCR 噪声（含价格/拼单/发货等词，或过短/过长）。"""
    if not name:
        return True
    bad = ["已拼", "拼单", "预计", "发货", "送达", "券后", "券前", "好评", "在拼", "¥", "Y3", "Y4"]
    return any(b in name for b in bad) or len(name) > 40


def main():
    if len(sys.argv) < 2:
        print("用法: kuanshi_to_standard.py <款式文件夹 或 父目录> [输出.json]", file=sys.stderr)
        sys.exit(1)
    path = sys.argv[1].rstrip("/")
    if glob.glob(os.path.join(path, "商品数据-*.xlsx")):
        folders = [path]
    else:
        folders = sorted(glob.glob(os.path.join(path, "款式_*")), key=lambda p: p)
        folders = [f for f in folders if os.path.isdir(f)]
    ocr_idx = load_ocr_index(folders[0]) if folders else {}
    results = [parse_folder(f, ocr_idx) for f in folders]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    text = json.dumps(results if len(results) > 1 else results[0], ensure_ascii=False, indent=2)
    if out:
        open(out, "w").write(text)
        print(f"✓ {len(results)} 款 -> {out}", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
