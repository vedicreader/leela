"Alt-dragging a number in a code cell changes the text, re-runs a safe cell as it goes, and leaves a ghost of the old output."

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

def _nb(path, src):
    cell = {'cell_type': 'code', 'id': 'c1', 'metadata': {}, 'execution_count': None, 'outputs': [], 'source': src}
    meta = {'kernelspec': {'name': 'python3', 'display_name': 'Python 3', 'language': 'python'}}
    path.write_text(json.dumps({'cells': [cell], 'metadata': meta, 'nbformat': 4, 'nbformat_minor': 5}))

async def _open(pg, p):
    await pg.evaluate('p => leeOpenFile(p)', str(p))
    await pg.wait_for_function("() => lee.kind === 'notebook' && lee.editors.get('c1')")

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
    await pg.wait_for_function("() => !lee.scrubbing", timeout=10000)

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
    assert mid and '6' in mid and ghost and '6' in ghost, (mid, ghost)
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
    assert doc.startswith('x = 6\n') and note and 'Not re-running' in note and 'write' in note, (doc, note)
    assert out == '' and count is None and not (tmp_path/'leaked.txt').exists()

def test_a_run_over_a_second_is_stopped_and_the_scrub_says_too_slow(tmp_path):
    nb = tmp_path/'n.ipynb'; _nb(nb, 'n = 1\ns = 0\nfor i in range(n * 10**9):\n    s += i')
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
