"Slide types set from the cell menu, the palette, RISE's chords and the cell's own button, in a real page."

import pytest

pytestmark = pytest.mark.slow

import asyncio, json

pytest.importorskip('playwright.async_api')

from test_completion_caret_slow import _real_page   # noqa: E402
from test_present_slow import READY   # noqa: E402

CELLS = [{'cell_type': 'markdown', 'id': 'm0', 'metadata': {'slideshow': {'slide_type': 'slide'}}, 'source': '# One'},
         *[{'cell_type': 'markdown', 'id': i, 'metadata': {}, 'source': s}
           for i, s in (('m1', 'VISIBLE-BODY'), ('m2', 'TO-SKIP'), ('m3', 'TO-NOTES'))],
         {'cell_type': 'code', 'id': 'c4', 'metadata': {}, 'execution_count': None, 'outputs': [], 'source': 'x = 1'}]
TYPES = '() => lee.cells.map(c => c.extra?.slideshow?.slide_type || null)'
MARK = '''id => { const el = document.querySelector(`.lee-cell[data-id="${id}"]`), b = el.querySelector('.lee-cell-slide');
  return {text: b.textContent, type: b.dataset.type, shown: getComputedStyle(b).visibility,
          dim: +getComputedStyle(el.querySelector('.lee-cellmain')).opacity < 1}; }'''
DECK = '''() => ({slides: document.querySelector('.lee-present .slides').textContent})'''

async def _walk(pg, root):
    out = {}
    await pg.route('**/browser/external', lambda r: asyncio.ensure_future(
        r.fulfill(status=200, content_type='application/json', body='{"ok": true}')))
    await pg.evaluate('p => leeOpenFile(p)', str(root/'deck.ipynb'))
    await pg.wait_for_function('() => document.querySelectorAll(".lee-cell").length === 5')
    out['marks0'] = [await pg.evaluate(MARK, i) for i in ('m0', 'm1')]
    until = lambda i, t: pg.wait_for_function(f'() => ({TYPES})()[{i}] === {json.dumps(t)}')
    await pg.evaluate("() => { selectCell(2); openMenu('cell', 120, 120); }")
    await pg.click('.lee-ctxmenu [data-action="slide_skip"]')
    await until(2, 'skip')
    out['skip_mark'] = await pg.evaluate(MARK, 'm2')
    await pg.evaluate('() => selectCell(3)')
    await pg.keyboard.press('ControlOrMeta+Shift+KeyP'); await pg.wait_for_selector('#cp')
    await pg.keyboard.type('slide type: notes'); await pg.keyboard.press('Enter')
    await until(3, 'notes')
    out['notes_mark'] = await pg.evaluate(MARK, 'm3')
    await pg.evaluate('() => focusCell(1)')
    await pg.wait_for_function('() => document.activeElement?.closest(".lee-cell")?.dataset.id === "m1"')
    await pg.keyboard.press('Shift+KeyI')
    await until(1, 'slide')
    await pg.evaluate('() => focusCell(4)')
    await pg.wait_for_function('() => document.activeElement?.closest(".cm-editor")')
    await pg.keyboard.press('Shift+KeyI'); await pg.wait_for_timeout(300)
    out['typed'] = await pg.evaluate(f'() => [LeeCM.getDoc(lee.editors.get("c4")), ({TYPES})()[4]]')
    await pg.evaluate("() => { document.activeElement.blur(); selectCell(4); setScope('editor'); }")
    await pg.keyboard.press('Shift+KeyG')
    await until(4, 'fragment')
    await pg.evaluate("() => { selectCell(0); selectCell(1, true); document.activeElement.blur(); setScope('editor'); }")
    await pg.keyboard.press('Shift+KeyB')
    await pg.wait_for_function(f'() => ({TYPES})().slice(0, 2).join() === "subslide,subslide"')
    await pg.keyboard.press('ControlOrMeta+KeyZ')
    await pg.wait_for_function(f'() => ({TYPES})().slice(0, 2).join() === "slide,slide"')
    out['after_undo'] = await pg.evaluate(TYPES)
    await pg.click('.lee-cell[data-id="m3"] .lee-cell-slide')
    await until(3, None)
    await pg.evaluate('() => selectCell(3)')
    await pg.click('.lee-cell[data-id="m3"] .lee-cell-slide')
    await until(3, 'slide')
    await pg.evaluate("() => leeAct('slide_notes')")
    await until(3, 'notes')
    await pg.evaluate('() => presentNotebook()')
    await pg.wait_for_function(READY, timeout=20000)
    out['deck'] = await pg.evaluate(DECK)
    for _ in range(100):
        st = await pg.evaluate("fetch('/present/state').then(r => r.json())")
        if st.get('live'): break
        await pg.wait_for_timeout(100)
    out['notes'] = ' '.join(s.get('notes', '') for s in st.get('slides', []))
    await pg.keyboard.press('Escape')
    await pg.wait_for_function('() => !document.querySelector(".lee-present")')
    await pg.evaluate("() => { selectCell(2); openMenu('cell', 120, 120); }")
    await pg.click('.lee-ctxmenu [data-action="slide_none"]')
    await until(2, None)
    out['none'] = await pg.evaluate('() => lee.cells[2].extra')
    await pg.evaluate('() => selectCell(0)')
    out['none_mark'] = await pg.evaluate(MARK, 'm2')
    await pg.evaluate('() => presentNotebook()')
    await pg.wait_for_function(READY, timeout=20000)
    out['deck2'] = await pg.evaluate(DECK)
    await pg.keyboard.press('Escape')
    await pg.wait_for_function('() => !document.querySelector(".lee-present")')
    await pg.evaluate("() => leeAct('save')")
    for _ in range(100):
        disk = json.loads((root/'deck.ipynb').read_text())['cells']
        if 'slideshow' in disk[4]['metadata'] and 'slideshow' not in disk[2]['metadata']: break
        await pg.wait_for_timeout(100)
    out['disk'] = [c['metadata'] for c in disk]
    return out

@pytest.mark.parametrize('browser', ['chromium', 'webkit'])
def test_a_slide_type_set_from_any_route_shows_on_the_cell_reaches_the_deck_and_the_file(tmp_path, browser):
    meta = {'kernelspec': {'name': 'python3', 'display_name': 'Python 3', 'language': 'python'}}
    (tmp_path/'deck.ipynb').write_text(json.dumps({'cells': CELLS, 'metadata': meta, 'nbformat': 4, 'nbformat_minor': 5}))
    out = asyncio.run(_real_page(lambda pg: _walk(pg, tmp_path), tmp_path, browser))
    assert out['marks0'][0]['text'] == 'slide' and out['marks0'][0]['shown'] == 'visible', out['marks0']
    assert out['marks0'][1]['type'] == 'none' and out['marks0'][1]['shown'] == 'hidden', 'an untyped cell shows no marker'
    assert (out['skip_mark']['text'], out['skip_mark']['dim']) == ('skip', True), out['skip_mark']
    assert (out['notes_mark']['text'], out['notes_mark']['dim']) == ('notes', False), out['notes_mark']
    assert 'I' in out['typed'][0] and out['typed'][1] is None, f'Shift+I in a cell editor changed the type: {out["typed"]}'
    assert out['after_undo'] == ['slide', 'slide', 'skip', 'notes', 'fragment'], out['after_undo']
    assert 'VISIBLE-BODY' in out['deck']['slides'] and 'TO-SKIP' not in out['deck']['slides'], out['deck']
    assert 'TO-NOTES' not in out['deck']['slides'] and 'TO-NOTES' in out['notes'], (out['deck'], out['notes'])
    assert out['none'] == {} and out['none_mark']['type'] == 'none' and not out['none_mark']['dim'], out
    assert 'TO-SKIP' in out['deck2']['slides'], 'the next deck reads the cleared type'
    assert [m.get('slideshow', {}).get('slide_type') for m in out['disk']] == ['slide', 'slide', None, 'notes', 'fragment'], out['disk']
    assert 'slideshow' not in out['disk'][2]
