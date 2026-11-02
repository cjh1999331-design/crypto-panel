import test from 'node:test';
import assert from 'node:assert/strict';
import {drawdowns,equityRange,strategyStats,closeReason,riskProgress,blackoutCountdown,duration,curveSVG} from '../assets/history.mjs';
const t=n=>new Date(Date.parse('2026-11-01T00:00:00Z')+n*3600000).toISOString();
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-9,`${a} != ${b}`);
test('回撤按时序峰值，重复点去重，最大回撤起止与当前回撤独立',()=>{
 const p=[100,120,90,115,130,117].map((equity,i)=>({timestamp:t(i),equity}));
 const dd=drawdowns([...p].reverse());near(dd.max.amount,30);near(dd.max.percent,25);
 assert.equal(dd.max.start,t(1));assert.equal(dd.max.end,t(2));near(dd.current.amount,13);near(dd.current.percent,10);
 assert.equal(drawdowns([]).current,null);assert.equal(drawdowns([{timestamp:t(0),equity:0}]).current.percent,null);
 const flat=drawdowns([1,1,1].map((equity,i)=>({timestamp:t(i),equity})));assert.equal(flat.max.start,null);assert.equal(flat.current.amount,0);
 assert.match(curveSVG(p,dd),/回撤峰值/);assert.match(curveSVG(p,dd),/回撤低点/);
 assert.equal(equityRange([...p,p[0]],'all',Date.parse(t(8))).length,6);
});
test('日/周为最近24h/7d，仅使用范围内真实点，排除未来点',()=>{
 const points=[0,1,143,144,167,168,169].map(i=>({timestamp:t(i),equity:100+i}));
 assert.deepEqual(equityRange(points,'day',Date.parse(t(168))).map(p=>p.timestamp),[t(144),t(167),t(168)]);
 assert.equal(equityRange(points,'week',Date.parse(t(168))).length,6);
 assert.equal(equityRange(points,'day',Date.parse(t(300))).length,0);
});
test('策略统计：净盈亏、平均盈亏比、手续费/毛盈亏总和绝对值，零分母为缺失',()=>{
 const trades=[{strategy:'mean_reversion',pnl:10,fee:1,gross_pnl:12},{strategy:'mean_reversion',pnl:-4,fee:1,gross_pnl:-3},{strategy:'mean_reversion',pnl:0,fee:1,gross_pnl:1},{strategy:'manual',pnl:-2,fee:.1,gross_pnl:-1.9},{strategy:'breakout',pnl:5,fee:null,gross_pnl:6},{strategy:'other',pnl:999,fee:0,gross_pnl:999}];
 const [mr,bo,manual]=strategyStats(trades);assert.equal(mr.count,3);near(mr.winRate,100/3);near(mr.payoff,2.5);near(mr.average,2);near(mr.total,6);near(mr.feeRatio,30);
 assert.equal(bo.feeRatio,null);assert.equal(bo.payoff,null);assert.equal(manual.total,-2);
 assert.equal(strategyStats([])[0].average,null);assert.equal(strategyStats([])[0].winRate,null);
 assert.equal(strategyStats([{strategy:'manual',pnl:0,fee:1,gross_pnl:0}])[2].feeRatio,null);
});
test('实际运行器平仓原因映射，未知原因原样',()=>{
 for(const [raw,label] of Object.entries({stop_live:'止损',stop:'止损',target_live:'止盈',take_profit:'止盈',timeout:'到期',manual_close:'手动',paused_flatten:'手动（暂停平仓）',liquidation_live:'强平',decision_ban:'手动（决议禁开）',new_reason:'new_reason'}))assert.equal(closeReason(raw),label);
});
test('风险进度：UTC+7换日、8%熔断、多空独立5%、planned_risk优先、止损距离',()=>{
 const now=Date.parse('2026-11-02T18:00:00Z');
 const a={day:'2026-11-03',day_start:100,equity:96,positions:[{symbol:'BTC',side:1,entry:100,stop:95,qty:2,planned_risk:3,mark_price:100},{symbol:'ETH',side:1,entry:100,stop:98,qty:1,planned_risk:null,mark_price:100},{symbol:'SOL',side:-1,entry:100,stop:102,qty:1,mark_price:100}]};
 const r=riskProgress(a,now);near(r.daily.used,50);near(r.long.amount,5);near(r.long.used,100);near(r.short.amount,2);near(r.stops[0].distance,5);near(r.stops[2].distance,2);
 assert.equal(riskProgress({...a,day:'2026-11-02'},now).daily.used,null);
 assert.equal(riskProgress({...a,equity:90},now).daily.used,100);
 const missing=riskProgress({...a,positions:[{side:1}]},now);assert.equal(missing.long.used,null);assert.equal(missing.stops[0].distance,null);
 assert.equal(riskProgress(null,now).daily.ratio,null);
});
test('倒计时：[start,end)，生效窗口优先，重叠按最早结束，未来按最早开始',()=>{
 const w=(start,end)=>({start:t(start),end:t(end),symbols:['BTC-USDT-SWAP'],reason:'事件'}),rows=[w(10,12),w(2,8),w(3,5)];
 assert.equal(blackoutCountdown(rows,Date.parse(t(0))).window.start,t(2));
 const start=blackoutCountdown(rows,Date.parse(t(2)));assert.equal(start.active,true);assert.equal(start.milliseconds,6*3600000);
 assert.equal(blackoutCountdown(rows,Date.parse(t(4))).window.end,t(5));
 assert.equal(blackoutCountdown(rows,Date.parse(t(8))).active,false);
 assert.equal(blackoutCountdown(rows,Date.parse(t(12))),null);
 assert.equal(duration(90061000),'1天 01:01:01');assert.equal(duration(-1),'00:00:00');
});
