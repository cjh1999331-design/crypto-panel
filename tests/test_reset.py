import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from make_snapshot import (build_snapshot, build_account, build_public_accounts, build_events,
                           build_scan, build_team, filter_team_reset, pause_metadata)
from history_snapshot import build_history
from validate_account import validate_account

ROOT = Path(__file__).resolve().parents[1]
RESET = '2026-11-02T18:25:00.000000Z'
OLD = '2026-11-02T18:24:59Z'
NEW = '2026-11-02T18:25:01Z'


class ResetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'paper_main').mkdir()
        self.save('paper_main/PAUSED.json', dict(paused=True, reset=True, reset_at='2026-11-03T01:25+07:00', since=OLD,
                  message='模拟盘已暂停，等待重新开始', next_initial_equity=100, archive='/private/archive/SECRET'))

    def save(self, name, data):
        (self.root/name).write_text(json.dumps(data, ensure_ascii=False))

    def assert_clean(self, value):
        for ts in re.findall(r'\d{4}-\d{2}-\d{2}T[^"\s]+', json.dumps(value)):
            self.assertGreaterEqual(datetime.fromisoformat(ts.replace('Z','+00:00')), datetime.fromisoformat(RESET.replace('Z','+00:00')))
        self.assertNotIn('archive', json.dumps(value))
        self.assertNotIn('SECRET', json.dumps(value))

    def test_paused_only_empty_account_and_cli_all_public_outputs(self):
        out=self.root/'out'
        result=subprocess.run([sys.executable, str(ROOT/'tools/make_snapshot.py'), '--source-root', str(self.root), '--output', str(out/'snapshot.json')],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        snapshot=json.loads((out/'snapshot.json').read_text())
        a=snapshot['accounts'][0]
        self.assertEqual((a['balance'],a['marked_equity'],a['status']),(100,100,'暂停'))
        for key in ('positions','trades','equity'): self.assertEqual(a[key],[])
        account=validate_account(json.loads((out/'account.json').read_text()))
        self.assertEqual(account['accounts'][0]['equity_curve'],[])
        self.assertEqual(account['accounts'][0]['fills'],[])
        for path in out.glob('*.json'): self.assert_clean(json.loads(path.read_text()))
        self.assertEqual(build_snapshot(self.root)['accounts'][0]['status'],'暂停')
        result=subprocess.run([sys.executable,str(ROOT/'tools/make_snapshot.py'),'--source-root',str(self.root),'--output',str(out/'snapshot.json'),'--historical','--account-source-root',str(self.root/'archive')],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads((out/'snapshot.json').read_text())['accounts'][0]['status'],'暂停')

    def test_logs_reports_alerts_and_decisions_strict_reset_boundary(self):
        (self.root/'team').mkdir()
        report=lambda ts:dict(ts=ts,role='tech',status='已完成',phase='P1',meeting='测试',title='测试报告',summary='公开摘要',grade='A')
        (self.root/'team/team_log.jsonl').write_text('\n'.join(json.dumps(report(ts)) for ts in (OLD,RESET,NEW)))
        self.save('team/team_status.json', dict(updated_at=OLD,meeting='旧会议',phase='P1',roles={'tech':dict(status='已完成',task='旧任务',last_report=report(OLD))}))
        team=filter_team_reset(build_team(self.root/'team'),RESET)
        self.assertEqual(len(team['log']),2);self.assertEqual(team['status']['roles'],{})
        alerts=[dict(ts=ts,wake=True,symbol='BTC',type='volume') for ts in (OLD,RESET,NEW)]
        (self.root/'alerts.jsonl').write_text('\n'.join(json.dumps(r) for r in alerts))
        (self.root/'paper_main/events.jsonl').write_text('\n'.join(json.dumps(dict(timestamp=ts,event='trade_opened')) for ts in (OLD,RESET,NEW)))
        self.save('decisions.json',dict(updated_at=OLD,symbols={'BTC-USDT-SWAP':dict(bias='long')}))
        self.save('paper_main/scan.json',dict(generated_at=OLD,schema_version=1))
        self.assertEqual(build_scan(self.root)['recent_signals'],[])
        events=build_events(self.root)
        self.assertEqual(len(events['events']),4)
        self.assertTrue(all(e['wake'] for e in events['events'] if e['type']=='异动'))
        history=build_history(self.root)
        self.assertEqual(len(history['alert_groups']),2)
        for value in (team,events,history,build_public_accounts(self.root)): self.assert_clean(value)

    def test_pause_without_reset_preserves_final_equity(self):
        self.save('paper_main/PAUSED.json',dict(paused=True,since=NEW))
        self.save('paper_main/state.json',dict(balance=105,engines={},risk_per_trade=.03,daily_loss_limit=.08,max_positions=3,leverage=5,initial=100))
        a=build_account(self.root,'paper_main','主力盘')
        self.assertEqual(a['status'],'暂停');self.assertEqual(a['pause']['final_equity'],105)
        self.assertEqual(build_public_accounts(self.root)['accounts'][0]['equity'],105)

    def test_current_public_files_contain_no_pre_reset_timestamp(self):
        for path in (ROOT/'paper').glob('*.json'): self.assert_clean(json.loads(path.read_text()))


if __name__=='__main__': unittest.main()
