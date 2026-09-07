"Dynamic documents: one markdown file for a goal, its plan, its research, its code and its prompts."

__version__ = '0.1.0'

from .doc import Brick, Doc, KINDS, MODES, STATUS, brick_id, defs_of, downstream, order, reads_of, upstream
from .context import Item, SCOPES, Spec, body_text, members, render, resolve, spec_of, strip_work_log, weigh
from .export import from_ipynb, modules, to_ipynb, to_report, write_modules
from .layout import arrange, measure

__all__ = ['Brick', 'Doc', 'KINDS', 'MODES', 'STATUS', 'brick_id', 'defs_of', 'downstream', 'order',
           'reads_of', 'upstream', 'Item', 'SCOPES', 'Spec', 'body_text', 'members', 'render',
           'resolve', 'spec_of', 'strip_work_log', 'weigh', 'from_ipynb', 'modules', 'to_ipynb',
           'to_report', 'write_modules', 'arrange', 'measure']
