"Contextual menus, as rows naming actions from the shared keymap; labels and chords come from it."

from dataclasses import dataclass

from fastcore.all import L

from ...core.keys import KEYS, chord_display, lookup

__all__ = ['MenuItem', 'MENUS', 'menu', 'web_menus']

@dataclass(frozen=True)
class MenuItem:
    "One action in a contextual menu; a blank action is a separator."
    action: str = ''
    kind: str = ''
    def __post_init__(self):
        if self.kind not in ('', 'warn'):
            raise ValueError(f'{self.action or "separator"}: bad menu kind {self.kind!r}')

S = MenuItem
MENUS = {
    'files': L(S('quick_open'), S('add_root'), S(), S('new_file'), S('new_notebook'),
               S('new_dir'), S(), S('code_search'), S('refresh_files')),
    'file': L(S('open'), S('show_diff'), S('git_blame'), S(), S('git_stage'), S('git_unstage'),
              S('git_discard', 'warn'), S('git_ignore'), S(), S('copy_rel_path'), S('copy_abs_path'),
              S(), S('clip_to_vault'), S(), S('new_file'),
              S('new_dir'), S(), S('rename'), S('delete', 'warn')),
    'folder': L(S('git_stage'), S('git_ignore'), S(), S('new_file'), S('new_dir'), S(),
                S('copy_rel_path'), S('copy_abs_path'), S(),
                S('clip_to_vault'), S(), S('rename'), S('delete', 'warn'), S(), S('add_root'),
                S('refresh_files')),
    'root': L(S('new_file'), S('new_dir'), S(), S('copy_abs_path'), S(), S('remove_root', 'warn'),
              S(), S('add_root'), S('refresh_files')),
    'editor': L(S('complete'), S('ai_complete'), S('show_docs'), S(), S('find_similar'),
                S('code_map'), S('git_blame'), S(), S('extract_variable'), S('extract_method'),
                S('extract_constant'), S('inline_variable'), S('move_symbol'), S('rename_symbol'),
                S('replace_workspace'), S(), S('move_line_up'), S('move_line_down'),
                S(), S('run_selection'), S('agent_selection'), S('comment')),
    'cell': L(S('run_cell'), S('run_advance'), S('run_insert'), S(), S('run_above'),
              S('run_below'), S('run_all'), S('restart_run_all'), S(),
              S('cell_select_above'), S('cell_select_below'), S('cell_move_up'),
              S('cell_move_down'), S('cell_above'), S('cell_below'), S('cell_duplicate'), S(),
              S('cell_copy'), S('cell_cut'), S('cell_paste_above'), S('cell_paste_below'), S(),
              S('cell_merge_above'), S('cell_merge_below'), S('cell_type'), S('cell_split'),
              S(), S('clear_cell_output'), S('clear_all_outputs'), S(), S('show_docs'),
              S('find_similar'), S('git_blame'), S('run_selection'), S('agent_selection'),
              S(), S('cell_delete', 'warn')),
    'variable': L(S('expand'), S('grid'), S(), S('edit_value'), S('promote'),
                  S(), S('copy_value'), S('copy_path')),
    'tab': L(S('save'), S('show_diff'), S('git_blame'), S(),
             S('copy_rel_path'), S('copy_abs_path'), S(), S('clip_to_vault'), S(),
             S('close_tab'), S('close_others'), S('close_right'), S('close_saved')),
    'kernel': L(S('pick_kernel'), S('switch_env'), S(), S('interrupt', 'warn'),
                S('restart', 'warn')),
    'exec': L(S('exec_run'), S('exec_promote'), S('toggle_scope'), S(), S('exec_clear')),
}

def menu(surface):
    "The rows for one surface, in declaration order."
    return MENUS.get(surface, L())

def _row(item):
    "One menu row: a separator, or an action with its keymap label and effective chord."
    if not item.action: return {'separator': True}
    key = lookup(item.action)
    return {'action': item.action, 'label': key.label or item.action.replace('_', ' '),
            'chord': chord_display(key), 'kind': item.kind}

def web_menus():
    "JSON-ready menus, resolving labels and effective user chords from the keymap."
    return {surface: [_row(i) for i in items] for surface, items in MENUS.items()}

_known = set(KEYS.attrgot('action'))
if _missing := sorted({i.action for rows in MENUS.values() for i in rows if i.action} - _known):
    raise ValueError('menus name actions the keymap does not declare: ' + ', '.join(_missing))
