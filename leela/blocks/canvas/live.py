"The live half: one namespace per canvas, cells that run, and bindings that recompute when their inputs move."

from __future__ import annotations
import io, math, time, traceback
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import is_dataclass, asdict
from .doc import downstream, order

__all__ = ['Runtime', 'jsonable', 'stream', 'result', 'error_out', 'BOOT']

#: What every canvas namespace starts with. A learning document should not open with an import cell.
BOOT = "import math, random, json, statistics\nfrom datetime import date, datetime, timedelta\n"

def _records(v):
    to_dict = getattr(v, 'to_dict', None)
    return to_dict(orient='records') if to_dict else None

def jsonable(v, depth=0):
    "A value a brick can be drawn from: JSON where possible, a repr where not."
    if v is None or isinstance(v, (bool, int, str)): return v
    if isinstance(v, float): return v if math.isfinite(v) else repr(v)
    if depth > 6: return repr(v)
    if isinstance(v, dict): return {str(k): jsonable(x, depth + 1) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)): return [jsonable(x, depth + 1) for x in v]
    if is_dataclass(v) and not isinstance(v, type): return jsonable(asdict(v), depth + 1)
    if hasattr(v, 'tolist'): return jsonable(v.tolist(), depth + 1)
    rec = _records(v)
    if rec is not None: return jsonable(rec, depth + 1)
    return repr(v)

def stream(text, name='stdout'): return dict(output_type='stream', name=name, text=text)
def result(v): return dict(output_type='execute_result', data={'text/plain': repr(v)}, json=jsonable(v), metadata={})
def error_out(e):
    tb = traceback.format_exception(type(e), e, e.__traceback__)
    return dict(output_type='error', ename=type(e).__name__, evalue=str(e), traceback=[l.rstrip() for l in tb[-4:]])

class Runtime:
    "A canvas's namespace. In the IDE this is a kunda kernel; the spike runs it in process."
    def __init__(self, boot=BOOT):
        self.ns = {'__name__': 'canvas'}
        self.count = 0
        #: What each brick defined the last time it ran. A name a brick stops defining is dropped,
        #: so a renamed or deleted cell cannot leave the old name readable to everything downstream.
        self.owned = {}
        if boot: exec(compile(boot, '<boot>', 'exec'), self.ns)

    def run(self, brick):
        "Execute one code brick. Returns nbformat-shaped outputs and how long it took."
        out, err, t0 = io.StringIO(), io.StringIO(), time.perf_counter()
        outputs = []
        try:
            with redirect_stdout(out), redirect_stderr(err): value = self._exec(brick.body or '', brick.id)
            if value is not None: outputs.append(result(value))
        except Exception as e: outputs.append(error_out(e))
        for text, name in ((out.getvalue(), 'stdout'), (err.getvalue(), 'stderr')):
            if text: outputs.insert(0, stream(text, name))
        self.count += 1
        self.retire(brick)
        return dict(outputs=outputs, ms=(time.perf_counter() - t0) * 1000, count=self.count,
                    defs=list(brick.defs), ok=not any(o['output_type'] == 'error' for o in outputs))

    def retire(self, brick):
        "Drop the names this brick used to define and no longer does. Returns what went."
        now = set(brick.defs) if brick.runs else set()
        gone = self.owned.get(brick.id, set()) - now
        for n in gone: self.ns.pop(n, None)
        if now: self.owned[brick.id] = now
        else: self.owned.pop(brick.id, None)
        return sorted(gone)

    def forget(self, brick_id):
        "Drop every name one brick defined. What a removed brick leaves behind is nothing."
        gone = self.owned.pop(brick_id, set())
        for n in gone: self.ns.pop(n, None)
        return sorted(gone)

    def close(self):
        "Release whatever the namespace holds. In process there is nothing to release."
        self.ns.clear(); self.owned.clear()

    def _exec(self, src, tag):
        "Run a block and hand back its trailing expression, the way a notebook cell does."
        import ast
        tree = ast.parse(src)
        if tree.body and isinstance(tree.body[-1], ast.Expr):
            last = ast.Expression(tree.body.pop().value)
            exec(compile(tree, f'<{tag}>', 'exec'), self.ns)
            return eval(compile(last, f'<{tag}>', 'eval'), self.ns)
        exec(compile(tree, f'<{tag}>', 'exec'), self.ns)
        return None

    def value(self, expr):
        "Evaluate one binding expression against the namespace."
        try: return dict(ok=True, value=jsonable(eval(expr, self.ns)))
        except Exception as e: return dict(ok=False, error=f'{type(e).__name__}: {e}')

    def bindings(self, brick):
        "Every port on a brick, resolved. A failed port reports rather than blanking the brick."
        return {port: self.value(expr) for port, expr in (brick.binds or {}).items()}

    def set(self, name, value): self.ns[name] = value

    def run_all(self, bricks):
        "Every code brick in dependency order. What a canvas does when it opens."
        return {b.id: self.run(b) for b in order(bricks)}

    def react(self, bricks, names, skip=()):
        "Rerun what depends on `names` and re-resolve every binding it touched. `skip` has just run."
        runs, ports = {}, {}
        for b in downstream(bricks, names):
            if b.id in skip: continue
            if b.runs: runs[b.id] = self.run(b)
            if b.binds: ports[b.id] = self.bindings(b)
        return dict(runs=runs, ports=ports)
