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
        self.assertEqual([a['id'] for a in result['accounts']], ['paper_main'])
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
        main, = result['accounts']
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

    def test_meeting_directory_is_never_read(self):
        self.make_main()
        (self.root / 'paper_meeting').mkdir()
        (self.root / 'paper_meeting/state.json').write_text('{broken')
        result = validate_account(build_public_accounts(self.root, self.now))
        self.assertEqual([a['id'] for a in result['accounts']], ['paper_main'])

    def test_manual_status_and_positions_whitelist_and_scan_fallback(self):
        directory = self.make_main()
        state = json.loads((directory / 'state.json').read_text())
        order = dict(symbol='BTC-USDT-SWAP', side='short', entry=100, stop=110, take_profit=80,
                     valid_until='2026-11-03T18:00:00+07:00', id='PRIVATE_SENTINEL', note='PRIVATE_SENTINEL')
        statuses = ['pending', 'filled', 'expired', 'rejected', 'cancelled']
        state['manual_status'] = {str(i): dict(status=s, order=order, reason='PRIVATE_SENTINEL') for i, s in enumerate(statuses)}
        state['engines'] = {'BTC-USDT-SWAP': dict(position=dict(side=-1,qty=1,entry=100,stop=110,margin=20,strategy='manual'))}
        state['prices'] = {'BTC-USDT-SWAP': 99}
        (directory / 'state.json').write_text(json.dumps(state))
        result = validate_account(build_public_accounts(self.root, self.now))
        main = result['accounts'][0]
        self.assertEqual(main['positions'][0]['strategy'], 'manual')
        self.assertEqual([r['status'] for r in main['manual_status']], statuses)
        row = main['manual_status'][0]
        self.assertEqual((row['symbol'],row['side'],row['limit'],row['stop'],row['take_profit']), ('BTC-USDT-SWAP',-1,100,110,80))
        self.assertEqual(row['valid_until'], '2026-11-03T11:00:00.000000Z')
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))
        state.pop('manual_status')
        (directory / 'state.json').write_text(json.dumps(state))
        (directory / 'scan.json').write_text(json.dumps(dict(manual_status={'private':dict(status='pending')})))
        row = validate_account(build_public_accounts(self.root,self.now))['accounts'][0]['manual_status'][0]
        self.assertIsNone(row['symbol']);self.assertIsNone(row['limit']);self.assertEqual(row['status'],'pending')
        (directory / 'scan.json').write_text('{broken')
        self.assertEqual(build_public_accounts(self.root,self.now)['accounts'][0]['manual_status'], [])

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
