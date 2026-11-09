"Plain data across a process line: a tagged JSON form for the few exact types a scrub may copy. Self-contained: the kernel runs its text, the worker imports it."
import base64, datetime as dt, json, sys

CAP = 10**5
NP_KINDS = 'biufcmMSU'

class Bad(Exception): pass

def _b64(b): return base64.b64encode(b).decode()

def _nd(np, a, spend):
    if type(a) is not np.ndarray or a.dtype.kind not in NP_KINDS or a.dtype.fields is not None or a.dtype.subdtype is not None: raise Bad(f'an array of {a.dtype}')
    spend(a.size)
    return {'t': 'nd', 'dtype': a.dtype.str, 'shape': list(a.shape), 'v': _b64(np.ascontiguousarray(a).tobytes())}

def _strs(vals, spend):
    spend(len(vals))
    if not all(type(v) is str for v in vals): raise Bad('text that is not all str')
    return {'t': 'strs', 'v': list(vals)}

def _index(pd, np, ix, spend):
    if type(ix) is pd.RangeIndex:
        if type(ix.name) not in (str, type(None)): raise Bad('an index name')
        return {'t': 'range', 'v': [ix.start, ix.stop, ix.step], 'name': ix.name}
    if type(ix) is not pd.Index or type(ix.name) not in (str, type(None)): raise Bad('an index that is not plain')
    a = ix.to_numpy()
    out = _strs(a.tolist(), spend) if a.dtype.kind == 'O' else _nd(np, a, spend)
    return {**out, 'name': ix.name}

def _col(pd, np, s, spend):
    dtype = s.dtype
    if isinstance(dtype, np.dtype) and dtype.kind in 'biufcmM': return _nd(np, s.to_numpy(), spend)
    if isinstance(dtype, pd.StringDtype): return _strs(s.tolist(), spend)
    raise Bad(f'a column of {dtype}')

def encode(x, budget=None, seen=None, depth=0):
    "`x` as JSON-ready data, or `Bad` when it is not an exact plain type or is over the element cap."
    budget = [CAP] if budget is None else budget
    seen = set() if seen is None else seen
    if depth > 30: raise Bad('nested too deeply')
    def spend(n):
        budget[0] -= n
        if budget[0] < 0: raise Bad(f'bigger than {CAP} elements')
    t = type(x)
    if t in (type(None), bool, int, float, str): spend(1); return x
    if t is bytes: spend(len(x) // 8 + 1); return {'t': 'bytes', 'v': _b64(x)}
    if t is complex: spend(1); return {'t': 'complex', 'v': [x.real, x.imag]}
    if t in (list, tuple, set, frozenset, dict):
        if id(x) in seen: raise Bad('a container that holds itself')
        seen.add(id(x))
        try:
            rec = lambda v: encode(v, budget, seen, depth + 1)
            v = [[rec(k), rec(val)] for k, val in x.items()] if t is dict else [rec(i) for i in x]
        finally: seen.discard(id(x))
        return {'t': t.__name__, 'v': v}
    if t in (dt.datetime, dt.time) and x.tzinfo is not None: raise Bad('a time zone')
    if t is dt.datetime or t is dt.date or t is dt.time: spend(1); return {'t': t.__name__, 'v': x.isoformat()}
    if t is dt.timedelta: spend(1); return {'t': 'timedelta', 'v': [x.days, x.seconds, x.microseconds]}
    np, pd = sys.modules.get('numpy'), sys.modules.get('pandas')
    if np is not None:
        if t is np.ndarray: return _nd(np, x, spend)
        if isinstance(x, np.generic) and t.__module__ == 'numpy' and x.dtype.kind in NP_KINDS:
            spend(1); return {**_nd(np, np.asarray(x), spend), 't': 'npscalar'}
    if pd is not None and np is not None:
        if t is pd.Series:
            if type(x.name) not in (str, int, type(None)): raise Bad('a series name')
            return {'t': 'series', 'name': x.name, 'index': _index(pd, np, x.index, spend), 'v': _col(pd, np, x, spend)}
        if t is pd.DataFrame:
            if type(x.columns) is not pd.Index or not x.columns.is_unique or not all(type(c) in (str, int) for c in x.columns): raise Bad('columns that are not plain names')
            return {'t': 'frame', 'index': _index(pd, np, x.index, spend), 'cols': [[c, _col(pd, np, x[c], spend)] for c in x.columns]}
    raise Bad(f'a {t.__module__}.{t.__qualname__}' if t.__module__ != 'builtins' else f'a {t.__qualname__}')

def decode(o):
    "The value `encode` made `o` from."
    if not isinstance(o, dict): return o
    t = o['t']
    if t in ('list', 'tuple', 'set', 'frozenset'): return {'list': list, 'tuple': tuple, 'set': set, 'frozenset': frozenset}[t](decode(i) for i in o['v'])
    if t == 'dict': return {decode(k): decode(v) for k, v in o['v']}
    if t == 'bytes': return base64.b64decode(o['v'])
    if t == 'complex': return complex(*o['v'])
    if t == 'datetime': return dt.datetime.fromisoformat(o['v'])
    if t == 'date': return dt.date.fromisoformat(o['v'])
    if t == 'time': return dt.time.fromisoformat(o['v'])
    if t == 'timedelta': return dt.timedelta(*o['v'])
    import numpy as np
    if t in ('nd', 'npscalar'):
        a = np.frombuffer(base64.b64decode(o['v']), dtype=np.dtype(o['dtype'])).reshape(o['shape']).copy()
        return a[()] if t == 'npscalar' else a
    import pandas as pd
    def ix(i):
        if i['t'] == 'range': return pd.RangeIndex(*i['v'], name=i['name'])
        return pd.Index(i['v'] if i['t'] == 'strs' else decode(i), name=i['name'])
    col = lambda c: c['v'] if c['t'] == 'strs' else decode(c)
    if t == 'series': return pd.Series(col(o['v']), index=ix(o['index']), name=o['name'])
    if t == 'frame': return pd.DataFrame({c: col(v) for c, v in o['cols']}, index=ix(o['index']))
    raise ValueError(f'unknown tag {t}')

def snapshot_json(ns, names):
    "JSON for the names of `ns` that `encode` accepts: `{'ok': {name: data}, 'missing': [...]}`, or `{'bad': name, 'why': text}` for the first that it does not."
    out, missing = {}, []
    for n in names:
        if n not in ns: missing.append(n); continue
        try: out[n] = encode(ns[n])
        except Bad as e: return json.dumps({'bad': n, 'why': str(e)})
        except Exception as e: return json.dumps({'bad': n, 'why': f'a value that could not be read ({type(e).__name__})'})
    return json.dumps({'ok': out, 'missing': missing})
