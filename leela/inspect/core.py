"""Variable info, representations, resolvers and snapshots for python namespaces.

This is the inspection engine: it turns a live namespace into the grouped, expandable
node tree both leela frontends render. Vendored from dhrishti, where it was authored
literately under nbdev; leela owns it as plain Python now."""


__all__ = ['leela_cfg', 'LAZY', 'MAX_CHILDREN', 'GROUPS', 'PROFILES', 'SORTS', 'GRUV', 'GHDK', 'PALETTES', 'VarInfo',
           'safe_repr', 'get_shape', 'get_dtype', 'Resolver', 'DictResolver', 'ListTupleResolver', 'SetResolver',
           'DequeResolver', 'ObjectResolver', 'array_detail', 'frame_detail', 'series_detail', 'ArrayResolver',
           'FrameResolver', 'SeriesResolver', 'register_resolver', 'resolve_for', 'is_gridable', 'array_page',
           'register_str_provider', 'str_provider', 'provided_str', 'value_str', 'var_info', 'snapshot', 'walk',
           'expand', 'grid_page', 'category', 'sort_keys', 'profile_view']

import inspect, itertools, pathlib, datetime, enum, uuid
from collections import deque
from dataclasses import dataclass

from .. import leela_cfg
from IPython.core.formatters import _safe_repr
import numpy as np
import pandas as pd


LAZY = '…'
@dataclass
class VarInfo:
	'One inspector row: a namespace binding or a container child.'
	name:str
	type:str
	qualifier:str=''
	value:str=''
	shape:str|None=None
	dtype:str|None=None
	is_container:bool=False
	is_grid:bool=False
	is_error:bool=False
	path:str=''
	accessor:tuple=()
	more_offset:int|None=None

def safe_repr(v, n=300): return r[:n-1] if len(r:=_safe_repr(v))>n else r

def get_shape(v):
	'tuple(v.shape) as a string; else len(v) for sized non-strings; else None.'
	try:
		s = getattr(v, 'shape', None)
		if s is not None and not callable(s): return str(tuple(s))
		if hasattr(v, '__len__') and not isinstance(v, (str, bytes, bytearray)): return str(len(v))
	except Exception: return None
	return None

def get_dtype(v):
	'str(v.dtype) when present, else None.'
	try: return str(d) if (d:=getattr(v, 'dtype', None)) is not None else None
	except: return None

class Resolver:
	'Decides if a value is a container and yields its ordered children.'
	def can(self, v): raise NotImplementedError
	def children(self, v): raise NotImplementedError   # -> list[(name, step, child)]

class DictResolver(Resolver):
	def can(self, v): return isinstance(v, dict)
	def children(self, v): return [(repr(k), f'[{k!r}]', val) for k,val in v.items()]

class ListTupleResolver(Resolver):
	def can(self, v): return isinstance(v, (list, tuple))
	def children(self, v): return [(str(i), f'[{i}]', x) for i,x in enumerate(v)]

class SetResolver(Resolver):
	'Sets: positional children in a stable order (sorted by repr); path fragment is display-only, not index-addressable.'
	def can(self, v): return isinstance(v, (set, frozenset))
	def children(self, v): return [(str(i), f'[{i}]', x) for i,x in enumerate(sorted(v, key=repr))]

class DequeResolver(Resolver):
	'Deques: positional, index-addressable children (deque supports d[i]).'
	def can(self, v): return isinstance(v, deque)
	def children(self, v): return [(str(i), f'[{i}]', x) for i,x in enumerate(v)]

_LEAF = (bool, int, float, complex, str, bytes, bytearray, type(None))

def _slot_names(v):
	'Slot names declared across v\'s MRO (excluding __dict__/__weakref__).'
	out = []
	for c in type(v).__mro__:
		s = getattr(c, '__slots__', ())
		if isinstance(s, str): s = (s,)
		out += [n for n in s if n not in ('__dict__', '__weakref__')]
	return out

class ObjectResolver(Resolver):
	'Catch-all like pydev\'s DefaultResolver: dir()-based children so __slots__ objects, properties and class attrs all expand; dunders and callables are skipped.'
	def can(self, v):
		if isinstance(v, _LEAF): return False
		return bool(getattr(v, '__dict__', None)) or bool(_slot_names(v)) or hasattr(v, '__members__')
	def _keep(self, v, k):
		if k.startswith('__') and k.endswith('__'): return False
		try: a = getattr(v, k)
		except: return True   # surface attribute errors as a child rather than hide the name
		return not (inspect.isroutine(a) or inspect.isbuiltin(a) or inspect.ismodule(a))
	def children(self, v):
		names = dir(v) or list(getattr(v, '__members__', ()))
		out = []
		for k in sorted(n for n in names if self._keep(v, n)):
			try: out.append((k, f'.{k}', getattr(v, k)))
			except Exception as e: out.append((k, f'.{k}', f'<error {type(e).__name__}: {e}>'))
		return out

_MAX_ELEMS = 90   # element rows generated per expand (metadata rows add on top; keeps total under snapshot MAX_CHILDREN)

def _stat(fn):
	'Call a numpy/pandas reduction, returning None if it raises (e.g. non-numeric data).'
	try: return fn()
	except Exception: return None

def array_detail(v):
	'Curated child rows for an ndarray: metadata, numeric stats, then indexed elements (capped).'
	rows = [('shape', '.shape', v.shape), ('dtype', '.dtype', v.dtype), ('size', '.size', v.size)]
	rows += [(nm, f'.{nm}()', s) for nm,fn in [('min',v.min),('max',v.max),('mean',v.mean),
	                                           ('std',v.std),('sum',v.sum)] if (s:=_stat(fn)) is not None]
	rows += [(str(i), f'[{i}]', x) for i,x in itertools.islice(enumerate(v), _MAX_ELEMS)]
	n = len(v)
	if n > _MAX_ELEMS: rows.append(('…', '', f'{n-_MAX_ELEMS} more'))
	return rows

def frame_detail(v):
	'Curated child rows for a DataFrame: metadata then each column as a Series.'
	return [('shape', '.shape', v.shape), ('size', '.size', v.size), ('dtypes', '.dtypes', v.dtypes),
	        *[(str(c), f'[{c!r}]', v[c]) for c in v.columns]]

def series_detail(v):
	'Curated child rows for a Series: metadata then indexed elements (capped).'
	rows = [('dtype', '.dtype', v.dtype), ('size', '.size', v.size), ('name', '.name', v.name)]
	rows += [(str(ix), f'.iloc[{i}]', x) for i,(ix,x) in itertools.islice(enumerate(v.items()), _MAX_ELEMS)]
	n = len(v)
	if n > _MAX_ELEMS: rows.append(('…', '', f'{n-_MAX_ELEMS} more'))
	return rows

class ArrayResolver(Resolver):
	'Expands an ndarray into stats + element rows (peers the grid table).'
	def can(self, v): return isinstance(v, np.ndarray) and v.ndim >= 1
	def children(self, v): return array_detail(v)

class FrameResolver(Resolver):
	'Expands a DataFrame into metadata + column Series.'
	def can(self, v): return isinstance(v, pd.DataFrame)
	def children(self, v): return frame_detail(v)

class SeriesResolver(Resolver):
	'Expands a Series into metadata + element rows.'
	def can(self, v): return isinstance(v, pd.Series)
	def children(self, v): return series_detail(v)

_RESOLVERS = [DictResolver(), ListTupleResolver(), SetResolver(), DequeResolver(), ArrayResolver(), FrameResolver(),
              SeriesResolver(), ObjectResolver()]

def register_resolver(r, last=False):
	'Register a resolver; inserted before the catch-all ObjectResolver unless last=True.'
	_RESOLVERS.insert(len(_RESOLVERS) if last else len(_RESOLVERS)-1, r)

def resolve_for(v):
	'First resolver that handles v, else None (None => not a container).'
	for r in _RESOLVERS:
		try:
			if r.can(v): return r
		except: continue
	return None

def is_gridable(v):
	'True for a numpy ndarray (1-2D) or a pandas DataFrame/Series.'
	if isinstance(v, np.ndarray): return v.ndim in (1, 2)
	return True if isinstance(v, (pd.DataFrame, pd.Series)) else False

def _cell(x): return safe_repr(x,40)

def array_page(v, roff=0, coff=0, rows=50, cols=50):
	'Page a gridable value -> dict(headers,index,cells,nrows,ncols,roff,coff,rows,cols), or None.'
	if isinstance(v, pd.DataFrame):
		nrows, ncols = v.shape
		sub = v.iloc[roff:roff+rows, coff:coff+cols]
		headers = [str(c) for c in sub.columns]
		index = [str(i) for i in sub.index]
		cells = [[_cell(x) for x in row] for row in sub.values.tolist()]
	elif isinstance(v, pd.Series):
		nrows, ncols = v.shape[0], 1
		sub = v.iloc[roff:roff+rows]
		headers = [str(v.name) if v.name is not None else 'value']
		index = [str(i) for i in sub.index]
		cells = [[_cell(x)] for x in sub.tolist()]
	elif isinstance(v, np.ndarray) and v.ndim == 2:
		nrows, ncols = v.shape
		sub = v[roff:roff+rows, coff:coff+cols]
		headers = [str(c) for c in range(coff, min(coff+cols, ncols))]
		index = [str(r) for r in range(roff, min(roff+rows, nrows))]
		cells = [[_cell(x) for x in row] for row in sub.tolist()]
	elif isinstance(v, np.ndarray) and v.ndim == 1:
		nrows, ncols = v.shape[0], 1
		sub = v[roff:roff+rows]
		headers = ['0']
		index = [str(r) for r in range(roff, min(roff+rows, nrows))]
		cells = [[_cell(x)] for x in sub.tolist()]
	else: return None
	return {'headers': headers, 'index': index, 'cells': cells, 'nrows': nrows, 'ncols': ncols, 'roff': roff,
	        'coff': coff, 'rows': rows, 'cols': cols}

_PROVIDERS = []

def register_str_provider(typ, fn):
	'Register fn(value)->str as the display string for instances of typ (and subclasses).'
	_PROVIDERS.append((typ, fn))

def str_provider(typ):
	'Decorator: @str_provider(T) registers the decorated fn as T\'s value-string provider.'
	def deco(fn): register_str_provider(typ, fn); return fn
	return deco

def provided_str(v):
	'Custom display string for v (latest-registered isinstance match), or None.'
	for typ, fn in reversed(_PROVIDERS):
		try:
			if isinstance(v, typ): return fn(v)
		except: continue
	return None

def value_str(v):
	'Display string for v: a registered provider if any, else safe_repr(v).'
	s = provided_str(v)
	return s if s is not None else safe_repr(v)

def _bytes_str(b):
	h = bytes(b[:8]).hex()
	return f'{h}… ({len(b)} bytes)' if len(b) > 8 else f'{h} ({len(b)} bytes)'

register_str_provider(pathlib.Path, lambda p: str(p))
register_str_provider(datetime.date, lambda d: d.isoformat())
register_str_provider(datetime.time, lambda t: t.isoformat())
register_str_provider(datetime.datetime, lambda d: d.isoformat())
register_str_provider(enum.Enum, lambda e: f'{type(e).__name__}.{e.name}')
register_str_provider(uuid.UUID, lambda u: str(u))
register_str_provider(bytes, _bytes_str)
register_str_provider(bytearray, _bytes_str)
register_str_provider(np.ndarray, lambda a: f'ndarray shape={tuple(a.shape)} {a.dtype}')
register_str_provider(np.generic, lambda x: str(x))
register_str_provider(np.dtype, lambda d: str(d))
register_str_provider(pd.DataFrame, lambda d: f'DataFrame [{d.shape[0]}×{d.shape[1]}]')
register_str_provider(pd.Series, lambda s: f'Series [{s.shape[0]}] {s.dtype}')

MAX_CHILDREN = 100   # page size for one expand call

def var_info(name, v, accessor, path):
	'Build a VarInfo for one value at the given accessor/path.'
	try: return VarInfo(name=name, type=type(v).__name__, qualifier=getattr(type(v), '__module__', '') or '',
		value=value_str(v), shape=get_shape(v), dtype=get_dtype(v), is_container=resolve_for(v) is not None,
		is_grid=is_gridable(v), path=path, accessor=accessor)
	except Exception as e: return VarInfo(name=name, type='?', value=f'<error {e}>', is_error=True, path=path, accessor=accessor)

def snapshot(ns, hidden=frozenset(), name=None, typ=None):
	'namespace dict -> sorted list[VarInfo], skipping hidden/dunder; optional name-substring & type-name filters.'
	keys = sorted(k for k in ns if k not in hidden and not k.startswith('__'))
	if name: keys = [k for k in keys if name.lower() in k.lower()]
	if typ:  keys = [k for k in keys if ns[k].__class__.__name__.lower() == typ.lower()]
	return [var_info(k, ns[k], (k,), k) for k in keys]

def walk(ns, accessor):
	'Resolve a positional accessor (name, *idxs) to (object, readable_path). Raises KeyError/IndexError on bad path.'
	name, *idxs = accessor
	obj, path = ns[name], name
	for i in idxs:
		r = resolve_for(obj)
		if r is None: raise KeyError(accessor)
		_, step, obj = r.children(obj)[i]
		path += step
	return obj, path

def expand(ns, accessor, offset=0, limit=MAX_CHILDREN):
	'One level of children of the value at accessor as VarInfo, windowed to kids[offset:offset+limit]; a load-more sentinel (more_offset set) trails a partial window.'
	try: obj, path = walk(ns, tuple(accessor))
	except Exception: return []
	r = resolve_for(obj)
	if r is None: return []
	kids = r.children(obj)
	out = [var_info(nm, child, tuple(accessor) + (offset + i,), path + step)
	       for i,(nm, step, child) in enumerate(kids[offset:offset+limit])]
	if len(kids) > offset+limit:
		out.append(VarInfo(name='…', type='', value=f'{len(kids)-(offset+limit)} more',
           path=path, accessor=tuple(accessor), more_offset=offset+limit))
	return out

def grid_page(ns, accessor, roff=0, coff=0, rows=50, cols=50):
	'Walk accessor to a gridable object and return a page dict, or None.'
	try:
		obj, _ = walk(ns, tuple(accessor))
		if not is_gridable(obj): return None
		return array_page(obj, roff, coff, rows, cols)
	except: return None

def category(name, v, hidden=frozenset()):
	'Classify a namespace entry: \'special\' | \'module\' | \'type\' | \'function\' | \'data\'.'
	if name in hidden or name.startswith('_') or name in ('In','Out','exit','quit','get_ipython'): return 'special'
	if inspect.ismodule(v): return 'module'
	if isinstance(v, type): return 'type'
	if callable(v): return 'function'
	return 'data'

GROUPS = {'special':'Special Variables', 'type':'Types', 'function':'Functions', 'module':'Modules'}

# profile -> per-category disposition: 'top' | 'group' | 'hidden' ('data' is always top-level)
PROFILES = {
	'minimal':  {'type':'hidden', 'function':'group', 'module':'hidden', 'special':'hidden'},
	'standard': {'type':'group',  'function':'group',  'module':'group',  'special':'group'},
	'full':     {'type':'top',    'function':'top',    'module':'top',    'special':'group'},
	}

SORTS = ('name', 'recent', 'type', 'size')   # tree sort orders shared by every frontend

def _size_of(v):
	'Best-effort element count for size sorting (ndarray/DataFrame .size, else len, else 0).'
	try:
		s = getattr(v, 'size', None)
		if isinstance(s, int): return s
		return len(v)
	except Exception: return 0

def sort_keys(ns, keys, sort='name', order=None):
	'Order namespace `keys` by `sort` (name|recent|type|size); `order` is a name->version map (higher = more recent).'
	order = order or {}
	if sort == 'recent': return sorted(keys, key=lambda k: (-order.get(k, 0), k.lower()))
	if sort == 'type':   return sorted(keys, key=lambda k: (type(ns[k]).__name__.lower(), k.lower()))
	if sort == 'size':   return sorted(keys, key=lambda k: (-_size_of(ns[k]), k.lower()))
	return sorted(keys)   # name (default)

def profile_view(ns, hidden=frozenset(), profile='standard', sort='name', order=None):
	'Group a namespace per profile, ordered within each group by `sort` -> ordered list[(label|None, [VarInfo])].'
	disp = PROFILES.get(profile, PROFILES['standard'])
	cats = {}
	for k in sort_keys(ns, list(ns), sort, order):
		cats.setdefault(category(k, ns[k], hidden), []).append(var_info(k, ns[k], (k,), k))
	out = [(None, cats.get('data', []))]
	for c in ('module', 'type', 'function', 'special'):
		vs = cats.get(c)
		if not vs: continue
		d = disp.get(c, 'group')
		if d == 'top':     out.append((None, vs))
		elif d == 'group': out.append((GROUPS[c], vs))
		# 'hidden' -> omit
	return [(lbl, vs) for lbl, vs in out if vs]

GRUV = dict(
	bg_h='#1d2021', bg='#282828', bg1='#3c3836', bg2='#504945', bg3='#665c54', bg4='#7c6f64',
	fg='#ebdbb2', fg2='#d5c4a1', fg4='#a89984', gray='#928374',
	red='#fb4934', green='#b8bb26', yellow='#fabd2f', blue='#83a598',
	purple='#d3869b', aqua='#8ec07c', orange='#fe8019', primary='#8ec07c')

GHDK = dict(
	bg_h='#0d1117', bg='#161b22', bg1='#21262d', bg2='#30363d', bg3='#484f58', bg4='#6e7681',
	fg='#e6edf3', fg2='#c9d1d9', fg4='#8b949e', gray='#6e7681',
	red='#ff7b72', green='#3fb950', yellow='#d29922', blue='#58a6ff',
	purple='#bc8cff', aqua='#39c5cf', orange='#f0883e', primary='#58a6ff')

PALETTES = {'gruvbox': GRUV, 'github-dark': GHDK}
