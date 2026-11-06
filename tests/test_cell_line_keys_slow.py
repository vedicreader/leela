"Inside a notebook cell's editor the line chords act on the line, the cell moves keep Alt+Shift+arrows, and `keys.json` rebinds the editing commands."

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
        await pg.keyboard.press(f'{mod}+Shift+D')
        out['duplicate'] = await pg.evaluate('({doc: _doc(), ids: lee.cells.map(c => c.id)})')
        await pg.evaluate("() => { LeeCM.setDoc(_v, 'x = x'); _at(1, 0); }")
        await pg.keyboard.press(f'{mod}+d')
        out['next'] = await pg.evaluate('({sel: _v.state.selection.ranges.map(r => [r.from, r.to]), action: lee.lastKeyEvent.action})')
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
          comment: _traps('cell_comment', {key: '/', code: 'Slash', altKey: true, ..._mod()}, _cm()),
          arrow_up: _traps('cell_move_up', {key: 'ArrowUp', code: 'ArrowUp', altKey: true, shiftKey: true}, _cm()),
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
        await pg.evaluate(f"() => {{ LeeCM.setDoc(_v, {json.dumps(BODY)}); _at(2); }}")
        await pg.keyboard.press('Alt+Shift+ArrowDown')
        await pg.wait_for_function("() => lee.cells[1]?.id === 'c1'")
        out['move'] = await pg.evaluate("""() => ({ids: lee.cells.map(c => c.id), doc: LeeCM.getDoc(lee.editors.get('c1')),
          focused: lee.editors.get('c1').hasFocus})""")
        return out
    got = _run(go, roots=[tmp_path])
    assert got['comment'] == 'a = 1\n# b = 2\nc = 3', 'comment toggled more than the cursor line'
    assert got['uncomment'] == BODY
    assert got['duplicate']['doc'] == 'a = 1\nb = 2\nb = 2\nc = 3' and got['duplicate']['ids'] == ['c1', 'c2'], got['duplicate']
    assert got['next'] == {'sel': [[0, 1]], 'action': 'select_next_occurrence'}, got['next']
    assert got['move']['ids'] == ['c2', 'c1'] and got['move']['doc'] == BODY, f'Alt+Shift+Down in a cell did not move it: {got["move"]}'
    assert got['move']['focused'], 'the moved cell lost the caret'
    assert got['copy_line']['text'].strip() == 'b = 2', got['copy_line']
    assert got['copy_sel']['text'] == BODY[2:8], got['copy_sel']
    for k in ('copy_line', 'copy_sel'):
        assert got[k]['key'] == {'prevented': False, 'action': ''}, f'{k}: the router took copy from the editor'
    assert got['cut_key'] == {'prevented': False, 'action': ''}, 'the router took cut from the editor'
    for name, r in got['edit_cell'].items():
        assert r['ran'] and r['prevented'], f'{name}: the cell-level chord does not answer while editing: {r}'
    for name, r in got['command'].items():
        assert r['ran'] and r['prevented'], f'{name}: the cell-level chord is gone in command mode: {r}'


def test_keys_json_swaps_the_editing_chords_inside_a_cell(tmp_path, monkeypatch):
    "CodeMirror's own keymap answered Cmd+D and Alt+Shift+Down, so `keys.json` could not move either."
    import leela.core.keys as keymap
    nb = tmp_path/'n.ipynb'; _nb(nb)
    over = tmp_path/'keys.json'
    over.write_text(json.dumps({'keys': {'copy_line_down': 'mod+d', 'select_next_occurrence': 'mod+shift+d'}}))
    # The watcher reloads from `keymap_path()`, so a file passed to `reload` alone is undone at the first poll.
    monkeypatch.setenv('LEELA_KEYMAP', str(over))
    keymap.reload(); notes = list(keymap.NOTES)

    async def go(pg):
        await pg.evaluate('p => leeOpenFile(p)', str(nb))
        await pg.wait_for_function("() => lee.kind === 'notebook' && lee.editors.get(lee.cells[0]?.id)")
        await pg.evaluate(SETUP)
        await pg.evaluate('_at(2)')
        await pg.keyboard.press('ControlOrMeta+d')
        dup = await pg.evaluate('_doc()')
        await pg.evaluate("() => { LeeCM.setDoc(_v, 'x = x'); _at(1, 0); }")
        await pg.keyboard.press('ControlOrMeta+Shift+D')
        return {'dup': dup, 'sel': await pg.evaluate('_v.state.selection.ranges.map(r => [r.from, r.to])')}
    try: got = _run(go, roots=[tmp_path])
    finally: keymap.reload(tmp_path/'gone.json')
    assert not notes, notes
    assert got == {'dup': 'a = 1\nb = 2\nb = 2\nc = 3', 'sel': [[0, 1]]}, got
