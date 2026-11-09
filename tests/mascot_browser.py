"""Reset UI + pointer/touch/accessibility contracts and actual mobile artifacts."""
import copy
import json
import os
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
BASE=os.environ.get('PANEL_URL','http://127.0.0.1:8008/')

def check(page):
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')

def errors_for(page):
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    return errors

def contracts(browser):
    source=json.loads((ROOT/'paper/account.json').read_text())
    market=json.loads((ROOT/'tests/fixtures/market.json').read_text())
    now=datetime.now(timezone.utc);ts=now.isoformat();source['updated_at']=ts
    context=browser.new_context(viewport={'width':390,'height':844},has_touch=True)
    context.route_web_socket('**/ws/v5/**',lambda ws:ws.on_message(lambda msg:ws.send('pong') if msg=='ping' else None))
    context.route('https://www.okx.com/api/v5/**',lambda r:r.fulfill(json=market['candles'] if '/candles?' in r.request.url else market['tickers'] if '/tickers?' in r.request.url else market['funding'] if '/funding-rate?' in r.request.url else market['interest']))
    context.route('**/paper/account.json?*',lambda r:r.fulfill(json=source))
    context.route('**/paper/events.json?*',lambda r:r.fulfill(json=dict(schema_version=1,generated_at=ts,source_status='ok',events=[])))
    context.route('**/paper/team.json?*',lambda r:r.fulfill(json=dict(schema_version=1,status=dict(updated_at=None,meeting=None,phase=None,roles={}),log=[])))
    page=context.new_page();errors=errors_for(page)
    page.goto(BASE,wait_until='networkidle')
    page.wait_for_selector('#mascot[data-state="paused"]')
    assert page.locator('.role-card,#role-cards').count()==0
    assert page.locator('#pinned-equity').inner_text()=='100.00'
    assert '模拟盘已暂停，等待重新开始' in page.locator('#pause-banner').inner_text()
    assert '模拟盘已暂停，暂无持仓' in page.locator('#live-positions').inner_text()
    assert '暂无记录' in page.locator('#equity-error').inner_text()
    page.locator('#mascot-touch').tap()
    assert page.locator('#mascot-bubble').inner_text()=='模拟盘暂停中'
    first=page.locator('#mascot').get_attribute('class')
    page.locator('#mascot-touch').tap()
    assert first!=page.locator('#mascot').get_attribute('class')
    assert page.locator('#mascot-drawer').is_visible();page.keyboard.press('Escape')
    # Real mouse pointer drag: moving must not toggle the expression.
    button=page.locator('#mascot-touch');r=button.bounding_box();x=r['x']+r['width']/2;y=r['y']+r['height']/2
    before=page.locator('#mascot').get_attribute('class')
    page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+14,y+10,steps=5);page.mouse.up()
    assert page.locator('#mascot').get_attribute('class')==before
    pos=json.loads(page.evaluate("localStorage.getItem('modi-mascot-position')"));assert pos=={'x':14,'y':10},pos
    # Touch drag uses the same pointer capture path; it must not trigger a tap.
    cdp=context.new_cdp_session(page)
    cdp.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':x+14,'y':y+10}]})
    cdp.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[{'x':x-12,'y':y-10}]})
    cdp.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
    assert page.locator('#mascot').get_attribute('class')==before
    saved=page.evaluate("localStorage.getItem('modi-mascot-position')")
    page.reload(wait_until='networkidle')
    page.wait_for_selector('#mascot[data-state="paused"]')
    assert page.locator('#mascot-touch').evaluate('e=>e.style.transform')==f"translate({json.loads(saved)['x']}px, {json.loads(saved)['y']}px)"
    page.locator('#mascot-collapse').tap();assert 'collapsed' in page.locator('#mascot').get_attribute('class')
    assert page.locator('#mascot-touch').bounding_box()['width']>=44
    page.locator('#mascot-touch').tap();assert 'collapsed' not in page.locator('#mascot').get_attribute('class')
    page.locator('#mascot-reports').tap();assert page.locator('#mascot-drawer').is_visible()
    assert page.locator('#mascot-report-list').inner_text()=='暂无报告'
    page.keyboard.press('Escape');assert not page.locator('#mascot-drawer').is_visible()
    page.locator('#mascot-reports').focus();page.keyboard.press('Enter');assert page.locator('#mascot-drawer').is_visible()
    page.locator('[data-close]').click();assert not page.locator('#mascot-drawer').is_visible()
    assert page.locator('#mascot-reports').evaluate('e=>e===document.activeElement')
    page.emulate_media(reduced_motion='reduce');assert page.locator('#mascot').evaluate("e=>e.classList.contains('still')")
    assert page.locator('.mascot-body').evaluate('e=>getComputedStyle(e).animationName')=='none'
    page.emulate_media(reduced_motion='no-preference')
    for prop in ('hardwareConcurrency','deviceMemory'):
        low=context.new_page();low.add_init_script(f"Object.defineProperty(navigator,'{prop}',{{get:()=>2}})")
        low.goto(BASE,wait_until='networkidle');assert low.locator('#mascot').evaluate("e=>e.classList.contains('still')")
        assert low.locator('.mascot-body').evaluate('e=>getComputedStyle(e).animationName')=='none';low.close()
    page.locator('[data-nav="paper"]').click();page.wait_for_function("() => document.querySelector('#history-trades').textContent.includes('暂无记录')")
    assert '暂无记录' in page.locator('#history-strategies').inner_text()
    assert page.locator('#history-error').inner_text()==''
    for width in (320,360,390):page.set_viewport_size({'width':width,'height':844});check(page)
    # An expired public snapshot is the only reason this paused mascot goes offline.
    source['updated_at']=(now-timedelta(minutes=16)).isoformat()
    page.goto(BASE,wait_until='networkidle');page.wait_for_selector('#mascot[data-state="offline"]')
    source['updated_at']=ts;source.pop('pause');source['accounts'][0].update(status='运行中',strategy_enabled=True,daily_loss_limit=.08)
    page.reload(wait_until='networkidle');page.wait_for_selector('#mascot[data-state="idle"]')
    # Latest reports live in the drawer, with source text escaped.
    team=dict(schema_version=1,status=json.loads((ROOT/'tests/fixtures/team/team_status.json').read_text()),log=[])
    for role,r in team['status']['roles'].items():r['last_report']=dict(ts=ts,title='新报告 <script>',summary='公开摘要',grade='A-')
    context.route('**/paper/team.json?*',lambda r:r.fulfill(json=team))
    page.reload(wait_until='networkidle');page.locator('#mascot-reports').tap()
    page.wait_for_function("() => document.querySelectorAll('#mascot-report-list article').length===4")
    assert '<script>' in page.locator('#mascot-report-list').inner_text();assert page.locator('#mascot-report-list script').count()==0
    assert not errors,errors
    context.close()
    print('浏览器契约通过：暂停/空状态、鼠标和触摸拖动、点击区分/位置恢复、收起、键盘/Esc抽屉、4成员报告、reduced-motion/低端设备、过期离线、320/360/390无溢出、pageerror=0。')

def artifacts(browser):
    # Local public data is never intercepted in this context.
    errors=[]
    with tempfile.TemporaryDirectory() as tmp:
        context=browser.new_context(viewport={'width':390,'height':844},has_touch=True,record_video_dir=tmp,record_video_size={'width':390,'height':844})
        begin=time.monotonic();page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(BASE,wait_until='domcontentloaded');page.wait_for_selector('#mascot[data-state]');page.evaluate('document.fonts.ready')
        page.screenshot(path=str(ROOT/'shot-mobile.png'),animations='disabled')
        start=time.monotonic()-begin
        page.locator('#mascot-touch').tap();page.wait_for_timeout(450)
        page.screenshot(path=str(ROOT/'shot-mascot.png'),animations='disabled')
        r=page.locator('#mascot-touch').bounding_box();x=r['x']+50;y=r['y']+50
        page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+16,y+12,steps=8);page.mouse.up();page.wait_for_timeout(450)
        page.locator('#mascot-collapse').tap();page.wait_for_timeout(450)
        page.locator('#mascot-touch').tap();page.wait_for_timeout(450)
        page.locator('#mascot-reports').tap();page.wait_for_timeout(450)
        page.screenshot(path=str(ROOT/'shot-drawer.png'),animations='disabled')
        page.keyboard.press('Escape');page.wait_for_timeout(500)
        page.locator('[data-nav="paper"]').click();page.wait_for_function("() => document.querySelector('#history-trades').textContent.includes('暂无记录')")
        page.screenshot(path=str(ROOT/'shot-history.png'),animations='disabled')
        video=page.video.path();context.close()
        subprocess.run(['ffmpeg','-y','-loglevel','error','-ss',str(start),'-i',video,'-t','7.5','-an','-c:v','libvpx-vp9','-crf','35','-b:v','0',str(ROOT/'rec-mascot.webm')],check=True)
    duration=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(ROOT/'rec-mascot.webm')]))
    assert 0<duration<=8,duration
    assert not errors,errors
    print(f'真实快照截图完成：shot-mobile / shot-history / shot-mascot / shot-drawer，均390×844；录屏 {duration:.2f}s；pageerror=0。')


def main():
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        try:contracts(browser);artifacts(browser)
        finally:browser.close()
if __name__=='__main__':main()
