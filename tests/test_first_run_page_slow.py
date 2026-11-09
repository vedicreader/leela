"First run in a real window: 'Learn something' switches to Learn mode and focuses the Start box."
import asyncio
from pathlib import Path
import pytest
from tools.isolate import isolate
isolate()
pytestmark = pytest.mark.slow

OUT = str(Path(__file__).resolve().parents[1]/'target')

def _env(monkeypatch):
    from abhyasa.learner import temp_learning
    from leela.blocks.learn import host
    lr = temp_learning()
    monkeypatch.setattr(host, 'learn_store', lambda ws, vault=None, write=False: ('test', lr))
    monkeypatch.setattr(host, 'HOSTS', ('127.0.0.1', 'localhost', '::1'))

def _run(scenario, viewport):
    from playwright.async_api import async_playwright
    from leela.workspace import Workspace
    from tests.test_web_slow import _free_port, _launch, _serve, _started, fake_kernels
    async def go():
        restore = fake_kernels(); ws = Workspace(roots=[])
        port = _free_port(); srv = _serve(ws, port); await _started(srv)
        try:
            async with async_playwright() as pw:
                browser = await _launch(pw)
                try:
                    pg = await browser.new_page(viewport=viewport)
                    bad = []; pg.on('pageerror', lambda e: bad.append(str(e)))
                    await pg.goto(f'http://127.0.0.1:{port}/', wait_until='networkidle')
                    await pg.wait_for_function('window.lee && lee.keys.length')
                    await scenario(pg, ws, bad)
                finally: await browser.close()
        finally: srv.should_exit = True; ws.shutdown_now(); restore()
    asyncio.run(go())

async def _shots(pg, name):
    for mode in ('light', 'dark'):
        await pg.evaluate(f"applyTheme('leela:{mode}:relaxed')"); await pg.wait_for_timeout(500)
        await pg.screenshot(path=f'{OUT}/{name}-{mode}.png')
    await pg.evaluate("applyTheme('leela:light:relaxed')")

@pytest.mark.parametrize('w,h,name', [(1500, 900, 'm4-firstrun'), (860, 900, 'm4-firstrun-860')])
def test_the_page_shows_three_choices_without_overflow(w, h, name):
    pytest.importorskip('playwright.async_api')
    async def scenario(pg, ws, bad):
        ways = pg.locator('#editor .lee-first-way'); await ways.first.wait_for()
        assert await ways.count() == 3 and ' '.join(await ways.locator('strong').all_inner_texts()) == 'Open a folder Learn something Write or run code'
        assert 'Switch between Code and Learn' in await pg.locator('.lee-first-note').inner_text()
        for i in range(3): assert await ways.nth(i).is_visible()
        assert await pg.evaluate("() => { const e = document.querySelector('#editor'); return e.scrollWidth <= e.clientWidth }")
        await _shots(pg, name)
        assert not bad, bad
    _run(scenario, dict(width=w, height=h))

def test_learn_something_switches_mode_and_focuses_the_start_box(monkeypatch):
    pytest.importorskip('playwright.async_api')
    _env(monkeypatch)
    async def scenario(pg, ws, bad):
        await pg.locator('#first-learn').click()
        await pg.locator('#start-form #start-q').wait_for(timeout=30000)
        await pg.wait_for_function("document.activeElement && document.activeElement.id === 'start-q'", timeout=10000)
        assert ws.mode == 'learn' and ws.tab.kind == 'learn' and ws.tab.page == '/'
        assert await pg.evaluate("document.querySelector('#shell').classList.contains('lee-learn-on')")
        assert await pg.locator('.lee-first-way').count() == 0
        assert not bad, bad
    _run(scenario, dict(width=1500, height=900))
