"""The terminal IDE.

The same `Workspace`, `Notebook` and `Kernel` the web frontend drives, rendered
with Textual. Layout mirrors the browser deliberately -- files and a key
cheatsheet left, tabs and cells centre, exec strip and agent below, variables
right -- so muscle memory carries between the two.

Bindings are not written here. Each pane declares `BINDINGS` generated from
`leela.keys` for its own scope, and Textual's focus chain then does
exactly what the scope model describes: the focused pane's bindings win, and
`global` sits on the App underneath them all. Adding a key in Python lights it
up here and in the browser at once.

Neither are the buttons. Every toolbar in here is generated from
`leela.buttons`, and a click runs `app.<action>` -- the same action the same
key runs. That matters more in the terminal than in the browser: `ctrl+enter`,
`shift+enter` and `alt+<key>` only reach a Textual app from a terminal that
speaks the kitty keyboard protocol, and in Terminal.app they simply do not
arrive. The keys are still there for terminals that deliver them, every one of
them is rebindable in `keys.json`, and nothing is reachable *only* by a chord.

Cells are `TextArea`s with `language='python'`, which is tree-sitter
highlighting via textual[syntax] -- the same grammar family the file editor uses
for every other language.
"""

from __future__ import annotations
import asyncio, json, subprocess
from functools import partial
from fastcore.all import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Provider
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, Label, OptionList, Static, Tree, TextArea, Tabs, Tab
from rich.text import Text

from ..inspect.core import GHDK, SORTS
from .. import errstr
from ..buttons import bar as btn_bar
from ..diffs import diff_label, diff_rows, did_you_mean, fuzzy_rank, udiff
from ..keys import (KEYS, NOTES, WEB_ONLY_SCOPES, chord_display, keymap_path, tui_bindings,
                    toast_rows, help_rows, write_keymap)
from ..term import lazygit_argv, LazygitMissing
from ..nb import Notebook, Cell
from ..runs import RUNS_FILE
from ..workspace import Workspace

__all__ = ['IdeApp', 'run']

PAL = GHDK


def _binds(scope):
    """Textual Bindings for one scope, straight from the shared keymap.

    Actions are namespaced to `app.` because every `action_*` method lives on `IdeApp`,
    while the bindings themselves are declared on the pane that owns the scope. Textual
    resolves an unqualified action against the widget that *declared* the binding and does
    not fall back to the app -- so without this prefix every scoped binding is silently
    dead: it is listed in the footer and in `f1`, and no key press ever reaches a handler.
    """
    return [Binding(k, f'app.{a}', l, show=s) for k, a, l, s in tui_bindings(scope)]


# Textual's TextArea knows these; anything else falls back to plain text.
_TA_LANGS = {'python', 'markdown', 'json', 'yaml', 'html', 'css', 'javascript',
             'sql', 'toml', 'bash', 'rust', 'go', 'java', 'xml'}
def _ta_lang(name): return name if name in _TA_LANGS else None


# Diff colours match the browser's, because the two frontends are meant to be the same
# IDE. The marker column is painted rather than taken from the text, which is why
# `diff_rows` strips it: one parse, two renderers, neither re-deriving the other's.
_DIFF_STYLE = {'add': PAL['green'], 'del': PAL['red'], 'hunk': PAL['aqua'],
               'head': PAL['gray'], 'ctx': PAL['fg2']}
_DIFF_MARK = {'add': '+', 'del': '-', 'ctx': ' ', 'hunk': '', 'head': ''}


def diff_text(rows):
    "A parsed unified diff as `rich.Text`, with the new-side line number in a gutter."
    if not rows: return Text('(no changes)', style=PAL['gray'])
    t = Text(no_wrap=True, overflow='ellipsis')
    for r in rows:
        t.append(f"{r.line or '':>5} ", style=PAL['fg4'])
        t.append(f"{_DIFF_MARK[r.kind]}{r.text}\n", style=_DIFF_STYLE[r.kind])
    return t


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
class ActionCommands(Provider):
    """Every keymap action, in the command palette, findable by name.

    The third door into the same room, and the one that scales: a toolbar has room for
    the dozen actions worth a permanent button, while this has room for all of them --
    including the ones whose chord the terminal ate, and the ones deliberately left
    unbound so a user can claim the chord themselves.
    """
    def _rows(self):
        for k in KEYS:
            if k.scope in WEB_ONLY_SCOPES: continue
            yield (f'{k.label or k.action}', k.action,
                   f'{k.scope} · {chord_display(k.action)}')

    async def discover(self):
        for text, action, help in self._rows():
            yield DiscoveryHit(text, partial(self.app.run_action, f'app.{action}'), help=help)

    async def search(self, query):
        m = self.matcher(query)
        for text, action, help in self._rows():
            if (score := m.match(text)):
                yield Hit(score, m.highlight(text), partial(self.app.run_action, f'app.{action}'), help=help)


# ---------------------------------------------------------------------------
# buttons
# ---------------------------------------------------------------------------
class ActionBar(Horizontal):
    """One row of clickable buttons, generated from `leela.buttons`.

    The action is namespaced to `app.` for the same reason `_binds` namespaces the keys:
    every `action_*` method lives on `IdeApp`, while the button itself is mounted inside a
    pane, and Textual resolves an unqualified action against the widget that declared it.
    So a button and its key end up in exactly the same handler, by construction.

    One row, and it clips: a horizontal scrollbar would eat the row the buttons are in.
    Whatever falls off a narrow terminal is still in the command palette.
    """
    def __init__(self, name, **kw):
        super().__init__(**kw)
        self.bar_name = name
        self.add_class('actionbar')

    def compose(self):
        for i, b in enumerate(btn_bar(self.bar_name)):
            btn = Button(b.label, id=f'b-{self.bar_name}-{i}', action=f'app.{b.action}',
                         tooltip=b.tooltip, compact=True, flat=True,
                         classes='leebtn ' + (b.kind or 'plain'))
            btn.can_focus = False    # tab-order belongs to the editors, not to a toolbar
            yield btn


# ---------------------------------------------------------------------------
# panes
# ---------------------------------------------------------------------------
class FileTree(Tree):
    "The left tree over every open folder. Directories load lazily, as in the web frontend."
    BINDINGS = _binds('files')

    def __init__(self, ws, **kw):
        super().__init__('files', **kw)
        self.ws = ws
        self.show_root = False
        self.guide_depth = 2

    def on_mount(self): self.reload_roots()

    def reload_roots(self):
        self.clear()
        for e in self.ws.fs.ls(None):
            self.root.add(Text(e.name, style=f"bold {PAL['aqua']}"), data=e, allow_expand=True)
        self.root.expand()

    def _add(self, node, e):
        style = PAL['blue'] if e.is_dir else PAL['fg2']
        return node.add(Text(e.name, style=style), data=e, allow_expand=e.is_dir)

    async def on_tree_node_expanded(self, ev):
        e = ev.node.data
        if e is None or not e.is_dir or ev.node.children: return
        try:
            for c in self.ws.fs.ls(e.path): self._add(ev.node, c)
        except Exception as ex: self.app.notify(str(ex), severity='error')

    async def on_tree_node_selected(self, ev):
        e = ev.node.data
        if e is not None and not e.is_dir: await self.app.open_path(e.path)

    @property
    def sel(self):
        n = self.cursor_node
        return n.data if n is not None else None


class KeyToast(VerticalScroll):
    "The cheatsheet: keys worth advertising that do not fit the footer."
    def compose(self):
        for k, lbl in toast_rows():
            yield Label(Text.assemble((f'{k:16}', f"bold {PAL['aqua']}"), (lbl, PAL['fg4'])))


def screen_capture(app, title=None):
    """The app's own screen, as `(svg, text)`.

    Textual's `export_screenshot` builds a recording `rich.Console`, prints the
    compositor's render into it, and exports SVG. The same console can also export plain
    text, so one render gives both -- and they are genuinely different products. The SVG
    is for a person to look at; the text is what the assistant should be handed, because
    a terminal screen *is* a grid of characters and a picture of text is a worse copy of
    it, at perhaps fifty times the tokens.

    `screen._compositor` is private, and is reached here because it is what Textual's own
    public `export_screenshot` reaches. If a future version moves it, the caller falls
    back to SVG alone rather than losing the feature.
    """
    import io
    from rich.console import Console
    w, h = app.size
    console = Console(width=w, height=h, file=io.StringIO(), force_terminal=True,
                      color_system='truecolor', record=True, legacy_windows=False, safe_box=False)
    console.print(app.screen._compositor.render_update(
        full=True, screen_stack=app._background_screens, simplify=True))
    # `clear=False`: rich's exporters empty the record buffer by default, so exporting SVG
    # first and text second would hand back an empty string for the half that matters.
    return (console.export_svg(title=title or app.title, clear=False),
            console.export_text(clear=False))


_TRAIL = '<details><summary>what I did'


def _strip_trail(reply):
    """Drop the folded tool trail from a reply before rendering it here.

    The trail is markdown with `<details>` in it, which is exactly right for the saved
    notebook -- Jupyter folds it, and a reader next week can open it -- and exactly wrong
    for a Rich renderer, which prints the tags. The same information is already above the
    reply as activity lines, so here it is redundant as well as ugly.
    """
    i = reply.find(_TRAIL)
    return reply if i < 0 else reply[:i].rstrip()


def _then(_, i):
    "Run an edit for its effect and return the cell index to land on -- see `IdeApp._struct`."
    return i


def _cell_title(c):
    "A cell's own mark, so the three kinds are told apart without reading any of them."
    if c.cell_type == 'code': return f"[{c.execution_count or ' '}]"
    return '✦ ask' if c.is_prompt else 'md'


class CellBox(Vertical):
    """One notebook cell: a highlighted editor plus its output (or, for a prompt cell, its answer).

    `whole_file` is the same widget doing the other job. A plain file opens as a one-cell
    document so that one editor path serves both, which was right -- except that a cell is
    capped at twenty rows, and a *file* rendered in twenty rows with the rest simply not
    drawn is not an editor. In file mode the box takes the pane instead, and the TextArea
    scrolls inside it.
    """
    def __init__(self, cell: Cell, i: int, whole_file=False, lang=None, title='', **kw):
        super().__init__(**kw)
        self.cell, self.i, self.whole_file, self.lang = cell, i, whole_file, lang
        self.file_title = title
        if whole_file: self.add_class('filecell')

    def _title(self):
        "A file says which file it is; a cell says which kind of cell it is."
        return self.file_title if (self.whole_file and self.file_title) else _cell_title(self.cell)

    def compose(self):
        lang = _ta_lang(self.lang or ('python' if self.cell.cell_type == 'code' else 'markdown'))
        ta = TextArea(self.cell.source, language=lang,
                      theme='vscode_dark', soft_wrap=True, tab_behavior='indent',
                      id=f'ta-{self.cell.id}', classes='cellta')
        ta.show_line_numbers = self.whole_file
        ta.border_title = self._title()
        yield ta
        # The output is scrolled, not clipped. It has a ceiling -- one `df.describe()`
        # should not push the next cell off the screen -- but a ceiling that hides the last
        # line of a traceback with no way to reach it is the bug this pane had.
        with VerticalScroll(id=f'outwrap-{self.cell.id}', classes='cellout'):
            yield Static('', id=f'out-{self.cell.id}')

    @property
    def ta(self): return self.query_one(f'#ta-{self.cell.id}', TextArea)

    def show_outputs(self):
        try:
            out = self.query_one(f'#out-{self.cell.id}', Static)
            wrap = self.query_one(f'#outwrap-{self.cell.id}', VerticalScroll)
        except Exception: return          # mid-unmount; the next paint will catch it
        c = self.cell
        if c.is_prompt:
            # a prompt cell's "output" is its answer, kept on the cell rather than in an
            # nbformat output, so it renders from its own fields
            t = Text()
            for x in c.calls:
                # `line` is the activity stream's own rendering ("🔍 Search Approvals").
                # Notebooks written before it fall back to the older {tool, args} shape.
                t.append('  ' + (x.get('line') or f"⚙ {x.get('tool','?')} {str(x.get('args',''))[:90]}") + '\n',
                         style=PAL['gray'])
            if c.reply: t.append(_strip_trail(c.reply).rstrip(), style=PAL['fg'])
            elif c.running: t.append('  thinking…', style=PAL['aqua'])
            out.update(t)
            wrap.display = bool(c.reply or c.calls or c.running)
        else:
            txt = c.text.rstrip()
            out.update(Text(txt, style=PAL['red'] if c.has_error else PAL['fg2']))
            wrap.display = bool(txt)
        self.ta.border_title = self._title()


class NotebookView(VerticalScroll):
    "The centre pane for a notebook: a column of cells, one of which is current."
    BINDINGS = _binds('editor')

    def __init__(self, **kw):
        super().__init__(**kw)
        self.nb: Notebook | None = None
        self.sel = 0
        self.whole_file = False       # this document is a plain file, shown as one editor

    async def load(self, nb, keep=False, whole_file=False, lang=None, title=''):
        """Rebuild the cell column. Both halves are awaited: Textual's unmount and mount are
        deferred, and painting before they land queries widgets that do not exist yet.

        `keep` holds the selection where it was, for a rebuild the user did not ask for --
        the agent adding approval or compaction cells mid-turn should not scroll them back
        to the top of the notebook."""
        sel = self.sel if keep else 0
        self.nb, self.sel, self.whole_file = nb, min(sel, max(0, len(nb) - 1)), whole_file
        self.set_class(whole_file, 'filemode')
        await self.remove_children()
        for i, c in enumerate(nb.cells):
            await self.mount(CellBox(c, i, whole_file=whole_file, lang=lang, title=title, classes='cell'))
        self._paint()

    def _paint(self):
        for b in self.query(CellBox):
            b.set_class(b.i == self.sel, 'sel')
            b.show_outputs()

    def box(self, i=None):
        i = self.sel if i is None else i
        bs = list(self.query(CellBox))
        return bs[i] if 0 <= i < len(bs) else None

    def sync(self):
        "Push editor text back into the document before anything structural happens."
        if self.nb is None: return
        for b in self.query(CellBox):
            if b.i < len(self.nb): self.nb[b.i].source = b.ta.text

    def focus_cell(self, i):
        self.sel = max(0, min(i, len(self.nb or []) - 1))
        self._paint()
        if (b := self.box()) is None: return
        b.ta.focus()
        # Scroll on the *next* refresh rather than now. A structural edit rebuilds this
        # whole column, and until layout has run the new cell has no region to scroll to --
        # so scrolling immediately aims at wherever the old layout put things, and lands
        # somewhere arbitrary. Focus is set straight away, so typing still goes to the
        # right cell either way.
        self.call_after_refresh(self.scroll_to_widget, b)


class ExecBox(TextArea):
    "The merged exec editor; the live/isolated toggle decides where its code runs."
    BINDINGS = _binds('exec')

    def __init__(self, **kw):
        super().__init__('', language='python', theme='vscode_dark', soft_wrap=True,
                         tab_behavior='indent', **kw)

    def on_mount(self): self.border_title = 'exec · live'


class VarTree(Tree):
    "The right pane: the kernel's own inspector, one level at a time."
    BINDINGS = _binds('vars')

    def __init__(self, **kw):
        super().__init__('vars', **kw)
        self.show_root = False
        self.guide_depth = 2
        self.filter = ''
        self.profile, self.sort = 'minimal', 'recent'

    def row(self, v):
        t = Text(no_wrap=True, overflow='ellipsis')
        t.append(v.get('name', ''), style=f"bold {PAL['red'] if v.get('is_error') else PAL['aqua']}")
        typ = v.get('type') or ''
        if v.get('shape'): typ = f"{typ}: {v['shape']}"
        if typ: t.append(f'  {{{typ}}}', style=PAL['gray'])
        if val := (v.get('value') or ''):
            t.append('  '); t.append(val[:80], style=PAL['fg2'])
        if v.get('is_grid'): t.append('  ▦', style=PAL['orange'])
        return t

    def show(self, groups):
        "Rebuild from an /api/rows payload, keeping expansion and the cursor where they were."
        open_ = {tuple(n.data['accessor']) for n in self._iter_nodes() if n.is_expanded and n.data}
        cur = self.cursor_node.data.get('accessor') if (self.cursor_node and self.cursor_node.data) else None
        self.clear()
        for g in groups or []:
            parent = self.root
            if g.get('label'):
                parent = self.root.add(Text(str(g['label']).upper(), style=f"bold {PAL['yellow']}"), data=None)
            for v in g.get('nodes', []):
                if self.filter and self.filter not in (v.get('name', '') or '').lower(): continue
                parent.add(self.row(v), data=v, allow_expand=bool(v.get('is_container')))
        self._replay(open_, cur)

    def _iter_nodes(self, node=None):
        node = node or self.root
        for c in node.children:
            yield c
            yield from self._iter_nodes(c)

    @work(exclusive=True, group='varreplay')
    async def _replay(self, open_, cur):
        for n in list(self._iter_nodes()):
            if n.data and tuple(n.data.get('accessor') or ()) in open_: n.expand()
            if cur and n.data and n.data.get('accessor') == cur: self.move_cursor(n)

    async def on_tree_node_expanded(self, ev):
        if ev.node.data is None or ev.node.children: return
        kids = await self.app.kapi('/api/expand', {'accessor': json.dumps(ev.node.data['accessor'])})
        for v in kids or []:
            ev.node.add(self.row(v), data=v, allow_expand=bool(v.get('is_container')))

    @property
    def sel(self):
        n = self.cursor_node
        return n.data if (n and n.data) else None


class HelpScreen(ModalScreen):
    "Every binding, grouped by the pane it belongs to."
    BINDINGS = [Binding('escape,f1', 'dismiss', 'close')]
    CSS = """
    HelpScreen { align: center middle; background: $background 70%; }
    #helpbox { width: 80%; max-width: 100; height: auto; max-height: 85%;
               background: $panel; border: round $primary; padding: 0 2; }
    """
    def compose(self):
        with VerticalScroll(id='helpbox'):
            yield Label(Text.assemble(
                ('your keys: ', f"bold {PAL['orange']}"), (str(keymap_path()), PAL['fg4']),
                ('   ·  every action below can be rebound there', PAL['gray'])))
            for n in NOTES: yield Label(Text(f'  ⚠ {n}', style=PAL['red']))
            yield Label(Text('  ⌨ ctrl+enter / shift+enter / alt+… need a terminal that speaks the kitty '
                             'keyboard protocol (kitty, ghostty, WezTerm, iTerm2). The f-keys and the '
                             'buttons work everywhere.', style=PAL['gray']))
            for scope, rows in help_rows().items():
                if not rows: continue
                yield Label(Text(scope.upper(), style=f"bold {PAL['yellow']}"))
                for k, lbl in rows:
                    yield Label(Text.assemble(('  '), (f'{k:22}', f"bold {PAL['aqua']}"), (lbl, PAL['fg2'])))


class KernelScreen(ModalScreen):
    """Choose what this tab's kernel is: the launcher, and the interpreter behind it.

    Two lists rather than one, because they are two questions -- which venv's packages the
    notebook can import, and whether execs may run alongside a busy cell. Picking either
    one restarts the kernel, which is why the current state is spelled out above them:
    what is about to be thrown away should be on the screen when the choice is made.

    Dismisses `{'kind':..., 'python':...}`, or None.
    """
    BINDINGS = [Binding('escape', 'cancel', 'cancel')]
    CSS = """
    KernelScreen { align: center middle; background: $background 60%; }
    #kbox { width: 80%; max-width: 100; height: auto; max-height: 85%;
            background: $panel; border: round $primary; padding: 0 1; }
    #kbox OptionList { height: auto; max-height: 10; border: none; background: $surface; margin: 0 0 1 0; }
    """

    def __init__(self, opts):
        super().__init__()
        self.opts = opts

    def compose(self):
        o = self.opts
        with VerticalScroll(id='kbox'):
            yield Label(Text('kernel', style=f"bold {PAL['orange']}"))
            yield Label(Text.assemble(
                (f"  {o['key']}  ", PAL['fg4']),
                ('⏺ running' if o['alive'] else '○ not started',
                 PAL['aqua'] if o['alive'] else PAL['gray']),
                (f"  pid {o['pid']}" if o['pid'] else '', PAL['fg4']),
                ('   · private to this tab' if o['private'] else '   · shared across this folder', PAL['gray'])))
            if o['boot_error']: yield Label(Text(f"  ⚠ {o['boot_error']}", style=PAL['red']))
            yield Label(Text('  choosing either of these restarts the kernel — its variables are lost',
                             style=PAL['gray']))
            yield Label(Text('launcher', style=f"bold {PAL['yellow']}"))
            yield OptionList(*[self._kind_row(k) for k in o['kinds']], id='kinds')
            yield Label(Text('interpreter', style=f"bold {PAL['yellow']}"))
            yield OptionList(*[self._py_row(p) for p in o['pythons']], id='pys')

    def _kind_row(self, k):
        t = Text()
        t.append('● ' if k['current'] else '○ ', style=PAL['aqua'] if k['current'] else PAL['gray'])
        t.append(k['id'], style=PAL['fg'] if k['available'] else PAL['gray'])
        if k['note']: t.append(f"   {k['note']}", style=PAL['red'])
        return t

    def _py_row(self, p):
        t = Text()
        t.append('● ' if p['current'] else '○ ', style=PAL['aqua'] if p['current'] else PAL['gray'])
        t.append(f"{p['label']:24}", style=PAL['fg'])
        t.append(p['path'], style=PAL['fg4'])
        return t

    def on_option_list_option_selected(self, ev):
        if ev.option_list.id == 'kinds':
            k = self.opts['kinds'][ev.option_index]
            if not k['available']: return self.app.status(k['note'], err=True)
            self.dismiss({'kind': k['id']})
        else:
            self.dismiss({'python': self.opts['pythons'][ev.option_index]['path']})

    def action_cancel(self): self.dismiss(None)


class PromptScreen(ModalScreen):
    "One-line prompt; dismisses with the text, or None on escape."
    BINDINGS = [Binding('escape', 'cancel', 'cancel')]
    CSS = """
    PromptScreen { align: center middle; background: $background 60%; }
    #pbox { width: 70%; max-width: 90; height: auto; background: $panel; border: round $primary; padding: 0 1; }
    """
    def __init__(self, title, value=''): super().__init__(); self._t, self._v = title, value
    def compose(self):
        with Vertical(id='pbox'):
            yield Label(Text(self._t, style=f"bold {PAL['orange']}"))
            yield Input(value=self._v, id='pin')
    def on_mount(self): self.query_one('#pin', Input).focus()
    def on_input_submitted(self, ev): self.dismiss(ev.value)
    def action_cancel(self): self.dismiss(None)


class PickerScreen(ModalScreen):
    """Pick one of a list. Dismisses with the chosen item, or None on escape.

    The browser has a modal with arrow keys and a filter box for every list it shows --
    files, hits, commands. This is that, so choosing a completion or a file feels the
    same in both frontends instead of the terminal quietly opening the first match.
    """
    BINDINGS = [Binding('escape', 'cancel', 'cancel')]
    CSS = """
    PickerScreen { align: center middle; background: $background 60%; }
    #pickbox { width: 80%; max-width: 110; height: auto; max-height: 80%;
               background: $panel; border: round $primary; padding: 0 1; }
    #picklist { height: auto; max-height: 22; border: none; background: $surface; }
    """
    def __init__(self, title, items, fmt=str):
        super().__init__()
        self._t, self.items, self.fmt = title, list(items), fmt

    def compose(self):
        with Vertical(id='pickbox'):
            yield Label(Text(self._t, style=f"bold {PAL['orange']}"))
            yield OptionList(*[self.fmt(i) for i in self.items], id='picklist')

    def on_mount(self): self.query_one('#picklist', OptionList).focus()
    def on_option_list_option_selected(self, ev): self.dismiss(self.items[ev.option_index])
    def action_cancel(self): self.dismiss(None)


class PreviewScreen(ModalScreen):
    """Show a block of text -- a diff, a docstring, a suggestion -- and optionally offer it.

    Dismisses True when `accept` is given and enter is pressed, None otherwise, so the
    same screen serves both "read this" and "shall I apply this?".
    """
    BINDINGS = [Binding('escape,q', 'cancel', 'close'), Binding('enter', 'accept', 'accept')]
    CSS = """
    PreviewScreen { align: center middle; background: $background 70%; }
    #prevbox { width: 90%; max-width: 120; height: auto; max-height: 85%;
               background: $panel; border: round $primary; padding: 0 1; }
    """
    def __init__(self, title, body, accept=''):
        super().__init__()
        self._t, self._body, self._accept = title, body, accept

    def compose(self):
        with VerticalScroll(id='prevbox'):
            yield Label(Text(self._t, style=f"bold {PAL['yellow']}"))
            yield Static(self._body if isinstance(self._body, Text) else Text(str(self._body), style=PAL['fg2']))
            yield Label(Text(f'  enter: {self._accept}   ·   escape: leave it' if self._accept
                             else '  escape to close', style=PAL['gray']))

    def action_accept(self): self.dismiss(True if self._accept else None)
    def action_cancel(self): self.dismiss(None)


class ApprovalScreen(ModalScreen):
    """The agent wants to change something. Show what, and take an answer with a reason.

    The reason box is the point. `y` and `n` alone make this a permission dialog; typing
    "no, that file is generated, edit the notebook instead" makes it a turn in the
    conversation, and the harness sends that sentence back to the model. A refusal without
    a reason produces an agent that tries the same edit again with the indentation changed.

    Dismisses `(ok, note)`.
    """
    BINDINGS = [Binding('escape', 'refuse', 'refuse'), Binding('ctrl+y', 'approve', 'approve')]
    CSS = """
    ApprovalScreen { align: center middle; background: $background 70%; }
    #apprbox { width: 90%; max-width: 120; height: auto; max-height: 85%;
               background: $panel; border: round $warning; padding: 0 1; }
    #apprnote { margin: 1 0 0 0; }
    """

    def __init__(self, ask):
        super().__init__()
        self.ask = ask

    def compose(self):
        with VerticalScroll(id='apprbox'):
            yield Label(Text(f'🔐 approval needed — {self.ask.tool}', style=f"bold {PAL['orange']}"))
            yield Label(Text(self.ask.summary, style=PAL['fg']))
            if self.ask.preview: yield Static(Text(self.ask.preview, style=PAL['fg2']))
            yield Input(placeholder='reason (optional, and it goes back to the model)', id='apprnote')
            yield Label(Text('  ctrl+y: approve   ·   enter: refuse with this reason   ·   escape: refuse',
                             style=PAL['gray']))

    def on_mount(self): self.query_one('#apprnote', Input).focus()
    def _note(self): return self.query_one('#apprnote', Input).value.strip()
    def action_approve(self): self.dismiss((True, self._note()))
    def action_refuse(self): self.dismiss((False, self._note()))
    def on_input_submitted(self, e): self.dismiss((False, self._note()))


# ---------------------------------------------------------------------------
# app
# ---------------------------------------------------------------------------
class IdeApp(App):
    "leela in the terminal: notebooks, files, and live variables from the notebook's own kernel."
    TITLE = 'leela'          # without this Textual titles the terminal window 'IdeApp'
    BINDINGS = _binds('global')
    COMMANDS = App.COMMANDS | {ActionCommands}

    CSS = """
    Screen { background: $background; }
    #body { height: 1fr; }
    #left { width: 32; border-right: solid $panel; }
    #right { width: 52; border-left: solid $panel; }
    #left.hidden, #right.hidden { display: none; }
    #centre { width: 1fr; }
    #filetree { height: 1fr; padding: 0 1; }
    KeyToast { height: 10; border-top: round $panel; padding: 0 1; }
    KeyToast Label { height: 1; }
    #nbview { height: 1fr; padding: 0 1; }
    .cell { height: auto; padding: 0 0 1 0; border-left: solid $background; }
    .cell.sel { border-left: solid $accent; }
    .cellta { height: auto; max-height: 20; border: round $panel; background: $surface;
              border-title-color: $accent; border-title-align: left; }
    .cellta:focus { border: round $accent; }
    /* A file is not a cell. In file mode the one box takes the pane and the editor
       scrolls inside it, instead of showing the first twenty lines and nothing else. */
    #nbview.filemode { padding: 0 1 0 1; }
    .cell.filecell { height: 1fr; padding: 0; }
    .filecell .cellta { height: 1fr; max-height: 100%; }
    .cellout { height: auto; max-height: 16; padding: 0 1; color: $foreground; scrollbar-size: 1 1; }

    /* Toolbars: one row of buttons per pane, one row high. A row is what a terminal has
       to spare, so the buttons are borderless and the bar clips rather than scrolls --
       a horizontal scrollbar would take the row the buttons are in. What falls off the
       end of a narrow terminal is still in the command palette, which lists every
       action there is. */
    .actionbar { height: 1; width: 100%; overflow: hidden; background: $panel; }
    .leebtn { height: 1; min-width: 0; width: auto; border: none; padding: 0 1; margin: 0;
              background: $boost; color: $foreground; text-style: none; }
    .leebtn:hover { background: $accent 40%; }
    .leebtn.go { color: $success; text-style: bold; }
    .leebtn.warn { color: $warning; }
    #execwrap { height: 13; border-top: round $panel; }
    #execlog { height: 1fr; padding: 0 1; }
    ExecBox { height: 6; border: round $panel; background: $surface;
              border-title-color: $accent; border-title-align: left; }
    ExecBox:focus { border: round $accent; }
    #agentwrap { height: 8; border-top: round $panel; }
    #agentlog { height: 1fr; padding: 0 1; }
    #agentprompt { border: none; background: $surface; }
    #vartop { height: 1; padding: 0 1; }
    #varfilter { height: 1; border: none; background: $surface; }
    #vartree { height: 1fr; padding: 0 1; }
    #tabs { height: 1; }
    /* Not docked. `Footer` docks bottom itself, and a second bottom-docked widget
       lands in exactly the same row -- which hid every status message behind the
       footer. Left in the normal vertical flow it sits just above it, where the
       search notes, the lazygit message and the assistant's state are readable. */
    #status { height: 1; background: $panel; color: $foreground; padding: 0 1; }
    Footer { background: $panel; }
    """

    def __init__(self, ws: Workspace, **kw):
        super().__init__(**kw)
        self.ws = ws
        self.docs: dict[str, Notebook] = {}
        self.scope_mode = 'live'          # live | isolated
        self.hist, self.hidx = [], 0
        self._exec_lines = []
        self.last_edits = {}              # {path: (before, after)} from the assistant's last turn
        self._rebuilding = 0              # >0 while the tab bar is being rebuilt; see `_sync_tabs`
        self._asking = ''                 # the question a turn in flight is answering
        self._reply = ''                  # the answer so far, while it streams in
        self._unlisten = None             # unregisters this frontend from the approval queue

    # -- layout ------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Tabs(id='tabs')
        yield ActionBar('toolbar', id='toolbar')
        with Horizontal(id='body'):
            with Vertical(id='left'):
                yield ActionBar('files', id='filesbar')
                yield FileTree(self.ws, id='filetree')
                yield ActionBar('keys', id='keysbar')
                yield KeyToast()
            with Vertical(id='centre'):
                yield NotebookView(id='nbview')
                with Vertical(id='execwrap'):
                    yield Static('', id='execlog')
                    yield ExecBox(id='execbox')
                    yield ActionBar('exec', id='execbar')
                with Vertical(id='agentwrap'):
                    yield Static(Text('(no agent activity yet)', style=PAL['gray']), id='agentlog')
                    yield Input(placeholder=f'ask leela to do something…  ({chord_display("agent_send")})',
                                id='agentprompt')
                    yield ActionBar('agent', id='agentbar')
            with Vertical(id='right'):
                yield Static('', id='vartop')
                yield Input(placeholder='filter…', id='varfilter')
                yield VarTree(id='vartree')
                yield ActionBar('vars', id='varsbar')
        yield Static('', id='status')
        yield Footer()

    async def on_mount(self):
        self.theme = 'textual-dark'
        await self._sync_tabs()
        self._paint_scope()
        if self.ws.tab: await self._load_tab()
        self.set_interval(2.5, self.refresh_vars)
        self._watch_approvals()
        self.query_one('#filetree', FileTree).focus()
        # A keymap that half-loaded is worth one line on the status bar: the alternative is
        # a user pressing a key they wrote down themselves and getting nothing.
        self.status(f'{NOTES[0]} · f1 for the rest' if NOTES else 'ready', err=bool(NOTES))

    def on_unmount(self):
        if (stop := getattr(self, '_unlisten', None)): stop()

    # -- helpers -----------------------------------------------------------
    def status(self, msg, err=False):
        self.query_one('#status', Static).update(
            Text(f' {msg}', style=PAL['red'] if err else PAL['fg4']))

    async def kapi(self, path, params=None):
        "One call to whichever inspector the panel is watching: the tab's kernel, or a chosen env."
        k = self.ws.inspector()
        return await k.api(path, params) if k else None

    async def _explain(self, k, err):
        """A kernel error with a `did you mean` appended, when a near-miss name exists.

        Guarded on the message: the suggestion costs a call to the inspector, and only a
        `NameError` can use one.
        """
        if not (err and 'is not defined' in err): return err
        return did_you_mean(err, await k.names(self.scope_mode)) if k else err

    def _edit_ctx(self):
        """`(widget, text, cursor_offset)` for whichever editor holds the cursor.

        Completion, the model's suggestion and the docstring lookup all ask the kernel
        the same pair of questions -- what code, and where in it -- so "the cursor" is
        resolved once here rather than three times.
        """
        box = self.query_one('#execbox', ExecBox)
        ta = box if box.has_focus else (b.ta if (b := self._view().box()) else None)
        if ta is None: return None, '', 0
        return ta, ta.text, len(ta.get_text_range((0, 0), ta.cursor_location))

    def _buffer_text(self):
        "What the editor holds for the active tab, in the shape `Workspace.disk_text` returns."
        t, nb = self.ws.tab, self.doc
        if t is None or nb is None: return None
        self._view().sync()
        return nb.source_text() if t.kind == 'notebook' else nb[0].source

    async def kernel(self):
        self.status('starting kernel…')
        k = await self.ws.kernel()
        self.status(f'kernel {Path(self.ws.kernel_key()).name}' + (f' · {k.boot_error}' if k.boot_error else ''))
        return k

    async def _sync_tabs(self):
        """Rebuild the tab bar only when its labels actually change.

        `Tabs.clear()` is awaitable, and adding before the removal lands raises on
        duplicate ids -- so await it, and skip the whole dance when nothing moved
        (which is the common case, since a keystroke marking a tab dirty gets here).

        The rebuild also *selects*, and that is the subtle part: a `Tabs` with nothing
        active selects the first tab it is given, which posts an activation for tab 0 that
        `on_tabs_tab_activated` faithfully acts on -- so opening a second file put you
        straight back on the first one. Hence `want_i`, read before the first `await` and
        restored after the last, and `_rebuilding`, which tells the handler that an
        activation arriving mid-rebuild is the widget talking to itself rather than the
        user choosing a tab.
        """
        tabs = self.query_one('#tabs', Tabs)
        want = [('● ' if t.dirty else '') + t.title for t in self.ws.tabs]
        want_i = self.ws.active
        self._rebuilding += 1
        try:
            if want != [str(t.label) for t in tabs.query(Tab)]:
                await tabs.clear()
                for i, lbl in enumerate(want): await tabs.add_tab(Tab(lbl, id=f't{i}'))
            if self.ws.tabs:
                self.ws.activate(want_i)
                try: tabs.active = f't{want_i}'
                except Exception: pass
        finally:
            self._rebuilding -= 1

    def _tabs_soon(self):
        "Fire-and-forget tab refresh, for the sync call sites."
        self.run_worker(self._sync_tabs(), exclusive=True, group='tabs')

    @property
    def doc(self):
        t = self.ws.tab
        return None if t is None else self.docs.get(t.path or t.title)

    async def open_path(self, path):
        try: self.ws.open(path); self.ws.save()
        except Exception as e: return self.status(str(e), err=True)
        await self._sync_tabs()
        await self._load_tab()

    async def _load_tab(self):
        t = self.ws.tab
        view = self.query_one('#nbview', NotebookView)
        if t is None: return
        key = t.path or t.title
        if t.kind == 'notebook':
            if key not in self.docs:
                try: self.docs[key] = Notebook.load(t.path) if t.path else Notebook.blank()
                except Exception as e: return self.status(errstr(e), err=True)
            await view.load(self.docs[key])
        else:
            # a plain file is shown as a single cell, so one editor path serves both --
            # in file mode, though, that cell is the whole pane rather than twenty rows
            try: text = self.ws.fs.read(t.path) if t.path else ''
            except Exception as e: return self.status(errstr(e), err=True)
            if key not in self.docs:
                self.docs[key] = Notebook([Cell(source=text, cell_type='code')], t.path)
            await view.load(self.docs[key], whole_file=True, lang=t.lang, title=t.title)
        await self.kernel()
        await self.refresh_vars()

    # -- variables ---------------------------------------------------------
    async def refresh_vars(self):
        # This runs on a 2.5s interval, so it can fire against a screen that is being torn
        # down or is behind a modal. `query_one` raises `NoMatches` there, which Textual
        # surfaces as an uncaught error in whatever test or session happens to be running.
        try: tree = self.query_one('#vartree', VarTree)
        except Exception: return
        base = '/agent/api/rows' if self.scope_mode == 'isolated' else '/api/rows'
        d = await self.kapi(base, {'profile': tree.profile, 'sort': tree.sort})
        if d is None:
            try: self.query_one('#vartop', Static).update(Text(' no kernel inspector', style=PAL['gray']))
            except Exception: pass
            return
        tree.show(d.get('groups'))
        self._paint_scope()

    def _paint_scope(self):
        live = self.scope_mode == 'live'
        t = self.query_one('#vartop', Static)
        tree = self.query_one('#vartree', VarTree)
        # The env is named only when it is *not* the tab's kernel: a panel that is watching
        # a running app rather than the notebook must never be mistaken for the notebook.
        env = next((e['name'] for e in self.ws.envs() if e['current']), '') if self.ws.env_base else ''
        t.update(Text.assemble(
            (' live ', f"bold {'black on ' + PAL['aqua'] if live else PAL['gray']}"),
            ('  '),
            (' isolated ', f"bold {'black on ' + PAL['orange'] if not live else PAL['gray']}"),
            (f'  ▶ {env}' if env else '', f"bold {PAL['green']}"),
            (f"   {tree.profile} · {tree.sort}", PAL['fg4'])))
        try: self.query_one('#execbox', ExecBox).border_title = f'exec · {self.scope_mode}'
        except Exception: pass

    # -- global actions ----------------------------------------------------
    def action_focus_files(self): self.query_one('#filetree').focus()
    def action_focus_editor(self):
        v = self.query_one('#nbview', NotebookView)
        v.focus_cell(v.sel)
    def action_focus_exec(self): self.query_one('#execbox', ExecBox).focus()
    def action_focus_vars(self): self.query_one('#vartree').focus()
    def action_focus_agent(self): self.query_one('#agentprompt').focus()
    def action_toggle_left(self): self.query_one('#left').toggle_class('hidden')
    def action_toggle_right(self): self.query_one('#right').toggle_class('hidden')
    def action_help(self): self.push_screen(HelpScreen())
    def action_quit(self): self.exit()

    def action_toggle_scope(self):
        self.scope_mode = 'isolated' if self.scope_mode == 'live' else 'live'
        self._paint_scope()
        self.run_worker(self.refresh_vars())

    @work
    async def action_save(self):
        t = self.ws.tab
        nb = self.doc
        if t is None or nb is None: return self.status('nothing to save')
        self.query_one('#nbview', NotebookView).sync()
        # A scratch tab has nowhere to go yet, so ask -- otherwise `new notebook` makes
        # something that cannot be kept, which is a worse offer than not making it.
        if not t.path:
            root = self.ws.fs.roots[0] if self.ws.fs.roots else None
            if root is None: return self.status('open a folder first', err=True)
            name = await self.push_screen_wait(
                PromptScreen(f'save in {root.name}/ as', f'{t.title}.ipynb' if t.kind == 'notebook' else t.title))
            if not name: return
            was = t.title
            t.path, t.title, t.scratch = str(root/name), Path(name).name, False
            self.docs[t.path] = self.docs.pop(was, nb)
        try:
            if t.kind == 'notebook': nb.save(t.path, sandbox=self.ws.fs)
            else: self.ws.fs.write(t.path, nb[0].source)
            t.dirty = False
            await self._sync_tabs()
            self.query_one('#filetree', FileTree).reload_roots()
            self.ws.save()
            self.status(f'saved {Path(t.path).name}')
        except Exception as e: self.status(errstr(e), err=True)

    action_save_all = action_save

    async def action_close_tab(self):
        self.ws.close(); self.ws.save(); await self._sync_tabs(); await self._load_tab()
    async def action_next_tab(self): self.ws.cycle(1); await self._sync_tabs(); await self._load_tab()
    async def action_prev_tab(self): self.ws.cycle(-1); await self._sync_tabs(); await self._load_tab()

    async def action_interrupt(self):
        if (k := self.ws.kernel_peek()): await k.interrupt(); self.status('interrupted')

    @work
    async def action_restart(self):
        if (k := self.ws.kernel_peek()):
            self.status('restarting kernel…')
            await k.restart()
            self.status('kernel restarted')
            await self.refresh_vars()

    @work
    async def action_pick_kernel(self):
        "Choose the launcher and the interpreter, from a list, with the mouse."
        pick = await self.push_screen_wait(KernelScreen(self.ws.kernel_options()))
        if not pick: return
        self.status('starting the new kernel…')
        try: o = await self.ws.set_kernel(kind=pick.get('kind'),
                                          python=pick.get('python', False))
        except Exception as e: return self.status(errstr(e), err=True)
        self.status(f"kernel: {o['running_kind']} · {Path(o['python'] or 'leela’s own python').name}")
        await self.refresh_vars()

    def action_palette(self): self.action_command_palette()
    def action_quick_open(self): self._quick_open()
    def action_code_search(self): self._code_search()

    @work
    async def _quick_open(self):
        "Fuzzy-find a file, then pick from the ranked list -- `wapp` finds `web/app.py`."
        name = await self.push_screen_wait(PromptScreen('open file', ''))
        if not name: return
        hits = fuzzy_rank(name, self.ws.fs.walk(), key=str, limit=200)
        if not hits: return self.status(f'no file matching {name!r}', err=True)
        root = self.ws.fs.roots[0] if self.ws.fs.roots else None
        rel = lambda p: str(p.relative_to(root)) if (root and p.is_relative_to(root)) else str(p)
        p = await self.push_screen_wait(PickerScreen(f'{len(hits)} files', hits, fmt=rel))
        if p is not None: await self.open_path(p)

    @work
    async def _code_search(self):
        q = await self.push_screen_wait(PromptScreen('search code'))
        if not q: return
        hits = self.ws.search.search(q)
        note = f'{self.ws.search.backend}' + (f' — {self.ws.search.note}' if self.ws.search.note else '')
        if not hits: return self.status(f'no matches ({note})')
        self.status(f'{len(hits)} matches ({note}) · opened the first')
        t = Text()
        for h in hits[:20]:
            t.append(f"{Path(h.path).name}:{h.line}  ", style=PAL['aqua'])
            t.append(h.text[:90] + '\n', style=PAL['fg2'])
        self.query_one('#agentlog', Static).update(t)
        await self.open_path(hits[0].path)

    # -- running files -----------------------------------------------------
    async def _run_code(self, code, label=None):
        """Run one block in the tab's kernel and log it in the exec strip.

        The exec log is the right place for it whether the code came from the exec box, a
        selection, or a whole file: it is the running account of everything that was asked
        of this kernel outside the notebook, and a file that printed something belongs in
        that account.
        """
        k = await self.kernel()
        if self.scope_mode == 'isolated':
            r = await k.api('/agent/api/exec', {'code': code, 'scope': 'isolated'})
            ok = bool(r and r.get('ok'))
            txt = await self._explain(k, (r or {}).get('error')) or (r or {}).get('stdout') or 'ok'
        else:
            res = await k.execute(code)
            ok, txt = res.ok, (await self._explain(k, res.error) or res.text or 'ok')
        self._exec_lines.append((label or code, txt.strip(), not ok))
        self._exec_lines = self._exec_lines[-40:]
        self._paint_exec()
        await self.refresh_vars()
        return ok, txt

    @work
    async def action_run_file(self):
        """Run the open .py as a script, in the tab's own kernel.

        The buffer is what runs, not the file on disk -- editing and then running should
        run what is on the screen. Everything it defines stays in the namespace afterwards,
        which is the difference between this and a subprocess: the variable panel has the
        script's own state in it when it finishes.
        """
        t = self.ws.tab
        src = self._buffer_text() if (t is not None and t.kind != 'notebook') else None
        code, label = self.ws.run_file_code(src=src)
        if code is None: return self.status(label, err=True)
        self.status(f'running {label}…')
        ok, _ = await self._run_code(code, f'▶ {label}')
        self.status(f'{label} finished' if ok else f'{label} raised — see the exec log', err=not ok)

    @work
    async def action_run_selection(self):
        "Run just what is selected, in whichever editor holds the cursor."
        w, _, _ = self._edit_ctx()
        sel = (getattr(w, 'selected_text', '') or '').strip() if w is not None else ''
        if not sel: return self.status('select some code first', err=True)
        ok, _ = await self._run_code(sel)
        self.status('ran the selection' if ok else 'the selection raised — see the exec log', err=not ok)

    @work
    async def action_run_all(self):
        "Every code cell, top to bottom, stopping at the first error -- or the whole file, if it is one."
        v = self._view()
        if v.nb is None: return
        if v.whole_file: return self.action_run_file()
        v.sync()
        k = await self.kernel()
        self.status('running every cell…')
        for i, c in enumerate(v.nb.cells):
            if c.cell_type != 'code' or not c.source.strip(): continue
            self.status(f'running cell {i}…')
            await v.nb.run(i, k)
            if (b := v.box(i)): b.show_outputs()
            if c.has_error:
                self.status(f'cell {i} raised — stopped there', err=True)
                break
        else:
            self.status('ran every cell')
        if self.ws.tab: self.ws.tab.dirty = True
        await self._sync_tabs()
        await self.refresh_vars()

    async def action_new_notebook(self):
        "An unsaved notebook to type in. `ctrl+s` asks where it should live."
        self.ws.new_scratch('notebook')
        await self._sync_tabs()
        await self._load_tab()
        self.status('new notebook — ctrl+s asks where to save it')

    @work
    async def action_edit_keys(self):
        """Show the user's keymap file, writing the template first if it does not exist.

        Not opened as a tab: it lives in leela's config directory, and the file sandbox is
        confined to the folders the user opened -- which is the correct answer, and means
        the path plus the format is what this can usefully offer.
        """
        p = keymap_path()
        made = False
        if not p.exists():
            try:
                write_keymap(p); made = True
            except Exception as e: return self.status(errstr(e), err=True)
        t = Text()
        t.append(f'{p}\n\n', style=f"bold {PAL['aqua']}")
        t.append('written with every action and its current chord — edit it and restart leela.\n'
                 if made else 'edit it and restart leela.\n', style=PAL['fg2'])
        t.append('an action maps to one chord or several, separated by spaces; "" unbinds it.\n\n',
                 style=PAL['fg2'])
        t.append('  "run_cell": "ctrl+enter f5 ctrl+y"\n', style=PAL['green'])
        for n in NOTES: t.append(f'\n⚠ {n}', style=PAL['red'])
        self.push_screen(PreviewScreen('your keybindings', t))
        self.status(f'keymap: {p}')

    # -- dev servers -------------------------------------------------------
    @work
    async def action_run_app(self):
        """Start a run configuration -- or the open file -- under a live inspector.

        The inspector goes inside the process the command runs in, which is what lets the
        variable panel watch a request handler mutate state while the app serves. Something
        started in a terminal instead has no inspector in it and cannot be watched; the
        picker says so, because that is the question everyone asks about this feature.
        """
        rs = list(self.ws.runs.runs)
        t = self.ws.tab
        here = self.ws.runs.for_file(t.path) if (t is not None and (t.path or '').endswith('.py')) else None
        opts = rs + ([here] if here and not any(r.name == here.name for r in rs) else [])
        if not opts:
            return self.status(f'no run configurations — write {RUNS_FILE} or open a .py', err=True)
        pick = opts[0] if len(opts) == 1 else await self.push_screen_wait(
            PickerScreen('run', opts, fmt=lambda r: f'{r.name:16} {r.cmd}'))
        if pick is None: return
        self.status(f'starting {pick.name}…')
        try: srv = await self.ws.run(pick.name if self.ws.runs.get(pick.name) else pick.cmd)
        except Exception as e: return self.status(errstr(e), err=True)
        self.query_one('#agentlog', Static).update(Text('\n'.join(srv.tail(14)), style=PAL['fg2']))
        self.status(f"{srv.label}: app {srv.app_url or '?'} · inspector {srv.base or 'pending'}"
                    + (' · ctrl+alt+e to watch it' if srv.base else ''))

    @work
    async def action_edit_runs(self):
        "Show (and create) the project's run configurations file."
        p = self.ws.runs.path
        if p is None: return self.status('open a folder first', err=True)
        made = False
        if not p.exists():
            t = self.ws.tab
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(self.ws.runs.template(t.path if t else None), indent=2) + '\n')
                made = True
            except Exception as e: return self.status(errstr(e), err=True)
        self.ws.runs.load()
        txt = Text()
        txt.append(f'{p}\n\n', style=f"bold {PAL['aqua']}")
        txt.append('written with a starting entry — edit it and run with ctrl+alt+d.\n' if made
                   else 'edit it and run with ctrl+alt+d.\n', style=PAL['fg2'])
        txt.append('each entry is a command line; leela runs it in a process with an inspector\n'
                   'in it, so its module namespace shows up in the variable panel.\n\n', style=PAL['fg2'])
        txt.append('  {"name": "api", "cmd": "uvicorn app:app --port 8000", "watch": "app"}\n\n',
                   style=PAL['green'])
        txt.append('something you start yourself can join in too, in one line:\n', style=PAL['fg2'])
        txt.append('  import leela.inspect as li; li.serve(name="api")\n', style=PAL['green'])
        for r in self.ws.runs.runs: txt.append(f'\n  {r.name:16} {r.cmd}', style=PAL['fg4'])
        if self.ws.runs.note: txt.append(f'\n⚠ {self.ws.runs.note}', style=PAL['red'])
        self.push_screen(PreviewScreen('run configurations', txt))
        self.status(f'runs: {p}')

    # -- git, terminal, research -------------------------------------------
    @work
    async def action_git(self):
        """Hand the real terminal to lazygit, then take it back.

        This is where the TUI has it easier than the browser: `App.suspend()` restores
        the terminal to the state it was in before Textual started, so lazygit gets a
        genuine tty with no pty to emulate and no websocket in between. The web
        frontend has to build all of that; here it is a context manager.

        The tree is reloaded afterwards because a rebase or a checkout will have moved
        files underneath us.
        """
        root = self.ws.fs.roots[0] if self.ws.fs.roots else None
        try: argv = lazygit_argv(root)
        except LazygitMissing as e: return self.status(str(e), err=True)
        with self.suspend():
            try: subprocess.run(argv, cwd=str(root) if root else None)
            except Exception as e: return self.status(errstr(e), err=True)
        self.query_one('#filetree', FileTree).reload_roots()
        self.status('back from lazygit')

    @work
    async def action_terminal(self):
        "A shell on the real terminal, the same way `action_git` runs lazygit."
        root = self.ws.fs.roots[0] if self.ws.fs.roots else None
        from ..term import default_shell
        with self.suspend():
            print('leela: type `exit` to return to the IDE', flush=True)
            try: subprocess.run([default_shell()], cwd=str(root) if root else None)
            except Exception as e: return self.status(errstr(e), err=True)
        self.query_one('#filetree', FileTree).reload_roots()
        self.status('back from the shell')

    def _show_docs(self, docs, title, note=''):
        "Render web results into the bottom pane, the same shape code hits use."
        t = Text()
        t.append(f'{title}  —  {note}\n', style=f"bold {PAL['yellow']}")
        for d in docs[:20]:
            t.append(f'{d.title[:70]}\n', style=PAL['aqua'])
            t.append(f'  {d.url}\n', style=PAL['fg4'])
        self.query_one('#agentlog', Static).update(t)

    @work
    async def action_web_search(self):
        "Search the web without leaving the editor."
        q = await self.push_screen_wait(PromptScreen('search the web'))
        if not q: return
        self.status('searching…')
        docs = await asyncio.to_thread(self.ws.research.search, q)
        if not docs: return self.status(self.ws.research.note, err=True)
        self._show_docs(docs, f'web: {q}', self.ws.research.note)
        self.status(self.ws.research.note)

    @work
    async def action_read_url(self):
        "Fetch one page as markdown into the bottom pane."
        url = await self.push_screen_wait(PromptScreen('read a url'))
        if not url: return
        self.status(f'fetching {url}…')
        doc = await asyncio.to_thread(self.ws.research.read, url)
        if doc is None: return self.status(self.ws.research.note, err=True)
        t = Text()
        t.append(f'{doc.title}\n', style=f"bold {PAL['yellow']}")
        t.append(doc.text[:4000], style=PAL['fg2'])
        self.query_one('#agentlog', Static).update(t)
        self.status(self.ws.research.note)

    @work
    async def action_research(self):
        "Search, read the top results, and drop the cited digest into the bottom pane."
        q = await self.push_screen_wait(PromptScreen('research a question'))
        if not q: return
        self.status('reading the top results… this takes a moment')
        docs, digest = await asyncio.to_thread(self.ws.research.dig, q)
        if not digest: return self.status(self.ws.research.note, err=True)
        t = Text()
        t.append(f'{q}  —  {self.ws.research.note}\n', style=f"bold {PAL['yellow']}")
        t.append(digest[:8000], style=PAL['fg2'])
        self.query_one('#agentlog', Static).update(t)
        self.status(self.ws.research.note)

    @work
    async def action_switch_env(self):
        """Point the variable panel at another live env -- an app leela started, or another kernel.

        Every process that registered an inspector is on this list, whoever started it: a
        notebook kernel, an app run from a configuration, or something you launched
        yourself that called `leela.inspect.serve()`. What is *not* on it is a process with
        no inspector in it, because there is nothing there to read.
        """
        envs = self.ws.envs()
        rows = [{'name': 'the tab’s own kernel', 'base': None, 'kind': 'kernel', 'pid': None,
                 'current': not self.ws.env_base}] + envs
        def fmt(e):
            mark = '● ' if e['current'] else '○ '
            tail = f" · pid {e['pid']}" if e.get('pid') else ''
            return f"{mark}{e['name']:24} {e['kind']:7}{tail}"
        pick = await self.push_screen_wait(PickerScreen(
            f'{len(envs)} live env(s) — anything running leela.inspect.serve()', rows, fmt=fmt))
        if pick is None: return
        self.ws.watch_env(pick['base'])
        self._paint_scope()
        await self.refresh_vars()
        self.status(f"watching {pick['name']}" if pick['base'] else 'back on the tab’s kernel')

    # tab_1..tab_9
    def _mk_tab_action(i):
        async def f(self):
            self.ws.activate(i); await self._sync_tabs(); await self._load_tab()
        return f
    for _i in range(1, 10): locals()[f'action_tab_{_i}'] = _mk_tab_action(_i - 1)
    del _mk_tab_action, _i

    # -- editor actions ----------------------------------------------------
    def _view(self): return self.query_one('#nbview', NotebookView)

    async def _run_cell(self, advance=False, insert=False):
        v = self._view()
        if v.nb is None: return
        v.sync()
        # A file has no cells to run, advance through or insert after: "run" there means
        # run the file, with the argv and the `__main__` a script expects.
        if v.whole_file:
            if self.ws.tab and (self.ws.tab.path or '').endswith('.py'): return self.action_run_file()
            return self.status(f'{self.ws.tab.title if self.ws.tab else "this"} is not python — nothing to run')
        i = v.sel
        c = v.nb[i]
        if c.cell_type == 'markdown':
            if (b := v.box(i)): b.show_outputs()
        elif c.is_prompt:
            # The answer goes in the cell, not the pane below -- that is what makes it part
            # of the document. Off the UI thread, like every other model call here.
            self.status('thinking…')
            self._hook_activity()
            c.running = True
            # Streamed straight into the cell: `ask_cell_stream` appends each chunk to
            # `cell.reply` on the way past, so repainting the cell *is* the live view. The
            # advantage of having put the answer in the document in the first place.
            box = v.box(i)
            def paint():
                # Refreshed here rather than only inside the stream, because the tool loop
                # runs *before* the first token: without this the cell shows nothing at all
                # for however long the model spends looking around, which is exactly the
                # stretch the feed exists to fill.
                a = self.ws.ai
                v.nb[i].calls = a.activity.rows(mark=a.activity._mark)
                if box is not None: box.show_outputs()
            # A tool call that returns nothing to the stream still has to show up, so the
            # activity hook repaints the cell for the length of this turn.
            prev, self.ws.ai.activity.on_change = self.ws.ai.activity.on_change, \
                lambda _act: self.call_from_thread(paint)
            try: await asyncio.to_thread(self._pump_cell, self.ws.ask_cell_stream(v.nb, i), paint)
            except Exception as e: return self.status(errstr(e), err=True)
            finally:
                c.running = False
                self.ws.ai.activity.on_change = prev
            self.last_edits = self.ws.ai.changes()
            await v.load(v.nb, keep=True)   # approval/compaction cells landed while it worked
            if (b := v.box(i)): b.show_outputs()
            if self.ws.tab: self.ws.tab.dirty = True
            await self._sync_tabs()
            edited = ', '.join(Path(p).name for p in self.last_edits) if self.last_edits else ''
            if edited and not self.ws.ai.problems:
                self.status(f'answered · edited {edited} (ctrl+alt+l for the diff)')
            else: self._say_note(self.ws.ai)
        else:
            self.status(f'running cell {i}…')
            k = await self.kernel()
            await v.nb.run(i, k)
            if (b := v.box(i)): b.show_outputs()
            if self.ws.tab: self.ws.tab.dirty = True
            await self._sync_tabs()
            self.status(f'cell {i} done' + (' · error' if c.has_error else ''))
            await self.refresh_vars()
        if insert or (advance and i + 1 >= len(v.nb)):
            v.nb.insert(i + 1); await v.load(v.nb); v.focus_cell(i + 1)
        elif advance:
            v.focus_cell(i + 1)

    async def action_run_cell(self): await self._run_cell()
    async def action_run_advance(self): await self._run_cell(advance=True)
    async def action_run_insert(self): await self._run_cell(insert=True)

    async def _struct(self, fn):
        """Apply a structural edit, then put the cursor back where it belongs.

        `NotebookView.load` rebuilds the whole column and selects the first cell, which is
        right when opening a notebook and wrong after an edit: it means pressing a cell
        key twice acts on two different cells, and the view jumps to the top every time
        you insert one. `fn(v)` returns the index to land on.
        """
        v = self._view()
        if v.nb is None: return
        # A file is one document, not a column of cells: inserting or deleting one here
        # would silently split the buffer the editor is showing.
        if v.whole_file: return self.status('cells belong to notebooks — this tab is a file')
        v.sync()
        i = fn(v)
        await v.load(v.nb)
        v.focus_cell(i)
        if self.ws.tab: self.ws.tab.dirty = True
        self._tabs_soon()

    async def action_cell_above(self): await self._struct(lambda v: _then(v.nb.insert(v.sel), v.sel))
    async def action_cell_below(self): await self._struct(lambda v: _then(v.nb.insert(v.sel + 1), v.sel + 1))
    async def action_cell_delete(self): await self._struct(lambda v: _then(v.nb.delete(v.sel), max(0, v.sel - 1)))
    async def action_cell_split(self):
        v = self._view()
        b = v.box()
        off = len(b.ta.get_text_range((0, 0), b.ta.cursor_location)) if b else 0
        await self._struct(lambda v: _then(v.nb.split(v.sel, off), v.sel + 1))
    async def action_cell_type(self):
        await self._struct(lambda v: _then(v.nb.cycle_type(v.sel), v.sel))

    def action_comment(self):
        b = self._view().box()
        if b is None: return
        lines = b.ta.text.split('\n')
        allc = all(not l.strip() or l.lstrip().startswith('#') for l in lines)
        b.ta.text = '\n'.join(
            (l.replace('# ', '', 1).replace('#', '', 1) if allc and l.strip() else
             (('# ' + l) if l.strip() and not allc else l)) for l in lines)

    # -- completion, docs, diffs -------------------------------------------
    # Two completions, answering two different questions. `complete` asks the kernel what
    # names exist: instant, and right by construction because it is the real namespace.
    # `ai_complete` asks the model what should come next, which costs a forward pass -- so
    # it is never fired by typing, and what comes back is proposed rather than inserted.
    @work
    async def action_complete(self):
        "Completions from the tab's own kernel, so venv modules complete like they do in a shell."
        w, code, pos = self._edit_ctx()
        if w is None: return self.status('put the cursor in some code first', err=True)
        k = await self.kernel()
        r = await k.complete(code, pos)
        ms = r.get('matches') or []
        if not ms: return self.status('no completions there')
        pick = await self.push_screen_wait(PickerScreen(f'{len(ms)} completions', ms))
        if pick is None: return
        # A match replaces everything from `from` to the cursor, so only the part the user
        # has not typed yet gets inserted -- which needs no cursor arithmetic at all.
        head = code[r.get('from', pos):pos]
        w.insert(pick[len(head):] if pick.startswith(head) else pick)
        w.focus()

    @work
    async def action_ai_complete(self):
        "What the local model thinks belongs at the cursor. Proposed first; enter inserts it."
        w, code, pos = self._edit_ctx()
        if w is None: return self.status('put the cursor in some code first', err=True)
        self.status('asking the model…')
        c = self.ws.completer
        text = await asyncio.to_thread(c.complete, code, pos)
        self.status(c.note, err=not text)
        if not text: return
        if await self.push_screen_wait(PreviewScreen('suggestion', Text(text, style=PAL['green']),
                                                     accept='insert it')):
            w.insert(text)
            w.focus()

    @work
    async def action_show_docs(self):
        "Signature and docstring for the name at the cursor, from the object the kernel actually holds."
        w, code, pos = self._edit_ctx()
        if w is None: return self.status('put the cursor on a name first', err=True)
        k = await self.kernel()
        txt = await k.inspect_obj(code, pos)
        if not txt: return self.status('the kernel knows nothing about that name')
        self.push_screen(PreviewScreen('docs', Text(txt, style=PAL['fg2'])))

    def action_capture(self):
        """Photograph the IDE's own screen for the assistant.

        Not quite the web IDE's capability, and worth saying so: a browser can grab any
        window on the desktop, while Textual can only render itself. What it *can* do it
        does better -- the screen goes to the model as text, which is exact and cheap,
        where the browser has to send a picture. The SVG is written out beside it, into
        leela's own config directory rather than the project being edited, because a
        screenshot of a TUI is still worth keeping.
        """
        try: svg, text = screen_capture(self)
        except Exception as e:                       # a Textual version moved the compositor
            return self.status(f'could not capture the screen ({errstr(e)})', err=True)
        self.ws.put_screen(text=text, note='the terminal IDE’s own screen')
        try: p = self.ws.save_screen(svg)
        except Exception as e:
            return self.status(f'captured for the assistant; svg not saved ({errstr(e)})')
        self.status(f'screen captured — rides along with your next question · {p}')

    def action_show_diff(self):
        "The open buffer against the file on disk. The dirty dot says *that* it changed; this says what."
        t = self.ws.tab
        if t is None: return self.status('nothing open')
        disk = self.ws.disk_text(t)
        if disk is None: return self.status(f'{t.title} has never been saved', err=True)
        rows = diff_rows(udiff(disk, self._buffer_text() or ''))
        if not rows: return self.status('no unsaved changes')
        self.push_screen(PreviewScreen(f'unsaved changes — {t.title}', diff_text(rows)))

    def _cursor_loc(self):
        "The active tab's path and the cursor's line -- the anchor for a similarity query."
        t = self.ws.tab
        if t is None or not t.path: return None, 1
        b = self._view().box()
        return t.path, (b.ta.cursor_location[0] + 1 if b else 1)

    def _show_hits(self, hits, title):
        "Render hits into the bottom pane and jump to the first one."
        t = Text()
        t.append(f'{title}\n', style=f"bold {PAL['yellow']}")
        for h in hits[:25]:
            t.append(f"{h.symbol or Path(h.path).stem}", style=PAL['aqua'])
            t.append(f"  {Path(h.path).name}:{h.line}", style=PAL['fg4'])
            t.append(f"  {h.text[:70]}\n", style=PAL['fg2'])
        self.query_one('#agentlog', Static).update(t)

    @work
    async def action_find_similar(self):
        """Code like the function under the cursor, via usearch clustering over kosha's
        index (falling back to nearest neighbours when the index is too small to cluster)."""
        path, line = self._cursor_loc()
        if path is None: return self.status('open a file first', err=True)
        self.status('finding similar code…')
        hits = self.ws.search.peers(path, line)
        note = f'{self.ws.search.backend} · {self.ws.search.note}'
        if not hits: return self.status(f'nothing similar ({note})')
        self._show_hits(hits, f'code like {Path(path).name}:{line}  —  {note}')
        self.status(f'{len(hits)} similar ({note})')

    @work
    async def action_code_map(self):
        "An ANN clustering of the whole indexed corpus: the codebase grouped by shape."
        self.status('clustering the codebase…')
        cs = self.ws.search.clusters()
        if not cs: return self.status(self.ws.search.note or 'no clusters', err=True)
        t = Text()
        t.append(f'code map — {len(cs)} clusters ({self.ws.search.note})\n', style=f"bold {PAL['yellow']}")
        for c in cs[:20]:
            t.append(f'{c.label:28}', style=PAL['aqua'])
            t.append(f'{c.size:5d} chunks  {len(c.files)} files\n', style=PAL['fg4'])
        self.query_one('#agentlog', Static).update(t)
        self.status(f'{len(cs)} clusters')

    # -- exec actions ------------------------------------------------------
    async def action_exec_run(self):
        box = self.query_one('#execbox', ExecBox)
        code = box.text.strip()
        if not code: return
        await self._run_code(code)
        self.hist.append(code); self.hidx = len(self.hist)
        box.text = ''

    def _paint_exec(self):
        t = Text()
        for code, out, err in self._exec_lines:
            t.append(code, style=PAL['fg']); t.append('  →  ', style=PAL['gray'])
            t.append(out[:400] + ('\n' if not out.endswith('\n') else ''),
                     style=PAL['red'] if err else PAL['aqua'])
        self.query_one('#execlog', Static).update(t)

    def action_exec_newline(self):
        self.query_one('#execbox', ExecBox).insert('\n')
    def action_exec_clear(self):
        self._exec_lines = []; self._paint_exec()
    def action_exec_prev(self): self._recall(-1)
    def action_exec_next(self): self._recall(1)
    def _recall(self, d):
        if not self.hist: return
        self.hidx = max(0, min(len(self.hist), self.hidx + d))
        b = self.query_one('#execbox', ExecBox)
        b.text = '' if self.hidx >= len(self.hist) else self.hist[self.hidx]
    async def action_exec_promote(self):
        self.scope_mode = 'live'; self._paint_scope(); await self.action_exec_run()

    # -- file actions ------------------------------------------------------
    @work
    async def action_new_file(self): await self._new('file')
    @work
    async def action_new_dir(self): await self._new('dir')

    async def _new(self, kind):
        tree = self.query_one('#filetree', FileTree)
        e = tree.sel
        parent = Path(e.path) if (e and e.is_dir) else (Path(e.path).parent if e else self.ws.fs.roots[0])
        name = await self.push_screen_wait(PromptScreen(f'new {kind} in {parent.name}/'))
        if not name: return
        try:
            ent = self.ws.fs.mkdir(parent/name) if kind == 'dir' else self.ws.fs.touch(parent/name)
            tree.reload_roots()
            self.status(f'created {name}')
            if kind == 'file': await self.open_path(ent.path)
        except Exception as ex: self.status(errstr(ex), err=True)

    @work
    async def action_rename(self):
        tree = self.query_one('#filetree', FileTree)
        if (e := tree.sel) is None: return self.status('select a file first')
        name = await self.push_screen_wait(PromptScreen('rename to', Path(e.path).name))
        if not name: return
        try: self.ws.fs.rename(e.path, name); tree.reload_roots(); self.status('renamed')
        except Exception as ex: self.status(errstr(ex), err=True)

    @work
    async def action_delete(self):
        tree = self.query_one('#filetree', FileTree)
        if (e := tree.sel) is None: return self.status('select a file first')
        ok = await self.push_screen_wait(PromptScreen(f'delete {Path(e.path).name}?  type yes'))
        if (ok or '').strip().lower() != 'yes': return
        try: self.ws.fs.delete(e.path); tree.reload_roots(); self.status('deleted')
        except Exception as ex: self.status(errstr(ex), err=True)

    @work
    async def action_add_root(self):
        p = await self.push_screen_wait(PromptScreen('folder to open'))
        if not p: return
        try:
            self.ws.add_root(p); self.ws.save()
            self.query_one('#filetree', FileTree).reload_roots()
            self.status(f'opened {p}')
        except Exception as ex: self.status(errstr(ex), err=True)

    def action_refresh_files(self): self.query_one('#filetree', FileTree).reload_roots()
    def action_open(self): pass          # Tree's own selection handles it
    def action_up_dir(self): pass
    def action_filter_files(self): self.status('use ctrl+p to find a file by name')

    # -- variable actions --------------------------------------------------
    def action_filter_vars(self): self.query_one('#varfilter').focus()
    def action_expand(self):
        if (n := self.query_one('#vartree', VarTree).cursor_node): n.toggle()

    @work
    async def action_edit_value(self):
        tree = self.query_one('#vartree', VarTree)
        if (v := tree.sel) is None: return self.status('select a variable first')
        expr = await self.push_screen_wait(PromptScreen(f"set {v['name']} =", v.get('value', '')))
        if expr is None: return
        r = await self.kapi('/api/set', {'accessor': json.dumps(v['accessor']), 'expr': expr})
        if r and r.get('ok'): self.status(f"set {v['name']}"); await self.refresh_vars()
        else: self.status((r or {}).get('error', 'set failed'), err=True)

    @work
    async def action_promote(self):
        tree = self.query_one('#vartree', VarTree)
        if (v := tree.sel) is None: return self.status('select a variable first')
        r = await self.kapi('/api/promote', {'accessor': json.dumps(v['accessor'])})
        if r and r.get('ok'): self.status(f"promoted {v['name']}"); await self.refresh_vars()
        else: self.status((r or {}).get('error', 'promote failed'), err=True)

    def action_copy_value(self):
        if (v := self.query_one('#vartree', VarTree).sel):
            self.copy_to_clipboard(str(v.get('value', ''))); self.status('copied value')
    def action_copy_path(self):
        if (v := self.query_one('#vartree', VarTree).sel):
            self.copy_to_clipboard(str(v.get('path') or v.get('name'))); self.status('copied path')
    def action_grid(self): self.status('grid view arrives with the dev-server panel')

    def _set_profile(self, p):
        self.query_one('#vartree', VarTree).profile = p
        self.run_worker(self.refresh_vars())
    def action_profile_minimal(self): self._set_profile('minimal')
    def action_profile_standard(self): self._set_profile('standard')
    def action_profile_full(self): self._set_profile('full')
    def action_sort(self):
        t = self.query_one('#vartree', VarTree)
        t.sort = SORTS[(SORTS.index(t.sort) + 1) % len(SORTS)]
        self.run_worker(self.refresh_vars())

    # -- agent -------------------------------------------------------------
    @work
    async def action_agent_send(self):
        """One turn with the assistant, off the UI thread.

        Its tools edit files directly, so what comes back with the reply is a diff per
        changed file, taken from disk on either side of each write rather than from what
        the tools reported: a tool result is a claim, and the file is the fact.
        """
        i = self.query_one('#agentprompt', Input)
        q = i.value.strip()
        if not q: return
        i.value = ''
        log = self.query_one('#agentlog', Static)
        self._asking = q
        self._hook_activity()
        log.update(Text.assemble((f'▸ {q}\n', PAL['fg']), ('thinking…', PAL['gray'])))
        self.status('thinking…')
        ai = self.ws.ai
        self._reply = ''
        # Streamed, not blocked on: a cloud turn with a tool loop in it is far too long to
        # sit in front of with nothing moving.
        await asyncio.to_thread(self._pump, self.ws.ask_stream(q))
        text = self._reply
        self._asking = ''
        self.last_edits = ai.changes()
        t = Text()
        t.append(f'▸ {q}\n', style=PAL['fg'])
        for line in ai.turn_lines(): t.append(f'  {line}\n', style=PAL['gray'])
        for p, (was, now) in self.last_edits.items():
            t.append(f'  ✎ {Path(p).name}  {diff_label(was, now)}   (ctrl+alt+l for the diff)\n',
                     style=PAL['orange'])
        t.append(text, style=PAL['fg2'])
        for p in ai.problems: t.append(f'\n⚠ {p}', style=PAL['red'])
        log.update(t)
        self._say_note(ai)
        await self._after_edits()

    def _say_note(self, ai):
        """The status line after a turn: what went wrong if anything did, else the note.

        A turn can finish looking fine while the engine refused the compaction it needed,
        or answered a cheap job with nothing. Those failures cannot raise -- their callers
        have nowhere to put an exception -- so the status line is where they surface.
        """
        if ai.problems: return self.status(ai.problems[-1] + '  (ctrl+alt+l for the rest)', err=True)
        self.status(ai.note, err=not ai.ready)

    async def _after_edits(self):
        """Reload the open tab when the assistant moved the file underneath it.

        Silently only when there is nothing to lose. Typing while the model thinks is
        normal, and unsaved edits are not the model's to overwrite just because it reached
        the same file -- so that case is offered, with the diff, and the choice is the user's.
        """
        t = self.ws.tab
        if t is None or t.path not in self.last_edits: return
        take = True
        if t.dirty:
            was, now = self.last_edits[t.path]
            take = await self.push_screen_wait(PreviewScreen(
                f'{Path(t.path).name} changed on disk — you have unsaved edits',
                diff_text(diff_rows(udiff(was, now))), accept='reload from disk, discarding yours'))
        if not take: return self.status('kept your buffer — ctrl+s overwrites')
        self.docs.pop(t.path, None)
        await self._load_tab()
        self.status(f'{Path(t.path).name} reloaded from disk')

    def action_agent_stop(self):
        try:
            if self.ws.ai.cancel(): return self.status('asked the model to stop')
        except Exception as e: return self.status(errstr(e), err=True)
        self.status('assistant is not running')

    # -- approval ----------------------------------------------------------
    def _watch_approvals(self):
        """Register this frontend as somewhere an approval can be asked.

        `Approvals` refuses immediately when nothing is listening, which is the right
        answer for a headless run and the wrong one here. Registered through `listen`
        rather than by assigning `on_ask`, so the notebook recorder that is already hooked
        there keeps getting both halves of every exchange.
        """
        self._unlisten = self.ws.approvals.listen(on_ask=self._ask_approval)

    def _ask_approval(self, ask):
        "Called on the model's worker thread; hop to the UI thread to put the modal up."
        try: self.call_from_thread(self._show_approval, ask)
        except Exception: pass

    @work
    async def _show_approval(self, ask):
        got = await self.push_screen_wait(ApprovalScreen(ask))
        ok, note = got if got else (False, '')
        self.ws.answer_approval(ask.id, ok, note)
        self.status(('approved' if ok else 'refused') + f' {ask.tool}' + (f' — {note}' if note else ''))

    def _pump(self, chunks):
        """Drain a markdown-chunk iterator on a worker thread, repainting as it arrives.

        The paint is coalesced rather than fired per chunk: a model emits tokens far faster
        than a terminal can usefully redraw, and `call_from_thread` blocks until the UI
        thread is done, so painting every chunk would throttle the model to the refresh
        rate. Twenty a second looks continuous and costs nothing.
        """
        from time import monotonic
        last = 0.0
        for c in chunks:
            self._reply += c
            if (now := monotonic()) - last > 0.05:
                last = now
                try: self.call_from_thread(self._paint_stream)
                except Exception: pass
        try: self.call_from_thread(self._paint_stream)
        except Exception: pass
        return self._reply

    def _pump_cell(self, chunks, paint):
        "Drain a prompt cell's stream, repainting the cell itself. Coalesced like `_pump`."
        from time import monotonic
        last = 0.0
        for _ in chunks:
            if (now := monotonic()) - last > 0.05:
                last = now
                try: self.call_from_thread(paint)
                except Exception: pass
        try: self.call_from_thread(paint)
        except Exception: pass

    def _paint_stream(self):
        """The agent pane mid-turn: the question, the tool calls so far, and the answer as it lands.

        The activity list collapses once the answer starts arriving. This pane is seven
        rows; a full tool trail would push the answer straight off the bottom, and while
        the model is writing, the answer is the thing being watched. The whole trail stays
        one key away in `ctrl+alt+l`.
        """
        try: log = self.query_one('#agentlog', Static)
        except Exception: return
        lines = self.ws.ai.turn_lines()
        t = Text()
        if self._asking: t.append(f'▸ {self._asking}\n', style=PAL['fg'])
        if self._reply and len(lines) > 2:
            t.append(f'  … {len(lines)-2} earlier steps\n', style=PAL['fg4'])
            lines = lines[-2:]
        for line in lines[-8:]: t.append(f'  {line}\n', style=PAL['gray'])
        if self._reply: t.append(self._reply, style=PAL['fg2'])
        elif self.ws.ai.busy: t.append('  thinking…', style=PAL['aqua'])
        log.update(t)

    def _hook_activity(self):
        """Point the agent's activity stream at this app, on the first turn that needs it.

        Not at mount: touching `ws.ai` builds the agent, and the whole point of building it
        lazily is that opening the IDE must not wait on anything a model needs.
        """
        self.ws.ai.activity.on_change = self._on_activity

    def _on_activity(self, act):
        "Repaint the agent pane as each tool call starts and finishes, from whichever thread fired it."
        try: self.call_from_thread(self._paint_activity)
        except Exception: pass

    def _paint_activity(self):
        "A tool call started or finished. Same painter as the token stream, so they cannot fight."
        self._paint_stream()

    def action_agent_tools(self):
        """What the assistant actually did: every tool call, and the diff of every file that moved.

        In a modal rather than the bottom pane, because a diff is not readable in seven
        rows -- and the diff is the part of "what it did" worth reading.
        """
        ai = self.ws.ai
        s = ai.status()
        t = Text()
        t.append(f"{s['model_note']}  ·  {s['ntools']} tools  ·  {s['nskills']} skills"
                 + (' · thinking now' if s['busy'] else '') + '\n', style=f"bold {PAL['yellow']}")
        # `note` usually restates the line above once a turn has run, so it only earns a
        # row when it is saying something else -- a failure, or why the model is missing.
        if s['note'] and not s['note'].startswith(s['model_note']): t.append(f"{s['note']}\n", style=PAL['fg4'])
        t.append(f"context {100*s['pct_full']:.0f}% full"
                 + (f" · {s['compactions']} compaction(s)" if s['compactions'] else '')
                 + (f"  ·  {s['usage']}" if s['use']['total'] else '') + '\n', style=PAL['gray'])
        # What failed quietly. These are the ones with nowhere else to go: a cheap job
        # returns '' to a caller that cannot raise, and a native engine complains on a file
        # descriptor rather than in an exception.
        for p in s.get('problems') or []: t.append(f'⚠ {p}\n', style=PAL['red'])
        t.append('\n')
        for a in ai.activity.acts[-25:]:
            t.append(f'{a.line()}\n', style=PAL['aqua'] if a.ok else PAL['red'])
        for p, (was, now) in self.last_edits.items():
            t.append(f'\n{p}  {diff_label(was, now)}\n', style=f"bold {PAL['orange']}")
            t.append(diff_text(diff_rows(udiff(was, now))))
        if not (ai.activity.acts or self.last_edits): t.append('(nothing yet)', style=PAL['gray'])
        self.push_screen(PreviewScreen('what the assistant did', t))

    @work
    async def action_agent_transcript(self):
        d = await self.kapi('/agent/api/transcript')
        cells = (d or {}).get('cells') or []
        t = Text()
        for c in cells[-20:]:
            t.append(' '.join(c['source'].split())[:110] + '\n',
                     style=PAL['purple'] if c['cell_type'] == 'markdown' else PAL['fg2'])
        self.query_one('#agentlog', Static).update(t or Text('(no transcript yet)', style=PAL['gray']))

    # -- events ------------------------------------------------------------
    async def on_tabs_tab_activated(self, ev):
        """A tab was selected. Rebuilds of the bar send one of these too, and lie about which.

        `_sync_tabs` clears the bar and adds the tabs back, and `Tabs.add_tab` activates the
        first one it is given -- so opening a *second* file posts an activation for tab 0
        after the assignment that selected tab 1, and the file you just opened flips back to
        the one you were on. `Tabs.active` is set synchronously by that assignment, so it is
        the honest record of what was actually chosen: anything that disagrees with it is a
        message from the rebuild rather than from the user.
        """
        if ev.tab is None or self._rebuilding: return
        tabs = self.query_one('#tabs', Tabs)
        if str(tabs.active) != str(ev.tab.id): return
        i = int(str(ev.tab.id)[1:])
        if i != self.ws.active:
            self.ws.activate(i)
            await self._load_tab()

    async def on_input_changed(self, ev):
        if ev.input.id == 'varfilter':
            self.query_one('#vartree', VarTree).filter = (ev.value or '').strip().lower()
            await self.refresh_vars()

    def on_text_area_changed(self, ev):
        if self.ws.tab and not self.ws.tab.dirty:
            self.ws.tab.dirty = True
            self._tabs_soon()

    def on_descendant_focus(self, ev):
        "Track which cell has the cursor, so run/split act on what the user is looking at."
        w = ev.widget
        if isinstance(w, TextArea) and (box := w.parent) is not None and isinstance(box, CellBox):
            v = self._view()
            v.sel = box.i
            v._paint()


def run(roots=(), agent='restricted', kernel_port=8400, kernel='ipykernel',
        model=None, approvals='ask', agent_scope='overlay', python=None):
    "Launch the terminal IDE over `roots`, or the saved workspace when none are given."
    import os
    kw = dict(port=kernel_port, agent=agent, kernel=kernel, model=model, approvals=approvals,
              agent_scope=agent_scope, python=python)
    ws = Workspace.load(**kw) if not roots else Workspace(**kw)
    for r in roots: ws.add_root(r)
    if not ws.fs.roots: ws.add_root(os.getcwd())
    app = IdeApp(ws)
    try: app.run()
    finally: asyncio.run(ws.shutdown())
