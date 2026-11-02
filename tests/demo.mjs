import {teamCards,ROLES} from '../assets/team.mjs';
import {configureMotion,roleEffect,reducedMotion} from '../assets/effects.mjs';
configureMotion();
const fixture=await fetch('./fixtures/demo.json').then(r=>r.json());
let timers=[];
function run(){
 timers.forEach(clearTimeout);timers=[];
 const base=fixture.team,now=Date.parse(base.generated_at);
 const render=status=>{
  const data=structuredClone(base);for(const r of Object.values(data.status.roles))r.status=status;
  const snapshotAt=new Date(now-(status==='离线'?16*60000:0)).toISOString();
  document.querySelector('#role-cards').innerHTML=teamCards(data,{}, {now,snapshotAt,reduced:reducedMotion(),hidden:document.hidden});
 };
 document.documentElement.classList.add('has-live-state');
 fixture.scenes.forEach((scene,i)=>{
  timers.push(setTimeout(()=>{
   render(scene.status);document.querySelector('#demo-step').textContent=`演示数据 · ${i+1}/${fixture.scenes.length} · ${scene.label}`;
   if(scene.effect)Object.keys(ROLES).forEach((role,n)=>timers.push(setTimeout(()=>roleEffect(role,scene.effect,scene.sign),n*55)));
  },scene.at));
 });
}
document.querySelector('#replay').addEventListener('click',run);run();
