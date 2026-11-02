// Public snapshot contract. This module never calls an exchange or private endpoint.
const finite = n => typeof n === 'number' && Number.isFinite(n);
export const mainAccounts = data => (data?.accounts || []).filter(a => a.id === (data?.mode === 'live' ? 'live_main' : 'paper_main'));
export function validManualStatus(rows) {
  return rows === undefined || Array.isArray(rows) && rows.every(r => r && typeof r === 'object' &&
    (r.symbol == null || /^[A-Z0-9]+-USDT-SWAP$/.test(r.symbol)) && (r.side == null || [1,-1].includes(r.side)) &&
    ['pending','filled','expired','rejected','cancelled'].includes(r.status) &&
    ['limit','stop','take_profit'].every(k => r[k] == null || finite(r[k]) && r[k] > 0) &&
    (r.valid_until == null || Number.isFinite(Date.parse(r.valid_until))));
}
export const localDay = (now = Date.now()) => new Date(now + 7 * 3600000).toISOString().slice(0, 10);
export function dayNumber(startDate = '2026-11-02', now = Date.now()) {
  const start = /^\d{4}-\d{2}-\d{2}$/.test(startDate) ? Date.parse(startDate + 'T00:00:00+07:00') : NaN;
  const base = Number.isFinite(start) ? start : Date.parse('2026-11-02T00:00:00+07:00');
  return Math.max(1, Math.floor((now - base) / 86400000) + 1);
}
export function validAccount(data) {
  const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const nullable = n => n === null || finite(n);
  const timestamp = t => typeof t === 'string' && /(?:Z|[+-]\d{2}:\d{2})$/.test(t) && Number.isFinite(Date.parse(t));
  const symbol = s => typeof s === 'string' && /^[A-Z0-9]+-USDT-SWAP$/.test(s);
  if (!object(data) || !['paper','live'].includes(data.mode) || typeof data.source !== 'string' || !timestamp(data.updated_at) ||
      !Array.isArray(data.accounts) || !data.accounts.length || !object(data.decisions)) return false;
  if (data.accounts.some(a=>!object(a)) || new Set(data.accounts.map(a=>a.id)).size !== data.accounts.length) return false;
  const accountsValid=data.accounts.every(a => {
    if (!new RegExp(`^${data.mode}_[a-z0-9_]+$`).test(a.id) || a.mode !== data.mode ||
        !['未启动','运行中','已停止','已停手','事件窗口禁开新仓'].includes(a.status) ||
        !['balance','equity','daily_pnl','daily_loss_limit'].every(k=>nullable(a[k]))) return false;
    if (!Array.isArray(a.positions) || !Array.isArray(a.fills) || !Array.isArray(a.equity_curve)) return false;
    if (a.status === '未启动') {
      if (['balance','equity','daily_pnl','daily_loss_limit'].some(k=>a[k] !== null) || a.positions.length || a.fills.length || a.equity_curve.length) return false;
    } else if (!finite(a.balance) || !finite(a.equity) || !finite(a.daily_loss_limit) || a.daily_loss_limit <= 0 || a.daily_loss_limit > 1) return false;
    if (a.risk != null && !object(a.risk)) return false;
    if (a.risk?.leverage_tiers != null && (!object(a.risk.leverage_tiers) || !['turnover_gte_50000000','turnover_lt_50000000','threshold_usdt'].every(k=>finite(a.risk.leverage_tiers[k]) && a.risk.leverage_tiers[k]>0))) return false;
    if (a.strategies != null && (!object(a.strategies) || !Object.values(a.strategies).every(p=>object(p) && Object.values(p).every(finite)))) return false;
    const strategyNames = ['ema','breakout','mean_reversion'];
    if (a.enabled_strategies != null && (!Array.isArray(a.enabled_strategies) || new Set(a.enabled_strategies).size !== a.enabled_strategies.length || !a.enabled_strategies.every(s=>strategyNames.includes(s)))) return false;
    if (a.entry_mode_by_strategy != null && (!object(a.entry_mode_by_strategy) || !Object.entries(a.entry_mode_by_strategy).every(([s,m])=>strategyNames.includes(s) && ['maker','taker'].includes(m)))) return false;
    if (!validManualStatus(a.manual_status)) return false;
    return a.positions.every(p=>object(p) && symbol(p.symbol) && [-1,1].includes(p.side) && finite(p.qty) && p.qty>0 && finite(p.entry) && p.entry>0 && ['stop','leverage','take_profit','mark_price','unrealized_pnl'].every(k=>nullable(p[k]))) &&
      a.fills.every(f=>object(f) && symbol(f.symbol) && timestamp(f.timestamp) && ['open','close'].includes(f.kind) && finite(f.qty) && f.qty>0 && finite(f.price) && f.price>0 && finite(f.notional) && nullable(f.pnl) && Math.abs(f.notional-f.qty*f.price)<=Math.max(1,f.notional)*1e-8) &&
      a.equity_curve.every(p=>object(p) && finite(p.equity) && timestamp(p.timestamp));
  });
  const d=data.decisions;
  return accountsValid && ['active','missing'].includes(d.status) && object(d.symbols) &&
    Object.entries(d.symbols).every(([s,r])=>symbol(s) && object(r) && ['long','short','watch','ban'].includes(r.bias) && (r.note===null || typeof r.note==='string') && nullable(r.size_factor)) &&
    Array.isArray(d.blackout_windows) && d.blackout_windows.every(w=>object(w) && timestamp(w.start) && timestamp(w.end) && Date.parse(w.start)<Date.parse(w.end) && Array.isArray(w.symbols) && w.symbols.length>0 && w.symbols.every(s=>s==='*' || symbol(s)) && (w.reason==null || typeof w.reason==='string'));
}
export function activeWindows(decisions, now = Date.now(), symbol = null) {
  return (decisions?.blackout_windows || []).filter(w => Date.parse(w.start) <= now && now < Date.parse(w.end) && (!symbol || w.symbols.includes('*') || w.symbols.includes(symbol)));
}
export function strategyState(account, decisions, now = Date.now()) {
  if (account.status === '未启动') return '未启动';
  if (account.status === '已停止' || account.strategy_enabled === false) return '已停止';
  const today = account.day === localDay(now);
  if (account.status === '已停手' || (today && account.risk?.blocked)) return '已停手';
  if (account.status === '事件窗口禁开新仓' || activeWindows(decisions, now).length) return '事件窗口禁开新仓';
  return '运行中';
}
export function summarizeAccounts(data, tickers = [], now = Date.now()) {
  if (!data) return null;
  const prices = new Map(tickers.map(t=>[t.id,t.last]));
  const started = mainAccounts(data).filter(a=>a.status !== '未启动');
  if (!started.length) return null;
  const accounts = started.map(a=>{
    const live = a.status !== '已停止' && a.positions.every(p=>finite(prices.get(p.symbol)));
    const equity = live ? a.balance + a.positions.reduce((sum,p)=>sum+Math.max(finite(p.margin)?-p.margin:-Infinity,p.side*p.qty*(prices.get(p.symbol)-p.entry)),0) : a.equity;
    const isToday = a.day ? a.day === localDay(now) : localDay(Date.parse(a.updated_at || data.updated_at)) === localDay(now);
    const daily = isToday ? finite(a.day_start) ? equity-a.day_start : a.daily_pnl : null;
    const baseline = finite(a.day_start) ? a.day_start : finite(daily) ? equity-daily : null;
    const loss = finite(daily) && baseline > 0 ? Math.max(0,-daily/baseline) : null;
    let state = strategyState(a,data.decisions,now);
    if (state === '运行中' && loss !== null && loss >= a.daily_loss_limit) state='已停手';
    return {account:a,equity,live,daily,loss,state};
  });
  const positions = started.flatMap(a=>a.positions.map(p=>{
    const mark = a.status !== '已停止' && finite(prices.get(p.symbol)) ? prices.get(p.symbol) : p.mark_price;
    return {...p, account:a.name || (data.mode === 'live' ? '实盘策略' : '模拟策略'), mark,
      pnl:finite(mark) ? p.side*p.qty*(mark-p.entry) : p.unrealized_pnl,
      notional:finite(mark) ? Math.abs(p.qty*mark) : null};
  }));
  const equity=accounts.reduce((s,a)=>s+a.equity,0);
  const initial=started.every(a=>finite(a.initial)) ? started.reduce((s,a)=>s+a.initial,0) : null;
  const fills=started.flatMap(a=>a.fills).sort((a,b)=>Date.parse(b.timestamp)-Date.parse(a.timestamp));
  const today=fills.filter(f=>localDay(Date.parse(f.timestamp)) === localDay(now));
  return {accounts,positions,equity,balance:started.reduce((s,a)=>s+a.balance,0),initial,
    pnl:initial === null ? null : equity-initial, fills,today,
    turnover:today.reduce((s,f)=>s+f.notional,0),
    size:positions.every(p=>finite(p.notional)) ? positions.reduce((s,p)=>s+p.notional,0) : null};
}
export function aggregateCurve(accounts) {
  const started=accounts.filter(a=>['paper_main','live_main'].includes(a.id) && a.status !== '未启动');
  if (!started.length || started.some(a=>!a.equity_curve.length)) return [];
  const byAccount=started.map(a=>new Map(a.equity_curve.map(p=>[Date.parse(p.timestamp),p.equity])));
  const times=[...new Set(byAccount.flatMap(m=>[...m.keys()]))].sort((a,b)=>a-b);
  const latest=byAccount.map(()=>null), out=[];
  for (const ts of times) {
    byAccount.forEach((m,i)=>{if(m.has(ts))latest[i]=m.get(ts);});
    // Never backfill an account before its first real observation.
    if(latest.every(finite))out.push({time:Math.floor(ts/1000),value:latest.reduce((s,n)=>s+n,0)});
  }
  return [...new Map(out.map(p=>[p.time,p])).values()];
}

// qty is base-coin quantity in the public contract, not the number of contracts.
// Isolated insurance caps each position's loss at its own posted margin.
export function isolatedPnL(p, mark) {
  if (!finite(mark) || mark<=0) return null;
  const raw=p.side*p.qty*(mark-p.entry);
  return finite(p.margin) && p.margin>=0 ? Math.max(-p.margin,raw) : raw;
}
export function liveBalance(data, quotes=new Map(), now=Date.now(), quoteMaxAge=45000) {
  const started=mainAccounts(data).filter(a=>a.status!=='未启动');
  if(!started.length)return null;
  let equity=0, dailyBase=0, baselineKnown=true, fallback=false, missing=false;
  const positions=[];
  for(const a of started){
    let accountEquity=a.equity;
    if(a.positions.length && a.status!=='已停止'){
      let pnl=0,known=true;
      for(const p of a.positions){
        const q=quotes.get(p.symbol);
        const live=q && finite(q.price) && q.price>0 && finite(q.at) && now-q.at<=quoteMaxAge && q.at<=now+60000;
        const mark=live?q.price:p.mark_price, value=isolatedPnL(p,mark);
        fallback ||= !live;
        if(value===null)known=false;else pnl+=value;
        positions.push({...p,mark,pnl:value,source:live?'实时价':'快照标记价'});
      }
      accountEquity=known?a.balance+pnl:a.equity;
      missing ||= !known;
    }
    equity+=accountEquity;
    if(a.day===localDay(now) && finite(a.day_start) && a.day_start>0)dailyBase+=a.day_start;else baselineKnown=false;
  }
  const daily=baselineKnown?equity-dailyBase:null;
  return {equity,daily,percent:daily===null?null:daily/dailyBase*100,positions,fallback,missing,
    source:missing?'缺少标记价 · 回退快照权益':fallback?'回退快照标记价':positions.length?'OKX 实时报价':'空仓 · 快照权益'};
}
