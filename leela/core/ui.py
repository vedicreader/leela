"Shared UI atoms: keyboard-aware buttons, action bars, activity icons."

from __future__ import annotations
from dataclasses import dataclass
from fastcore.all import L
from .keys import KEYS, chord_display, lookup
from fasthtml.common import Button, Div, NotStr

__all__ = ['Btn', 'BARS', 'BUTTONS', 'bar', 'tip', 'btn', 'action_bar', 'menu_button',
           'activity_icon', 'ICONS']

# The `web_` prefix names the bars added later, not the browser's own: nothing filters on it.
BARS = ('toolbar', 'cell', 'files', 'keys', 'exec', 'vars', 'agent',
        'web_editor', 'web_files', 'web_vars')

def _with_chord(what, action):
    "`what`, plus the chord that also does it when there is one."
    c = chord_display(action)
    return f'{what}  ({c})' if c and c != '–' else what

@dataclass(frozen=True)
class Btn:
    "One clickable control: the action it runs, its face, and the bar it belongs to."
    action: str
    label: str
    title: str = ''
    bar: str = 'toolbar'
    kind: str = ''
    def __post_init__(self):
        if self.bar not in BARS: raise ValueError(f'{self.action}: unknown bar {self.bar!r}')
    @property
    def tooltip(self):
        "What to show on hover: what it does, and the key that also does it."
        k = lookup(self.action)
        return _with_chord(self.title or (k.label if k else self.action), self.action)

BUTTONS = L(
    Btn('run_cell',     '▶ run',    'run the current cell',            'toolbar', 'go'),
    Btn('run_advance',  '▶ next',   'run it and move on',              'toolbar'),
    Btn('run_all',      '▶ all',    'run every cell, top to bottom',   'toolbar'),
    Btn('clear_all_outputs', 'clear',    'clear every cell output',   'toolbar'),
    Btn('run_file',     '▶ file',   'run the whole file in the kernel','toolbar'),
    Btn('run_selection','▶ sel',    'run only the selection',       'toolbar'),
    Btn('cell_below',   '+ cell',   'insert a cell below',             'toolbar'),
    Btn('notebook_undo','undo',     'undo the last cell operation',     'toolbar'),
    Btn('notebook_redo','redo',     'redo the last cell operation',     'toolbar'),
    Btn('cell_type',    'type',     'code / markdown / prompt',        'toolbar'),
    Btn('save',         'save',     'save this tab',                   'toolbar'),
    Btn('show_diff',    'diff',     'what changed since the last save','toolbar'),
    Btn('interrupt',    'stop',     'interrupt the kernel',            'toolbar', 'warn'),
    Btn('restart',      'restart',  'restart the kernel',              'toolbar', 'warn'),
    Btn('run_app',      'run',      'start a run configuration under an inspector', 'toolbar'),
    Btn('pick_kernel',  'kernel',   'choose the kernel and interpreter','toolbar'),
    Btn('present_notebook', 'present', 'present the notebook as slides', 'toolbar'),
    Btn('palette',      'cmds',     'command palette',                 'toolbar'),
    Btn('help',         'keys',     'every binding',                   'toolbar'),
    Btn('run_cell',     '▶',        'run this cell',                   'cell', 'go'),
    Btn('stop_cell',    '■',        'stop this cell; restart its kernel if interrupt is ignored', 'cell', 'warn'),
    Btn('run_above',    '↑▶',       'run every code cell above this one','cell'),
    Btn('run_insert',   '▶+',       'run it and open a new cell below','cell'),
    Btn('cell_move_up', '↑',        'move this cell up',               'cell'),
    Btn('cell_move_down','↓',        'move this cell down',             'cell'),
    Btn('cell_type',    '↻',        'code / markdown / prompt',        'cell'),
    Btn('cell_below',   '+',        'insert a cell below',             'cell'),
    Btn('cell_delete',  '×',        'delete this cell',                'cell', 'warn'),
    Btn('new_file',     '+file',    'new file',                        'files'),
    Btn('new_notebook', '+nb',      'new notebook',                    'files'),
    Btn('new_dir',      '+dir',     'new folder',                      'files'),
    Btn('refresh_files','⟳',        'reread the tree',                 'files'),
    Btn('show_hidden',  '.*',       'show dotfiles like .gitignore and .github', 'files'),
    Btn('open_folder',  'open…',    'open a file or a folder', 'files'),
    Btn('add_root',     'add…',     'add a folder to this window',     'files'),
    Btn('help',         'all',      'every binding',                   'keys'),
    Btn('edit_keys',    'edit',     'change these keys',               'keys'),
    Btn('exec_run',     '▶ run',    'run this in the kernel',          'exec', 'go'),
    Btn('toggle_scope', 'live/iso', 'run live, or sandboxed',          'exec'),
    Btn('exec_clear',   'clear',    'clear the log',                   'exec'),
    Btn('switch_env',   'env…',     'watch another live namespace',    'vars'),
    Btn('edit_value',   'set',      'set the selected variable',       'vars'),
    Btn('promote',      '→live',    'copy it into the live namespace', 'vars'),
    Btn('copy_value',   'copy',     'copy its value',                  'vars'),
    Btn('agent_send',   '▶ send',   'ask the assistant',               'agent', 'go'),
    Btn('agent_stop',   'stop',     'stop the turn in flight',         'agent', 'warn'),
    Btn('agent_tools',  'what it did', 'tool calls and diffs',         'agent'),
    Btn('show_docs',    'docs',     'docs for the symbol at the cursor','web_editor'),
    Btn('find_similar', 'similar',  'code like the symbol at the cursor','web_editor'),
    Btn('code_map',     'map',      'code clusters across this project','web_editor'),
    Btn('quick_open',   'go to file…', 'go to a file in the open folders', 'web_files'),
    Btn('grid',         'grid',     'open the selected table or array','web_vars'),
)

def bar(name):
    "The buttons for one bar, in declaration order."
    return BUTTONS.filter(lambda b: b.bar == name)

def tip(action):
    "The tooltip for an action, whether or not it has a button: the label plus its chord."
    k = lookup(action)
    return _with_chord(k.label if (k and k.label) else action, action)

_acts = set(KEYS.attrgot('action'))
if _m := sorted({b.action for b in BUTTONS} - _acts):
    raise ValueError('buttons name actions the keymap does not declare: ' + ', '.join(_m))


def btn(b):
    "One button from the shared table. The click runs the same action its key runs."
    return Button(b.label, cls='lee-btn ' + (b.kind or 'plain'), title=b.tooltip,
                  data_action=b.action, onclick=f'leeAct("{b.action}")')

def action_bar(name, **kw):
    "A whole bar of them, in the order `leela.core.ui` declares."
    return Div(*bar(name).map(btn), cls=f'lee-bar lee-bar-{name}', **kw)

def menu_button(surface):
    "Mouse-discoverable door into the same contextual registry used by right-click."
    return Button('⋯', cls='lee-more', title=f'{surface} actions', aria_label=f'{surface} actions',
                  onclick=f'leeMenuAt("{surface}", this)')

ICONS = {
    'files': '<path d="M2.5 5.5h6l1.7 2h7.3v8.5h-15zM2.5 5.5V4h5l1.5 1.5"/>',
    'symbols': '<path d="M5 3.5h10M5 10h10M5 16.5h10"/><circle cx="3" cy="3.5" r="1"/>'
               '<circle cx="3" cy="10" r="1"/><circle cx="3" cy="16.5" r="1"/>',
    'workflows': '<circle cx="4" cy="10" r="2"/><circle cx="16" cy="5" r="2"/><circle cx="16" cy="15" r="2"/>'
                 '<path d="M6 9.3 14 5.7M6 10.7 14 14.3"/>',
    'releases': '<path d="M3 7.5 10 4l7 3.5v5L10 16l-7-3.5z"/><path d="M10 9.5 17 6M10 9.5 3 6M10 9.5V16"/>',
    'deploys': '<rect x="2.5" y="11" width="7" height="6" rx="1"/><rect x="11.5" y="3" width="6" height="5" rx="1"/>'
               '<path d="M9.5 12.5h3a2 2 0 0 0 2-2V8"/>',
    'drive': '<rect x="3" y="3" width="14" height="3.5" rx="1"/><rect x="3" y="8.25" width="14" height="3.5" rx="1"/>'
             '<rect x="3" y="13.5" width="14" height="3.5" rx="1"/>',
    'git': '<circle cx="5" cy="4" r="2"/><circle cx="15" cy="6" r="2"/><circle cx="5" cy="16" r="2"/>'
           '<path d="M5 6v8m2-7h4a4 4 0 0 1 4 4v-3"/>',
}

def activity_icon(kind):
    "Small monochrome activity-bar icons; labels remain available to assistive tech."
    return NotStr(f'<svg viewBox="0 0 20 20" aria-hidden="true">{ICONS.get(kind, ICONS["git"])}</svg>')
