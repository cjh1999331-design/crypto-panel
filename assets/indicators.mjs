// EMA 使用首个 period 样本的 SMA 作种子，预热区返回 null。
export function ema(values, period) {
  if (!Number.isInteger(period) || period < 1) throw new RangeError('周期必须为正整数');
  const out = Array(values.length).fill(null);
  let sum = 0, count = 0, prev = null;
  const alpha = 2 / (period + 1);
  values.forEach((v, i) => {
    if (!Number.isFinite(v)) { sum = 0; count = 0; prev = null; return; }
    if (prev === null) {
      sum += v; count++;
      if (count === period) out[i] = prev = sum / period;
    } else out[i] = prev = prev + alpha * (v - prev);
  });
  return out;
}

export function rsi(values, period = 14) {
  if (!Number.isInteger(period) || period < 1) throw new RangeError('周期必须为正整数');
  const out = Array(values.length).fill(null);
  if (values.length <= period) return out;
  let gain = 0, loss = 0;
  const value = () => loss === 0 ? (gain === 0 ? 50 : 100) : 100 - 100 / (1 + gain / loss);
  for (let i = 1; i < values.length; i++) {
    const delta = values[i] - values[i - 1];
    if (i <= period) {
      gain += Math.max(delta, 0) / period; loss += Math.max(-delta, 0) / period;
      if (i === period) out[i] = value();
    } else {
      gain = (gain * (period - 1) + Math.max(delta, 0)) / period;
      loss = (loss * (period - 1) + Math.max(-delta, 0)) / period;
      out[i] = value();
    }
  }
  return out;
}

export function macd(values, fast = 12, slow = 26, signalPeriod = 9) {
  const f = ema(values, fast), s = ema(values, slow);
  const dif = values.map((_, i) => f[i] === null || s[i] === null ? null : f[i] - s[i]);
  const dea = ema(dif, signalPeriod);
  // 柱使用 DIF − DEA，不乘 2。
  return { dif, dea, histogram: dif.map((v, i) => v === null || dea[i] === null ? null : v - dea[i]) };
}

export function parseCandles(rows) {
  const byTime = new Map();
  for (const row of rows) {
    const [ts, o, h, l, c, vol, , quote, confirm] = row;
    const bar = { time: Number(ts) / 1000, open: Number(o), high: Number(h), low: Number(l), close: Number(c), volume: Number(vol), turnover: Number(quote), confirm: String(confirm) };
    if (row.length < 9 || [ts, o, h, l, c, vol, quote].some(v => v === '' || v == null) ||
      !Object.values(bar).filter(v => typeof v === 'number').every(Number.isFinite) ||
      bar.time <= 0 || bar.low <= 0 || bar.high < Math.max(bar.open, bar.close) || bar.low > Math.min(bar.open, bar.close) || bar.volume < 0 || bar.turnover < 0 || !['0', '1'].includes(bar.confirm)) continue;
    byTime.set(bar.time, bar);
  }
  return [...byTime.values()].sort((a, b) => a.time - b.time);
}

export function analyze(candles) {
  const bars = candles.filter(b => b.confirm === '1');
  const closes = bars.map(b => b.close);
  const e20 = ema(closes, 20), e50 = ema(closes, 50), e200 = ema(closes, 200);
  const rs = rsi(closes), mc = macd(closes);
  const i = bars.length - 1, bar = bars[i];
  if (bars.length < 51) return { ready: false, count: null, bars, e20, e50, e200, rsi: rs, macd: mc };
  const prev20 = bars.slice(i - 20, i), prev50 = bars.slice(i - 50, i);
  const high20 = Math.max(...prev20.map(b => b.high)), low20 = Math.min(...prev20.map(b => b.low));
  const high50 = Math.max(...prev50.map(b => b.high)), low50 = Math.min(...prev50.map(b => b.low));
  const average = prev20.reduce((sum, b) => sum + b.turnover, 0) / 20;
  const ratio = average > 0 ? bar.turnover / average : null;
  const location = bar.high > bar.low ? (bar.close - bar.low) / (bar.high - bar.low) : null;
  const checks = [
    { pass: bar.close > high20, close: bar.close, high20 },
    { pass: ratio !== null && ratio >= 1.5, turnover: bar.turnover, average, ratio },
    { pass: location !== null && location >= .7, location },
    { pass: e20[i] > e50[i] && bar.close > e20[i], close: bar.close, ema20: e20[i], ema50: e50[i] },
    { pass: rs[i] > 50 && rs[i] < 70, rsi: rs[i] },
    { pass: mc.histogram[i] > 0 && mc.histogram[i] > mc.histogram[i - 1], histogram: mc.histogram[i], previous: mc.histogram[i - 1] },
  ];
  return { ready: true, bars, bar, e20, e50, e200, rsi: rs, macd: mc, checks, count: checks.filter(c => c.pass).length, levels: { high20, low20, high50, low50 } };
}
