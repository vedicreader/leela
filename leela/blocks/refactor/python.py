"Small, conservative Python extraction plans."

from __future__ import annotations
import ast, builtins, re, textwrap
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
    # the selection carries its own indentation, and `ast` will not parse an indented block
    block = textwrap.dedent(text)
    try: selected = ast.parse(block).body
    except SyntaxError as e: raise ValueError(f'select whole statements to extract ({e.msg})') from e
    if not selected: raise ValueError('select statements')
    if any(isinstance(n, (ast.Return, ast.Yield, ast.YieldFrom)) for node in selected for n in ast.walk(node)):
        raise ValueError('a selection that returns or yields cannot be lifted into its own function')
    params, stores = _reads_before_writes(selected), _writes(selected)
    params = [p for p in params if p not in set(dir(builtins))]
    returns = sorted(n for n in stores if n in _reads(source[end:]))
    body = ''.join(indent + '    ' + line if line.strip() else line for line in block.splitlines(True))
    if not body.endswith('\n'): body += '\n'   # a selection can end mid-line; a body cannot
    if returns: body += f'{indent}    return {", ".join(returns)}\n'
    args = list(params)
    if kind != 'method':
        call, head = f'{name}({", ".join(args)})', ', '.join(args)
        if returns: call = f'{", ".join(returns)} = {call}'
        definition = f'{indent}def {name}({head}):\n{body}'
        return FileEdit(path, source, source[:start] + definition + '\n' + indent + call + '\n' + source[end:], 1)
    # a method has to be a sibling of the one it came out of: nested inside it, `self.name` is
    # not an attribute of anything
    args = [p for p in args if p != 'self']
    call = f'self.{name}({", ".join(args)})'
    if returns: call = f'{", ".join(returns)} = {call}'
    holder, member = _enclosing_method(source, start)
    body = textwrap.indent(textwrap.dedent(body), member + '    ')
    definition = f'\n\n{member}def {name}(self{", " if args else ""}{", ".join(args)}):\n{body.rstrip()}\n'
    after = source[:start] + indent + call + '\n' + source[end:]
    at = _offset_after(after, holder)
    return FileEdit(path, source, after[:at] + definition + after[at:], 1)

def _enclosing_method(source, pos):
    "The method `pos` sits in and the indent its siblings use, or a reason there is none."
    tree, starts = ast.parse(source), _starts(source)
    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        for fn in [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            begin, stop = _at(source, starts, fn)
            if begin <= pos <= stop: return fn, ' ' * fn.col_offset
    raise ValueError('extract a method from inside one of a class\'s own methods')

def _offset_after(source, node):
    "Where a sibling of `node` goes: the end of the statement it follows."
    starts = _starts(source)
    for fn in [n for n in ast.walk(ast.parse(source))
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == node.name]:
        return _at(source, starts, fn)[1]
    return len(source)

def _writes(nodes):
    "Every name the selection binds."
    return {n.id for node in nodes for n in ast.walk(node)
            if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.AugStore))} | {
            n.id for node in nodes for n in ast.walk(node)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}

def _reads(text):
    """Every name the text loads, so a name still wanted afterwards can be told from a dead one.

    The tail of a file is the middle of a block and rarely parses. The identifier fallback errs
    towards handing a value back, which is untidy rather than broken."""
    for candidate in (text, textwrap.dedent(text)):
        try: tree = ast.parse(candidate)
        except SyntaxError: continue
        return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    return set(re.findall(r'\b[A-Za-z_][A-Za-z0-9_]*\b', text))

#: Where a statement reads before it binds. `ast.walk` is breadth-first, so it would see the target
#: of `total = total + 1` before the value and call the name already bound.
_EVAL_ORDER = {ast.Assign: ('value', 'targets'), ast.AugAssign: ('value', 'target'),
               ast.AnnAssign: ('value', 'target'), ast.For: ('iter', 'target'),
               ast.AsyncFor: ('iter', 'target'), ast.comprehension: ('iter', 'target'),
               ast.withitem: ('context_expr', 'optional_vars')}

def _reads_before_writes(nodes):
    """Names the selection reads before it binds them: those have to arrive as parameters.

    A name both read and bound, as in `total = total + n`, is a parameter as well as a result.
    Subtracting the bound names from the read ones would miss it."""
    bound, params = set(), []
    def visit(node):
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                if node.id not in bound and node.id not in params: params.append(node.id)
            else: bound.add(node.id)
            return
        if (order := _EVAL_ORDER.get(type(node))) is not None:
            for field in order:
                for child in _children(getattr(node, field, None)): visit(child)
            for name, value in ast.iter_fields(node):
                if name in order: continue
                for child in _children(value): visit(child)
            return
        for child in ast.iter_child_nodes(node): visit(child)
    for node in nodes: visit(node)
    return sorted(params)

def _children(value):
    if isinstance(value, list): return [x for x in value if isinstance(x, ast.AST)]
    return [value] if isinstance(value, ast.AST) else []

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
