"""Binding a `Workspace` to the agent harness.

This file used to be the assistant. It is now the *adapter*: `leela.agent` is the brain
and knows nothing about leela, and everything it needs arrives through `Host`. What is
left here is the part that genuinely belongs to the application -- how a leela workspace
answers the harness's questions, and how an approval turns into a conversation in a
notebook.

Two application-side decisions live here rather than in the harness:

**Approval reads as a conversation, in the document.** `notebook_approvals` writes each
request and each answer into the notebook as markdown cells beside the prompt cell that
caused them. So a refusal and its reason are saved with the work, read in order with
everything else, and legible next week -- and in plain Jupyter, where they are just
markdown. The harness supplies the queue and the rendering; the notebook is leela's idea
of where a conversation lives.

**Activity is saved with the answer.** A prompt cell's reply gets the tool calls folded
underneath it, so a notebook read later still shows which files the answer came from.

`Assistant` and `ide_tools` survive as thin aliases because both frontends and the tests
call them by name, and renaming things that work is not a feature.
"""

from __future__ import annotations

from . import errstr, leela_cfg
from .agent.activity import Activity
from .agent.chat import Agent, Completer
from .agent.hitl import Approvals, answer_md, ask_md
from .agent.host import Hit, Host
from .agent.tools import MAX_TOOL_CHARS, WRITE_TOOLS, tools_for

__all__ = ['WorkspaceHost', 'Assistant', 'Completer', 'ide_tools', 'notebook_approvals',
           'MAX_TOOL_CHARS', 'WRITE_TOOLS']


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

    def check(self, path, must_exist=False): return self.ws.fs._check(path, must_exist=must_exist)
    def walk(self): return list(self.ws.fs.walk())
    def read(self, path): return self.ws.fs.read(self.check(path))
    def write(self, path, text): return self.ws.fs.write(path, text).path
    def text_at(self, path): return self.ws.text_at(path)

    # -- seeing the code -----------------------------------------------------
    def search(self, query, limit=20): return self.ws.search.search(query, limit=limit)
    def peers(self, path, line, limit=20): return self.ws.search.peers(path, line, limit=limit)
    def symbols(self, path): return self.ws.search.symbols(path)

    @property
    def search_note(self):
        s = self.ws.search
        return f'{s.backend}: {s.note}' if s.note else str(s.backend)

    # -- reading the web -----------------------------------------------------
    def web_search(self, query, n=20): return self.ws.research.search(query, n=n)
    def read_url(self, url): return self.ws.research.read(url)

    def research(self, query):
        _, digest = self.ws.research.dig(query)
        return digest

    @property
    def research_note(self): return self.ws.research.note

    # -- notebooks -----------------------------------------------------------
    def nb_cells(self, path):
        from .nb import Notebook
        return [(c.id, c.cell_type, c.source) for c in Notebook.load(self.check(path)).cells]

    def nb_add_cell(self, path, source, index=-1, cell_type='code'):
        from .nb import Cell, Notebook
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
    def run_python(self, code):
        if self.session is None: raise NotImplementedError('no agent session on this kernel')
        r = self.session.run(code)
        if r.error: return r.error
        out = r.stdout or ''
        if r.result is not None: out += ('\n' if out else '') + r.result.value
        return out or '(ok)'

    def inspect_python(self, code):
        """Read-only execution: `AgentSession`'s isolated scope, which leela already had.

        `scope='isolated'` seeds the owner's state into a safepyrun sandbox and throws away
        every write, which is exactly the contract a sub-agent needs and exactly what the
        inspection engine was already built to do. Nothing new had to be invented here --
        the capability existed and was simply not offered as a tool.
        """
        if self.session is None: raise NotImplementedError('no agent session on this kernel')
        r = self.session.run(code, scope='isolated')
        if r.error: return r.error
        out = r.stdout or ''
        if r.result is not None: out += ('\n' if out else '') + r.result.value
        return out or '(ok)'

    @property
    def kernel_kind(self): return getattr(self.ws, 'kernel_kind', 'ipykernel')

    def list_vars(self):
        if self.session is None: raise NotImplementedError('no agent session on this kernel')
        return '\n'.join(f'{v.name}: {v.type} = {v.value}' for _, vs in self.session.view('minimal') for v in vs)

    def terminal_text(self, lines=200):
        terms = self.ws.terms.all()
        if not terms: return 'no terminal is open in the IDE'
        parts = [f'--- terminal {t.pid} ({" ".join(t.argv)}) ---\n{t.text(lines)}' for t in terms]
        return '\n\n'.join(parts).strip()

    # -- the person ----------------------------------------------------------
    @property
    def approvals(self): return getattr(self.ws, 'approvals', None)

    def note(self, text):
        fn = getattr(self.ws, 'on_note', None)
        if fn:
            try: fn(text)
            except Exception: pass


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
    from .nb import Cell

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
    def on_answer(a): _add(answer_md(a), {'kind': 'approval', 'id': a.id, 'tool': a.tool,
                                          'state': 'approved' if a.answer else 'refused'})

    return Approvals(tools=tools, mode=mode, timeout=timeout, host=host, on_ask=on_ask, on_answer=on_answer)


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

    def __init__(self, ws, session=None, model_id=None, sp=None, approve=None, **kw):
        host = WorkspaceHost(ws, session)
        kw.setdefault('cfg', leela_cfg)
        kw.setdefault('approvals', getattr(ws, 'approvals', None))
        # `approve` used to be a rishi policy passed straight through. An `Approvals` now
        # owns that decision, so a policy handed in here is honoured by wrapping it.
        if approve is not None and kw.get('approvals') is None:
            kw['approvals'] = _PolicyApprovals(approve)
        super().__init__(host, model=model_id, sp=sp, **kw)
        self.ws = ws

    @property
    def tools_note(self): return f'{len(self.tools)} tools, {len(self.skills)} skills'


class _PolicyApprovals(Approvals):
    "An `Approvals` wrapping a plain `approve(tool_call) -> bool`, for a caller that brought its own."

    def __init__(self, approve):
        super().__init__(tools=WRITE_TOOLS, mode='ask')
        self._approve = approve

    def request(self, name, args):
        from .agent.hitl import Ask, preview_for, _summary
        a = Ask(tool=name, args=args, summary=_summary(name, args), preview=preview_for(name, args))
        self.history.append(a)
        try: ok = self._approve({'function': {'name': name, 'arguments': args}})
        except Exception as e: return a.resolve(False, errstr(e))
        return a.resolve(bool(ok))


def ide_tools(ws, session=None):
    "Every tool the agent gets, bound to one `Workspace`. Kept for callers that want the list alone."
    return tools_for(WorkspaceHost(ws, session))
