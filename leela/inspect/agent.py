"""Restricted execution for AI agents over the owner's live namespace.

An overlay layer -- agents read everything, create their own names, and can never
rebind or delete the owner's -- plus an AST restriction list checked before every cell."""


__all__ = ['RuleBlock', 'load_inspectors', 'run_inspectors', 'policy_inspectors', 'run_coro', 'run_py', 'AgentSession',
           'agent_tools', 'conversation_logger']

import ast, os, runpy, inspect, datetime, asyncio
from fastcore.all import Path, filter_keys, filter_dict, not_, in_
from IPython.utils.capture import capture_output
from .runtime import *
from .. import leela_cfg
from .core import *

class RuleBlock(Exception):
	'Raised by an inspector to deliberately block a cell; any other inspector exception is a bug, and fails open'

def load_inspectors(path=None):
	'Inspector functions from `path`, $LEELA_INSPECTORS, or ~/.config/leela/inspectors.py; the file may define `inspect(tree[, code])` and/or a list `inspectors` (clikernel\'s file contract).'
	p = path or os.environ.get('LEELA_INSPECTORS') or leela_cfg/'inspectors.py'
	if not (p := Path(p).expanduser()).exists(): return []
	ns = runpy.run_path(str(p))
	ins = list(ns.get('inspectors', []))
	if callable(ns.get('inspect')): ins.append(ns['inspect'])
	return ins

def _call_inspector(f, tree, code):
	'1-arg inspectors get the transformed AST; 2-arg ones also get the raw cell source.'
	return f(tree, code) if len(inspect.signature(f).parameters) > 1 else f(tree)

def run_inspectors(inspectors, code):
	'''Concatenated notes from every inspector for `code` (\'\' for unparseable code — execution reports the syntax error)
	 RuleBlock propagates, any other inspector exception fails open with a warning note.'''
	try: tree = ast.parse(code)
	except SyntaxError: return ''
	notes = []
	for f in inspectors:
		try: n = _call_inspector(f, tree, code)
		except RuleBlock: raise
		except Exception as e: n = f'[inspector {getattr(f, "__name__", "?")} crashed, check skipped: {type(e).__name__}: {e}]\n'
		if n: notes.append(n)
	return ''.join(notes)

_MUTATORS = frozenset('append extend insert remove pop clear update add discard popitem setdefault sort reverse'.split())
_BLOCKED_CALLS = frozenset('exec eval setattr delattr globals vars breakpoint'.split())
_DESTRUCTIVE = {('os','remove'),('os','unlink'),('os','rmdir'),('os','removedirs'),('os','rename'),
                ('os','replace'),('os','system'),('os','popen'),('shutil','rmtree'),('shutil','move')}
_DESTRUCTIVE_ATTRS = frozenset(('rmtree','unlink','rmdir'))

def _root(node):
	"Base Name id of a dotted/indexed/called chain (x.a[0].b() -> 'x'), or None."
	while isinstance(node, (ast.Attribute, ast.Subscript, ast.Call)):
		node = node.func if isinstance(node, ast.Call) else node.value
	return node.id if isinstance(node, ast.Name) else None

def _block(msg): raise RuleBlock(msg)

def _check_del(node, owner):
	"Refuse `del` of an owner name."
	for t in node.targets:
		r = t.id if isinstance(t, ast.Name) else _root(t)
		if r in owner: _block(f"cannot delete owner variable '{r}'; you may only delete names you created")

def _check_assign(node, owner):
	"Refuse in-place rebind (attr/item target) or augmented-assign of an owner object."
	tgts = node.targets if isinstance(node, ast.Assign) else [node.target]
	fn = lambda r: _block(f"cannot modify owner variable '{r}' in place; bind your result to a new name instead")
	[fn(r) for t in tgts for u in ast.walk(t) if isinstance(u, (ast.Attribute, ast.Subscript)) and (r:=_root(u)) in owner]
	if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and node.target.id in owner:
		_block(f''''{node.target.id} += ...' may mutate the owner's object in place; use a new name,
		 e.g. {node.target.id}2 = {node.target.id} + ...''')

def _check_call(node, owner):
	"Refuse escapes (exec/eval/os.system/...) and owner-mutating method calls."
	f = node.func
	if isinstance(f, ast.Name) and f.id in _BLOCKED_CALLS: _block(f"call to '{f.id}' is not allowed in the agent session")
	if not isinstance(f, ast.Attribute): return
	r = _root(f.value)
	if r == 'subprocess' or (isinstance(f.value, ast.Name) and (f.value.id, f.attr) in _DESTRUCTIVE):
		_block(f"'{r}.{f.attr}' is a shell/filesystem escape and is not allowed in the agent session; use your own shell tool")
	if f.attr in _DESTRUCTIVE_ATTRS:
		_block(f"'.{f.attr}()' deletes resources and is not allowed in the agent session")
	if f.attr in _MUTATORS and r in owner:
		_block(f"'.{f.attr}()' would mutate owner variable '{r}'; copy it to a new name first")
	if r in owner and any(k.arg == 'inplace' and getattr(k.value, 'value', None) is True for k in node.keywords):
		_block(f"inplace=True would mutate owner variable '{r}'; drop inplace and bind the result to a new name")

_CHECKS = {ast.Delete: _check_del, ast.Assign: _check_assign, ast.AugAssign: _check_assign,
           ast.AnnAssign: _check_assign, ast.Call: _check_call}

def policy_inspectors(owner_names):
	"The default restriction list, closed over `owner_names` (a callable giving the currently protected names): agents may read owner variables and create their own; deleting, rebinding in place, or mutating owner state — and destructive file/shell escapes — are blocked."
	def guard(tree, code):
		owner = owner_names()
		for node in ast.walk(tree):
			chk = _CHECKS.get(type(node))
			if chk: chk(node, owner)
			elif isinstance(node, ast.Attribute) and node.attr in ('__dict__', '__globals__') and _root(node) in owner:
				_block(f"direct '{node.attr}' access on owner objects is not allowed")
		return None
	return [guard]

import io
from contextlib import redirect_stdout
from safepyrun import RunPython

def run_coro(coro):
	"Run an awaitable to completion from sync code, even inside a running event loop."
	try: asyncio.get_running_loop()
	except RuntimeError: return asyncio.run(coro)
	from concurrent.futures import ThreadPoolExecutor
	with ThreadPoolExecutor(1) as ex: return ex.submit(asyncio.run, coro).result()

def run_py(code, ban_defs=False, g=None):
	"Run `code` in a safepyrun allowlist sandbox; return captured stdout (+ repr of any result), or an error string."
	r = RunPython(g=g, ban_defs=ban_defs)
	buf = io.StringIO()
	try:
		with redirect_stdout(buf): res = run_coro(r(code))
		out = buf.getvalue()
		if res is not None: out = (out + '\n' if out else '') + repr(res)
		return out or '(ok)'
	except Exception as e: return f"{type(e).__name__}: {e}"

class AgentSession:
	'''Sandboxed Python session over a shared owner namespace. You can read and access any owner variable freely; your writes land in your own layer and never touch the owner. Mutating or deleting owner variables is blocked. copy to a new name first (e.g. `df2 = df.copy()`, `lst2 = lst[:]`). Check available variables before writing code.'''
	def __init__(self,
		owner=None,   # callable -> namespace dict to protect (default: leela's inspected namespace)
		rules=None,   # extra inspectors appended to the default policy (default: load_inspectors())
		log=True):    # transcript notebook: True -> leela_sessions/agent_<stamp>.ipynb, a path -> that file, False -> off
		self.owner = owner if owner is not None else IPythonClient().ns
		self.layer, self.ns = {}, {}
		self.inspectors = policy_inspectors(self.owner_names) + (load_inspectors() if rules is None else list(rules))
		stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
		self.log_path = None if not log else (SESSION_DIR/f'agent_{stamp}.ipynb' if log is True else Path(log))

	def owner_names(self):
		'Currently protected names: everything in the owner namespace the agent hasn\'t shadowed.'
		return {k for k in self.owner() if k not in self.layer}

	def _sync_in(self):
		o = self.owner()
		for k in [k for k in self.ns if k not in o and k not in self.layer and k != '__builtins__']: del self.ns[k]
		self.ns.update({k: o[k] for k in self.owner_names()})
		return self.ns

	def _sync_out(self):
		o = self.owner()
		for k, v in self.ns.items():
			if k != '__builtins__' and o.get(k) is not v: self.layer[k] = v
		for k in [k for k in self.layer if k not in self.ns]: del self.layer[k]

	def view_ns(self):
		'Merged read view (owner + agent layer) for snapshots/expands/grids.'
		return filter_keys(self._sync_in(),not_(in_('__builtins__')))

	def _log(self, code, note=''):
		'Transcribe an attempted cell into the agent notebook, outcome first (`# blocked:` / `# error:` / `# scope: isolated`).'
		if self.log_path: log_run((f'# {note}\n' if note else '') + code, path=self.log_path)

	def log_md(self, text):
		'Append `text` as a markdown cell to the agent notebook -- conversation context between the code cells (no-op when logging is off).'
		if self.log_path: log_run(text, path=self.log_path, cell_type='markdown')

	def run(self, code, scope='overlay'):
		'''Run agent code under the restriction list. scope='overlay' execs in the overlay and persists new names in the agent layer;
		 'isolated' runs in a safepyrun sandbox (owner state seeded read-only, all writes discarded).
		 The owner namespace is never written either way; every attempt lands in the transcript notebook.'''
		try: note = run_inspectors(self.inspectors, code)
		except RuleBlock as e:
			self._log(code, f'blocked: {e}')
			return ExecResult(ok=False, error=f'blocked: {e}')
		if scope == 'isolated': return self._run_isolated(code, note)
		run_ns = self._sync_in()
		cap = err = val = None
		try:
			with capture_output() as cap: val = exec_capture(code, run_ns)
		except Exception as e: err = f'{type(e).__name__}: {e}'
		self._sync_out()
		self._log(code, f'error: {err}' if err else '')
		out = note + (cap.stdout if cap is not None else '')
		if err: return ExecResult(ok=False, stdout=out, error=err)
		return ExecResult(ok=True, result=None if val is None else flat_result(val), stdout=out)

	def _run_isolated(self, code, note=''):
		'Run `code` in a safepyrun sandbox: the merged read view is seeded (throwaway copy), writes are discarded, and non-allowlisted escapes are refused.'
		self._log(code, 'scope: isolated')
		buf = io.StringIO()
		try:
			with redirect_stdout(buf): val = run_coro(RunPython(g=self.view_ns())(code))
		except Exception as e: return ExecResult(ok=False,stdout=note+buf.getvalue(),error=f'{type(e).__name__}: {e}')
		return ExecResult(ok=True, stdout=note + buf.getvalue(), result=None if val is None else flat_result(val))

	def snapshot(self, name=None, typ=None): return snapshot(self.view_ns(), frozenset(), name, typ)
	def view(self, profile='standard', sort='name', order=None): return profile_view(self.view_ns(), frozenset(), profile, sort, order)
	def expand(self, accessor, offset=0): return expand(self.view_ns(), accessor, offset)
	def grid(self,accessor,roff=0,coff=0,rows=50,cols=50): return grid_page(self.view_ns(),accessor,roff,coff,rows,cols)

def agent_tools(session):
	'''Tools for a tool-calling agent over an AgentSession. `list_vars` shows what is available; call it first. `run_python` executes code in the session.'''
	def list_vars() -> str:
		'List the variables visible in the session: name, type, and a short value.'
		rows = [f'{v.name}: {v.type} = {v.value}' for _, vs in session.view('minimal') for v in vs]
		return '\n'.join(rows) or '(empty session)'
	def run_python(code: str) -> str:
		'''Run Python in the shared session. Read any variable freely; bind results to NEW names to keep them across
		calls. Mutating or deleting the owner's variables is refused - rebind to a new name instead
		(e.g. df2 = df.drop(...)).'''
		if (r:=session.run(code)).error: return r.error
		out = r.stdout or ''
		if r.result is not None: out += ('\n' if out else '') + r.result.value
		return out or '(ok)'
	return [list_vars, run_python]

def conversation_logger(session, order=5):
	'Rishi ChatCallback that logs each turn (user prompt + assistant reply) as markdown cells into the session transcript, interleaved with run_python code cells.'
	try: from rishi.core import ChatCallback, resp_text, normalize_message
	except: raise Exception('Conversation logger is a Rishi callback. `uv add rishi`')
	class ConversationLogger(ChatCallback):
		def before_send(self):
			m = self.chat.turn_msg
			if m is not None and (t := resp_text(normalize_message(m)).strip()): session.log_md('**user**\n\n' + t)
		def after_response(self):
			if (t := resp_text(self.chat.turn_res).strip()): session.log_md('**assistant**\n\n' + t)
	cb = ConversationLogger(); cb.order = order
	return cb
