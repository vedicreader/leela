"The run button on a shell block in an agent reply, driven in a browser."

import pytest

pytestmark = pytest.mark.slow
pytest.importorskip('playwright.async_api')

from tests.test_web_slow import _run   # noqa: E402

REPLY = r'''([md, where]) => { const r = document.createElement('div'); r.className = 'lee-reply'; r.id = where;
  (where === 'inlog' ? document.querySelector('#agentlog') : document.body).appendChild(r); renderMarkdown(r, md); }'''


def test_a_shell_block_in_an_agent_reply_runs_and_stops(tmp_path):
    "Run shows the output and exit state under the block, stop ends a long run, and a reply outside the agent log gets no button."
    async def go(pg):
        await pg.evaluate(REPLY, ['```bash\necho hi; exit 3\n```\n\n```sh\nsleep 30\n```\n\n```python\nprint(1)\n```', 'inlog'])
        await pg.evaluate(REPLY, ['```bash\necho elsewhere\n```', 'outside'])
        await pg.wait_for_selector('#inlog .lee-code-surface >> nth=2', state='attached')   # the agent pane starts closed
        await pg.wait_for_selector('#outside .lee-code-surface', state='attached')
        runs = pg.locator('#inlog [data-shell-run]')
        counts = await runs.count(), await pg.locator('#outside [data-shell-run]').count()
        await runs.nth(0).dispatch_event('click')
        await pg.wait_for_function("document.querySelector('#inlog .lee-code-run')?.textContent.includes('exit 3')")
        first = await pg.locator('#inlog .lee-code-run').nth(0).text_content()
        await runs.nth(1).dispatch_event('click')
        await pg.wait_for_function("document.querySelectorAll('#inlog [data-shell-run]')[1].textContent === 'stop'")
        await runs.nth(1).dispatch_event('click')
        await pg.wait_for_function("document.querySelectorAll('#inlog .lee-code-run')[1]?.textContent.includes('stopped')")
        return counts, first, await runs.nth(1).text_content()
    counts, first, label = _run(go, roots=[tmp_path])
    assert counts == (2, 0), 'bash and sh in the agent log; not python, not outside it'
    assert first.split() == ['hi', 'exit', '3'] and label == 'run'


def test_a_background_result_folds_from_its_header(tmp_path):
    "A delegation that lands between turns is a disclosure: open on arrival, and its header folds the report away."
    async def go(pg):
        await pg.evaluate("() => backgroundCard(null, {id: 'run_8b2dae555865', state: 'completed', question: 'q', answer: 'long report'})")
        card = pg.locator('#agentlog .lee-agent-background')
        before = await card.evaluate('el => [el.tagName, el.open, el.querySelector(":scope > summary").textContent]')
        await card.locator('summary').dispatch_event('click')
        after = await card.evaluate('el => [el.open, !!el.querySelector(":scope > pre")]')
        return before, after
    before, after = _run(go, roots=[tmp_path])
    assert before[1] is True and after[0] is False
