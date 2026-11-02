import { coinIcon } from './coins.mjs';
const fmt=n=>Number.isFinite(n)?n.toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2}):'—';
const signed=n=>(n>0?'+':'')+fmt(n);
const tone=n=>Number.isFinite(n)?n>=0?'up':'down':'';
export function rangePoints(points,range,now=Date.now()) {
  const since=range==='day'?now/1000-86400:range==='week'?now/1000-7*86400:-Infinity;
  return points.filter(p=>p.time>=since && p.time<=now/1000);
}
export function equitySVG(points) {
  const rows=points.length?points:[{time:0,value:100},{time:1,value:100}];
  const values=rows.map(p=>p.value),lo=Math.min(...values),hi=Math.max(...values),pad=Math.max((hi-lo)*.15,1);
  const bottom=lo-pad,span=hi-lo+pad*2,start=rows[0].time,duration=rows.at(-1).time-start || 1;
  const x=p=>16+(p.time-start)/duration*608,y=v=>140-(v-bottom)/span*112;
  const path=rows.map((p,i)=>`${i?'L':'M'}${x(p).toFixed(2)},${y(p.value).toFixed(2)}`).join(' ');
  const stamp=t=>new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Bangkok',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(t*1000);
  return `<svg viewBox="0 0 640 180" role="img" aria-label="${points.length?'账户权益曲线':'暂无记录，100 USDT 平线'}" data-points="${points.length}">${[0,.5,1].map(n=>`<line x1="16" x2="624" y1="${28+n*112}" y2="${28+n*112}" class="equity-grid"/>`).join('')}<path d="${path}" fill="none" stroke="currentColor" stroke-width="2" vector-effect="non-scaling-stroke"/>${points.length===1?`<circle cx="16" cy="${y(rows[0].value)}" r="3" fill="currentColor"/>`:''}<text x="16" y="20">${fmt(hi)} USDT</text>${points.length?`<text x="16" y="172">${stamp(start)}</text><text x="624" y="172" text-anchor="end">${stamp(rows.at(-1).time)}</text>`:'<text x="624" y="172" text-anchor="end">100 U</text>'}</svg>`;
}
// Keep the shared candle panel mounted across quote updates; only one row is open.
export class HomePositions {
  constructor(host,parking,onChange) {
    this.host=host;this.parking=parking;this.onChange=onChange;this.positions=[];this.expanded=null;
    host.addEventListener('click',event=>{const button=event.target.closest('[data-position]');if(button)this.toggle(button.dataset.position);});
  }
  toggle(key) {
    this.expanded=this.expanded===key?null:key;
    this.mount();this.onChange(this.positions.find(p=>p.key===this.expanded));
  }
  mount() {
    const panel=document.getElementById('price-panel');
    const slot=this.expanded && [...this.host.querySelectorAll('.position-item')].find(e=>e.dataset.key===this.expanded)?.querySelector('.position-chart');
    if(panel && panel.parentElement!==(slot || this.parking))(slot || this.parking).append(panel);
    this.host.querySelectorAll('[data-position]').forEach(b=>b.setAttribute('aria-expanded',String(b.dataset.position===this.expanded)));
    this.host.querySelectorAll('.position-item').forEach(e=>{e.querySelector('.position-detail').hidden=e.dataset.key!==this.expanded;});
  }
  render(positions,paused) {
    this.positions=positions.map((p,i)=>({...p,key:`${p.symbol}:${p.side}:${i}`}));
    if(!this.positions.some(p=>p.key===this.expanded))this.expanded=null;
    const keys=this.positions.map(p=>p.key).join(',');
    if(this.host.dataset.keys!==keys) {
      const panel=document.getElementById('price-panel');if(panel)this.parking.append(panel);
      this.host.innerHTML=this.positions.map((p,i)=>`<article class="position-item" data-key="${p.key}"><button class="position-row" data-position="${p.key}" aria-expanded="false" aria-controls="position-detail-${i}"></button><div id="position-detail-${i}" class="position-detail" hidden><div class="position-meta"></div><div class="position-chart"></div></div></article>`).join('');
      this.host.dataset.keys=keys;
    }
    if(!positions.length) {
      const text=paused?'模拟盘已暂停，暂无持仓':'暂无持仓';
      if(this.host.textContent!==text)this.host.innerHTML=`<p class="empty position-empty">${text}</p>`;
    }
    [...this.host.querySelectorAll('.position-item')].forEach((item,i)=>{
      const p=this.positions[i],button=item.querySelector('button');
      const markup=`<span class="position-coin">${coinIcon(p.symbol)}<strong>${p.symbol.split('-')[0]}</strong><span class="side ${p.side===1?'up':'down'}">${p.side===1?'多':'空'}</span></span><span data-label="名义价值 (USDT)">${fmt(p.notional)}<small>USDT</small></span><span class="position-return ${tone(p.pnl)}"><b data-label="浮盈亏 (USDT)">${signed(p.pnl)}</b><small data-label="浮盈率 / 保证金">${signed(p.percent)}%</small></span>`;
      if(button.innerHTML!==markup)button.innerHTML=markup;
      item.querySelector('.position-meta').textContent=`保证金 ${fmt(p.margin)} USDT · 杠杆 ${Number.isFinite(p.leverage)?p.leverage+'×':'—'} · ${p.source}`;
    });
    this.mount();
  }
}
