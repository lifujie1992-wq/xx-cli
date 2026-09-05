#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sphxd 智能店长(链接复制) —— 抓取 + 逐商品数[适用型号]，报哪个商品型号数 > 阈值。

与 sphxd_move.py 的搬家流程不同, 这里:
  - 链接由【人工】粘贴进页面的链接框(本脚本不填链接);
  - grab: 点[开始批量抓取商品], 轮询直到抓取成功;
  - skucheck: 逐个打开商品详情弹窗 → 切[SKU信息]tab → 数[适用型号]行数,
              报出型号数 > THRESHOLD(默认100)的商品序号。

复用 sphxd_move.py 的 OpenBridge 封装与实测选择器(JS_CLICK / 适用型号区 .sku-type-box>li.sku-item),
不自行另写一套, 守 X-CLI 既有能力。

关键坑(实测):
  - 商品列表是【虚拟滚动】, 弹窗[上一个/下一个]只在打开时已加载的连续区间走;
    [下一个]能懒加载到真正末尾, [上一个]能懒加载回真正开头。
  - 故每次全量遍历前, 先 _open_first_modal 开弹窗, 再 _goto_first(狂点上一个直到
    【稳定】禁用)倒回真正第1个, 才能用[下一个]覆盖全部商品; 否则会从中途开始漏前面的。
  - 上一个/下一个 在加载瞬间会瞬时禁用, 判定到头/到尾都做二次确认, 防早停。

用法:
  python3 sku_check.py grab                 # 人工已贴好链接后, 点抓取并等完成
  python3 sku_check.py skucheck             # 抓取成功后, 逐商品数适用型号(报 > --gt)
  python3 sku_check.py skucheck --gt 100    # 自定义阈值(默认100)
  python3 sku_check.py scanlong             # 全量扫描: 报型号值 > --limit 字(默认40, 只读)
  python3 sku_check.py fixlong              # 全量修复: 把超长且在 FIXMAP 内的型号改短并复验
  python3 sku_check.py run                  # grab + skucheck 一条龙
"""
import sys, os, json, time, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# 复用既有封装: OpenBridge 调用 + 点击序列 + 弹窗/SKU 选择器
from sphxd_move import (
    ev, evj, JS_CLICK,
    _wait_review_dialog, _review_dialog_open, _close_review_modal,
)


# ---------------- grab: 点抓取(链接由人工粘贴) ----------------
def step_grab_clickonly():
    """假定链接已由人工粘贴进链接框。仅点[开始批量抓取商品]并轮询抓取成功。"""
    # 确认页面上有抓取按钮和已粘贴的链接
    st = evj("(()=>{const ta=document.querySelector('textarea.el-textarea__inner');"
             "const b=[...document.querySelectorAll('button')].some(e=>e.textContent.trim()==='开始批量抓取商品');"
             "const lines=ta?ta.value.split('\\n').filter(s=>s.trim()).length:0;"
             "return JSON.stringify({hasBtn:b,hasTa:!!ta,lines})})()")
    if not st.get("hasBtn"):
        print("⛔ 当前页面没有[开始批量抓取商品]按钮, 请确认停在链接复制工作台。")
        return None
    print(f"  链接框已粘贴 {st.get('lines')} 行链接。")
    if not st.get("lines"):
        print("⛔ 链接框是空的, 请先把链接粘贴进页面再跑。")
        return None
    r = ev("(()=>{const b=[...document.querySelectorAll('button')].find(e=>e.textContent.trim()==='开始批量抓取商品');"
           "if(!b)return 'no-btn';b.click();return 'clicked'})()")
    if r != "clicked":
        print("⛔ 没点到抓取按钮。")
        return None
    print("  已点击[开始批量抓取商品], 等待抓取完成...")
    for _ in range(120):
        time.sleep(3)
        d = evj("(()=>{const t=document.body.innerText;const m=t.match(/抓取成功\\s*(\\d+)\\s*个/);"
                "const s=t.match(/跳过复制\\s*(\\d+)\\s*个/);return JSON.stringify({ok:m?m[1]:null,skip:s?s[1]:null})})()")
        if d.get("ok") is not None:
            print(f"  ✓ 抓取完成: 成功 {d['ok']} 个, 跳过 {d.get('skip')} 个")
            return d
    print("  ⚠️ 等待抓取超时, 请人工检查页面。")
    return None


# ---------------- skucheck: 逐商品数适用型号 ----------------
def _switch_sku_tab():
    """当前商品详情弹窗内切到[SKU信息]tab。"""
    ev("(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();if(!dlg)return'x';" + JS_CLICK +
       "const t=[...dlg.querySelectorAll('.el-tabs__item,[role=tab]')].find(e=>/^SKU信息/.test(e.textContent.trim()));"
       "if(t)rclick(t);return't';})()")
    time.sleep(1.0)


def _count_models():
    """当前弹窗(已在SKU信息tab): 数[适用型号]区 li.sku-item 行数(有值的)。返回 int, -1=没找到型号区。"""
    cnt = ev("(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();if(!dlg)return'-1';"
             "const ml=[...dlg.querySelectorAll('*')].find(e=>e.childElementCount===0&&/^适用型号/.test((e.textContent||'').trim()));"
             "if(!ml)return'-1';const mt=ml.getBoundingClientRect().top;"
             "const box=[...dlg.querySelectorAll('.sku-type-box')].find(b=>b.getBoundingClientRect().top>=mt-30);if(!box)return'0';"
             "const lis=[...box.querySelectorAll('li.sku-item')].filter(li=>((li.querySelector('input.el-input__inner')||{}).value||'').trim());"
             "return String(lis.length);})()")
    try:
        return int(cnt)
    except Exception:
        return -1


def _open_first_modal():
    """打开第一个商品详情弹窗(走[描述图]入口, 实测稳定; [审核商品]在累计会话态下点不开)。"""
    r = "no-btn"
    for _ in range(3):
        ev("(()=>{const sc=[...document.querySelectorAll('*')].find(e=>e.scrollHeight-e.clientHeight>200&&e.clientHeight>150);"
           "if(sc)sc.scrollTop=0;return 'top';})()")
        time.sleep(0.8)
        r = ev("(()=>{" + JS_CLICK + "const vh=innerHeight;const b=[...document.querySelectorAll('button')]"
               ".filter(e=>e.textContent.trim()==='描述图').find(e=>{const t=e.getBoundingClientRect().top;return t>40&&t<vh-40;});"
               "if(!b)return 'no-btn';b.scrollIntoView({block:'center'});rclick(b);return 'opened';})()")
        if r == "opened" and _wait_review_dialog(6):
            return True
        time.sleep(0.6)
    return False


def _modal_name():
    return ev("(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();"
              "const i=dlg?dlg.querySelector('input.el-input__inner'):null;return i?i.value.slice(0,30):'';})()")


def _wait_modal_ready(tries=12):
    """弹窗刚打开时内容/导航按钮要等加载好(否则名字读空、上一个/下一个误判禁用)。"""
    for _ in range(tries):
        ok = ev("(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();"
                "if(!dlg)return '0';const nav=[...dlg.querySelectorAll('button')].some(b=>/上一个|下一个/.test(b.textContent));"
                "return nav?'1':'0';})()")
        if ok == "1":
            return True
        time.sleep(0.6)
    return False


def _prev_disabled():
    return ev("(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();if(!dlg)return'1';"
              "const b=[...dlg.querySelectorAll('button')].find(e=>/上一个/.test(e.textContent));"
              "return (!b||b.disabled||/is-disabled|disabled/.test(b.className))?'1':'0';})()") == "1"


def _prev_disabled_stable():
    """连续两次确认[上一个]禁用(规避加载瞬间误判)。"""
    if not _prev_disabled():
        return False
    time.sleep(0.7)
    return _prev_disabled()


def _goto_first():
    """在弹窗内狂点[上一个]直到【稳定】禁用 → 定位到真正第1个商品(上一个会懒加载, 能退到顶)。"""
    _wait_modal_ready()
    time.sleep(0.6)
    for _ in range(80):
        if _prev_disabled_stable():
            return True
        ev("(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();"
           "const b=[...dlg.querySelectorAll('button')].find(e=>/上一个/.test(e.textContent));if(b)b.click();return'p';})()")
        time.sleep(1.0)
    return _prev_disabled()


def _next_state():
    return evj("(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();"
               "if(!dlg)return JSON.stringify({has:false,dis:true});"
               "const b=[...dlg.querySelectorAll('button')].find(e=>/下一个/.test(e.textContent));"
               "return JSON.stringify({has:!!b,dis:b?(b.disabled||/is-disabled|disabled/.test(b.className)):true})})()")


def _next_product():
    """点弹窗[下一个], 返回 True=已切到下一个, False=已是最后一个(二次确认禁用, 防加载瞬间误判早停)。"""
    nx = _next_state()
    if not nx["has"] or nx["dis"]:
        time.sleep(0.8)                 # 可能是加载中瞬时禁用, 等一下再确认
        nx = _next_state()
        if not nx["has"] or nx["dis"]:
            return False
    ev("(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();"
       "const b=[...dlg.querySelectorAll('button')].find(e=>/下一个/.test(e.textContent));if(b)b.click();return 'next';})()")
    time.sleep(1.8)
    return True


def step_skucheck(threshold=100, max_products=200):
    """逐商品: 切SKU信息tab → 数适用型号行数。报出 > threshold 的商品序号。"""
    print(f"逐商品数[适用型号]行数, 报型号数 > {threshold} 的商品...")
    if not _open_first_modal():
        print("⛔ 商品详情弹窗未打开(描述图入口失效), 请确认已抓取成功且列表有商品。")
        return []
    _goto_first()   # 倒回真正第1个, 避免从中途开始漏前面的商品
    out = []
    for idx in range(1, max_products + 1):
        if not _review_dialog_open():
            print("  弹窗意外关闭, 停止。")
            break
        _switch_sku_tab()
        n = _count_models()
        name = _modal_name()
        flag = "  ⬅ 适用型号 > %d" % threshold if n > threshold else ""
        print(f"  #{idx} 适用型号 {n} 个 | {name}{flag}")
        out.append({"idx": idx, "models": n, "name": name})
        if not _next_product():
            print("  已到最后一个商品。")
            break
    _close_review_modal()
    hits = [o for o in out if o["models"] > threshold]
    print("\n================ 结果 ================")
    print(f"共检查 {len(out)} 个商品。适用型号 > {threshold} 的商品:")
    if hits:
        for h in hits:
            print(f"  ▶ 第 {h['idx']} 个商品 —— {h['models']} 个适用型号  ({h['name']})")
        print("\n序号汇总: " + ", ".join("第%d个" % h["idx"] for h in hits))
    else:
        print("  (无)")
    return out


# ---------------- 扫描/修复: 型号值超长(规格长度不能超过40字) ----------------
def _all_model_values():
    """当前弹窗(已在SKU信息tab): 返回[适用型号]区所有行的 {i, v(值), len(字符数)}。
    i 是该行在型号区 sku-item 列表中的下标(用于回写时定位)。"""
    return evj("(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();if(!dlg)return'[]';"
               "const ml=[...dlg.querySelectorAll('*')].find(e=>e.childElementCount===0&&/^适用型号/.test((e.textContent||'').trim()));"
               "if(!ml)return'[]';const mt=ml.getBoundingClientRect().top;"
               "const box=[...dlg.querySelectorAll('.sku-type-box')].find(b=>b.getBoundingClientRect().top>=mt-30);if(!box)return'[]';"
               "const lis=[...box.querySelectorAll('li.sku-item')];const out=[];"
               "lis.forEach((li,i)=>{const inp=li.querySelector('input.el-input__inner');const v=inp?(inp.value||''):'';"
               "if(v.trim())out.push({i,v,len:[...v].length})});return JSON.stringify(out)})()")


def _set_model_value(i, newv):
    """把型号区第 i 个 sku-item 的输入框值改成 newv(原生 setter + input/change/blur 持久化)。"""
    code = ("(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();if(!dlg)return'nodlg';"
            "const ml=[...dlg.querySelectorAll('*')].find(e=>e.childElementCount===0&&/^适用型号/.test((e.textContent||'').trim()));"
            "if(!ml)return'no-ml';const mt=ml.getBoundingClientRect().top;"
            "const box=[...dlg.querySelectorAll('.sku-type-box')].find(b=>b.getBoundingClientRect().top>=mt-30);if(!box)return'no-box';"
            "const li=[...box.querySelectorAll('li.sku-item')][" + str(i) + "];if(!li)return'no-li';"
            "const inp=li.querySelector('input.el-input__inner');if(!inp)return'no-inp';"
            "const nv=" + json.dumps(newv, ensure_ascii=False) + ";"
            "const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;s.call(inp,nv);"
            "for(const e of['input','change','blur'])inp.dispatchEvent(new Event(e,{bubbles:true}));"
            "return inp.value;})()")
    return ev(code)


def step_scanlong(limit=40, max_products=200):
    """逐商品扫描[适用型号]区, 报出字符数 > limit 的型号值(只读, 不改)。"""
    print(f"逐商品扫描型号值, 报字符数 > {limit} 的(会触发'规格长度不能超过{limit}字')...")
    if not _open_first_modal():
        print("⛔ 商品详情弹窗未打开。")
        return []
    _goto_first()   # 倒回真正第1个
    out, visited = [], 0
    for idx in range(1, max_products + 1):
        if not _review_dialog_open():
            break
        _switch_sku_tab()
        name = _modal_name()
        vals = _all_model_values()
        longs = [v for v in vals if v["len"] > limit]
        if longs:
            print(f"\n  #{idx} {name} —— {len(longs)} 个超长型号:")
            for v in longs:
                print(f"      [{v['len']}字] {v['v']}")
            out.append({"idx": idx, "name": name, "longs": longs})
        visited = idx
        if not _next_product():
            break
    _close_review_modal()
    print(f"\n================ 扫描结果 (共遍历 {visited} 个商品) ================")
    if out:
        print(f"{len(out)} 个商品有超长型号:")
        for o in out:
            print(f"  第{o['idx']}个 {o['name']}: {len(o['longs'])}个")
    else:
        print(f"  没有任何型号超过 {limit} 字符。")
    return out


# 精确替换表: 原超长型号值 -> 修复后(≤40字, 仅去重复品牌前缀, 不改机型核心值)。
# 不在表内的超长值只报告、不乱截, 避免误删核心机型。
FIXMAP = {
    "华为nova12pro/华为nova12Ultra星耀版,华为nova12Ultra":
        "华为nova12pro/nova12Ultra星耀版,nova12Ultra",
    "华为PURA70PRO/华PURA70PROPLUS,华为P70PRO/华为P70PROPLUS":
        "华为PURA70PRO/PURA70PRO+,P70PRO/P70PRO+",
}


def step_fixlong(limit=40, max_products=200):
    """逐商品: 把[适用型号]区超长(>limit)且在 FIXMAP 内的型号值改成短版, 即时复验。
    不在 FIXMAP 内的超长值只报告不改。"""
    for k, v in FIXMAP.items():
        assert len([*v]) <= limit, f"FIXMAP 修复值仍超长: {v}"
    print(f"逐商品修复超长型号(目标 ≤{limit}字, 仅去重复品牌前缀)...")
    if not _open_first_modal():
        print("⛔ 商品详情弹窗未打开。")
        return []
    _goto_first()   # 倒回真正第1个, 确保覆盖全部商品
    fixed, skipped, unknown = [], [], []
    for idx in range(1, max_products + 1):
        if not _review_dialog_open():
            break
        _switch_sku_tab()
        name = _modal_name()
        vals = _all_model_values()
        longs = [v for v in vals if v["len"] > limit]
        for lv in longs:
            new = FIXMAP.get(lv["v"])
            if not new:
                print(f"  #{idx} {name}: ⚠️ 超长但不在修复表, 跳过 -> [{lv['len']}字] {lv['v']}")
                unknown.append({"idx": idx, "v": lv["v"]})
                continue
            res = _set_model_value(lv["i"], new)
            time.sleep(0.4)
            # 复验: 重新读该行长度
            again = _all_model_values()
            row = next((r for r in again if r["i"] == lv["i"]), None)
            ok = row is not None and row["len"] <= limit and row["v"] == new
            print(f"  #{idx} {name}: {'✓' if ok else '✗'} [{lv['len']}→{row['len'] if row else '?'}字] {new}")
            (fixed if ok else skipped).append({"idx": idx, "name": name, "from": lv["v"], "to": new, "ok": ok})
        if not _next_product():
            break
    _close_review_modal()
    print("\n================ 修复结果 ================")
    print(f"成功修复 {len(fixed)} 个; 失败 {len(skipped)} 个; 不在修复表 {len(unknown)} 个。")
    if skipped:
        print("  ⚠️ 以下未改成功(请人工核查):")
        for s in skipped:
            print(f"     第{s['idx']}个 {s['name']}")
    return fixed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["grab", "skucheck", "run", "scanlong", "fixlong"])
    ap.add_argument("--gt", type=int, default=100, help="适用型号数阈值(报 > 此值的商品, 默认100)")
    ap.add_argument("--limit", type=int, default=40, help="型号字符上限(默认40)")
    a = ap.parse_args()
    if a.step == "grab":
        step_grab_clickonly()
    elif a.step == "skucheck":
        step_skucheck(a.gt)
    elif a.step == "scanlong":
        step_scanlong(a.limit)
    elif a.step == "fixlong":
        step_fixlong(a.limit)
    elif a.step == "run":
        r = step_grab_clickonly()
        if r and r.get("ok") not in (None, "0"):
            step_skucheck(a.gt)
        else:
            print("抓取无成功商品, 不做SKU检查。")


if __name__ == "__main__":
    main()
