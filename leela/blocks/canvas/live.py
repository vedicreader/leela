"The live half: one namespace per canvas, cells that run, and bindings that recompute when their inputs move."

from __future__ import annotations
import asyncio, io, json, math, threading, time, traceback
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import is_dataclass, asdict
from .doc import downstream, order

__all__ = ['Dataflow', 'Runtime', 'KernelRuntime', 'runtime_for', 'jsonable', 'stream', 'result',
           'error_out', 'BOOT', 'TIMEOUT']

#: What every canvas namespace starts with. A learning document should not open with an import cell.
BOOT = "import math, random, json, statistics\nfrom datetime import date, datetime, timedelta\n"
#: Seconds one cell may run before it is interrupted. A document is read on a phone, not batched.
TIMEOUT = 30

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

def _err(name, msg): return dict(output_type='error', ename=name, evalue=msg, traceback=[f'{name}: {msg}'])

class Dataflow:
    "The dataflow half, which is the same wherever the code runs."
    def __init__(self):
        self.count = 0
        #: What each brick defined the last time it ran. A name a brick stops defining is dropped,
        #: so a renamed or deleted cell cannot leave the old name readable to everything downstream.
        self.owned = {}

    def run(self, brick):
        "Execute one code brick. Returns nbformat-shaped outputs and how long it took."
        t0 = time.perf_counter()
        outputs = self.exec_cell(brick.body or '', brick.id)
        self.count += 1
        self.retire(brick)
        return dict(outputs=outputs, ms=(time.perf_counter() - t0) * 1000, count=self.count,
                    defs=list(brick.defs), ok=not any(o['output_type'] == 'error' for o in outputs))

    def retire(self, brick):
        "Drop the names this brick used to define and no longer does. Returns what went."
        now = set(brick.defs) if brick.runs else set()
        gone = self.owned.get(brick.id, set()) - now
        if gone: self.drop(sorted(gone))
        if now: self.owned[brick.id] = now
        else: self.owned.pop(brick.id, None)
        return sorted(gone)

    def forget(self, brick_id):
        "Drop every name one brick defined. What a removed brick leaves behind is nothing."
        gone = self.owned.pop(brick_id, set())
        if gone: self.drop(sorted(gone))
        return sorted(gone)

    def value(self, expr):
        "Evaluate one binding expression."
        return self.eval_many({'v': expr})['v']

    def bindings(self, brick):
        "Every port on a brick, resolved. A failed port reports rather than blanking the brick."
        return self.eval_many(dict(brick.binds or {}))

    def snapshot(self, names=None):
        "`{name: resolved}` for the names asked about, or every public one."
        return self.eval_many({n: n for n in (names or self.names())})

    def run_all(self, bricks):
        "Every code brick in dependency order. What a canvas does when it is trusted."
        return {b.id: self.run(b) for b in order(bricks)}

    def react(self, bricks, names, skip=()):
        "Rerun what depends on `names` and re-resolve every binding it touched. `skip` has just run."
        runs, ports = {}, {}
        for b in downstream(bricks, names):
            if b.id in skip: continue
            if b.runs: runs[b.id] = self.run(b)
            if b.binds: ports[b.id] = self.bindings(b)
        return dict(runs=runs, ports=ports)

    def close(self): pass

class Runtime(Dataflow):
    "This process's own namespace, for the spike and the tests, never the IDE's."
    def __init__(self, boot=BOOT):
        super().__init__()
        self.ns = {'__name__': 'canvas'}
        if boot: exec(compile(boot, '<boot>', 'exec'), self.ns)

    def exec_cell(self, src, tag='cell'):
        out, err, outputs = io.StringIO(), io.StringIO(), []
        try:
            with redirect_stdout(out), redirect_stderr(err): value = self._exec(src, tag)
            if value is not None: outputs.append(result(value))
        except Exception as e: outputs.append(error_out(e))
        for text, name in ((out.getvalue(), 'stdout'), (err.getvalue(), 'stderr')):
            if text: outputs.insert(0, stream(text, name))
        return outputs

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

    def eval_many(self, exprs):
        out = {}
        for key, expr in exprs.items():
            try: out[key] = dict(ok=True, value=jsonable(eval(expr, self.ns)))
            except Exception as e: out[key] = dict(ok=False, error=f'{type(e).__name__}: {e}')
        return out

    def ready(self, timeout=None): return True
    def assign(self, name, value): self.ns[name] = value
    set = assign
    def drop(self, names):
        for n in names: self.ns.pop(n, None)
    def names(self):
        "What the document has computed: not a private name, a function or an imported module."
        import types
        return sorted(k for k, v in self.ns.items()
                      if not k.startswith('_') and not callable(v) and not isinstance(v, types.ModuleType))
    def close(self): self.ns.clear(); self.owned.clear()

#: Defined inside the kernel so a binding can be resolved without shipping a value back as a repr.
KERNEL_BOOT = '''
import json as _cv_json_mod, math as _cv_math
def _cv_jsonable(v, depth=0):
    if v is None or isinstance(v, (bool, int, str)): return v
    if isinstance(v, float): return v if _cv_math.isfinite(v) else repr(v)
    if depth > 6: return repr(v)
    if isinstance(v, dict): return {str(k): _cv_jsonable(x, depth + 1) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)): return [_cv_jsonable(x, depth + 1) for x in v]
    if hasattr(v, 'tolist'): return _cv_jsonable(v.tolist(), depth + 1)
    to_dict = getattr(v, 'to_dict', None)
    if to_dict is not None:
        try: return _cv_jsonable(to_dict(orient='records'), depth + 1)
        except Exception: pass
    try:
        from dataclasses import is_dataclass, asdict as _cv_asdict
        if is_dataclass(v) and not isinstance(v, type): return _cv_jsonable(_cv_asdict(v), depth + 1)
    except Exception: pass
    return repr(v)
def _cv_eval(pairs):
    out = {}
    for key, expr in pairs.items():
        try: out[key] = {'ok': True, 'value': _cv_jsonable(eval(expr, globals()))}
        except Exception as e: out[key] = {'ok': False, 'error': f'{type(e).__name__}: {e}'}
    print(_cv_json_mod.dumps(out))
def _cv_names():
    import types as _cv_types
    _cv_skip = {'In', 'Out', 'exit', 'quit', 'get_ipython'}
    print(_cv_json_mod.dumps(sorted(k for k, v in list(globals().items())
                                    if not k.startswith('_') and k not in _cv_skip
                                    and not callable(v)
                                    and not isinstance(v, _cv_types.ModuleType))))
'''

class KernelRuntime(Dataflow):
    "Canvas code on a kunda kernel: another process, a bounded run, and an interrupt."
    def __init__(self, start, timeout=TIMEOUT, boot=BOOT, loop=None):
        super().__init__()
        #: `start` is kept, not just the kernel it returns: a kernel that dies is started again.
        self._start, self._kernel = start, None
        self.timeout, self._boot = timeout, (KERNEL_BOOT + (boot or ''))
        self._own_loop = loop is None
        self._lp, self._th, self._ready, self._pending, self._late = loop, None, False, None, False
        self._lp_lock = threading.Lock()

    def _loop(self):
        "A loop of this runtime's own, so a sync caller never drives the web process's loop."
        with self._lp_lock:
            if self._lp is None:
                self._lp = asyncio.new_event_loop()
                self._th = threading.Thread(target=self._lp.run_forever, daemon=True, name='canvas-runtime')
                self._th.start()
            return self._lp

    def _call(self, coro, timeout):
        return asyncio.run_coroutine_threadsafe(coro, self._loop()).result(timeout)

    def submit(self, coro, timeout=None):
        "Run `coro` on this runtime's loop and wait for it."
        return self._call(coro, timeout if timeout is not None else self.timeout + 15)

    async def _kernel_now(self):
        "The kernel, started on first use and again after one dies. A start that outlasts `timeout` keeps going, and calls fail at once until it is up."
        if self._kernel is None:
            if self._late and not self._pending.done(): raise TimeoutError('the kernel is still starting; try again shortly')
            if self._pending is None:
                k = self._start()
                if asyncio.iscoroutine(k) or asyncio.isfuture(k): self._pending = asyncio.ensure_future(k)
                else: self._kernel, self._ready = k, False
            if (p := self._pending) is not None:
                try: k = await asyncio.wait_for(asyncio.shield(p), self.timeout)
                except BaseException as e:
                    if p is not self._pending: raise
                    if p.done(): self._pending, self._late = None, False
                    elif isinstance(e, TimeoutError): self._late = True
                    raise
                if p is self._pending: self._pending, self._late, self._kernel, self._ready = None, False, k, False
        if not self._ready:
            self._ready = True                          # set first, or a failed boot boots again
            await self._bounded(self._kernel, self._boot, self.timeout)
        return self._kernel

    def ready(self, timeout=None):
        "Wait for the kernel to be up, however long a start that outlasted `timeout` takes. False if it did not come up."
        async def up():
            if (p := self._pending) is not None and not p.done(): await asyncio.wait({p})
            await self._kernel_now()
        try: self._call(up(), timeout)
        except Exception: return False
        return True

    async def _bounded(self, k, code, timeout):
        "Run `code`, and stop it when it outstays `timeout`."
        task = asyncio.ensure_future(k.execute(code, timeout=timeout))
        try: return await asyncio.wait_for(asyncio.shield(task), timeout)
        except (asyncio.TimeoutError, TimeoutError): pass
        why = f'nothing came back in {timeout}s'
        if not getattr(k, 'alive', True): why = 'the kernel died running this'   # `os._exit`, or a segfault
        else:
            try: await k.interrupt()
            except Exception: pass
            try: return await asyncio.wait_for(asyncio.shield(task), 5)
            except (asyncio.TimeoutError, TimeoutError): why += ', and it would not stop'
        task.cancel()
        try: await k.shutdown()
        except Exception: pass
        self._kernel, self._ready = None, False
        raise TimeoutError(f'{why}; the kernel was replaced and the namespace is gone')

    def exec_cell(self, src, tag='cell'):
        if not (src or '').strip(): return []
        try:
            r = self._call(self._run_code(src), self.timeout + 15)
            return list(getattr(r, 'outputs', None) or [])
        except TimeoutError as e: return [_err('TimeoutError', str(e))]
        except Exception as e: return [error_out(e)]

    async def _run_code(self, src):
        k = await self._kernel_now()
        if k is None: raise RuntimeError('no kernel')
        return await self._bounded(k, src, self.timeout)

    def _json_call(self, code, default):
        "Run a driver that prints one JSON line, and read it back."
        try: outs = self.exec_cell(code)
        except Exception: return default
        for o in outs:
            if o.get('output_type') == 'stream' and o.get('name') == 'stdout':
                for line in reversed(str(o.get('text') or '').splitlines()):
                    try: return json.loads(line)
                    except Exception: continue
        return default

    def eval_many(self, exprs):
        if not exprs: return {}
        got = self._json_call(f'_cv_eval({json.dumps(dict(exprs))})', None)
        if not isinstance(got, dict):
            return {k: dict(ok=False, error='the kernel did not answer') for k in exprs}
        return {k: got.get(k, dict(ok=False, error='no answer for this port')) for k in exprs}

    def assign(self, name, value):
        "A value the browser sent, put into the kernel as JSON rather than as a repr."
        self.exec_cell(f'{name} = __import__("json").loads({json.dumps(json.dumps(value))})')
    set = assign

    def drop(self, names):
        body = ', '.join(json.dumps(n) for n in names)
        self.exec_cell(f'for _cv_n in ({body},):\n    globals().pop(_cv_n, None)\ndel _cv_n')

    def names(self): return self._json_call('_cv_names()', []) or []

    def close(self):
        p = self._pending
        if self._kernel is None and p is not None and p.done() and not p.cancelled() and p.exception() is None: self._kernel = p.result()
        k, self._kernel, self._ready, self._pending, self._late = self._kernel, None, False, None, False
        self.owned.clear()
        if k is not None and hasattr(k, 'shutdown'):
            try: self._call(k.shutdown(), 10)
            except Exception: pass
        with self._lp_lock:
            lp, th = (self._lp, self._th) if self._own_loop else (None, None)
            if lp is not None: self._lp = None
        if lp is not None:
            async def cancel_rest():
                rest = asyncio.all_tasks() - {asyncio.current_task()}
                for t in rest: t.cancel()
                await asyncio.gather(*rest, return_exceptions=True)
            try: asyncio.run_coroutine_threadsafe(cancel_rest(), lp).result(10)
            except Exception: pass
            lp.call_soon_threadsafe(lp.stop)
            th.join(10)
            if not th.is_alive(): lp.close()

def runtime_for(pool=None, key='canvas', cwd=None, timeout=TIMEOUT):
    "A kernel-backed runtime where a pool can give one, and this process's namespace where none can."
    if pool is None: return Runtime()
    async def start():
        kw = {'cwd': str(cwd)} if cwd else {}
        return await pool.get(key, **kw)
    return KernelRuntime(start, timeout=timeout)
