import hashlib, os, re, shutil, subprocess, sys
from time import monotonic
from fastcore.basics import AttrDict, first
from fastcore.xdg import xdg_data_home
from fastcore.xtras import Path, atomic_save
from ..nb import check
from ... import errstr
from .learn import PKG, _NAME

__all__ = ['NO_UV', 'TOO_LONG', 'tool_names', 'tool_key', 'tool_dir', 'tool_python', 'tool_kernel', 'tool_indexed', 'tool_stale', 'tool_of', 'kernel_reqs', 'install_cmds', 'make_tool_env', 'upgrade_tool_env',
           'index_env', 'tool_job', 'env_state', 'env_job', 'active_job', 'start_tool_job', 'LIBRARY_TOTAL', 'library_check']

NO_UV = 'Leela needs uv to install packages for a lesson.'
TOO_LONG = 'The install took too long. Try again.'
BUSY = 'Another install of these packages is still running. Try again later.'
NO_PY = 'The install did not make a Python for the lesson. Try again.'
LIBRARY_TOTAL = 20.   # seconds for one library check; each test keeps abhyasa's `runner.per_test`
_KEY, _WHEEL = re.compile(r'[0-9a-f]{16}'), re.compile(r'no (usable |matching )?wheels?', re.I)

def tool_names(names) -> list[str]:
    "The sorted, unique requirement strings in `names`. `ValueError` for no names, more than 5, or one that does not match `PKG`."
    if not isinstance(names, (list, tuple)): raise ValueError('package: give a list of package names')
    if not names: raise ValueError('package: give at least one name')
    if len(names) > 5: raise ValueError('package: give at most 5 names')
    if bad := [n for n in names if not (isinstance(n, str) and PKG.fullmatch(n))]: raise ValueError(f'package: {bad[0]!r} is not a package name')
    return sorted(set(names))

def tool_key(names, py=sys.version_info) -> str:
    "The first 16 hex characters of the SHA-256 of the Python `major.minor` and the sorted `names`."
    return hashlib.sha256((f'{py[0]}.{py[1]}\n' + '\n'.join(tool_names(names))).encode()).hexdigest()[:16]

def tool_dir(key):
    "The folder of the tool environment `key`. `ValueError` for a key that `tool_key` cannot make."
    if not (isinstance(key, str) and _KEY.fullmatch(key)): raise ValueError('key: give the 16 character key of a tool environment')
    return xdg_data_home()/'leela'/'tools'/key

def _python(d): return d/'.venv'/'bin'/'python'

def tool_python(key):
    "The Python of the tool environment `key` when it has a `ready` file and an executable Python; else None."
    try: d = tool_dir(key)
    except ValueError: return None
    p = _python(d)
    return p if (d/'ready').is_file() and p.is_file() and os.access(p, os.X_OK) else None

def tool_kernel(key):
    "The Python of the tool environment `key` when it is ready and holds the kernel packages, so a notebook kernel can start from it; else None."
    return p if (p := tool_python(key)) and (tool_dir(key)/'kernel').is_file() else None

def tool_indexed(key):
    "True when kosha last indexed the packages of the tool environment `key` without an error."
    try: return (tool_dir(key)/'indexed').is_file()
    except ValueError: return False

def _index(key):
    "Index the tool environment `key` through `index_env`; the error text, or '' after a full index."
    (d := tool_dir(key)/'indexed').unlink(missing_ok=True)
    try: index_env(key)
    except Exception as e: return errstr(e)
    d.touch()
    return ''

def tool_stale(key):
    "True when the tool environment `key` holds an ipykernel whose shell can stop answering (kunda's `ipykernel_notice`)."
    from kunda.support import ipykernel_notice
    return bool((p := tool_python(key)) and ipykernel_notice(p))

def tool_of(python):
    "The key of the tool environment whose Python is `python`, or None."
    d = Path(python).parent.parent.parent
    return d.name if d.parent == xdg_data_home()/'leela'/'tools' and tool_python(d.name) else None

def kernel_reqs() -> list[str]:
    "The kernel packages a lesson kernel starts from: ipykernel at kunda's floor, and ipymini at the version Leela runs."
    from kunda.support import kernel_requirements
    return kernel_requirements(('ipykernel', 'ipymini'))

def install_cmds(names, d, uv:str, py=sys.version_info) -> list[list[str]]:
    "The `uv venv` and `uv pip install` argv lists that make the environment for `names` and `kernel_reqs` in `d`, wheels only."
    return [[uv, 'venv', str(d/'.venv'), '--python', f'{py[0]}.{py[1]}'],
            [uv, 'pip', 'install', '--python', str(_python(d)), '--only-binary', ':all:', *tool_names(names), *kernel_reqs()]]

def _uv_error(names, r):
    err = r.stderr or ''
    if _WHEEL.search(err):
        base = [_NAME.match(n)[0] for n in names]
        name = first(n for n in base if n.lower() in err.lower()) or ', '.join(base)
        return f'{name} has no wheel for this computer, so Leela cannot install it.'
    return first(l.strip() for l in reversed(err.splitlines()) if l.strip()) or f'uv exited {r.returncode}.'

def make_tool_env(names, run=subprocess.run, uv=None,
                  budget=600):  # seconds for both commands together
    "Make the tool environment for `names` once, then index it: `AttrDict(key, ok, python, error)`, plus `index_error` when the index fails. `ready` is written before the index, so a lesson runs while it builds; a failed index runs again on the next call, and a call while another builds it does not wait. A ready environment with no `kernel` file gets only the install."
    from ...workspace import _session_lock
    names = tool_names(names)
    key = tool_key(names)
    d = tool_dir(key)
    def res(ok, error='', index_error=''):
        p = tool_python(key)
        return AttrDict(key=key, ok=ok, python=str(p) if p else None, error=error, **({'index_error': index_error} if index_error else {}))
    if tool_kernel(key) and tool_indexed(key) and not tool_stale(key): return res(True)
    with _session_lock(d, timeout=0 if tool_kernel(key) else budget) as held:
        if not held: return res(True) if tool_kernel(key) else res(False, BUSY)
        if tool_kernel(key) and not tool_stale(key): return res(True, index_error='' if tool_indexed(key) else _index(key))
        if not (uv := uv or shutil.which('uv')): return res(False, NO_UV)
        cmds = install_cmds(names, d, uv)
        if tool_python(key): cmds = cmds[1:]
        else:
            shutil.rmtree(d, ignore_errors=True)
            d.mkdir(parents=True)
        end = monotonic() + budget
        for cmd in cmds:
            if (left := end - monotonic()) <= 0: return res(False, TOO_LONG)
            try: r = run(cmd, capture_output=True, text=True, timeout=left, stdin=subprocess.DEVNULL)
            except subprocess.TimeoutExpired: return res(False, TOO_LONG)
            except OSError as e: return res(False, errstr(e))
            if r.returncode: return res(False, _uv_error(names, r))
        p = _python(d)
        if not (p.is_file() and os.access(p, os.X_OK)): return res(False, NO_PY)
        with atomic_save(d/'kernel', mode='w') as f: f.write('\n'.join(kernel_reqs()) + '\n')
        with atomic_save(d/'ready', mode='w') as f: f.write('\n'.join(names) + '\n')
        return res(True, index_error=_index(key))

def upgrade_tool_env(key):
    "Install the kernel packages again into the stale tool environment `key`, through `make_tool_env`."
    try: names = (tool_dir(key)/'ready').read_text().split()
    except (OSError, ValueError): return AttrDict(key=key, ok=False, python=None, error='The tool environment is not ready.')
    return make_tool_env(names)

def library_check(spec, source, key:str) -> dict:
    "The `run_isolated` report for `source` against `spec`'s tests, closed, in the Python of the tool environment `key`. `ValueError` when it is not ready."
    from ..nb.exercise import _as_checked
    if not (python := tool_python(key)): raise ValueError('The tool environment is not ready.')
    tests = [t if isinstance(t, str) else dict(test=t['test'], say=t['say'], hidden=not t['shown']) for t in spec['tests']]
    return _as_checked(check.run_isolated('assert', spec['fname'], source, tests, total=LIBRARY_TOTAL, sandbox=True, python=str(python), unix=True))

def index_env(key):
    "Index the packages of the tool environment `key` in kosha, so `/learn/lookup?tool=` finds them."
    from kosha import Kosha
    Kosha(dir=tool_dir(key)).sync(repo=False, graph=False, pyproject=False, verbose=False, in_parallel=False)

def tool_job(job, report):
    "The `tool_env` job: `make_tool_env`, which installs and indexes. `JobError` for a failed install; an index failure is `index_error` in the result."
    from ..vault.jobs import JobError
    names = job.params['names']
    report(current='installing and indexing ' + ' '.join(names), progress=0.1)
    r = make_tool_env(names)
    if not r.ok: raise JobError(r.error)
    return dict(r)

def env_state(jobs, key) -> str:
    "`ready`, `indexing` while a job builds the code index of a ready environment, `unindexed`, `installing`, or `missing`."
    busy = jobs is not None and active_job(jobs, key)
    if tool_kernel(key): return 'ready' if tool_indexed(key) else 'indexing' if busy else 'unindexed'
    return 'installing' if busy else 'missing'

def env_job(jobs, key):
    "The newest `tool_env` job for `key`, or None."
    return None if jobs is None else first(j for j in jobs.all(limit=100, kind='tool_env') if j.target == key)

def active_job(jobs, key):
    "The queued or running `tool_env` job for `key` whose process is alive, or None."
    return first(j for j in jobs.all(limit=100, kind='tool_env') if j.active and j.target == key and jobs.alive(j))

def start_tool_job(jobs, names):
    "The `tool_env` job that makes the environment for `names`: the active one for its key, else a new one."
    names = tool_names(names)
    return active_job(jobs, key := tool_key(names)) or jobs.start('tool_env', key, names=names)


def learn_settings(ws):
    from ..settings.settings import Settings
    return dict(Settings(ws.project_root).effective().get('learn', {}))


def learn_store(ws, vault=None, write=False):
    from abhyasa.learner import Learning
    ref = ws.vaults.get(vault)
    if ref is None: raise KeyError('Learning vault is not attached.')
    if write and not ref.agent_writable: raise PermissionError('Learning vault is read-only for the agent.')
    memory = ws.vaults.memory(ref.name)
    return ref.name, Learning(memory._store('learning'))


def learn_guard(ai, text, spec=None):
    from abhyasa.models import guard
    return guard(text, spec or ai.spec_or_none('plan'), ai.ws.vault_pii)


def learn_ask(ai):
    def prepare(prompt, sp, backend):
        return learn_guard(ai, prompt, backend.spec), learn_guard(ai, sp, backend.spec)
    def ask(prompt, sp=''):
        return ai.oneshot(prompt, sp, 'plan', 2048, prepare=prepare, wait=True, strict=True)
    return ask


def register_learn_jobs(ws):
    from abhyasa import agent_tools as engine
    import inspect
    captures = ws.__dict__.setdefault('_learn_jobs', {})
    def run(job, report):
        if job.id not in captures: raise RuntimeError('The originating learning session is no longer available. Start a new walk.')
        ai, lr = captures[job.id]
        try:
            kw = dict(stopping=lambda: ws.jobs.stopping(job.id), progress=lambda stage, frac: report(progress=frac, current=stage))
            params = inspect.signature(engine.create_walk).parameters
            if 'settings' in params: kw['settings'] = job.params['settings']
            if 'guard' in params: kw['guard'] = lambda text: learn_guard(ai, text)
            r = engine.create_walk(lr, learn_ask(ai), job.target, **kw)
            r.update(operation_id=job.id, vault=job.params['vault'])
            if r['status'] == 'ok': r['data']['tab'] = dict(kind='learn_walk', vault=r['vault'], walk=r['walk'])
            if r['status'] == 'stopped': r['cancelled'] = True
            return r
        finally: captures.pop(job.id, None)
    ws.jobs.register('learn_walk', run)


def start_learn_job(ai, goal):
    from abhyasa.agent_tools import result
    ws = ai.ws
    vault, lr = learn_store(ws, write=True)
    settings = learn_settings(ws)
    with ws.jobs._lock:
        for job in ws.jobs.all(kind='learn_walk'):
            if job.active and job.target == goal and job.params.get('vault') == vault and job.params.get('thread') == ai.session_id:
                return result('ok', operation_id=job.id, vault=vault, data=dict(job=job.id))
        job = ws.jobs.new('learn_walk', goal, vault=vault, thread=ai.session_id, settings=settings, _cancel=True)
        ws._learn_jobs[job.id] = (ai, lr)
        try: ws.jobs.launch(job.id)
        except Exception:
            ws._learn_jobs.pop(job.id, None)
            raise
    return result('ok', operation_id=job.id, vault=vault, data=dict(job=job.id))


def learn_tools(ai):
    import inspect
    from abhyasa import agent_tools as engine
    from ...agent.tools import small_tool
    from shalya.core import writes
    def wrap(name, args):
        def call(**kwargs):
            if not ai.learn_mode:
                return engine.failed('mode_off', 'Turn Learn mode on before using learning tools.', extra=('mode_off',))
            try:
                if name == 'create_walk': return start_learn_job(ai, **kwargs)
                vault, lr = learn_store(ai.ws, write=name != engine.walk_state.__name__)
                fn = getattr(engine, name)
                params = inspect.signature(fn).parameters
                if 'ask' in params: kwargs['ask'] = learn_ask(ai)
                if 'settings' in params: kwargs['settings'] = learn_settings(ai.ws)
                r = fn(lr, **kwargs)
                r['vault'] = vault
                return r
            except PermissionError as e: return engine.failed('read_only', str(e))
            except KeyError as e: return engine.failed('not_found', str(e))
        call.__name__ = name
        call.__doc__ = getattr(engine, name).__doc__ or ''
        call.__annotations__ = {k: {'str': str, 'int': int}[v.split(':', 1)[0]] for k, v in args.items()}
        call.__signature__ = inspect.Signature([inspect.Parameter(k, inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=call.__annotations__[k]) for k in args])
        call.__doc__ += '\n\n' + '\n'.join(f'{k}: {v}' for k, v in args.items())
        if name != engine.walk_state.__name__: writes(call)
        return small_tool(call)
    return [wrap(name, args) for name, args in engine.TOOLS]
