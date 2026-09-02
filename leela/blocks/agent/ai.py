"Binding a `Workspace` to the agent harness."

from __future__ import annotations
from ..runtime.kernels import python_for, venv_env
import asyncio, functools, inspect, json, os, re, threading
from fnmatch import fnmatch
from fastcore.all import L, Path, delegates, first
from ... import errstr, leela_cfg
from ..fs.fs import Unsafe
from ...agent.agent import Agent, Approvals, Ask, _summary, answer_md, ask_md, preview_for
from shalya.core import (MAX_API, MAX_GREP_HITS, MAX_HITS, MAX_TOOL_CHARS,
                         WRITE_TOOLS as HARNESS_WRITE_TOOLS, clip, failed, one_line as _1, summary)
from shalya.host import (ApiHost, AskHost, CodeHost, DENY, Host, MemoryHost, NotebookHost, SessionHost,
                         ShellHost, WatchHost, WebHost)
#: `tools_for` stays Ramabana's: it builds the image group from the turn's model, which shalya
#: cannot know. Everything else above is the toolset's own, taken from where it lives.
from ...agent.tools import tools_for
from ...agent.spec import MAX_OPS, SpecHost
from ...core.session import assigned_names as _assigned
from ..vault.jobs import cadence
from .video import VideoJobs, video_available, video_tools

from shalya.core import GIT_READ_TOOLS, GIT_TOOLS, GIT_WRITE_TOOLS

FAILED_PREFIXES = ('edit failed', 'write failed', 'could not')
FAST_SEARCH_LEGS = ('symbols', 'rg', 'fts')
BRIEFING_NOTES = 24_000   #: characters of pinned notes a briefing carries; a completion asks for less
MAX_ATTRS = 20
NEWS_WRITE_TOOLS = frozenset({'news_follow', 'news_unfollow', 'news_refresh'})
WRITE_TOOLS = HARNESS_WRITE_TOOLS | GIT_WRITE_TOOLS | NEWS_WRITE_TOOLS | frozenset({'run_cell'})

__all__ = ['WorkspaceHost', 'Assistant', 'Interventions', 'ide_tools', 'api_context',
           'notebook_approvals', 'BRIEFING_NOTES', 'MAX_TOOL_CHARS', 'WRITE_TOOLS']

CONTROL_MODES = frozenset({'autopilot', 'guided', 'directed'})
STOP_NOTE = 'the user stopped this turn'
GUIDED_TOOLS = WRITE_TOOLS | frozenset({'web_search', 'read_url', 'research'})

STATE_TEMPLATE = """# Agent charter

## Role
[What should the agent be responsible for in this workspace?]

## Goal
[The outcome it should move toward.]

## Hard boundaries
- [Project-specific non-negotiable rules.]

## Routing rules
- [When this workspace expects a specialized tool or skill.]

## Tool practices
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
        self.stopping = False
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
    def stop(self, note=STOP_NOTE):
        "Refuse every call still to come this turn, and release the one already waiting."
        with self._state_lock: self.stopping, self.run_policy, self.pause_next = True, None, False
        self.cancel_all(note)
    def resume(self):
        with self._state_lock: self.stopping = False
    def queue_steer(self, text):
        with self._state_lock:
            self.queued_steer = str(text or '').strip()
            if self.queued_steer: self.run_policy, self.pause_next = {'kind': 'once', 'remaining': 1}, False
            a = self.current if self.queued_steer and self.current is not None and self.current.pending else None
            if a is not None: self.queued_steer = ''
        if a is not None: self.answer(a.id, False, text)
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
                'pause_next': self.pause_next, 'queued_steer': self.queued_steer, 'stopping': self.stopping}
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
        if self.stopping: return a.resolve(False, STOP_NOTE)
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
            else:
                # A bare backend denial reads to a model as a transient permission failure and it
                # proposes the same call again, so "no" resolves as a durable instruction.
                instruction = (('The user stopped this turn. Do not run this call or any other one. '
                    'Stop now and reply with a short summary of what you had already done.')
                    if self.stopping else
                    ('The user rejected this tool call. Do not retry this call or an '
                    'equivalent action unless the user explicitly asks for it later.'))
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

class WorkspaceHost(CodeHost, NotebookHost, WebHost, MemoryHost, WatchHost, ApiHost, ShellHost,
                    SessionHost, AskHost, Host):
    "A `Workspace`, answering the harness's questions."
    mk_chat = None                          # `Agent.lend_model` fills this; declaring it is the opt-in
    # Leela serves the inspector from inside the kernel process, so this holds for ipykernel too.
    concurrent = True
    def __init__(self, ws, session=None): self.ws, self.session = ws, session
    #: Every group above is declared by inheritance rather than probed.
    @property
    def roots(self): return [str(r) for r in self.ws.fs.roots]
    @property
    def project(self):
        "The folder the agent's commands run in: the chosen one, else the first open."
        root = self.ws.project_root
        return str(root) if root else (self.roots[0] if self.roots else '')
    @property
    def writable_roots(self):
        "The open folders a write may land in, which is not every folder the agent may read."
        if len(self.ws.fs.roots) < 2 or self.ws.allow_workspace_repo_writes: return self.roots
        return [self.project] if self.project else self.roots
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
            # The gate is the open roots, not the open tabs.
            hint = f'; open folders: {", ".join(self.roots)}' if self.roots else ''
            if reading and not getattr(self.ws, 'agent_read_outside', False):
                hint += '; open the folder, or turn on reading outside the open folders in agent settings'
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
            raise Unsafe(f'{path} is readable, but writes to another workspace repository are disabled. '
                f'Writable: {", ".join(self.writable_roots)}. Enable workspace repository writes in '
                'agent settings to write to the other open folders')
        return target
    def write(self, path, text): return self.ws.fs.write(self.check_write(path), text).path
    def text_at(self, path): return self.ws.text_at(path)
    def search(self, query, limit=20): return self.ws.search.agent_search(query, limit=limit)
    def search_blend(self, query, limit=20, legs=None):
        "Leela's own blend: every backend at once, each hit stamped with the legs that agreed."
        return self.ws.search.search(query, limit=limit, mode='all', legs=legs)
    def peers(self, path, line, limit=20): return self.ws.search.peers(path, line, limit=limit)
    def symbols(self, path): return self.ws.search.symbols(path)
    def public_api(self, package, limit=MAX_API): return self.ws.search.package_api(package)
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
    @property
    def _pii(self):
        "What a retrieval does about personal information here. The workspace's, never the model's."
        return getattr(self.ws, 'vault_pii', 'off')
    def memory_search(self, query, limit=8): return self._vault().context(query, sections=limit, pii=self._pii)
    def memory_tree(self, document=''): return self._vault().toc(document or None, pii=self._pii)
    def memory_read(self, node_id): return self._vault().read(node_id, pii=self._pii)
    def memory_topics(self, limit=12): return self._vault().clusters(limit)
    def memory_forget(self, doc_id): return self._vault(write=True).forget(doc_id)
    def memory_documents(self, limit=50): return self._vault().all_documents(limit)
    def memory_sections(self, doc_id): return self._vault().sections(doc_id, pii=self._pii)
    def ask(self, question, ref=None, instruction='', **kw):
        "The vault answers with citations, on this session's model. `pii` is not the caller's to set."
        kw.pop('pii', None)
        if self.mk_chat is not None: kw.setdefault('mk_chat', self.mk_chat)
        return self._vault().vault.ask(question, ref=ref, instruction=str(instruction or ''),
                                       pii=self._pii, **kw)
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
    @property
    def headers(self): return self.ws.__dict__.setdefault('_api_headers', {})
    @property
    def spec_info(self): return self.ws.__dict__.setdefault('_api_spec_info', {})
    @property
    def _creds(self):
        "One user's keys, read where the workbench writes them rather than held on the host."
        from ..vault.spec import CREDS
        return CREDS.all()
    def api_creds(self, name, headers=None, reach=None):
        "Set what is sent with calls to one spec and nothing else; `headers=None` clears it."
        from ..vault.spec import CREDS
        return CREDS.set(name, headers, reach=reach)
    def api_keyed(self):
        "What may be said about each spec out loud: header names, the variables behind them, reach."
        from ..vault.spec import CREDS, env_status
        return {n: dict(headers=p['headers'], reach=p['reach'], env=env_status(p['refs']))
                for n, p in CREDS.policies().items()}
    def reach_refusal(self, name):
        "Why a model may not call this spec, or None."
        from ..vault.spec import CREDS
        if CREDS.reach(name) != 'local' or self.model_local is None: return None
        local, model = self.model_local()
        if local: return None
        return (f'{name} is marked local-only and this conversation runs on {model}, which is not a '
                f'model on this machine. Nothing was sent. Switch to a local model, or change the '
                f'reach of {name} on the vault workbench.')
    def _client(self, key, parsed):
        "Cached against the credentials too, so a key set on the page reaches a running host."
        from ..vault.spec import expand
        creds = self._creds.get(key, {})
        seal, got = tuple(sorted(creds.items())), self._clients.get(key)
        if got is None or got[0] != seal:
            from fastspec.oapi import OpenAPIClient
            got = self._clients[key] = (seal, OpenAPIClient(parsed, timeout=self.timeout, sync=True,
                                                            headers={**self.headers, **expand(creds)}))
        return got[1]
    timeout, max_ops = 60.0, MAX_OPS
    model_local = None      # `Assistant` fills this once there is a turn model to ask about
    api_load, api_ops = SpecHost.api_load, SpecHost.api_ops
    api_fetch = SpecHost.api_call       # ungated: the person reading the page owns the data on it
    api_names, _spec, _page = SpecHost.api_names, SpecHost._spec, SpecHost._page
    api_count = SpecHost.api_count
    def api_call(self, operation, name='', **params):
        "What a model reaches through, which is why reach is enforced here and not in `api_fetch`."
        from ..vault.spec import SpecError
        key, _ = self._spec(name)
        if refusal := self.reach_refusal(key): raise SpecError(refusal)
        return self.api_fetch(operation, key, **params)
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
    def nb_run_cell(self, path, cell_id, timeout=120):
        "Run one cell in the kernel its notebook's tab runs in, the way the Run button does."
        from ..nb.nb import Notebook
        p = self.check(path, must_exist=True)
        nb = Notebook.load(p)
        i = first(i for i, c in enumerate(nb.cells) if c.id == cell_id)
        if i is None: return f'no cell {cell_id!r} in {path}; call notebook_cells for the ids'
        if nb[i].cell_type != 'code': return f'cell {cell_id} is a {nb[i].cell_type} cell; only code cells run'
        loop = self._loop()
        if loop is None: return 'no running event loop owns the kernels here, so no cell can be run'
        tab = first(t for t in getattr(self.ws, 'tabs', []) if str(getattr(t, 'path', '') or '') == str(p))
        try: k = asyncio.run_coroutine_threadsafe(self.ws.runtime(tab), loop).result(120)
        except Exception as e: return f'could not start the kernel for {path}: {errstr(e)}'
        before = self._var_snapshot()
        try: c = asyncio.run_coroutine_threadsafe(nb.run(i, k), loop).result(max(1, int(timeout)))
        except TimeoutError: return f'cell {cell_id} has not finished in {timeout}s; it is still running in the kernel'
        except Exception as e: return f'could not run cell {cell_id}: {errstr(e)}'
        if (origins := getattr(self.ws, 'origins', None)) is not None: origins.cell(c, path)
        return self._cell_report(path, c, before)
    def _var_snapshot(self):
        "Name to value for every visible variable, or None when no inspector will say."
        try: return {r['name']: r['value'] for r in self._var_rows()}
        except Exception: return None
    def _cell_report(self, path, c, before):
        "What one run did: its outputs, whether it raised, its execution count, and what moved."
        head = f'ran cell {c.id} of {path}  [In[{c.execution_count}]'
        if c.execution_ms is not None: head += f', {c.execution_ms:.0f} ms'
        after = self._var_snapshot()
        changed = ([] if before is None or after is None
                   else sorted(n for n, v in after.items() if before.get(n) != v))
        body = [head + ']', c.text.rstrip() or '(no output)']
        if c.has_error: body.append('the cell raised: the traceback above is from this run')
        body.append('bindings changed: ' + (', '.join(changed) if changed else 'none'))
        return '\n'.join(body)
    def _kernel(self):
        k = self.ws.runtime_peek() or self._start_kernel()
        if k is None or not getattr(k, 'base', None) or not hasattr(k, 'api_sync'):
            raise NotImplementedError('no live kernel inspector')
        return k
    def _start_kernel(self):
        "Start the tab's kernel for a tool that needs one. `None` where there is no loop to start it on."
        loop = self._loop()
        if loop is None: return None
        try: return asyncio.run_coroutine_threadsafe(self.ws.runtime(), loop).result(120)
        except Exception: return None
    def _loop(self):
        "The loop that owns the kernels, or None when this call is already on it or it is gone."
        loop = getattr(self.ws, '_loop', None)
        if loop is None or not loop.is_running(): return None
        try:
            if asyncio.get_running_loop() is loop: return None
        except RuntimeError: pass
        return loop
    @staticmethod
    def _partial(out, error, bound=()):
        "A failed run said in full: the printed output, and the names bound before the line that raised."
        return ((f'{out}\n' if out else '') + error +
                '\n[partial run: everything before the error already happened' +
                (f'; bound {", ".join(bound)}' if bound else '') + ']')
    def _exec_text(self, r, bound=()):
        if not r: return 'kernel inspector did not answer'
        out = r.get('stdout') or ''
        if r.get('error'): return self._partial(out, r['error'], bound)
        result = r.get('result')
        if isinstance(result, dict): result = result.get('value') or result.get('text') or str(result)
        if result is not None: out += ('\n' if out else '') + str(result)
        return out or '(ok)'
    def _session_text(self, r, bound=()):
        "One `AgentSession` run as the text the model sees."
        out = r.stdout or ''
        if r.error: return self._partial(out, r.error, bound)
        if r.result is not None: out += ('\n' if out else '') + r.result.value
        return out or '(ok)'
    def _bound_after(self, code):
        "Of the names the call meant to bind, the ones that exist now. The kernel keeps no before."
        names = _assigned(code)
        if not names: return ()
        try: have = {r['name'] for r in self._var_rows()}
        except Exception: return ()
        return [n for n in names if n in have]
    def _run(self, code, scope):
        "One execution, reported with whatever it managed before an exception ended it."
        if self.session is not None:
            before = set(self.session.layer)
            r = self.session.run(code, scope=scope)
            bound = sorted(set(self.session.layer) - before)
            self._note_origin(bound, scope, ok=not r.error)
            return self._session_text(r, bound)
        r = self._kernel().api_sync('/agent/api/exec', {'code': code, 'scope': scope})
        failed = bool((r or {}).get('error'))
        bound = self._bound_after(code) if failed and scope == 'overlay' else ()
        self._note_origin(bound if failed else _assigned(code), scope, ok=not failed)
        return self._exec_text(r, bound)
    def _note_origin(self, names, scope, ok=True):
        "Attribute what the overlay bound. `isolated` discards its writes, so it binds nothing."
        origins = getattr(self.ws, 'origins', None)
        if names and origins is not None and scope == 'overlay': origins.record(names, 'run_python', ok)
    def run_python(self, code):
        "Run in the agent's own layer over the user's namespace, never in the namespace itself."
        return self._run(code, 'overlay' if 'overlay' in self.scopes else 'isolated')
    def inspect_python(self, code, scope='isolated'):
        "Read-only execution in one of `AgentSession`'s scopes; neither can change what the user made."
        if scope not in self.scopes:
            return (f'scope {scope!r} is not available here (allowed: {", ".join(self.scopes)}); '
                'the workspace was opened with a narrower agent scope')
        return self._run(code, scope)
    @property
    def scopes(self):
        s = getattr(self.ws, 'agent_scope', 'overlay')
        return ('isolated',) if s == 'isolated' else ('isolated', 'overlay')
    @property
    def kernel_kind(self): return getattr(self.ws, 'kernel_kind', 'ipykernel')
    def _rows(self, path):
        r = self._kernel().api_sync(path, {'profile': 'minimal', 'sort': 'name'})
        return None if r is None else [v for g in r.get('groups', []) for v in g.get('nodes', [])]
    def _var_rows(self):
        "The merged view `DhrishtiHost` reads: what the user has, plus what this agent has bound."
        if self.session is not None:
            return [{'name': v.name, 'type': v.type, 'value': v.value}
                    for _, vs in self.session.view('minimal') for v in vs]
        # an `agent='off'` inspector refuses the merged route, and owner-only beats nothing at all
        rows = self._rows('/agent/api/rows')
        if rows is None: rows = self._rows('/api/rows') or []
        return [{'name': v.get('name'), 'type': v.get('type'), 'value': v.get('value')} for v in rows]
    def list_vars(self):
        "Every visible variable, and what last bound it: a value alone does not say where it came from."
        origins = getattr(self.ws, 'origins', None)
        return '\n'.join(f"{r['name']}: {r['type']} = {r['value']}"
                         + ('' if origins is None else origins.note(r['name'])) for r in self._var_rows())
    def inspect_var(self, name, attrs=()):
        "One name, without `globals()`: whether it is bound, what it is, and the attributes asked for."
        name = str(name or '').strip()
        if not name.isidentifier(): return f'{name!r} is not a variable name'
        row = first(r for r in self._var_rows() if r['name'] == name)
        if row is None: return f"{name} is not bound, in the user's namespace or your own layer"
        out = [f"{name}: {row['type']} = {row['value']}"]
        for a in [str(a).strip() for a in list(attrs)[:MAX_ATTRS]]:
            if a: out.append(f'{name}.{a} = ' + self.inspect_python(f'{name}.{a}').strip())
        return '\n'.join(out)
    def owner_names(self):
        "Top-level names in the user's own namespace, which nothing the agent does may replace."
        if self.session is not None: return set(self.session.owner())
        return {v.get('name') for v in (self._rows('/api/rows') or [])}
    def promote_var(self, name):
        "Hand one name the agent bound in its own layer to the user, the way the vars pane does."
        name = str(name or '').strip()
        if not name.isidentifier(): return f'{name!r} is not a variable name'
        if name in self.owner_names():
            return (f'{name!r} already exists in the user\'s namespace and will not be replaced. '
                'Bind your result to a new name and promote that.')
        if self.session is not None:
            if name not in self.session.layer: return self._unbound(name)
            self.session.owner()[name] = self.session.layer.pop(name)
            self.session.ns.pop(name, None)
            return f'{name} is now in the user\'s namespace'
        r = self._kernel().api_sync('/api/promote', {'accessor': json.dumps([name])})
        if r is None: return f'could not promote {name!r}: the kernel inspector refused or is unreachable'
        if not r.get('ok'): return self._unbound(name) if 'no agent variable' in str(r.get('error')) else str(r['error'])
        # stop shadowing it, or the layer's copy leaves the promoted name outside the owner policy
        self._kernel().api_sync('/agent/api/exec', {'code': f'del {name}', 'scope': 'overlay'})
        return f'{name} is now in the user\'s namespace'
    @staticmethod
    def _unbound(name): return f'no agent variable {name!r}; bind it with run_python first'
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
        # The bundle's interpreter redirection is taken off: a shell command that runs python
        # would otherwise import the app's own standard library.
        p = subprocess.Popen(str(command), shell=True, cwd=str(d), text=True, errors='replace',
                             env=venv_env(python_for(d, session=None)),
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

def _session_tools(host):
    "One variable read and the Run button, as the two tools Leela adds to the live session."
    @summary(lambda a: f'Inspect {a.get("name","")}')
    def inspect_var(name: str, attrs: str = '') -> str:
        """Report one live variable: whether it is bound, what it is, and the attributes `attrs` names.
        `attrs` is comma separated, such as `shape, dtypes`. This needs no approval. Use `list_vars` for the whole namespace. The sandbox refuses `inspect_python` over `globals()` or `vars()`.
        """
        try: return clip(host.inspect_var(name, [a for a in str(attrs).replace(',', ' ').split() if a]))
        except Exception as e: return f'inspect_var failed: {errstr(e)}'
    @summary(lambda a: f'Run {a.get("path","")} cell {a.get("cell_id","?")}')
    def run_cell(path: str, cell_id: str, timeout: int = 120) -> str:
        """Run one notebook cell in the user's live kernel, as pressing Run on it would.
        The source runs as it is on disk, in that notebook tab's kernel, against the user's namespace and execution counter. The notebook file is never written. Take `cell_id` from `notebook_cells`. `run_python` is not a substitute: it runs in your own layer, not the user's.
        """
        try: return clip(host.nb_run_cell(path, cell_id, timeout))
        except Exception as e: return f'run_cell failed: {errstr(e)}'
    return [inspect_var, run_cell]

def _search_tools(host, legs=None, mx=MAX_TOOL_CHARS):
    "Leela's blended search as one tool: every backend at once, each hit stamped with what agreed."
    @summary(lambda a: f'Search all for {_1(a.get("query"))}')
    def search_all(query: str) -> str:
        "Search every code backend at once: exact symbols, literal text, keywords, and meaning."
        try: hits = host.search_blend(query, limit=MAX_HITS, legs=legs)
        except Exception as e: return f'search_all failed: {errstr(e)}'
        if not hits: return f'no matches ({host.search_note})'
        rows = L(hits).map(lambda h: f'{h.path}:{h.line}  {h.symbol or ""}  {h.text}'
            f'  [{"+".join(getattr(h, "sources", None) or [])}]')
        return clip(f'[{host.search_note}]\n' + '\n'.join(rows), mx)
    return [search_all]

def _news_tools(host, mx=MAX_TOOL_CHARS):
    "The feeds and the loaded specs, as tools. The memory tools read the main shelf; feeds are on `news`."
    from ..vault.news import NEWS_SHELF, fetch_feed, feed_title, news_rows, poll_feeds
    def feeds():
        f = getattr(host.ws, 'feeds', None)
        if f is None: raise ValueError('this workspace follows no sources')
        return f
    def story(d, chars=240):
        m = d.get('meta') or {}
        return dict(doc_id=d.get('doc_id') or d.get('id'), title=d.get('title'), feed=m.get('feed'),
            published=str(m.get('published') or '')[:19], author=m.get('author'),
            link=d.get('source'), summary=str(m.get('summary') or '')[:chars])
    @summary(lambda a: 'Followed sources')
    def news_feeds() -> str:
        """List the sources this vault follows, how often each is read, and what it last said.
        Feed items are filed on the `news` shelf, not the main one. Use `news_latest` to read them and `news_story` to open one.
        """
        try: rows = [dict(url=f.url, title=f.title, every=f.every, enabled=f.enabled,
                          last_status=f.last_status or 'not read yet', new_since_last_read=f.items)
                     for f in feeds()]
        except Exception as e: return f'news_feeds failed: {errstr(e)}'
        return clip(json.dumps(rows, default=str), mx)
    @summary(lambda a: 'Latest news' + (f' matching {_1(a.get("match"))}' if a.get('match') else '')
                       + (f' from {a["feed"]}' if a.get('feed') else ''))
    def news_latest(match: str = '', feed: str = '', limit: int = 20) -> str:
        """Recent feed items, newest first: headline, source, date, standfirst and `doc_id`.
        `match` narrows by headline or standfirst, `feed` by the source's name. This reads what is already filed. Call `news_refresh` first when the question is about today.
        """
        try: found = news_rows(host._vault(), match=match, feed=feed, limit=max(1, int(limit)))
        except Exception as e: return f'news_latest failed: {errstr(e)}'
        if not found: return 'nothing on the news shelf matches that.'
        return clip(json.dumps([story(x) for x in found], default=str), mx * 2)
    @summary(lambda a: f'Read {_1(a.get("doc"))}')
    def news_story(doc: str) -> str:
        """One feed item in full, by the `doc_id` or the headline `news_latest` reported.
        Feed items are on the `news` shelf, so `memory_read` cannot open them.
        """
        text = host._vault().document_text(doc, shelf=NEWS_SHELF)
        if not text: return f'no such item on the news shelf: {doc!r}. Call news_latest for what is there.'
        return clip(text, mx * 2)
    @summary(lambda a: f'Follow {a.get("title") or a.get("url","")}')
    def news_follow(url: str, title: str = '', every: str = '1h') -> str:
        """Follow a source and read it now. `url` may be the site itself, whose feed is found for you.
        A refusal means the source carries no feed; never retry with a guessed `/rss.xml`. `every` is the cadence after this call.
        """
        try: f = feeds().add(url, title, every)
        except Exception as e: return f'could not follow that: {errstr(e)}'
        out = poll_feeds(host._vault(write=True), feeds(), only=f.id)
        return f"following {f.title} at {f.url}, {cadence(f.seconds)}; filed {out['added']} items."
    @summary(lambda a: f'Unfollow {a.get("url","")}')
    def news_unfollow(url: str) -> str:
        "Stop following one source. What it already filed stays in the vault."
        f = first(x for x in feeds() if url in (x.id, x.url, x.title))
        if f is None: return f'not following {url!r}. Call news_feeds to see what is followed.'
        feeds().remove(f.id)
        return f'stopped following {f.title or f.url}; its items remain on the news shelf.'
    @summary(lambda a: f'Refresh {a.get("feed") or "every source"}')
    def news_refresh(feed: str = '') -> str:
        """Read followed sources now and file whatever is new. Returns what came in, per feed.
        `feed` is one source's address or title from `news_feeds`; every source when omitted.
        """
        try: out = poll_feeds(host._vault(write=True), feeds(), force=True, only=feed)
        except Exception as e: return f'news_refresh failed: {errstr(e)}'
        if not out['feeds']: return f'not following {feed!r}. Call news_feeds to see what is followed.'
        return clip(json.dumps(out, default=str), mx)
    @summary(lambda a: 'API access')
    def api_access() -> str:
        """Report what each loaded spec sends, what backs it, and which models may call it.
        Header and environment variable names only, never a value. A spec with no credentials goes out unauthenticated. A local-only spec refuses on a hosted model, and the refusal names what to change.
        """
        from ..vault.spec import EXAMPLES
        keyed, loaded = host.api_keyed(), sorted(host.specs)
        if not loaded:
            ex = ', '.join(f'api_load({x.path!r})' for x in EXAMPLES)
            return f'no specification is loaded; call api_load first. Keyless examples: {ex}.'
        rows = {n: keyed.get(n) or dict(headers=[], reach='cloud', env={}) for n in loaded}
        for n, r in rows.items():
            if not r['headers']: r['note'] = 'no credentials — calls go out unauthenticated'
            if refusal := host.reach_refusal(n): r['refused'] = refusal
        return clip(json.dumps(rows, default=str), mx)
    return [news_feeds, news_latest, news_story, news_follow, news_unfollow, news_refresh, api_access]

def api_context(host):
    "The specs already loaded in this session, as something the model is told rather than finds."
    names = sorted(getattr(host, 'specs', {}) or {})
    if not names: return ''
    keyed, rows = host.api_keyed(), []
    for n in names:
        info, pol = dict(getattr(host, 'spec_info', {}).get(n) or {}), keyed.get(n) or {}
        groups, ops = info.get('groups') or [], info.get('operations')
        bits = [f"{info.get('title') or n} — {ops} operation{'' if ops == 1 else 's'} in "
                f"{len(groups)} group{'' if len(groups) == 1 else 's'}"]
        if groups[:8]: bits.append('groups: ' + ', '.join(groups[:8]) + ('…' if len(groups) > 8 else ''))
        if pol.get('headers'): bits.append('sends ' + ', '.join(pol['headers']))
        if missing := [k for k, ok in (pol.get('env') or {}).items() if not ok]:
            bits.append(f"but nothing here sets {', '.join(missing)}, so a call will fail")
        if pol.get('reach') == 'local': bits.append('local-only: a hosted model may not call it')
        rows.append(f'- `{n}`: ' + '. '.join(bits) + '.')
    return ('\n\n## APIs loaded in this session\n\n' + '\n'.join(rows) + """

These are loaded already — do not `api_load` them again. `api_ops(name=…, match=…)` finds the
operation and `api_call` runs it; say which one answered. A spec marked local-only refuses on a
hosted model rather than sending anything, and the refusal names what to change.""")

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
    if action.tool in {'run_python', 'run_cell'}: return f'{action.tool} (live kernel state)'
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
        # engines outlive backends, so the old accelerator's have to go too, or the next chat is
        # handed the build this call was meant to replace
        if self.engines is not None: self.engines.drop('litert')
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
        engines=True,      # share loaded engines with the rest of the daemon; an `EngineBroker`, or False
        **kwargs
    ):
        from .models import load_models
        from ..runtime.engines import engine_broker
        load_models()
        self.engines = engine_broker() if engines is True else (engines or None)
        host = WorkspaceHost(ws, session)
        from ..settings.settings import agent_cfg
        kwargs.setdefault('cfg', agent_cfg())
        if 'approvals' not in kwargs: kwargs['approvals'] = getattr(ws, 'approvals', None)
        kwargs.setdefault('compact', getattr(ws, 'compact_auto', True))
        kwargs.setdefault('compact_strategy', getattr(ws, 'compact_strategy', 'surgical'))
        kwargs.setdefault('max_tool_calls', getattr(ws, 'tool_budget', 'auto'))
        kwargs.setdefault('max_steps', getattr(ws, 'step_budget', 'auto'))
        kwargs.setdefault('subagent_writes', getattr(ws, 'subagent_writes', False))
        if approve is not None and kwargs.get('approvals') is None:
            kwargs['approvals'] = _PolicyApprovals(approve)
        self.ws, self.surface = ws, surface
        self.session_state = str(getattr(ws, 'agent_state', '') or '')
        self._news_toolset = _news_tools(host)
        self._session_toolset = _session_tools(host)
        self._search_toolset = _search_tools(host, legs=None if surface == 'agent' else FAST_SEARCH_LEGS)
        self.video_jobs = VideoJobs() if video_available() else None
        self._video_toolset = video_tools(host, jobs=self.video_jobs) if self.video_jobs else []
        super().__init__(host, model=model, sp=sp, **kwargs)
        self.mark_surface()
        host.model_local = self.model_local     # a local-only api is gated on the turn model
        self.lend_model()   # so the vault's `ask` uses this session's engine, not a second one
        def user_steering(instruction: str) -> str:
            "Return a user's intervention after a skipped tool call so the agent can redirect its next step."
            return f'User steering after skipping the proposed call: {instruction}'
        self._steering_tool = user_steering
        self.turn_transactions = {}
    def mark_surface(self):
        "Claim the live session for Leela. The CLI shares this log and leaves no such mark."
        from .turns import mark_surface
        mark_surface(getattr(self, 'cfg', None), getattr(self, 'session_id', ''), self.surface)
    def _steered(self, prompt):
        "Fold in a steer that no tool result consumed."
        if self.approvals is None or not isinstance(prompt, str): return prompt
        steer = self.approvals.consume_steer()
        return f'{prompt}\n\nUser steering: {steer}'.strip() if steer else prompt

    def _prepare(self, prompt):
        if self.approvals is not None and hasattr(self.approvals, 'resume'): self.approvals.resume()
        return super()._prepare(self._steered(prompt))

    def cancel(self, run_id='', grace=None):
        "Cancel one run and preserve Leela's pending-approval state."
        run = self.run(run_id)
        if self.approvals is not None:
            if getattr(run, 'kind', 'root') == 'root' and hasattr(self.approvals, 'stop'): self.approvals.stop()
            else: self.approvals.cancel_all('the run was cancelled')
        return super().cancel(run_id, grace)
    def terminate(self, run_id=''):
        "Terminate one run through Ramabana's lifecycle API."
        run = self.run(run_id)
        if self.approvals is not None:
            if getattr(run, 'kind', 'root') == 'root' and hasattr(self.approvals, 'stop'): self.approvals.stop()
            else: self.approvals.cancel_all('the run was terminated')
        return super().terminate(run_id)

    def _be(self, job='turn'):
        "The backend for `job`, on an engine the whole daemon shares rather than a copy of the weights per workspace."
        be = super()._be(job)
        if self.engines is not None: self.engines.attach(be)
        return be

    @property
    def tools(self):
        if self._tools is None:
            registered = {f.__name__ for f in self.registry.tools}
            self.registry.tools.extend(f for f in [*self._news_toolset, *self._session_toolset,
                                                   *self._search_toolset, *self._video_toolset]
                if f.__name__ not in registered)
            if self._steering_tool not in self.registry.tools: self.registry.tools.append(self._steering_tool)
            built = super().tools
            # `_plain` is what the briefing is written from, and `built` is untouched: the turn
            # model keeps the Git writes without being invited to reach for them.
            self._plain = [f for f in self._plain if f.__name__ not in GIT_WRITE_TOOLS]
            return built
        return super().tools

    def _sub_plain(self):
        "No delegated agent gets leela's Git writes, whichever list upstream hands back."
        refused = {*GIT_WRITE_TOOLS, 'user_steering'}
        return [f for f in super()._sub_plain() if f.__name__ not in refused]
    def model_local(self):
        "Whether this turn's model runs on this machine, and what it is called."
        spec = self.spec_or_none()
        return (bool(spec and spec.local), spec.name if spec else 'an unresolved model')
    def system_prompt(self):
        base = super().system_prompt() + api_context(self.host)
        if (writable := self.host.writable_roots) != self.host.roots:
            base += ('\n\n## Writable folders\n\nEvery folder above can be read. Edits and new files may only '
                'land in:\n' + ''.join(f'\n- {r}' for r in writable) + '\n\nA write anywhere else is refused '
                'until the user turns on workspace repository writes in agent settings.')
        layers = getattr(self.ws, 'agent_state_layers', {})
        enabled = [(name, row.get('text', '')) for name, row in layers.items()
            if row.get('enabled', True) and str(row.get('text', '')).strip()]
        if not enabled and self.session_state: enabled = [('task', self.session_state)]
        if enabled:
            base += '\n\n## User-owned starting state\n' + ''.join(
                f'\n### {name.title()} state\n\n{text.strip()}\n' for name, text in enabled)
        if memory := self.memory_context(self.surface, max_chars=BRIEFING_NOTES):
            base += ('\n\n## User-selected memory notes\n'
                'Treat these as durable user context. If a note conflicts with the current request or code, ask rather than guessing.\n\n' + memory)
        return base
    def memory_context(self, surface, max_chars=BRIEFING_NOTES):
        "Ramabana's hook. The completer asks it too, and only this fills it in."
        return self.ws.agent_memory_context(surface, max_chars=max_chars)
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
            'branchable': str(turn_id) in self.checkpoints, 'known': bool(checkpoint or tx),
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
    return tools_for(host, extra=_news_tools(host) + _search_tools(host) + _session_tools(host))
