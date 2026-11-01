import hashlib, os, re, shutil, subprocess, sys
from time import monotonic
from fastcore.basics import AttrDict, first
from fastcore.xdg import xdg_data_home
from fastcore.xtras import atomic_save
from ..nb import check
from ... import errstr
from .learn import PKG, _NAME

__all__ = ['NO_UV', 'TOO_LONG', 'tool_names', 'tool_key', 'tool_dir', 'tool_python', 'tool_kernel', 'tool_indexed', 'kernel_reqs', 'install_cmds', 'make_tool_env',
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

def kernel_reqs() -> list[str]:
    "The kernel packages a lesson kernel starts from, ipykernel and ipymini, at the versions Leela runs."
    from kunda.support import as_installed
    return as_installed(('ipykernel', 'ipymini'))

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
    if tool_kernel(key) and tool_indexed(key): return res(True)
    with _session_lock(d, timeout=0 if tool_kernel(key) else budget) as held:
        if not held: return res(True) if tool_kernel(key) else res(False, BUSY)
        if tool_kernel(key): return res(True, index_error='' if tool_indexed(key) else _index(key))
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
