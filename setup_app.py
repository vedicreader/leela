#!/usr/bin/env python3
"""Build Leela as a desktop application on whichever platform you are on.

    python setup_app.py             # dist/Leela.app, or dist/Leela/Leela.exe
    python setup_app.py --alias     # macOS only: a bundle that imports from this checkout
    python setup_app.py --check     # say what would happen, and build nothing

Why the interpreter dance on macOS: docs/desktop.md.
"""
from __future__ import annotations
import argparse, json, os, re, shutil, subprocess, sys, sysconfig, time
from fastcore.all import Path, first

ROOT = Path(__file__).resolve().parent
VENV = ROOT/'packaging'/'.app-venv'
#: What the frozen app installs. The bundle is built from the lock over these.
APP_EXTRAS = ('desktop', 'macapp')   # the gateway is a dependency now, not an extra
#: Written into the bundle at build; read back to tell a stale install from a current one.
STAMP = 'leela-build.json'
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

__all__ = ['is_framework', 'framework_python', 'py_version', 'lock_requirements', 'build_venv',
           'git_stamp', 'stamp_path', 'write_stamp', 'read_stamp', 'platform_setup', 'running_from',
           'main']

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

def git_stamp():
    "The commit the tree is on and whether it is dirty, or `None` outside a checkout."
    def git(*a):
        r = subprocess.run(['git', *a], cwd=ROOT, capture_output=True, text=True, timeout=30)
        return r.stdout.strip() if not r.returncode else None
    try: sha = git('rev-parse', 'HEAD')
    except (OSError, subprocess.SubprocessError): return None
    if not sha: return None
    return {'commit': sha, 'dirty': bool(git('status', '--porcelain', '--untracked-files=no')),
            'version': _leela_version(), 'built': time.strftime('%Y-%m-%dT%H:%M:%S')}

def _leela_version():
    m = re.search(r'__version__\s*=\s*[\'"]([^\'"]+)', (ROOT/'leela'/'__init__.py').read_text())
    return m.group(1) if m else ''

def stamp_path(bundle):
    "Where the build stamp lives inside `bundle`, on either platform."
    b = Path(bundle)
    return (b/'Contents'/'Resources'/STAMP) if b.suffix == '.app' else (b/STAMP)

def write_stamp(bundle):
    """Record which commit the bundle was built from.

    A bundle is derived from the tree and nothing else compared them, so an app built before a fix
    installs over one built after it and reports the version it always did.
    """
    if (st := git_stamp()) is None: st = {'commit': '', 'dirty': False, 'version': _leela_version(),
                                          'built': time.strftime('%Y-%m-%dT%H:%M:%S')}
    p = stamp_path(bundle)
    if p.parent.is_dir(): p.write_text(json.dumps(st, indent=1) + '\n')
    return st

def read_stamp(bundle):
    "The stamp `bundle` was built with, or None when it has none."
    try: return json.loads(stamp_path(bundle).read_text())
    except (OSError, ValueError): return None

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
        run(exe, '-m', 'pip', 'install', '--quiet', '--no-deps', '-e', f'{ROOT}[desktop,macapp]')
    else: run(exe, '-m', 'pip', 'install', '--quiet', '-e', f'{ROOT}[desktop,macapp]')
    mark_namespaces(exe)
    return exe

#: PEP 420 namespaces py2app has to copy whole. `ruamel` arrives with `ruamel.yaml`, which gheasy
#: reads and writes workflows through.
NAMESPACE_PKGS = ('ruamel',)

def mark_namespaces(exe):
    """Give each PEP 420 namespace an `__init__.py`, because py2app cannot find one without it.

    py2app's `detect_dunder_file` recipe puts every package that reads `__file__` in the copy-whole
    list, and `collect_packagedirs` then resolves each through modulegraph's `imp.find_module`,
    which predates PEP 420 and raises `No module named 'ruamel'` on a directory with no
    `__init__.py`. The build died there with nothing else said. The marker is written inside the
    build venv, which is generated, and only where the namespace has exactly one distribution in it.
    """
    site = next(iter((VENV/'lib').glob('python*/site-packages')), None)
    if site is None: return
    for name in NAMESPACE_PKGS:
        d = site/name
        if not d.is_dir() or (d/'__init__.py').exists(): continue
        (d/'__init__.py').write_text('')
        print(f'· marked {name}/ as a package for py2app')

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

def running_from(bundle):
    """The pids of processes running out of `bundle`, so a build does not overwrite a live app.

    py2app writes the bundle in place, and `python313.zip` is the running app's standard library.
    Replacing it under a live process leaves every import it has not made yet reading a file that
    is no longer the one it opened: `ZipImportError: bad local file header`, from whatever happens
    to import next, naming nothing that would lead anyone back to a rebuild.
    """
    target = str(Path(bundle).resolve())
    try: out = subprocess.run(['ps', '-Ao', 'pid,command'], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError): return []
    pids = []
    for line in out.splitlines()[1:]:
        pid, _, command = line.strip().partition(' ')
        # The executable, not the whole command line: this very check names the bundle in its own
        # arguments, and so does every grep, editor and shell that has the path in it.
        exe = command.split(' ', 1)[0]
        if exe.startswith(target + os.sep) and pid.isdigit() and int(pid) != os.getpid():
            pids.append(int(pid))
    return pids

def main(argv=None):
    p = argparse.ArgumentParser(prog='setup_app.py', description=__doc__.splitlines()[0])
    p.add_argument('--alias', action='store_true',
                   help='macOS: build a bundle that imports from this checkout. Starts in '
                        'seconds and tracks your edits, but is not distributable.')
    p.add_argument('--check', action='store_true', help='report what would happen, then stop')
    p.add_argument('--rebuild-venv', action='store_true', help='discard packaging/.app-venv and make it again')
    p.add_argument('--force', action='store_true', help='build even where the app being replaced is running')
    a = p.parse_args(argv)
    if a.check: return check()
    out = ROOT/'dist'/('Leela.app' if sys.platform == 'darwin' else 'Leela')
    if not a.force and (live := running_from(out)):
        raise SystemExit(f'{out} is running as pid {", ".join(map(str, live))}. Quit it first, or pass --force.\n'
                         'A build replaces the standard library the running app imports from, and it fails from '
                         'then on with a zip error that says nothing about the build.')

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
    stamp = write_stamp(out)
    print(f"\nbuilt {out}")
    print(f"  from {stamp['commit'][:12]}{' with uncommitted changes' if stamp['dirty'] else ''}")

if __name__ == '__main__': main()
