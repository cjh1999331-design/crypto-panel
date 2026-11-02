// Pure rules shared by the dashboard, recording demo and unit tests.
export function isStale(ts, now=Date.now(), minutes=15) {
  const at=Date.parse(ts);
  return !Number.isFinite(at) || at>now+60000 || now-at>minutes*60000;
}
export function roleState(data, role, {now=Date.now(), offlineMinutes=15}={}) {
  const r=data?.status?.roles?.[role];
  if (!r) return {status:'离线',state:'offline',reason:'暂无角色状态'};
  if(r.status==='离线')return {status:'离线',state:'offline',reason:'团队标记离线'};
  if(isStale(data.status.updated_at,now,offlineMinutes) || isStale(data.generated_at,now,offlineMinutes))
    return {status:'离线',state:'offline',reason:`团队状态或快照超过 ${offlineMinutes} 分钟未更新`};
  return {status:r.status,state:({'工作中':'working','待命':'idle','已完成':'done'})[r.status] || 'offline',reason:r.task || '暂无当前任务'};
}
// A multiset identity handles anonymous duplicates. A watermark prevents replay
// when a rolling snapshot drops and later reintroduces an old row.
export const recordKey = r => JSON.stringify(r.id ? [r.id,r.ts || r.timestamp] : r);
export class NewRecords {
  constructor(){this.seen=new Map();this.watermark=-Infinity;this.ready=false;}
  update(rows){
    const counts=new Map(),fresh=[],previousWatermark=this.watermark;
    for(const row of rows){
      const key=recordKey(row),n=(counts.get(key)||0)+1;counts.set(key,n);
      const ts=Date.parse(row.ts || row.timestamp);
      if(this.ready && Number.isFinite(ts) && ts>=previousWatermark && n>(this.seen.get(key)||0))fresh.push(row);
      if(Number.isFinite(ts))this.watermark=Math.max(this.watermark,ts);
    }
    for(const [key,n] of counts)this.seen.set(key,Math.max(n,this.seen.get(key)||0));
    if(this.seen.size>5000){this.seen=counts;}
    this.ready=true;return fresh;
  }
}
export const motionAllowed = ({reduced=false,hidden=false,state='idle'}={}) => !reduced && !hidden && state!=='offline';
export const animationClasses = (state,options={}) => motionAllowed({...options,state}) ? `motion-${state}` : '';
export const EVENT_LABELS={universe_refreshed:'扫描币池',signal:'发现信号',stale_signal_skip:'跳过过期信号',risk_skip:'风险过滤',decision_skip:'决议过滤',trade_opened:'开仓',trade_closed:'平仓',daily_halt:'日停手',config_changed:'配置变更',started:'进程启动',stopped:'进程停止',resumed:'进程恢复',interrupted:'进程中断',maker_placed:'挂单等待',maker_cancelled:'挂单取消',funding_observed:'费率更新',funding:'资金费结算',network_error:'行情连接失败',decision_close:'决议平仓',skipped_min_size:'跳过最小数量',skipped_cap:'跳过仓位上限',liquidated:'强平'};
EVENT_LABELS['异动']='异动';
export function publicHttpsUrl(value){
 if(typeof value!=='string' || value.length>500 || /[\s\\\x00-\x1f]/.test(value))return false;
 try{
  const u=new URL(value),host=u.hostname.toLowerCase().replace(/\.$/,'');
  if(u.protocol!=='https:' || u.username || u.password || u.port)return false;
  if(/^\d+(?:\.\d+){3}$/.test(host)){
   const [a,b]=host.split('.').map(Number);
   return !(a===0 || a===10 || a===127 || a>=224 || a===169&&b===254 || a===172&&b>=16&&b<=31 || a===192&&b===168 || a===100&&b>=64&&b<=127);
  }
  return /^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}$/.test(host) && !/\.(localhost|local|internal|test|invalid|example|home|lan)$/.test(host);
 }catch{return false;}
}
export function eventText(r){return [EVENT_LABELS[r.type] || '事件',r.coin?.replace('-USDT-SWAP',''),({ema:'EMA 趋势',breakout:'突破放量',mean_reversion:'均值回归'})[r.strategy],r.direction,r.price==null?'':`@ ${r.price}`,r.reason].filter(Boolean).join(' · ');}
export function validEvents(data){
 const fields=new Set(['ts','type','coin','strategy','direction','price','reason','source_url']);
 return data?.schema_version===1 && Array.isArray(data.events) && data.events.length<=300 && data.events.every(r=>
   Object.keys(r).every(k=>fields.has(k)) && Number.isFinite(Date.parse(r.ts)) && Object.hasOwn(EVENT_LABELS,r.type) &&
   (r.coin===null || /^[A-Z0-9]+-USDT-SWAP$/.test(r.coin)) && (r.strategy===null || ['ema','breakout','mean_reversion'].includes(r.strategy)) &&
   (r.direction===null || ['多','空'].includes(r.direction)) && (r.price===null || Number.isFinite(r.price) && r.price>0) && (r.reason===null || typeof r.reason==='string' && r.reason.length<=80) &&
   (r.source_url===undefined || r.type==='异动' && publicHttpsUrl(r.source_url)));
}
