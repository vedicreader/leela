"Inside a notebook cell's editor the line chords act on the line; the cell-level versions answer in command mode and on their own chords."

import json

import pytest

pytestmark = pytest.mark.slow

pytest.importorskip('playwright.async_api')

from test_web_slow import _run   # noqa: E402

BODY = 'a = 1\nb = 2\nc = 3'

SETUP = r"""() => {
  window._v = lee.editors.get(lee.cells[0].id);
  window._at = (n, col = 1) => { const l = _v.state.doc.line(n); _v.focus(); _v.dispatch({selection: {anchor: l.from + col}}); };
  window._doc = () => LeeCM.getDoc(_v);
  window._mod = () => ({metaKey: MAC, ctrlKey: !MAC});
  window._cm = () => document.querySelector('.lee-cell .cm-content');
  window._press = (init, target) => {
    const e = new KeyboardEvent('keydown', {bubbles: true, cancelable: true, composed: true, ...init});
    target.dispatchEvent(e); return {prevented: e.defaultPrevented, action: lee.lastKeyEvent.action};
  };
  window._traps = (name, init, target) => {
    let ran = false; const orig = ACTIONS[name]; ACTIONS[name] = () => { ran = true; };
    const r = _press(init, target); ACTIONS[name] = orig; return {ran, ...r};
  };
  window._copied = () => {
    const dt = new DataTransfer();
    _cm().dispatchEvent(new ClipboardEvent('copy', {clipboardData: dt, bubbles: true, cancelable: true}));
    return dt.getData('text/plain');
  };
}"""


def _nb(path):
    cells = [{'cell_type': 'code', 'id': i, 'metadata': {}, 'execution_count': None, 'outputs': [], 'source': s}
             for i, s in (('c1', BODY), ('c2', 'z = 0'))]
    meta = {'kernelspec': {'name': 'python3', 'display_name': 'Python 3', 'language': 'python'}}
    path.write_text(json.dumps({'cells': cells, 'metadata': meta, 'nbformat': 4, 'nbformat_minor': 5}))


def test_a_cell_editor_takes_line_chords_and_the_cell_versions_keep_their_own(tmp_path):
    """Copy, cut, comment and copy-line-down acted on the whole cell, because the router took the chords before the editor saw them."""
    nb = tmp_path/'n.ipynb'; _nb(nb)

    async def go(pg):
        out = {}
        await pg.evaluate('p => leeOpenFile(p)', str(nb))
        await pg.wait_for_function("() => lee.kind === 'notebook' && lee.editors.get(lee.cells[0]?.id)")
        await pg.evaluate(SETUP)
        mod = 'ControlOrMeta'
        await pg.evaluate('_at(2)')
        await pg.keyboard.press(f'{mod}+/')
        out['comment'] = await pg.evaluate('_doc()')
        await pg.keyboard.press(f'{mod}+/')
        out['uncomment'] = await pg.evaluate('_doc()')
        await pg.evaluate('_at(2)')
        await pg.keyboard.press('Alt+Shift+ArrowDown')
        out['duplicate'] = await pg.evaluate('({doc: _doc(), ids: lee.cells.map(c => c.id)})')
        await pg.evaluate("() => { LeeCM.setDoc(_v, 'a = 1\\nb = 2\\nc = 3'); _at(2); }")
        out['copy_line'] = await pg.evaluate("() => ({text: _copied(), key: _press({key: 'c', code: 'KeyC', ..._mod()}, _cm())})")
        out['copy_sel'] = await pg.evaluate("""() => {
          _v.dispatch({selection: {anchor: 2, head: 8}});
          return {text: _copied(), key: _press({key: 'c', code: 'KeyC', ..._mod()}, _cm())};
        }""")
        out['cut_key'] = await pg.evaluate("() => _press({key: 'x', code: 'KeyX', ..._mod()}, _cm())")
        await pg.evaluate('_at(2)')
        out['edit_cell'] = await pg.evaluate("""() => ({
          copy: _traps('cell_copy', {key: 'C', code: 'KeyC', shiftKey: true, ..._mod()}, _cm()),
          cut: _traps('cell_cut', {key: 'X', code: 'KeyX', shiftKey: true, ..._mod()}, _cm()),
          comment: _traps('cell_comment', {key: '/', code: 'Slash', ctrlKey: true, altKey: true, shiftKey: true}, _cm()),
          up: _traps('cell_move_up', {key: 'PageUp', code: 'PageUp', altKey: true, shiftKey: true}, _cm()),
          down: _traps('cell_move_down', {key: 'PageDown', code: 'PageDown', altKey: true, shiftKey: true}, _cm())})""")
        out['command'] = await pg.evaluate("""() => {
          document.activeElement.blur();
          const head = document.querySelector('.lee-cell');
          return {
            copy: _traps('cell_copy', {key: 'c', code: 'KeyC', ..._mod()}, head),
            cut: _traps('cell_cut', {key: 'x', code: 'KeyX', ..._mod()}, head),
            comment: _traps('comment', {key: '/', code: 'Slash', ..._mod()}, head),
            down: _traps('cell_move_down', {key: 'ArrowDown', code: 'ArrowDown', altKey: true, shiftKey: true}, head)};
        }""")
        return out
    got = _run(go, roots=[tmp_path])
    assert got['comment'] == 'a = 1\n# b = 2\nc = 3', 'comment toggled more than the cursor line'
    assert got['uncomment'] == BODY
    assert got['duplicate']['doc'] == 'a = 1\nb = 2\nb = 2\nc = 3' and got['duplicate']['ids'] == ['c1', 'c2'], got['duplicate']
    assert got['copy_line']['text'].strip() == 'b = 2', got['copy_line']
    assert got['copy_sel']['text'] == BODY[2:8], got['copy_sel']
    for k in ('copy_line', 'copy_sel'):
        assert got[k]['key'] == {'prevented': False, 'action': ''}, f'{k}: the router took copy from the editor'
    assert got['cut_key'] == {'prevented': False, 'action': ''}, 'the router took cut from the editor'
    for name, r in got['edit_cell'].items():
        assert r['ran'] and r['prevented'], f'{name}: the cell-level chord does not answer while editing: {r}'
    for name, r in got['command'].items():
        assert r['ran'] and r['prevented'], f'{name}: the cell-level chord is gone in command mode: {r}'
