"""Real-data screenshots first; intercepted contract scenarios never enter artifacts."""
from datetime import datetime, timedelta, timezone
import copy
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get('PANEL_URL', 'http://127.0.0.1:8008/')


def no_overflow(page):
    page.wait_for_function('() => document.documentElement.scrollWidth <= innerWidth',timeout=3000)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), '页面横向溢出'


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get('CHROME_PATH','/usr/bin/google-chrome'),
                                    headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        try:
            page = browser.new_page(viewport={'width':1440,'height':1050},device_scale_factor=1)
            errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('console',lambda m:errors.append(m.text) if m.type=='error' else None)
            page.goto(BASE,wait_until='networkidle',timeout=60000)
            page.wait_for_function("() => document.querySelectorAll('#conditions li').length===6 && document.querySelectorAll('#price-chart canvas').length>0")
            page.wait_for_function("() => document.querySelectorAll('#strategy-states .strategy-row').length===2")
            page.wait_for_function("() => document.querySelector('#bt60-status').textContent.includes('策略')")
            page.evaluate('document.fonts.ready')
            assert page.locator('#alerts').inner_text()==''
            assert page.locator('.role-card').count()==6
            assert page.locator('.data-card').count()==2
            assert page.locator('.workstation').count()==6
            assert page.locator('#chart-error').is_hidden()
            assert page.locator('#equity-error').is_hidden()
            assert page.locator('#mode-tag').inner_text()=='模拟盘'
            source=json.loads((ROOT/'paper/account.json').read_text())
            balance=sum(a['balance'] for a in source['accounts'] if a['status']!='未启动')
            assert float(page.locator('#total-equity').inner_text().replace(',',''))==round(balance,2)
            no_overflow(page)
            page.screenshot(path=str(ROOT/'shot-desktop.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            page.wait_for_timeout(400)
            no_overflow(page)
            assert page.locator('.role-cards').evaluate("e=>getComputedStyle(e).gridTemplateColumns.split(' ').length")==2
            page.screenshot(path=str(ROOT/'shot-mobile.png'),full_page=True)
            print('真实行情与快照：1440 桌面、390×844 手机整页截图已生成。')

            for width in (390,360,320):
                page.set_viewport_size({'width':width,'height':844})
                no_overflow(page)
                for name in ('timeline','bt60','market','history'):
                    page.locator(f'#{name}-fold > summary').click()
                    no_overflow(page)
                assert page.locator('#bt60-results .bt60-group').count()>0
                assert page.locator('#market-body tr').count()==30
                assert page.locator('#history-summary article').count()==4
                page.locator('#search').fill('ZEC')
                assert page.locator('#market-body tr').count()==1
                page.locator('#search').fill('')
                for name in ('timeline','bt60','market','history'):
                    page.locator(f'#{name}-fold > summary').click()
            page.locator('#home-page [data-timeframe="4H"]').click()
            page.wait_for_function("() => document.querySelector('#analysis-period').textContent.includes('4 小时')")
            assert '1 小时' in page.locator('[data-role="tech"] .team-metric').inner_text()
            page.locator('#home-page [data-timeframe="1H"]').click()
            page.wait_for_function("() => document.querySelector('#analysis-period').textContent.includes('1 小时')")
            print('手机 390/360/320、全部折叠区展开、搜索、1H/4H：通过，无页面横向溢出。')

            # Contract-only synthetic responses. Never write these to paper/ or screenshots.
            now=datetime.now(timezone.utc)
            iso=lambda t:t.isoformat().replace('+00:00','Z')
            day=(now+timedelta(hours=7)).date().isoformat()
            position=dict(symbol='XTEST-USDT-SWAP',side=-1,qty=2,entry=100,stop=104,take_profit=90,
                          leverage=5,margin=40,mark_price=98,unrealized_pnl=4,liquidation_price=119,entry_time=iso(now))
            active=next(a for a in source['accounts'] if a['status']!='未启动')
            active={**copy.deepcopy(active), 'id':'live_strategy','name':'验证策略','mode':'live','status':'运行中',
                    'updated_at':iso(now),'balance':100,'equity':104,'initial':100,'day':day,'day_start':100,'daily_pnl':4,
                    'positions':[position],'strategy_enabled':True,'risk':None,'strategies':{},
                    'fills':[dict(timestamp=iso(now),symbol=position['symbol'],side=-1,kind='open',qty=2,price=100,notional=200,pnl=None)]}
            decisions=dict(status='active',version='test',updated_at=iso(now),meeting='验证会议',global_size_factor=.5,
                symbols={'ZEC-USDT-SWAP':dict(bias='watch',note='等待公开信号',size_factor=.5)},
                blackout_windows=[dict(start=iso(now-timedelta(minutes=1)),end=iso(now+timedelta(hours=1)),symbols=['*'],reason='验证窗口')])
            live=dict(mode='live',source='仅测试响应',updated_at=iso(now),accounts=[active],decisions=decisions)
            page.route('**/paper/account.json?*',lambda route:route.fulfill(json=live))
            page.reload(wait_until='networkidle')
            page.wait_for_function("() => document.querySelector('#mode-tag').textContent==='实盘'")
            assert page.locator('#total-equity').inner_text()=='100.00'
            assert page.locator('#live-positions tr').count()==1
            assert '5.0×' in page.locator('#live-positions').inner_text()
            assert '200.00' in page.locator('.data-card').first.inner_text()
            assert '事件窗口禁开新仓' in page.locator('#strategy-states').inner_text()
            assert '观察' in page.locator('#coin-decision').inner_text()
            assert '生效中' in page.locator('#decisions-panel').inner_text()
            assert page.locator('#strategy-states input').is_disabled()
            assert '暂无策略参数' in page.locator('#strategy-params').inner_text()
            assert '暂无风控细项' in page.locator('#room-risk-params').inner_text()
            no_overflow(page)
            print('拦截响应验证：live 同结构复用、持仓/成交/决议/事件窗口/只读开关通过。')
            assert not errors, errors
            print('console.error / pageerror：0；全部布局与契约浏览器检查通过。')
        finally:
            browser.close()


if __name__=='__main__':
    main()
