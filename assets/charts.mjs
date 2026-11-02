import { ema, rsi, macd } from './indicators.mjs';
export const COLORS = ['#b6ff3b', '#79bfff', '#ffce70', '#c995ff', '#70e3be', '#ff9d63', '#e788ca', '#b5c7cf'];
const up = '#b6ff3b', down = '#ff647c';
const formatter = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Bangkok', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
export function chartAvailable() { return Boolean(globalThis.LightweightCharts); }
function makeChart(element) {
  const chart = LightweightCharts.createChart(element, {
    width: element.clientWidth, height: element.clientHeight,
    layout: { background: { color: '#0b100c' }, textColor: '#91a283', fontSize: 10, fontFamily: 'JetBrains Mono, monospace' },
    grid: { vertLines: { color: '#1c281a' }, horzLines: { color: '#1c281a' } },
    rightPriceScale: { borderColor: '#34442b', minimumWidth: 78 },
    timeScale: { borderColor: '#34442b', timeVisible: true, secondsVisible: false, rightOffset: 3,
      tickMarkFormatter: time => formatter.format(new Date(Number(time) * 1000)) },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    localization: { locale: 'zh-CN', timeFormatter: time => formatter.format(new Date(Number(time) * 1000)) },
    handleScroll: { vertTouchDrag: false }, handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
  });
  const observer = new ResizeObserver(() => chart.applyOptions({ width: element.clientWidth, height: element.clientHeight }));
  observer.observe(element);
  return { chart, destroy() { observer.disconnect(); chart.remove(); } };
}
function line(chart, color, title, options = {}) {
  return chart.addLineSeries({ color, title, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, ...options });
}
function seriesData(bars, values) { return bars.flatMap((b, i) => Number.isFinite(values[i]) ? [{ time: b.time, value: values[i] }] : []); }
export function createCandleCharts() {
  const groups = ['price', 'volume', 'rsi', 'macd'].map(name => makeChart(document.getElementById(`${name}-chart`)));
  const [price, volume, strength, convergence] = groups.map(g => g.chart);
  const candles = price.addCandlestickSeries({ upColor: up, downColor: down, borderVisible: false, wickUpColor: up, wickDownColor: down, priceLineVisible: false });
  const averages = [line(price, up, 'EMA20'), line(price, '#edc879', 'EMA50'), line(price, '#ba9aff', 'EMA200')];
  const vol = volume.addHistogramSeries({ priceFormat: { type: 'volume' }, priceLineVisible: false, lastValueVisible: false });
  const rs = line(strength, '#ba9aff', 'RSI14');
  for (const value of [30, 70]) rs.createPriceLine({ price: value, color: '#536176', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '' });
  const dif = line(convergence, '#80aaff', 'DIF'), dea = line(convergence, '#edc879', 'DEA');
  const hist = convergence.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false, priceFormat: { type: 'price', precision: 6, minMove: .000001 } });
  let syncing = false, initialized = false;
  const subscriptions = groups.map(({ chart }) => {
    const handler = range => {
      if (!range || syncing) return;
      syncing = true;
      for (const target of groups) if (target.chart !== chart) target.chart.timeScale().setVisibleLogicalRange(range);
      syncing = false;
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(handler);
    return handler;
  });
  return {
    update(bars) {
      const range = initialized ? price.timeScale().getVisibleLogicalRange() : null;
      const closes = bars.map(b => b.close), mc = macd(closes);
      const minimum = Math.min(...closes), precision = minimum >= 100 ? 2 : minimum >= 1 ? 4 : minimum >= .01 ? 6 : 8;
      const priceFormat = { type: 'price', precision, minMove: 10 ** -precision };
      candles.applyOptions({ priceFormat }); averages.forEach(a => a.applyOptions({ priceFormat }));
      candles.setData(bars.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })));
      [20, 50, 200].forEach((period, i) => averages[i].setData(seriesData(bars, ema(closes, period))));
      vol.setData(bars.map(b => ({ time: b.time, value: b.volume, color: b.close >= b.open ? '#7ee7c380' : '#f3818c80' })));
      // 空值用 whitespace 对齐全部副图的逻辑索引。
      const aligned = values => bars.map((b, i) => Number.isFinite(values[i]) ? { time: b.time, value: values[i] } : { time: b.time });
      rs.setData(aligned(rsi(closes))); dif.setData(aligned(mc.dif)); dea.setData(aligned(mc.dea));
      hist.setData(bars.map((b, i) => mc.histogram[i] === null ? { time: b.time } : { time: b.time, value: mc.histogram[i], color: mc.histogram[i] >= 0 ? '#7ee7c380' : '#f3818c80' }));
      price.timeScale().setVisibleLogicalRange(range || { from: Math.max(0, bars.length - 100), to: bars.length + 2 });
      initialized = true;
    },
    reset() { price.timeScale().fitContent(); },
    destroy() { groups.forEach((g, i) => { g.chart.timeScale().unsubscribeVisibleLogicalRangeChange(subscriptions[i]); g.destroy(); }); },
  };
}
export function createEquityChart(accounts) {
  const group = makeChart(document.getElementById('equity-chart'));
  accounts.forEach((account, i) => {
    const series = line(group.chart, account.status === '已停止' ? '#687266' : COLORS[i % COLORS.length], account.name, { lineWidth: 2, lineStyle: account.status === '已停止' ? 2 : 0, priceFormat: { type: 'price', precision: 2, minMove: .01 } });
    const unique = new Map(account.equity.map(p => [Math.floor(Date.parse(p.timestamp) / 1000), p.equity]));
    series.setData([...unique].sort(([a], [b]) => a - b).map(([time, value]) => ({ time, value })));
  });
  group.chart.timeScale().fitContent();
  return group;
}

// The home balance curve contains only the current public snapshot's accounts.
export function createBalanceChart(points) {
  const group=makeChart(document.getElementById('equity-chart'));
  const series=group.chart.addAreaSeries({topColor:'#b6ff3b48',bottomColor:'#b6ff3b02',lineColor:'#b6ff3b',lineWidth:2,priceLineVisible:false,lastValueVisible:false});
  series.setData(points);
  group.chart.timeScale().fitContent();
  return group;
}
