import asyncio
from pathlib import Path

import pytest

from tools.isolate import isolate

isolate()
pytestmark = pytest.mark.slow

GRADE = r'{"correct": true, "grade": 10, "feedback": "Correct.", "first_error": "", "misconception": ""}'


def test_real_abhyasa_step_stays_inside_the_leela_tab(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    from abhyasa.agent_tools import create_walk
    from abhyasa.learner import temp_learning
    from playwright.async_api import async_playwright
    from ramabana.core import ModelSpec
    from leela.blocks.learn import host
    from leela.workspace import Workspace
    from tests.fakemodel import install
    from tests.test_web_slow import _free_port, _launch, _serve, _started, fake_kernels
    from tools.s2_native_pilot import PLAN

    lr = temp_learning()
    made = create_walk(lr, lambda p, sp='': PLAN, 'fractions', settings={})
    assert made['status'] == 'ok'
    jid = made['walk']
    for step, q in zip(lr.journey(jid).steps, ('What does a fraction name?', 'How do you add fractions?')):
        lr.update(step['slug'], core='A fraction names equal parts of a whole.')
        lr.walk_slug(jid, step['slug'], note_none=True, check={**step['check'], 'q': q})
    monkeypatch.setattr(host, 'learn_store', lambda ws, vault=None, write=False: ('test', lr))
    monkeypatch.setattr(host, 'HOSTS', ('127.0.0.1', 'localhost', '::1'))

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
                    pg = await browser.new_page(viewport=dict(width=1280, height=1000))
                    await pg.goto(f'http://127.0.0.1:{port}/', wait_until='networkidle')
                    await pg.wait_for_function('window.lee && lee.keys.length')
                    await pg.evaluate("leeRight('agent')")
                    await pg.locator('#agentprompt').wait_for()
                    shell_style = """() => {
                      const css = s => { const x = getComputedStyle(document.querySelector(s)); return [x.fontFamily, x.fontSize, x.color, x.backgroundColor] };
                      return [css('body'), css('.lee-tab'), css('#agentprompt')];
                    }"""
                    before = await pg.evaluate(shell_style)
                    href, history = await pg.evaluate('() => [location.href, window.history.length]')
                    ws.open_learn_walk('workspace', jid); ws.save(); await pg.evaluate('mountTab()')
                    check = pg.locator('.abh #check .check')
                    await check.wait_for(timeout=30000)
                    abh = pg.locator('.abh')
                    assert await pg.locator('.abh body > nav, .abh .crumbs, .abh .gear').count() == 0
                    assert await pg.locator('script[src*="htmx"]').count() == 1
                    assert not await pg.evaluate("() => !!document.activeElement?.closest('.abh')")
                    assert before == await pg.evaluate(shell_style)
                    assert [href, history] == await pg.evaluate('() => [location.href, window.history.length]')
                    Path('target').mkdir(exist_ok=True)
                    await pg.evaluate("applyTheme('leela:light:relaxed')")
                    await abh.screenshot(path='target/p0-step-light.png')
                    first = await pg.locator('.abh h1.idea').text_content()
                    shell = await abh.evaluate("el => [...el.parentElement.children].filter(x => x !== el).map(x => x.outerHTML)")
                    await pg.locator('.abh .outline a[href$="/1"]').evaluate('el => el.click()')
                    await pg.wait_for_function("old => document.querySelector('.abh h1.idea')?.textContent !== old", arg=first)
                    assert shell == await abh.evaluate("el => [...el.parentElement.children].filter(x => x !== el).map(x => x.outerHTML)")
                    assert [href, history] == await pg.evaluate('() => [location.href, window.history.length]')
                    await pg.locator('.abh a[href$="/0"]').first.evaluate('el => el.click()')
                    await pg.wait_for_function("old => document.querySelector('.abh h1.idea')?.textContent === old", arg=first)
                    await pg.evaluate("applyTheme('leela:dark:relaxed')")
                    await abh.screenshot(path='target/p0-step-dark.png')
                    assert await abh.evaluate("el => getComputedStyle(el).backgroundColor") == await pg.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--lee-bg').trim()")
                    await pg.evaluate("applyTheme('leela:light:relaxed')")
                    await pg.locator('.abh #ans').fill('A fraction names equal parts of a whole.')
                    await pg.locator('.abh #send').click()
                    await pg.locator('.abh #check').get_by_text('Correct.', exact=True).wait_for(timeout=30000)
                    assert lr.attempts()
                    await abh.screenshot(path='target/p0-answered-light.png')
                    await pg.evaluate("applyTheme('leela:dark:relaxed')")
                    await abh.screenshot(path='target/p0-answered-dark.png')
                    assert await abh.evaluate("el => getComputedStyle(el).backgroundColor") == await pg.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--lee-bg').trim()")
                    assert before == await pg.evaluate(shell_style)
                    assert [href, history] == await pg.evaluate('() => [location.href, window.history.length]')
                finally: await browser.close()
        finally:
            srv.should_exit = True; ws.shutdown_now(); restore()
    asyncio.run(go())
