"Probe and install kernel support into a project's Python environment."

from __future__ import annotations

import os, shutil, subprocess, sys, threading, time
from pathlib import Path

__all__ = ['clean_env', 'strip_bundle', 'BUNDLE_ONLY', 'work_dir', 'support_paths', 'kernel_support', 'install_kernel_support', 'LEELA_PY',
           'INSPECTOR', 'INSPECTOR_TTL', 'KERNEL_PACKAGES', 'as_installed', 'installable', 'inspector_support',
           'install_inspector_support']

#: Leela's own minor version. A kernel may borrow Leela's `sys.path` only when it matches.
LEELA_PY = tuple(sys.version_info[:2])

#: What a kernel that cannot borrow Leela's own copy has to have of its own. `dhrishti` and not
#: its imports: numpy and pandas are the two that are noticed missing, but IPython comes with it
#: and the bundle's is bytecode for another version. Unpinned, because the versions are the
#: project's choice. Pinned by `tests/test_runtime.py`.
INSPECTOR = ('dhrishti',)

#: Seconds an inspector answer is reused for. A person who installs pandas by hand should not have
#: to restart Leela to be believed.
INSPECTOR_TTL = 90

#: What a project environment needs to run either kernel. `ipymini` names `comm`, `ipython` and
#: `kernmini` and no more, but imports `fastcore` and `microio`, and `kernmini` moved `debug` out
#: from under it after the version `ipymini` asks for, so resolving the declared requirements alone
#: installs a kernel that cannot start. These are the distributions, and `as_installed` supplies the
#: versions.
KERNEL_PACKAGES = ('ipykernel', 'ipymini', 'kernmini', 'fastcore', 'microio')

_INSPECT = {}
_locks, _locks_lock = {}, threading.Lock()

from ...core.envs import BUNDLE_ONLY, clean_env, strip_bundle   # defined where the environment is

def work_dir(cwd=None):
    """`cwd` as a string, or a directory a child can actually be started in.

    A double-clicked app inherits `/` as its working directory, and one started from `open` inherits
    the bundle, which is read-only and code-signed. Either way a kernel launched there cannot write
    a file beside itself, and the error it gives says nothing about why.
    """
    if cwd: return str(cwd)
    here = os.getcwd()
    if not getattr(sys, 'frozen', False): return here
    return here if here != os.sep and os.access(here, os.W_OK) else str(Path.home())

def support_paths():
    "The `sys.path` entries `bootstrap_src` hands a kernel to borrow from."
    return [p for p in sys.path if p and os.path.isabs(p) and os.path.exists(p)]

def _lock_for(python):
    "One lock per interpreter: two installers in one venv is a race, and three surfaces offer it."
    with _locks_lock: return _locks.setdefault(str(python), threading.Lock())

def _run(args, timeout=180):
    return subprocess.run([str(x) for x in args], env=clean_env(), text=True,
        encoding='utf-8', errors='replace', capture_output=True, timeout=timeout)

def _last_line(text):
    "The line a traceback ends on. numpy's ABI failure wraps its own in eighteen lines of advice."
    return next((l for l in reversed((text or '').strip().splitlines()) if l.strip()), '').strip()

def _probe(python, module, paths=()):
    "Whether `module` imports in `python`, with its version or the failure."
    # The same question the bootstrap asks, and asked the same way: paths only where the version
    # matches. Extending regardless is what made a 3.13 kernel fail on the bundle's 3.12 bytecode.
    pre = (f'import sys\nif tuple(sys.version_info[:2]) == {LEELA_PY!r}: '
           f'sys.path.extend({list(paths)!r})\n') if paths else ''
    p = _run([python, '-c', f'{pre}import {module}; print(getattr({module}, "__version__", "installed"))'], 15)
    return {'available': p.returncode == 0,
        'version': p.stdout.strip() if p.returncode == 0 else '',
        'error': _last_line(p.stderr or p.stdout) if p.returncode else ''}

def kernel_support(python):
    "Importability of both supported kernel launchers in ``python``."
    python = str(Path(python).expanduser())
    return {m: _probe(python, m) for m in ('ipykernel', 'ipymini')}

def inspector_support(python, refresh=False):
    """Whether a kernel on `python` could import the live-variable inspector.

    Asked of the pinned dhrishti itself rather than of a list of package names, so a dependency
    added upstream is answered for too, and so the answer includes what stopped it.
    """
    python = str(Path(python).expanduser())
    hit = _INSPECT.get(python)
    if not refresh and hit and time.time() - hit[0] < INSPECTOR_TTL: return hit[1]
    state = _probe(python, 'dhrishti.serving', support_paths())
    _INSPECT[python] = (time.time(), state)
    return state

def installable(python):
    "Whether Leela may install into `python`. Never itself, and never inside a signed bundle."
    if not python: return False
    p = os.path.abspath(str(python))
    if p == os.path.abspath(sys.executable): return False
    return '/Contents/Resources/' not in p and '/Contents/MacOS/' not in p

def as_installed(names=KERNEL_PACKAGES):
    """`names` pinned to the versions Leela is running, and left loose where Leela has none.

    Leela's own environment is the one combination of these that is known to start a kernel: it is
    resolved from a lock and every release is tested against it. Asking an index for the newest of
    each instead is what produced `ipymini 0.1.20` beside `kernmini 0.1.9`, which import each other
    and do not fit. When Leela upgrades, so does what it installs.
    """
    from importlib.metadata import PackageNotFoundError, version
    out = []
    for name in names:
        try: out.append(f'{name}=={version(name)}')
        except (PackageNotFoundError, ValueError, OSError): out.append(name)
    return out

def _attempts(python, packages):
    "Installer commands to try, in order, for environments that intentionally lack pip."
    out = []
    if uv := shutil.which('uv'): out.append([uv, 'pip', 'install', '--python', python, *packages])
    out.append([python, '-m', 'pip', 'install', *packages])
    if not uv and _run([python, '-m', 'ensurepip', '--upgrade']).returncode == 0:
        out.insert(0, [python, '-m', 'pip', 'install', *packages])
    return out

def _log(command, p):
    return {'command': command, 'returncode': p.returncode,
        'output': (p.stdout + '\n' + p.stderr).strip()[-8000:]}

def _detail(logs):
    return next((a['output'] for a in reversed(logs) if a['output']), 'no installer answered')

def install_kernel_support(python, packages=None):
    """Install kernel packages, preferring uv for environments intentionally lacking pip.

    An installer that returned 0 and left a kernel that will not import is a failure of the
    packages, not of the installer, and saying so is the difference between a report about
    `ipymini` and one about the `pip` a uv environment was never going to have.
    """
    python = str(Path(python).expanduser().absolute())
    packages, logs, unimportable = list(packages or as_installed()), [], ''
    with _lock_for(python):
        for command in _attempts(python, packages):
            p = _run(command, 600)
            logs.append(_log(command, p))
            if p.returncode == 0:
                support = kernel_support(python)
                if all(x['available'] for x in support.values()):
                    return {'ok': True, 'python': python, 'support': support, 'attempts': logs}
                unimportable = '; '.join(f"{name} installed but does not import ({x['error']})"
                                         for name, x in support.items() if not x['available'])
    raise RuntimeError(f'kernel support installation failed: {unimportable or _detail(logs)}')

def install_inspector_support(python, packages=INSPECTOR):
    "Give `python` its own copy of what the inspector imports, then ask it again."
    python = str(Path(python).expanduser().absolute())
    logs = []
    with _lock_for(python):
        for command in _attempts(python, packages):
            p = _run(command, 600)
            logs.append(_log(command, p))
            if p.returncode != 0: continue
            state = inspector_support(python, refresh=True)
            if state['available']:
                return {'ok': True, 'python': python, 'inspector': state, 'attempts': logs}
            raise RuntimeError(f'{" and ".join(packages)} are installed, and the inspector still '
                               f'will not import: {state["error"]}')
    raise RuntimeError(f'could not install {" and ".join(packages)}: {_detail(logs)}')
