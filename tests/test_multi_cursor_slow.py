"Several cursors and column mode in a notebook cell and a file editor, in Chromium and WebKit."

import json

import pytest

pytestmark = pytest.mark.slow

pytest.importorskip('playwright.async_api')

from test_web_slow import _run   # noqa: E402

BODY = 'x = x\na = 1\nb = 22\nccc = 3'
WORDS = 'aa bb cc\ndd ee ff\ngg hh ii\njj kk ll'
BROWSERS = pytest.mark.parametrize('browser', ['chromium', 'webkit'])
COLUMN = 'Control+Alt+Shift+Backslash'

SETUP = r"""() => {
  window._use = v => { window._v = v; };
  window._at = (n, col = 0) => { const l = _v.state.doc.line(n); _v.focus(); _v.dispatch({selection: {anchor: l.from + col}}); };
  window._ranges = () => _v.state.selection.ranges.map(r => [r.from, r.to]);
  window._cols = () => _v.state.selection.ranges.map(r => r.head - _v.state.doc.lineAt(r.head).from);
  window._xy = (n, col) => { const c = _v.coordsAtPos(_v.state.doc.line(n).from + col); return {x: c.left + 1, y: (c.top + c.bottom) / 2}; };
  window._column = () => !!_v.dom.classList.contains('lee-column');
  window._badge = () => { const b = _v.dom.querySelector('.lee-column-badge'); return !!b && !!b.offsetParent; };
}"""


async def _checks(pg, view):
    "Every check on the editor `view` names, each recorded rather than raised, so one run shows them all."
    out, mod = {}, 'ControlOrMeta'
    mac = await pg.evaluate('MAC')
    hold, word = ('Meta', 'Alt+Shift+ArrowRight') if mac else ('Control', 'Control+Shift+ArrowRight')
    async def reset(n=1, col=0): await pg.evaluate(f'() => {{ _use({view}); LeeCM.setDoc(_v, {json.dumps(BODY)}); _at({n}, {col}); }}')
    async def step(name, fn):
        try: out[name] = await fn()
        except Exception as e: out[name] = f'error: {type(e).__name__}: {str(e).splitlines()[0]}'
    async def next_twice():
        await reset(); await pg.keyboard.press(f'{mod}+d'); await pg.keyboard.press(f'{mod}+d')
        return await pg.evaluate('_ranges()')
    async def all_matches():
        await reset(); await pg.evaluate('_v.dispatch({selection: {anchor: 0, head: 1}})')
        await pg.keyboard.press(f'{mod}+Shift+L'); return await pg.evaluate('_ranges()')
    async def palette_below():
        await reset(2)
        await pg.keyboard.press(f'{mod}+Shift+P'); await pg.wait_for_selector('#cp', timeout=3000)
        await pg.keyboard.type('add_cursor_below'); await pg.keyboard.press('Enter'); await pg.wait_for_timeout(100)
        await pg.keyboard.type('z'); return await pg.evaluate('LeeCM.getDoc(_v)')
    async def drag():
        await reset(2); a, b = await pg.evaluate('[_xy(2, 1), _xy(4, 1)]')
        await pg.keyboard.down('Shift'); await pg.keyboard.down('Alt')
        await pg.mouse.move(a['x'], a['y']); await pg.mouse.down(); await pg.mouse.move(b['x'], b['y'], steps=6); await pg.mouse.up()
        await pg.keyboard.up('Alt'); await pg.keyboard.up('Shift'); return await pg.evaluate('_ranges()')
    async def alt_click():
        await reset(2); p = await pg.evaluate('_xy(4, 2)')
        await pg.keyboard.down('Alt'); await pg.mouse.click(p['x'], p['y']); await pg.keyboard.up('Alt')
        return await pg.evaluate('_ranges()')
    async def definition():
        await reset(); p = await pg.evaluate("(document.querySelector('#status').textContent = '', _xy(1, 0))")
        await pg.keyboard.down(hold); await pg.mouse.click(p['x'], p['y']); await pg.keyboard.up(hold)
        await pg.wait_for_function("() => /definition/.test(document.querySelector('#status').textContent)", timeout=3000)
        r = {'status': await pg.evaluate("document.querySelector('#status').textContent.includes(' of x')"), 'ranges': await pg.evaluate('_ranges().length')}
        # Several hits arrive as a modal list, which owns the keyboard until it closes.
        if await pg.evaluate("!/ 1 definition/.test(document.querySelector('#status').textContent)"):
            await pg.wait_for_selector('.lee-modal', timeout=3000); await pg.keyboard.press('Escape')
            await pg.wait_for_selector('.lee-modal', state='detached', timeout=3000)
        return r
    async def find_all():
        await reset(); await pg.keyboard.press(f'{mod}+f'); await pg.wait_for_selector('#leefindq', timeout=3000)
        await pg.keyboard.type('x'); await pg.click('#leefind [data-find="select"]', timeout=2000)
        r = await pg.evaluate('_ranges()'); await pg.evaluate('findClose()'); return r
    async def column():
        await reset(2, 2); r = {}
        await pg.keyboard.press(COLUMN); r['on'] = await pg.evaluate('[_column(), _badge()]')
        await pg.keyboard.press('ArrowDown'); await pg.keyboard.press('ArrowDown')
        sel = lambda: pg.evaluate('[lee.sel, _ranges().length]')
        r['three'] = await sel()
        await pg.keyboard.press('ArrowDown'); r['edge'] = await sel()
        await pg.keyboard.type('#'); r['typed'] = await pg.evaluate('LeeCM.getDoc(_v)')
        await pg.keyboard.press('ArrowRight'); r['right'] = await pg.evaluate('_cols()')
        await pg.keyboard.press(COLUMN); r['off'] = await pg.evaluate('[_column(), _badge(), _ranges().length]')
        await pg.keyboard.press('Escape'); r['collapsed'] = await pg.evaluate('_ranges().length')
        await reset(4, 7); await pg.keyboard.press(COLUMN)
        for _ in range(3): await pg.keyboard.press('ArrowUp')
        r['clamped'] = await pg.evaluate('_cols()')
        await pg.keyboard.press('Escape'); r['escape'] = await pg.evaluate('[_column(), _ranges().length]')
        await reset(2, 0); await pg.keyboard.press(COLUMN)
        await pg.keyboard.press('ArrowRight'); await pg.keyboard.press('ArrowRight'); await pg.keyboard.press('ArrowDown')
        r['goal'] = await pg.evaluate('_cols()'); await pg.keyboard.press(COLUMN)
        texts = lambda: pg.evaluate('_v.state.selection.ranges.map(r => _v.state.sliceDoc(r.from, r.to))')
        await pg.evaluate(f'() => {{ LeeCM.setDoc(_v, {json.dumps(WORDS)}); _at(1, 3); }}')
        await pg.keyboard.press(COLUMN); await pg.keyboard.press('ArrowDown'); await pg.keyboard.press('ArrowDown')
        await pg.keyboard.press(word); await pg.keyboard.type('X'); r['word'] = await pg.evaluate('LeeCM.getDoc(_v)')
        await pg.keyboard.press('Shift+End'); r['to_end'] = await texts()
        await pg.keyboard.press('Shift+ArrowDown'); r['grow'] = await texts()
        await pg.keyboard.press(COLUMN)
        await pg.keyboard.press(COLUMN); await pg.evaluate('document.activeElement.blur()'); r['blur'] = await pg.evaluate('_column()')
        return r
    for name, fn in [('next_twice', next_twice), ('all_matches', all_matches), ('palette_below', palette_below),
                     ('drag', drag), ('alt_click', alt_click), ('definition', definition),
                     ('find_all', find_all), ('column', column)]: await step(name, fn)
    return out


def _verdict(got, cell_index=None):
    "The checks that failed, by name, so a red run names each one. `cell_index` is the cell the caret must stay in."
    c = got.get('column') if isinstance(got.get('column'), dict) else {}
    stays = lambda r: isinstance(r, list) and r[1] == 3 and cell_index in (None, r[0])
    want = {
        'next_twice': got['next_twice'] == [[0, 1], [4, 5]],
        'all_matches': got['all_matches'] == [[0, 1], [4, 5]],
        'palette_below': got['palette_below'] == 'x = x\nza = 1\nzb = 22\nccc = 3',
        'drag': isinstance(got['drag'], list) and len(got['drag']) == 3,
        'alt_click': isinstance(got['alt_click'], list) and len(got['alt_click']) == 2,
        'definition': got['definition'] == {'status': True, 'ranges': 1},
        'find_all': got['find_all'] == [[0, 1], [4, 5]],
        'column_on': c.get('on') == [True, True],
        'column_three': stays(c.get('three')),
        'column_edge': stays(c.get('edge')),
        'column_typed': c.get('typed') == 'x = x\na #= 1\nb #= 22\ncc#c = 3',
        'column_right': c.get('right') == [4, 4, 4],
        'column_off': c.get('off') == [False, False, 3],
        'column_collapsed': c.get('collapsed') == 1,
        'column_clamped': c.get('clamped') == [5, 5, 6, 7],
        'column_escape': c.get('escape') == [False, 4],
        'column_goal_follows': c.get('goal') == [2, 2],
        'column_word': c.get('word') == 'aa X cc\ndd X ff\ngg X ii\njj kk ll',
        'column_shift_end': c.get('to_end') == [' cc', ' ff', ' ii'],
        'column_shift_down': c.get('grow') == [' cc', ' ff', ' ii', 'k l'],
        'column_blur': c.get('blur') is False,
    }
    return [k for k, ok in want.items() if not ok]


@BROWSERS
def test_several_cursors_in_a_notebook_cell(tmp_path, browser):
    "CodeMirror kept one range, so Cmd+D, Cmd+Shift+L, add-cursor and Alt-drag each left a single cursor, and there was no column mode."
    nb = tmp_path/'n.ipynb'
    cells = [{'cell_type': t, 'id': i, 'metadata': {}, 'source': s, **({'execution_count': None, 'outputs': []} if t == 'code' else {})}
             for i, t, s in (('c0', 'code', 'z = 0'), ('c1', 'code', BODY), ('md', 'markdown', 'one\ntwo'), ('c3', 'code', 'w = 3'))]
    nb.write_text(json.dumps({'cells': cells, 'metadata': {'kernelspec': {'name': 'python3', 'display_name': 'Python 3', 'language': 'python'}},
                              'nbformat': 4, 'nbformat_minor': 5}))

    async def go(pg):
        await pg.evaluate('p => leeOpenFile(p)', str(nb))
        await pg.wait_for_function("() => lee.kind === 'notebook' && lee.editors.get('c1')")
        await pg.evaluate(SETUP)
        out = await _checks(pg, "lee.editors.get('c1')")
        try:
            await pg.evaluate("() => focusCell(2)"); await pg.keyboard.press('Enter')
            await pg.wait_for_function("() => document.querySelector('.lee-cell[data-id=\"md\"]').hasAttribute('data-md-edit')")
            await pg.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
            await pg.evaluate("() => { _use(lee.editors.get('md')); _at(1, 0); leeAct('add_cursor_below'); }")
            md = {'two': await pg.evaluate('_ranges().length')}
            edit = "() => [document.querySelector('.lee-cell[data-id=\"md\"]').hasAttribute('data-md-edit'), _ranges().length]"
            await pg.keyboard.press('Escape'); md['first'] = await pg.evaluate(edit)
            await pg.keyboard.press('Escape'); md['second'] = await pg.evaluate(edit)
        except Exception as e: md = f'error: {type(e).__name__}: {str(e).splitlines()[0]}'
        out['markdown'] = md
        return out
    got = _run(go, roots=[tmp_path], browser=browser)
    bad = _verdict(got, 1)
    if got['markdown'] != {'two': 2, 'first': [True, 1], 'second': [False, 1]}: bad.append('markdown_escape')
    assert not bad, json.dumps({'bad': bad, 'got': got})


@BROWSERS
def test_several_cursors_in_a_file_and_a_merge(tmp_path, browser):
    "The file editor and both sides of a merge kept one range; the file editor had no column mode."
    f = tmp_path/'f.py'; f.write_text(BODY + '\n')

    async def go(pg):
        await pg.evaluate('p => leeOpenFile(p)', str(f))
        await pg.wait_for_function("() => lee.editors.get('file') && LeeCM.getDoc(lee.editors.get('file')).startsWith('x = x')")
        await pg.evaluate(SETUP)
        out = await _checks(pg, "lee.editors.get('file')")
        out['merge'] = await pg.evaluate("""() => {
          const host = document.createElement('div'); document.body.appendChild(host);
          const m = LeeCM.createMerge(host, {left: 'a\\nb', right: 'a\\nb'}), S = m.b.state.selection.constructor;
          const two = v => (v.dispatch({selection: S.create([S.cursor(0), S.cursor(2)])}), v.state.selection.ranges.length);
          const r = [two(m.a), two(m.b)]; LeeCM.destroyMerge(m); host.remove(); return r;
        }""")
        return out
    got = _run(go, roots=[tmp_path], browser=browser)
    bad = _verdict(got)
    if got['merge'] != [2, 2]: bad.append('merge')
    assert not bad, json.dumps({'bad': bad, 'got': got})
