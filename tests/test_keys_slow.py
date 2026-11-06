"Keys v2 in a real page: the overlay keeps menu chords from running behind it, ⌘N and ⌘W, command-mode letters, old chords and the recorder."

import asyncio, json

import pytest

pytestmark = pytest.mark.slow

pytest.importorskip('playwright.async_api')

from test_completion_caret_slow import _real_page   # noqa: E402

MOD = 'ControlOrMeta'

WATCH = r"""() => {
  window._seen = [];
  addEventListener('keydown', e => _seen.push({code: e.code, prevented: e.defaultPrevented, action: lee.lastKeyEvent.action}));
  window._ran = [];
  for (const a of ['quick_open', 'new_file', 'tree_new_file', 'close_tab', 'toggle_scope', 'cell_below', 'cell_delete'])
    { const f = ACTIONS[a]; ACTIONS[a] = (...x) => { _ran.push(a); return f(...x); }; }
  window.inputDialog = async () => `made${_ran.length}.py`;
}"""

def _nb(path):
    cells = [{'cell_type': 'code', 'id': i, 'metadata': {}, 'execution_count': None, 'outputs': [], 'source': s}
             for i, s in (('c1', 'a = 1'), ('c2', 'z = 0'))]
    meta = {'kernelspec': {'name': 'python3', 'display_name': 'Python 3', 'language': 'python'}}
    path.write_text(json.dumps({'cells': cells, 'metadata': meta, 'nbformat': 4, 'nbformat_minor': 5}))

async def _last(pg): return await pg.evaluate('() => _seen.at(-1)')

def test_an_open_palette_swallows_a_menu_chord_and_runs_nothing_behind_it(tmp_path):
    "⌘P with the palette open ran Open File behind it: the page handled no key, so the Mac menu row ran."
    async def go(pg):
        await pg.evaluate(WATCH)
        await pg.evaluate("() => leeAct('palette')")
        await pg.wait_for_selector('#cp')
        await pg.keyboard.press(f'{MOD}+P')
        await pg.wait_for_timeout(200)
        return {'last': await _last(pg), 'ran': await pg.evaluate('() => _ran'), 'modals': await pg.evaluate("() => $$('.lee-modal').length"),
                'chords': await pg.evaluate('() => lee.menuChords.length')}
    got = asyncio.run(_real_page(go, tmp_path))
    assert got['chords'] > 20
    assert got['last']['prevented'] and 'quick_open' not in got['ran'] and got['modals'] == 1, got

def test_new_file_takes_mod_n_from_the_editor_and_from_the_files_panel(tmp_path):
    (tmp_path/'a.py').write_text('x = 1\n')
    async def go(pg):
        await pg.evaluate(WATCH)
        await pg.evaluate('p => leeOpenFile(p)', str(tmp_path/'a.py'))
        await pg.wait_for_selector('#filecm .cm-content')
        await pg.click('#filecm .cm-content')
        await pg.evaluate("() => $$('.lee-node.sel').forEach(n => n.classList.remove('sel'))")
        await pg.keyboard.press(f'{MOD}+N')
        await pg.wait_for_function("() => _ran.includes('new_file')")
        await pg.wait_for_timeout(500)
        await pg.evaluate("() => leeAct('focus_files')")
        await pg.keyboard.press(f'{MOD}+Alt+Shift+N')   # the chord a Chrome tab gets
        await pg.wait_for_function("() => _ran.filter(a => a === 'new_file').length === 2")
        await pg.wait_for_timeout(500)
        await pg.evaluate("() => leeAct('focus_files')")
        await pg.keyboard.press('n')
        await pg.wait_for_function("() => _ran.includes('tree_new_file')")
        await pg.wait_for_timeout(500)
        return await pg.evaluate('() => _ran')
    ran = asyncio.run(_real_page(go, tmp_path))
    made = sorted(p.name for p in tmp_path.glob('made*.py'))
    assert len(made) == 3, (made, ran)

def test_mod_w_closes_a_tab_and_leaves_the_window_to_close_when_none_is_open(tmp_path):
    (tmp_path/'a.py').write_text('x = 1\n'); (tmp_path/'b.py').write_text('y = 2\n')
    async def go(pg):
        await pg.evaluate(WATCH)
        for f in ('a.py', 'b.py'):
            await pg.evaluate('p => leeOpenFile(p)', str(tmp_path/f))
            await pg.wait_for_function(f"() => $$('.lee-tab').length >= {1 + (f == 'b.py')}")
        await pg.click('#filecm .cm-content')
        await pg.keyboard.press(f'{MOD}+W')
        await pg.wait_for_function("() => $$('.lee-tab').length === 1")
        await pg.click('#filecm .cm-content')
        await pg.keyboard.press('Alt+W')
        await pg.wait_for_function("() => $$('.lee-tab').length === 0")
        return await pg.evaluate("""() => { const e = new KeyboardEvent('keydown', {key: 'w', code: 'KeyW', metaKey: MAC, ctrlKey: !MAC, bubbles: true, cancelable: true});
          document.body.dispatchEvent(e); return {prevented: e.defaultPrevented, ran: _ran}; }""")
    got = asyncio.run(_real_page(go, tmp_path))
    assert got['ran'].count('close_tab') == 2 and not got['prevented'], got

def test_notebook_command_mode_letters_insert_and_delete_cells(tmp_path):
    "Jupyter's letters: Escape leaves the cell editor, `b` inserts below, `d d` deletes, and a letter typed in a cell stays text."
    nb = tmp_path/'n.ipynb'; _nb(nb)
    async def go(pg):
        await pg.evaluate(WATCH)
        await pg.evaluate('p => leeOpenFile(p)', str(nb))
        await pg.wait_for_function("() => lee.kind === 'notebook' && lee.editors.get(lee.cells[0]?.id)")
        await pg.evaluate('() => focusCell(0)')
        await pg.wait_for_timeout(200)
        await pg.keyboard.type('b')
        typed = await pg.evaluate("() => LeeCM.getDoc(lee.editors.get('c1'))")
        await pg.keyboard.press('Escape')
        await pg.keyboard.press('b')
        await pg.wait_for_function('() => lee.cells.length === 3')
        await pg.evaluate("() => document.activeElement?.blur()")
        await pg.keyboard.press('d')
        once = await pg.evaluate('() => lee.cells.length')
        await pg.keyboard.press('d')
        await pg.wait_for_function('() => lee.cells.length === 2')
        return {'typed': typed, 'once': once, 'ran': await pg.evaluate('() => _ran')}
    got = asyncio.run(_real_page(go, tmp_path))
    assert got['typed'].startswith('b') or got['typed'].endswith('b'), got
    assert got['once'] == 3 and got['ran'].count('cell_below') == 1 and got['ran'].count('cell_delete') == 1, got

def test_an_old_chord_runs_its_action_and_says_the_new_one(tmp_path):
    (tmp_path/'a.py').write_text('x = 1\n')
    async def go(pg):
        await pg.evaluate(WATCH)
        await pg.evaluate("() => document.activeElement?.blur()")
        was = await pg.evaluate('() => lee.execScope')
        await pg.keyboard.press('Alt+I')
        await pg.wait_for_function("() => _ran.includes('toggle_scope')")
        return {'was': was, 'now': await pg.evaluate('() => lee.execScope'), 'status': await pg.evaluate("() => $('#status')?.textContent || ''"),
                'leaked': await pg.evaluate("() => _seen.some(e => e.code === 'KeyI')")}
    got = asyncio.run(_real_page(go, tmp_path))
    assert got['was'] != got['now'] and not got['leaked'] and got['status'] == '⌥I is now ⌥T', got

def test_the_recorder_writes_the_physical_key_and_the_page_shows_glyphs(tmp_path):
    "Recording Option+W on a Mac wrote `alt+∑`, and the help showed `alt+shift+b` where the menu showed ⌥⇧B."
    async def go(pg):
        return await pg.evaluate("""() => ({
          w: chordFromEvent(new KeyboardEvent('keydown', {key: '∑', code: 'KeyW', altKey: true})),
          dead: chordFromEvent(new KeyboardEvent('keydown', {key: 'Dead', code: 'KeyE', altKey: true})),
          q: chordFromEvent(new KeyboardEvent('keydown', {key: '?', code: 'Slash', shiftKey: true})),
          glyph: displayChord('alt+shift+b / mod+shift+p'), mac: MAC})""")
    got = asyncio.run(_real_page(go, tmp_path))
    assert got['w'] == 'alt+w' and got['dead'] == 'alt+e' and got['q'] == 'shift+/', got
    assert got['glyph'] == ('⌥⇧B / ⇧⌘P' if got['mac'] else 'Alt+Shift+B / Ctrl+Shift+P'), got
