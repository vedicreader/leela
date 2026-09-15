"The keymap and the buttons and menus that name the same actions."

import json
import pytest
from fastcore.all import first
from leela.core.keys import (DEFAULTS, KEYS, apply_overrides, help_rows,
                        keymap_json, lookup, read_overrides, web_keymap)
from leela.core.ui import BARS, BUTTONS, bar, tip
from leela.blocks.keys.menus import MENUS, web_menus

def test_every_action_is_bound_reachable_and_documented():
    assert {k['action'] for k in web_keymap()} == {k.action for k in KEYS}
    labelled = {k.action for k in KEYS if k.label}
    shown = sum(len(rows) for rows in help_rows().values())
    assert shown == len(labelled)
    for action in ('complete', 'ai_complete', 'show_docs'):
        k = next(k for k in KEYS if k.action == action)
        assert k.scope == 'global', f'{action} is {k.scope}-scoped and cannot fire in the exec strip'
    known = {k.action for k in KEYS}
    assert not [b.action for b in BUTTONS if b.action not in known]
    runs = {'run_cell', 'run_advance', 'run_insert', 'exec_run', 'agent_send'}
    clickable = {b.action for b in BUTTONS}
    assert not (runs - clickable), f'run commands without buttons: {sorted(runs - clickable)}'
    t = tip('run_cell')
    assert 'run cell' in t and 'mod+enter' in t and 'f5' not in t
    # Named for where it runs: it is the one run command that is still the kernel, now that
    # running a script means a managed process with its own terminal.
    assert tip('run_selection') == 'run the selection in the kernel  (hyper+s)'
    known = {k.action for k in DEFAULTS}
    used = {item.action for rows in MENUS.values() for item in rows if item.action}
    assert not (used - known)
    rows = web_menus()['file']
    open_row = next(row for row in rows if row.get('action') == 'open')
    assert open_row['label'] == 'open / toggle folder'
    assert open_row['chord'] == 'enter'


def test_run_commands_follow_pycharm_jupyter_gestures_without_function_keys():
    "`mod` is Command in a Mac browser and Control in other browsers."
    expected = {'run_cell': 'mod+enter', 'run_advance': 'shift+enter',
                'run_insert': 'alt+enter', 'exec_run': 'mod+enter',
                'agent_send': 'mod+enter'}
    for action, chord in expected.items():
        k = next(k for k in KEYS if k.action == action)
        assert k.keys[0] == chord, f'{action} advertises {k.keys[0]} instead of {chord}'
    assert not [(k.action, c) for k in DEFAULTS for c in k.keys if c.startswith('f')]

def test_no_default_chord_lands_on_one_the_browser_will_not_deliver():
    assert lookup('cell_above').key == 'mod+alt+up'
    assert lookup('cell_below').key == 'mod+alt+down'
    reserved = {'ctrl+up', 'ctrl+down', 'ctrl+left', 'ctrl+right'}
    landed = [(k.action, c) for k in DEFAULTS for c in k.keys if c in reserved]
    assert not landed, f'these sit on a macOS-reserved chord: {landed}'
    chords = [(k.action, c) for k in DEFAULTS for c in k.keys]
    assert not [(a, c) for a, c in chords if c.startswith('ctrl+alt+')]
    assert not [(a, c) for a, c in chords if c.startswith('f')]
    row = next(r for r in web_keymap() if r['action'] == 'run_above')
    chord = row['chords'][0]
    assert chord['hyper'] and all(chord[x] for x in ('mod', 'ctrl', 'alt', 'shift'))
    assert lookup('run_above').key == 'hyper+enter'
    assert 'hyper+r' in lookup('restart').keys
    by_action = {k.action: k.key for k in DEFAULTS}
    assert by_action['new_file'] == 'n'
    assert by_action['new_dir'] == 'N'
    assert 'ctrl+n' not in (by_action['new_file'], by_action['new_dir'])


def test_definition_clipboard_and_notebook_navigation_use_practical_chords():
    assert lookup('find_definition').key == 'mod+b'
    assert lookup('cell_copy').key == 'mod+c'
    assert lookup('cell_cut').key == 'mod+x'
    assert lookup('cell_first').key == 'mod+home'
    assert lookup('cell_last').key == 'mod+end'
    assert lookup('cell_page_up').key == 'alt+pageup'
    assert lookup('cell_page_down').key == 'alt+pagedown'


def test_pycharm_notebook_actions_are_bound_and_discoverable():
    expected = {
        'run_advance': 'shift+enter', 'run_insert': 'alt+enter',
        'cell_select_above': 'ctrl+shift+up', 'cell_select_below': 'ctrl+shift+down',
        'cell_move_up': 'alt+shift+up', 'cell_move_down': 'alt+shift+down',
    }
    assert {a: lookup(a).key for a in expected} == expected
    assert lookup('complete').keys[0] == 'alt+/'
    assert lookup('settings').key == 'mod+,', 'settings use the platform-standard preferences chord'


def _keymap(tmp_path, d):
    p = tmp_path / 'keys.json'
    p.write_text(json.dumps(d))
    return p

def test_a_user_keymap_replaces_the_chord_and_leaves_the_rest(tmp_path):
    p = _keymap(tmp_path, {'keys': {'run_cell': 'ctrl+y f5', 'quit': ''}})
    ks = apply_overrides(DEFAULTS, read_overrides(p, notes=[]), notes=[])
    by = {k.action: k for k in ks}
    assert by['run_cell'].keys == ['ctrl+y', 'f5']
    assert by['quit'].keys == [] and not by['quit'].bound
    assert by['save'].key == lookup('save').key

def test_a_broken_entry_costs_that_entry_and_nothing_else(tmp_path):
    "One typo must not throw the file away, and must not be silent either."
    p = _keymap(tmp_path, {'run_cell': 'ctrl+y', 'nope': 'ctrl+q',
                           'save': 'ctrl+bogus+s', 'focus_files': 'alt+shift+3'})
    notes = []
    ks = apply_overrides(DEFAULTS, read_overrides(p, notes=notes), notes=notes)
    by = {k.action: k for k in ks}
    assert by['run_cell'].keys[0] == 'ctrl+y'
    assert by['save'].key == lookup('save').key
    assert by['focus_files'].key == 'alt+shift+1'
    assert len(notes) == 3 and all(isinstance(n, str) and n for n in notes)

def test_a_rejected_override_does_not_leak_into_the_defaults(tmp_path):
    "The trial map is a copy: a refused entry must not still be sitting in the table it was tried."
    p = _keymap(tmp_path, {'focus_files': 'alt+shift+3'})
    apply_overrides(DEFAULTS, read_overrides(p, notes=[]), notes=[])
    assert lookup('focus_files').key == 'alt+shift+1'
    assert {k.action: k.key for k in DEFAULTS}['focus_files'] == 'alt+shift+1'

def test_an_unreadable_keymap_is_a_note_not_a_crash(tmp_path):
    "A config file that cannot be parsed must never be able to stop the IDE from starting."
    p = tmp_path / 'keys.json'
    p.write_text('{oops')
    notes = []
    assert read_overrides(p, notes=notes) == {}
    assert len(notes) == 1 and str(p) in notes[0]
    assert read_overrides(tmp_path / 'nothing-here.json', notes=notes) == {}
    assert len(notes) == 1, 'a missing file is the normal case, not a problem'

def test_the_written_template_reproduces_the_map(tmp_path):
    "What `--write-keymap` writes, read back, is the map it was written from."
    p = tmp_path / 'keys.json'
    for over in ({}, {'run_cell': 'ctrl+y', 'quit': 'hyper+q', 'save': ''}):
        want = apply_overrides(DEFAULTS, over, notes=[])
        p.write_text(json.dumps(keymap_json(want)))
        ks = apply_overrides(DEFAULTS, read_overrides(p, notes=[]), notes=[])
        assert {k.action: k.key for k in ks} == {k.action: k.key for k in want}

def _written(path, keys=None, keep=True):
    from leela.core.keys import write_keymap
    write_keymap(path, keys=keys, keep=keep)
    return json.loads(path.read_text())

def test_a_written_keymap_holds_only_what_a_person_changed(tmp_path):
    """`--write-keymap` used to dump all ~160 chords."""
    d = _written(tmp_path/'keys.json', keys=DEFAULTS)
    assert d['keys'] == {}
    ks = apply_overrides(DEFAULTS, {'run_cell': 'ctrl+y', 'save': ''}, notes=[])
    d = _written(tmp_path/'changed.json', keys=ks)
    assert d['keys'] == {'run_cell': 'ctrl+y', 'save': ''}

def test_an_unbound_action_is_an_override_and_not_an_empty_one(tmp_path):
    "`\"\"` unbinds, so a falsy check would drop the one entry the file exists to carry."
    p = tmp_path/'keys.json'
    ks = apply_overrides(DEFAULTS, {'save': ''}, notes=[])
    assert _written(p, keys=ks)['keys'] == {'save': ''}
    back = apply_overrides(DEFAULTS, read_overrides(p, notes=[]), notes=[])
    assert not first(back.filter(lambda k: k.action == 'save')).bound
    assert _written(p, keys=DEFAULTS)['keys'] == {'save': ''}, 'and it survives a second write'

def test_the_action_names_stay_discoverable_without_binding_anything(tmp_path):
    "A near-empty file still has to tell a person what there is to rebind."
    p = tmp_path/'keys.json'
    d = _written(p, keys=DEFAULTS)
    assert d['_defaults'] == {k.action: k.key for k in DEFAULTS}
    assert read_overrides(p, notes=[]) == {}, '`_defaults` is a reference, never an override'

def test_a_chord_a_person_typed_survives_a_rewrite_even_when_it_equals_the_default(tmp_path):
    "Writing over a hand-written file must not silently drop what is in it."
    p = tmp_path/'keys.json'
    p.write_text(json.dumps({'keys': {'save': lookup('save').key, 'run_cell': 'ctrl+y'}}))
    assert _written(p, keys=DEFAULTS)['keys'] == {'save': lookup('save').key, 'run_cell': 'ctrl+y'}

def test_a_full_dump_is_pruned_and_what_it_replaced_is_kept(tmp_path):
    "The file the old writer left behind is the one that has to be repaired, and backed up first."
    from leela.core.backups import backup_dir
    p = tmp_path/'keys.json'
    p.write_text(json.dumps({'_help': keymap_json()['_help'],
                             'keys': {k.action: k.key for k in DEFAULTS}}))
    assert _written(p, keys=DEFAULTS)['keys'] == {}
    assert len(list((backup_dir()/'guard').glob('keys.json.*'))) == 1

def test_a_keymap_written_before_a_default_moved_does_not_collide_after_it(tmp_path):
    """`add_root` moved from `o` to `O` and `open_folder` took `o`."""
    from dataclasses import replace
    from fastcore.all import L
    import leela.core.keys as K
    was = L([replace(k, key='o') if k.action == 'add_root' else k
             for k in DEFAULTS if k.action != 'open_folder'])
    p = tmp_path/'keys.json'
    p.write_text(json.dumps({'_help': keymap_json()['_help'],
                             'keys': {k.action: k.key for k in was}}))
    notes = []
    apply_overrides(DEFAULTS, read_overrides(p, notes=notes), notes=notes)
    assert [n for n in notes if 'add_root' in n], 'the old full dump is what collides'
    keep = K.DEFAULTS
    K.DEFAULTS = was
    try: K.write_keymap(p, keys=was)
    finally: K.DEFAULTS = keep
    assert json.loads(p.read_text())['keys'] == {}
    notes = []
    ks = apply_overrides(DEFAULTS, read_overrides(p, notes=notes), notes=notes)
    assert notes == []
    assert {k.action: k.key for k in ks}['add_root'] == 'O'

def test_reset_empties_the_overrides_and_the_defaults_come_back(tmp_path, monkeypatch):
    "Reset is the recovery path, so what it writes has to leave nothing behind."
    import leela.core.keys as K
    p = tmp_path/'keys.json'
    p.write_text(json.dumps({'keys': {'save': 'ctrl+y'}}))
    monkeypatch.setenv('LEELA_KEYMAP', str(p))
    K.reload()
    assert K.lookup('save').key == 'ctrl+y'
    K.write_keymap(keys=K.DEFAULTS, keep=False)
    assert json.loads(p.read_text())['keys'] == {}
    K.reload()
    assert {k.action: k.key for k in K.KEYS} == {k.action: k.key for k in K.DEFAULTS}
    assert K.NOTES == []

def test_the_keys_panel_saves_the_overrides_and_not_a_copy_of_every_chord():
    "The panel's save was the third full-dump writer, and the bundle is what the browser runs."
    from tests.assets import JS as js
    assert 'const merged = ' in js and 'JSON.stringify({keys: merged()}' in js
    assert "post('/keys/check', {keys: merged()})" in js, 'the check sees what the save will write'
    assert 'if (r.overrides) d.overrides = r.overrides;' in js, 'a reset is not undone by a save'


@pytest.mark.parametrize('name', BARS)
def test_every_bar_has_buttons(name):
    "A declared bar that renders empty is a hole in a toolbar someone is looking at."
    assert len(bar(name)) > 0


def test_project_roots_are_removed_from_the_workspace_not_deleted_from_disk():
    root_actions = [row.action for row in MENUS['root'] if row.action]
    assert 'remove_root' in root_actions
    assert 'delete' not in root_actions

def test_cell_menu_exposes_cross_notebook_clipboard_without_stealing_text_shortcuts():
    "All four are menu actions; copy/cut additionally carry the standard chords."
    actions = [row.action for row in MENUS['cell'] if row.action]
    for action in ('cell_copy', 'cell_cut', 'cell_paste_above', 'cell_paste_below'):
        assert action in actions
    by_action = {k.action: k.key for k in DEFAULTS}
    assert by_action['cell_paste_above'] == '' and by_action['cell_paste_below'] == ''
    assert by_action['cell_copy'] == 'mod+c' and by_action['cell_cut'] == 'mod+x'
    from tests.assets import JS as js
    assert "['cell_copy', 'cell_cut'].includes(k.action)" in js
    assert "lee.kind !== 'notebook'" in js
    assert 'selection?.from !== selection?.to' in js


def test_cmd_z_is_notebook_undo_and_the_old_chord_migrates():
    """Deleting a cell was not undoable by the key everyone presses: `mod+alt+z` was the only way and nobody found it."""
    from leela.core import keys as K
    by = {k.action: k for k in K.KEYS}
    assert by['notebook_undo'].key == 'mod+z' and by['notebook_redo'].key == 'mod+shift+z'
    assert K._SNAPSHOT_MIGRATIONS['notebook_undo'] == ('mod+alt+z', 'mod+z')
    kept = K._migrated({'notebook_undo': 'mod+alt+z', 'notebook_redo': 'hyper+u'},
                       K._SNAPSHOT_MIGRATIONS)
    assert kept['notebook_undo'] == 'mod+z', 'the old default moves'
    assert kept['notebook_redo'] == 'hyper+u', 'a chord somebody chose is left alone'

def test_the_document_undoes_first_and_the_notebook_after():
    """`mod+z` in a cell is CodeMirror's history until that runs out, and the cell operation after."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1]/'leela'/'blocks'/'keys'/'keymap.js').read_text()
    assert 'notebook_undo:' in src and 'notebook_redo:' in src, 'both chords route through it'
    body = src[src.index("window.addEventListener('keydown'"):]
    # The document is asked first, and only a False answer reaches the action.
    assert body.index('LeeCM[cmd](view)') < body.index('leeAct(match.binding.action)')

def test_indent_is_named_so_it_reaches_the_palette_and_the_help():
    """The three indent commands worked, because CodeMirror's `defaultKeymap` binds them, and were in neither the palette nor the keys help because nothing named them."""
    assert lookup('indent_more').key == 'mod+]'
    assert lookup('indent_less').key == 'mod+['
    assert lookup('indent_selection').key == 'hyper+]'
    for action in ('indent_more', 'indent_less', 'indent_selection'):
        k = lookup(action)
        assert k.scope == 'editor', f'{action} is {k.scope}: indent only means anything in a document'
        assert k.label, 'the palette lists labelled keys, so an unlabelled one is unreachable'
    # The chords the tab strip and the terminal already own are the neighbouring brackets.
    assert lookup('next_tab').key == 'alt+]' and lookup('prev_tab').key == 'alt+['

def test_undo_is_reachable_on_the_editor_bundle():
    "The router calls it, so the vendored build has to export it. It did not before."
    from tests.assets import cm_exports
    names = cm_exports()
    assert {'undo', 'redo'} <= names, 'rebuild frontend/editor.js with esbuild'
    assert {'create', 'getDoc', 'focus', 'selection'} <= names, 'and nothing else was dropped'

def test_reload_from_disk_is_reachable_without_a_chord():
    """Every `takeDiskVersion` call sat behind some other flow, so a tab showing a version that had moved on had no command to fix it."""
    k = lookup('reload_file')
    assert k.label == 'reload from disk' and k.scope == 'global'
    assert k.key == '', 'it is a menu and palette command; a default chord would need an audit'
    assert 'reload_file' in {r['action'] for r in web_menus()['tab'] if r.get('action')}
    from leela.blocks.keys.menus import BAR, MenuItem
    files = first(rows for name, rows in BAR if name == 'File')
    assert 'reload_file' in {r.action for r in files if isinstance(r, MenuItem) and r.action}
