import asyncio, re, sys
from pathlib import Path

import pytest

from tools.isolate import isolate

isolate()
pytestmark = pytest.mark.slow

OUT = str(Path(__file__).resolve().parents[1]/'target')
GRADE = r'{"correct": false, "grade": 2, "feedback": "Look at positions.", "first_error": "You add raw scores.", "misconception": ""}'
SHELL = """() => { const css = s => { const x = getComputedStyle(document.querySelector(s)); return [x.fontFamily, x.fontSize, x.color, x.backgroundColor] }; return [css('body'), css('#agentprompt')] }"""


def _env(monkeypatch):
    sys.path.insert(0, str(Path(__import__('abhyasa').__file__).resolve().parents[1]/'tests'))
    from talk_data import talk_walk, TALK_RULES
    from abhyasa.learner import temp_learning
    from abhyasa.models import Fake
    from abhyasa.show import talk_from_walk
    from leela.blocks.learn import host
    lr = temp_learning()
    jid = talk_walk(lr)
    for st, q in zip(lr.journey(jid).steps, ('What does a rank tell you?', 'What does softmax give?', 'Why divide by the root of dk?')):
        lr.update(st['slug'], core=st.get('statement') or 'A fact.')
        if st['check'].get('kind') != 'demo': lr.walk_slug(jid, st['slug'], note_none=True, check={**st['check'], 'q': q})
    lr.walk_step(jid, 0, note='Softmax makes weights from scores. Look at what a large score does.')
    talk_from_walk(lr, Fake(TALK_RULES), jid)
    monkeypatch.setattr(host, 'learn_store', lambda ws, vault=None, write=False: ('test', lr))
    monkeypatch.setattr(host, 'HOSTS', ('127.0.0.1', 'localhost', '::1'))
    return lr, jid


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
        be.asked = []
        def one(prompt, sp, max_tokens, deadline=None):
            be.asked.append(prompt)
            if 'The learner asks' in prompt:
                slug = re.search(r'idea (\S+):', prompt)[1]
                return '{"changes": [{"op": "move", "idea": "%s", "to": 2, "why": "you asked"}]}' % slug
            return GRADE
        be._oneshot = one
        port = _free_port(); srv = _serve(ws, port); await _started(srv)
        try:
            async with async_playwright() as pw:
                browser = await _launch(pw)
                try:
                    pg = await browser.new_page(viewport=viewport or dict(width=1500, height=900))
                    bad = []
                    pg.on('pageerror', lambda e: bad.append(str(e)))
                    await pg.goto(f'http://127.0.0.1:{port}/', wait_until='networkidle')
                    await pg.wait_for_function('window.lee && lee.keys.length', timeout=60000)
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


async def _shot(pg, name, full=False):
    for mode in ('light', 'dark'):
        await pg.evaluate(f"applyTheme('leela:{mode}:relaxed')"); await pg.wait_for_timeout(500)
        await pg.screenshot(path=f'{OUT}/p2-{name}-{mode}.png', full_page=full)
    await pg.evaluate("applyTheme('leela:light:relaxed')")


def test_step_shows_source_note_talk_keys_and_feedback(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid = _env(monkeypatch)
    async def scenario(pg, ws, port, bad, be):
        await pg.evaluate("applyTheme('leela:light:relaxed')")
        before = await pg.evaluate(SHELL)
        ws.open_walk('workspace', jid); ws.save(); await pg.evaluate('mountTab()')
        await _open(pg, f'/w/{jid}/0', '.abh #check .check')
        abh = pg.locator('.abh')
        assert await abh.locator('.src-line .pill').text_content() == 'your source'
        assert 'section 1' in await abh.locator('.src-line').text_content()
        assert 'large score' in await abh.locator('.note').first.text_content()
        assert await abh.locator('#rail a', has_text='Open the talk').count() == 1
        await _shot(pg, 'step')
        await pg.evaluate("window.leeOpenVaultDoc = (...a) => { window.__vault = a }")
        pages = len(pg.context.pages)
        await abh.locator('.src-open').click()
        got = await pg.evaluate('window.__vault')
        assert got[1:3] == ['', 'learn'] and got[0] and len(pg.context.pages) == pages
        pill = pg.locator('#modebar [data-learn-keys]')
        await pill.wait_for(timeout=10000)
        await pill.click()
        assert await abh.locator('.kf-panel').is_visible()
        await pill.click()
        await abh.locator('#ans').fill('a recurrent model computes one position after another')
        await abh.locator('#send').click()
        await abh.locator('#check').get_by_text('Look at positions.').wait_for(timeout=30000)
        await pg.wait_for_timeout(700)
        assert 'tries left' in await abh.locator('#check').text_content()
        assert await abh.locator('#check').get_by_text('Teach me').count() == 1
        assert await abh.locator('#check').get_by_text('You add raw scores.').count() == 1
        assert lr.attempts()
        await _shot(pg, 'answered')
        await abh.get_by_text('Skip this idea').first.click()
        await pg.wait_for_function("() => !document.querySelector('.abh #check')", timeout=30000)
        await pg.wait_for_timeout(700)
        await pg.screenshot(path=f'{OUT}/p2-section-done-light.png')
        assert 'skipped' in await abh.text_content() or 'Next' in await abh.text_content()
        await _open(pg, f'/w/{jid}/1', '.abh #check .check')
        assert await abh.locator('#rail-0.on, #rail-0').count() == 1
        await pg.screenshot(path=f'{OUT}/p2-step1-light.png')
        await abh.locator('#rail a', has_text='Open the talk').evaluate('el => el.click()')
        await pg.wait_for_function("() => !document.querySelector('.abh #rail')", timeout=30000)
        await pg.wait_for_timeout(800)
        assert ws.tab.page.startswith('/t/'), ws.tab.page
        assert await pg.evaluate(SHELL) == before
        assert not bad, bad
    _run(tmp_path, scenario)


def test_overview_change_box_goes_through_the_host_and_plan_tools_work(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid = _env(monkeypatch)
    async def scenario(pg, ws, port, bad, be):
        await pg.evaluate("applyTheme('leela:light:relaxed')")
        before = await pg.evaluate(SHELL)
        ws.open_walk('workspace', jid); ws.save(); await pg.evaluate('mountTab()')
        await _open(pg, f'/w/{jid}')
        abh = pg.locator('.abh')
        assert await abh.locator('.grip').count() == 3
        assert await abh.get_by_text('Add a source').count() >= 1
        assert await abh.locator('a', has_text='as a talk').count() == 1
        await _shot(pg, 'overview')
        names = lambda: abh.locator('.edit-row').evaluate_all("rs => rs.map(r => r.querySelector('a')?.textContent)")
        first = (await names())[0]
        box = abh.locator('textarea').first
        reqs = []; pg.on('response', lambda r: reqs.append(r.url.split('/learn/abh')[1][:40]) if '/learn/abh/' in r.url else None)
        await box.fill('move the first idea to the end')
        asked = len(be.asked)
        await box.press('Enter')
        await abh.locator('[data-act=undo-change]').first.wait_for(timeout=30000)
        assert len(be.asked) > asked and any('The learner asks' in p for p in be.asked)
        assert (await names())[1] == first and any('/improv' in u for u in reqs) and '/events' in reqs, reqs
        await pg.screenshot(path=f'{OUT}/p2-undo-light.png')
        await abh.locator('[data-act=undo-change]').first.click()
        await pg.wait_for_timeout(1500)
        assert (await names())[0] == first
        grips = abh.locator('.grip')
        await grips.nth(0).scroll_into_view_if_needed(); await pg.wait_for_timeout(300)
        a, b = await grips.nth(1).bounding_box(), await grips.nth(0).bounding_box()
        order = await names()
        await pg.mouse.move(a['x'] + 4, a['y'] + 4); await pg.mouse.down()
        await pg.mouse.move(b['x'] + 4, b['y'] - 20, steps=12); await pg.mouse.up()
        await pg.wait_for_timeout(1500)
        assert await names() != order
        await abh.locator('summary', has_text='Earlier versions').click()
        await pg.wait_for_timeout(1500)
        await pg.screenshot(path=f'{OUT}/p2-history-light.png')
        await abh.locator('.edit-row summary').first.click()
        assert await abh.locator('.edit-row details[open]').count() == 1
        assert await pg.evaluate(SHELL) == before
        assert not bad, bad
    _run(tmp_path, scenario)
