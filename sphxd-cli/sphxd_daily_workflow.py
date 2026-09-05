#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书链接 -> 智能店长链接复制 的每日编排脚本。

口径:
  - 每日上限按页面实际「抓取成功 N 个」累计，不按粘贴链接数累计。
  - 粘贴后被跳过的链接会在飞书标记为已复制，避免后续重复尝试；但不计入每日有效数。
  - 飞书没有未复制链接时，自动调用 ali1688 的 phone_case_workflow.sh next 补一批。
  - 默认不点击「下一步：开始搬家」。如要完整自动搬家，必须显式传 --confirm-move。
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

import sphxd_feishu_grab as grab


HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
STATE_FILE = DATA_DIR / "sphxd_daily_state.json"
ALI_WORKFLOW = Path("~/x-cli/ali1688-cli/phone_case_workflow.sh")


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_key():
    return date.today().isoformat()


def load_state():
    if STATE_FILE.exists():
        state = json.load(open(STATE_FILE, encoding="utf-8"))
    else:
        state = {}
    if state.get("date") != today_key():
        state = {
            "date": today_key(),
            "effectiveCopied": 0,
            "attemptedLinks": 0,
            "skippedLinks": 0,
            "failedLinks": 0,
            "batches": [],
            "refills": [],
        }
    return state


def save_state(state):
    DATA_DIR.mkdir(exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    json.dump(state, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tmp.replace(STATE_FILE)


def run_refill(pages, delay):
    cmd = [str(ALI_WORKFLOW), "next", str(pages), str(delay)]
    result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    event = {
        "time": now(),
        "cmd": cmd,
        "returncode": result.returncode,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
    }
    if result.returncode != 0:
        raise RuntimeError(json.dumps(event, ensure_ascii=False, indent=1))
    return event


def move_current_batch(confirm):
    if not confirm:
        return {"moved": False, "reason": "missing --confirm-move"}
    clicked = grab.ev(
        "(()=>{const b=[...document.querySelectorAll('button')].find(e=>/开始搬家/.test(e.textContent));"
        "if(!b)return 'no-button';b.click();return 'clicked';})()"
    )
    if clicked != "clicked":
        raise RuntimeError(f"未能点击开始搬家: {clicked}")
    last = None
    for _ in range(90):
        time.sleep(2)
        last = grab.evj(
            "(()=>{const t=document.body.innerText;"
            "function vis(e){if(!e)return false;const r=e.getBoundingClientRect();const s=getComputedStyle(e);"
            "return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'}"
            "const submitted=t.match(/已提交\\s*(\\d+)\\s*个商品搬家/);"
            "const back=[...document.querySelectorAll('button')].some(e=>e.textContent.trim()==='返回继续复制');"
            "const ta=document.querySelector('textarea.el-textarea__inner');"
            "const grab=[...document.querySelectorAll('button')].find(e=>e.textContent.trim()==='开始批量抓取商品');"
            "const linkPage=vis(ta)&&vis(grab);"
            "return JSON.stringify({submitted:submitted?Number(submitted[1]):null,back,linkPage,text:t.slice(0,800)})})()",
            timeout=120,
        )
        if last.get("submitted") is not None or last.get("back") or last.get("linkPage"):
            return {"moved": True, "result": last}
    raise TimeoutError(f"等待开始搬家结果超时: {last}")


def return_to_link_page():
    state = grab.on_link_page()
    if state.get("ok"):
        return {"already": True}
    clicked = grab.ev(
        "(()=>{const btns=[...document.querySelectorAll('button')];"
        "const b=btns.find(e=>e.textContent.trim()==='返回继续复制')||"
        "btns.find(e=>e.textContent.trim()==='返回上一步');"
        "if(!b)return 'no-return-button';b.click();return 'clicked';})()"
    )
    time.sleep(3)
    if not grab.on_link_page().get("ok"):
        grab.ensure_link_page()
    return {"clicked": clicked}


def fetch_records_or_refill(limit, refill_pages, refill_delay, state):
    records, has_more = grab.fetch_uncopied(limit)
    if records:
        return records, has_more, None

    refill = run_refill(refill_pages, refill_delay)
    state.setdefault("refills", []).append(refill)
    save_state(state)
    records, has_more = grab.fetch_uncopied(limit)
    return records, has_more, refill


def process_one_batch(records, confirm_move, visual_copy=True):
    links = [r["link"] for r in records]
    batch = {
        "time": now(),
        "records": records,
        "submittedLinks": len(records),
        "grabResult": None,
        "effectiveCopied": 0,
        "markedCopied": 0,
        "cleaning": None,
        "move": None,
        "visualCopy": visual_copy,
    }
    json.dump(batch, open(grab.CURRENT_BATCH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    grab.fill_and_start(links, visual_copy=visual_copy)
    result = grab.wait_grab_result()
    effective = int(result.get("ok") or 0)
    skipped = int(result.get("skip") or 0)
    failed = int(result.get("fail") or 0)
    batch["grabResult"] = result
    batch["effectiveCopied"] = effective
    batch["skipped"] = skipped
    batch["failed"] = failed

    # 跳过项通常是平台已复制/重复链接。标记本次尝试过的链接，避免后续反复消耗时间。
    batch["markedCopied"] = grab.mark_copied(records)

    if effective > 0:
        category = grab.set_batch_category()
        titles = grab.clean_all_titles(max_products=effective)
        descimg = grab.clean_desc_images(max_products=effective)
        batch["cleaning"] = {
            "category": category,
            "titles": titles,
            "descimg": descimg,
        }
        batch["move"] = move_current_batch(confirm_move)
        if confirm_move:
            return_to_link_page()
    else:
        return_to_link_page()

    json.dump(batch, open(grab.CURRENT_BATCH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return batch


def cmd_status():
    state = load_state()
    sample = grab.fetch_uncopied_count_sample()
    print(json.dumps({
        "date": state["date"],
        "stateFile": str(STATE_FILE),
        "effectiveCopiedToday": state["effectiveCopied"],
        "attemptedLinksToday": state["attemptedLinks"],
        "skippedLinksToday": state["skippedLinks"],
        "failedLinksToday": state["failedLinks"],
        "batchesToday": len(state.get("batches", [])),
        "refillsToday": len(state.get("refills", [])),
        "uncopiedSample": sample,
        "lastBatch": (state.get("batches") or [])[-1:] or None,
    }, ensure_ascii=False, indent=1))


def cmd_run(args):
    state = load_state()
    made_progress = False
    for _ in range(args.max_batches):
        remaining = args.daily_limit - int(state.get("effectiveCopied", 0))
        if remaining <= 0:
            break

        batch_limit = min(args.batch_size, remaining)
        records, has_more, refill = fetch_records_or_refill(
            batch_limit,
            args.refill_pages,
            args.refill_delay,
            state,
        )
        if not records:
            break

        batch = process_one_batch(records, args.confirm_move, visual_copy=not args.no_visual_copy)
        batch["hasMoreAfterFetch"] = has_more
        batch["refilledBeforeBatch"] = refill is not None
        state["batches"].append(batch)
        state["effectiveCopied"] += int(batch.get("effectiveCopied") or 0)
        state["attemptedLinks"] += int(batch.get("submittedLinks") or 0)
        state["skippedLinks"] += int(batch.get("skipped") or 0)
        state["failedLinks"] += int(batch.get("failed") or 0)
        save_state(state)
        made_progress = True

        if not args.confirm_move:
            break

    print(json.dumps({
        "ok": True,
        "madeProgress": made_progress,
        "date": state["date"],
        "effectiveCopiedToday": state["effectiveCopied"],
        "dailyLimit": args.daily_limit,
        "remainingToday": max(0, args.daily_limit - state["effectiveCopied"]),
        "attemptedLinksToday": state["attemptedLinks"],
        "skippedLinksToday": state["skippedLinks"],
        "failedLinksToday": state["failedLinks"],
        "batchesToday": len(state.get("batches", [])),
        "refillsToday": len(state.get("refills", [])),
        "stateFile": str(STATE_FILE),
        "note": "未传 --confirm-move，本次只处理一批并停在搬家前。" if not args.confirm_move else "已按 --confirm-move 自动点击开始搬家。",
    }, ensure_ascii=False, indent=1))


def main():
    parser = argparse.ArgumentParser(description="每日 150 有效复制编排")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    run = sub.add_parser("run")
    run.add_argument("--daily-limit", type=int, default=150)
    run.add_argument("--batch-size", type=int, default=50)
    run.add_argument("--max-batches", type=int, default=12)
    run.add_argument("--refill-pages", type=int, default=1)
    run.add_argument("--refill-delay", type=float, default=8)
    run.add_argument("--no-visual-copy", action="store_true", help="不切到飞书页面演示复制，直接后台填入智能店长")
    run.add_argument("--confirm-move", action="store_true", help="确认点击「下一步：开始搬家」并循环到每日上限")
    args = parser.parse_args()

    if args.cmd == "status":
        cmd_status()
    elif args.cmd == "run":
        cmd_run(args)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=1), file=sys.stderr)
        raise
