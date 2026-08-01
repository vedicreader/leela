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

Cells are `TextArea`s with `language='python'`, which is tree-sitter
highlighting via textual[syntax] -- the same grammar family the file editor uses
for every other language.
"""

from __future__ import annotations
import asyncio, json, subprocess
from fastcore.all import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Input, Label, OptionList, Static, Tree, TextArea, Tabs, Tab
from rich.text import Text

from ..inspect.core import GHDK, SORTS
from .. import errstr
from ..diffs import diff_label, diff_rows, did_you_mean, fuzzy_rank, udiff
from ..keys import tui_bindings, toast_rows, help_rows
from ..term import lazygit_argv, LazygitMissing
from ..nb import Notebook, Cell
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
            yield Label(Text.assemble((f'{k:14}', f"bold {PAL['aqua']}"), (lbl, PAL['fg4'])))


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


def _then(_, i):
    "Run an edit for its effect and return the cell index to land on -- see `IdeApp._struct`."
    return i


def _cell_title(c):
    "A cell's own mark, so the three kinds are told apart without reading any of them."
    if c.cell_type == 'code': return f"[{c.execution_count or ' '}]"
    return '✦ ask' if c.is_prompt else 'md'


class CellBox(Vertical):
    "One notebook cell: a highlighted editor plus its output (or, for a prompt cell, its answer)."
    def __init__(self, cell: Cell, i: int, **kw):
        super().__init__(**kw)
        self.cell, self.i = cell, i

    def compose(self):
        ta = TextArea(self.cell.source, language=_ta_lang('python' if self.cell.cell_type == 'code' else 'markdown'),
                      theme='vscode_dark', soft_wrap=True, tab_behavior='indent',
                      id=f'ta-{self.cell.id}', classes='cellta')
        ta.border_title = _cell_title(self.cell)
        yield ta
        yield Static('', id=f'out-{self.cell.id}', classes='cellout')

    @property
    def ta(self): return self.query_one(f'#ta-{self.cell.id}', TextArea)

    def show_outputs(self):
        try: out = self.query_one(f'#out-{self.cell.id}', Static)
        except Exception: return          # mid-unmount; the next paint will catch it
        c = self.cell
        if c.is_prompt:
            # a prompt cell's "output" is its answer, kept on the cell rather than in an
            # nbformat output, so it renders from its own fields
            t = Text()
            for x in c.calls: t.append(f"⚙ {x.get('tool','?')} {str(x.get('args',''))[:90]}\n", style=PAL['gray'])
            if c.reply: t.append(c.reply.rstrip(), style=PAL['fg'])
            out.update(t)
            out.display = bool(c.reply or c.calls)
        else:
            txt = c.text.rstrip()
            out.update(Text(txt, style=PAL['red'] if c.has_error else PAL['fg2']))
            out.display = bool(txt)
        self.ta.border_title = _cell_title(c)


class NotebookView(VerticalScroll):
    "The centre pane for a notebook: a column of cells, one of which is current."
    BINDINGS = _binds('editor')

    def __init__(self, **kw):
        super().__init__(**kw)
        self.nb: Notebook | None = None
        self.sel = 0

    async def load(self, nb):
        "Rebuild the cell column. Both halves are awaited: Textual's unmount and mount are\n        deferred, and painting before they land queries widgets that do not exist yet."
        self.nb, self.sel = nb, 0
        await self.remove_children()
        for i, c in enumerate(nb.cells): await self.mount(CellBox(c, i, classes='cell'))
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
            for scope, rows in help_rows().items():
                if not rows: continue
                yield Label(Text(scope.upper(), style=f"bold {PAL['yellow']}"))
                for k, lbl in rows:
                    yield Label(Text.assemble(('  '), (f'{k:18}', f"bold {PAL['aqua']}"), (lbl, PAL['fg2'])))


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


# ---------------------------------------------------------------------------
# app
# ---------------------------------------------------------------------------
class IdeApp(App):
    "leela in the terminal: notebooks, files, and live variables from the notebook's own kernel."
    TITLE = 'leela'          # without this Textual titles the terminal window 'IdeApp'
    BINDINGS = _binds('global')

    CSS = """
    Screen { background: $background; }
    #body { height: 1fr; }
    #left { width: 30; border-right: solid $panel; }
    #right { width: 52; border-left: solid $panel; }
    #left.hidden, #right.hidden { display: none; }
    #centre { width: 1fr; }
    #filetree { height: 1fr; padding: 0 1; }
    KeyToast { height: 12; border-top: round $panel; padding: 0 1; }
    KeyToast Label { height: 1; }
    #nbview { height: 1fr; padding: 0 1; }
    .cell { height: auto; padding: 0 0 1 0; border-left: solid $background; }
    .cell.sel { border-left: solid $accent; }
    .cellta { height: auto; max-height: 20; border: round $panel; background: $surface;
              border-title-color: $accent; border-title-align: left; }
    .cellta:focus { border: round $accent; }
    .cellout { height: auto; max-height: 16; padding: 0 1; color: $foreground; }
    #execwrap { height: 12; border-top: round $panel; }
    #execlog { height: 1fr; padding: 0 1; }
    ExecBox { height: 6; border: round $panel; background: $surface;
              border-title-color: $accent; border-title-align: left; }
    ExecBox:focus { border: round $accent; }
    #agentwrap { height: 7; border-top: round $panel; }
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

    # -- layout ------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Tabs(id='tabs')
        with Horizontal(id='body'):
            with Vertical(id='left'):
                yield FileTree(self.ws, id='filetree')
                yield KeyToast()
            with Vertical(id='centre'):
                yield NotebookView(id='nbview')
                with Vertical(id='execwrap'):
                    yield Static('', id='execlog')
                    yield ExecBox(id='execbox')
                with Vertical(id='agentwrap'):
                    yield Static(Text('(no agent activity yet)', style=PAL['gray']), id='agentlog')
                    yield Input(placeholder='ask leela to do something…  (ctrl+enter)', id='agentprompt')
            with Vertical(id='right'):
                yield Static('', id='vartop')
                yield Input(placeholder='filter…', id='varfilter')
                yield VarTree(id='vartree')
        yield Static('', id='status')
        yield Footer()

    async def on_mount(self):
        self.theme = 'textual-dark'
        await self._sync_tabs()
        self._paint_scope()
        if self.ws.tab: await self._load_tab()
        self.set_interval(2.5, self.refresh_vars)
        self.query_one('#filetree', FileTree).focus()
        self.status('ready')

    # -- helpers -----------------------------------------------------------
    def status(self, msg, err=False):
        self.query_one('#status', Static).update(
            Text(f' {msg}', style=PAL['red'] if err else PAL['fg4']))

    async def kapi(self, path, params=None):
        "One call to the active kernel's inspector."
        k = self.ws.kernel_peek()
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
        """
        tabs = self.query_one('#tabs', Tabs)
        want = [('● ' if t.dirty else '') + t.title for t in self.ws.tabs]
        if want != [str(t.label) for t in tabs.query(Tab)]:
            await tabs.clear()
            for i, lbl in enumerate(want): tabs.add_tab(Tab(lbl, id=f't{i}'))
        if self.ws.tabs:
            try: tabs.active = f't{self.ws.active}'
            except Exception: pass

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
        else:
            # a plain file is shown as a single cell, so one editor path serves both
            try: text = self.ws.fs.read(t.path)
            except Exception as e: return self.status(errstr(e), err=True)
            if key not in self.docs:
                self.docs[key] = Notebook([Cell(source=text, cell_type='code')], t.path)
        await view.load(self.docs[key])
        await self.kernel()
        await self.refresh_vars()

    # -- variables ---------------------------------------------------------
    async def refresh_vars(self):
        tree = self.query_one('#vartree', VarTree)
        base = '/agent/api/rows' if self.scope_mode == 'isolated' else '/api/rows'
        d = await self.kapi(base, {'profile': tree.profile, 'sort': tree.sort})
        if d is None:
            self.query_one('#vartop', Static).update(Text(' no kernel inspector', style=PAL['gray']))
            return
        tree.show(d.get('groups'))
        self._paint_scope()

    def _paint_scope(self):
        live = self.scope_mode == 'live'
        t = self.query_one('#vartop', Static)
        tree = self.query_one('#vartree', VarTree)
        t.update(Text.assemble(
            (' live ', f"bold {'black on ' + PAL['aqua'] if live else PAL['gray']}"),
            ('  '),
            (' isolated ', f"bold {'black on ' + PAL['orange'] if not live else PAL['gray']}"),
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

    async def action_save(self):
        t = self.ws.tab
        nb = self.doc
        if t is None or nb is None: return self.status('nothing to save')
        self.query_one('#nbview', NotebookView).sync()
        try:
            if t.kind == 'notebook': nb.save(t.path, sandbox=self.ws.fs)
            else: self.ws.fs.write(t.path, nb[0].source)
            t.dirty = False; await self._sync_tabs()
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

    # -- dev servers -------------------------------------------------------
    @work
    async def action_run_app(self):
        """Run the open .py under a live inspector. Its module globals register as another
        env, so the variable panel can watch a request handler mutate state as it serves."""
        t = self.ws.tab
        if t is None or not t.path.endswith('.py'): return self.status('open a .py app first', err=True)
        self.status('starting dev server…')
        try: srv = await self.ws.dev.start(t.path)
        except Exception as e: return self.status(errstr(e), err=True)
        self.query_one('#agentlog', Static).update(
            Text('\n'.join(srv.tail(12)), style=PAL['fg2']))
        self.status(f"{srv.label}: app {srv.app_url or '?'} · inspector {srv.base or 'pending'}")

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

    def action_switch_env(self):
        """Point the variable panel at another live env -- a dev server, or another kernel."""
        from ..inspect.server import active
        envs = active()
        self.status('live envs: ' + ', '.join(f"{e['name']}:{e['port']}" for e in envs) if envs else 'no live envs')

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
        i = v.sel
        c = v.nb[i]
        if c.cell_type == 'markdown':
            if (b := v.box(i)): b.show_outputs()
        elif c.is_prompt:
            # The answer goes in the cell, not the pane below -- that is what makes it part
            # of the document. Off the UI thread, like every other model call here.
            self.status('thinking…')
            try: await asyncio.to_thread(self.ws.ask_cell, v.nb, i)
            except Exception as e: return self.status(errstr(e), err=True)
            self.last_edits = self.ws.ai.changes()
            if (b := v.box(i)): b.show_outputs()
            if self.ws.tab: self.ws.tab.dirty = True
            await self._sync_tabs()
            edited = ', '.join(Path(p).name for p in self.last_edits) if self.last_edits else ''
            self.status(f'answered · edited {edited} (ctrl+alt+l for the diff)' if edited
                        else self.ws.ai.note, err=not self.ws.ai.ready)
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
        k = await self.kernel()
        if self.scope_mode == 'isolated':
            r = await k.api('/agent/api/exec', {'code': code, 'scope': 'isolated'})
            ok = bool(r and r.get('ok'))
            txt = await self._explain(k, (r or {}).get('error')) or (r or {}).get('stdout') or 'ok'
        else:
            res = await k.execute(code)
            ok, txt = res.ok, (await self._explain(k, res.error) or res.text or 'ok')
        self._exec_lines.append((code, txt.strip(), not ok))
        self._exec_lines = self._exec_lines[-40:]
        self._paint_exec()
        self.hist.append(code); self.hidx = len(self.hist)
        box.text = ''
        await self.refresh_vars()

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
        log.update(Text.assemble((f'▸ {q}\n', PAL['fg']), ('thinking…', PAL['gray'])))
        self.status('thinking…')
        ai = self.ws.ai
        before = len(ai.calls)
        text = await asyncio.to_thread(self.ws.ask, q)   # attaches any pending screen capture
        self.last_edits = ai.changes()
        t = Text()
        t.append(f'▸ {q}\n', style=PAL['fg'])
        for name, args in ai.calls[before:]:
            t.append(f'  ⚙ {name} {str(args)[:120]}\n', style=PAL['gray'])
        for p, (was, now) in self.last_edits.items():
            t.append(f'  ✎ {Path(p).name}  {diff_label(was, now)}   (ctrl+alt+l for the diff)\n',
                     style=PAL['orange'])
        t.append(text, style=PAL['fg2'])
        log.update(t)
        self.status(ai.note, err=not ai.ready)
        await self._after_edits()

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
        if (c := getattr(self.ws.ai, 'chat', None)) is not None:
            try: c.cancel(); return self.status('asked the model to stop')
            except Exception as e: return self.status(errstr(e), err=True)
        self.status('assistant is not running')

    def action_agent_tools(self):
        """What the assistant actually did: every tool call, and the diff of every file that moved.

        In a modal rather than the bottom pane, because a diff is not readable in seven
        rows -- and the diff is the part of "what it did" worth reading.
        """
        ai = self.ws.ai
        t = Text()
        t.append(f'{ai.note} · {len(ai.tools)} tools' + (' · thinking now' if ai.busy else '') + '\n',
                 style=f"bold {PAL['yellow']}")
        for name, args in ai.calls[-25:]:
            t.append(f'{name}', style=PAL['aqua'])
            t.append(f'  {str(args)[:110]}\n', style=PAL['fg4'])
        for p, (was, now) in self.last_edits.items():
            t.append(f'\n{p}  {diff_label(was, now)}\n', style=f"bold {PAL['orange']}")
            t.append(diff_text(diff_rows(udiff(was, now))))
        if not (ai.calls or self.last_edits): t.append('(nothing yet)', style=PAL['gray'])
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
        if ev.tab is None: return
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


def run(roots=(), agent='restricted', kernel_port=8400):
    "Launch the terminal IDE over `roots`, or the saved workspace when none are given."
    import os
    ws = Workspace.load(port=kernel_port, agent=agent) if not roots else Workspace(port=kernel_port, agent=agent)
    for r in roots: ws.add_root(r)
    if not ws.fs.roots: ws.add_root(os.getcwd())
    app = IdeApp(ws)
    try: app.run()
    finally: asyncio.run(ws.shutdown())
