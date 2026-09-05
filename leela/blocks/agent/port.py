"""What the pane's routes need of whatever is running the agent.

`app.py` read thirty-four members off `Workspace`. Six of them are Leela's kernels and notebooks;
the rest are the agent's own, and a second host -- Ramabana with no IDE around it -- has all of
them under other names. `AgentPort` is those thirty-four collected into six, and `WorkspacePort`
is Leela's implementation. `execution` is the one that may be `None`: a host with no kernel has
nothing to run a cell in, and the four routes that reach for it answer rather than raise.
"""

from __future__ import annotations

__all__ = ['AgentPort', 'WorkspacePort', 'NO_EXECUTION', 'SETTINGS']

#: the fifteen scalars the pane reads and writes. A host stores them wherever it likes.
SETTINGS = ('model', 'inline_model', 'completion_model', 'job_models', 'tool_budget', 'step_budget',
            'compact_auto', 'compact_strategy', 'agent_read_outside', 'allow_workspace_repo_writes',
            'subagent_writes', 'vault_pii', 'local_multimodal', 'litert_backend',
            'agent_memory_selection')

class AgentPort:
    "The six things the pane's routes touch. Anything running the agent can supply them."
    threads: object        #: the `Threads` object: rows, add, drop, switch
    assistants: object     #: the agent, the inline agent, the notebook approvals
    settings: object       #: the fifteen scalars, and `save()`
    state: object          #: the charter and its layers
    history: object        #: stamping, freshening and saving a turn's history
    execution: object      #: kernels and working directories; `None` where there are none

class _Settings:
    "Attribute access over one host's storage, refusing any name that is not the pane's."
    __slots__ = ('_ws',)
    def __init__(self, ws): object.__setattr__(self, '_ws', ws)
    def __getattr__(self, k):
        if k not in SETTINGS: raise AttributeError(f'{k} is not an agent setting')
        return getattr(self._ws, k)
    def __setattr__(self, k, v):
        if k not in SETTINGS: raise AttributeError(f'{k} is not an agent setting')
        setattr(self._ws, k, v)
    def save(self): self._ws.save()

class _Assistants:
    "The live agents. `built_*` never constructs one: asking is what the probe routes do."
    __slots__ = ('_ws',)
    def __init__(self, ws): self._ws = ws
    @property
    def agent(self): return self._ws.ai
    @property
    def inline(self): return self._ws.inline_ai
    @property
    def built_agent(self): return self._ws._ai
    @property
    def built_inline(self): return self._ws._inline_ai
    @property
    def notebook_approvals(self): return self._ws._notebook_approvals

class _State:
    "The charter the agent is briefed with, and the layers it is assembled from."
    __slots__ = ('_ws',)
    def __init__(self, ws): self._ws = ws
    @property
    def text(self): return self._ws.agent_state
    @property
    def layers(self): return self._ws.agent_state_layers

class _History:
    __slots__ = ('_ws',)
    def __init__(self, ws): self._ws = ws
    def stamp(self, *a, **kw): return self._ws.history_stamp(*a, **kw)
    def fresh(self, *a, **kw): return self._ws.fresh_history(*a, **kw)
    def with_timelines(self, *a, **kw): return self._ws.with_timelines(*a, **kw)
    def ask(self, *a, **kw): return self._ws.ask(*a, **kw)
    def prepare_turn(self, *a, **kw): return self._ws.prepare_turn(*a, **kw)
    def save(self): return self._ws.save()

class _Execution:
    "Kernels and working directories. A host without them supplies no `execution` at all."
    __slots__ = ('_ws',)
    def __init__(self, ws): self._ws = ws
    def runtime(self, *a, **kw): return self._ws.runtime(*a, **kw)
    def peek(self, *a, **kw): return self._ws.runtime_peek(*a, **kw)
    def kernel_peek(self, *a, **kw): return self._ws.kernel_peek(*a, **kw)
    def cwd_for(self, *a, **kw): return self._ws.cwd_for(*a, **kw)

class _NoExecution:
    """A host with no kernels. Nothing runs, nothing is running, and the working directory is
    wherever the process already is. The routes then answer instead of raising, which is the whole
    point: Leela never reaches this and Ramabana reaches nothing else."""
    async def runtime(self, *a, **kw): return None
    def peek(self, *a, **kw): return None
    def kernel_peek(self, *a, **kw): return None
    def cwd_for(self, *a, **kw):
        from pathlib import Path
        return Path.cwd()

NO_EXECUTION = _NoExecution()

class WorkspacePort(AgentPort):
    "Leela's port: a `Workspace` behind the six."
    def __init__(self, ws):
        self._ws = ws
        self.assistants, self.settings = _Assistants(ws), _Settings(ws)
        self.state, self.history, self.execution = _State(ws), _History(ws), _Execution(ws)
    @property
    def threads(self): return self._ws.threads
    @property
    def built_threads(self): return self._ws._threads
