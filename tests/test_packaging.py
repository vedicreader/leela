"The desktop build definitions, checked without building anything."

from __future__ import annotations

import re
import importlib.util, json, shutil, subprocess, sys
from pathlib import Path

import pytest
from fastcore.basics import first

ROOT = Path(__file__).resolve().parents[1]

def load(rel):
    "Import a packaging definition by path; they are scripts, not importable modules."
    spec = importlib.util.spec_from_file_location(f'pkg_{Path(rel).parent.name}', ROOT/rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

@pytest.fixture(scope='module')
def mac(): return load('packaging/macos/setup.py')

@pytest.fixture(scope='module')
def win(): return load('packaging/windows/setup.py')

def files(mod):
    "Every source file the definition would copy, as paths relative to the repository."
    return {str(Path(f).relative_to(ROOT)) for _, fs in mod.DATA_FILES for f in fs}

def dests(mod):
    return {d for d, _ in mod.DATA_FILES}

@pytest.mark.parametrize('which', ['mac', 'win'])
def test_the_asset_walk_reaches_subdirectories(which, request):
    """`vendor/fonts/` is the canary."""
    mod = request.getfixturevalue(which)
    got = files(mod)
    assert any(f.startswith('leela/vendor/fonts/') for f in got), 'fonts were left out'
    assert {'leela/vendor/fonts'} <= {d.replace('\\', '/') for d in dests(mod)}
    assert 'leela/static/lee-ide.js' in got and 'leela/static/lee-ide.css' in got and 'leela/static/lee-hl.css' in got
    assert any(f.endswith('.woff2') for f in got), 'the webfonts themselves were left out'


def test_the_window_is_allowed_to_load_the_loopback_server(mac):
    """Without this the app builds, launches, and shows a blank window."""
    ats = mac.PLIST['NSAppTransportSecurity']
    assert ats == {'NSAllowsLocalNetworking': True}
    assert 'NSAllowsArbitraryLoads' not in ats, 'the exemption must stay narrow'


@pytest.mark.parametrize('which', ['mac', 'win'])
def test_a_package_whose_init_is_an_extension_is_grafted_in(which, request):
    """A freezer flattens such a package to the single `.so` and every Python submodule beside it goes missing, silently, until something imports one."""
    import sysconfig
    site = Path(sysconfig.get_paths()['purelib'])
    mod = request.getfixturevalue(which)
    named = set(mod.PACKAGES) | set(mod.GRAFTED)
    for d in sorted(p for p in site.iterdir() if p.is_dir()):
        if not list(d.glob('__init__.*.so')): continue
        if not any(p.suffix == '.py' for p in d.iterdir()): continue
        assert d.name in named, f'{d.name!r} would be flattened; name it in GRAFTED'

@pytest.mark.parametrize('which', ['mac', 'win'])
def test_no_frozen_package_is_shadowed_by_a_directory_in_the_repository_root(which, request):
    """py2app resolves a `packages` name by testing it as a path before looking for the module, and the build runs from the root, so `packaging` copied this repository's own `packaging/`, a stale `dist/` inside it and all, in place of the library."""
    for name in request.getfixturevalue(which).PACKAGES:
        if name == 'leela': continue
        assert not (ROOT/name).exists(), \
            f'{name!r} is also a path in the repository root; put it in INCLUDES instead'

@pytest.mark.parametrize('which', ['mac', 'win'])
def test_every_frozen_package_is_the_import_name_and_not_the_distribution_name(which, request):
    """`PACKAGES` is copied whole because the scanner cannot see an import made inside a function."""
    for name in request.getfixturevalue(which).PACKAGES:
        if name in ('clr_loader', 'pythonnet'): continue     # Windows-only, absent on the test host
        # A uv-made venv carries no pip, which is why the installer falls back to uv. The build
        # venv is made with `python -m venv` and upgrades pip first, so the bundle does get one.
        if name == 'pip': continue
        assert importlib.util.find_spec(name) is not None, f'{name!r} is not an importable package'

def test_the_mac_build_hands_py2app_no_install_requires(mac):
    """py2app 0.28.10 raises `install_requires is no longer supported`, and the build runs from the repository root, so setuptools fills that field in from `pyproject.toml` and every build died before py2app copied a file."""
    import os
    cwd = os.getcwd()
    try:
        os.chdir(ROOT)                       # what `setup_app.py` builds from, and the whole cause
        d = mac.Frozen({'name': 'Leela', 'version': '0'})
        d.parse_config_files()
    finally: os.chdir(cwd)
    assert not d.install_requires, 'py2app refuses a distribution carrying install_requires'


APP = ROOT/'dist'/('Leela.app/Contents/MacOS/Leela' if sys.platform == 'darwin' else 'Leela/Leela.exe')

@pytest.mark.slow
@pytest.mark.skipif(not APP.exists(), reason='no built app in dist/ — run setup_app.py first')
def test_the_built_app_starts_and_serves_its_workspace(tmp_path):
    """What a successful build does not prove: that the bundle can import what it needs."""
    import json, os, time, urllib.request

    env = {**os.environ, 'XDG_CONFIG_HOME': str(tmp_path/'config'),
           'LEELA_WINDOW_SIZE': '900x600', 'PYTHONUNBUFFERED': '1'}
    log = tmp_path/'app.log'
    with log.open('w') as out:
        proc = subprocess.Popen([str(APP), str(tmp_path/'work')], env=env,
                                stdout=out, stderr=subprocess.STDOUT, text=True)
    serving, deadline = tmp_path/'config'/'leela'/'serving.json', time.time() + 120
    try:
        while time.time() < deadline:
            if proc.poll() is not None:
                pytest.fail(f'the app exited with {proc.returncode}:\n{log.read_text()[-3000:]}')
            try: port = json.loads(serving.read_text())['port']; break
            except Exception: time.sleep(.5)
        else: pytest.fail(f'the app never began serving:\n{log.read_text()[-3000:]}')
        try: body = urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=30).read().decode()
        # Every other exit from this test prints the app log and this one did not, so a 500 from
        # the bundle arrived as a bare HTTPError with nothing to say which import had failed.
        except urllib.error.HTTPError as e:
            pytest.fail(f'the app served {e.code} for its own page:\n{e.read().decode()[-1500:]}\n'
                        f'--- app log ---\n{log.read_text()[-3000:]}')
        assert 'lee-ide' in body, f'served a page without the IDE bundle:\n{body[:500]}'
        # A page proves the server imports. It does not prove the *kernel* does, and it did not:
        # pygments loads a style by importing its name, none were bundled, `import IPython` died in
        # the kernel process, and every cell failed on a gateway read timeout instead.
        req = urllib.request.Request(f'http://127.0.0.1:{port}/exec',
                                     data=json.dumps({'code': 'import IPython; print(6*7)'}).encode(),
                                     headers={'Content-Type': 'application/json'})
        # Wrapped for the same reason as the page above: a 500 here is the kernel failing to
        # import, and the assert that would have printed the log is never reached.
        try: ran = urllib.request.urlopen(req, timeout=240).read().decode()
        except urllib.error.HTTPError as e:
            pytest.fail(f'the bundled kernel answered {e.code}:\n{e.read().decode()[-1500:]}\n'
                        f'--- app log ---\n{log.read_text()[-4000:]}')
        assert '42' in ran, f'the bundled kernel could not run a cell:\n{ran[:600]}\n{log.read_text()[-2000:]}'
    finally:
        proc.terminate()
        try: proc.wait(timeout=20)
        except subprocess.TimeoutExpired: proc.kill()


@pytest.mark.parametrize('which', ['mac', 'win'])
def test_pygments_is_copied_whole_or_the_bundled_kernel_cannot_start(which, request):
    """It resolves a style or a lexer by importing its name, 49 and 263 of them that no scanner sees, so a bundle got `pygments/styles/__init__` and none of the styles."""
    mod = request.getfixturevalue(which)
    assert 'pygments' in mod.PACKAGES, 'naming it in INCLUDES would carry the two that are imported'
    assert 'pygments' not in mod.EXCLUDES

@pytest.mark.parametrize('which', ['mac', 'win'])
def test_fastclaude_is_copied_whole_or_no_claude_code_model_can_run(which, request):
    """`fastclaude.session` wraps `files('fastclaude')` in `Path` at import, which raises on a `zipfile.Path`, and `rishi.claude` imports it."""
    assert 'fastclaude' in request.getfixturevalue(which).PACKAGES


def test_a_windowed_launch_is_given_a_utf8_locale(mac):
    """launchd hands an app no LANG, the C locale is POSIX, `open()` defaults to ASCII, and `import rishi.claude` died on a UTF-8 byte, which surfaced as Claude Code being reported not installed."""
    env = mac.PLIST['LSEnvironment']
    assert env['LANG'].lower().endswith('utf-8') and env['PYTHONUTF8'] == '1'


def test_the_build_environment_installs_what_the_lock_names(tmp_path, monkeypatch):
    """pip resolves `>=` against what it finds and keeps what it already has, so `.app-venv` went on carrying the rishi and ramabana it was first built with while the repository moved."""
    import setup_app
    if shutil.which('uv') is None: pytest.skip('no uv here; the lock is what uv exports')
    req = setup_app.lock_requirements()
    assert req is not None and req.exists(), 'uv export answered nothing'
    # Three spellings, all exact: a registry pin is `name==version`, a package taken from a branch
    # exports as `name @ git+URL@sha`, and a checkout beside this one as `-e ../name`. None is a floor.
    pinned, from_git, local = {}, {}, set()
    for line in req.read_text().splitlines():
        if line.startswith(('#', ' ')) or not line.strip(): continue
        if line.startswith('-e '): local.add(Path(line[3:].strip()).name)
        elif ' @ git+' in line:
            nm, _, ref = line.partition(' @ git+')
            from_git[nm.strip()] = ref.strip()
        elif '==' in line:
            nm, _, ver = line.partition('==')
            pinned[nm] = ver
    import tomllib
    lock = tomllib.loads((setup_app.ROOT/'uv.lock').read_text())
    named = {p['name']: p['version'] for p in lock['package'] if 'version' in p}
    for name in ('rishi', 'ramabana', 'fastcore'):
        assert name in pinned or name in from_git or name in local, \
            f'{name} missing from the exported requirements'
        if name in local: continue
        if name in from_git:
            assert re.search(r'@[0-9a-f]{40}$', from_git[name]), \
                f'{name} comes from git at {from_git[name]}, which names no commit'
            continue
        assert pinned[name].split(';')[0].strip() == named[name], \
            f'{name} pinned at {pinned[name]} but the lock names {named[name]}'
    assert 'leela' not in pinned and 'leela' not in from_git and 'leela' not in local, \
        'the project itself is installed editable, not from the lock'


@pytest.mark.skipif(not APP.exists(), reason='no built app in dist/ — run setup_app.py first')
def test_a_build_refuses_to_overwrite_the_app_that_is_running(tmp_path):
    """py2app writes in place, and `python313.zip` is the running app's standard library."""
    import os, setup_app, subprocess, sys, time
    bundle = tmp_path/'Leela.app'
    (bundle/'Contents'/'MacOS').mkdir(parents=True)
    inside = bundle/'Contents'/'MacOS'/'python'
    os.symlink(sys.executable, inside)
    assert setup_app.running_from(bundle) == [], 'nothing is running from it yet'
    # a process that merely names the bundle is not running from it: this test does, and so does
    # every grep and editor with the path on its command line
    mentions = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)', str(bundle)])
    live = subprocess.Popen([str(inside), '-c', 'import time; time.sleep(20)'])
    try:
        for _ in range(50):
            if (pids := setup_app.running_from(bundle)): break
            time.sleep(0.1)
        # `running_from` reads `ps`, so it can only see an interpreter that stays where it was
        # started from. A framework build re-execs itself out of `Python.app` and `ps` then names
        # that, never the bundle: the fixture cannot hold on such a Python, and the guard it is
        # testing has nothing to answer. Asking the interpreter where it thinks it is covers both
        # that and a symlink it refuses to start through at all.
        if not pids:
            named = subprocess.run(['ps', '-o', 'command=', '-p', str(live.pid)],
                                   capture_output=True, text=True).stdout.strip()
            if not named.startswith(str(inside)):
                pytest.skip(f'ps names this process {named or "(gone)"!r} rather than the bundle, '
                            'so the fixture cannot hold on this interpreter')
        assert pids == [live.pid], f'the process running out of the bundle, and only it: {pids}'
    finally:
        for p in (mentions, live): p.terminate(); p.wait(5)

#: Packages whose functions are handed to `fastcore.funccall`, which schemas them with `docments`
#: and so reads their source. `ramabana` and `fastcore` are already copied whole for other reasons.
NEEDS_SOURCE = ('shalya', 'fastspec', 'urai', 'ramabana', 'fastcore')

def test_every_package_a_tool_schema_is_read_from_ships_its_source():
    """`docments` calls `inspect.getsource`, and a package reached from the zip has only `.pyc`."""
    app = ROOT/'dist'/'Leela.app'
    if not app.is_dir(): pytest.skip('no local build; the release is built on a runner')
    lib = first(sorted((app/'Contents'/'Resources'/'lib').glob('python3.*')))
    assert lib is not None, 'the bundle has no lib/python3.x at all'
    missing = [name for name in NEEDS_SOURCE if not any((lib/name).glob('**/*.py'))]
    assert not missing, (f'{", ".join(missing)} ship without source: add them to PACKAGES in '
                         'packaging/macos/setup.py, or every tool schema raises OSError')


#: What the bundle has to be able to import for a feature a person uses on their first day. Every one
#: of these was shipped and unusable at some point because the scanner cannot see how it is reached:
#: `cmath` through a Cython module, `ipykernel_launcher` through a `-m` string, `chardet`'s
#: accelerator as a top-level extension, `nbformat`'s schema as a data file beside `__file__`.
BUNDLED_IMPORTS = ('cmath', 'ipykernel_launcher', 'dhrishti', 'chardet', 'nbformat', 'vishalakshi', 'litert_lm',
                   'rishi.claude')

@pytest.mark.slow
def test_the_bundle_can_import_what_its_features_need():
    """Every other check here asserts a name is on a list."""
    app = ROOT/'dist'/'Leela.app'
    if not app.is_dir(): pytest.skip('dist/Leela.app is not built')
    python = app/'Contents'/'MacOS'/'python'
    if not python.exists(): pytest.skip('the bundle ships no interpreter helper')
    src = 'import ' + ', '.join(BUNDLED_IMPORTS)
    env = {'PYTHONHOME': str(app/'Contents'/'Resources'),
           'PYTHONPATH': ':'.join([str(app/'Contents'/'Resources'/'lib'/'python313.zip'),
                                   str(app/'Contents'/'Resources'/'lib'/'python3.13'),
                                   str(app/'Contents'/'Resources'/'lib'/'python3.13'/'lib-dynload'),
                                   str(_pyskills())])}
    # `-B` and the pyskills dir, as the app has them: a `.pyc` or `pyskills.pth` written here unseals the bundle.
    r = subprocess.run([str(python), '-B', '-c', src], capture_output=True, text=True, timeout=180, env=env)
    assert r.returncode == 0, f'the bundle cannot import what it ships:\n{r.stderr.strip()[-1500:]}'


@pytest.mark.slow
def test_the_browser_driver_is_a_file_the_app_can_execute():
    """`playwright` and `patchright` drive a browser by *running* `driver/node`, and a file inside `python313.zip` cannot be run, so fossick's browser fetching failed in the packaged app and nowhere else."""
    import os, zipfile
    app = ROOT/'dist'/'Leela.app'
    if not app.is_dir(): pytest.skip('dist/Leela.app is not built')
    lib = first(sorted((app/'Contents'/'Resources'/'lib').glob('python3.*')))
    nodes = [lib/name/'driver'/'node' for name in ('playwright', 'patchright')]
    for node in nodes:
        assert node.is_file(), f'{node} is not on disk, so nothing can run it'
        assert os.access(node, os.X_OK), f'{node} lost its execute bit on the way into the bundle'
    a, b = (os.stat(n) for n in nodes)
    assert a.st_ino == b.st_ino, 'the same 121MB binary is in the bundle twice'
    z = first(sorted((app/'Contents'/'Resources'/'lib').glob('python3*.zip')))
    with zipfile.ZipFile(z) as f: names = f.namelist()
    assert not [n for n in names if n.split('/')[0] in ('playwright', 'patchright')], \
        'the archive still holds a copy that would shadow the grafted one'

def test_the_token_stylesheet_is_built_and_current():
    """`lee-hl.css` colours every `hl-*` span; a theme added to `THEMES` without a rebuild would paint nothing."""
    import sys
    sys.path.insert(0, str(ROOT/'tools'))
    import build_hl_css
    assert build_hl_css.OUT.read_text() == build_hl_css.css(), 'lee-hl.css is stale; run python tools/build_hl_css.py'

def test_the_canvas_bundle_is_built_and_current():
    """`/canvas/js` used to concatenate `leela/blocks/canvas/*.js` at request time, and the wheel excludes exactly those files, so an installed Leela served an empty canvas."""
    import sys
    sys.path.insert(0, str(ROOT/'tools'))
    import build_ide_js as builder
    for block in builder.OWN_BUNDLE:
        out = builder.own_out(block)
        assert out.is_file(), f'{out.name} has never been built'
        assert out.read_text() == builder.own_bundle(block), \
            f'{out.name} is stale; run python tools/build_ide_js.py'


def test_the_wheel_carries_every_bundle_the_app_serves():
    """The exclusions keep the modules out of the wheel."""
    import zipfile
    from leela.core.web import IDE_BUNDLES
    from leela.blocks.canvas import ui
    wheels = sorted((ROOT/'dist').glob('leela-*.whl'))
    if not wheels: pytest.skip('no wheel in dist/ — run python -m build --wheel first')
    with zipfile.ZipFile(wheels[-1]) as z: names = set(z.namelist())
    for b in (*IDE_BUNDLES, ui.BUNDLE):
        assert f'leela/static/{b}' in names, f'{b} is not in the wheel'
    assert not [n for n in names if n.startswith('leela/static/js/')], 'the sources should stay out'
    assert not [n for n in names if n.startswith('leela/blocks/') and n.endswith('.js')]

def test_signing_reaches_every_executable_and_gives_them_the_entitlements(tmp_path, monkeypatch):
    """`sign` covered `.so`, `.dylib` and frameworks only, so the helper `python` and Playwright's `node` stayed ad hoc under a Developer ID bundle."""
    import sys
    sys.path.insert(0, str(ROOT/'tools'))
    import build_release
    app = tmp_path/'Leela.app'
    macho = b'\xcf\xfa\xed\xfe' + bytes(12)
    for rel, exe in (('Contents/MacOS/Leela', True), ('Contents/MacOS/python', True), ('Contents/Resources/lib/x.so', False),
                     ('Contents/Resources/lib/playwright/driver/node', True), ('Contents/Frameworks/Python.framework/Versions/3.13/Python', False)):
        (p := app/rel).parent.mkdir(parents=True, exist_ok=True); p.write_bytes(macho)
        if exe: p.chmod(0o755)
    (app/'Contents'/'Resources'/'notes.txt').write_text('not code')
    calls = []
    monkeypatch.setattr(build_release, 'run', lambda *a, **kw: calls.append([str(x) for x in a]))
    build_release.sign(app, 'ID')
    signed = {c[-1]: c for c in calls if c[0] == 'codesign' and '--verify' not in c}
    rel = lambda p: str(app/p)
    for p in ('Contents/MacOS/python', 'Contents/Resources/lib/playwright/driver/node'):
        assert '--entitlements' in signed[rel(p)], p
    assert '--entitlements' not in signed[rel('Contents/Resources/lib/x.so')]
    assert rel('Contents/Resources/notes.txt') not in signed and rel('Contents/MacOS/Leela') not in signed, 'the main executable is signed with the bundle'
    order = [c[-1] for c in calls if c[0] == 'codesign']
    assert order.index(rel('Contents/Frameworks/Python.framework')) > order.index(rel('Contents/Frameworks/Python.framework/Versions/3.13/Python'))
    assert order[-2] == str(app) and '--entitlements' in calls[-2] and '--verify' in calls[-1]
    assert build_release.ENTITLEMENTS.is_file()

def test_signing_signs_a_hardlinked_driver_once_and_keeps_it_one_file(tmp_path, monkeypatch):
    """`codesign --force` on each path split the `link_duplicates` hardlink, so the bundle carried the same 121MB `node` twice."""
    import os, sys
    sys.path.insert(0, str(ROOT/'tools'))
    import build_release
    app = tmp_path/'Leela.app'
    lib = app/'Contents'/'Resources'/'lib'
    for n in ('playwright', 'patchright'): (lib/n/'driver').mkdir(parents=True)
    (a := lib/'playwright'/'driver'/'node').write_bytes(b'\xcf\xfa\xed\xfe' + bytes(28)); a.chmod(0o755)
    os.link(a, b := lib/'patchright'/'driver'/'node')
    calls = []
    monkeypatch.setattr(build_release, 'run', lambda *a, **kw: calls.append([str(x) for x in a]))
    build_release.sign(app, 'ID')
    assert len([c for c in calls if c[-1] in (str(a), str(b))]) == 1
    assert os.stat(a).st_ino == os.stat(b).st_ino

def test_liteparse_is_grafted_and_pils_spare_libraries_are_dropped(mac):
    """`libpdfium.dylib` must sit beside `_liteparse.so`, and no code may stay in the zip, where it cannot be signed."""
    assert 'liteparse' in mac.GRAFTED and 'PIL/.dylibs/' in mac.UNREACHABLE

@pytest.mark.slow
def test_the_bundles_zip_holds_no_code_notarisation_would_refuse():
    """Apple's notary reads inside `python313.zip`, and a Mach-O file there is unsigned: 19 of them made a submission Invalid."""
    import zipfile
    z = ROOT/'dist'/'Leela.app'/'Contents'/'Resources'/'lib'/'python313.zip'
    if not z.is_file(): pytest.skip('dist/Leela.app is not built')
    with zipfile.ZipFile(z) as f:
        code = [n for n in f.namelist() if not n.endswith('/') and '.dSYM/' not in n and f.read(n)[:4] in (b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xce\xfa\xed\xfe')]
    assert not code, code[:10]

@pytest.mark.slow
def test_the_bundle_parses_a_pdf(tmp_path):
    app = ROOT/'dist'/'Leela.app'
    if not app.is_dir(): pytest.skip('dist/Leela.app is not built')
    from PIL import Image
    Image.new('RGB', (40, 20), 'white').save(pdf := tmp_path/'one.pdf', 'PDF')
    res = app/'Contents'/'Resources'
    src = (f"import sys; sys.path[:] = {[str(res/'lib'/'python313.zip'), str(res/'lib'/'python3.13'), str(res/'lib'/'python3.13'/'lib-dynload')]}\n"
           f"from liteparse import LiteParse; LiteParse().parse({str(pdf)!r}); print('ok')")
    r = subprocess.run([str(app/'Contents'/'MacOS'/'python'), '-I', '-S', '-B', '-c', src], capture_output=True, text=True, timeout=120)
    assert r.stdout.strip().endswith('ok'), r.stderr[-1500:]

def _pyskills():
    from leela import pyskills_home
    return pyskills_home()

def _unsealed(app):
    "Files under `app` that `codesign` did not seal: added since signing, or touched after it."
    seal, main = app/'Contents'/'_CodeSignature'/'CodeResources', app/'Contents'/'MacOS'/app.stem
    # The main executable takes its signature after `CodeResources` is written.
    return sorted(str(p.relative_to(app)) for p in app.rglob('*')
                  if p.is_file() and not p.is_symlink() and p != main and p.stat().st_mtime > seal.stat().st_mtime)

def _bundle_pids(app):
    out = subprocess.run(['ps', '-Ao', 'pid=,command='], capture_output=True, text=True).stdout
    return [l.strip() for l in out.splitlines() if str(app) in l.split(None, 1)[-1].split(' -')[0]]

@pytest.mark.slow
@pytest.mark.skipif(sys.platform != 'darwin' or not APP.exists(), reason='no built Leela.app in dist/')
def test_running_the_signed_app_leaves_it_sealed_and_leaves_no_process_behind(tmp_path):
    """A signed bundle that writes into itself fails `codesign --verify` and Gatekeeper. Each of `.pyc`
    in a grafted package, `.sesskey` and `pyskills.pth` did. A forked pool also outlived the quit."""
    import json, os, time, urllib.request
    src = APP.parents[2]
    def verify(app): return subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], capture_output=True, text=True)
    if not (src/'Contents'/'_CodeSignature'/'CodeResources').exists(): pytest.skip('the build is not signed')
    app = tmp_path/'Leela.app'
    subprocess.run(['ditto', str(src), str(app)], check=True, timeout=600)
    assert verify(app).returncode == 0, f'already unsealed; rebuild:\n{verify(app).stderr[-1500:]}\n{_unsealed(app)[:20]}'
    before = {p: p.stat().st_mtime_ns for p in app.rglob('*') if p.is_file()}
    work = tmp_path/'work'; work.mkdir()
    for i in range(30): (work/f'm{i}.py').write_text(f'def f{i}(x): return x+{i}\n')
    env = {**os.environ, 'XDG_CONFIG_HOME': str(tmp_path/'config'), 'XDG_DATA_HOME': str(tmp_path/'data'),
           'LEELA_WINDOW_SIZE': '900x600', 'PYTHONUNBUFFERED': '1'}
    log = tmp_path/'app.log'
    with log.open('w') as out:
        proc = subprocess.Popen([str(app/'Contents'/'MacOS'/'Leela'), str(work)], env=env, stdout=out, stderr=subprocess.STDOUT)
    serving, deadline = tmp_path/'config'/'leela'/'serving.json', time.time() + 120
    try:
        while time.time() < deadline:
            if proc.poll() is not None: pytest.fail(f'the app exited with {proc.returncode}:\n{log.read_text()[-3000:]}')
            try: port = json.loads(serving.read_text())['port']; break
            except Exception: time.sleep(.5)
        else: pytest.fail(f'the app never began serving:\n{log.read_text()[-3000:]}')
        urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=30).read()
        req = urllib.request.Request(f'http://127.0.0.1:{port}/exec', data=json.dumps({'code': 'print(6*7)'}).encode(),
                                     headers={'Content-Type': 'application/json'})
        assert '42' in urllib.request.urlopen(req, timeout=240).read().decode()
        time.sleep(15)   # long enough for the startup indexers to run and write, if anything does
    finally:
        proc.terminate()   # SIGTERM quits through Cocoa, as Cmd+Q does
        try: proc.wait(timeout=30)
        except subprocess.TimeoutExpired: proc.kill(); pytest.fail(f'SIGTERM did not quit the app:\n{log.read_text()[-3000:]}')
    for _ in range(20):
        if not (left := _bundle_pids(app)): break
        time.sleep(.5)
    assert not left, f'processes outlived the app:\n' + '\n'.join(left)
    after = {p: p.stat().st_mtime_ns for p in app.rglob('*') if p.is_file()}
    assert after == before, f'the app wrote into itself: {sorted(str(p.relative_to(app)) for p in after.keys() ^ before.keys() or [k for k in after if after[k] != before.get(k)])}'
    assert not _unsealed(app)
    assert (r := verify(app)).returncode == 0, r.stderr[-1500:]
    assert (tmp_path/'data'/'leela'/'.sesskey').exists(), 'the session key went to the data dir'

@pytest.mark.slow
@pytest.mark.skipif(sys.platform != 'darwin' or not APP.exists(), reason='no built Leela.app in dist/')
def test_quitting_mid_clip_is_quick_and_leaves_no_forked_worker(tmp_path):
    """Forked workers inherited the no-op SIGTERM handler, so the quit waited two seconds on each of 14
    and a Force Quit left the rest idle for good."""
    import json, os, time, urllib.parse, urllib.request
    docs = tmp_path/'docs'; docs.mkdir()
    page = '<html><body>' + ''.join(f'<h2>Section {i}</h2><p>{"words about recall " * 400}</p>' for i in range(200)) + '</body></html>'
    for i in range(48): (docs/f'p{i}.html').write_text(page)
    env = {**os.environ, 'XDG_CONFIG_HOME': str(tmp_path/'config'), 'XDG_DATA_HOME': str(tmp_path/'data'),
           'VISHALAKSHI_VAULT': str(tmp_path/'vault'/'vault.db'), 'LEELA_INDEX_WORKERS': '6',
           'LEELA_WINDOW_SIZE': '900x600', 'PYTHONUNBUFFERED': '1'}
    log = tmp_path/'app.log'
    with log.open('w') as out:
        proc = subprocess.Popen([str(APP), str(docs)], env=env, stdout=out, stderr=subprocess.STDOUT)
    serving, deadline = tmp_path/'config'/'leela'/'serving.json', time.time() + 120
    try:
        while time.time() < deadline:
            if proc.poll() is not None: pytest.fail(f'the app exited with {proc.returncode}:\n{log.read_text()[-3000:]}')
            try: port = json.loads(serving.read_text())['port']; break
            except Exception: time.sleep(.5)
        else: pytest.fail(f'the app never began serving:\n{log.read_text()[-3000:]}')
        q = urllib.parse.urlencode(dict(target=str(docs), kind='clip'))
        urllib.request.urlopen(f'http://127.0.0.1:{port}/clip?{q}', timeout=60).read()
        end = time.time() + 120
        while len(_bundle_pids(APP.parents[2])) < 4 and time.time() < end: time.sleep(.2)
        assert len(_bundle_pids(APP.parents[2])) >= 4, f'no pool was forked:\n{log.read_text()[-3000:]}'
    finally:
        t0 = time.time(); proc.terminate()   # through Cocoa, as Cmd+Q and Dock Quit are
        try: proc.wait(timeout=30)
        except subprocess.TimeoutExpired: proc.kill(); pytest.fail(f'SIGTERM did not quit the app:\n{log.read_text()[-3000:]}')
    assert time.time() - t0 < 8, f'the quit took {time.time() - t0:.1f}s; six workers at two seconds each is the old fault'
    for _ in range(20):
        if not (left := _bundle_pids(APP.parents[2])): break
        time.sleep(.5)
    assert not left, 'processes outlived the app:\n' + '\n'.join(left)
