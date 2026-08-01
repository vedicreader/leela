"""Executing code in a namespace, completing names in it, and logging what ran.

`Bridge` is the seam the server talks through: it reads the namespace live on every
call, which is why the inspector never needs cache invalidation."""


__all__ = ['SESSION_DIR', 'ExecResult', 'fmt_err', 'exec_capture', 'flat_result', 'ns_complete', 'ip_complete', 'complete',
           'current_session', 'set_logging', 'hist_path', 'log_run', 'history', 'list_sessions', 'read_session', 'run',
           'set_value', 'IPythonClient', 'NsClient', 'Bridge', 'on_change']

from dataclasses import dataclass
import ast,datetime, re, builtins, keyword, IPython
from fastcore.xtras import Path
from fastcore.nbio import read_nb, write_nb, new_nb, mk_cell
from IPython import get_ipython
from IPython.utils.capture import capture_output
from .core import *

@dataclass
class ExecResult:
	'Outcome of running code: last value as an inspector row, captured stdout, and error text.'
	ok: bool; result: VarInfo|None = None; stdout: str = ''; error: str|None = None

def fmt_err(res):
	'Formatted exception text from a run_cell result, or None.'
	e = getattr(res, 'error_in_exec', None) or getattr(res, 'error_before_exec', None)
	return f'{type(e).__name__}: {e}' if e is not None else None

def exec_capture(code, ns):
	'Exec statements in ns; return the value of a trailing expression, else None.'
	block = ast.parse(code)
	value = None
	if block.body and isinstance(block.body[-1], ast.Expr):
		last = ast.Expression(block.body.pop().value)
		exec(compile(block, '<leela>', 'exec'), ns)
		value = eval(compile(last, '<leela>', 'eval'), ns)
	else: exec(compile(block, '<leela>', 'exec'), ns)
	return value

def flat_result(val):
	'A non-expandable result row (isolated mode leaves nothing reachable in user_ns).'
	return VarInfo(name='result', type=type(val).__name__, value=value_str(val))

def ns_complete(code, pos, ns):
	'Namespace completion fallback when there is no IPython kernel (headless serve()).'
	tok = re.search(r'[\w.]*$', code[:pos]).group(0)
	if not tok: return {'from': pos, 'matches': []}
	if '.' in tok:
		base, _, prefix = tok.rpartition('.')
		try: obj = eval(base, {'__builtins__': builtins}, ns)     # evaluated in the inspected namespace only
		except Exception: return {'from': pos, 'matches': []}
		cands = [a for a in dir(obj) if a.startswith(prefix) and (prefix or not a.startswith('_'))]
		return {'from': pos - len(prefix), 'matches': sorted(cands)[:50]}
	names = set(ns) | set(dir(builtins)) | set(keyword.kwlist)
	cands = [n for n in names if n.startswith(tok)]
	return {'from': pos - len(tok), 'matches': sorted(cands)[:50]}

def ip_complete(ip, code, pos):
	'Real IPython InteractiveShell.complete(text, line, cursor) -> (pre, matches); None if that signature doesn\'t apply.'
	bol = code.rfind('\n', 0, pos) + 1                     # current physical line + cursor within it:
	eol = code.find('\n', pos); eol = len(code) if eol < 0 else eol   # gives IPython the `import ...`
	line, cur = code[bol:eol], pos - bol                   # context so venv modules complete too
	token = re.search(r'[\w.]*$', code[:pos]).group(0)
	cmp = getattr(ip, 'Completer', None)   # real kernel: legacy ip.complete() returns nothing while Jedi is on
	old = getattr(cmp, 'use_jedi', None)
	if cmp is not None: cmp.use_jedi = False
	try: pre, matches = ip.complete(token, line, cur)
	except: return None
	finally: setattr(cmp, 'use_jedi', old) if old else None   # restore so the user's own tab-completion keeps Jedi
	return {'from': pos - len(pre), 'matches': list(matches)[:50]}

def complete(code, pos, ns=None):
	'Completions for the token ending at offset `pos` -> {\'from\': int, \'matches\': [str]}. Handles execnb\'s CaptureShell completer (single-arg, what `serve` runs on), a real IPython kernel, and a headless namespace fallback.'
	ip = get_ipython()
	if ip is None: return ns_complete(code, pos, ns or {})
	prefix = code[:pos]
	try: matches = ip.complete(prefix)   # execnb CaptureShell.complete(c) -> [tail matches]
	except: matches = None
	if isinstance(matches, list):        # tail after the last dot is what those matches replace
		tail = re.search(r'[\w.]*$', prefix).group(0).rpartition('.')[-1]
		return {'from': pos - len(tail), 'matches': matches[:50]}
	return ip_complete(ip, code, pos) or {'from': pos, 'matches': []}

SESSION_DIR = Path('leela_sessions')   # created lazily: nothing lands on disk until something is logged
_LEGACY_DIR = Path('dhristi_sessions')    # the old misspelling; still read so existing logs stay reachable
_SESSION = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
_log_on = True

def current_session():
	"Stem of the notebook `run` appends to. One rolling file, not one per process."
	return 'history'

def set_logging(on=True, dir=None):
	'Turn run logging on/off, and optionally point it at another directory; returns the directory in force.'
	global _log_on, SESSION_DIR
	_log_on = on
	if dir is not None: SESSION_DIR = Path(dir)
	return SESSION_DIR

def hist_path():
	'The single rolling notebook every global exec is appended to.'
	return SESSION_DIR/f'{current_session()}.ipynb'

def log_run(code, path=None, cell_type='code'):
	'''Append `code` to the rolling history notebook, or to an explicit `path` (agent transcripts).
	Best-effort; never raises. With logging off an implicit log is a no-op, and no directory is created.'''
	if path is None and not _log_on: return
	try:
		p = Path(path) if path else hist_path()
		p.parent.mkdir(parents=True, exist_ok=True)
		nb = read_nb(p) if p.exists() else new_nb([])
		nb['cells'].append(mk_cell(code, cell_type))
		write_nb(nb, p)
	except: pass

def history(n=None, path=None):
	'Code cells of the rolling history notebook, newest last - what the exec box cycles through.'
	p = Path(path) if path else hist_path()
	if not p.exists(): return []
	try: cells = [c['source'] for c in read_nb(p)['cells'] if c.get('cell_type')=='code']
	except: return []
	return cells[-n:] if n else cells

def list_sessions():
	'Logged notebooks (rolling history, agent transcripts, legacy per-run sessions), newest first, as [(stem, n_code_cells)].'
	out, seen = [], set()
	for d in (SESSION_DIR, _LEGACY_DIR):
		if not d.exists(): continue
		for p in sorted(d.glob('*.ipynb'), reverse=True):
			if p.stem in seen: continue
			seen.add(p.stem)
			try: n = sum(c.get('cell_type')=='code' for c in read_nb(p)['cells'])
			except: n = 0
			out.append((p.stem, n))
	return out

def read_session(name):
	'Code-cell sources for a logged notebook by stem; [] if missing, or if the name would escape the session dir.'
	if '/' in name or chr(92) in name or name.startswith('.'): return []
	for d in (SESSION_DIR, _LEGACY_DIR):
		p = d/f'{name}.ipynb'
		if p.exists():
			try: return [c['source'] for c in read_nb(p)['cells'] if c.get('cell_type')=='code']
			except: return []
	return []


def run(code, scope='global'):
	'Run `code` in the kernel; scope=\'global\' mutates user_ns, \'isolated\' uses a scratch copy.'
	ip = get_ipython()
	if ip is None: return ExecResult(ok=False, error='no IPython kernel')
	if scope == 'isolated':
		try:
			with capture_output() as cap: val = exec_capture(code, dict(ip.user_ns))
			return ExecResult(ok=True, result=None if val is None else flat_result(val), stdout=cap.stdout)
		except Exception as e: return ExecResult(ok=False, error=f'{type(e).__name__}: {e}')
	log_run(code)
	with capture_output() as cap: res = ip.run_cell(code, store_history=True)
	err = fmt_err(res)
	result = var_info('result', res.result, ('_',), '_') if res.result is not None else None
	return ExecResult(ok=bool(res.success) and err is None, result=result, stdout=cap.stdout, error=err)

def set_value(accessor, expr, ns=None):
	"Assign `expr` (evaluated in user_ns) to the lvalue at `accessor`; return error text or None."
	ns = ns or (ip.user_ns if (ip:=get_ipython()) else None)
	if not ns: return 'no IPython kernel'
	try: _, path = walk(ns, tuple(accessor))
	except Exception as e: return f'bad accessor: {e}'
	try:
		exec(f'{path} = ({expr})', ns)
		return None
	except Exception as e: return f'{type(e).__name__}: {e}'

class IPythonClient:
	'Default namespace source: the live IPython kernel (empty when not in IPython).'
	def ns(self): return ip.user_ns if (ip:= get_ipython()) else {}
	def hidden(self): return frozenset(getattr(ip, 'user_ns_hidden', ())) if (ip:= get_ipython()) else frozenset()
	def set_value(self, accessor, expr): return set_value(accessor, expr)

class NsClient:
	'A plain-dict namespace source for headless serve() and real (non-mock) tests.'
	def __init__(self, ns, hidden=frozenset()): self.ns_, self.hidden_ = ns, frozenset(hidden)
	def ns(self): return self.ns_
	def hidden(self): return self.hidden_
	def set_value(self, accessor, expr): return set_value(accessor, expr, ns=self.ns_)

class Bridge:
	'Frontend-agnostic access to a namespace via an injected client (defaults to the live IPython kernel).'
	def __init__(self, client=None): self.client = client or IPythonClient()
	def snapshot(self, name=None, typ=None): return snapshot(self.client.ns(), self.client.hidden(), name, typ)
	def view(self, profile='standard', sort='name', order=None):
		return profile_view(self.client.ns(), self.client.hidden(), profile, sort, order)
	def expand(self, accessor, offset=0): return expand(self.client.ns(), accessor, offset)
	def grid(self, accessor, roff=0, coff=0, rows=50, cols=50): return grid_page(self.client.ns(), accessor, roff, coff, rows, cols)
	def set_value(self, accessor, expr): return self.client.set_value(accessor, expr)

def on_change(cb):
	'Register cb() to fire after each cell execution; returns False outside IPython.'
	if not (ip:= get_ipython()): return False
	ip.events.register('post_run_cell', lambda res: cb()); return True
