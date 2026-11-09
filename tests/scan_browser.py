"""Scan/selection browser contracts; intercepted fixtures never enter screenshots."""
import copy
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
BASE=os.environ.get('PANEL_URL','http://127.0.0.1:8029/')

def main():
    source=json.loads((ROOT/'paper/account.json').read_text())
    source=copy.deepcopy(source)
    position=lambda symbol,stamp: dict(symbol=symbol,side=1,qty=1,entry=100,stop=98,margin=20,
        liquidation_price=81,leverage=5,take_profit=104,mark_price=101,unrealized_pnl=1,entry_time=stamp)
    main_account=source['accounts'][0]
    main_account.update(status='运行中',positions=[position('BTC-USDT-SWAP','2026-11-02T00:00:00Z'),
        position('SOL-USDT-SWAP','2026-11-02T01:00:00Z')],enabled_strategies=['mean_reversion'],
        strategies={'mean_reversion':{'rsi':25,'trend':.02}},entry_mode_by_strategy={'mean_reversion':'maker'})
    source['accounts']=[main_account]
    row=lambda symbol,quote,side,held:dict(instId=symbol,quote_24h=quote,spread=.0002,leverage_cap=10,
        signals={'mean_reversion':side,'breakout':None},signal_status='ok',held=held,bar_ts=1)
    scan=dict(schema_version=1,generated_at=source['updated_at'],source_status='ok',instruments=[
        row('BTC-USDT-SWAP',1e8,None,True),row('ETH-USDT-SWAP',5e7,1,False),row('SOL-USDT-SWAP',1e7,-1,True)],
        recent_signals=[dict(timestamp='2026-11-02T02:00:00Z',instId='ETH-USDT-SWAP',strategy='mean_reversion',side=1,
                             opened=False,reason='maker_pending')],positions=[])
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        try:
            page=browser.new_page(viewport={'width':390,'height':844})
            page.route_web_socket('**/ws/v5/**',lambda ws:ws.on_message(lambda msg:ws.send('pong') if msg=='ping' else None))
            errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('console',lambda m:errors.append(m.text) if m.type=='error' else None)
            page.route('**/paper/account.json?*',lambda route:route.fulfill(json=source))
            page.route('**/paper/scan.json?*',lambda route:route.fulfill(json=scan))
            page.goto(BASE,wait_until='networkidle',timeout=60000)
            page.wait_for_function("() => document.querySelector('#chart-symbol').value==='SOL-USDT-SWAP' && document.querySelector('#scan-count').textContent==='3 币'")
            assert page.locator('#scan-body tr').count()==3
            assert '今日会议标的 ZEC' in page.locator('#meeting-target').inner_text()
            assert '会议标的' in page.locator('[data-role="gork"] .team-metric').inner_text()
            assert ''.join(page.locator('#enabled-strategies').inner_text().split())=='均值回归maker'
            assert page.locator('#scan-held button').count()==2
            assert 'maker 待成交' in page.locator('#scan-recent').inner_text()
            for selector,expected in [('signal',2),('held',2),('all',3)]:
                page.select_option('#scan-filter',selector)
                assert page.locator('#scan-body tr').count()==expected
            page.locator('[data-scan-sort="quote_24h"]').click()
            assert page.locator('#scan-body tr').first.locator('td').first.inner_text()=='SOL'
            page.select_option('#chart-symbol','ETH-USDT-SWAP')
            page.wait_for_function("() => document.querySelector('#room-symbol').textContent==='ETH-USDT-SWAP'")
            page.locator('#home-page [data-timeframe="4H"]').click()
            assert page.locator('#chart-symbol').input_value()=='ETH-USDT-SWAP'
            page.locator('#scan-held [data-chart-coin="BTC-USDT-SWAP"]').click()
            assert page.locator('#chart-symbol').input_value()=='BTC-USDT-SWAP'
            for width in (390,360,320):
                page.set_viewport_size({'width':width,'height':844})
                page.wait_for_function('() => document.documentElement.scrollWidth <= innerWidth')
                assert page.locator('#scan-table').evaluate('e=>e.scrollWidth>e.parentElement.clientWidth')
            # Fresh page with no holdings uses today's meeting symbol, even with signals.
            main_account['positions']=[]
            for row in scan['instruments']:row['held']=False
            page.reload(wait_until='networkidle')
            page.wait_for_function("() => document.querySelector('#chart-symbol').value==='ZEC-USDT-SWAP'")
            assert 'ETH' in page.locator('#chart-symbol').inner_text()
            assert not errors,errors
            print('扫描排序/筛选、最近信号、持仓、默认最新开仓、任意持仓/信号币、空仓会议回退、动态 maker、320/360/390 横向滚动：通过；console.error / pageerror：0。')
        finally:browser.close()

if __name__=='__main__':main()
