import asyncio, sys, time
from pathlib import Path

import pytest

from tools.isolate import isolate

isolate()
pytestmark = pytest.mark.slow

OUT = str(Path(__file__).resolve().parents[1]/'target')
GRADE = r'{"correct": false, "grade": 2, "feedback": "Look at positions.", "first_error": "You add raw scores.", "misconception": ""}'
SHELL = """() => { const css = s => { const x = getComputedStyle(document.querySelector(s)); return [x.fontFamily, x.fontSize, x.color, x.backgroundColor] }; return [css('body'), css('#agentprompt')] }"""
MAIN = "() => { const r = document.querySelector('.abh main').getBoundingClientRect(); return [Math.round(r.width), document.querySelector('.abh').getBoundingClientRect().width] }"


def _env(monkeypatch):
    from talk_data import talk_walk
    from abhyasa.learner import temp_learning
    from abhyasa.path import join_course
    from leela.blocks.learn import host
    lr = temp_learning()
    jid = talk_walk(lr)
    for n, pre in (('Noise', []), ('Denoise', ['noise']), ('Sample', ['denoise'])): lr.put(n, f'{n} a picture.', 'ml', prereqs=pre)
    lr.put_journey(dict(id='gw', title='Diffusion for comics', goal='Fine-tune diffusion for comics', mode='walk', source=None, started=time.time(), created=1.,
                        steps=[dict(slug=s, status='todo', check=dict(way='words', kind='short', depth=2)) for s in ('noise', 'denoise', 'sample')], chips=[], chip_counts={}, notes=[]))
    lr.walk_step('gw', 0, done=dict(outcome='solid', at=time.time())); lr.update('noise', floor=4, seen=1, last=time.time(), stability=5., due=time.time() + 5*86400)
    cid = join_course(lr, 'gw').id
    lr.update('softmax', floor=3, seen=2, last=time.time(), stability=3., due=time.time() + 3*86400)
    lr.record('softmax', 'What does softmax give for a list of scores?', answer='the biggest score', correct=False, grade=2)
    time.sleep(.02)
    lr.record('softmax', 'What does softmax give for a list of scores?', answer='weights that sum to 1', correct=True, grade=9)
    monkeypatch.setattr(host, 'learn_store', lambda ws, vault=None, write=False: ('test', lr))
    monkeypatch.setattr(host, 'HOSTS', ('127.0.0.1', 'localhost', '::1'))
    return lr, jid, cid


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
        asked = be.asked = []
        def one(prompt, sp, max_tokens, deadline=None): asked.append(prompt); return GRADE
        be._oneshot = one
        port = _free_port(); srv = _serve(ws, port); await _started(srv)
        try:
            async with async_playwright() as pw:
                browser = await _launch(pw)
                try:
                    pg = await browser.new_page(viewport=viewport or dict(width=1500, height=900))
                    bad = []
                    pg.on('pageerror', lambda e: bad.append(str(e)))
                    pg.on('response', lambda r: bad.append((r.status, r.url)) if r.status >= 400 and '/git/file' not in r.url and '/lsp/' not in r.url else None)
                    await pg.goto(f'http://127.0.0.1:{port}/', wait_until='networkidle')
                    await pg.wait_for_function('window.lee && lee.keys.length')
                    await pg.evaluate("leeRight('agent')")
                    await pg.locator('#agentprompt').wait_for()
                    await scenario(pg, ws, port, bad, be)
                finally: await browser.close()
        finally:
            srv.should_exit = True; ws.shutdown_now(); restore()
    asyncio.run(go())


async def _open(pg, path, sel='.abh main'):
    await pg.evaluate('p => leeLearnOpen(p)', path)
    await pg.locator(sel).first.wait_for(timeout=30000)
    await pg.wait_for_load_state('networkidle'); await pg.wait_for_timeout(900)


async def _shot(pg, name):
    for mode in ('light', 'dark'):
        await pg.evaluate(f"applyTheme('leela:{mode}:relaxed')"); await pg.wait_for_timeout(500)
        await pg.screenshot(path=f'{OUT}/{name}-{mode}.png', full_page=False)
    await pg.evaluate("applyTheme('leela:light:relaxed')")


def test_palette_opens_home_with_continue_courses_keys_and_start(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, cid = _env(monkeypatch)
    async def scenario(pg, ws, port, bad, be):
        await pg.evaluate("applyTheme('leela:light:relaxed')")
        before = await pg.evaluate(SHELL)
        await pg.evaluate("palette()")
        await pg.locator('#cp').fill('Learn: Home')
        await pg.locator('.lee-mrow', has_text='Learn: Home').first.click()
        await pg.locator('.abh main h1', has_text='Home').wait_for(timeout=30000)
        await pg.wait_for_load_state('networkidle'); await pg.wait_for_timeout(1200)
        abh = pg.locator('.abh')
        assert ws.tab.kind == 'learn' and ws.tab.page == '/'
        assert await abh.locator('[data-part=continue-card] a.btn.go').count() == 1
        assert await abh.locator('.review-line').inner_text() and await abh.locator('[data-part=walks] .jrow').count() == 2
        assert await abh.locator('#start-form #start-q').count() == 1
        assert await pg.locator('#modebar [data-learn-keys]').is_visible() and await abh.locator('#kf, #kf-panel').count() == 0
        w, full = await pg.evaluate(MAIN)
        assert w <= 740 and full > 900, (w, full)
        await _shot(pg, 'p3-today')
        assert await pg.evaluate(SHELL) == before
        await pg.locator('#modebar [data-learn-keys]').click()
        help_ = pg.locator('.lee-help'); await help_.wait_for(timeout=5000)
        assert await help_.locator('h4', has_text='Learn').count() == 1 and await abh.locator('#kf').count() == 0
        await pg.screenshot(path=f'{OUT}/p3-today-keys-light.png')
        await pg.keyboard.press('Escape'); await help_.wait_for(state='detached', timeout=5000)
        await abh.evaluate("el => el.scrollTo(0, el.scrollHeight)")
        await pg.wait_for_timeout(300)
        assert await pg.locator('#modebar [data-learn-keys]').is_visible() and not await abh.locator('#kf-pill').is_visible()
        await pg.screenshot(path=f'{OUT}/p3-today-low-light.png')
        assert not bad, bad
    _run(tmp_path, scenario)


def test_start_box_makes_a_walk_through_the_leela_model_path(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, cid = _env(monkeypatch)
    async def scenario(pg, ws, port, bad, be):
        await _open(pg, '/')
        n = len(be.asked)
        await pg.locator('.abh #start-q').fill('how attention works')
        await pg.locator('.abh #start-read button.go').click(timeout=15000)
        await pg.wait_for_function('n => window.__asked > n', arg=n, timeout=1) if False else None
        for _ in range(60):
            if len(be.asked) > n: break
            await pg.wait_for_timeout(250)
        assert len(be.asked) > n
        assert not await pg.locator('script[src*="build"]').count()
    _run(tmp_path, scenario)


def test_concept_page_dont_get_this_goes_to_the_agent_pane(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, cid = _env(monkeypatch)
    async def scenario(pg, ws, port, bad, be):
        await pg.evaluate("applyTheme('leela:light:relaxed')")
        await _open(pg, '/c/softmax', '.abh #concept-name')
        abh = pg.locator('.abh')
        assert await abh.locator('.depth i').count() == 5 and await abh.locator('.depth i:not(:empty), .depth i[class]:not([class=""])').count() >= 1
        assert await abh.locator('text=Your attempts').count() and await abh.locator('details', has_text='earlier answer').count()
        assert await abh.locator('text=In your walks').count() and await abh.locator('text=Source').count()
        w, full = await pg.evaluate(MAIN)
        assert w <= 740, w
        await _shot(pg, 'p4-concept')
        assert not await pg.evaluate('() => !!document.querySelector("#kf-panel") && !document.querySelector("#kf-panel").hidden')
        assert not await pg.evaluate('() => lee.agentLearnMode')
        await abh.locator('button.rh-page').click()
        await pg.wait_for_function('() => lee.agentLearnMode === true', timeout=15000)
        await pg.locator('#agentlog, .lee-turn, .turn', has_text="I don't get this idea: Softmax").first.wait_for(timeout=15000)
        assert await abh.locator('#rh-offer .rh-way').count() == 0
        assert await pg.locator('#agentprompt').input_value() == ''
        await pg.wait_for_timeout(1500)
        assert not bad, bad
    _run(tmp_path, scenario)


def test_course_page(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, cid = _env(monkeypatch)
    async def scenario(pg, ws, port, bad, be):
        await _open(pg, f'/course/{cid}', '.abh .course-card')
        abh = pg.locator('.abh')
        assert await abh.locator('.course-card a.btn.go').count() == 1 and await abh.locator('text=Stages').count()
        assert (await pg.evaluate(MAIN))[0] <= 740
        await _shot(pg, 'p4-course')
        assert not bad, bad
    _run(tmp_path, scenario)
