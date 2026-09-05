#!/usr/bin/env /usr/bin/python3
"""CloakBrowser CDP 助手 — 经 connect_over_cdp 驱动隐身 Chrome(9223)。
所有命令都作用在持久 PDD 页面上,状态(打开的弹窗/已填字段)跨调用保持。

  cloak.py goto <url>                打开/复用 PDD 页面并导航
  cloak.py eval '<js>'               执行 JS(表达式或含 ; / return 的 async 体),打印 JSON
  cloak.py click '<selector>'        Playwright 真实点击(CSS / text=)
  cloak.py hover '<selector>'        悬停(级联菜单展开用)
  cloak.py fill '<selector>' '<v>'   填输入框(走真实事件,React 可识别)
  cloak.py upload '<selector>' <p>   给 file input 塞文件(隐藏也行)
  cloak.py shot <path>               截图
  cloak.py url                       打印当前 URL/标题
"""
import sys, json
from playwright.sync_api import sync_playwright

CDP = "http://localhost:9223"
PDD_HINT = "pinduoduo.com"

def get_page(ctx, make=False):
    pages = [p for p in ctx.pages if PDD_HINT in (p.url or "")]
    if pages:
        return pages[0]
    if make or not ctx.pages:
        return ctx.new_page()
    return ctx.pages[0]

def main():
    if len(sys.argv) < 2:
        print(__doc__); return
    cmd = sys.argv[1]
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        try:
            if cmd == "goto":
                page = get_page(ctx, make=True)
                page.goto(sys.argv[2], wait_until="domcontentloaded", timeout=60000)
                out = {"ok": True, "url": page.url, "title": page.title()}
            elif cmd == "eval":
                page = get_page(ctx)
                js = sys.argv[2]
                expr = "async () => { %s }" % js if (";" in js or "return" in js) else "async () => (%s)" % js
                out = {"ok": True, "result": page.evaluate(expr)}
            elif cmd == "click":
                page = get_page(ctx)
                page.click(sys.argv[2], timeout=8000)
                out = {"ok": True, "clicked": sys.argv[2]}
            elif cmd == "hover":
                page = get_page(ctx)
                page.hover(sys.argv[2], timeout=8000)
                out = {"ok": True, "hovered": sys.argv[2]}
            elif cmd == "fill":
                page = get_page(ctx)
                page.fill(sys.argv[2], sys.argv[3], timeout=8000)
                out = {"ok": True, "filled": sys.argv[2]}
            elif cmd == "upload":
                page = get_page(ctx)
                page.set_input_files(sys.argv[2], sys.argv[3], timeout=8000)
                out = {"ok": True, "uploaded": sys.argv[3]}
            elif cmd == "shot":
                page = get_page(ctx)
                page.screenshot(path=sys.argv[2], full_page=False)
                out = {"ok": True, "path": sys.argv[2]}
            elif cmd == "url":
                page = get_page(ctx)
                out = {"url": page.url, "title": page.title()}
            else:
                out = {"ok": False, "error": "unknown cmd"}
        except Exception as e:
            out = {"ok": False, "error": str(e)[:400]}
    print(json.dumps(out, ensure_ascii=False, default=str))

if __name__ == "__main__":
    main()
