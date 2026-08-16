"What a block may touch, and the ordered wiring that applies it."

from __future__ import annotations
from fastcore.basics import store_attr

__all__ = ['Ctx', 'CAPABILITIES', 'EAGER', 'LAZY', 'APP', 'Block', 'connect_all', 'block_caps']

EAGER = ('fs', 'fs_watch', 'pool', 'search', 'memory', 'research', 'journal', 'terms',
         'dev', 'approvals', 'jobs', 'vaults', 'feeds', 'browser')

# `runs` follows the active project root, so a block that copied it at connect would answer for
# whichever folder happened to open first
LAZY = ('ai', 'inline_ai', 'completer', 'lsp', 'tab', 'pending_approval', 'runs')

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


class Block:
    "One connected feature, as recorded by `connect_all`."
    __slots__ = ('name', 'module', 'caps', 'order')
    def __init__(self, name, module, caps, order): store_attr()
    def __repr__(self): return f'Block({self.name!r}, order={self.order}, caps={list(self.caps)})'

def block_caps(module):
    "A block's declared capabilities. Absent `CAPS` means unrestricted, for un-migrated blocks."
    caps = getattr(module, 'CAPS', None)
    if caps is None: return None
    unknown = sorted(set(caps) - set(CAPABILITIES))
    if unknown: raise ValueError(f'{block_name(module)}: unknown capabilities {unknown}')
    return tuple(caps)

def block_name(module):
    "`leela.blocks.git.app` -> `git`, so the name is the folder rather than the file."
    parts = getattr(module, '__name__', str(module)).split('.')
    return getattr(module, 'NAME', None) or (parts[-2] if len(parts) > 1 else parts[-1])

def connect_all(app, session, blocks, **services):
    "Connect `blocks` to `app` in order, each with its own narrowed `Ctx`; returns `Block` receipts."
    out = []
    for i, m in enumerate(blocks):
        name, caps = block_name(m), block_caps(m)
        m.connect(app, Ctx(session, name=name, caps=caps, **services))
        out.append(Block(name, m, caps or CAPABILITIES, i))
    return out
