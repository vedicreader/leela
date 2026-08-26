#!/usr/bin/env python3
"""Build Leela as a desktop application on whichever platform you are on.

    python setup_app.py             # dist/Leela.app, or dist/Leela/Leela.exe
    python setup_app.py --alias     # macOS only: a bundle that imports from this checkout
    python setup_app.py --check     # say what would happen, and build nothing

Why the interpreter dance on macOS: docs/desktop.md.
"""
from __future__ import annotations
import argparse, json, os, shutil, subprocess, sys, sysconfig
from fastcore.all import Path, first

ROOT = Path(__file__).resolve().parent
VENV = ROOT/'packaging'/'.app-venv'
#: What the frozen app installs. The bundle is built from the lock over these.
APP_EXTRAS = ('desktop', 'gateway', 'macapp')
# Framework builds on macOS, best first. Not newest first: the version here is the version the
# app ships, and a kernel may only borrow Leela's own `sys.path` from an interpreter of the same
# minor version (`blocks/runtime/support.py`). So the order is what projects are most likely to be
# on, and 3.13 leads. uv's and pyenv's interpreters are absent on purpose: both are
# python-build-standalone, `PYTHONFRAMEWORK` is empty, and py2app cannot embed one in a bundle.
FRAMEWORK_CANDIDATES = (
    '/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13',
    '/Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14',
    '/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12',
    '/opt/homebrew/opt/python@3.13/bin/python3.13',
    '/opt/homebrew/opt/python@3.14/bin/python3.14',
    '/opt/homebrew/opt/python@3.12/bin/python3.12',
    '/usr/local/opt/python@3.13/bin/python3.13',
    '/usr/local/opt/python@3.14/bin/python3.14',
    '/usr/local/opt/python@3.12/bin/python3.12',
    '/usr/bin/python3',
)

__all__ = ['is_framework', 'framework_python', 'py_version', 'lock_requirements', 'build_venv', 'platform_setup', 'main']

def run(*args, **kw):
    print('·', ' '.join(str(a) for a in args))
    return subprocess.run([str(a) for a in args], check=True, **kw)

def is_framework(python=None):
    "Whether `python` (default: this interpreter) is a macOS framework build."
    if python is None: return bool(sysconfig.get_config_var('PYTHONFRAMEWORK'))
    # JSON, not two words: `PYTHONFRAMEWORK` is empty off macOS, and splitting eats the version.
    probe = ('import json,sysconfig,sys;'
             "print(json.dumps([sysconfig.get_config_var('PYTHONFRAMEWORK') or '', "
             'list(sys.version_info[:2])]))')
    try: out = subprocess.run([str(python), '-c', probe], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError): return False
    if out.returncode: return False
    try: name, version = json.loads(out.stdout.strip() or 'null')
    except (ValueError, TypeError): return False
    return bool(name) and tuple(version) >= (3, 12)

def framework_python():
    "The first framework interpreter on this machine that py2app can build against."
    return first(p for c in FRAMEWORK_CANDIDATES if (p := Path(c)).exists() and is_framework(p))

def py_version(python):
    "The `(major, minor)` of `python`, or None when it will not say."
    try: out = subprocess.run([str(python), '-c', 'import sys;print(*sys.version_info[:2])'],
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError): return None
    try: return tuple(int(n) for n in out.stdout.split())
    except ValueError: return None

def build_venv(python, force=False):
    "A build environment on `python`: a plain `venv`, since `uv venv` links what we are avoiding."
    if force: shutil.rmtree(VENV, ignore_errors=True)
    exe = VENV/'bin'/'python'
    # A build environment left over from another interpreter is not reusable: it was reused in
    # silence, so the app went on shipping the old version while the build printed the new one.
    if exe.exists() and py_version(exe) != py_version(python):
        print(f'· rebuilding {VENV.name}: it is on {py_version(exe)}, this build wants {py_version(python)}')
        shutil.rmtree(VENV, ignore_errors=True)
    if not exe.exists():
        VENV.parent.mkdir(parents=True, exist_ok=True)
        run(python, '-m', 'venv', VENV)
    run(exe, '-m', 'pip', 'install', '--upgrade', '--quiet', 'pip', 'setuptools', 'wheel')
    if (req := lock_requirements()) is not None:
        run(exe, '-m', 'pip', 'install', '--quiet', '--upgrade', '-r', req)
        run(exe, '-m', 'pip', 'install', '--quiet', '--no-deps', '-e', f'{ROOT}[desktop,gateway,macapp]')
    else: run(exe, '-m', 'pip', 'install', '--quiet', '-e', f'{ROOT}[desktop,gateway,macapp]')
    return exe

def lock_requirements(extras=APP_EXTRAS):
    """`uv.lock` as a pinned requirements file, or None where uv cannot answer.

    pip resolves `>=` against whatever it finds and keeps whatever it already has, so a build
    environment went on shipping the rishi and ramabana the app was built with months ago while
    the repository moved. The lock is the tested set; the bundle should carry that one.
    """
    if not (ROOT/'uv.lock').exists(): return None
    args = ['uv', 'export', '--frozen', '--no-dev', '--no-hashes', '--no-emit-project',
            '--format', 'requirements-txt']
    for e in extras: args += ['--extra', e]
    try: out = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError): return None
    if out.returncode or not out.stdout.strip():
        print(f'· uv export failed; falling back to resolving from pyproject: {out.stderr.strip()[:200]}')
        return None
    (req := VENV/'app-requirements.txt').parent.mkdir(parents=True, exist_ok=True)
    req.write_text(out.stdout)   # inside the venv, so git ignores it with everything else
    return req

def platform_setup():
    "The py2app or py2exe definition for this platform, and the argv it expects."
    if sys.platform == 'darwin': return ROOT/'packaging'/'macos'/'setup.py', ['py2app']
    if sys.platform == 'win32': return ROOT/'packaging'/'windows'/'setup.py', []
    raise SystemExit(f'no desktop build for {sys.platform}; macOS and Windows build on '
                     'their own OS, and the CI workflow does that on tags')

def check():
    "What a build would do here, without doing it. Answers on any platform, including Linux."
    print(f'platform        {sys.platform}')
    print(f'interpreter     {sys.executable}')
    try: setup, _ = platform_setup()
    except SystemExit as e: print(f'definition      none — {e}')
    else: print(f'definition      {setup.relative_to(ROOT)}')
    if sys.platform == 'darwin':
        print(f'framework build {"yes" if (ok := is_framework()) else "no"}')
        if not ok:
            found = framework_python()
            print(f'would rebuild   {VENV.relative_to(ROOT)} on {found or "NOTHING FOUND"}')
            if not found: print('  install one: brew install python@3.12, or python.org')
    try:
        import webview  # noqa: F401
        print('pywebview       installed')
    except ImportError: print('pywebview       MISSING — pip install "leela[desktop]"')

def main(argv=None):
    p = argparse.ArgumentParser(prog='setup_app.py', description=__doc__.splitlines()[0])
    p.add_argument('--alias', action='store_true',
                   help='macOS: build a bundle that imports from this checkout. Starts in '
                        'seconds and tracks your edits, but is not distributable.')
    p.add_argument('--check', action='store_true', help='report what would happen, then stop')
    p.add_argument('--rebuild-venv', action='store_true', help='discard packaging/.app-venv and make it again')
    a = p.parse_args(argv)
    if a.check: return check()

    setup, extra = platform_setup()
    # `LEELA_APP_VENV` marks the re-exec, so a bad build env reports rather than forks forever.
    if sys.platform == 'darwin' and not is_framework():
        if os.environ.get('LEELA_APP_VENV'):
            raise SystemExit(f'{sys.executable} is still not a framework build; run `python setup_app.py --check`')
        if (found := framework_python()) is None:
            raise SystemExit('py2app needs a framework Python, and this one is a standalone build whose '
                             'stdlib extension modules are not files.\n'
                             'Install one and try again:  brew install python@3.12')
        print(f'framework Python: {found}')
        exe = build_venv(found, force=a.rebuild_venv)
        run(exe, __file__, *(['--alias'] if a.alias else []), env={**os.environ, 'LEELA_APP_VENV': '1'})
        return

    run(sys.executable, ROOT/'tools'/'build_icons.py')
    args = [sys.executable, setup, *extra]
    if a.alias and sys.platform == 'darwin': args.append('--alias')
    run(*args, cwd=ROOT)
    print(f"\nbuilt {ROOT/'dist'/('Leela.app' if sys.platform == 'darwin' else 'Leela')}")

if __name__ == '__main__': main()
