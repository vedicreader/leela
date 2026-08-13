"""What a block is allowed to touch: capabilities it uses, session state it shares."""

from __future__ import annotations

__all__ = ['Ctx', 'CAPABILITIES', 'EAGER', 'LAZY', 'APP']

# Bound at construction.
EAGER = ('fs', 'pool', 'search', 'memory', 'research', 'runs', 'journal', 'terms', 'dev',
         'approvals', 'jobs')

# Resolved on access. `ai`/`inline_ai`/`completer`/`lsp` are expensive to build; `tab` and
# `pending_approval` read mutable session state, so capturing them once would go stale.
LAZY = ('ai', 'inline_ai', 'completer', 'lsp', 'tab', 'pending_approval')

# Owned by the application rather than the workspace: one set per `ide_app`.
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
        # `caps=None` means "everything". An undeclared slot is simply never assigned, so the
        # refusal is CPython's own unset-slot AttributeError and costs nothing to enforce.
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
        "Explain an undeclared capability instead of reporting a missing attribute."
        # Only reached once normal lookup fails, i.e. exactly the narrowing case. Defining it
        # at all moves the type onto CPython's hooked attribute path; `tools/bench_ctx.py`
        # measures the cost as ~0ns eager, ~32ns lazy.
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
