"""What a block is allowed to touch.

`ide_app` is one 2,600-line closure over a `Workspace`, and its routes reach into roughly
thirty attributes of it -- `ws.fs` fifty times, `ws.ai` forty-six, `ws.memory` thirty-three.
Moving those routes into separate modules without changing that does not buy modularity: it
buys thirty files that each need the whole `Workspace` to exist before they can be
imported, constructed or tested. `Ctx` is the seam that makes the move worth making.

Two kinds of thing hang off a workspace, and the distinction is the whole design:

- **capabilities** -- `fs`, `pool`, `memory`, `search`: services a block *uses*. These are
  what a block should declare, and what `vishalakshi` and `ramabana` will substitute.
- **session state** -- `tabs`, `active`, `model`, `agent_state`: mutable facts about this
  particular workspace. Shared, not injected. Blocks reach these through `ctx.session`.

Capabilities are bound at construction, so `ctx.fs` is one slot read -- the same machine
work as `ws.fs`, with no descriptor and no `__getattr__` in the path. The four expensive
ones (`ai`, `inline_ai`, `completer`, `lsp`) stay lazy, because binding them eagerly would
build an `Assistant` and load a model for every workspace at startup, including the ones
whose user never opens the agent pane.

`narrow` is how a block declares its dependencies:

    ctx.narrow('fs', 'pool')      # a Ctx where `.memory` raises AttributeError

Undeclared *eager* capabilities are simply never assigned, so the enforcement is CPython's
own unset-slot `AttributeError` and costs nothing at runtime. Lazy ones check a frozenset,
which is one hash lookup on a path that is about to call a model.
"""

from __future__ import annotations

__all__ = ['Ctx', 'CAPABILITIES', 'EAGER', 'LAZY', 'APP']

# Bound at construction: cheap attribute reads on an already-built Workspace.
EAGER = ('fs', 'pool', 'search', 'memory', 'research', 'runs', 'journal', 'terms', 'dev',
         'approvals')

# Resolved on access. `ai`/`inline_ai`/`completer`/`lsp` construct something expensive on
# first touch; `tab`/`pending_approval` are cheap but read mutable session state, so
# capturing them once would hand blocks a stale answer.
LAZY = ('ai', 'inline_ai', 'completer', 'lsp', 'tab', 'pending_approval')

# Owned by the application rather than the workspace: one set per `ide_app`, supplied at
# construction. These are the closure variables blocks could not otherwise share -- see
# `leela/core/session.py`. `gate` and `catalog` come in the same way because they are also
# per-app, handed to `ide_app` by `serve_ide`.
APP = ('docs', 'debug', 'running', 'gate', 'catalog')

CAPABILITIES = EAGER + LAZY + APP


def _lazy(name):
    "A property reading `name` off the session, refused when the block did not declare it."
    def get(self):
        if self._lazy is not None and name not in self._lazy:
            raise AttributeError(_undeclared(self, name))
        return getattr(self.session, name)
    return property(get, doc=f'`Workspace.{name}`, resolved on access.')


def _undeclared(ctx, name):
    return (f"block {ctx.name!r} used capability {name!r} without declaring it; "
            f"add it to the block's `caps`")


class Ctx:
    "The capability surface handed to one block's `connect`."

    __slots__ = ('session', 'name', '_lazy', '_app') + EAGER + APP

    def __init__(self, session, name='', caps=None, **app):
        unknown = sorted(set(app) - set(APP))
        if unknown: raise TypeError(f'unknown application capabilities: {unknown}')
        self.session, self.name, self._app = session, name, app
        # None means "everything", which is what the un-narrowed workspace-wide Ctx is.
        # A declared set narrows all three halves: eager and app slots below, lazy via
        # `_lazy`. An undeclared slot is simply never assigned, so the refusal is CPython's
        # own unset-slot AttributeError and costs nothing to enforce.
        want = None if caps is None else frozenset(caps)
        self._lazy = want
        for c in EAGER:
            if want is None or c in want: setattr(self, c, getattr(session, c))
        for c in APP:
            if (want is None or c in want) and c in app: setattr(self, c, app[c])

    def narrow(self, *caps):
        "A `Ctx` exposing only `caps`. Anything else raises `AttributeError` on first use."
        unknown = sorted(set(caps) - set(CAPABILITIES))
        if unknown: raise ValueError(f'unknown capabilities: {unknown}')
        return type(self)(self.session, self.name, caps=caps, **self._app)

    def __getattr__(self, name):
        """Explain an undeclared capability instead of reporting a missing attribute.

        Only reached when normal lookup has already failed -- an unset slot, i.e. exactly
        the narrowing case -- so the success path pays nothing for this. That is the whole
        reason narrowing is enforced by leaving slots unassigned rather than by checking a
        set on every access.
        """
        if name in APP and name not in self._app:
            raise AttributeError(
                f'block {self.name!r} asked for {name!r}, which this application does not '
                f'provide; `ide_app` supplies {sorted(self._app) or "nothing"}')
        if name in CAPABILITIES: raise AttributeError(_undeclared(self, name))
        raise AttributeError(f'{type(self).__name__!r} object has no attribute {name!r}')

    @property
    def caps(self):
        "The declared capability names, or every one of them when unrestricted."
        return sorted(self._lazy) if self._lazy is not None else sorted(CAPABILITIES)

    def __repr__(self):
        n = 'all' if self._lazy is None else ','.join(sorted(self._lazy))
        return f'Ctx({self.name!r}, caps={n})'


for _c in LAZY: setattr(Ctx, _c, _lazy(_c))
del _c
