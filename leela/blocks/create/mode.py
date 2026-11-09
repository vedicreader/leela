"The Create mode: registered on import, by the first look at the registry."

from ..modes.modes import Mode, register_mode
from .scene import contract_missing, create_context, create_tools, says

__all__ = ['CREATE']

CREATE = register_mode(Mode('create', 'Create', tab_kinds=('story',), layout=dict(files=False, exec=False, exec_handle=False, agent=True, main='story'),
    toolset=create_tools, context=create_context, contract_check=contract_missing, says=says, palette=('Mode: Create', 'Create: New scene')))
