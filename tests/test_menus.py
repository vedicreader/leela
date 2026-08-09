"""Contextual actions stay tied to the shared operation and key registries."""

from leela.keys import DEFAULTS
from leela.menus import MENUS, web_menus


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
    """All four are menu actions; copy/cut additionally carry the standard chords.

    Those chords used to be unbound, because binding Copy/Cut would have taken them from the
    editor. They are bound now because the router gives them back: it only treats them as
    cell operations in a notebook with no source selected. The guard is the whole reason this
    is safe, so it is asserted here rather than left to the keymap alone.
    """
    actions = [row.action for row in MENUS['cell'] if row.action]
    for action in ('cell_copy', 'cell_cut', 'cell_paste_above', 'cell_paste_below'):
        assert action in actions
    by_action = {k.action: k.key for k in DEFAULTS}
    assert by_action['cell_paste_above'] == '' and by_action['cell_paste_below'] == ''
    assert by_action['cell_copy'] == 'mod+c' and by_action['cell_cut'] == 'mod+x'

    from pathlib import Path
    js = (Path(__file__).resolve().parents[1]/'leela/web/static/lee-ide.js').read_text()
    assert "['cell_copy', 'cell_cut'].includes(k.action)" in js   # the chords are special-cased
    assert "lee.kind !== 'notebook'" in js                        # outside a notebook, hands off
    assert 'selection?.from !== selection?.to' in js              # and yields to selected text


def test_new_entry_defaults_are_browser_safe_contextual_letters():
    by_action = {k.action: k.key for k in DEFAULTS}
    assert by_action['new_file'] == 'n'
    assert by_action['new_dir'] == 'N'
    assert 'ctrl+n' not in (by_action['new_file'], by_action['new_dir'])
