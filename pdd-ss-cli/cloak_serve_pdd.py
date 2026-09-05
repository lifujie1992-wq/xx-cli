#!/usr/bin/env /usr/bin/python3
"""起常驻 CloakBrowser(stealth Chromium)并开 CDP 9223，供 pdd-ss-cli 挂载。
复用 ~/.kwaishop-publisher/cloak-profile 持久 profile（已含 mms.pinduoduo.com 登录态）。
"""
import os, sys, time
from pathlib import Path
from cloakbrowser import launch_persistent_context

PROFILE = str(Path.home() / ".kwaishop-publisher" / "cloak-profile")
PORT = int(os.environ.get("CLOAK_CDP_PORT", "9223"))
URL = "https://mms.pinduoduo.com/"

ctx = launch_persistent_context(
    PROFILE,
    headless=False,
    args=[f"--remote-debugging-port={PORT}", "--remote-allow-origins=*"],
    viewport={"width": 1440, "height": 1000},
    locale="zh-CN",
    timezone="Asia/Shanghai",
)
page = ctx.pages[0] if ctx.pages else ctx.new_page()
try:
    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
except Exception as exc:
    print(f"[serve] 首次导航异常(忽略): {exc}", flush=True)
print(f"[serve] CloakBrowser 已启动 CDP=http://localhost:{PORT} url={page.url}", flush=True)
sys.stdout.flush()
while True:
    time.sleep(5)
