"The Learn mode: registered on import, by the Learn block's `connect` or the first look at the registry."

from ..modes.modes import Mode, register_mode
from . import tools
from .tools import learn_context, learn_tools

__all__ = ['LEARN']

LEARN = register_mode(Mode('learn', 'Learn', tab_kinds=('learn',), layout=dict(files=False, exec=False, exec_handle=False, agent=True, main='learn'),
    toolset=learn_tools, context=learn_context, settings_section='learn', shelf='learning', bar='learn', contract_check=lambda: tools.contract_missing(),
    palette=('Learn: Home', 'Learn: Graph', 'Learn: Progress', 'Ask about this page')))
