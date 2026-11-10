"A live cell in a Learn step: edit, run, see the output change, stop an endless loop, and a check that moves the gauge. Real browser, real kernel."
import asyncio, sys
from pathlib import Path

import pytest

from tools.isolate import isolate

isolate()
pytestmark = pytest.mark.slow

OUT = str(Path(__file__).resolve().parents[1]/'target')
CODE = dict(src='# Make x 4, then run\nx = 3\nprint(x * 2)', watch=['x'], expect=dict(var='x', value='4'))


def _env(monkeypatch):
    from talk_data import talk_walk
    from abhyasa.learner import temp_learning
    from abhyasa.path import check_code
    from leela.blocks.learn import host
    lr = temp_learning()
    jid = talk_walk(lr)
    for st in lr.journey(jid).steps:
        lr.update(st['slug'], core=st.get('statement') or 'A fact.')
        lr.walk_slug(jid, st['slug'], note_none=True)
    lr.walk_slug(jid, lr.journey(jid).steps[0]['slug'], code=check_code(CODE), note='x is a name for a number.')
    monkeypatch.setattr(host, 'learn_store', lambda ws, vault=None, write=False: ('test', lr))
    monkeypatch.setattr(host, 'HOSTS', ('127.0.0.1', 'localhost', '::1'))
    return lr, jid


def _run(tmp_path, scenario):
    from playwright.async_api import async_playwright
    from leela.workspace import Workspace
    from tests.fakemodel import install
    from tests.test_web_slow import _free_port, _launch, _serve, _started
    lesson = tmp_path/'lesson.py'; lesson.write_text('answer = 42\n')
    async def go():
        ws = Workspace(roots=[tmp_path.resolve()]); ws.open(lesson)
        install(ws, [])
        port = _free_port(); srv = _serve(ws, port); await _started(srv)
        try:
            async with async_playwright() as pw:
                browser = await _launch(pw)
                try:
                    pg = await browser.new_page(viewport=dict(width=1400, height=900))
                    bad = []
                    pg.on('pageerror', lambda e: bad.append(str(e)))
                    await pg.goto(f'http://127.0.0.1:{port}/', wait_until='networkidle')
                    await pg.wait_for_function('window.lee && lee.keys.length', timeout=60000)
                    await scenario(pg, ws, port, bad)
                finally: await browser.close()
        finally:
            srv.should_exit = True; ws.shutdown_now()
    asyncio.run(go())


async def _type(pg, lines):
    "Replace the code of the first cell with `lines`."
    ed = pg.locator('.abh .lee-livecell .lv-ed .cm-content, .abh .lee-livecell .lv-ta').first
    await ed.click(); await pg.keyboard.press('ControlOrMeta+A'); await pg.keyboard.press('Backspace')
    for k, l in enumerate(lines):
        if k: await pg.keyboard.press('Enter')
        await pg.keyboard.type(l)


async def _shot(pg, name):
    for mode in ('light', 'dark'):
        await pg.evaluate(f"applyTheme('leela:{mode}:relaxed')"); await pg.wait_for_timeout(400)
        await pg.screenshot(path=f'{OUT}/bve-{name}-{mode}.png')
    await pg.evaluate("applyTheme('leela:light:relaxed')")


async def _out(pg, text, secs=30):
    try: await pg.wait_for_function('t => document.querySelector(".abh .lv-out")?.textContent.includes(t)', arg=text, timeout=secs*1000)
    except Exception: raise AssertionError(f'no {text!r} in: ' + await pg.locator('.abh .lee-livecell').text_content())


def test_a_learner_edits_runs_and_checks_the_code_of_a_step(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid = _env(monkeypatch)
    slug = lr.journey(jid).steps[0]['slug']
    async def scenario(pg, ws, port, bad):
        await pg.evaluate("applyTheme('leela:light:relaxed')")
        ws.open_walk('workspace', jid); ws.save(); await pg.evaluate('mountTab()')
        await pg.evaluate('p => leeLearnOpen(p)', f'/w/{jid}/0')
        cell = pg.locator('.abh .lee-livecell.lv-on')
        await cell.wait_for(timeout=30000)
        assert 'This code runs on your computer.' in await cell.text_content()
        await _type(pg, ['x = 3', 'print(x * 2)'])
        await cell.locator('.lv-run').click()
        await _out(pg, '6')
        assert await cell.locator('.lv-watch').text_content() == 'x3'
        await _type(pg, ['x = 4', 'print(x * 2)'])
        await pg.keyboard.press('ControlOrMeta+Enter')            # the chord stays inside the cell
        await _out(pg, '8')
        assert '6' not in await cell.locator('.lv-out').text_content() and await cell.locator('.lv-watch').text_content() == 'x4'
        await _shot(pg, 'live-cell')
        await _type(pg, ['while True:', 'pass'])
        await cell.locator('.lv-run').click()
        await _out(pg, 'stopped after 5 seconds', 40)
        await _shot(pg, 'live-cell-stopped')
        await _type(pg, ['y = x + 1', 'print(y)'])                 # the kernel goes on, and keeps x
        await cell.locator('.lv-run').click()
        await _out(pg, '5')
        await _type(pg, ['x = 3', 'print(x * 2)'])
        await cell.locator('.lv-run').click(); await _out(pg, '6')
        n = len(lr.attempts(slug, limit=None))
        await cell.locator('.lv-check').click()
        await pg.wait_for_function('() => /Not yet/.test(document.querySelector(".abh .lv-state").textContent)', timeout=15000)
        assert len(lr.attempts(slug, limit=None)) == n + 1 and not lr.attempts(slug, limit=1)[0].correct
        await _type(pg, ['x = 4', 'print(x * 2)'])
        await cell.locator('.lv-run').click(); await _out(pg, '8')
        await cell.locator('.lv-check').click()
        await pg.wait_for_function('() => /meets the check/.test(document.querySelector(".abh .lv-state").textContent)', timeout=15000)
        a = lr.attempts(slug, limit=1)[0]
        assert len(lr.attempts(slug, limit=None)) == n + 2 and a.correct and a.kind == 'code' and a.method == 'code'
        assert 'Your level on this idea' in await cell.locator('.lv-state').text_content()
        await _shot(pg, 'live-cell-checked')
        await cell.locator('.lv-reset').click()
        assert 'x = 3' in await pg.locator('.abh .lv-ed').text_content() and not (await cell.locator('.lv-out').text_content()).strip()
        assert not bad, bad
    _run(tmp_path, scenario)
