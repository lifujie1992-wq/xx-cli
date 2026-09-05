#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1688 -> 视频号小店 批量搬家 (智能店长 sphxd.jiancent.com / 链接复制)

固化流程(每批 <=50 个链接):
  1) 填链接 -> 开始批量抓取商品
  2) 批量设置小店分类 = 手机通讯>手机配件>手机壳/保护套 (应用所有)
  3) 标题删词: 删除 代发/一件代发/工厂直销/厂家直销/1688 等词
  4) 描述图: 逐商品打开, OCR 判断并删除"购买须知/买家须知"类图片
  4.6) 必填补填: 走查每个商品[审核商品]弹窗(列表徽标漏报依赖属性,不可信),
       逐个补 适用品牌=苹果/Apple + 工艺=其他(已填跳过); autobatch 据此停在搬家前
  5) (可选) 下一步: 开始搬家

每一步都是独立子命令, 可单独跑, 方便调试与断点续跑。

依赖:
  - OpenBridge 守护进程 (127.0.0.1:10088) + Chrome 已登录 sphxd.jiancent.com
  - tesseract (chi_sim) 用于描述图 OCR  (见 ocrjudge.py)

用法:
  python3 sphxd_move.py grab --batch 0          # 第 0 批 50 个链接 -> 抓取
  python3 sphxd_move.py category                # 批量设类目
  python3 sphxd_move.py titles                  # 标题删词
  python3 sphxd_move.py descimg                 # 描述图清理(OCR)
  python3 sphxd_move.py move                     # 点"下一步:开始搬家"
  python3 sphxd_move.py process --batch 0        # 2~4 步一条龙(不含抓取/搬家)
"""
import sys, os, json, re, time, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ocrjudge

SESSION = "sphxd-move"

from openbridge_client import OpenBridgeClient

BRIDGE = OpenBridgeClient(SESSION)
LINK_PAGE_URL = "https://sphxd.jiancent.com/copy/move?copyType=linksCopy"  # 链接复制工作台(grab 自动导航到这里)
LINKS_JSON = os.path.join(HERE, "data", "links.json")
DONE_JSON = os.path.join(HERE, "data", "done.json")        # 已搬成功的 offer id(自动落账)
CURRENT_JSON = os.path.join(HERE, "data", "current_batch.json")  # 本批链接暂存
BATCH_SIZE = 50


def _offer_id(u):
    m = re.search(r"/offer/(\d+)", u)
    return m.group(1) if m else u


def _load_done():
    """已复制记录表(done.json): 统一为 1688 链接口径, 返回链接列表。"""
    return json.load(open(DONE_JSON)) if os.path.exists(DONE_JSON) else []


def _done_ids():
    """已复制的归一化去重键(offer id 集合, 防链接参数差异)。"""
    return {_offer_id(u) for u in _load_done()}


def _mark_done(links):
    """把本批链接并入 done.json(按 offer id 去重)。"""
    cur = _load_done()
    seen = {_offer_id(u) for u in cur}
    for u in links:
        if _offer_id(u) not in seen:
            cur.append(u)
            seen.add(_offer_id(u))
    json.dump(sorted(cur), open(DONE_JSON, "w"), ensure_ascii=False, indent=0)
    print(f"  ✓ 已落账, done.json 累计 {len(seen)} 个已复制链接")


def _pending_links():
    """links.json 排除已复制(done.json, 按链接/offer id)后的待搬链接。跑前必读此表。"""
    links = json.load(open(LINKS_JSON))
    done = _done_ids()
    pend = [u for u in links if _offer_id(u) not in done]
    print(f"[去重] 已复制记录表 done.json: {len(done)} 个; links.json: {len(links)} 个; 排除后待搬: {len(pend)} 个")
    return pend

TARGET_CATEGORY = "手机通讯>手机配件>手机壳/保护套"
# 标题删词表(可按需增删)。出现即从标题中删除。
TITLE_BAD_WORDS = ["一件代发", "代发", "工厂直销", "厂家直销", "源头工厂", "外贸", "跨境", "批发", "亚马逊", "1688"]


# ---------------- OpenBridge 封装 ----------------
def cmd(action, args=None):
    return BRIDGE.call(action, args)


def ev(code):
    """evaluate JS, 返回其字符串结果(JS 里请 return JSON.stringify(...))。"""
    return cmd("evaluate", {"code": code}).get("value")


def evj(code):
    return json.loads(ev(code))


def navigate(url, new_tab=False):
    return cmd("navigate", {"url": url, "newTab": new_tab, "groupTitle": "1688商品搬家"})


# ---------------- 通用 JS 片段 ----------------
# deep: 穿透 shadow DOM 的 querySelectorAll
JS_DEEP = ("function deep(s,r=document,a=[]){for(const e of r.querySelectorAll('*')){"
           "if(e.matches(s))a.push(e);if(e.shadowRoot)deep(s,e.shadowRoot,a)}return a}")
# React/Vue 受控输入回填
JS_SETV = ("function setv(el,v){const p=el.tagName==='TEXTAREA'?HTMLTextAreaElement:HTMLInputElement;"
           "const s=Object.getOwnPropertyDescriptor(p.prototype,'value').set;s.call(el,v);"
           "el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));}")
# 派发完整鼠标点击序列(用于自定义控件)
JS_CLICK = ("function rclick(el){const r=el.getBoundingClientRect();const o={bubbles:true,cancelable:true,"
            "clientX:r.x+r.width/2,clientY:r.y+r.height/2,view:window};"
            "for(const t of['pointerdown','mousedown','pointerup','mouseup','click'])"
            "el.dispatchEvent(new(t.startsWith('pointer')?PointerEvent:MouseEvent)(t,o));}")


# ---------------- 步骤 1: 填链接 + 抓取 ----------------
def _on_link_page():
    chk = ("(()=>{const ta=document.querySelector('textarea.el-textarea__inner');"
           "const g=[...document.querySelectorAll('button')].some(e=>e.textContent.trim()==='开始批量抓取商品');"
           "return JSON.stringify({ok:!!ta&&g})})()")
    return json.loads(ev(chk)).get("ok")


def ensure_on_link_page():
    """确保停在链接复制工作台(链接框+开始批量抓取按钮); 不在就自动导航过去。"""
    if _on_link_page():
        return
    print(f"  导航到链接复制工作台: {LINK_PAGE_URL}")
    navigate(LINK_PAGE_URL, new_tab=False)
    time.sleep(5)
    if not _on_link_page():
        raise RuntimeError("进不去链接复制工作台: " + LINK_PAGE_URL)


def step_grab(batch_idx, size=BATCH_SIZE):
    ensure_on_link_page()      # 自动导航到链接复制页, 不靠手动/记忆
    links = _pending_links()   # 已自动排除 done.json 里搬过的
    chunk = links[batch_idx * size:(batch_idx + 1) * size]
    if not chunk:
        print(f"批次 {batch_idx} 无链接(待搬 {len(links)} 条已取完)。")
        return
    json.dump(chunk, open(CURRENT_JSON, "w"), ensure_ascii=False)  # 暂存本批链接,move 成功后落账
    val = "\n".join(chunk)
    print(f"批次 {batch_idx}: 待搬 {len(links)} 条, 本批填入 {len(chunk)} 个链接...")
    code = ("(()=>{const ta=document.querySelector('textarea.el-textarea__inner');if(!ta)return 'no-ta';"
            + JS_SETV + "setv(ta," + json.dumps(val) + ");return JSON.stringify({lines:ta.value.split('\\n').length})})()")
    print("  ", ev(code))
    # 点开始批量抓取
    ev("(()=>{const b=[...document.querySelectorAll('button')].find(e=>e.textContent.trim()==='开始批量抓取商品');"
       "if(!b)return 'no-btn';b.click();return 'clicked'})()")
    print("  已点击[开始批量抓取商品], 等待抓取完成...")
    # 轮询直到进入商品列表(出现 '抓取成功' 文案)
    for _ in range(120):
        time.sleep(3)
        st = ev("(()=>{const t=document.body.innerText;const m=t.match(/抓取成功\\s*(\\d+)\\s*个/);"
                "const s=t.match(/跳过复制\\s*(\\d+)\\s*个/);return JSON.stringify({ok:m?m[1]:null,skip:s?s[1]:null})})()")
        d = json.loads(st)
        if d.get("ok") is not None:
            print(f"  抓取完成: 成功 {d['ok']} 个, 跳过 {d.get('skip')} 个")
            return d
    print("  ⚠️ 等待超时, 请人工检查页面")
    return None


# ---------------- 步骤 2: 批量设类目 ----------------
def step_category():
    print("批量设置小店分类 ->", TARGET_CATEGORY)
    # 打开 批量[设置小店分类]
    r = ev("(()=>{const b=[...document.querySelectorAll('button')].find(e=>e.textContent.trim()==='设置小店分类');"
           "if(!b)return 'no-btn';b.click();return 'opened'})()")
    if r != "opened":
        raise RuntimeError("找不到[设置小店分类]按钮")
    time.sleep(1.5)
    # 展开自定义下拉
    ev("(()=>{const box=[...document.querySelectorAll('.el-dialog')].find(d=>/选择发布商品类目/.test(d.textContent));"
       "const sel=box.querySelector('.pro-filter-select');" + JS_CLICK + "rclick(sel);return 'open-dd'})()")
    time.sleep(1.2)
    # 搜索关键字
    ev("(()=>{const inp=[...document.querySelectorAll('input')].find(e=>e.placeholder==='输入关键字搜索');"
       "if(!inp)return 'no';" + JS_SETV + "setv(inp,'手机壳');return 'searched'})()")
    time.sleep(1.5)
    # 选中目标类目
    r = ev("(()=>{const opt=[...document.querySelectorAll('li,div,p,span')].find(e=>e.textContent.trim()==="
           + json.dumps(TARGET_CATEGORY) + "&&e.childElementCount===0);if(!opt)return 'no-opt';"
           + JS_CLICK + "rclick(opt);return 'selected'})()")
    if r != "selected":
        raise RuntimeError("下拉里找不到目标类目: " + TARGET_CATEGORY)
    time.sleep(1)
    # 应用所有
    ev("(()=>{const box=[...document.querySelectorAll('.el-dialog')].find(d=>/选择发布商品类目/.test(d.textContent));"
       "const b=[...box.querySelectorAll('button')].find(e=>e.textContent.trim()==='应用所有');b.click();return 'applied'})()")
    time.sleep(2)
    print("  已[应用所有]")


# ---------------- 步骤 3: 标题删词 ----------------
def _scroll_load_all():
    """商品列表是懒加载追加: 滚到底直到数量稳定, 让所有商品的标题框都进 DOM。"""
    cnt = ("[...document.querySelectorAll('.el-input__inner')].filter(e=>e.placeholder==='请输入'"
           "&&/[\\u4e00-\\u9fa5]/.test(e.value)).length")
    last = -1
    for _ in range(40):
        n = evj("(()=>{const sc=[...document.querySelectorAll('*')].find(e=>e.scrollHeight-e.clientHeight>200&&e.clientHeight>150);"
                "if(sc)sc.scrollTop=sc.scrollHeight;return JSON.stringify(" + cnt + ")})()")
        if n == last:
            break
        last = n
        time.sleep(0.8)
    return last


def step_titles():
    print("标题删词:", TITLE_BAD_WORDS)
    n = _scroll_load_all()
    print(f"  懒加载到底, 标题框 {n} 个")
    code = ("(()=>{const words=" + json.dumps(TITLE_BAD_WORDS, ensure_ascii=False) + ";" + JS_SETV +
            "const hasCJK=s=>/[\\u4e00-\\u9fa5]/.test(s);"
            # 标题输入框: placeholder=请输入 且 值含中文(排除隐藏 token 框/售价/类目/时间)
            "const ins=[...document.querySelectorAll('input.el-input__inner')].filter(e=>e.placeholder==='请输入'&&hasCJK(e.value)&&e.value.length>6);"
            "let changed=0;const samples=[];"
            "for(const t of ins){let v=t.value;const o=v;for(const w of words){v=v.split(w).join('')}"
            "v=v.replace(/\\s+/g,' ').trim();if(v!==o){setv(t,v);changed++;if(samples.length<5)samples.push({from:o,to:v})}}"
            "return JSON.stringify({total:ins.length,changed,samples})})()")
    d = evj(code)
    print(f"  标题框 {d['total']} 个, 删词改动 {d['changed']} 个")
    for s in d["samples"]:
        print("   -", s["from"], "=>", s["to"])
    return d


# ---------------- 步骤 4: 描述图清理(OCR) ----------------
def _open_descimg_first():
    """点第一个商品的[描述图]按钮打开弹窗, 并启用批量。"""
    ev("(()=>{const b=[...document.querySelectorAll('button')].find(e=>e.textContent.trim()==='描述图');"
       "if(!b)return 'no';b.click();return 'ok'})()")
    time.sleep(2.5)
    # 启用批量(若当前是"启用批量"而非"关闭批量")
    ev("(()=>{const el=[...document.querySelectorAll('.el-dialog .el-checkbox,.el-dialog span')]"
       ".find(e=>e.textContent.trim()==='启用批量');if(el){(el.closest('.el-checkbox')||el).click();return 'enabled'}return 'already'})()")
    time.sleep(1)


def _desc_current_srcs():
    """读取当前商品所有描述图 src(完整 url), 按显示顺序。"""
    return evj("(()=>{const items=[...document.querySelectorAll('.img-item')];"
               "return JSON.stringify(items.map(it=>{const im=it.querySelector('img.el-image__inner');return im?im.src:''}))})()")


def _ensure_batch_on():
    """确保描述图弹窗处于"批量"模式(勾选框可见)。切换商品后该状态会被重置, 故每次删前都要确认。"""
    st = evj("(()=>{const en=[...document.querySelectorAll('.el-dialog span,.el-dialog .el-checkbox')]"
             ".find(e=>e.textContent.trim()==='启用批量');"
             "if(en){(en.closest('.el-checkbox')||en).click();return JSON.stringify({did:'enabled'})}"
             "return JSON.stringify({did:'already'})})()")
    if st.get("did") == "enabled":
        time.sleep(0.8)


def _desc_delete_indices(indices):
    """勾选给定下标的描述图并批量删除+确认。返回删除前后图片数。"""
    _ensure_batch_on()
    code = ("(()=>{const idx=" + json.dumps(indices) + ";const items=[...document.querySelectorAll('.img-item')];"
            "const allcb=[...document.querySelectorAll('.el-dialog .el-checkbox')].filter(c=>{const r=c.getBoundingClientRect();return r.width>=18&&r.width<=22});"
            "function cbFor(it){const r=it.getBoundingClientRect();return allcb.find(c=>{const cr=c.getBoundingClientRect();"
            "return cr.x>=r.x&&cr.x<=r.x+r.width&&Math.abs(cr.y-r.y)<60})}"
            "let n=0;for(const i of idx){const it=items[i];if(!it)continue;const cb=cbFor(it);if(cb){cb.click();n++}}"
            "return JSON.stringify({before:items.length,checked:n})})()")
    d = evj(code)
    if d["checked"] == 0:
        return d
    time.sleep(0.8)
    # 点 批量删除(N)
    ev("(()=>{const b=[...document.querySelectorAll('.el-dialog button')].find(e=>/^批量删除/.test(e.textContent.trim()));"
       "if(b)b.click();return 'del'})()")
    time.sleep(1.2)
    # 确认弹窗 确定
    ev("(()=>{const box=[...document.querySelectorAll('.el-message-box,.el-dialog')].find(d=>/确定要删除/.test(d.textContent));"
       "if(!box)return 'no-confirm';const b=[...box.querySelectorAll('button')].find(e=>e.textContent.trim()==='确定');"
       "if(b)b.click();return 'confirmed'})()")
    time.sleep(1.5)
    d["after"] = evj("(()=>JSON.stringify([...document.querySelectorAll('.img-item')].length))()")
    return d


def _desc_has_next():
    return evj("(()=>{const b=[...document.querySelectorAll('.el-dialog button')].find(e=>/下一个/.test(e.textContent));"
               "return JSON.stringify({exists:!!b,disabled:b?b.disabled||/is-disabled/.test(b.className):true})})()")


def _desc_next():
    ev("(()=>{const b=[...document.querySelectorAll('.el-dialog button')].find(e=>/下一个/.test(e.textContent));"
       "if(b)b.click();return 'next'})()")
    time.sleep(2)


def _desc_close():
    ev("(()=>{const b=[...document.querySelectorAll('.el-dialog button')].find(e=>e.textContent.trim()==='关闭');"
       "if(b)b.click();return 'closed'})()")
    time.sleep(1)


def step_descimg(max_products=200):
    """逐商品处理描述图: OCR 判断须知图并删除。在描述图弹窗内用[下一个]切换。"""
    print("描述图清理(OCR 判断购买须知/买家须知)...")
    _open_descimg_first()
    total_deleted = 0
    for pi in range(max_products):
        srcs = _desc_current_srcs()
        srcs = [s for s in srcs if s]
        if not srcs:
            print(f"  商品#{pi+1}: 无描述图")
        else:
            res = ocrjudge.judge_urls(srcs)
            notice_idx = [i for (i, u, isn, ex_) in res if isn]
            if notice_idx:
                d = _desc_delete_indices(notice_idx)
                total_deleted += d.get("checked", 0)
                print(f"  商品#{pi+1}: {len(srcs)}图, 删除违规图(须知/工厂/报价) {notice_idx} -> {d.get('before')}→{d.get('after')}")
            else:
                print(f"  商品#{pi+1}: {len(srcs)}图, 无可删图")
        nx = _desc_has_next()
        if not nx["exists"] or nx["disabled"]:
            print("  已到最后一个商品。")
            break
        _desc_next()
    _desc_close()
    print(f"描述图清理完成, 共删除 {total_deleted} 张须知图。")


# ---------------- 步骤 4.5: 必填缺失检查(商品信息 tab) ----------------
def step_check_required():
    """处理完描述图后, 切回[商品信息]tab, 扫描列表里每行"N个必填(属性|资质)为空"徽标,
    报出缺必填的商品(标题)。其实列表就能看出来, 无需逐个点进商品。
    返回缺失商品列表; autobatch 据此决定是否停在搬家前(避免点搬家被弹窗拦)。"""
    print("必填缺失检查(切回[商品信息]tab, 扫列表徽标)...")
    # 描述图处理后当前视图可能停在[描述图]tab, 先切回[商品信息]tab
    r = ev("(()=>{" + JS_CLICK +
           "const b=[...document.querySelectorAll('.tool-list button,button')]"
           ".find(e=>e.textContent.trim()==='商品信息');"
           "if(!b)return 'no-tab';rclick(b);return 'switched'})()")
    print("   切换商品信息 tab:", r)
    time.sleep(1.5)
    _scroll_load_all()   # 懒加载到底, 确保所有行的徽标都进 DOM
    # 行内徽标: "1个必填属性为空，请审核商品核实" / "...必填资质为空..."
    code = ("(()=>{const re=/(\\d+)个必填(属性|资质)为空/;"
            "const badges=[...document.querySelectorAll('div,span')].filter(e=>e.childElementCount===0&&re.test(e.textContent||''));"
            "const out=badges.map(b=>{let row=b;for(let k=0;k<12&&row;k++){"
            "const ti=row.querySelector&&row.querySelector('input.el-input__inner');"
            "if(ti&&ti.placeholder==='请输入'&&/[\\u4e00-\\u9fa5]/.test(ti.value))"
            "return{badge:b.textContent.trim(),title:ti.value.slice(0,30)};row=row.parentElement;}"
            "return{badge:b.textContent.trim(),title:null};});"
            "return JSON.stringify(out)})()")
    items = evj(code)
    if items:
        print(f"  ⚠️ {len(items)} 个商品缺必填(需人工补填后才能搬家成功):")
        for it in items:
            print(f"     - {it['title']}  [{it['badge']}]")
    else:
        print("  ✓ 无必填缺失, 可继续搬家")
    return items


# ---------------- 步骤 4.6: 深检并补填必填属性(适用品牌/工艺) ----------------
# 为什么走查每个商品弹窗而不信列表徽标:
#   列表行内"N个必填属性为空"徽标【严重漏报】依赖属性——[工艺]依赖[适用品牌],
#   品牌没填时工艺显示"请选择适用品牌后选择"(锁定),徽标根本不算它; 且很多商品
#   品牌本身就空却没被标记。所以唯一可靠口径=进每个商品[审核商品]弹窗逐项读。
# 填什么:
#   适用品牌 = brand(本店全苹果机型, 默认 苹果/Apple; 该下拉无"其他"选项)
#   工艺     = 其他(下拉里有"其他"; 工艺必须在适用品牌填好后才可选)
# 不点行内[应用](=应用到所有, 会覆盖其余商品已填的值)。选完即时生效, 无需保存。
DEFAULT_BRAND = "苹果/Apple"
REQUIRED_ATTRS = [("适用品牌", None), ("工艺", "其他")]  # value=None 表示用 brand

# SKU[适用型号]里"留言备注类"型号特征(这类不是真实机型, 是让买家留言下单的占位): 命中即删该型号行。
SKU_MODEL_BADPAT = "留言|备注|咨询|客服|联系|下单留言|其它型号下单|其他型号下单|看备注|拍前|默认"


def _clean_sku_models():
    """当前模态: 切[SKU信息]tab → [适用型号]区删掉留言备注类型号行 → 返回 {models, deleted, empty}。
    结构(实测): 适用型号区 .sku-type-box > ul.sku-list > li.sku-item; 型号名=li 内 input.el-input__inner 值;
    删除按钮=li 内 button.J_skuInfoDeleteItem。empty=True 表示型号区(删完后)为空→该商品应整体删除。"""
    # 切 SKU信息 tab
    ev("(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();if(!dlg)return'x';" + JS_CLICK +
       "const t=[...dlg.querySelectorAll('.el-tabs__item,[role=tab]')].find(e=>/^SKU信息/.test(e.textContent.trim()));if(t)rclick(t);return't';})()")
    time.sleep(1.2)
    # 循环: 找型号区第一个留言备注型号行→点其删除→直到没有; 再回报型号总数
    deleted = 0
    for _ in range(30):
        r = ev("(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();if(!dlg)return'nodlg';" + JS_CLICK +
               "const ml=[...dlg.querySelectorAll('*')].find(e=>e.childElementCount===0&&/^适用型号/.test((e.textContent||'').trim()));"
               "if(!ml)return'no-model-section';const mt=ml.getBoundingClientRect().top;"
               "const box=[...dlg.querySelectorAll('.sku-type-box')].find(b=>b.getBoundingClientRect().top>=mt-30);if(!box)return'no-box';"
               "const bad=" + json.dumps(SKU_MODEL_BADPAT) + ";const re=new RegExp(bad);"
               "const li=[...box.querySelectorAll('li.sku-item')].find(li=>{const v=((li.querySelector('input.el-input__inner')||{}).value||'').trim();return re.test(v);});"
               "if(!li)return'done';const del=li.querySelector('button.J_skuInfoDeleteItem');if(!del)return'no-del';"
               "li.scrollIntoView({block:'center'});rclick(del);return'deleted';})()")
        if r == "deleted":
            deleted += 1
            time.sleep(1.0)
            # ‼️ 删规格后必弹确认框: .el-dialog.pro-message-box 文本"删除该规格...请慎重", 点[确定]才真删
            for _ in range(3):
                c = ev("(()=>{const box=[...document.querySelectorAll('.el-dialog')]"
                       ".filter(d=>d.offsetParent&&/删除该规格|请慎重/.test(d.textContent)).pop();"
                       "if(!box)return 'no-confirm';const b=[...box.querySelectorAll('button')]"
                       ".find(e=>e.textContent.trim()==='确定');if(!b)return 'no-ok';b.click();return 'confirmed';})()")
                if c == "confirmed":
                    break
                time.sleep(0.6)
            time.sleep(0.8)
            continue
        break
    # 统计型号区剩余行数
    cnt = ev("(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();if(!dlg)return'-1';"
             "const ml=[...dlg.querySelectorAll('*')].find(e=>e.childElementCount===0&&/^适用型号/.test((e.textContent||'').trim()));"
             "if(!ml)return'-1';const mt=ml.getBoundingClientRect().top;"
             "const box=[...dlg.querySelectorAll('.sku-type-box')].find(b=>b.getBoundingClientRect().top>=mt-30);if(!box)return'0';"
             "const lis=[...box.querySelectorAll('li.sku-item')].filter(li=>((li.querySelector('input.el-input__inner')||{}).value||'').trim());"
             "return String(lis.length);})()")
    try:
        models = int(cnt)
    except Exception:
        models = -1
    return {"models": models, "deleted": deleted, "empty": models == 0}


def _close_review_modal():
    ev("(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();"
       "const b=dlg?[...dlg.querySelectorAll('button')].find(e=>e.textContent.trim()==='关闭'):null;"
       "if(b)b.click();return 'closed';})()")
    time.sleep(1.5)


def _attr_value(label):
    """读弹窗内某属性当前显示值: 下拉取 .pro-filter-select 文本(空=请选择), 文本框取 input.value。
    返回 '__NF__'=无此属性行。"""
    return ev("(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();"
              "if(!dlg)return '';const lab=" + json.dumps(label, ensure_ascii=False) + ";"
              "const box=[...dlg.querySelectorAll('.attr-item-box')].find(b=>{const t=(b.textContent||'');"
              "const i=t.indexOf(lab);return i>=0&&i<6});if(!box)return '__NF__';"
              "const sel=box.querySelector('.pro-filter-select');const inp=box.querySelector('input');"
              "let v=sel?sel.textContent.trim():(inp?inp.value:'');return v.replace(/\\s+/g,' ').slice(0,30);})()")


def _attr_is_empty(val):
    if val == "__NF__":
        return False                      # 没这属性 => 不用填
    return ("请选择" in val) or ("请输入" in val) or not val


def _fill_attr(label, value):
    """若 label 必填且空, 打开其下拉选 value。返回 filled / already / skip / err-*。"""
    val = _attr_value(label)
    if val == "__NF__":
        return "skip"
    if not _attr_is_empty(val):
        return "already"
    if "后选择" in val:                    # 仍锁定(依赖项未填), 等一下再读
        time.sleep(1.2)
        val = _attr_value(label)
        if "后选择" in val:
            return "err-locked"
    r = ev("(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();if(!dlg)return 'nodlg';" + JS_CLICK +
           "const lab=" + json.dumps(label, ensure_ascii=False) + ";"
           "const box=[...dlg.querySelectorAll('.attr-item-box')].find(b=>{const t=(b.textContent||'');"
           "const i=t.indexOf(lab);return i>=0&&i<6});if(!box)return 'no-box';"
           "box.scrollIntoView({block:'center'});const sel=box.querySelector('.pro-filter-select');"
           "if(!sel)return 'no-sel';rclick(sel);return 'opened';})()")
    if r != "opened":
        return "err-open"
    time.sleep(0.9)
    p = ev("(()=>{const want=" + json.dumps(value, ensure_ascii=False) + ";" + JS_CLICK +
           "const dd=[...document.querySelectorAll('.pro-filter-dropdown,.el-popper,[class*=dropdown]')]"
           ".filter(d=>d.offsetParent&&d.textContent.indexOf(want)>=0).pop();if(!dd)return 'no-dd';"
           "const opt=[...dd.querySelectorAll('li,div,span,p')].find(e=>e.childElementCount===0&&e.textContent.trim()===want);"
           "if(!opt)return 'no-opt';rclick(opt);return 'picked';})()")
    time.sleep(0.6)
    return "filled" if p == "picked" else "err-" + p


def _review_dialog_open():
    return ev("(()=>JSON.stringify([...document.querySelectorAll('.el-dialog')].some(d=>d.offsetParent)))()") == "true"


def _wait_review_dialog(tries=12):
    for _ in range(tries):
        if _review_dialog_open():
            return True
        time.sleep(0.6)
    return False


def _review_switch_info_tab():
    ev("(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();if(!dlg)return 'nodlg';" + JS_CLICK +
       "const t=[...dlg.querySelectorAll('.el-tabs__item,[role=tab]')].find(e=>/^商品信息/.test(e.textContent.trim()));"
       "if(t)rclick(t);return 't';})()")
    time.sleep(0.6)


def _clean_title_in_modal():
    """弹窗[商品信息]tab 内: 把标题输入框里的 TITLE_BAD_WORDS 去掉。
    ‼️ 标题删词必须在弹窗里改才持久: 列表里 setv 改的只动 DOM, 一重渲染就被原始数据覆盖回去;
       弹窗内改会真正写进数据模型(实测关弹窗后列表同步变干净)。返回 cleaned/clean/no-title。"""
    words = json.dumps(TITLE_BAD_WORDS, ensure_ascii=False)
    return ev("(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();"
              "if(!dlg)return 'nodlg';const words=" + words + ";"
              # 标题唯一锁定: maxLength===60(商品标题限60字), 颜色/型号是-1。别用'第一个长中文input'(会选错到颜色/型号)
              "const t=[...dlg.querySelectorAll('input')].find(e=>e.offsetParent&&e.maxLength===60&&/[\\u4e00-\\u9fa5]/.test(e.value||''));"
              "if(!t)return 'no-title';"
              "let v=t.value,o=v;for(const w of words)v=v.split(w).join('');v=v.replace(/\\s+/g,' ').trim();"
              "if(v===o)return 'clean';const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;"
              "s.call(t,v);for(const e of['input','change','blur'])t.dispatchEvent(new Event(e,{bubbles:true}));"
              "return 'cleaned';})()")


def step_fill_required(brand=DEFAULT_BRAND, max_products=80):
    """走查【所有】抓取商品(弹窗内深检, 不信列表徽标), 每个: 清标题删词 + 补 适用品牌=brand + 工艺=其他。
    用弹窗[下一个]逐个翻; 已填的跳过; 先适用品牌后工艺(工艺依赖前者)。返回逐商品结果。"""
    print(f"深检补填必填属性(适用品牌={brand}, 工艺=其他), 走查全部商品...")
    # 开商品详情弹窗的坑(实测):
    #  - [审核商品]按钮在累计会话态下点不开弹窗(失效); 但[描述图]按钮开的是【同一个】商品
    #    详情弹窗(只是默认停在描述图 tab), 稳定可开。故统一用[描述图]开, 进去切回[商品信息]tab。
    #  - 列表虚拟滚动: 靠前的按钮可能在视口外(y<0)被回收, 必须先滚到顶再点【视口内】第一个。
    r = "no-btn"
    for _ in range(3):
        ev("(()=>{const sc=[...document.querySelectorAll('*')].find(e=>e.scrollHeight-e.clientHeight>200&&e.clientHeight>150);"
           "if(sc)sc.scrollTop=0;return 'top';})()")
        time.sleep(0.8)
        r = ev("(()=>{" + JS_CLICK + "const vh=innerHeight;const b=[...document.querySelectorAll('button')]"
               ".filter(e=>e.textContent.trim()==='描述图').find(e=>{const t=e.getBoundingClientRect().top;return t>40&&t<vh-40;});"
               "if(!b)return 'no-btn';b.scrollIntoView({block:'center'});rclick(b);return 'opened';})()")
        if r == "opened" and _wait_review_dialog(6):
            break
        time.sleep(0.6)
    if r != "opened" or not _review_dialog_open():
        print("  商品详情弹窗未打开(描述图入口), 终止。")
        return []
    _review_switch_info_tab()               # 切一次即可, 翻[下一个]不会跳回描述图tab; 每步都切反而冲掉标题渲染
    out, fixed = [], 0
    for idx in range(1, max_products + 1):
        if not _review_dialog_open():       # 弹窗意外关闭, 兜底重开当前商品不可行, 直接停
            print("  弹窗已关闭, 停止走查。")
            break
        _review_switch_info_tab()           # 商品信息tab
        time.sleep(0.6)
        name = ev("(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();"
                  "const i=dlg?dlg.querySelector('input.el-input__inner'):null;return i?i.value.slice(0,22):'';})()")
        rb = _fill_attr("适用品牌", brand)
        time.sleep(0.5)                    # 给工艺解锁的时间
        rg = _fill_attr("工艺", "其他")
        sku = _clean_sku_models()          # SKU[适用型号]: 删留言备注型号(会切到SKU tab); empty=型号区空→待删商品
        # ‼️ 标题删词放最后: SKU/属性操作会切tab+重渲染冲掉标题编辑, 故清完标题后紧接[下一个], 中间不再有重渲染
        _review_switch_info_tab()           # 从SKU tab切回商品信息tab
        time.sleep(0.8)                     # 等标题渲染好再清, 否则读空值误判clean
        ct = _clean_title_in_modal()
        if ct == "cleaned":                 # 当场复验, 没清干净再补一次
            time.sleep(0.4)
            if "STILLBAD" == ev("(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();"
                                 "const t=[...dlg.querySelectorAll('input')].find(e=>e.offsetParent&&e.maxLength===60);"
                                 "return t&&/跨境|外贸|批发/.test(t.value)?'STILLBAD':'OK';})()"):
                _clean_title_in_modal()
        ok = (rb in ("filled", "already", "skip") and rg in ("filled", "already", "skip")
              and ct in ("cleaned", "clean", "no-title"))
        if "filled" in (rb, rg):
            fixed += 1
        if sku.get("deleted") or sku.get("empty"):
            print(f"  {'✓' if ok else '✗'} #{idx} {name} | 标题:{ct} 品牌:{rb} 工艺:{rg} | SKU型号:剩{sku['models']}个 删留言{sku['deleted']}个{' ⚠️空→待删商品' if sku['empty'] else ''}")
        else:
            print(f"  {'✓' if ok else '✗'} #{idx} {name} | 标题:{ct} 品牌:{rb} 工艺:{rg} | SKU型号{sku['models']}个")
        out.append({"name": name, "title": ct, "brand": rb, "craft": rg, "sku": sku, "ok": ok})
        nx = evj("(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();"
                 "if(!dlg)return JSON.stringify({has:false,dis:true});"
                 "const b=[...dlg.querySelectorAll('button')].find(e=>/下一个/.test(e.textContent));"
                 "return JSON.stringify({has:!!b,dis:b?(b.disabled||/is-disabled|disabled/.test(b.className)):true})})()")
        if not nx["has"] or nx["dis"]:
            break
        ev("(()=>{const dlg=[...document.querySelectorAll('.el-dialog')].filter(d=>d.offsetParent).pop();"
           "const b=[...dlg.querySelectorAll('button')].find(e=>/下一个/.test(e.textContent));if(b)b.click();return 'next';})()")
        time.sleep(1.8)
    _close_review_modal()
    bad = [o for o in out if not o["ok"]]
    sku_del = sum(o["sku"].get("deleted", 0) for o in out if o.get("sku"))
    empties = [o for o in out if o.get("sku", {}).get("empty")]
    print(f"走查 {len(out)} 个商品, 补填 {fixed} 个, 删留言备注型号 {sku_del} 个, 空型号商品 {len(empties)} 个, 异常 {len(bad)} 个。")
    for b in bad:
        print(f"    ⚠️ {b['name']} 适用品牌:{b['brand']} 工艺:{b['craft']}")
    if empties:
        print("  ⚠️ 以下商品[适用型号]为空, 需删除该商品(请人工在列表点[移除], 或确认后我来删):")
        for e in empties:
            print(f"     - {e['name']}")
    return out


# ---------------- 步骤 5: 开始搬家 ----------------
def step_move(confirm=False):
    if not confirm:
        print("⚠️ [开始搬家]是不可逆提交(真实上架)。如确认请加 --confirm。")
        return False
    ev("(()=>{const b=[...document.querySelectorAll('button')].find(e=>/开始搬家/.test(e.textContent));"
       "if(b)b.click();return 'clicked'})()")
    # 轮询等待成功页(提交越多越慢; 商品多时提交可达 1-2 分钟, 故给足 120s)
    for _ in range(60):
        time.sleep(2)
        r = evj("(()=>{const t=document.body.innerText;const m=t.match(/已提交\\s*(\\d+)\\s*个商品搬家/);"
                # 提交完成会跳回链接页(出现[返回继续复制]或链接输入框), 也算成功信号
                "const back=[...document.querySelectorAll('button')].some(e=>e.textContent.trim()==='返回继续复制');"
                "return JSON.stringify({submitted:m?m[1]:null,back})})()")
        if r.get("submitted") or r.get("back"):
            print(f"✅ 搬家已提交{(' '+r['submitted']+' 个商品') if r.get('submitted') else '完成'}")
            if os.path.exists(CURRENT_JSON):   # 自动落账: 本批链接写入 done.json
                _mark_done(json.load(open(CURRENT_JSON)))
                os.remove(CURRENT_JSON)
            return True
    print("⚠️ 未检测到搬家成功提示, 请人工确认")
    return False


def _return_continue():
    """搬家成功页 -> 点[返回继续复制]回到链接输入页。"""
    ev("(()=>{const b=[...document.querySelectorAll('button')].find(e=>e.textContent.trim()==='返回继续复制');"
       "if(b)b.click();return 'ret'})()")
    time.sleep(3)


def step_autobatch(batch_idx, size=BATCH_SIZE):
    """全自动一批: (必要时返回链接页) -> 抓取 -> 类目 -> 标题 -> 描述图 -> 搬家。"""
    onlink = evj("(()=>{const ta=document.querySelector('textarea.el-textarea__inner');"
                 "const grab=[...document.querySelectorAll('button')].some(e=>e.textContent.trim()==='开始批量抓取商品');"
                 "return JSON.stringify({link:!!ta&&grab})})()")
    if not onlink.get("link"):
        print("当前不在链接页, 点[返回继续复制]...")
        _return_continue()
    r = step_grab(batch_idx, size)
    if not r or r.get("ok") in (None, "0"):
        print("抓取无成功商品(可能全部跳过), 停止本批。")
        return False
    step_category()
    step_titles()
    step_descimg()
    results = step_fill_required()       # 深检走查所有商品, 补 适用品牌+工艺
    if not results:                       # 一个都没走查到=入口失效, 不可盲搬(可能漏补必填)
        print(f"⛔ 批次 {batch_idx} 必填走查未执行(详情弹窗入口失效), 已停在搬家前, 不提交。")
        return False
    bad = [r for r in results if not r["ok"]]
    if bad:
        print(f"⛔ 批次 {batch_idx} 有 {len(bad)} 个商品必填补填异常, 已停在搬家前。请人工核实后再 move --confirm。")
        return False
    ok = step_move(confirm=True)
    print(f"批次 {batch_idx} 完成, 搬家{'成功' if ok else '未确认'}。")
    return ok


# ---------------- 编排 ----------------
def step_process(batch_idx):
    """处理已抓取的商品列表: 类目 + 标题 + 描述图(不含抓取与搬家)。"""
    step_category()
    step_titles()
    step_descimg()
    step_fill_required()
    print(f"批次 {batch_idx} 处理完成(类目/标题/描述图/必填补填)。下一步可人工核对后 move。")


def step_run(batch_idx):
    """一条龙: 抓取 -> 设类目 -> 标题删词 -> 描述图清理 (不含搬家)。"""
    r = step_grab(batch_idx)
    if not r or r.get("ok") in (None, "0"):
        print("抓取无成功商品(可能全部跳过), 停止本批。")
        return
    step_category()
    step_titles()
    step_descimg()
    results = step_fill_required()
    bad = [r for r in results if not r["ok"]]
    tip = f"⚠️ {len(bad)} 个补填异常需人工核实" if bad else "必填已补齐"
    print(f"\n批次 {batch_idx} 全部清洗完成({tip})。请人工核对后再 move --confirm 搬家。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["grab", "category", "titles", "descimg", "check", "fillreq", "move", "process", "run", "autobatch"])
    ap.add_argument("--batch", type=int, default=0)
    ap.add_argument("--brand", default=DEFAULT_BRAND, help="补填的适用品牌(默认 苹果/Apple)")
    ap.add_argument("--size", type=int, default=BATCH_SIZE, help="本批链接数(默认50); 一次跑完可设大)")
    ap.add_argument("--confirm", action="store_true")
    a = ap.parse_args()
    if a.step == "grab":
        step_grab(a.batch, a.size)
    elif a.step == "category":
        step_category()
    elif a.step == "titles":
        step_titles()
    elif a.step == "descimg":
        step_descimg()
    elif a.step == "check":
        step_check_required()
    elif a.step == "fillreq":
        step_fill_required(a.brand)
    elif a.step == "move":
        step_move(a.confirm)
    elif a.step == "process":
        step_process(a.batch)
    elif a.step == "run":
        step_run(a.batch)
    elif a.step == "autobatch":
        step_autobatch(a.batch, a.size)


if __name__ == "__main__":
    main()
