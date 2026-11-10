"The keymap and menus carry the side-pane actions, and no new chord is bound."

from leela.blocks.keys.menus import MENUS
from leela.core.keys import lookup


def test_open_to_the_side_and_copy_to_the_other_notebook_are_menu_rows_with_no_chord():
    for action, scope in (('open_side', 'global'), ('cell_to_other', 'editor')):
        key = lookup(action)
        assert key and key.scope == scope and not key.bound, action
    assert 'open_side' in [r.action for r in MENUS['file']] and 'open_side' in [r.action for r in MENUS['tab']]
    assert 'cell_to_other' in [r.action for r in MENUS['cell']]
