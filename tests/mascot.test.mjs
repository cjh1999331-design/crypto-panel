import test from 'node:test';
import assert from 'node:assert/strict';
import {Mascot,mascotState,isDrag,motionEnabled} from '../assets/mascot.mjs';
import {validEvents} from '../assets/state.mjs';
import {validAccount,strategyState} from '../assets/account.mjs';
import {validSnapshot} from '../assets/dashboard.mjs';
import {readFileSync} from 'node:fs';
const now=Date.parse('2026-11-02T19:00Z'),ts=new Date(now).toISOString();
const base={now,updated_at:ts,accounts:[{id:'paper_main',status:'运行中',positions:[],fills:[],daily_pnl:1,day:'2026-11-03'}]};
const state=s=>mascotState(s).state;
test('吉祥物抽屉只展示当前四名成员，旧报告不会让旧成员重新出现',()=>{
 const list={innerHTML:''};
 const report=title=>({ts,title,summary:'公开摘要',grade:'A'});
 const roles=Object.fromEntries(['gork','claude','codex','grok','umi','tech','industry','news','risk','trader'].map(role=>[role,{last_report:report(role+'报告')}]));
 const team={status:{roles},log:[{...report('Grok最新报告'),ts:new Date(now+1000).toISOString(),role:'grok'},
  {...report('旧成员日志'),role:'trader'}]};
 Mascot.prototype.renderReports.call({team,drawer:{querySelector:()=>list}});
 assert.equal((list.innerHTML.match(/<article>/g)||[]).length,4);
 assert.match(list.innerHTML,/gork 总指挥/);assert.match(list.innerHTML,/claude/);assert.match(list.innerHTML,/Codex/);assert.match(list.innerHTML,/Grok最新报告/);
 assert.doesNotMatch(list.innerHTML,/umi 主席|umi报告|tech报告|industry报告|news报告|risk报告|trader报告|旧成员/);
});
test('mascotState is deterministic and obeys offline > paused > stop > open > wake > profit > idle',()=>{
 const s=structuredClone(base);s.accounts[0].daily_pnl=null;
 assert.equal(state(s),'idle');assert.deepEqual(mascotState(s),mascotState(structuredClone(s)));
 s.accounts[0].daily_pnl=1;assert.equal(state(s),'happy');assert.match(mascotState(s).message,/\+1U/);
 s.events=[{ts,type:'异动',wake:true}];assert.equal(state(s),'alert');assert.match(mascotState(s).message,/1 条/);
 s.accounts[0].fills=[{timestamp:ts,kind:'open'}];assert.equal(state(s),'excited');
 s.events.push({ts,type:'trade_closed',reason:'止损'});assert.equal(state(s),'sad');
 s.pause={paused:true};assert.equal(state(s),'paused');
 s.updated_at='2026-11-02T18:44:59Z';assert.equal(state(s),'offline');
 assert.equal(state({...base,dataDisconnected:true}),'offline');assert.equal(state(null),'offline');assert.equal(state({...base,now:NaN}),'offline');
});
test('recent and UTC+7 boundaries; missing values never invent numbers',()=>{
 const s=structuredClone(base);s.accounts[0].day='2026-11-02';s.events=[{ts:'2026-11-02T18:00Z',type:'trade_closed',reason:'止损'},{ts:'2026-11-02T19:01Z',type:'异动',wake:true}];
 assert.equal(state(s),'idle');assert.doesNotMatch(mascotState(s).message,/\d/);
 s.events=[{ts,type:'异动',wake:false}];assert.equal(state(s),'idle');
 s.events=[{ts:'2026-11-02T18:45Z',type:'异动',wake:true}];assert.equal(state(s),'alert');
 assert.equal(state({...s,updated_at:'2026-11-02T18:45Z'}),'alert');
});
test('drag threshold, low device and reduced motion',()=>{
 assert.equal(isDrag({x:0,y:0},{x:4,y:4}),false);assert.equal(isDrag({x:0,y:0},{x:8,y:0}),false);assert.equal(isDrag({x:0,y:0},{x:9,y:0}),true);
 assert.equal(motionEnabled(),true);for(const options of [{reduced:true},{hardwareConcurrency:2},{deviceMemory:2}])assert.equal(motionEnabled(options),false);
});
test('published reset contracts remain valid, strategy state and alert wake survive validation',()=>{
 const read=name=>JSON.parse(readFileSync(new URL('../paper/'+name+'.json',import.meta.url),'utf8'));
 assert.equal(validAccount(read('account')),true);assert.equal(validSnapshot(read('snapshot')),true);
 const account=read('account').accounts[0];
 const state=strategyState(account,{});
 assert.ok(['暂停','运行中','已停止','未启动'].includes(state), state);
 if(account.pause?.paused || account.status==='暂停') assert.equal(state,'暂停');
 const e={ts,type:'异动',coin:null,strategy:null,direction:null,price:null,reason:'放量',wake:true};
 assert.equal(validEvents({schema_version:1,events:[e]}),true);assert.equal(validEvents({schema_version:1,events:[{...e,wake:'true'}]}),false);
});
