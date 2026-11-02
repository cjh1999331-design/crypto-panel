// Public qty is base currency unless explicitly tagged as contracts.
const positive = n => Number.isFinite(n) && n > 0;
export function baseQuantity(row) {
  if (!positive(row.qty)) return null;
  if (row.qty_unit !== 'contracts') return row.qty;
  return positive(row.ctVal) ? row.qty * row.ctVal * (positive(row.ctMult) ? row.ctMult : 1) : null;
}
export function positionAmounts(row, mark = row.mark_price) {
  const qty = baseQuantity(row);
  // An explicit snapshot notional defines the exposure at its snapshot mark.
  const exposure = Number.isFinite(row.notional) && row.notional>=0 && positive(row.mark_price) ? row.notional / row.mark_price : qty;
  const notional = Number.isFinite(row.notional) && row.notional>=0
    ? positive(row.mark_price) && positive(mark) ? exposure*mark : row.notional
    : positive(mark) && qty !== null ? qty*mark : null;
  const pnl = positive(mark) && qty !== null ? row.side * qty * (mark-row.entry) : row.unrealized_pnl ?? null;
  return {qty,mark,notional,pnl,percent:Number.isFinite(pnl) && positive(row.margin) ? pnl/row.margin*100 : null};
}
export function orderAmounts(row) {
  const qty = baseQuantity(row), entry = row.limit;
  return {notional:Number.isFinite(row.notional) ? row.notional : positive(entry) && qty !== null ? entry*qty : null,
    risk:Number.isFinite(row.planned_risk) ? row.planned_risk : positive(entry) && positive(row.stop) && qty !== null ? Math.abs(entry-row.stop)*qty : null};
}
export function quoteFor(row, quotes, tickers=[], priceAt=0, now=Date.now()) {
  const q=quotes.get(row.symbol);
  if(q && positive(q.price) && Number.isFinite(q.at) && now-q.at<=45000 && q.at<=now+60000) return {mark:q.price,source:'WebSocket 实时价'};
  const ticker=tickers.find(t=>t.id===row.symbol);
  if(positive(ticker?.last) && priceAt>0 && now-priceAt<=24000) return {mark:ticker.last,source:'轮询实时价'};
  return {mark:row.mark_price,source:'快照标记价 · 行情回退'};
}
export function manualOrders(account, scan) {
  const main=(account?.accounts || []).find(a=>a.id===(account?.mode==='live'?'live_main':'paper_main'));
  return main?.manual_status ?? (account?.mode==='live' ? [] : scan?.manual_status) ?? [];
}
export function pendingOrders(account, scan) {
  const main=(account?.accounts || []).find(a=>a.id===(account?.mode==='live'?'live_main':'paper_main'));
  const maker=main?.pending_orders ?? (account?.mode==='live' ? [] : scan?.pending_orders) ?? [];
  return [...manualOrders(account,scan).filter(r=>r.status==='pending').map(r=>({...r,kind:'manual'})),
    ...maker.filter(r=>!r.status || r.status==='pending').map(r=>({...r,symbol:r.symbol || r.instId,kind:'maker'}))];
}
export function chartLevels(positions, orders, symbol) {
  const levels=[];
  for(const p of positions.filter(p=>p.symbol===symbol)) for(const [key,title,color] of [['entry','入场','#06727d'],['stop','止损','#c53045'],['take_profit','止盈','#087c50']])
    if(positive(p[key])) levels.push({price:p[key],title,color});
  for(const p of orders.filter(p=>p.symbol===symbol))
    if(positive(p.limit)) levels.push({price:p.limit,title:'挂单限价',color:'#916000'});
  return levels;
}
