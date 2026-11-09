"Stuck in a notebook, learn without losing your place: Explain a failing cell, Learn about a selection, and open a lesson back in Code."
import asyncio, json
from pathlib import Path

import pytest

from tests.test_learn_tab_pages_slow import GRADE, OUT, _env

pytestmark = pytest.mark.slow

IDLE = "() => !document.querySelector('.abh[aria-busy]')"
SAID = "() => document.querySelector('#agentlog').innerText"
NB = {'cells': [
    {'cell_type': 'code', 'id': 'c1', 'metadata': {}, 'execution_count': 1, 'source': 'x = 1', 'outputs': []},
    {'cell_type': 'code', 'id': 'c2', 'metadata': {}, 'execution_count': 2, 'source': 'y = 1/0',
     'outputs': [{'output_type': 'error', 'ename': 'ZeroDivisionError', 'evalue': 'division by zero', 'traceback': ['ZeroDivisionError: division by zero']}]}],
    'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}


def _run(tmp_path, scenario):
    from playwright.async_api import async_playwright
    from ramabana.core import ModelSpec
    from leela.workspace import Workspace
    from tests.fakemodel import Step, install
    from tests.test_web_slow import _free_port, _launch, _serve, _started, fake_kernels
    nb = tmp_path/'broken.ipynb'; nb.write_text(json.dumps(NB))
    async def go():
        restore = fake_kernels(); ws = Workspace(roots=[tmp_path.resolve()]); ws.open(nb)
        be = install(ws, [Step('It divides by zero.')], spec=ModelSpec('grade-hosted', 'remote', 'scripted/model', ctx=128_000))
        be.supports_deadline = True
        be.contexts, runner = [], ws.threads.active.runner
        start = runner.start
        runner.start = lambda q, att, reasoning, context, path, grounding: be.contexts.append(context) or start(q, att, reasoning, context, path, grounding)
        be._oneshot = lambda prompt, sp, max_tokens, deadline=None: GRADE
        port = _free_port(); srv = _serve(ws, port); await _started(srv)
        try:
            async with async_playwright() as pw:
                browser = await _launch(pw)
                try:
                    pg = await browser.new_page(viewport=dict(width=1500, height=900))
                    await pg.goto(f'http://127.0.0.1:{port}/', wait_until='networkidle')
                    await pg.wait_for_function('window.lee && lee.keys.length && lee.cells.length')
                    await pg.evaluate("leeRight('agent')")
                    await pg.locator('#agentprompt').wait_for()
                    await scenario(pg, ws, be, port)
                finally: await browser.close()
        finally:
            srv.should_exit = True; ws.shutdown_now(); restore()
    asyncio.run(go())


async def _shot(pg, name):
    for mode in ('light', 'dark'):
        await pg.evaluate("m => { document.documentElement.dataset.mode = m; }", mode)
        await pg.screenshot(path=f'{OUT}/m3-{name}-{mode}.png')
    await pg.evaluate("() => { document.documentElement.dataset.mode = 'light'; }")


def test_explain_sends_the_failing_cell_to_the_agent_in_code_mode(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, be, port):
        reports, turns = [], []
        pg.on('request', lambda r: reports.append(r.post_data) if r.url.endswith('/nb/cell') else turns.append(json.loads(r.post_data)) if r.url.endswith('/agent/turn') else None)
        await pg.locator('.lee-cell[data-id="c1"] .cm-content').click()
        await pg.wait_for_function("() => true"); await pg.wait_for_timeout(800)
        assert json.loads(reports[-1]) == {'cell': 'c1'} and ws.tab.cell == 'c1'
        await pg.locator('.lee-cell[data-id="c2"] [data-explain]').scroll_into_view_if_needed()
        await _shot(pg, 'explain')
        await pg.locator('.lee-cell[data-id="c2"] [data-explain]').click()
        await pg.wait_for_function("() => document.querySelector('#agentlog').innerText.includes('Explain what this cell does')", timeout=20000)
        assert turns[-1]['cell'] == 'c2' and turns[-1]['prompt'].startswith('Explain what this cell does')
        assert ws.tab.cell == 'c2'
        await pg.wait_for_function("() => !lee.agentBusy", timeout=30000)
        assert any('ZeroDivisionError: division by zero' in m and '<active-cell id="c2"' in m for m in be.contexts), be.contexts
    _run(tmp_path, scenario)


def test_explain_waits_for_a_busy_agent_or_a_draft(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, be, port):
        await pg.locator('#agentprompt').fill('my draft')
        await pg.evaluate("leeExplainCell('c2')")
        await pg.wait_for_function("() => /Send or clear your message/.test(document.body.innerText)", timeout=5000)
        assert await pg.locator('#agentprompt').input_value() == 'my draft' and not be.sent
        await pg.locator('#agentprompt').fill('')
        await pg.evaluate('lee.agentBusy = true')
        await pg.evaluate("leeExplainCell('c2')")
        await pg.wait_for_function("() => /The agent is working/.test(document.body.innerText)", timeout=5000)
        assert not be.sent and await pg.locator('#agentprompt').input_value() == ''
        await pg.evaluate('lee.agentBusy = false')
    _run(tmp_path, scenario)


def test_the_palette_and_the_cell_menu_offer_both(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, be, port):
        await pg.evaluate('palette()')
        await pg.locator('#cp').fill('explain this')
        assert 'Explain this cell' in await pg.locator('#cplist').inner_text()
        await pg.locator('#cp').fill('learn about')
        assert 'Learn about this' in await pg.locator('#cplist').inner_text()
        await pg.keyboard.press('Escape')
        menus = await pg.evaluate("() => JSON.stringify(lee.menus?.cell || [])")
        assert 'explain_cell' in menus and 'learn_about' in menus
    _run(tmp_path, scenario)


def test_learn_about_this_switches_mode_and_fills_the_prompt_without_sending(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, be, port):
        await pg.evaluate("() => { const v = lee.editors.get('c2'); v.focus(); v.dispatch({selection: {anchor: 4, head: 7}}); }")
        await pg.evaluate("leeAct('learn_about')")
        await pg.wait_for_function("lee.mode === 'learn'", timeout=20000)
        await pg.wait_for_function("() => document.querySelector('#agentprompt').value.startsWith('Teach me about')", timeout=10000)
        box = pg.locator('#agentprompt')
        assert await box.input_value() == 'Teach me about 1/0'
        assert await box.evaluate('e => [e.selectionStart, e.selectionEnd, document.activeElement === e]') == [18, 18, True]
        assert ws.mode == 'learn' and not be.sent and 'Teach me about' not in await pg.evaluate(SAID) and not await pg.locator('#agentlog .lee-agent-turn').count()
        assert await pg.evaluate("document.querySelector('#shell').classList.contains('no-left')")
        await _shot(pg, 'learn-about')
        # a draft is kept: the line goes under it, and the person is told
        await pg.evaluate("leeModeSet('code')")
        await pg.wait_for_function("lee.mode === 'code'", timeout=20000)
        await box.fill('my own draft')
        await pg.evaluate("leeLearnAbout('ZeroDivisionError: division by zero')")
        await pg.wait_for_function("lee.mode === 'learn'", timeout=20000)
        await pg.wait_for_function("() => /Nothing was sent/.test(document.body.innerText)", timeout=5000)
        assert await box.input_value() == 'my own draft\nTeach me about ZeroDivisionError: division by zero' and not be.sent
    _run(tmp_path, scenario)


def test_open_in_a_notebook_from_a_concept_step_returns_to_code(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch)
    import abhyasa.core.leela as AL
    here = {}
    monkeypatch.setattr(AL, 'leela_base', lambda: here.get('url'))
    from leela.blocks.learn import app as LA
    monkeypatch.setattr(LA, 'learning_store', lambda memory: lr.vault)
    async def scenario(pg, ws, be, port):
        here['url'] = f'http://127.0.0.1:{port}'
        await pg.evaluate("leeModeSet('learn')")
        await pg.wait_for_function("lee.mode === 'learn'", timeout=20000)
        ws.open_walk('workspace', jid); ws.save(); await pg.evaluate('mountTab()')
        await pg.locator('.abh #check .check').wait_for(timeout=30000)
        await pg.wait_for_function(IDLE, timeout=30000)
        from abhyasa.core.leela import leela_line
        from fasthtml.common import to_xml
        html = to_xml(leela_line(lr.journey(jid), 0))
        await pg.evaluate("h => document.querySelector('.abh main').insertAdjacentHTML('beforeend', h)", html)
        pages, before = [], len(ws.tabs)
        pg.context.on('page', lambda p: pages.append(p))
        await _shot(pg, 'concept')
        await pg.locator('.abh .leela-line a').click()
        await pg.wait_for_function("() => lee.mode === 'code' && lee.path && !lee.path.endsWith('broken.ipynb') && !!document.querySelector('.lee-cell')", timeout=30000)
        assert ws.mode == 'code' and ws.tab.kind == 'notebook' and Path(ws.tab.path).name != 'broken.ipynb' and len(ws.tabs) > before, [t.path for t in ws.tabs]
        assert await pg.evaluate('lee.path') == ws.tab.path
        assert not pages, 'no new browser tab'
        assert not await pg.evaluate("document.querySelector('#shell').classList.contains('no-left')")
        await _shot(pg, 'back-in-code')
    _run(tmp_path, scenario)
