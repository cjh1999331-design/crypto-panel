import test from 'node:test';
import assert from 'node:assert/strict';
import { ema, rsi, macd, parseCandles, analyze } from '../assets/indicators.mjs';
import { normalizeTickers, positionPnL } from '../assets/api.mjs';
const near = (a, b, epsilon = 1e-9) => assert.ok(Math.abs(a - b) < epsilon, `${a} ≠ ${b}`);

test('EMA：SMA 种子、递推及预热空值', () => {
  assert.deepEqual(ema([1, 2, 3, 4, 5], 3), [null, null, 2, 3, 4]);
  const result = ema([10, 10, 10, 16, 10], 3);
  near(result[3], 13); near(result[4], 11.5);
  assert.deepEqual(ema([1, 2], 3), [null, null]);
  assert.throws(() => ema([1], 0), RangeError);
});

test('RSI14：Wilder 参考序列和边界行情', () => {
  const closes = [44.34,44.09,44.15,43.61,44.33,44.83,45.10,45.42,45.84,46.08,45.89,46.03,45.61,46.28,46.28,46.00,46.03,46.41,46.22,45.64,46.21];
  const values = rsi(closes);
  assert.equal(values[13], null);
  near(values[14], 70.4641350211, 1e-8);
  near(values[15], 66.2496185536, 1e-8);
  assert.equal(rsi(Array(30).fill(5)).at(-1), 50);
  assert.equal(rsi(Array.from({ length: 30 }, (_, i) => i)).at(-1), 100);
  assert.equal(rsi(Array.from({ length: 30 }, (_, i) => 30 - i)).at(-1), 0);
});

test('MACD：DIF/DEA 预热、默认周期及柱值不乘 2', () => {
  const linear = macd(Array.from({ length: 80 }, (_, i) => i + 1));
  assert.equal(linear.dif[24], null); near(linear.dif[25], 7);
  assert.equal(linear.dea[32], null); near(linear.dea[33], 7); near(linear.histogram.at(-1), 0);
  const small = macd([1, 2, 3, 2, 1, 2], 2, 3, 2);
  near(small.dif[3], 1 / 6); near(small.dea[3], 1 / 3); near(small.histogram[3], -1 / 6);
  near(small.dif[4], -1 / 9); near(small.histogram[4], -4 / 27);
});

function fixture() {
  const bars = Array.from({ length: 250 }, (_, i) => ({ time: 1700000000 + i * 3600, open: 100 + i * .02, close: 100 + i * .02 + Math.sin(i * 1.8) * .6, high: 106, low: 99, volume: 10, turnover: 1000, confirm: '1' }));
  bars.push({ time: 1700000000 + 250 * 3600, open: 105, close: 107, high: 107.5, low: 104, volume: 20, turnover: 1500, confirm: '1' });
  return bars;
}

test('六条件：逐项实际值、排除未收盘和信号本身、前 20/50 支撑阻力', () => {
  const bars = fixture(), result = analyze(bars);
  assert.equal(result.ready, true);
  assert.equal(result.checks[0].pass, true); assert.equal(result.levels.high20, 106);
  assert.equal(result.checks[1].pass, true); near(result.checks[1].ratio, 1.5);
  near(result.checks[2].location, 3 / 3.5); assert.equal(result.checks[2].pass, true);
  assert.equal(result.checks[3].pass, true);
  assert.equal(result.checks[4].pass, result.checks[4].rsi > 50 && result.checks[4].rsi < 70);
  assert.equal(result.checks[5].pass, true);
  assert.equal(result.count, result.checks.filter(c => c.pass).length);
  const pending = { ...bars.at(-1), time: bars.at(-1).time + 3600, close: 1000, high: 1001, turnover: 1e9, confirm: '0' };
  assert.deepEqual(analyze([...bars, pending]), result);
  const changed = bars.map(b => ({ ...b })); changed.at(-1).close = 106; changed.at(-1).turnover = 1499;
  const failed = analyze(changed);
  assert.equal(failed.checks[0].pass, false); assert.equal(failed.checks[1].pass, false); assert.equal(failed.checks[2].pass, false);
  assert.equal(result.levels.high50, 106); assert.equal(result.levels.low50, 99);
});

test('六条件：零波幅与零成交均值不产生无穷比值，样本不足不报信号', () => {
  const bars = fixture().map(b => ({ ...b, open: 1, close: 1, high: 1, low: 1, turnover: 0 }));
  const a = analyze(bars);
  assert.equal(a.checks[1].ratio, null); assert.equal(a.checks[1].pass, false);
  assert.equal(a.checks[2].location, null); assert.equal(a.checks[2].pass, false);
  assert.equal(a.checks[3].pass, false); assert.equal(a.checks[4].pass, false); assert.equal(a.checks[5].pass, false);
  assert.equal(analyze(bars.slice(0, 50)).ready, false);
});

test('K 线解析：倒序转正序、去重、USDT 成交额字段与 confirm', () => {
  const first = ['1700000000000', '10', '12', '9', '11', '5', '50', '550', '1'];
  const second = ['1700003600000', '11', '13', '10', '12', '6', '60', '720', '0'];
  const result = parseCandles([second, first, first, ['broken']]);
  assert.equal(result.length, 2); assert.equal(result[0].turnover, 550); assert.equal(result[1].confirm, '0');
});

test('行情单位与多空浮盈：USDT 永续过滤、币数量换算与逐仓下限', () => {
  const rows = normalizeTickers([{ instId: 'BTC-USDT-SWAP', last: '120', open24h: '100', volCcy24h: '10', vol24h: '9999' }, { instId: 'BTC-USD-SWAP', last: '120' }]);
  assert.equal(rows.length, 1); near(rows[0].change, 20); assert.equal(rows[0].turnover, 1200);
  const p = { side: 1, qty: 2, entry: 100, margin: 20 };
  assert.equal(positionPnL(p, 110), 20); assert.equal(positionPnL({ ...p, side: -1 }, 110), -20);
  assert.equal(positionPnL(p, 50, true), -20); assert.equal(positionPnL(p, undefined), null);
});
