// NODE_PATH may point at an existing Playwright installation; no server is needed.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const root = path.resolve(__dirname, '..');
  const browser = await chromium.launch({executablePath:process.env.CHROME_PATH || '/usr/bin/google-chrome',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.route('http://panel.test/**', route => {
      const name = new URL(route.request().url()).pathname;
      if (name === '/') return route.fulfill({contentType:'text/html',body:'<div id="mascot"></div><dialog id="drawer"><button data-close>关闭</button><div id="mascot-report-list"></div></dialog><div id="cards"></div>'});
      return route.fulfill({path:path.join(root,name),contentType:'text/javascript'});
    });
    await page.goto('http://panel.test/');
    await page.evaluate(async () => {
      const {Mascot} = await import('/assets/mascot.mjs');
      const {ROLES,teamCards} = await import('/assets/team.mjs');
      const ts = new Date().toISOString();
      const roles = Object.fromEntries([...Object.keys(ROLES),'umi','tech','industry','news','risk','trader'].map(role => [role,{status:'已完成',task:role,last_report:{ts,title:role+' 报告 <script>',summary:'公开摘要',grade:'A'}}]));
      const team = {schema_version:1,status:{updated_at:ts,roles},log:[]};
      const mascot = new Mascot(document.querySelector('#mascot'),document.querySelector('#drawer'));
      mascot.update({updated_at:ts,accounts:[{id:'paper_main',status:'暂停'}]},team);
      document.querySelector('#cards').innerHTML = teamCards(team,{}, {now:Date.parse(ts),snapshotAt:ts});
    });
    await page.locator('#mascot-reports').click();
    assert.equal(await page.locator('#drawer').isVisible(),true);
    assert.equal(await page.locator('#mascot-report-list article').count(),4);
    assert.equal(await page.locator('#cards .role-card').count(),4);
    const text = await page.locator('#mascot-report-list').innerText();
    for (const name of ['gork 总指挥','claude','Codex','Grok']) assert.ok(text.includes(name));
    assert.doesNotMatch(text,/umi 主席|umi 报告|tech 报告|industry 报告|news 报告|risk 报告|trader 报告/);
    assert.equal(await page.locator('#mascot-report-list script').count(),0);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#drawer').isVisible(),false);
    assert.deepEqual(errors,[]);
    console.log('团队卡片与吉祥物抽屉：仅 gork、claude、Codex、Grok；旧成员隐藏、文本转义、Esc 关闭、页面异常 0。');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode=1; });
