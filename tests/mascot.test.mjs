import test from 'node:test';
import assert from 'node:assert/strict';
import {mascotState,isDrag,motionEnabled} from '../assets/mascot.mjs';
import {validEvents} from '../assets/state.mjs';
import {validAccount,strategyState} from '../assets/account.mjs';
import {validSnapshot} from '../assets/dashboard.mjs';
import {readFileSync} from 'node:fs';
const now=Date.parse('2026-11-02T19:00Z'),ts=new Date(now).toISOString();
const base={now,updated_at:ts,accounts:[{id:'paper_main',status:'运行中',positions:[],fills:[],daily_pnl:1,day:'2026-11-03'}]};
const state=s=>mascotState(s).state;
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
test('published reset contracts remain valid, paused strategy and alert wake survive validation',()=>{
 const read=name=>JSON.parse(readFileSync(new URL('../paper/'+name+'.json',import.meta.url),'utf8'));
 assert.equal(validAccount(read('account')),true);assert.equal(validSnapshot(read('snapshot')),true);
 assert.equal(strategyState(read('account').accounts[0],{}),'暂停');
 const e={ts,type:'异动',coin:null,strategy:null,direction:null,price:null,reason:'放量',wake:true};
 assert.equal(validEvents({schema_version:1,events:[e]}),true);assert.equal(validEvents({schema_version:1,events:[{...e,wake:'true'}]}),false);
});
