"""Open folders, open tabs, and which kernel each tab talks to.

The kernel binding is the interesting decision here. Tabs bind **per root**, not
per tab: every notebook and every file under one open folder shares a single
kernel, so the exec strip, the scratch box and two open notebooks all see the
same variables. That is what makes "run this cell, then poke at the result in
the exec box" work at all, and it is why `Tab.kernel_key` defaults to the
enclosing root rather than the tab's own path. A tab can opt out and take a
private kernel when it should not share state.

State persists to the leela config dir, so reopening the IDE restores the
folders and tabs but never the kernels -- a dead kernel's variables are gone,
and pretending otherwise would be a lie about what is live.
"""

from __future__ import annotations
import time
from dataclasses import dataclass
from fastcore.all import Path, L, ifnone

from . import Dictable, leela_cfg
from .ai import Assistant, Completer, notebook_approvals
from .devserver import DevServers
from .fs import Sandbox, Unsafe, lang_for, is_texty
from .kernels import KernelPool
from .nb import Notebook
from .research import Research
from .search import Search
from .term import Terminals

__all__ = ['Tab', 'Workspace', 'ws_path']


def ws_path(): return leela_cfg/'workspace.json'


@dataclass
class Tab(Dictable):
    'One open editor tab.'
    path: str                       # absolute path; '' for an unsaved buffer
    kind: str = 'text'              # 'notebook' | 'text'
    title: str = ''
    dirty: bool = False
    private_kernel: bool = False    # take a kernel of my own instead of the root's
    scratch: bool = False           # never written to disk

    def __post_init__(self):
        if not self.title: self.title = Path(self.path).name or 'untitled'
        if self.path.endswith('.ipynb'): self.kind = 'notebook'

    @property
    def lang(self): return 'python' if self.kind == 'notebook' else lang_for(self.path)


class Workspace:
    "The IDE's session: open folders, open tabs, and the kernels behind them."

    def __init__(self, roots=(), port=8000, agent='restricted', dev_port=9000, kernel='ipykernel',
                 model=None,              # the agent's turn model; None takes the routing default
                 approvals='ask'):        # 'ask' | 'auto' (approve every write) | 'off' (refuse them)
        self.fs = Sandbox(roots)
        self.pool = KernelPool(port=port, default_kernel=kernel)
        self.dev = DevServers(port=dev_port)
        self.search = Search(self.fs)
        self.research = Research(self.fs)
        self.terms = Terminals(cwd=self.fs.roots[0] if self.fs.roots else None)
        self.agent = agent
        # `kernel_kind`, not `kernel`: `kernel()` below is the coroutine that hands out the
        # live kernel for a tab, and an attribute of the same name shadows it — every
        # `await ws.kernel()` in both frontends then awaits the string 'ipykernel'.
        self.kernel_kind = kernel
        self.tabs = L()
        self.active = 0
        self._untitled = 0
        self._ai = self._completer = None
        self.model = model                # the turn model; None takes the routing default
        self.screen = (None, '', '')      # a capture waiting to ride along with the next question
        self.on_note = None               # a frontend's status line, when one has registered
        # Where an approval raised mid-turn writes itself. Set by `ask_cell` for the length
        # of one prompt cell and cleared afterwards, so an approval for a question typed in
        # the prompt bar does not land in whichever notebook happens to be open.
        self._approval_target = None
        self.approvals = notebook_approvals(lambda: self._approval_target, mode=approvals)

    @property
    def ai(self):
        "The assistant, built on first ask. Held here so both frontends share one conversation."
        if self._ai is None:
            self._ai = Assistant(self, model_id=self.model, on_compact=self._compacted)
            self.approvals.host = self._ai.host
        return self._ai

    def _compacted(self, summary):
        """Write a compaction summary into the notebook the conversation is happening in.

        Everywhere else compaction is invisible until you notice the agent has forgotten
        something. Here it is a cell: readable, editable, and saved with the work. If the
        model dropped something that mattered you can type it straight back in.
        """
        t = self._approval_target
        if not t: return
        nb, i = t
        from .nb import Cell
        c = Cell(source=f'**🗜 context compacted**\n\n{summary}', cell_type='markdown')
        c.approval = {'kind': 'compaction'}
        nb.insert(min(i + 1, len(nb)), c)
        nb.dirty = True

    @property
    def completer(self):
        "Inline completion, on the assistant's engine -- so it loads with it and is missing for the same reasons."
        if self._completer is None: self._completer = Completer(self.ai)
        return self._completer

    # -- folders ---------------------------------------------------------------
    def add_root(self, p): return self.fs.add_root(p)

    def drop_root(self, p):
        "Close a folder, and every tab that lived inside it."
        r = self.fs.drop_root(p)
        self.tabs = self.tabs.filter(lambda t: not (t.path and Path(t.path).is_relative_to(r)))
        self.active = min(self.active, max(0, len(self.tabs)-1))
        return r

    # -- tabs ------------------------------------------------------------------
    @property
    def tab(self): return self.tabs[self.active] if self.tabs else None

    def find(self, path):
        p = str(Path(path).expanduser().resolve())
        return next((i for i, t in enumerate(self.tabs) if t.path == p), None)

    def open(self, path, kind=None):
        "Open a file, focusing it if it is already open. Refuses anything outside the open folders."
        p = self.fs._check(path, must_exist=True)
        if not is_texty(p) and p.suffix.lower() != '.ipynb': raise Unsafe(f'{p.name} is not a text file')
        if (i := self.find(p)) is not None:
            self.active = i
            return self.tabs[i]
        t = Tab(path=str(p), kind=ifnone(kind, 'notebook' if p.suffix == '.ipynb' else 'text'))
        self.tabs.append(t)
        self.active = len(self.tabs) - 1
        return t

    def new_scratch(self, kind='notebook'):
        "An unsaved buffer -- what the IDE opens when there is nothing to open yet."
        self._untitled += 1
        t = Tab(path='', kind=kind, title=f'untitled-{self._untitled}', scratch=True)
        self.tabs.append(t)
        self.active = len(self.tabs) - 1
        return t

    def close(self, i=None):
        i = self.active if i is None else i
        if not (0 <= i < len(self.tabs)): return None
        t = self.tabs.pop(i)
        self.active = max(0, min(self.active if i > self.active else self.active-1, len(self.tabs)-1))
        return t

    def activate(self, i):
        if 0 <= i < len(self.tabs): self.active = i
        return self.tab

    def cycle(self, d=1):
        if self.tabs: self.active = (self.active + d) % len(self.tabs)
        return self.tab

    # -- what is on disk -------------------------------------------------------
    # The editor's buffer and the file are two different things, and the IDE's own
    # features move the file underneath the buffer: the assistant edits, lazygit checks
    # out, a dev server writes. So "what is on disk" is asked often enough to belong here
    # rather than being re-derived by every frontend and by the assistant.
    def text_at(self, ref):
        """One file as a single diffable document, or None when it cannot be read.

        Notebooks come back as `Notebook.source_text` rather than as raw JSON -- a diff
        against the editor should talk about cells, not about nbformat -- and a path that
        does not exist yet is `''`, so a newly created file diffs as a pure addition
        instead of as an error.
        """
        try: p = self.fs._check(ref)
        except Exception: return None
        if not p.exists(): return ''
        try: return Notebook.load(p).source_text() if p.suffix == '.ipynb' else self.fs.read(p)
        except Exception: return None

    def disk_text(self, tab=None):
        "A tab's file as it is on disk, in the shape its buffer is compared against; None when unsaved."
        t = tab or self.tab
        return None if (t is None or not t.path) else self.text_at(t.path)

    # -- prompt cells, and what the assistant can see --------------------------
    def ask_cell(self, nb, i):
        """Answer the prompt cell at `i`, with the notebook above it as its context.

        Blocking -- the model runs on whichever thread calls this, so both frontends hand
        it to a worker. The reply lands *in the cell*, which is the whole point: it is
        saved with the document, read in order with everything else, and re-runnable.

        Everything the agent does while answering lands in the same document: an approval
        it raises becomes markdown cells below this one, a compaction becomes a summary
        cell, and the tool calls are folded under the answer. So the notebook is the whole
        record of the exchange, not just its last line.
        """
        c = nb[i]
        if not c.is_prompt: raise ValueError(f'cell {i} is a {c.cell_type} cell, not a prompt')
        a = self.ai
        png, screen, _ = self.take_screen()
        self._approval_target = (nb, i)
        try:
            text = a.ask_with(c.source, context=nb.context(i, since=nb.prompt_start(i)),
                              screen=screen, image=png)
        finally:
            self._approval_target = None
        trail = a.turn_md()
        c.reply = f'{text}\n\n{trail}' if trail else text
        c.calls = a.activity.rows(mark=a.activity._mark)
        nb.dirty = True
        return c

    def ask(self, prompt):
        "One turn from a prompt bar, with any pending capture attached."
        png, screen, _ = self.take_screen()
        return self.ai.ask_with(prompt, screen=screen, image=png)

    def ask_stream(self, prompt):
        "The same turn, yielding markdown as it arrives. A cloud turn is far too long to sit through."
        png, screen, _ = self.take_screen()
        return self.ai.stream_with(prompt, screen=screen, image=png)

    def ask_cell_stream(self, nb, i):
        """Answer the prompt cell at `i`, filling the cell in as the answer arrives.

        Yields each markdown chunk *and* appends it to `cell.reply` on the way past, so a
        frontend can either render the chunks itself or simply repaint the cell — the cell
        is already the correct thing to look at, which is the advantage of having put the
        answer in the document in the first place.

        The activity trail is appended at the end rather than streamed, because it is a
        fold that belongs under the finished answer, not interleaved with it.
        """
        c = nb[i]
        if not c.is_prompt: raise ValueError(f'cell {i} is a {c.cell_type} cell, not a prompt')
        a = self.ai
        png, screen, _ = self.take_screen()
        c.reply, c.calls = '', []
        nb.dirty = True
        self._approval_target = (nb, i)
        try:
            for chunk in a.stream_with(c.source, context=nb.context(i, since=nb.prompt_start(i)),
                                       screen=screen, image=png):
                c.reply += chunk
                # Refreshed per chunk, not only at the end: a frontend that repaints the
                # cell should see the tool trail and the answer agree at every moment.
                c.calls = a.activity.rows(mark=a.activity._mark)
                yield chunk
        finally:
            self._approval_target = None
            if (trail := a.turn_md()): c.reply += f'\n\n{trail}'
            c.calls = a.activity.rows(mark=a.activity._mark)
            nb.dirty = True

    # -- approvals -------------------------------------------------------------
    @property
    def pending_approval(self):
        "The write waiting for a person, or None. What both frontends poll while a turn runs."
        return self.approvals.pending

    def answer_approval(self, id, ok, note=''):
        "Answer the pending approval. `note` is the reason, and the reason goes back to the model."
        return self.approvals.answer(id, ok, note)

    def put_screen(self, png=None, text='', note=''):
        """Hold a capture for the next question. One slot, because the useful capture is the latest.

        Two shapes, because the frontends can capture different things. The browser sends
        a picture -- it can grab any window on the desktop, and a photograph is the only
        way to carry that. The terminal sends text, because its screen *is* text, and
        handing a model a picture of characters it could have read directly is a waste of
        both fidelity and context.
        """
        self.screen = (png or None, text or '', note or '')
        return self.screen

    def take_screen(self):
        """Consume the pending capture as `(png, text, note)`.

        Consumed rather than kept: something captured to explain one thing should not
        silently ride along with an unrelated question ten minutes later.
        """
        s, self.screen = self.screen, (None, '', '')
        return s

    def save_screen(self, svg, name=None):
        "Write a captured screen where a person can open it -- leela's own config dir, not the project."
        d = leela_cfg/'screens'
        d.mkdir(parents=True, exist_ok=True)
        p = d/(name or f"screen-{time.strftime('%Y%m%d-%H%M%S')}.svg")
        p.write_text(svg)
        return p

    # -- kernels ---------------------------------------------------------------
    def kernel_key(self, tab=None):
        """Which kernel a tab uses. Per open root by default, so tabs in one project share a
        namespace with each other and with the exec strip; `private_kernel` opts out."""
        t = tab or self.tab
        if t is None: return str(self.fs.roots[0]) if self.fs.roots else 'default'
        if t.private_kernel: return f'tab:{t.path or t.title}'
        if not t.path: return str(self.fs.roots[0]) if self.fs.roots else 'default'
        try: return str(self.fs.root_of(t.path))
        except Unsafe: return 'default'

    async def kernel(self, tab=None):
        "The live kernel for a tab, started on first use."
        t = tab or self.tab
        key = self.kernel_key(t)
        cwd = key if Path(key).is_dir() else (self.fs.roots[0] if self.fs.roots else None)
        return await self.pool.get(key, cwd=cwd, name=Path(key).name if cwd else None, agent=self.agent)

    def kernel_peek(self, tab=None): return self.pool.peek(self.kernel_key(tab))

    async def shutdown(self):
        "Stop every kernel, dev server, terminal and model this workspace started."
        self.terms.close_all()
        if self._ai is not None: self._ai.close()
        await self.dev.stop_all()
        await self.pool.close_all()

    # -- persistence -----------------------------------------------------------
    def state(self):
        return {'roots': [str(r) for r in self.fs.roots],
                'tabs': [t.dict() for t in self.tabs if not t.scratch],
                'active': self.active, 'saved': time.time()}

    def save(self, path=None):
        "Persist folders and tabs (never kernels -- their namespaces do not survive the process)."
        p = Path(path or ws_path())
        try: p.write_json(self.state())
        except OSError: pass
        return p

    @classmethod
    def load(cls, path=None, port=8000, agent='restricted', kernel='ipykernel',
             model=None, approvals='ask'):
        "Restore a saved workspace, dropping any folder or file that has since gone away."
        p = Path(path or ws_path())
        try: d = p.read_json()
        except Exception: d = {}
        ws = cls(port=port, agent=agent, kernel=kernel, model=model, approvals=approvals)
        for r in d.get('roots', []):
            try: ws.add_root(r)
            except Exception: pass
        for t in d.get('tabs', []):
            try: ws.open(t['path'])
            except Exception: pass
        ws.active = min(d.get('active', 0), max(0, len(ws.tabs)-1))
        return ws
