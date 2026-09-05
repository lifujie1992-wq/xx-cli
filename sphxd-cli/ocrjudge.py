#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
描述图 OCR 判定: 下载描述图 -> tesseract(chi_sim) -> 关键词命中判定。

判定逻辑(借鉴 智梦AI京东全自动鉴图P图 的违规词分类):
  - STRONG_KEYWORDS : 须知/售后话术图 -> 命中即删 (购买须知/买家须知/退换货等)
  - FACTORY_KEYWORDS: 厂家/代发/货源水印图 -> 命中即删 (工厂直销/源头工厂/1688等)
  - MARKETING_KEYWORDS: 促销/营销水印图 -> 命中即删 (秒杀/包邮/特价等)
  - CONTACT_KEYWORDS : 联系方式图 -> 命中即删 (手机号/电话/微信)

任一类命中 -> should_delete=True, isn(须知)=STRONG_KEYWORDS 命中。
OCR/下载失败 -> 保守不删 (should_delete=False), ocr_text 以 "ERR:" 开头。

依赖: tesseract + chi_sim 语言包。
注意: tesseract 必须用 cwd + 相对文件名调用 (绝对路径在某些版本会报错, 见 README)。

可选 AI 视觉模型升级路径 (与 智梦AI 一致的 qwen-vl-plus 三层降级):
  设置环境变量 OCR_AI_API_KEY (或 DASHSCOPE_API_KEY) 后, 当 tesseract 无命中
  但图片疑似含复杂文字时, 可调用 OpenAI 兼容接口的 qwen-vl-plus 复检。
  默认不启用 (OCR_AI_ENABLED=0)。
"""
import hashlib
import os
import re
import subprocess
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DESC_IMG_DIR = os.path.join(HERE, "data", "desc_imgs")

# ---- 关键词表 (借鉴 智梦AI京东全自动鉴图P图 的违规词分类) ----

# 须知/售后话术图: 强删除 (这些是 1688 详情图里最该清的售后说明图)
STRONG_KEYWORDS = [
    "购买须知", "买家须知", "卖家须知", "售后须知",
    "须知", "售后说明", "售后服务", "退换货", "退换说明",
    "七天无理由", "7天无理由", "质保说明", "保修说明",
]

# 厂家/代发/货源水印图: 删除 (1688 工厂直供话术, 搬到小店属违规引流)
FACTORY_KEYWORDS = [
    "工厂直销", "厂家直销", "厂商直销", "直销",
    "实力工厂", "源头工厂", "源头厂家", "源头货",
    "工厂", "厂家", "厂商", "生产线", "生产基地",
    "一件代发", "代发", "批发", "厂家直供", "工厂直供",
    "1688", "阿里巴巴", "诚信通",
]

# 促销/营销水印图: 删除 (智梦AI 重点识别的促销水印类)
MARKETING_KEYWORDS = [
    "促销水印", "促销", "店铺水印", "水印",
    "秒杀", "特价", "优惠", "包邮", "热卖", "新品", "上新",
    "量大从优", "活动价", "限时", "抢购",
]

# 联系方式图: 删除 (手机号/QQ/微信等引流联系方式)
CONTACT_KEYWORDS = [
    "手机号", "手机号码", "电话", "联系电话",
    "微信号", "微信", "加微信", "二维码",
    "QQ号", "旺旺", "客服电话",
]

ALL_DELETE_KEYWORDS = STRONG_KEYWORDS + FACTORY_KEYWORDS + MARKETING_KEYWORDS + CONTACT_KEYWORDS

# ---- tesseract 调用 ----

TESSERACT_BIN = os.environ.get("TESSERACT_BIN", "tesseract")
TESSERACT_LANG = os.environ.get("TESSERACT_LANG", "chi_sim+eng")


def _hash_url(url):
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def _download(url, dest_dir=DESC_IMG_DIR):
    """下载图片到 dest_dir, 返回 (相对cwd文件名, 绝对路径)。tesseract 需相对路径。"""
    os.makedirs(dest_dir, exist_ok=True)
    fname = _hash_url(url) + ".jpg"
    abspath = os.path.join(dest_dir, fname)
    if not os.path.exists(abspath):
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r, open(abspath, "wb") as f:
            f.write(r.read())
    # 相对 cwd 的路径: data/desc_imgs/<hash>.jpg
    return os.path.relpath(abspath, os.getcwd()), abspath


def _tesseract(rel_path):
    """对相对路径图片跑 tesseract, 返回 OCR 文本。失败返回 "ERR:..."。"""
    try:
        # 必须 cwd + 相对文件名 (绝对路径在某些 tesseract 版本会失败)
        proc = subprocess.run(
            [TESSERACT_BIN, rel_path, "stdout", "-l", TESSERACT_LANG],
            capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0:
            return "ERR:tesseract_rc=" + str(proc.returncode)
        return proc.stdout or ""
    except FileNotFoundError:
        return "ERR:tesseract_not_found"
    except subprocess.TimeoutExpired:
        return "ERR:tesseract_timeout"
    except Exception as e:
        return "ERR:" + type(e).__name__


def _find_hits(text):
    """在 OCR 文本里找命中的关键词, 返回 (hits, is_notice)。"""
    if not text or text.startswith("ERR:"):
        return [], False
    hits = [kw for kw in ALL_DELETE_KEYWORDS if kw in text]
    is_notice = any(kw in text for kw in STRONG_KEYWORDS)
    return hits, is_notice


# ---- 可选 AI 视觉模型复检 (qwen-vl-plus, 默认关闭) ----

def _ai_vision_check(url, text):
    """当 tesseract 无命中但需要更强判定时, 调 qwen-vl-plus 复检。
    默认不启用; 需设置 OCR_AI_API_KEY / DASHSCOPE_API_KEY 且 OCR_AI_ENABLED=1。
    返回 (hits, is_notice) 或 None(未启用/失败时)。"""
    if os.environ.get("OCR_AI_ENABLED", "0") != "1":
        return None
    api_key = os.environ.get("OCR_AI_API_KEY") or os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        return None
    try:
        import json as _json
        base = os.environ.get("OCR_AI_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        model = os.environ.get("OCR_AI_MODEL", "qwen-vl-plus")
        prompt = (
            "你是电商图片违规文字识别助手。识别图片是否包含以下关键词: "
            + "、".join(ALL_DELETE_KEYWORDS)
            + "。同时识别手机号/电话/二维码等联系方式。"
            "输出严格 JSON: {\"hits\":[\"关键词\"], \"is_notice\":true/false}"
        )
        body = _json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": "你是电商图片违规文字识别助手，输出必须是严格 JSON。"},
                {"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": url}},
                    {"type": "text", "text": prompt},
                ]},
            ],
        }).encode("utf-8")
        req = urllib.request.Request(base + "/chat/completions", data=body, headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = _json.loads(r.read())
        content = resp["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            return None
        obj = _json.loads(m.group(0))
        hits = obj.get("hits", [])
        is_notice = bool(obj.get("is_notice", False))
        return hits, is_notice
    except Exception:
        return None


# ---- 主入口 ----

def judge_urls(srcs):
    """对一组描述图 URL 做 OCR 判定。

    Args:
        srcs: list[str] 图片 URL 列表
    Returns:
        list[(idx, url, should_delete, ocr_text)]
        - idx: 在 srcs 中的下标
        - url: 原始 URL
        - should_delete: 是否应删除 (须知/工厂/营销/联系方式 任一命中)
        - ocr_text: OCR 文本 (失败时 "ERR:...")
    """
    results = []
    for idx, url in enumerate(srcs):
        if not url:
            results.append((idx, url, False, "ERR:empty_url"))
            continue
        try:
            rel_path, _abspath = _download(url)
        except Exception as e:
            results.append((idx, url, False, "ERR:download:" + type(e).__name__))
            continue
        text = _tesseract(rel_path)
        hits, is_notice = _find_hits(text)
        should_delete = bool(hits) or is_notice
        # tesseract 无命中时, 若启用 AI 视觉模型则复检
        if not should_delete:
            ai = _ai_vision_check(url, text)
            if ai is not None:
                ai_hits, ai_notice = ai
                should_delete = bool(ai_hits) or ai_notice
                if should_delete:
                    hits = ai_hits
                    is_notice = ai_notice
                    text = text + " [AI:" + ",".join(ai_hits) + "]"
        results.append((idx, url, should_delete, text))
    return results


# ---- CLI 自测 ----

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        urls = sys.argv[1:]
    else:
        # 用 data/desc_imgs 里已有的图自测 (读取 desc_ocr_matches.json)
        matches_file = os.path.join(HERE, "data", "desc_ocr_matches.json")
        if os.path.exists(matches_file):
            import json
            urls = [m["url"] for m in json.load(open(matches_file, encoding="utf-8"))]
        else:
            print("用法: python3 ocrjudge.py <url1> [url2 ...]")
            sys.exit(1)
    print("判定关键词:")
    print("  STRONG(须知):", STRONG_KEYWORDS)
    print("  FACTORY(工厂):", FACTORY_KEYWORDS)
    print("  MARKETING(营销):", MARKETING_KEYWORDS)
    print("  CONTACT(联系):", CONTACT_KEYWORDS)
    print("-" * 60)
    for idx, url, should_delete, text in judge_urls(urls):
        tag = "删除" if should_delete else "保留"
        short = text[:80].replace("\n", " ") if text else ""
        print(f"[{idx}] {tag} {url[-50:]}")
        print(f"    OCR: {short}")
