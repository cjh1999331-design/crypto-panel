"""One final browser pass: isolated interactions, then real history screenshot."""
import copy
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get('PANEL_URL', 'http://127.0.0.1:8008/')


def no_overflow(page):
    page.wait_for_function('() => document.documentElement.scrollWidth <= innerWidth')
    assert page.evaluate('() => document.documentElement.scrollWidth <= innerWidth')


def main():
    now = datetime.now(timezone.utc)
    ts = now.isoformat()
    source = json.loads((ROOT / 'paper/account.json').read_text())
    source = copy.deepcopy(source)
    a = source['accounts'][0]
    a.update(status='运行中', strategy_enabled=True, updated_at=ts, day=(now+timedelta(hours=7)).date().isoformat(),
             day_start=100, balance=96, equity=96, positions=[], strategies={'mean_reversion': {'rsi': 25, 'trend': .02}, 'breakout': {'lookback': 20}},
             enabled_strategies=['mean_reversion'], entry_mode_by_strategy={'mean_reversion': 'maker'})
    source['updated_at'] = ts
    source.pop('pause', None)
    a['daily_loss_limit'] = .08
    source['decisions']['blackout_windows'] = [{'start': (now-timedelta(minutes=1)).isoformat(), 'end': (now+timedelta(minutes=5)).isoformat(), 'symbols': ['BTC-USDT-SWAP'], 'reason': '公开事件'}]
    symbol = lambda n: f'C{n}-USDT-SWAP'
    scan = dict(schema_version=1, generated_at=ts, source_status='ok', instruments=[dict(instId=symbol(i), quote_24h=1e8-i, spread=.0001, leverage_cap=10, signals={'mean_reversion': 1, 'breakout': 1}, signal_status='ok', held=False) for i in range(23)],
                recent_signals=[dict(instId=symbol(i), timestamp=(now-timedelta(minutes=i)).isoformat(), strategy='mean_reversion', side=1, opened=False, reason='maker_pending') for i in range(14)] + [dict(instId='OLD-USDT-SWAP', timestamp=ts, strategy='breakout', side=1, opened=False, reason='strategy_disabled')], positions=[])
    h = copy.deepcopy(json.loads((ROOT/'paper/history.json').read_text()))
    h.update(generated_at=ts, historical=False)
    template = dict(symbol='BTC-USDT-SWAP',strategy='manual',side=1,entry_time=(now-timedelta(hours=2)).isoformat(),exit_time=ts,qty=1,leverage=5,entry=100,exit=101,notional=100,margin=20,pnl=.9,pnl_percent=4.5,fee=.1,gross_pnl=1,reason='target_live')
    h['equity']=[dict(timestamp=(now-timedelta(hours=3-i)).isoformat(),equity=100-i) for i in range(4)]
    h['trades'] = [dict(template, symbol='BTC-USDT-SWAP', strategy='manual', entry_time=(now-timedelta(hours=2)).isoformat(), exit_time=(now-timedelta(minutes=i)).isoformat()) for i in range(25)] + [dict(template, symbol='ETH-USDT-SWAP', strategy='mean_reversion')]
    h['alert_groups'] = [dict(wake_index=1, timestamp=ts, adopted=False, alerts=[dict(ts=ts, symbol='ETH-USDT-SWAP', type='volume', adopted=False)], orders=[]), dict(wake_index=2, timestamp=ts, adopted=True, alerts=[dict(ts=ts, symbol='BTC-USDT-SWAP', type='breakout', adopted=True)], orders=[dict(symbol='BTC-USDT-SWAP', side=1, status='filled', time=ts, closed_time=ts, pnl=-2, match='exact')])]
    market = json.loads((ROOT/'tests/fixtures/market.json').read_text())
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/google-chrome', headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        try:
            context = browser.new_context(viewport={'width':390,'height':844}, reduced_motion='reduce')
            page = context.new_page()
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('console', lambda m: errors.append(m.text) if m.type=='error' else None)
            page.route('**/paper/account.json?*', lambda r:r.fulfill(json=source))
            page.route('**/paper/scan.json?*', lambda r:r.fulfill(json=scan))
            page.route('**/paper/history.json?*', lambda r:r.fulfill(json=h))
            def api(route):
                url=route.request.url
                data=market['candles'] if '/candles?' in url else market['tickers'] if '/tickers?' in url else {'code':'0','data':[{'instId':'ZEC-USDT-SWAP','fundingRate':'0','fundingTime':str(int(now.timestamp()*1000)),'oiCcy':'0'}]}
                route.fulfill(json=data)
            page.route('https://www.okx.com/api/v5/**', api)
            page.route_web_socket('**/ws/v5/**',lambda ws:ws.on_message(lambda message:ws.send('pong') if message=='ping' else None))
            if os.environ.get('HISTORY_BROWSER_RESUME')=='history':
                page.goto(BASE+'#/paper', wait_until='networkidle', timeout=60000)
            else:
                page.goto(BASE, wait_until='networkidle', timeout=60000)
                page.wait_for_function("() => document.querySelector('#scan-body').children.length===15")
                if not os.environ.get('HISTORY_BROWSER_RESUME'):
                    assert page.locator('#scan-recent tr').count()==10
                    assert 'OLD' not in page.locator('#scan-recent').inner_text()
                assert '突破放量' not in page.locator('#home-page').inner_text()
                assert '放量突破六条件' not in page.locator('#home-page').inner_text()
                assert page.locator('#bt60-fold,#market-fold,#history-fold').count()==0
                assert page.locator('#team-fold,#role-cards').count()==0
                assert page.locator('#strategy-states input').count()==1
                page.locator('#scan-expand').click();assert page.locator('#scan-body tr').count()==23
                page.locator('#scan-expand').click();assert page.locator('#scan-body tr').count()==15
                page.locator('#signals-expand').click();assert page.locator('#scan-recent tr').count()==14
                page.locator('#signals-expand').click();assert page.locator('#scan-recent tr').count()==10
                page.locator('#scan-recent [data-chart-coin]').first.click()
                page.wait_for_selector('#coin-page:not([hidden])')
                page.locator('#coin-page > .page-heading [data-timeframe="4H"]').click()
                page.locator('#coin-page > .page-heading [data-timeframe="1H"]').click()
                page.wait_for_function("() => document.querySelector('#conditions').children.length===7")
                for width in (390,360):
                    page.set_viewport_size({'width':width,'height':844});no_overflow(page)
                page.locator('[data-nav="paper"]').click()
            page.wait_for_function("() => document.querySelector('#history-trades').children.length===20")
            assert '禁开中，剩余' in page.locator('#history-blackout').inner_text()
            assert page.locator('#history-risk progress').count()==3
            assert page.locator('#history-strategies .history-card').count()==3
            assert '未采纳' in page.locator('#history-alerts').inner_text()
            assert '精确引用' in page.locator('#history-alerts').inner_text()
            assert '最终净盈亏 -2.00 USDT' in page.locator('#history-alerts').inner_text()
            for period in ('day','week','all'):
                page.locator(f'#history-range [data-range="{period}"]').click()
                assert page.locator(f'#history-range [data-range="{period}"]').get_attribute('aria-pressed')=='true'
                assert page.locator('#history-curve svg').count()==1
            page.locator('#history-next').click();assert page.locator('#history-trades .trade-card').count()==6
            page.select_option('#history-symbol','ETH-USDT-SWAP');assert page.locator('#history-trades .trade-card').count()==1
            page.select_option('#history-strategy','manual');assert page.locator('#history-trades .trade-card').count()==0
            page.select_option('#history-symbol','');assert page.locator('#history-trades .trade-card').count()==20
            page.select_option('#history-strategy','');assert page.locator('#history-trades .trade-card').count()==20
            for width in (390,360):
                page.set_viewport_size({'width':width,'height':844});no_overflow(page)
                for detail in page.locator('#paper-page > details').all():
                    detail.locator(':scope > summary').click();assert not detail.evaluate('e=>e.open')
                    detail.locator(':scope > summary').click();assert detail.evaluate('e=>e.open')
                no_overflow(page)
            assert not errors, errors
            context.close()
            # Actual local snapshots only; no synthetic account/history/market responses.
            real = browser.new_context(viewport={'width':390,'height':844}, reduced_motion='reduce')
            page = real.new_page()
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('console', lambda m: errors.append(m.text) if m.type=='error' else None)
            page.goto(BASE+'#/paper', wait_until='networkidle', timeout=60000)
            page.wait_for_function("() => document.querySelector('#history-trades').textContent.includes('暂无记录')")
            page.evaluate('document.fonts.ready')
            assert page.locator('#history-trades .trade-card').count()==len(json.loads((ROOT/'paper/history.json').read_text())['trades'])
            for width in (360,390):
                page.set_viewport_size({'width':width,'height':844});no_overflow(page)
            page.screenshot(path=str(ROOT/'shot-history.png'),animations='disabled')
            assert not errors, errors
            print('统一浏览器验收通过：首页精简、扫描15行/信号10条展开、选币/周期、账户历史曲线/战绩/成交筛选分页/折叠/风控/倒计时/异动关联；390/360px无页面横向溢出；console.error/pageerror=0。真实账户历史整页截图：shot-history.png (390×844)。')
            real.close()
        except Exception:
            print('Browser errors:', errors)
            if not page.is_closed():
                print('History status:', page.locator('#history-error').inner_text(), 'cards:', page.locator('#history-trades .trade-card').count())
            raise
        finally:
            browser.close()

if __name__=='__main__':
    main()
