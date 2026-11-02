import test from 'node:test';
import assert from 'node:assert/strict';
import {baseQuantity,positionAmounts,orderAmounts,quoteFor,pendingOrders,chartLevels} from '../assets/portfolio.mjs';
import {chartUniverse} from '../assets/scan.mjs';
import {validManualStatus} from '../assets/account.mjs';
import {tradeMarkers} from '../assets/realtime.mjs';
const p={symbol:'SPCX-USDT-SWAP',qty:2,side:1,entry:100,stop:95,take_profit:115,margin:40,mark_price:102};
const account=(positions=[p],manual_status=[],pending_orders=[])=>({mode:'paper',accounts:[{id:'paper_main',status:'运行中',positions,manual_status,pending_orders,fills:[]}]});
test('多空浮盈、名义价值和保证金百分比独立计算；零保证金不除零',()=>{
 for(const side of [1,-1])for(const mark of [90,110]){
  const result=positionAmounts({...p,side},mark);
  assert.equal(result.notional,2*mark);assert.equal(result.pnl,side*2*(mark-100));
  assert.equal(result.percent,result.pnl/40*100);
 }
 assert.equal(positionAmounts({...p,margin:0},110).percent,null);
 assert.equal(positionAmounts({...p,mark_price:null,unrealized_pnl:3},null).pnl,3);
});
test('币数不会重复乘面值；明确张数才乘 ctVal × ctMult；快照名义价值保持原口径随价更新',()=>{
 assert.equal(baseQuantity({...p,ctVal:.01,ctMult:2}),2);
 assert.equal(baseQuantity({...p,qty_unit:'contracts',ctVal:.01,ctMult:2}),.04);
 assert.equal(baseQuantity({...p,qty_unit:'contracts'}),null);
 assert.equal(validManualStatus([{status:'pending',qty:10,qty_unit:'contracts'}]),false);
 assert.equal(validManualStatus([{status:'pending',qty:10,qty_unit:'contracts',ctVal:.1}]),true);
 const contracts=positionAmounts({...p,qty_unit:'contracts',ctVal:.01,ctMult:2},110);
 assert.equal(contracts.notional,4.4);assert.equal(contracts.pnl,.4);assert.equal(contracts.percent,1);
 assert.equal(positionAmounts({...p,notional:408},102).notional,408);
 assert.equal(positionAmounts({...p,notional:408},110).notional,440);
 assert.equal(positionAmounts({...p,notional:408,mark_price:null},110).notional,408);
 assert.equal(positionAmounts({...p,notional:408},null).notional,408);
});
test('挂单按限价计名义价值；多空绝对价差风险，优先 planned_risk，不把缺数量当成零',()=>{
 for(const side of [1,-1])assert.deepEqual(orderAmounts({...p,side,limit:100,stop:side===1?95:105}),{notional:200,risk:10});
 assert.deepEqual(orderAmounts({...p,limit:100,planned_risk:12,notional:210}),{notional:210,risk:12});
 assert.deepEqual(orderAmounts({limit:100,stop:90}),{notional:null,risk:null});
 assert.equal(orderAmounts({...p,qty_unit:'contracts',ctVal:.1,limit:100}).risk,1);
});
test('报价来源和时效：WS 优先、失败轮询、失效或未来包回退快照标记价',()=>{
 const now=100000,tickers=[{id:p.symbol,last:104}],quotes=new Map([[p.symbol,{price:105,at:now}]]);
 assert.equal(quoteFor(p,quotes,tickers,now,now).mark,105);
 quotes.set(p.symbol,{price:105,at:now-45001});
 assert.deepEqual(quoteFor(p,quotes,tickers,now,now),{mark:104,source:'轮询实时价'});
 assert.equal(quoteFor(p,quotes,tickers,now-24001,now).mark,102);
 quotes.set(p.symbol,{price:110,at:now+60001});
 assert.match(quoteFor(p,quotes,[],0,now).source,/快照标记价/);
});
test('所有持仓/会议 pending/maker 都可切图，最新开仓默认；结束状态退出；实盘不混入旧扫描',()=>{
 const manual={symbol:'ZEC-USDT-SWAP',status:'pending',side:1,limit:1200};
 const maker={symbol:'INTC-USDT-SWAP',status:'pending',side:-1,limit:60};
 const a=account([{...p,entry_time:'2026-11-02T01:00:00Z'},{...p,symbol:'BTC-USDT-SWAP',entry_time:'2026-11-02T02:00:00Z'}],[manual,{...manual,status:'filled'}],[maker]);
 assert.equal(pendingOrders(a).length,2);
 const u=chartUniverse(a,null,'ETH-USDT-SWAP');assert.equal(u.defaultSymbol,'BTC-USDT-SWAP');
 assert.equal(u.choices.filter(c=>c.held || c.pending).length,4);
 assert.equal(chartUniverse(account([], [manual],[maker]),null,'ETH-USDT-SWAP').defaultSymbol,'ZEC-USDT-SWAP');
 assert.equal(chartUniverse(account(),null,'ETH-USDT-SWAP').choices.find(c=>c.id===p.symbol).positions.length,1);
 assert.equal(pendingOrders({mode:'live',accounts:[]},{manual_status:[manual],pending_orders:[maker]}).length,0);
 assert.equal(pendingOrders(null,{manual_status:[manual],pending_orders:[maker]}).length,2);
 assert.equal(pendingOrders(account([],[],[]),{manual_status:[manual],pending_orders:[maker]}).length,0);
});
test('每个币的水平线和开平仓标记隔离，会议账户与重复成交不污染图表',()=>{
 const a=account();a.accounts[0].fills=[{symbol:p.symbol,timestamp:new Date(210000).toISOString(),kind:'open',side:1},{symbol:p.symbol,timestamp:new Date(310000).toISOString(),kind:'close',side:1}];
 a.accounts.push({...a.accounts[0],id:'paper_meeting'});
 const bars=[{time:100},{time:200},{time:300}];
 assert.deepEqual(tradeMarkers(a,p.symbol,bars).map(m=>m.text),['开仓多','平仓多']);
 assert.deepEqual(tradeMarkers(a,'ZEC-USDT-SWAP',bars),[]);
 const levels=chartLevels([p,{...p,symbol:'ZEC-USDT-SWAP'}],[{symbol:p.symbol,limit:99},{symbol:'INTC-USDT-SWAP',limit:60}],p.symbol);
 assert.deepEqual(levels.map(l=>[l.title,l.price]),[['入场',100],['止损',95],['止盈',115],['挂单限价',99]]);
});
