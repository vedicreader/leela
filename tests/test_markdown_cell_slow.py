"A markdown cell is read rendered, and opens its editor on request."

import json
import pytest

pytestmark = pytest.mark.slow

pytest.importorskip('playwright.async_api')

from test_web_slow import _run   # noqa: E402

CELLS = [('markdown', '# Title\n\nsome prose'), ('code', 'x = 1'), ('markdown', 'second cell')]
VIS = r"""(i) => [...document.querySelectorAll(`.lee-cell[data-i="${i}"] .cm-editor`)]
  .filter(e => e.getBoundingClientRect().height > 0).length"""
SHOWN = r"""(i) => { const m = document.querySelector(`.lee-cell[data-i="${i}"] .lee-md-cell`);
  return !!m && m.getBoundingClientRect().height > 0 }"""
STATE = r"""() => ({sel: lee.sel, src: lee.cells.map(c => c.source),
  editing: [...document.querySelectorAll('.lee-cell[data-md-edit]')].map(e => +e.dataset.i)})"""


def test_a_markdown_cell_shows_rendered_and_edits_on_request(tmp_path):
    p = tmp_path/'md.ipynb'
    p.write_text(json.dumps({'cells': [
        {'cell_type': t, 'source': s.splitlines(True), 'metadata': {}, 'id': f'c{i}',
         **({'outputs': [], 'execution_count': None} if t == 'code' else {})} for i, (t, s) in enumerate(CELLS)],
        'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    async def go(pg):
        out = {}
        await pg.evaluate(f'leeOpenFile({str(p)!r})')
        await pg.wait_for_selector('.lee-cell[data-i="0"] .lee-md-cell h1')
        await pg.evaluate('ensureCellMounted(1); ensureCellMounted(0)')
        await pg.wait_for_selector('.lee-cell[data-i="1"] .cm-editor')
        out['open'] = {'h1': await pg.inner_text('.lee-cell[data-i="0"] .lee-md-cell h1'),
                       'md_editors': await pg.evaluate(VIS, 0), 'code_editors': await pg.evaluate(VIS, 1)}
        await pg.dblclick('.lee-cell[data-i="0"] .lee-md-cell')
        await pg.wait_for_function(f'({VIS})(0) === 1')
        out['edit'] = {'shown': await pg.evaluate(SHOWN, 0), 'state': await pg.evaluate(STATE),
                       'focus': await pg.evaluate('!!document.activeElement.closest(".lee-cell[data-i=\'0\']")')}
        await pg.keyboard.type(' more')
        await pg.keyboard.press('Escape')
        await pg.wait_for_function(f'({VIS})(0) === 0')
        await pg.wait_for_function('document.querySelector(".lee-cell[data-i=\'0\'] .lee-md-cell").textContent.includes("more")')
        out['esc'] = {'shown': await pg.evaluate(SHOWN, 0), 'state': await pg.evaluate(STATE)}
        await pg.keyboard.press('Enter')
        await pg.wait_for_function(f'({VIS})(0) === 1')
        out['enter'] = await pg.evaluate(STATE)
        await pg.keyboard.press('Shift+Enter')
        await pg.wait_for_function(f'({VIS})(0) === 0')
        out['shift'] = {'state': await pg.evaluate(STATE), 'shown': await pg.evaluate(SHOWN, 0)}
        await pg.click('.lee-cell[data-i="1"] .cm-content')
        await pg.keyboard.press('End')
        await pg.keyboard.press('Enter')
        await pg.keyboard.press('Escape')
        out['code'] = {'state': await pg.evaluate(STATE), 'editors': await pg.evaluate(VIS, 1)}
        return out
    got = _run(go, roots=[tmp_path])
    assert got['open'] == {'h1': 'Title', 'md_editors': 0, 'code_editors': 1}, got['open']
    assert got['edit']['state']['editing'] == [0] and not got['edit']['shown'] and got['edit']['focus'], got['edit']
    assert got['esc']['shown'] and got['esc']['state']['editing'] == [], got['esc']
    assert got['esc']['state']['src'][0].endswith('some prose more'), 'the caret did not start at the end'
    assert got['enter']['editing'] == [0], 'Enter in command mode did not open the editor'
    assert got['shift']['state']['sel'] == 1 and got['shift']['state']['editing'] == [] and got['shift']['shown'], got['shift']
    assert got['code']['editors'] == 1 and got['code']['state']['src'][1] == 'x = 1\n', got['code']
