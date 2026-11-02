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
        self.assertEqual(len(result['accounts']), 5)
        self.assertNotIn('paper_meeting', [a['id'] for a in result['accounts']])
        (self.root / 'paper_meeting/state.json').write_text('{broken')
        self.assertEqual(len(m.build_snapshot(self.root)['accounts']), 5)
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



class ScanTests(unittest.TestCase):
    def test_scan_whitelist_cutoff_and_atomic_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);directory=root/'paper_main';directory.mkdir()
            now=datetime(2026,11,2,tzinfo=timezone.utc)
            row=dict(timestamp='2026-11-01T01:00:00Z',instId='BTC-USDT-SWAP',strategy='mean_reversion',side=1,opened=False,reason='maker_pending',private_note='SECRET_SENTINEL')
            raw=dict(schema_version=1,generated_at='2026-11-02T00:00:00Z',instruments=[dict(instId='BTC-USDT-SWAP',quote_24h=6e7,spread=.001,leverage_cap=10,bar_ts=1,signals={'mean_reversion':1,'breakout':None},held=True,signal_status='ok',secret='SECRET_SENTINEL')],recent_signals=[row,dict(row,timestamp='2026-10-30T23:59:59Z'),dict(row,timestamp='2026-11-03T00:00:00Z')],positions=[dict(instId='BTC-USDT-SWAP',strategy='mean_reversion',side=1,entry_time=row['timestamp'],secret='SECRET_SENTINEL')],api_key='SECRET_SENTINEL')
            raw['manual_status']={'private-order':dict(status='pending',order=dict(symbol='BTC-USDT-SWAP',side='long',entry=100,stop=90,take_profit=120,valid_until='2026-11-03T00:00:00Z',note='SECRET_SENTINEL'))}
            raw['positions'][0]['strategy']='manual'
            source=directory/'scan.json';source.write_text(json.dumps(raw));before=source.read_bytes()
            scan=m.build_scan(root,now)
            self.assertEqual(len(scan['instruments']),1);self.assertEqual(len(scan['recent_signals']),1)
            self.assertEqual(scan['instruments'][0]['signals']['mean_reversion'],1)
            self.assertEqual(scan['recent_signals'][0]['reason'],'maker_pending')
            self.assertEqual(scan['manual_status'][0]['limit'],100)
            self.assertEqual(scan['positions'][0]['strategy'],'manual')
            self.assertNotIn('SECRET_SENTINEL',json.dumps(scan))
            output=root/'public/scan.json';m.write_snapshot(scan,output)
            self.assertEqual(json.loads(output.read_text()),scan)
            self.assertEqual(source.read_bytes(),before)
            self.assertFalse(output.with_suffix('.tmp').exists())

    def test_missing_scan_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=m.build_scan(tmp)
            self.assertEqual(result['source_status'],'missing')
            self.assertIsNone(result['generated_at'])
            self.assertEqual(result['instruments'],[])

class StrategySnapshotTests(unittest.TestCase):
    setUp=SnapshotTests.setUp

    def test_current_strategy_modes_are_published_from_state(self):
        directory=self.root/'paper_main'
        shutil.copytree(self.root/'paper_4h',directory)
        raw=dict(self.state,**m.LEGACY_RISK,enabled_strategies=['mean_reversion'],
                 strategies={'mean_reversion':{'rsi':25,'trend':.02}},entry_mode='taker',
                 entry_mode_by_strategy={'mean_reversion':'maker','breakout':'taker'})
        (directory/'state.json').write_text(json.dumps(raw))
        accounts=m.build_public_accounts(self.root)['accounts']
        main=next(a for a in accounts if a['id']=='paper_main')
        self.assertEqual(main['enabled_strategies'],['mean_reversion'])
        self.assertEqual(main['entry_mode_by_strategy'],{'mean_reversion':'maker'})
        raw.pop('enabled_strategies');raw.pop('entry_mode_by_strategy');raw['entry_mode']='maker'
        (directory/'state.json').write_text(json.dumps(raw))
        main=m.build_public_accounts(self.root)['accounts'][0]
        self.assertEqual(main['entry_mode_by_strategy'],{'mean_reversion':'maker'})

if __name__ == '__main__':
    unittest.main()
