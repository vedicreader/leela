"""Tests for the shared keymap, and for it actually reaching a handler.

`leela.keys` already refuses to import if two bindings collide, so the table
itself is self-checking. What it cannot check is the other half of the contract: that
each declared action exists on the app, and that pressing the key runs it. Both halves
failed silently once -- every scoped binding in the terminal IDE was listed in the footer
and in `f1` and wired to nothing -- which is what these tests exist to stop.
"""

import asyncio
import pytest

from leela.keys import KEYS, SCOPES, WEB_ONLY_SCOPES, help_rows, tui_key, web_keymap
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
