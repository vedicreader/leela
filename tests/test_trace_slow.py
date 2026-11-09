"The run trace in a real window: columns per pass, the scrub slider, and the ghost of the last run."
import asyncio, json
from pathlib import Path
import pytest

pytestmark = pytest.mark.slow

pytest.importorskip('playwright.async_api')

from test_completion_caret_slow import _real_page   # noqa: E402

BS = """def bsearch(a, x):
    low, high = 0, len(a) - 1
    while low <= high:
        mid = (low + high) // 2
        if a[mid] < x: low = mid + 1
        elif a[mid] > x: high = mid - 1
        else: return mid
    return -1
bsearch([1, 3, 5, 7, 9, 11], 7)"""
SHOTS = Path(__file__).resolve().parent.parent/'target'

def test_tracing_a_binary_search_shows_a_column_per_pass_and_scrubs(tmp_path):
    """The pane listed names after a run but never what each line did on each pass; now the pane keeps the numbers and the editor the columns."""
    p = tmp_path/'bs.ipynb'
    cell = {'cell_type': 'code', 'id': 'c1', 'metadata': {}, 'execution_count': None, 'outputs': [], 'source': BS}
    p.write_text(json.dumps({'cells': [cell], 'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    SHOTS.mkdir(exist_ok=True)
    async def go(pg):
        out = {}
        await pg.set_viewport_size({'width': 1500, 'height': 900})
        await pg.evaluate(f'leeOpenFile({str(p)!r})')
        await pg.wait_for_function("() => lee.cells && lee.cells.length && lee.editors.get('c1')")
        await pg.evaluate('() => { selectCell(0); leeRight("vars"); }')
        await pg.click('#tracebtn')
        await pg.click('#tracerun')
        await pg.wait_for_selector('.cm-line .lee-lens', timeout=60000)
        out['mids'] = await pg.evaluate("() => [...document.querySelectorAll('.cm-line')].find(l => l.textContent.includes('mid = (low')).querySelectorAll('.lee-lc').length && [...[...document.querySelectorAll('.cm-line')].find(l => l.textContent.includes('mid = (low')).querySelectorAll('.lee-lc')].map(e => e.textContent)")
        out['note'] = await pg.inner_text('#tracenote')
        out['output'] = await pg.evaluate("() => JSON.stringify(lee.cells[0].outputs)")
        await pg.evaluate("() => document.documentElement.dataset.mode = 'dark'")
        await pg.screenshot(path=str(SHOTS/'bvc-trace-dark.png'))
        await pg.evaluate("() => document.documentElement.dataset.mode = 'light'")
        await pg.screenshot(path=str(SHOTS/'bvc-trace-light.png'))
        await pg.evaluate("() => { const s = lee.trace.model.states.findIndex(x => x.line === 4); leeTraceScrub(s); }")
        out['vals'] = await pg.inner_text('#tracevals')
        out['dbg'] = await pg.evaluate("() => !!document.querySelector('.cm-lee-trace-line')")
        out['cur'] = ['4']
        out['spark'] = await pg.eval_on_selector_all('#tracevals svg', 'els => els.length')
        await pg.evaluate("() => { LeeCM.setDoc(lee.editors.get('c1'), LeeCM.getDoc(lee.editors.get('c1')).replace('], 7)', '], 11)')); }")
        await pg.click('#tracerun')
        await pg.wait_for_function("() => document.querySelectorAll('.lee-lens s').length > 0", timeout=60000)
        out['ghost'] = await pg.eval_on_selector_all('.lee-lens s', 'els => els.map(e => e.textContent)')
        out['note2'] = await pg.inner_text('#tracenote')
        await pg.screenshot(path=str(SHOTS/'bvc-trace-diff-light.png'))
        await pg.evaluate("() => document.documentElement.dataset.mode = 'dark'")
        await pg.screenshot(path=str(SHOTS/'bvc-trace-diff-dark.png'))
        return out
    out = asyncio.run(_real_page(go, tmp_path))
    assert [m for m in out['mids'] if m] == ['mid=2', 'mid=4', 'mid=3'], out
    assert 'steps' in out['note'] and '3' in out['output']
    assert 'line 4' in out['vals'] and 'mid' in out['vals'] and out['spark'] >= 1, out
    assert out['cur'] == ['4'] and out['dbg'], out
    assert out['ghost'] and 'differ from the last run' in out['note2'], out
