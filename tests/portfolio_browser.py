"""Multi-instrument/amount contracts. Fixtures are confined to this browser context."""
import copy
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
BASE=os.environ.get('PANEL_URL','http://127.0.0.1:8008/')

def contracts(browser):
    now=datetime.now(timezone.utc)
    ts=lambda n=0:(now+timedelta(seconds=n)).isoformat().replace('+00:00','Z')
    data=json.loads((ROOT/'paper/account.json').read_text())
    data['updated_at']=ts()
    data.pop('pause',None)
    position=lambda symbol,side,entry,stamp:dict(symbol=symbol,side=side,qty=2,entry=entry,
        stop=entry-5*side,take_profit=entry+10*side,margin=40,leverage=5,
        mark_price=entry+1,unrealized_pnl=side*2,entry_time=stamp,liquidation_price=entry-20*side)
    a=data['accounts'][0]
    a.update(status='运行中',daily_loss_limit=.08,positions=[position('SPCX-USDT-SWAP',1,100,ts(-200)),
        position('INTC-USDT-SWAP',-1,60,ts(-100))],fills=[
        dict(symbol='INTC-USDT-SWAP',side=-1,qty=2,kind='close',price=61,notional=122,pnl=-2,timestamp=ts(-300))],
        manual_status=[dict(symbol='ZEC-USDT-SWAP',side=1,status='pending',limit=1200,
            stop=1150,take_profit=1300,qty=1,planned_risk=52,valid_until=ts(3600))],
        pending_orders=[dict(symbol='ETH-USDT-SWAP',side=-1,status='pending',limit=3000,
            stop=3100,take_profit=2800,qty=.5,valid_until=ts(3600))])
    data['accounts']=[a]
    scan=dict(schema_version=1,generated_at=ts(),source_status='ok',instruments=[],positions=[],recent_signals=[])
    market=json.loads((ROOT/'tests/fixtures/market.json').read_text())
    requests=[];messages=[];sockets=[];rest_failed=False
    context=browser.new_context(viewport={'width':390,'height':844})
    def socket(ws):
        sockets.append(ws)
        def message(raw):
            if raw=='ping':ws.send('pong')
            else:messages.append(json.loads(raw))
        ws.on_message(message)
    context.route_web_socket('**/ws/v5/**',socket)
    page=context.new_page();errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('console',lambda m:errors.append(m.text) if m.type=='error' else None)
    page.route('**/paper/account.json?*',lambda r:r.fulfill(json=data))
    page.route('**/paper/scan.json?*',lambda r:r.fulfill(json=scan))
    def api(route):
        path=urlparse(route.request.url)
        if path.path.endswith('/tickers'):
            result=dict(code='1',data=[]) if rest_failed else dict(code='0',data=[dict(instId=p['symbol'],last=str(p['entry']+1),open24h=str(p['entry']),volCcy24h='100000',ts=str(int(datetime.now(timezone.utc).timestamp()*1000))) for p in a['positions']])
        elif path.path.endswith('/candles'):
            symbol=parse_qs(path.query)['instId'][0];requests.append(symbol)
            result=copy.deepcopy(market['candles'])
            # Chart bars follow current time; every symbol has visibly distinct price history.
            anchor={'SPCX':100,'INTC':60,'ZEC':1200,'ETH':3000}.get(symbol.split('-')[0],100)
            for i,row in enumerate(result['data']):
                row[0]=str(int(now.timestamp()//3600*3600*1000)-i*3600000)
                for j,offset in ((1,0),(2,2),(3,-2),(4,1)):row[j]=str(anchor+offset+(i%5)*.2)
        else:result=market['funding'] if path.path.endswith('/funding-rate') else market['interest']
        route.fulfill(json=result)
    page.route('https://www.okx.com/api/v5/**',api)
    page.goto(BASE,wait_until='networkidle')
    page.wait_for_selector('.position-row')
    assert page.locator('.position-row').count()==2
    for symbol in ('SPCX-USDT-SWAP','INTC-USDT-SWAP'):
        page.locator(f'[data-position^="{symbol}:"]').click()
        page.wait_for_function("() => document.querySelectorAll('#chart-levels span').length===3 && !document.querySelector('#candle-updated').textContent.includes('加载中')")
        assert symbol in requests
        assert page.locator('.position-detail:visible').count()==1
        assert '挂单限价' not in page.locator('#chart-levels').inner_text()
        assert not page.locator('#chart-error').is_visible()
    assert all(p in page.locator('#chart-levels').inner_text() for p in ['60.0000','65.0000','50.0000'])
    # Pending orders remain available on the existing single-coin research route.
    for symbol in ('ZEC-USDT-SWAP','ETH-USDT-SWAP'):
        page.goto(BASE+'#/coin/'+symbol,wait_until='networkidle')
        page.wait_for_function("() => document.querySelector('#chart-levels').textContent.includes('挂单限价') && !document.querySelector('#candle-updated').textContent.includes('加载中')")
        assert symbol in requests
    page.wait_for_timeout(100)
    subscriptions=[m for m in messages if m.get('op')=='subscribe' and m['args'][0]['channel'].startswith('candle')]
    unsubscriptions=[m for m in messages if m.get('op')=='unsubscribe' and m['args'][0]['channel'].startswith('candle')]
    assert subscriptions[-1]['args']==[dict(channel='candle1H',instId='ETH-USDT-SWAP')]
    assert any(m['args']==[dict(channel='candle1H',instId='ZEC-USDT-SWAP')] for m in unsubscriptions)
    page.goto(BASE,wait_until='networkidle')
    # Both maker and meeting orders carry monetary amounts, with planned risk taking precedence.
    zec=page.locator('[data-order="ZEC-USDT-SWAP"]')
    assert zec.locator('[data-label="名义价值 (USDT)"]').inner_text()=='1,200.00'
    assert zec.locator('[data-label="计划风险 (USDT)"]').inner_text()=='52.00'
    eth=page.locator('[data-order="ETH-USDT-SWAP"]')
    assert eth.locator('[data-label="名义价值 (USDT)"]').inner_text()=='1,500.00'
    assert eth.locator('[data-label="计划风险 (USDT)"]').inner_text()=='50.00'
    # Every accepted WebSocket price immediately updates both long and short cards.
    public=[s for s in sockets if s.url.endswith('/public')][-1]
    for symbol,value in [('SPCX-USDT-SWAP',110),('INTC-USDT-SWAP',55)]:
        public.send(json.dumps(dict(arg=dict(channel='mark-price',instId=symbol),data=[dict(markPx=str(value),ts=str(int(datetime.now(timezone.utc).timestamp()*1000)))])))
    spcx=page.locator('[data-position^="SPCX-USDT-SWAP:"]')
    page.wait_for_function("() => document.querySelector('[data-position^=\"SPCX-USDT-SWAP:\"] [data-label=\"名义价值 (USDT)\"]').textContent.startsWith('220.00')")
    assert spcx.locator('[data-label="浮盈亏 (USDT)"]').inner_text()=='+20.00'
    assert spcx.locator('[data-label="浮盈率 / 保证金"]').inner_text()=='+50.00%'
    assert 'WebSocket 实时价' in spcx.locator('..').locator('.position-meta').text_content()
    intc=page.locator('[data-position^="INTC-USDT-SWAP:"]')
    assert intc.locator('[data-label="浮盈亏 (USDT)"]').inner_text()=='+10.00'
    assert intc.locator('[data-label="浮盈率 / 保证金"]').inner_text()=='+25.00%'
    for width in (390,360):
        page.set_viewport_size({'width':width,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        for cell in page.locator('#live-positions td,#manual-orders td').all():
            rect=cell.bounding_box()
            assert cell.is_visible() and rect['x']>=0 and rect['x']+rect['width']<=width,rect
    # Losing quotes and failing REST must visibly return to the snapshot mark.
    rest_failed=True
    public.close()
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    page.wait_for_function("() => document.querySelector('[data-position^=\"SPCX-USDT-SWAP:\"]').parentElement.textContent.includes('快照标记价')")
    assert spcx.locator('[data-label="名义价值 (USDT)"]').inner_text().split()[0]=='202.00'
    assert spcx.locator('[data-label="浮盈亏 (USDT)"]').inner_text()=='+2.00'
    rest_failed=False
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    page.wait_for_function("() => document.querySelector('[data-position^=\"SPCX-USDT-SWAP:\"]').parentElement.textContent.includes('轮询实时价')")
    # A closed selected symbol must collapse even when it remains in scanner signals.
    page.locator('[data-position^="INTC-USDT-SWAP:"]').click()
    a['positions']=[a['positions'][0]]
    scan['instruments']=[dict(instId='INTC-USDT-SWAP',quote_24h=1e8,spread=.001,leverage_cap=5,held=False,signals={'mean_reversion':-1})]
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    page.wait_for_function("() => document.querySelectorAll('.position-row').length===1 && document.querySelectorAll('.position-detail:not([hidden])').length===0")
    a['positions'].append(position('BTC-USDT-SWAP',1,100,ts(-10)))
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    page.wait_for_function("() => document.querySelectorAll('.position-row').length===2")
    a['positions']=[];a['manual_status'][0]['status']='filled';a['pending_orders']=[]
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    page.wait_for_function("() => document.querySelector('#live-positions').textContent==='暂无持仓'")
    for width in (390,360):
        page.set_viewport_size({'width':width,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    assert not errors,errors
    context.close()
    print('多币 K 线：持仓/会议 pending/maker、逐币水平线、切换退订订阅、动态增删/平仓/会议回退、WS与轮询金额/保证金浮盈率/回退来源、390/360 无溢出、控制台=0：通过。')

if __name__=='__main__':
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        try:contracts(browser)
        finally:browser.close()
