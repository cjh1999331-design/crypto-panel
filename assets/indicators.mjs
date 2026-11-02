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

// Entry checks mirror bt60.engine.make_signal; EWM uses adjust=False.
function ewm(values,alpha){let prev=null;return values.map(v=>{if(!Number.isFinite(v))return null;prev=prev===null?v:alpha*v+(1-alpha)*prev;return prev;});}
export function analyze(candles,parameters=null) {
  const bars=candles.filter(b=>b.confirm==='1'),i=bars.length-1,bar=bars[i],closes=bars.map(b=>b.close);
  const e50=ewm(closes,2/51),e200=ewm(closes,2/201);
  const tr=bars.map((b,j)=>Math.max(b.high-b.low,j?Math.abs(b.high-closes[j-1]):0,j?Math.abs(b.low-closes[j-1]):0));
  const atr=ewm(tr,1/14);
  const gains=ewm(closes.map((c,j)=>j?Math.max(0,c-closes[j-1]):null),1/14),losses=ewm(closes.map((c,j)=>j?Math.max(0,closes[j-1]-c):null),1/14);
  const rs=closes.map((c,j)=>j>=14 && losses[j]>0?100-100/(1+gains[j]/losses[j]):null);
  const band=j=>{const list=closes.slice(j-19,j+1);if(list.length<20)return null;const mid=list.reduce((n,v)=>n+v,0)/20,sd=Math.sqrt(list.reduce((n,v)=>n+(v-mid)**2,0)/20);return {low:mid-2*sd,high:mid+2*sd};};
  const previous=band(i-1),current=band(i);
  const contiguous=bars.length>=201 && bars.slice(-200).every((b,j)=>b.time-bars[bars.length-201+j].time===3600);
  const configured=parameters && Number.isFinite(parameters.rsi) && Number.isFinite(parameters.trend);
  const ready=Boolean(contiguous && configured);
  const deviation=i>=0?Math.abs(e50[i]/e200[i]-1):null,slope=i>=5 && atr[i]>0?Math.abs(e50[i]-e50[i-5])/atr[i]:null;
  const volatility=i>=13 && bar?atr[i]/bar.close:null;
  const average=i>=20?bars.slice(i-20,i).reduce((n,b)=>n+b.turnover,0)/20:null;
  const volume=average>0?bar.turnover/average:null;
  const longRsi=configured && Number.isFinite(rs[i-1]) && rs[i-1]<parameters.rsi;
  const shortRsi=configured && Number.isFinite(rs[i-1]) && rs[i-1]>100-parameters.rsi;
  const longBand=Boolean(previous && current && closes[i-1]<previous.low && bar.close>=current.low);
  const shortBand=Boolean(previous && current && closes[i-1]>previous.high && bar.close<=current.high);
  const f=(v,d=2)=>Number.isFinite(v)?v.toFixed(d):'—';
  const checks=[
    {label:'启用配置 / 连续 1H 已收盘样本',pass:ready,detail:`${configured?'均值回归已启用':'等待主力盘启用配置'}；${bars.length} 根，需最近 201 根连续 1H`},
    {label:'趋势偏离度 |EMA50 / EMA200 − 1|',pass:configured && deviation!==null && deviation<parameters.trend,detail:`当前 ${f(deviation===null?null:deviation*100)}%；阈值 < ${f(configured?parameters.trend*100:null)}%`},
    {label:'EMA50 五根斜率 / ATR14',pass:slope!==null && slope<.8,detail:`当前 ${f(slope,3)}；阈值 < 0.80`},
    {label:'ATR14 / 收盘价',pass:volatility!==null && volatility>=.002 && volatility<=.035,detail:`当前 ${f(volatility===null?null:volatility*100,3)}%；范围 0.20%–3.50%`},
    {label:'成交额 / 前 20 根均值',pass:volume!==null && volume>=.8,detail:`当前 ${f(volume)}×；阈值 ≥ 0.80×`},
    {label:'前一根 RSI14',pass:longRsi || shortRsi,detail:`当前 ${f(rs[i-1])}；多 < ${f(configured?parameters.rsi:null,0)} ${longRsi?'满足':'未满足'} / 空 > ${f(configured?100-parameters.rsi:null,0)} ${shortRsi?'满足':'未满足'}`},
    {label:'布林带回归（20 根 / 2σ）',pass:longRsi&&longBand || shortRsi&&shortBand,detail:`多：前收盘 ${f(closes[i-1],4)} < 前下轨 ${f(previous?.low,4)}，现收盘 ${f(bar?.close,4)} ≥ 下轨 ${f(current?.low,4)} ${longBand?'满足':'未满足'}；空：前收盘 > 前上轨 ${f(previous?.high,4)} 且现收盘 ≤ 上轨 ${f(current?.high,4)} ${shortBand?'满足':'未满足'}`},
  ];
  const common=checks.slice(0,5).every(c=>c.pass);
  const levels=i>=50?Object.fromEntries([20,50].flatMap(n=>[['high'+n,Math.max(...bars.slice(i-n,i).map(b=>b.high))],['low'+n,Math.min(...bars.slice(i-n,i).map(b=>b.low))]])):null;
  return {ready,bars,bar,checks,count:checks.filter(c=>c.pass).length,side:common && longRsi && longBand?1:common && shortRsi && shortBand?-1:0,levels,e20:ema(closes,20),e50:ema(closes,50),e200:ema(closes,200),rsi:rs};
}
