"""The inspector that runs inside each kernel, as a JSON API.

leela talks to a kernel over two channels, deliberately split: execution goes down the
kernel's shell channel, and inspection comes over HTTP from *this* server, started inside
that same kernel. Shell messages queue behind a running cell, so a comm-based variable
tree would freeze during exactly the long cell you most want to watch; a background
thread does not.

Only the JSON surface leela consumes is here -- `/api/*` for the owner namespace and
`/agent/api/*` for the agent overlay. leela also served a full htmx inspector UI from
these same routes; leela renders its own frontends, so that half is gone.
"""

import os, sys, secrets, json, socket, subprocess, time, atexit
from dataclasses import asdict
from fastcore.all import run as srun, docstring
from fastcore.nbio import read_nb
from fasthtml.common import *
from fasthtml.jupyter import JupyUvi

from .. import leela_cfg
from .core import *
from .runtime import *
from .agent import *

# -- the registry: one JSON file per live inspector, so the IDE can find kernels by pid --
def reg_dir():
	'Directory holding one JSON file per live leela server (override with $LEELA_REG_DIR).'
	d = Path(os.environ.get('LEELA_REG_DIR', Path(leela_cfg/'reg')))
	d.mkdir(parents=True, exist_ok=True)
	return d

def _git_name(cwd=None):
	'Basename of the enclosing git repo, or None.'
	try: return Path(srun(f'git -C {str(cwd or Path.cwd())} rev-parse --show-toplevel')).name
	except: return None

def _pkg_name(ns):
	'Top-level package name inferred from a namespace\'s __package__/__name__, or None.'
	if not ns: return None
	for k in ('__package__','__name__'):
		if (v:= ns.get(k)) and v!='__main__': return str(v).split('.')[0]
	return None

def env_name(explicit=None, ns=None):
	'Env label: explicit > git repo name > package name > cwd basename.'
	return explicit or _git_name() or _pkg_name(ns) or Path.cwd().name

def free_port(start=8000, tries=50):
	'First bindable TCP port at/after start.'
	for p in range(start, start+tries):
		with socket.socket() as s:
			try: s.bind(('127.0.0.1', p)); return p
			except OSError: continue
	raise OSError(f'no free port in {start}..{start+tries}')

def _alive(pid):
	"Is a process with pid running and not a zombie? (os.kill(pid,0) also succeeds for a defunct process)."
	try: os.kill(pid, 0)
	except ProcessLookupError: return False
	except PermissionError: return True
	except Exception: return False
	try:
		st = subprocess.run(['ps','-o','state=','-p',str(pid)], capture_output=True, text=True, timeout=2).stdout.strip()
		if st[:1] == 'Z': return False   # zombie/defunct: reads as alive but is dead
	except Exception: pass
	return True

def register(name, port, base=None):
	"Write this server's registry entry and return it."
	bs = base or f'http://127.0.0.1:{port}'
	e = dict(name=name, port=port, pid=os.getpid(), cwd=str(Path.cwd()), base=bs, started=time.time())
	(reg_dir()/f'{port}.json').write_json(e)
	return e

def unregister(port):
	"Remove this server's registry entry."
	try: (reg_dir()/f'{port}.json').unlink()
	except FileNotFoundError: pass

def active():
	'Live registry entries, pruning any whose process has died.'
	out = []
	for f in sorted(reg_dir().glob('*.json')):
		try: e = f.read_json()
		except Exception: continue
		if _alive(e.get('pid', -1)): out.append(e)
		else:
			try: f.unlink()
			except Exception: pass
	return out

bridge = Bridge()

# A JSON-only app. leela served an htmx inspector UI from here as well; leela renders
# its own, polling /api/rows from the IDE process, so none of that markup is carried over --
# and with it go the static assets, the highlight.js headers and the /live websocket.
app, rt = fast_app(pico=False)

_profile, _sort = 'minimal', 'recent'
_ver, _fp, _seq = {}, {}, 0   # owner recency: name->version, name->value-fingerprint, monotonic counter
_aver, _afp = {}, {}          # agent-overlay recency (name->version, name->fingerprint; shares the _seq counter)
_server: JupyUvi|None = None
_port = _env = None

def _track(ns, ver, fp):
	"Bump a version for each name in `ns` whose value fingerprint changed; prune removed. Returns `ver` (name->version)."
	global _seq
	seen = set()
	for k, v in list(ns.items()):
		if k.startswith('__'): continue
		seen.add(k)
		try: f = (type(v).__name__, value_str(v), str(get_shape(v)))
		except Exception: f = ('?', '', '')
		if fp.get(k) != f: fp[k] = f; _seq += 1; ver[k] = _seq
	for k in [k for k in fp if k not in seen]: fp.pop(k, None); ver.pop(k, None)   # prune removed
	return ver

def _track_order(): return _track(bridge.client.ns(), _ver, _fp)                              # owner recency -> sort='recent'
def _agent_order(): return _track(_agent.layer, _aver, _afp) if _agent is not None else {}     # agent-overlay recency

_tok, _agent_mode = None, 'restricted'
_agent:AgentSession|None = None
def _tok_p(port): return reg_dir()/f'token-{port}'

def _owner_tok():
	"This server's owner token, minting it on first use (minting arms the owner-endpoint gate)."
	global _tok
	if _tok is None: _tok = secrets.token_urlsafe(16)
	return _tok

def _write_token(port):
	p = _tok_p(port)
	p.write_text(_owner_tok())
	p.chmod(0o600)
	atexit.register(lambda: p.unlink(missing_ok=True))
	return p

def _authed(req):
	'Owner-endpoint gate: open when no token is armed; else the X-Leela-Token header (or ?token=) must match.'
	if _tok is None: return True
	tok = req.headers.get('x-leela-token') or req.query_params.get('token')
	return tok == _tok

def agent_session() -> AgentSession:
	global _agent
	if _agent is None: _agent = AgentSession()
	return _agent

def agent_layer():
	"Names the connected agent has created/shadowed -> their values; inspect it live from your own kernel."
	return _agent.layer if _agent is not None else {}

# -- the owner namespace -------------------------------------------------------
def _vd(v): return asdict(v)

@rt('/api/rows')
def api_rows(profile:str=None, sort:str=None):
	'Grouped node tree for a profile + sort order (name|recent|type|size).'
	pf = profile if profile in PROFILES else _profile
	sr = sort if sort in SORTS else _sort
	groups = [{'label':lbl, 'nodes':[_vd(v) for v in vs]} for lbl,vs in bridge.view(pf, sr, _track_order())]
	return {'profile':pf, 'sort':sr, 'sorts':list(SORTS), 'profiles':list(PROFILES), 'groups':groups}

@rt('/api/expand')
def api_expand(accessor:str, offset:int=0):
	'One level of children at accessor as a JSON list of VarInfo dicts (trailing load-more sentinel carries more_offset).'
	return JSONResponse([_vd(v) for v in bridge.expand(tuple(json.loads(accessor)), offset)])

@rt('/api/grid')
def api_grid(accessor:str, roff:int=0, coff:int=0):
	'A grid page at accessor as JSON (headers/index/cells/nrows/ncols/…), or null if not gridable.'
	return JSONResponse(bridge.grid(tuple(json.loads(accessor)), roff, coff))

@rt('/api/envs')
def api_envs():
	"This server's env label + all live leela environments — the discovery feed for the frontend env picker."
	return {'env':_env, 'envs':active()}

@rt('/api/exec')
def api_exec(req, code:str, scope:str='global'):
	"Run code in the server's namespace; return {ok, result, stdout, error} as JSON (the terminal exec bar consumes this)."
	if not _authed(req): return JSONResponse({'error': 'owner token required'}, status_code=403)
	r = run(code, scope if scope in ('global','isolated') else 'global')
	return {'ok': r.ok, 'stdout': r.stdout, 'error': r.error,
	                     'result': _vd(r.result) if r.result is not None else None}

@rt('/api/promote')
def api_promote(req, accessor:str):
	"Adopt an agent-overlay top-level var into the owner namespace (owner-token gated); JSON {ok, error} — the TUI promote action consumes this."
	if not _authed(req): return JSONResponse({'ok': False, 'error': 'owner token required'}, status_code=403)
	a = tuple(json.loads(accessor))
	if len(a) != 1: return {'ok': False, 'error': 'can only promote a whole (top-level) variable'}
	err = _promote(a[0])
	return {'ok': err is None, 'error': err}

@rt('/api/sessions')
def api_sessions():
	"Saved session notebooks (current first) as JSON — the terminal sessions browser feed."
	cur = current_session()
	counts = dict(list_sessions())
	sess = [{'name': cur, 'count': counts.get(cur, 0), 'current': True}]
	sess += [{'name': s, 'count': n, 'current': False} for s, n in list_sessions() if s != cur]
	return {'current': cur, 'sessions': sess}

@rt('/api/session')
def api_session(name:str=''):
	"Code-cell sources for a saved session as JSON."
	return {'name': name, 'cells': read_session(name)}

@rt('/api/set')
def api_set(req, accessor:str, expr:str):
	"Assign `expr` (evaluated in the namespace) to the value at `accessor`; owner-token gated. JSON {ok, error} — the TUI inline editor consumes this."
	if not _authed(req): return JSONResponse({'ok': False, 'error': 'owner token required'}, status_code=403)
	err = bridge.set_value(tuple(json.loads(accessor)), expr)
	return {'ok': err is None, 'error': err}
@rt('/api/history')
def api_history(n:int=0):
	"The rolling exec-history notebook's code cells, newest last - what the IDE's exec box cycles through."
	return {'cells': history(n or None), 'path': str(hist_path()), 'logging': _log_on}

# -- the agent overlay ---------------------------------------------------------
AGENT_POLICY = f'''agent access: persistent session defined by {docstring(AgentSession)}. Use builtins, numpy and pandas where possible. import only once. dont run same code again. check globals. check if a module is avilable before using it.'''

def _agent_gate():
	"JSON 403 when the agent surface is disabled, else None."
	if _agent_mode == 'off': return JSONResponse({'error': 'agent access disabled on this server'}, status_code=403)
	return None

@rt('/agent/api/info')
def agent_info():
	"The agent-facing contract: env label, mode, policy text, transcript notebook path, and the names the agent has created so far."
	if (g := _agent_gate()) is not None: return g
	s = agent_session()
	return {'env': _env, 'mode': _agent_mode, 'policy': AGENT_POLICY,
	        'log': str(s.log_path) if s.log_path else None, 'agent_names': sorted(s.layer)}

@rt('/agent/api/rows')
def agent_rows(profile:str=None, sort:str=None):
	"Grouped node tree over the merged view (owner namespace + agent layer) in a sort order, same shape as /api/rows."
	if (g := _agent_gate()) is not None: return g
	s = agent_session()
	pf = profile if profile in PROFILES else 'standard'
	sr = sort if sort in SORTS else _sort
	groups = [{'label': lbl, 'nodes': [_vd(v) for v in vs]} for lbl, vs in s.view(pf, sr, _agent_order())]
	return {'profile': pf, 'sort': sr, 'sorts': list(SORTS), 'profiles': list(PROFILES), 'groups': groups, 'agent_names': sorted(s.layer)}

@rt('/agent/api/expand')
def agent_expand(accessor:str, offset:int=0):
	"One level of children at accessor in the merged view, as JSON VarInfo dicts."
	return _agent_gate() or JSONResponse([_vd(v) for v in agent_session().expand(tuple(json.loads(accessor)), offset)])

@rt('/agent/api/grid')
def agent_grid(accessor:str, roff:int=0, coff:int=0):
	"A grid page at accessor in the merged view, or null if not gridable."
	return _agent_gate() or JSONResponse(agent_session().grid(tuple(json.loads(accessor)), roff, coff))

@rt('/agent/api/transcript')
def agent_transcript_json():
	"The connected agent's transcript notebook as JSON {log, cells:[{cell_type, source}]} — the TUI transcript view consumes this."
	if (g := _agent_gate()) is not None: return g
	s = _agent
	if s is None or not s.log_path or not Path(s.log_path).exists(): return {'log': None, 'cells': []}
	cells = read_nb(str(s.log_path))['cells']
	return {'log': str(s.log_path), 'cells': [{'cell_type': c['cell_type'], 'source': c['source']} for c in cells]}

@rt('/agent/api/exec')
def agent_exec(code:str, scope:str='overlay'):
	"Run agent code under the restriction list; scope='overlay' persists the agent's names, 'isolated' discards writes ('readonly' servers force it)."
	g = _agent_gate()
	if g is not None: return g
	scope = 'isolated' if (_agent_mode == 'readonly' or scope == 'isolated') else 'overlay'
	r = agent_session().run(code, scope)
	return {'ok': r.ok, 'stdout': r.stdout, 'error': r.error, 'scope': scope,
	                     'result': _vd(r.result) if r.result is not None else None}

def _promote(name):
	"Copy the agent overlay's top-level var `name` into the owner namespace (a live reference handoff); error text or None."
	s = _agent
	if s is None or name not in s.layer: return f'no agent variable {name!r}'
	bridge.client.ns()[name] = s.layer[name]
	return None

# -- starting it ---------------------------------------------------------------
def _ag(o='restricted'): return o if o in ('restricted', 'readonly', 'off') else 'restricted'

def _start(port=8000, profile='minimal', name=None, agent='restricted', token=True, ns=None, base=None):
	global _server, _port, _env, _profile, _agent_mode
	_profile, _env, _agent_mode = profile, env_name(name,ns), _ag(agent)
	if _server is None:
		_port = free_port(port)
		if token: _write_token(_port)
		_server = JupyUvi(app, port=_port, daemon=True)
		if base: base = f'{base}:{_port}'
		register(_env, _port, base)
		atexit.register(unregister, _port)
		return True
	return False

def serve_in_kernel(port=8000, name=None, profile='minimal', agent='restricted', token=True):
	'''Start the inspector *inside* a live IPython kernel and return the port it bound.

	This is what leela bootstraps every notebook kernel with, so the panel shows that
	kernel's own namespace. It runs on a background thread, which is the point: shell
	messages queue behind a running cell, so a comm-based tree would freeze during a
	long cell, while this one keeps answering.
	agent: restricted|readonly|off. token=True gates /api/exec, /api/set and /api/promote.'''
	_start(port, profile, name, agent, token)
	return _port

def serve(port=8000, ns=None, name=None, profile='minimal', agent='restricted', token=True):
	'''Start the inspector in a background thread for a plain process; returns its base URL.

	ns defaults to the caller's globals. This is what `leela.devserver` runs an app under,
	so the app's module namespace shows up in the variable panel as just another env.'''
	global bridge
	ns = ns or sys._getframe(1).f_globals
	bridge = Bridge(NsClient(ns))
	_start(port, profile, name, agent, token, ns, 'http://127.0.0.1')
	return _server, f'http://127.0.0.1:{_port}'
