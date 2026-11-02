import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from make_snapshot import build_public_accounts, build_decisions, clean_trade, clean_position, build_account
from validate_account import validate_account


class PublicAccountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = datetime(2026, 11, 2, 1, tzinfo=timezone.utc)

    def make_main(self):
        directory = self.root / 'paper_main'
        directory.mkdir()
        state = dict(balance=100, initial=100, day='2026-11-02', day_start=105, updated_at=self.now.isoformat(),
                     risk_per_trade=.03, daily_loss_limit=.08, same_direction_risk_limit=.05,
                     leverage_tiers=dict(turnover_gte_50000000=10, turnover_lt_50000000=5, threshold_usdt=50000000),
                     engines={}, prices={}, strategies={'breakout': {'lookback':20, 'private':'PRIVATE_SENTINEL'}})
        (directory / 'state.json').write_text(json.dumps(state))
        (directory / 'trades.csv').write_text('instId,entry_time,exit_time,side,quantity,entry,exit,net_pnl\nBTC-USDT-SWAP,2026-11-02T00:00:00Z,2026-11-02T00:30:00Z,1,2,100,101,1.8\n')
        (directory / 'events.jsonl').write_text(json.dumps(dict(event='trade_opened',symbol='BTC-USDT-SWAP',entry_time='2026-11-02T00:00:00Z',side=1,quantity=2,entry=100))+'\n')
        (directory / 'equity.csv').write_text('timestamp,equity\n2026-11-02T00:30:00Z,100\n')
        return directory

    def test_absent_accounts_are_null_not_fake_funded(self):
        result = validate_account(build_public_accounts(self.root, self.now))
        self.assertEqual(len(result['accounts']), 2)
        for a in result['accounts']:
            self.assertEqual(a['status'], '未启动')
            self.assertIsNone(a['balance'])
        bad = copy.deepcopy(result)
        bad['accounts'][0]['balance'] = 100
        with self.assertRaises(ValueError):
            validate_account(bad)

    def test_public_snapshot_actual_fills_and_daily_pnl(self):
        self.make_main()
        result = validate_account(build_public_accounts(self.root, self.now))
        main, missing = result['accounts']
        self.assertEqual(main['daily_pnl'], -5)
        self.assertEqual(main['daily_loss_limit'], .08)
        self.assertEqual([f['notional'] for f in main['fills']], [202,200])
        self.assertEqual(main['fills'][0]['pnl'], 1.8)
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))
        tomorrow = build_public_accounts(self.root, datetime(2026,11,3,tzinfo=timezone.utc))
        self.assertIsNone(tomorrow['accounts'][0]['daily_pnl'])

    def test_explicit_stopped_event_overrides_recent_mtime(self):
        directory = self.make_main()
        with (directory / 'events.jsonl').open('a') as f:
            f.write(json.dumps(dict(event='stopped',timestamp='2026-11-02T00:59:59Z'))+'\n')
        result = build_public_accounts(self.root,self.now)
        self.assertEqual(result['accounts'][0]['status'],'已停止')
        self.assertFalse(result['accounts'][0]['strategy_enabled'])
        self.assertEqual(result['accounts'][0]['balance'],100)

    def test_decisions_whitelist_and_redaction_before_truncation(self):
        raw = dict(version=2,updated_at=self.now.isoformat(),meeting='公开会议',global_size_factor=.5,
            symbols={'BTC-USDT-SWAP':dict(bias='watch',size_factor=.2,note='观察支撑'),
                     'ETH-USDT-SWAP':dict(bias='ban',size_factor=0,note='x'*201+'api_key=PRIVATE_SENTINEL')},
            blackout_windows=[dict(start='2026-11-02T02:00:00Z',end='2026-11-02T03:00:00Z',symbols=['*'],reason='事件窗口')],
            manual_orders=[dict(id='PRIVATE_SENTINEL')],api_key='PRIVATE_SENTINEL')
        (self.root/'decisions.json').write_text(json.dumps(raw))
        d=build_decisions(self.root)
        self.assertEqual(d['symbols']['BTC-USDT-SWAP']['note'],'观察支撑')
        self.assertIsNone(d['symbols']['ETH-USDT-SWAP']['note'])
        self.assertNotIn('manual_orders',d)
        self.assertNotIn('PRIVATE_SENTINEL',json.dumps(d))
        validate_account(build_public_accounts(self.root,self.now))

    def test_schema_rejects_unknown_fields_duplicates_and_bad_notional(self):
        self.make_main()
        result=build_public_accounts(self.root,self.now)
        for mutate in (lambda d:d.update(api_key='PRIVATE_SENTINEL'),
                       lambda d:d['accounts'].append(d['accounts'][0]),
                       lambda d:d['accounts'][0]['fills'][0].update(notional=1),
                       lambda d:d['accounts'][0].update(mode='live')):
            bad=copy.deepcopy(result);mutate(bad)
            with self.assertRaises(ValueError):validate_account(bad)
        live=copy.deepcopy(result);live['mode']='live'
        for a in live['accounts']:
            a['mode']='live';a['id']=a['id'].replace('paper_','live_')
        validate_account(live)


if __name__ == '__main__':
    unittest.main()
