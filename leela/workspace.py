"""Open folders, open tabs, and which kernel each tab talks to.

The kernel binding is the interesting decision here. Notebook tabs own a private
kernel by default, while source-file tabs under one open folder share that folder's
kernel. The exec strip and Variables follow the active tab, so two notebooks cannot
silently leak state into each other; a notebook can explicitly attach to the folder
kernel when sharing is useful.

State persists to the leela config dir, so reopening the IDE restores the
folders and tabs but never the kernels -- a dead kernel's variables are gone,
and pretending otherwise would be a lie about what is live.
"""

from __future__ import annotations
import hashlib, time
from dataclasses import dataclass
from fastcore.all import Path, L, ifnone

from . import Dictable, leela_cfg
from .ai import Assistant, Completer, notebook_approvals
from .devserver import DevServers
from .fs import Sandbox, Unsafe, lang_for, is_texty
from .kernels import KernelPool
from .nb import Notebook
from .research import Research
from .runs import Run, Runs
from .search import Search
from .term import Terminals

__all__ = ['Tab', 'Workspace', 'ws_path']


class _EnvClient:
    """Read-only access to some *other* process's inspector, in the shape `Kernel.api` has.

    So the panel does not care what it is looking at. A kernel has an execution channel and
    a lifecycle on top of this; an app leela started, or a process that called
    `dhrishti.serving.serve()` itself, has only the HTTP surface -- which is all the variable
    tree ever used.
    """

    def __init__(self, base, name=''):
        self.base, self.name = base, name
        self.alive, self.boot_error, self.pid = True, None, None
        self.kernel_kind = 'env'

    @property
    def token(self):
        "The owner token this inspector wrote next to its registry entry, if it armed one."
        from dhrishti.serving import reg_dir
        try: return (reg_dir()/f"token-{self.base.rsplit(':', 1)[-1]}").read_text().strip() or None
        except Exception: return None

    async def api(self, path, params=None, timeout=15):
        import httpx
        h = {'X-Dhrishti-Token': t} if (t := self.token) else {}
        try:
            async with httpx.AsyncClient(base_url=self.base, timeout=timeout, headers=h) as c:
                r = await c.get(path, params=params or {})
                r.raise_for_status()
                return r.json()
        except Exception:
            return None

    def api_sync(self, path, params=None, timeout=15):
        import httpx2 as httpx
        h = {'X-Dhrishti-Token': t} if (t := self.token) else {}
        try:
            with httpx.Client(base_url=self.base, timeout=timeout, headers=h) as c:
                r = c.get(path, params=params or {}); r.raise_for_status(); return r.json()
        except Exception: return None

    async def names(self, scope='live', profile='full'):
        r = await self.api('/api/rows', {'profile': profile, 'sort': 'name'})
        return L(n.get('name', '') for g in (r or {}).get('groups', []) for n in g.get('nodes', []))

    async def execute(self, code, on_output=None, **kw):
        """Execute through the watched runtime's owner HTTP surface.

        A managed notebook kernel normally uses its richer Jupyter shell channel. External
        kernels and leela-started apps only expose the inspector, but that inspector owns
        the same namespace and has a token-gated executor. Normalising it to ``ExecOutcome``
        means cells, files and the exec strip follow the runtime picked in the UI instead
        of silently falling back to the tab kernel.
        """
        from .kernels import ExecOutcome
        r = await self.api('/api/exec', {'code': code, 'scope': 'global'},
                           timeout=kw.get('timeout') or 120)
        if r is None: return ExecOutcome(ok=False, error=f'{self.name} did not answer')
        outs = []
        if (text := r.get('stdout')):
            outs.append({'output_type': 'stream', 'name': 'stdout', 'text': text})
        if (result := r.get('result')) is not None:
            outs.append({'output_type': 'execute_result', 'execution_count': None, 'metadata': {},
                         'data': {'text/plain': result.get('value', '')}})
        if (err := r.get('error')):
            typ, _, value = err.partition(': ')
            outs.append({'output_type': 'error', 'ename': typ, 'evalue': value,
                         'traceback': [err]})
        if on_output:
            for out in outs: on_output(out)
        return ExecOutcome(ok=bool(r.get('ok')), outputs=outs, error=err or None)
    async def complete(self, code, pos): return {'from': pos, 'matches': []}
    async def inspect_obj(self, code, pos, detail=0): return ''
    async def interrupt(self): pass
    async def restart(self): pass


def ws_path(): return leela_cfg/'workspace.json'


@dataclass
class Tab(Dictable):
    'One open editor tab.'
    path: str                       # absolute path; '' for an unsaved buffer
    kind: str = 'text'              # 'notebook' | 'text'
    title: str = ''
    dirty: bool = False
    private_kernel: bool | None = None  # notebooks own one by default; files use the folder kernel
    scratch: bool = False               # never written to disk
    running: int = 0                    # in-flight cells; transient tab-bar feedback
    cwd: str = ''                       # optional per-tab working-directory override

    def __post_init__(self):
        if not self.title: self.title = Path(self.path).name or 'untitled'
        if self.path.endswith('.ipynb'): self.kind = 'notebook'
        if self.private_kernel is None: self.private_kernel = self.kind == 'notebook'

    @property
    def lang(self): return 'python' if self.kind == 'notebook' else lang_for(self.path)


class Workspace:
    "The IDE's session: open folders, open tabs, and the kernels behind them."

    def __init__(self, roots=(), port=8000, agent='restricted', dev_port=9000, kernel='ipykernel',
                 model=None,              # the agent pane's model; None takes the routing default
                 inline_model=None,       # prompt cells default to GPT-5.6 Luna
                 completion_model=None,   # code completion defaults to GPT-4.1
                 local_multimodal=False,  # opt in to LiteRT vision/audio encoders
                 approvals='ask',         # 'ask' | 'auto' (approve every write) | 'off' (refuse them)
                 agent_scope='overlay',   # widest scope `inspect_python` may use: 'overlay' | 'isolated'
                 python=None,             # interpreter kernels launch under; None is leela's own
                 transport='direct', gateway=None):
        self.fs = Sandbox(roots)
        # Leela stays in its own environment; user code belongs to the folder's. A
        # conventional project venv is therefore the runtime default, without importing
        # or installing the IDE itself into that venv.
        from .kernels import project_python
        runtime_python = python or project_python(self.fs.roots)
        self.pool = KernelPool(port=port, default_kernel=kernel, default_python=runtime_python,
                               transport=transport, gateway=gateway)
        self.dev = DevServers(port=dev_port)
        # Both go through the provider registry rather than being constructed directly, so
        # an alternate implementation is `LEELA_SEARCH=…` / `LEELA_MEMORY=…` rather than an
        # edit here. `leela` is registered like any other provider, so the default takes
        # exactly the same path an alternate does. See `leela/core/providers.py`.
        from .core.providers import build as build_provider
        self.search = build_provider('search', self.fs)
        # Web memory reuses Kosha's already-resident embedder but owns a document-tree DB;
        # code ASTs and prose headings are different corpora and should not share tables.
        self.memory = build_provider('memory', kosha=getattr(self.search, '_kosha', None))
        self.research = Research(self.fs, memory=self.memory)
        self.runs = Runs(self.fs.roots[0] if self.fs.roots else None)
        from .journal import OperationJournal
        journal_key = hashlib.sha256('\0'.join(map(str, self.fs.roots)).encode()).hexdigest()[:16]
        self.journal = OperationJournal(leela_cfg/'journals'/f'{journal_key}.json', self.fs)
        self._lsp = None
        # Which live inspector the variable panel is looking at, when it is not the tab's
        # own kernel. A base URL, because that is what identifies an env across processes.
        self.env_base = None
        self.terms = Terminals(cwd=self.fs.roots[0] if self.fs.roots else None)
        self.agent = agent
        # `kernel_kind`, not `kernel`: `kernel()` below is the coroutine that hands out the
        # live kernel for a tab, and an attribute of the same name shadows it — every
        # `await ws.kernel()` would otherwise await the string 'ipykernel'.
        self.kernel_kind = kernel
        # The widest scope the agent's read-only execution may reach for. Neither scope
        # can change what the user made; 'isolated' additionally denies it the real
        # interpreter, which is the setting for a machine where even a scratch layer in
        # the kernel is unwanted.
        self.agent_scope = agent_scope
        self.tabs = L()
        self.active = 0
        self._untitled = 0
        self._ai = self._inline_ai = self._completer = None
        from .agent.core import env as model_env
        self.model = model                # agent-pane model; None takes the routing default
        self.inline_model = inline_model or model_env('MODEL_INLINE') or 'gpt-mini'
        self.completion_model = completion_model or model_env('MODEL_COMPLETION') or 'gpt-4.1'
        self.local_multimodal = bool(local_multimodal)
        self.compact_auto, self.compact_strategy = True, 'surgical'
        self.agent_state = ''             # compatibility alias for the task layer
        self.agent_state_layers = {name: {'text': '', 'enabled': True, 'source': 'workspace'} for name in
                                   ('organization', 'project', 'task', 'preferences', 'branch', 'ephemeral')}
        # Explicit per-surface note routing. Notes remain durable in Memory; this selection
        # says which ones enter model context for this workspace/session.
        self.agent_memory_selection = {'agent': [], 'inline': [], 'completion': []}
        self.screen = (None, '', '')      # a capture waiting to ride along with the next question
        self.on_note = None               # a frontend's status line, when one has registered
        # Where an approval raised mid-turn writes itself. Set by `ask_cell` for the length
        # of one prompt cell and cleared afterwards, so an approval for a question typed in
        # the prompt bar does not land in whichever notebook happens to be open.
        self._approval_target = None
        self.approvals = notebook_approvals(lambda: self._approval_target, mode=approvals)

    @property
    def ai(self):
        "The agent-pane assistant: durable conversation and the model chosen for agentic work."
        if self._ai is None:
            self._ai = Assistant(self, model=self.model, surface='agent', local_multimodal=self.local_multimodal,
                                 on_compact=self._compacted, history_name='agent')
            if self.completion_model:
                self._ai.set_model(self.completion_model, job='completion')
            self.approvals.host = self._ai.host
        return self._ai

    @property
    def inline_ai(self):
        "Prompt cells use their own smaller model and conversation, never the agent pane's context."
        if self._inline_ai is None:
            from .agent.core import env
            self._inline_ai = Assistant(self, model=self.inline_model or env('MODEL_INLINE'), surface='inline',
                                        local_multimodal=self.local_multimodal,
                                        on_compact=self._compacted, history_name='inline')
            self.approvals.host = self._inline_ai.host
        return self._inline_ai

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
    def _rebrief_agents(self):
        """Tell any live assistant that the open folders changed.

        The sandbox already lets the agent *reach* a newly opened folder -- `WorkspaceHost`
        reads `fs.roots` live -- but its briefing, code index scope, skills and extensions are
        discovered once and cached, so without this a folder opened mid-chat is reachable yet
        unmentioned. `refresh` re-discovers those and re-briefs the running conversation without
        reloading the model. Guarded because opening a folder must not fail on an agent that isn't ready.
        """
        for a in (self._ai, self._inline_ai):
            if a is not None:
                try: a.refresh()
                except Exception: pass

    def add_root(self, p):
        r = self.fs.add_root(p)
        if self.runs.root is None: self.runs = Runs(self.fs.roots[0])
        # Adopt a project venv only before any runtime has started. Opening another folder
        # must never restart or silently retarget a live namespace.
        if not self.pool.kernels and self.pool.default_python is None:
            from .kernels import project_python
            if (py := project_python([r])): self.pool.choose(python=py)
        self._rebrief_agents()
        return r

    def drop_root(self, p):
        "Close a folder, and every tab that lived inside it."
        r = self.fs.drop_root(p)
        self.tabs = self.tabs.filter(lambda t: not (t.path and Path(t.path).is_relative_to(r)))
        self.active = min(self.active, max(0, len(self.tabs)-1))
        self._rebrief_agents()
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
            self.watch_env(None)
            return self.tabs[i]
        t = Tab(path=str(p), kind=ifnone(kind, 'notebook' if p.suffix == '.ipynb' else 'text'))
        self.tabs.append(t)
        self.active = len(self.tabs) - 1
        self.watch_env(None)
        return t

    def new_scratch(self, kind='notebook'):
        "An unsaved buffer -- what the IDE opens when there is nothing to open yet."
        self._untitled += 1
        t = Tab(path='', kind=kind, title=f'untitled-{self._untitled}', scratch=True)
        self.tabs.append(t)
        self.active = len(self.tabs) - 1
        self.watch_env(None)
        return t

    def create_document(self, path):
        """Create a file in its native empty shape.

        In particular, an `.ipynb` is a JSON document, not a zero-byte text file. Both
        frontends come through here so creating a notebook by typing its extension works
        the same way as the dedicated new-notebook action.
        """
        p = self.fs._check(path)
        if p.exists(): raise FileExistsError(str(p))
        if p.suffix.lower() == '.ipynb':
            Notebook.blank(p).save(p, sandbox=self.fs)
            return self.fs.entry(p)
        return self.fs.touch(p)

    def close(self, i=None):
        i = self.active if i is None else i
        if not (0 <= i < len(self.tabs)): return None
        t = self.tabs.pop(i)
        self.active = max(0, min(self.active if i > self.active else self.active-1, len(self.tabs)-1))
        self.watch_env(None)
        return t

    def activate(self, i):
        if 0 <= i < len(self.tabs):
            self.active = i
            self.watch_env(None)
        return self.tab

    def cycle(self, d=1):
        if self.tabs:
            self.active = (self.active + d) % len(self.tabs)
            self.watch_env(None)
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
    def _agent_context(self, nb, i, prompt, agent=None):
        agent = agent or self.ai
        # The notebook is the inline agent's source of truth. Send every cell above the
        # prompt on every run: cells may have been edited since the backend last saw them.
        # Their keep/discard policy travels in the markup and is used only if the selected
        # model's context window forces compaction.
        context = nb.context(i)
        from .agent.runtime import ACTION_NOTICE, prompt_notices
        if ACTION_NOTICE in prompt_notices(prompt):
            try:
                live = agent.host.list_vars()
                if live: context += f'\n<live-variables>\n{live}\n</live-variables>'
            except Exception: pass
        return context

    @staticmethod
    def _requested_name(prompt):
        import re
        m = re.search(r'\bas\s+([A-Za-z_]\w*)\s*$', (prompt or '').strip())
        return m.group(1) if m else ''

    def _name_exists(self, name, agent=None):
        if not name: return True
        try:
            import re
            return bool(re.search(rf'(?m)^{re.escape(name)}\s*:', (agent or self.inline_ai).host.list_vars()))
        except Exception: return True       # unverifiable is not the same as failed

    def _action_retry(self, prompt, agent=None):
        name = self._requested_name(prompt)
        if not name or self._name_exists(name, agent): return ''
        scale = (' Call `scale_numeric` with source `df` and this output name.'
                 if 'scale' in prompt.lower() and 'numeric' in prompt.lower() else
                 ' Call the appropriate execution tool now with only the required transformation.')
        return (f'The action is incomplete: `{name}` does not exist in the live namespace. '
                f'Do not explain or plan.{scale} Verify `{name}` exists, then answer briefly.')

    def ask_cell(self, nb, i):
        """Answer the prompt cell at `i`, with the notebook above it as its context.

        Blocking -- the model runs on whichever thread calls this, so the web frontend hands
        it to a worker. The reply lands *in the cell*, which is the whole point: it is
        saved with the document, read in order with everything else, and re-runnable.

        Everything the agent does while answering lands in the same document: an approval
        it raises becomes markdown cells below this one, a compaction becomes a summary
        cell, and the tool calls are folded under the answer. So the notebook is the whole
        record of the exchange, not just its last line.
        """
        c = nb[i]
        if not c.is_prompt: raise ValueError(f'cell {i} is a {c.cell_type} cell, not a prompt')
        a = self.inline_ai
        png, screen, _ = self.take_screen()
        self._approval_target = (nb, i)
        started = time.perf_counter()
        try:
            text = a.ask_with(c.source, context=self._agent_context(nb, i, c.source, a),
                              screen=screen, image=png, context_path=nb.path)
            for _ in range(2):
                retry = self._action_retry(c.source, a)
                if not retry: break
                text += '\n\n' + a.ask(retry)
        finally:
            self._approval_target = None
            c.execution_ms = (time.perf_counter() - started) * 1000
        trail = a.turn_md()
        c.reply = f'{text}\n\n{trail}' if trail else text
        c.calls = a.activity.rows(mark=a.activity._mark)
        c.usage = a.turn_use.dict()
        nb.dirty = True
        return c

    def _attachment_context(self, refs=(), max_file=120_000, max_total=300_000):
        "Workspace files selected with @, as grounded text context and multimodal image parts."
        text, images, used = [], [], 0
        image_exts = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}
        for ref in dict.fromkeys(str(x) for x in (refs or ()) if str(x).strip()):
            p = self.fs._check(ref, must_exist=True)
            if not p.is_file(): raise ValueError(f'attachment is not a file: {ref}')
            if p.suffix.lower() in image_exts:
                images.append(p.read_bytes())
                continue
            raw = p.read_bytes()[:max_file]
            body = raw.decode('utf-8', 'replace')
            remaining = max_total - used
            if remaining <= 0: break
            body = body[:remaining]; used += len(body)
            clipped = '\n[attachment clipped]' if len(raw) >= max_file else ''
            text.append(f'<attached-file path="{p}">\n{body}{clipped}\n</attached-file>')
        return '\n\n'.join(text), images

    def ask(self, prompt, attachments=(), context='', context_path=''):
        "One turn from a prompt bar, grounded by the open notebook and @-selected files."
        png, screen, _ = self.take_screen()
        attached, images = self._attachment_context(attachments)
        context = '\n\n'.join(x for x in (context, attached) if x)
        media = ([png] if png else []) + images
        return self.ai.ask_with(prompt, context=context, screen=screen, image=media or None,
                                context_path=context_path)

    def ask_stream(self, prompt, attachments=(), reasoning=None, context='', context_path=''):
        """The same turn, yielding markdown as it arrives.

        Reasoning effort is a provider-level cloud option. Local engines keep their own
        decoding policy, so the composer may safely retain one preference while models
        change without passing an unsupported argument into Rishi.
        """
        png, screen, _ = self.take_screen()
        attached, images = self._attachment_context(attachments)
        context = '\n\n'.join(x for x in (context, attached) if x)
        media = ([png] if png else []) + images
        kw = {'reasoning_effort': reasoning} if reasoning and not self.ai.model.local else {}
        return self.ai.stream_with(prompt, context=context, screen=screen, image=media or None,
                                   context_path=context_path, **kw)

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
        a = self.inline_ai
        png, screen, _ = self.take_screen()
        c.reply, c.calls, c.usage = '', [], {}
        nb.dirty = True
        self._approval_target = (nb, i)
        started = time.perf_counter()
        try:
            # Ground action prompts in the live namespace before a small local model
            # decides what to execute; notebook output is evidence, not Python source.
            context = self._agent_context(nb, i, c.source, a)
            prompts = [a.stream_with(c.source, context=context, screen=screen, image=png,
                                     context_path=nb.path)]
            for attempt in range(3):
                for chunk in prompts[-1]:
                    c.reply += chunk
                    # Refreshed per chunk, not only at the end: a frontend that repaints the
                    # cell should see the tool trail and the answer agree at every moment.
                    c.calls = a.activity.rows(mark=a.activity._mark)
                    yield chunk
                retry = self._action_retry(c.source, a)
                if not retry or attempt == 2: break
                sep = '\n\n'
                c.reply += sep
                yield sep
                prompts.append(a.stream(retry))
        finally:
            self._approval_target = None
            c.execution_ms = (time.perf_counter() - started) * 1000
            if (trail := a.turn_md()): c.reply += f'\n\n{trail}'
            c.calls = a.activity.rows(mark=a.activity._mark)
            c.usage = a.turn_use.dict()
            nb.dirty = True

    # -- approvals -------------------------------------------------------------
    @property
    def pending_approval(self):
        "The write waiting for a person, or None. What the web frontend polls during a turn."
        return self.approvals.pending

    def answer_approval(self, id, ok, note='', session=False, tool=None, args=None):
        """Resolve one checkpoint, including an optional user rewrite of the proposed call."""
        return self.approvals.answer(id, ok, note, session=session, tool=tool, args=args)

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
    def cwd_for(self, tab=None):
        """The tab's working directory: override, notebook directory, then project root.

        Notebook paths are authored relative to the notebook itself. A notebook under
        ``nbs/`` using ``..`` expects the project root—the behavior in Jupyter and PyCharm.
        Source files still use their Git/open-folder root. An explicit override wins for
        both and remains confined to an open folder.
        """
        t = tab or self.tab
        if t is not None and t.cwd:
            try:
                p = self.fs._check(t.cwd, must_exist=True)
                if p.is_dir(): return p
            except (Unsafe, OSError): pass
        if t is not None and t.path:
            try:
                root = self.fs.root_of(t.path)
                if t.kind == 'notebook': return Path(t.path).parent
                from .git import repo_root
                return repo_root(Path(t.path).parent) or root
            except Unsafe: pass
        if self.fs.roots:
            from .git import repo_root
            return repo_root(self.fs.roots[0]) or self.fs.roots[0]
        return None

    def set_cwd(self, path=None, tab=None):
        """Set a per-tab cwd, or clear it with an empty path to return to auto mode."""
        t = tab or self.tab
        if t is None: raise ValueError('nothing open')
        if not path:
            t.cwd = ''
            return self.cwd_for(t)
        p = self.fs._check(path, must_exist=True)
        if not p.is_dir(): raise ValueError(f'not a directory: {p}')
        t.cwd = str(p)
        return p

    def kernel_key(self, tab=None):
        """Which kernel a tab uses. Notebooks are private by default; source files share
        their open root. ``private_kernel`` is the explicit attachment choice."""
        t = tab or self.tab
        if t is None: return str(self.fs.roots[0]) if self.fs.roots else 'default'
        if t.private_kernel: return f'tab:{t.path or t.title}'
        if not t.path: return str(self.fs.roots[0]) if self.fs.roots else 'default'
        try: return str(self.fs.root_of(t.path))
        except Unsafe: return 'default'

    async def kernel(self, tab=None):
        "The live kernel for a tab, started in the folder that owns that tab."
        t = tab or self.tab
        key, cwd = self.kernel_key(t), self.cwd_for(t)
        try: name = self.fs.root_of(t.path).name if t and t.path else Path(cwd).name
        except Exception: name = Path(cwd).name if cwd else None
        return await self.pool.get(key, cwd=cwd, name=name, agent=self.agent)

    def kernel_peek(self, tab=None): return self.pool.peek(self.kernel_key(tab))

    def watched_kernel(self):
        "The managed kernel selected in the env picker, if that is what is being watched."
        if not self.env_base: return None
        return next((k for k in self.pool.kernels.values()
                     if k is not None and getattr(k, 'base', None) == self.env_base), None)

    async def runtime(self, tab=None):
        """Where Run executes: the explicitly picked runtime, else the tab's kernel.

        For a managed kernel this returns the real ``Kernel`` and retains rich Jupyter
        outputs. For an inspected app/external kernel it returns ``_EnvClient``, whose
        token-gated HTTP executor runs in that process's live namespace.
        """
        if (k := self.watched_kernel()) is not None: return k
        if self.env_base and (env := self.inspector(tab)) is not None: return env
        t = tab or self.tab
        k = await self.kernel(t)
        # Inspector bootstrap is not the kernel itself. A project may have shadowed Leela's
        # dhrishti with an older package, leaving execution healthy but Variables blank.
        # Retry bootstrap in the existing process (no restart, namespace preserved), with
        # a cooldown so a genuinely broken environment is not hammered by panel polling.
        if getattr(k, 'inspect', False) and not getattr(k, 'base', None):
            now, last = time.monotonic(), getattr(k, '_inspector_retry_at', 0.0)
            if now - last >= 10:
                k._inspector_retry_at = now
                k.boot_error = None
                await k.bootstrap()
        desired, current = self.cwd_for(t), getattr(k, 'cwd', None)
        if desired and current and Path(desired).resolve() != Path(current).resolve():
            # Preserve a live namespace when an upgraded Leela corrects notebook cwd from
            # project root to notebook directory. Restarting would fix cwd but discard every
            # variable; one hidden chdir gives the existing process the same semantics.
            result = await k.execute(f'import os as __leela_os; __leela_os.chdir({str(desired)!r}); del __leela_os')
            if not result.ok: raise RuntimeError(result.error or f'could not change kernel cwd to {desired}')
            k.cwd = desired
        return k

    def runtime_peek(self, tab=None):
        "The selected runtime without starting a tab kernel."
        return self.watched_kernel() or (self.inspector(tab) if self.env_base else self.kernel_peek(tab))

    # -- live envs -------------------------------------------------------------
    # The variable panel used to be able to look at exactly one thing: the active tab's
    # kernel. Everything else that registers an inspector -- an app leela started, a
    # process that called `dhrishti.serving.serve()` itself -- was discoverable and
    # unwatchable, which is a strange place to stop.
    def envs(self):
        """Every inspector this IDE could point the variable panel at.

        Kernels are listed from the pool rather than from the registry so a tab's kernel is
        named after its folder, the way the rest of the IDE names it; everything else comes
        from the registry, which is where any process that called `serve()` writes itself.
        """
        from dhrishti.serving import active
        out, seen = L(), set()
        for key, k in self.pool.kernels.items():
            if not (k and getattr(k, 'base', None)): continue
            seen.add(k.base)
            out.append({'name': Path(key).name or 'kernel', 'base': k.base, 'kind': 'kernel',
                        'pid': k.pid, 'current': k.base == self.env_base,
                        'is_tab': key == self.kernel_key()})
        for e in active():
            if e.get('base') in seen: continue
            out.append({'name': e.get('name') or f"pid {e.get('pid')}", 'base': e['base'],
                        'kind': 'app', 'pid': e.get('pid'), 'cwd': e.get('cwd', ''),
                        'current': e['base'] == self.env_base, 'is_tab': False})
        return out

    def watch_env(self, base=None):
        "Point the variable panel at one env, or back at the active tab's kernel with `None`."
        self.env_base = base or None
        return self.env_base

    def inspector(self, tab=None):
        """What the variable panel should be reading: the chosen env, else the tab's kernel.

        Falls back rather than failing when the chosen env has gone away -- an app you were
        watching exits, and the panel should quietly return to the kernel instead of going
        blank and staying blank.
        """
        if self.env_base:
            e = next((x for x in self.envs() if x['base'] == self.env_base), None)
            if e is None: self.env_base = None
            else: return _EnvClient(e['base'], e['name'])
        return self.kernel_peek(tab)

    # -- run configurations ----------------------------------------------------
    async def run(self, name_or_path, save=False):
        """Start a run configuration, or a file, under a live inspector. Returns the `DevServer`.

        The inspector goes *inside* the process the command runs in, which is what makes
        the variable panel able to show a request handler mutating state while it serves.
        A command started anywhere else -- a shell, another terminal -- has no inspector in
        it and cannot be watched; that is what `dhrishti.serving.serve()` is for.
        """
        r = self.runs.get(name_or_path)
        if r is None:
            p = self.fs._check(name_or_path, must_exist=True)
            r = self.runs.for_file(p)
            if save: self.runs.add(r)
        root = self.fs.roots[0] if self.fs.roots else None
        return await self.dev.start(r.cmd, cwd=r.resolved_cwd(root) if root else None,
                                    name=r.name, watch=r.watch, env=r.resolved_env(root))

    def kernel_options(self, tab=None):
        """Everything a kernel picker needs, so neither frontend has to know how kernels work.

        Both halves of the choice are here because both are things people mean by "which
        kernel": the *launcher* (ipykernel, or ipymini for execs that do not queue behind a
        running cell) and the *interpreter* (which venv's packages the notebook can import).
        `available` is on the launcher rather than filtered out of the list, so an option
        that is missing says why instead of not being there.
        """
        from .kernels import KERNELS, find_pythons, ipymini_available
        t = tab or self.tab
        k = self.kernel_peek(t)
        cur_py = self.pool.default_python
        return {
            'key': self.kernel_key(t),
            'alive': bool(k and k.alive),
            'pid': k.pid if k else None,
            'boot_error': k.boot_error if k else None,
            'api_error': getattr(k, 'last_api_error', '') if k else '',
            'private': bool(t and t.private_kernel),
            'cwd': str(self.cwd_for(t) or ''),
            'kinds': [{'id': n, 'current': n == self.pool.default_kernel,
                       'available': n != 'ipymini' or ipymini_available(),
                       'note': ('' if n != 'ipymini' or ipymini_available()
                                else 'install project kernel support')} for n in KERNELS],
            'running_kind': getattr(k, 'kernel_kind', self.pool.default_kernel),
            'pythons': [{**p, 'current': p['path'] == cur_py or (cur_py is None and i == 0)}
                        for i, p in enumerate(find_pythons(self.fs.roots))],
            'python': cur_py,
        }

    async def set_kernel(self, kind=None, python=False, private=None, tab=None, restart=True):
        """Point a tab at a different kernel, and start it.

        The old kernel is shut down rather than left running: two interpreters holding two
        copies of a large frame is not what anyone asked for by picking from a list, and the
        variable panel can only show one of them anyway. What *is* preserved is the choice
        of when -- `restart=False` lets a caller stage the selection and apply it later.
        """
        t = tab or self.tab
        old_key = self.kernel_key(t)
        # A kernel choice is also a variable-view choice. If the panel was pinned to a
        # process (or to the old kernel's inspector URL), leaving that pin in place makes
        # a successful kernel switch look broken because its namespace never appears.
        self.watch_env(None)
        self.pool.choose(kernel=kind, python=python)
        if private is not None and t is not None: t.private_kernel = bool(private)
        if not restart: return self.kernel_options(t)
        new_key = self.kernel_key(t)
        # Changing interpreter/launcher restarts the selected kernel. Changing attachment
        # keeps the old one alive because another notebook or file may still be using it.
        if old_key == new_key: await self.pool.close(new_key)
        elif old_key.startswith('tab:'): await self.pool.close(old_key)
        await self.kernel(t)
        return self.kernel_options(t)

    async def restart_kernel(self, tab=None):
        "Restart the tab's kernel in place, keeping its key and its port."
        k = self.kernel_peek(tab)
        if k is None: return await self.kernel(tab)
        await k.restart()
        return k

    # -- running a file --------------------------------------------------------
    def initialize_empty_notebooks(self, root=None):
        """Turn zero-byte ``.ipynb`` placeholders into valid empty notebooks before code runs.

        Generic file pickers and older Leela builds created notebooks with ``touch``. They
        open as blank documents here, but project indexers read them directly from disk and
        correctly reject empty JSON. There is no content to lose, so normalize only exact
        zero-byte notebooks, never malformed non-empty files.
        """
        root = self.fs._check(root or self.cwd_for(), must_exist=True)
        fixed = []
        for path in self.fs.walk(root):
            if path.suffix.lower() != '.ipynb': continue
            try:
                if path.stat().st_size == 0:
                    Notebook.blank(path).save(path, sandbox=self.fs); fixed.append(str(path))
            except OSError: continue
        return fixed

    def run_file_code(self, tab=None, src=None):
        """`(code, label)` that runs a tab's file as a script in its kernel, or `(None, why)`.

        Notebooks are cells and files are scripts, and until now only the first of those
        could actually be run: a `.py` tab was a one-cell document, so "run" meant "run the
        whole thing as a cell", with no `__main__` and no argv. This is the other half --
        the same file, run the way `python file.py` would run it, but *in* the kernel, so
        the variable panel has what it defined afterwards.
        """
        from .kernels import run_file_src
        t = tab or self.tab
        if t is None: return None, 'nothing open'
        if t.kind == 'notebook': return None, 'this is a notebook — run its cells, or use run all'
        if not t.path: return None, f'{t.title} has never been saved'
        if not t.path.endswith('.py'): return None, f'{Path(t.path).name} is not a python file'
        if src is None:
            src = self.text_at(t.path)
            if src is None: return None, f'could not read {Path(t.path).name}'
        return run_file_src(t.path, src, cwd=self.cwd_for(t)), Path(t.path).name

    @property
    def lsp(self):
        if self._lsp is None:
            from .lsp import PyrightService
            self._lsp = PyrightService(self.fs.roots[0] if self.fs.roots else None)
        return self._lsp

    async def shutdown(self):
        "Stop every kernel, dev server, terminal and model this workspace started."
        self.terms.close_all()
        if self._ai is not None: self._ai.close()
        if self._inline_ai is not None: self._inline_ai.close()
        if self._lsp is not None: self._lsp.close()
        await self.dev.stop_all()
        await self.pool.close_all()

    # -- persistence -----------------------------------------------------------
    def agent_memory_context(self, target='agent', max_chars=24_000):
        "Selected user notes for one model surface, bounded and visibly titled."
        ids = self.agent_memory_selection.get(target, [])
        if not ids: return ''
        notes = {str(note['id']): note for note in self.memory.agent_notes()}
        blocks, used = [], 0
        for doc_id in ids:
            note = notes.get(str(doc_id))
            if not note: continue
            text = self.memory.exact_text(doc_id).strip()
            if not text: continue
            room = max_chars - used
            if room <= 0: break
            text = text[:room]; used += len(text)
            blocks.append(f"### {note.get('title') or 'Memory note'}\n\n{text}")
        return '\n\n'.join(blocks)

    def restore_remembered_agent_state(self):
        "Restore the newest compatible charter without starting a model or hiding the source."
        if any(str(layer.get('text') or '').strip() for layer in self.agent_state_layers.values()):
            return False
        roots = {str(Path(root).resolve()) for root in self.fs.roots}
        if not roots: return False
        states = self.memory.agent_states()
        compatible = []
        for state in states:
            saved_roots = {str(Path(root).expanduser().resolve())
                           for root in ((state.get('meta') or {}).get('agent') or {}).get('roots', [])}
            if saved_roots == roots or not saved_roots: compatible.append(state)
        if not compatible: return False
        text = self.memory.agent_state_text(compatible[0]['id']).strip()
        if not text: return False
        self.agent_state = text
        self.agent_state_layers['task'] = {'text': text, 'enabled': True, 'source': 'memory'}
        return True

    def state(self):
        def saved_tab(t):
            d = t.dict(); d.pop('running', None); return d
        return {'version': 2, 'roots': [str(r) for r in self.fs.roots],
                'tabs': [saved_tab(t) for t in self.tabs if not t.scratch],
                'active': self.active, 'model': self.model, 'inline_model': self.inline_model,
                'completion_model': self.completion_model,
                'local_multimodal': self.local_multimodal, 'agent_state': self.agent_state,
                'agent_state_layers': self.agent_state_layers,
                'agent_memory_selection': self.agent_memory_selection,
                'compact_auto': self.compact_auto, 'compact_strategy': self.compact_strategy,
                'saved': time.time()}

    def save(self, path=None):
        "Persist folders and tabs (never kernels -- their namespaces do not survive the process)."
        p = Path(path or getattr(self, '_state_path', None) or ws_path())
        try: p.write_json(self.state())
        except OSError: pass
        return p

    @classmethod
    def load(cls, path=None, port=8000, agent='restricted', kernel='ipykernel',
             model=None, inline_model=None, completion_model=None, local_multimodal=None,
             approvals='ask', agent_scope='overlay', python=None, transport='direct', gateway=None):
        "Restore a saved workspace, dropping any folder or file that has since gone away."
        p = Path(path or ws_path())
        try: d = p.read_json()
        except Exception: d = {}
        ws = cls(port=port, agent=agent, kernel=kernel,
                 model=model if model is not None else d.get('model'),
                 inline_model=(inline_model if inline_model is not None else
                               d.get('inline_model') or 'gpt-mini'),
                 completion_model=(completion_model if completion_model is not None else
                                   d.get('completion_model') or 'gpt-4.1'),
                 local_multimodal=(local_multimodal if local_multimodal is not None else
                                   d.get('local_multimodal', False)),
                 approvals=approvals, agent_scope=agent_scope, python=python,
                 transport=transport, gateway=gateway)
        ws._state_path = p
        ws.compact_auto = bool(d.get('compact_auto', True))
        ws.compact_strategy = str(d.get('compact_strategy') or 'surgical')
        ws.agent_state = str(d.get('agent_state') or '')
        saved_selection = d.get('agent_memory_selection')
        if isinstance(saved_selection, dict):
            for target in ws.agent_memory_selection:
                values = saved_selection.get(target, [])
                if isinstance(values, list): ws.agent_memory_selection[target] = list(dict.fromkeys(map(str, values)))
        saved_layers = d.get('agent_state_layers')
        if isinstance(saved_layers, dict):
            for name, layer in saved_layers.items():
                if name in ws.agent_state_layers and isinstance(layer, dict):
                    ws.agent_state_layers[name].update(text=str(layer.get('text') or ''),
                                                       enabled=bool(layer.get('enabled', True)),
                                                       source=str(layer.get('source') or 'workspace'))
        if ws.agent_state and not any(str(layer.get('text') or '').strip()
                                      for layer in ws.agent_state_layers.values()):
            ws.agent_state_layers['task']['text'] = ws.agent_state
        for r in d.get('roots', []):
            try: ws.add_root(r)
            except Exception: pass
        for t in d.get('tabs', []):
            try:
                tab = ws.open(t['path'])
                # Before workspace v2, False was merely the global default and did not
                # express an intentional shared attachment. Migrate notebooks to private.
                if d.get('version', 0) >= 2 and 'private_kernel' in t:
                    tab.private_kernel = bool(t['private_kernel'])
                tab.cwd = str(t.get('cwd') or '')
            except Exception: pass
        ws.active = min(d.get('active', 0), max(0, len(ws.tabs)-1))
        if ws.restore_remembered_agent_state(): ws.save()
        return ws
