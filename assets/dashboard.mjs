import { analyze } from './indicators.mjs';
import { positionPnL } from './api.mjs';
const finite = value => typeof value === 'number' && Number.isFinite(value);
function validRisk(r) {
  if (!r || !['risk_per_trade','daily_loss_limit'].every(k => finite(r[k]) && r[k] > 0)) return false;
  const dynamic = finite(r.same_direction_risk_limit) && r.same_direction_risk_limit > 0 && r.same_direction_risk_limit <= 1 &&
    r.leverage_tiers && ['turnover_gte_50000000','turnover_lt_50000000','threshold_usdt'].every(k => finite(r.leverage_tiers[k]) && r.leverage_tiers[k] > 0);
  return ['max_positions','leverage'].every(k => (finite(r[k]) && r[k] > 0) || (r[k] === null && dynamic));
}
export function validSnapshot(data) {
  return data?.schema_version === 1 && Number.isFinite(Date.parse(data.generated_at)) && Array.isArray(data.accounts) && data.accounts.length > 0 &&
    new Set(data.accounts.map(a => a.id)).size === data.accounts.length && data.accounts.every(a => /^paper_[a-z0-9_]+$/.test(a.id) && (a.status === undefined || ['运行中','已停止','暂停'].includes(a.status)) && finite(a.balance) && finite(a.marked_equity) &&
      Array.isArray(a.positions) && a.positions.every(p => /^[A-Z0-9]+-USDT-SWAP$/.test(p.symbol) && [-1, 1].includes(p.side) && ['qty', 'entry', 'stop', 'margin'].every(k => finite(p[k])) && p.qty > 0) &&
      Array.isArray(a.trades) && Array.isArray(a.equity) && a.equity.length <= 500 && a.equity.every(p => finite(p.equity) && Number.isFinite(Date.parse(p.timestamp))) && (a.pause?.reset && a.status==='暂停' && a.risk===null || validRisk(a.risk)));
}
export function accountMetrics(account, tickers = [], now = Date.now()) {
  const prices = new Map(tickers.map(t => [t.id, t.last]));
  const live = account.positions.every(p => finite(prices.get(p.symbol)));
  const equity = live ? account.balance + account.positions.reduce((sum, p) => sum + positionPnL(p, prices.get(p.symbol), true), 0) : account.marked_equity;
  const day = new Date(now + 7 * 3600000).toISOString().slice(0, 10);
  const currentDay = account.day === day;
  const loss = currentDay && finite(account.day_start) && account.day_start > 0 ? Math.max(0, (account.day_start - equity) / account.day_start) : null;
  const limit = account.risk.daily_loss_limit;
  return { account, equity, live, loss, limit, remaining: loss === null ? null : Math.max(0, limit - loss),
    locked: currentDay && (account.risk.blocked || (loss !== null && loss >= limit)), currentDay };
}
export function roomMetrics(snapshot, tickers, now = Date.now()) {
  if (!snapshot?.accounts.length) return null;
  const current = snapshot.accounts.filter(a => a.status !== '已停止');
  if (!current.length) return null;
  const accounts = current.map(a => accountMetrics(a, tickers, now));
  const equity = accounts.reduce((sum, a) => sum + a.equity, 0);
  const initial = current.every(a => finite(a.initial) && a.initial > 0) ? current.reduce((sum, a) => sum + a.initial, 0) : null;
  const worst = accounts.filter(a => a.loss !== null).sort((a, b) => b.loss - a.loss)[0] || null;
  return { accounts, equity, pnl: initial === null ? null : (equity / initial - 1) * 100,
    positions: current.reduce((sum, a) => sum + a.positions.length, 0), worst,
    locked: accounts.some(a => a.locked), incompleteDay: accounts.some(a => a.loss === null), live: accounts.every(a => a.live) };
}
export function technicalStatus(bars) {
  const data = analyze(bars,{rsi:25,trend:.02});
  if (!data.ready) return { count: null, cross: '等待已收盘数据' };
  const i = data.bars.length - 1;
  const [fast, slow, prevFast, prevSlow] = [data.e20[i], data.e50[i], data.e20[i - 1], data.e50[i - 1]];
  const cross = fast > slow ? (prevFast <= prevSlow ? '刚金叉' : '金叉状态') : fast < slow ? (prevFast >= prevSlow ? '刚死叉' : '死叉状态') : '均线重合';
  return { count: data.count, cross };
}
