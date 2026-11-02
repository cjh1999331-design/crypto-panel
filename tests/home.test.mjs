import test from 'node:test';
import assert from 'node:assert/strict';
import {equitySVG,rangePoints} from '../assets/home.mjs';
import {coinIcon,coinIdentity} from '../assets/coins.mjs';
test('日/周/全部筛选真实观测点，不伪造范围边界或未来值',()=>{
 const now=1000000000,points=[{time:now/1000-8*86400,value:99},{time:now/1000-2*86400,value:101},{time:now/1000,value:100},{time:now/1000+1,value:103}];
 assert.deepEqual(['day','week','all'].map(r=>rangePoints(points,r,now).length),[1,2,3]);
 assert.equal(rangePoints([], 'day', now).length,0);
});
test('权益 SVG 空记录是100U平线，真实数据按时间间距绘制，单点可见',()=>{
 const empty=equitySVG([]);assert.match(empty,/暂无记录，100 USDT 平线/);assert.match(empty,/M16.00,84.00 L624.00,84.00/);assert.match(empty,/100 U/);
 assert.match(equitySVG([{time:1,value:104}]),/<circle/);
 const svg=equitySVG([{time:1,value:100},{time:2,value:99},{time:5,value:102}]);
 assert.match(svg,/L168.00,/);assert.match(svg,/data-points="3"/);assert.doesNotMatch(svg,/NaN|Infinity/);
});
test('本地图标固定尺寸和lazy加载；未知币使用稳定哈希彩色首字母，无外部请求',()=>{
 assert.equal(coinIdentity('BTC-USDT-SWAP').path,'./assets/coins/btc.svg');
 assert.match(coinIcon('BTC'),/width="26" height="26" loading="lazy"/);
 for(const symbol of ['SPCX','INTC','XAU']){
  assert.equal(coinIdentity(symbol).path,null);assert.doesNotMatch(coinIcon(symbol),/<img/);
  assert.match(coinIcon(symbol),new RegExp('>'+symbol[0]+'</span>'));
  assert.deepEqual(coinIdentity(symbol),coinIdentity(symbol+'-USDT-SWAP'));
 }
 assert.doesNotMatch(coinIcon('<script>'),/<script>/);
});
test('浅色主题正文、次要文字、涨跌与强调色在两种底色满足 AA 4.5:1',async()=>{
 const {readFile}=await import('node:fs/promises');
 const css=await readFile(new URL('../assets/style.css',import.meta.url),'utf8');
 const root=css.match(/:root\{([^}]+)\}/)[1];
 const rgb=hex=>(hex.length===4?[...hex.slice(1)].map(c=>c+c):hex.slice(1).match(/../g)).map(c=>parseInt(c,16)/255);
 const L=hex=>rgb(hex).map(c=>c<=.04045?c/12.92:((c+.055)/1.055)**2.4).reduce((s,c,i)=>s+c*[.2126,.7152,.0722][i],0);
 for(const token of ['text','muted','green','red','cyan','purple','amber']){
  const fg=root.match(new RegExp(`--${token}:(#[0-9a-f]+)`))[1];
  for(const bg of ['#fff','#f5f6f8'])assert.ok((L(bg)+.05)/(L(fg)+.05)>=4.5,`${token} on ${bg}`);
 }
 assert.doesNotMatch(css,/backdrop-filter|(?:radial|linear)-gradient/);
});
