import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from history_snapshot import build_history
from make_snapshot import build_decisions, build_public_accounts, build_scan, write_snapshot, sensitive


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.main = self.root / 'paper_main'
        self.main.mkdir()
        self.symbol = 'BTC-USDT-SWAP'
        self.ts = '2026-11-01T00:00:00Z'
        self.state = {'manual_status': {'private-order-id': {'status': 'filled', 'time': '2026-11-01T01:00:00Z', 'order': {'id': 'private-order-id', 'symbol': self.symbol, 'side': 'long', 'entry': 100}}}}
        self.decision = {'updated_at': '2026-11-01T01:00:00Z', 'manual_orders': [{'id': 'private-order-id', 'symbol': self.symbol, 'side': 'long', 'note': 'GROUP_CHAT_ORIGINAL'}]}
        self.trade = {'instId': self.symbol, 'strategy': 'manual', 'side': '1', 'quantity': '2', 'entry': '100', 'exit': '110', 'leverage': '5', 'margin': '40', 'net_pnl': '19', 'fee': '1', 'reason': 'target_live', 'entry_time': '2026-11-01T01:00:00Z', 'exit_time': '2026-11-01T02:00:00Z', 'order_id': 'private-order-id', 'note': 'GROUP_CHAT_ORIGINAL', 'api_key': 'SECRET_SENTINEL'}
        self.alerts = [{'ts': self.ts, 'wake': True, 'wake_index': 1, 'symbol': self.symbol, 'type': 'breakout', 'detail': 'GROUP_CHAT_ORIGINAL', 'author': 'PRIVATE_REAL_NAME', 'api_key': 'SECRET_SENTINEL'}, {'ts': self.ts, 'wake': True, 'wake_index': 1, 'symbol': 'ETH-USDT-SWAP', 'type': 'volume'}, {'ts': self.ts, 'wake': False, 'wake_index': 9, 'symbol': self.symbol}]
        self.save()

    def save(self, trades=None):
        (self.main / 'state.json').write_text(json.dumps(self.state))
        (self.root / 'decisions.json').write_text(json.dumps(self.decision))
        (self.root / 'alerts.jsonl').write_text('\n'.join(json.dumps(a) for a in self.alerts) + '\n{partial')
        rows = trades if trades is not None else [self.trade]
        keys = list(dict.fromkeys(k for t in rows for k in t)) if rows else list(self.trade)
        with (self.main / 'trades.csv').open('w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(rows)
        (self.main / 'equity.csv').write_text('timestamp,equity,api_key\n2026-11-01T00:00:00Z,100,SECRET_SENTINEL\n2026-11-01T01:00:00Z,120,SECRET_SENTINEL\n')

    def build(self):
        return build_history(self.root, datetime(2026, 11, 2, tzinfo=timezone.utc))

    def test_group_association_status_final_pnl_and_unadopted_coin(self):
        result = self.build()
        self.assertEqual(len(result['alert_groups']), 1)
        g = result['alert_groups'][0]
        self.assertTrue(g['adopted']); self.assertEqual(len(g['alerts']), 2)
        self.assertEqual([a['adopted'] for a in g['alerts']], [True, False])
        self.assertEqual(g['orders'][0]['status'], 'filled'); self.assertEqual(g['orders'][0]['pnl'], 19)
        self.assertEqual(g['orders'][0]['match'], 'time')
        self.assertEqual(result['trades'][0]['notional'], 200)
        self.assertEqual(result['trades'][0]['pnl_percent'], 47.5)
        self.assertEqual(result['trades'][0]['gross_pnl'], 20)

    def test_unadopted_without_decision_and_pending_without_fake_pnl(self):
        self.decision['manual_orders'] = []; self.state['manual_status'] = {}; self.save()
        self.assertFalse(self.build()['alert_groups'][0]['adopted'])
        self.decision['manual_orders'] = [{'symbol': self.symbol, 'side': 'long'}]; self.save(trades=[])
        order = self.build()['alert_groups'][0]['orders'][0]
        self.assertIsNone(order['pnl']); self.assertIsNone(order['closed_time'])

    def test_exact_index_or_timestamp_wins_over_later_time_candidate(self):
        self.alerts.append(dict(self.alerts[0], ts='2026-11-01T00:30:00Z', wake_index=2))
        for field, ref in [('alert_ref', 1), ('source_alert', self.ts), ('alert_ref', '1')]:
            self.decision['manual_orders'][0] = dict(self.decision['manual_orders'][0], **{field: ref})
            self.save(); groups = {g['wake_index']: g for g in self.build()['alert_groups']}
            self.assertTrue(groups[1]['adopted']); self.assertFalse(groups[2]['adopted'])
            self.assertEqual(groups[1]['orders'][0]['match'], 'exact')
            self.decision['manual_orders'][0].pop(field)
        self.save(); groups = {g['wake_index']: g for g in self.build()['alert_groups']}
        self.assertTrue(groups[2]['adopted']); self.assertFalse(groups[1]['adopted'])
        self.decision['manual_orders'][0]['alert_ref'] = 99; self.save()
        self.assertFalse(any(g['adopted'] for g in self.build()['alert_groups']))

    def test_24h_inclusive_boundary_and_before_or_after_not_associated(self):
        self.state['manual_status'] = {}
        for ts, adopted in [('2026-11-02T00:00:00Z', True), ('2026-11-02T00:00:01Z', False), ('2026-10-31T23:59:59Z', False)]:
            self.decision['updated_at'] = ts; self.save()
            self.assertEqual(self.build()['alert_groups'][0]['adopted'], adopted)
        self.decision['manual_orders'][0]['created_at'] = '2026-11-01T00:01:00Z'; self.save()
        self.assertTrue(self.build()['alert_groups'][0]['adopted'])

    def test_historical_manual_status_order_survives_new_decisions(self):
        self.decision = {'manual_orders': [], 'updated_at': '2026-11-05T00:00:00Z'}; self.save()
        self.assertEqual(self.build()['alert_groups'][0]['orders'][0]['pnl'], 19)

    def test_private_trade_join_uses_symbol_and_actual_entry_time_if_no_trade_id(self):
        self.trade.pop('order_id'); self.save()
        self.assertEqual(self.build()['alert_groups'][0]['orders'][0]['pnl'], 19)
        self.trade['entry_time'] = '2026-11-01T02:00:00Z'; self.save()
        self.assertIsNone(self.build()['alert_groups'][0]['orders'][0]['pnl'])

    def test_whitelist_no_unknown_fields_or_messages_and_source_read_only(self):
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = self.build(); text = json.dumps(result)
        for value in ['SECRET_SENTINEL', 'GROUP_CHAT_ORIGINAL', 'PRIVATE_REAL_NAME', 'private-order-id', 'api_key', 'note', 'detail']:
            self.assertNotIn(value, text)
        self.assertEqual(set(result['equity'][0]), {'timestamp', 'equity'})
        self.assertEqual(set(result['alert_groups'][0]['orders'][0]), {'symbol','side','status','time','closed_time','pnl','match'})
        self.assertFalse(sensitive(result))
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        write_snapshot(result, self.root / 'public/history.json')
        self.assertEqual(json.loads((self.root/'public/history.json').read_text()), result)

    def test_unknown_reason_retained_but_sensitive_reason_suppressed(self):
        self.trade['reason'] = 'new_exit_reason'; self.save(); self.assertEqual(self.build()['trades'][0]['reason'], 'new_exit_reason')
        self.trade['reason'] = 'secret_credentials'; self.save(); self.assertIsNone(self.build()['trades'][0]['reason'])
        self.trade['reason'] = '原始群聊\n消息'; self.save(); self.assertIsNone(self.build()['trades'][0]['reason'])

    def test_decision_blackout_exact_field_allowlist(self):
        self.decision['blackout_windows'] = [{'start': self.ts, 'end': '2026-11-01T01:00:00Z', 'symbols': [self.symbol], 'reason': '事件窗口', 'api_key': 'SECRET_SENTINEL', 'chat': 'GROUP_CHAT_ORIGINAL'}]
        self.save(); row = build_decisions(self.root)['blackout_windows'][0]
        self.assertEqual(set(row), {'start','end','symbols','reason'})
        self.assertNotIn('SECRET_SENTINEL', json.dumps(row))
        self.decision['blackout_windows'][0]['reason'] = 'secret_' + 'x'*300; self.save()
        self.assertIsNone(build_decisions(self.root)['blackout_windows'][0]['reason'])

    def test_full_equity_points_not_sampled_and_duplicates_deduped(self):
        rows = [f'2026-11-01T{i//60:02}:{i%60:02}:00Z,{100 if i!=333 else 40}' for i in range(600)]
        (self.main / 'equity.csv').write_text('timestamp,equity\n'+'\n'.join(rows+rows[:1]))
        result = self.build(); self.assertEqual(len(result['equity']),600)
        self.assertEqual(min(p['equity'] for p in result['equity']),40)

if __name__ == '__main__':
    unittest.main()
