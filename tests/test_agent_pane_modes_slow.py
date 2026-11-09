import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.isolate import isolate

isolate()
pytestmark = pytest.mark.slow

OUT = str(Path(__file__).resolve().parents[1]/'target')
WRAPPED = ('<notebook path="a.ipynb">\ncell\n</notebook>\n\n<user-request>\nWhat is a fraction?\n</user-request>\n\n'
           '<system-reminder>\nTHIS IDEA IS ONE IDEA WITH ONE CLEAR POINT.\n</system-reminder>')


def test_the_display_text_is_the_persons_words_and_the_stored_turn_is_unchanged():
    from leela.blocks.agent.turns import shown_prompt, with_capabilities
    ai = SimpleNamespace(turn_capabilities=lambda tid: {'files': []})
    stored = [{'turn_id': 't1', 'prompt': WRAPPED}, {'turn_id': 't2', 'prompt': 'plain words'}]
    out = with_capabilities(ai, stored)
    assert [t['prompt'] for t in out] == ['What is a fraction?', 'plain words']
    assert stored[0]['prompt'] == WRAPPED
    assert shown_prompt('<user-request>\nIs it? \n</user-request>') == 'Is it?'
    assert shown_prompt(None) is None


async def _mode(pg, mode):
    await pg.evaluate("""async m => { const r = await api('/agent/threads'); const id = lee.agentThread || r.active;
      const d = await post('/agent/learn-mode', {on: m === 'learn', thread: id}); await refreshAgentThreads(); window.__mode = d; }""", mode)
    await pg.wait_for_function(f"document.querySelector('#agentmode')?.dataset.mode === '{mode}'")


async def _shot(pg, name):
    for theme in ('light', 'dark'):
        await pg.evaluate(f"applyTheme('leela:{theme}:relaxed')"); await pg.wait_for_timeout(400)
        await pg.screenshot(path=f'{OUT}/m2b-{name}-{theme}.png')
    await pg.evaluate("applyTheme('leela:light:relaxed')")


def _run(tmp_path, scenario):
    from playwright.async_api import async_playwright
    from leela.workspace import Workspace
    from tests.test_web_slow import _free_port, _launch, _serve, _started, fake_kernels
    f = tmp_path/'a.py'; f.write_text('x = 1\n')
    async def go():
        restore = fake_kernels(); ws = Workspace(roots=[tmp_path.resolve()]); ws.open(f)
        port = _free_port(); srv = _serve(ws, port); await _started(srv)
        try:
            async with async_playwright() as pw:
                browser = await _launch(pw)
                try:
                    pg = await browser.new_page(viewport=dict(width=1400, height=900))
                    bad = []
                    pg.on('pageerror', lambda e: bad.append(str(e)))
                    await pg.goto(f'http://127.0.0.1:{port}/', wait_until='networkidle')
                    try: await pg.wait_for_function('window.lee && lee.keys.length')
                    except Exception as e: raise AssertionError(bad) from e
                    await pg.evaluate("leeRight('agent')")
                    await pg.locator('#agentprompt').wait_for()
                    await scenario(pg)
                    assert not bad, bad
                finally: await browser.close()
        finally:
            srv.should_exit = True; ws.shutdown_now(); restore()
    asyncio.run(go())


def test_mode_label_starters_and_hidden_chrome(tmp_path):
    pytest.importorskip('playwright.async_api')
    async def scenario(pg):
        assert await pg.locator('#agentmode').inner_text() == 'Code'
        assert await pg.locator('#agentlearn:visible').count() == 0
        await _shot(pg, 'code-empty')
        await _mode(pg, 'learn')
        assert await pg.locator('#agentmode').inner_text() == 'Learn'
        assert await pg.locator('.lee-agent-welcome:visible [data-setup]').count() == 0
        starters = pg.locator('.lee-agent-starters button')
        assert await starters.all_inner_texts() == ['Teach me something new', 'Explain what is on my screen', 'Quiz me on what I learned today']
        await starters.nth(1).click()
        assert await pg.locator('#agentprompt').input_value() == 'Explain what is on my screen'
        assert await pg.evaluate("document.querySelectorAll('.lee-agent-turn').length") == 0
        await _shot(pg, 'learn-empty')
        turns = [dict(turn_id='s:1', prompt='What is a fraction?', reply='A part of a whole.', model='m', capabilities=dict(files=[], revisable=True, undoable=False, branchable=True, known=True)),
                 dict(turn_id='s:2', prompt='Fix a.py', reply='Done.', model='m', capabilities=dict(files=['a.py'], revisable=True, undoable=True, branchable=True, known=True))]
        await pg.evaluate('t => { const log = document.querySelector("#agentlog"); renderTurns(log, t, "", false); }', turns)
        bars = pg.locator('.lee-response-revision')
        assert await bars.count() == 2
        assert await bars.nth(0).locator('[data-revise], [data-undo]').count() == 0
        assert await bars.nth(0).inner_text() and 'Restore files' not in await bars.nth(0).inner_text()
        assert await bars.nth(1).locator('[data-revise]').count() == 1 and await bars.nth(1).locator('[data-undo]').count() == 1
        assert await pg.locator('.lee-agent-starters:visible').count() == 0
        await _shot(pg, 'learn-turns')
        await _mode(pg, 'code')
        assert await pg.locator('#agentmode').inner_text() == 'Code'
        assert await pg.locator('.lee-agent-starters').count() == 0
    _run(tmp_path, scenario)


def test_live_and_resumed_user_turns_show_only_the_persons_words(tmp_path):
    pytest.importorskip('playwright.async_api')
    async def scenario(pg):
        got = await pg.evaluate("""w => { const log = document.querySelector('#agentlog');
          renderTurns(log, [{turn_id: 's:9', prompt: w, reply: 'ok', model: 'm', capabilities: {files: []}}], '', false);
          const live = userMessage(w); log.appendChild(live);
          return [...log.querySelectorAll('.lee-user-message-body')].map(e => e.textContent) }""", WRAPPED)
        assert got and all(g == 'What is a fraction?' for g in got) and len(got) == 2
        text = await pg.locator('#agentlog').inner_text()
        assert 'user-request' not in text and 'THIS IDEA' not in text
        await _shot(pg, 'user-turn')
    _run(tmp_path, scenario)
