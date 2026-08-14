#!/usr/bin/env python3
"""Build Leela as a desktop application on whichever platform you are on.

    python setup_app.py             # dist/Leela.app, or dist/Leela/Leela.exe
    python setup_app.py --alias     # macOS only: a bundle that imports from this checkout
    python setup_app.py --check     # say what would happen, and build nothing

`tools/build_release.py` calls this and then makes the DMG. The two platform definitions are
in `packaging/macos/setup.py` and `packaging/windows/setup.py`; everything this file adds is
the part that is about the *interpreter* rather than about the bundle.

That part matters on macOS. py2app copies the stdlib's extension modules out of the running
Python, and a `uv`-managed standalone distribution -- which is what a Leela checkout normally
has -- keeps several of them, `zlib` among them, statically linked into the binary rather than
present as `.so` files. The build gets a long way in and then fails on an import that has no
file behind it. So when the active interpreter is not a framework build, this script finds one
that is, creates `packaging/.app-venv` against it, installs Leela and py2app there, and
re-runs itself inside it. The rebuilt environment is reused on subsequent builds.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT/'packaging'/'.app-venv'
# The interpreters that are framework builds on macOS, best first: python.org, then Homebrew
# on Apple silicon and Intel, then the system one, which works but is old and unpatchable.
FRAMEWORK_CANDIDATES = (
    '/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13',
    '/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12',
    '/opt/homebrew/opt/python@3.13/bin/python3.13',
    '/opt/homebrew/opt/python@3.12/bin/python3.12',
    '/usr/local/opt/python@3.13/bin/python3.13',
    '/usr/local/opt/python@3.12/bin/python3.12',
    '/usr/bin/python3',
)

__all__ = ['is_framework', 'framework_python', 'build_venv', 'platform_setup', 'main']


def run(*args, **kw):
    print('·', ' '.join(str(a) for a in args))
    return subprocess.run([str(a) for a in args], check=True, **kw)


def is_framework(python=None):
    """Whether `python` is a macOS framework build, and so usable by py2app.

    Asked of the running interpreter when `python` is None, which is the common case and
    avoids paying for a subprocess to learn something already in this process.
    """
    if python is None: return bool(sysconfig.get_config_var('PYTHONFRAMEWORK'))
    # JSON rather than two words: `PYTHONFRAMEWORK` is the empty string everywhere but macOS,
    # and splitting `" (3, 12)"` on a space reads the version as the framework's name -- which
    # says yes to every interpreter on the machine.
    probe = ('import json,sysconfig,sys;'
             "print(json.dumps([sysconfig.get_config_var('PYTHONFRAMEWORK') or '', "
             'list(sys.version_info[:2])]))')
    try:
        out = subprocess.run([str(python), '-c', probe], capture_output=True, text=True,
                             timeout=30)
    except (OSError, subprocess.SubprocessError): return False
    if out.returncode: return False
    try: name, version = __import__('json').loads(out.stdout.strip() or 'null')
    except (ValueError, TypeError): return False
    return bool(name) and tuple(version) >= (3, 12)


def framework_python():
    "The first framework interpreter on this machine that py2app can build against."
    seen = set()
    for c in FRAMEWORK_CANDIDATES:
        p = Path(c)
        if not p.exists() or str(p) in seen: continue
        seen.add(str(p))
        if is_framework(p): return p
    return None


def build_venv(python, force=False):
    """A build environment on `python` with Leela, its extras, and py2app installed.

    Deliberately a plain `venv` rather than `uv venv`: uv's default is to link its own
    standalone interpreter, which is the thing being avoided.
    """
    if force: shutil.rmtree(VENV, ignore_errors=True)
    exe = VENV/'bin'/'python'
    if not exe.exists():
        VENV.parent.mkdir(parents=True, exist_ok=True)
        run(python, '-m', 'venv', VENV)
    run(exe, '-m', 'pip', 'install', '--upgrade', '--quiet', 'pip', 'setuptools', 'wheel')
    run(exe, '-m', 'pip', 'install', '--quiet', '-e', f'{ROOT}[desktop,gateway,macapp]')
    return exe


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
        ok = is_framework()
        print(f'framework build {"yes" if ok else "no"}')
        if not ok:
            found = framework_python()
            print(f'would rebuild   {VENV.relative_to(ROOT)} on {found or "NOTHING FOUND"}')
            if not found:
                print('  install one: brew install python@3.12, or python.org')
    try:
        import webview  # noqa: F401
        print('pywebview       installed')
    except ImportError:
        print('pywebview       MISSING — pip install "leela[desktop]"')


def main(argv=None):
    p = argparse.ArgumentParser(prog='setup_app.py', description=__doc__.splitlines()[0])
    p.add_argument('--alias', action='store_true',
                   help='macOS: build a bundle that imports from this checkout. Starts in '
                        'seconds and tracks your edits, but is not distributable.')
    p.add_argument('--check', action='store_true', help='report what would happen, then stop')
    p.add_argument('--rebuild-venv', action='store_true',
                   help='discard packaging/.app-venv and make it again')
    a = p.parse_args(argv)
    if a.check: return check()

    setup, extra = platform_setup()
    # `LEELA_APP_VENV` marks the re-exec, so a build environment that is somehow still not a
    # framework build reports that instead of forking interpreters forever.
    if sys.platform == 'darwin' and not is_framework():
        if os.environ.get('LEELA_APP_VENV'):
            raise SystemExit(f'{sys.executable} is still not a framework build; '
                             'run `python setup_app.py --check`')
        found = framework_python()
        if found is None:
            raise SystemExit(
                'py2app needs a framework Python, and this one is a standalone build whose '
                'stdlib extension modules are not files.\n'
                'Install one and try again:  brew install python@3.12')
        print(f'framework Python: {found}')
        exe = build_venv(found, force=a.rebuild_venv)
        run(exe, __file__, *(['--alias'] if a.alias else []),
            env={**os.environ, 'LEELA_APP_VENV': '1'})
        return

    run(sys.executable, ROOT/'tools'/'build_icons.py')
    args = [sys.executable, setup, *extra]
    if a.alias and sys.platform == 'darwin': args.append('--alias')
    run(*args, cwd=ROOT)
    out = ROOT/'dist'/('Leela.app' if sys.platform == 'darwin' else 'Leela')
    print(f'\nbuilt {out}')


if __name__ == '__main__': main()
