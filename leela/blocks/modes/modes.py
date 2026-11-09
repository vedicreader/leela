"The mode registry: a mode is a named workspace preset with its own agent tools and context."

import re
from dataclasses import dataclass, field
from importlib import import_module
from typing import Callable
from fastcore.basics import first
from ..runtime.kernels import output_text

__all__ = ['Mode', 'register_mode', 'get_mode', 'modes', 'mode_ids', 'cell_anchor', 'LAYOUT_KEYS', 'DEFAULT_MODE']

DEFAULT_MODE = 'code'
LAYOUT_KEYS = ('files', 'exec', 'exec_handle', 'agent', 'main')
BUILTIN = ('leela.blocks.learn.mode',)
ANCHOR_SRC, ANCHOR_ERR, ANCHOR_OUT = 4000, 1500, 2000

@dataclass
class Mode:
    "One workspace preset: layout, tab kinds, the agent's tools and context, and the UI names."
    id: str
    title: str
    tab_kinds: tuple = ()
    layout: dict = field(default_factory=dict)
    toolset: Callable = lambda ai: []
    context: Callable = lambda ai: ''
    settings_section: str = ''
    shelf: str = ''
    palette: tuple = ()
    contract_check: Callable = lambda: []
    bar: str = ''
    def dict(self): return dict(id=self.id, title=self.title, layout=dict(self.layout), palette=list(self.palette), bar=self.bar, tab_kinds=list(self.tab_kinds))

_REG = {}

def register_mode(m):
    "Add `m`; registering the same object again is a no-op, another mode with its id is refused."
    if (old := _REG.get(m.id)) is not None and old is not m: raise ValueError(f'mode {m.id!r} is already registered')
    _REG[m.id] = m
    return m

register_mode(Mode('code', 'Code', tab_kinds=('notebook', 'text'), layout=dict(files=True, exec=True, exec_handle=True, agent=True, main='editor')))

def modes():
    "Every registered mode, the base `code` mode first."
    for n in BUILTIN: import_module(n)
    return list(_REG.values())

def mode_ids(): return [m.id for m in modes()]

def get_mode(id):
    "The mode `id`; `KeyError` for one nobody registered."
    modes()
    if not isinstance(id, str) or id not in _REG: raise KeyError(f'no mode {id!r}')
    return _REG[id]

ANSI = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')

def cell_anchor(ws, cell=''):
    "The active notebook cell as agent context: source, the last run's error, clipped output. Empty with no notebook tab, or no cell to point at."
    docs, t = getattr(ws, 'docstore', None), ws.tab
    if docs is None or t is None or t.kind != 'notebook' or (nb := docs.doc_for(t)) is None: return ''
    cid = cell or getattr(t, 'cell', '')
    c = first((c for c in nb.cells if c.id == cid), None) if cid else None
    c = c or first((c for c in reversed(nb.cells) if c.has_error), None)
    if c is None: return ''
    body = [f'<active-cell id="{c.id}" index="{nb.cells.index(c)}" type="{c.cell_type}">']
    if src := c.source.strip(): body.append(f'<source>\n{src[:ANCHOR_SRC]}\n</source>')
    if c.cell_type == 'code':
        errs = [o for o in c.outputs if o.get('output_type') == 'error']
        if errs:
            e = errs[-1]
            tb = ANSI.sub('', '\n'.join(e.get('traceback') or [])) or f"{e.get('ename', '')}: {e.get('evalue', '')}"
            body.append(f'<error>\n{tb[-ANCHOR_ERR:]}\n</error>')
        if out := output_text([o for o in c.outputs if o.get('output_type') != 'error']).strip(): body.append(f'<output>\n{out[:ANCHOR_OUT]}\n</output>')
    body.append('</active-cell>')
    return '\n'.join(body)
