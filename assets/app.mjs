import { NewRecords, recordKey, roleState, isStale, validEvents, eventText } from './state.mjs';
import { PublicStream, mergeCandle, tradeMarkers } from './realtime.mjs';
import { configureMotion, reducedMotion, rollNumber, roleEffect, toast, typeLine } from './effects.mjs';
import { mainAccounts, liveBalance, validAccount, summarizeAccounts, aggregateCurve, activeWindows, dayNumber } from './account.mjs';
import { ROLES, validTeam, teamCards, teamTime, timelineMarkup } from './team.mjs';
import config from '../config.js';
import { validSnapshot, technicalStatus } from './dashboard.mjs';
import { validScan, scanRows, signalText, meetingSymbol, chartUniverse, strategyEntries, strategyName, reasonText } from './scan.mjs';
import { PublicAPI, normalizeTickers, number, positionPnL } from './api.mjs';
import { parseCandles, analyze } from './indicators.mjs';
import { chartAvailable, createCandleCharts, createEquityChart, createBalanceChart, COLORS } from './charts.mjs';

const $ = id => document.getElementById(id);
configureMotion();
const teamRecords=new NewRecords(),fillRecords=new NewRecords(),eventRecords=new NewRecords(),liveQuotes=new Map();
let quoteStream=null,candleStream=null,quoteStreamKey='',candleStreamKey='',streamReason='',teamRenderKey='';
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const num = (value, digits = 2) => Number.isFinite(value) ? value.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits }) : '—';
const price = value => num(value, value >= 100 ? 2 : value >= 1 ? 4 : value >= .01 ? 6 : 8);
const compact = value => !Number.isFinite(value) ? '—' : Math.abs(value) >= 1e8 ? num(value / 1e8) + ' 亿' : Math.abs(value) >= 1e4 ? num(value / 1e4) + ' 万' : num(value);
const signed = (value, digits = 2) => Number.isFinite(value) ? (value > 0 ? '+' : '') + num(value, digits) : '—';
const tone = value => Number.isFinite(value) ? value >= 0 ? 'up' : 'down' : '';
const clock = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Bangkok', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
const time = value => { const ms = typeof value === 'number' ? value : Date.parse(value); return Number.isFinite(ms) ? clock.format(ms) : '—'; };
const api = new PublicAPI(), errors = new Map(), funding = new Map(), interests = new Map(), candleCache = new Map();
let tickers = [], top = [], priceAt = 0, slowAt = 0, priceBusy = false, slowBusy = false, snapshotBusy = false;
const configuredSymbol = /^[A-Z0-9]+-USDT-SWAP$/.test(config.symbol) ? config.symbol : 'ZEC-USDT-SWAP';
let focusSymbol = configuredSymbol, homeCoin = focusSymbol, manualHomeCoin = null;
let route = 'home', coin = focusSymbol, timeframe = '1H', routeVersion = 0, sortKey = 'turnover', sortDirection = -1;
let candleCharts = null, equityChart = null, snapshot = null, accountId = null, tradePage = 0;
let lastCandleRequest = '', candleBusy = new Set();
let publicAccount = null, publicBusy = false;
let team = null, teamBusy = false, teamRole = '', teamMeeting = '';
let scan = null, scanBusy = false, scanSort = 'quote_24h', scanDirection = -1;
function syncHomeCoin() {
  focusSymbol = meetingSymbol(team?.status.meeting, configuredSymbol);
  const universe = chartUniverse(publicAccount, scan, focusSymbol);
  if (!universe.choices.some(c => c.id === manualHomeCoin)) manualHomeCoin = null;
  homeCoin = manualHomeCoin || universe.defaultSymbol;
  $('chart-symbol').innerHTML = universe.choices.map(c => `<option value="${escape(c.id)}">${escape(c.id.split('-')[0])} · ${[c.held?'持仓币':'',c.signal?'信号币':'',c.meeting?'今日会议标的':''].filter(Boolean).join(' / ')}</option>`).join('');
  $('chart-symbol').value = homeCoin;
  $('meeting-target').textContent = team?.status.meeting ? `今日会议标的 ${focusSymbol.split('-')[0]} · 独立会议观察` : `暂无会议标的 · 当前使用公开配置 ${configuredSymbol.split('-')[0]}`;
  if (route === 'home' && coin !== homeCoin) {
    coin = homeCoin; routeVersion++;
    candleCharts?.destroy(); candleCharts = null;
    $('candle-updated').textContent = '加载中';
    $('conditions').innerHTML = ''; $('signal-summary').innerHTML = '<strong>— <small>/ 6</small></strong><span>等待 K 线数据</span>';
    const cached = candleCache.get(coin + '/' + timeframe);
    if (cached) showCandles(cached.bars, cached.at);
    refreshCandles();
  }
  syncStreams();
}
function renderScan() {
  $('scan-count').textContent = scan?.source_status === 'missing' ? '待更新' : scan ? `${scan.instruments.length} 币` : '— 币';
  $('scan-updated').textContent = scan?.generated_at ? `${time(scan.generated_at)} UTC+7 · 原生 1H 扫描` : '等待下次主力盘轮询生成 scan.json';
  const rows = scanRows(scan, $('scan-filter').value, scanSort, scanDirection);
  const coinButton = id => `<button data-chart-coin="${escape(id)}">${escape(id.split('-')[0])}</button>`;
  $('scan-body').innerHTML = rows.length ? rows.map(r => `<tr><td><a href="#/coin/${encodeURIComponent(r.instId)}">${escape(r.instId.split('-')[0])}</a></td><td>${compact(r.quote_24h)} USDT</td><td>${num(r.spread === null ? null : r.spread*100,3)}%</td><td>${num(r.leverage_cap,0)}×</td><td>${escape(signalText(r))}</td><td>${r.held?'持仓':'空仓'}</td></tr>`).join('') : '<tr><td colspan="6" class="empty">暂无符合条件的币种</td></tr>';
  $('scan-recent').innerHTML = scan?.recent_signals.length ? [...scan.recent_signals].sort((a,b)=>Date.parse(b.timestamp)-Date.parse(a.timestamp)).map(r => `<tr><td>${time(r.timestamp)}</td><td>${coinButton(r.instId)} / ${escape(strategyName(r.strategy))}</td><td class="${r.side===1?'up':'down'}">${r.side===1?'多':'空'}</td><td>${r.opened?'已开仓':escape(reasonText(r.reason))}</td></tr>`).join('') : '<tr><td colspan="4" class="empty">最近 48 小时暂无信号</td></tr>';
  const held = chartUniverse(publicAccount, scan, focusSymbol).choices.filter(c=>c.held);
  $('scan-held').innerHTML = held.length ? held.map(c=>coinButton(c.id)).join('') : '暂无持仓';
}
async function refreshScan() {
  if (scanBusy) return; scanBusy = true;
  try {
    const response = await fetch(`./paper/scan.json?t=${Date.now()}`,{cache:'no-store',credentials:'omit',signal:AbortSignal.timeout(12000)});
    if (!response.ok) throw new Error('扫描快照读取失败');
    const data = await response.json(); if (!validScan(data)) throw new Error('扫描快照格式无效');
    scan=data;setError('scan',null);syncHomeCoin();renderScan();if(route==='home')renderHome();
  } catch {setError('scan','全市场扫描暂无有效更新');}
  finally {scanBusy=false;}
}
$('scan-filter').addEventListener('change',renderScan);
$('scan-table').addEventListener('click',event=>{
  const button=event.target.closest('[data-scan-sort]');if(!button)return;
  const key=button.dataset.scanSort;
  scanDirection=scanSort===key?-scanDirection:key==='instId'?1:-1;scanSort=key;
  $('scan-table').querySelectorAll('[data-scan-sort]').forEach(b=>{
    const active=b.dataset.scanSort===key;
    b.closest('th').setAttribute('aria-sort',active?(scanDirection===1?'ascending':'descending'):'none');
    b.textContent=b.textContent.replace(/ [↑↓]$/,'')+(active?(scanDirection===1?' ↑':' ↓'):'');
  });renderScan();
});
function chooseHomeCoin(id) {manualHomeCoin=id;syncHomeCoin();renderHome();}
$('chart-symbol').addEventListener('change',()=>chooseHomeCoin($('chart-symbol').value));
$('scan-panel').addEventListener('click',event=>{const b=event.target.closest('[data-chart-coin]');if(b)chooseHomeCoin(b.dataset.chartCoin);});
function renderTimeline() { $('team-timeline').innerHTML = timelineMarkup(team, teamRole, teamMeeting); }
async function refreshTeam() {
  if (teamBusy) return; teamBusy = true;
  try {
    const response = await fetch(`./paper/team.json?t=${Date.now()}`, {cache:'no-store', credentials:'omit', signal:AbortSignal.timeout(12000)});
    if (!response.ok) throw new Error('团队数据读取失败');
    const data = await response.json();
    if (!validTeam(data)) throw new Error('团队数据格式无效');
    const fresh=teamRecords.update(data.log);
    team = data; setError('team', null); syncHomeCoin();
    $('team-updated').textContent = team.status.updated_at ? `团队更新 ${teamTime(team.status.updated_at)}` : '团队待命 · 暂无更新';
    const meetings = [...new Set(team.log.map(r => r.meeting))].sort().reverse();
    if (team.status.meeting && !meetings.includes(team.status.meeting)) meetings.unshift(team.status.meeting);
    if (!meetings.includes(teamMeeting)) teamMeeting = '';
    $('team-meeting').innerHTML = '<option value="">全部会议</option>' + meetings.map(m => `<option value="${escape(m)}">${escape(m)}</option>`).join('');
    $('team-meeting').value = teamMeeting; renderTimeline(); if (route === 'home') renderHome();
    for(const row of fresh){roleEffect(row.role,'report');toast(`${ROLES[row.role]} · 新报告：${row.title}`);}
  } catch { setError('team', '团队数据暂时无法读取'); }
  finally { teamBusy = false; }
}
$('team-role-filters').innerHTML = Object.entries({'':'全部',...ROLES}).map(([role,name]) => `<button data-team-role="${role}" class="${role ? '' : 'active'}" aria-pressed="${!role}">${name}</button>`).join('');
$('team-role-filters').addEventListener('click', event => {
  const button = event.target.closest('[data-team-role]'); if (!button) return;
  teamRole = button.dataset.teamRole;
  $('team-role-filters').querySelectorAll('button').forEach(b => { b.classList.toggle('active', b === button); b.setAttribute('aria-pressed', String(b === button)); });
  renderTimeline();
});
$('team-meeting').addEventListener('change', () => { teamMeeting = $('team-meeting').value; renderTimeline(); });

function setError(key, message) {
  if (message) errors.set(key, message); else errors.delete(key);
  $('alerts').innerHTML = [...errors.values()].map(m => `<div class="alert">${escape(m)}。已有数据会保留，将自动重试。</div>`).join('');
}
function description(error) { return /^(OKX|接口|请求)/.test(error.message) ? error.message : '网络连接失败或请求超时'; }
function badge(row) { return `<span class="coin-badge" aria-hidden="true">${escape(row.symbol.slice(0, 1))}</span><div><a href="#/coin/${encodeURIComponent(row.id)}">${escape(row.symbol)}</a><small>USDT 永续</small></div>`; }
function decorated() {
  return top.map(r => ({ ...r, funding: funding.get(r.id)?.rate ?? null, oi: Number.isFinite(interests.get(r.id)?.qty) ? interests.get(r.id).qty * r.last : null }));
}
function renderMarket() {
  const rows = decorated(), query = $('search').value.trim().toUpperCase();
  const selected = rows.filter(r => r.symbol.includes(query)).sort((a, b) => {
    const av = a[sortKey], bv = b[sortKey];
    if (av == null) return bv == null ? 0 : 1;
    if (bv == null) return -1;
    return (typeof av === 'string' ? av.localeCompare(bv) : av - bv) * sortDirection;
  });
  $('market-body').innerHTML = selected.length ? selected.map(r => `<tr data-coin="${escape(r.id)}"><td class="rank">${String(r.rank).padStart(2, '0')}</td><td><div class="coin-cell">${badge(r)}</div></td><td>${price(r.last)}</td><td><span class="change ${tone(r.change)}">${signed(r.change)}${r.change === null ? '' : '%'}</span></td><td>${compact(r.turnover)}</td><td title="${funding.has(r.id) ? '获取：' + time(funding.get(r.id).at) + ' UTC+7；下次结算：' + time(funding.get(r.id).settlement) : '等待获取'}" class="${tone(r.funding)}">${r.funding === null ? '—' : signed(r.funding * 100, 4) + '%'}</td><td title="${interests.has(r.id) ? '获取：' + time(interests.get(r.id).at) + ' UTC+7' : '等待获取'}">${compact(r.oi)}</td></tr>`).join('') : `<tr><td colspan="7" class="empty">${tickers.length ? '没有匹配的币种' : '行情尚未加载，正在重试…'}</td></tr>`;
  if (!rows.length) return;
  const up = rows.filter(r => r.change > 0).length, down = rows.filter(r => r.change < 0).length;
  const leader = rows.filter(r => r.change !== null).sort((a, b) => b.change - a.change)[0];
  const oiRows = rows.filter(r => r.oi !== null);
  $('market-stats').innerHTML = `<article class="stat"><span>样本成交额 · 24 小时</span><strong>${compact(rows.reduce((s, r) => s + (r.turnover || 0), 0))}</strong><small>前 ${rows.length} 合约 · USDT 估算</small></article><article class="stat"><span>上涨 / 下跌</span><strong><span class="up">${up}</span> <small>/</small> <span class="down">${down}</span></strong><small>前 ${rows.length} 合约 · 平盘 ${rows.filter(r => r.change === 0).length}</small></article><article class="stat"><span>涨幅领先</span><strong>${escape(leader?.symbol || '—')} <small class="${tone(leader?.change)}">${signed(leader?.change)}%</small></strong><small>按 24 小时价格变动排名</small></article><article class="stat"><span>持仓总额</span><strong>${oiRows.length ? compact(oiRows.reduce((s, r) => s + r.oi, 0)) : '—'}</strong><small>${oiRows.length} / ${rows.length} 合约 · USDT 估算</small></article>`;
}
function renderQuote() {
  const ticker = tickers.find(r => r.id === coin);
  $('coin-quote').innerHTML = ticker ? `<span class="${tone(ticker.change)}">${price(ticker.last)} USDT　${signed(ticker.change)}%</span>　<span class="muted">24h 变动 · ${time(priceAt)} UTC+7 更新</span>` : '等待该合约实时行情';
}
async function refreshPrices() {
  if (priceBusy) return;
  priceBusy = true;
  try {
    const data = normalizeTickers(await api.get('market/tickers', { instType: 'SWAP' }, 10));
    if (!data.length) throw new Error('接口未返回有效 USDT 永续行情');
    tickers = data;
    top = data.filter(r => r.turnover !== null).sort((a, b) => b.turnover - a.turnover).slice(0, 30).map((r, i) => ({ ...r, rank: i + 1 }));
    priceAt = Date.now(); setError('prices', null);
    $('price-updated').textContent = `${time(priceAt)} UTC+7 更新`;
    renderMarket(); if (route === 'coin') renderQuote(); if (route === 'home') renderHome(); if (route === 'paper' && snapshot) renderPaperLive();
    if (['home', 'market', 'coin'].includes(route)) refreshSlow();
  } catch (error) { setError('prices', `行情：${description(error)}`); if (!tickers.length) renderMarket(); }
  finally { priceBusy = false; refreshHealth(); }
}
async function refreshSlow() {
  if (slowBusy || !top.length) return;
  slowBusy = true;
  const wanted = [...new Set([...top.map(r => r.id), ...(coin ? [coin] : [])])];
  try {
    const tasks = [];
    if (Date.now() - slowAt >= 60000) tasks.push((async () => {
      try {
        const rows = await api.get('public/open-interest', { instType: 'SWAP' });
        if (!rows.some(r => number(r.oiCcy) !== null)) throw new Error('接口持仓量为空');
        const at = Date.now();
        rows.forEach(r => { const qty = number(r.oiCcy); if (qty !== null) interests.set(r.instId, { qty, at }); });
        slowAt = at; setError('oi', null);
      } catch (error) { setError('oi', `持仓量：${description(error)}`); }
    })());
    const due = wanted.filter(id => Date.now() - (funding.get(id)?.at || 0) >= 60000);
    if (due.length) tasks.push((async () => {
      const results = await Promise.allSettled(due.map(async id => {
        const rows = await api.get('public/funding-rate', { instId: id });
        const row = rows.find(r => r.instId === id), rate = number(row?.fundingRate);
        if (rate === null) throw new Error('接口资金费率为空');
        funding.set(id, { rate, at: Date.now(), settlement: number(row.fundingTime) });
        if (route === 'market') renderMarket();
      }));
      const failed = results.filter(r => r.status === 'rejected');
      setError('funding', failed.length ? `资金费率：${failed.length} 个合约获取失败` : null);
    })());
    await Promise.all(tasks);
    $('slow-updated').textContent = `资金费率 / 持仓量 · 60 秒刷新 · ${slowAt ? '最近持仓数据 ' + time(slowAt) + ' UTC+7' : '持仓量等待获取'}`;
    if (route === 'market') renderMarket();
  } finally { slowBusy = false; }
}

function renderAnalysis(bars) {
  const data = analyze(bars);
  $('signal-summary').innerHTML = `<strong>${data.ready ? data.count : '—'} <small>/ 6</small></strong><span>${data.ready ? '项条件满足' : '已收盘样本不足'}</span>`;
  $('signal-time').textContent = data.ready ? `信号 K 线开盘：${time(data.bar.time * 1000)} UTC+7` : '至少需要 51 根已收盘 K 线；EMA200 需 200 根预热。';
  if (!data.ready) { $('conditions').innerHTML = ''; $('levels').innerHTML = '<p class="muted">历史数据不足</p>'; return; }
  const c = data.checks;
  const labels = ['收盘突破前 20 根最高价', '成交额达到均值 1.5 倍', '收盘位置 ≥ 0.7', 'EMA20 > EMA50 且收盘 > EMA20', '50 < RSI14 < 70', 'MACD 柱为正且继续增大'];
  const details = [
    `收盘 ${price(c[0].close)} > 区间高点 ${price(c[0].high20)}`,
    `${compact(c[1].turnover)} / 均值 ${compact(c[1].average)} USDT；倍数 ${num(c[1].ratio)}×`,
    `实际 ${num(c[2].location, 3)}；(收盘 − 最低) / (最高 − 最低)`,
    `EMA20 ${price(c[3].ema20)} / EMA50 ${price(c[3].ema50)}；收盘 ${price(c[3].close)}`,
    `实际 RSI14：${num(c[4].rsi)}`,
    `当前 ${num(c[5].histogram, 6)} / 前一根 ${num(c[5].previous, 6)}`,
  ];
  $('conditions').innerHTML = labels.map((label, i) => `<li class="${c[i].pass ? 'passed' : ''}"><div class="condition-name">${label}<span class="${c[i].pass ? 'up' : ''}">${c[i].pass ? '满足' : '未满足'}</span></div><p>${details[i]}</p></li>`).join('');
  const levels = data.levels;
  $('levels').innerHTML = `<div class="level-row"><span>回看窗口</span><span class="up">支撑 · 最低</span><span class="down">阻力 · 最高</span></div>${[20, 50].map(n => `<div class="level-row"><span>前 ${n} 根</span><span>${price(levels['low' + n])}</span><span>${price(levels['high' + n])}</span></div>`).join('')}`;
}
function showCandles(bars, at) {
  renderAnalysis(bars);
  if (route === 'home') { $('analysis-period').textContent = `${timeframe === '1H' ? '1 小时' : '4 小时'} · 已收盘信号`; renderHome(); }
  $('candle-updated').textContent = `${bars.length} 根 · ${time(at)} 更新`;
  if (!chartAvailable()) { $('chart-error').hidden = false; $('chart-error').textContent = '图表库加载失败，请检查 CDN 连接后刷新页面。六条件仍可查看。'; return; }
  try {
    if (!candleCharts) candleCharts = createCandleCharts();
    candleCharts.update(bars); candleCharts.markers(tradeMarkers(publicAccount,coin,bars)); $('chart-error').hidden = true;
  } catch { $('chart-error').hidden = false; $('chart-error').textContent = '图表暂时无法绘制，指标数据仍可查看。'; }
}
async function refreshCandles(force = false) {
  if (!['home', 'coin'].includes(route)) return;
  const id = coin, bar = timeframe, key = id + '/' + bar, version = routeVersion;
  const cached = candleCache.get(key);
  if (candleBusy.has(key) || (!force && cached && Date.now() - cached.at < 60000)) return;
  candleBusy.add(key); lastCandleRequest = key;
  try {
    const bars = parseCandles(await api.get('market/candles', { instId: id, bar, limit: 300 }, 8));
    if (!bars.length) throw new Error('接口未返回有效 K 线');
    const at = Date.now(); candleCache.set(key, { bars, at });
    if (id === focusSymbol && bar === '1H') setError('technical', null);
    if (route === 'home') renderHome();
    if (!['home', 'coin'].includes(route) || coin !== id || timeframe !== bar) return;
    // 同一合约被离开又进入时也可使用刚完成的数据。
    if (version !== routeVersion && lastCandleRequest !== key) return;
    setError('candles', null); showCandles(bars, at);updateStreamStatus();
  } catch (error) { if (['home', 'coin'].includes(route) && coin === id && timeframe === bar) setError('candles', `K 线：${description(error)}`); }
  finally { candleBusy.delete(key); }
}

async function refreshSnapshot() {
  if (snapshotBusy) return;
  snapshotBusy = true;
  try {
    const response = await fetch(`./paper/snapshot.json?t=${Date.now()}`, { cache: 'no-store', credentials: 'omit', signal: AbortSignal.timeout(12000) });
    if (!response.ok) throw new Error('接口未找到快照，请先生成 paper/snapshot.json');
    const data = await response.json();
    if (!validSnapshot(data)) throw new Error('接口快照格式不完整');
    const changed = snapshot?.generated_at !== data.generated_at;
    snapshot = {...data, accounts:data.accounts.filter(a => ['paper_main','paper_1h','paper_4h','paper_1h_aggr','paper_4h_aggr'].includes(a.id))}; setError('snapshot', null);
    if (!snapshot.accounts.some(a => a.id === accountId)) accountId = snapshot.accounts[0].id;
    if (route === 'home') { renderHome(); if (changed || !equityChart) renderEquity(); }
    if (route === 'paper') {
      renderPaper();
      if (changed || !equityChart) renderEquity();
    }
    refreshHealth();
  } catch (error) { setError('snapshot', `模拟盘：${description(error)}`); }
  finally { snapshotBusy = false; }
}
function renderPaper() {
  if (!snapshot) return;
  $('snapshot-time').textContent = `生成：${time(snapshot.generated_at)} UTC+7`;
  $('account-tabs').innerHTML = snapshot.accounts.map(a => `<button data-account="${escape(a.id)}" class="${a.id === accountId ? 'active' : ''} ${a.status === '已停止' ? 'archived' : ''}" aria-pressed="${a.id === accountId}">${escape(a.name)}${a.status === '已停止' ? ' · 历史' : ''}</button>`).join('');
  renderPaperLive(); renderAccount(); refreshHealth();
}
function renderPaperLive() {
  if (!snapshot) return;
  const prices = new Map(tickers.map(t => [t.id, t.last]));
  $('paper-cards').innerHTML = snapshot.accounts.map((a, i) => {
    const stopped = a.status === '已停止';
    const allKnown = a.positions.every(p => prices.has(p.symbol));
    const liveEquity = stopped ? a.marked_equity : allKnown ? a.balance + a.positions.reduce((sum, p) => sum + positionPnL(p, prices.get(p.symbol), true), 0) : null;
    return `<article class="stat ${stopped ? 'archived' : ''}"><span><span style="color:${stopped ? '#899580' : COLORS[i % COLORS.length]}">●</span> ${escape(a.name)} ${stopped ? '<span class="pill">历史</span>' : ''}</span><strong>${num(liveEquity)} <small>USDT</small></strong><small>${stopped ? '已停止 · 历史权益' : '实时权益估值'}${allKnown || stopped ? '' : ' · 等待行情'}</small><div class="stat-row"><span>余额 ${num(a.balance)}</span><span>快照权益 ${num(a.marked_equity)}</span></div></article>`;
  }).join('');
  renderPositions(prices);
}
function selectedAccount() { return snapshot?.accounts.find(a => a.id === accountId); }
function renderPositions(prices = new Map(tickers.map(t => [t.id, t.last]))) {
  const account = selectedAccount(); if (!account) return;
  $('position-count').textContent = account.positions.length + ' 仓';
  $('positions-label').textContent = account.status === '已停止' ? '历史持仓' : '当前持仓';
  $('paper-price-time').textContent = account.status === '已停止' ? '已停止 · 历史持仓快照' : priceAt ? `现价更新 ${time(priceAt)} UTC+7` : '现价每 8 秒刷新';
  $('positions').innerHTML = account.positions.length ? account.positions.map(p => {
    const current = account.status === '已停止' ? null : prices.get(p.symbol), pnl = positionPnL(p, current);
    return `<tr><td><a href="#/coin/${encodeURIComponent(p.symbol)}">${escape(p.symbol.replace('-USDT-SWAP', ''))}</a>${p.strategy==='manual'?'<small class="position-source">会议单</small>':''}<span class="side ${p.side === 1 ? 'up' : 'down'}">${p.side === 1 ? '多' : '空'}</span></td><td>${num(p.qty, 6)}</td><td>${price(p.entry)}</td><td>${price(current)}</td><td>${price(p.stop)}</td><td>${price(p.liquidation_price)}</td><td class="${tone(pnl)}">${signed(pnl, 4)}</td></tr>`;
  }).join('') : `<tr><td colspan="7" class="empty">${account.status === '已停止' ? '历史快照无持仓' : '当前空仓，等待下一次策略信号'}</td></tr>`;
}
function renderAccount() {
  const account = selectedAccount(); if (!account) return;
  const r = account.risk;
  $('risk').innerHTML = `<span>每笔风险 <b>${num(r.risk_per_trade * 100)}%</b></span><span>${r.max_positions === null ? '同向风险' : '最多持仓'} <b>${r.max_positions === null ? num(r.same_direction_risk_limit * 100) + '%' : num(r.max_positions, 0) + ' 仓'}</b></span><span>逐仓杠杆 <b>${r.leverage === null ? '分档最高 ' + num(Math.max(r.leverage_tiers.turnover_gte_50000000,r.leverage_tiers.turnover_lt_50000000),0) + '×' : num(r.leverage, 1) + '×'}</b></span><span>日亏上限 <b>${num(r.daily_loss_limit * 100)}%</b></span><span>风控状态 <b>${account.status === '已停止' ? '已停止 · 历史' : r.blocked ? '当日暂停开仓' : '正常'}</b></span>${r.legacy_defaults ? '<span>旧版默认参数</span>' : ''}<span>源数据 <b>${escape(time(account.updated_at))} UTC+7</b></span>`;
  renderPositions(); renderTrades();
}
function renderTrades() {
  const account = selectedAccount(); if (!account) return;
  const total = Math.max(1, Math.ceil(account.trades.length / 20));
  tradePage = Math.min(Math.max(0, tradePage), total - 1);
  const reasons = { signal: '策略信号', stop: '止损', stop_live: '实时止损', liquidated: '模拟强平', end: '回测结束', end_of_data: '数据结束', take_profit: '止盈', other: '其他' };
  $('trades').innerHTML = account.trades.length ? account.trades.slice(tradePage * 20, (tradePage + 1) * 20).map(t => `<tr><td>${escape(time(t.timestamp))}</td><td>${escape(t.symbol?.replace('-USDT-SWAP', ''))}</td><td><span class="${t.side === 1 ? 'up' : 'down'}">${t.side === 1 ? '多' : t.side === -1 ? '空' : '—'}</span> / ${t.kind === 'open' ? '开仓' : '平仓'}</td><td>${num(t.qty, 6)}</td><td>${price(t.kind === 'open' ? t.entry : t.exit)}</td><td class="${tone(t.pnl)}">${t.kind === 'open' ? '—' : signed(t.pnl, 4)}</td><td>${t.kind === 'open' ? '策略开仓' : reasons[t.reason] || '其他'}</td></tr>`).join('') : '<tr><td colspan="7" class="empty">暂无成交记录</td></tr>';
  $('trades-page').textContent = `${tradePage + 1} / ${total} 页 · 共 ${account.trades.length} 笔`;
  $('trades-prev').disabled = tradePage === 0; $('trades-next').disabled = tradePage >= total - 1;
}
function renderEquity() {
  if (route === 'home') { renderBalance(); return; }
  if (!snapshot) return;
  $('equity-panel').querySelector('h2').textContent='历史资金曲线';
  $('equity-panel').querySelector('.panel-heading p').textContent='标记权益 · USDT · 每条最多 500 点 · UTC+7';
  $('equity-legend').innerHTML = snapshot.accounts.map((a, i) => `<span style="color:${a.status === '已停止' ? '#899580' : COLORS[i % COLORS.length]}">● ${escape(a.name)}${a.status === '已停止' ? ' · 历史' : ''}</span>`).join('');
  if (!chartAvailable()) { $('equity-error').hidden = false; $('equity-error').textContent = '图表库加载失败，请检查 CDN 连接后刷新。账户数据仍可查看。'; return; }
  try {
    equityChart?.destroy(); equityChart = createEquityChart(snapshot.accounts); $('equity-error').hidden = true;
  } catch { $('equity-error').hidden = false; $('equity-error').textContent = '权益曲线暂时无法绘制。'; }
}
function refreshHealth() {
  renderPinnedBalance();updateStreamStatus();
  const healthy = priceAt && Date.now() - priceAt < 24000 && !errors.has('prices');
  if (!snapshot) return;
  const staleGenerated = Date.now() - Date.parse(snapshot.generated_at) > 15 * 60000;
  const staleSource = snapshot.accounts.filter(a => a.status !== '已停止').some(a => !a.updated_at || Date.now() - Date.parse(a.updated_at) > 15 * 60000);
  $('snapshot-age').textContent = staleGenerated || staleSource ? '数据可能延迟' : '快照在 15 分钟内更新';
  $('snapshot-age').className = `pill ${staleGenerated || staleSource ? 'stale' : 'up'}`;
  $('snapshot-age').title = staleSource ? '部分模拟账户的源数据超过 15 分钟未更新' : '';
  if (publicAccount) return;
  $('home-snapshot-status').textContent = `${staleGenerated || staleSource ? '数据可能延迟 · ' : ''}快照生成 ${time(snapshot.generated_at)} UTC+7`;
  $('home-snapshot-status').className = staleGenerated || staleSource ? 'stale' : 'muted';
}
function renderHome() {
  const ticker = tickers.find(r => r.id === focusSymbol), rank = top.find(r => r.id === focusSymbol)?.rank;
  const hourly = candleCache.get(focusSymbol + '/1H');
  const technical = hourly ? technicalStatus(hourly.bars) : { count: null, cross: '等待 1 小时 K 线' };
  const publicMetrics = summarizeAccounts(publicAccount, tickers);
  const metrics = publicAccount ? (publicMetrics ? {positions:publicMetrics.positions.length,accounts:publicMetrics.accounts,equity:publicMetrics.equity,locked:publicMetrics.accounts.some(a=>a.state==='已停手'),worst:null} : null) : null;

  const details = {};
  details.umi = `${focusSymbol.split('-')[0]} · 会议标的${ticker ? ` · ${price(ticker.last)} USDT · 24 小时 ${signed(ticker.change)}%` : ''}`;
  if (technical.count !== null) details.tech = `1 小时六条件 ${technical.count}/6 · ${technical.cross}`;
  if (ticker?.turnover != null) details.industry = `24 小时成交额 ${compact(ticker.turnover)} USDT${rank ? ` · 第 ${rank}/30` : ''}`;
  if (metrics) {
    details.risk = `当前 ${metrics.positions} 仓 · ${metrics.accounts.length} 个盘${metrics.locked ? ' · 锁仓' : ''}`;
    details.trader = `主力盘权益 ${num(metrics.equity)} USDT`;
  }
  const teamKey=JSON.stringify([team,Object.keys(ROLES).map(r=>roleState(team,r,{offlineMinutes:config.offlineMinutes}).state),reducedMotion(),document.hidden]);
  if(teamKey!==teamRenderKey){
    $('role-cards').innerHTML=teamCards(team,details,{offlineMinutes:config.offlineMinutes,reduced:reducedMotion(),hidden:document.hidden});teamRenderKey=teamKey;
  }else for(const [role,text] of Object.entries(details)){
    const metric=$('role-cards').querySelector(`[data-role="${role}"] .team-metric`);if(metric)metric.textContent=text;
  }
  $('room-symbol').textContent = coin;
  const active = candleCache.get(coin + '/' + timeframe);
  const analysis = active ? analyze(active.bars) : null;
  const chartTicker=tickers.find(r=>r.id===coin);
  $('room-ticker').innerHTML = `${escape(coin)}　<span class="${tone(chartTicker?.change)}">${price(chartTicker?.last)} USDT</span>　${timeframe === '1H' ? '1 小时' : '4 小时'} 六条件 ${analysis?.ready ? analysis.count : '—'}/6`;
  // Keep the original snapshot metrics for the legacy account route. The home
  // view is authoritative from account.json, including future live snapshots.
  renderPublicHome();
}
async function refreshPublicAccount() {
  if (publicBusy) return;
  publicBusy=true;
  try {
    const response=await fetch(`./paper/account.json?t=${Date.now()}`,{cache:'no-store',credentials:'omit',signal:AbortSignal.timeout(12000)});
    if (!response.ok) throw new Error('公开账户快照读取失败');
    const data=await response.json();
    if (!validAccount(data)) throw new Error('公开账户快照格式无效');
    const changed=publicAccount?.updated_at !== data.updated_at || publicAccount?.mode !== data.mode;
    const freshFills=fillRecords.update(mainAccounts(data).flatMap(a=>a.fills));
    publicAccount=data;renderPinnedBalance();
    for(const fill of freshFills)toast(`新成交 · ${fill.symbol.split('-')[0]} ${fill.kind==='open'?'开仓':'平仓'} @ ${fill.price}`);
    setError('account',null);syncHomeCoin();renderScan();
    if(route==='home'){renderHome();if(changed || !equityChart)renderBalance();} else if(route==='coin')renderDecisions();
  }catch{setError('account','账户快照暂无有效更新');renderPinnedBalance();}
  finally{publicBusy=false;}
}
function renderBalance() {
  if(!publicAccount || route!=='home')return;
  $('equity-legend').textContent='主力盘权益 · USDT · UTC+7';
  $('equity-panel').querySelector('h2').textContent='EQUITY / 权益轨迹';
  $('equity-panel').querySelector('.panel-heading p').textContent='主力盘 · 真实观测点';
  const points=aggregateCurve(publicAccount.accounts);
  equityChart?.destroy();equityChart=null;
  $('equity-error').hidden=Boolean(points.length);
  if(!points.length){$('equity-error').textContent='暂无权益曲线';return;}
  if(!chartAvailable()){$('equity-error').hidden=false;$('equity-error').textContent='图表库暂无连接';return;}
  try{equityChart=createBalanceChart(points);}catch{$('equity-error').hidden=false;$('equity-error').textContent='权益图暂无';}
}
function renderPublicHome() {
  const summary=summarizeAccounts(publicAccount,tickers);
  const mode=publicAccount?.mode==='live'?'实盘':'模拟盘';
  $('execution-metrics').innerHTML=`<span>今日成交 <b>${summary?num(summary.today.length,0)+' 笔':'—'}</b></span><span>今日成交额 <b>${compact(summary?.turnover)} USDT</b></span><span>持仓名义金额 <b>${compact(summary?.size)} USDT</b></span>`;
  $('mode-tag').textContent=mode;$('execution-mode').textContent=mode;
  $('bot-pnl').textContent=summary?signed(summary.pnl)+' USDT':'—';
  $('bot-pnl').className=tone(summary?.pnl);
  $('bot-positions').textContent=summary?summary.positions.length+' 仓':'—';
  renderPinnedBalance();
  $('total-pnl').innerHTML=summary?`<span>权益 ${num(summary.equity)} USDT</span><span class="${tone(summary.pnl)}">总盈亏 ${signed(summary.pnl)} USDT${summary.initial>0?' / '+signed(summary.pnl/summary.initial*100)+'%':''}</span>`:'暂无已启动策略';
  const stale=publicAccount && Date.now()-Date.parse(publicAccount.updated_at)>config.offlineMinutes*60000;
  const sourceStale=summary?.accounts.some(({account:a})=>!a.updated_at || Date.now()-Date.parse(a.updated_at)>config.offlineMinutes*60000);
  $('home-snapshot-status').textContent=publicAccount?`${stale || sourceStale?'数据可能延迟 · ':''}${time(publicAccount.updated_at)} UTC+7`:'暂无快照时间';
  $('home-snapshot-status').className=stale || sourceStale?'stale':'muted';
  const positions=summary?.positions || [];
  $('live-position-count').textContent=summary?positions.length+' 仓':'—';
  $('live-positions').innerHTML=positions.length?positions.map(p=>`<tr><td><a href="#/coin/${encodeURIComponent(p.symbol)}">${escape(p.symbol.replace('-USDT-SWAP',''))}</a><small class="position-source">${p.strategy==='manual'?'会议单':escape(p.account)}</small></td><td class="${p.side===1?'up':'down'}">${p.side===1?'多':'空'}</td><td>${price(p.entry)}</td><td>${price(p.stop)}</td><td>${price(p.take_profit)}</td><td>${Number.isFinite(p.leverage)?num(p.leverage,1)+'×':'—'}</td><td class="${tone(p.pnl)}">${signed(p.pnl)}</td></tr>`).join(''):'<tr><td colspan="7" class="empty">暂无持仓</td></tr>';
  $('recent-fills').innerHTML=summary?.fills.length?summary.fills.slice(0,8).map(f=>`<li><div><a href="#/coin/${encodeURIComponent(f.symbol)}">${escape(f.symbol.replace('-USDT-SWAP',''))}</a><span class="${f.side===1?'up':f.side===-1?'down':''}">${f.side===1?'多':f.side===-1?'空':'—'} / ${f.kind==='open'?'开仓':'平仓'}</span><time>${time(f.timestamp)}</time></div><div><span>${num(f.qty,4)} × ${price(f.price)}</span><span class="${tone(f.pnl)}">${f.kind==='close'?signed(f.pnl)+' USDT':'成交额 '+compact(f.notional)}</span></div></li>`).join(''):'<li class="empty">暂无成交</li>';
  const accounts=mainAccounts(publicAccount);
  const main=accounts[0];
  const manual=main?.manual_status?.length?main.manual_status:scan?.manual_status || [];
  $('manual-orders-panel').hidden=!manual.length;
  $('manual-orders').innerHTML=manual.map(r=>`<tr><td>${escape(r.symbol?.replace('-USDT-SWAP','') || '—')}</td><td class="${r.side===1?'up':r.side===-1?'down':''}">${r.side===1?'多':r.side===-1?'空':'—'}</td><td>${price(r.limit)}</td><td>${price(r.stop)}</td><td>${price(r.take_profit)}</td><td>${time(r.valid_until)}</td><td>${escape(r.status)}</td></tr>`).join('');
  $('enabled-strategies').innerHTML=main?strategyEntries(main).map(({name,mode})=>`<div>${escape(strategyName(name))} <b>${escape(mode || '入场方式未提供')}</b></div>`).join('') || '暂无启用策略':'等待主力盘快照';
  $('strategy-states').innerHTML=accounts.length?accounts.map(a=>{
    const metric=summary?.accounts.find(m=>m.account.id===a.id),state=metric?.state || '未启动';
    const enabled=state!=='未启动' && state!=='已停止';
    return `<div class="strategy-row"><span>${escape(a.name || (a.mode==='live'?'实盘策略':'模拟策略'))}</span><span class="strategy-state ${state==='运行中'?'up':state==='已停手'?'down':'muted'}">${state}</span><input type="checkbox" role="switch" aria-label="${escape(a.name || '策略')}开关，只读" ${enabled?'checked':''} disabled></div>`;
  }).join(''):'<p class="empty">暂无策略状态</p>';
  $('daily-risk').innerHTML=summary?summary.accounts.map(({account:a,loss})=>{
    const remaining=loss===null?null:Math.max(0,a.daily_loss_limit-loss);
    const percent=loss===null?0:Math.min(100,loss/a.daily_loss_limit*100);
    return `<div class="loss-item"><div><span>${escape(a.name || '策略')} · 日亏停手线 ${num(a.daily_loss_limit*100,0)}%</span><strong class="${remaining===0?'down':'up'}">${remaining===null?'—':num(remaining*100)+'%'} <small>剩余</small></strong></div><progress max="100" value="${percent}" aria-label="当日亏损额度使用比例" ${loss===null?'data-missing="true"':''}></progress><small>当日亏损 ${loss===null?'—':num(loss*100)+'%'}${loss===null?' · 暂无当日基准':''}</small></div>`;
  }).join(''):'暂无当日亏损数据';
  $('room-risk-params').innerHTML=summary?summary.accounts.map(({account:a,loss})=>{
    const r=a.risk;
    return `<article class="risk-config"><h3>${escape(a.name || '策略')}</h3>${r?`<div class="risk-config-grid"><span>单笔风险 <b>${num(r.risk_per_trade*100)}%</b></span><span>同向风险 <b>${Number.isFinite(r.same_direction_risk_limit)?num(r.same_direction_risk_limit*100)+'%':'—'}</b></span><span>逐仓杠杆 <b>${r.leverage_tiers?num(r.leverage_tiers.turnover_gte_50000000,0)+'× / '+num(r.leverage_tiers.turnover_lt_50000000,0)+'×':Number.isFinite(r.leverage)?num(r.leverage,0)+'×':'—'}</b></span><span>日亏上限 <b>${num(a.daily_loss_limit*100)}%</b></span></div>`:'<p class="muted">暂无风控细项</p>'}<small>当日亏损 ${loss===null?'—':num(loss*100)+'%'}</small></article>`;
  }).join(''):'<p class="empty">暂无实际风控参数</p>';
  const strategyNames={breakout:'突破放量',mean_reversion:'均值回归',ema:'EMA 趋势'};
  const paramNames={fast:'快线',slow:'慢线',lookback:'回看',volume:'成交额倍数',rsi:'RSI 阈值',trend:'趋势距离'};
  $('strategy-params').innerHTML=accounts.map(a=>Object.entries(a.strategies || {}).map(([key,values])=>`<div class="strategy-parameters"><h3>${escape(a.name || '策略')} / ${strategyNames[key] || '策略'}</h3><dl class="thresholds">${Object.entries(values).filter(([k])=>Object.hasOwn(paramNames,k)).map(([k,v])=>`<div><dt>${paramNames[k]}</dt><dd>${num(v,Number.isInteger(v)?0:3)}</dd></div>`).join('')}</dl></div>`).join('')).join('') || '<p class="empty">暂无策略参数</p>';
  renderDecisions();
  $('history-summary').innerHTML=snapshot?snapshot.accounts.filter(a=>['paper_1h','paper_4h','paper_1h_aggr','paper_4h_aggr'].includes(a.id)).map(a=>`<article><span>${escape(a.id)}</span><span class="pill">已停止</span><strong>${num(a.marked_equity)} <small>USDT</small></strong></article>`).join(''):'暂无历史快照';
}
function renderDecisions() {
  const d=publicAccount?.decisions;
  const bias={long:'偏多',short:'偏空',watch:'观察',ban:'禁开仓'};
  const rule=d?.symbols?.[coin];
  $('coin-decision').innerHTML=`<span class="eyebrow">MEETING / 会议结论 · ${escape(coin.replace('-USDT-SWAP',''))}</span><strong>${rule?bias[rule.bias] || '—':'暂无'}</strong><p>${escape(rule?.note || '暂无会议结论')}</p>`;
  if(!d || d.status==='missing'){$('decisions-panel').innerHTML='<p class="muted">暂无决议</p><p class="muted">事件窗口：暂无</p>';return;}
  const windows=d.blackout_windows.filter(w=>Date.parse(w.end)>Date.now());
  $('decisions-panel').innerHTML=`<p>${escape(d.meeting || '暂无会议名称')} · 版本 ${escape(d.version || '—')}</p><small>${time(d.updated_at)} UTC+7</small><p>全局仓位系数 ${num(d.global_size_factor)}</p>${Object.entries(d.symbols).map(([symbol,r])=>`<article><strong>${escape(symbol.replace('-USDT-SWAP',''))} · ${bias[r.bias] || '—'}</strong><small>仓位系数 ${num(r.size_factor)}</small><p>${escape(r.note || '暂无')}</p></article>`).join('') || '<p>暂无币种决议</p>'}<h3>事件窗口</h3>${windows.length?windows.map(w=>`<article><span class="${Date.parse(w.start)<=Date.now()?'down':'muted'}">${Date.parse(w.start)<=Date.now()?'生效中':'待生效'} · ${escape(w.symbols.join(' / '))}</span><p>${time(w.start)} → ${time(w.end)} UTC+7</p><small>${escape(w.reason || '暂无原因')}</small></article>`).join(''):'<p class="muted">暂无</p>'}`;
}

async function refreshTechnical() {
  const key = focusSymbol + '/1H', cached = candleCache.get(key);
  if (cached && Date.now() - cached.at < 60000 || candleBusy.has(key)) return;
  candleBusy.add(key);
  try {
    const bars = parseCandles(await api.get('market/candles', { instId: focusSymbol, bar: '1H', limit: 300 }, 8));
    if (!bars.length) throw new Error('接口未返回有效 K 线');
    candleCache.set(key, { bars, at: Date.now() }); setError('technical', null);
    if (route === 'home') { renderHome(); if (coin === focusSymbol && timeframe === '1H') showCandles(bars, candleCache.get(key).at); }
  } catch (error) { setError('technical', `技术卡：${description(error)}`); }
  finally { candleBusy.delete(key); }
}
let bt60Busy = false;
const btColumns = [
  ['segment', '数据段'], ['return_pct', '收益 %'], ['max_drawdown_pct', '最大回撤 %'], ['trades', '交易次数'], ['win_rate_pct', '胜率 %'], ['payoff_ratio', '盈亏比'], ['profit_factor', '盈利因子'], ['cost_over_abs_gross_pct', '成本 / 毛利绝对值 %'], ['cost_over_gross_winning_pct', '成本 / 盈利交易毛利 %'], ['cost_over_initial_pct', '成本 / 本金 %'],
];
const btExtra = [['fees','手续费'],['slippage','滑点'],['funding','净资金费'],['gross_pnl','毛利润净和'],['total_cost','总成本'],['gross_winning_pnl','盈利交易毛利'],['isolated_insurance_credit','逐仓保险补偿'],['liquidations','爆仓次数'],['daily_halt_days','日停手天数'],['average_daily_candidates','日均候选数'],['final_equity','期末权益'],['realized_losses_over_3pct','损失超过 3% 的交易数'],['max_trade_loss_pct_of_entry_equity','最大单笔损失 / 入场权益 %'],['reconciliation_error','对账误差']];
function btTable(rows, columns) {
  return `<div class="table-scroll" tabindex="0" aria-label="回测指标，可左右滑动"><table><thead><tr>${columns.map(([,label]) => `<th>${label}</th>`).join('')}</tr></thead><tbody>${rows.map(r => `<tr class="${r.qualified ? 'qualified-row' : ''}">${columns.map(([key]) => `<td class="${key === 'return_pct' ? tone(r[key]) : ''}">${key === 'segment' ? `${r.segment === '选参段' ? '样本内（选参段）' : escape(r.segment)}${r.qualified ? ' ✓ 合格' : ''}` : key === 'reconciliation_error' ? Number.isFinite(r[key]) ? r[key].toExponential(2) : '—' : num(r[key], ['trades','liquidations','daily_halt_days','realized_losses_over_3pct'].includes(key) ? 0 : 2)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}
async function refreshBT60() {
  if (bt60Busy) return; bt60Busy = true;
  try {
    const response = await fetch(`./paper/bt60.json?t=${Date.now()}`, { cache:'no-store', credentials:'omit', signal:AbortSignal.timeout(12000) });
    if (!response.ok) throw new Error('接口未找到回测快照');
    const data = await response.json();
    if (data.schema_version !== 1 || !Array.isArray(data.rows) || !data.rows.length) throw new Error('接口回测格式不完整');
    const groups = new Map();
    data.rows.forEach(row => { const key = row.strategy_code + '/' + row.timeframe; if (!groups.has(key)) groups.set(key, []); groups.get(key).push(row); });
    const utc = value => Number.isFinite(Date.parse(value)) ? new Date(value).toISOString().slice(0,16).replace('T',' ') : '数据缺失';
    const period = p => p ? `[${utc(p.start)}, ${utc(p.end)}) UTC` : '数据缺失：报告未提供区间';
    $('bt60-meta').textContent = `数据区间：${period(data.period)}；样本外：${period(data.out_of_sample)}；报告生成：${utc(data.generated_at)} UTC。金额单位 USDT。`;
    $('bt60-status').textContent = `${groups.size} 个策略 × 周期 · ${data.qualified?.length ?? '—'} 条合格记录`;
    const parameterLabels = { fast:'快线', slow:'慢线', lookback:'回看', volume:'成交额倍数', rsi:'强弱阈值', trend:'趋势距离' };
    $('bt60-results').innerHTML = [...groups.values()].map(rows => {
      const r = rows[0], qualified = rows.some(row => row.qualified);
      const params = Object.entries(r.parameters || {}).map(([k,v]) => `${parameterLabels[k] || escape(k)} ${num(v, Number.isInteger(v) ? 0 : 2)}`).join(' / ');
      return `<article class="bt60-group ${qualified ? 'qualified-group' : ''}"><h3><span>${escape(r.strategy)} × ${r.timeframe === '15m' ? '15 分钟' : r.timeframe === '1H' ? '1 小时' : '4 小时'}</span>${qualified ? '<span class="qualified-label">样本外合格组合</span>' : '<span class="muted">未入选合格表</span>'}</h3>${btTable(rows,btColumns)}<details><summary>完整成本与执行指标 · ${params}</summary>${btTable(rows, [btColumns[0], ...btExtra])}</details></article>`;
    }).join('');
    setError('bt60', null);
  } catch (error) { setError('bt60', `回测 BT60：${description(error)}`); $('bt60-status').textContent = '读取失败 · 等待重试'; }
  finally { bt60Busy = false; }
}

function navigate() {
  routeVersion++;
  const hash = location.hash || '#/';
  const match = /^#\/coin\/([A-Z0-9]+-USDT-SWAP)$/.exec(hash);
  route = match ? 'coin' : hash === '#/paper' ? 'paper' : hash === '#/market' ? 'market' : 'home';
  coin = match?.[1] || homeCoin;
  candleCharts?.destroy(); candleCharts = null; equityChart?.destroy(); equityChart = null;
  for (const page of ['home', 'market', 'coin', 'paper']) $(`${page}-page`).hidden = route !== page;
  document.querySelectorAll('[data-nav]').forEach(a => { const active = a.dataset.nav === (route === 'coin' ? 'market' : route); a.classList.toggle('active', active); if (active) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
  $('home-price-slot').append($('price-panel'));
  $('home-analysis-slot').append($('analysis-content'));
  $('home-equity-slot').append($('equity-panel'));
  if (route === 'home') $('home-market-slot').append($('market-content'));
  if (route === 'market') $('market-page').append($('market-content'));
  renderMarket();
  if (route === 'coin') { $('coin-price-slot').append($('price-panel')); $('coin-analysis-slot').append($('analysis-content')); }
  if (route === 'paper') $('paper-equity-slot').append($('equity-panel'));
  document.querySelectorAll('[data-timeframe]').forEach(b => { const active = b.dataset.timeframe === timeframe; b.classList.toggle('active', active); b.setAttribute('aria-pressed', String(active)); });
  setError('candles', null);
  document.title = route === 'coin' ? `${coin.split('-')[0]} · MODI 交易团队` : 'MODI · AI 交易团队';
  if (['home', 'coin'].includes(route)) {
    $('coin-title').textContent = coin.replace('-USDT-SWAP', '') + ' / USDT 永续'; renderQuote();
    $('signal-summary').innerHTML = '<strong>— <small>/ 6</small></strong><span>等待 K 线数据</span>';
    $('conditions').innerHTML = ''; $('signal-time').textContent = '仅分析最后一根已收盘 K 线'; $('levels').innerHTML = '<p class="muted">等待 K 线数据</p>'; $('candle-updated').textContent = '加载中'; $('chart-error').hidden = true;
    renderDecisions();
    const cached = candleCache.get(coin + '/' + timeframe); if (cached) showCandles(cached.bars, cached.at);
    refreshCandles(); refreshSlow();
    if (route === 'home') { syncHomeCoin(); refreshTeam(); refreshScan(); renderHome(); refreshTechnical(); if (snapshot) renderEquity(); refreshBT60(); }
  } else if (route === 'paper') { if (snapshot) { renderPaper(); renderEquity(); } }
  else { renderMarket(); refreshSlow(); }
  if (route === 'home' || route === 'paper') refreshSnapshot();
  refreshPublicAccount();syncStreams();
}
$('search').addEventListener('input', renderMarket);
$('market-table').addEventListener('click', event => {
  const button = event.target.closest('[data-sort]');
  if (button) {
    const key = button.dataset.sort;
    sortDirection = sortKey === key ? -sortDirection : ['symbol', 'rank'].includes(key) ? 1 : -1; sortKey = key;
    document.querySelectorAll('[data-sort]').forEach(b => {
      const th = b.closest('th'); th.setAttribute('aria-sort', b.dataset.sort === key ? sortDirection === 1 ? 'ascending' : 'descending' : 'none');
      b.innerHTML = b.innerHTML.replace(/ [↑↓]$/, '') + (b.dataset.sort === key ? sortDirection === 1 ? ' ↑' : ' ↓' : '');
    }); renderMarket(); return;
  }
  const row = event.target.closest('[data-coin]'); if (row && !event.target.closest('a')) location.hash = '#/coin/' + row.dataset.coin;
});
document.querySelectorAll('[data-timeframe]').forEach(button => button.addEventListener('click', () => {
  if (timeframe === button.dataset.timeframe) return;
  timeframe = button.dataset.timeframe;
  document.querySelectorAll('[data-timeframe]').forEach(b => { b.classList.toggle('active', b === button); b.setAttribute('aria-pressed', b === button); }); navigate();
}));
$('account-tabs').addEventListener('click', event => { const button = event.target.closest('[data-account]'); if (button) { accountId = button.dataset.account; tradePage = 0; renderPaper(); } });
$('reset-chart').addEventListener('click', () => candleCharts?.reset());
$('trades-prev').addEventListener('click', () => { tradePage--; renderTrades(); });
$('trades-next').addEventListener('click', () => { tradePage++; renderTrades(); });
window.addEventListener('hashchange', navigate);
window.addEventListener('load', () => { if (['home', 'coin'].includes(route)) { const cached = candleCache.get(coin + '/' + timeframe); if (cached) showCandles(cached.bars, cached.at); } if (['home', 'paper'].includes(route)) renderEquity(); });
function renderPinnedBalance(){
  const current=liveBalance(publicAccount,liveQuotes);
  rollNumber($('pinned-equity'),current?.equity);
  $('pinned-mode').textContent=publicAccount?(publicAccount.mode==='live'?'实盘':'模拟盘'):'—';
  $('pinned-daily').textContent=current?.daily!=null?`当日 ${signed(current.daily)} / ${signed(current.percent)}%`:'当日盈亏 · 暂无当日起始权益';
  $('pinned-daily').className=tone(current?.daily);
  $('pinned-source').textContent=current?.source || '暂无账户数据';
  const stale=publicAccount && (isStale(publicAccount.updated_at,Date.now(),config.offlineMinutes) || mainAccounts(publicAccount).filter(a=>!['未启动','已停止'].includes(a.status)).some(a=>isStale(a.updated_at,Date.now(),config.offlineMinutes)));
  $('pinned-time').textContent=publicAccount?`${stale?'延迟 · ':''}${time(publicAccount.updated_at)} UTC+7`:'— UTC+7';
  $('pinned-time').className=stale?'stale':'';
  if(route==='home')rollNumber($('total-equity'),current?.equity);
}
function updateStreamStatus(){
  const current=candleCache.get(coin+'/'+timeframe);
  const live=candleStream?.state==='实时' && Date.now()-candleStream.lastData<45000;
  const polled=current && Date.now()-current.at<90000;
  const state=live?'实时':polled?'轮询':'离线';
  const reason=live?'OKX 公共 WebSocket':polled?'公共 REST · 60 秒刷新':streamReason || '等待有效行情';
  $('stream-status').textContent=`${state} · ${reason}`;
  $('stream-status').className='pill '+(state==='实时'?'up':state==='离线'?'stale':'');
  const quotesLive=quoteStream?.state==='实时' && Date.now()-quoteStream.lastData<45000;
  $('connection-text').textContent=quotesLive?'实时':priceAt && Date.now()-priceAt<24000?'轮询':'离线';
  $('connection-dot').className='dot '+(quotesLive || priceAt && Date.now()-priceAt<24000?'live':'error');
  document.documentElement.classList.toggle('has-live-state',quotesLive || live || priceAt && Date.now()-priceAt<24000 || Object.keys(ROLES).some(r=>roleState(team,r,{offlineMinutes:config.offlineMinutes}).state!=='offline'));
}
function syncStreams(){
  if(document.hidden)return;
  const symbols=[...new Set([coin,...mainAccounts(publicAccount).filter(a=>!['未启动','已停止'].includes(a.status)).flatMap(a=>a.positions.map(p=>p.symbol))])].sort();
  const key=symbols.join(',');
  if(key!==quoteStreamKey){
    quoteStream?.stop();quoteStreamKey=key;
    quoteStream=new PublicStream({url:'wss://ws.okx.com:8443/ws/v5/public',args:symbols.flatMap(instId=>[{channel:'tickers',instId},{channel:'mark-price',instId}]),maxFailures:config.wsMaxFailures,
      onState:state=>{if(state!=='实时')liveQuotes.clear();renderPinnedBalance();updateStreamStatus();},onData:body=>{
        const id=body.arg?.instId;if(!symbols.includes(id))return false;
        const row=body.data[0],value=number(row.markPx ?? row.last),at=number(row.ts);
        if(!(value>0) || !at || Date.now()-at>45000 || at>Date.now()+60000)return false;
        const previous=liveQuotes.get(id);if(previous && previous.at>at)return false;
        liveQuotes.set(id,{price:value,at});
        const ticker=tickers.find(t=>t.id===id);if(ticker)ticker.last=value;
        renderPinnedBalance();if(route==='coin')renderQuote();
        if(route==='home')$('room-ticker').textContent=`${coin} · ${price(liveQuotes.get(coin)?.price)} USDT · ${timeframe} · OKX 实时报价`;
        return true;
      }});quoteStream.start();
  }
  const candleKey=['home','coin'].includes(route)?coin+'/'+timeframe:'';
  if(candleKey!==candleStreamKey){
    candleStream?.stop();candleStreamKey=candleKey;
    if(candleKey){const id=coin,bar=timeframe;
      candleStream=new PublicStream({url:'wss://ws.okx.com:8443/ws/v5/business',args:[{channel:'candle'+bar,instId:id}],maxFailures:config.wsMaxFailures,
        onState:(state,reason)=>{streamReason=reason;updateStreamStatus();},onData:body=>{
          if(body.arg?.instId!==id || body.arg?.channel!=='candle'+bar)return false;
          const next=parseCandles(body.data.filter(Array.isArray)).at(-1);if(!next || Date.now()/1000-next.time>(bar==='1H'?7200:28800))return false;
          const cached=candleCache.get(candleKey);if(!cached)return false; // REST seeds history first.
          const bars=mergeCandle(cached.bars,next),at=Date.now();candleCache.set(candleKey,{bars,at});
          if(coin===id && timeframe===bar){renderAnalysis(bars);if(chartAvailable()){
            if(!candleCharts)candleCharts=createCandleCharts();candleCharts.update(bars);candleCharts.markers(tradeMarkers(publicAccount,coin,bars));
          }$('candle-updated').textContent=`${bars.length} 根 · ${time(at)} 实时更新`;}
          return true;
        }});candleStream.start();
    }
  }
}
let eventsBusy=false,eventsData=null;
async function refreshEvents(){
 if(eventsBusy)return;eventsBusy=true;
 try{
  const response=await fetch(`./paper/events.json?t=${Date.now()}`,{cache:'no-store',credentials:'omit',signal:AbortSignal.timeout(12000)});
  if(!response.ok)throw new Error();const data=await response.json();if(!validEvents(data))throw new Error();
  const fresh=eventRecords.update(data.events),keys=new Set(fresh.map(recordKey));
  if(JSON.stringify(data.events)!==JSON.stringify(eventsData?.events)){
   const list=$('events-terminal'),nearBottom=list.scrollTop+list.clientHeight>=list.scrollHeight-40;
   list.replaceChildren();
   if(!data.events.length)list.innerHTML='<li class="empty">暂无事件</li>';
   for(const event of data.events){
    const li=document.createElement('li');li.className='event-'+event.type;
    const clock=document.createElement('time');clock.dateTime=event.ts;clock.textContent=time(event.ts);
    const line=document.createElement('span'),message=document.createElement('span');line.append(message);li.append(clock,line);list.append(li);
    if(keys.has(recordKey(event)))typeLine(message,eventText(event));else message.textContent=eventText(event);
    if(event.source_url){const link=document.createElement('a');link.href=event.source_url;link.textContent='来源 ↗';link.target='_blank';link.rel='noopener noreferrer';line.append(' ',link);}
   }
   if(!eventsData || nearBottom)list.scrollTop=list.scrollHeight;
  }
  eventsData=data;$('events-count').textContent=data.events.length+' 条';
  $('events-status').textContent=data.source_status==='missing'?'暂无事件源':`${isStale(data.generated_at,Date.now(),config.offlineMinutes)?'事件快照延迟 · ':''}${time(data.generated_at)} UTC+7 · 每 60 秒同步`;
  for(const event of fresh){
   if(event.type==='trade_opened'){roleEffect('trader','excited');toast(eventText(event));}
   if(event.type==='daily_halt' || event.type==='trade_closed' && /止损|强平/.test(event.reason || '')){roleEffect('risk','warning',event.type==='daily_halt'?'停手':'止损');toast(eventText(event));}
  }
 }catch{$('events-status').textContent='事件快照读取失败 · 保留已有记录';}
 finally{eventsBusy=false;}
}

document.addEventListener('visibilitychange',()=>{
 if(document.hidden){quoteStream?.stop();candleStream?.stop();quoteStreamKey='';candleStreamKey='';}
 else {syncStreams();refreshPrices();refreshPublicAccount();refreshTeam();refreshScan();refreshEvents();if(['home','coin'].includes(route))refreshCandles(true);}
});
navigate();refreshPrices();refreshEvents();
setInterval(()=>{if(!document.hidden){refreshPrices();renderPinnedBalance();if(route==='home')renderHome();}},8000);
setInterval(()=>{if(!document.hidden){
 if(['home','coin'].includes(route))refreshCandles();
 refreshSnapshot();refreshPublicAccount();refreshTeam();refreshScan();refreshBT60();refreshEvents();refreshSlow();
}},60000);
setInterval(()=>{if(!document.hidden){refreshHealth();if(route==='home')renderHome();
 for(const stream of [quoteStream,candleStream])if(stream?.state==='实时' && Date.now()-stream.lastData>45000)stream.socket?.close();
}},10000);
const updateClock = () => { $('utc-clock').textContent = new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Bangkok',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(Date.now()) + ' UTC+7'; $('day-number').textContent = 'DAY ' + dayNumber(config.startDate); };
updateClock(); setInterval(updateClock, 1000);
