"""Delegating a question whose *answer* is small and whose *working* is enormous.

The pattern is aai-coding's `looker`, generalised. `looker` answers a question about a
screenshot by sending it to a fresh ephemeral thread with a narrow charter and returning
only the answer, so the images never enter the caller's context. The images are incidental;
the shape is the idea.

"Find every place we already handle this" is the canonical case. It costs twenty tool
results and yields three lines of conclusion, and those twenty results then sit in the
context window for the rest of the session, getting summarised at compaction time and
paid for on every subsequent turn. Handing it to a sub-agent means the search happens, the
conclusion comes back, and the twenty results are thrown away with the conversation that
produced them.

Two design choices worth stating:

**On the same engine.** `Backend.spawn` shares the loaded model, so delegation never means
a second multi-gigabyte load or a second provider client.

**On the cheap model, by default.** Routing already sends `subagent` to the local model.
Fan-out is a search problem, not a reasoning problem: reading twenty results and reporting
which three matter is comfortably within a small model, and it is the exact work the
routing policy exists to keep off the wire.

The sub-agent gets **no write tools**. Not a policy that can be relaxed by argument: a
delegated question is a question, and an agent nobody is watching should not be editing
files. If work needs doing, the answer comes back and the main agent does it under the
approval the user is actually looking at.
"""

from __future__ import annotations

from . import agent_err
from .tools import WRITE_TOOLS, clip, MAX_TOOL_CHARS

__all__ = ['SUB_SP', 'SUB_MAX_STEPS', 'read_only', 'delegate', 'subagent_tools']

SUB_MAX_STEPS = 12

SUB_SP = """You are a research sub-agent inside a Python IDE. Another agent has delegated one \
question to you because answering it takes many tool calls and the answer is short.

- Answer exactly the question asked. Nothing else.
- Use your tools as much as you need; nobody is paying attention to how many calls it takes.
- Report what you found, with file paths and line numbers, not what you infer or expect.
- If the answer is that there is nothing, say so plainly. A confident wrong answer is far \
worse than "no matches, and here is what I searched for".
- You cannot edit anything. If the answer implies a change, describe the change and stop."""


def read_only(tools):
    "The tools a sub-agent may have: everything that only reads. See the module docstring."
    return [t for t in tools if getattr(t, '__name__', '') not in WRITE_TOOLS]


def delegate(backend, question, tools=(), sp=SUB_SP, max_steps=SUB_MAX_STEPS):
    """Ask `question` in a throwaway conversation on `backend`'s engine. Returns the answer text.

    The conversation is closed in a `finally` because the whole benefit is that it does not
    outlive the question -- a sub-agent whose context leaks back into the session is just a
    slower way of doing the work inline.
    """
    sub = None
    try:
        sub = backend.spawn(sp=sp, tools=read_only(tools))
        if hasattr(sub, 'max_steps'): sub.max_steps = max_steps
        return sub.send(question)
    except Exception as e:
        return f'delegation failed: {agent_err(e)}'
    finally:
        if sub is not None:
            try: sub.close()
            except Exception: pass


def subagent_tools(get_backend, get_tools):
    """The `delegate` tool, bound to whatever backend routing says sub-agents run on.

    Both arguments are callables so a model switch mid-session is picked up: the tool the
    model is holding must not be pinned to the backend that happened to be current when
    the tool list was built.
    """

    def delegate_search(question: str) -> str:
        """Hand a broad search question to a sub-agent and get back only its conclusion.

        Use this when answering would take many `search_code` / `view_file` / `read_url`
        calls whose results you do not need to keep -- "where else do we do X", "which
        files import Y", "what does this library's API look like". The sub-agent has your
        read-only tools and none of your write tools, and its working is discarded, so the
        cost to your context is one question and one answer.

        Ask one self-contained question. The sub-agent cannot see this conversation.
        """
        b = get_backend()
        if b is None: return 'no model is available to delegate to'
        return clip(delegate(b, question, get_tools()), MAX_TOOL_CHARS)

    return [delegate_search]
