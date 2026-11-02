const { chromium } = require('playwright');
const assert = require('node:assert/strict');
(async () => {
 const browser=await chromium.launch({executablePath:process.env.CHROME_PATH || '/usr/bin/google-chrome',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
 try {
 const page=await browser.newPage({viewport:{width:1440,height:1050}});
 const base=process.env.PANEL_URL || 'http://127.0.0.1:8008/';
 const artifacts=process.env.SCREENSHOT_DIR || '/tmp';
 const errors=[],networkErrors=[];page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')(m.text().includes('WebSocket connection')?networkErrors:errors).push(m.text())});
 await page.goto(base);
 await page.waitForFunction(()=>document.querySelectorAll('#conditions li').length===6 && document.querySelectorAll('#price-chart canvas').length>0,{},{timeout:45000});
 await page.waitForTimeout(6000);
 console.log('home',await page.locator('#connection-text').innerText(),'roles',await page.locator('.role-card').count(),'BT60',await page.locator('#bt60-status').innerText(),'alerts',await page.locator('#alerts').innerText());
 console.log('cards',await page.locator('#role-cards').innerText());
 console.log('chart errors',await page.locator('#chart-error').isVisible(),await page.locator('#equity-error').isVisible());
 console.log('overflow desktop',await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth));
 await page.screenshot({path:artifacts+'/umi-home-desktop.png',fullPage:true});
 await page.locator('#home-page [data-timeframe="4H"]').click();await page.waitForFunction(()=>document.querySelector('#analysis-period').innerText.includes('4 小时'));
 assert.match(await page.locator('.role-card').nth(1).innerText(),/1 小时/);
 await page.locator('[data-nav="market"]').click();
 await page.locator('#search').fill('ZEC');console.log('search',await page.locator('#market-body tr').count());await page.locator('#search').fill('');
 await page.locator('[data-sort="change"]').click();
 await page.goto(new URL('#/coin/BTC-USDT-SWAP',base).href);
 await page.waitForFunction(()=>document.querySelectorAll('#conditions li').length===6,{},{timeout:45000});
 console.log('coin canvases',await page.locator('#coin-page canvas').count());
 await page.locator('[data-nav="paper"]').click();await page.waitForSelector('#account-tabs button');
 console.log('paper',await page.locator('#paper-cards .stat').count(),'equity',await page.locator('#paper-page canvas').count());
 await page.locator('#account-tabs button').last().click();if(await page.locator('#trades-next').isEnabled()) await page.locator('#trades-next').click();
 await page.locator('[data-nav="home"]').click();await page.waitForSelector('#home-page canvas');
 for(const width of [390,360,320]){
  await page.setViewportSize({width,height:844});await page.waitForTimeout(300);
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);assert.equal(overflow,false,`overflow ${width}`);
  assert.equal(await page.locator('.role-cards').evaluate(el=>getComputedStyle(el).gridTemplateColumns.split(' ').length),2);
  if(width===390)await page.screenshot({path:artifacts+'/umi-home-mobile.png',fullPage:true});
 }
 console.log('mobile widths 390/360/320: no overflow, 2 columns');
 console.log('外部 WebSocket 网络错误',networkErrors.length);
 console.log('console/page errors',JSON.stringify(errors));
 assert.deepEqual(errors,[]);
 } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exit(1)});
