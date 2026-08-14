"Probe and install kernel support into a project's Python environment."

from __future__ import annotations

import os, shutil, subprocess
from pathlib import Path

__all__ = ['clean_env', 'kernel_support', 'install_kernel_support']

def clean_env():
    "Environment for a child Python, without py2app's interpreter redirection state."
    env = os.environ.copy()
    for name in ('PYTHONHOME', 'PYTHONPATH', 'PYTHONEXECUTABLE', '__PYVENV_LAUNCHER__', 'RESOURCEPATH'):
        env.pop(name, None)
    env['PYTHONUTF8'] = '1'
    return env

def _run(args, timeout=180):
    return subprocess.run([str(x) for x in args], env=clean_env(), text=True,
        encoding='utf-8', errors='replace', capture_output=True, timeout=timeout)

def _probe(python, module):
    "Whether `module` imports in `python`, with its version or the failure."
    p = _run([python, '-c', f'import {module}; print(getattr({module}, "__version__", "installed"))'], 15)
    return {'available': p.returncode == 0,
        'version': p.stdout.strip() if p.returncode == 0 else '',
        'error': (p.stderr or p.stdout).strip() if p.returncode else ''}

def kernel_support(python):
    "Importability of both supported kernel launchers in ``python``."
    python = str(Path(python).expanduser())
    return {m: _probe(python, m) for m in ('ipykernel', 'ipymini')}

def install_kernel_support(python, packages=('ipykernel>=7.3.0', 'ipymini>=0.0.1')):
    "Install kernel packages, preferring uv for environments intentionally lacking pip."
    python = str(Path(python).expanduser().absolute())
    attempts = []
    if uv := shutil.which('uv'):
        attempts.append([uv, 'pip', 'install', '--python', python, *packages])
    attempts.append([python, '-m', 'pip', 'install', *packages])
    if not uv:
        bootstrap = _run([python, '-m', 'ensurepip', '--upgrade'])
        if bootstrap.returncode == 0:
            attempts.insert(0, [python, '-m', 'pip', 'install', *packages])
    logs = []
    for command in attempts:
        p = _run(command, 600)
        logs.append({'command': command, 'returncode': p.returncode,
            'output': (p.stdout + '\n' + p.stderr).strip()[-8000:]})
        if p.returncode == 0:
            support = kernel_support(python)
            if all(x['available'] for x in support.values()):
                return {'ok': True, 'python': python, 'support': support, 'attempts': logs}
    detail = next((a['output'] for a in reversed(logs) if a['output']), 'no installer answered')
    raise RuntimeError(f'kernel support installation failed: {detail}')
