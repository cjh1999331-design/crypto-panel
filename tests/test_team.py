import copy
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest

spec = importlib.util.spec_from_file_location('snapshot', Path(__file__).resolve().parents[1] / 'tools/make_snapshot.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
FIXTURES = Path(__file__).parent / 'fixtures'


class TeamTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.row = dict(ts='2026-11-02T20:35:00+07:00', role='risk', phase='P1',
                        meeting='示例会议', title='示例报告', summary='等待风险条件满足。',
                        grade='A', status='已完成', id='risk-1')
        self.status = dict(updated_at=self.row['ts'], meeting='示例会议', phase='P1', roles={
            'risk': dict(name='风控', status='工作中', task='检查风险', last_report={k:self.row[k] for k in ('ts','title','summary','grade')})})

    def build(self, rows=None, status=None):
        (self.root / 'team_log.jsonl').write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in (rows or []))+'\n')
        (self.root / 'team_status.json').write_text(json.dumps(self.status if status is None else status, ensure_ascii=False))
        return m.build_team(self.root)

    def test_whitelist_truncation_and_latest_id_by_instant(self):
        old = dict(self.row, ts='2026-11-02T19:35:00+07:00', title='旧报告')
        new = dict(self.row, ts='2026-11-02T13:36:00Z', title='新'*45, summary='摘'*220, extra='内部备注')
        result = self.build([new, old])
        self.assertEqual(len(result['log']), 1)
        self.assertEqual(result['log'][0]['title'], '新'*40)
        self.assertEqual(result['log'][0]['summary'], '摘'*200)
        self.assertEqual(result['warnings']['duplicate_log'], 1)
        self.assertNotIn('内部备注', json.dumps(result, ensure_ascii=False))
        self.assertEqual(result['status']['roles']['risk']['name'], '风控')

    def test_invalid_fields_skip_and_optional_fields(self):
        invalid = [dict(self.row, **{k:v}) for k,v in [
            ('role','other'),('phase','P8'),('grade','G'),('status','运行中'),
            ('ts','2026-11-02T20:35:00'),('ts','bad'),('ts','9999-12-31T23:59:59-23:59'),
            ('title',3),('summary',None),('meeting',''),('id',[]),('role',[])]]
        valid = dict(self.row)
        del valid['id'], valid['grade']
        result = self.build([*invalid, [], None, valid, valid])
        self.assertEqual(result['warnings']['invalid_log'], len(invalid)+2)
        self.assertEqual(len(result['log']), 2)
        self.assertIsNone(result['log'][0]['grade'])
        self.assertNotIn('id', result['log'][0])

    def test_all_roles_phases_grades_and_statuses(self):
        rows = [dict(self.row, id=f'row-{i}', role=list(m.TEAM_ROLES)[i%6], phase=f'P{i%8}',
                     grade=[None,*'ABCDEF'][i%7], status=['工作中','已完成','待命'][i%3]) for i in range(168)]
        result = self.build(rows)
        self.assertEqual(len(result['log']), 168)
        self.assertEqual(result['warnings']['invalid_log'], 0)

    def test_redaction_scans_complete_records_before_truncation(self):
        private_name = '\u9648\u5bb6\u8c6a'
        bad = [private_name, 'A'*24, 'aB12+/'*4, 'APIkey', 'sEcReT', 'Passphrase', '账号：123', 'test@example.org']
        rows = [dict(self.row, id=f'bad-{i}', summary='摘'*201 + value) for i,value in enumerate(bad)]
        rows.append(dict(self.row, extra={'note':private_name}))
        rows.append(dict(self.row, apiKey='short'))
        result = self.build(rows + [dict(self.row, id='valid', summary='B'*23)])
        self.assertEqual(result['warnings']['redacted_log'], len(rows))
        self.assertEqual(len(result['log']), 1)
        encoded = json.dumps(result, ensure_ascii=False)
        for value in bad:
            self.assertNotIn(value, encoded)
        self.assertNotIn('apiKey', encoded)

    def test_status_redaction_discards_whole_role_and_counts(self):
        state = copy.deepcopy(self.status)
        state['roles']['risk']['last_report']['summary'] = '摘'*201 + 'x'*24
        state['roles']['trader'] = dict(name='操盘', status='待命', task='', last_report=None, secret='a')
        state['roles']['tech'] = dict(name='不公开名称', status='待命', task='', last_report=None)
        result = self.build(status=state)
        self.assertEqual(result['warnings']['redacted_status'], 2)
        self.assertEqual(list(result['status']['roles']), ['tech'])
        self.assertEqual(result['status']['roles']['tech']['name'], '技术')
        state['meeting'] = 'x'*24
        result = self.build(status=state)
        self.assertEqual(result['status']['roles'], {})
        self.assertIsNone(result['status']['meeting'])
        self.assertEqual(result['warnings']['redacted_status'], 1)

    def test_status_schema_invalid_role_and_report(self):
        for key,value in [('status','错误'), ('task',1), ('last_report',{'ts':'bad'}), ('last_report',[] )]:
            state = copy.deepcopy(self.status)
            state['roles']['risk'][key] = value
            result = self.build(status=state)
            self.assertEqual(result['status']['roles'], {})
            self.assertEqual(result['warnings']['invalid_status'], 1)
        for key,value in [('updated_at','2026-11-02T13:00:00'), ('phase','P9'),('meeting',None)]:
            result = self.build(status=dict(self.status, **{key:value}))
            self.assertEqual(result['warnings']['invalid_status'], 1)

    def test_empty_missing_and_malformed_sources(self):
        missing = m.build_team(self.root)
        self.assertEqual(missing['warnings']['missing_files'], 2)
        self.assertEqual(missing['log'], [])
        idle = dict(updated_at=None, meeting=None, phase=None, roles={role:dict(name=name,status='待命',task='',last_report=None) for role,name in m.TEAM_ROLES.items()})
        result = self.build(status=idle)
        self.assertTrue(all(v == 0 for v in result['warnings'].values()))
        (self.root / 'team_log.jsonl').write_text('{broken\n42\n')
        (self.root / 'team_status.json').write_text('{broken')
        result = m.build_team(self.root)
        self.assertEqual(result['warnings']['invalid_log'], 2)
        self.assertEqual(result['warnings']['invalid_status'], 1)

    def test_recent_200_sorted_and_fixture(self):
        rows = [dict(self.row, id=f'row-{i}', ts=f'2026-11-02T13:{i//60:02d}:{i%60:02d}Z') for i in range(250)]
        result = self.build(rows[::-1])
        self.assertEqual(len(result['log']), 200)
        self.assertEqual(result['log'][0]['id'], 'row-249')
        self.assertEqual(result['log'][-1]['id'], 'row-50')
        fixture = m.build_team(FIXTURES / 'team')
        self.assertEqual(len(fixture['status']['roles']), 6)
        self.assertEqual(len(fixture['log']), 8)
        self.assertTrue(all(v == 0 for v in fixture['warnings'].values()))

    def test_team_only_cli_atomic_output_without_account_sources(self):
        output = self.root / 'public/snapshot.json'
        command = [sys.executable, str(Path(m.__file__)), '--team-only', '--team-root', str(FIXTURES / 'team'),
                   '--source-root', str(self.root / 'missing'), '--output', str(output)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertFalse(output.exists())
        data = json.loads(output.with_name('team.json').read_text())
        self.assertEqual(len(data['log']), 8)
        self.assertFalse(output.with_name('team.tmp').exists())


class GradeRegressionTests(unittest.TestCase):
    setUp=TeamTests.setUp
    build=TeamTests.build
    def test_signed_grades_preserved_in_status_and_log(self):
        for letter in 'ABCDEF':
            for sign in ('', '+', '-'):
                grade=letter+sign
                state=copy.deepcopy(self.status)
                state['roles']['risk']['last_report']['grade']=grade
                result=self.build([dict(self.row,grade=grade)],state)
                self.assertEqual(result['log'][0]['grade'],grade)
                self.assertEqual(result['status']['roles']['risk']['last_report']['grade'],grade)
                self.assertEqual(result['warnings']['invalid_log'],0)
                self.assertEqual(result['warnings']['invalid_status'],0)

    def test_invalid_reasons_identify_field_and_location_without_source_text(self):
        state=copy.deepcopy(self.status)
        state['roles']['risk']['last_report']['grade']='A++'
        result=self.build([dict(self.row,grade='A++'),dict(self.row,title=123),dict(self.row,role='DO_NOT_PUBLISH')],state)
        details=result['warnings']['details']
        self.assertIn(dict(source='team_log.jsonl',field='grade',reason='expected_A_F_optional_sign',line=1),details)
        self.assertTrue(any(r.get('line')==2 and r['field']=='title' for r in details))
        self.assertTrue(any(r.get('role')=='risk' and r['field']=='grade' for r in details))
        self.assertNotIn('DO_NOT_PUBLISH',json.dumps(result))
        self.assertNotIn('A++',json.dumps(result))

if __name__ == '__main__':
    unittest.main()
