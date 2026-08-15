"Binding a `Workspace` to the agent harness."

from __future__ import annotations
import functools, inspect, json, os, re, threading
from fnmatch import fnmatch
from fastcore.all import L, Path, delegates, first
from ... import errstr, leela_cfg
from ..fs.fs import Unsafe
from ...agent.agent import Agent, Approvals, Ask, _summary, answer_md, ask_md, preview_for
from ...agent.tools import MAX_HITS, MAX_TOOL_CHARS, WRITE_TOOLS as HARNESS_WRITE_TOOLS
from ...agent.tools import DENY, MAX_GREP_HITS, Host, clip, failed, tools_for
from ...agent.spec import SpecHost
from .video import VideoJobs, video_available, video_tools

from ramabana.git import GIT_READ_TOOLS, GIT_TOOLS, GIT_WRITE_TOOLS

FAILED_PREFIXES = ('edit failed', 'write failed', 'could not')
FAST_SEARCH_LEGS = ('symbols', 'rg', 'fts')
WRITE_TOOLS = HARNESS_WRITE_TOOLS | GIT_WRITE_TOOLS

__all__ = ['WorkspaceHost', 'Assistant', 'Interventions', 'ide_tools',
           'notebook_approvals', 'MAX_TOOL_CHARS', 'WRITE_TOOLS']

CONTROL_MODES = frozenset({'autopilot', 'guided', 'directed'})
GUIDED_TOOLS = WRITE_TOOLS | frozenset({'web_search', 'read_url', 'research'})

STATE_TEMPLATE = """# Agent charter

## Role
[What should the agent be responsible for in this workspace?]

## Goal
[The outcome it should move toward.]

## Hard boundaries
- Never claim a tool ran unless its result confirms it.
- Never overwrite user changes or bypass workspace safety checks.
- [Project-specific non-negotiable rules.]

## Routing rules
- Repository behavior or implementation questions → search code, then read the exact source.
- Current external facts → search the web, then read an authoritative source.
- Runtime state → inspect the live namespace before executing a change.
- [When this workspace expects a specialized tool or skill.]

## Tool practices
- Read before editing; use exact paths and current hash addresses.
- Prefer the narrowest tool that produces the requested result.
- Verify writes and execution from tool results, not from intention.
- [Project-specific tool conventions.]

## Verification
- [Tests, checks, screenshots, or evidence required before reporting completion.]

## Progress
### Done
- [Confirmed completed work.]

### In progress
- [Current work.]

### Blocked
- [Open blockers, or none.]

## Key decisions
- [Decision]: [Reason and consequences.]

## Next steps
1. [Next concrete action.]

## Critical context
- [Exact paths, symbols, commands, data, or constraints needed to continue.]

## State maintenance
- Update this state after a milestone, important decision, failed approach, or compaction.
- Remove stale instructions instead of accumulating contradictions.
"""

class Intervention(Ask):
    "A proposed call, including provenance when the person rewrites it before execution."
    def __init__(self, *a, control='guided', **kw):
        super().__init__(*a, **kw)
        self.control = control
        self.original_tool = self.tool
        self.original_args = dict(self.args)
        self.before = self.after = None
        self.revision, self.branch_id, self.parent_action_id = 0, 'main', ''
    @property
    def edited(self): return self.tool != self.original_tool or self.args != self.original_args
    def dict(self):
        return {**super().dict(), 'args': self.args, 'control': self.control, 'edited': self.edited,
            'original_tool': self.original_tool, 'original_args': self.original_args,
            'action_id': self.id, 'revision': self.revision, 'branch_id': self.branch_id,
            'parent_action_id': self.parent_action_id,
            'rollback': self.before is not None and self.after is not None and self.before != self.after}

class Interventions(Approvals):
    "Approval queue extended with editable tool calls and teleprompter control levels."
    def __init__(self, *a, control='guided', **kw):
        super().__init__(*a, **kw)
        self.control = control if control in CONTROL_MODES else 'guided'
        self.run_policy = None
        self.pause_next = False
        self.queued_steer = ''
        self._state_lock = threading.Lock()
        self._execution_meta = []
    def set_control(self, control):
        if control not in CONTROL_MODES: raise ValueError(f'unknown agent control mode {control!r}')
        with self._state_lock: self.control, self.run_policy, self.pause_next = control, None, False
        return control
    def set_run_policy(self, policy='once', count=1):
        "Set a temporary run-through policy for calls after the current checkpoint."
        if policy not in {'once', 'count', 'until_write', 'reads', 'until_failure', 'completion'}:
            raise ValueError(f'unknown run policy {policy!r}')
        count = max(1, min(50, int(count or 1)))
        with self._state_lock:
            self.run_policy = {'kind': policy, 'remaining': count} if policy in {'once', 'count'} else {'kind': policy}
            self.pause_next = False
        return dict(self.run_policy)
    def set_pause_next(self):
        with self._state_lock: self.pause_next, self.run_policy = True, None
    def queue_steer(self, text):
        with self._state_lock:
            self.queued_steer = str(text or '').strip()
            if self.queued_steer: self.run_policy, self.pause_next = {'kind': 'once', 'remaining': 1}, False
        return self.queued_steer
    def consume_steer(self):
        with self._state_lock:
            text, self.queued_steer = self.queued_steer, ''
            if text: self.run_policy = None
        return text
    def observe_result(self, ok):
        "Capture a write result and end an until-failure run after a failed call."
        a = self.history[-1] if self.history else None
        if a is not None and a.before is not None and a.args.get('path'):
            a.after = self.host.text_at(a.args['path'])
        with self._state_lock:
            if not ok and self.run_policy and self.run_policy.get('kind') == 'until_failure':
                self.run_policy, self.pause_next = None, True
    def rollback(self, id):
        "Restore one file call only when no later write has changed its resolved output."
        a = first(reversed(self.history), lambda x: x.id == id)
        if a is None or a.before is None or a.after is None: raise ValueError('that call has no file snapshot')
        path = a.args.get('path')
        if self.host.text_at(path) != a.after: raise ValueError('the file changed after this call; rollback refused')
        self.host.write(path, a.before)
        return path
    def _policy_bypasses(self, name):
        with self._state_lock:
            if self.pause_next:
                self.pause_next = False
                return False
            p = self.run_policy
            if not p: return False
            kind = p['kind']
            if kind in {'once', 'count'}:
                p['remaining'] -= 1
                if p['remaining'] <= 0: self.run_policy = None
                return True
            if kind == 'until_write':
                if name in WRITE_TOOLS:
                    self.run_policy = None
                    return False
                return True
            if kind == 'reads': return name not in WRITE_TOOLS
            return kind in {'until_failure', 'completion'}
    def state(self):
        with self._state_lock:
            return {'control': self.control, 'run_policy': dict(self.run_policy) if self.run_policy else None,
                'pause_next': self.pause_next, 'queued_steer': self.queued_steer}
    def request(self, name, args, force=False, timeout=None, action_id='', revision=0,
        branch_id='main', parent_action_id=''):
        args = dict(args or {})
        required = name in self.tools
        bypassed = not force and self._policy_bypasses(name)
        control_checkpoint = not bypassed and (self.control == 'directed' or
            (self.control == 'guided' and name in GUIDED_TOOLS))
        checkpoint = force or (required and not bypassed) or control_checkpoint
        a = Intervention(tool=name, args=args, summary=_summary(name, args),
            preview=preview_for(name, args, self.host), control=self.control)
        if action_id: a.id = str(action_id)
        a.revision, a.branch_id, a.parent_action_id = int(revision or 0), branch_id, parent_action_id
        if self.host is not None and name in {'edit_file', 'create_file'} and args.get('path'):
            a.before = self.host.text_at(args['path'])
        self.history.append(a)
        if not checkpoint: return a.resolve(True)
        if required and self.mode == 'auto' and self.control != 'directed': return a.resolve(True)
        if required and self.mode == 'off':
            return a.resolve(False, 'approval is switched off for this session')
        if self.listeners < 1:
            return a.resolve(False, 'nothing is listening for interventions, so this could not be asked')
        self.current = a
        self._notify('ask', a)
        wait_for = self.timeout if timeout is None else timeout
        if not a.wait(wait_for):
            a.resolve(False, f'no answer after {wait_for}s')
            self._notify('answer', a)
        return a
    def answer(self, id, ok, note='', session=False, tool=None, args=None):
        "Resolve a checkpoint; only approval may replace the call that will execute."
        a = self.current
        if a is None or a.id != id or not a.pending: return None
        if ok:
            if tool: a.tool = str(tool)
            if args is not None: a.args = dict(args)
            a.summary, a.preview = _summary(a.tool, a.args), preview_for(a.tool, a.args, self.host)
        return super().answer(id, ok, note, session=session)
    def gate(self, tool_call):
        "Pause according to the control level, then apply an approved rewrite to the live call."
        if hasattr(tool_call, 'name'):
            name, args = tool_call.name, getattr(tool_call, 'arguments', {})
        else:
            fn = (tool_call or {}).get('function', {})
            name, args = fn.get('name', '?'), fn.get('arguments', {})
        action_id = (tool_call.get('id') or '') if isinstance(tool_call, dict) else ''
        a = self.request(name, args, action_id=action_id)
        if isinstance(tool_call, dict):
            fn = tool_call.setdefault('function', {})
            if a:
                fn['name'], fn['arguments'] = a.tool, a.args
                with self._state_lock:
                    self._execution_meta.append({'action_id': a.id, 'revision': a.revision,
                        'branch_id': a.branch_id,
                        'parent_action_id': a.parent_action_id,
                        'tool': a.tool, 'args': dict(a.args)})
            elif tool_call.get('id'):
                instruction = ('The user rejected this tool call. Do not retry this call or an '
                    'equivalent action unless the user explicitly asks for it later.')
                if a.note: instruction += f' User direction: {a.note}'
                fn['name'], fn['arguments'] = 'user_steering', {'instruction': instruction}
                return True
        return a
    def execution_meta(self, name, args):
        "Consume identity recorded by the approval hook before the wrapped tool executes."
        with self._state_lock:
            i = first(i for i, row in enumerate(self._execution_meta)
                if row['tool'] == name and row['args'] == dict(args or {}))
            return self._execution_meta.pop(i) if i is not None else {}

class WorkspaceHost(Host):
    "A `Workspace`, answering the harness's questions."
    mk_chat = None                          # `Agent.lend_model` fills this; declaring it is the opt-in
    def __init__(self, ws, session=None): self.ws, self.session = ws, session
    @property
    def capabilities(self):
        "What a workspace has by construction. `session` is left to the probe; see `docs/integration.md`."
        return {**super().capabilities, 'notebook': True, 'web': True, 'memory': True,
                'watch': True, 'api': True, 'shell': True}
    @property
    def roots(self): return [str(r) for r in self.ws.fs.roots]
    @property
    def project(self):
        "The folder the agent's commands run in: the chosen one, else the first open."
        root = self.ws.project_root
        return str(root) if root else (self.roots[0] if self.roots else '')
    def _readable_outside(self, path):
        "A path outside the open folders that may still be read, or None. Credentials never are."
        if not getattr(self.ws, 'agent_read_outside', False): return None
        p = Path(path).expanduser().resolve()
        if any(fnmatch(str(p), pat) for pat in DENY): return None
        return p if p.exists() else None
    def check(self, path, must_exist=False, reading=False):
        try: return self.ws.fs._check(path, must_exist=must_exist)
        except Unsafe as e:
            if reading and (outside := self._readable_outside(path)) is not None: return outside
            opened = [t.path for t in self.ws.tabs if t.path]
            hint = f'; open files: {", ".join(opened[-5:])}' if opened else ''
            raise Unsafe(f'{e}{hint}') from e
    def grep(self, pattern, path_filter='', regex=True, ignore_case=False, limit=MAX_GREP_HITS):
        "Exact matching through the workspace's own ripgrep, rather than a `read` per file."
        hits = self.ws.search.search(pattern, limit=limit * 4, regex=regex)
        if path_filter: hits = hits.filter(lambda h: path_filter.lower() in str(h.path).lower())
        if not ignore_case:                      # leela's ripgrep leg folds case; a cased ask does not
            try: rx = re.compile(pattern if regex else re.escape(pattern))
            except re.error: return None
            hits = hits.filter(lambda h: rx.search(h.text))
        return list(hits)[:limit]
    def walk(self): return list(self.ws.fs.walk())
    def read(self, path): return self.ws.fs.read(self.check(path))
    def check_write(self, path):
        target = self.check(path)
        active = Path(self.project).expanduser().resolve() if self.project else None
        if len(self.ws.fs.roots) > 1 and active and not target.is_relative_to(active) and not self.ws.allow_workspace_repo_writes:
            raise Unsafe('writes to another workspace repository are disabled; enable workspace repository writes in agent settings')
        return target
    def write(self, path, text): return self.ws.fs.write(self.check_write(path), text).path
    def text_at(self, path): return self.ws.text_at(path)
    def search(self, query, limit=20): return self.ws.search.agent_search(query, limit=limit)
    def search_blend(self, query, limit=20, legs=None):
        "Leela's own blend: every backend at once, each hit stamped with the legs that agreed."
        return self.ws.search.search(query, limit=limit, mode='all', legs=legs)
    def peers(self, path, line, limit=20): return self.ws.search.peers(path, line, limit=limit)
    def symbols(self, path): return self.ws.search.symbols(path)
    @property
    def search_note(self):
        s = self.ws.search
        return f'{s.backend}: {s.note}' if s.note else str(s.backend)
    def web_search(self, query, n=20): return self.ws.research.search(query, n=n)
    def read_url(self, url, remember=True): return self.ws.research.read(url, remember=remember)
    def research(self, query):
        _, digest = self.ws.research.dig(query)
        return digest
    @property
    def research_note(self): return self.ws.research.note
    def _vault(self, write=False):
        "The active vault's `Memory`, refusing a write the toggle does not allow."
        vaults = getattr(self.ws, 'vaults', None)
        if vaults is None: return self.ws.memory
        ref = vaults.active
        if write and not ref.agent_writable:
            raise PermissionError(f'the agent may not write to {ref.name}; turn on agent writes for it first')
        return vaults.memory(ref.name)
    def memory_search(self, query, limit=8): return self._vault().context(query, sections=limit)
    def memory_tree(self, document=''): return self._vault().toc(document or None)
    def memory_read(self, node_id): return self._vault().read(node_id)
    def memory_topics(self, limit=12): return self._vault().clusters(limit)
    def memory_forget(self, doc_id): return self._vault(write=True).forget(doc_id)
    def memory_documents(self, limit=50): return self._vault().all_documents(limit)
    def memory_sections(self, doc_id): return self._vault().sections(doc_id)
    def ask(self, question, ref=None, instruction='', **kw):
        "The vault answers with citations, on this session's model. `pii` is not the caller's to set."
        kw.pop('pii', None)
        if self.mk_chat is not None: kw.setdefault('mk_chat', self.mk_chat)
        return self._vault().vault.ask(question, ref=ref, instruction=str(instruction or ''), **kw)
    def remember(self, text, title=None, tags=()):
        return self._vault(write=True)._open().note(str(text), title=title, tags=list(tags or []))
    def watch(self, target, action='url', every='1d', note=None, **kw):
        return self._vault(write=True).watch(target, action=action, every=every, note=note, **kw)
    def unwatch(self, watch_id): return self._vault(write=True).unwatch(watch_id)
    def watches(self, due_only=False): return self._vault().watches(due_only=due_only)
    def poll(self):
        "Fire what has come due. A watch files itself into memory, so this needs the write."
        return self._vault(write=True).poll()
    # `SpecHost` is a `LocalHost`, so specs are borrowed rather than inherited. The workspace
    # holds the loaded ones, so they outlive one `WorkspaceHost`.
    @property
    def specs(self): return self.ws.__dict__.setdefault('_api_specs', {})
    @property
    def _clients(self): return self.ws.__dict__.setdefault('_api_clients', {})
    headers, timeout = {}, 60.0
    api_load, api_ops, api_call = SpecHost.api_load, SpecHost.api_ops, SpecHost.api_call
    api_names, _spec = SpecHost.api_names, SpecHost._spec
    def nb_cells(self, path):
        from ..nb.nb import Notebook
        return [(c.id, c.cell_type, c.source) for c in Notebook.load(self.check(path)).cells]
    def nb_add_cell(self, path, source, index=-1, cell_type='code'):
        from ..nb.nb import Cell, Notebook
        p = self.check(path)
        nb = Notebook.load(p) if p.exists() else Notebook.blank(p)
        c = nb.insert(len(nb) if index < 0 else int(index), Cell(source=source, cell_type=cell_type))
        if len(nb) == 2 and not nb[0].source.strip() and nb[1] is c: nb.delete(0)
        nb.save(p, sandbox=self.ws.fs)
        return c.id
    def _kernel(self):
        k = self.ws.runtime_peek()
        if k is None or not getattr(k, 'base', None) or not hasattr(k, 'api_sync'):
            raise NotImplementedError('no live kernel inspector')
        return k
    @staticmethod
    def _exec_text(r):
        if not r: return 'kernel inspector did not answer'
        if r.get('error'): return r['error']
        out = r.get('stdout') or ''
        result = r.get('result')
        if isinstance(result, dict): result = result.get('value') or result.get('text') or str(result)
        if result is not None: out += ('\n' if out else '') + str(result)
        return out or '(ok)'
    @staticmethod
    def _session_text(r):
        "One `AgentSession` run as the text the model sees."
        if r.error: return r.error
        out = r.stdout or ''
        if r.result is not None: out += ('\n' if out else '') + r.result.value
        return out or '(ok)'
    def run_python(self, code):
        if self.session is not None: return self._session_text(self.session.run(code))
        return self._exec_text(self._kernel().api_sync('/api/exec', {'code': code, 'scope': 'global'}))
    def inspect_python(self, code, scope='isolated'):
        "Read-only execution in one of `AgentSession`'s scopes; neither can change what the user made."
        if scope not in self.scopes:
            return (f'scope {scope!r} is not available here (allowed: {", ".join(self.scopes)}); '
                'the workspace was opened with a narrower agent scope')
        if self.session is not None: return self._session_text(self.session.run(code, scope=scope))
        return self._exec_text(self._kernel().api_sync('/agent/api/exec', {'code': code, 'scope': scope}))
    @property
    def scopes(self):
        s = getattr(self.ws, 'agent_scope', 'overlay')
        return ('isolated',) if s == 'isolated' else ('isolated', 'overlay')
    @property
    def kernel_kind(self): return getattr(self.ws, 'kernel_kind', 'ipykernel')
    def list_vars(self):
        if self.session is not None:
            return '\n'.join(f'{v.name}: {v.type} = {v.value}' for _, vs in self.session.view('minimal') for v in vs)
        r = self._kernel().api_sync('/api/rows', {'profile': 'minimal', 'sort': 'name'}) or {}
        return '\n'.join(f"{v.get('name')}: {v.get('type')} = {v.get('value')}"
            for g in r.get('groups', []) for v in g.get('nodes', []))
    def terminal_text(self, lines=200):
        terms = self.ws.terms.all()
        if not terms: return 'no terminal is open in the IDE'
        parts = [f'--- terminal {t.pid} ({" ".join(t.argv)}) ---\n{t.text(lines)}' for t in terms]
        return '\n\n'.join(parts).strip()
    def run_cmd(self, command, cwd=None, timeout=120):
        "Run one command in the project, the way the user would run it in leela's terminal."
        import signal, subprocess
        if not str(command or '').strip(): return 0, ''
        if not self.roots: raise NotImplementedError('no folder is open')
        d = self.check(cwd) if cwd else self.check(self.project)
        if not d.is_dir(): d = d.parent
        new_session = os.name == 'posix'
        p = subprocess.Popen(str(command), shell=True, cwd=str(d), text=True, errors='replace',
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=new_session)
        try:
            out, _ = p.communicate(timeout=max(1, int(timeout)))
            return p.returncode, out or ''
        except subprocess.TimeoutExpired:
            if new_session:
                try: os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                except Exception: p.kill()
            else: p.kill()
            out, _ = p.communicate()
            return 124, f'{out or ""}\n[killed after {timeout}s]'
    @property
    def shell_note(self):
        return f'commands run in {self.project}' if self.roots else 'no folder is open'
    @property
    def approvals(self): return getattr(self.ws, 'approvals', None)
    def note(self, text):
        fn = getattr(self.ws, 'on_note', None)
        if fn:
            try: fn(text)
            except Exception: pass

def _search_tools(host, legs=None, mx=MAX_TOOL_CHARS):
    "Leela's blended search as one tool: every backend at once, each hit stamped with what agreed."
    def search_all(query: str) -> str:
        "Search every code backend at once: exact symbols, literal text, keywords, and meaning."
        try: hits = host.search_blend(query, limit=MAX_HITS, legs=legs)
        except Exception as e: return f'search_all failed: {errstr(e)}'
        if not hits: return f'no matches ({host.search_note})'
        rows = L(hits).map(lambda h: f'{h.path}:{h.line}  {h.symbol or ""}  {h.text}'
            f'  [{"+".join(getattr(h, "sources", None) or [])}]')
        return clip(f'[{host.search_note}]\n' + '\n'.join(rows), mx)
    return [search_all]

def notebook_approvals(get_target, tools=WRITE_TOOLS, mode='ask', timeout=300, host=None):
    "An `Approvals` that writes the whole exchange into the notebook."
    from ..nb.nb import Cell
    def _add(md, meta):
        t = get_target()
        if not t: return None
        nb, i = t
        c = Cell(source=md, cell_type='markdown')
        c.approval = meta
        nb.insert(min(i + 1 + _n_approvals(nb, i), len(nb)), c)
        nb.dirty = True
        return c
    def on_ask(a): _add(ask_md(a), {'kind': 'approval', 'id': a.id, 'tool': a.tool, 'state': 'pending'})
    def on_answer(a):
        md = answer_md(a)
        if getattr(a, 'edited', False):
            md += (f'\n\nEdited `{a.original_tool}` into `{a.tool}` before execution.'
                f'\n\n```json\n{json.dumps(a.args, indent=2, default=str)}\n```')
        _add(md, {'kind': 'approval', 'id': a.id, 'tool': a.tool,
            'state': 'approved' if a.answer else 'refused',
            'edited': bool(getattr(a, 'edited', False))})
    return Interventions(tools=tools, mode=mode, timeout=timeout, host=host,
        on_ask=on_ask, on_answer=on_answer)

def _irreversible(action):
    "How a completed action reads in the turn's irreversible list, or None if restoring files undoes."
    if action.tool == 'memory_forget': return f"memory_forget ({action.args.get('doc_id', 'unknown document')})"
    if action.tool == 'run_python': return 'run_python (live kernel state)'
    if action.tool == 'run_shell': return f"run_shell ({action.args.get('command', 'command')})"
    if action.tool in GIT_WRITE_TOOLS: return action.tool
    return None

def _n_approvals(nb, i):
    "How many approval cells already sit below the prompt cell at `i`."
    n = 0
    for c in nb.cells[i + 1:]:
        if getattr(c, 'approval', None) is None: break
        n += 1
    return n

class Assistant(Agent):
    "The IDE's agent, built over a `Workspace`."
    LITERT_BACKENDS = ('cpu', 'gpu')
    def set_litert_backend(self, which):
        "Choose the accelerator LiteRT engines are built on, and release the loaded ones."
        which = str(which or '').strip().lower()
        if which not in self.LITERT_BACKENDS:
            raise ValueError(f'litert backend must be one of {", ".join(self.LITERT_BACKENDS)}')
        if self.busy: raise RuntimeError('cannot change the LiteRT backend while the assistant is working')
        os.environ['LEELA_LITERT_BACKEND'] = which
        for key in [k for k in self._backends if k[0] == 'litert']: self._backends.pop(key).close()
        self.note = f'LiteRT backend {which}'
        return which
    @delegates(Agent.__init__)
    def __init__(self,
        ws,
        session=None,
        model=None,
        sp=None,
        approve=None,
        surface='agent',
        **kwargs
    ):
        from .models import load_models
        load_models()
        host = WorkspaceHost(ws, session)
        kwargs.setdefault('cfg', leela_cfg)
        kwargs.setdefault('approvals', getattr(ws, 'approvals', None))
        kwargs.setdefault('compact', getattr(ws, 'compact_auto', True))
        kwargs.setdefault('compact_strategy', getattr(ws, 'compact_strategy', 'surgical'))
        kwargs.setdefault('max_tool_calls', getattr(ws, 'tool_budget', 'auto'))
        kwargs.setdefault('max_steps', getattr(ws, 'step_budget', 'auto'))
        if approve is not None and kwargs.get('approvals') is None:
            kwargs['approvals'] = _PolicyApprovals(approve)
        self.ws, self.surface = ws, surface
        self.session_state = str(getattr(ws, 'agent_state', '') or '')
        self._search_toolset = _search_tools(host, legs=None if surface == 'agent' else FAST_SEARCH_LEGS)
        self.video_jobs = VideoJobs() if video_available() else None
        self._video_toolset = video_tools(host, jobs=self.video_jobs) if self.video_jobs else []
        super().__init__(host, model=model, sp=sp, **kwargs)
        self.lend_model()   # so the vault's `ask` uses this session's engine, not a second one
        def user_steering(instruction: str) -> str:
            "Return a user's intervention after a skipped tool call so the agent can redirect its next step."
            return f'User steering after skipping the proposed call: {instruction}'
        self._steering_tool = user_steering
        self.turn_transactions = {}
    @property
    def tools(self):
        if self._tools is None:
            registered = {f.__name__ for f in self.registry.tools}
            self.registry.tools.extend(f for f in [*self._search_toolset, *self._video_toolset]
                if f.__name__ not in registered)
            if self._steering_tool not in self.registry.tools: self.registry.tools.append(self._steering_tool)
            built = super().tools
            self._plain = [f for f in self._plain if f.__name__ not in GIT_WRITE_TOOLS]
            return built
        return super().tools
    def system_prompt(self):
        base = super().system_prompt()
        layers = getattr(self.ws, 'agent_state_layers', {})
        enabled = [(name, row.get('text', '')) for name, row in layers.items()
            if row.get('enabled', True) and str(row.get('text', '')).strip()]
        if not enabled and self.session_state: enabled = [('task', self.session_state)]
        if enabled:
            base += '\n\n## User-owned starting state\n' + ''.join(
                f'\n### {name.title()} state\n\n{text.strip()}\n' for name, text in enabled)
        if memory := self.ws.agent_memory_context(self.surface):
            base += ('\n\n## User-selected memory notes\n'
                'Treat these as durable user context. If a note conflicts with the current request or code, ask rather than guessing.\n\n' + memory)
        return base
    def set_state(self, text, layer='task', enabled=True, source='user'):
        "Replace one explicit state layer and re-brief the live model without losing history."
        if layer not in self.ws.agent_state_layers: raise ValueError(f'unknown state layer {layer!r}')
        text = str(text or '').strip()
        self.ws.agent_state_layers[layer] = {'text': text, 'enabled': bool(enabled), 'source': source}
        if layer == 'task': self.session_state = self.ws.agent_state = text
        self.ws.save()
        self.refresh()
        return text
    def _finish(self, text, prompt=''):
        out = super()._finish(text, prompt)
        changes = self.changes()
        irreversible = [note for a in self.activity.since(self.activity._mark)
                        if a.done and a.ok and (note := _irreversible(a))]
        self.turn_transactions[self.current_turn_id] = {
            'turn_id': self.current_turn_id, 'branch_id': self.current_branch_id,
            'files': {p: {'before': before, 'after': after} for p, (before, after) in changes.items()},
            'irreversible': irreversible, 'rolled_back': False}
        self.ws.journal.record('Agent turn', [(p, before, after) for p, (before, after) in changes.items()],
            kind='agent', irreversible=irreversible)
        return out
    def turn_capabilities(self, turn_id):
        "Which post-turn operations have a real checkpoint or artifact behind them."
        checkpoint = self.checkpoints.get(str(turn_id), {})
        after = checkpoint.get('after') or []
        revisable = any(isinstance(m, dict) and m.get('role') == 'assistant' and
            not m.get('tool_calls') and str(m.get('content') or '').strip() for m in after)
        tx = self.turn_transactions.get(str(turn_id)) or {}
        files = list((tx.get('files') or {}).keys())
        return {'revisable': revisable, 'undoable': bool(files) and not tx.get('rolled_back'),
            'files': files, 'irreversible': list(tx.get('irreversible') or [])}
    def rollback_turn(self, turn_id):
        "Atomically restore every unchanged artifact from a completed turn."
        tx = self.turn_transactions.get(str(turn_id))
        if tx is None: raise KeyError(f'no transaction for {turn_id}')
        if tx['rolled_back']: raise ValueError('that turn was already rolled back')
        conflicts = [p for p, snap in tx['files'].items() if self.host.text_at(p) != snap['after']]
        if conflicts: raise ValueError('changed after the turn: ' + ', '.join(conflicts))
        for path, snap in tx['files'].items(): self.host.write(path, snap['before'])
        tx['rolled_back'] = True
        return tx
    def _action_meta(self, name, args):
        base = super()._action_meta(name, args)
        if self.approvals is not None:
            approved = self.approvals.execution_meta(name, args)
            base.update({k: v for k, v in approved.items() if k not in {'tool', 'args'}})
        base['branch_id'] = self.current_branch_id
        return base
    def _record(self, f):
        "Observe results for run-until-failure and deliver queued steering between calls."
        run = super()._record(f)
        @functools.wraps(f)
        def wrapper(*args, **kw):
            approvals = self.approvals
            try: out = run(*args, **kw)
            except Exception:
                if approvals is not None: approvals.observe_result(False)
                raise
            ok = not (failed(out) or str(out).startswith(FAILED_PREFIXES))
            if approvals is not None:
                approvals.observe_result(ok)
                if steer := approvals.consume_steer():
                    out = f'{out}\n\nUser steering for the next decision: {steer}'
            return out
        return wrapper
    def status(self):
        out = super().status()
        if self.approvals is not None: out.update(self.approvals.state())
        out['compaction'] = {'auto': self.compactor.auto, 'strategy': self.compactor.strategy,
            'count': self.compactor.count, 'note': self.compactor.note,
            'threshold': self.compactor.due(self.backend)}
        return out
    @property
    def turn_media(self):
        "Everything the newest turn has to draw: what the model generated, plus finished video jobs."
        return self.last_media + (self.video_jobs.unshown() if self.video_jobs else [])
    @property
    def tools_note(self): return f'{len(self.tools)} tools, {len(self.skills)} skills'

class _PolicyApprovals(Approvals):
    "An `Approvals` wrapping a plain `approve(tool_call) -> bool`."
    def __init__(self, approve):
        super().__init__(tools=WRITE_TOOLS, mode='ask')
        self._approve = approve
    def request(self, name, args):
        a = Ask(tool=name, args=args, summary=_summary(name, args), preview=preview_for(name, args))
        self.history.append(a)
        try: ok = self._approve({'function': {'name': name, 'arguments': args}})
        except Exception as e: return a.resolve(False, errstr(e))
        return a.resolve(bool(ok))

def ide_tools(ws, session=None):
    "Every tool the agent gets, bound to one `Workspace`."
    host = WorkspaceHost(ws, session)
    return tools_for(host, extra=_search_tools(host))
