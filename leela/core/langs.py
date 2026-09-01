"The languages Leela can run, serve and highlight, in one place."
from __future__ import annotations
from dataclasses import dataclass, field

__all__ = ['Lang', 'LANGS', 'lang_named', 'lang_of_ext', 'lang_ids', 'servers_for', 'DEFAULT_LANG']

DEFAULT_LANG = 'python'

@dataclass(frozen=True)
class Lang:
    "One language Leela knows. Only Python has a kernel, a runner and inspection all three."
    id: str
    label: str
    exts: tuple = ()
    kernel: str = ''        # the Jupyter kernelspec that runs it
    runner: str = ''        # the in-process runner that runs it where no kernel is installed
    servers: tuple = ()
    inspect: bool = False   # whether dhrishti can read its namespace
    install: str = ''

LANGS = {l.id: l for l in [
    Lang('python', 'Python', ('.py', '.pyi', '.ipynb'), kernel='python3', inspect=True,
         servers=(('basedpyright-langserver', ('--stdio',)), ('pyright-langserver', ('--stdio',)),
                  ('pyrefly', ('lsp',)), ('ty', ('server',)))),
    Lang('rust', 'Rust', ('.rs',), kernel='rust', runner='cargo',
         servers=(('rust-analyzer', ()),),
         install='cargo install evcxr_jupyter && evcxr_jupyter --install'),
    Lang('javascript', 'JavaScript', ('.js', '.mjs', '.cjs', '.jsx'), kernel='deno', runner='node',
         servers=(('typescript-language-server', ('--stdio',)), ('vtsls', ('--stdio',)),
                  ('deno', ('lsp',))),
         install='deno jupyter --install'),
    Lang('typescript', 'TypeScript', ('.ts', '.mts', '.cts', '.tsx'), kernel='deno',
         servers=(('typescript-language-server', ('--stdio',)), ('vtsls', ('--stdio',)),
                  ('deno', ('lsp',))),
         install='deno jupyter --install'),
]}

_BY_EXT = {e: l.id for l in LANGS.values() for e in l.exts}

def lang_named(name):
    "The `Lang` for a language id, or None. An alias nbformat writes, like `python3`, resolves too."
    if not name: return None
    name = str(name).lower()
    if name in LANGS: return LANGS[name]
    return LANGS.get(name.rstrip('0123456789')) or None

def lang_of_ext(ext):
    "The language id for a file extension, or None."
    return _BY_EXT.get(str(ext or '').lower())

def lang_ids(): return tuple(LANGS)

def servers_for(lang):
    "LSP server candidates for a language, in the order they should be tried."
    l = lang_named(lang)
    return l.servers if l else ()
