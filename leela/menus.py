"""Single-source contextual menus for the browser IDE.

Buttons answer "what is always useful here?"; menus answer "what can I do to this
thing?".  Like :mod:`leela.buttons`, every row names an action from the shared
keymap.  Labels and chords are resolved from that keymap when JSON is produced,
so a user keybinding edit is reflected in the menu without a second registry to
keep in sync.
"""

from dataclasses import dataclass

from fastcore.all import L

from .keys import KEYS, chord_display, lookup

__all__ = ['MenuItem', 'MENUS', 'menu', 'web_menus']


@dataclass(frozen=True)
class MenuItem:
    "One action in a contextual menu; a blank action is a separator."
    action: str = ''
    kind: str = ''       # '' | 'warn'

    def __post_init__(self):
        if self.kind not in ('', 'warn'):
            raise ValueError(f'{self.action or "separator"}: bad menu kind {self.kind!r}')


S = MenuItem
MENUS = {
    # File-pane background, files, and folders deliberately differ: "open" is not a
    # meaningful operation on a folder row, whose disclosure arrow already expands it.
    'files': L(S('quick_open'), S('add_root'), S(), S('new_file'), S('new_notebook'),
               S('new_dir'), S(), S('code_search'), S('refresh_files')),
    'file': L(S('open'), S(), S('new_file'), S('new_dir'), S(), S('rename'),
              S('delete', 'warn')),
    'folder': L(S('new_file'), S('new_dir'), S(), S('rename'), S('delete', 'warn'),
                S(), S('add_root'), S('refresh_files')),
    'root': L(S('new_file'), S('new_dir'), S(), S('remove_root', 'warn'),
              S(), S('add_root'), S('refresh_files')),

    # Plain files use editor; notebooks use cell. Cell includes the symbol operations
    # because a code cell is still an editor under the pointer.
    'editor': L(S('complete'), S('ai_complete'), S('show_docs'), S(), S('find_similar'),
                S('code_map'), S(), S('run_selection'), S('comment')),
    'cell': L(S('run_cell'), S('run_advance'), S('run_insert'), S(), S('run_above'),
              S('run_below'), S('run_all'), S('restart_run_all'), S(),
              S('cell_select_above'), S('cell_select_below'), S('cell_move_up'),
              S('cell_move_down'), S('cell_above'), S('cell_below'), S('cell_duplicate'), S(),
              S('cell_copy'), S('cell_cut'), S('cell_paste_above'), S('cell_paste_below'), S(),
              S('cell_merge_above'), S('cell_merge_below'), S('cell_type'), S('cell_split'),
              S(), S('clear_cell_output'), S('clear_all_outputs'), S(), S('show_docs'),
              S('find_similar'), S('run_selection'), S(), S('cell_delete', 'warn')),
    'variable': L(S('expand'), S('grid'), S(), S('edit_value'), S('promote'),
                  S(), S('copy_value'), S('copy_path')),
    'tab': L(S('save'), S('show_diff'), S(), S('close_tab')),
    'kernel': L(S('pick_kernel'), S('switch_env'), S(), S('interrupt', 'warn'),
                S('restart', 'warn')),
    'exec': L(S('exec_run'), S('exec_promote'), S('toggle_scope'), S(), S('exec_clear')),
}


def menu(surface):
    "The rows for one surface, in declaration order."
    return MENUS.get(surface, L())


def web_menus():
    "JSON-ready menus, resolving labels and effective user chords from the keymap."
    out = {}
    for surface, items in MENUS.items():
        rows = []
        for item in items:
            if not item.action:
                rows.append({'separator': True})
                continue
            key = lookup(item.action)
            rows.append({'action': item.action,
                         'label': key.label or item.action.replace('_', ' '),
                         'chord': chord_display(key),
                         'kind': item.kind})
        out[surface] = rows
    return out


_known = set(KEYS.attrgot('action'))
if _missing := sorted({i.action for rows in MENUS.values() for i in rows if i.action} - _known):
    raise ValueError('menus name actions the keymap does not declare: ' + ', '.join(_missing))
