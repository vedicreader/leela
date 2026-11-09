"First touch of scrub and trace: a hint under the cell, an old result marked at once, and a Trace button on the cell that starts at step 1 and plays."
import asyncio, json
from pathlib import Path
import pytest

pytestmark = pytest.mark.slow

pytest.importorskip('playwright.async_api')

from test_completion_caret_slow import _real_page   # noqa: E402
from test_scrub_slow import _nb, _open, _drag, _release, OUT, DOC   # noqa: E402

SHOTS = Path(__file__).resolve().parent.parent/'target'

def test_a_number_that_changes_with_live_off_marks_the_output_old_until_the_next_run(tmp_path):
    nb = tmp_path/'n.ipynb'; _nb(nb, 'x = 3\nprint(x*2)', live=False)
    async def go(pg):
        await _open(pg, nb)
        await pg.evaluate("() => { try { localStorage.removeItem('lee-scrub-used'); } catch {} }")
        await pg.evaluate('runCell(0)'); await pg.wait_for_function("() => document.querySelector('#out-c1').innerText.trim() === '6'")
        await pg.evaluate("() => document.querySelector('#cm-c1 .cm-content').focus()")
        await pg.wait_for_selector('#tip-c1')
        tip = await pg.inner_text('#tip-c1'); SHOTS.mkdir(exist_ok=True)
        await pg.screenshot(path=str(SHOTS/'b2-scrub-hint.png'))
        await _drag(pg, 2, None); await pg.wait_for_timeout(400)
        await _release(pg)
        stale = await pg.evaluate("() => document.querySelector('#stale-c1')?.innerText"), await pg.evaluate(OUT), await pg.evaluate(DOC)
        await pg.screenshot(path=str(SHOTS/'b2-scrub-old.png'))
        gone_tip = await pg.evaluate("() => !document.querySelector('.lee-scrub-tip')")
        await pg.evaluate('runCell(0)'); await pg.wait_for_function("() => document.querySelector('#out-c1').innerText.trim() === '10'")
        return tip, stale, gone_tip, await pg.evaluate("() => !document.querySelector('#stale-c1')")
    tip, stale, gone_tip, cleared = asyncio.run(_real_page(go, tmp_path))
    assert tip.startswith(('Hold Option and drag the 3.', 'Hold Alt and drag the 3.')) and 'Live: off.' in tip and 'Turn on' in tip, tip
    assert stale == ('old: run again', '6', 'x = 5\nprint(x*2)'), stale
    assert gone_tip and cleared

def test_the_trace_button_on_the_cell_starts_at_step_one_and_play_walks_the_run(tmp_path):
    nb = tmp_path/'t.ipynb'; _nb(nb, 'a = 1\nb = a + 1\nc = b + 1', live=False)
    async def go(pg):
        await pg.set_viewport_size({'width': 1500, 'height': 900})
        await pg.evaluate(f'leeOpenFile({str(nb)!r})')
        await pg.wait_for_function("() => lee.cells && lee.cells.length && lee.editors.get('c1')")
        await pg.evaluate('() => { selectCell(0); leeRight("vars"); }')
        await pg.click('.lee-cell .lee-cbtn-trace')
        await pg.wait_for_selector('#trbar-c1', timeout=60000)
        first = await pg.inner_text('#trbar-c1 .lee-trpos')
        slider_in_pane = await pg.evaluate("() => !!document.querySelector('#tracebox input[type=range]')")
        await pg.click('#trbar-c1 [data-play]')
        await pg.wait_for_function("() => lee.trace.step >= 2", timeout=10000)
        await pg.wait_for_function("() => document.querySelector('#trbar-c1 [data-play]').textContent === 'Play'", timeout=5000)
        pane = await pg.inner_text('#tracepos')
        await pg.screenshot(path=str(SHOTS/'b2-trace-cell.png'))
        return first, slider_in_pane, pane
    first, slider, pane = asyncio.run(_real_page(go, tmp_path))
    assert first.startswith('step 1 of') and not slider and pane.split(' / ')[0].isdigit(), (first, slider, pane)
