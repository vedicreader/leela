"Small, conservative Python extraction plans."

from __future__ import annotations
import ast, builtins, re
from functools import partial
from itertools import accumulate

from fastcore.all import first

from .refactor import FileEdit

__all__ = ['extract', 'inline']

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
    "One safe single-file extraction; unsupported selections fail rather than guess."
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
    if source[_line(source, start)[1]:start].strip() or source[end:source.find('\n', end) if source.find('\n', end) >= 0 else len(source)].strip():
        raise ValueError('functions require complete statement lines')
    tree = ast.parse(source); selected = ast.parse(text).body
    if not selected: raise ValueError('select statements')
    loads = {n.id for node in selected for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    stores = {n.id for node in selected for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    if stores or any(isinstance(n, (ast.Return, ast.Yield, ast.YieldFrom)) for node in selected for n in ast.walk(node)):
        raise ValueError('function extraction currently requires statements without assigned results')
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

def _starts(source):
    "Character offset at which each line begins, plus the end of the text."
    return list(accumulate(map(len, source.splitlines(True)), initial=0))

def _at(source, starts, node):
    "A node's (start, end) character offsets. `col_offset` counts utf-8 bytes, not characters."
    def one(lineno, col):
        begin = starts[lineno - 1]
        return begin + len(source[begin:starts[lineno]].encode()[:col].decode('utf-8', 'ignore'))
    return one(node.lineno, node.col_offset), one(node.end_lineno, node.end_col_offset)

_ATOMIC = (ast.Name, ast.Constant, ast.Attribute, ast.Subscript, ast.Call,
           ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp, ast.JoinedStr)

def _binding(tree, name):
    "The one plain `name = value` statement that defines `name`, or a reason there isn't one."
    if any(name in n.names for n in ast.walk(tree) if isinstance(n, (ast.Global, ast.Nonlocal))):
        raise ValueError(f'{name} is declared global or nonlocal')
    stores = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == name
              and isinstance(n.ctx, (ast.Store, ast.Del))]
    plain = [n for n in ast.walk(tree) if isinstance(n, ast.Assign) and len(n.targets) == 1
             and isinstance(n.targets[0], ast.Name) and n.targets[0].id == name]
    if len(plain) != 1 or len(stores) != 1:
        raise ValueError(f'inline needs {name} assigned exactly once, as a plain `{name} = value`')
    return plain[0]

def inline(path, source, pos):
    "Replace a variable's uses with its value and delete the assignment."
    pos = int(pos)
    if not 0 <= pos <= len(source): raise ValueError('put the cursor on a variable first')
    tree, starts = ast.parse(source), _starts(source)
    at = partial(_at, source, starts)
    spans = {n: at(n) for n in ast.walk(tree) if isinstance(n, ast.Name)}
    here = first(n for n, (a, b) in spans.items() if a <= pos <= b)
    if here is None: raise ValueError('put the cursor on a variable first')
    assign = _binding(tree, here.id)
    astart, aend = at(assign)
    lstart, lend = starts[assign.lineno - 1], starts[assign.end_lineno]
    if source[lstart:astart].strip() or source[aend:lend].strip():
        raise ValueError('inline needs the assignment on lines of its own')
    value = source[slice(*at(assign.value))]
    if not isinstance(assign.value, _ATOMIC): value = f'({value})'
    uses = [span for n, span in spans.items() if n.id == here.id and isinstance(n.ctx, ast.Load)]
    if not uses: raise ValueError(f'{here.id} is never read, so there is nothing to inline')
    if any(a < aend for a, _ in uses): raise ValueError(f'{here.id} is read before it is assigned')
    after = source
    for a, b in sorted(uses, reverse=True): after = after[:a] + value + after[b:]
    return FileEdit(path, source, after[:lstart] + after[lend:], len(uses))
