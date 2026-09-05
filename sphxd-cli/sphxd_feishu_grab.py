#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从飞书多维表格取 50 个未复制链接 -> 智能店长「链接复制」页 -> 开始批量抓取商品。

状态口径:
  - 飞书字段「是否复制过」是主状态。只取 false 的记录；抓取页返回结果后批量置 true。
  - 本地 data/feishu_sphxd_batches.json 记录每次提交的 record_id/link/result, 便于审计。

用法:
  python3 sphxd_feishu_grab.py status
  python3 sphxd_feishu_grab.py grab --limit 50
"""
import argparse
import json
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

import ocrjudge

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
DATA_DIR.mkdir(exist_ok=True)
BATCH_LEDGER = DATA_DIR / "feishu_sphxd_batches.json"
CURRENT_BATCH = DATA_DIR / "feishu_current_batch.json"

SESSION = "sphxd-feishu-grab"

from openbridge_client import OpenBridgeClient

BRIDGE = OpenBridgeClient(SESSION)
LINK_PAGE_URL = "https://sphxd.jiancent.com/copy/move?copyType=linksCopy"
FEISHU_BASE_URL = "https://my.feishu.cn/base/REPLACE_WITH_FEISHU_APP_TOKEN"
TARGET_CATEGORY = "手机通讯>手机配件>手机壳/保护套"
TITLE_BAD_WORDS = ["工厂", "代发", "批发", "跨境", "外贸"]

BASE_TOKEN = "REPLACE_WITH_FEISHU_APP_TOKEN"
TABLE_ID = "tblg4CP7ZzaA7utR"
FIELDS = ["店铺名称", "链接", "是否复制过"]


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def offer_id(url):
    m = re.search(r"/offer/(\d+)", url)
    return m.group(1) if m else url


def normalize_link(value):
    value = str(value or "").strip()
    m = re.search(r"\((https?://[^)]+)\)", value)
    if m:
        return m.group(1).strip()
    m = re.search(r"https?://\S+", value)
    return m.group(0).strip() if m else value


def lark(args, expect_json=True):
    result = subprocess.run(["lark-cli", *args], cwd=str(HERE), text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(json.dumps({
            "cmd": ["lark-cli", *args],
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }, ensure_ascii=False))
    return json.loads(result.stdout) if expect_json else result.stdout


def tmp_json(payload):
    f = tempfile.NamedTemporaryFile(
        "w",
        suffix=".json",
        prefix=".feishu_sphxd_",
        dir=HERE,
        delete=False,
        encoding="utf-8",
    )
    with f:
        json.dump(payload, f, ensure_ascii=False)
    return Path(f.name)


def load_batch_ledger():
    if not BATCH_LEDGER.exists():
        return {"batches": []}
    return json.load(open(BATCH_LEDGER, encoding="utf-8"))


def save_batch_ledger(data):
    tmp = BATCH_LEDGER.with_suffix(".json.tmp")
    json.dump(data, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, BATCH_LEDGER)


def fetch_uncopied(limit=50):
    payload = {
        "logic": "and",
        "conditions": [["是否复制过", "==", False]],
    }
    f = tmp_json(payload)
    try:
        args = [
            "base", "+record-list",
            "--as", "user",
            "--base-token", BASE_TOKEN,
            "--table-id", TABLE_ID,
            "--field-id", "店铺名称",
            "--field-id", "链接",
            "--field-id", "是否复制过",
            "--filter-json", f"@{f.name}",
            "--limit", str(limit),
            "--format", "json",
        ]
        out = lark(args)
    finally:
        try:
            f.unlink()
        except OSError:
            pass
    data = out["data"]
    rows = []
    for record_id, row in zip(data.get("record_id_list", []), data.get("data", [])):
        shop, link, copied = row
        rows.append({
            "recordId": record_id,
            "shopName": shop,
            "link": normalize_link(link),
            "copied": bool(copied),
            "offerId": offer_id(normalize_link(link)),
        })
    return rows, bool(data.get("has_more"))


def fetch_uncopied_count_sample():
    rows, has_more = fetch_uncopied(200)
    return {"sample": len(rows), "hasMore": has_more}


def mark_copied(records):
    if not records:
        return 0
    payload = {
        "record_id_list": [r["recordId"] for r in records],
        "patch": {"是否复制过": True},
    }
    f = tmp_json(payload)
    try:
        lark([
            "base", "+record-batch-update",
            "--as", "user",
            "--base-token", BASE_TOKEN,
            "--table-id", TABLE_ID,
            "--json", f"@{f.name}",
        ])
    finally:
        try:
            f.unlink()
        except OSError:
            pass
    return len(records)


def cmd(action, args=None, timeout=120):
    return BRIDGE.call(action, args, timeout=timeout)


def ev(code, timeout=120):
    return cmd("evaluate", {"code": code}, timeout=timeout).get("value")


def evj(code, timeout=120):
    return json.loads(ev(code, timeout=timeout))


JS_SETV = (
    "function setv(el,v){const p=el.tagName==='TEXTAREA'?HTMLTextAreaElement:HTMLInputElement;"
    "const s=Object.getOwnPropertyDescriptor(p.prototype,'value').set;s.call(el,v);"
    "el.dispatchEvent(new Event('input',{bubbles:true}));"
    "el.dispatchEvent(new Event('change',{bubbles:true}));}"
)
JS_RCLICK = (
    "function rclick(el){const r=el.getBoundingClientRect();"
    "const o={bubbles:true,cancelable:true,clientX:r.x+r.width/2,clientY:r.y+r.height/2,view:window};"
    "for(const t of ['pointerdown','mousedown','pointerup','mouseup','click'])"
    "el.dispatchEvent(new (t.startsWith('pointer')?PointerEvent:MouseEvent)(t,o));}"
)


def on_link_page():
    try:
        return evj(
            "(()=>{const ta=document.querySelector('textarea.el-textarea__inner');"
            "function vis(e){if(!e)return false;const r=e.getBoundingClientRect();const s=getComputedStyle(e);"
            "return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'}"
            "const btn=[...document.querySelectorAll('button')].find(e=>e.textContent.trim()==='开始批量抓取商品');"
            "return JSON.stringify({ok:vis(ta)&&vis(btn),url:location.href,title:document.title})})()"
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def ensure_link_page():
    state = on_link_page()
    if state.get("ok"):
        return
    cmd("navigate", {"url": LINK_PAGE_URL, "newTab": False, "group_title": "视频号小店复制"})
    time.sleep(5)
    state = on_link_page()
    if not state.get("ok"):
        raise RuntimeError(f"未进入链接复制页: {state}")


def write_clipboard(text):
    subprocess.run(["pbcopy"], input=text, text=True, check=True)


def show_feishu_copy(links):
    value = "\n".join(links)
    cmd("navigate", {"url": FEISHU_BASE_URL, "newTab": False, "group_title": "飞书链接复制"})
    time.sleep(4)
    write_clipboard(value)
    ev(
        "(()=>{const id='codex-copy-preview';document.getElementById(id)?.remove();"
        "const box=document.createElement('textarea');box.id=id;box.value=" + json.dumps(value, ensure_ascii=False) + ";"
        "box.style.cssText='position:fixed;z-index:2147483647;left:24px;top:24px;width:720px;height:420px;"
        "font-size:13px;line-height:1.45;background:#fff;color:#111;border:2px solid #2563eb;"
        "box-shadow:0 12px 36px rgba(0,0,0,.25);padding:12px;';"
        "document.body.appendChild(box);box.focus();box.select();"
        "return JSON.stringify({ok:true,lines:box.value.split(/\\n/).filter(Boolean).length})})()"
    )
    time.sleep(1.5)


def paste_links_into_sphxd(links):
    ensure_link_page()
    value = "\n".join(links)
    write_clipboard(value)
    filled = ev(
        "(()=>{const ta=document.querySelector('textarea.el-textarea__inner');"
        "if(!ta)return JSON.stringify({ok:false,error:'textarea not found'});"
        "ta.focus();"
        "const dt=new DataTransfer();dt.setData('text/plain'," + json.dumps(value) + ");"
        "ta.dispatchEvent(new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:dt}));"
        + JS_SETV +
        "setv(ta," + json.dumps(value) + ");"
        "return JSON.stringify({ok:true,lines:ta.value.split('\\n').filter(Boolean).length})})()"
    )
    filled = json.loads(filled)
    if not filled.get("ok") or filled.get("lines") != len(links):
        raise RuntimeError(f"链接粘贴失败: {filled}")
    return filled


def fill_and_start(links, visual_copy=False):
    if visual_copy:
        show_feishu_copy(links)
        paste_links_into_sphxd(links)
    else:
        ensure_link_page()
        value = "\n".join(links)
        filled = ev(
            "(()=>{const ta=document.querySelector('textarea.el-textarea__inner');"
            "if(!ta)return JSON.stringify({ok:false,error:'textarea not found'});"
            + JS_SETV +
            "setv(ta," + json.dumps(value) + ");"
            "return JSON.stringify({ok:true,lines:ta.value.split('\\n').filter(Boolean).length})})()"
        )
        filled = json.loads(filled)
        if not filled.get("ok") or filled.get("lines") != len(links):
            raise RuntimeError(f"链接填入失败: {filled}")

    # 若承诺书未勾选则勾选。已有签署时这里无副作用。
    ev(
        "(()=>{const label=[...document.querySelectorAll('label.el-checkbox')].find(e=>/已签署/.test(e.textContent));"
        "if(!label)return 'no-label';"
        "if(!/is-checked/.test(label.className)) label.click();"
        "return 'ok';})()"
    )
    time.sleep(0.5)
    clicked = ev(
        "(()=>{const b=[...document.querySelectorAll('button')].find(e=>e.textContent.trim()==='开始批量抓取商品');"
        "if(!b)return 'no-button';b.click();return 'clicked';})()"
    )
    if clicked != "clicked":
        raise RuntimeError(f"未能点击开始批量抓取商品: {clicked}")


def wait_grab_result(timeout=420):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        time.sleep(3)
        result = evj(
            "(()=>{const t=document.body.innerText;"
            "const ok=t.match(/抓取成功\\s*(\\d+)\\s*个/);"
            "const skip=t.match(/跳过复制\\s*(\\d+)\\s*个/);"
            "const fail=t.match(/抓取失败\\s*(\\d+)\\s*个/);"
            "const next=[...document.querySelectorAll('button')].some(e=>{"
            "const r=e.getBoundingClientRect();"
            "return /下一步：开始搬家/.test(e.textContent)&&r.width>0&&r.height>0&&getComputedStyle(e).display!=='none'&&getComputedStyle(e).visibility!=='hidden'});"
            "return JSON.stringify({ok:ok?Number(ok[1]):null,skip:skip?Number(skip[1]):0,fail:fail?Number(fail[1]):0,next,text:t.slice(0,800)})})()"
        )
        last = result
        if result.get("ok") is not None or result.get("next"):
            return result
    raise TimeoutError(f"等待抓取完成超时: {last}")


def ensure_product_list():
    state = evj(
        "(()=>{const text=document.body.innerText;"
        "const ok=/抓取成功\\s*\\d+\\s*个/.test(text);"
        "const btn=[...document.querySelectorAll('button')].some(e=>e.textContent.trim()==='设置小店分类');"
        "return JSON.stringify({ok:ok&&btn,url:location.href,title:document.title})})()"
    )
    if not state.get("ok"):
        raise RuntimeError(f"当前不在抓取后的商品列表页: {state}")


def set_batch_category(category=TARGET_CATEGORY):
    ensure_product_list()
    opened = ev(
        "(()=>{const b=[...document.querySelectorAll('button')].find(e=>e.textContent.trim()==='设置小店分类');"
        "if(!b)return 'no-button';b.click();return 'opened';})()"
    )
    if opened != "opened":
        raise RuntimeError(f"未能打开设置小店分类弹窗: {opened}")
    time.sleep(1)

    select_opened = ev(
        "(()=>{const d=[...document.querySelectorAll('.el-dialog')].filter(x=>x.offsetParent).pop();"
        "const sel=d&&d.querySelector('.pro-filter-select');"
        "if(!sel)return 'no-select';"
        + JS_RCLICK +
        "rclick(sel);return 'opened';})()"
    )
    if select_opened != "opened":
        raise RuntimeError(f"未能打开类目下拉: {select_opened}")
    time.sleep(0.5)

    fill(
        "(()=>[...document.querySelectorAll('.move-select-cid-popper input,.pro-filter-select__popper input,input')]"
        ".find(e=>e.placeholder==='输入关键字搜索'))()",
        "手机壳",
    )
    time.sleep(1.5)

    selected = ev(
        "(()=>{const want=" + json.dumps(category, ensure_ascii=False) + ";"
        "const p=[...document.querySelectorAll('.move-select-cid-popper,.pro-filter-select__popper,.el-popper')]"
        ".filter(e=>e.offsetParent).pop();"
        "const opt=p&&[...p.querySelectorAll('.select-item')]"
        ".find(e=>e.textContent.trim()===want);"
        "if(!opt)return 'no-option';"
        "const h=opt._vei&&opt._vei.onClick&&opt._vei.onClick.value;"
        "if(h){h(new MouseEvent('click',{bubbles:true,cancelable:true,view:window}));return 'handler-called'};"
        + JS_RCLICK +
        "rclick(opt);return 'clicked';})()"
    )
    if selected not in ("handler-called", "clicked"):
        raise RuntimeError(f"未能选择类目 {category}: {selected}")
    time.sleep(1)

    confirmed = evj(
        "(()=>{const d=[...document.querySelectorAll('.el-dialog')].filter(x=>x.offsetParent).pop();"
        "const shown=d&&[...d.querySelectorAll('.pro-filter-select')].some(e=>e.textContent.trim()==="
        + json.dumps(category, ensure_ascii=False)
        + ");"
        "return JSON.stringify({shown:!!shown,text:d?d.innerText.replace(/\\s+/g,' ').slice(0,500):''})})()"
    )
    if not confirmed.get("shown"):
        raise RuntimeError(f"类目未回填到弹窗: {confirmed}")

    applied = ev(
        "(()=>{const d=[...document.querySelectorAll('.el-dialog')].filter(x=>x.offsetParent).pop();"
        "const b=d&&[...d.querySelectorAll('button')].find(e=>e.textContent.trim()==='应用所有');"
        "if(!b)return 'no-apply-all';b.click();return 'clicked';})()"
    )
    if applied != "clicked":
        raise RuntimeError(f"未能点击应用所有: {applied}")
    time.sleep(3)

    result = evj(
        "(()=>{const dialogs=[...document.querySelectorAll('.el-dialog')].filter(x=>x.offsetParent).length;"
        "const cats=[...document.querySelectorAll('input.el-input__inner')]"
        ".filter(e=>/手机通讯>手机配件>手机壳/.test(e.value||''))"
        ".map(e=>e.value);"
        "return JSON.stringify({dialogs,visibleCategoryCount:cats.length,uniqueCategories:[...new Set(cats)]})})()"
    )
    return result


def fill(selector_expr, value):
    filled = ev(
        "(()=>{const el=" + selector_expr + ";"
        "if(!el)return JSON.stringify({ok:false,error:'input not found'});"
        + JS_SETV +
        "setv(el," + json.dumps(value, ensure_ascii=False) + ");"
        "return JSON.stringify({ok:true,value:el.value||''})})()"
    )
    filled = json.loads(filled)
    if not filled.get("ok"):
        raise RuntimeError(f"填入失败: {filled}")
    return filled


def review_dialog_open():
    return ev("(()=>JSON.stringify([...document.querySelectorAll('.el-dialog')].some(d=>d.offsetParent)))()") == "true"


def wait_review_dialog(tries=12):
    for _ in range(tries):
        if review_dialog_open():
            return True
        time.sleep(0.6)
    return False


def close_review_dialog():
    ev(
        "(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();"
        "const b=dlg?[...dlg.querySelectorAll('button')].find(e=>e.textContent.trim()==='关闭'):null;"
        "if(b)b.click();return 'closed';})()"
    )
    time.sleep(1)


def switch_review_info_tab():
    ev(
        "(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();"
        "if(!dlg)return 'nodlg';"
        + JS_RCLICK +
        "const t=[...dlg.querySelectorAll('.el-tabs__item,[role=tab],button')]"
        ".find(e=>/^商品信息/.test(e.textContent.trim()));"
        "if(t)rclick(t);return 'switched';})()"
    )
    time.sleep(0.8)


def switch_review_desc_tab():
    ev(
        "(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();"
        "if(!dlg)return 'nodlg';"
        + JS_RCLICK +
        "const t=[...dlg.querySelectorAll('.el-tabs__item,[role=tab],button')]"
        ".find(e=>/^描述图/.test(e.textContent.trim()));"
        "if(t)rclick(t);return 'switched';})()"
    )
    time.sleep(1.2)


def open_first_product_dialog():
    ensure_product_list()
    if review_dialog_open():
        return
    result = "no-button"
    for _ in range(3):
        ev(
            "(()=>{const sc=[...document.querySelectorAll('*')]"
            ".find(e=>e.scrollHeight-e.clientHeight>200&&e.clientHeight>150);"
            "if(sc)sc.scrollTop=0;return 'top';})()"
        )
        time.sleep(0.8)
        result = ev(
            "(()=>{"
            + JS_RCLICK +
            "const vh=innerHeight;"
            "const b=[...document.querySelectorAll('button')]"
            ".filter(e=>e.textContent.trim()==='描述图')"
            ".find(e=>{const r=e.getBoundingClientRect();return r.top>40&&r.top<vh-40&&r.width>0&&r.height>0;});"
            "if(!b)return 'no-button';"
            "b.scrollIntoView({block:'center'});"
            "rclick(b);return 'opened';})()"
        )
        if result == "opened" and wait_review_dialog(8):
            switch_review_info_tab()
            return
        time.sleep(0.8)
    raise RuntimeError(f"未能打开第一个商品详情弹窗: {result}")


def reset_and_open_first_product_dialog(default_tab="info"):
    if review_dialog_open():
        close_review_dialog()
    ensure_product_list()
    result = "no-button"
    for _ in range(3):
        ev(
            "(()=>{const sc=[...document.querySelectorAll('*')]"
            ".find(e=>e.scrollHeight-e.clientHeight>200&&e.clientHeight>150);"
            "if(sc)sc.scrollTop=0;return 'top';})()"
        )
        time.sleep(0.8)
        result = ev(
            "(()=>{"
            + JS_RCLICK +
            "const vh=innerHeight;"
            "const b=[...document.querySelectorAll('button')]"
            ".filter(e=>e.textContent.trim()==='描述图')"
            ".find(e=>{const r=e.getBoundingClientRect();return r.top>40&&r.top<vh-40&&r.width>0&&r.height>0;});"
            "if(!b)return 'no-button';"
            "b.scrollIntoView({block:'center'});"
            "rclick(b);return 'opened';})()"
        )
        if result == "opened" and wait_review_dialog(8):
            if default_tab == "desc":
                switch_review_desc_tab()
            else:
                switch_review_info_tab()
            return
        time.sleep(0.8)
    raise RuntimeError(f"未能重新打开第一个商品详情弹窗: {result}")


def clean_title_in_modal():
    words = json.dumps(TITLE_BAD_WORDS, ensure_ascii=False)
    return evj(
        "(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();"
        "if(!dlg)return JSON.stringify({status:'nodlg'});"
        "const words=" + words + ";"
        "const t=[...dlg.querySelectorAll('input')].find(e=>e.offsetParent&&e.maxLength===60&&/[\\u4e00-\\u9fa5]/.test(e.value||''));"
        "if(!t)return JSON.stringify({status:'no-title'});"
        "let v=t.value,o=v;"
        "for(const w of words){v=v.split(w).join('')}"
        "v=v.replace(/\\s+/g,' ').trim();"
        "const removed=words.filter(w=>o.includes(w));"
        "if(v!==o){"
        "const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;"
        "s.call(t,v);"
        "for(const e of ['input','change','blur'])t.dispatchEvent(new Event(e,{bubbles:true}));"
        "}"
        "const residual=words.filter(w=>t.value.includes(w));"
        "return JSON.stringify({status:v===o?'clean':'cleaned',before:o,after:t.value,removed,residual});})()"
    )


def clean_all_titles(max_products=80):
    reset_and_open_first_product_dialog(default_tab="info")
    rows = []
    for index in range(1, max_products + 1):
        if not review_dialog_open():
            raise RuntimeError(f"商品详情弹窗意外关闭，已处理 {len(rows)} 个")
        switch_review_info_tab()
        result = clean_title_in_modal()
        rows.append({"index": index, **result})
        nx = evj(
            "(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();"
            "if(!dlg)return JSON.stringify({has:false,disabled:true});"
            "const b=[...dlg.querySelectorAll('button')].find(e=>/下一个/.test(e.textContent));"
            "return JSON.stringify({has:!!b,disabled:b?(b.disabled||/is-disabled|disabled/.test(b.className)):true})})()"
        )
        if not nx.get("has") or nx.get("disabled"):
            break
        ev(
            "(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();"
            "const b=dlg&&[...dlg.querySelectorAll('button')].find(e=>/下一个/.test(e.textContent));"
            "if(b)b.click();return 'next';})()"
        )
        time.sleep(1.5)
    close_review_dialog()
    changed = [r for r in rows if r.get("status") == "cleaned"]
    residual = [r for r in rows if r.get("residual")]
    return {
        "total": len(rows),
        "changed": len(changed),
        "residual": len(residual),
        "changedSamples": changed[:10],
        "residualSamples": residual[:10],
    }


def current_desc_image_srcs():
    return evj(
        "(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();"
        "if(!dlg)return JSON.stringify([]);"
        "const items=[...dlg.querySelectorAll('.product-image-item')];"
        "return JSON.stringify(items.map(it=>{const img=it.querySelector('.img-item img.el-image__inner,.img-item img');"
        "return img?img.src:''}).filter(Boolean))})()",
        timeout=120,
    )


def ensure_desc_batch_on():
    state = evj(
        "(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();"
        "if(!dlg)return JSON.stringify({ok:false,error:'no dialog'});"
        "function rclick(el){const r=el.getBoundingClientRect();"
        "const o={bubbles:true,cancelable:true,clientX:r.x+r.width/2,clientY:r.y+r.height/2,view:window};"
        "for(const t of ['pointerdown','mousedown','pointerup','mouseup','click'])"
        "el.dispatchEvent(new (t.startsWith('pointer')?PointerEvent:MouseEvent)(t,o));}"
        "let box=[...dlg.querySelectorAll('label.el-checkbox')].find(e=>e.textContent.trim()==='关闭批量');"
        "if(box)return JSON.stringify({ok:true,enabled:true});"
        "box=[...dlg.querySelectorAll('label.el-checkbox')].find(e=>e.textContent.trim()==='启用批量');"
        "if(!box)return JSON.stringify({ok:false,error:'batch toggle not found'});"
        "rclick(box);"
        "return JSON.stringify({ok:true,enabled:/is-checked/.test(box.className),clicked:true})})()"
    )
    time.sleep(0.8)
    return state


def delete_desc_indices(indices):
    if not indices:
        return {"before": len(current_desc_image_srcs()), "checked": 0, "after": len(current_desc_image_srcs())}
    ensure_desc_batch_on()
    checked = evj(
        "(()=>{const idx=" + json.dumps(indices) + ";"
        "const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();"
        "if(!dlg)return JSON.stringify({before:0,checked:0,error:'no dialog'});"
        "function rclick(el){const r=el.getBoundingClientRect();"
        "const o={bubbles:true,cancelable:true,clientX:r.x+r.width/2,clientY:r.y+r.height/2,view:window};"
        "for(const t of ['pointerdown','mousedown','pointerup','mouseup','click'])"
        "el.dispatchEvent(new (t.startsWith('pointer')?PointerEvent:MouseEvent)(t,o));}"
        "const items=[...dlg.querySelectorAll('.product-image-item')];"
        "let n=0;"
        "for(const i of idx){const it=items[i];if(!it)continue;"
        "const cb=it.querySelector('label.el-checkbox');"
        "if(cb&&!/is-checked/.test(cb.className)){rclick(cb);n++}"
        "else if(cb){n++}}"
        "return JSON.stringify({before:items.length,checked:n})})()"
    )
    if checked.get("checked", 0) == 0:
        return checked
    time.sleep(0.8)
    ev(
        "(()=>{function rclick(el){const r=el.getBoundingClientRect();"
        "const o={bubbles:true,cancelable:true,clientX:r.x+r.width/2,clientY:r.y+r.height/2,view:window};"
        "for(const t of ['pointerdown','mousedown','pointerup','mouseup','click'])"
        "el.dispatchEvent(new (t.startsWith('pointer')?PointerEvent:MouseEvent)(t,o));}"
        "const b=[...document.querySelectorAll('button.J_imageBatchOperateEditImageBatchDelete')]"
        ".find(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0});"
        "if(!b)return 'no-delete-button';rclick(b);return 'delete-clicked';})()"
    )
    time.sleep(1.2)
    confirmed = ev(
        "(()=>{const box=[...document.querySelectorAll('.el-message-box,.el-dialog')]"
        ".filter(d=>d.offsetParent&&/确定要删除|删除/.test(d.textContent)).pop();"
        "if(!box)return 'no-confirm';"
        "const b=[...box.querySelectorAll('button')].find(e=>e.textContent.trim()==='确定');"
        "if(!b)return 'no-ok';"
        "const r=b.getBoundingClientRect();"
        "const o={bubbles:true,cancelable:true,clientX:r.x+r.width/2,clientY:r.y+r.height/2,view:window};"
        "for(const t of ['pointerdown','mousedown','pointerup','mouseup','click'])"
        "b.dispatchEvent(new (t.startsWith('pointer')?PointerEvent:MouseEvent)(t,o));"
        "return 'confirmed';})()"
    )
    time.sleep(1.8)
    checked["confirmed"] = confirmed
    checked["after"] = len(current_desc_image_srcs())
    return checked


def next_review_product():
    nx = evj(
        "(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();"
        "if(!dlg)return JSON.stringify({has:false,disabled:true});"
        "const b=[...dlg.querySelectorAll('button')].find(e=>/下一个/.test(e.textContent));"
        "return JSON.stringify({has:!!b,disabled:b?(b.disabled||/is-disabled|disabled/.test(b.className)):true})})()"
    )
    if not nx.get("has") or nx.get("disabled"):
        return False
    ev(
        "(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();"
        "const b=dlg&&[...dlg.querySelectorAll('button')].find(e=>/下一个/.test(e.textContent));"
        "if(b)b.click();return 'next';})()"
    )
    time.sleep(1.8)
    return True


def clean_desc_images(max_products=80):
    reset_and_open_first_product_dialog(default_tab="desc")
    rows = []
    total_deleted = 0
    for index in range(1, max_products + 1):
        if not review_dialog_open():
            raise RuntimeError(f"商品详情弹窗意外关闭，已处理 {len(rows)} 个")
        switch_review_desc_tab()
        srcs = current_desc_image_srcs()
        if not srcs:
            row = {"index": index, "images": 0, "deleteIndices": [], "deleted": 0, "matches": []}
        else:
            judged = ocrjudge.judge_urls(srcs)
            delete_indices = [i for i, _url, should_delete, _ocr in judged if should_delete]
            matches = [
                {"idx": i, "ocr": ocr, "urlTail": url[-80:]}
                for i, url, should_delete, ocr in judged
                if should_delete
            ]
            deletion = delete_desc_indices(delete_indices)
            deleted = deletion.get("checked", 0)
            total_deleted += deleted
            row = {
                "index": index,
                "images": len(srcs),
                "deleteIndices": delete_indices,
                "deleted": deleted,
                "matches": matches,
                "deleteResult": deletion,
            }
        rows.append(row)
        if not next_review_product():
            break
    close_review_dialog()
    changed = [r for r in rows if r.get("deleted", 0) > 0]
    errors = [
        {"index": r["index"], "matches": r.get("matches", [])}
        for r in rows
        if any(str(m.get("ocr", "")).startswith("ERR:") for m in r.get("matches", []))
    ]
    return {
        "totalProducts": len(rows),
        "totalDeleted": total_deleted,
        "productsWithDeletedImages": len(changed),
        "changedSamples": changed[:10],
        "ocrErrorMatches": errors[:10],
    }


def cmd_status():
    sample = fetch_uncopied_count_sample()
    ledger = load_batch_ledger()
    print(json.dumps({
        "baseToken": BASE_TOKEN,
        "tableId": TABLE_ID,
        "uncopiedSample": sample,
        "batchLedger": str(BATCH_LEDGER),
        "batches": len(ledger.get("batches", [])),
        "lastBatch": (ledger.get("batches") or [])[-1:] or None,
    }, ensure_ascii=False, indent=1))


def cmd_grab(limit, no_mark, visual_copy=True):
    records, has_more = fetch_uncopied(limit)
    if not records:
        print(json.dumps({"ok": True, "message": "没有未复制链接", "count": 0}, ensure_ascii=False))
        return
    links = [r["link"] for r in records]
    batch = {
        "time": now(),
        "limit": limit,
        "hasMoreAfterFetch": has_more,
        "records": records,
        "result": None,
        "markedCopied": False,
    }
    json.dump(batch, open(CURRENT_BATCH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    fill_and_start(links, visual_copy=visual_copy)
    result = wait_grab_result()
    batch["result"] = result
    marked = 0 if no_mark else mark_copied(records)
    batch["markedCopied"] = marked == len(records)
    batch["markedCount"] = marked

    ledger = load_batch_ledger()
    ledger.setdefault("batches", []).append(batch)
    save_batch_ledger(ledger)
    json.dump(batch, open(CURRENT_BATCH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({
        "ok": True,
        "submitted": len(records),
        "result": result,
        "markedCopied": marked,
        "visualCopy": visual_copy,
        "currentBatch": str(CURRENT_BATCH),
        "batchLedger": str(BATCH_LEDGER),
    }, ensure_ascii=False, indent=1))


def cmd_category():
    result = set_batch_category()
    print(json.dumps({
        "ok": True,
        "category": TARGET_CATEGORY,
        "result": result,
    }, ensure_ascii=False, indent=1))


def cmd_titles(max_products):
    result = clean_all_titles(max_products)
    print(json.dumps({
        "ok": result["residual"] == 0,
        "badWords": TITLE_BAD_WORDS,
        "result": result,
    }, ensure_ascii=False, indent=1))


def cmd_descimg(max_products):
    result = clean_desc_images(max_products)
    print(json.dumps({
        "ok": True,
        "deleteKeywords": ocrjudge.STRONG_KEYWORDS + ocrjudge.FACTORY_KEYWORDS,
        "result": result,
    }, ensure_ascii=False, indent=1))


def main():
    parser = argparse.ArgumentParser(description="Feishu -> sphxd linksCopy batch grab")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    grab = sub.add_parser("grab")
    grab.add_argument("--limit", type=int, default=50)
    grab.add_argument("--no-mark", action="store_true", help="抓取后不回写飞书 是否复制过=true")
    grab.add_argument("--no-visual-copy", action="store_true", help="不切飞书页面演示复制，直接后台填入智能店长")
    sub.add_parser("category")
    titles = sub.add_parser("titles")
    titles.add_argument("--max-products", type=int, default=50)
    descimg = sub.add_parser("descimg")
    descimg.add_argument("--max-products", type=int, default=50)
    args = parser.parse_args()

    if args.cmd == "status":
        cmd_status()
    elif args.cmd == "grab":
        cmd_grab(args.limit, args.no_mark, visual_copy=not args.no_visual_copy)
    elif args.cmd == "category":
        cmd_category()
    elif args.cmd == "titles":
        cmd_titles(args.max_products)
    elif args.cmd == "descimg":
        cmd_descimg(args.max_products)


if __name__ == "__main__":
    main()
