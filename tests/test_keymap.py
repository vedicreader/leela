"""Tests for the shared keymap, and for it actually reaching a handler.

`leela.keys` already refuses to import if two bindings collide, so the table
itself is self-checking. What it cannot check is the other half of the contract: that
each declared action exists on the app, and that pressing the key runs it. Both halves
failed silently once -- every scoped binding in the terminal IDE was listed in the footer
and in `f1` and wired to nothing -- which is what these tests exist to stop.
"""

import asyncio
import json
import pytest

from leela import keys as K
from leela.keys import (DEFAULTS, KEYS, SCOPES, WEB_ONLY_SCOPES, apply_overrides, help_rows,
                        keymap_json, lookup, read_overrides, tui_key, web_keymap)
from leela.tui.app import IdeApp, _binds


def test_every_action_has_a_handler():
    "The footer cannot advertise a key that has nowhere to go."
    missing = [k.action for k in KEYS
               if k.scope not in WEB_ONLY_SCOPES and not hasattr(IdeApp, f'action_{k.action}')]
    assert not missing, f'no action_* method on IdeApp for: {missing}'


@pytest.mark.parametrize('scope', SCOPES)
def test_bindings_are_namespaced_to_the_app(scope):
    """Every `action_*` lives on `IdeApp` while scoped bindings are declared on the panes.

    Textual resolves an unqualified action against the widget that declared the binding
    and does not fall back to the app, so an un-namespaced scoped binding is dead on
    arrival: advertised everywhere, wired to nothing.
    """
    for b in _binds(scope):
        assert b.action.startswith('app.'), f'{scope}: {b.action!r} is not namespaced to the app'


def test_web_and_terminal_agree_on_the_actions():
    "Both frontends generate from one table, so neither can grow an action the other lacks."
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


def test_every_chord_that_needs_a_modern_terminal_has_a_plain_fallback():
    """`ctrl+enter`, `shift+enter` and `alt+enter` need the kitty keyboard protocol.

    In Terminal.app they arrive as a bare `enter`, which is to say the most important keys
    in the IDE cannot be pressed at all -- so every binding that leads with one of them
    carries a function key as well. This is the test that stops a new one being added
    without one.
    """
    hard = {'ctrl+enter', 'shift+enter', 'alt+enter'}
    for k in KEYS:
        if k.keys and k.keys[0] in hard:
            assert len(k.keys) > 1, f'{k.action} is only reachable by {k.keys[0]}'
            assert k.keys[1].startswith('f'), f'{k.action}: {k.keys[1]} is no easier to press'


def test_an_unbound_action_is_still_a_real_action():
    "An action with no chord is declared, labelled, clickable and rebindable -- just not bound."
    k = lookup('run_selection')
    assert k.keys == [] and not k.bound and k.label
    assert {r['action'] for r in web_keymap()} >= {'run_selection'}
    assert not [b for b in _binds(k.scope) if b.action.endswith('run_selection')]


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
                           'save': 'ctrl+bogus+s', 'focus_files': 'ctrl+e'})
    notes = []
    ks = apply_overrides(DEFAULTS, read_overrides(p, notes=notes), notes=notes)
    by = {k.action: k for k in ks}
    assert by['run_cell'].keys[0] == 'ctrl+y'          # the good one landed
    assert by['save'].key == lookup('save').key        # the bad chord was refused
    assert by['focus_files'].key == 'ctrl+b'           # the collision was refused
    assert len(notes) == 3 and all(isinstance(n, str) and n for n in notes)


def test_a_rejected_override_does_not_leak_into_the_defaults(tmp_path):
    "The trial map is a copy: a refused entry must not still be sitting in the table it was tried against."
    p = _keymap(tmp_path, {'focus_files': 'ctrl+e'})
    apply_overrides(DEFAULTS, read_overrides(p, notes=[]), notes=[])
    assert lookup('focus_files').key == 'ctrl+b'
    assert {k.action: k.key for k in DEFAULTS}['focus_files'] == 'ctrl+b'


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


def _press(app, chord, focus, check):
    "Boot the app, focus a pane, press one canonical chord, and report what `check` saw."
    async def run():
        async with app.run_test(size=(120, 40)) as pilot:
            for _ in range(6): await pilot.pause()
            await asyncio.sleep(0.4)
            for _ in range(4): await pilot.pause()
            focus(app)
            for _ in range(3): await pilot.pause()
            await pilot.press(tui_key(chord))
            for _ in range(4): await pilot.pause()
            await asyncio.sleep(0.2)
            for _ in range(3): await pilot.pause()
            return check(app)
    return asyncio.run(run())


def test_an_editor_binding_runs_its_action(app):
    "The regression test for the dead-scope bug: press the key, check the document moved."
    def focus(a): a._view().focus_cell(3)
    got = _press(app, 'ctrl+alt+m', focus, lambda a: a._view().nb[3].cell_type)
    assert got == 'markdown', 'ctrl+alt+m did not reach action_cell_type'


def test_cycling_a_cell_leaves_the_cursor_where_it_was(app):
    """A structural edit rebuilds the cell column, and `NotebookView.load` selects the first
    cell -- so without `_struct` putting it back, pressing a cell key twice acts on two
    different cells and the view jumps to the top of the notebook every time."""
    def focus(a): a._view().focus_cell(3)

    def check(a):
        v = a._view()
        return v.nb[3].cell_type, v.sel
    kind, sel = _press(app, 'ctrl+alt+m', focus, check)
    assert (kind, sel) == ('markdown', 3)


def test_an_exec_binding_runs_its_action(app):
    "Same, for a pane whose bindings live on a different widget."
    def focus(a):
        box = a.query_one('#execbox')
        box.focus()
        box.text = 'total'
    lines = _press(app, 'ctrl+enter', focus, lambda a: a._exec_lines)
    assert lines, 'ctrl+enter did not reach action_exec_run'
    assert lines[-1][0] == 'total'
