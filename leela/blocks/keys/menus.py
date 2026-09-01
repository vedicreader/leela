"Contextual menus, as rows naming actions from the shared keymap; labels and chords come from it."

from dataclasses import dataclass

from fastcore.all import L

from ...core.keys import KEYS, chord_display, lookup

__all__ = ['MenuItem', 'Std', 'Js', 'MENUS', 'BAR', 'menu', 'web_menus']

@dataclass(frozen=True)
class MenuItem:
    "One action in a contextual menu; a blank action is a separator."
    action: str = ''
    kind: str = ''
    def __post_init__(self):
        if self.kind not in ('', 'warn'):
            raise ValueError(f'{self.action or "separator"}: bad menu kind {self.kind!r}')

@dataclass(frozen=True)
class Std:
    "A row AppKit already implements: the selector goes to the responder chain, target nil."
    title: str
    selector: str
    key: str = ''
    mods: str = 'mod'

@dataclass(frozen=True)
class Js:
    "A row the keymap has no action for. Debug is only reachable as JS, so it is named as JS."
    title: str
    expr: str

S = MenuItem
MENUS = {
    'files': L(S('quick_open'), S('open_folder'), S('add_root'), S(), S('new_file'), S('new_notebook'),
               S('new_dir'), S(), S('nbdev_prepare'), S('fastship'),
               S(), S('code_search'), S('refresh_files')),
    'file': L(S('open'), S('show_diff'), S('git_blame'), S(), S('git_stage'), S('git_unstage'),
              S('git_discard', 'warn'), S('git_ignore'), S(), S('copy_rel_path'), S('copy_abs_path'),
              S(), S('clip_to_vault'), S(), S('new_file'),
              S('new_dir'), S(), S('file_cut'), S('file_copy'), S('file_paste'),
              S('file_duplicate'), S(), S('rename'), S('delete', 'warn')),
    'folder': L(S('add_folder'), S('git_stage'), S('git_ignore'), S(), S('new_file'), S('new_dir'), S(),
                S('copy_rel_path'), S('copy_abs_path'), S(),
                S('clip_to_vault'), S(), S('file_cut'), S('file_copy'), S('file_paste'),
                S('file_duplicate'), S(), S('rename'), S('delete', 'warn'), S(), S('open_folder'), S('add_root'),
                S('refresh_files')),
    'root': L(S('new_file'), S('new_dir'), S(), S('copy_abs_path'), S(), S('remove_root', 'warn'),
              S(), S('open_folder'), S('add_root'), S('refresh_files')),
    'editor': L(S('complete'), S('ai_complete'), S('show_docs'), S('ask_ai'), S('summarise'), S(), S('find_similar'),
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
              S('cell_split_symbols'),
              S(), S('clear_cell_output'), S('clear_all_outputs'), S(), S('show_docs'),
              S('find_similar'), S('git_blame'), S('run_selection'), S('agent_selection'),
              S(), S('cell_delete', 'warn')),
    'variable': L(S('expand'), S('grid'), S(), S('edit_value'), S('promote'),
                  S(), S('copy_value'), S('copy_path')),
    'tab': L(S('save'), S('reload_file'), S('show_diff'), S('git_blame'), S(),
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

#: The Mac menu bar, in the order macOS expects. `__app__` is spliced into the application menu
#: rather than made a menu of its own. Rows are keymap actions, AppKit selectors, or JS.
BAR = (
    ('__app__', L(S('settings'), S('setup_models'))),
    ('File',    L(S('new_file'), S('new_notebook'), S('new_dir'), S(),
                  S('quick_open'), S('open_folder'), S('add_root'), S('recent_tabs'), S(),
                  S('save'), S('save_all'), S('reload_file'), S(), S('close_tab'), S('close_others'),
                  S('close_right'), S('close_saved'), S('remove_root'), S(),
                  S('copy_rel_path'), S('copy_abs_path'))),
    ('Edit',    L(S('workspace_undo'), S('workspace_redo'), S(),
                  Std('Cut', 'cut:', 'x'), Std('Copy', 'copy:', 'c'), Std('Paste', 'paste:', 'v'),
                  Std('Select All', 'selectAll:', 'a'), S(),
                  S('find_in_file'), S('code_search'), S('replace_workspace'), S(),
                  S('comment'), S('format_doc'), S('complete'), S('ai_complete'), S(),
                  S('rename_symbol'), S('extract_variable'), S('extract_method'),
                  S('extract_constant'), S('inline_variable'), S('move_symbol'))),
    ('View',    L(S('toggle_left'), S('toggle_right'), S('toggle_bottom'), S(),
                  S('focus_files'), S('focus_editor'), S('focus_exec'), S('focus_vars'),
                  S('focus_agent'), S(), S('panel_git'), S('panel_releases'), S('panel_deploys'),
                  S(), S('show_diff'), S('local_history'), S('git_blame'), S('show_hidden'),
                  S('refresh_files'), S(),
                  Std('Enter Full Screen', 'toggleFullScreen:', 'f', 'mod+ctrl'))),
    ('Run',     L(S('run_cell'), S('run_advance'), S('run_insert'), S('run_above'), S(),
                  S('run_all'), S('run_file'), S('run_selection'), S(),
                  S('run_app'), S('edit_runs'), S(),
                  S('interrupt'), S('restart'), S('restart_run_all'), S(),
                  S('pick_kernel'), S('switch_env'), S('toggle_scope'), S('clear_all_outputs'))),
    ('Tools',   L(S('palette'), S('help'), S('edit_keys'), S(),
                  S('terminal'), S('git'), S(), S('find_repo'), S('find_definition'),
                  S('find_usages'), S('show_docs'), S(), S('sync_index'), S('nbdev_prepare'),
                  S('fastship'), S(), S('web_search'), S('research'), S('read_url'),
                  S('browse_url'), S('browse_tabs'), S(),
                  S('agent_selection'), Js('Inline Completions…', 'showCompletions()'),
                  S('capture'), S(),
                  S('open_vault'), S('memory_notes'), S('new_memory_note'), S('clip_to_vault'))),
    ('Debug',   L(Js('Debug This File', 'leeDebugFile()'), S('run_app'), S('edit_runs'), S(),
                  Js('Continue', "leeDebugControl('continue')"),
                  Js('Step Over', "leeDebugControl('next')"),
                  Js('Step Into', "leeDebugControl('stepIn')"),
                  Js('Step Out', "leeDebugControl('stepOut')"), S(),
                  Js('Stop Debugger', 'leeDebugStop()'), S(),
                  S('interrupt'), S('restart'))),
    ('Window',  L(Std('Minimize', 'performMiniaturize:', 'm'), Std('Zoom', 'performZoom:'), S(),
                  S('next_tab'), S('prev_tab'), S(), S('close_tab'), S(),
                  Std('Bring All to Front', 'arrangeInFront:'))),
    ('Help',    L(S('help'), S('edit_keys'))),
)

_bar_acts = {r.action for _, rows in BAR for r in rows if isinstance(r, MenuItem) and r.action}
if _missing := sorted(_bar_acts - _known):
    raise ValueError('the menu bar names actions the keymap does not declare: ' + ', '.join(_missing))
