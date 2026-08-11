"""Binding a `Workspace` to the agent harness.

This file used to be the assistant. It is now the *adapter*: `leela.agent` is the brain
and knows nothing about the rest of leela, and everything it needs arrives through `Host`.
What is left here is the part that genuinely belongs to the application -- how a leela
workspace answers the harness's questions, and how an approval turns into a conversation
in a notebook.

Two application-side decisions live here rather than in the harness:

**Approval reads as a conversation, in the document.** `notebook_approvals` writes each
request and each answer into the notebook as markdown cells beside the prompt cell that
caused them. So a refusal and its reason are saved with the work, read in order with
everything else, and legible next week -- and in plain Jupyter, where they are just
markdown. The harness supplies the queue and the rendering; the notebook is leela's idea
of where a conversation lives.

**Activity is saved with the answer.** A prompt cell's reply gets the tool calls folded
underneath it, so a notebook read later still shows which files the answer came from.

`Assistant` and `ide_tools` survive as thin aliases because the web app and tests
call them by name, and renaming things that work is not a feature.
"""

from __future__ import annotations

import functools, inspect, json, os, threading

from ... import errstr, leela_cfg
from ..fs.fs import  Unsafe
from ...agent.agent import (Activity, Agent, Approvals, Ask, Completer, _summary, answer_md, ask_md,
                          preview_for)
from ...agent.tools import (MAX_TOOL_CHARS, WRITE_TOOLS as HARNESS_WRITE_TOOLS, Hit, Host, clip,
                          tools_for)

GIT_WRITE_TOOLS = frozenset({'git_fetch', 'git_checkout', 'git_pull', 'git_push'})
WRITE_TOOLS = HARNESS_WRITE_TOOLS | GIT_WRITE_TOOLS

__all__ = ['WorkspaceHost', 'Assistant', 'Completer', 'Interventions', 'ide_tools',
           'notebook_approvals', 'MAX_TOOL_CHARS', 'WRITE_TOOLS']

# The web teleprompter has three levels. Guided adds checkpoints for calls that cross a
# process boundary; ordinary repository reads remain automatic. Directed stops at every
# locally executed tool. The original write policy remains in force in all three modes.
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
        with self._state_lock:
            self.control, self.run_policy, self.pause_next = control, None, False
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
        a = next((x for x in reversed(self.history) if x.id == id), None)
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
        # The write policy and the teleprompter policy are independent. “Approve later
        # writes” must not accidentally disable directed mode or guided network checks.
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
        # Approval and rejection are deliberately separate workflows. An approval owns a
        # live call, so its edited arguments must become that call. A rejection executes
        # nothing: retaining the original proposal preserves attribution and, importantly,
        # lets a person reject a malformed call without first repairing its form.
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
                # A bare backend denial is too weak: models commonly interpret it as a
                # transient permission failure and immediately propose the same call again.
                # Resolve through a harmless result that records rejection as a durable
                # instruction. A human note adds direction, but is not required for “no”.
                instruction = ('The user rejected this tool call. Do not retry this call or an '
                               'equivalent action unless the user explicitly asks for it later.')
                if a.note: instruction += f' User direction: {a.note}'
                fn['name'], fn['arguments'] = 'user_steering', {'instruction': instruction}
                return True
        return a

    def execution_meta(self, name, args):
        "Consume identity recorded by the approval hook before the wrapped tool executes."
        with self._state_lock:
            i = next((i for i, row in enumerate(self._execution_meta)
                      if row['tool'] == name and row['args'] == dict(args or {})), None)
            return self._execution_meta.pop(i) if i is not None else {}


class WorkspaceHost(Host):
    """A `Workspace`, answering the harness's questions.

    Almost every method is one line, which is the point: `Workspace` already had all of
    this, it was simply reachable only by importing it. Anything the workspace cannot do
    raises `NotImplementedError`, and the harness responds by not offering that tool at
    all -- so an IDE with no kernel bound yet has an agent that reads and edits and does
    not keep trying to run Python.
    """

    def __init__(self, ws, session=None):
        self.ws, self.session = ws, session

    # -- where it is allowed to be -------------------------------------------
    @property
    def roots(self): return [str(r) for r in self.ws.fs.roots]

    def check(self, path, must_exist=False):
        try: return self.ws.fs._check(path, must_exist=must_exist)
        except Unsafe as e:
            # Keep the sandbox refusal, but tell the model what is actually open. A local
            # model can copy an absolute path with one wrong digit; without this context it
            # retries guesses even though the intended notebook is visibly open in Leela.
            opened = [t.path for t in self.ws.tabs if t.path]
            hint = f'; open files: {", ".join(opened[-5:])}' if opened else ''
            raise Unsafe(f'{e}{hint}') from e
    def walk(self): return list(self.ws.fs.walk())
    def read(self, path): return self.ws.fs.read(self.check(path))
    def write(self, path, text): return self.ws.fs.write(path, text).path
    def text_at(self, path): return self.ws.text_at(path)

    # -- seeing the code -----------------------------------------------------
    def search(self, query, limit=20): return self.ws.search.agent_search(query, limit=limit)
    def peers(self, path, line, limit=20): return self.ws.search.peers(path, line, limit=limit)
    def symbols(self, path): return self.ws.search.symbols(path)

    @property
    def search_note(self):
        s = self.ws.search
        return f'{s.backend}: {s.note}' if s.note else str(s.backend)

    # -- reading the web -----------------------------------------------------
    def web_search(self, query, n=20): return self.ws.research.search(query, n=n)
    def read_url(self, url, remember=True): return self.ws.research.read(url, remember=remember)

    def research(self, query):
        _, digest = self.ws.research.dig(query)
        return digest

    @property
    def research_note(self): return self.ws.research.note

    # -- durable research memory --------------------------------------------
    def memory_search(self, query, limit=8): return self.ws.memory.context(query, sections=limit)
    def memory_tree(self, document=''): return self.ws.memory.toc(document or None)
    def memory_read(self, node_id): return self.ws.memory.read(node_id)
    def memory_topics(self, limit=12): return self.ws.memory.clusters(limit)
    def memory_forget(self, doc_id): return self.ws.memory.forget(doc_id)

    # -- notebooks -----------------------------------------------------------
    def nb_cells(self, path):
        from ..nb.nb import Notebook
        return [(c.id, c.cell_type, c.source) for c in Notebook.load(self.check(path)).cells]

    def nb_add_cell(self, path, source, index=-1, cell_type='code'):
        from ..nb.nb import Cell, Notebook
        p = self.check(path)
        nb = Notebook.load(p) if p.exists() else Notebook.blank(p)
        c = nb.insert(len(nb) if index < 0 else int(index), Cell(source=source, cell_type=cell_type))
        # `Notebook.blank` seeds one empty cell so a human always has somewhere to type.
        # Filling a notebook by tool call does not need that, and leaving it behind means
        # every agent-created notebook opens with a stray blank cell at the top.
        if len(nb) == 2 and not nb[0].source.strip() and nb[1] is c: nb.delete(0)
        nb.save(p, sandbox=self.ws.fs)
        return c.id

    # -- the live session ----------------------------------------------------
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

    def run_python(self, code):
        if self.session is not None:
            r = self.session.run(code)
            if r.error: return r.error
            out = r.stdout or ''
            if r.result is not None: out += ('\n' if out else '') + r.result.value
            return out or '(ok)'
        # The web agent lives outside the kernel. Its approved write tool reaches the
        # owner namespace through the authenticated inspector, exactly like the exec bar.
        return self._exec_text(self._kernel().api_sync('/api/exec', {'code': code, 'scope': 'global'}))

    def inspect_python(self, code, scope='isolated'):
        """Read-only execution: `AgentSession`'s own scopes, which leela already had.

        Neither scope can change what the user made -- `isolated` because it runs on a copy
        in a safepyrun allowlist, `overlay` because the AST policy refuses to delete,
        rebind or mutate an owner name and sends the agent's own bindings to its layer
        instead. So both are safe to hand to an agent nobody is watching, and the choice is
        about how much Python the question needs rather than how much trust it gets.

        A workspace opened with `agent_scope='isolated'` refuses overlay and says so, which
        is the setting for a machine where the agent's own scratch layer is not wanted.
        """
        if scope not in self.scopes:
            return (f'scope {scope!r} is not available here (allowed: {", ".join(self.scopes)}); '
                    'the workspace was opened with a narrower agent scope')
        if self.session is not None:
            r = self.session.run(code, scope=scope)
            if r.error: return r.error
            out = r.stdout or ''
            if r.result is not None: out += ('\n' if out else '') + r.result.value
            return out or '(ok)'
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

    # -- running a command ---------------------------------------------------
    def run_cmd(self, command, cwd=None, timeout=120):
        """Run one command in the project, the way the user would run it in leela's terminal.

        A subprocess rather than the kernel: `pytest`, `git` and `ruff` are programs, not
        Python, and running them through the user's kernel would mean the agent's test run
        shares a process with the user's variables. The terminal is the right model, and
        `read_terminal` already showed the agent the *other half* of this -- what the user
        ran. This is its own half.

        Confinement is the working directory, which `check` resolves and refuses outside
        the open folders. That is honestly all it is: a shell can name any path, so a
        command is a *write* everywhere it matters and goes to a person for approval like
        one. The sandbox that matters here is the human.
        """
        import os, signal, subprocess
        if not str(command or '').strip(): return 0, ''      # the capability probe
        roots = self.roots
        if not roots: raise NotImplementedError('no folder is open')
        d = self.check(cwd) if cwd else self.check(roots[0])
        if not d.is_dir(): d = d.parent
        # Its own session, so a timeout can kill the whole tree. `pytest -n 4` or anything
        # behind a pipe leaves children that outlive the shell, and a leaked test runner
        # holding a port is a failure the *next* run reports, in a way nobody can trace.
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
        roots = self.roots
        return f'commands run in {roots[0]}' if roots else 'no folder is open'

    # -- the person ----------------------------------------------------------
    @property
    def approvals(self): return getattr(self.ws, 'approvals', None)

    def note(self, text):
        fn = getattr(self.ws, 'on_note', None)
        if fn:
            try: fn(text)
            except Exception: pass


# ---------------------------------------------------------------------------
# application tools
# ---------------------------------------------------------------------------
def _git_tools(host):
    """Git operations bound to an open repository and kept inside workspace roots."""
    from pathlib import Path
    from ..git.git import GitRepo

    def repo(path=''):
        roots = [Path(r).expanduser().resolve() for r in host.roots]
        if not roots: raise ValueError('open a project folder first')
        selected = host.check(path or roots[0], must_exist=True)
        found = GitRepo.at(selected)
        # Git can discover a worktree above an opened subfolder. The IDE may show that
        # repository, but an agent checkout must not modify siblings outside its sandbox.
        if not any(found.root == root or found.root.is_relative_to(root) for root in roots):
            raise ValueError(f'Git root {found.root} is outside the open folders; open the repository root first')
        return found

    def result(r, output=''):
        info = r.info()
        summary = {'root': info['root'], 'branch': info['branch'], 'upstream': info['upstream'],
                   'ahead': info['ahead'], 'behind': info['behind'], 'clean': info['clean'],
                   'branches': info['branches'], 'changes': info['changes']}
        return ((output.strip() + '\n') if output and output.strip() else '') + json.dumps(summary, indent=2)

    def git_status(path: str = '') -> str:
        """Show repository status, local and remote branches, upstream, and changed files.

        `path` selects a repository when several folders are open; leave it empty for the
        first open folder. Use this before checkout or pull so local changes are visible.
        """
        try:
            r = repo(path)
            return clip(result(r), MAX_TOOL_CHARS * 2)
        except Exception as e: return f'git status failed: {errstr(e)}'

    def git_fetch(path: str = '') -> str:
        """Fetch and prune remote refs, then return the refreshed branch status.

        This contacts the configured remotes but does not merge into the working tree.
        Remote-only branches become visible to `git_status` and `git_checkout`.
        """
        try:
            r = repo(path)
            return clip(result(r, r.fetch()), MAX_TOOL_CHARS * 2)
        except Exception as e: return f'git fetch failed: {errstr(e)}'

    def git_checkout(branch: str, path: str = '') -> str:
        """Switch to a local branch or create a local tracking branch from `REMOTE/BRANCH`.

        Call `git_fetch` and inspect `git_status` first. Git refuses a checkout that would
        overwrite local work; never discard or stash the user's changes implicitly.
        """
        try:
            r = repo(path)
            r.checkout(str(branch or '').strip())
            return clip(result(r), MAX_TOOL_CHARS * 2)
        except Exception as e: return f'git checkout failed: {errstr(e)}'

    def git_pull(path: str = '') -> str:
        """Fast-forward the current branch from its configured upstream.

        This deliberately uses `--ff-only`: divergent history is reported for the user to
        resolve explicitly rather than creating a surprise merge commit.
        """
        try:
            r = repo(path)
            return clip(result(r, r.pull()), MAX_TOOL_CHARS * 2)
        except Exception as e: return f'git pull failed: {errstr(e)}'

    def git_push(path: str = '') -> str:
        """Push the current branch to its configured upstream.

        The branch must already have an upstream. This never force-pushes and never creates
        remote branches implicitly.
        """
        try:
            r = repo(path)
            return clip(result(r, r.push()), MAX_TOOL_CHARS * 2)
        except Exception as e: return f'git push failed: {errstr(e)}'

    return [git_status, git_fetch, git_checkout, git_pull, git_push]


# ---------------------------------------------------------------------------
# approval, as a conversation in the notebook
# ---------------------------------------------------------------------------
def notebook_approvals(get_target, tools=WRITE_TOOLS, mode='ask', timeout=300, host=None):
    """An `Approvals` that writes the whole exchange into the notebook.

    `get_target` returns `(notebook, index)` for the cell the current turn belongs to, or
    None when the turn did not come from a notebook -- a question typed into the prompt bar
    still needs approving, it just has nowhere to be written down, and the queue works the
    same either way.

    The cells go in *below* the prompt cell and in order, so reading the notebook top to
    bottom reads as: the question, then what the agent wanted to do, then what you said
    back, then the answer. Which is what happened.

    They are markdown cells carrying `metadata.leela.kind = 'approval'`, the same trick
    prompt cells use: valid nbformat, legible in plain Jupyter, and recognisable to leela
    when the file is reopened.
    """
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
            import json
            md += (f'\n\nEdited `{a.original_tool}` into `{a.tool}` before execution.'
                   f'\n\n```json\n{json.dumps(a.args, indent=2, default=str)}\n```')
        _add(md, {'kind': 'approval', 'id': a.id, 'tool': a.tool,
                  'state': 'approved' if a.answer else 'refused',
                  'edited': bool(getattr(a, 'edited', False))})

    return Interventions(tools=tools, mode=mode, timeout=timeout, host=host,
                         on_ask=on_ask, on_answer=on_answer)


def _n_approvals(nb, i):
    "How many approval cells already sit below the prompt cell at `i`, so the next one lands after them."
    n = 0
    for c in nb.cells[i + 1:]:
        if getattr(c, 'approval', None) is None: break
        n += 1
    return n


# ---------------------------------------------------------------------------
# what the frontends hold
# ---------------------------------------------------------------------------
class Assistant(Agent):
    """The IDE's agent, built over a `Workspace`.

    A subclass rather than a factory so the frontends' `ws.ai` keeps its shape, and so the
    two things the application wants to add -- a workspace-flavoured note, and the
    conversation-in-the-notebook approval -- have somewhere to live that is not the harness.
    """

    LITERT_BACKENDS = ('cpu', 'gpu')

    def set_litert_backend(self, which):
        """Choose the accelerator LiteRT engines are built on. Releases the loaded ones.

        ramabana reads `$LEELA_LITERT_BACKEND` when it builds an engine and maps it to
        `litert_lm.Backend`, so this sets the variable rather than reaching past it -- the CLI
        agent sharing this machine then agrees with the IDE about which accelerator to use.

        The choice belongs to the engine, not a conversation, so loaded LiteRT backends are
        released and rebuilt lazily. Cloud and llama.cpp backends are untouched. Same shape and
        the same reasoning as `set_local_multimodal`, which this deliberately mirrors.
        """
        which = str(which or '').strip().lower()
        if which not in self.LITERT_BACKENDS:
            raise ValueError(f'litert backend must be one of {", ".join(self.LITERT_BACKENDS)}')
        if self.busy: raise RuntimeError('cannot change the LiteRT backend while the assistant is working')
        os.environ['LEELA_LITERT_BACKEND'] = which
        for key in [k for k in self._backends if k[0] == 'litert']:
            self._backends.pop(key).close()
        self.note = f'LiteRT backend {which}'
        return which

    def __init__(self, ws, session=None, model=None, sp=None, approve=None, surface='agent', **kw):
        from .models import load_models
        load_models()  # saved aliases work in prompt cells and the web dropdown alike
        host = WorkspaceHost(ws, session)
        kw.setdefault('cfg', leela_cfg)
        kw.setdefault('approvals', getattr(ws, 'approvals', None))
        kw.setdefault('compact', getattr(ws, 'compact_auto', True))
        kw.setdefault('compact_strategy', getattr(ws, 'compact_strategy', 'surgical'))
        # `approve` used to be a rishi policy passed straight through. An `Approvals` now
        # owns that decision, so a policy handed in here is honoured by wrapping it.
        if approve is not None and kw.get('approvals') is None:
            kw['approvals'] = _PolicyApprovals(approve)
        self.ws, self.surface = ws, surface
        self.session_state = str(getattr(ws, 'agent_state', '') or '')
        self._git_toolset = _git_tools(host)
        super().__init__(host, model=model, sp=sp, **kw)

        def user_steering(instruction: str) -> str:
            "Return a user's intervention after a skipped tool call so the agent can redirect its next step."
            return f'User steering after skipping the proposed call: {instruction}'
        self._steering_tool = user_steering
        self.turn_transactions = {}

    @property
    def tools(self):
        if self._tools is None:
            registered = {f.__name__ for f in self.registry.tools}
            self.registry.tools.extend(f for f in self._git_toolset if f.__name__ not in registered)
            if self._steering_tool not in self.registry.tools: self.registry.tools.append(self._steering_tool)
            built = super().tools
            # Ramabana's delegated agents inherit the parent's plain tools and only know
            # the harness's generic write set. Keep application-specific Git writes out
            # of that read-only delegation surface altogether.
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
        irreversible = []
        for action in self.activity.since(self.activity._mark):
            if not (action.done and action.ok): continue
            if action.tool == 'memory_forget':
                irreversible.append(f"memory_forget ({action.args.get('doc_id', 'unknown document')})")
            elif action.tool == 'run_python':
                irreversible.append('run_python (live kernel state)')
            elif action.tool == 'run_shell':
                irreversible.append(f"run_shell ({action.args.get('command', 'command')})")
            elif action.tool in GIT_WRITE_TOOLS:
                irreversible.append(action.tool)
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
            # execution_meta also retains tool/args for matching the approval to the later
            # wrapper call. They are lookup fields, not Activity.start keyword arguments;
            # passing them alongside start(name, args) produces “multiple values for tool”.
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
            if approvals is not None and (steer := approvals.consume_steer()):
                try: call_args = dict(inspect.signature(f).bind_partial(*args, **kw).arguments)
                except Exception: call_args = dict(kw)
                self.calls.append((f.__name__, call_args))
                act = self.activity.start(f.__name__, call_args)
                out = f'Tool call skipped before execution. User steering: {steer}'
                self.activity.finish(act, out, ok=False)
                approvals.observe_result(False)
                return out
            try: out = run(*args, **kw)
            except Exception:
                if approvals is not None: approvals.observe_result(False)
                raise
            ok = not str(out).startswith(('edit failed', 'write failed', 'could not',
                                          'git status failed', 'git fetch failed',
                                          'git checkout failed', 'git pull failed', 'git push failed'))
            if approvals is not None: approvals.observe_result(ok)
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
    def tools_note(self): return f'{len(self.tools)} tools, {len(self.skills)} skills'


class _PolicyApprovals(Approvals):
    "An `Approvals` wrapping a plain `approve(tool_call) -> bool`, for a caller that brought its own."

    def __init__(self, approve):
        super().__init__(tools=WRITE_TOOLS, mode='ask')
        self._approve = approve

    def request(self, name, args):
        from ...agent.agent import Ask, preview_for, _summary
        a = Ask(tool=name, args=args, summary=_summary(name, args), preview=preview_for(name, args))
        self.history.append(a)
        try: ok = self._approve({'function': {'name': name, 'arguments': args}})
        except Exception as e: return a.resolve(False, errstr(e))
        return a.resolve(bool(ok))


def ide_tools(ws, session=None):
    "Every tool the agent gets, bound to one `Workspace`. Kept for callers that want the list alone."
    host = WorkspaceHost(ws, session)
    return tools_for(host, extra=_git_tools(host))
