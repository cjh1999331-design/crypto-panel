import test from 'node:test';
import assert from 'node:assert/strict';
import { dayNumber, localDay, validAccount, summarizeAccounts, aggregateCurve, strategyState } from '../assets/account.mjs';
const now=Date.parse('2026-11-02T01:00:00Z');
const decision={status:'missing',symbols:{},blackout_windows:[]};
function account(id='paper_main') {return {id,mode:'paper',status:'运行中',equity:100,balance:100,initial:100,daily_pnl:0,daily_loss_limit:.08,day:'2026-11-02',day_start:100,positions:[],fills:[],equity_curve:[],risk:{blocked:false}};}
const data=(accounts=[account()])=>({mode:'paper',source:'公开快照',updated_at:new Date(now).toISOString(),accounts,decisions:decision});
test('统一账户支持 live、唯一公开别名、未启动 null；拒绝虚构未启动金额和错误成交额',()=>{
 assert.equal(validAccount(data()),true);
 const live={...account('live_main'),mode:'live'};assert.equal(validAccount({...data([live]),mode:'live'}),true);
 assert.equal(validAccount(data([account(),account()])),false);
 const unstarted={...account('paper_meeting'),status:'未启动',equity:null,balance:null,daily_pnl:null,daily_loss_limit:null};
 assert.equal(validAccount(data([unstarted])),true);
 assert.equal(summarizeAccounts(data([unstarted]),[],now),null);
 assert.equal(validAccount(data([{...unstarted,balance:0}])),false);
 const fill={timestamp:new Date(now).toISOString(),symbol:'BTC-USDT-SWAP',kind:'open',qty:2,price:10,notional:21};
 assert.equal(validAccount(data([{...account(),fills:[fill]}])),false);
});
test('UTC+7 日界、DAY N 和今日成交双边金额；不存在的盘不补零余额',()=>{
 assert.equal(localDay(Date.parse('2026-11-01T17:00:00Z')),'2026-11-02');
 assert.equal(dayNumber('2026-11-02',Date.parse('2026-11-02T16:59:59Z')),1);
 assert.equal(dayNumber('2026-11-02',Date.parse('2026-11-02T17:00:00Z')),2);
 assert.equal(dayNumber(undefined,now),1);
 const fills=['2026-11-01T16:59:59Z','2026-11-01T17:00:00Z','2026-11-02T00:10:00Z'].map((timestamp,i)=>({timestamp,notional:(i+1)*20}));
 const result=summarizeAccounts(data([{...account(),fills}]),[],now);
 assert.equal(result.today.length,2);assert.equal(result.turnover,100);assert.equal(result.balance,100);
 assert.equal(summarizeAccounts(data([{...account(),day:'2026-11-01'}]),[],now).accounts[0].loss,null);
});
test('SIZE 用标记名义金额、逐仓封顶权益；缺现价不偷用入场价，停止后保留真实资金',()=>{
 const position={symbol:'BTC-USDT-SWAP',side:1,qty:2,entry:100,margin:10,mark_price:95,unrealized_pnl:-10};
 const a={...account(),equity:90,positions:[position]};
 const m=summarizeAccounts(data([a]),[{id:position.symbol,last:80}],now);
 assert.equal(m.size,160);assert.equal(m.equity,90);assert.equal(m.positions[0].pnl,-40);
 const missing=summarizeAccounts(data([{...a,positions:[{...position,mark_price:null}]}]),[],now);
 assert.equal(missing.size,null);assert.equal(missing.equity,90);
 const stopped=summarizeAccounts(data([{...a,status:'已停止'}]),[{id:position.symbol,last:80}],now);
 assert.equal(stopped.balance,100);assert.equal(stopped.equity,90);assert.equal(stopped.accounts[0].state,'已停止');
});
test('8% 精确停手边界、事件窗口起止和策略状态优先级',()=>{
 const d={...decision,blackout_windows:[{start:'2026-11-02T01:00:00Z',end:'2026-11-02T02:00:00Z',symbols:['*']}]};
 assert.equal(strategyState(account(),d,now),'事件窗口禁开新仓');
 assert.equal(strategyState(account(),d,now+3600000),'运行中');
 assert.equal(strategyState({...account(),status:'已停止'},d,now),'已停止');
 const a={...account(),balance:92,equity:92};
 assert.equal(summarizeAccounts(data([a]),[],now).accounts[0].state,'已停手');
});
test('合计权益曲线按真实观测时间对齐；不回填首次记录以前的金额',()=>{
 const point=(h,equity)=>({timestamp:`2026-11-02T0${h}:00:00Z`,equity});
 const a={...account(),equity_curve:[point(1,100),point(3,102)]},b={...account('paper_meeting'),equity_curve:[point(2,80),point(3,81)]};
 const curve=aggregateCurve([a,b]);assert.deepEqual(curve.map(p=>p.value),[180,183]);
 assert.equal(curve[0].time,Date.parse('2026-11-02T02:00:00Z')/1000);
 assert.deepEqual(aggregateCurve([a,{...b,equity_curve:[]}]),[]);
});
