"Alt-dragging a number in a code cell changes the text; with live scrub on, a copy of a safe cell runs as it goes in a worker and leaves a ghost of the old output."

import asyncio, json
from pathlib import Path
import pytest

pytestmark = pytest.mark.slow

pytest.importorskip('playwright.async_api')

from test_completion_caret_slow import _real_page   # noqa: E402

ROOT = Path(__file__).parents[1]
PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
DOC = "() => LeeCM.getDoc(lee.editors.get('c1'))"
OUT = "() => document.querySelector('#out-c1').innerText.trim()"
GHOST = "() => { const g = document.querySelector('#ghost-c1'); return g && g.innerText; }"
NOTE = "() => { const n = document.querySelector('#note-c1'); return n && n.innerText; }"
BOX = """() => { const v = lee.editors.get('c1'), t = LeeCM.getDoc(v), at = t.search(/\\d/);
  const a = v.coordsAtPos(at), b = v.coordsAtPos(at + 1, -1); return {x: (a.left + b.left) / 2, y: (a.top + a.bottom) / 2}; }"""

def _nb(path, src, live=True):
    cell = {'cell_type': 'code', 'id': 'c1', 'metadata': {'scrub': {'live': True}} if live else {}, 'execution_count': None, 'outputs': [], 'source': src}
    meta = {'kernelspec': {'name': 'python3', 'display_name': 'Python 3', 'language': 'python'}}
    path.write_text(json.dumps({'cells': [cell], 'metadata': meta, 'nbformat': 4, 'nbformat_minor': 5}))

async def _open(pg, p):
    await pg.evaluate('p => leeOpenFile(p)', str(p))
    await pg.wait_for_function("() => lee.kind === 'notebook' && lee.editors.get('c1')")
    if json.loads(p.read_text())['cells'][0]['metadata'].get('scrub'):
        await pg.evaluate("() => { lee.sel = 0; return leeAct('scrub_live'); }")
        await pg.wait_for_function("() => lee.cells[0].extra?.scrub?.live === true", timeout=10000)

async def _drag(pg, steps, wait):
    "Alt-drag the first number right by `steps` quarters of 16 px, waiting for `wait(i)` after each."
    box = await pg.evaluate(BOX)
    await pg.keyboard.down('Alt')
    await pg.mouse.move(box['x'], box['y']); await pg.wait_for_timeout(100)
    armed = await pg.evaluate("() => !!document.querySelector('.lee-scrub-hint') && document.body.classList.contains('lee-scrub-armed')")
    await pg.mouse.down()
    for i in range(1, steps + 1):
        await pg.mouse.move(box['x'] + 4 * i, box['y'])
        if wait: await wait(i)
    return armed

async def _release(pg):
    await pg.mouse.up(); await pg.keyboard.up('Alt')
    await pg.wait_for_function("() => !lee.scrubbing.size", timeout=10000)

def test_dragging_a_number_follows_in_the_output_undoes_in_one_step_and_leaves_a_ghost(tmp_path):
    nb = tmp_path/'n.ipynb'; _nb(nb, 'x = 3\nprint(x*2)')
    async def go(pg):
        await _open(pg, nb)
        await pg.evaluate('runCell(0)'); await pg.wait_for_function("() => document.querySelector('#out-c1').innerText.trim() === '6'")
        seen = []
        async def want(i):
            await pg.wait_for_function(f"() => document.querySelector('#out-c1').innerText.trim() === '{6 + 2 * i}'", timeout=10000)
            seen.append(await pg.evaluate(OUT))
        armed = await _drag(pg, 2, want)
        mid_ghost = await pg.evaluate(GHOST)
        for scheme in ('light', 'dark'):
            await pg.evaluate('m => { lee.theme = {...lee.theme, mode: m}; paintTheme(); }', scheme)
            await pg.wait_for_timeout(200)
            await pg.screenshot(path=str(ROOT/'target'/f'bvb-scrub-{scheme}.png'))
        await pg.wait_for_timeout(1300)
        saved = ''.join(json.loads(nb.read_text())['cells'][0]['source'])
        await _release(pg)
        await pg.wait_for_function("() => lee.cells[0].execution_count === 2 && !lee.cells[0].running", timeout=20000)
        after = await pg.evaluate(DOC); out = await pg.evaluate(OUT); ghost = await pg.evaluate(GHOST)
        await pg.keyboard.press('ControlOrMeta+z')
        undone = await pg.evaluate(DOC)
        await pg.keyboard.press('ControlOrMeta+z')
        twice = await pg.evaluate(DOC)
        await pg.evaluate('runCell(0)'); await pg.wait_for_timeout(1500)
        return armed, seen, mid_ghost, after, out, ghost, saved, undone, twice, await pg.evaluate(GHOST)
    armed, seen, mid, after, out, ghost, saved, undone, twice, cleared = asyncio.run(_real_page(go, tmp_path))
    assert armed and seen == ['8', '10'], (armed, seen)
    assert after == 'x = 5\nprint(x*2)' and out == '10', (after, out)
    assert mid and '8' in mid and ghost is None, (mid, ghost)
    assert saved == 'x = 3\nprint(x*2)', 'the file was written during the gesture'
    assert undone == 'x = 3\nprint(x*2)', undone
    assert twice == undone, 'one undo must be enough'
    assert cleared is None, 'an ordinary run clears the ghost'

def test_an_impure_cell_changes_the_number_names_the_reason_and_does_not_run(tmp_path):
    nb = tmp_path/'n.ipynb'; _nb(nb, "x = 3\nopen('leaked.txt', 'w').write(str(x))\nprint(x*2)")
    async def go(pg):
        await _open(pg, nb)
        await _drag(pg, 3, None)
        await pg.wait_for_function("() => document.querySelector('#note-c1')")
        await _release(pg)
        await pg.wait_for_timeout(500)
        return await pg.evaluate(DOC), await pg.evaluate(NOTE), await pg.evaluate(OUT), await pg.evaluate('() => lee.cells[0].execution_count')
    doc, note, out, count = asyncio.run(_real_page(go, tmp_path))
    assert doc.startswith('x = 6\n') and note and 'Not re-running' in note and 'safe list' in note, (doc, note)
    assert out == '' and count is None and not (tmp_path/'leaked.txt').exists()

def test_a_run_over_a_second_is_stopped_and_the_scrub_says_too_slow(tmp_path):
    nb = tmp_path/'n.ipynb'; _nb(nb, 'import time\nt = time.time()\nwhile time.time() - t < 20: pass')
    async def go(pg):
        await _open(pg, nb)
        await _drag(pg, 1, None)
        await pg.wait_for_function("() => (document.querySelector('#note-c1') || {}).innerText?.includes('Too slow')", timeout=20000)
        await _release(pg)
        return await pg.evaluate(NOTE), await pg.evaluate('() => lee.cells[0].running')
    note, running = asyncio.run(_real_page(go, tmp_path))
    assert 'Too slow' in note and not running

def test_a_picture_ghost_overlays_and_a_text_ghost_sits_beneath(tmp_path):
    nb = tmp_path/'n.ipynb'; _nb(nb, 'x = 3')
    async def go(pg):
        await _open(pg, nb)
        return await pg.evaluate("""p => {
          const c = lee.cells[0]; c.outputs = [{output_type: 'stream', name: 'stdout', text: 'now\\n'}]; renderOutputs(c);
          leeScrubGhost(c, [{output_type: 'display_data', data: {'image/png': p}, metadata: {}}]);
          const img = document.querySelector('#ghost-c1.overlay img');
          leeScrubGhost(c, [{output_type: 'stream', name: 'stdout', text: 'then\\n'}]);
          const g = document.querySelector('#ghost-c1');
          leeScrubGhost(c, c.outputs);
          return [!!img, g.classList.contains('overlay'), g.innerText, !!document.querySelector('#ghost-c1')];
        }""", PNG)
    img, overlay, text, left = asyncio.run(_real_page(go, tmp_path))
    assert img and not overlay and 'then' in text and not left

def test_a_scrub_tick_leaves_the_run_count_and_gutter_alone(tmp_path):
    nb = tmp_path/'n.ipynb'; _nb(nb, 'x = 3\nprint(x*2)')
    async def go(pg):
        await _open(pg, nb)
        await pg.evaluate('runCell(0)'); await pg.wait_for_function("() => document.querySelector('#out-c1').innerText.trim() === '6'")
        before = await pg.evaluate("() => [lee.cells[0].execution_count, document.querySelector('#g-c1').textContent]")
        await _drag(pg, 2, None)
        await pg.wait_for_function("() => document.querySelector('#out-c1').innerText.trim() === '10'", timeout=10000)
        mid = await pg.evaluate("() => [lee.cells[0].execution_count, document.querySelector('#g-c1').textContent]")
        await _release(pg)
        await pg.wait_for_function("() => lee.cells[0].execution_count === 2 && !lee.cells[0].running", timeout=20000)
        return before, mid, await pg.evaluate("() => leeScrubS.warm === lee.tabKey")
    before, mid, warmed = asyncio.run(_real_page(go, tmp_path))
    assert before == mid and warmed, (before, mid, warmed)

def test_escape_puts_the_number_and_the_output_back_and_a_lost_pointer_ends_the_drag(tmp_path):
    nb = tmp_path/'n.ipynb'; _nb(nb, 'x = 3\nprint(x*2)')
    async def go(pg):
        await _open(pg, nb)
        await pg.evaluate('runCell(0)'); await pg.wait_for_function("() => document.querySelector('#out-c1').innerText.trim() === '6'")
        await _drag(pg, 2, None)
        await pg.wait_for_function("() => document.querySelector('#out-c1').innerText.trim() === '10'", timeout=10000)
        await pg.keyboard.press('Escape')
        await pg.wait_for_function("() => document.querySelector('#out-c1').innerText.trim() === '6' && !lee.scrubbing.size", timeout=10000)
        esc = await pg.evaluate(DOC), await pg.evaluate(GHOST)
        await pg.mouse.up(); await pg.keyboard.up('Alt')
        await _drag(pg, 1, None)
        await pg.evaluate("() => dispatchEvent(new Event('blur'))")
        await pg.wait_for_function("() => !lee.scrubbing.size && !leeScrubS.drag", timeout=10000)
        return esc, await pg.evaluate(DOC), await pg.evaluate("() => document.body.classList.contains('lee-scrubbing')")
    (doc, ghost), after_blur, still = asyncio.run(_real_page(go, tmp_path))
    assert doc == 'x = 3\nprint(x*2)' and ghost is None, (doc, ghost)
    assert after_blur == 'x = 4\nprint(x*2)' and not still

def test_a_number_dragged_past_what_the_check_allows_stops_re_running_and_says_why(tmp_path):
    nb = tmp_path/'n.ipynb'; _nb(nb, 'import time\ntime.sleep(1)\nprint("done")')
    async def go(pg):
        await _open(pg, nb)
        await pg.evaluate('runCell(0)'); await pg.wait_for_function("() => document.querySelector('#out-c1').innerText.includes('done')", timeout=20000)
        await _drag(pg, 1, None)
        await pg.wait_for_function("() => document.querySelector('#note-c1')", timeout=10000)
        await _release(pg)
        return await pg.evaluate(DOC), await pg.evaluate(NOTE), await pg.evaluate(OUT)
    doc, note, out = asyncio.run(_real_page(go, tmp_path))
    assert 'sleep(2)' in doc and 'sleeps' in note and out == 'done', (doc, note, out)

def test_the_palette_nudges_and_alt_arrows_move_the_number_under_the_caret_one_undo_step_each(tmp_path):
    nb = tmp_path/'n.ipynb'; _nb(nb, 'x = 3\nprint(x*2)')
    async def go(pg):
        await _open(pg, nb)
        await pg.evaluate('runCell(0)'); await pg.wait_for_function("() => document.querySelector('#out-c1').innerText.trim() === '6'")
        await pg.evaluate("() => { const v = lee.editors.get('c1'); v.focus(); v.dispatch({selection: {anchor: 5}}); }")
        await pg.evaluate("() => leeAct('scrub_up')")
        await pg.wait_for_function("() => document.querySelector('#out-c1').innerText.trim() === '8'", timeout=10000)
        await pg.keyboard.press('Alt+ArrowUp')
        await pg.wait_for_function("() => document.querySelector('#out-c1').innerText.trim() === '10'", timeout=10000)
        await pg.evaluate("() => leeAct('scrub_down')")
        await pg.wait_for_function("() => document.querySelector('#out-c1').innerText.trim() === '8'", timeout=10000)
        await pg.wait_for_function("() => !lee.scrubbing.size", timeout=10000)
        out = [await pg.evaluate(DOC)]
        for _ in range(3): await pg.keyboard.press('ControlOrMeta+z'); out.append(await pg.evaluate(DOC))
        return out
    out = asyncio.run(_real_page(go, tmp_path))
    assert out[0] == 'x = 4\nprint(x*2)' and out[-1] == 'x = 3\nprint(x*2)', out

def test_the_scrub_box_sets_the_number_from_a_typed_or_spoken_value(tmp_path):
    nb = tmp_path/'n.ipynb'; _nb(nb, 'x = 3\nprint(x*2)')
    async def go(pg):
        await _open(pg, nb)
        await pg.evaluate('runCell(0)'); await pg.wait_for_function("() => document.querySelector('#out-c1').innerText.trim() === '6'")
        await pg.evaluate("() => { const v = lee.editors.get('c1'); v.focus(); v.dispatch({selection: {anchor: 5}}); leeAct('scrub_value'); }")
        await pg.fill('#scrubvalue', '21')
        await pg.wait_for_function("() => document.querySelector('#out-c1').innerText.trim() === '42'", timeout=10000)
        await pg.press('#scrubvalue', 'Enter')
        await pg.wait_for_function("() => !lee.scrubbing.size && !document.querySelector('#scrubvalue')", timeout=10000)
        return await pg.evaluate(DOC)
    assert asyncio.run(_real_page(go, tmp_path)) == 'x = 21\nprint(x*2)'

def test_live_scrub_is_off_until_the_cell_opts_in_and_a_drag_then_only_changes_the_number(tmp_path):
    nb = tmp_path/'n.ipynb'; _nb(nb, 'x = 3\nprint(x*2)', live=False)
    async def go(pg):
        await _open(pg, nb)
        await pg.evaluate('runCell(0)'); await pg.wait_for_function("() => document.querySelector('#out-c1').innerText.trim() === '6'")
        calls = []
        pg.on('request', lambda r: calls.append(r.url) if 'scrub/run' in r.url else None)
        await _drag(pg, 2, None)
        await pg.wait_for_timeout(600)
        await _release(pg)
        await pg.wait_for_timeout(600)
        off = [await pg.evaluate(DOC), await pg.evaluate(OUT), await pg.evaluate(GHOST), await pg.evaluate(NOTE), await pg.evaluate('() => lee.cells[0].execution_count'), len(calls)]
        await pg.evaluate("() => { lee.sel = 0; return leeAct('scrub_live'); }")
        await pg.wait_for_function("() => lee.cells[0].extra?.scrub?.live === true", timeout=10000)
        await pg.evaluate("() => { lee.sel = 0; return leeAct('scrub_live'); }")
        await pg.wait_for_function("() => !lee.cells[0].extra?.scrub", timeout=10000)
        return off
    doc, out, ghost, note, count, calls = asyncio.run(_real_page(go, tmp_path))
    assert doc == 'x = 5\nprint(x*2)' and out == '6' and ghost is None and note is None and count == 1 and calls == 0, (doc, out, ghost, note, count, calls)
