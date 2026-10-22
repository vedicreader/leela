"Leela's features, one folder each, and the order they connect in."

from importlib import import_module

__all__ = ['NAMES', 'BLOCKS', 'blocks']

#: Connection order, which is the wiring `ide_app` applies. Keeping it here rather than in
#: `app.py` is what lets a block be added without touching the application.
NAMES = ('keys settings search memory vault debug agent nb research browser term runs '
         'workspace git workflows pipelines drive stack fs lsp vars runtime tabs editor '
         'refactor').split()

def blocks():
    "The block modules in connection order. Each resolves `connect` and `CAPS` lazily."
    return [import_module(f'{__name__}.{n}') for n in NAMES]

def __getattr__(name):
    if name == 'BLOCKS': return blocks()
    raise AttributeError(name)
