#!/usr/bin/env node

import { execFile } from "node:child_process";
import { promisify } from "node:util";
import fs from "node:fs/promises";
import path from "node:path";

const execFileAsync = promisify(execFile);

const cfg = {
  baseToken: "REPLACE_WITH_FEISHU_APP_TOKEN",
  tableID: "tblV47nFb6dhqgrR",
  viewID: "vewuNwuUGQ",
  statusField: "晓风云库状态",
  larkCLI: "~/.npm-global/bin/lark-cli",
  doudianSession: "doudian-business-center",
  xfSession: "doudian-xf-batch",
  relationID: "123456789",
  plugID: "REPLACE_WITH_PLUGIN_ID",
  xfBaseURL: "https://xfdyorder.zzbtool.com/zzb_super_goods_xf/index.html?t=1783143706746",
  stateFile: "~/xx-cli/doudian-business-center/output/xf-cloud-batch-state.jsonl",
};

const args = new Map();
for (let i = 2; i < process.argv.length; i++) {
  const a = process.argv[i];
  if (a.startsWith("--")) {
    const key = a.slice(2);
    const next = process.argv[i + 1];
    if (!next || next.startsWith("--")) args.set(key, "true");
    else args.set(key, process.argv[++i]);
  }
}
const limit = Number(args.get("limit") || 0);
const startOffset = Number(args.get("start-offset") || 0);
const onlyKeyword = args.get("keyword") || "";
const retryGrowthSkipped = args.get("retry-growth-skipped") === "true";
const retryFindTabFailures = args.get("retry-find-tab-failures") === "true";
const retryXFEmpty = args.get("retry-xf-empty") === "true";

cfg.baseToken = args.get("base-token") || cfg.baseToken;
cfg.tableID = args.get("table-id") || cfg.tableID;
cfg.viewID = args.get("view-id") || cfg.viewID;
cfg.statusField = args.get("status-field") || cfg.statusField;
cfg.larkCLI = args.get("lark-cli") || cfg.larkCLI;
cfg.doudianSession = args.get("doudian-session") || cfg.doudianSession;
cfg.xfSession = args.get("xf-session") || cfg.xfSession;
cfg.relationID = args.get("relation-id") || cfg.relationID;
cfg.plugID = args.get("plug-id") || cfg.plugID;
cfg.xfBaseURL = args.get("xf-base-url") || cfg.xfBaseURL;
cfg.stateFile = args.get("state-file") || cfg.stateFile;

function log(...parts) {
  console.error(...parts);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

const openBridgeURL = (process.env.OPENBRIDGE_URL || "http://127.0.0.1:10088").replace(/\/$/, "");
let evaluateSequence = 0;

async function openBridgeCommand(toolName, args = {}, timeoutMs = 90000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${openBridgeURL}/command`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ toolName, args }),
      signal: controller.signal,
    });
    const raw = await response.text();
    let envelope;
    try {
      envelope = JSON.parse(raw);
    } catch {
      throw new Error(`OpenBridge ${toolName} returned non-JSON (HTTP ${response.status}): ${raw.slice(0, 500)}`);
    }
    if (envelope.error) {
      throw new Error(`${envelope.error.code || "OPENBRIDGE_ERROR"}: ${envelope.error.message || toolName}`);
    }
    if (!response.ok) {
      throw new Error(`OpenBridge ${toolName} failed with HTTP ${response.status}`);
    }
    return envelope.data;
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error(`OpenBridge ${toolName} timed out after ${timeoutMs}ms`);
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

async function selectSessionTab(session) {
  const found = await openBridgeCommand("browser_find_tab", { sessionId: session, activate: false });
  if (!found?.tabs?.length) return false;
  await openBridgeCommand("browser_select_tab", { tabId: found.tabs[0].tabId, sessionId: session });
  return true;
}

async function runEvaluate(args) {
  const data = await openBridgeCommand("browser_evaluate", args);
  if (!data?.result || typeof data.result !== "object") {
    throw new Error(`Unexpected OpenBridge browser_evaluate response: ${JSON.stringify(data).slice(0, 500)}`);
  }
  return data.result;
}

async function evaluateOpenBridge(session, expression, timeoutMs = 90000) {
  const key = `__xcli_openbridge_${Date.now()}_${++evaluateSequence}`;
  const wrapped = `(() => {
    const __key = ${JSON.stringify(key)};
    const __pack = value => ({state: "fulfilled", type: value === null ? "object" : typeof value, value: value === undefined ? null : value});
    try {
      const __value = (0, eval)(${JSON.stringify(expression)});
      if (__value && typeof __value.then === "function") {
        globalThis[__key] = {state: "pending", key: __key};
        Promise.resolve(__value).then(
          value => { globalThis[__key] = __pack(value); },
          error => { globalThis[__key] = {state: "rejected", message: String(error && (error.stack || error.message) || error)}; }
        );
        return globalThis[__key];
      }
      return __pack(__value);
    } catch (error) {
      return {state: "rejected", message: String(error && (error.stack || error.message) || error)};
    }
  })()`;
  let state = await runEvaluate({ sessionId: session, expression: wrapped });
  const deadline = Date.now() + timeoutMs;
  while (state.state === "pending") {
    if (Date.now() >= deadline) throw new Error("OpenBridge browser_evaluate timed out waiting for async JavaScript");
    await sleep(50);
    const poll = `(() => {
      const __key = ${JSON.stringify(key)};
      const __value = globalThis[__key];
      if (!__value) return {state: "rejected", message: "async evaluation state was lost"};
      if (__value.state !== "pending") delete globalThis[__key];
      return __value;
    })()`;
    state = await runEvaluate({ sessionId: session, expression: poll });
  }
  if (state.state === "rejected") throw new Error(`OpenBridge JavaScript evaluation failed: ${state.message}`);
  if (state.state !== "fulfilled") throw new Error(`Unknown OpenBridge evaluate state: ${JSON.stringify(state)}`);
  return { type: state.type, value: state.value };
}

async function openbridge(session, action, callArgs = {}) {
  const args = { ...callArgs };
  if (Object.hasOwn(args, "group_title")) {
    args.groupTitle = args.group_title;
    delete args.group_title;
  }

  if (action === "find_tab") {
    if (Object.hasOwn(args, "url")) {
      args.urlContains = args.url;
      delete args.url;
    }
    delete args.active;
    const found = await openBridgeCommand("browser_find_tab", { ...args, activate: false });
    if (!found?.tabs?.length) throw new Error("TAB_NOT_FOUND: OpenBridge found no matching Chrome tab");
    await openBridgeCommand("browser_select_tab", { tabId: found.tabs[0].tabId, sessionId: session });
    return found;
  }

  if (action === "navigate") {
    if (!args.newTab && !(await selectSessionTab(session))) args.newTab = true;
  } else if (!(await selectSessionTab(session))) {
    throw new Error(`TAB_NOT_FOUND: no OpenBridge tab is assigned to session ${session}`);
  }

  if (action === "evaluate") {
    if (typeof args.code !== "string") throw new Error("OpenBridge evaluate requires a string code argument");
    return evaluateOpenBridge(session, args.code);
  }

  args.sessionId = session;
  const toolName = action.startsWith("browser_") ? action : `browser_${action}`;
  return openBridgeCommand(toolName, args);
}

async function evalJSON(session, code) {
  const data = await openbridge(session, "evaluate", { code });
  return JSON.parse(data.value);
}

function extractPlainText(value) {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  if (Array.isArray(value)) {
    return value.map(extractPlainText).join("");
  }
  if (typeof value === "object") {
    if ("text" in value) return String(value.text || "");
    if ("name" in value) return String(value.name || "");
    return Object.values(value).map(extractPlainText).join("");
  }
  return String(value);
}

async function runLark(command, flags) {
  const argv = ["base", command, "--as", "user", "--base-token", cfg.baseToken, "--table-id", cfg.tableID, ...flags];
  const { stdout } = await execFileAsync(cfg.larkCLI, argv, {
    maxBuffer: 1024 * 1024 * 10,
    env: { ...process.env, LARK_CLI_NO_PROXY: "1" },
  });
  const jsonStart = stdout.indexOf("{");
  if (jsonStart < 0) throw new Error(`lark-cli returned non-JSON: ${stdout.slice(0, 500)}`);
  const json = JSON.parse(stdout.slice(jsonStart));
  if (!json.ok) throw new Error(`lark-cli ${command} failed: ${JSON.stringify(json.error || json).slice(0, 500)}`);
  return json.data;
}

async function listRecords() {
  const out = [];
  let offset = startOffset;
  while (true) {
    const data = await runLark("+record-list", [
      "--view-id",
      cfg.viewID,
      "--limit",
      "100",
      "--offset",
      String(offset),
    ]);
    const fields = data.fields || [];
    const records = data.data || [];
    const ids = data.record_id_list || [];
    for (let i = 0; i < records.length; i++) {
      const row = {};
      fields.forEach((field, idx) => {
        row[field] = records[i][idx];
      });
      out.push({ recordID: ids[i], row });
    }
    if (!data.has_more || records.length === 0) break;
    offset += records.length;
  }
  return out;
}

async function updateStatus(recordID, status) {
  await runLark("+record-upsert", ["--record-id", recordID, "--json", JSON.stringify({ [cfg.statusField]: status })]);
}

async function appendState(entry) {
  await fs.mkdir(path.dirname(cfg.stateFile), { recursive: true });
  await fs.appendFile(cfg.stateFile, `${JSON.stringify({ at: new Date().toISOString(), ...entry })}\n`);
}

async function getBusinessClue(keyword) {
  try {
    await openbridge(cfg.doudianSession, "find_tab", {
      url: "https://fxg.jinritemai.com/ffa/bu/NewBusinessCenter",
      active: false,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    if (!message.includes("no tab matching") && !message.includes("tab was closed")) {
      throw err;
    }
    await openbridge(cfg.doudianSession, "navigate", {
      url: "https://fxg.jinritemai.com/ffa/bu/NewBusinessCenter?source=business_center",
      newTab: true,
    });
    await sleep(3500);
  }
  const code = `(async function(){
    const keyword = ${JSON.stringify(keyword)};
    const payload = {
      condition: {
        clue_info: keyword,
        hit_clue_label_ext: true,
        show_new_supply_link: true,
        include_hot_sales_products: true,
        sort: {sort_direction: 1, sort_field: "MATCH_DEGREE"}
      },
      clue_type: "",
      clue_type_new: 11,
      page: {current: 1, page_size: 20},
      terminal_type: 0,
      source: "business_center"
    };
    const res = await fetch("/api/commop/business_chance_center/clue/common/real_time_list", {
      method: "POST",
      credentials: "include",
      headers: {"content-type": "application/json"},
      body: JSON.stringify(payload)
    });
    const json = await res.json();
    const list = Array.isArray(json.data) ? json.data : [];
    const exact = list.find((row) => String(row?.clue_detail?.name || "").trim() === keyword);
    if (!exact) return JSON.stringify({ok:false, reason:"没有找到完全匹配商机", total: json.total || 0});
    const d = exact.clue_detail || {};
    const ind = exact.clue_indicator || {};
    return JSON.stringify({
      ok: true,
      clue_id: String(d.clue_id || ""),
      name: String(d.name || ""),
      image: String(d.product_pic_url || (Array.isArray(d.pic_url_list) ? d.pic_url_list[0] : "") || ""),
      search_pv_cnt: Number(ind.search_pv_cnt || 0),
      growth: Number(ind.pay_amount_ind_30d_rate || 0),
      price_min: Number(d.price_min || 0),
      price_max: Number(d.price_max || 0)
    });
  })()`;
  return evalJSON(cfg.doudianSession, code);
}

function xfURL(clue) {
  const url = new URL(cfg.xfBaseURL);
  url.hash =
    `/searchSimilarGoodsIframe?t=2&title=${encodeURIComponent(clue.name)}` +
    `&img=${encodeURIComponent(clue.image)}` +
    `&price=0&price2=&relationId=${encodeURIComponent(cfg.relationID)}` +
    `&plugId=${encodeURIComponent(cfg.plugID)}`;
  return url.toString();
}

async function waitForRows(timeoutMs = 30000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const res = await evalJSON(
      cfg.xfSession,
      `(function(){
        const rows = [...document.querySelectorAll("tr, .n-data-table-tr")]
          .filter((row) => row.offsetParent && /ID：/.test(row.innerText || ""));
        return JSON.stringify({count: rows.length, title: document.title, body: document.body.innerText.slice(0, 300)});
      })()`,
    );
    if (res.count > 0) return res.count;
    await sleep(1000);
  }
  throw new Error("晓风页面未加载出货源列表");
}

async function clickXFTag(label) {
  const res = await evalJSON(
    cfg.xfSession,
    `(async function(){
      const label = ${JSON.stringify(label)};
      const candidates = [...document.querySelectorAll("div,span,button")]
        .filter((el) => el.offsetParent && (el.innerText || el.textContent || "").trim() === label);
      const el = candidates.find((x) => String(x.className).includes("c-p")) || candidates[0];
      if (!el) return JSON.stringify({ok:false, label, reason:"not found"});
      el.scrollIntoView({block:"center", inline:"center"});
      el.dispatchEvent(new MouseEvent("mousedown", {bubbles:true, composed:true, buttons:1}));
      el.dispatchEvent(new MouseEvent("mouseup", {bubbles:true, composed:true}));
      el.click();
      await new Promise((r) => setTimeout(r, 900));
      return JSON.stringify({ok:true, label, cls:String(el.className)});
    })()`,
  );
  if (!res.ok) throw new Error(`筛选项 ${label} 未找到`);
}

async function chooseLowestAmongFirstThreeAndAdd() {
  const picked = await evalJSON(
    cfg.xfSession,
    `(async function(){
      const rows = [...document.querySelectorAll("tr, .n-data-table-tr")]
        .filter((row) => row.offsetParent && /ID：/.test(row.innerText || ""));
      if (rows.length < 3) return JSON.stringify({ok:false, reason:"筛选后不足 3 条货源", row_count: rows.length});
      const firstThree = rows.slice(0, 3).map((row, index) => {
        const cells = [...row.querySelectorAll("td, .n-data-table-td")];
        const priceText = (cells.at(-1)?.innerText || row.innerText || "").replace(/\\s+/g, " ");
        const priceMatches = [...priceText.matchAll(/\\d+(?:\\.\\d{1,2})?/g)].map((m) => Number(m[0]));
        const text = (row.innerText || "").replace(/\\s+/g, " ");
        const id = (text.match(/ID：\\s*(\\d+)/) || [])[1] || "";
        return {
          index,
          row,
          text,
          id,
          price: priceMatches.length ? priceMatches.at(-1) : Number.POSITIVE_INFINITY
        };
      });
      firstThree.sort((a, b) => a.price - b.price);
      const target = firstThree[0];
      if (!Number.isFinite(target.price)) return JSON.stringify({ok:false, reason:"前三条价格解析失败"});
      const cb = target.row.querySelector(".n-checkbox, [role=checkbox], input[type=checkbox]");
      if (!cb) return JSON.stringify({ok:false, reason:"目标行 checkbox 未找到"});
      cb.scrollIntoView({block:"center", inline:"center"});
      cb.dispatchEvent(new MouseEvent("mousedown", {bubbles:true, composed:true, buttons:1}));
      cb.dispatchEvent(new MouseEvent("mouseup", {bubbles:true, composed:true}));
      cb.click();
      await new Promise((r) => setTimeout(r, 700));
      const addBtn = [...document.querySelectorAll("button")]
        .find((btn) => btn.offsetParent && (btn.innerText || btn.textContent || "").trim() === "添加云商品库");
      if (!addBtn) return JSON.stringify({ok:false, reason:"添加云商品库按钮未找到", picked: target});
      addBtn.scrollIntoView({block:"center", inline:"center"});
      addBtn.dispatchEvent(new MouseEvent("mousedown", {bubbles:true, composed:true, buttons:1}));
      addBtn.dispatchEvent(new MouseEvent("mouseup", {bubbles:true, composed:true}));
      addBtn.click();
      await new Promise((r) => setTimeout(r, 1500));
      const modal = [...document.querySelectorAll(".n-modal,.n-card,[role=dialog]")]
        .reverse().find((el) => el.offsetParent && /加入云商品库/.test(el.innerText || ""));
      if (!modal) return JSON.stringify({ok:false, reason:"加入云商品库确认框未出现", picked: target});
      const okBtn = [...modal.querySelectorAll("button")]
        .find((btn) => btn.offsetParent && (btn.innerText || btn.textContent || "").trim() === "确定");
      if (!okBtn) return JSON.stringify({ok:false, reason:"加入云商品库确定按钮未找到", picked: target});
      okBtn.dispatchEvent(new MouseEvent("mousedown", {bubbles:true, composed:true, buttons:1}));
      okBtn.dispatchEvent(new MouseEvent("mouseup", {bubbles:true, composed:true}));
      okBtn.click();
      await new Promise((r) => setTimeout(r, 9000));
      const body = document.body.innerText || "";
      const success = /成功添加\\s*1\\s*个商品/.test(body) || /失败\\s*0\\s*个商品/.test(body);
      const skipped = /跳过\\s*[1-9]\\d*\\s*个商品/.test(body);
      const failed = (body.match(/失败\\s*(\\d+)\\s*个商品/) || [])[1] || "";
      const successModal = [...document.querySelectorAll(".n-modal,.n-card,[role=dialog]")]
        .reverse().find((el) => el.offsetParent && /成功添加|温馨提示|失败|跳过/.test(el.innerText || ""));
      if (successModal) {
        const closeBtn = [...successModal.querySelectorAll("button")]
          .find((btn) => btn.offsetParent && (btn.innerText || btn.textContent || "").trim() === "关闭");
        if (closeBtn) closeBtn.click();
      }
      return JSON.stringify({
        ok: success || skipped,
        failed,
        skipped,
        picked: {
          index: target.index,
          id: target.id,
          price: target.price,
          text: target.text.slice(0, 260)
        },
        body_tail: body.slice(-700)
      });
    })()`,
  );
  if (!picked.ok) throw new Error(picked.reason || `添加云商品库失败: ${picked.body_tail || ""}`);
  return picked;
}

async function closeXF() {
  try {
    await openbridge(cfg.xfSession, "close_tab", {});
  } catch {
    // Ignore; the next navigate can reuse the session.
  }
}

async function processRecord(record, ordinal, total) {
  const keyword = extractPlainText(record.row["关键词"]).trim();
  if (!keyword) return { status: "skipped", reason: "关键词为空" };
  log(`[${ordinal}/${total}] ${keyword}`);
  const clue = await getBusinessClue(keyword);
  if (!clue.ok) {
    return { status: "failed", reason: clue.reason || "未找到完全匹配商机" };
  }
  if (clue.name !== keyword) {
    return { status: "failed", reason: `名字不完全匹配: ${clue.name}` };
  }
  if (clue.search_pv_cnt <= 10000) {
    return { status: "failed", reason: `搜索次数不足: ${clue.search_pv_cnt}` };
  }
  if (!clue.image) {
    return { status: "failed", reason: "商机图片为空，无法打开晓风以图搜款" };
  }

  await openbridge(cfg.xfSession, "navigate", { url: xfURL(clue), newTab: true });
  await waitForRows();
  for (const tag of ["抖音面单", "一件代发", "包邮"]) {
    await clickXFTag(tag);
  }
  await sleep(3500);
  const picked = await chooseLowestAmongFirstThreeAndAdd();
  await closeXF();
  return { status: "success", clue, picked };
}

async function withTimeout(promise, ms, label) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} timed out after ${ms}ms`)), ms);
  });
  try {
    return await Promise.race([promise, timeout]);
  } finally {
    clearTimeout(timer);
  }
}

async function main() {
  const records = await listRecords();
  let pending = records.filter(({ row }) => {
    const status = extractPlainText(row[cfg.statusField]).trim();
    if (status === "") return true;
    if (retryGrowthSkipped && status.startsWith("未添加：成交增速不大于 0:")) return true;
    if (retryFindTabFailures && status.startsWith("未添加：find_tab:")) return true;
    if (retryXFEmpty && status === "未添加：晓风页面未加载出货源列表") return true;
    return false;
  });
  if (onlyKeyword) pending = pending.filter(({ row }) => extractPlainText(row["关键词"]).trim() === onlyKeyword);
  if (limit > 0) pending = pending.slice(0, limit);
  const summary = {
    total_records: records.length,
    pending_count: pending.length,
    success: 0,
    skipped: 0,
    failed: 0,
    state_file: cfg.stateFile,
    processed: [],
  };
  log(`读取 ${records.length} 条，待处理 ${pending.length} 条。`);

  let ok = 0;
  let failed = 0;
  let skipped = 0;
  for (let i = 0; i < pending.length; i++) {
    const record = pending[i];
    const keyword = extractPlainText(record.row["关键词"]).trim();
    try {
      const result = await withTimeout(processRecord(record, i + 1, pending.length), 240000, `处理 ${keyword}`);
      if (result.status === "success") {
        await updateStatus(record.recordID, "已添加到晓风云库");
        ok++;
        summary.processed.push({
          record_id: record.recordID,
          keyword,
          status: "success",
          source_id: result.picked.picked.id,
          price: result.picked.picked.price,
        });
        log(`  OK 已添加：¥${result.picked.picked.price} ID=${result.picked.picked.id}`);
      } else {
        const reason = result.reason || "跳过";
        await updateStatus(record.recordID, `未添加：${reason}`.slice(0, 200));
        skipped++;
        summary.processed.push({ record_id: record.recordID, keyword, status: "skipped", reason });
        log(`  SKIP ${reason}`);
      }
      await appendState({ record_id: record.recordID, keyword, result });
    } catch (err) {
      failed++;
      const message = err instanceof Error ? err.message : String(err);
      await updateStatus(record.recordID, `未添加：${message}`.slice(0, 200)).catch(() => {});
      await appendState({ record_id: record.recordID, keyword, error: message });
      await closeXF();
      summary.processed.push({ record_id: record.recordID, keyword, status: "failed", reason: message });
      log(`  FAIL ${message}`);
    }
  }
  summary.success = ok;
  summary.skipped = skipped;
  summary.failed = failed;
  log(`完成：成功 ${ok}，跳过 ${skipped}，失败 ${failed}。`);
  return summary;
}

main().then((summary) => {
  console.log(JSON.stringify({ ok: true, data: summary }, null, 2));
}).catch((err) => {
  const message = err instanceof Error ? err.message : String(err);
  console.log(JSON.stringify({ ok: false, error: { code: "xf_cloud_failed", message } }, null, 2));
  console.error(err instanceof Error ? err.stack || err.message : err);
  process.exit(1);
});
