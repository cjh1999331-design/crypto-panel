import copy
import csv
import shutil
import importlib.util
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location('snapshot', Path(__file__).resolve().parents[1] / 'tools/make_snapshot.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        position = dict(side=1, qty=2, entry=100, stop=90, margin=20, entry_time='2026-11-01T00:00:00Z', liquidation_price=88)
        self.state = dict(balance=100, prices={'BTC-USDT-SWAP': 80, 'ETH-USDT-SWAP': 90},
                          engines={'BTC-USDT-SWAP': dict(position=position, trades=[]),
                                   'ETH-USDT-SWAP': dict(position=dict(position, side=-1, qty=1), trades=[])},
                          api_key='SECRET_SENTINEL', internal_path='/private/SECRET_SENTINEL', blocked=False)
        for account_id, _ in m.ACCOUNTS:
            directory = self.root / account_id
            directory.mkdir()
            (directory / 'state.json').write_text(json.dumps(self.state))
            (directory / 'trades.csv').write_text('symbol,entry_time,exit_time,side,qty,entry,exit,pnl,reason,api_key\nBTC-USDT-SWAP,2026-11-01T00:00:00Z,2026-11-01T01:00:00Z,1,2,100,101,1.5,SECRET_SENTINEL,SECRET_SENTINEL\n')
            (directory / 'equity.csv').write_text('timestamp,equity\n' + ''.join(f'2026-11-01T{i//3600:02d}:{i//60%60:02d}:{i%60:02d}Z,{100+i/100}\n' for i in range(1001)))
            events = [dict(event='network_error', timestamp='2026-11-02T00:00:00Z', error='SECRET_SENTINEL'),
                      dict(event='trade_opened', symbol='BTC-USDT-SWAP', **position, api_key='SECRET_SENTINEL'),
                      dict(event='poll', timestamp='2026-11-01T02:00:00Z', internal='SECRET_SENTINEL')]
            (directory / 'events.jsonl').write_text('\n'.join(json.dumps(e) for e in events) + '\n{"unfinished":')

    def test_values_whitelist_and_all_four_accounts(self):
        result = m.build_snapshot(self.root, datetime(2026, 11, 2, tzinfo=timezone.utc))
        self.assertEqual(result['schema_version'], 1)
        self.assertEqual(len(result['accounts']), 4)
        self.assertNotIn('SECRET_SENTINEL', json.dumps(result))
        self.assertNotIn('/private/', json.dumps(result))
        account = result['accounts'][0]
        # 多仓亏损封顶 -20；空仓盈 +10。
        self.assertEqual(account['marked_equity'], 90)
        self.assertEqual(account['positions'][0]['liquidation_price'], 88)
        self.assertTrue(account['risk']['legacy_defaults'])
        self.assertEqual(account['risk']['leverage'], 3)
        self.assertEqual(len(account['trades']), 2)
        self.assertEqual(account['trades'][0]['reason'], 'other')
        self.assertEqual(account['updated_at'], '2026-11-01T02:00:00.000000Z')
        self.assertLessEqual(len(account['equity']), 500)
        self.assertEqual(account['equity'][0]['equity'], 100)
        self.assertEqual(account['equity'][-1]['equity'], 110)

    def test_new_risk_and_closed_trade_dedup(self):
        directory = self.root / 'paper_4h'
        state = copy.deepcopy(self.state)
        state.update(risk_per_trade=.03, max_positions=6, leverage=10, daily_loss_limit=.05)
        state['engines']['BTC-USDT-SWAP']['trades'] = [dict(symbol='ignored', entry_time='2026-11-01T00:00:00Z', exit_time='2026-11-01T01:00:00Z', side=1, qty=2, entry=100, exit=101, pnl=2, reason='signal')]
        (directory / 'state.json').write_text(json.dumps(state))
        result = m.build_account(self.root, 'paper_4h', '测试')
        self.assertFalse(result['risk']['legacy_defaults'])
        self.assertEqual(result['risk']['max_positions'], 6)
        self.assertEqual(len(result['trades']), 2)
        self.assertEqual(result['trades'][0]['pnl'], 2)

    def test_invalid_source_keeps_previous_output(self):
        output = self.root / 'snapshot.json'
        output.write_text('previous')
        (self.root / 'paper_1h/state.json').write_text('{broken')
        with self.assertRaises(ValueError):
            m.write_snapshot(m.build_snapshot(self.root), output)
        self.assertEqual(output.read_text(), 'previous')

    def test_missing_source_and_nonfinite_balance_fail(self):
        path = self.root / 'paper_4h/state.json'
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            m.build_snapshot(self.root)
        path.write_text(json.dumps(dict(self.state, balance=float('nan'))))
        with self.assertRaises(ValueError):
            m.build_snapshot(self.root)

    def test_dynamic_accounts_and_real_daily_baseline(self):
        for account_id in ('paper_main', 'paper_meeting'):
            shutil.copytree(self.root / 'paper_4h', self.root / account_id)
            state = dict(self.state, initial=100, day='2026-11-02', day_start=103,
                         risk_per_trade=.03, max_positions=6, leverage=5, daily_loss_limit=.08)
            (self.root / account_id / 'state.json').write_text(json.dumps(state))
        result = m.build_snapshot(self.root)
        self.assertEqual(len(result['accounts']), 6)
        account = next(a for a in result['accounts'] if a['id'] == 'paper_main')
        self.assertEqual(account['initial'], 100)
        self.assertEqual(account['day_start'], 103)
        self.assertEqual(account['day'], '2026-11-02')
        self.assertEqual(account['risk']['daily_loss_limit'], .08)
        self.assertFalse(account['risk']['legacy_defaults'])
        # Unknown/new accounts cannot silently inherit old 5% limits.
        (self.root / 'paper_main/state.json').write_text(json.dumps(self.state))
        with self.assertRaises(ValueError):
            m.build_snapshot(self.root)

    def test_no_accounts_and_missing_daily_baseline(self):
        result = m.build_snapshot(self.root)
        self.assertIsNone(result['accounts'][0]['initial'])
        self.assertIsNone(result['accounts'][0]['day_start'])
        self.assertIsNone(result['accounts'][0]['day'])
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaises(ValueError):
                m.build_snapshot(empty)

    def make_bt60(self):
        root = self.root / 'results'
        root.mkdir()
        rows = [dict(strategy='SECRET_SENTINEL', strategy_code='ema', timeframe='1H',
                     segment=segment, parameters='{"fast":12,"secret":"SECRET_SENTINEL"}',
                     trades='45', return_pct='4.209946966548586', fees='6.3805010892878675',
                     payoff_ratio='', gross_pnl='NaN', api_key='SECRET_SENTINEL')
                for segment in ('选参段', '样本外', '全60天')]
        for name, data in [('bt60_summary.csv', rows), ('bt60_qualified.csv', [rows[1]])]:
            with (root / name).open('w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(data)
        (root / 'bt60_summary.md').write_text('生成时间：2026-11-02T12:06:59.319625+00:00。\n区间为 UTC [2026-09-03 00:00, 2026-11-02 00:00)，样本外为 [2026-10-13 00:00, 2026-11-02 00:00)。\nSECRET_SENTINEL')
        return root

    def test_bt60_values_qualified_whitelist_and_periods(self):
        root = self.make_bt60()
        before = {p.name:p.read_bytes() for p in root.iterdir()}
        result = m.build_bt60(root)
        self.assertEqual(len(result['rows']), 3)
        self.assertEqual(result['rows'][1]['return_pct'], 4.209946966548586)
        self.assertEqual(result['rows'][1]['fees'], 6.3805010892878675)
        self.assertIsNone(result['rows'][0]['payoff_ratio'])
        self.assertIsNone(result['rows'][0]['gross_pnl'])
        self.assertEqual([r['qualified'] for r in result['rows']], [False, True, False])
        self.assertTrue(all(r['qualified_combination'] for r in result['rows']))
        self.assertEqual(result['period']['start'], '2026-09-03T00:00:00.000000Z')
        self.assertEqual(result['out_of_sample']['start'], '2026-10-13T00:00:00.000000Z')
        self.assertEqual(result['note'], '价差条件无历史数据，未用于回测')
        self.assertNotIn('SECRET_SENTINEL', json.dumps(result))
        self.assertEqual({p.name:p.read_bytes() for p in root.iterdir()}, before)

    def test_bt60_missing_dates_and_mismatched_qualification(self):
        root = self.make_bt60()
        (root / 'bt60_summary.md').write_text('缺少日期')
        result = m.build_bt60(root)
        self.assertIsNone(result['period'])
        self.assertIsNone(result['generated_at'])
        p = root / 'bt60_qualified.csv'
        p.write_text(p.read_text().replace('ema', 'breakout'))
        with self.assertRaises(ValueError):
            m.build_bt60(root)

    def test_atomic_output_and_sampling(self):
        output = self.root / 'public/snapshot.json'
        result = m.build_snapshot(self.root)
        m.write_snapshot(result, output)
        self.assertEqual(json.loads(output.read_text()), result)
        self.assertFalse(output.with_suffix('.tmp').exists())
        self.assertEqual(m.downsample([]), [])
        self.assertEqual(m.downsample([1, 2]), [1, 2])
        self.assertEqual(m.numeric('NaN'), None)
        self.assertEqual(m.iso('SECRET_SENTINEL'), None)

    def test_archived_and_two_hour_liveness_boundary(self):
        now = datetime(2026, 11, 2, 13, 0, tzinfo=timezone.utc)
        self.assertTrue(all(a['status'] == '已停止' for a in m.build_snapshot(self.root, now)['accounts']))
        directory = self.root / 'paper_main'
        shutil.copytree(self.root / 'paper_4h', directory)
        state = dict(self.state, **m.LEGACY_RISK)
        (directory / 'state.json').write_text(json.dumps(state))
        (directory / 'equity.csv').write_text('timestamp,equity\n2026-11-02T10:59:59Z,100\n')
        os.utime(directory / 'state.json', (now.timestamp()-7201,)*2)
        self.assertEqual(m.build_account(self.root, 'paper_main', '主力盘', now)['status'], '已停止')

        os.utime(directory / 'state.json', (now.timestamp()-7200,)*2)
        self.assertEqual(m.build_account(self.root, 'paper_main', '主力盘', now)['status'], '运行中')
        os.utime(directory / 'state.json', (now.timestamp()-7201,)*2)
        (directory / 'equity.csv').write_text('timestamp,equity\n2026-11-02T12:59:59Z,100\n')
        self.assertEqual(m.build_account(self.root, 'paper_main', '主力盘', now)['status'], '运行中')
        # 明确 state 时间优先于文件拷贝产生的新 mtime。
        (directory / 'state.json').write_text(json.dumps(dict(state, updated_at='2026-11-02T10:00:00Z')))
        (directory / 'equity.csv').write_text('timestamp,equity\n')
        self.assertEqual(m.build_account(self.root, 'paper_main', '主力盘', now)['status'], '已停止')

    def test_main_dynamic_risk_schema_keeps_real_limits(self):
        directory = self.root / 'paper_main'
        shutil.copytree(self.root / 'paper_4h', directory)
        state = dict(self.state, risk_per_trade=.03, daily_loss_limit=.08, same_direction_risk_limit=.05,
                     leverage_tiers=dict(turnover_gte_50000000=10, turnover_lt_50000000=5, threshold_usdt=50000000,
                                         private_note='SECRET_SENTINEL'))
        (directory / 'state.json').write_text(json.dumps(state))
        risk = m.build_account(self.root, 'paper_main', '主力盘')['risk']
        self.assertIsNone(risk['max_positions'])
        self.assertIsNone(risk['leverage'])
        self.assertEqual(risk['same_direction_risk_limit'], .05)
        self.assertEqual(risk['leverage_tiers']['turnover_gte_50000000'], 10)
        self.assertNotIn('SECRET_SENTINEL', json.dumps(risk))
        self.assertFalse(risk['legacy_defaults'])
        for update in [dict(leverage=-1),dict(same_direction_risk_limit=None),dict(leverage_tiers={})]:
            (directory / 'state.json').write_text(json.dumps(dict(state, **update)))
            with self.assertRaises(ValueError):
                m.build_account(self.root, 'paper_main', '主力盘')



if __name__ == '__main__':
    unittest.main()
