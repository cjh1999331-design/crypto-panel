import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('snapshot', Path(__file__).resolve().parents[1] / 'tools/make_snapshot.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class EventsTests(unittest.TestCase):
    def test_whitelist_and_redaction(self):
        row=dict(timestamp='2026-11-02T12:00:00Z',event='trade_opened',symbol='BTC-USDT-SWAP',strategy='breakout',side=-1,entry=100,
                 id='internal-order',path='/workspace/private',api_key='secret-material',reason='token=secret /private someone@example.com')
        public=m.clean_event(row)
        self.assertEqual(set(public), {'ts','type','coin','strategy','direction','price','reason'})
        self.assertEqual(public['direction'],'空')
        self.assertEqual(public['price'],100)
        self.assertEqual(public['reason'],'原因未公开')
        encoded=json.dumps(public)
        for private in ['internal-order','/workspace','secret-material','someone@example.com','api_key']:
            self.assertNotIn(private,encoded)
        self.assertEqual(m.clean_event(dict(row,event='config_changed',old={'token':'secret'},new={'path':'/private'}))['reason'],'策略配置已更新')

    def test_types_reasons_counts_and_malformed_fields(self):
        base=dict(timestamp='2026-11-02T12:00:00Z',event='trade_closed',reason='stop')
        self.assertEqual(m.clean_event(base)['reason'],'止损')
        self.assertEqual(m.clean_event(dict(base,event='risk_skip',reason='daily_halted'))['type'],'daily_halt')
        self.assertEqual(m.clean_event(dict(base,event='universe_refreshed',count=104))['reason'],'104 个币')
        self.assertEqual(m.clean_event(dict(base,event='network_error',error='api_key=secret'))['reason'],'公共数据暂不可用')
        for raw in [None,[],{},dict(base,event='unsupported'),dict(base,timestamp='bad'),dict(base,timestamp='2026-11-02T12:00:00')]:
            self.assertIsNone(m.clean_event(raw))
        row=m.clean_event(dict(base,strategy=[],symbol='/private',price='NaN',reason={'secret':'x'}))
        self.assertIsNone(row['coin']);self.assertIsNone(row['strategy']);self.assertIsNone(row['price'])
        self.assertEqual(row['reason'],'原因未公开')

    def test_main_only_recent_lines_without_writing_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            self.assertEqual(m.build_events(root)['source_status'],'missing')
            before={}
            for directory in ('paper_main','paper_meeting'):
                d=root/directory;d.mkdir();p=d/'events.jsonl'
                rows=[dict(timestamp=f'2026-11-02T12:{i//60:02d}:{i%60:02d}Z',event='signal',symbol='BTC-USDT-SWAP',strategy='breakout',side=1) for i in range(350)]
                if directory == 'paper_meeting':
                    rows = [dict(r, symbol='ETH-USDT-SWAP') for r in rows]
                p.write_text('\n'.join(json.dumps(r) for r in rows)+'\nmalformed\n');before[p]=p.read_bytes()
            result=m.build_events(root)
            self.assertEqual(result['source_status'],'ok');self.assertEqual(len(result['events']),299)
            self.assertTrue(all(r['coin']=='BTC-USDT-SWAP' for r in result['events']))
            self.assertEqual(result['events'][-1]['ts'],'2026-11-02T12:05:49.000000Z')
            for path,content in before.items():self.assertEqual(path.read_bytes(),content)
            m.write_snapshot(result,root/'public/events.json')
            self.assertFalse((root/'public/events.tmp').exists())

    def test_alert_whitelist_short_text_and_public_https_only(self):
        raw=dict(ts='2026-11-02T12:00:00Z',symbol='BTC',type='放量',value=2.5,detail='成交额上升',
                 source_url='https://www.okx.com/markets',id='PRIVATE_SENTINEL',api_key='PRIVATE_SENTINEL')
        row=m.clean_alert(raw)
        self.assertEqual(row['type'],'异动');self.assertEqual(row['coin'],'BTC-USDT-SWAP')
        self.assertEqual(row['reason'],'放量 · 2.5 · 成交额上升')
        self.assertEqual(row['source_url'],raw['source_url'])
        self.assertNotIn('PRIVATE_SENTINEL',json.dumps(row))
        for url in ['http://www.okx.com/a','file:///private','javascript:alert(1)','https://localhost/a',
                    'https://127.0.0.1/a','https://10.1.2.3/a','https://[::1]/a','https://foo.internal/a',
                    'https://user:password@www.okx.com/a','https://www.okx.com:8000/a','https://www.okx.com/?api_key=secret']:
            self.assertNotIn('source_url',m.clean_alert(dict(raw,source_url=url)),url)
        for value in ['api_key=PRIVATE_SENTINEL','x'*100+' secret=PRIVATE_SENTINEL','/workspace/private','someone@example.com']:
            self.assertNotIn('PRIVATE_SENTINEL',m.clean_alert(dict(raw,detail=value))['reason'])
        self.assertLessEqual(len(m.clean_alert(dict(raw,detail='价格变化'*100))['reason']),80)
        for bad in [None,[],{},dict(raw,ts='invalid')]:self.assertIsNone(m.clean_alert(bad))
        self.assertEqual(m.clean_alert(dict(raw,value={},detail=[],symbol='/private'))['reason'],'放量')

    def test_recent_100_alerts_merged_sorted_and_missing_optional(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'paper_main').mkdir();p=root/'paper_main/events.jsonl'
            p.write_text(json.dumps(dict(timestamp='2026-11-02T12:02:00Z',event='started'))+'\n')
            self.assertEqual(len(m.build_events(root)['events']),1)
            alert=root/'alerts.jsonl'
            rows=[dict(ts=f'2026-11-02T12:{i//60:02d}:{i%60:02d}Z',symbol='ETH-USDT-SWAP',type='价格',value=i) for i in range(120)]
            alert.write_text('\n'.join(json.dumps(r) for r in rows)+'\n')
            before={f:f.read_bytes() for f in (p,alert)}
            events=m.build_events(root)['events']
            self.assertEqual(len(events),101);self.assertEqual(events[0]['ts'],'2026-11-02T12:00:20.000000Z')
            self.assertEqual(events[-1]['type'],'started');self.assertEqual(sum(r['type']=='异动' for r in events),100)
            self.assertEqual(before,{f:f.read_bytes() for f in before})
            p.unlink();self.assertEqual(m.build_events(root)['source_status'],'ok')

if __name__=='__main__':unittest.main()
