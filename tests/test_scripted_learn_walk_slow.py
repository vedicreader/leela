r"""The scripted model in a real browser: a person who explores the preview walk never sees raw JSON or a failure line.

Learn mode on, 'teach me fractions' in the agent pane, then each button of the first step: a wrong answer, a right answer, Hint, Explain and I don't know."""
import asyncio, re
from pathlib import Path
import pytest

TOPIC = 'teach me fractions'
SHOTS = Path(__file__).resolve().parent.parent/'target'
BAD = ('{"', 'could not', 'Traceback', 'Try again')

async def _api(pg, method, url, body=None):
    return await pg.evaluate(r"""async ([m, u, b]) => {
      const r = await fetch(u, {method: m, headers: {'Content-Type': 'application/json', 'Accept': 'application/json'}, body: b === null ? undefined : JSON.stringify(b)});
      return {status: r.status};
    }""", [method, url, body])

async def _clean(pg, where):
    "The text of the walk page has no JSON, no failure line and no retry."
    t = await pg.inner_text('.abh')
    assert not [b for b in BAD if b in t], f'{where}: {t}'
    return t

@pytest.mark.slow
def test_every_button_of_the_first_step_answers_in_plain_words(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    from playwright.async_api import async_playwright
    from leela.workspace import Workspace
    from test_web_slow import fake_kernels, _free_port, _serve, _started, _launch
    from tools.scripted_learn import install_scripted
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'vault.db'))
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    SHOTS.mkdir(exist_ok=True)
    async def go():
        restore = fake_kernels()
        ws = Workspace(roots=[tmp_path.resolve()], approvals='auto')
        install_scripted(ws)
        port = _free_port(); srv = _serve(ws, port); await _started(srv)
        seen = {}
        try:
            async with async_playwright() as pw:
                b = await _launch(pw)
                try:
                    pg = await b.new_page(viewport=dict(width=1500, height=900))
                    await pg.goto(f'http://127.0.0.1:{port}/', wait_until='networkidle')
                    await pg.wait_for_function('window.lee && lee.keys.length')
                    assert (await _api(pg, 'POST', '/agent/learn-mode', {'on': True}))['status'] == 200
                    await pg.evaluate("() => leeRight('agent')")
                    await pg.fill('#agentprompt', TOPIC)
                    await pg.evaluate('() => sendAgent()')
                    await pg.wait_for_selector('.lee-tab[data-kind="learn"]', timeout=30000)
                    await pg.wait_for_selector('.abh #check .check', timeout=30000)
                    await pg.wait_for_function("() => document.querySelector('.abh #check .check')?.innerText.includes('?')", timeout=30000)
                    await pg.wait_for_timeout(1500)
                    seen['first'] = await _clean(pg, 'first step')
                    await pg.wait_for_timeout(800)
                    await pg.screenshot(path=str(SHOTS/'s1-note-check-light.png'))
                    await pg.locator('.abh #ans').fill('banana')
                    await pg.locator('.abh #send').click()
                    await pg.wait_for_function("() => /Teach me/.test(document.querySelector('.abh #check')?.innerText || '')", timeout=30000)
                    seen['wrong'] = await _clean(pg, 'wrong answer')
                    await pg.wait_for_timeout(1200)
                    await pg.screenshot(path=str(SHOTS/'s1-wrong-light.png'))
                    await pg.locator('.abh #hint').click()
                    await pg.wait_for_selector('.abh #check .hint', timeout=30000)
                    seen['hint'] = await _clean(pg, 'hint')
                    await pg.locator('.abh #idk').click()
                    await pg.wait_for_function("() => /Check:|1\\. /.test(document.querySelector('.abh')?.innerText || '')", timeout=30000)
                    await pg.wait_for_timeout(1200)
                    seen['teach'] = await _clean(pg, 'Teach me')
                    await pg.screenshot(path=str(SHOTS/'s1-explain-light.png'))
                    await pg.locator('.abh').get_by_text('Comparing fractions').first.click()
                    await pg.wait_for_function("() => /Two friends/.test(document.querySelector('.abh')?.innerText || '') && /1 of 8/.test(document.querySelector('.abh #check')?.innerText || '')", timeout=30000)
                    await pg.wait_for_timeout(1000)
                    await pg.locator('.abh #ans').fill('You eat more, because fourths are bigger than eighths')
                    await pg.locator('.abh #send').click()
                    await pg.wait_for_function("() => /Correct/i.test(document.querySelector('.abh #check')?.innerText || '')", timeout=30000)
                    await pg.wait_for_timeout(1200)
                    seen['right'] = await _clean(pg, 'right answer')
                    await pg.screenshot(path=str(SHOTS/'s1-right-light.png'))
                    await pg.locator('.abh').get_by_text('Adding fractions').first.click()
                    await pg.wait_for_function("() => /You eat 1 of 5/.test(document.querySelector('.abh')?.innerText || '') && /5 equal slices/.test(document.querySelector('.abh #check')?.innerText || '')", timeout=30000)
                    await pg.wait_for_timeout(1000)
                    await pg.locator('.abh #idk').click()
                    await pg.wait_for_function("() => /Check:|1\\. /.test(document.querySelector('.abh')?.innerText || '')", timeout=30000)
                    await pg.wait_for_timeout(800)
                    seen['idk'] = await _clean(pg, "I don't know")
                    seen['url'] = pg.url
                finally: await b.close()
        finally:
            srv.should_exit = True
            ws.shutdown_now()
            restore()
        return seen
    seen = asyncio.run(asyncio.wait_for(go(), 250))
    assert 'Teach me' in seen['wrong'] and 'Not yet' in seen['wrong'] and 'Error:' in seen['wrong'], seen['wrong']
    assert 'Correct' in seen['right'] and 'HINT' in seen['hint'].upper()
    assert 'THE TUTOR' in seen['first'].upper() and '?' in seen['first'], seen['first']
    assert 'Check' in seen['idk'] and 'Check' in seen['teach'], (seen['idk'], seen['teach'])


@pytest.mark.slow
def test_show_me_draws_a_demo_with_a_lock_in_button(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    from playwright.async_api import async_playwright
    from leela.workspace import Workspace
    from test_web_slow import fake_kernels, _free_port, _serve, _started, _launch
    from tools.scripted_learn import install_scripted
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'vault.db'))
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    SHOTS.mkdir(exist_ok=True)
    async def go():
        restore = fake_kernels()
        ws = Workspace(roots=[tmp_path.resolve()], approvals='auto')
        install_scripted(ws)
        port = _free_port(); srv = _serve(ws, port); await _started(srv)
        seen = {}
        try:
            async with async_playwright() as pw:
                b = await _launch(pw)
                try:
                    pg = await b.new_page(viewport=dict(width=1500, height=900))
                    await pg.goto(f'http://127.0.0.1:{port}/', wait_until='networkidle')
                    await pg.wait_for_function('window.lee && lee.keys.length')
                    assert (await _api(pg, 'POST', '/agent/learn-mode', {'on': True}))['status'] == 200
                    await pg.evaluate("() => leeRight('agent')")
                    await pg.fill('#agentprompt', TOPIC)
                    await pg.evaluate('() => sendAgent()')
                    await pg.wait_for_selector('.abh #check .check', timeout=30000)
                    await pg.wait_for_function("() => /Cut a pizza/.test(document.querySelector('.abh')?.innerText || '')", timeout=30000)
                    await pg.wait_for_timeout(1000)
                    await pg.locator('.abh').get_by_role('button', name=re.compile('^Show me')).first.click()
                    await pg.wait_for_function("() => [...document.querySelectorAll('.abh button, .abh [data-rupaka] button')].some(b => /Lock in/i.test(b.innerText))", timeout=60000)
                    await pg.wait_for_timeout(1200)
                    seen['page'] = await _clean(pg, 'demo')
                    await pg.screenshot(path=str(SHOTS/'s1-demo-light.png'))
                    await pg.evaluate("applyTheme('leela:dark:relaxed')")
                    await pg.wait_for_timeout(800)
                    await pg.screenshot(path=str(SHOTS/'s1-demo-dark.png'))
                    await pg.locator('.abh').get_by_text('Show it in 3D').first.click()
                    await pg.wait_for_function("() => document.querySelector('.abh canvas') || /Equal parts in 3D|One whole|3D explainer/.test(document.querySelector('.abh')?.innerText || '')", timeout=60000)
                    await pg.wait_for_timeout(1500)
                    seen['scene'] = await _clean(pg, '3D explainer')
                    await pg.screenshot(path=str(SHOTS/'s1-explainer-dark.png'))
                finally: await b.close()
        finally:
            srv.should_exit = True
            ws.shutdown_now()
            restore()
        return seen
    seen = asyncio.run(asyncio.wait_for(go(), 250))
    assert 'could not make' not in seen['scene'].lower()
    assert 'Lock in' in seen['page'] and 'equal parts' in seen['page'].lower(), seen['page']
