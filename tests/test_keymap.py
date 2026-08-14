"""Tests for the browser keymap and user overrides."""

import json
import pytest

from leela.core import keys as K
from leela.core.keys import (DEFAULTS, KEYS, apply_overrides, help_rows,
                        keymap_json, lookup, read_overrides, web_keymap)


def test_web_keymap_contains_every_action():
    assert {k['action'] for k in web_keymap()} == {k.action for k in KEYS}


def test_help_covers_every_labelled_binding():
    "f1 is generated, so a new binding shows up there without anyone remembering to add it."
    labelled = {k.action for k in KEYS if k.label}
    shown = sum(len(rows) for rows in help_rows().values())
    assert shown == len(labelled)


def test_completions_and_docs_reach_the_exec_strip():
    """`complete`, `ai_complete` and `show_docs` resolve the cursor from whichever editor
    holds it, so they must be global -- an editor-scoped binding can never fire in the
    exec strip, whatever its handler is willing to do."""
    for action in ('complete', 'ai_complete', 'show_docs'):
        k = next(k for k in KEYS if k.action == action)
        assert k.scope == 'global', f'{action} is {k.scope}-scoped and cannot fire in the exec strip'


def test_run_commands_follow_pycharm_jupyter_gestures_without_function_keys():
    """`mod` is Command in a Mac browser and Control in other browsers."""
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
    """macOS grabs a handful of Ctrl chords before any app -- terminal or browser -- so a
    binding on one is dead on a Mac in *both* frontends, not merely inconvenient. Mission
    Control (ctrl+up/down) and Space switching (ctrl+left/right) are the ones a dev hits."""
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


# ---- the user's own keymap ------------------------------------------------
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
    """One typo must not throw the file away, and must not be silent either.

    Each override is applied on its own and checked against the map as it stands, so an
    unknown action, an unparseable chord and a collision are three notes and three kept
    defaults -- while the good entry in the same file still lands.
    """
    p = _keymap(tmp_path, {'run_cell': 'ctrl+y', 'nope': 'ctrl+q',
                           'save': 'ctrl+bogus+s', 'focus_files': 'alt+shift+3'})
    notes = []
    ks = apply_overrides(DEFAULTS, read_overrides(p, notes=notes), notes=notes)
    by = {k.action: k for k in ks}
    assert by['run_cell'].keys[0] == 'ctrl+y'          # the good one landed
    assert by['save'].key == lookup('save').key        # the bad chord was refused
    assert by['focus_files'].key == 'alt+shift+1'      # the collision was refused
    assert len(notes) == 3 and all(isinstance(n, str) and n for n in notes)


def test_a_rejected_override_does_not_leak_into_the_defaults(tmp_path):
    "The trial map is a copy: a refused entry must not still be sitting in the table it was tried against."
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
