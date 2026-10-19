"The browser IDE's single-source keymap, shipped to the browser by `web_keymap()`."

import json, os
from dataclasses import dataclass, asdict, replace
from fastcore.all import L, Path, first, ifnone

__all__ = ['Key', 'SCOPES', 'EDITING_SCOPES', 'KEYS', 'DEFAULTS', 'NOTES',
           'parse_key', 'web_key', 'by_scope', 'web_keymap',
           'help_rows', 'toast_rows', 'lookup', 'chord_display', 'keymap_path', 'read_overrides',
           'apply_overrides', 'only_changed', 'bulk_map', 'keymap_json', 'write_keymap', 'reload']

EDITING_SCOPES = ('editor', 'exec', 'agent', 'term')
SCOPES = ('global', 'files', 'editor', 'exec', 'vars', 'agent', 'term', 'canvas', 'vault', 'review')

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
        if self.scope in EDITING_SCOPES or self.scope == 'global':
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
    Key('focus_files',      'alt+shift+1',   'global', 'files',               'footer'),
    Key('focus_editor',     'alt+shift+2',   'global', 'editor',              'footer'),
    Key('focus_exec',       'alt+shift+3',   'global', 'exec',                'footer'),
    Key('focus_vars',       'alt+shift+4',   'global', 'variables',           'footer'),
    Key('focus_agent',      'alt+shift+5',   'global', 'agent',               'footer'),
    Key('palette',          'mod+shift+p',   'global', 'command palette',     'footer'),
    Key('settings',         'mod+,',         'global', 'settings',             'toast'),
    Key('quick_open',       'mod+p',         'global', 'open file',           'toast'),
    Key('recent_tabs',      'mod+e',         'global', 'recent files',        'toast'),
    Key('code_search',      'mod+shift+f',    'global', 'search code',        'toast'),
    Key('find_repo',        'mod+shift+o',    'global', 'find repository',    'toast'),
    Key('find_definition',  'mod+b',          'global', 'declaration or usages', 'toast'),
    Key('find_definition_only', '',           'global', 'go to definition'),
    Key('find_in_file',     'mod+f',          'global', 'find across cells',  'toast'),
    Key('find_usages',      'hyper+u',        'global', 'find usages',        'toast'),
    Key('rename_symbol',    'mod+alt+r',      'global', 'rename symbol',       'toast'),
    Key('replace_workspace','mod+shift+h',    'global', 'replace in workspace', 'toast'),
    Key('workspace_undo',   'hyper+,',        'global', 'undo workspace operation'),
    Key('workspace_redo',   'hyper+.',        'global', 'redo workspace operation'),
    Key('extract_variable', 'mod+alt+v',      'global', 'extract variable',    'toast'),
    Key('extract_method',   'mod+alt+m',      'global', 'extract method / function'),
    Key('extract_constant', 'mod+alt+c',      'global', 'extract constant'),
    Key('inline_variable',  'mod+alt+n',      'global', 'inline variable'),
    Key('move_symbol',      'mod+alt+f',      'global', 'move function or class to a file', 'toast'),
    Key('sync_index',       'hyper+i',        'global', 'sync Kosha index'),
    Key('nbdev_prepare',    '',               'global', 'nbdev prepare'),
    Key('fastship',         '',               'global', 'fastship release tools'),
    Key('setup_models',     '',               'global', 'models and updates'),
    Key('save',             'mod+s',         'global', 'save',                'toast'),
    Key('save_all',         'alt+shift+s',   'global', 'save all'),
    Key('show_diff',        'alt+shift+d',   'global', 'what changed',        'toast'),
    Key('reload_file',      '',              'global', 'reload from disk'),
    Key('local_history',    'hyper+h',       'global', 'local file history',  'toast'),
    Key('git_blame',        'hyper+b',       'global', 'who wrote this',      'toast'),
    Key('git_stage',        '',              'files',  'stage selected path'),
    Key('git_unstage',      '',              'files',  'unstage selected path'),
    Key('git_discard',      '',              'files',  'discard selected changes'),
    Key('git_ignore',       '',              'files',  'add selected path to .gitignore'),
    Key('complete',         'alt+/ ctrl+space', 'global', 'complete',         'toast'),
    Key('ai_complete',      'alt+shift+space', 'global', 'ai completion',     'toast'),
    Key('show_docs',        'alt+shift+h',   'global', 'docs for symbol',     'toast'),
    Key('ask_ai',           'hyper+a',       'global', 'ask AI about the selection'),
    Key('summarise',        'hyper+m',       'global', 'summarise the selection'),
    Key('capture',          'alt+shift+p',   'global', 'screenshot for the assistant', 'toast'),
    Key('agent_selection',  'alt+shift+n',   'global', 'send selection to the agent', 'toast'),
    Key('clip_to_vault',    '',              'global', 'clip into the vault'),
    Key('memory_notes',     '',              'global', 'manage memory notes'),
    Key('new_memory_note',  '',              'global', 'create a memory note'),
    Key('open_vault',       'hyper+v',       'global', 'open the vault'),
    Key('vault_read',       '',              'global', 'read a file into the vault'),
    Key('vault_find',       '',              'global', 'find in the vault'),
    Key('vault_review',     '',              'global', 'vault review queue'),
    Key('learned_review',   '',              'global', 'review what the agent learned'),
    Key('vault_settings',   '',              'global', 'vault settings: vaults, privacy, cadence, tidy'),
    Key('close_tab',        'alt+w',         'global', 'close tab',           'toast'),
    Key('copy_rel_path',    'alt+y',         'global', 'copy relative path',  'toast'),
    Key('copy_abs_path',    'alt+shift+y',   'global', 'copy absolute path'),
    Key('close_others',     '',              'global', 'close other tabs'),
    Key('close_right',      '',              'global', 'close tabs to the right'),
    Key('close_saved',      '',              'global', 'close saved tabs'),
    Key('next_tab',         'alt+]',         'global', 'next tab'),
    Key('prev_tab',         'alt+[',         'global', 'previous tab'),
    Key('toggle_left',      'alt+shift+b hyper+left', 'global', 'toggle file pane'),
    Key('toggle_right',     'alt+shift+v hyper+right', 'global', 'toggle agent / variables pane'),
    Key('toggle_bottom',    'hyper+down',    'global', 'toggle bottom tools'),
    Key('toggle_scope',     'alt+i',         'global', 'live / isolated',     'toast'),
    Key('interrupt',        'alt+shift+i',    'global', 'interrupt kernel',   'toast'),
    Key('restart',          'alt+shift+r hyper+r', 'global', 'restart kernel'),
    Key('pick_kernel',      'alt+shift+k',   'global', 'choose kernel',       'toast'),
    Key('switch_env',       'alt+shift+e',   'global', 'watch another env',   'toast'),
    Key('edit_runs',        '',              'global', 'run configurations'),
    Key('run_file',         'mod+alt+enter',  'global', 'run this script',    'toast'),
    Key('run_selection',    'hyper+s',       'global', 'run the selection in the kernel'),
    Key('new_notebook',     'hyper+n',       'global', 'new notebook'),
    Key('new_canvas',       'hyper+j',       'global', 'new canvas'),
    Key('notebook_language', '',           'global', 'notebook language'),
    Key('add_folder',       '',              'global', 'stage this folder, ignores first'),
    Key('edit_keys',        'hyper+k',       'global', 'edit keybindings'),
    Key('run_app',          'alt+shift+a',   'global', 'run a configuration', 'toast'),
    Key('terminal',         'ctrl+`',        'global', 'terminal',            'toast'),
    Key('git',              'alt+shift+g',   'global', 'lazygit',             'toast'),
    Key('panel_git',        'hyper+g',       'global', 'source control panel', 'toast'),
    Key('panel_releases',   'hyper+p',       'global', 'releases panel',      'toast'),
    Key('panel_deploys',    'hyper+l',       'global', 'deploys panel',       'toast'),
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
    Key('run_above',        'hyper+enter',     'editor', 'run all cells above'),
    Key('run_below',        'hyper+pageDown',  'editor', 'run this cell and below'),
    Key('run_all',          'mod+shift+enter', 'editor', 'run every cell'),
    Key('restart_run_all',  'hyper+backspace', 'editor', 'restart kernel and run all'),
    Key('cell_select_above','ctrl+shift+up',   'editor', 'select cell above'),
    Key('cell_select_below','ctrl+shift+down', 'editor', 'select cell below'),
    Key('cell_first',       'mod+home',         'editor', 'first cell',          'toast'),
    Key('cell_last',        'mod+end',          'editor', 'last cell',           'toast'),
    Key('cell_page_up',     'alt+pageup',       'editor', 'previous page of cells'),
    Key('cell_page_down',   'alt+pagedown',     'editor', 'next page of cells'),
    Key('cell_move_up',     'alt+shift+up',    'editor', 'move cell up'),
    Key('cell_move_down',   'alt+shift+down',  'editor', 'move cell down'),
    Key('cell_above',       'mod+alt+up',      'editor', 'insert cell above'),
    Key('cell_below',       'mod+alt+down',    'editor', 'insert cell below'),
    Key('cell_delete',      'mod+alt+backspace', 'editor', 'delete cell'),
# Naming these here is what puts them in the palette and the keys help. CodeMirror's own keymap
# already answers them inside an editor, and it is the same command either way.
    Key('indent_more',      'mod+]',           'editor', 'indent'),
    Key('indent_less',      'mod+[',           'editor', 'outdent'),
    Key('indent_selection', 'hyper+]',         'editor', 're-indent to the syntax', 'toast'),
    Key('notebook_undo',    'mod+z',           'editor', 'undo cell operation', 'toast'),
    Key('notebook_redo',    'mod+shift+z',     'editor', 'redo cell operation'),
    Key('cell_type',        'alt+shift+m',     'editor', 'code / markdown / prompt', 'toast'),
    Key('cell_split',       'alt+shift+-',     'editor', 'split cell'),
    Key('cell_split_symbols', 'alt+shift+/',   'editor', 'split into one cell per def', 'toast'),
    Key('cell_collapse',    'hyper+c',         'editor', 'collapse / expand cell'),
    Key('cell_duplicate',   'hyper+d',         'editor', 'duplicate cell below'),
    Key('cell_copy',        'mod+c',           'editor', 'copy cell'),
    Key('cell_cut',         'mod+x',           'editor', 'cut cell'),
    Key('cell_paste_above', '',                'editor', 'paste cell above'),
    Key('cell_paste_below', '',                'editor', 'paste cell below'),
    Key('cell_merge_above', 'hyper+up',        'editor', 'merge cell above'),
    Key('cell_merge_below', 'hyper+pageup',    'editor', 'merge cell below'),
    Key('clear_cell_output','hyper+delete',    'editor', 'clear this cell output'),
    Key('clear_all_outputs','mod+shift+backspace', 'editor', 'clear all outputs'),
    Key('move_line_up',     'alt+up',        'editor', 'move line up',        'toast'),
    Key('move_line_down',   'alt+down',      'editor', 'move line down'),
    Key('comment',          'mod+/',         'editor', 'toggle comment',      'toast'),
    Key('find_similar',     'ctrl+shift+a',  'editor', 'code like this',      'toast'),
    Key('code_map',         'ctrl+shift+m',  'editor', 'code map (clusters)'),
    Key('exec_run',         'mod+enter',     'exec',   'run',                  'footer'),
    Key('exec_newline',     'alt+enter',     'exec',   'newline'),
    Key('exec_prev',        'ctrl+shift+up', 'exec',   'older',               'toast'),
    Key('exec_next',        'ctrl+shift+down', 'exec', 'newer',               'toast'),
    Key('exec_clear',       'alt+shift+l',   'exec',   'clear log'),
    Key('exec_promote',     'mod+shift+g',   'exec',   'run in live namespace'),
    Key('open',             'enter',         'files',  'open / toggle folder','footer'),
    Key('tree_down',        'down',          'files',  'next item',           'footer'),
    Key('tree_up',          'up',            'files',  'previous item'),
    Key('tree_expand',      'right',         'files',  'expand / enter folder'),
    Key('tree_collapse',    'left',          'files',  'collapse / parent'),
    Key('up_dir',           'backspace',     'files',  'parent folder'),
    Key('new_file',         'n',             'files',  'new file',            'toast'),
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
    Key('open_folder',      'o',             'files',  'open folder in a new window', 'toast'),
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
    Key('agent_new',        'mod+shift+n',   'agent',  'new conversation'),
    Key('agent_threads',    'mod+shift+t',   'agent',  'switch conversation'),
    Key('agent_stop',       'alt+shift+c',   'agent',  'stop agent'),
    Key('agent_tools',      'alt+shift+t',   'agent',  'what the agent did'),
    Key('agent_fold_turn',  'alt+shift+j',   'agent',  'fold this turn'),
    Key('agent_fold_all',   'alt+shift+z',   'agent',  'fold every turn'),
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

def _signature(chord):
    "A chord as it collides: modifiers sorted, and `mod` folded into `ctrl`."
    mods, base = parse_key(chord)
    if 'mod' in mods: mods = (mods - {'mod'}) | {'ctrl'}
    return tuple(sorted(mods)), base

def _dupes(keys):
    "(scope, chord) pairs bound twice, and actions declared twice. Both are real conflicts."
    seen, bad = {}, []
    keys = L(keys)
    for k in keys:
        for c in k.keys:
            sig = (k.scope, _signature(c))
            if sig in seen: bad.append(f'{c} is bound by both {seen[sig]} and {k.action} in scope {k.scope}')
            else: seen[sig] = k.action
    acts = keys.attrgot('action')
    bad += [f'action {a!r} declared twice' for a in set(acts) if acts.count(a) > 1]
    g = {_signature(c): k.action for k in keys.filter(lambda k: k.scope == 'global') for c in k.keys}
    for k in keys.filter(lambda k: k.scope != 'global'):
        for c in k.keys:
            if (t := _signature(c)) in g: bad.append(f'{c} is both global ({g[t]}) and {k.scope} ({k.action})')
    return bad

def by_scope(scope): return KEYS.filter(lambda k: k.scope == scope)
def lookup(action): return first(KEYS.filter(lambda k: k.action == action))

def chord_display(action_or_key, sep=' / '):
    "How a binding is written for a person: every chord it answers to, or an em dash when unbound."
    k = lookup(action_or_key) if isinstance(action_or_key, str) else action_or_key
    if k is None: return ''
    return sep.join(k.keys) if k.bound else '—'

def web_keymap():
    "The whole table as JSON-ready rows for the browser handler."
    return [{**asdict(k), 'chords': [web_key(c) for c in k.keys]} for k in KEYS]

def help_rows():
    "Every binding grouped by scope, for the full help overlay: {scope: [(chord_display, label)]}."
    return {s: [(chord_display(k), k.label) for k in by_scope(s) if k.label] for s in SCOPES}

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
        notes.append(f'{p}: {type(e).__name__}: {e} — using the default keys')
        return {}
    if not isinstance(d, dict):
        notes.append(f'{p}: expected an object of action -> chord — using the default keys')
        return {}
    help_text = ' '.join(map(str, d.get('_help') or ()))
    generated_snapshot = isinstance(d.get('keys'), dict) and len(d['keys']) > 50 and 'leela keymap' in help_text
    legacy_generated = generated_snapshot and 'mod is Command' not in help_text
    if isinstance(d.get('keys'), dict): d = d['keys']
    if legacy_generated: d = _migrated(d, _GENERATED_DEFAULT_MIGRATIONS)
    if generated_snapshot: d = _migrated(d, _SNAPSHOT_MIGRATIONS)
    out = {}
    for a, c in d.items():
        if a.startswith('_') or a == 'agent_transcript': continue
        if not isinstance(c, str): notes.append(f'{p}: {a}: {c!r} is not a chord string')
        else: out[a] = c.strip()
    return out

def apply_overrides(keys, over, notes=None):
    "`keys` with the user's chords applied one at a time, skipping what cannot work."
    notes = ifnone(notes, NOTES)
    out = L(list(keys))
    for a, c in (over or {}).items():
        i = out.argfirst(lambda k: k.action == a)
        if i is None:
            notes.append(f'keymap: no action named {a!r}')
            continue
        try: cand = replace(out[i], key=c)
        except ValueError as e:
            notes.append(f'keymap: {a}: {e}')
            continue
        trial = L(list(out)); trial[i] = cand
        if bad := _dupes(trial):
            notes.append(f'keymap: {a} -> {c!r} conflicts ({bad[0]}) — kept {out[i].key or "unbound"}')
            continue
        out = trial
    return out

_BULK = 50

def bulk_map(over):
    "Whether `over` names more actions than a person edits by hand, so a machine wrote it."
    return len(over) > _BULK

def _same_chord(a, b):
    "Whether two chord strings bind the same keys in the same order."
    if a == b: return True
    try: return [_signature(c) for c in a.split()] == [_signature(c) for c in b.split()]
    except ValueError: return False

def only_changed(over, base=None):
    "`over` without the entries that repeat a default."
    d = {k.action: k.key for k in L(ifnone(base, DEFAULTS))}
    return {a: c for a, c in over.items() if not _same_chord(d.get(a, ''), c)}

def keymap_json(keys=None, over=None):
    "The overrides as the JSON a user edits, with every action and its default beside them."
    ks = L(ifnone(keys, KEYS))
    over = ifnone(over, only_changed({k.action: k.key for k in ks}))
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
    eff = only_changed({k.action: k.key for k in L(ifnone(keys, KEYS))})
    guard(p, reason='before the keymap was rewritten')
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(keymap_json(keys, {**kept, **eff}), indent=2) + '\n')
    return p

def reload(path=None):
    "Rebuild `KEYS` from the defaults plus the user's file. Called once at import."
    global KEYS
    NOTES.clear()
    KEYS = apply_overrides(DEFAULTS, read_overrides(path), NOTES)
    return KEYS

if _c := _dupes(DEFAULTS): raise ValueError('keymap conflicts:\n  ' + '\n  '.join(_c))
KEYS = DEFAULTS
reload()
