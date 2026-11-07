"Binding a `Workspace` to the agent harness."

from __future__ import annotations
from ..runtime.kernels import NoVenv, python_for, venv_env
import asyncio, functools, inspect, json, os, re, threading
from fnmatch import fnmatch
from fastcore.all import AttrDict, L, Path, delegates, first
from ... import errstr, leela_cfg
from ..fs.fs import Unsafe
from ..fs.office import is_office, office_text
from ...agent.agent import PERSON_ONLY, SECRET_ARGS, Agent, Approvals, Ask, _hidden, _summary, answer_md, ask_md, plan_tools, preview_for
from ...agent.runtime import current_run
from shalya.core import (MAX_API, MAX_GREP_HITS, MAX_HITS, MAX_TOOL_CHARS,
                         WRITE_TOOLS as HARNESS_WRITE_TOOLS, Refusal, clip, failed, one_line as _1, summary)
from shalya.host import (ApiHost, AskHost, BrowserHost, CodeHost, DENY, GitHost, Host, LocalHost, MemoryHost,
                         NotebookHost, OwnPythonHost, SessionHost, ShellHost, WatchHost, WebHost)
#: `tools_for` stays Ramabana's: it builds the image group from the turn's model, which shalya
#: cannot know. Everything else above is the toolset's own, taken from where it lives.
from ...agent.tools import PATH_WRITES, keep_media, path_write, small_tool, tools_for, write_targets
from ...agent.spec import MAX_OPS, SpecHost
from ...core.session import assigned_names as _assigned
from ..vault.jobs import cadence
from ..memory.memory import PrivacyBlocked, query_refusal, source_kind, withheld_why, withhold_local
from .video import VideoJobs, video_tools

from shalya.core import GIT_READ_TOOLS, GIT_TOOLS, GIT_WRITE_TOOLS
#: Tools the backend can dispatch that no briefing, warm fit, form or picker names. The git writes
#: are not among them: they are briefed, gated by `Interventions` like any write, and undone by the
#: turn's rollback (option A of the phase 5 plan).
HIDDEN = frozenset({'user_steering'})

FAILED_PREFIXES = ('edit failed', 'write failed', 'could not')
VAULT_MARKS = ('\n\nIn vault text, `[EMAIL]`-style placeholders are personal information masked for this model, and `[withheld: …]` '
               'is text it may not see. Neither is the document\'s content: say what is masked rather than guessing it. Rows carry each '
               "document's `level` (open, personal, local) and `doctype`.")
BRIEFING_NOTES = 24_000   #: characters of pinned notes a briefing carries; a completion asks for less
SMALL_BRIEFING = 2000     #: …and what a small profile's briefing gives each of its extra blocks (state, notes)
MAX_ATTRS = 20
NEWS_WRITE_TOOLS = frozenset({'news_follow', 'news_unfollow', 'news_refresh'})
WRITE_TOOLS = HARNESS_WRITE_TOOLS | NEWS_WRITE_TOOLS | frozenset({'run_cell', 'add_demo', 'add_exercise'})   # grade_exercise only adds a note under the learner's checks, so it does not ask

__all__ = ['WorkspaceHost', 'Assistant', 'Interventions', 'ide_tools', 'api_context',
           'notebook_approvals', 'BRIEFING_NOTES', 'MAX_TOOL_CHARS', 'WRITE_TOOLS']

CONTROL_MODES = frozenset({'autopilot', 'guided', 'directed'})
CONTROL_APPROVALS = {'autopilot': 'auto', 'edits': 'edits'}   #: the approvals mode a pane control puts in place while it holds
KEPT = ('policy', 'person', 'loop', 'pause')   #: asks a mode switch leaves for the person
STOP_NOTE = 'the user stopped this turn'
def _restore(tool, args, was_tool, was): return args if tool != was_tool else {**args, **{k: was[k] for k in SECRET_ARGS.get(tool, ()) if k in was}}
def _times(n): return {2: 'twice', 3: 'three times'}.get(n, f'{n} times')
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
        return {**super().dict(), 'args': _hidden(self.tool, self.args), 'control': self.control, 'edited': self.edited,
            'original_tool': self.original_tool, 'original_args': _hidden(self.original_tool, self.original_args),
            'action_id': self.id, 'revision': self.revision, 'branch_id': self.branch_id,
            'parent_action_id': self.parent_action_id,
            'rollback': self.before is not None and self.after is not None and self.before != self.after}

class Interventions(Approvals):
    "Approval queue extended with editable tool calls and teleprompter control levels."
    def __init__(self, *a, control='guided', **kw):
        super().__init__(*a, **kw)
        self.control = control if control in CONTROL_MODES else 'guided'
        self.chosen, self.held = self.control, None   # the pane's choice (edits too), and the mode it replaced
        self.run_policy = None
        self.pause_next = False
        self.queued_steer = ''
        self.stopping = False
        self._state_lock = threading.Lock()
        self._execution_meta = []
    def set_control(self, control):
        "Set the pane's control. Autopilot and edits put their approvals mode in place; the others put back the mode they replaced."
        base = 'autopilot' if control == 'edits' else control
        if base not in CONTROL_MODES: raise ValueError(f'unknown agent control mode {control!r}')
        with self._state_lock: self.control, self.chosen, self.run_policy, self.pause_next = base, control, None, False
        want, was = CONTROL_APPROVALS.get(control), self.held
        if want is None: self.held = None
        elif was is None: self.held = self.mode
        if want is None: return '' if was is None else Approvals.set_mode(self, was)
        return 'approvals: off' if self.held == 'off' else Approvals.set_mode(self, want)
    def set_mode(self, mode):
        "A mode chosen outright; no control puts back an earlier one."
        self.held = None
        return super().set_mode(mode)
    def _settle(self):
        settled = [a for a in self.waiting if a.forced not in KEPT and self.mode != 'ask' and not (self.mode == 'edits' and not self.edits_cover(a.tool))]
        if not settled: return ''
        ok = self.mode != 'off'
        for a in settled: self.answer(a.id, ok, f'answered by /approve {self.mode}')
        return f' · {"approved" if ok else "refused"} what was waiting'
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
            a.after = self._shot(a.tool, a.args)
        with self._state_lock:
            if not ok and self.run_policy and self.run_policy.get('kind') == 'until_failure':
                self.run_policy, self.pause_next = None, True
    def rollback(self, id):
        "Restore one file call only when no later write has changed its resolved output."
        a = first(reversed(self.history), lambda x: x.id == id)
        if a is None or a.before is None or a.after is None: raise ValueError('that call has no file snapshot')
        if path_write(a.tool, a.args): return self._unsave(a)
        path = a.args.get('path')
        if self.host.text_at(path) != a.after: raise ValueError('the file changed after this call; rollback refused')
        self.host.write(path, a.before)
        return path
    def _shot(self, name, args):
        "What a rollback compares: a file's text, or for a drawing which of its pictures exist."
        if path_write(name, args): return {p: self.host.exists(p) for p in write_targets(name, args)}
        return self.host.text_at(args['path'])
    def _unsave(self, a):
        "Remove the pictures a drawing made; one that existed before it cannot be put back."
        if any(a.before.values()): raise ValueError('this drawing replaced an existing picture; rollback refused')
        if self._shot(a.tool, a.args) != a.after: raise ValueError('the pictures changed after this call; rollback refused')
        for p, made in a.after.items():
            if made: self.host.delete(p)
        return ', '.join(a.after)
    def _take_pause(self):
        with self._state_lock: paused, self.pause_next = self.pause_next, False
        return paused
    def _policy_bypasses(self, name, args=None):
        with self._state_lock:
            p = self.run_policy
            if not p: return False
            kind = p['kind']
            if kind in {'once', 'count'}:
                p['remaining'] -= 1
                if p['remaining'] <= 0: self.run_policy = None
                return True
            writes = name in WRITE_TOOLS or path_write(name, args)
            if kind == 'until_write':
                if writes:
                    self.run_policy = None
                    return False
                return True
            if kind == 'reads': return not writes
            return kind in {'until_failure', 'completion'}
    def state(self):
        with self._state_lock:
            return {'control': self.control, 'chosen': self.chosen, 'run_policy': dict(self.run_policy) if self.run_policy else None,
                'pause_next': self.pause_next, 'queued_steer': self.queued_steer, 'stopping': self.stopping}
    def request(self, name, args, force=False, timeout=None, action_id='', revision=0,
        branch_id='main', parent_action_id=''):
        args = dict(args or {})
        required = name in self.tools or path_write(name, args)   # a drawing saved where the call names is a write
        # ramabana's repeat guard: the DOOM_LOOPth identical gated call is put to the person whatever
        # the mode or run policy says; a read between neither counts nor resets the streak
        loop = (force or required) and self._looping(name, args)
        paused = not self.stopping and self._take_pause()
        bypassed = not force and not paused and self._policy_bypasses(name, args)
        # under auto, guided's extra network pauses go: only directed, chosen to step through, still pauses
        control_checkpoint = not bypassed and (self.control == 'directed' or
            (self.control == 'guided' and self.mode != 'auto' and (name in GUIDED_TOOLS or path_write(name, args))))
        checkpoint = force or loop or paused or (required and not bypassed) or control_checkpoint
        a = Intervention(tool=name, args=args, summary=_summary(name, shown := _hidden(name, args)),
            preview=preview_for(name, shown, self.host), control=self.control,
            run_id=getattr(current_run(), 'id', '') or '')
        if path_write(name, args): a.preview = f"saves {', '.join(write_targets(name, args))}\n\n{args.get('prompt', '')}"   # ramabana 0.2.3's preview names only the first
        if loop: a.preview = f'the same call {_times(self._streak)} running -- allow it?\n\n{a.preview}'.strip()
        if action_id: a.id = str(action_id)
        a.revision, a.branch_id, a.parent_action_id = int(revision or 0), branch_id, parent_action_id
        if self.host is not None and args.get('path') and (name in {'edit_file', 'create_file', 'replace_text', 'edit_cell'} or path_write(name, args)):
            a.before = self._shot(name, args)
        self.history.append(a)
        if self.stopping: return a.resolve(False, STOP_NOTE)
        if name in PERSON_ONLY: a.forced = 'person'
        if required and (self.mode == 'off' or self.control != 'directed' or self.rule_for(name, args) is not None):
            # a path write is not in `tools`; a pause still lets the policy, a saved rule or mode off refuse
            if (d := self.decide(name, args, force=name not in self.tools, ask=a, loop=loop or paused)) is not None: return d
        if not a.forced: a.forced = 'loop' if loop else 'pause' if paused else ''
        if not checkpoint: return a.resolve(True)
        with self._lock:
            closing, heard = self.closed, self.listeners > 0 or self.no_listener == 'wait'
            if not closing and heard: self._asks[a.id], self.current = a, a
        if closing: return self._decided(a, False, 'the session is closing')
        if not heard:
            why = (f'the same call {_times(self._streak)} running, and nothing is listening to ask about it' if loop
                   else 'nothing is listening for interventions, so this could not be asked')
            return self._decided(a, False, why)
        self._notify('ask', a)
        wait_for = self.timeout if timeout is None else timeout
        if not a.wait(wait_for):
            with self._lock: late = self._asks.pop(a.id, None) is not None and a.pending
            if late:
                a.resolve(False, f'no answer after {wait_for}s')
                self._notify('answer', a)
        return a
    def answer(self, id, ok, note='', session=False, tool=None, args=None):
        "Resolve a checkpoint; only approval may replace the call that will execute."
        a = self._asks.get(id)
        if a is None or not a.pending: return None
        if ok:
            if tool: a.tool = str(tool)
            if args is not None: a.args = _restore(a.tool, dict(args), a.original_tool, a.original_args)
            shown = _hidden(a.tool, a.args)
            a.summary, a.preview = _summary(a.tool, shown), preview_for(a.tool, shown, self.host)
        if ok and session and self.held is not None: self.held = 'auto'   # session trust outlives the control
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
                        'tool': a.tool, 'args': _hidden(a.tool, dict(a.args))})
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
            # ramabana 0.2.87 passes `args` with each `secret_args` value as `[SECRET]`
            i = first(i for i, row in enumerate(self._execution_meta)
                if row['tool'] == name and _hidden(name, row['args']) == _hidden(name, dict(args or {})))
            return self._execution_meta.pop(i) if i is not None else {}

class WorkspaceHost(CodeHost, NotebookHost, WebHost, BrowserHost, MemoryHost, WatchHost, ApiHost, ShellHost,
                    SessionHost, OwnPythonHost, AskHost, GitHost, Host):
    "A `Workspace`, answering the harness's questions."
    mk_chat = None                          # `Agent.lend_model` fills this; declaring it is the opt-in
    # Leela serves the inspector from inside the kernel process, so this holds for ipykernel too.
    concurrent = True
    #: The kernel this turn's Python runs in, and who the last call ran in: a tab the person clicks mid-turn moves neither.
    _pin = _seen = None
    def __init__(self, ws, session=None): self.ws, self.session, self._bg, self._cells = ws, session, {}, {}
    def new_turn(self):
        "A turn takes the kernel of the tab in front of the person when it first needs one, and keeps it to the end."
        self._pin = None
    @staticmethod
    def _ident(k):
        "Which process answers: the object, then its inspector and pid, which a restart replaces."
        return (None if getattr(k, 'kernel_kind', '') == 'env' else id(k), getattr(k, 'base', None), getattr(k, 'pid', None))
    def _moved(self, k):
        "The line that says this call's kernel is not the last call's, so nothing bound there is here."
        was, self._seen = self._seen, self._ident(k)
        if was is None or was == self._seen: return ''
        if was[0] is not None and was[0] == self._seen[0]: return '[the kernel restarted since your last call: every name you bound is gone]\n'
        return (f"[this ran in the {getattr(k, 'name', '') or 'selected'} kernel, not the one your last call ran in "
                '(the person switched tabs or runtimes, or that kernel closed): every name you bound is gone]\n')
    #: Every group above is declared by inheritance rather than probed.
    @property
    def roots(self): return [str(r) for r in self.ws.fs.roots if r != self.ws.fs.loose]
    @property
    def loose_files(self): return [str(p) for p in self.ws.fs.admitted]
    @property
    def project(self):
        "The folder the agent's commands run in: the chosen one, else the first open."
        root = self.ws.project_root
        return str(root) if root and root != self.ws.fs.loose else (self.roots[0] if self.roots else '')
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
    def read(self, path):
        "A file's text; a Word, PowerPoint or Excel file reads as its Markdown."
        p = self.check(path)
        return office_text(p) if is_office(p) else self.ws.fs.read(p)
    def check_write(self, path):
        target = self.check(path)
        active = Path(self.project).expanduser().resolve() if self.project else None
        if len(self.ws.fs.roots) > 1 and active and not target.is_relative_to(active) and not self.ws.allow_workspace_repo_writes:
            raise Unsafe(f'{path} is readable, but writes to another workspace repository are disabled. '
                f'Writable: {", ".join(self.writable_roots)}. Enable workspace repository writes in '
                'agent settings to write to the other open folders')
        return target
    def write(self, path, text): return self.ws.write_text_at(self.check_write(path), text)
    def exists(self, path):
        "Whether `path` is a file the agent may read; one outside the roots, or missing, is not."
        try: return self.check(path, reading=True).exists()
        except Exception: return False
    def delete(self, path):
        "Remove one file inside the writable roots (a `/rewind` of a created file); one already gone is not an error."
        self.ws.fs._fixed(p := self.check_write(path), 'deleted')
        p.unlink(missing_ok=True)
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
    def web_search(self, query, n=20):
        if why := query_refusal(query): raise PrivacyBlocked(why, 'pii_blocked')
        return self.ws.research.search(query, n=n)
    def read_url(self, url, remember=True): return self.ws.research.read(url, remember=remember)
    def research(self, query):
        if why := query_refusal(query): raise PrivacyBlocked(why, 'pii_blocked')
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
        "What a retrieval does about personal information: a local turn model reads it whole, a hosted one through `vault_pii`."
        if self.model_local is not None and self.model_local()[0]: return 'off'
        return getattr(self.ws, 'vault_pii', 'redact')
    def _hold(self, o):
        "A hosted model never gets a Local-only document: a stored `off` passes Personal text whole, and nothing more."
        if self.model_local is not None and self.model_local()[0]: return o
        return withhold_local(o, self._vault().vault)
    def _typed(self, rows):
        "Rows saying each document's level and type, so a mask or a withheld marker in what follows is explained."
        return [{k: r.get(k) for k in ('id', 'doc_id', 'title', 'kind', 'shelf', 'source', 'added_at', 'level', 'doctype', 'node_id', 'depth', 'page', 'summary')
                 if r.get(k) is not None} for r in self._vault().typed(rows)]
    def memory_search(self, query, limit=8): return self._hold(self._vault().context(query, sections=limit, pii=self._pii))
    def memory_tree(self, document=''): return self._hold(self._vault().toc(document or None, pii=self._pii))
    def memory_read(self, node_id): return self._hold(self._vault().read(node_id, pii=self._pii))
    def memory_forget(self, doc_id): return self._vault(write=True).forget(doc_id)
    def memory_documents(self, limit=50):
        from vishalakshi.pii import gated
        return self._hold(gated(self._typed(self._vault().all_documents(limit)), self._pii, self._vault().vault))
    def memory_sections(self, doc_id):
        rows = self._vault().sections(doc_id, pii=self._pii)
        lv = first(self._typed([dict(doc_id=str(doc_id).split('#')[0])])) or {}
        return self._hold([dict(r, doc_id=str(doc_id).split('#')[0], level=lv.get('level'), doctype=lv.get('doctype')) for r in rows])
    def ask(self, question, ref=None, instruction='', **kw):
        "The vault answers with citations, on this session's model. It chooses its own policy: local when a local runtime exists, else redact; `vault_pii` governs retrieval, not this."
        kw.pop('pii', None)
        if self.mk_chat is not None: kw.setdefault('mk_chat', self.mk_chat)
        v = self._vault().vault
        out = v.ask(question, ref=ref, instruction=str(instruction or ''), **kw)
        if self.model_local is not None and self.model_local()[0]: return out
        from vishalakshi.pii import gated
        # the turn model reads the citations, and under `local` they name what only the local model was shown
        return AttrDict(out, cited=self._hold(gated(L(out.cited), self._pii, v)), context=None, prompt=None)
    def remember(self, text, title=None, tags=(), key=''):
        "File a note; `key` upserts the same note later."
        return self._vault(write=True)._open().note(str(text), title=title, tags=list(tags or []), key=key)
    @property
    def watch_actions(self):
        "Every kind the vault watches, folders included: a vault is always attached here."
        from vishalakshi.acquire import ACTIONS
        return ACTIONS
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
    def read_guard(self, chk):
        "shalya's read guard: a file the vault filed goes to a hosted model as its document's level allows."
        p = str(chk.path)
        if source_kind(p) != 'url':
            q = Path(p).expanduser()
            p = str(q if q.is_absolute() or not self.project else Path(self.project)/q)
        img = chk.kind == 'image'
        sent = self.ws.vault_send(src=p, spec=AttrDict(local=bool(chk.local), name=chk.model or 'an unresolved model'), image=img)
        how = first(sent.rows).how if sent is not None and sent.rows else 'whole'
        if how == 'whole': return None
        if how == 'masked': return self.ws.vault_screened(chk.text or '', sent, Path(p).name)
        return Refusal(withheld_why(Path(p).name, sent), sent.kind, p)
    def _exec_gate(self, text):
        "Refuse code or a command naming a vault document a hosted model may not have whole: its output cannot be masked."
        local, model = self.model_local() if self.model_local is not None else (False, 'an unresolved model')
        vaults = getattr(self.ws, 'vaults', None)
        if local or vaults is None or not str(text or '').strip(): return
        spec = AttrDict(local=False, name=model)
        for v, s, shelf, doc in vaults.sources():
            name = Path(s).name
            if name not in text or source_kind(s) != 'file' or not re.search(rf'(?<![\w.-]){re.escape(name)}(?![\w-])', text): continue
            sent = self.ws.vault_send(ref=(v, shelf, doc), spec=spec, image=True)
            if not sent.ok: raise PrivacyBlocked(withheld_why(Path(s).name, sent) + ' The code was not run.', sent.kind, [doc])
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
        nb.reveal(first(j for j, x in enumerate(nb.cells) if x is c))   # the fold lives in the file, so unfold it there
        nb.save(p, sandbox=self.ws.fs)
        return c.id
    def nb_run_cell(self, path, cell_id, timeout=120):
        "Run one cell in the kernel its notebook's tab runs in, the way the Run button does."
        from ..nb.nb import Notebook, run_watched
        from ...workspace import Tab
        p = self.check(path, must_exist=True)
        nb = Notebook.load(p)
        i = first(i for i, c in enumerate(nb.cells) if c.id == cell_id)
        if i is None: return f'no cell {cell_id!r} in {path}; call notebook_cells for the ids'
        if nb[i].cell_type != 'code': return f'cell {cell_id} is a {nb[i].cell_type} cell; only code cells run'
        if nb.reveal(i): nb.save(p, sandbox=self.ws.fs)
        loop = self._loop()
        if loop is None: return 'no running event loop owns the kernels here, so no cell can be run'
        # an unopened notebook gets the private kernel its tab would have, never the kernel of the tab in front
        tab = first(t for t in getattr(self.ws, 'tabs', []) if str(getattr(t, 'path', '') or '') == str(p)) or Tab(path=str(p), kind='notebook')
        try: k = asyncio.run_coroutine_threadsafe(self.ws.runtime(tab), loop).result(120)
        except NoVenv as e: return e.for_agent
        except Exception as e: return f'could not start the kernel for {path}: {errstr(e)}'
        was, self._cells[str(p)] = self._cells.get(str(p)), self._ident(k)
        note = ('' if was in (None, self._cells[str(p)]) else
                "[this notebook's kernel is not the one your last run_cell here used (it restarted, or closed and started again): names from earlier cells are gone]\n")
        before = self._var_snapshot(k)
        try: c, _ = asyncio.run_coroutine_threadsafe(run_watched(nb, i, k), loop).result(max(1, int(timeout)))
        except TimeoutError: return f'cell {cell_id} has not finished in {timeout}s; it is still running in the kernel'
        except Exception as e: return f'could not run cell {cell_id}: {errstr(e)}'
        if (origins := getattr(self.ws, 'origins', None)) is not None: origins.cell(c, path)
        return note + self._cell_report(path, c, before, k)
    def nb_check_exercise(self, path, cell_id, timeout=120):
        "The learner's exercise cell run and checked as the Check button does, from the open tab's notebook when there is one: the full verdict as JSON text."
        from ..nb.exercise import Refused, check_cell
        from ..nb.nb import Notebook
        from ...workspace import Tab
        p = self.check(path, must_exist=True)
        loop = self._loop()
        if loop is None: return 'no running event loop owns the kernels here, so no cell can be run'
        tab = first(t for t in getattr(self.ws, 'tabs', []) if str(getattr(t, 'path', '') or '') == str(p))
        store = getattr(self.ws, 'docstore', None)
        _, nb, lock = store.owner(str(p)) if tab and store else (None, None, None)
        if nb is None: nb, lock = Notebook.load(p), asyncio.Lock()
        c = first(c for c in nb.cells if c.id == cell_id)
        if c is None: return f'no cell {cell_id!r} in {path}; call notebook_cells for the ids'
        tab = tab or Tab(path=str(p), kind='notebook')
        try: v = asyncio.run_coroutine_threadsafe(check_cell(nb, c, lock, lambda: self.ws.runtime(tab), getattr(self.ws, 'jobs', None)), loop).result(max(1, int(timeout)))
        except Refused as e: return str(e)
        except NoVenv as e: return e.for_agent
        except TimeoutError: return f'cell {cell_id} has not finished in {timeout}s; it is still running in the kernel'
        tab.dirty = True
        return json.dumps(v, indent=1)
    def nb_grade_exercise(self, path, cell_id, score, note):
        "Grade the learner's checked exercise cell in its open tab's notebook, then file a full pass on the learning shelf."
        from ..nb.exercise import Refused, grade_cell
        from ..nb.lesson import exercise_filing, record_exercise
        p = self.check(path, must_exist=True)
        loop = self._loop()
        if loop is None: return 'no running event loop owns the notebooks here, so nothing can be graded'
        tab = first(t for t in getattr(self.ws, 'tabs', []) if str(getattr(t, 'path', '') or '') == str(p))
        store = getattr(self.ws, 'docstore', None)
        _, nb, lock = store.owner(str(p)) if tab and store else (None, None, None)
        if nb is None: return f'{path} is not open in a tab. Open it, check the exercise there, then grade it.'
        c = first(c for c in nb.cells if c.id == cell_id)
        if c is None: return f'no cell {cell_id!r} in {path}; call notebook_cells for the ids'
        async def grade():
            state = grade_cell(nb, c, lock, score, note)
            return state['passed'] and exercise_filing(nb, c, p)
        try: filing = asyncio.run_coroutine_threadsafe(grade(), loop).result(30)
        except Refused as e: return str(e)
        tab.dirty = True
        head = f'Graded {score} of 10.'
        if not filing: return head + ' Not filed on the learning shelf: only a full pass is.'
        try: return f'{head} {record_exercise(self._vault(write=True), filing)}'
        except Exception as e: return f'{head} Not filed on the learning shelf: {errstr(e)}'
    def _var_snapshot(self, k=None):
        "Name to value for every variable `k` (else the agent's kernel) shows, or None when no inspector will say."
        try: return {r['name']: r['value'] for r in self._var_rows(k)}
        except Exception: return None
    def _cell_report(self, path, c, before, k=None):
        "What one run did: its outputs, whether it raised, its execution count, and what moved."
        head = f'ran cell {c.id} of {path}  [In[{c.execution_count}]'
        if c.execution_ms is not None: head += f', {c.execution_ms:.0f} ms'
        after = self._var_snapshot(k)
        changed = ([] if before is None or after is None
                   else sorted(n for n, v in after.items() if before.get(n) != v))
        body = [head + ']', c.text.rstrip() or '(no output)']
        if c.has_error: body.append('the cell raised: the traceback above is from this run')
        body.append('bindings changed: ' + (', '.join(changed) if changed else 'none'))
        return '\n'.join(body)
    def _kernel(self):
        k = (self._pin if getattr(self._pin, 'alive', False) else None) or self.ws.runtime_peek() or self._start_kernel()
        if k is None or not getattr(k, 'base', None) or not hasattr(k, 'api_sync'):
            raise NotImplementedError('no live kernel inspector')
        self._pin = k
        return k
    def _start_kernel(self):
        "Start the tab's kernel for a tool that needs one. `None` where there is no loop to start it on."
        loop = self._loop()
        if loop is None: return None
        try: return asyncio.run_coroutine_threadsafe(self.ws.runtime(), loop).result(120)
        except NoVenv as e: raise RuntimeError(e.for_agent) from None
        except Exception: return None
    def restart_kernel(self):
        "Restart the tab's kernel through the one path the kernel menu uses."
        if self.session is not None: self.session.layer.clear(); return "cleared the agent's layer; no kernel runs behind this session"
        if (loop := self._loop()) is None: raise NotImplementedError('kernel restart needs the workspace loop')
        r = asyncio.run_coroutine_threadsafe(self.ws.restart_kernel(self._pin if getattr(self._pin, 'alive', False) else None), loop).result(120)
        self._seen = None   # asked for, so the next call has nothing to warn about
        return f"restarted the kernel at {r['base']}: every name is gone and saved outputs are stale" if r['base'] else 'no kernel was running; the next run starts a fresh one'
    def _on_loop(self, coro, timeout=60):
        "Run a browser coroutine on the workspace loop: `Browser.cdp` drops every page and cast when asked from another."
        if (loop := self._loop()) is None: coro.close(); raise RuntimeError('the browser needs the workspace loop')
        return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout)
    @property
    def _pages(self): return self.ws.__dict__.setdefault('_agent_pages', [])
    def _agent_page(self, page=''):
        "One page the agent opened: `page`, else the latest. A person's page is never one."
        if not self._pages: raise ValueError('no page is open; call browse(url) first')
        if not page: return self._pages[-1]
        if page not in self._pages: raise ValueError(f'{page} is not a page the agent opened; its pages: {", ".join(self._pages)}')
        return page
    def _on_page(self, page, f, acting=''):
        "Run `f(tid)` on an agent page, refusing one that has wandered where `browse` would not go; `acting` also refuses Leela's own."
        b, tid = self.ws.browser, self._agent_page(page)
        async def go():
            url = (await b.state(tid))['url']
            if acting and b.is_own(url):
                raise PermissionError(f"{acting} is refused on Leela's own page: it could press its own approvals or call its API; use screenshot or page_text")
            if not await b.allowed(url):
                raise PermissionError(f'the page is now at {url}, where browse would not go')
            return await f(tid)
        return self._on_loop(go())
    def browse(self, url):
        from ..browser.browser import DEFAULT_SIZE
        b = self.ws.browser
        url = b.check(url)
        async def go():
            tid = self._pages[-1] if self._pages else None
            if tid:
                try: await b.goto(tid, url)
                except Exception:
                    if tid in {t.id for t in await b.pages()}: raise
                    self._pages.remove(tid); tid = None   # the person closed it
            if tid is None:
                tid = (await b.open(url)).id
                self._pages.append(tid)
                await b.resize(tid, *DEFAULT_SIZE)
            await b.settle(tid)
            st = await b.state(tid)
            if st['url'] in ('', 'about:blank'): raise ConnectionError(f'{url} did not load: Chrome left the tab blank')
            if not await b.allowed(st['url']):
                await (await b.page(tid)).page.navigate(url='about:blank')
                raise PermissionError(f"{url} went on to {st['url']}, where browse would not go")
            return f"{tid}  {st['title'] or '(untitled)'}  {st['url']}"
        return self._on_loop(go(), 90)
    def screenshot(self, page=''):
        "Save the page as a JPEG inside an open folder and return its path; a retaken smaller shot says so in its name."
        shot = self._on_page(page, self.ws.browser.screenshot)
        d = Path(self.ws.cwd_for()).resolve()
        if not any(d.is_relative_to(Path(r).resolve()) for r in self.roots): d = Path(self.project)
        (d := d/'.leela-attachments').mkdir(parents=True, exist_ok=True)
        if not (d/'.gitignore').exists(): (d/'.gitignore').write_text('*\n')
        scaled = f'-scaled-{round(shot.scale * 100)}pct' if getattr(shot, 'scale', 1) < 1 else ''
        (p := d/f'shot-{os.urandom(6).hex()}{scaled}.jpg').write_bytes(shot)
        return str(p)
    def page_text(self, page=''): return self._on_page(page, self.ws.browser.markdown)
    def page_reload(self, page=''):
        b = self.ws.browser
        async def go(tid):
            await b.reload(tid); await b.settle(tid)
            return (await b.state(tid))['title'] or '(untitled)'
        return self._on_page(page, go)
    def page_click(self, page, x, y):
        b = self.ws.browser
        async def click(tid):
            for kind in ('mousePressed', 'mouseReleased'): await b.mouse(tid, kind, x, y)
            return f'clicked {x},{y}'
        return self._on_page(page, click, 'clicking')
    def page_type(self, page, text):
        b = self.ws.browser
        async def type_(tid): await b.insert(tid, text); return f'typed {len(text)} characters'
        return self._on_page(page, type_, 'typing')
    def page_eval(self, page, js):
        b = self.ws.browser
        async def ev(tid):
            v = await (await b.page(tid)).eval(js)
            return v if isinstance(v, str) else json.dumps(v, default=str)
        return self._on_page(page, ev, 'running script')
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
        self._exec_gate(code)
        if self.session is not None:
            before = set(self.session.layer)
            r = self.session.run(code, scope=scope)
            bound = sorted(set(self.session.layer) - before)
            self._note_origin(bound, scope, ok=not r.error)
            return self._session_text(r, bound)
        k = self._kernel()
        note = self._moved(k)
        r = k.api_sync('/agent/api/exec', {'code': code, 'scope': scope})
        failed = bool((r or {}).get('error'))
        bound = self._bound_after(code) if failed and scope == 'overlay' else ()
        self._note_origin(bound if failed else _assigned(code), scope, ok=not failed)
        return note + self._exec_text(r, bound)
    def _note_origin(self, names, scope, ok=True):
        "Attribute what the overlay bound. `isolated` discards its writes, so it binds nothing."
        origins = getattr(self.ws, 'origins', None)
        if names and origins is not None and scope == 'overlay': origins.record(names, 'run_python', ok)
    def run_python(self, code):
        "Run in the agent's own layer over the user's namespace, never in the namespace itself."
        out = self._run(code, 'overlay' if 'overlay' in self.scopes else 'isolated')
        if (m := re.search(r"No module named '([\w]+)", out)) and m[1] in LEELA_PACKAGES:
            out += f"\n[{m[1]} is Leela's, not the project's: run Leela's tools with own_python]"
        return out
    def own_python(self, code, timeout=120):
        "Run in Leela's own kernel: Leela's interpreter and packages, the project folder as cwd, none of the user's names."
        self._exec_gate(code)
        if (loop := self._loop()) is None: raise RuntimeError("Leela's kernel needs the workspace loop")
        async def go(): return await (await self.ws.own_kernel()).execute(code)
        r = asyncio.run_coroutine_threadsafe(go(), loop).result(max(1, int(timeout)) + 60)
        return r.text.rstrip() or (r.error or '(ok)')
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
    def _rows(self, path, k=None):
        r = (k or self._kernel()).api_sync(path, {'profile': 'minimal', 'sort': 'name'})
        return None if r is None else [v for g in r.get('groups', []) for v in g.get('nodes', [])]
    def _var_rows(self, k=None):
        "The merged view `DhrishtiHost` reads: what the user has, plus what this agent has bound."
        if self.session is not None and k is None:
            return [{'name': v.name, 'type': v.type, 'value': v.value}
                    for _, vs in self.session.view('minimal') for v in vs]
        # an `agent='off'` inspector refuses the merged route, and owner-only beats nothing at all
        rows = self._rows('/agent/api/rows', k)
        if rows is None: rows = self._rows('/api/rows', k) or []
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
        self._exec_gate(command)
        d, new_session = self._cwd(cwd), os.name == 'posix'
        # The bundle's interpreter redirection is taken off: a shell command that runs python
        # would otherwise import the app's own standard library.
        p = subprocess.Popen(str(command), shell=True, cwd=str(d), text=True, errors='replace', env=self._env(d),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
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
    def _cwd(self, cwd=None):
        if not self.roots: raise NotImplementedError('no folder is open')
        d = self.check(cwd) if cwd else self.check(self.project)
        return d if d.is_dir() else d.parent
    def _env(self, d):
        env = venv_env(python_for(d, self.ws))
        if not env.get('TERM'): env['TERM'] = 'dumb'   # no tty here, but a tool that reads TERM must find one
        return env
    def run_cmd_bg(self, command, cwd=None):
        "Start `command` in the project with its output in a log file; returns a run id."
        import subprocess, tempfile, uuid
        self._exec_gate(command)
        d = self._cwd(cwd)
        log = tempfile.NamedTemporaryFile('w', prefix='leela-bg-', suffix='.log', delete=False)
        p = subprocess.Popen(str(command), shell=True, cwd=str(d), env=self._env(d), stdin=subprocess.DEVNULL,
                             stdout=log, stderr=subprocess.STDOUT, start_new_session=os.name == 'posix')
        log.close()
        rid = f'cmd_{uuid.uuid4().hex[:8]}'
        self._bg[rid] = (p, Path(log.name))
        return rid
    _bg_run, cmd_output, cmd_stop = LocalHost._bg_run, LocalHost.cmd_output, LocalHost.cmd_stop
    def close(self):
        for rid, (p, log) in list(self._bg.items()):
            if p.poll() is None: self.cmd_stop(rid)
            log.unlink(missing_ok=True)
        self._bg.clear()
    def environment(self):
        "This process, the project's interpreter, the live runtimes and the commands on PATH."
        import shutil, sys
        proj = self.project
        lines = [f'this process: {sys.executable}; inspect_python honours {", ".join(self.scopes)}',
                 f'project python: {(python_for(proj, self.ws) or "none: the person sets up .venv or chooses an interpreter; ask them") if proj else "no folder is open"}',
                 "run_python, inspect_python, run_cell and run_shell use the project's interpreter, which imports only the project's packages; "
                 f"own_python runs on this process's interpreter, with Leela's packages ({', '.join(LEELA_PACKAGES)}) and the project folder as cwd"]
        lines += [f"runtime: {e['name']} ({e['kind']}, pid {e.get('pid')}){' current' if e.get('current') else ''}" for e in self.ws.envs()]
        lines += [f'{c}: {shutil.which(c) or "not on PATH"}' for c in ('python', 'uv', 'git', 'rg', 'ffmpeg')]
        return '\n'.join(lines)
    @property
    def approvals(self): return getattr(self.ws, 'approvals', None)
    def note(self, text):
        fn = getattr(self.ws, 'on_note', None)
        if fn:
            try: fn(text)
            except Exception: pass

#: Packages that are Leela's own tools: they import in `own_python`, never in a project kernel.
LEELA_PACKAGES = ('leela', 'ramabana', 'shalya', 'rupaka', 'abhyasa', 'kosha', 'dhrishti', 'kunda', 'vishalakshi', 'litesearch', 'fossick', 'pullup', 'gheasy', 'nbformat')

def _session_tools(host):
    "The Run button and the demo inserter, as the tools Leela adds to the live session; `inspect_python('')` reads the namespace."
    @summary(lambda a: f'Run {a.get("path","")} cell {a.get("cell_id","?")}')
    def run_cell(path: str, cell_id: str, timeout: int = 120) -> str:
        """Run one notebook cell in the user's live kernel, as pressing Run on it would.
        The source runs as it is on disk, in that notebook tab's kernel, against the user's namespace and execution counter. The notebook file is never written. Take `cell_id` from `notebook_cells`. `run_python` is not a substitute: it runs in your own layer, not the user's.
        """
        try: return clip(host.nb_run_cell(path, cell_id, timeout))
        except Exception as e: return f'run_cell failed: {errstr(e)}'
    @summary(lambda a: f'Add demo to {a.get("path", "")}')
    def add_demo(path: str, spec: dict | str, after_cell_id: str = '') -> str:
        "Insert one markdown demo cell into any `.ipynb`. Demos belong in lesson notebooks."
        from rupaka.spec import validate
        from ..nb.lesson import demo_refusal, fence
        try:
            if isinstance(spec, str): spec = json.loads(spec)
            if errors := validate(spec): return demo_refusal(errors)
            p = host.check_write(path)
            if p.suffix != '.ipynb': return 'add_demo failed: path must be an .ipynb notebook'
            cells = host.nb_cells(str(p))
            index = -1
            if after_cell_id:
                index = first(i + 1 for i, (cid, _, _) in enumerate(cells) if cid == after_cell_id)
                if index is None: return f'no cell {after_cell_id!r} in {path}; call notebook_cells for the ids'
            return host.nb_add_cell(str(p), fence(spec), index=index, cell_type='markdown')
        except Exception as e: return f'add_demo failed: {errstr(e)}'
    @summary(lambda a: f'Add exercise to {a.get("path", "")}')
    def add_exercise(path: str, task: str, fname: str, stub: str, tests: list | str, solution: str,
                     after_cell_id: str = '', uses: list | None = None, packages: list | None = None) -> str:
        "Exercises belong in lesson notebooks. The solution only checks the tests and is never stored. With `packages`, the code runs with those packages, no network and no API key."
        from ..learn.tools import make_tool_env, tool_names
        from ..nb.exercise import check_solution, exercise_cells, validate_exercise_spec
        from ..nb.nb import Notebook
        try:
            if isinstance(tests, str): tests = json.loads(tests)
            spec = validate_exercise_spec(dict(task=task, fname=fname, stub=stub, tests=tests, uses=[] if uses is None else uses))
            if packages is not None:
                if not (made := make_tool_env(names := tool_names(packages))).ok: return f'add_exercise failed: {made.error}'
                spec = validate_exercise_spec(spec | dict(env=made.key, requires=names))
            checked = check_solution(spec, solution)
            ref, draft, n = checked['solution'], checked['stub'], len(spec['tests'])
            if ref.get('timeout'): return 'the solution check times out (timeout)'
            if ref.get('error'): return 'the solution check errors'
            if not ref.get('found'): return 'the solution defines no callable function'
            rows = ref['checks']
            if bad := [t['say'] for t, r in zip(spec['tests'], rows) if r['status'] == 'fail']:
                return 'the solution fails: ' + ', '.join(bad)
            if any(r['status'] == 'timeout' for r in rows): return 'the solution check times out (timeout)'
            if len(rows) != n or any(r['status'] != 'pass' for r in rows): return 'the solution check errors'
            got = [r['status'] for r in draft.get('checks', [])]
            if got.count('pass') == n: return 'the stub already passes every test'
            stub = ('the stub check times out' if draft.get('timeout') else 'the stub check errors' if draft.get('error')
                    else 'the stub defines no callable function' if not draft.get('found')
                    else '; '.join(f'the stub {w} {got.count(s)} of {n} tests' for s, w in (('fail', 'fails'), ('error', 'errors on'), ('timeout', 'times out on')) if s in got)
                    or 'the stub does not pass every test')
            p = host.check_write(path)
            if p.suffix != '.ipynb': return 'add_exercise failed: path must be an .ipynb notebook'
            nb = Notebook.load(p)
            index = first(i + 1 for i, c in enumerate(nb.cells) if c.id == after_cell_id) if after_cell_id else len(nb)
            if index is None: return f'no cell {after_cell_id!r} in {path}; call notebook_cells for the ids'
            task_cell, code = exercise_cells(spec)
            nb.insert(index, task_cell)
            nb.insert(index + 1, code)
            nb.reveal(index + 1)
            nb.save(p, sandbox=host.ws.fs)
            return f'Added the exercise (cells {task_cell.id}, {code.id}). Checked: the solution passes {n} of {n}; {stub}.'
        except Exception as e: return f'add_exercise failed: {errstr(e)}'
    add_exercise.secret_args = ('solution',)
    @summary(lambda a: f'Check {a.get("path", "")} cell {a.get("cell_id", "?")}')
    def check_exercise(path: str, cell_id: str, timeout: int = 120) -> str:
        """Run the learner's exercise code cell and its checks in the notebook's kernel, as pressing Check does.
        Returns JSON: the learner's current source, a summary, and every check with its test, status and what the function returned. Hidden tests are included for you; never show them. Take `cell_id` from `notebook_cells`.
        """
        try: return clip(host.nb_check_exercise(path, cell_id, timeout))
        except Exception as e: return f'check_exercise failed: {errstr(e)}'
    @summary(lambda a: f'Grade {a.get("path", "")} cell {a.get("cell_id", "?")}')
    def grade_exercise(path: str, cell_id: str, score: int, note: str) -> str:
        """Store your grade of the learner's approach on the exercise cell you just checked: `score` is a whole number from 0 to 10, `note` one plain line saying why. Call check_exercise first; a changed source needs a new check. A full pass is filed on the learning shelf. Never put a hidden test or a solution in the note, the page shows it.
        """
        try: return clip(host.nb_grade_exercise(path, cell_id, score, note))
        except Exception as e: return f'grade_exercise failed: {errstr(e)}'
    return [small_tool(run_cell), small_tool(add_demo), small_tool(add_exercise), small_tool(check_exercise), small_tool(grade_exercise)]   # the Run button belongs to a small session too

def _stat_sig(p):
    try: s = Path(p).stat(); return s.st_mtime_ns, s.st_size
    except OSError: return 0, 0

def _code_rows(rows):
    return '\n\n'.join(f"{r['name']} ({r['package']}) {r['path']}:{r['line']}" + ''.join(f'\n{x}' for x in (r['doc'], r['snippet']) if x) for r in rows)

def _lesson_tools(host, env):
    "The tools Leela adds only while the active tab is a lesson; `env()` gives that lesson's tool environment key and packages at call time."
    @summary(lambda a: f'Look up code for {_1(a.get("q"))}')
    def look_up_code(q: str) -> str:
        "Search the code index for `q`: the lesson's library packages when it has a tool environment, else the project. Returns name, package, path:line, doc and a short snippet per hit."
        from ..learn.app import NO_INDEX, find_code
        key, names = env()
        try: rows = find_code(host.ws.search, q, list(names), key)
        except Exception: rows = None
        return NO_INDEX if rows is None else clip(_code_rows(rows)) if rows else 'Nothing found.'
    return [small_tool(look_up_code)]

def _news_tools(host, mx=MAX_TOOL_CHARS):
    "The feeds as tools. The memory tools read the main shelf; feeds are on `news`. What the loaded specs send is `api_context`, in the briefing."
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
    return [small_tool(f) for f in (news_feeds, news_latest, news_story, news_follow, news_unfollow, news_refresh)]   # gated by a followed feed, whatever the profile

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
        else: bits.append('no credentials: calls go out unauthenticated')
        if missing := [k for k, ok in (pol.get('env') or {}).items() if not ok]:
            bits.append(f"but nothing here sets {', '.join(missing)}, so a call will fail")
        if pol.get('reach') == 'local': bits.append('local-only: a hosted model may not call it')
        rows.append(f'- `{n}`: ' + '. '.join(bits) + '.')
    return ('\n\n## APIs loaded in this session\n\n' + '\n'.join(rows) + """

These are loaded already — do not `api_load` them again. `api_ops(name=…, match=…)` finds the
operation and `api_call` runs it; say which one answered. A spec marked local-only refuses on a
hosted model rather than sending anything, and the refusal names what to change.""")

def notebook_approvals(get_target, tools=WRITE_TOOLS, mode='ask', timeout=300, host=None, rules_path=None):
    "An `Approvals` that writes the whole exchange into the notebook."
    from ..nb.nb import Cell
    def _add(md, meta):
        t = get_target()
        if not t: return None
        nb, i = t[0], at_cell(*t)
        if i < 0: return None
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
                f'\n\n```json\n{json.dumps(_hidden(a.tool, a.args), indent=2, default=str)}\n```')
        _add(md, {'kind': 'approval', 'id': a.id, 'tool': a.tool,
            'state': 'approved' if a.answer else 'refused',
            'edited': bool(getattr(a, 'edited', False))})
    return Interventions(tools=tools, mode=mode, timeout=timeout, host=host, rules_path=rules_path,
        on_ask=on_ask, on_answer=on_answer)

def _irreversible(action):
    "How a completed action reads in the turn's irreversible list, or None if restoring files undoes."
    if action.tool == 'memory_forget': return f"memory_forget ({action.args.get('doc_id', 'unknown document')})"
    if action.tool in {'run_python', 'run_cell'}: return f'{action.tool} (live kernel state)'
    if action.tool == 'own_python': return "own_python (Leela's kernel state, and any file it wrote)"
    if action.tool == 'run_shell': return f"run_shell ({action.args.get('command', 'command')})"
    if action.tool in GIT_WRITE_TOOLS: return action.tool
    return None

def at_cell(nb, ref):
    "Where `ref` is in `nb` now: an index as is, a Cell by identity, -1 once it has gone."
    return ref if isinstance(ref, int) else next((j for j, c in enumerate(nb.cells) if c is ref), -1)

def _n_approvals(nb, i):
    "How many approval cells already sit below the prompt cell at `i`."
    n = 0
    for c in nb.cells[i + 1:]:
        if getattr(c, 'approval', None) is None: break
        n += 1
    return n

FRESH_HINT = 'Start a new conversation with + at the top of the agent panel; this one stays in the agent history.'   #: what a turn too large for any window says in Leela

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
        warm=False,        # seed a fresh conversation with dhrona's accepted rounds
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
        from ...workspace import SUBAGENT_SETTINGS
        for k in SUBAGENT_SETTINGS:
            if (v := getattr(ws, k, None)) is not None: kwargs.setdefault(k, v)
        kwargs.setdefault('verify', getattr(ws, 'verify', ''))
        kwargs.setdefault('fresh_hint', FRESH_HINT)
        kwargs.setdefault('optin', tuple(getattr(ws, 'agent_optin', ()) or ()))
        kwargs.setdefault('profile', getattr(ws, 'agent_profile', 'auto') or 'auto')   # `auto`: small for a local or ≤32k model
        if approve is not None and kwargs.get('approvals') is None:
            kwargs['approvals'] = _PolicyApprovals(approve)
        self.ws, self.surface = ws, surface
        self.session_state = str(getattr(ws, 'agent_state', '') or '')
        self._news_toolset = _news_tools(host)
        self._session_toolset = _session_tools(host)
        self._lesson_toolset = _lesson_tools(host, lambda: self._lesson_env())
        self._lesson_seen = (None, None)   # (seal, (step, packages)) of the last learning-store read
        self.video_jobs = VideoJobs()   # offered with no video model too, so asking for one says how to add it
        self._video_toolset = video_tools(host, jobs=self.video_jobs)
        self._built_mode = None            # whether a feed was followed when the tool list was last built
        self._briefed_mode = None          # …and the one the live turn backend was last briefed with
        self._briefed_lesson, self._briefed_charter = False, ''   # the lesson charter text the live turn backend was briefed with
        super().__init__(host, model=model, sp=sp, warm=warm, **kwargs)
        from ...workspace import AGENT_CHANNELS
        for k, attr in AGENT_CHANNELS.items(): setattr(self, attr, getattr(ws, k, '') or '')
        self.mark_surface()
        host.model_local = self.model_local     # a local-only api is gated on the turn model
        self.lend_model()   # so the vault's `ask` uses this session's engine, not a second one
        def user_steering(instruction: str) -> str:
            "Return a user's intervention after a skipped tool call so the agent can redirect its next step."
            return f'User steering after skipping the proposed call: {instruction}'
        self._steering_tool = small_tool(user_steering)   # the refusal path rewrites a rejected call to it, in every profile
        self.turn_transactions = {}
    def resume_session(self, selector='latest', keep_model=True):
        "Continue a stored conversation on the model picked here, not the one it last ran."
        return super().resume_session(selector, keep_model=keep_model)
    def mark_surface(self):
        "Claim the live session for Leela. The CLI shares this log and leaves no such mark."
        from .turns import mark_surface
        mark_surface(getattr(self, 'cfg', None), getattr(self, 'session_id', ''), self.surface)
    def _with_steer(self, prompt):
        "Fold in a steer that no tool result consumed."
        if self.approvals is None or not isinstance(prompt, str): return prompt
        steer = self.approvals.consume_steer()
        return f'{prompt}\n\nUser steering: {steer}'.strip() if steer else prompt

    def _prepare(self, prompt):
        self.host.new_turn()
        if self.approvals is not None and hasattr(self.approvals, 'resume'): self.approvals.resume()
        self._follow_mode()
        return super()._prepare(self._with_steer(prompt))

    def _mode(self):
        "What the tool set follows: whether a feed is followed."
        feeds = getattr(self.ws, 'feeds', None)
        return feeds is not None and any(True for _ in feeds)

    def _lesson_nb(self):
        "The active tab's notebook when it is a lesson notebook, else None."
        from ..nb.nb import Notebook
        tab = getattr(self.ws, 'tab', None)
        if tab is None or tab.kind != 'notebook' or not tab.path: return None
        try: nb = Notebook.load(self.host.check(tab.path))
        except Exception: return None
        return nb if nb.meta.get('lesson') else None
    def _lesson(self): return self._lesson_nb() is not None
    def _lesson_env(self, nb=None):
        "`(key, packages)` of the active lesson's one tool environment; `(None, ())` for none."
        from ..nb.lesson import env_packages, lesson_env
        if nb is None and (nb := self._lesson_nb()) is None: return None, ()
        return (key := lesson_env(nb)), env_packages(key)
    def _lesson_ctx(self):
        "`(step, packages)` of the active lesson, None outside one. The learning store is read again only when the notebook, its lesson meta, the store file or its WAL, or the environment changed; a store error gives no step and is not kept."
        from ..nb.lesson import lesson_step
        if (nb := self._lesson_nb()) is None: return None
        key, packages = self._lesson_env(nb)
        mem = getattr(self.ws, 'memory', None)
        db = getattr(mem, 'path', None)
        seal = (str(self.ws.tab.path), json.dumps(nb.meta['lesson'], sort_keys=True, default=str), key, packages, id(mem),
                *(_stat_sig(f) for f in ((db, Path(f'{db}-wal')) if db else ())))
        if self._lesson_seen[0] == seal: return self._lesson_seen[1]
        try: step = lesson_step(mem, nb) if mem is not None else None
        except Exception:
            self._lesson_seen = (None, None)
            return None, packages
        self._lesson_seen = (seal, (step, packages))
        return step, packages
    def _charter(self):
        "The lesson charter for the active tab, with its walk step and packages; '' outside a lesson."
        from ..nb.lesson import lesson_charter
        return '' if (c := self._lesson_ctx()) is None else lesson_charter(*c)
    def _follow_mode(self):
        "Re-brief the live turn backend when a feed came or went, the active tab became or stopped being a lesson notebook, or the lesson charter's text changed, since it was last briefed. A form or a route may rebuild `tools` between turns; the backend's own briefing is what counts. A turn with no change rebuilds nothing."
        from ..nb.lesson import CHARTER_TAIL
        if self._briefed_mode is None: self._briefed_mode = self._built_mode   # a backend installed from outside (`tests.fakemodel`) was briefed with what `tools` built
        mode, charter = self._mode(), self._charter()
        lesson = bool(charter)
        if (self._briefed_mode is None or mode == self._briefed_mode) and lesson == self._briefed_lesson and charter == self._briefed_charter:
            self._briefed_mode = mode
            return
        self._forget()
        be = self._be('turn')
        prompt = self.system_prompt()
        be.refresh(prompt, self.tools)
        self._briefed_mode, self._briefed_lesson = mode, CHARTER_TAIL in prompt
        self._briefed_charter = charter if self._briefed_lesson else ''

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
        spec = self.routing.spec(job); fresh = (spec.backend, spec.model_id) not in self._backends
        be = super()._be(job)
        if fresh and job == 'turn':
            from ..nb.lesson import CHARTER_TAIL
            self._briefed_mode, self._briefed_lesson = self._built_mode, CHARTER_TAIL in be.sp
            self._briefed_charter = c if self._briefed_lesson and (c := self._charter()) and c in be.sp else ''
        if self.engines is not None: self.engines.attach(be)
        return be

    @property
    def tools(self):
        "Leela's own tools on the registry: news tools while a feed is followed, lesson tools while the active tab is a lesson, the rest always."
        if self._tools is None:
            feeds = mode = self._mode()
            want = [*(self._news_toolset if feeds else []), *(self._lesson_toolset if self._lesson() else []), *self._session_toolset, *self._video_toolset]
            stale = {id(f) for f in [*self._news_toolset, *self._lesson_toolset]} - {id(f) for f in want}
            self.registry.tools[:] = [f for f in self.registry.tools if id(f) not in stale]
            registered = {f.__name__ for f in self.registry.tools}
            self.registry.tools.extend(f for f in want if f.__name__ not in registered)
            if self._steering_tool not in self.registry.tools: self.registry.tools.append(self._steering_tool)
            self._built_mode = mode
            return super().tools
        return super().tools

    @property
    def skills(self):
        "Ramabana's skills and Leela's own `leela` skill, which sits on the registry outside any mod, as Leela's tools do."
        from .skill import SKILL_NAME, skill_for
        reg = self.registry
        if not any(s.name == SKILL_NAME for s in reg.skills): reg.skills.append(skill_for(self))
        return super().skills

    @property
    def _plain(self):
        "What the model is offered: everything but `user_steering`, which is dispatchable after a refusal and never advertised."
        return [f for f in super()._plain if f.__name__ not in HIDDEN]

    def _sub_plain(self, spec=None):
        "A delegated agent gets neither the Git writes (briefed to the main agent, not delegable) nor `user_steering`, on top of `ROOT_ONLY` (delegation, the plan) which ramabana's own `_sub_plain` already drops. Its own set, not `HIDDEN`."
        refused = {*GIT_WRITE_TOOLS, 'user_steering'}
        return [f for f in super()._sub_plain(spec) if f.__name__ not in refused]
    def model_local(self):
        "Whether this turn's model runs on this machine, and what it is called."
        spec = self.spec_or_none()
        return (bool(spec and spec.local), spec.name if spec else 'an unresolved model')

    def system_prompt(self):
        "Ramabana's briefing, then Leela's blocks. A small profile gets the same blocks clipped to `SMALL_BRIEFING`, and one line where a paragraph was."
        small = self.profile == 'small'
        base = super().system_prompt() + api_context(self.host)   # '' unless a spec is loaded, in either profile
        base += VAULT_MARKS
        if charter := self._charter(): base += '\n\n' + charter
        if loose := getattr(self.host, 'loose_files', ()):
            base += f'\n\nLoose files: {", ".join(loose)}. Each was opened on its own: read and edit it, but nothing beside it is yours to touch.'
        if (writable := self.host.writable_roots) != self.host.roots:
            base += (f'\n\nWritable folders: {", ".join(writable)}. A write anywhere else is refused.' if small else
                '\n\n## Writable folders\n\nEvery folder above can be read. Edits and new files may only '
                'land in:\n' + ''.join(f'\n- {r}' for r in writable) + '\n\nA write anywhere else is refused '
                'until the user turns on workspace repository writes in agent settings.')
        if self.surface == 'agent':
            base += ('\n\nThe user can run a `bash` fence from your reply with its run button; you never see the output.' if small else
                '\n\nThe user can run a `bash`, `sh` or `zsh` fence in your reply with its run button. It runs in the project '
                'folder and reads no input, so it cannot answer a password prompt. Its output is shown to them, not to you. '
                'When a command should run as the user -- one that relies on their logged-in tools or keys, or one your tools '
                'refuse -- give it in a `bash` fence, ask them to run it, and ask them to paste back the part of the output you need.')
        layers = getattr(self.ws, 'agent_state_layers', {})
        enabled = [(name, row.get('text', '')) for name, row in layers.items()
            if row.get('enabled', True) and str(row.get('text', '')).strip()]
        if not enabled and self.session_state: enabled = [('task', self.session_state)]
        if enabled:
            state = ''.join(f'\n### {name.title()} state\n\n{text.strip()}\n' for name, text in enabled)
            base += '\n\n## User-owned starting state\n' + (clip(state, SMALL_BRIEFING) if small else state)
        if memory := self.memory_context(self.surface, max_chars=SMALL_BRIEFING if small else BRIEFING_NOTES):
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
            'git': list(self.git_undo.get(self.current_turn_id, [])),   # each with gheasy's `undo` token
            'git_state': self._repo_state() if self.git_undo.get(self.current_turn_id) else ('', ''),   # (head, branch) after the turn
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
        files, git = list((tx.get('files') or {}).keys()), list(tx.get('git') or [])
        return {'revisable': revisable, 'undoable': bool(files or [g for g in git if g.get('undo')]) and not tx.get('rolled_back'),
            'branchable': str(turn_id) in self.checkpoints, 'known': bool(checkpoint or tx),
            'files': files, 'git': git, 'irreversible': list(tx.get('irreversible') or [])}
    def _keep_undo(self, name, out):
        "ramabana keeps the undo token; the row also remembers which repository it belongs to, so a multi-root rollback can say what it cannot reach."
        super()._keep_undo(name, out)
        try: root = json.loads(out).get('root')
        except Exception: return
        rows = self.git_undo.get(self.current_turn_id) or []
        if root and rows and 'root' not in rows[-1]: rows[-1]['root'] = str(root)
    def _dirty_paths(self):
        "Tracked files with uncommitted changes in the project repository, as absolute paths (a rename counts by its new name)."
        from gheasy.repo import GitRepo
        root = Path(self.host.roots[0])
        out = str(GitRepo.at(root).run('status', '--porcelain', '--untracked-files=no'))
        return [str((root/line[3:].split(' -> ')[-1].strip().strip('"')).resolve()) for line in out.splitlines() if line.strip()]
    def _repo_state(self):
        "`(head, branch)` of the project repository, or `('', '')` without one."
        try:
            from gheasy.repo import GitRepo
            r = GitRepo.at(self.host.roots[0])
            return str(r.run('rev-parse', 'HEAD')).strip(), str(r.run('branch', '--show-current')).strip()   # `info()` may answer from its cache
        except Exception: return '', ''
    def rollback_turn(self, turn_id):
        "Atomically restore every unchanged artifact from a completed turn: its git writes first (a checkout undone puts the tree where the file texts were taken from), then its files. Refused, touching nothing, when a file or HEAD moved after the turn: a git undo is a hard reset to before the turn, and it must not take a later commit with it."
        tx = self.turn_transactions.get(str(turn_id))
        if tx is None: raise KeyError(f'no transaction for {turn_id}')
        if tx['rolled_back']: raise ValueError('that turn was already rolled back')
        conflicts = [p for p, snap in tx['files'].items() if self.host.text_at(p) != snap['after']]
        if conflicts: raise ValueError('changed after the turn: ' + ', '.join(conflicts))
        writes = [g for g in tx.get('git') or [] if g.get('undo')]
        if writes:
            here = Path(self.host.roots[0]).resolve()
            if foreign := [g['root'] for g in writes if g.get('root') and Path(g['root']).resolve() != here]:
                raise ValueError(f"git writes in {foreign[0]} can't be undone from here (the rollback runs in {here}) — undo refused")
            (head, branch), (now, on) = tx.get('git_state') or ('', ''), self._repo_state()
            if not head or not now: raise ValueError('git state unknown: the repository could not be read before or after the turn — undo refused')
            if head != now or branch != on:
                raise ValueError(f'HEAD moved after the turn: {head[:12]} on {branch} .. {now[:12]} on {on} — undo refused')
            own = {str(Path(p).resolve()) for p in tx['files']}
            if outside := [p for p in self._dirty_paths() if p not in own]:
                raise ValueError("uncommitted changes outside this turn's files: " + ', '.join(outside)
                                 + ' — a git undo would discard them; commit or stash them first — undo refused')
            tx['git_result'] = self._undo_git_writes(writes)
        for path, snap in tx['files'].items(): self.host.write(path, snap['before'])
        tx['rolled_back'] = True
        return tx
    def _undo_git_writes(self, writes):
        "Apply the turn's git `undo` tokens, newest first, stopping at the first gheasy refuses: the error names what was already undone and that HEAD moved with it, so a retry meets the HEAD guard rather than applying a token twice. The turn stays undoable."
        from gheasy.repo import GitRepo
        repo, undone = GitRepo.at(self.host.roots[0]), []
        for w in reversed(writes):
            try: repo.undo(w['undo']); undone.append(w)
            except Exception as e:
                names = ', '.join(f"{u['tool']} ({u.get('summary') or u.get('undoes') or u['undo']})" for u in undone) or 'none'
                head, _ = self._repo_state()
                raise ValueError(f"undid {len(undone)} git write(s) — already undone: {names}; HEAD moved to {head[:12]} as a result, "
                                 f"so the turn's later undo is refused until you look at the tree; {w['tool']}: {errstr(e)}")
        return f'undid {len(undone)} git write(s)'

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
        @functools.wraps(run)
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
                    out = keep_media(f'{out}\n\nUser steering for the next decision: {steer}', out)
            return out
        if (ro := getattr(f, 'read_only', None)) is not None: wrapper.read_only = self._record(ro)   # what a read-only view is handed
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

class _PolicyApprovals(Approvals):
    "An `Approvals` wrapping a plain `approve(tool_call) -> bool`."
    def __init__(self, approve):
        super().__init__(tools=WRITE_TOOLS, mode='ask')
        self._approve = approve
    def request(self, name, args, force=False, timeout=None):
        "`force` and `timeout` are the base signature's; a plain policy answers at once either way."
        a = Ask(tool=name, args=args, summary=_summary(name, args), preview=preview_for(name, args))
        self.history.append(a)
        try: ok = self._approve({'function': {'name': name, 'arguments': args}})
        except Exception as e: return a.resolve(False, errstr(e))
        return a.resolve(bool(ok))

def ide_tools(ws, session=None):
    "Every tool the agent gets, bound to one `Workspace`."
    host = WorkspaceHost(ws, session)
    feeds = getattr(ws, 'feeds', None)
    news = _news_tools(host) if feeds is not None and any(True for _ in feeds) else []
    return tools_for(host, extra=news + _session_tools(host), optin=tuple(getattr(ws, 'agent_optin', ()) or ()))
