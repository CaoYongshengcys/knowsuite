/* KnowSuite 控制台截图：puppeteer-core + 本机 Edge，带渲染断言 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const BASE = 'http://127.0.0.1:8100/?token=demo-admin#';
const OUT = 'D:\\code_cys\\knowsuite\\_shots';

const TABS = [
  { tab: 'overview', file: 'ks_overview.png', marker: '#healthOut', contains: 'knowsuite',
    extra: null },
  { tab: 'eval', file: 'ks_eval.png', marker: '#esList', contains: '储能论文知识库',
    extra: async (p) => { const it = await p.$('#runList .item'); if (it) { await it.click(); await new Promise(r=>setTimeout(r,1200)); } } },
  { tab: 'version', file: 'ks_version.png', marker: '#chainList', contains: '宽频振荡辨识论文',
    extra: async (p) => { const it = await p.$('#chainList .item'); if (it) { await it.click(); await new Promise(r=>setTimeout(r,1200)); } } },
  { tab: 'oem', file: 'ks_oem.png', marker: '#brandList', contains: '电科智库', extra: null },
  { tab: 'video', file: 'ks_video.png', marker: '#jobList', contains: '组会报告_储能控制策略',
    extra: null },
];

(async () => {
  const browser = await puppeteer.launch({ executablePath: EDGE, headless: true,
    args: ['--no-first-run', '--hide-scrollbars', '--force-device-scale-factor=1.5'] });
  let fail = 0;
  for (const t of TABS) {
    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 860, deviceScaleFactor: 1.5 });
    try {
      await page.goto(BASE + t.tab, { waitUntil: 'networkidle0', timeout: 30000 });
      // 等待数据标记真实渲染（最多 15s）
      await page.waitForFunction(
        (sel, kw) => { const el = document.querySelector(sel); return el && el.textContent.includes(kw); },
        { timeout: 15000 }, t.marker, t.contains);
      if (t.extra) { try { await t.extra(page); } catch (e) { console.log(t.tab, 'extra warn:', e.message); } }
      await new Promise(r => setTimeout(r, 600));
      await page.screenshot({ path: OUT + '\\' + t.file });
      const kb = Math.round(fs.statSync(OUT + '\\' + t.file).size / 1024);
      console.log('OK  ', t.tab, '->', t.file, kb + 'KB', '(data verified: "' + t.contains + '")');
    } catch (e) {
      console.log('FAIL', t.tab, ':', e.message.split('\n')[0]);
      fail++;
    }
    await page.close();
  }
  await browser.close();
  console.log(fail ? 'SOME FAILED: ' + fail : 'ALL SCREENSHOTS OK');
})().catch(e => { console.error('FATAL', e.message); process.exit(1); });
