"""The approval hook fastllm does not have, written the way it should be added upstream.

Rishi gates every tool call: `ChatToolHandler.approve_tool_call` runs the chat's `approve`
callback, and a refusal is appended to history as a tool response saying so. fastllm's
`AsyncChat._call` has no such gate -- it fans the calls straight out through
`parallel_async` -- which means the same `confirm_writes` policy that protects the local
backend evaporates the moment you point leela at a cloud model. For a harness whose write
tools edit the user's repository, that is not a gap to work around locally and forget.

So this is a patch, deliberately shaped as the upstream diff rather than as a leela
workaround, and kept in one file so lifting it into a pull request is a copy:

1. `AsyncChat.approve` -- a class attribute defaulting to None, so every existing chat
   keeps today's behaviour exactly and nothing has to be passed to get it.
2. `AsyncChat.tcdict` -- the property that already carries `tool_schemas` and `ns` into
   the parallel call now carries `approve` too. One key.
3. `_alite_call_func` -- takes `approve=None`, and returns the refusal string instead of
   calling the function.

That is the whole change: one attribute, one dict key, one guard. It goes through
`tcdict` rather than a module global precisely because the policy has to be *per chat* --
a sub-agent running with tools of its own must not inherit the main conversation's
approval prompt.

The refusal has to be a tool *result*, not a dropped call: providers require every
`tool_use` to be answered by a `tool_result`, so filtering the call list instead would
produce a conversation the API rejects. Returning a string keeps the pairing intact and
lets the model read why it was stopped -- which is the point of `hitl.Ask.reply`.

`apply()` is idempotent and returns whether the patch is in place, because the harness has
to keep working when fastllm is not installed at all.
"""

from __future__ import annotations

from . import agent_err
from .hitl import DENIED, _tc

__all__ = ['apply', 'applied', 'PATCHED_ATTR']

PATCHED_ATTR = '_leela_hitl'      # set on fastllm.chat once, so applying twice is free
_note = 'not attempted'


def applied():
    "Whether fastllm currently has the approval hook, without importing it if it is absent."
    import sys
    m = sys.modules.get('fastllm.chat')
    return bool(m is not None and getattr(m, PATCHED_ATTR, False))


def note():
    "Why the patch is or is not in place. Shown next to the model in the IDE's status."
    return _note


def apply():
    """Give `fastllm.AsyncChat` an `approve` callback. Returns True when it is in place.

    Never raises. fastllm being absent is an ordinary state for a leela install that only
    ever runs local models, and an editor that will not open because a cloud provider
    stack is missing is a worse editor.
    """
    global _note
    try:
        import fastllm.chat as fc
    except Exception as e:
        _note = f'fastllm not available ({agent_err(e)})'
        return False
    if getattr(fc, PATCHED_ATTR, False):
        _note = 'approval hook installed'
        return True
    try:
        _patch(fc)
    except Exception as e:
        _note = f'approval hook could not be installed ({agent_err(e)}); cloud tool calls are ungated'
        return False
    setattr(fc, PATCHED_ATTR, True)
    _note = 'approval hook installed'
    return True


def _patch(fc):
    """The three-line change itself, isolated so the diff to send upstream is obvious.

    Upstream these would be an `approve=None` parameter on `AsyncChat.__init__`, a
    `@patch(as_prop=True)` on `tcdict`, and an edited `_alite_call_func`. From outside the
    package `@patch` cannot be used for `tcdict`: it reads the `self:AsyncChat` annotation
    to find its target, and under `from __future__ import annotations` that name would
    have to be resolvable in *this* module's globals -- which would mean importing fastllm
    at import time, exactly what the lazy loading elsewhere is avoiding. A direct property
    assignment says the same thing without the ceremony.
    """
    from fastllm.chat import AsyncChat, _call_func, _mk_tool_result
    from toolslm.funccall import call_func_async
    from fastcore.utils import maybe_await

    # (1) Default: no policy, i.e. exactly today's behaviour.
    if not hasattr(AsyncChat, 'approve'): AsyncChat.approve = None

    # (2) Thread the policy to where the calls are made. `tcdict` is already the carrier
    #     for everything `_alite_call_func` needs, so there is no new plumbing.
    AsyncChat.tcdict = property(lambda self: dict(
        tool_schemas=self.tool_schemas, ns=self.ns, approve=getattr(self, 'approve', None)))

    # (3) The gate. Signature-compatible with the original, so an un-patched caller that
    #     passes only the old three arguments still works.
    async def _alite_call_func(tc, tool_schemas, ns, approve=None):
        "Call a tool asynchronously, unless `approve(tc)` says not to."
        ok = True
        if approve is not None:
            try: ok = approve(tc)
            except Exception as e: return f'{DENIED}. The approval policy failed: {agent_err(e)}'
            if not ok: return _decision_text(ok) or DENIED
        res = _call_func(tc, tool_schemas, ns, call_func_async)
        out = _mk_tool_result(await maybe_await(res))
        # An approval can come with a condition attached ("yes, but keep the docstring").
        # That is guidance the model needs *while* it works, so it rides back on the result.
        if (said := _decision_text(ok)): out = f'{out}\n\n{said}'
        return out

    fc._alite_call_func = _alite_call_func


def _decision_text(ok):
    """Whatever the policy wanted to say about its decision, or ''.

    A policy may return a plain bool -- in which case there is nothing to say and the
    canned refusal stands -- or an object with `reply()`, which is how `hitl.Ask` carries
    the reason a person gave. Anything that raises while explaining itself is ignored: a
    broken message must not turn an answered approval into a failed tool call.
    """
    r = getattr(ok, 'reply', None)
    if not callable(r): return ''
    try: return r() or ''
    except Exception: return ''
