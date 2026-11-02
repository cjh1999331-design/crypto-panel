const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const root = path.resolve(__dirname,'..');
const fixture = name => JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures',name),'utf8'));
const populated = JSON.parse(execFileSync('python3',['-c',"import sys,json;sys.path.insert(0,'tools');from make_snapshot import build_team;print(json.dumps(build_team('tests/fixtures/team')))"],{cwd:root,encoding:'utf8'}));
const market = fixture('market.json');
const snapshot = fixture('snapshot.json');
// Adapt the existing account fixtures to the public account.json contract.
const publicSnapshot = {
 mode:'paper',source:'测试公开快照',updated_at:snapshot.generated_at,
 accounts:snapshot.accounts.filter(a=>['paper_main','paper_meeting'].includes(a.id)).map(a=>({
  ...a,mode:'paper',equity:a.marked_equity,daily_pnl:a.day_start==null?null:a.marked_equity-a.day_start,
  daily_loss_limit:a.risk.daily_loss_limit,equity_curve:a.equity,fills:[],strategies:{},strategy_enabled:true,
 })),decisions:{status:'missing',symbols:{},blackout_windows:[]}
};
const artifacts = process.env.SCREENSHOT_DIR || '/tmp/crypto-panel-team-check';
const base = process.env.PANEL_URL || 'http://127.0.0.1:8018/';
(async () => {
 fs.mkdirSync(artifacts,{recursive:true});
 const browser = await chromium.launch({executablePath:process.env.CHROME_PATH || '/usr/bin/google-chrome',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
 try {
  const page=await browser.newPage({viewport:{width:1600,height:1100}});
  const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});
  // 外部市场数据用公开格式的本地示例，团队文件本身仍从 HTTP 服务器读取。
  await page.route('https://www.okx.com/api/v5/**',route=>{
    const name=new URL(route.request().url()).pathname;
    const data=name.endsWith('/tickers') ? market.tickers : name.endsWith('/candles') ? market.candles : name.endsWith('/funding-rate') ? market.funding : market.interest;
    return route.fulfill({json:data});
  });
  await page.goto(base);
  await page.waitForFunction(()=>!document.querySelector('#team-updated').textContent.includes('等待团队数据'));
  assert.equal(await page.locator('.role-card').count(),6);
  await page.route('**/paper/team.json?*',route=>route.fulfill({json:fixture('team-empty.json')}));
  await page.reload();
  await page.evaluate(()=>{document.querySelector('#timeline-fold').open=true;});
  await page.waitForFunction(()=>document.querySelector('#team-updated').textContent.includes('团队待命'));
  await page.waitForFunction(()=>document.querySelectorAll('#conditions li').length===6 && document.querySelectorAll('#price-chart canvas').length>0);
  assert.equal(await page.locator('.role-card').count(),6);
  assert.equal(await page.locator('.team-badge.idle').count(),6);
  assert.equal(await page.locator('.grade-none').count(),6);
  assert.equal(await page.locator('#team-timeline').innerText(),'暂无记录');
  await page.screenshot({path:path.join(artifacts,'team-empty-desktop.png')});
  console.log('真实数据 HTTP 加载通过；空团队示例：6 张待命卡、无评级、暂无记录');

  await page.route('**/paper/team.json?*',route=>route.fulfill({json:populated}));
  await page.route('**/paper/snapshot.json?*',route=>route.fulfill({json:snapshot}));
  await page.route('**/paper/account.json?*',route=>route.fulfill({json:publicSnapshot}));
  await page.reload();
  await page.evaluate(()=>{document.querySelector('#timeline-fold').open=true;});
  await page.waitForFunction(()=>document.querySelectorAll('.team-entry').length===8);
  await page.waitForFunction(()=>document.querySelector('[data-role="trader"]').textContent.includes('209.00'));
  assert.equal(await page.locator('.team-badge.working').count(),2);
  assert.equal(await page.locator('.team-badge.done').count(),2);
  assert.equal(await page.locator('.team-badge.idle').count(),2);
  assert.match(await page.locator('[data-role="risk"] .team-metric').innerText(),/当前 0 仓 · 2 个盘/);
  assert.match(await page.locator('[data-role="trader"] .team-metric').innerText(),/当前合计权益 209.00 USDT/);
  assert.match(await page.locator('[data-role="tech"] .team-metric').innerText(),/1 小时六条件/);
  assert.equal(await page.locator('#room-risk-params .risk-config').count(),2);
  assert.match(await page.locator('.team-entry').first().innerText(),/20:40 UTC\+7/);
  assert.match(await page.locator('.team-entry').first().innerText(),/P6/);
  await page.screenshot({path:path.join(artifacts,'team-populated-desktop.png')});
  await page.locator('[data-team-role="tech"]').click();
  assert.equal(await page.locator('.team-entry').count(),2);
  await page.locator('#team-meeting').selectOption('示例会议乙');
  assert.equal(await page.locator('.team-entry').count(),1);
  await page.locator('[data-team-role="risk"]').click();
  assert.equal(await page.locator('#team-timeline').innerText(),'暂无记录');
  await page.locator('#team-meeting').selectOption('');
  assert.equal(await page.locator('.team-entry').count(),1);
  await page.locator('[data-team-role=""]').click();
  assert.equal(await page.locator('.team-entry').count(),8);
  console.log('示例团队：状态/评级/时间/倒序/组合筛选/当前指标排除历史盘：通过');

  await page.locator('[data-nav="paper"]').click();
  await page.waitForSelector('#paper-cards .stat');
  assert.equal(await page.locator('#paper-cards .archived').count(),4);
  assert.equal(await page.locator('#account-tabs .archived').count(),4);
  await page.locator('#account-tabs .archived').first().click();
  assert.match(await page.locator('#risk').innerText(),/已停止 · 历史/);
  assert.match(await page.locator('#paper-price-time').innerText(),/历史持仓快照/);
  assert.equal(await page.locator('#positions-label').innerText(),'历史持仓');
  await page.screenshot({path:path.join(artifacts,'team-history-paper.png')});
  await page.locator('[data-nav="home"]').click();
  await page.waitForSelector('#home-page canvas');
  await page.locator('#home-page [data-timeframe="4H"]').click();
  assert.match(await page.locator('[data-role="tech"] .team-metric').innerText(),/1 小时/);
  for (const width of [390,360,320]) {
    await page.setViewportSize({width,height:1000});
    await page.waitForTimeout(200);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`横向溢出 ${width}`);
    assert.equal(await page.locator('.role-cards').evaluate(el=>getComputedStyle(el).gridTemplateColumns.split(' ').length),2);
    if(width===390) {
      await page.screenshot({path:path.join(artifacts,'team-populated-mobile.png'),fullPage:true});
      await page.locator('.team-panel').screenshot({path:path.join(artifacts,'team-timeline-mobile.png')});
    }
  }
  // 更新后日志为空、全部盘停止时，不保留旧的当前数字。
  const empty={schema_version:1,status:{updated_at:null,meeting:null,phase:null,roles:{}},log:[]};
  await page.route('**/paper/team.json?*',route=>route.fulfill({json:empty}));
  await page.route('**/paper/snapshot.json?*',route=>route.fulfill({json:{...snapshot,generated_at:'2026-11-02T13:41:00Z',accounts:snapshot.accounts.map(a=>({...a,status:'已停止'}))}}));
  await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));
  await page.route('**/paper/account.json?*',route=>route.fulfill({json:{...publicSnapshot,updated_at:'2026-11-02T13:41:00Z',accounts:publicSnapshot.accounts.map(a=>({...a,status:'已停止',strategy_enabled:false}))}}));
  await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));
  await page.waitForFunction(()=>document.querySelector('#strategy-states').textContent.includes('已停止'));
  assert.match(await page.locator('[data-role="trader"] .team-metric').innerText(),/209.00/);
  assert.equal(await page.locator('#team-timeline').innerText(),'暂无记录');
  assert.equal(await page.locator('#total-equity').innerText(),'209.00');
  assert.deepEqual(errors,[]);
  console.log('历史盘标签/灰色，停止后保留真实资金/团队刷新为空，手机 390/360/320 无溢出：通过；控制台与页面异常：0');
  console.log('截图：'+artifacts);
 } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exit(1)});
