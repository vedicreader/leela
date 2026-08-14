"""Small, conservative Python extraction plans."""

from __future__ import annotations
import ast, builtins, re

from .refactor import FileEdit

__all__ = ['extract']


def _name(name):
    if not str(name).isidentifier(): raise ValueError('name must be a valid Python identifier')
    return str(name)


def _line(source, pos): return source.count('\n', 0, pos), source.rfind('\n', 0, pos) + 1

def _indent(source, pos):
    _, start = _line(source, pos)
    return re.match(r'[ \t]*', source[start:]).group()

def _expr(text):
    try: return ast.parse(text, mode='eval').body
    except SyntaxError as e: raise ValueError('select one complete Python expression') from e

def extract(path, source, start, end, kind, name):
    """One safe single-file extraction; unsupported selections fail rather than guess."""
    start, end, name = int(start), int(end), _name(name)
    if not 0 <= start < end <= len(source): raise ValueError('select code before extracting')
    text, indent = source[start:end], _indent(source, start)
    if kind in {'variable', 'constant'}:
        node = _expr(text)
        if kind == 'constant':
            try: ast.literal_eval(node)
            except Exception as e: raise ValueError('constants must be literal values') from e
            name = name.upper()
            if not re.fullmatch(r'[A-Z_][A-Z0-9_]*', name): raise ValueError('constant names use UPPER_CASE')
            if indent: raise ValueError('extract constants from module scope')
            tree = ast.parse(source); at = 0
            if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant): at = tree.body[0].end_lineno
            while at < len(source.splitlines()) and source.splitlines()[at].startswith(('import ', 'from ')): at += 1
            point = sum(len(x) + 1 for x in source.splitlines()[:at])
            after = source[:point] + f'{name} = {text}\n' + source[point:start] + name + source[end:]
        else:
            line, line_start = _line(source, start)
            after = source[:line_start] + f'{indent}{name} = {text}\n' + source[line_start:start] + name + source[end:]
        return FileEdit(path, source, after, 1)
    if kind not in {'function', 'method'}: raise ValueError('unknown extraction')
    # Both ends must sit on their own line, or the definition would be spliced into the middle
    # of a statement. `_line` returns the *start* of the line, so the head slice runs forwards.
    if source[_line(source, start)[1]:start].strip() or source[end:source.find('\n', end) if source.find('\n', end) >= 0 else len(source)].strip():
        raise ValueError('functions require complete statement lines')
    tree = ast.parse(source); selected = ast.parse(text).body
    if not selected: raise ValueError('select statements')
    loads = {n.id for node in selected for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    stores = {n.id for node in selected for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    if stores or any(isinstance(n, (ast.Return, ast.Yield, ast.YieldFrom)) for node in selected for n in ast.walk(node)):
        raise ValueError('function extraction currently requires statements without assigned results')
    # `__builtins__` is the builtins *dict* in an imported module, so `dir` on it would have
    # listed dict methods and turned `print`/`len` into parameters.
    params = sorted(loads - stores - set(dir(builtins)))
    body = ''.join(indent + '    ' + line if line.strip() else line for line in text.splitlines(True))
    call = f'{name}({", ".join(params)})'
    if kind == 'method':
        if not indent: raise ValueError('extract method inside a class')
        params = [p for p in params if p != 'self']; call = f'self.{name}({", ".join(params)})'
        definition = f'{indent}def {name}(self{", " if params else ""}{", ".join(params)}):\n{body}'
    else: definition = f'{indent}def {name}({", ".join(params)}):\n{body}'
    after = source[:start] + definition + '\n' + indent + call + '\n' + source[end:]
    return FileEdit(path, source, after, 1)
