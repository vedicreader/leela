"""The agent harness: a coding agent that happens to be running inside leela.

This package is the *brain*, and the rest of leela is one application that gives it
hands. The split is deliberate and is going to be load-bearing: once the harness has
been driven in anger it moves into its own distribution, and the only way that stays a
file move rather than an excavation is if the seam is real from the first commit.

**The rule: nothing in `leela.agent` imports from `leela` outside this package.**
fastcore, rishi, fastllm and aidialog are fair game; `leela.workspace`, `leela.nb`,
`leela.tui` and `leela.web` are not. Everything the IDE knows -- which folders are open,
how to search them, how to run code in the user's kernel, how to ask the person sitting
there whether an edit is alright -- arrives through the `Host` protocol in `host.py`.
`leela/ai.py` is the one file that knows about both sides, and it is thirty lines.

What lives here, and why each piece is a piece:

- `host.py`       what an application must supply to host an agent
- `backend.py`    one chat protocol over two very different engines: rishi (local,
                  synchronous, litert) and fastllm (cloud, async, every provider)
- `models.py`     the model table, and the routing policy that decides which model a
                  *job* goes to -- cheap work local, real work wherever you pointed it
- `hitl.py`       approval as a conversation rather than as a modal dialog
- `fastllm_hitl.py`  the patch that gives fastllm the approval hook rishi already has
- `compact.py`    surviving a long conversation, and saying so afterwards
- `skills.py`     skills discovered from installed packages and skill directories
- `tools.py`      the tools themselves, written against `Host`
- `extensions.py` user Python that registers more of all of the above
- `subagent.py`   delegation to a cheap model whose context is thrown away
- `chat.py`       the facade the application actually holds
"""

__all__ = ['Host', 'Backend', 'Agent', 'Completer', 'Approvals', 'Ask', 'ModelSpec', 'Routing',
           'agent_err', 'AgentError']


class AgentError(Exception):
    "Something the harness refuses to do, as opposed to something that went wrong doing it."


def agent_err(e):
    "How every harness surface reports a caught exception: `TypeName: message`."
    return f'{type(e).__name__}: {e}'


def _lazy(name):
    from importlib import import_module
    mod, attr = {'Host': ('.host', 'Host'), 'Backend': ('.backend', 'Backend'),
                 'Agent': ('.chat', 'Agent'), 'Completer': ('.chat', 'Completer'),
                 'Approvals': ('.hitl', 'Approvals'), 'Ask': ('.hitl', 'Ask'),
                 'ModelSpec': ('.models', 'ModelSpec'), 'Routing': ('.models', 'Routing')}[name]
    return getattr(import_module(mod, __name__), attr)


def __getattr__(name):
    """Import the heavy names on first touch.

    `backend.py` reaches for rishi (a multi-gigabyte local engine) and fastllm (which
    pulls a provider stack); neither should be imported because someone asked for
    `leela.agent.Host`. Same reason `Assistant` has always loaded its model lazily.
    """
    if name in __all__ and name not in ('agent_err', 'AgentError'): return _lazy(name)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
