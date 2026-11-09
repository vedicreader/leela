"The run trace beside the code: values at the end of each line, a step bar, ghosts of the last run, and a clean exit."
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
LOOP = "t = 0\nfor i in range(5000):\n    t += i\nprint(t)"
SHOTS = Path(__file__).resolve().parent.parent/'target'
LENS = '.cm-line .lee-lens'

def _nb(p, source):
    cell = {'cell_type': 'code', 'id': 'c1', 'metadata': {}, 'execution_count': None, 'outputs': [], 'source': source}
    p.write_text(json.dumps({'cells': [cell], 'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))

async def _open(pg, p):
    await pg.set_viewport_size({'width': 1500, 'height': 900})
    await pg.evaluate(f'leeOpenFile({str(p)!r})')
    await pg.wait_for_function("() => lee.cells && lee.cells.length && lee.editors.get('c1')")
    await pg.evaluate('() => { selectCell(0); leeRight("vars"); }')
    await pg.click('#tracebtn')

async def _strips(pg):
    "{source of each line that has a strip: the text of its current column}"
    return await pg.evaluate("""() => Object.fromEntries([...document.querySelectorAll('.cm-line')].filter(l => l.querySelector('.lee-lens'))
      .map(l => [l.textContent.replace(l.querySelector('.lee-lens').textContent, '').trim(), [...l.querySelectorAll('.lee-lc.cur')].map(c => c.textContent).join('|')]))""")

def test_the_values_sit_beside_each_line_scrub_with_the_step_and_close_cleanly(tmp_path):
    "Each traced line ends in its values; the step bar and the arrows move them; Escape and an edit take them away."
    p = tmp_path/'bs.ipynb'; _nb(p, BS); SHOTS.mkdir(exist_ok=True)
    async def go(pg):
        out = {}
        await _open(pg, p)
        await pg.click('#tracerun')
        await pg.wait_for_selector(LENS, timeout=60000)
        out['doc'] = await pg.evaluate("() => LeeCM.getDoc(lee.editors.get('c1'))")
        out['strips'] = await _strips(pg)
        out['cols'] = await pg.eval_on_selector_all('.cm-line .lee-lens', "els => els.map(e => e.querySelectorAll('.lee-lc').length)")
        out['bar'] = await pg.inner_text('#trbar-c1')
        out['focus'] = await pg.evaluate("() => document.activeElement.id")
        out['undo'] = await pg.evaluate("() => LeeCM.getDoc(lee.editors.get('c1')) === lee.cells[0].source")
        await pg.evaluate("() => document.documentElement.dataset.mode = 'light'")
        await pg.screenshot(path=str(SHOTS/'bvc2-inline-light.png'))
        await pg.evaluate("() => document.documentElement.dataset.mode = 'dark'")
        await pg.screenshot(path=str(SHOTS/'bvc2-inline-dark.png'))
        await pg.evaluate("() => document.documentElement.dataset.mode = 'light'")
        # scrub: the first step shows only what had run; the current line carries the background
        await pg.evaluate("() => leeTraceScrub(0)")
        out['first'] = await pg.evaluate("() => [lee.trace.step, document.querySelector('.cm-lee-trace-line')?.textContent.trim().slice(0, 30)]")
        out['pos0'] = await pg.inner_text('#trbar-c1 .lee-trpos')
        await pg.click('#trbar-c1 button[data-d="1"]')
        out['pos1'] = await pg.inner_text('#trbar-c1 .lee-trpos')
        await pg.evaluate("() => { const k = lee.trace.model.states.findIndex(x => x.line === 4 && x.step > lee.trace.model.states[3].step); leeTraceScrub(k); }")
        out['mid_line'] = await pg.evaluate("() => document.querySelector('.cm-lee-trace-line')?.textContent.trim().slice(0, 12)")
        out['cur_cols'] = await pg.eval_on_selector_all('.lee-lc.cur', 'els => els.map(e => e.textContent)')
        # a click on a column jumps to that step
        await pg.evaluate("() => { const c = [...document.querySelectorAll('.lee-lc')].find(c => c.textContent.includes('mid=2')); c.click(); }")
        out['jump'] = await pg.evaluate("() => lee.trace.model.states[lee.trace.step].values.mid")
        # a click on a name plots it above the code and in the pane
        await pg.evaluate("() => [...document.querySelectorAll('.lee-lp .n')].find(n => n.textContent === 'mid').click()")
        out['plot'] = await pg.evaluate("() => !!document.querySelector('#trtop-c1 svg')")
        await pg.screenshot(path=str(SHOTS/'bvc2-plot-light.png'))
        await pg.click('#trtop-c1 button')
        out['plot_off'] = await pg.evaluate("() => !document.querySelector('#trtop-c1')")
        # arrows with the strip focused
        await pg.focus('#trbar-c1')
        before = await pg.evaluate('() => lee.trace.step')
        await pg.keyboard.press('ArrowLeft')
        out['arrow'] = [before, await pg.evaluate('() => lee.trace.step')]
        await pg.keyboard.press('ArrowRight'); await pg.keyboard.press('ArrowRight')
        out['arrow2'] = await pg.evaluate('() => lee.trace.step')
        # Escape closes
        await pg.keyboard.press('Escape')
        out['closed'] = await pg.evaluate("() => [document.querySelectorAll('.lee-lens').length, document.querySelectorAll('.cm-lee-trace-line').length, !!document.querySelector('#trbar-c1'), lee.trace.model]")
        out['doc2'] = await pg.evaluate("() => LeeCM.getDoc(lee.editors.get('c1'))")
        out['hist'] = await pg.evaluate("() => { const v = lee.editors.get('c1'); const u = LeeCM.undo(v); return [u, LeeCM.getDoc(v) === lee.cells[0].source]; }")
        # run again, then edit: strips go, with the note
        await pg.click('#tracerun')
        await pg.wait_for_selector(LENS, timeout=60000)
        await pg.evaluate("() => { const v = lee.editors.get('c1'); v.focus(); v.dispatch({selection: {anchor: v.state.doc.length}}); }")
        await pg.keyboard.type(' ')
        await pg.wait_for_function("() => !document.querySelector('.lee-lens')")
        out['note'] = await pg.inner_text('#trcleared-c1')
        out['pane'] = await pg.inner_text('#tracebox')
        # a second run with another input: the old values stay beside the new, struck through
        await pg.evaluate("() => { const v = lee.editors.get('c1'); LeeCM.setDoc(v, LeeCM.getDoc(v).trim().replace('], 7)', '], 7)')); }")
        await pg.click('#tracerun')
        await pg.wait_for_selector(LENS, timeout=60000)
        await pg.evaluate("() => { const v = lee.editors.get('c1'); LeeCM.setDoc(v, LeeCM.getDoc(v).replace('], 7)', '], 11)')); }")
        await pg.click('#tracerun')
        await pg.wait_for_selector('.lee-lens s', timeout=60000)
        out['ghost'] = await pg.eval_on_selector_all('.lee-lens s', 'els => els.map(e => e.textContent)')
        await pg.screenshot(path=str(SHOTS/'bvc2-ghost-light.png'))
        await pg.evaluate("() => document.documentElement.dataset.mode = 'dark'")
        await pg.screenshot(path=str(SHOTS/'bvc2-ghost-dark.png'))
        return out
    out = asyncio.run(_real_page(go, tmp_path))
    s = out['strips']
    assert out['doc'] == BS and out['doc2'] == BS, out
    assert s['mid = (low + high) // 2'] == 'mid=3' and s['low, high = 0, len(a) - 1'] == 'low=0 high=5', s
    assert any(k.startswith('if a[mid] < x') for k in s) and out['cols'].count(3) >= 1, out
    assert 'step' in out['bar'] and out['focus'] == 'trbar-c1', out
    assert out['first'][0] == 0 and out['pos0'].startswith('step 1 of') and out['pos1'].startswith('step 2 of'), out
    assert out['mid_line'].startswith('mid ='), out
    assert out['jump'] == '2' and out['plot'] and out['plot_off'], out
    assert out['arrow'][1] == out['arrow'][0] - 1, out
    assert out['closed'] == [0, 0, False, None], out
    assert out['hist'][1], out
    assert out['note'] == 'Trace cleared: the cell changed.' and 'Trace cleared' in out['pane'], out
    assert out['ghost'], out

def test_a_long_loop_stays_quick_and_says_how_many_passes_were_skipped(tmp_path):
    "5000 passes are sampled by the tracer; the strip shows the marker, a window of columns, and scrubbing stays fast."
    p = tmp_path/'loop.ipynb'; _nb(p, LOOP); SHOTS.mkdir(exist_ok=True)
    async def go(pg):
        out = {}
        await _open(pg, p)
        await pg.click('#tracerun')
        await pg.wait_for_selector(LENS, timeout=90000)
        out['n'] = await pg.evaluate("() => lee.trace.model.states.length")
        out['skip'] = await pg.eval_on_selector_all('.lee-lskip', 'els => els.map(e => e.textContent)')
        out['cols'] = await pg.eval_on_selector_all('.cm-line .lee-lens', "els => els.map(e => e.querySelectorAll('.lee-lc').length)")
        out['ms'] = await pg.evaluate("""() => { const t0 = performance.now(); const n = lee.trace.model.states.length;
          for (let k = 0; k < 60; k++) leeTraceScrub(Math.floor(k * n / 60)); return performance.now() - t0; }""")
        out['folds'] = await pg.eval_on_selector_all('.lee-lf', 'els => els.map(e => e.textContent)')
        await pg.screenshot(path=str(SHOTS/'bvc2-loop-light.png'))
        return out
    out = asyncio.run(_real_page(go, tmp_path))
    assert out['skip'] and 'skipped' in out['skip'][0], out
    assert max(out['cols']) <= 8 and out['folds'], out
    assert out['ms'] < 3000, out
