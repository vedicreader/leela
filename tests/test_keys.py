"The keymap and the buttons and menus that name the same actions."

import json
import pytest
from leela.core import keys as K
from leela.core.keys import (DEFAULTS, KEYS, apply_overrides, help_rows,
                        keymap_json, lookup, read_overrides, web_keymap)
from leela.core.ui import BARS, BUTTONS, bar, tip
from leela.core.keys import KEYS
from leela.core.keys import DEFAULTS
from leela.blocks.keys.menus import MENUS, web_menus

def test_web_keymap_contains_every_action():
    assert {k['action'] for k in web_keymap()} == {k.action for k in KEYS}

def test_help_covers_every_labelled_binding():
    "f1 is generated, so a new binding shows up there without anyone remembering to add it."
    labelled = {k.action for k in KEYS if k.label}
    shown = sum(len(rows) for rows in help_rows().values())
    assert shown == len(labelled)

def test_completions_and_docs_reach_the_exec_strip():
    "`complete`, `ai_complete` and `show_docs` resolve the cursor from whichever editor"
    for action in ('complete', 'ai_complete', 'show_docs'):
        k = next(k for k in KEYS if k.action == action)
        assert k.scope == 'global', f'{action} is {k.scope}-scoped and cannot fire in the exec strip'

def test_run_commands_follow_pycharm_jupyter_gestures_without_function_keys():
    "`mod` is Command in a Mac browser and Control in other browsers."
    expected = {'run_cell': 'mod+enter', 'run_advance': 'shift+enter',
                'run_insert': 'alt+enter', 'exec_run': 'mod+enter',
                'agent_send': 'mod+enter'}
    for action, chord in expected.items():
        k = next(k for k in KEYS if k.action == action)
        assert k.keys[0] == chord, f'{action} advertises {k.keys[0]} instead of {chord}'
    assert not [(k.action, c) for k in DEFAULTS for c in k.keys if c.startswith('f')]

def test_cell_insertion_uses_platform_mod_instead_of_macos_control_option_arrows():
    assert lookup('cell_above').key == 'mod+alt+up'
    assert lookup('cell_below').key == 'mod+alt+down'

def test_definition_clipboard_and_notebook_navigation_use_practical_chords():
    assert lookup('find_definition').key == 'mod+b'
    assert lookup('cell_copy').key == 'mod+c'
    assert lookup('cell_cut').key == 'mod+x'
    assert lookup('cell_first').key == 'mod+home'
    assert lookup('cell_last').key == 'mod+end'
    assert lookup('cell_page_up').key == 'alt+pageup'
    assert lookup('cell_page_down').key == 'alt+pagedown'

def test_no_binding_lands_on_a_macos_reserved_chord():
    "macOS grabs a handful of Ctrl chords before any app -- terminal or browser -- so a"
    reserved = {'ctrl+up', 'ctrl+down', 'ctrl+left', 'ctrl+right'}
    landed = [(k.action, c) for k in DEFAULTS for c in k.keys if c in reserved]
    assert not landed, f'these sit on a macOS-reserved chord: {landed}'

def test_defaults_avoid_altgr_and_function_key_fallbacks():
    chords = [(k.action, c) for k in DEFAULTS for c in k.keys]
    assert not [(a, c) for a, c in chords if c.startswith('ctrl+alt+')]
    assert not [(a, c) for a, c in chords if c.startswith('f')]

def test_pycharm_notebook_actions_are_bound_and_discoverable():
    expected = {
        'run_advance': 'shift+enter', 'run_insert': 'alt+enter',
        'cell_select_above': 'ctrl+shift+up', 'cell_select_below': 'ctrl+shift+down',
        'cell_move_up': 'alt+shift+up', 'cell_move_down': 'alt+shift+down',
    }
    assert {a: lookup(a).key for a in expected} == expected
    assert lookup('complete').keys[0] == 'alt+/'
    assert lookup('settings').key == 'mod+,', 'settings use the platform-standard preferences chord'

def test_hyper_unlocks_dense_caps_lock_shortcuts():
    "Hyper is Command+Control+Option+Shift on the web."
    row = next(r for r in web_keymap() if r['action'] == 'run_above')
    chord = row['chords'][0]
    assert chord['hyper'] and all(chord[x] for x in ('mod', 'ctrl', 'alt', 'shift'))
    assert lookup('run_above').key == 'hyper+enter'
    assert 'hyper+r' in lookup('restart').keys

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
    p.write_text(json.dumps(keymap_json()))
    ks = apply_overrides(DEFAULTS, read_overrides(p, notes=[]), notes=[])
    assert {k.action: k.key for k in ks} == {k.action: k.key for k in KEYS}

def test_every_button_names_a_real_action():
    "A button wired to nothing is worse than no button: it looks like the feature exists."
    known = {k.action for k in KEYS}
    assert not [b.action for b in BUTTONS if b.action not in known]

@pytest.mark.parametrize('name', BARS)
def test_every_bar_has_buttons(name):
    "A declared bar that renders empty is a hole in a toolbar someone is looking at."
    assert len(bar(name)) > 0

def test_run_commands_have_buttons_as_well_as_function_keys():
    "The function keys are reliable, but every run command remains directly clickable."
    runs = {'run_cell', 'run_advance', 'run_insert', 'exec_run', 'agent_send'}
    clickable = {b.action for b in BUTTONS}
    assert not (runs - clickable), f'run commands without buttons: {sorted(runs - clickable)}'

def test_a_tooltip_says_what_it_does_and_which_key_does_it():
    "Hovering is how the keys get discovered, so the chord travels with the button."
    t = tip('run_cell')
    assert 'run cell' in t and 'mod+enter' in t and 'f5' not in t
    assert tip('run_selection') == 'run the selection  (hyper+s)'

def test_every_menu_action_is_declared_once_in_the_keymap():
    known = {k.action for k in DEFAULTS}
    used = {item.action for rows in MENUS.values() for item in rows if item.action}
    assert not (used - known)

def test_menu_labels_and_chords_come_from_the_keymap():
    rows = web_menus()['file']
    open_row = next(row for row in rows if row.get('action') == 'open')
    assert open_row['label'] == 'open / toggle folder'
    assert open_row['chord'] == 'enter'

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
    from pathlib import Path
    from tests.assets import JS as js
    assert "['cell_copy', 'cell_cut'].includes(k.action)" in js
    assert "lee.kind !== 'notebook'" in js
    assert 'selection?.from !== selection?.to' in js

def test_new_entry_defaults_are_browser_safe_contextual_letters():
    by_action = {k.action: k.key for k in DEFAULTS}
    assert by_action['new_file'] == 'n'
    assert by_action['new_dir'] == 'N'
    assert 'ctrl+n' not in (by_action['new_file'], by_action['new_dir'])
