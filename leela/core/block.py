"The block contract, and the ordered wiring that applies it."

from __future__ import annotations

from fastcore.basics import store_attr

from .ctx import CAPABILITIES, Ctx

__all__ = ['Block', 'connect_all', 'block_caps']

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
