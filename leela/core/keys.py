"The browser IDE's single-source keymap, shipped to the browser by `web_keymap()`."

import json, os, sys
from dataclasses import dataclass, asdict, replace
from fastcore.all import L, Path, first, ifnone
from kavacha import chord_glyph

__all__ = ['Key', 'SCOPES', 'EDITING_SCOPES', 'KEYS', 'DEFAULTS', 'NOTES',
           'parse_key', 'web_key', 'by_scope', 'web_keymap',
           'help_rows', 'PRESENT_KEYS', 'toast_rows', 'lookup', 'chord_display', 'keymap_path', 'read_overrides',
           'apply_overrides', 'TOOK', 'only_changed', 'bulk_map', 'keymap_json', 'write_keymap', 'reload',
           'changed', 'refresh', 'VERSION', 'SAME_IDEA', 'NO_MENU', 'TWICE', 'CHROME_RESERVED', 'LEGACY',
           'glyphs', 'legacy_rows']

EDITING_SCOPES = ('editor', 'exec', 'agent', 'term')
SCOPES = ('global', 'files', 'editor', 'exec', 'vars', 'agent', 'term', 'vault', 'review')

_NAMED = {'enter', 'escape', 'tab', 'backspace', 'delete', 'space', 'up', 'down', 'left', 'right',
          'home', 'end', 'pageup', 'pagedown', *[f'f{i}' for i in range(1, 13)]}

_WEB_BASE = {'enter': 'Enter', 'escape': 'Escape', 'tab': 'Tab', 'backspace': 'Backspace',
             'delete': 'Delete', 'space': ' ', 'up': 'ArrowUp', 'down': 'ArrowDown',
             'left': 'ArrowLeft', 'right': 'ArrowRight', 'home': 'Home', 'end': 'End',
             'pageup': 'PageUp', 'pagedown': 'PageDown',
             **{f'f{i}': f'F{i}' for i in range(1, 13)}}
_WEB_CODE = {**{chr(c): f'Key{chr(c).upper()}' for c in range(ord('a'), ord('z') + 1)},
             **{str(i): f'Digit{i}' for i in range(10)},
             'enter': 'Enter', 'space': 'Space', 'tab': 'Tab', 'escape': 'Escape',
             'backspace': 'Backspace', 'delete': 'Delete',
             'up': 'ArrowUp', 'down': 'ArrowDown', 'left': 'ArrowLeft', 'right': 'ArrowRight',
             'home': 'Home', 'end': 'End', 'pageup': 'PageUp', 'pagedown': 'PageDown',
             '[': 'BracketLeft', ']': 'BracketRight', '/': 'Slash', '\\': 'Backslash',
             '`': 'Backquote', '-': 'Minus', '=': 'Equal', '.': 'Period', ',': 'Comma',
             ';': 'Semicolon', "'": 'Quote'}

def parse_key(k):
    "Canonical chord -> (frozenset of modifiers, base key). 'X' normalises to ({'shift'}, 'x')."
    *mods, base = k.split('+')
    mods = {m.lower() for m in mods}
    if 'hyper' in mods: mods = (mods - {'hyper'}) | {'mod', 'ctrl', 'alt', 'shift'}
    if base.lower() in _NAMED: base = base.lower()
    elif len(base) == 1 and base.isupper(): mods, base = mods | {'shift'}, base.lower()
    bad = mods - {'mod', 'ctrl', 'alt', 'shift'}
    if bad: raise ValueError(f'unknown modifier(s) {sorted(bad)} in {k!r}')
    if base not in _NAMED and len(base) != 1: raise ValueError(f'unknown base key {base!r} in {k!r}')
    return frozenset(mods), base

@dataclass(frozen=True)
class Key:
    "One binding: what it does, the chord that triggers it, and where it is advertised."
    action: str
    key: str
    scope: str = 'global'
    label: str = ''
    show: str = 'help'
    def __post_init__(self):
        if self.scope not in SCOPES: raise ValueError(f'{self.action}: unknown scope {self.scope!r}')
        if self.show not in ('footer', 'toast', 'help'): raise ValueError(f'{self.action}: bad show {self.show!r}')
        if self.scope in EDITING_SCOPES and self.scope != 'editor' or self.scope == 'global':
            for c in self.keys:
                mods, base = parse_key(c)
                if not mods and base not in _NAMED:
                    raise ValueError(f'{self.action}: bare {c!r} cannot bind in scope {self.scope!r}')
    @property
    def keys(self):
        "Every chord this action answers to, first one first. Empty when the action is unbound."
        return L(self.key.split())
    @property
    def bound(self): return bool(self.keys)

def web_key(k):
    "Canonical chord -> the dict the browser handler matches a KeyboardEvent against."
    hyper = 'hyper' in {part.lower() for part in k.split('+')[:-1]}
    mods, base = parse_key(k)
    key = _WEB_BASE.get(base, base)
    if 'shift' in mods and len(key) == 1: key = key.upper()
    return {'key': key, 'code': _WEB_CODE.get(base), 'hyper': hyper, 'mod': 'mod' in mods,
            'ctrl': 'ctrl' in mods, 'alt': 'alt' in mods, 'shift': 'shift' in mods}

DEFAULTS = L(
    Key('focus_files',      'mod+1 alt+shift+1',   'global', 'files',               'footer'),
    Key('focus_editor',     'mod+2 alt+shift+2',   'global', 'editor',              'footer'),
    Key('focus_exec',       'mod+3 alt+shift+3',   'global', 'exec',                'footer'),
    Key('focus_vars',       'mod+4 alt+shift+4',   'global', 'variables',           'footer'),
    Key('focus_agent',      'mod+5 alt+shift+5',   'global', 'agent',               'footer'),
    Key('palette',          'mod+shift+p mod+shift+a',   'global', 'command palette',     'footer'),
    Key('settings',         'mod+,',         'global', 'settings',             'toast'),
    Key('quick_open',       'mod+p',         'global', 'go to file…',         'toast'),
    Key('recent_tabs',      'mod+e',         'global', 'recent files',        'toast'),
    Key('code_search',      'mod+shift+f',    'global', 'search code',        'toast'),
    Key('find_repo',        'mod+shift+o',    'global', 'find repository',    'toast'),
    Key('find_definition',  'mod+b',          'global', 'declaration or usages', 'toast'),
    Key('find_definition_only', '',           'global', 'go to definition'),
    Key('find_in_file',     'mod+f',          'global', 'find across cells',  'toast'),
    Key('find_usages',      'alt+f',        'global', 'find usages',        'toast'),
    Key('rename_symbol',    'mod+alt+r',      'global', 'rename symbol',       'toast'),
    Key('replace_workspace','mod+shift+h',    'global', 'replace in workspace', 'toast'),
    Key('workspace_undo',   'mod+alt+z',        'global', 'undo workspace operation'),
    Key('workspace_redo',   'mod+alt+shift+z',        'global', 'redo workspace operation'),
    Key('extract_variable', 'mod+alt+v',      'global', 'extract variable',    'toast'),
    Key('extract_method',   'mod+alt+m',      'global', 'extract method / function'),
    Key('extract_constant', 'mod+alt+c',      'global', 'extract constant'),
    Key('inline_variable',  'mod+alt+n',      'global', 'inline variable'),
    Key('move_symbol',      'mod+alt+f',      'global', 'move function or class to a file', 'toast'),
    Key('sync_index',       '',        'global', 'sync Kosha index'),
    Key('nbdev_prepare',    '',               'global', 'nbdev prepare'),
    Key('fastship',         '',               'global', 'fastship release tools'),
    Key('setup_models',     '',               'global', 'models and updates'),
    Key('check_updates',    '',               'global', 'check for updates…'),
    Key('save',             'mod+s',         'global', 'save',                'toast'),
    Key('save_all',         'alt+shift+s',   'global', 'save all'),
    Key('show_diff',        'alt+shift+d',   'global', 'what changed',        'toast'),
    Key('reload_file',      '',              'global', 'reload from disk'),
    Key('local_history',    'alt+h',       'global', 'local file history',  'toast'),
    Key('git_blame',        'alt+b',       'global', 'who wrote this',      'toast'),
    Key('git_stage',        '',              'files',  'stage selected path'),
    Key('git_unstage',      '',              'files',  'unstage selected path'),
    Key('git_discard',      '',              'files',  'discard selected changes'),
    Key('git_ignore',       '',              'files',  'add selected path to .gitignore'),
    Key('complete',         'alt+/ ctrl+space', 'global', 'complete',         'toast'),
    Key('ai_complete',      'alt+shift+space', 'global', 'ai completion',     'toast'),
    Key('show_docs',        'alt+shift+h',   'global', 'docs for symbol',     'toast'),
    Key('ask_ai',           'alt+q',       'global', 'ask AI about the selection'),
    Key('summarise',        '',       'global', 'summarise the selection'),
    Key('capture',          'alt+shift+p',   'global', 'screenshot for the assistant', 'toast'),
    Key('agent_selection',  'alt+shift+n',   'global', 'send selection to the agent', 'toast'),
    Key('explain_cell',     '',              'global', 'explain this cell'),
    Key('learn_about',      '',              'global', 'learn about this'),
    Key('clip_to_vault',    '',              'global', 'clip into the vault'),
    Key('memory_notes',     '',              'global', 'manage memory notes'),
    Key('new_memory_note',  '',              'global', 'create a memory note'),
    Key('open_vault',       'alt+v',       'global', 'open the vault'),
    Key('vault_read',       '',              'global', 'read a file into the vault'),
    Key('vault_find',       '',              'global', 'find in the vault'),
    Key('vault_review',     '',              'global', 'vault review queue'),
    Key('dictate',          '',              'global', 'Dictate'),
    Key('learned_review',   '',              'global', 'review what the agent learned'),
    Key('vault_settings',   '',              'global', 'vault settings: vaults, privacy, cadence, tidy'),
    Key('close_tab',        'mod+w alt+w',         'global', 'close tab',           'toast'),
    Key('copy_rel_path',    'alt+y',         'global', 'copy relative path',  'toast'),
    Key('copy_abs_path',    'alt+shift+y',   'global', 'copy absolute path'),
    Key('close_others',     '',              'global', 'close other tabs'),
    Key('close_right',      '',              'global', 'close tabs to the right'),
    Key('close_saved',      '',              'global', 'close saved tabs'),
    Key('next_tab',         'alt+]',         'global', 'next tab'),
    Key('prev_tab',         'alt+[',         'global', 'previous tab'),
    Key('toggle_left',      'alt+shift+b', 'global', 'toggle file pane'),
    Key('toggle_right',     'alt+shift+v', 'global', 'toggle agent / variables pane'),
    Key('toggle_bottom',    'mod+j',    'global', 'toggle bottom tools'),
    Key('leave_full_screen', 'mod+shift+e',  'global', 'leave full screen pane', 'toast'),
    Key('term_option_meta', '',              'global', 'Terminal: Option key as Meta'),
    Key('toggle_scope',     'alt+t',         'global', 'live / isolated',     'toast'),
    Key('interrupt',        'alt+shift+i',    'global', 'interrupt kernel',   'toast'),
    Key('restart',          'alt+shift+r', 'global', 'restart kernel'),
    Key('pick_kernel',      'alt+shift+k',   'global', 'choose kernel',       'toast'),
    Key('switch_env',       'alt+shift+e',   'global', 'watch another env',   'toast'),
    Key('edit_runs',        '',              'global', 'run configurations'),
    Key('run_file',         'mod+alt+enter',  'global', 'run this script',    'toast'),
    Key('run_selection',    'alt+shift+enter',       'global', 'run the selection in the kernel'),
    Key('new_notebook',     'mod+shift+n mod+alt+j',       'global', 'new notebook'),
    Key('new_lesson',       '',              'global', 'new lesson notebook'),
    Key('notebook_language', '',           'global', 'notebook language'),
    Key('present_notebook', 'alt+r',         'global', 'present notebook as slides'),
    Key('add_folder',       '',              'global', 'stage this folder, ignores first'),
    Key('new_file',         'mod+n mod+alt+shift+n', 'global', 'new file', 'toast'),
    Key('open_folder',      'mod+o',         'global', 'open…',               'toast'),
    Key('edit_keys',        'mod+alt+k',       'global', 'edit keybindings'),
    Key('run_app',          'alt+shift+a',   'global', 'run a configuration', 'toast'),
    Key('terminal',         'ctrl+`',        'global', 'terminal',            'toast'),
    Key('git',              'alt+shift+g',   'global', 'lazygit',             'toast'),
    Key('panel_git',        'alt+g',       'global', 'source control panel', 'toast'),
    Key('panel_releases',   'alt+p',       'global', 'releases panel',      'toast'),
    Key('panel_deploys',    'alt+d',       'global', 'deploys panel',       'toast'),
    Key('web_search',       'alt+shift+w',   'global', 'search the web',      'toast'),
    Key('research',         'alt+shift+q',   'global', 'research a question'),
    Key('read_url',         'alt+shift+u',   'global', 'read a url'),
    Key('browse_url',       'alt+shift+o',   'global', 'browse a url in a tab'),
    Key('browse_tabs',      '',              'global', 'adopt a page open in the browser'),
    Key('help',             'mod+shift+/',   'global', 'keys',                'footer'),
    Key('quit',             '',              'global', 'quit'),
    *[Key(f'tab_{i}', f'alt+{i}', 'global', f'tab {i}') for i in range(1, 10)],
    Key('run_cell',         'mod+enter',       'editor', 'run cell',              'footer'),
    Key('run_advance',      'shift+enter',     'editor', 'run and select below',  'footer'),
    Key('run_insert',       'alt+enter',       'editor', 'run and insert below'),
    Key('stop_cell',        'alt+shift+c',     'editor', 'stop running cell'),
    Key('check_exercise',   'alt+s',           'editor', 'check my work'),
    Key('run_above',        '',     'editor', 'run all cells above'),
    Key('run_below',        '',  'editor', 'run this cell and below'),
    Key('run_all',          'mod+shift+enter', 'editor', 'run every cell'),
    Key('restart_run_all',  '', 'editor', 'restart kernel and run all'),
    Key('cell_select_above','ctrl+shift+up',   'editor', 'select cell above'),
    Key('cell_select_below','ctrl+shift+down', 'editor', 'select cell below'),
    Key('cell_first',       'mod+home',         'editor', 'first cell',          'toast'),
    Key('cell_last',        'mod+end',          'editor', 'last cell',           'toast'),
    Key('cell_page_up',     'alt+pageup',       'editor', 'previous page of cells'),
    Key('cell_page_down',   'alt+pagedown',     'editor', 'next page of cells'),
    Key('cell_move_up',     'alt+shift+up alt+shift+pageup',     'editor', 'move cell up'),
    Key('cell_move_down',   'alt+shift+down alt+shift+pagedown', 'editor', 'move cell down'),
    Key('cell_above',       'mod+alt+up a',      'editor', 'insert cell above'),
    Key('cell_below',       'mod+alt+down b',    'editor', 'insert cell below'),
    Key('cell_delete',      'mod+alt+backspace d', 'editor', 'delete cell'),
    Key('present_from_cell', '',               'editor', 'present from this cell'),
# RISE's own chords. Leela's router lets them through to any editor or field, so they type there.
    Key('slide_none',       '',                'editor', 'slide type: none (continue)'),
    Key('slide_slide',      'shift+i',         'editor', 'slide type: slide'),
    Key('slide_subslide',   'shift+b',         'editor', 'slide type: subslide'),
    Key('slide_fragment',   'shift+g',         'editor', 'slide type: fragment'),
    Key('slide_skip',       '',                'editor', 'slide type: skip'),
    Key('slide_notes',      '',                'editor', 'slide type: notes'),
# Naming these here is what puts them in the palette and the keys help. CodeMirror's own keymap
# already answers them inside an editor, and it is the same command either way.
    Key('indent_more',      'mod+]',           'editor', 'indent'),
    Key('indent_less',      'mod+[',           'editor', 'outdent'),
    Key('indent_selection', 'mod+alt+l',         'editor', 're-indent to the syntax', 'toast'),
    Key('notebook_undo',    'mod+z z',           'editor', 'undo cell operation', 'toast'),
    Key('notebook_redo',    'mod+shift+z',     'editor', 'redo cell operation'),
    Key('cell_type',        'alt+shift+m',     'editor', 'code / markdown / prompt', 'toast'),
    Key('cell_to_markdown', 'm',               'editor', 'make a markdown cell'),
    Key('cell_to_code',     'y',               'editor', 'make a code cell'),
    Key('cell_edit',        'enter',           'editor', 'edit markdown cell'),
    Key('cell_render',      'escape',          'editor', 'render markdown cell, or stop editing the cell'),
    Key('cell_split',       'alt+shift+-',     'editor', 'split cell'),
    Key('cell_split_symbols', 'alt+shift+/',   'editor', 'split into one cell per def', 'toast'),
    Key('cell_collapse',    'o',         'editor', 'collapse / expand cell'),
    Key('heading_toggle',   '',                'editor', 'collapse / expand heading section'),
    Key('collapse_all_headings', '',           'editor', 'collapse every heading'),
    Key('expand_all_headings',   '',           'editor', 'expand every heading'),
    Key('scrub_up',         '',                'editor', 'nudge the number under the caret up'),
    Key('scrub_down',       '',                'editor', 'nudge the number under the caret down'),
    Key('scrub_value',      '',                'editor', 'scrub the number under the caret to a value'),
    Key('scrub_live',       '',                'editor', 'live scrub on or off for this cell'),
    Key('cell_duplicate',   'shift+d',         'editor', 'duplicate cell below'),
    Key('cell_comment',     'mod+alt+/',         'editor', 'comment the whole cell'),
    Key('cell_copy',        'mod+c mod+shift+c c', 'editor', 'copy cell'),
    Key('cell_cut',         'mod+x mod+shift+x x', 'editor', 'cut cell'),
    Key('cell_paste_above', 'shift+v',                'editor', 'paste cell above'),
    Key('cell_paste_below', 'v',                'editor', 'paste cell below'),
    Key('cell_merge_above', '',        'editor', 'merge cell above'),
    Key('cell_merge_below', 'shift+m',    'editor', 'merge cell below'),
    Key('clear_cell_output','',    'editor', 'clear this cell output'),
    Key('clear_all_outputs','mod+shift+backspace', 'editor', 'clear all outputs'),
    Key('move_line_up',     'alt+up',        'editor', 'move line up',        'toast'),
    Key('move_line_down',   'alt+down',      'editor', 'move line down'),
# CodeMirror's editing commands. A cell or file editor drops CodeMirror's own chords for them, so
# these rows and `keys.json` are the only chords they answer to.
    Key('copy_line_up',     '',              'editor', 'duplicate line above'),
    Key('copy_line_down',   'mod+shift+d',   'editor', 'duplicate line'),
    Key('delete_line',      'mod+shift+k',   'editor', 'delete line'),
    Key('select_line',      '',              'editor', 'select line'),
    Key('select_next_occurrence', 'mod+d',   'editor', 'add next occurrence to the selection'),
    Key('select_all_occurrences', 'mod+shift+l', 'editor', 'select every occurrence'),
    Key('add_cursor_above', '',              'editor', 'add cursor above'),
    Key('add_cursor_below', '',              'editor', 'add cursor below'),
    Key('column_mode',      '',      'editor', 'column mode: up and down add a cursor at the column'),
    Key('matching_bracket', 'mod+shift+\\',  'editor', 'go to matching bracket'),
    Key('select_parent_syntax', 'mod+i',     'editor', 'expand selection to the enclosing syntax'),
    Key('block_comment',    '',              'editor', 'toggle block comment'),
    Key('comment',          'mod+/',         'editor', 'toggle comment',      'toast'),
    Key('find_similar',     'mod+alt+shift+a',  'editor', 'code like this',      'toast'),
    Key('code_map',         'ctrl+shift+m',  'editor', 'code map (clusters)'),
    Key('exec_run',         'mod+enter',     'exec',   'run',                  'footer'),
    Key('exec_newline',     '',     'exec',   'newline'),
    Key('exec_prev',        'ctrl+shift+up', 'exec',   'older',               'toast'),
    Key('exec_next',        'ctrl+shift+down', 'exec', 'newer',               'toast'),
    Key('exec_clear',       'alt+shift+l',   'exec',   'clear log'),
    Key('exec_promote',     'mod+shift+enter',   'exec',   'run in live namespace'),
    Key('open',             'enter',         'files',  'open / toggle folder','footer'),
    Key('tree_down',        'down',          'files',  'next item',           'footer'),
    Key('tree_up',          'up',            'files',  'previous item'),
    Key('tree_expand',      'right',         'files',  'expand / enter folder'),
    Key('tree_collapse',    'left',          'files',  'collapse / parent'),
    Key('up_dir',           'backspace',     'files',  'parent folder'),
    Key('tree_new_file',    'n',             'files',  'new file here',       'toast'),
    Key('new_dir',          'N',             'files',  'new folder',          'toast'),
    Key('rename',           'r',             'files',  'rename',              'toast'),
    # Scope-qualified, the way `mod+enter` is three different runs: `cell_copy` is editor-scoped,
    # so in the tree these are the only claim on the clipboard chords.
    Key('file_copy',        'mod+c',         'files',  'copy'),
    Key('file_cut',         'mod+x',         'files',  'cut'),
    Key('file_paste',       'mod+v',         'files',  'paste into folder'),
    Key('file_duplicate',   'mod+d',         'files',  'duplicate'),
    Key('tree_mark_up',     'shift+up',      'files',  'extend selection up'),
    Key('tree_mark_down',   'shift+down',    'files',  'extend selection down'),
    Key('delete',           'd',             'files',  'delete from disk'),
    Key('refresh_files',    'R',             'files',  'refresh'),
    Key('show_hidden',      'H',             'files',  'show dotfiles',       'toast'),
    Key('tree_open_folder', 'o',             'files',  'open folder in a new window here', 'toast'),
    Key('add_root',         'O',             'files',  'add folder to this window',   'toast'),
    Key('remove_root',      '',              'files',  'remove folder from workspace'),
    Key('filter_files',     '/',             'files',  'filter'),
    Key('expand',           'enter',         'vars',   'expand',              'footer'),
    Key('filter_vars',      '/',             'vars',   'filter',              'footer'),
    Key('edit_value',       'i',             'vars',   'edit',                'toast'),
    Key('grid',             'g',             'vars',   'grid',                'toast'),
    Key('copy_value',       'y',             'vars',   'copy value'),
    Key('copy_path',        'Y',             'vars',   'copy path'),
    Key('promote',          'p',             'vars',   'promote to live'),
    Key('sort',             'o',             'vars',   'cycle sort'),
    Key('profile_minimal',  '1',             'vars',   'minimal'),
    Key('profile_standard', '2',             'vars',   'standard'),
    Key('profile_full',     '3',             'vars',   'full'),
    Key('format_doc',       'alt+shift+f',   'editor', 'format document',      'toast'),
    Key('agent_send',       'mod+enter',     'agent',  'send',                 'footer'),
    Key('agent_steer_force','mod+shift+enter','agent',  'stop and send next'),
    Key('agent_new',        'mod+l mod+alt+a',   'agent',  'new conversation'),
    Key('agent_threads',    'mod+y',   'agent',  'all conversations'),
    Key('agent_stop',       'alt+shift+c',   'agent',  'stop agent'),
    Key('agent_tools',      'alt+shift+t',   'agent',  'what the agent did'),
    Key('agent_fold_turn',  'alt+shift+j',   'agent',  'fold this turn'),
    Key('agent_fold_all',   'alt+shift+z',   'agent',  'fold every turn'),
    Key('agent_menu',       '',              'agent',  'agent: more actions'),
    Key('agent_history',    '',              'agent',  'conversation history'),
    Key('agent_assess',     '',              'agent',  'assess this conversation'),
    Key('agent_round',      '',              'agent',  'capture as round…'),
    Key('agent_accept',     '',              'agent',  'accept round…'),
    Key('agent_calm',       '',              'agent',  'calm view'),
    Key('agent_expand',     '',              'agent',  'expand agent pane'),
    Key('agent_research',   '',              'agent',  'research tool, next conversation'),
    Key('agent_exhash',     '',              'agent',  'hash-addressed edits, next conversation'),
    Key('agent_browser',    '',              'agent',  'browser, next conversation'),
    Key('agent_warm',       '',              'agent',  'warm start, next conversation'),
    Key('agent_full',       '',              'agent',  'full briefing, next conversation'),
    Key('agent_state',      '',              'agent',  'agent state…'),
    Key('vault_next_page',  'j',             'vault',  'next page',           'footer'),
    Key('vault_prev_page',  'k',             'vault',  'previous page',       'footer'),
    Key('vault_next_flag',  ']',             'vault',  'next flagged page',   'toast'),
    Key('vault_prev_flag',  '[',             'vault',  'previous flagged page', 'toast'),
    Key('vault_reread',     'r',             'vault',  're-read pages with another model', 'toast'),
    Key('vault_history',    'h',             'vault',  'page versions',       'toast'),
    Key('vault_proofread',  'p',             'vault',  'proofread this document', 'toast'),
    Key('vault_as_sent',    'm',             'vault',  'as sent to a hosted model', 'toast'),
    Key('vault_find_doc',   '/',             'vault',  'find in this document', 'toast'),
    Key('vault_ask_page',   'a',             'vault',  'ask about this page',  'toast'),
    Key('review_next',      'j',             'review', 'next change',         'footer'),
    Key('review_prev',      'k',             'review', 'previous change',     'footer'),
    Key('review_accept',    'a',             'review', 'accept',              'footer'),
    Key('review_reject',    'x',             'review', 'reject',              'footer'),
    Key('review_accept_page', 'A',           'review', 'accept the page',     'toast'),
    Key('review_accept_doc', 'alt+a',        'review', 'accept the document', 'toast'),
    Key('review_doubts',    'd',             'review', 'doubts only',         'toast'),
    Key('review_edit',      'e',             'review', 'edit, then accept',   'toast'),
    Key('review_undo',      'u',             'review', 'undo',                'toast'),
    Key('term_new',         'ctrl+shift+`',  'term',   'new terminal',        'toast'),
    Key('term_next',        'ctrl+shift+]',  'term',   'next terminal'),
    Key('term_prev',        'ctrl+shift+[',  'term',   'previous terminal'),
    Key('term_close',       'alt+shift+x',   'term',   'close terminal',      'toast'),
)

#: Actions that may share one modifier chord across scopes, because the chord means the same thing in each.
SAME_IDEA = (('run_cell', 'exec_run', 'agent_send'), ('run_all', 'agent_steer_force', 'exec_promote'),
             ('stop_cell', 'agent_stop'), ('cell_copy', 'file_copy'), ('cell_cut', 'file_cut'),
             ('select_next_occurrence', 'file_duplicate'), ('cell_select_above', 'exec_prev'), ('cell_select_below', 'exec_next'))
#: Bound global actions with no menu bar row.
NO_MENU = frozenset(f'tab_{i}' for i in range(1, 10))
#: Command-mode chords that run only when pressed twice in a row, as Jupyter's `d d`.
TWICE = {'cell_delete': 'd'}
#: Chords Chrome keeps for itself, so a binding needs another chord to work in a browser tab.
CHROME_RESERVED = frozenset(['mod+n', 'mod+t', 'mod+w', 'mod+shift+n', 'mod+shift+t', 'mod+shift+w', 'ctrl+tab', 'mod+l',
                             *(f'mod+{i}' for i in range(1, 9))])
#: Old default chords, for one release: pressed with nothing bound, they run the action and say where it went.
LEGACY = {'alt+i': 'toggle_scope', 'hyper+u': 'find_usages', 'hyper+,': 'workspace_undo', 'hyper+.': 'workspace_redo',
          'hyper+i': 'sync_index', 'hyper+b': 'git_blame', 'hyper+m': 'summarise', 'hyper+v': 'open_vault',
          'hyper+n': 'new_notebook', 'hyper+k': 'edit_keys', 'hyper+g': 'panel_git', 'hyper+p': 'panel_releases',
          'hyper+l': 'panel_deploys', 'hyper+/': 'cell_comment', 'hyper+\\': 'column_mode', 'hyper+enter': 'run_above',
          'hyper+pagedown': 'run_below', 'hyper+backspace': 'restart_run_all', 'hyper+pageup': 'cell_merge_below',
          'hyper+delete': 'clear_cell_output', 'mod+shift+t': 'agent_threads', 'mod+shift+g': 'exec_promote'}

def _host_fold():
    "Whether `mod` and `ctrl` are one key on this host: they are on Windows and Linux, not on a Mac."
    return sys.platform != 'darwin'

def _signature(chord, fold=True):
    "A chord as it collides: modifiers sorted, and with `fold` the `mod` folded into `ctrl`."
    mods, base = parse_key(chord)
    if fold and 'mod' in mods: mods = (mods - {'mod'}) | {'ctrl'}
    return tuple(sorted(mods)), base

def _dupes(keys, fold=True):
    "(scope, chord) pairs bound twice, and actions declared twice. Both are real conflicts."
    seen, bad = {}, []
    keys = L(keys)
    for k in keys:
        for c in k.keys:
            sig = (k.scope, _signature(c, fold))
            if sig in seen: bad.append(f'{c} is bound by both {seen[sig]} and {k.action} in scope {k.scope}')
            else: seen[sig] = k.action
    acts = keys.attrgot('action')
    bad += [f'action {a!r} declared twice' for a in set(acts) if acts.count(a) > 1]
    g = {_signature(c, fold): k.action for k in keys.filter(lambda k: k.scope == 'global') for c in k.keys}
    for k in keys.filter(lambda k: k.scope != 'global'):
        for c in k.keys:
            if (t := _signature(c, fold)) in g: bad.append(f'{c} is both global ({g[t]}) and {k.scope} ({k.action})')
    return bad

def by_scope(scope): return KEYS.filter(lambda k: k.scope == scope)
def lookup(action): return first(KEYS.filter(lambda k: k.action == action))

def _twice(k, c): return f'{c} {c}' if TWICE.get(k.action) == c else c

def chord_display(action_or_key, sep=' / '):
    "How a binding is written for a person: every chord it answers to, or a dash when unbound."
    k = lookup(action_or_key) if isinstance(action_or_key, str) else action_or_key
    if k is None: return ''
    return sep.join(_twice(k, c) for c in k.keys) if k.bound else '–'

def _browser_safe(c):
    try: return _signature(c) not in {_signature(r) for r in CHROME_RESERVED}
    except ValueError: return True

def web_keymap():
    "The whole table as JSON-ready rows for the browser handler, each chord with its glyphs and whether a browser tab gets it."
    return [{**asdict(k), 'display': [chord_glyph(_twice(k, c)) for c in k.keys],
             'chords': [web_key(c) | {'browser': _browser_safe(c), 'twice': TWICE.get(k.action) == c} for c in k.keys]} for k in KEYS]

def legacy_rows():
    "LEGACY as rows the page matches when no binding does: the old chord, the action, and what to say."
    return [{'action': a, 'chord': web_key(c), 'old': chord_glyph(c), 'now': chord_glyph(lookup(a).keys[0]) if lookup(a) and lookup(a).bound else ''}
            for c, a in LEGACY.items() if lookup(a)]

def glyphs(extra=()):
    "Every chord the page may show, as `{'mac': {chord: glyph}, 'pc': {chord: text}}`."
    cs = {c for k in KEYS for c in k.keys}
    cs |= {c for ks, _ in PRESENT_KEYS for c in ks.split()} | set(LEGACY) | set(extra)
    return {'mac': {c: chord_glyph(c) for c in cs}, 'pc': {c: chord_glyph(c, mac=False) for c in cs}}

#: The presenter's keys as `(chords, label)`, for the keys help only. `present.js` binds them while a presentation is open; no row is a binding.
PRESENT_KEYS = (('right down space pagedown', 'next step'), ('left up shift+space pageup', 'previous step'), ('n', 'speaker notes'),
                ('f', 'full screen on or off'), ('x', 'laser on or off'), ('b', 'blank screen on or off'), ('escape', 'close one thing'))

def help_rows():
    "Every binding grouped by scope, and the presenter's keys as `present`, for the full help overlay: {scope: [(chord_display, label)]}."
    return {**{s: [(chord_display(k), k.label) for k in by_scope(s) if k.label] for s in SCOPES}, 'present': list(PRESENT_KEYS)}

def toast_rows():
    "The short cheatsheet for the left sidebar: keys that earn space but are not in the footer."
    return [(chord_display(k, sep=' '), k.label) for k in KEYS if k.show == 'toast']

NOTES = L()

def keymap_path(path=None):
    "Where overrides are read from: the argument, else `$LEELA_KEYMAP`, else `<config>/keys.json`."
    from .. import leela_cfg
    return Path(path or os.environ.get('LEELA_KEYMAP') or (leela_cfg/'keys.json'))

_GENERATED_DEFAULT_MIGRATIONS = {
    'focus_files': ('ctrl+b', 'alt+shift+1'),
    'focus_editor': ('ctrl+j', 'alt+shift+2'),
    'focus_exec': ('ctrl+e', 'alt+shift+3'),
    'focus_vars': ('ctrl+r', 'alt+shift+4'),
    'focus_agent': ('ctrl+g', 'alt+shift+5'),
    'palette': ('ctrl+shift+p f3', 'mod+shift+p'),
    'quick_open': ('ctrl+p', 'mod+p'),
    'code_search': ('ctrl+shift+f f4', 'mod+shift+f'),
    'save': ('ctrl+s', 'mod+s'),
    'save_all': ('ctrl+alt+s', 'alt+shift+s'),
    'show_diff': ('ctrl+alt+/', 'alt+shift+d'),
    'complete': ('ctrl+space', 'alt+/ ctrl+space'),
    'ai_complete': ('ctrl+alt+space', 'alt+shift+space'),
    'show_docs': ('ctrl+alt+h', 'alt+shift+h'),
    'capture': ('ctrl+alt+p', 'alt+shift+p'),
    'toggle_left': ('ctrl+alt+b', 'alt+shift+b'),
    'toggle_right': ('ctrl+alt+r', 'alt+shift+v'),
    'interrupt': ('ctrl+alt+i f10', 'alt+shift+i'),
    'restart': ('ctrl+alt+k', 'alt+shift+r'),
    'pick_kernel': ('ctrl+alt+j', 'alt+shift+k'),
    'switch_env': ('ctrl+alt+e', 'alt+shift+e'),
    'run_file': ('ctrl+alt+enter f9', 'mod+alt+enter'),
    'run_app': ('ctrl+alt+d', 'alt+shift+a'),
    'terminal': ('ctrl+alt+`', 'ctrl+`'),
    'git': ('ctrl+alt+v', 'alt+shift+g'),
    'web_search': ('ctrl+alt+w', 'alt+shift+w'),
    'research': ('ctrl+alt+n', 'alt+shift+q'),
    'read_url': ('ctrl+alt+u', 'alt+shift+u'),
    'help': ('f1', 'mod+shift+/'),
    'quit': ('ctrl+alt+q', ''),
    'run_cell': ('f5 ctrl+enter', 'mod+enter'),
    'run_advance': ('f6 shift+enter', 'shift+enter'),
    'run_insert': ('f7 alt+enter', 'alt+enter'),
    'run_all': ('f8', 'mod+shift+enter'),
    'cell_delete': ('ctrl+alt+delete', 'mod+alt+backspace'),
    'cell_type': ('ctrl+alt+m', 'alt+shift+m'),
    'cell_split': ('ctrl+alt+-', 'alt+shift+-'),
    'comment': ('ctrl+/', 'mod+/'),
    'exec_run': ('f5 ctrl+enter', 'mod+enter'),
    'exec_newline': ('alt+enter f7', 'alt+enter'),
    'exec_clear': ('ctrl+l', 'alt+shift+l'),
    'exec_promote': ('ctrl+alt+g', 'mod+shift+g'),
    'agent_send': ('f5 ctrl+enter', 'mod+enter'),
    'agent_stop': ('ctrl+alt+c', 'alt+shift+c'),
    'agent_tools': ('ctrl+alt+l', 'alt+shift+t'),
    'term_close': ('ctrl+alt+x', 'alt+shift+x'),
    'cell_above': ('ctrl+alt+up', 'mod+alt+up'),
    'cell_below': ('ctrl+alt+down', 'mod+alt+down'),
    'rename': ('f2 r', 'r'),
}

_SNAPSHOT_MIGRATIONS = {
    'restart': ('alt+shift+r', 'alt+shift+r hyper+r'),
    'toggle_left': ('alt+shift+b', 'alt+shift+b hyper+left'),
    'toggle_right': ('alt+shift+v', 'alt+shift+v hyper+right'),
    'run_selection': ('', 'hyper+s'), 'new_notebook': ('', 'hyper+n'),
    'edit_keys': ('', 'hyper+k'),
    'rename_symbol': ('', 'mod+alt+r'), 'replace_workspace': ('', 'mod+shift+h'),
    'workspace_undo': ('', 'hyper+,'), 'workspace_redo': ('', 'hyper+.'),
    'open_vault': ('', 'hyper+v'),
    'notebook_undo': ('mod+alt+z', 'mod+z'), 'notebook_redo': ('mod+alt+shift+z', 'mod+shift+z'),
}

#: Keys v2 (6 Nov 2026): Hyper off every default, JetBrains layout, a second chord where Chrome keeps the first.
_V2_MIGRATIONS = {
    **{f'focus_{n}': (f'alt+shift+{i}', f'mod+{i} alt+shift+{i}') for i, n in enumerate(['files', 'editor', 'exec', 'vars', 'agent'], 1)},
    'palette': ('mod+shift+p', 'mod+shift+p mod+shift+a'), 'find_usages': ('hyper+u', 'alt+f'),
    'workspace_undo': ('hyper+,', 'mod+alt+z'), 'workspace_redo': ('hyper+.', 'mod+alt+shift+z'), 'sync_index': ('hyper+i', ''),
    'local_history': ('hyper+h', 'alt+h'), 'git_blame': ('hyper+b', 'alt+b'), 'ask_ai': ('hyper+a', 'alt+q'),
    'summarise': ('hyper+m', ''), 'open_vault': ('hyper+v', 'alt+v'), 'close_tab': ('alt+w', 'mod+w alt+w'),
    'toggle_left': ('alt+shift+b hyper+left', 'alt+shift+b'), 'toggle_right': ('alt+shift+v hyper+right', 'alt+shift+v'),
    'toggle_bottom': ('hyper+down', 'mod+j'), 'toggle_scope': ('alt+i', 'alt+t'), 'restart': ('alt+shift+r hyper+r', 'alt+shift+r'),
    'run_selection': ('hyper+s', 'alt+shift+enter'), 'new_notebook': ('hyper+n', 'mod+shift+n mod+alt+j'),
    'edit_keys': ('hyper+k', 'mod+alt+k'), 'panel_git': ('hyper+g', 'alt+g'), 'panel_releases': ('hyper+p', 'alt+p'),
    'panel_deploys': ('hyper+l', 'alt+d'), 'new_file': ('n', 'mod+n mod+alt+shift+n'), 'open_folder': ('o', 'mod+o'),
    'run_above': ('hyper+enter', ''), 'run_below': ('hyper+pageDown', ''), 'restart_run_all': ('hyper+backspace', ''),
    'cell_above': ('mod+alt+up', 'mod+alt+up a'), 'cell_below': ('mod+alt+down', 'mod+alt+down b'),
    'cell_delete': ('mod+alt+backspace', 'mod+alt+backspace d'), 'notebook_undo': ('mod+z', 'mod+z z'),
    'indent_selection': ('hyper+]', 'mod+alt+l'), 'cell_comment': ('hyper+/', 'mod+alt+/'), 'cell_collapse': ('hyper+c', 'o'),
    'cell_duplicate': ('hyper+d', 'shift+d'), 'cell_copy': ('mod+c mod+shift+c', 'mod+c mod+shift+c c'),
    'cell_cut': ('mod+x mod+shift+x', 'mod+x mod+shift+x x'), 'cell_paste_above': ('', 'shift+v'), 'cell_paste_below': ('', 'v'),
    'cell_merge_above': ('hyper+up', ''), 'cell_merge_below': ('hyper+pageup', 'shift+m'), 'clear_cell_output': ('hyper+delete', ''),
    'column_mode': ('hyper+\\', ''), 'find_similar': ('ctrl+shift+a', 'mod+alt+shift+a'), 'exec_newline': ('alt+enter', ''),
    'exec_promote': ('mod+shift+g', 'mod+shift+enter'), 'agent_new': ('mod+shift+n', 'mod+l mod+alt+a'), 'agent_threads': ('mod+shift+t', 'mod+y'),
}
#: Actions that became global; a bare key a person gave one is the files panel's, so it moves to the tree action.
_TREE = {'new_file': 'tree_new_file', 'open_folder': 'tree_open_folder'}

def _bare(c):
    try: return all(not parse_key(x)[0] - {'shift'} for x in c.split())
    except ValueError: return False

def _tree_moved(d):
    "`d` with a bare chord on `new_file` or `open_folder` moved to its files-panel action."
    mv = lambda a, c: _TREE[a] if a in _TREE and _TREE[a] not in d and isinstance(c, str) and c.strip() and _bare(c) else a
    return {mv(a, c): c for a, c in d.items()}

def _migrated(d, table):
    "`d` with every action still holding an exact old default moved onto the new one."
    return {a: table[a][1] if a in table and c == table[a][0] else c for a, c in d.items()}

def read_overrides(path=None, notes=None):
    "`{action: chord}` from the user's keymap file. Never raises: a broken file is a note."
    p = Path(path or keymap_path())
    notes = ifnone(notes, NOTES)
    try: d = json.loads(p.read_text())
    except FileNotFoundError: return {}
    except Exception as e:
        notes.append(f'{p}: {type(e).__name__}: {e}. Leela uses the default keys')
        return {}
    if not isinstance(d, dict):
        notes.append(f'{p}: expected an object of action -> chord. Leela uses the default keys')
        return {}
    help_text = ' '.join(map(str, d.get('_help') or ()))
    generated_snapshot = isinstance(d.get('keys'), dict) and len(d['keys']) > 50 and 'leela keymap' in help_text
    legacy_generated = generated_snapshot and 'mod is Command' not in help_text
    if isinstance(d.get('keys'), dict): d = d['keys']
    if legacy_generated: d = _migrated(d, _GENERATED_DEFAULT_MIGRATIONS)
    if generated_snapshot: d = _migrated(_migrated(d, _SNAPSHOT_MIGRATIONS), _V2_MIGRATIONS)
    d = _tree_moved(d)
    out = {}
    for a, c in d.items():
        if a.startswith('_') or a == 'agent_transcript': continue
        if not isinstance(c, str): notes.append(f'{p}: {a}: {c!r} is not a chord string')
        else: out[a] = c.strip()
    return out

TOOK = L()   # what the user's chords took from a default, in words; not an error, so apart from NOTES

def _clash(k1, c1, k2, c2, fold):
    "Whether chord `c1` of `k1` and chord `c2` of `k2` fire on the same press: one chord, in one scope or a global one."
    return _signature(c1, fold) == _signature(c2, fold) and (k1.scope == k2.scope or 'global' in (k1.scope, k2.scope))

def _defaults_win(out, todo, notes, fold):
    "`out` with `todo` applied one entry at a time, skipping any that collides: a machine-written map never outranks a default."
    trial = L(list(out))
    for i, k in todo.items(): trial[i] = k
    if not _dupes(trial, fold): return trial
    moved = True
    while todo and moved:
        moved = False
        for i in list(todo):
            trial = L(list(out)); trial[i] = todo[i]
            if not _dupes(trial, fold): out, moved = trial, True; del todo[i]
    for i, k in todo.items():
        trial = L(list(out)); trial[i] = k
        notes.append(f'keymap: {k.action} -> {k.key!r} conflicts ({_dupes(trial, fold)[0]}). Leela kept {out[i].key or "unbound"}')
    return out

def _user_wins(out, todo, fold):
    "(keys, notes, took): the user's chords placed, a default losing only the chord a user chord takes. None if a collision is left."
    notes, took, mine = [], [], {}
    for i, k in todo.items():
        if len({_signature(c, fold) for c in k.keys}) < len(k.keys):
            notes.append(f'keymap: {k.action} -> {k.key!r} names one chord twice. Leela kept {out[i].key or "unbound"}'); continue
        hit = first(o.action for j, o in mine.items() if any(_clash(k, c, o, d, fold) for c in k.keys for d in o.keys))
        if hit: notes.append(f'keymap: {k.action} -> {k.key!r} conflicts with {hit}, which you also set. Leela kept {out[i].key or "unbound"}')
        else: mine[i] = k
    res, lost = L(list(out)), {}
    for i, k in mine.items(): res[i] = k
    for i, k in mine.items():
        for j, o in enumerate(res):
            if j in mine or not o.bound: continue
            gone = [d for d in o.keys if any(_clash(k, c, o, d, fold) for c in k.keys)]
            if not gone: continue
            keep = [d for d in o.keys if d not in gone]
            lost.setdefault(o.action, o.key)
            res[j] = replace(o, key=' '.join(keep))
            took.append(f'keymap: {k.action} took {" ".join(gone)!r} from {o.action}; {o.action} keeps {" ".join(keep) or "no chord"}')
    if _dupes(res, fold): return None
    res.displaced = lost
    return res, notes, took

def apply_overrides(keys, over, notes=None, took=None):
    """`keys` with the user's chords applied, skipping what cannot work. In a hand-written map your chord wins over a
    built-in default, which loses only that chord (told in `took`); two of your own chords that collide are refused (told in `notes`).
    A map of more than `_BULK` entries counts as machine-written, so a default outranks it: copy only what you change."""
    notes, took = ifnone(notes, NOTES), ifnone(took, TOOK)
    fold = _host_fold()
    out, todo = L(list(keys)), {}
    for a, c in (over or {}).items():
        i = out.argfirst(lambda k: k.action == a)
        if i is None: notes.append(f'keymap: no action named {a!r}'); continue
        try: todo[i] = replace(out[i], key=c)
        except ValueError as e: notes.append(f'keymap: {a}: {e}')
    if not todo: return out
    if not bulk_map(over):
        if r := _user_wins(out, todo, fold):
            res, n, t = r
            notes.extend(n); took.extend(t)
            return res
        notes.append(f'keymap: the table already has a collision ({_dupes(out, fold)[0] if _dupes(out, fold) else "after your chords"}). Your chords were tried one at a time, defaults first')
    return _defaults_win(out, todo, notes, fold)

_BULK = 50

def bulk_map(over):
    "Whether `over` names more actions than a person edits by hand, so a machine wrote it."
    return len(over) > _BULK

def _same_chord(a, b):
    "Whether two chord strings bind the same keys in the same order."
    if a == b: return True
    try: return [_signature(c, _host_fold()) for c in a.split()] == [_signature(c, _host_fold()) for c in b.split()]
    except ValueError: return False

def only_changed(over, base=None):
    "`over` without the entries that repeat a default."
    d = {k.action: k.key for k in L(ifnone(base, DEFAULTS))}
    return {a: c for a, c in over.items() if not _same_chord(d.get(a, ''), c)}

def _chosen(keys):
    "What differs from the defaults in `keys`, without the defaults that lost a chord to the user: those follow the next default."
    ks = ifnone(keys, KEYS)
    gone = getattr(ks, 'displaced', {})
    return {a: c for a, c in only_changed({k.action: k.key for k in L(ks)}).items() if a not in gone}

def keymap_json(keys=None, over=None):
    "The overrides as the JSON a user edits, with every action and its default beside them."
    ks = L(ifnone(keys, KEYS))
    over = ifnone(over, _chosen(keys))
    return {'_help': ['leela keymap: action -> chord, or several chords separated by spaces.',
                      'A chord is [mod+][ctrl+][alt+][shift+]base; hyper is Command+Control+Option+Shift on macOS; mod is Command on macOS and Control elsewhere; base is a character or a name '
                      '(enter, escape, tab, space, up, f1..f12).',
                      'An empty string unbinds the action. Delete an entry to take leela\'s default.',
                      '"keys" holds only what you changed. Every action absent from it follows leela\'s default, '
                      'including when that default moves in a later release.',
                      '"_defaults" lists every action and the chord leela ships it with. leela rewrites it and '
                      'never reads it. Copy a line into "keys" to change one.',
                      'Anything unparseable or conflicting is skipped and reported in the IDE.'],
            '_defaults': {k.action: k.key for k in DEFAULTS},
            'keys': dict(over)}

def write_keymap(path=None, keys=None, keep=True):
    "Write the overrides where the user can edit them, keeping a copy of what was there."
    from .backups import guard
    p = Path(path or keymap_path())
    kept = read_overrides(p, notes=L()) if keep else {}
    if bulk_map(kept): kept = only_changed(kept)
    eff = _chosen(keys)
    guard(p, reason='before the keymap was rewritten')
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(keymap_json(keys, {**kept, **eff}), indent=2) + '\n')
    return p

def _read(p):
    try: return Path(p).read_bytes()
    except OSError: return None

_seen = (None, None)   # the file `KEYS` came from, and its bytes then
VERSION = 0            # counts changes to what the page is sent, so each workspace's watcher tells its pages once

def _bump(was):
    global VERSION
    if (list(KEYS), list(NOTES)) != was: VERSION += 1

def reload(path=None):
    "Rebuild `KEYS` from the defaults plus the user's file. Called once at import."
    global KEYS, _seen
    p, was = Path(path) if path else keymap_path(), (list(KEYS), list(NOTES))
    _seen = (p, _read(p))
    NOTES.clear(); TOOK.clear()
    KEYS = apply_overrides(DEFAULTS, read_overrides(p), NOTES, TOOK)
    _bump(was)
    return KEYS

def changed():
    "Whether the keymap file holds other bytes than the ones `KEYS` came from."
    p = keymap_path()
    return (p, _read(p)) != _seen

def refresh():
    "Reload if the file changed. True if it did. A file that is not a JSON object keeps the last good keys."
    global _seen
    p = keymap_path()
    b = _read(p)
    if (p, b) == _seen: return False
    try: d = None if b is None else json.loads(b)
    except ValueError as e: d = e
    if d is None or isinstance(d, dict):
        reload(p)
        return True
    _seen, was = (p, b), (list(KEYS), list(NOTES))
    why = f'{type(d).__name__}: {d}' if isinstance(d, Exception) else 'expected an object of action -> chord'
    NOTES.clear()
    NOTES.append(f'{p}: {why}. The last good keys stay in use.')
    _bump(was)
    return True

if _c := _dupes(DEFAULTS): raise ValueError('keymap conflicts:\n  ' + '\n  '.join(_c))
KEYS = DEFAULTS
reload()
