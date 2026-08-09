"""The block contract, and the ordered wiring that applies it.

A block is a folder with a `connect(app, ctx)` function, in the shape lego uses:

    leela/blocks/git/
        cfg.py      # settings and defaults this block owns
        svc.py      # the domain service -- no web imports, testable on its own
        ui.py       # FastHTML fragments
        app.py      # routes + connect(app, ctx)
        git.css     # optional, block-owned
        git.js      # optional, block-owned

and a module-level declaration of what it needs:

    CAPS = ('fs', 'journal')

    def connect(app, ctx):
        rt = app.route
        @rt('/git/info')
        def git_info(): return ui.info(ctx.fs, ...)

`connect` receives a `Ctx` already narrowed to `CAPS`, so a block that reaches for
something it did not declare fails loudly the first time that route runs, rather than
quietly re-coupling to the whole workspace.

Order matters here for the same reason it does in lego, but for a different mechanism.
lego's auth block reads a skip list that earlier blocks append to. Leela has no such
handshake; what it has is Starlette's router, where the *first* matching route wins. A
block registering `/{fname:path}` before the specific routes would shadow all of them. So
`connect_all` preserves the order it is given, and the route inventory test in
`tests/test_route_inventory.py` is what catches a block that shadows another's path.
"""

from __future__ import annotations

from .ctx import CAPABILITIES, Ctx

__all__ = ['Block', 'connect_all', 'block_caps']


class Block:
    """One connected feature, as recorded by `connect_all`.

    Kept deliberately thin -- a block is a *module*, not an instance of this. This is the
    receipt: what was connected, in what order, with which capabilities, so the wiring is
    inspectable at runtime and assertable in tests.
    """
    __slots__ = ('name', 'module', 'caps', 'order')

    def __init__(self, name, module, caps, order):
        self.name, self.module, self.caps, self.order = name, module, caps, order

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
    """Connect `blocks` to `app` in order, each with its own narrowed `Ctx`.

    Returns the `Block` receipts. `session` is the `Workspace`; `services` are the
    application-scoped capabilities (`docs`, `debug`, `running`, `gate`, `catalog`) that
    `ide_app` owns. Every block gets a `Ctx` over the same session and the same services,
    differing only in what it is allowed to see.
    """
    out = []
    for i, m in enumerate(blocks):
        name, caps = block_name(m), block_caps(m)
        m.connect(app, Ctx(session, name=name, caps=caps, **services))
        out.append(Block(name, m, caps or CAPABILITIES, i))
    return out
