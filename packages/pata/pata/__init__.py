"Dynamic documents: one space for a goal, its plan, its research, its code and its prompts."

__version__ = '0.0.1'

from .doc import Block, Doc, FLAVOURS, MODES, RELATIONS, STATUS, block_id, flavour, short
from .context import Item, Spec, SCOPES, render, resolve, spec_of, weigh
from .export import from_ipynb, modules, to_ipynb, to_markdown, write_modules
from .layout import arrange, measure

__all__ = ['Block', 'Doc', 'FLAVOURS', 'MODES', 'RELATIONS', 'STATUS', 'Item', 'Spec', 'SCOPES',
           'block_id', 'flavour', 'short', 'render', 'resolve', 'spec_of', 'weigh',
           'from_ipynb', 'modules', 'to_ipynb', 'to_markdown', 'write_modules', 'arrange', 'measure']
