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
from leela.keys import KEYS


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
