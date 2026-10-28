import hashlib, os, re, shutil, subprocess, sys
from time import monotonic
from fastcore.basics import AttrDict, first
from fastcore.xdg import xdg_data_home
from fastcore.xtras import atomic_save
from ... import errstr
from .learn import PKG, _NAME

__all__ = ['NO_UV', 'TOO_LONG', 'tool_names', 'tool_key', 'tool_dir', 'tool_python', 'install_cmds', 'make_tool_env', 'index_env', 'tool_job', 'active_job']

NO_UV = 'Leela needs uv to install packages for a lesson.'
TOO_LONG = 'The install took too long. Try again.'
BUSY = 'Another install of these packages is still running. Try again later.'
NO_PY = 'The install did not make a Python for the lesson. Try again.'
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

def install_cmds(names, d, uv:str, py=sys.version_info) -> list[list[str]]:
    "The `uv venv` and `uv pip install` argv lists that make the environment for `names` in `d`, wheels only."
    return [[uv, 'venv', str(d/'.venv'), '--python', f'{py[0]}.{py[1]}'],
            [uv, 'pip', 'install', '--python', str(_python(d)), '--only-binary', ':all:', *tool_names(names)]]

def _uv_error(names, r):
    err = r.stderr or ''
    if _WHEEL.search(err):
        base = [_NAME.match(n)[0] for n in names]
        name = first(n for n in base if n.lower() in err.lower()) or ', '.join(base)
        return f'{name} has no wheel for this computer, so Leela cannot install it.'
    return first(l.strip() for l in reversed(err.splitlines()) if l.strip()) or f'uv exited {r.returncode}.'

def make_tool_env(names, run=subprocess.run, uv=None,
                  budget=600):  # seconds for both commands together
    "Make the tool environment for `names` once: `AttrDict(key, ok, python, error)`. `ready` is written only after both commands succeed and the Python exists."
    from ...workspace import _session_lock
    names = tool_names(names)
    key = tool_key(names)
    d = tool_dir(key)
    def res(ok, error=''): p = tool_python(key); return AttrDict(key=key, ok=ok, python=str(p) if p else None, error=error)
    if tool_python(key): return res(True)
    if not (uv := uv or shutil.which('uv')): return res(False, NO_UV)
    with _session_lock(d, timeout=budget) as held:
        if not held: return res(False, BUSY)
        if tool_python(key): return res(True)
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
        end = monotonic() + budget
        for cmd in install_cmds(names, d, uv):
            if (left := end - monotonic()) <= 0: return res(False, TOO_LONG)
            try: r = run(cmd, capture_output=True, text=True, timeout=left, stdin=subprocess.DEVNULL)
            except subprocess.TimeoutExpired: return res(False, TOO_LONG)
            except OSError as e: return res(False, errstr(e))
            if r.returncode: return res(False, _uv_error(names, r))
        p = _python(d)
        if not (p.is_file() and os.access(p, os.X_OK)): return res(False, NO_PY)
        with atomic_save(d/'ready', mode='w') as f: f.write('\n'.join(names) + '\n')
        return res(True)

def index_env(key):
    "Index the packages of the tool environment `key` in kosha, so `/learn/lookup?tool=` finds them."
    from kosha import Kosha
    Kosha(dir=tool_dir(key)).sync(repo=False, graph=False, pyproject=False, verbose=False, in_parallel=False)

def tool_job(job, report):
    "The `tool_env` job: make the environment, then index it. `JobError` for a failed install; an index failure is `index_error` in the result."
    from ..vault.jobs import JobError
    names = job.params['names']
    report(current='installing ' + ' '.join(names), progress=0.1)
    r = make_tool_env(names)
    if not r.ok: raise JobError(r.error)
    report(current='indexing the packages', progress=0.8)
    try: index_env(r.key)
    except Exception as e: r.index_error = errstr(e)
    return dict(r)

def active_job(jobs, key):
    "The queued or running `tool_env` job for `key` whose process is alive, or None."
    return first(j for j in jobs.all(limit=100, kind='tool_env') if j.active and j.target == key and jobs.alive(j))
