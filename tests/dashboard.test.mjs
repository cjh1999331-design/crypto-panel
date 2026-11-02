import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { validSnapshot, accountMetrics, roomMetrics, technicalStatus } from '../assets/dashboard.mjs';
const now = Date.parse('2026-11-02T01:00:00Z');
function account(id, limit=.05) {
  return {id,name:id,balance:100,marked_equity:100,initial:100,day:'2026-11-02',day_start:100,positions:[],trades:[],equity:[],risk:{risk_per_trade:.01,daily_loss_limit:limit,max_positions:3,leverage:3,blocked:false}};
}
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-9, `${a} != ${b}`);
test('快照支持动态新增主力盘、交易室盘；拒绝重复和缺失风控参数',()=>{
 const accounts=['paper_1h','paper_4h','paper_1h_aggr','paper_4h_aggr','paper_main','paper_meeting'].map(id=>account(id));
 const s={schema_version:1,generated_at:new Date(now).toISOString(),accounts};
 assert.equal(validSnapshot(s),true);assert.equal(validSnapshot({...s,accounts:accounts.slice(4)}),true);
 assert.equal(validSnapshot({...s,accounts:[]}),false);
 assert.equal(validSnapshot({...s,accounts:[accounts[0],accounts[0]]}),false);
 assert.equal(validSnapshot({...s,accounts:[{...accounts[0],risk:{}}]}),false);
});
test('各盘独立 5% / 8% 上限，精确边界锁仓，亏损最大的盘显示自己的剩余额度',()=>{
 const old={...account('paper_1h'),balance:96},main={...account('paper_main',.08),balance:94};
 const s={accounts:[old,main]};const m=roomMetrics(s,[],now);
 assert.equal(m.worst.account.id,'paper_main');near(m.worst.remaining,.02);assert.equal(m.locked,false);
 assert.equal(accountMetrics({...main,balance:92},[],now).locked,true);
 assert.equal(accountMetrics({...old,balance:95},[],now).locked,true);
 near(accountMetrics({...main,balance:92},[],now).remaining,0);
 const blocked={...main,risk:{...main.risk,blocked:true}};
 assert.equal(roomMetrics({accounts:[blocked,old]},[],now).locked,true);
});
test('总权益与盈亏按全部盘、真实本金汇总；持仓浮盈遵循逐仓亏损下限',()=>{
 const main={...account('paper_main',.08),balance:90,positions:[{symbol:'ZEC-USDT-SWAP',side:1,qty:2,entry:100,margin:10}]};
 const m=roomMetrics({accounts:[main,account('paper_meeting')]},[{id:'ZEC-USDT-SWAP',last:80}],now);
 assert.equal(m.positions,1);assert.equal(m.equity,180);near(m.pnl,-10);assert.equal(m.live,true);
 const snapshot=roomMetrics({accounts:[{...main,marked_equity:91,initial:null}]},[],now);
 assert.equal(snapshot.equity,91);assert.equal(snapshot.live,false);assert.equal(snapshot.pnl,null);
});
test('UTC+7 日界和缺失基准不伪造日亏，旧交易日与冻结状态不冒充今天',()=>{
 const a={...account('paper_main',.08),balance:90,risk:{...account('paper_main',.08).risk,blocked:true}};
 assert.equal(accountMetrics(a,[],Date.parse('2026-11-01T17:00:00Z')).locked,true);
 const stale=accountMetrics(a,[],Date.parse('2026-11-02T17:00:00Z'));
 assert.equal(stale.loss,null);assert.equal(stale.locked,false);
 assert.equal(accountMetrics({...a,day_start:null},[],now).remaining,null);
 const m=roomMetrics({accounts:[{...a,day:null}]},[],now);assert.equal(m.worst,null);assert.equal(m.incompleteDay,true);
});
test('技术卡只使用已收盘的 1 小时样本，正确显示金叉 / 死叉',()=>{
 const bars=Array.from({length:250},(_,i)=>({time:now/1000+i*3600,open:100+i,high:102+i,low:99+i,close:101+i,volume:10,turnover:1000,confirm:'1'}));
 const rising=technicalStatus(bars);assert.match(rising.cross,/金叉/);assert.ok(rising.count>=0&&rising.count<=7);
 const pending={...bars.at(-1),time:bars.at(-1).time+3600,close:1,confirm:'0'};assert.deepEqual(technicalStatus([...bars,pending]),rising);
 const falling=bars.map((b,i)=>({...b,open:400-i,close:399-i,high:401-i,low:398-i}));assert.match(technicalStatus(falling).cross,/死叉/);
 assert.equal(technicalStatus(bars.slice(0,30)).count,null);
});
test('历史盘不计入当前权益、持仓、盈亏、日亏与锁仓，全部停止时无当前指标',()=>{
 const archived={...account('paper_1h'),status:'已停止',balance:10,positions:[{}],risk:{...account('paper_1h').risk,blocked:true}};
 const main={...account('paper_main'),status:'运行中',balance:104};
 const m=roomMetrics({accounts:[archived,main]},[],now);
 assert.equal(m.equity,104);assert.equal(m.positions,0);assert.equal(m.locked,false);
 assert.equal(m.accounts.length,1);assert.equal(m.worst.account.id,'paper_main');near(m.pnl,4);
 assert.equal(roomMetrics({accounts:[archived]},[],now),null);
 const fixture=JSON.parse(readFileSync(new URL('./fixtures/snapshot.json',import.meta.url),'utf8'));
 assert.equal(validSnapshot(fixture),true);
 assert.equal(validSnapshot({...fixture,accounts:[{...main,status:'错误'}]}),false);
});
test('支持主力盘同向风险与分档杠杆，缺少真实限制时拒绝',()=>{
 const main={...account('paper_main'),risk:{risk_per_trade:.03,daily_loss_limit:.08,max_positions:null,leverage:null,
  same_direction_risk_limit:.05,leverage_tiers:{turnover_gte_50000000:10,turnover_lt_50000000:5,threshold_usdt:50000000}}};
 const s={schema_version:1,generated_at:new Date(now).toISOString(),accounts:[main]};
 assert.equal(validSnapshot(s),true);
 assert.equal(validSnapshot({...s,accounts:[{...main,risk:{...main.risk,leverage_tiers:null}}]}),false);
 assert.equal(validSnapshot({...s,accounts:[{...main,risk:{...main.risk,max_positions:-1}}]}),false);
});
