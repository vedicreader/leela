"Move top-level definitions between Python files, and repoint every import that named them."

from __future__ import annotations
import ast, builtins
from fastcore.all import Path, first

from .python import _at, _starts
from .refactor import FileEdit

__all__ = ['module_of', 'top_symbols', 'move_plan']

BUILTINS = frozenset(dir(builtins))

def module_of(path):
    "Dotted module name for a file, from the top of its `__init__.py` chain."
    p = Path(path)
    parts, d = ([] if p.stem == '__init__' else [p.stem]), p.parent
    while (d/'__init__.py').is_file(): parts.append(d.name); d = d.parent
    return '.'.join(reversed(parts))

def _parse(path, source):
    try: return ast.parse(source)
    except SyntaxError as e: raise ValueError(f'{Path(path).name} does not parse: {e.msg} (line {e.lineno})') from e

def _absolute(node, here):
    "The absolute module an `ImportFrom` names, resolving `level` against the module holding it."
    if not node.level: return node.module or ''
    return '.'.join([*here.split('.')[:-node.level], *([node.module] if node.module else [])])

def _stmt(target, here, names):
    "A `from ... import` reaching `target` from `here`, relative where a shared package allows one."
    tp, hp = target.split('.'), here.split('.')[:-1]
    n = 0
    while n < len(tp) - 1 and n < len(hp) and tp[n] == hp[n]: n += 1
    dots = '.' * (len(hp) - n + 1) if n else ''
    return f"from {dots}{'.'.join(tp[n:])} import {', '.join(names)}"

def _spec(alias): return f'{alias.name} as {alias.asname}' if alias.asname else alias.name
def _from(node, aliases): return f"from {'.' * node.level}{node.module or ''} import {', '.join(_spec(a) for a in aliases)}"

def _bound(tree):
    "Every name a module binds at its top level, mapped to the statement that binds it."
    out = {}
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): out[n.name] = n
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names: out[(a.asname or a.name).split('.')[0]] = n
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                for x in ast.walk(t):
                    if isinstance(x, ast.Name): out[x.id] = n
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name): out[n.target.id] = n
    return out

def _free(nodes):
    "Names the nodes read without binding, which is what has to reach them wherever they land."
    load, store = set(), set()
    for node in nodes:
        for n in ast.walk(node):
            if isinstance(n, ast.Name): (load if isinstance(n.ctx, ast.Load) else store).add(n.id)
            elif isinstance(n, ast.arg): store.add(n.arg)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): store.add(n.name)
            elif isinstance(n, ast.alias): store.add((n.asname or n.name).split('.')[0])
            elif isinstance(n, ast.ExceptHandler) and n.name: store.add(n.name)
            elif isinstance(n, ast.Global): store.update(n.names)
    return load - store - BUILTINS

def _span(source, starts, node):
    "What a definition owns: the comments above it, its decorators, and the blank lines below."
    lines = source.splitlines()
    top = min([d.lineno for d in getattr(node, 'decorator_list', [])] + [node.lineno])
    while top > 1 and lines[top - 2].lstrip().startswith('#'): top -= 1
    end = node.end_lineno
    while end < len(lines) and not lines[end].strip(): end += 1
    return starts[top - 1], starts[end]

def top_symbols(source):
    "Top-level functions and classes, each with the character span it owns."
    tree, starts = ast.parse(source), _starts(source)
    kind = lambda n: 'class' if isinstance(n, ast.ClassDef) else 'function'
    return [dict(name=n.name, kind=kind(n), line=n.lineno, **dict(zip(('start', 'end'), _span(source, starts, n))))
            for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]

def _apply(text, edits):
    for a, b, new in sorted(edits, reverse=True): text = text[:a] + new + text[b:]
    return text

def _import_point(tree, starts):
    "Where a new import goes: after the module docstring and the imports already following it."
    body, at, i = tree.body, 0, 0
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0].value, 'value', None), str):
        at, i = starts[body[0].end_lineno], 1
    while i < len(body) and isinstance(body[i], (ast.Import, ast.ImportFrom)):
        at, i = starts[body[i].end_lineno], i + 1
    return at

def _all_edit(text, starts, tree, add=(), drop=()):
    "An edit rewriting a module's `__all__`, or None when it has none this can read."
    node = first(n for n in tree.body if isinstance(n, ast.Assign) and len(n.targets) == 1
                 and isinstance(n.targets[0], ast.Name) and n.targets[0].id == '__all__')
    if node is None or not isinstance(node.value, (ast.List, ast.Tuple)): return None
    cur = [e.value for e in node.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    if len(cur) != len(node.value.elts): return None
    new = [x for x in cur if x not in set(drop)] + [x for x in add if x not in cur]
    if new == cur: return None
    return (*_at(text, starts, node.value), '[' + ', '.join(repr(x) for x in new) + ']')

def _has_import(tree, here, module, spec):
    "The `ImportFrom` already naming `spec` from `module`, and every spec it carries."
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and _absolute(n, here) == module:
            have = {_spec(a) for a in n.names}
            if spec in have: return n, have
    return None, set()

def _add_imports(text, tree, starts, here, froms, plains):
    "Edits folding `froms` into whatever import block the file already has, plus the plain imports."
    edits, add = [], []
    plain_texts = {f"import {_spec(a)}" for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    for module, specs in sorted(froms.items()):
        if module == here: continue
        node, have = None, set()
        for spec in sorted(specs):
            node, have = _has_import(tree, here, module, spec)
            if node is not None: break
        else:
            node, have = first((n, {_spec(a) for a in n.names}) for n in ast.walk(tree)
                               if isinstance(n, ast.ImportFrom) and _absolute(n, here) == module) or (None, set())
        want = sorted(have | set(specs))
        if want == sorted(have): continue
        if node is not None: edits.append((*_at(text, starts, node), _stmt(module, here, want)))
        else: add.append(_stmt(module, here, sorted(specs)))
    add += [p for p in sorted(plains) if p not in plain_texts]
    if add:
        at = _import_point(tree, starts)
        edits.append((at, at, ''.join(s + '\n' for s in add)))
    return edits

def _carry(froms, plains, node, name, here):
    "Record the import that gave `name` to the source file, so the destination gains it too."
    if isinstance(node, ast.ImportFrom):
        alias = first(a for a in node.names if (a.asname or a.name).split('.')[0] == name)
        froms.setdefault(_absolute(node, here), set()).add(_spec(alias))
    else:
        alias = first(a for a in node.names if (a.asname or a.name).split('.')[0] == name)
        plains.add(f'import {_spec(alias)}')

def _repoint(path, text, src_mod, dest_mod, names):
    "One file's imports of `names`, pointed at `dest_mod`."
    here, moved = module_of(path), set(names)
    tree, starts = _parse(path, text), _starts(text)
    bound, edits, hit, notes = _bound(tree), [], False, []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or _absolute(node, here) != src_mod: continue
        taken = [a for a in node.names if a.name in moved]
        if not taken: continue
        hit = True
        keep = [a for a in node.names if a.name not in moved]
        a, b = _at(text, starts, node)
        indent = text[starts[node.lineno - 1]:a]
        lines = ([_from(node, keep)] if keep else []) + [_stmt(dest_mod, here, [_spec(x) for x in taken])]
        if lines: edits.append((a, b, ('\n' + indent).join(lines)))
        else: edits.append((starts[node.lineno - 1], starts[node.end_lineno], ''))
    prefixes = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == src_mod: prefixes[alias.asname or alias.name] = (node, alias)
    for prefix, (node, alias) in prefixes.items():
        root = prefix.split('.')[0]
        reached = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in moved
                   and ''.join(text[slice(*_at(text, starts, n))].split()) == f'{prefix}.{n.attr}']
        if not reached: continue
        clash = sorted({n.attr for n in reached} & set(bound))
        if clash:
            notes.append(f'{Path(path).name} already binds {", ".join(clash)}; its `{prefix}.` uses were left alone')
            continue
        hit = True
        for n in reached: edits.append((*_at(text, starts, n), n.attr))
        loads = sum(1 for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == root and isinstance(n.ctx, ast.Load))
        if loads == len(reached):
            if len(node.names) == 1: edits.append((starts[node.lineno - 1], starts[node.end_lineno], ''))
            else: edits.append((*_at(text, starts, node),
                                'import ' + ', '.join(_spec(x) for x in node.names if x is not alias)))
        edits += _add_imports(text, tree, starts, here, {dest_mod: {n.attr for n in reached}}, set())
    if not hit: return None, notes
    return _apply(text, edits), notes

def _gained(path, before, after):
    "Names `after` reads without binding that `before` did not, which is how a move breaks a file."
    return sorted(_free([_parse(path, after)]) - _free([_parse(path, before or '')]))

def move_plan(read, src, names, dest, others=(), shim=True):
    """Move `names` from `src` into `dest` and repoint every file in `others` that imported them.

    `read` returns a file's text, or None when it does not exist. A destination that does not
    exist comes back with `before` None, which is what makes undo delete it again.
    """
    src, dest, names, notes = str(src), str(dest), list(names), []
    if not names: raise ValueError('choose a function or class to move')
    if Path(src).resolve() == Path(dest).resolve(): raise ValueError('choose a different file to move into')
    if Path(dest).suffix != '.py': raise ValueError('a move lands in a Python file')
    source = read(src)
    tree, starts = _parse(src, source), _starts(source)
    src_mod, dest_mod = module_of(src), module_of(dest)
    top = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    missing = [n for n in names if n not in top]
    if missing: raise ValueError(f"{', '.join(missing)} is not a top-level function or class in {Path(src).name}")
    moved = [top[n] for n in names]
    spans = sorted(_span(source, starts, n) for n in moved)
    block = ''.join(source[a:b] for a, b in spans).strip('\n') + '\n'
    rest = _apply(source, [(a, b, '') for a, b in spans])
    bound, froms, plains, back = _bound(tree), {}, set(), []
    for name in sorted(_free(moved) - set(names)):
        node = bound.get(name)
        if node is None: continue
        if isinstance(node, (ast.Import, ast.ImportFrom)): _carry(froms, plains, node, name, src_mod)
        else: back.append(name)
    if back: froms.setdefault(src_mod, set()).update(back)

    dtext = read(dest)
    fresh = dtext is None
    dtext = dtext or ''
    dtree, dstarts = _parse(dest, dtext), _starts(dtext)
    clash = [n for n in names if n in _bound(dtree)]
    if clash: raise ValueError(f"{Path(dest).name} already defines {', '.join(clash)}")
    dedits = _add_imports(dtext, dtree, dstarts, dest_mod, froms, plains)
    if (e := _all_edit(dtext, dstarts, dtree, add=names)): dedits.append(e)
    dbody = _apply(dtext, dedits)
    dafter = (dbody.rstrip('\n') + '\n\n\n' + block) if dbody.strip() else block

    rtree, rstarts = _parse(src, rest), _starts(rest)
    used = sorted(n for n in names if n in _free([rtree]))
    want = names if shim else used
    # A re-export the source does not otherwise need is dropped rather than refused: keeping it
    # would point the two modules at each other for nothing.
    if want and back:
        if used: raise ValueError(f'{src_mod} and {dest_mod} would import each other over '
                                  f'{", ".join(back)}; move those as well')
        want = []
        notes.append(f're-export left out: {dest_mod} imports {", ".join(back)} back from {src_mod}')
    sedits = _add_imports(rest, rtree, rstarts, src_mod, {dest_mod: set(want)}, set()) if want else []
    if (e := _all_edit(rest, rstarts, rtree, drop=() if shim else names)): sedits.append(e)
    safter = _apply(rest, sedits)

    rows = [FileEdit(src, source, safter, len(names)),
            FileEdit(dest, None if fresh else dtext, dafter, len(names))]
    for path in others:
        if Path(path).resolve() in (Path(src).resolve(), Path(dest).resolve()): continue
        text = read(path)
        if text is None: continue
        try: after, said = _repoint(path, text, src_mod, dest_mod, names)
        except ValueError as e: notes.append(str(e)); continue
        notes += said
        if after is not None and after != text: rows.append(FileEdit(str(path), text, after, 1))
    for row in rows:
        if (broke := _gained(row.path, row.before, row.after)):
            raise ValueError(f"{Path(row.path).name} would lose {', '.join(broke)}; move what it needs as well")
    return rows, notes
