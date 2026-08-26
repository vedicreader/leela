"Open folders, open tabs, and which kernel each tab talks to."

from __future__ import annotations
import asyncio, atexit, hashlib, json, os, threading, time
from dataclasses import dataclass
from fastcore.all import Path, L, atomic_save, first, ifnone

from . import Dictable, leela_cfg
from .agent.agent import Completer
from .blocks.agent.ai import Assistant, notebook_approvals
from .blocks.runtime.devserver import DevServers
from .blocks.fs.fs import Sandbox, Unsafe, lang_for, is_texty
from .blocks.runtime.kernels import KernelPool
from .blocks.nb.nb import Notebook, media_outputs
from .blocks.research.research import Research
from .blocks.runs.runs import Run, Runs
from .blocks.search.search import Search
from .blocks.term.term import Terminals

__all__ = ['Tab', 'Workspace', 'ws_path']

class _EnvClient:
    "Read-only access to some *other* process's inspector, in the shape `Kernel.api` has."
    def __init__(self, base, name=''):
        self.base, self.name = base, name
        self.alive, self.boot_error, self.pid = True, None, None
        self.kernel_kind = 'env'
    @property
    def token(self):
        "The owner token this inspector wrote next to its registry entry, if it armed one."
        from .core.inspectors import reg_dir
        try: return (reg_dir()/f"token-{self.base.rsplit(':', 1)[-1]}").read_text().strip() or None
        except Exception: return None
    @property
    def headers(self):
        "The owner token, as the header dhrishti's token-gated surface wants it."
        return {'X-Dhrishti-Token': t} if (t := self.token) else {}
    async def api(self, path, params=None, timeout=15):
        import httpx2 as httpx
        try:
            async with httpx.AsyncClient(base_url=self.base, timeout=timeout, headers=self.headers) as c:
                r = await c.get(path, params=params or {})
                r.raise_for_status()
                return r.json()
        except Exception:
            return None
    def api_sync(self, path, params=None, timeout=15):
        import httpx2 as httpx
        try:
            with httpx.Client(base_url=self.base, timeout=timeout, headers=self.headers) as c:
                r = c.get(path, params=params or {}); r.raise_for_status(); return r.json()
        except Exception: return None
    async def names(self, scope='live', profile='full'):
        r = await self.api('/api/rows', {'profile': profile, 'sort': 'name'})
        return L(n.get('name', '') for g in (r or {}).get('groups', []) for n in g.get('nodes', []))
    async def execute(self, code, on_output=None, **kw):
        "Execute through the watched runtime's owner HTTP surface."
        from .blocks.runtime.kernels import ExecOutcome
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

#: What a saved session is, as against the preferences saved beside it. Only a workspace that has
#: read or opened one writes them: a bare `Workspace` recording a model choice used to blank them.
SESSION_KEYS = ('roots', 'tabs', 'active', 'active_root')

TOOL_RANGE, STEP_RANGE = (20, 400), (8, 80)

def budget_value(v, lo, hi):
    "`auto`, or a number inside `lo..hi`. Anything else is `auto`, never a silent clamp to a bound."
    if isinstance(v, bool) or v is None: return 'auto'
    if isinstance(v, str) and v.strip().lower() == 'auto': return 'auto'
    try: n = int(str(v).strip())
    except (TypeError, ValueError): return 'auto'
    return n if lo <= n <= hi else 'auto'

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico', '.bmp'}
AUDIO_EXTS = {'.wav', '.mp3', '.m4a', '.ogg', '.flac', '.aac'}
VIDEO_EXTS = {'.mp4', '.webm', '.ogv', '.mov'}

@dataclass
class Tab(Dictable):
    "One open editor tab."
    path: str
    kind: str = 'text'
    title: str = ''
    dirty: bool = False
    private_kernel: bool | None = None
    scratch: bool = False
    running: int = 0
    cwd: str = ''
    ref: str = ''
    def __post_init__(self):
        if not self.title: self.title = Path(self.path).name or 'untitled'
        if self.path.endswith('.ipynb'): self.kind = 'notebook'
        elif self.path.lower().endswith('.pdf'): self.kind = 'pdf'
        elif Path(self.path).suffix.lower() in IMAGE_EXTS: self.kind = 'image'
        elif Path(self.path).suffix.lower() in AUDIO_EXTS: self.kind = 'audio'
        elif Path(self.path).suffix.lower() in VIDEO_EXTS: self.kind = 'video'
        if self.private_kernel is None: self.private_kernel = self.kind == 'notebook'
    @property
    def lang(self): return 'python' if self.kind == 'notebook' else lang_for(self.path)

class Workspace:
    "The IDE's session: open folders, open tabs, and the kernels behind them."
    def __init__(self, roots=(), port=8000, agent='restricted', dev_port=9000, kernel='ipykernel',
                 model=None,
                 inline_model=None,
                 completion_model=None,
                 local_multimodal=False,
                 kernels_auto_manage=False,
                 litert_backend='',
                 approvals='ask',
                 agent_scope='overlay',
                 python=None,
                 transport='direct', gateway=None, cdp_port=9223):
        self.fs = Sandbox(roots)
        self._owns_session = bool(self.fs.roots)
        self._swept = set()
        from .blocks.fs.watch import Watcher
        from .blocks.git.git import wire_env
        wire_env()
        self.fs_watch = Watcher(self.fs)
        from .blocks.runtime.kernels import project_python
        runtime_python = python or project_python(self.fs.roots)
        self.pool = KernelPool(port=port, default_kernel=kernel, default_python=runtime_python,
                               transport=transport, gateway=gateway)
        self.dev = DevServers(port=dev_port)
        from .core.ports import build as build_provider
        from .blocks.memory.memory import memory_shelf
        self.search = build_provider('search', self.fs)
        root = first(self.fs.roots)
        self.memory = build_provider('memory', shelf=memory_shelf(root),
                                     kosha=getattr(self.search, '_kosha', None))
        from .blocks.memory.vaults import Vaults
        self.vaults = Vaults(shelf=memory_shelf(root), own=self.memory)
        self.research = Research(self.fs, memory=self.memory)
        from .blocks.browser.browser import Browser
        self.browser = Browser(port=cdp_port)
        self._runs = None
        self.history = self.journal = self._timeline_path = None
        self._journal_key = ''
        self.rebind_journal()
        self._stop_backups = None
        self._down = False
        self._loop = None
        self._history_stamps = {}
        self._timeline_lock = threading.RLock()
        from .blocks.vault.clip import register_all
        from .blocks.vault.jobs import Jobs
        from .blocks.vault.news import Feeds
        self.feeds = Feeds()
        self.jobs = Jobs(leela_cfg/'jobs'/f'{self._journal_key}.db', memory=self.memory)
        register_all(self.jobs, self.memory, search=self.search, cwd=root, feeds=self.feeds)
        self._lsp = None
        self.env_base = None
        self.terms = Terminals(cwd=first(self.fs.roots))
        self.agent = agent
        self.kernel_kind = kernel
        self.agent_scope = agent_scope
        self.tabs = L()
        self.active = 0
        self._untitled = 0
        self._ai = self._inline_ai = self._completer = self._turn_runner = self._threads = None
        from .agent.core import env as model_env
        self.model = model
        self.inline_model = inline_model or model_env('MODEL_INLINE') or 'gpt-mini'
        self.completion_model = completion_model or model_env('MODEL_COMPLETION') or 'gpt-4.1'
        self.local_multimodal = bool(local_multimodal)
        self.kernels_auto_manage = bool(kernels_auto_manage)
        self.litert_backend = str(litert_backend or '').lower()
        if self.litert_backend: os.environ['LEELA_LITERT_BACKEND'] = self.litert_backend
        self.compact_auto, self.compact_strategy = True, 'surgical'
        self.tool_budget, self.step_budget = 'auto', 'auto'
        self.allow_workspace_repo_writes = False
        self.agent_read_outside = False     # reads may leave the open folders; writes never do
        self.subagent_writes = False        # delegated sub-agents may only read unless this is on
        self.active_root = None
        self.agent_state = ''
        self.agent_state_layers = {name: {'text': '', 'enabled': True, 'source': 'workspace'} for name in
                                   ('organization', 'project', 'task', 'preferences', 'branch', 'ephemeral')}
        self.agent_memory_selection = {'agent': [], 'inline': [], 'completion': []}
        self.job_models = {}                # harness job -> model, for the jobs without a field
        self.screen = (None, '', '')
        self.on_note = None
        self._approval_target, self.approvals_mode = None, approvals
        self._notebook_approvals = notebook_approvals(lambda: self._approval_target, mode=approvals)
        self._stop_notebook_approvals = self._notebook_approvals.listen()
    def sync_agent_routing(self, ai=None):
        "Apply saved agent-job choices to a live assistant."
        ai = ai or self.ai
        routes = {'completion': self.completion_model, **(self.job_models or {})}
        for job, name in routes.items():
            if name and ai.routing.name_for(job) != name: ai.set_model(name, job=job)
        return ai

    @property
    def threads(self):
        if self._threads is None:
            from .blocks.agent.threads import Threads
            self._threads = Threads(self)
        return self._threads
    @property
    def ai(self):
        "The active agent-pane assistant. Resolve on every access because the thread may change."
        return self.threads.active.ai
    @property
    def approvals(self): return self.threads.active.approvals
    @property
    def turn_runner(self):
        "The active thread's runner, or a stub assigned before any thread was built."
        if self._threads is None and self._turn_runner is not None: return self._turn_runner
        return self.threads.active.runner
    def start_backups(self):
        """Begin the chosen cadence, and take one now if it is already due.

        Not in `__init__`: a test that builds a hundred workspaces would start a hundred threads.
        """
        from .core.backups import backup_cadence, schedule_backups
        if self._stop_backups is not None: return self._stop_backups
        self._stop_backups = schedule_backups(backup_cadence())
        return self._stop_backups

    def guard_history(self, reason='before an overwrite'):
        "A copy of the conversation log before something replaces it. Cheap, and never raises."
        from .core.backups import guard
        path = getattr(self._ai, 'history_path', None) if self._ai is not None else None
        try: return guard(path, reason=reason) if path is not None else None
        except Exception: return None

    def _timelines(self):
        with self._timeline_lock:
            try: return self._timeline_path.read_json()
            except Exception: return {}
    def _timeline_key(self, thread_id, turn_id): return f'{thread_id}:{turn_id}'
    def timeline_parts(self, thread_id, turn_id):
        return list(self._timelines().get(self._timeline_key(thread_id, turn_id), ()))
    TIMELINE_KEEP = 200          # turns retained for restart and resync, oldest written first out

    def save_timeline(self, thread_id, turn_id, parts):
        "Atomically retain one thread turn's ordered browser events for restart and resync."
        key = self._timeline_key(thread_id, turn_id)
        with self._timeline_lock:
            rows = self._timelines(); rows.pop(key, None); rows[key] = list(parts)
            for old in list(rows)[:-self.TIMELINE_KEEP]: rows.pop(old, None)
            self._timeline_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._timeline_path.with_name(f'.{self._timeline_path.name}.{os.getpid()}.tmp')
            try:
                tmp.write_json(rows); os.replace(tmp, self._timeline_path)
            finally:
                if tmp.exists(): tmp.unlink()
        return rows[key]
    def history_stamp(self, ai=None):
        "What identifies the conversation log as it is now: cheap, and enough to notice a write."
        ai = ai or self.ai
        try:
            p = Path(ai.history_path); st = p.stat()
            return f'{p}:{st.st_mtime_ns}:{st.st_size}'
        except Exception: return ''
    def fresh_history(self, ai=None):
        """Reread the conversation log, but only when it has actually changed.

        Parsing is linear in its size, which reaches 60MB once Leela and the CLI share one. A stat
        tells an unchanged log from a written one.
        """
        ai = ai or self.ai
        stamp = self.history_stamp(ai)
        if stamp and self._history_stamps.get(id(ai)) == stamp: return False
        ai.refresh_history()
        self._history_stamps[id(ai)] = stamp
        return True
    def with_timelines(self, turns):
        rows = self._timelines()
        out = []
        for turn in turns:
            key = self._timeline_key(turn.get('session', ''), turn.get('turn_id', ''))
            out.append({**turn, **({'timeline': rows[key]} if key in rows else {})})
        return out
    @property
    def inline_ai(self):
        "Prompt cells use their own smaller model and conversation, never the agent pane's context."
        if self._inline_ai is None:
            from .agent.core import env
            self._inline_ai = Assistant(self, model=self.inline_model or env('MODEL_INLINE'), surface='inline',
                                        local_multimodal=self.local_multimodal, approvals=self._notebook_approvals,
                                        on_compact=self._compacted, history_name='inline')
            self._notebook_approvals.host = self._inline_ai.host
        return self._inline_ai
    def _compacted(self, summary):
        "Write a compaction summary into the notebook the conversation is happening in."
        t = self._approval_target
        if not t: return
        nb, i = t
        from .blocks.nb.nb import Cell
        c = Cell(source=f'**🗜 context compacted**\n\n{summary}', cell_type='markdown')
        c.approval = {'kind': 'compaction'}
        nb.insert(min(i + 1, len(nb)), c)
        nb.dirty = True
    @property
    def completer(self):
        "Inline completion, on the assistant's engine. It loads and is missing with the assistant."
        if self._completer is None: self._completer = Completer(self.ai)
        return self._completer
    def _rebrief_agents(self):
        "Tell any live assistant that the open folders changed."
        for a in (self._ai, self._inline_ai):
            if a is not None:
                try: a.refresh()
                except Exception: pass
    def journal_key(self):
        "Which undo history these folders own. The empty set is its own bucket, not everyone's."
        roots = [str(r) for r in self.fs.roots]
        return hashlib.sha256('\0'.join(roots).encode()).hexdigest()[:16] if roots else 'no-folder'
    def rebind_journal(self):
        """Point the journal and the history at the folders open now."""
        key = self.journal_key()
        if key == self._journal_key: return self.journal
        from .core.session import FileHistory, OperationJournal, Trash
        self._journal_key = key
        self.history = FileHistory(leela_cfg/'history'/key)
        self.trash = Trash(leela_cfg/'trash'/key)
        self.journal = OperationJournal(leela_cfg/'journals'/f'{key}.json', self.fs,
                                        history=self.history, trash=self.trash)
        self.history.pinned = self.journal.blobs   # an open operation's bodies survive pruning
        self._timeline_path = leela_cfg/'timelines'/f'{key}.json'
        return self.journal
    def retarget(self, tab, old, new):
        "Point one open tab at a path that has just moved, keeping its place in the strip."
        rest = Path(tab.path).relative_to(Path(old)) if tab.path != str(old) else None
        tab.path = str(Path(new)/rest) if rest is not None else str(new)
        tab.title = Path(tab.path).name or tab.title
        return tab
    def add_root(self, p):
        r = self.fs.add_root(p)
        self._owns_session = True
        self.rebind_journal()
        if not self.pool.kernels and self.pool.default_python is None:
            from .blocks.runtime.kernels import project_python
            if (py := project_python([r])): self.pool.choose(python=py)
        self._rebrief_agents()
        self.fs_watch.start(restart=True)
        return r
    def drop_root(self, p):
        "Close a folder, and every tab that lived inside it."
        r = self.fs.drop_root(p)
        self._owns_session = True   # closing the last folder is a session to save, not an empty one
        # The folder the project surfaces were about is gone, so the choice is stale. `project_root`
        # guards against it, but anything reading `active_root` directly would follow it out.
        if self.active_root and Path(self.active_root) not in self.fs.roots: self.active_root = ''
        self.rebind_journal()
        self.tabs = self.tabs.filter(lambda t: not (t.path and Path(t.path).is_relative_to(r)))
        self.active = min(self.active, max(0, len(self.tabs)-1))
        self._rebrief_agents()
        self.fs_watch.start(restart=True)
        return r
    @property
    def tab(self): return self.tabs[self.active] if self.tabs else None
    def find(self, path):
        p = str(Path(path).expanduser().resolve())
        return first(i for i, t in enumerate(self.tabs) if t.path == p)
    def activate_root(self, path):
        "Point the project-scoped surfaces at one of the open folders."
        p = self.fs._check(path, must_exist=True)
        if not p.is_dir(): p = p.parent
        root = self.fs.root_of(p)
        self.active_root = root
        self._rebrief_agents()
        return root
    @property
    def project_root(self):
        "The folder the project surfaces are about: the chosen one, else the first open folder."
        if self.active_root and self.active_root in self.fs.roots: return self.active_root
        return first(self.fs.roots)
    @property
    def runs(self):
        "The saved runs of the folder the project surfaces are about. That is not always the first opened."
        root = self.project_root
        if self._runs is None or self._runs.root != root: self._runs = Runs(root)
        return self._runs
    def _add_tab(self, t):
        "Append a tab, focus it, and point the variable panel back at its kernel."
        self.tabs.append(t)
        self._owns_session = True
        self.active = len(self.tabs) - 1
        self.watch_env(None)
        return t
    def open(self, path, kind=None):
        "Open a file, focusing it if it is already open. Refuses anything outside the open folders."
        p = self.fs._check(path, must_exist=True)
        if not is_texty(p) and p.suffix.lower() not in ('.ipynb', '.pdf', *IMAGE_EXTS):
            raise Unsafe(f'{p.name} is not a text file')
        try: self.active_root = self.fs.root_of(p)
        except Unsafe: pass
        if (i := self.find(p)) is not None:
            self.active = i
            self.watch_env(None)
            return self.tabs[i]
        return self._add_tab(Tab(path=str(p), kind=ifnone(kind, 'notebook' if p.suffix == '.ipynb' else
                                                                'pdf' if p.suffix.lower() == '.pdf' else
                                                                'image' if p.suffix.lower() in IMAGE_EXTS else 'text')))
    def open_vault_doc(self, doc_id, shelf='', vault='', title=''):
        "Open a vault document as a tab. It has no path: the client reads it back through `/vault/doc`."
        ref = f'{vault or self.vaults.active.name}|{shelf}|{doc_id}'
        if (i := first(i for i, t in enumerate(self.tabs) if t.ref == ref)) is not None:
            self.active = i
            return self.tabs[i]
        return self._add_tab(Tab(path='', kind='vault', ref=ref, scratch=True,
                                 title=title or doc_id, private_kernel=False))
    def open_vault_workbench(self, view='browse'):
        "Open the vault workbench as a tab. One is enough: it is a place, not a document."
        if (i := first(i for i, t in enumerate(self.tabs) if t.kind == 'vaultwb')) is not None:
            self.tabs[i].ref = view
            self.active = i
            return self.tabs[i]
        return self._add_tab(Tab(path='', kind='vaultwb', ref=view, scratch=True, title='vault',
                                 private_kernel=False))
    def note_vault_view(self, view):
        "Which section the workbench is showing. Reopening the tab is not starting it over."
        t = first(t for t in self.tabs if t.kind == 'vaultwb')
        if t is None or not view or t.ref == view: return None
        t.ref = view
        self.save()
        return t
    def open_web(self, target, title=''):
        "Open a CDP target as a tab, focusing it if that page is already cast."
        if (i := first(i for i, t in enumerate(self.tabs)
                       if t.kind == 'web' and t.ref == target)) is not None:
            self.active = i
            return self.tabs[i]
        return self._add_tab(Tab(path='', kind='web', ref=target, scratch=True,
                                 title=title or 'page', private_kernel=False))
    def new_scratch(self, kind='notebook'):
        "An unsaved buffer, opened when there is nothing to open yet."
        self._untitled += 1
        return self._add_tab(Tab(path='', kind=kind, title=f'untitled-{self._untitled}', scratch=True))
    def create_document(self, path):
        "Create a file in its native empty shape."
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
    def move_tab(self, i, j):
        "Drag a tab to a new position, keeping the same document active afterwards."
        if not (0 <= i < len(self.tabs)): return self.tab
        j = max(0, min(int(j), len(self.tabs) - 1))
        if i == j: return self.tab
        held = self.tabs[self.active] if 0 <= self.active < len(self.tabs) else None
        self.tabs.insert(j, self.tabs.pop(i))
        if held is not None: self.active = self.tabs.index(held)
        return self.tab
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
    def text_at(self, ref):
        "One file as a single diffable document, or None when it cannot be read."
        try: p = self.fs._check(ref)
        except Exception: return None
        if not p.exists(): return ''
        try: return Notebook.load(p).source_text() if p.suffix == '.ipynb' else self.fs.read(p)
        except Exception: return None
    def disk_text(self, tab=None):
        "A tab's file as it is on disk, in the shape its buffer is compared against; None when unsaved."
        t = tab or self.tab
        return None if (t is None or not t.path) else self.text_at(t.path)
    def _agent_context(self, nb, i, prompt, agent=None):
        agent = agent or self.ai
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
        "The name a prompt asked to be left behind. People write it `as \\`df_norm\\`.`, backticks and all."
        import re
        m = re.search(r'\bas\s+[`\'"]?([A-Za-z_]\w*)[`\'"]?[.!]?\s*$', (prompt or '').strip())
        return m.group(1) if m else ''
    def _name_exists(self, name, agent=None, owner=False):
        """Whether `name` is bound: in the agent's merged view, or in the user's own namespace.

        The merged view is what the agent sees. Only the user's own namespace answers the question
        a prompt cell asks, which is whether the next cell can use the name.
        """
        if not name: return True
        h = (agent or self.inline_ai).host
        try:
            if owner: return name in h.owner_names()
            import re
            return bool(re.search(rf'(?m)^{re.escape(name)}\s*:', h.list_vars()))
        except Exception: return True
    def _land(self, prompt, agent=None):
        "Give the user the name their prompt asked to be left behind, if the agent bound it."
        name = self._requested_name(prompt)
        if not name: return ''
        a = agent or self.inline_ai
        try: out = a.host.promote_var(name)
        except Exception: return ''
        if out.startswith(name): a.host.note(out)
        return out
    def _action_retry(self, prompt, agent=None):
        name = self._requested_name(prompt)
        if not name or self._name_exists(name, agent, owner=True): return ''
        return (f'The action is incomplete: `{name}` is not in the user\'s namespace. '
                'Do not explain or plan, and do not install anything: the session refuses pip and '
                'shell escapes, so use only what the notebook has already imported. Call '
                f'`run_python` with just the transformation asked for, binding it to `{name}`, then '
                f'call `promote_var` with `{name}`. Answer briefly.')
    def ask_cell(self, nb, i):
        "Answer the prompt cell at `i`, with the notebook above it as its context."
        c = nb[i]
        if not c.is_prompt: raise ValueError(f'cell {i} is a {c.cell_type} cell, not a prompt')
        a = self.inline_ai
        png, screen, _ = self.take_screen()
        self._approval_target = (nb, i)
        started = time.perf_counter()
        try:
            text = a.ask_with(c.source, context=self._agent_context(nb, i, c.source, a),
                              screen=screen, image=png, context_path=nb.path)
            for attempt in range(3):
                self._land(c.source, a)
                retry = self._action_retry(c.source, a)
                if not retry or attempt == 2: break
                text += '\n\n' + a.ask(retry)
        finally:
            self._approval_target = None
            c.execution_ms = (time.perf_counter() - started) * 1000
        trail = a.turn_md()
        c.reply = f'{text}\n\n{trail}' if trail else text
        c.calls = a.activity.rows(mark=a.activity._mark)
        c.usage = a.turn_use.dict()
        c.outputs = media_outputs(a.turn_media)
        nb.dirty = True
        return c
    def folder_manifest(self, ref, limit=300):
        "What is in a folder, as a listing rather than its contents."
        root = self.fs._check(ref, must_exist=True)
        if not root.is_dir(): raise ValueError(f'not a folder: {ref}')
        found = sorted(self.fs.walk(root, limit=limit * 4))
        rows = []
        for f in found[:limit]:
            try: size = f.stat().st_size
            except OSError: continue
            rows.append(f'  {f.relative_to(root)}\t{size}\t{lang_for(str(f)) or ""}'.rstrip())
        shown = len(found)
        more = f'\n  [{shown - limit} more files not listed]' if shown > limit else ''
        return (f'<attached-folder path="{root}" files="{shown}">\n'
                f'  name\tbytes\tlanguage\n' + '\n'.join(rows) + more + '\n</attached-folder>')
    def _selection_context(self, sel, max_text=60_000):
        "One highlighted range, as the editor had it."
        path = str(sel.get('path') or 'untitled')
        a, b = int(sel.get('from') or 1), int(sel.get('to') or 1)
        body = str(sel.get('text') or '')[:max_text]
        return f'<attached-selection path="{path}" lines="{a}-{b}">\n{body}\n</attached-selection>'
    def _vault_context(self, ref, max_text=60_000):
        "One vault document or section, as grounded text the turn can quote and cite."
        doc, shelf, vault = str(ref.get('doc') or ''), str(ref.get('shelf') or ''), str(ref.get('vault') or '')
        m = self.vaults.memory(vault or None)
        # A section id carries its document's id before the `#`. `shelf_text` reads only the part
        # that was pointed at.
        row = m.document(doc.split('#')[0], shelf or None)
        title = ref.get('title') or row.get('title') or doc
        body = m.shelf_text(doc, shelf or None, max_text)
        if not body: raise ValueError(f'{title}: nothing readable in the vault')
        src = f' source="{row.get("source")}"' if row.get('source') else ''
        return (f'<attached-document vault="{vault or self.vaults.active.name}" shelf="{shelf or "main"}" '
                f'title="{title}"{src}>\n{body}\n</attached-document>')

    def _attachment_context(self, refs=(), spec=None, max_file=120_000, max_total=300_000):
        "Workspace files selected with @, as grounded text context and multimodal content parts."
        from ramabana.cli import MEDIA, Attachment, media_note, media_parts
        text, images, sound, used = [], [], [], 0
        image_exts = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}
        audio_exts = {ext for ext, (kind, _) in MEDIA.items() if kind == 'audio'}
        seen, items = set(), []
        for ref in (refs or ()):
            key = json.dumps(ref, sort_keys=True) if isinstance(ref, dict) else str(ref).strip()
            if not key or key in seen: continue
            seen.add(key); items.append(ref)
        for ref in items:
            if isinstance(ref, dict) and ref.get('kind') == 'selection':
                text.append(self._selection_context(ref))
                continue
            if isinstance(ref, dict) and ref.get('kind') == 'vault':
                text.append(self._vault_context(ref))
                continue
            p = self.fs._check(ref, must_exist=True)
            if p.is_dir():
                text.append(self.folder_manifest(p))
                continue
            if not p.is_file(): raise ValueError(f'attachment is not a file: {ref}')
            if p.suffix.lower() in image_exts:
                images.append(p.read_bytes())
                continue
            if p.suffix.lower() in audio_exts:
                sound.append(Attachment(p))
                continue
            raw = p.read_bytes()[:max_file]
            body = raw.decode('utf-8', 'replace')
            remaining = max_total - used
            if remaining <= 0: break
            body = body[:remaining]; used += len(body)
            clipped = '\n[attachment clipped]' if len(raw) >= max_file else ''
            text.append(f'<attached-file path="{p}">\n{body}{clipped}\n</attached-file>')
        # sound goes out as content parts where the model can hear it, and by path where it cannot
        if not sound: return '\n\n'.join(text), images
        text.append(media_note(sound, spec).strip())
        return '\n\n'.join(text), images + media_parts(sound, spec)
    def _grounding(self, attachments, context):
        "`(context, screen, media)` for one prompt-bar turn: pending capture plus @-selected files."
        png, screen, _ = self.take_screen()
        attached, media = self._attachment_context(attachments, self.ai.model)
        return ('\n\n'.join(x for x in (context, attached) if x), screen,
                ([png] if png else []) + media)
    def ask(self, prompt, attachments=(), context='', context_path=''):
        "One turn from a prompt bar, grounded by the open notebook and @-selected files."
        self.sync_agent_routing()
        context, screen, media = self._grounding(attachments, context)
        return self.ai.ask_with(prompt, context=context, screen=screen, image=media or None,
                                context_path=context_path)
    def prepare_turn(self, attachments=(), context=''):
        "Capture and validate one prompt-bar turn before the server accepts it."
        self.sync_agent_routing()
        return self._grounding(attachments, context)
    def ask_stream(self, prompt, attachments=(), reasoning=None, context='', context_path='',
                   grounding=None, on_registered=None, ai=None):
        """The same turn, yielding markdown as it arrives.

        `ai` pins the conversation the turn belongs to, against a thread switch mid-turn. It
        defaults to the active one."""
        ai = ai or self.ai
        self.sync_agent_routing(ai)
        context, screen, media = grounding or self._grounding(attachments, context)
        kw = {'reasoning_effort': reasoning} if reasoning and not ai.model.local else {}
        return ai.stream_with(prompt, context=context, screen=screen, image=media or None,
                              context_path=context_path, on_registered=on_registered, **kw)
    def ask_cell_stream(self, nb, i):
        "Answer the prompt cell at `i`, filling the cell in as the answer arrives."
        c = nb[i]
        if not c.is_prompt: raise ValueError(f'cell {i} is a {c.cell_type} cell, not a prompt')
        a = self.inline_ai
        png, screen, _ = self.take_screen()
        c.reply, c.calls, c.usage, c.outputs = '', [], {}, []
        nb.dirty = True
        self._approval_target = (nb, i)
        started = time.perf_counter()
        try:
            context = self._agent_context(nb, i, c.source, a)
            prompts = [a.stream_with(c.source, context=context, screen=screen, image=png,
                                     context_path=nb.path)]
            for attempt in range(3):
                for chunk in prompts[-1]:
                    c.reply += chunk
                    c.calls = a.activity.rows(mark=a.activity._mark)
                    yield chunk
                self._land(c.source, a)
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
            c.outputs = media_outputs(a.turn_media)
            nb.dirty = True
    @property
    def pending_approval(self):
        "The write waiting for a person, or None. What the web frontend polls during a turn."
        return self.approvals.pending
    def answer_approval(self, id, ok, note='', session=False, tool=None, args=None):
        "Resolve one checkpoint, including an optional user rewrite of the proposed call."
        return self.approvals.answer(id, ok, note, session=session, tool=tool, args=args)
    def put_screen(self, png=None, text='', note=''):
        "Hold a capture for the next question. One slot, because the useful capture is the latest."
        self.screen = (png or None, text or '', note or '')
        return self.screen
    def take_screen(self):
        "Consume the pending capture as `(png, text, note)`."
        s, self.screen = self.screen, (None, '', '')
        return s
    def save_screen(self, svg, name=None):
        "Write a captured screen into leela's own config dir, not the project."
        d = leela_cfg/'screens'
        d.mkdir(parents=True, exist_ok=True)
        p = d/(name or f"screen-{time.strftime('%Y%m%d-%H%M%S')}.svg")
        p.write_text(svg)
        return p
    def cwd_for(self, tab=None):
        "The tab's working directory: override, notebook directory, then project root."
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
                from .blocks.git.git import repo_root
                return repo_root(Path(t.path).parent) or root
            except Unsafe: pass
        if (root := self.project_root) is not None:
            from .blocks.git.git import repo_root
            return repo_root(root) or root
        return None
    def set_cwd(self, path=None, tab=None):
        "Set a per-tab cwd, or clear it with an empty path to return to auto mode."
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
        "Which kernel a tab uses. Notebooks are private by default. Source files share one per folder."
        t = tab or self.tab
        fallback = str(self.project_root) if self.project_root is not None else 'default'
        if t is None: return fallback
        if t.private_kernel: return f'tab:{t.path or t.title}'
        if not t.path: return fallback
        try: return str(self.fs.root_of(t.path))
        except Unsafe: return 'default'
    async def kernel(self, tab=None):
        "The live kernel for a tab, started in its folder's interpreter."
        t = tab or self.tab
        key, cwd = self.kernel_key(t), self.cwd_for(t)
        from .blocks.runtime.kernels import python_for
        try: name = self.fs.root_of(t.path).name if t and t.path else Path(cwd).name
        except Exception: name = Path(cwd).name if cwd else None
        return await self.pool.get(key, cwd=cwd, name=name, agent=self.agent,
                                   python=python_for(cwd, self))
    def kernel_peek(self, tab=None): return self.pool.peek(self.kernel_key(tab))
    def watched_kernel(self):
        "The managed kernel selected in the env picker, if that is what is being watched."
        if not self.env_base: return None
        return first(k for k in self.pool.kernels.values()
                     if k is not None and getattr(k, 'base', None) == self.env_base)
    async def runtime(self, tab=None):
        "Where Run executes: the explicitly picked runtime, else the tab's kernel."
        if (k := self.watched_kernel()) is not None: return k
        if self.env_base and (env := self.inspector(tab)) is not None: return env
        t = tab or self.tab
        k = await self.kernel(t)
        if getattr(k, 'inspect', False) and not getattr(k, 'base', None):
            now, last = time.monotonic(), getattr(k, '_inspector_retry_at', 0.0)
            if now - last >= 10:
                k._inspector_retry_at = now
                k.boot_error = None
                await k.bootstrap()
        desired, current = self.cwd_for(t), getattr(k, 'cwd', None)
        if desired and current and Path(desired).resolve() != Path(current).resolve():
            result = await k.execute(f'import os as __leela_os; __leela_os.chdir({str(desired)!r}); del __leela_os')
            if not result.ok: raise RuntimeError(result.error or f'could not change kernel cwd to {desired}')
            k.cwd = desired
        return k
    def runtime_peek(self, tab=None):
        "The selected runtime without starting a tab kernel."
        return self.watched_kernel() or (self.inspector(tab) if self.env_base else self.kernel_peek(tab))
    def envs(self):
        "Every inspector this IDE could point the variable panel at."
        from .core.inspectors import active
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
        "What the variable panel should be reading: the chosen env, else the tab's kernel."
        if self.env_base:
            e = first(x for x in self.envs() if x['base'] == self.env_base)
            if e is None: self.env_base = None
            else: return _EnvClient(e['base'], e['name'])
        return self.kernel_peek(tab)
    async def run(self, name_or_path, save=False):
        "Start a run configuration, or a file, under a live inspector. Returns the `DevServer`."
        r = self.runs.get(name_or_path)
        if r is None:
            p = self.fs._check(name_or_path, must_exist=True)
            r = self.runs.for_file(p)
            if save: self.runs.add(r)
        root = self.project_root
        cwd = r.resolved_cwd(root) if root else None
        # An app belongs in its own project's environment.
        from .blocks.runtime.kernels import python_for
        return await self.dev.start(r.cmd, cwd=cwd, name=r.name, watch=r.watch,
                                    env=r.resolved_env(root), python=python_for(cwd or root, self))
    def kernel_options(self, tab=None):
        "Everything a kernel picker needs, so neither frontend has to know how kernels work."
        from .blocks.runtime.kernels import KERNELS, find_pythons, ipymini_available, python_for
        t = tab or self.tab
        k = self.kernel_peek(t)
        # What this tab's kernel is actually started under. `Workspace.kernel` resolves it the
        # same way. `default_python` is one interpreter for the whole workspace, taken from the
        # folder opened first.
        cur_py = python_for(self.cwd_for(t), self)
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
            'auto_manage': self.kernels_auto_manage,
        }
    async def set_kernel(self, kind=None, python=False, private=None, tab=None, restart=True):
        "Point a tab at a different kernel, and start it."
        t = tab or self.tab
        old_key = self.kernel_key(t)
        self.watch_env(None)
        self.pool.choose(kernel=kind, python=python)
        if private is not None and t is not None: t.private_kernel = bool(private)
        if not restart: return self.kernel_options(t)
        new_key = self.kernel_key(t)
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
    def initialize_notebook(self, path, nb=None):
        """Make one zero-byte ``.ipynb`` valid JSON before code reads it, and report it when written.

        `nb` is the document already open on that path. Writing it, rather than a fresh blank, keeps
        the cell ids the browser and the server share: a blank invents new ones, and then the next
        save cannot match a single cell and refuses as a conflict.
        """
        if not path: return None
        path = Path(path)
        try:
            if path.stat().st_size: return None
        except OSError: return None
        (nb or Notebook.blank(path)).save(path, sandbox=self.fs)
        return str(path)
    def initialize_empty_notebooks(self, root=None):
        """Turn zero-byte ``.ipynb`` placeholders into valid empty notebooks before code runs.

        Once per root. It is a whole-tree walk, and it ran on every cell of every run to catch a
        placeholder only another tool can leave: Leela's own new notebooks are valid when created.
        """
        root = self.fs._check(root or self.cwd_for(), must_exist=True)
        if str(root) in self._swept: return []
        self._swept.add(str(root))
        return [f for p in self.fs.walk(root) if p.suffix.lower() == '.ipynb'
                and (f := self.initialize_notebook(p))]
    def run_file_code(self, tab=None, src=None):
        "`(code, label)` that runs a tab's file as a script in its kernel, or `(None, why)`."
        from .blocks.runtime.kernels import run_file_src
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
            from .blocks.lsp.lsp import PyrightService
            self._lsp = PyrightService(first(self.fs.roots))
        return self._lsp
    async def shutdown(self):
        "Save the session, then stop every kernel, dev server, terminal and model it started."
        # Once, and each step guarded: what a skipped one leaves behind is a live subprocess.
        if self._down: return
        self._down = True
        def step(fn):
            try: fn()
            except Exception: pass
        step(self.save)
        step(self.terms.close_all)
        step(self.fs_watch.close)
        if self._stop_backups is not None: step(self._stop_backups)
        if self._threads is not None: step(self._threads.shutdown)
        elif self._ai is not None: step(self._ai.close)
        step(self._notebook_approvals.cancel_all)
        step(self._stop_notebook_approvals)
        if self._inline_ai is not None: step(self._inline_ai.close)
        if self._lsp is not None: step(self._lsp.close)
        for coro in (self.dev.stop_all(), self.pool.close_all()):
            try: await coro
            except Exception: pass
    async def opened(self):
        "Remember the loop the kernels, terminals and sockets belong to."
        self._loop = asyncio.get_running_loop()
    def shutdown_now(self, timeout=10):
        "The same teardown from outside the loop, for process exit."
        # Back on the server's loop where there is one: a kernel's client cannot close from another.
        if self._down: return
        if (loop := self._loop) is not None and loop.is_running():
            try: return asyncio.run_coroutine_threadsafe(self.shutdown(), loop).result(timeout)
            except Exception: pass
        try: asyncio.run(self.shutdown())
        except Exception: pass
    def at_exit(self):
        "Tear this workspace down when the interpreter does, however it got there."
        atexit.register(self.shutdown_now); return self
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
        def saved_roots(state):
            return {str(Path(root).expanduser().resolve())
                    for root in ((state.get('meta') or {}).get('agent') or {}).get('roots', [])}
        compatible = [s for s in self.memory.agent_states()
                      if not (saved := saved_roots(s)) or saved == roots]
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
                'local_multimodal': self.local_multimodal, 'litert_backend': self.litert_backend,
                'kernels_auto_manage': self.kernels_auto_manage,
                'agent_state': self.agent_state,
                'agent_state_layers': self.agent_state_layers,
                'agent_memory_selection': self.agent_memory_selection,
                'compact_auto': self.compact_auto, 'compact_strategy': self.compact_strategy,
                'tool_budget': self.tool_budget, 'step_budget': self.step_budget,
                'allow_workspace_repo_writes': self.allow_workspace_repo_writes,
                'agent_read_outside': self.agent_read_outside,
                'subagent_writes': self.subagent_writes,
                'job_models': self.job_models,
                'active_root': str(self.active_root or ''),
                'saved': time.time()}
    def restore_settings(self, d):
        """Everything a saved session holds that is not its folders or its tabs."""
        d = d if isinstance(d, dict) else {}
        self.compact_auto = bool(d.get('compact_auto', True))
        self.compact_strategy = str(d.get('compact_strategy') or 'surgical')
        self.tool_budget = budget_value(d.get('tool_budget'), *TOOL_RANGE)
        self.step_budget = budget_value(d.get('step_budget'), *STEP_RANGE)
        self.allow_workspace_repo_writes = bool(d.get('allow_workspace_repo_writes', False))
        self.agent_read_outside = bool(d.get('agent_read_outside', False))
        self.subagent_writes = bool(d.get('subagent_writes', False))
        self.job_models = {str(k): str(v) for k, v in (d.get('job_models') or {}).items() if v}
        self.agent_state = str(d.get('agent_state') or '')
        saved_selection = d.get('agent_memory_selection')
        if isinstance(saved_selection, dict):
            for target in self.agent_memory_selection:
                values = saved_selection.get(target, [])
                if isinstance(values, list): self.agent_memory_selection[target] = list(dict.fromkeys(map(str, values)))
        saved_layers = d.get('agent_state_layers')
        if isinstance(saved_layers, dict):
            for name, layer in saved_layers.items():
                if name in self.agent_state_layers and isinstance(layer, dict):
                    self.agent_state_layers[name].update(text=str(layer.get('text') or ''),
                                                        enabled=bool(layer.get('enabled', True)),
                                                        source=str(layer.get('source') or 'workspace'))
        if self.agent_state and not any(str(layer.get('text') or '').strip()
                                        for layer in self.agent_state_layers.values()):
            self.agent_state_layers['task']['text'] = self.agent_state
        return self
    def reopen_saved_tabs(self, path=None):
        "Reopen the saved tabs under the folders open now, and count them."
        # Naming a folder is not a request for last session's other projects, but it is still
        # that folder's session.
        try: d = Path(path or getattr(self, '_state_path', None) or ws_path()).read_json()
        except Exception: return 0
        self._owns_session = True
        saved, opened = d.get('tabs') or [], 0
        for t in saved:
            place = str(t.get('path') or '')
            try:
                if not place or not self.fs.covers(Path(place).resolve()): continue
                tab = self.open(place)
                if int(d.get('version', 0)) >= 2 and 'private_kernel' in t:
                    tab.private_kernel = bool(t['private_kernel'])
                tab.cwd = str(t.get('cwd') or '')
                opened += 1
            except Exception: continue
        if opened:
            was = saved[min(max(int(d.get('active', 0)), 0), len(saved) - 1)] or {}
            self.active = ifnone(first(i for i, t in enumerate(self.tabs)
                                       if t.path == str(was.get('path') or '')), 0)
        return opened
    def save(self, path=None, only=None):
        "Persist the session, merged onto what the file already holds; `only` names a partial write."
        p = Path(path or getattr(self, '_state_path', None) or ws_path())
        state = self.state()
        if only: state = {k: v for k, v in state.items() if k in {*only, 'version', 'saved'}}
        elif not self._owns_session:
            for k in SESSION_KEYS: state.pop(k)
        try: held = p.read_json()
        except Exception: held = {}
        try:
            with atomic_save(p, mode='w', encoding='utf-8') as f:
                json.dump({**held, **state} if isinstance(held, dict) else state, f)
        except OSError: pass
        return p
    @classmethod
    def load(cls, path=None, port=8000, agent='restricted', kernel='ipykernel',
             model=None, inline_model=None, completion_model=None, local_multimodal=None,
             kernels_auto_manage=None,
             litert_backend=None,
             approvals='ask', agent_scope='overlay', python=None, transport='direct', gateway=None,
             cdp_port=9223):
        "Restore a saved workspace, dropping any folder or file that has since gone away."
        p = Path(path or ws_path())
        try: d = p.read_json()
        except Exception: d = {}
        ws = cls(port=port, agent=agent, kernel=kernel, cdp_port=cdp_port,
                 model=ifnone(model, d.get('model')),
                 inline_model=ifnone(inline_model, d.get('inline_model') or 'gpt-mini'),
                 completion_model=ifnone(completion_model, d.get('completion_model') or 'gpt-4.1'),
                 local_multimodal=ifnone(local_multimodal, d.get('local_multimodal', False)),
                 kernels_auto_manage=ifnone(kernels_auto_manage, d.get('kernels_auto_manage', False)),
                 litert_backend=ifnone(litert_backend, d.get('litert_backend', '')),
                 approvals=approvals, agent_scope=agent_scope, python=python,
                 transport=transport, gateway=gateway)
        ws._state_path = p
        ws._owns_session = True     # it read this file, so it is the one entitled to rewrite it
        ws.restore_settings(d)
        for r in d.get('roots', []):
            try: ws.add_root(r)
            except Exception: pass
        for t in d.get('tabs', []):
            try:
                tab = ws.open(t['path'])
                if d.get('version', 0) >= 2 and 'private_kernel' in t:
                    tab.private_kernel = bool(t['private_kernel'])
                tab.cwd = str(t.get('cwd') or '')
            except Exception: pass
        ws.active = min(d.get('active', 0), max(0, len(ws.tabs)-1))
        ws.active_root = None
        if saved_root := str(d.get('active_root') or ''):
            try: ws.activate_root(saved_root)
            except Exception: pass
        if ws.restore_remembered_agent_state(): ws.save()
        return ws
