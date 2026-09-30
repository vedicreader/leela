"The functional flow of one feature as a canvas: what calls what, each function's source, and what one real run passed through it."

from __future__ import annotations
import ast, json, os, re, subprocess, tempfile
from fastcore.all import L, Path, first
from .change import snip_root
from .doc import Brick, Canvas

__all__ = ['PLUGIN', 'resolve', 'slice_', 'cite', 'trace', 'unrun', 'flow_path', 'functions', 'build', 'flow']

#: How many functions one canvas shows. A flow longer than this is read as two.
CAP, TRACED_CAP = 15, 20

def _files(g, ns):
    "`{node: file}` for the nodes the graph knows a file for."
    ns = list(dict.fromkeys(ns))
    if not ns: return {}
    rows = g.gn(where=f'node IN ({",".join("?" * len(ns))})', where_args=ns)
    return {r['node']: r['file'] for r in rows if r.get('file')}

def _meta(r):
    m = r.get('metadata') or r.get('meta') or {}
    if isinstance(m, str):
        try: m = json.loads(m)
        except ValueError: m = {}
    return m

def resolve(g, entry, k=None):
    "The graph node `entry` names, as `(node, [])`, else `('', candidates)`."
    e = str(entry or '').strip()
    if not e: return '', []
    if _files(g, [e]): return e, []
    hits = [r['node'] for r in g.gn(where='node = ? OR node LIKE ?', where_args=[e, f'%.{e}'], limit=50)
            if r.get('file') and (r['node'] == e or r['node'].endswith('.' + e))][:10]
    if len(hits) == 1: return hits[0], []
    if hits or k is None: return '', hits
    try: rows = k.context(e, graph=True, env=False, limit=10)
    except Exception: rows = []
    names = L(rows).map(_meta).map(lambda m: [str(m.get('mod_name') or ''), f"{m.get('mod_name')}.{m.get('name')}"]).concat()
    fs = _files(g, [n for n in names if n and not n.endswith('.None')])
    cands = [n for n in dict.fromkeys(names) if n in fs]
    return (cands[0], []) if len(cands) == 1 else ('', cands)

def slice_(
    g,           # a kosha `CodeGraph`
    node,        # the entry point, a graph node name
    depth=2,     # how many calls deep to walk
    keep='',     # the package prefix a callee must have; the entry's top-level package when empty
    cap=CAP,     # the most rows returned
):
    "Breadth-first over what `node` calls, inside `keep`, as `{node, parent, depth, file}` rows."
    keep = keep or node.split('.')[0]
    rows, seen, front = [dict(node=node, parent='', depth=0, file=_files(g, [node]).get(node, ''))], {node}, [node]
    for d in range(1, depth + 1):
        nxt = []
        for p in front:
            kids = [c for c in dict.fromkeys(g.callees(p)) if c.startswith(keep + '.')]
            fs = _files(g, kids)
            for c in kids:
                if c in seen or c not in fs or len(rows) >= cap: continue
                seen.add(c); nxt.append(c)
                rows.append(dict(node=c, parent=p, depth=d, file=fs[c]))
        front = nxt
    return rows

def _rel(file, root): return Path(os.path.relpath(Path(file).resolve(), Path(root).resolve())).as_posix()

def _modules(rel):
    "Every module name `rel` could be imported as, longest first, for a `src/` layout and a package `__init__`."
    parts = [p for p in rel.removesuffix('.py').split('/') if p != '..']
    out = ['.'.join(parts[i:]) for i in range(len(parts))]
    return [*out, *(m.removesuffix('.__init__') for m in out if m.endswith('.__init__'))]

def cite(node, file, root):
    "`(path, symbol)` a snippet brick cites: `file` from `root`, and `node` inside its module."
    rel = _rel(file, root)
    m = first(m for m in _modules(rel) if node.startswith(m + '.'))
    return rel, node[len(m) + 1:] if m else node.rpartition('.')[2]

PLUGIN = r'''"Records what one pytest run calls inside FLOW_ROOT, for leela's flow canvas."
import json, os, reprlib, sys
import pytest
M, E = sys.monitoring, sys.monitoring.events
ROOT = os.path.realpath(os.environ.get('FLOW_ROOT', '.'))
OUT, CAP = os.environ.get('FLOW_OUT', ''), 2000
R = reprlib.Repr(maxstring=80, maxother=80, maxlist=6, maxtuple=6, maxdict=6, maxset=6, maxlevel=3)
calls, stack, firsts, lines, kept = [], [], {}, {}, {}
EVENTS = E.PY_START | E.PY_RESUME | E.PY_RETURN | E.PY_YIELD | E.PY_UNWIND | E.LINE

def keep(code):
    k = kept.get(code)
    if k is None:
        f = code.co_filename
        # `<frozen os>` and `<string>` are not paths, however `realpath` resolves them.
        f = os.path.realpath(f) if os.path.isabs(f) else ''
        parts, name = f.split(os.sep), os.path.basename(f)
        k = kept[code] = (bool(f) and f.startswith(ROOT + os.sep) and '.venv' not in parts and 'site-packages' not in parts
            and 'tests' not in parts[len(ROOT.split(os.sep)):] and not name.startswith('test_')
            and not name.endswith('_test.py') and name != '_leela_flow.py')
    return k

EXACT = (int, float, bool, type(None), str, bytes)

def _r(v):
    try: return R.repr(v)
    except Exception: return '<unreprable>'

def _exact(v):
    "`repr(v)` when it is short and reads back as `v`; None when `reprlib` had to cut it."
    if type(v) not in EXACT: return None
    s = repr(v)
    return s if len(s) <= 200 else None

def start(code, off):
    if not keep(code): return M.DISABLE
    key = (os.path.realpath(code.co_filename), code.co_qualname)
    rec = firsts.get(key)
    if rec is not None:
        rec['count'] += 1; stack.append(rec); return
    if len(calls) >= CAP: stack.append(None); return
    n = code.co_argcount + code.co_kwonlyargcount
    names = list(code.co_varnames[:n])
    if code.co_flags & 4: names.append('*' + code.co_varnames[n]); n += 1
    if code.co_flags & 8: names.append('**' + code.co_varnames[n])
    loc = sys._getframe(1).f_locals
    par = next((s['id'] for s in reversed(stack) if s), None)
    vals = {a: loc[a.lstrip('*')] for a in names if a.lstrip('*') in loc}
    exact = {a: _exact(v) for a, v in vals.items()}
    rec = dict(id=len(calls), parent=par, qualname=code.co_qualname, file=key[0], line=code.co_firstlineno,
               posonly=code.co_posonlyargcount, count=1, ret=None, raised=None,
               lazy=bool(code.co_flags & 0x3a0),   # generator, coroutine or async generator: calling it does not return `ret`
               args={a: exact[a] or _r(v) for a, v in vals.items()}, exact=all(x is not None for x in exact.values()))
    calls.append(rec); firsts[key] = rec; stack.append(rec)

def resume(code, off):
    if not keep(code): return M.DISABLE
    stack.append(firsts.get((os.path.realpath(code.co_filename), code.co_qualname)))

def ret(code, off, val):
    if not keep(code): return M.DISABLE
    s = stack.pop() if stack else None
    if s is not None and s['ret'] is None and s['raised'] is None: s['ret'] = _r(val)

def yld(code, off, val):
    if not keep(code): return M.DISABLE
    if stack: stack.pop()

def unwind(code, off, exc):
    if not keep(code): return
    s = stack.pop() if stack else None
    if s is not None and s['ret'] is None and s['raised'] is None: s['raised'] = type(exc).__name__

def line(code, n):
    if not keep(code): return M.DISABLE
    lines.setdefault(f'{os.path.realpath(code.co_filename)}::{code.co_qualname}', set()).add(n)

CALLBACKS = ((E.PY_START, start), (E.PY_RESUME, resume), (E.PY_RETURN, ret), (E.PY_YIELD, yld),
             (E.PY_UNWIND, unwind), (E.LINE, line))

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    tid = M.PROFILER_ID if M.get_tool(M.PROFILER_ID) is None else 4
    M.use_tool_id(tid, 'leela-flow')
    for ev, fn in CALLBACKS: M.register_callback(tid, ev, fn)
    stack.clear()
    M.set_events(tid, EVENTS)
    try: yield
    finally:
        M.set_events(tid, 0)
        for ev, _ in CALLBACKS: M.register_callback(tid, ev, None)
        M.free_tool_id(tid)
        M.restart_events()

def pytest_sessionfinish(session, exitstatus):
    if not OUT: return
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(dict(calls=calls, lines={k: sorted(v) for k, v in lines.items()}, exitstatus=int(exitstatus)), f)
'''

def trace(
    python,        # the project's interpreter, which must have pytest
    root,          # the project root; only code under it is recorded
    test,          # a pytest node id, e.g. `tests/test_x.py::test_y`
    timeout=120,   # seconds before the run is killed
    env=None,      # the environment to run in; this process's when None
):
    "Run one pytest node under `PLUGIN`: the project calls it made, their arguments, and the lines that ran."
    with tempfile.TemporaryDirectory() as d:
        Path(d, '_leela_flow.py').write_text(PLUGIN, encoding='utf-8')
        out, base = Path(d, 'flow.json'), dict(os.environ if env is None else env)
        base.update(PYTHONPATH=os.pathsep.join(x for x in (d, base.get('PYTHONPATH', '')) if x), FLOW_OUT=str(out), FLOW_ROOT=str(root))
        # `-o addopts=` drops a configured `-n auto`: xdist workers would record into files nobody reads.
        cmd = [str(python), '-m', 'pytest', '-q', '-p', '_leela_flow', '-p', 'no:cacheprovider', '-o', 'addopts=', str(test)]
        try: p = subprocess.run(cmd, cwd=str(root), env=base, capture_output=True, text=True, errors='replace', timeout=timeout)
        except subprocess.TimeoutExpired: return dict(ok=False, calls=[], error=f'the test ran past {timeout}s')
        except OSError as e: return dict(ok=False, calls=[], error=f'could not start {python}: {e}')
        tail = f'{p.stdout or ""}{p.stderr or ""}'[-2000:]
        if not out.exists(): return dict(ok=False, calls=[], out=tail, error=f'pytest recorded nothing (exit {p.returncode}): {tail.strip()[-600:]}')
        got = json.loads(out.read_text(encoding='utf-8'))
    st = got.get('exitstatus')
    r = dict(ok=st == 0, calls=got.get('calls') or [], lines=got.get('lines') or {}, exitstatus=st, out=tail)
    if st != 0: r['error'] = f'pytest exited {st}: {tail.strip()[-600:]}'
    return r

def _def(tree, qualname):
    "The def `qualname` names, through classes and enclosing functions."
    node = tree
    for part in qualname.split('.'):
        if part == '<locals>': continue
        node = first(n for n in ast.iter_child_nodes(node)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == part)
        if node is None: return None
    return node

def unrun(file, qualname, ran):
    "Statement lines of `qualname` in `file` not in `ran`; nested defs are not entered."
    try: fn = _def(ast.parse(Path(file).read_text(encoding='utf-8')), qualname)
    except (OSError, SyntaxError, ValueError): return []
    if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)): return []
    body = fn.body[1:] if ast.get_docstring(fn) is not None else fn.body
    got, todo = set(), list(body)
    while todo:
        n = todo.pop()
        if isinstance(n, ast.stmt): got.add(n.lineno)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): continue
        todo.extend(c for c in ast.iter_child_nodes(n) if isinstance(c, (ast.stmt, ast.excepthandler, ast.match_case)))
    return sorted(got - set(ran))

def flow_path(root, entry, path=''):
    "Where the canvas for `entry` goes: `path`, else the first free `flows/<slug>.canvas.md`."
    root = Path(root)
    if path:
        p = root/path
        if not p.name.endswith('.canvas.md'): p = p.with_name(p.name + '.canvas.md')
        if not Path(_real(p)).is_relative_to(_real(root)): raise ValueError(f'{path} is outside the project {root}')
        return str(p)
    s = re.sub(r'[^a-z0-9]+', '-', str(entry).lower()).strip('-') or 'flow'
    p, i = root/'flows'/f'{s}.canvas.md', 2
    while p.exists(): p, i = root/'flows'/f'{s}-{i}.canvas.md', i + 1
    return str(p)

def _real(f): return os.path.realpath(f)

def functions(rows, root, traced=None):
    "The functions a canvas shows, in order, each with `path`, `symbol`, `module`, `depth`, `by` and its `call` when traced."
    fns = []
    for r in rows:
        rel, sym = cite(r['node'], r['file'], root)
        fns.append(dict(r, path=rel, symbol=sym, module=r['node'].removesuffix('.' + sym), key=(_real(r['file']), sym)))
    sym_of = {f['node']: f['symbol'] for f in fns}
    for f in fns: f['by'] = sym_of.get(f['parent'], f['parent'])
    calls = (traced or {}).get('calls') or []
    if not calls: return fns
    calls = _beneath(calls, fns[0]['key'] if fns else None)
    by_key, by_id, depth, out, seen = {f['key']: f for f in fns}, {c['id']: c for c in calls}, {}, [], set()
    for c in calls:
        par = by_id.get(c.get('parent'))
        depth[c['id']] = depth[par['id']] + 1 if par else 0
        key = (_real(c['file']), c['qualname'])
        if key in seen or '<locals>' in c['qualname']: continue
        seen.add(key)
        f = by_key.get(key)
        if f is None:
            rel = _rel(c['file'], root)
            f = dict(node='', file=c['file'], path=rel, symbol=c['qualname'], module=first(_modules(rel)) or '', key=key)
        out.append(dict(f, depth=depth[c['id']], by=par['qualname'] if par else '', call=c))
        if len(out) >= TRACED_CAP: break
    return out

def _beneath(calls, key):
    "The calls made beneath the first call to `key`, or every call when the run never made it."
    top = first(c for c in calls if (_real(c['file']), c['qualname']) == key)
    if top is None: return calls
    ids = {top['id']}
    for c in calls:
        if c.get('parent') in ids: ids.add(c['id'])
    return [c for c in calls if c['id'] in ids]

def _said(f, lines):
    "The note under a traced function: the recorded call, its result, and what did not run."
    c = f['call']
    a = ', '.join(f'{k}={v}' for k, v in (c.get('args') or {}).items() if k not in ('self', 'cls'))
    s = f"Recorded call: `{f['symbol'].rpartition('.')[2]}({a})` " + (f"raised `{c['raised']}`." if c.get('raised') else f"returned `{c.get('ret')}`.")
    if c.get('count', 1) > 1: s += f" Called {c['count']} times."
    ran = (lines or {}).get(f"{c['file']}::{c['qualname']}")
    if ran is not None and (miss := unrun(c['file'], c['qualname'], set(ran))): s += f" Lines not run in this trace: {', '.join(map(str, miss))}."
    return s

def _rerun(f):
    "A cell repeating the recorded call, for a module-level function whose arguments are all literals."
    c, name = f['call'], f['symbol']
    if '.' in name or not f.get('module') or c.get('posonly') or c.get('lazy') or not c.get('exact'): return ''
    a = ', '.join(f'{k}={v}' for k, v in (c.get('args') or {}).items())
    return f"from {f['module']} import {name}\n{name}({a})"

def _canvas(entry, fns, traced=None, test=''):
    n, lines = len(fns), (traced or {}).get('lines')
    c = Canvas(meta={'title': f'How {entry} works'})
    c.add(Brick('goal', f'How `{entry}` works: {n} function{"s" if n != 1 else ""}' + (f', traced through `{test}`' if traced else '')))
    for i, f in enumerate(fns, 1):
        c.add(Brick('text', f"## {i}. `{f['symbol']}`" + (f"\n\nCalled by `{f['by']}`." if f.get('by') else '')))
        c.add(Brick('snippet', '', attrs=dict(path=f['path'], symbol=f['symbol'])))
        if not f.get('call'): continue
        c.add(Brick('note', _said(f, lines)))
        if (code := _rerun(f)): c.add(Brick('code', code))
    return c

def build(entry, rows, root, traced=None, test=''):
    "The flow as a canvas: a goal, then per function a heading, its cited source and, when traced, the call it saw."
    return _canvas(entry, functions(rows, root, traced), traced, test)

def flow(
    g,             # a kosha `CodeGraph`
    root,          # the project root the snippets cite from
    entry,         # a dotted function name, or the tail of one
    python='',     # the project interpreter, needed to trace
    test='',       # a pytest node id that exercises the feature
    depth=2,       # how many calls deep the static walk goes
    path='',       # where to write, relative to `root`; `flows/<slug>.canvas.md` when empty
    k=None,        # a `Kosha`, to resolve an entry the graph does not name
    env=None,      # the environment the test runs in
):
    "Resolve `entry`, walk what it calls, trace `test` when given, and build the canvas. Writes nothing."
    node, cands = resolve(g, entry, k)
    if not node:
        return dict(ok=False, candidates=cands, error=f'no single function matches {entry!r}' +
                    (f"; candidates: {', '.join(cands)}" if cands else '; name it by its dotted path, e.g. package.module.function'))
    try: out = flow_path(root, entry, path)
    except ValueError as e: return dict(ok=False, candidates=[], error=str(e))
    rows, traced, note = slice_(g, node, depth), None, ''
    if test and python:
        t = trace(python, root, test, env=env)
        if t.get('calls'): traced = t
        if not t.get('ok'): note = (t.get('error') or '') + ('; the canvas shows what ran before it failed' if traced else '; the canvas is the static call graph')
    elif test: note = 'no project interpreter was found, so the test was not run; the canvas is the static call graph'
    fns = functions(rows, snip_root(out), traced)
    if traced and fns and fns[0]['symbol'] != cite(node, rows[0]['file'], root)[1]:
        note = (note + '; ' if note else '') + f'the test never called `{node}`, so the canvas shows everything it ran'
    c = _canvas(entry, fns, traced, test)
    c.path = out
    tree = '\n'.join(f"{'  ' * f['depth']}{i}. {f['symbol']}  ({_rel(f['file'], root)})" for i, f in enumerate(fns, 1))
    return dict(ok=True, node=node, path=out, canvas=c, traced=traced is not None, note=note, tree=tree)
