"""Single-source keymap for both frontends.

Every binding in the IDE is declared once, here, as a `Key`. The Textual app
generates its `Binding`s from `tui_bindings()`; the web app ships the same table
to the browser as JSON via `web_keymap()` and builds its handler and its help
overlay from that. Nothing is hand-duplicated, so the two frontends cannot drift.

Canonical key syntax is `[ctrl+][alt+][shift+]base`, base being a single
printable character or a name (`enter`, `escape`, `tab`, `up`, `f1`, ...).
`shift+<letter>` is written as the bare uppercase letter (`X`), which is what
both toolkits actually deliver. An empty `key` is legal and means *unbound*: the
action still exists, is still clickable, and can still be given a chord in the
user's own keymap.

Scopes form a stack: a binding fires when its scope is the focused pane, or when
its scope is `global`. Two rules keep the map honest, enforced in `Key`:

- `global` bindings fire even while a cell editor has the cursor, so they must
  always carry a modifier -- a bare letter would type a letter.
- the same holds inside any `EDITING_SCOPES` pane.

Chords the browser refuses to hand over (ctrl+w, ctrl+tab, ctrl+n, ...) are
avoided outright rather than bound and silently lost on the web side.

**Two chords per action, not one.** `ctrl+enter`, `shift+enter` and `alt+enter`
only reach an application from a terminal that speaks the kitty keyboard
protocol (kitty, ghostty, WezTerm, recent iTerm2). In Terminal.app they arrive
as a bare `enter`, and `alt+<letter>` arrives as whatever character Option
produces -- so on a stock Mac the most important keys in the IDE are the ones
that cannot be pressed. Every binding that would otherwise be unreachable there
carries a plain function key as its second chord, and nothing important is
keyboard-only in any case: `leela.buttons` gives both frontends a clickable
button for the same actions.

**And the map is the user's to change.** `keys.json` in leela's config dir (or
wherever `$LEELA_KEYMAP` points) maps an action to the chord -- or chords -- it
should answer to:

    {"run_cell": "ctrl+enter f5 ctrl+y", "quit": ""}

It is applied over the defaults at import, one entry at a time; anything
unparseable, unknown or in conflict with the rest of the map is skipped and
reported in `NOTES`, which both frontends show. A broken config file must not
be able to stop the IDE from starting.
"""

import json, os
from dataclasses import dataclass, asdict, replace
from fastcore.all import L, Path, first

__all__ = ['Key', 'SCOPES', 'EDITING_SCOPES', 'WEB_ONLY_SCOPES', 'KEYS', 'DEFAULTS', 'NOTES',
           'parse_key', 'tui_key', 'web_key', 'by_scope', 'tui_bindings', 'web_keymap',
           'help_rows', 'toast_rows', 'lookup', 'chord_display', 'keymap_path', 'read_overrides',
           'apply_overrides', 'keymap_json', 'write_keymap', 'reload']

# Panes that own a text cursor. Bare-letter bindings are refused in these.
# `term` is the strictest of them: a pty consumes every keystroke, so anything bound
# here is a chord deliberately withheld from the child process.
EDITING_SCOPES = ('editor', 'exec', 'agent', 'term')
# Focusable panes, outermost first. `global` bindings fire from any of them.
SCOPES = ('global', 'files', 'editor', 'exec', 'vars', 'agent', 'term')

# Scopes that only one frontend can have. `term` is the browser's embedded pty; the TUI
# has no such pane because it hands the *real* terminal over with `App.suspend()`, so
# there is nothing of its own to close. Declared rather than left implicit, so a binding
# that never fires in the terminal frontend is a decision and not an oversight.
WEB_ONLY_SCOPES = ('term',)

_NAMED = {'enter', 'escape', 'tab', 'backspace', 'delete', 'space', 'up', 'down', 'left', 'right',
          'home', 'end', 'pageup', 'pagedown', *[f'f{i}' for i in range(1, 13)]}

# canonical base -> Textual key name (Textual spells punctuation out)
_TUI_BASE = {'/': 'slash', '\\': 'backslash', '.': 'full_stop', ',': 'comma', '=': 'equals_sign',
             '-': 'minus', '?': 'question_mark', "'": 'apostrophe', ';': 'semicolon',
             '`': 'grave_accent', '[': 'left_square_bracket', ']': 'right_square_bracket'}
# canonical base -> browser KeyboardEvent.key
_WEB_BASE = {'enter': 'Enter', 'escape': 'Escape', 'tab': 'Tab', 'backspace': 'Backspace',
             'delete': 'Delete', 'space': ' ', 'up': 'ArrowUp', 'down': 'ArrowDown',
             'left': 'ArrowLeft', 'right': 'ArrowRight', 'home': 'Home', 'end': 'End',
             'pageup': 'PageUp', 'pagedown': 'PageDown',
             **{f'f{i}': f'F{i}' for i in range(1, 13)}}   # KeyboardEvent.key is 'F2', not 'f2'


def parse_key(k):
    "Canonical chord -> (frozenset of modifiers, base key). 'X' normalises to ({'shift'}, 'x')."
    *mods, base = k.split('+')
    mods = {m.lower() for m in mods}
    if base.lower() in _NAMED: base = base.lower()
    elif len(base) == 1 and base.isupper(): mods, base = mods | {'shift'}, base.lower()
    bad = mods - {'ctrl', 'alt', 'shift'}
    if bad: raise ValueError(f'unknown modifier(s) {sorted(bad)} in {k!r}')
    if base not in _NAMED and len(base) != 1: raise ValueError(f'unknown base key {base!r} in {k!r}')
    return frozenset(mods), base


@dataclass(frozen=True)
class Key:
    'One binding: what it does, the chord that triggers it, and where it is advertised.'
    action: str          # what the frontends dispatch on (`focus_exec` -> action_focus_exec / the JS handler table)
    key: str             # canonical chord, or several alternatives separated by spaces ('f2 r'); '' is unbound
    scope: str = 'global'
    label: str = ''      # human text for help / footer / toast
    show: str = 'help'   # 'footer' (always-visible bar) | 'toast' (left-sidebar cheatsheet) | 'help' (overlay only)

    def __post_init__(self):
        if self.scope not in SCOPES: raise ValueError(f'{self.action}: unknown scope {self.scope!r}')
        if self.show not in ('footer', 'toast', 'help'): raise ValueError(f'{self.action}: bad show {self.show!r}')
        # A binding that can fire while a cell editor holds the cursor must carry a modifier.
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


def tui_key(k):
    "Canonical chord -> a Textual binding string."
    mods, base = parse_key(k)
    base = _TUI_BASE.get(base, base)
    if 'shift' in mods and len(base) == 1: base, mods = base.upper(), mods - {'shift'}
    return '+'.join([*[m for m in ('ctrl', 'alt', 'shift') if m in mods], base])


def web_key(k):
    "Canonical chord -> the dict the browser handler matches a KeyboardEvent against."
    mods, base = parse_key(k)
    key = _WEB_BASE.get(base, base)
    if 'shift' in mods and len(key) == 1: key = key.upper()
    return {'key': key, 'ctrl': 'ctrl' in mods, 'alt': 'alt' in mods, 'shift': 'shift' in mods}


# ---------------------------------------------------------------------------
# The map. Order within a scope is the order shown in help and the toast.
#
# Deliberately avoided, because Chrome will not release them: ctrl+w, ctrl+t,
# ctrl+n, ctrl+tab, ctrl+shift+w. Tab motion uses alt+[ / alt+] instead.
#
# Function keys are the second chord wherever the first one needs a terminal
# that speaks the kitty keyboard protocol. They are allotted once across the
# whole map so that a key means the same thing wherever the cursor is:
#
#   f1  help          f2  rename (files)   f3  command palette   f4  search code
#   f5  run           f6  run and advance  f7  run and insert    f8  run all
#   f9  run this file
#
# f5 is `run` in three scopes -- the cell, the exec box, the agent prompt -- which
# is the same promise `ctrl+enter` makes in each of them.
# ---------------------------------------------------------------------------
DEFAULTS = L(
    # -- global: reachable from any pane, including from inside a cell editor ----------
    Key('focus_files',      'ctrl+b',        'global', 'files',               'footer'),
    Key('focus_editor',     'ctrl+j',        'global', 'editor',              'footer'),
    Key('focus_exec',       'ctrl+e',        'global', 'exec',                'footer'),
    Key('focus_vars',       'ctrl+r',        'global', 'variables',           'footer'),
    Key('focus_agent',      'ctrl+g',        'global', 'agent',               'footer'),
    Key('palette',          'ctrl+shift+p f3', 'global', 'command palette',   'footer'),
    Key('quick_open',       'ctrl+p',        'global', 'open file',           'toast'),
    Key('code_search',      'ctrl+shift+f f4', 'global', 'search code',       'toast'),
    Key('save',             'ctrl+s',        'global', 'save',                'toast'),
    Key('save_all',         'ctrl+alt+s',    'global', 'save all'),
    Key('show_diff',        'ctrl+alt+/',    'global', 'what changed',        'toast'),
    # Both completions and the docstring lookup are global rather than editor-scoped, so
    # they also reach the exec strip -- a half-remembered attribute name is just as likely
    # to need looking up there, and all three handlers already resolve the cursor from
    # whichever editor holds it.
    Key('complete',         'ctrl+space',    'global', 'complete',            'toast'),
    Key('ai_complete',      'ctrl+alt+space', 'global', 'ai completion',      'toast'),
    Key('show_docs',        'ctrl+alt+h',    'global', 'docs for symbol',     'toast'),
    Key('capture',          'ctrl+alt+p',    'global', 'screenshot for the assistant', 'toast'),
    Key('close_tab',        'alt+w',         'global', 'close tab',           'toast'),
    Key('next_tab',         'alt+]',         'global', 'next tab'),
    Key('prev_tab',         'alt+[',         'global', 'previous tab'),
    Key('toggle_left',      'ctrl+alt+b',    'global', 'toggle file pane'),
    Key('toggle_right',     'ctrl+alt+r',    'global', 'toggle variable pane'),
    Key('toggle_scope',     'alt+i',         'global', 'live / isolated',     'toast'),
    Key('interrupt',        'ctrl+alt+i f10', 'global', 'interrupt kernel',   'toast'),
    Key('restart',          'ctrl+alt+k',    'global', 'restart kernel'),
    Key('pick_kernel',      'ctrl+alt+j',    'global', 'choose kernel',       'toast'),
    Key('switch_env',       'ctrl+alt+e',    'global', 'watch another env',   'toast'),
    Key('edit_runs',        '',              'global', 'run configurations'),
    # Running a *file* is its own thing, and not the same as running the cell the cursor is
    # in: it runs the whole buffer as a script, in the tab's kernel, so what it defines is
    # in the variable panel afterwards. `run_app` below is the third thing again -- a
    # long-lived server under an inspector rather than a script that finishes.
    Key('run_file',         'ctrl+alt+enter f9', 'global', 'run this file',   'toast'),
    Key('run_selection',    '',              'global', 'run the selection'),
    Key('new_notebook',     '',              'global', 'new notebook'),
    Key('edit_keys',        '',              'global', 'edit keybindings'),
    Key('run_app',          'ctrl+alt+d',    'global', 'run app under inspector', 'toast'),
    Key('terminal',         'ctrl+alt+`',    'global', 'terminal',            'toast'),
    Key('git',              'ctrl+alt+v',    'global', 'lazygit',             'toast'),
    Key('web_search',       'ctrl+alt+w',    'global', 'search the web',      'toast'),
    Key('research',         'ctrl+alt+n',    'global', 'research a question'),
    Key('read_url',         'ctrl+alt+u',    'global', 'read a url'),
    Key('help',             'f1',            'global', 'keys',                'footer'),
    Key('quit',             'ctrl+alt+q',    'global', 'quit',                'footer'),
    *[Key(f'tab_{i}', f'alt+{i}', 'global', f'tab {i}') for i in range(1, 10)],

    # -- editor: notebook cells and plain files ---------------------------------------
    Key('run_cell',         'ctrl+enter f5', 'editor', 'run cell',            'footer'),
    Key('run_advance',      'shift+enter f6', 'editor', 'run and advance',    'footer'),
    Key('run_insert',       'alt+enter f7',  'editor', 'run and insert below'),
    Key('run_all',          'f8',            'editor', 'run every cell'),
    Key('cell_above',       'ctrl+alt+up',   'editor', 'insert cell above'),
    Key('cell_below',       'ctrl+alt+down', 'editor', 'insert cell below'),
    Key('cell_delete',      'ctrl+alt+delete', 'editor', 'delete cell'),
    Key('cell_type',        'ctrl+alt+m',    'editor', 'code / markdown / prompt', 'toast'),
    Key('cell_split',       'ctrl+alt+-',    'editor', 'split cell'),
    Key('comment',          'ctrl+/',        'editor', 'toggle comment',      'toast'),
    Key('find_similar',     'ctrl+shift+a',  'editor', 'code like this',      'toast'),
    Key('code_map',         'ctrl+shift+m',  'editor', 'code map (clusters)'),

    # -- exec strip: the merged live/isolated box -------------------------------------
    Key('exec_run',         'ctrl+enter f5', 'exec',   'run',                 'footer'),
    Key('exec_newline',     'alt+enter f7',  'exec',   'newline'),
    Key('exec_prev',        'ctrl+up',       'exec',   'older',               'toast'),
    Key('exec_next',        'ctrl+down',     'exec',   'newer',               'toast'),
    Key('exec_clear',       'ctrl+l',        'exec',   'clear log'),
    Key('exec_promote',     'ctrl+alt+g',    'exec',   'run in live namespace'),

    # -- files: the left tree (no text cursor, so bare letters are fine) --------------
    Key('open',             'enter',         'files',  'open',                'footer'),
    Key('up_dir',           'backspace',     'files',  'up'),
    Key('new_file',         'a',             'files',  'new file',            'toast'),
    Key('new_dir',          'A',             'files',  'new folder',          'toast'),
    Key('rename',           'f2 r',          'files',  'rename',              'toast'),
    Key('delete',           'd',             'files',  'delete'),
    Key('refresh_files',    'R',             'files',  'refresh'),
    Key('add_root',         'o',             'files',  'open folder',         'toast'),
    Key('filter_files',     '/',             'files',  'filter'),

    # -- vars: the right-hand inspector -----------------------------------------------
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

    # -- agent session (bottom centre) -------------------------------------------------
    Key('agent_send',       'ctrl+enter f5', 'agent',  'send',                'footer'),
    Key('agent_stop',       'ctrl+alt+c',    'agent',  'stop agent'),
    Key('agent_transcript', 'ctrl+alt+t',    'agent',  'transcript'),
    Key('agent_tools',      'ctrl+alt+l',    'agent',  'what the agent did'),

    # -- terminal: a real pty, so almost every chord belongs to the child process.
    # Only what the pty must not swallow is bound here; `git` and the focus keys are
    # global and already reach this pane.
    Key('term_close',       'ctrl+alt+x',    'term',   'close terminal',      'toast'),
)


def _dupes(keys):
    "(scope, chord) pairs bound twice, and actions declared twice -- both are real conflicts."
    seen, bad = {}, []
    keys = L(keys)
    for k in keys:
        for c in k.keys:
            sig = (k.scope, tui_key(c))
            if sig in seen: bad.append(f'{c} is bound by both {seen[sig]} and {k.action} in scope {k.scope}')
            else: seen[sig] = k.action
    acts = keys.attrgot('action')
    bad += [f'action {a!r} declared twice' for a in set(acts) if acts.count(a) > 1]
    # A global chord that collides with a scoped one is ambiguous when that pane has focus.
    g = {tui_key(c): k.action for k in keys.filter(lambda k: k.scope == 'global') for c in k.keys}
    for k in keys.filter(lambda k: k.scope != 'global'):
        for c in k.keys:
            if (t := tui_key(c)) in g: bad.append(f'{c} is both global ({g[t]}) and {k.scope} ({k.action})')
    return bad


def by_scope(scope): return KEYS.filter(lambda k: k.scope == scope)
def lookup(action): return first(KEYS.filter(lambda k: k.action == action))


def chord_display(action_or_key, sep=' / '):
    "How a binding is written for a person: every chord it answers to, or an em dash when unbound."
    k = lookup(action_or_key) if isinstance(action_or_key, str) else action_or_key
    if k is None: return ''
    return sep.join(k.keys) if k.bound else '—'


def tui_bindings(scope):
    """[(textual_key, action, label, show_in_footer)] for one scope -- feed straight into Textual `Binding`s.

    One Binding per chord, but only the *first* chord of an action is shown in the footer:
    every alternative is real and fires, and a footer that listed `ctrl+enter` and `f5` as
    two separate entries would say the same thing twice in the row with the least room.
    """
    return [(tui_key(c), k.action, k.label, k.show == 'footer' and i == 0)
            for k in by_scope(scope) for i, c in enumerate(k.keys)]


def web_keymap():
    "The whole table as JSON-ready rows for the browser handler."
    return [{**asdict(k), 'chords': [web_key(c) for c in k.keys]} for k in KEYS]


def help_rows():
    "Every binding grouped by scope, for the full help overlay: {scope: [(chord_display, label)]}."
    return {s: [(chord_display(k), k.label) for k in by_scope(s) if k.label] for s in SCOPES}


def toast_rows():
    """The short cheatsheet for the left sidebar: keys that earn space but are not in the footer.

    Alternatives are separated by a space rather than ` / ` because this list is rendered
    in a sidebar a few characters wider than the longest chord in it, and the fallback
    chord is exactly what a reader on a terminal that eats the first one needs to see.
    """
    return [(chord_display(k, sep=' '), k.label) for k in KEYS if k.show == 'toast']


# ---------------------------------------------------------------------------
# the user's own keymap
# ---------------------------------------------------------------------------
NOTES = L()          # what went wrong reading it, in the words the frontends show


def keymap_path(path=None):
    "Where overrides are read from: the argument, else `$LEELA_KEYMAP`, else `<config>/keys.json`."
    from . import leela_cfg
    return Path(path or os.environ.get('LEELA_KEYMAP') or (leela_cfg/'keys.json'))


def read_overrides(path=None, notes=None):
    """`{action: chord}` from the user's keymap file. Never raises -- a broken file is a note.

    Two shapes are accepted, because both are things people write: the mapping at the top
    level, or under a `keys` key alongside whatever else they keep in the file. Anything
    starting with `_` is treated as a comment, so the template can explain itself in the
    file it is explaining.
    """
    p = Path(path or keymap_path())
    notes = NOTES if notes is None else notes
    try: d = json.loads(p.read_text())
    except FileNotFoundError: return {}
    except Exception as e:
        notes.append(f'{p}: {type(e).__name__}: {e} — using the default keys')
        return {}
    if not isinstance(d, dict):
        notes.append(f'{p}: expected an object of action -> chord — using the default keys')
        return {}
    if isinstance(d.get('keys'), dict): d = d['keys']
    out = {}
    for a, c in d.items():
        if a.startswith('_'): continue
        if not isinstance(c, str): notes.append(f'{p}: {a}: {c!r} is not a chord string')
        else: out[a] = c.strip()
    return out


def apply_overrides(keys, over, notes=None):
    """`keys` with the user's chords applied, entry by entry, skipping what cannot work.

    Applied one at a time and conflict-checked against the map as it stands, rather than
    all at once and validated at the end: a single typo should cost that one binding, not
    the whole file. What is skipped goes into `notes` and is shown in the IDE, because a
    keymap that silently ignores half of what you wrote is worse than no keymap at all.
    """
    notes = NOTES if notes is None else notes
    # `L(an_L)` hands back the *same* object (fastcore's NewChkMeta), so both of these
    # copy through a plain list -- otherwise a rejected override would still have been
    # written into the map it was being trialled against, defaults included.
    out = L(list(keys))
    for a, c in (over or {}).items():
        i = next((j for j, k in enumerate(out) if k.action == a), None)
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


def keymap_json(keys=None):
    "The effective map as the JSON a user would edit, with a comment explaining the format."
    ks = KEYS if keys is None else L(keys)
    return {'_help': ['leela keymap: action -> chord, or several chords separated by spaces.',
                      'A chord is [ctrl+][alt+][shift+]base; base is a character or a name '
                      '(enter, escape, tab, space, up, f1..f12).',
                      'An empty string unbinds the action. Delete an entry to take leela\'s default.',
                      'Anything unparseable or conflicting is skipped and reported in the IDE.'],
            'keys': {k.action: k.key for k in ks}}


def write_keymap(path=None, keys=None):
    "Write the effective map where the user can edit it, and return the path."
    p = Path(path or keymap_path())
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(keymap_json(keys), indent=2) + '\n')
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
