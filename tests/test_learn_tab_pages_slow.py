import asyncio, json
from pathlib import Path

import pytest

from tools.isolate import isolate

isolate()
pytestmark = pytest.mark.slow

OUT = str(Path(__file__).resolve().parents[1]/'target')
GRADE = r'{"correct": true, "grade": 10, "feedback": "Correct.", "first_error": "", "misconception": ""}'
SHELL = """() => { const css = s => { const x = getComputedStyle(document.querySelector(s)); return [x.fontFamily, x.fontSize, x.color, x.backgroundColor] }; return [css('body'), css('#agentprompt')] }"""


def _env(tmp_path, monkeypatch):
    from abhyasa.agent_tools import create_walk
    from abhyasa.learner import temp_learning
    from leela.blocks.learn import host
    from tools.s2_native_pilot import PLAN
    lr = temp_learning()
    jid = create_walk(lr, lambda p, sp='': PLAN, 'fractions', settings={})['walk']
    for step, q in zip(lr.journey(jid).steps, ('What does a fraction name?', 'How do you add fractions?')):
        lr.update(step['slug'], core='A fraction names equal parts of a whole.')
        lr.walk_slug(jid, step['slug'], note_none=True, check={**step['check'], 'q': q})
    monkeypatch.setattr(host, 'learn_store', lambda ws, vault=None, write=False: ('test', lr))
    monkeypatch.setattr(host, 'HOSTS', ('127.0.0.1', 'localhost', '::1'))
    return lr, jid, lr.journey(jid).steps[0]['slug']


def _run(tmp_path, scenario, viewport=None):
    from playwright.async_api import async_playwright
    from ramabana.core import ModelSpec
    from leela.workspace import Workspace
    from tests.fakemodel import install
    from tests.test_web_slow import _free_port, _launch, _serve, _started, fake_kernels
    lesson = tmp_path/'lesson.py'; lesson.write_text('answer = 42\n')
    async def go():
        restore = fake_kernels(); ws = Workspace(roots=[tmp_path.resolve()]); ws.open(lesson)
        be = install(ws, [], spec=ModelSpec('grade-hosted', 'remote', 'scripted/model', ctx=8000))
        be.supports_deadline = True
        be._oneshot = lambda prompt, sp, max_tokens, deadline=None: GRADE
        port = _free_port(); srv = _serve(ws, port); await _started(srv)
        try:
            async with async_playwright() as pw:
                browser = await _launch(pw)
                try:
                    pg = await browser.new_page(viewport=viewport or dict(width=1280, height=900))
                    await pg.goto(f'http://127.0.0.1:{port}/', wait_until='networkidle')
                    await pg.wait_for_function('window.lee && lee.keys.length')
                    await pg.evaluate("leeRight('agent')")
                    await pg.locator('#agentprompt').wait_for()
                    await scenario(pg, ws, port)
                finally: await browser.close()
        finally:
            srv.should_exit = True; ws.shutdown_now(); restore()
    asyncio.run(go())


def test_chords_work_only_inside_the_learn_tab(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        hints = []
        pg.on('request', lambda r: hints.append(r.url) if '/hint' in r.url else None)
        ws.open_walk('workspace', jid); ws.save(); await pg.evaluate('mountTab()')
        await pg.locator('.abh #check .check').wait_for(timeout=30000)
        await pg.wait_for_load_state('networkidle'); await pg.wait_for_timeout(1000)
        await pg.locator('.abh #ans').click()
        await pg.keyboard.press('Alt+KeyW')
        await pg.wait_for_timeout(1500)
        assert any(f'/learn/abh/w/{jid}/' in u for u in hints), hints
        before = len(hints)
        await pg.locator('#agentprompt').focus()
        await pg.keyboard.press('Alt+KeyW')
        await pg.wait_for_timeout(800)
        assert len(hints) == before
        assert (await pg.evaluate('lee.lastKeyEvent')).get('code') == 'KeyW'
        await pg.locator('.abh #ans').click()
        await pg.locator('.abh #ans').fill('A fraction names equal parts of a whole.')
        await pg.keyboard.press('Alt+KeyS')
        await pg.locator('.abh #check').get_by_text('Correct.', exact=True).wait_for(timeout=30000)
        assert lr.attempts()
    _run(tmp_path, scenario)


def test_learn_tab_opens_home_concept_progress_and_graph_by_path(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        bad = []
        pg.on('pageerror', lambda e: bad.append(str(e)))
        pg.on('response', lambda r: bad.append((r.status, r.url)) if r.status >= 400 and '/git/file' not in r.url else None)
        await pg.evaluate("applyTheme('leela:light:relaxed')")
        before = await pg.evaluate(SHELL)
        href = await pg.evaluate('() => [location.href, history.length]')
        for path in ('/', f'/c/{slug}', '/you', '/graph'):
            await pg.evaluate('p => leeLearnOpen(p)', path)
            await pg.locator('.abh main').first.wait_for(timeout=30000)
            await pg.wait_for_timeout(500)
            assert await pg.locator('.abh .crumbs a, .abh h1, .abh h2').count() or path == '/graph', path
            assert ws.tab.kind == 'learn' and ws.tab.page in (path, '/library/graph'), (ws.tab.page, path)
            await pg.screenshot(path=f'{OUT}/p0-page-{path.strip("/").split("/")[0] or "home"}.png')
            assert await pg.evaluate(SHELL) == before
            assert await pg.evaluate('() => [location.href, history.length]') == href
        assert not bad, bad
        await pg.evaluate('() => document.querySelector(".abh").insertAdjacentHTML("beforeend", \'<a id="t-keys" href="/keys">Keys</a><a id="t-set" href="/settings">Settings</a>\')')
        await pg.locator('#t-keys').evaluate('el => el.click()')
        await pg.wait_for_timeout(500)
        assert await pg.evaluate('() => !!document.querySelector(".lee-modal, .lee-help, #helpbody, [role=dialog]")')
        assert await pg.locator('.abh a[href="/keys"]').count() == 1
        await pg.keyboard.press('Escape')
        await pg.evaluate('p => leeLearnOpen(p)', f'/c/{slug}')
        await pg.locator('.abh main').first.wait_for()
        await pg.wait_for_timeout(300)
        link = pg.locator('.abh main a[href^="/w/"], .abh main a[href^="/c/"]').first
        if await link.count():
            await link.evaluate('el => el.click()')
            await pg.wait_for_timeout(800)
            assert await pg.locator('[data-learn-back]').is_enabled()
            await pg.locator('[data-learn-back]').click()
            await pg.wait_for_timeout(800)
            assert ws.tab.page == f'/c/{slug}'
    _run(tmp_path, scenario)
