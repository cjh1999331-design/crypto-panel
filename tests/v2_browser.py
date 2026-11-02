"""Real artifacts stay separate from intercepted contract tests; no source writes."""
import copy
import json
import os
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
BASE=os.environ.get('PANEL_URL','http://127.0.0.1:8008/')
CHROME=os.environ.get('CHROME_PATH','/usr/bin/google-chrome')


def no_overflow(page):
    page.wait_for_function('() => document.documentElement.scrollWidth <= innerWidth')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')


def monitor(page):
    app_errors,network_errors=[],[]
    page.on('pageerror',lambda e:app_errors.append(str(e)))
    def console(message):
        if message.type!='error':return
        # Chromium emits network errors independently of application catch handlers.
        # Keep and report them, never count them as a successful WebSocket connection.
        (network_errors if 'WebSocket connection' in message.text or 'Failed to load resource' in message.text else app_errors).append(message.text)
    page.on('console',console)
    return app_errors,network_errors


def video_10s(source,target,start=0):
    subprocess.run(['ffmpeg','-v','error','-y','-ss',str(start),'-i',str(source),'-t','10',
                    '-an','-c:v','libvpx-vp9','-deadline','realtime','-cpu-used','5','-crf','30','-b:v','0',str(target)],check=True)
    length=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(target)]))
    assert 9.95<=length<=10.1,(target,length)


def real_artifacts(browser):
    with tempfile.TemporaryDirectory(prefix='panel-record-') as temp:
        context=browser.new_context(viewport={'width':390,'height':844},device_scale_factor=1,
                                    record_video_dir=temp,record_video_size={'width':390,'height':844})
        page=context.new_page();errors,network=monitor(page)
        page.goto(BASE,wait_until='domcontentloaded',timeout=60000)
        page.wait_for_function("() => document.querySelectorAll('#role-cards .role-card').length===6 && document.querySelectorAll('#strategy-states .strategy-row').length===1")
        page.wait_for_function("() => document.querySelectorAll('#price-chart canvas').length>0 && document.querySelectorAll('#conditions li').length===6",timeout=65000)
        page.wait_for_function("() => document.querySelector('#bt60-results .bt60-group')")
        page.evaluate('document.fonts.ready')
        page.wait_for_timeout(700)
        no_overflow(page)
        assert not page.locator('.state-offline [class*="motion-"]').count()
        assert not page.locator('.workstation, .pixel-robot').count()
        assert page.locator('#events-terminal li').count()>0
        assert '暂无' not in page.locator('#pinned-equity').inner_text()
        assert page.locator('#alerts').inner_text()==''
        page.screenshot(path=str(ROOT/'shot-mobile.png'))
        page.locator('.execution-panel').screenshot(path=str(ROOT/'shot-positions.png'),style='html{scroll-padding-top:0!important}.header{position:static!important}')
        for width in (390,360):
            page.set_viewport_size({'width':width,'height':844});no_overflow(page)
            for cell in page.locator('#live-positions td,#manual-orders td').all():
                assert cell.is_visible()
                rect=cell.bounding_box();assert rect['x']>=0 and rect['x']+rect['width']<=width,rect
        page.set_viewport_size({'width':390,'height':844})
        tabs=page.locator('#coin-tabs button')
        if tabs.count()>1:
            tabs.nth(1).click()
            page.wait_for_function("() => !document.querySelector('#candle-updated').textContent.includes('加载中') && document.querySelectorAll('#chart-levels span').length>0")
            page.mouse.move(0,0)
            page.locator('.room').screenshot(path=str(ROOT/'shot-kline.png'),style='html{scroll-padding-top:0!important}.header{position:static!important}')
        else:raise AssertionError('真实快照少于两个币，无法生成第二币截图')
        page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path=str(ROOT/'shot-mobile-full.png'),full_page=True)
        # Screen capture starts with already loaded real data. Keep ten full seconds.
        start=page.evaluate('performance.now()/1000')
        page.wait_for_timeout(10300)
        source=page.video.path();context.close()
        video_10s(source,ROOT/'rec-mobile.webm',start)
        assert not errors,errors
        print(f'真实首页：截图与 10 秒视频完成；应用控制台/pageerror=0；外部网络错误={len(network)}。')
        if network:print('环境网络限制：'+network[0])

        page=browser.new_page(viewport={'width':1440,'height':1050});errors2,network2=monitor(page)
        page.goto(BASE,wait_until='domcontentloaded');page.wait_for_selector('#price-chart canvas')
        page.wait_for_function("() => document.querySelector('#bt60-results .bt60-group')")
        page.screenshot(path=str(ROOT/'shot-desktop.png'),full_page=True)
        for width in (390,360,320):
            page.set_viewport_size({'width':width,'height':844});no_overflow(page)
            assert page.locator('#role-cards').evaluate("e=>getComputedStyle(e).gridTemplateColumns.split(' ').length")==2
            for name in ('timeline','bt60','market','history'):
                page.locator(f'#{name}-fold > summary').click();no_overflow(page)
            page.evaluate('window.scrollTo(0,document.body.scrollHeight)')
            rect=page.locator('.pinned-balance').bounding_box();assert 0<=rect['y'] and rect['y']+rect['height']<=160,rect
            assert page.locator('#history-summary article').count()==4
            for name in ('timeline','bt60','market','history'):page.locator(f'#{name}-fold > summary').click()
        page.locator('#home-page [data-timeframe="4H"]').click()
        page.wait_for_function("() => document.querySelector('#analysis-period').textContent.includes('4 小时')")
        page.locator('[data-nav="market"]').click();page.locator('#search').fill('ZEC')
        page.wait_for_function("() => document.querySelector('#market-body').textContent.includes('ZEC')")
        page.locator('[data-nav="paper"]').click();page.wait_for_selector('#account-tabs button')
        assert page.locator('#paper-cards .stat').count()>=4
        no_overflow(page);assert not errors2,errors2;page.close()
        print('真实桌面/390/360/320、全部折叠区、固定右上角余额、1H/4H、市场/历史路由：通过。')

        context=browser.new_context(viewport={'width':390,'height':844},record_video_dir=temp,record_video_size={'width':390,'height':844})
        page=context.new_page();errors,network=monitor(page)
        page.goto(BASE+'tests/demo.html',wait_until='load')
        page.wait_for_selector('.role-card');no_overflow(page)
        assert '演示数据' in page.locator('.demo-banner').inner_text()
        page.wait_for_timeout(10300);source=page.video.path();context.close()
        video_10s(source,ROOT/'rec-demo.webm',.15)
        assert not errors and not network,(errors,network)
        print('演示页：独立 fixtures，六角色的八组场景，10 秒视频，控制台/pageerror=0。')


def contracts(browser):
    """Synthetic prices and states ONLY in this browser context; no artifacts."""
    now=datetime.now(timezone.utc);stamp=lambda t:t.isoformat().replace('+00:00','Z')
    ts=stamp(now);day=(now+timedelta(hours=7)).date().isoformat()
    team=json.loads((ROOT/'tests/fixtures/demo.json').read_text())['team']
    team['generated_at']=team['status']['updated_at']=ts
    for r in team['status']['roles'].values():r['status']='工作中'
    team['log']=[]
    account=json.loads((ROOT/'paper/account.json').read_text())
    p=dict(symbol='BTC-USDT-SWAP',side=1,qty=2,entry=100,margin=25,mark_price=98,unrealized_pnl=-4,stop=95,take_profit=110,leverage=5,liquidation_price=87.5,entry_time=ts,strategy='manual')
    a=account['accounts'][0];a.update(updated_at=ts,balance=100,equity=96,day=day,day_start=100,positions=[p],fills=[],status='运行中')
    a['manual_status']=[dict(symbol='ZEC-USDT-SWAP',side=1,limit=1218,stop=1172,take_profit=1284,
                             valid_until=stamp(now+timedelta(hours=1)),status=s) for s in ('pending','filled','expired','rejected','cancelled')]
    # Old snapshots must never make the meeting account contribute to the UI.
    meeting=copy.deepcopy(a);meeting.update(id='paper_meeting',name='会议策略',balance=9000,equity=9000)
    account['accounts']=[meeting,a];account['updated_at']=ts
    events=dict(schema_version=1,generated_at=ts,source_status='ok',events=[])
    market=json.loads((ROOT/'tests/fixtures/market.json').read_text())
    sockets=[]
    context=browser.new_context(viewport={'width':390,'height':844})
    def socket(ws):
        sockets.append(ws)
        ws.on_message(lambda msg:ws.send('pong') if msg=='ping' else None)
    context.route_web_socket('**/ws/v5/**',socket)
    page=context.new_page();errors,network=monitor(page)
    page.route('**/paper/team.json?*',lambda r:r.fulfill(json=team))
    page.route('**/paper/account.json?*',lambda r:r.fulfill(json=account))
    page.route('**/paper/events.json?*',lambda r:r.fulfill(json=events))
    def api(route):
        path=route.request.url.split('?')[0]
        result=market['tickers'] if path.endswith('/tickers') else market['candles'] if path.endswith('/candles') else market['funding'] if path.endswith('/funding-rate') else market['interest']
        route.fulfill(json=result)
    page.route('https://www.okx.com/api/v5/**',api)
    page.goto(BASE,wait_until='networkidle')
    page.wait_for_selector('.motion-working')
    assert page.locator('.motion-working').count()==6
    assert page.locator('#toasts .toast').count()==0
    assert page.locator('#pinned-equity').inner_text()=='96.00'
    assert page.locator('#total-equity').inner_text()=='96.00'
    assert page.locator('#daily-risk progress').count()==1
    assert page.locator('#strategy-states .strategy-row').count()==1
    assert '会议策略' not in page.locator('#home-page').inner_text()
    assert '会议单' in page.locator('#live-positions').inner_text()
    assert page.locator('#manual-orders tr').count()==5
    assert '1,218.00' in page.locator('#manual-orders').inner_text()
    for status in ('pending','filled','expired','rejected','cancelled'):
        assert status in page.locator('#manual-orders').inner_text()
    for width in (390,360,320):
        page.set_viewport_size({'width':width,'height':844});no_overflow(page)
    # Partial rows render placeholders; absent optional fields hide the table.
    a['manual_status']=[dict(status='pending')]
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    page.wait_for_function("() => document.querySelectorAll('#manual-orders tr').length===1")
    assert '—' in page.locator('#manual-orders').inner_text()
    a.pop('manual_status');account['accounts']=[a]
    page.route('**/paper/scan.json?*',lambda r:r.fulfill(json=dict(schema_version=1,generated_at=ts,
                source_status='ok',instruments=[],positions=[],recent_signals=[])))
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    page.wait_for_function("() => document.querySelector('#manual-orders-panel').hidden")
    # Every actual quote recomputes balance and daily PnL in the sticky header.
    public=[ws for ws in sockets if ws.url.endswith('/public')][-1]
    public.send(json.dumps(dict(arg=dict(channel='tickers',instId=p['symbol']),data=[dict(last='105',ts=str(int(datetime.now(timezone.utc).timestamp()*1000)))])))
    page.wait_for_function("() => document.querySelector('#pinned-equity').textContent==='110.00'")
    assert '+10.00%' in page.locator('#pinned-daily').inner_text()
    assert page.locator('#pinned-equity .number-in').count()==1
    # A new report triggers once, after the initial snapshot. Refresh by visibility
    # is also the path used when returning to the page after being backgrounded.
    team['log'].append(dict(ts=stamp(now+timedelta(seconds=1)),role='tech',title='测试新报告',summary='测试摘要',grade='A-',status='已完成',meeting='演示数据',phase='P1'))
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    page.wait_for_selector('[data-role="tech"].effect-report')
    assert page.locator('.report-particle').count()==1
    assert '新报告' in page.locator('#toasts').inner_text()
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    page.wait_for_timeout(200)
    assert page.locator('.report-particle').count()==1
    event=lambda kind,reason=None:dict(ts=stamp(now+timedelta(seconds=2)),type=kind,coin=p['symbol'],strategy='breakout',direction='多',price=105,reason=reason)
    events['events']=[event('trade_opened'),event('trade_closed','止损'),event('daily_halt','日亏触线停手'),
                      dict(event('异动','放量 · 2.5 倍'),strategy=None,price=None,direction=None,source_url='https://www.okx.com/markets')]
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    page.wait_for_selector('[data-role="trader"].effect-excited');page.wait_for_selector('[data-role="risk"].effect-warning')
    assert page.locator('[data-role="risk"] .warning-label').text_content()=='停手'
    page.wait_for_function("() => document.querySelector('#events-count').textContent==='4 条'")
    page.wait_for_function("() => document.querySelector('.event-异动').textContent.includes('2.5 倍')")
    assert page.locator('.event-异动 a').get_attribute('href')=='https://www.okx.com/markets'
    assert page.locator('.event-异动').evaluate('e=>getComputedStyle(e).color') != page.locator('.event-trade_opened').evaluate('e=>getComputedStyle(e).color')
    a['fills']=[dict(timestamp=stamp(now+timedelta(seconds=3)),symbol=p['symbol'],side=1,kind='open',qty=2,price=100,notional=200,pnl=None)]
    account['mode']=a['mode']='live';a['id']='live_main'
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    page.wait_for_function("() => document.querySelector('#pinned-mode').textContent==='实盘' && document.querySelector('#toasts').textContent.includes('新成交')")
    page.emulate_media(reduced_motion='reduce')
    page.wait_for_timeout(100)
    assert page.locator('[class*="motion-working"],[class*="effect-"],.number-in,.report-particle,.typing-line').count()==0
    assert page.locator('.robot-body').first.evaluate('e=>getComputedStyle(e).animationName')=='none'
    page.emulate_media(reduced_motion='no-preference')
    old=stamp(now-timedelta(minutes=16))
    roles=list(team['status']['roles'].values())
    for i,r in enumerate(roles):r['status']=('工作中','已完成','待命','离线')[i%4]
    # Team timestamps expire independently; a fresh account keeps every role idle.
    for field in ('updated_at','generated_at'):
        team['status']['updated_at']=team['generated_at']=ts
        if field=='updated_at':team['status'][field]=old
        else:team[field]=old
        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        page.wait_for_function("() => document.querySelectorAll('.state-idle.motion-idle').length===6")
        assert page.locator('.state-offline,.state-working,.state-done').count()==0
        for card in page.locator('.role-card').all():
            assert card.locator('.team-badge').inner_text()=='待命'
            assert float(card.evaluate('e=>getComputedStyle(e).opacity'))<1
            assert card.locator('.robot-stage').evaluate('e=>getComputedStyle(e).filter')=='none'
            assert not card.locator('.robot-zzz').is_visible()
            assert card.locator('.robot-body').evaluate('e=>getComputedStyle(e).animationName')=='breathe'
            assert card.locator('.robot-eyes').evaluate('e=>getComputedStyle(e).animationName')=='blink'
        assert '分钟未更新' not in page.locator('#role-cards').inner_text()
        assert '团队状态或快照' not in page.locator('#role-cards').inner_html()
    # Fresh account wins over an old legacy snapshot and old per-account source.
    legacy=json.loads((ROOT/'tests/fixtures/snapshot.json').read_text())
    legacy['generated_at']=old
    page.route('**/paper/snapshot.json?*',lambda r:r.fulfill(json=legacy))
    a['updated_at']=old
    page.reload(wait_until='networkidle')
    page.wait_for_function("() => document.querySelectorAll('.state-idle.motion-idle').length===6 && document.querySelector('#pinned-time').textContent.includes('延迟')")
    # A stale account snapshot overrides even a fresh legacy snapshot/team.
    legacy['generated_at']=team['generated_at']=team['status']['updated_at']=ts
    account['updated_at']=old
    page.reload(wait_until='networkidle')
    page.wait_for_function("() => document.querySelectorAll('.state-offline').length===6")
    assert page.locator('.state-offline').count()==6
    for card in page.locator('.role-card').all():
        assert card.locator('.robot-body').evaluate('e=>getComputedStyle(e).animationName')=='none'
        assert card.locator('.robot-eyes').evaluate('e=>getComputedStyle(e).animationName')=='none'
        assert card.locator('.robot-stage').evaluate('e=>getComputedStyle(e).filter')=='grayscale(1)'
        assert card.locator('.robot-zzz').is_visible()
        assert '快照超过 15 分钟未更新' in card.inner_text()
    assert page.locator('[class*="motion-"]').count()==0
    # Snapshot refresh recovers idle immediately, even with an expired team.
    account['updated_at']=ts;team['status']['updated_at']=old
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    page.wait_for_function("() => document.querySelectorAll('.state-idle.motion-idle').length===6")
    # On first load without account.json, legacy snapshot freshness is authoritative.
    page.route('**/paper/account.json?*',lambda r:r.fulfill(json={}))
    page.reload(wait_until='networkidle')
    page.wait_for_function("() => document.querySelectorAll('.state-idle.motion-idle').length===6 && document.querySelector('#alerts').textContent.includes('账户快照')")
    legacy['generated_at']=old
    page.reload(wait_until='networkidle')
    page.wait_for_function("() => document.querySelectorAll('.state-offline').length===6")
    # A non-default threshold applies to the browser's account snapshot too.
    page.route('**/paper/account.json?*',lambda r:r.fulfill(json=account))
    account['updated_at']=stamp(now-timedelta(minutes=2))
    config=(ROOT/'config.js').read_text().replace('offlineMinutes: 15','offlineMinutes: 1')
    page.route('**/config.js',lambda r:r.fulfill(body=config,content_type='text/javascript'))
    page.reload(wait_until='networkidle')
    page.wait_for_function("() => document.querySelectorAll('.state-offline').length===6 && document.querySelector('.team-task').textContent.includes('快照超过 1 分钟')")
    no_overflow(page);assert not errors and not network,(errors,network)
    low=context.new_page();low.add_init_script("Object.defineProperty(navigator,'hardwareConcurrency',{get:()=>2});Object.defineProperty(navigator,'deviceMemory',{get:()=>2})")
    low.goto(BASE,wait_until='domcontentloaded');low.wait_for_selector('.role-card');no_overflow(low)
    assert low.locator('html.low-power').count()==1
    assert low.locator('.role-card').first.evaluate('e=>getComputedStyle(e).backdropFilter')=='none'
    assert not errors and not network,(errors,network)
    context.close()
    print('隔离契约：报价重算、实盘标签/新成交提示、低端设备降级、新报告/交易动作、reduced-motion、团队过期待命呼吸眨眼、快照离线/恢复/回退/配置阈值、控制台=0：通过。')


def main():
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=CHROME,headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        try:
            from portfolio_browser import contracts as portfolio_contracts
            contracts(browser);portfolio_contracts(browser);real_artifacts(browser)
        finally:browser.close()

if __name__=='__main__':main()
