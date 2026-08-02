"""Tests for the clickable half of the IDE.

`leela.buttons` exists because a chord is not always deliverable: `ctrl+enter` needs a
terminal that speaks the kitty keyboard protocol, `alt+<letter>` needs Option configured
as Meta on macOS, and a browser keeps a dozen combinations for itself. The promise the
button table makes is that none of that can leave a feature unreachable -- so what these
tests check is the promise, not the pixels: every button names a real action, every action
it names has a handler, and the actions that are hardest to press by hand are the ones
that actually have buttons.
"""

import pytest

from leela.buttons import BARS, BUTTONS, bar, tip
from leela.keys import KEYS, WEB_ONLY_SCOPES, lookup
from leela.tui.app import IdeApp


def test_every_button_names_a_real_action():
    "A button wired to nothing is worse than no button: it looks like the feature exists."
    known = {k.action for k in KEYS}
    assert not [b.action for b in BUTTONS if b.action not in known]


def test_every_button_reaches_a_handler():
    "The same contract `test_keymap` holds the keymap to, for the other door into it."
    missing = [b.action for b in BUTTONS
               if lookup(b.action).scope not in WEB_ONLY_SCOPES
               and not hasattr(IdeApp, f'action_{b.action}')]
    assert not missing, f'no action_* method on IdeApp for: {missing}'


@pytest.mark.parametrize('name', BARS)
def test_every_bar_has_buttons(name):
    "A declared bar that renders empty is a hole in a toolbar someone is looking at."
    assert len(bar(name)) > 0


def test_the_keys_a_terminal_eats_all_have_buttons():
    """The point of the whole module, stated as a test.

    `ctrl+enter` and friends are the chords a stock macOS terminal never delivers. Each of
    them must be clickable somewhere, or a Terminal.app user cannot run a cell at all.
    """
    # `exec_newline` is the exception, and only because it is not a command: it types a
    # newline into the exec box, which a button cannot usefully do and `f7` already does.
    hard = {k.action for k in KEYS
            if k.keys and k.keys[0] in ('ctrl+enter', 'shift+enter', 'alt+enter')} - {'exec_newline'}
    clickable = {b.action for b in BUTTONS}
    assert not (hard - clickable), f'unreachable without a chord: {sorted(hard - clickable)}'


def test_the_command_palette_offers_every_action():
    """The third door, and the one with room for everything.

    A toolbar holds the dozen actions worth a permanent button; the palette holds all of
    them, which is what makes it the answer for a chord a terminal ate.
    """
    from leela.tui.app import ActionCommands
    rows = ActionCommands.__new__(ActionCommands)._rows()      # `_rows` needs no screen
    assert {a for _, a, _ in rows} == {k.action for k in KEYS if k.scope not in WEB_ONLY_SCOPES}


def test_a_tooltip_says_what_it_does_and_which_key_does_it():
    "Hovering is how the keys get discovered, so the chord travels with the button."
    t = tip('run_cell')
    assert 'run cell' in t and 'ctrl+enter' in t and 'f5' in t
    assert tip('run_selection') == 'run the selection', 'an unbound action advertises no chord'


def test_button_labels_stay_short_enough_for_a_terminal_row():
    "A toolbar is one row in the TUI; a long label pushes the buttons after it off the screen."
    long = [b.label for b in BUTTONS if b.bar != 'agent' and len(b.label) > 8]
    assert not long, f'too long for a terminal toolbar: {long}'
