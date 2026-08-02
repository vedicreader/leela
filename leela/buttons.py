"""Single-source button bars for both frontends.

`leela.keys` is the same idea for the keyboard: declare a thing once, and let each
frontend render it. This is the other half of the promise, and it exists because a
keyboard-only IDE is only as good as the terminal it is running in. `ctrl+enter` does
not survive Terminal.app, `alt+<letter>` does not survive macOS at all unless Option is
configured as Meta, and a browser keeps a dozen chords for itself. None of that is
leela's to fix -- but nothing important should be *reachable only* by a chord that a
particular terminal happens to swallow.

So every button here names an action from `leela.keys`, which is the same action the
keymap dispatches, which is the same `action_*` method on the Textual app and the same
entry in the browser's handler table. A button and a key are two doors into one room.
The import-time check below is what keeps it that way: a button naming an action the
keymap does not declare stops the package from importing, exactly as a duplicate chord
does.

Labels are short on purpose. A terminal toolbar is one row and the panes it sits above
matter more than it does; glyphs are kept to ones a monospace font reliably has.
"""

from dataclasses import dataclass
from fastcore.all import L

from .keys import KEYS, chord_display, lookup

__all__ = ['Btn', 'BARS', 'BUTTONS', 'bar', 'tip']

# Where a bar is drawn. `cell` is per-cell and only the browser has room for it; the
# terminal puts the same three actions in the main toolbar, acting on the selected cell.
BARS = ('toolbar', 'cell', 'files', 'keys', 'exec', 'vars', 'agent')


@dataclass(frozen=True)
class Btn:
    'One clickable control: the action it runs, its face, and the bar it belongs to.'
    action: str          # must name a `leela.keys` action
    label: str           # the button face
    title: str = ''      # tooltip; the keymap's own label when blank
    bar: str = 'toolbar'
    kind: str = ''       # '' | 'go' (the primary action of its bar) | 'warn'

    def __post_init__(self):
        if self.bar not in BARS: raise ValueError(f'{self.action}: unknown bar {self.bar!r}')

    @property
    def tooltip(self):
        "What to show on hover: what it does, and the key that also does it."
        k = lookup(self.action)
        what = self.title or (k.label if k else self.action)
        c = chord_display(self.action)
        return f'{what}  ({c})' if c and c != '—' else what


BUTTONS = L(
    # -- the main toolbar, above the editor -------------------------------------------
    Btn('run_cell',     '▶ run',    'run the current cell',            'toolbar', 'go'),
    Btn('run_advance',  '▶ next',   'run it and move on',              'toolbar'),
    Btn('run_all',      '▶ all',    'run every cell, top to bottom',   'toolbar'),
    Btn('run_file',     '▶ file',   'run the whole file in the kernel','toolbar'),
    Btn('run_selection','▶ sel',    'run just what is selected',       'toolbar'),
    Btn('cell_below',   '+ cell',   'insert a cell below',             'toolbar'),
    Btn('cell_type',    'type',     'code / markdown / prompt',        'toolbar'),
    Btn('save',         'save',     'save this tab',                   'toolbar'),
    Btn('show_diff',    'diff',     'what changed since the last save','toolbar'),
    Btn('interrupt',    'stop',     'interrupt the kernel',            'toolbar', 'warn'),
    Btn('restart',      'restart',  'restart the kernel',              'toolbar', 'warn'),
    Btn('run_app',      'run',      'start a run configuration under an inspector', 'toolbar'),
    Btn('pick_kernel',  'kernel',   'choose the kernel and interpreter','toolbar'),
    Btn('palette',      'cmds',     'command palette',                 'toolbar'),
    Btn('help',         'keys',     'every binding',                   'toolbar'),

    # -- per-cell, in the gutter ------------------------------------------------------
    Btn('run_cell',     '▶',        'run this cell',                   'cell', 'go'),
    Btn('run_insert',   '▶+',       'run it and open a new cell below','cell'),
    Btn('cell_type',    '↻',        'code / markdown / prompt',        'cell'),
    Btn('cell_below',   '+',        'insert a cell below',             'cell'),
    Btn('cell_delete',  '×',        'delete this cell',                'cell', 'warn'),

    # -- the file tree ----------------------------------------------------------------
    Btn('new_file',     '+file',    'new file',                        'files'),
    Btn('new_notebook', '+nb',      'new notebook',                    'files'),
    Btn('new_dir',      '+dir',     'new folder',                      'files'),
    Btn('refresh_files','⟳',        'reread the tree',                 'files'),
    Btn('add_root',     'open…',    'open another folder',             'files'),

    # -- the cheatsheet panel ---------------------------------------------------------
    Btn('help',         'all',      'every binding',                   'keys'),
    Btn('edit_keys',    'edit',     'change these keys',               'keys'),

    # -- the exec strip ---------------------------------------------------------------
    Btn('exec_run',     '▶ run',    'run this in the kernel',          'exec', 'go'),
    Btn('toggle_scope', 'live/iso', 'run live, or sandboxed',          'exec'),
    Btn('exec_clear',   'clear',    'clear the log',                   'exec'),

    # -- the variable panel -----------------------------------------------------------
    Btn('switch_env',   'env…',     'watch another live namespace',    'vars'),
    Btn('edit_value',   'set',      'set the selected variable',       'vars'),
    Btn('promote',      '→live',    'copy it into the live namespace', 'vars'),
    Btn('copy_value',   'copy',     'copy its value',                  'vars'),
    Btn('sort',         'sort',     'cycle the sort order',            'vars'),

    # -- the agent session ------------------------------------------------------------
    Btn('agent_send',   '▶ send',   'ask the assistant',               'agent', 'go'),
    Btn('agent_stop',   'stop',     'stop the turn in flight',         'agent', 'warn'),
    Btn('agent_tools',  'what it did', 'tool calls and diffs',         'agent'),
    Btn('agent_transcript', 'transcript', 'the conversation so far',   'agent'),
)


def bar(name):
    "The buttons for one bar, in declaration order."
    return BUTTONS.filter(lambda b: b.bar == name)


def tip(action):
    "The tooltip for an action, whether or not it has a button -- the label plus its chord."
    k = lookup(action)
    c = chord_display(action)
    what = k.label if (k and k.label) else action
    return f'{what}  ({c})' if c and c != '—' else what


_acts = set(KEYS.attrgot('action'))
if _m := sorted({b.action for b in BUTTONS} - _acts):
    raise ValueError('buttons name actions the keymap does not declare: ' + ', '.join(_m))
