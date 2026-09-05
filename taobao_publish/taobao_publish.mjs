#!/usr/bin/env node
/**
 * taobao_publish.mjs —— 淘宝「发布商品」自动化(从 cli_goods JSON 一键上架)
 *
 * 用法:
 *   node taobao_publish.mjs cli_goods_20260618.json            # 填完直接提交上架
 *   node taobao_publish.mjs cli_goods_20260618.json --draft    # 填完只存草稿,不提交
 *   node taobao_publish.mjs cli_goods_20260618.json --no-submit # 填完停在确认页,你手动点提交
 *
 * 前置:
 *   - CloakBrowser 已开,CDP 端口 9223,且已登录千牛/淘宝卖家后台
 *   - 本机有 playwright (node_modules 在 ~/),macOS 自带 sips
 *
 * 为什么不用「发布相似品」: 复制发布会锁死类目,跨类目发不了。本脚本走「发布商品」全新发,
 * 自己搜类目,因此任何类目都能发。
 *
 * 复用说明: 类目属性按「文本」实时匹配页面下拉选项(不写死 value id),所以同类目换商品直接可用;
 * 换类目时只需改 CONFIG.categoryKeyword + 检查 PROP_MAP 的标签名/默认值是否对得上。
 */
import { chromium } from 'playwright';
import { execSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import https from 'node:https';

// ───────────────────────── CONFIG(按需调整) ─────────────────────────
const CDP = 'http://127.0.0.1:9223';
const CONFIG = {
  // 类目搜索关键词 + 期望落到的类目路径(用于在候选里选对那一条)
  categoryKeyword: '半身裙',
  categoryPathIncludes: '女装',          // 候选行里包含这个词的优先(避开童装/运动)
  freightTemplate: '全国包邮',           // 运费模板名(店铺里必须已存在)
  shipTime: '48小时内发货',               // 发货时间
  // SKU 尺寸/规格的兜底值(JSON 里通常没有,必填,先填合理值,上架后可改)
  skuDefaults: { 裙长: '88', 图案: '纯色' },
  // 尺码归类: JSON 用字母码 S/M/L/XL → 尺码选择器里的「中国码」组
  sizeGroup: '中国码',
  materialDefault: { name: '其他材质', percent: '100' }, // 材质成分兜底
};

// JSON properties 名 → 发布表单里的属性标签 + 控件类型
//   type: 'select'(单选) | 'multi'(多选/checkbox/tag) | 'auto'(autocomplete 打字) | 'input'(纯文本)
// 填充时按 JSON 里的「值文本」去页面下拉里找同名选项点选(找不到就跳过并告警)。
const PROP_MAP = [
  { json: '版型',        label: '版型',         type: 'auto'   },
  { json: '面料',        label: '面料',         type: 'multi'  },
  { json: '面料工艺',    label: '面料工艺',     type: 'multi'  },
  { json: '裙型',        label: '裙型',         type: 'select' },
  { json: '适用人群',    label: '适用人群',     type: 'multi'  },
  { json: '腰型设计',    label: '腰型设计',     type: 'auto'   },
  { json: '款式细节',    label: '款式细节',     type: 'multi'  },
  { json: '上市年份季节',label: '上市年份季节', type: 'select' },
  { json: '功能',        label: '功能',         type: 'select' },
  { json: '是否有内衬',  label: '是否有内衬',   type: 'select' },
  { json: '开衩位置',    label: '开衩位置',     type: 'select' },
  { json: '适用年龄',    label: '适用年龄',     type: 'multi'  },
  { json: '穿着方式',    label: '穿着方式',     type: 'select' },
  { json: '货号',        label: '货号',         type: 'input'  },
];
// ──────────────────────────────────────────────────────────────────

const args = process.argv.slice(2);
const jsonPath = args.find(a => !a.startsWith('--'));
const MODE = args.includes('--draft') ? 'draft' : args.includes('--no-submit') ? 'review' : 'submit';
if (!jsonPath) { console.error('用法: node taobao_publish.mjs <product.json> [--draft|--no-submit]'); process.exit(1); }

const product = JSON.parse(fs.readFileSync(jsonPath, 'utf8')).products[0];
const log = (...a) => console.log('•', ...a);
const sleep = ms => new Promise(r => setTimeout(r, ms));

// ── helpers: CDP page ──
async function getPage() {
  const browser = await chromium.connectOverCDP(CDP);
  const ctx = browser.contexts()[0];
  let page = ctx.pages().find(p => p.url().includes('/sell/v2/publish.htm') || p.url().includes('/sell/ai/category'));
  return { browser, ctx, page };
}
const state = page => page.evaluate(() => window.__SELL_STATE__?.getState?.());

// 真实鼠标点开某个标签对应的 Fusion select,从自定义弹层 .options-item 里按文本点选
async function openSelectByLabel(page, label) {
  const box = await page.evaluate(lbl => {
    const lab = [...document.querySelectorAll('*')].find(e => e.offsetParent && e.childElementCount <= 2 && (e.textContent || '').trim() === lbl);
    if (!lab) return null;
    let row = lab; for (let i = 0; i < 7; i++) { row = row.parentElement; if (!row) break; if (row.querySelector('.next-select')) break; }
    const sel = row && row.querySelector('.next-select'); if (!sel) return null;
    sel.scrollIntoView({ block: 'center' }); const r = sel.getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  }, label);
  if (!box) return false;
  await sleep(250); await page.mouse.click(box.x, box.y); await sleep(700); return true;
}
async function pickOption(page, text) { // 在已打开的弹层里搜索+点选
  await page.evaluate(() => { const w = [...document.querySelectorAll('.next-overlay-wrapper.opened')].pop(); const i = w && w.querySelector('.options-search input'); if (i) { i.focus(); i.value = ''; } });
  await page.keyboard.type(text, { delay: 25 }); await sleep(700);
  return page.evaluate(t => {
    const w = [...document.querySelectorAll('.next-overlay-wrapper.opened')].pop(); if (!w) return false;
    const items = [...w.querySelectorAll('.options-item,.next-menu-item')].filter(e => e.offsetParent);
    const it = items.find(e => (e.textContent || '').trim() === t) || items.find(e => (e.textContent || '').trim().includes(t));
    if (it) { it.click(); return true; } return false;
  }, text);
}
async function fillSelect(page, label, values, { multi = false } = {}) {
  if (!(await openSelectByLabel(page, label))) return `${label}:行未找到`;
  const res = [];
  for (const v of [].concat(values)) { res.push(v + (await pickOption(page, v) ? '✓' : '✗')); if (!multi) break; }
  await page.keyboard.press('Escape').catch(() => {}); await page.mouse.click(5, 5).catch(() => {}); await sleep(300);
  return `${label}:${res.join(',')}`;
}
async function fillAuto(page, label, value) { // autocomplete: 打字即生效
  if (!(await openSelectByLabel(page, label))) return `${label}:行未找到`;
  await page.keyboard.type(value, { delay: 30 }); await sleep(900);
  await page.evaluate(t => { const w = [...document.querySelectorAll('.next-overlay-wrapper.opened')].pop(); if (w) { const it = [...w.querySelectorAll('.options-item,.next-menu-item')].find(e => e.offsetParent && (e.textContent || '').trim() === t); it && it.click(); } }, value);
  await page.keyboard.press('Escape').catch(() => {}); await sleep(300); return `${label}:${value}(auto)`;
}
async function fillInput(page, label, value) {
  const ok = await page.evaluate(({ lbl, val }) => {
    const lab = [...document.querySelectorAll('*')].find(e => e.offsetParent && e.childElementCount <= 2 && (e.textContent || '').trim() === lbl);
    if (!lab) return false; let row = lab; for (let i = 0; i < 7; i++) { row = row.parentElement; if (row.querySelector('input')) break; }
    const inp = row.querySelector('input'); if (!inp) return false; inp.scrollIntoView({ block: 'center' }); inp.focus(); return true;
  }, { lbl: label, val: value });
  if (!ok) return `${label}:行未找到`;
  await page.keyboard.type(value, { delay: 25 }); await page.keyboard.press('Tab'); await sleep(200); return `${label}:${value}`;
}

// 关掉「将更换成/被清空/确认操作」这类二次确认弹窗;返回是否点到了
async function clickConfirmDialog(page) {
  return page.evaluate(() => {
    const dlg = [...document.querySelectorAll('.next-dialog,[role="dialog"],.next-overlay-inner')].find(e => e.offsetParent && /将更换成|被清空|确认操作|确认更换/.test(e.textContent || ''));
    if (!dlg) return false;
    const b = [...dlg.querySelectorAll('button')].find(e => (e.textContent || '').trim() === '确定');
    if (b) { b.click(); return true; } return false;
  });
}
// 跑 fn,读模型 check;不过就重试(默认3次)。返回最终是否成功。
async function retry(fn, check, label, tries = 3) {
  for (let i = 0; i < tries; i++) {
    try { await fn(i); } catch (e) {}
    if (await check()) return true;
    await sleep(1000);
  }
  return false;
}

// ── 图片: 下载 → sips 补白成 1:1 方图 → 经 filechooser 上传 → 图块点选 ──
function dl(url, dest) {
  return new Promise((resolve, reject) => {
    const f = fs.createWriteStream(dest);
    https.get(url, { headers: { 'User-Agent': 'Mozilla/5.0', Referer: 'https://item.taobao.com/' } }, r => { r.pipe(f); f.on('finish', () => f.close(() => resolve(dest))); }).on('error', reject);
  });
}
function squarePad(src, dst) { // 取长边补白(白底),webp→jpg
  const W = +execSync(`sips -g pixelWidth "${src}" | awk '/pixelWidth/{print $2}'`).toString().trim();
  const H = +execSync(`sips -g pixelHeight "${src}" | awk '/pixelHeight/{print $2}'`).toString().trim();
  const S = Math.max(W, H);
  execSync(`sips -s format jpeg --padToHeightWidth ${S} ${S} --padColor FFFFFF "${src}" -o "${dst}" >/dev/null 2>&1`);
  return dst;
}

async function main() {
  const { browser, ctx, page: existing } = await getPage();
  let page = existing;
  if (!page) { page = await ctx.newPage(); }
  await page.bringToFront();

  // ── Phase 1: 选类目(全新发布) ──
  log('打开类目选择…');
  await page.goto('https://item.upload.taobao.com/sell/ai/category.htm?force=true', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await sleep(4000);
  await page.evaluate(() => { const t = [...document.querySelectorAll('*')].find(e => e.offsetParent && e.childElementCount === 0 && (e.textContent || '').trim() === '搜索发品'); (t?.closest('button,a,div,li') || t)?.click(); });
  await sleep(1000);
  const inp = page.locator('input[placeholder*="类目关键词"]');
  await inp.click(); await inp.fill(CONFIG.categoryKeyword); await inp.press('Enter'); await sleep(2500);
  await page.evaluate(inc => {
    const rows = [...document.querySelectorAll('*')].filter(e => { const t = (e.textContent || '').replace(/\s+/g, ''); return t.includes(inc) && t.includes('半身裙') && e.querySelectorAll('*').length < 6; });
    const row = rows[rows.length - 1]; const link = [...(row?.querySelectorAll('a,span') || [])].find(e => /半身裙|裙/.test(e.textContent || '')) || row; link?.click();
  }, CONFIG.categoryPathIncludes);
  await sleep(2000);
  await page.evaluate(() => { const b = [...document.querySelectorAll('button,a')].find(e => e.offsetParent && /确认.*下一步/.test((e.textContent || '').trim()) && !e.disabled); b?.click(); });
  await sleep(9000);
  log('类目:', await page.evaluate(() => document.querySelector('[class*="category"]')?.textContent?.trim().slice(0, 40)));

  // ── Phase 2: 标题 + 类目属性 ──
  const title = (product.title || '').slice(0, 60);
  const tin = page.locator('input[placeholder*="最多允许输入30个汉字"]').first();
  await tin.scrollIntoViewIfNeeded(); await tin.click(); await tin.fill(title);
  log('标题:', title);

  // 材质成分(material 特殊组件): 添加材质成分 → 选材质名 → 填含量
  await page.getByText('添加材质成分', { exact: true }).first().click().catch(() => {});
  await sleep(800);
  const matName = page.locator('input[placeholder="请选择材质"]').first();
  if (await matName.count()) {
    await matName.click(); await page.keyboard.type(CONFIG.materialDefault.name, { delay: 35 }); await sleep(1000);
    await page.evaluate(n => { const w = [...document.querySelectorAll('.next-overlay-wrapper.opened')].pop(); const it = w && [...w.querySelectorAll('.options-item,.next-menu-item')].find(e => (e.textContent || '').trim().includes(n)); it?.click(); }, CONFIG.materialDefault.name);
    await sleep(600);
    const pct = await page.evaluate(() => { const i = [...document.querySelectorAll('input')].find(x => x.offsetParent && /含量/.test(x.placeholder || '')); if (i) { i.setAttribute('data-pct', '1'); const r = i.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; } return null; });
    if (pct) { await page.mouse.click(pct.x, pct.y); await page.keyboard.type(CONFIG.materialDefault.percent, { delay: 50 }); await page.keyboard.press('Tab'); }
    log('材质成分:', CONFIG.materialDefault.name, CONFIG.materialDefault.percent + '%');
  }

  // 其余类目属性(按 JSON 文本匹配)
  const propByName = Object.fromEntries((product.properties || []).map(p => [p.name, p.values]));
  for (const m of PROP_MAP) {
    const vals = propByName[m.json]; if (!vals || !vals.length) continue;
    let r;
    if (m.type === 'auto') r = await fillAuto(page, m.label, vals[0]);
    else if (m.type === 'input') r = await fillInput(page, m.label, vals[0]);
    else if (m.type === 'multi') r = await fillSelect(page, m.label, vals, { multi: true });
    else r = await fillSelect(page, m.label, vals[0]); // select 单选取第一个
    log(r);
  }

  // ── Phase 3: 销售属性(颜色/尺码) + SKU 价格库存 ──
  await page.evaluate(() => { const t = [...document.querySelectorAll('*')].find(e => e.offsetParent && e.childElementCount <= 2 && (e.textContent || '').trim() === '销售信息'); t?.click(); });
  await sleep(1200);
  const colors = (propByName['颜色分类'] || ['白色']);
  for (const c of colors) {
    const ci = page.locator('input[placeholder="主色(必选)"]').first();
    await ci.click(); await ci.fill(''); await page.keyboard.type(c, { delay: 50 }); await sleep(600);
    // 点颜色行的 + 提交自定义色
    await page.evaluate(() => { const ci = document.querySelector('input[placeholder="主色(必选)"]'); let row = ci; for (let i = 0; i < 6; i++) { row = row.parentElement; if ([...row.querySelectorAll('button')].length) break; } const ciB = ci.getBoundingClientRect(); const plus = [...row.querySelectorAll('button')].filter(b => { const r = b.getBoundingClientRect(); return b.offsetParent && r.x > ciB.x + ciB.width && Math.abs(r.y - ciB.y) < 40; }).pop(); plus?.click(); });
    await sleep(900);
  }
  log('颜色:', colors.join('/'));

  // 尺码: 打开 → 切到「中国码」组 → 勾选字母码 → 面板确定 → 关二次确认弹窗(它在确定后才弹!)
  const sizes = (propByName['尺码'] || []);
  const skuExpect = Math.max(1, colors.length) * Math.max(1, sizes.length);
  if (sizes.length) {
    const ok = await retry(async () => {
      const si = page.locator('input[placeholder="请选择尺码"]').first();
      await si.scrollIntoViewIfNeeded(); await si.click(); await sleep(1000);
      // 切号型组(已是该组则点了无副作用)
      const grpBox = await page.evaluate(g => { const panel = [...document.querySelectorAll('*')].find(e => e.offsetParent && /已选\s*\d+\s*个/.test(e.textContent || '') && e.querySelector('button')); if (!panel) return null; const it = [...panel.querySelectorAll('*')].find(e => e.offsetParent && e.childElementCount <= 1 && (e.textContent || '').trim() === g); if (!it) return null; const r = it.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; }, CONFIG.sizeGroup);
      if (grpBox) { await page.mouse.click(grpBox.x, grpBox.y); await sleep(1000); }
      for (let t = 0; t < 6; t++) { if (await clickConfirmDialog(page)) break; await sleep(400); } // 切组若弹确认就关
      await sleep(1200);
      // 幂等勾选目标尺码(已勾的不再点,避免取消)
      for (const sz of sizes) {
        await page.evaluate(s => { const panel = [...document.querySelectorAll('*')].find(e => e.offsetParent && /已选\s*\d+\s*个/.test(e.textContent || '') && e.querySelector('button')); if (!panel) return; const it = [...panel.querySelectorAll('label,[class*="checkbox-wrapper"]')].find(e => e.offsetParent && (e.textContent || '').trim() === s); if (!it) return; const inp = it.querySelector('input'); if (inp && inp.checked) return; (inp || it).click(); }, sz);
        await sleep(300);
      }
      // 面板 确定
      await page.evaluate(() => { const panel = [...document.querySelectorAll('*')].find(e => e.offsetParent && /已选\s*\d+\s*个/.test(e.textContent || '') && e.querySelector('button')); const b = panel && [...panel.querySelectorAll('button')].find(e => (e.textContent || '').trim() === '确定'); b?.click(); });
      await sleep(1200);
      for (let t = 0; t < 8; t++) { if (await clickConfirmDialog(page)) break; await sleep(400); } // 确定后的「将更换成中国码」确认
      await sleep(1500);
    }, async () => page.evaluate(n => (window.__SELL_STATE__.getState().engine.getModels().formValues.sku || []).length >= n, skuExpect), '尺码');
    log('尺码:', sizes.join('/'), ok ? '✓' : '⚠️未确认');
  }

  // 批量价格/库存(带校验重试)
  const price = String(product.price), stock = String(product.skus?.[0]?.stock ?? 200);
  // 批量行的坑(实测): 批量填写要求价格+数量都填,但每次只生效「先填的那个」字段。
  // 所以两趟: 第一趟价格先填(价格生效)→ 第二趟数量先填(库存生效,价格保留)。
  const markBatchRow = () => page.evaluate(() => {
    const btn = [...document.querySelectorAll('button,span,a')].find(e => e.offsetParent && (e.textContent || '').trim() === '批量填写');
    let row = btn; for (let i = 0; i < 6; i++) { row = row.parentElement; if (!row) break; if ([...row.querySelectorAll('input')].length >= 2) break; }
    [...(row?.querySelectorAll('input') || [])].forEach(i => { if (i.placeholder === '价格') i.setAttribute('data-bp', '1'); if (i.placeholder === '数量') i.setAttribute('data-bq', '1'); });
  });
  const clickBatch = async () => { await page.evaluate(() => { const b = [...document.querySelectorAll('button,span,a')].find(e => e.offsetParent && (e.textContent || '').trim() === '批量填写'); (b?.closest('button') || b)?.click(); }); await sleep(1200); };
  const okPS = await retry(async () => {
    await markBatchRow();
    let p = page.locator('input[data-bp]').first(), q = page.locator('input[data-bq]').first();
    await p.click(); await p.fill(price); await sleep(220); await q.click(); await q.fill(stock); await sleep(220); await clickBatch(); // 价格生效
    await markBatchRow(); p = page.locator('input[data-bp]').first(); q = page.locator('input[data-bq]').first();
    await q.click(); await q.fill(stock); await sleep(220); await p.click(); await p.fill(price); await sleep(220); await clickBatch(); // 库存生效
  }, async () => page.evaluate(() => { const sku = window.__SELL_STATE__.getState().engine.getModels().formValues.sku || []; return sku.length > 0 && sku.every(s => +s.skuStock > 0 && s.skuPrice); }), '价格库存');
  log('价格/库存:', price, '/', stock, okPS ? '✓' : '⚠️未确认');

  // SKU 必填: 裙长 + 图案(更多批量)
  await page.evaluate(() => { const b = [...document.querySelectorAll('*')].find(e => e.offsetParent && (e.textContent || '').trim() === '更多批量'); b && b.scrollIntoView({ block: 'center' }); });
  await page.evaluate(() => { const b = [...document.querySelectorAll('*')].find(e => e.offsetParent && (e.textContent || '').trim() === '更多批量'); const r = b.getBoundingClientRect(); window.__mb = { x: r.x + r.width / 2, y: r.y + r.height / 2 }; });
  const mb = await page.evaluate(() => window.__mb); await page.mouse.click(mb.x, mb.y); await sleep(1200);
  // 裙长(input) + 图案(select) in 批量填充 dialog
  const qunBox = await page.evaluate(() => { const lab = [...document.querySelectorAll('*')].find(e => e.offsetParent && e.childElementCount <= 1 && (e.textContent || '').trim() === '裙长'); if (!lab) return null; const ly = lab.getBoundingClientRect(); const i = [...document.querySelectorAll('input')].find(e => { const r = e.getBoundingClientRect(); return e.offsetParent && r.y > ly.y && r.y < ly.y + 50 && Math.abs(r.x - ly.x) < 80; }); if (i) { const r = i.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; } return null; });
  if (qunBox) { await page.mouse.click(qunBox.x, qunBox.y); await page.keyboard.type(CONFIG.skuDefaults.裙长, { delay: 60 }); await sleep(300); }
  const tuanBox = await page.evaluate(() => { const lab = [...document.querySelectorAll('*')].find(e => e.offsetParent && e.childElementCount <= 1 && (e.textContent || '').trim() === '图案'); if (!lab) return null; const ly = lab.getBoundingClientRect(); const s = [...document.querySelectorAll('.next-select')].find(e => { const r = e.getBoundingClientRect(); return e.offsetParent && r.y > ly.y && r.y < ly.y + 50 && Math.abs(r.x - ly.x) < 80; }); if (s) { const r = s.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; } return null; });
  if (tuanBox) { await page.mouse.click(tuanBox.x, tuanBox.y); await sleep(900); await pickOption(page, CONFIG.skuDefaults.图案); }
  await sleep(400);
  await page.evaluate(() => { const dlg = [...document.querySelectorAll('*')].find(e => e.offsetParent && /批量填充/.test(e.textContent || '') && /填充内容/.test(e.textContent || '')); const b = [...(dlg || document).querySelectorAll('button')].find(e => e.offsetParent && (e.textContent || '').trim() === '批量填充'); b?.click(); });
  await sleep(1500);
  log('SKU 裙长/图案:', CONFIG.skuDefaults.裙长, '/', CONFIG.skuDefaults.图案);

  // ── Phase 4: 图片(主图补方图重传 + 详情图) ──
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'tbpub-'));
  const sqFiles = [];
  for (let i = 0; i < (product.main_images || []).length; i++) { const raw = path.join(work, `m${i}.img`); await dl(product.main_images[i], raw); const sq = path.join(work, `m${i}.jpg`); try { squarePad(raw, sq); sqFiles.push(sq); } catch {} }
  const detFiles = [];
  for (let i = 0; i < (product.detail_images || []).length; i++) { const raw = path.join(work, `d${i}.jpg`); try { await dl(product.detail_images[i], raw); if (fs.statSync(raw).size > 2000) detFiles.push(raw); } catch {} }

  // 主图: 进 图文描述 → 1:1主图「上传图片」→ 本地上传(filechooser) → 完成 → 点前 N 张方图
  await page.evaluate(() => { const t = [...document.querySelectorAll('*')].find(e => e.offsetParent && e.childElementCount <= 2 && (e.textContent || '').trim() === '图文描述'); t?.click(); });
  await sleep(800);
  await uploadAndSelect(page, ctx, '1:1主图区', sqFiles, 'main');
  log('主图:', sqFiles.length, '张');

  // 详情: 宝贝详情「图片」按钮(多选 max=100)→ 本地上传 → 完成 → 点前 N 张
  await uploadAndSelect(page, ctx, '宝贝详情', detFiles, 'desc');
  log('详情图:', detFiles.length, '张');

  // ── Phase 5: 物流(使用物流配送 + 包邮模板 + 发货时间) ──
  await page.evaluate(() => { const c = [...document.querySelectorAll('*')].filter(e => e.offsetParent && e.childElementCount <= 2 && (e.textContent || '').trim() === '物流服务').sort((a, b) => a.getBoundingClientRect().y - b.getBoundingClientRect().y); c[0]?.click(); });
  await sleep(1200);
  await page.evaluate(s => { const el = [...document.querySelectorAll('*')].find(e => e.offsetParent && (e.textContent || '').trim() === s); (el?.closest('label') || el)?.click(); }, CONFIG.shipTime);
  await sleep(400);
  const okFreight = await retry(async () => {
    // 勾选「使用物流配送」(已勾则跳过)→ 等运费模板下拉启用
    await page.evaluate(() => { const lbl = [...document.querySelectorAll('.next-checkbox-label')].find(e => e.offsetParent && (e.textContent || '').trim() === '使用物流配送'); const wrap = lbl?.closest('.next-checkbox-wrapper'); const inp = wrap?.querySelector('input'); if (wrap && inp && !inp.checked) { wrap.scrollIntoView({ block: 'center' }); wrap.click(); } });
    await sleep(1500);
    const tplBox = await page.evaluate(() => { const blk = document.querySelector('.logis-block'); const sel = blk && blk.querySelector('.next-select'); if (!sel) return null; sel.scrollIntoView({ block: 'center' }); const r = sel.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; });
    if (tplBox) { await page.mouse.click(tplBox.x, tplBox.y); await sleep(1200); await page.evaluate(t => { const w = [...document.querySelectorAll('.next-overlay-wrapper.opened')].pop(); const it = w && [...w.querySelectorAll('.options-item,.next-menu-item,li')].find(e => e.offsetParent && (e.textContent || '').trim() === t); it?.click(); }, CONFIG.freightTemplate); }
    await sleep(1200);
  }, async () => page.evaluate(() => !!window.__SELL_STATE__.getState().engine.getModels().formValues.tbExtractWay?.template), '运费模板');
  log('物流:', CONFIG.shipTime, '+', CONFIG.freightTemplate, okFreight ? '✓' : '⚠️未确认');

  // ── 提交前自检 ──
  await sleep(1500);
  const chk = await page.evaluate(() => {
    const fv = window.__SELL_STATE__.getState().engine.getModels().formValues;
    const sku = fv.sku || [];
    return {
      skus: sku.length,
      priceOK: sku.length > 0 && sku.every(s => s.skuPrice),
      stockOK: sku.length > 0 && sku.every(s => +s.skuStock > 0),
      freightOK: !!fv.tbExtractWay?.template,
      mainImgs: (JSON.stringify(fv.mainImagesGroup).match(/alicdn/g) || []).length,
      catProps: Object.keys(fv.catProp || {}).length,
    };
  });
  const green = chk.skus > 1 && chk.priceOK && chk.stockOK && chk.freightOK && chk.mainImgs > 0;
  log('自检:', JSON.stringify(chk), green ? '→ 全绿 ✅' : '→ 有缺失 ⚠️');

  // ── Phase 6: 提交 / 草稿 / 停 ──
  if (MODE === 'review') { log('已填完(--no-submit),请在浏览器里核对后手动点「提交宝贝信息」'); await browser.close(); return; }
  if (MODE === 'draft') { await page.evaluate(() => { const b = [...document.querySelectorAll('button')].find(e => e.offsetParent && /保存草稿/.test(e.textContent || '')); b?.click(); }); await sleep(3000); log('已存草稿'); await browser.close(); return; }
  await page.evaluate(() => { const b = [...document.querySelectorAll('button')].find(e => e.offsetParent && /提交宝贝信息/.test((e.textContent || '').trim())); b?.click(); });
  await sleep(5000);
  const res = await page.evaluate(() => ({ url: location.href, ok: /success\.htm/.test(location.href), id: (document.body.innerText.match(/商品ID[：:]\s*(\d+)/) || [])[1], err: (document.body.innerText.match(/错误\s*[\(（](\d+)[\)）]/) || [])[1], captcha: /验证|滑块|安全验证/.test(document.body.innerText) }));
  if (res.ok) log('✅ 上架成功! 商品ID:', res.id);
  else if (res.captcha) log('⚠️ 撞到安全验证/滑块,请在浏览器里手动完成,然后重点提交');
  else log('⚠️ 未跳成功页,可能还有', res.err, '个错误,请在浏览器里看「优化建议」面板');
  await browser.close();
}

// 上传图片到图片空间并选入(主图 sectionLabel='1:1主图区' / 详情='宝贝详情')
async function uploadAndSelect(page, ctx, sectionLabel, files, kind) {
  if (!files.length) return;
  // 找入口按钮: 主图用「上传图片」(第一个1:1槽),详情用「图片」
  const entryText = kind === 'main' ? '上传图片' : '图片';
  const box = await page.evaluate(t => { const el = [...document.querySelectorAll('*')].find(e => e.offsetParent && e.childElementCount <= 2 && (e.textContent || '').trim() === t); if (!el) return null; el.scrollIntoView({ block: 'center' }); const r = el.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; }, entryText);
  if (!box) { console.log('  (找不到', entryText, '入口,跳过', kind); return; }
  let uploaded = false;
  const onFC = async fc => { try { await fc.setFiles(files); uploaded = true; } catch {} };
  page.on('filechooser', onFC);
  await page.mouse.click(box.x, box.y); await sleep(2500);
  const fr = page.frames().find(f => f.url().includes('sucai-selector'));
  if (fr) { await fr.locator('text=本地上传').first().click().catch(() => {}); await sleep(4500); }
  // 完成上传
  const fr2 = page.frames().find(f => f.url().includes('sucai-selector'));
  if (fr2) await fr2.evaluate(() => { const b = [...document.querySelectorAll('button')].find(e => e.offsetParent && (e.textContent || '').trim() === '完成'); b?.click(); }).catch(() => {});
  await sleep(2500);
  // 点选刚传的前 N 张(画廊最前面就是最新上传的)
  const fr3 = page.frames().find(f => f.url().includes('sucai-selector'));
  if (fr3) {
    const off = await page.evaluate(() => { const f = [...document.querySelectorAll('iframe')].find(f => f.src && f.src.includes('sucai-selector')); const r = f.getBoundingClientRect(); return { x: r.x, y: r.y }; });
    // 取前 files.length 个图块 caption 坐标(基于网格 5 列)
    const tiles = await fr3.evaluate(n => { const caps = [...document.querySelectorAll('*')].filter(e => e.offsetParent && e.childElementCount === 0 && /\.(jpg|webp|png)$/i.test((e.textContent || '').trim())).slice(0, n); return caps.map(c => { const r = c.getBoundingClientRect(); return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y - 55) }; }); }, files.length);
    for (const t of tiles) { await page.mouse.click(off.x + t.x, off.y + t.y); await sleep(550); }
    await sleep(600);
    // 详情/确定
    const okBox = await fr3.evaluate(() => { const b = [...document.querySelectorAll('button')].find(e => e.offsetParent && /确定/.test(e.textContent || '')); if (b) { const r = b.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; } return null; }).catch(() => null);
    if (okBox) await page.mouse.click(off.x + okBox.x, off.y + okBox.y);
  }
  await sleep(2500);
  page.off('filechooser', onFC);
}

main().catch(e => { console.error('ERR', e.message); process.exit(1); });
