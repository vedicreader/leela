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
    """`vendor/fonts/` is the canary.

    A flat `iterdir()` here builds and ships perfectly happily, and the app then renders in
    whatever font the machine had. Nothing else in the suite would notice.
    """
    mod = request.getfixturevalue(which)
    got = files(mod)
    assert any(f.startswith('leela/vendor/fonts/') for f in got), 'fonts were left out'
    assert {'leela/vendor/fonts'} <= {d.replace('\\', '/') for d in dests(mod)}
    assert 'leela/static/lee-ide.js' in got and 'leela/static/lee-ide.css' in got
    assert any(f.endswith('.woff2') for f in got), 'the webfonts themselves were left out'

@pytest.mark.parametrize('which', ['mac', 'win'])
def test_the_javascript_sources_are_not_shipped_beside_the_bundle_built_from_them(which, request):
    "The same exclusion the wheel makes: the modules are the input to `static/lee-ide.js`."
    mod = request.getfixturevalue(which)
    shipped = files(mod)
    assert not [f for f in shipped if f.startswith('leela/static/js/')]
    assert not [f for f in shipped if f.startswith('leela/blocks/') and f.endswith('.js')]

@pytest.mark.parametrize('which', ['mac', 'win'])
def test_assets_land_where_a_frozen_leela_looks_for_them(which, request):
    "`leela.core.web.asset_dir` resolves `leela/static` under Resources or beside the exe."
    mod = request.getfixturevalue(which)
    assert {'leela/static', 'leela/vendor'} <= {d.replace('\\', '/') for d in dests(mod)}

@pytest.mark.parametrize('which', ['mac', 'win'])
def test_the_shell_and_the_browser_it_drives_are_both_frozen_in(which, request):
    "A bundle without pywebview has no window, and one without fossick has no inline browser."
    mod = request.getfixturevalue(which)
    assert {'webview', 'fossick', 'fastcdp', 'leela'} <= set(mod.PACKAGES)
    # The platform backend is imported by name at runtime, so the scanner never sees it.
    assert any('platforms' in i for i in mod.INCLUDES)

def test_the_other_platforms_webviews_are_left_out(mac, win):
    assert 'webview.platforms.gtk' in mac.EXCLUDES and 'webview.platforms.cocoa' in win.EXCLUDES

def test_the_window_is_allowed_to_load_the_loopback_server(mac):
    """Without this the app builds, launches, and shows a blank window.

    App Transport Security blocks cleartext HTTP from WKWebView, and Leela's server is
    cleartext HTTP on 127.0.0.1 by design.
    """
    ats = mac.PLIST['NSAppTransportSecurity']
    assert ats == {'NSAllowsLocalNetworking': True}
    assert 'NSAllowsArbitraryLoads' not in ats, 'the exemption must stay narrow'

def test_the_bundle_follows_the_system_appearance(mac):
    "Otherwise every dark theme Leela ships renders against a white window."
    assert mac.PLIST['NSRequiresAquaSystemAppearance'] is False

def test_a_folder_is_a_document_the_app_opens(mac):
    """What makes "Open With → Leela" appear on a folder, and a Dock drop mean something.

    Without a declared document type the packaged app can only ever be opened on its own, and
    the only way into a project is to type its path.
    """
    doc = first(mac.PLIST['CFBundleDocumentTypes'], lambda d: d['CFBundleTypeName'] == 'Folder')
    assert doc['LSItemContentTypes'] == ['public.folder']
    # Not `Owner`: Finder stays the default handler for folders and Leela is merely offered.
    assert doc['LSHandlerRank'] == 'Alternate'

def test_the_bundle_is_versioned_from_the_package(mac):
    from leela import __version__
    assert mac.PLIST['CFBundleShortVersionString'] == __version__

def test_the_frozen_script_is_the_desktop_entry_and_not_the_cli(mac, win):
    "`leela.cli:main` would serve with no window and never return the main thread."
    assert Path(mac.__dict__['ROOT'], 'leela_app.py').is_file()
    assert 'leela_app.py' in str(win.__dict__['ROOT']/'leela_app.py')

def test_windows_keeps_modules_as_files_for_the_kernels_it_launches(win):
    src = (ROOT/'packaging'/'windows'/'setup.py').read_text()
    assert 'zipfile=None' in src, 'a kernel subprocess cannot import from the parent library.zip'

def test_a_standalone_python_is_not_offered_to_py2app():
    """The failure this prevents is a build that dies on `import zlib` minutes in.

    uv's interpreters link the stdlib extension modules into the binary; py2app needs them as
    files. The probe answers about *another* interpreter, so it is a subprocess, and it has to
    be right about the one running the tests too.
    """
    import setup_app
    assert setup_app.is_framework(sys.executable) is setup_app.is_framework()
    assert setup_app.is_framework(Path('/definitely/not/a/python')) is False

def test_check_explains_the_situation_on_any_platform():
    "Including Linux, where there is nothing to build and saying so is the useful answer."
    out = subprocess.run([sys.executable, str(ROOT/'setup_app.py'), '--check'],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert 'platform' in out.stdout and 'pywebview' in out.stdout

def test_a_linux_build_is_refused_with_advice_rather_than_a_traceback(monkeypatch):
    import setup_app
    monkeypatch.setattr(setup_app.sys, 'platform', 'linux')
    with pytest.raises(SystemExit) as e: setup_app.platform_setup()
    assert 'their own OS' in str(e.value)

def test_the_artwork_is_committed_and_everything_drawn_from_it_is_not():
    """One source in the tree, and every icon `tools/build_icons.py` draws from it generated. They
    were committed so a build machine needed no Pillow, which the build extras now carry anyway --
    and a committed copy is one that can disagree with the artwork it came from."""
    import subprocess
    pytest.importorskip('PIL')
    import tools.build_icons as icons
    assert icons.SHEET.is_file() and icons.SHEET.stat().st_size > 1000, 'one sheet is the source'
    # Every mark is cut from it, so there is no second copy of the artwork to disagree with.
    assert not list(icons.ASSETS.glob('leela-mark*.png')), 'the marks are generated, not committed'
    assert not list(icons.ASSETS.glob('leela-turtle*.png')), 'and the old artwork is gone'
    tracked = subprocess.run(['git', 'ls-files', 'packaging/assets'], cwd=ROOT,
                             capture_output=True, text=True).stdout.split()
    drawn = {'Leela.png', 'Leela.ico', 'Leela.svg', 'Leela.icns'}
    assert not {Path(t).name for t in tracked} & drawn, 'generated icons are not committed'
    assert not any('Leela.iconset' in t for t in tracked)

@pytest.mark.parametrize('which', ['mac', 'win'])
def test_a_package_whose_init_is_an_extension_is_grafted_in(which, request):
    """A freezer flattens such a package to the single `.so` and every Python submodule beside it
    goes missing, silently, until something imports one. `apsw` is the case that shipped: the vault
    reaches `apsw.ext` through fastlite, so the app built, started, and died restoring a workspace.
    `PACKAGES` is not the answer for one of these -- py2app looks for an `__init__.py` to find it --
    so `GRAFTED` names it and the bundle gets the real directory after the freezer has run."""
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
    """py2app resolves a `packages` name by testing it as a path before looking for the module, and
    the build runs from the root, so `packaging` copied this repository's own `packaging/` -- a
    stale `dist/` inside it and all -- in place of the library. Such a name goes in `includes`.

    `leela` is the one name where that resolution is right, because the directory in the root is
    what we mean by it."""
    for name in request.getfixturevalue(which).PACKAGES:
        if name == 'leela': continue
        assert not (ROOT/name).exists(), \
            f'{name!r} is also a path in the repository root; put it in INCLUDES instead'

@pytest.mark.parametrize('which', ['mac', 'win'])
def test_every_frozen_package_is_the_import_name_and_not_the_distribution_name(which, request):
    """`PACKAGES` is copied whole because the scanner cannot see an import made inside a function.
    py2app warns that it cannot find the name, then raises `ImportError` when it goes to copy it,
    so one wrong name fails the build. The distribution is `koshas` and the package is `kosha`."""
    for name in request.getfixturevalue(which).PACKAGES:
        if name in ('clr_loader', 'pythonnet'): continue     # Windows-only, absent on the test host
        # A uv-made venv carries no pip, which is why the installer falls back to uv. The build
        # venv is made with `python -m venv` and upgrades pip first, so the bundle does get one.
        if name == 'pip': continue
        assert importlib.util.find_spec(name) is not None, f'{name!r} is not an importable package'

def test_the_mac_build_hands_py2app_no_install_requires(mac):
    """py2app 0.28.10 raises `install_requires is no longer supported`, and the build runs from the
    repository root, so setuptools fills that field in from `pyproject.toml` and every build died
    before py2app copied a file. The distribution class is what empties it again."""
    import os
    cwd = os.getcwd()
    try:
        os.chdir(ROOT)                       # what `setup_app.py` builds from, and the whole cause
        d = mac.Frozen({'name': 'Leela', 'version': '0'})
        d.parse_config_files()
    finally: os.chdir(cwd)
    assert not d.install_requires, 'py2app refuses a distribution carrying install_requires'

def test_both_platform_builds_say_to_draw_the_icons_first():
    "Nothing generated is in a fresh checkout, so a build that needs one has to name the command."
    for rel in ('packaging/macos/setup.py', 'packaging/windows/setup.py'):
        assert 'tools/build_icons.py' in (ROOT/rel).read_text(), rel

def test_the_build_extras_carry_what_the_build_imports():
    """`Leela.icns` is built, not committed, and the workflow installs the extras and nothing else.

    The freezer and the icon tooling both arrive through `kavacha`, which installs py2app or py2exe
    and Pillow per platform. Naming the extra is what a checkout can check; that the tooling is
    really there is the import below."""
    import tomllib
    extras = tomllib.load(open(ROOT/'pyproject.toml', 'rb'))['project']['optional-dependencies']
    for which in ('macapp', 'windows'):
        assert any(f'kavacha[{which}]' in d for d in extras[which]), f'{which} names no freezer'
    pytest.importorskip('PIL')
    from kavacha.icons import icns  # noqa: F401

def test_a_release_says_what_is_missing_rather_than_failing_inside_shutil(monkeypatch):
    "With the app build skipped and no bundle to package, both platforms say so."
    import tools.build_release as rel
    monkeypatch.setenv('LEELA_SKIP_APP_BUILD', '1')
    monkeypatch.setattr(rel, 'run', lambda *a, **kw: None)
    monkeypatch.setattr(rel, 'ROOT', Path('/nonexistent-leela-root'))
    for build in (rel.mac_release, rel.windows_release):
        with pytest.raises(SystemExit) as e: build()
        assert 'was not built' in str(e.value)

def test_the_favicon_is_the_mark_it_is_generated_from():
    """The favicons ship in the wheel, which has no build step, so they are committed like the JS
    bundles rather than drawn at install. Committed and generated means they can drift.

    Two of them: the mark is line work with no plate, so a tab strip shows its own colour through
    it and the ink has to follow `prefers-color-scheme`.
    """
    pytest.importorskip('PIL')
    import tools.build_icons as icons
    for variant, path in icons.FAVICONS.items():
        assert path.read_text() == icons.favicon(variant), \
            f'{path.name} is stale; run python tools/build_icons.py'
    assert icons.FAVICONS['light'].read_text() != icons.FAVICONS['dark'].read_text(), \
        'one artwork under two names is not a light and a dark variant'
    app = (ROOT/'leela'/'app.py').read_text()
    for name in ('favicon.svg', 'favicon-dark.svg'):
        assert f"_asset('{name}')" in app, f'{name} is generated but never served'

def test_the_app_artefacts_attach_to_the_release_the_tag_names(tmp_path, monkeypatch):
    "The last two release steps: build the bundle, then put it on the release just made."
    import tools.build_release as rel
    monkeypatch.setattr(rel, 'ROOT', Path(tmp_path))
    with pytest.raises(SystemExit) as e: rel.upload()
    assert 'nothing to upload' in str(e.value)
    (tmp_path/'leela').mkdir()
    (tmp_path/'leela'/'__init__.py').write_text('"doc"\n__version__ = "9.9.9"\n')
    (tmp_path/'dist').mkdir()
    (tmp_path/'dist'/'Leela-macOS.dmg').write_text('x')
    calls = []
    monkeypatch.setattr(rel, 'run', lambda *a, **kw: calls.append([str(x) for x in a]))
    rel.upload()
    assert calls[-1][:4] == ['gh', 'release', 'upload', 'v9.9.9']
    assert calls[-1][-1] == '--clobber'
    rel.upload('v1.2.3')
    assert calls[-1][3] == 'v1.2.3', 'CI passes the tag it was pushed for'

def test_the_desktop_workflow_puts_the_artefacts_on_the_release():
    "A tag push builds both bundles; without `contents: write` neither can attach."
    import yaml
    doc = yaml.safe_load((ROOT/'.github'/'workflows'/'desktop-artifacts.yml').read_text())
    assert doc['permissions']['contents'] == 'write'
    assert doc[True]['push']['tags'] == ['v*'], 'the tags `ship-release` pushes'
    for job in doc['jobs'].values():
        step = first(job['steps'], lambda s: s.get('name') == 'attach to the release')
        assert step, 'both platforms attach what they built'
        assert 'build_release.py upload' in step['run']
        assert step['if'] == "startsWith(github.ref, 'refs/tags/')"

def test_a_missing_window_icon_is_reported_rather_than_shrugged_off(monkeypatch, capsys):
    """`_icon` answers with `first`, which is None when nothing matches.

    The PNG is generated rather than committed, so a checkout that has not run the generator has no
    icon, and the window silently wore the default one."""
    import leela_app
    monkeypatch.setattr(leela_app.Path, 'is_file', lambda self: False)
    assert leela_app._icon() is None
    assert 'build_icons' in capsys.readouterr().out

def test_the_icon_generator_is_reproducible(tmp_path, monkeypatch):
    "The generated PNG must be what the generator makes, or a stale one is shipped."
    pytest.importorskip('PIL')
    import tools.build_icons as icons
    made = icons.image(1024)
    committed = __import__('PIL.Image', fromlist=['Image']).open(ROOT/'packaging'/'assets'/'Leela.png')
    assert made.tobytes() == committed.convert('RGBA').tobytes()

APP = ROOT/'dist'/('Leela.app/Contents/MacOS/Leela' if sys.platform == 'darwin' else 'Leela/Leela.exe')

@pytest.mark.slow
@pytest.mark.skipif(not APP.exists(), reason='no built app in dist/ — run setup_app.py first')
def test_the_built_app_starts_and_serves_its_workspace(tmp_path):
    """What a successful build does not prove: that the bundle can import what it needs.

    py2app and py2exe both produce a runnable artefact that dies on the first missing module,
    so the release workflow runs this after building.

    The address comes from the `serving.json` the workspace writes, not from its stdout: a frozen
    app's stdout is a block-buffered pipe, and reading it for the port blocked here forever while
    the bundle was in fact crashing. `XDG_CONFIG_HOME` moves that file, and the remembered folders
    with it, into `tmp_path`, so this neither reads nor disturbs the config of whoever runs it.
    """
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

def test_the_macmage_cantrip_only_posts_to_routes_that_exist():
    """The shortcuts reach Leela over HTTP from outside it, so a renamed route breaks them silently
    -- there is no import to fail and no page to 404 in front of anybody."""
    import ast, re
    src = (ROOT/'packaging'/'macmage'/'leela.py').read_text()
    tree = ast.parse(src)
    posted = {n.args[0].value for n in ast.walk(tree)
              if isinstance(n, ast.Call) and getattr(n.func, 'id', '') == 'call'
              and n.args and isinstance(n.args[0], ast.Constant)}
    assert posted, 'the cantrip calls something'
    known = {line.split(' ', 1)[1].strip() for line in (ROOT/'tests'/'routes.txt').read_text().splitlines() if ' ' in line}
    assert posted <= known, f'{posted - known} is not a route Leela serves'
    assert '/fs/add-root' in posted, 'the JSON one; `/fs/add_root` answers with a whole page'

def test_the_macmage_cantrip_reads_the_address_leela_publishes():
    "Both sides name the same file, and neither imports the other to find out."
    from leela.core.projects import SERVING
    src = (ROOT/'packaging'/'macmage'/'leela.py').read_text()
    assert "'leela'/'serving.json'" in src or "'serving.json'" in src
    assert SERVING.name == 'serving.json' and SERVING.parent.name == 'leela'
    assert 'import leela' not in src, 'a macmage virtualenv has no leela in it'

def test_both_platforms_leave_out_the_same_heavy_backends(mac, win):
    """`leela[local]` is not in the download: mlx, cv2, transformers and scipy alone were about
    400MB of a 1.4GB bundle, for a runtime most people never pick. Two lists that drift would
    quietly put it back on one platform."""
    assert mac.HEAVY == win.HEAVY
    for m in (mac, win):
        assert set(m.HEAVY) <= set(m.EXCLUDES), 'the heavy list is what EXCLUDES is built from'
        assert not set(m.HEAVY) & set(m.PACKAGES), 'excluded and copied whole at once'

def test_pip_is_shipped_so_the_app_can_fetch_a_backend(mac, win):
    """A signed bundle cannot be written into and carries no other installer, so without pip the
    on-demand backends are unreachable and leaning the build just removes features."""
    for m in (mac, win):
        assert 'pip' in m.PACKAGES, 'nothing imports pip, so only PACKAGES brings it'
        assert 'pip' not in m.EXCLUDES

def test_the_default_install_does_not_carry_the_local_backends():
    "The whole point of the leaning: `leela` alone must not resolve to `rishi[all]`."
    import tomllib
    cfg = tomllib.load(open(ROOT/'pyproject.toml', 'rb'))['project']
    assert not any('ramabana[all]' in d for d in cfg['dependencies']), 'ramabana[all] carries rishi[all]'
    assert any(d.startswith('ramabana') for d in cfg['dependencies'])
    local = cfg['optional-dependencies']['local']
    assert any('rishi[' in d and 'mlx' in d for d in local), 'the backends live in leela[local]'


@pytest.mark.parametrize('which', ['mac', 'win'])
def test_pygments_is_copied_whole_or_the_bundled_kernel_cannot_start(which, request):
    """It resolves a style or a lexer by importing its name -- 49 and 263 of them that no scanner
    sees -- so a bundle got `pygments/styles/__init__` and none of the styles. `import IPython`
    then died inside the kernel process, the gateway waited for a kernel that was already gone, and
    every cell failed on a read timeout with nothing naming pygments."""
    mod = request.getfixturevalue(which)
    assert 'pygments' in mod.PACKAGES, 'naming it in INCLUDES would carry the two that are imported'
    assert 'pygments' not in mod.EXCLUDES


def test_leela_asks_to_own_the_languages_it_edits(mac):
    """One list: the document types come from the same `LANGS` the file tree uses, so a language
    added there is a file type the app opens without anyone remembering this file."""
    from leela.blocks.fs.fs import LANGS
    types = {d['CFBundleTypeName']: d for d in mac.PLIST['CFBundleDocumentTypes']}
    src = types['Source file']
    assert src['LSHandlerRank'] == 'Owner' and src['CFBundleTypeRole'] == 'Editor'
    exts = set(src['CFBundleTypeExtensions'])
    assert 'py' in exts and 'ipynb' in exts and 'md' in exts
    assert not exts & {e.lstrip('.') for e in mac.VIEW_ELSEWHERE}, 'a browser renders these better'
    assert exts <= {e.lstrip('.') for e, l in LANGS.items() if l}, 'nothing claimed that Leela cannot edit'
    # A folder is still Finder's, or every directory in the Finder would open Leela.
    assert types['Folder']['LSHandlerRank'] == 'Alternate'


def test_a_windowed_launch_is_given_a_utf8_locale(mac):
    """launchd hands an app no LANG, the C locale is POSIX, `open()` defaults to ASCII, and
    `import rishi.claude` died on a UTF-8 byte -- which surfaced as Claude Code being reported not
    installed. The plist sets it before the interpreter starts; `leela.use_utf8` cannot."""
    env = mac.PLIST['LSEnvironment']
    assert env['LANG'].lower().endswith('utf-8') and env['PYTHONUTF8'] == '1'


def test_no_junk_directory_rides_along_inside_the_package():
    """`leela` is copied whole, and py2app copies a directory, not a git tree. A `uv` run from
    inside `leela/` left a 56MB `.venv` there and it went straight into the bundle, invisible to
    `git status` because it is ignored."""
    pkg = ROOT/'leela'
    junk = [p.name for p in pkg.iterdir()
            if p.is_dir() and (p.name in ('.venv', 'venv', 'node_modules', '.tox', 'dist', 'build')
                               or (p/'pyvenv.cfg').is_file())]
    assert junk == [], f'{junk} would be copied into the app; delete it'


def test_signing_and_notarising_are_opt_in(monkeypatch):
    "With no credentials the build still makes a launchable app, which is what a fork gets."
    import tools.build_release as rel
    for k in ('LEELA_NOTARY_PROFILE', 'LEELA_ASC_KEY', 'LEELA_ASC_KEY_ID', 'LEELA_ASC_ISSUER',
              'LEELA_APPLE_ID', 'LEELA_APPLE_PASSWORD', 'LEELA_TEAM_ID'):
        monkeypatch.delenv(k, raising=False)
    assert rel.notary_args() == []
    with pytest.raises(SystemExit, match='nothing to notarize'): rel.notarize(Path('x.dmg'))

@pytest.mark.parametrize('env,want', [
    ({'LEELA_NOTARY_PROFILE': 'p'}, '--keychain-profile'),
    ({'LEELA_ASC_KEY': 'k.p8', 'LEELA_ASC_KEY_ID': 'i', 'LEELA_ASC_ISSUER': 's'}, '--key'),
    ({'LEELA_APPLE_ID': 'a@b.c', 'LEELA_APPLE_PASSWORD': 'x', 'LEELA_TEAM_ID': 'T'}, '--apple-id'),
])
def test_each_way_of_authenticating_to_the_notary_service(env, want, monkeypatch):
    "A keychain profile is one secret instead of three, so it is preferred where it exists."
    import tools.build_release as rel
    for k in ('LEELA_NOTARY_PROFILE', 'LEELA_ASC_KEY', 'LEELA_ASC_KEY_ID', 'LEELA_ASC_ISSUER',
              'LEELA_APPLE_ID', 'LEELA_APPLE_PASSWORD', 'LEELA_TEAM_ID'):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items(): monkeypatch.setenv(k, v)
    assert want in rel.notary_args()

def test_the_notarised_dmg_is_stapled(monkeypatch, tmp_path):
    "Without stapling Gatekeeper asks Apple on first launch, and fails when there is no network."
    import tools.build_release as rel
    monkeypatch.setenv('LEELA_NOTARY_PROFILE', 'leela')
    calls = []
    monkeypatch.setattr(rel, 'run', lambda *a, **kw: calls.append([str(x) for x in a]))
    rel.notarize(tmp_path/'Leela.dmg')
    assert calls[0][:3] == ['xcrun', 'notarytool', 'submit'] and '--wait' in calls[0]
    assert calls[1][:3] == ['xcrun', 'stapler', 'staple']
    assert calls[2][:3] == ['xcrun', 'stapler', 'validate']

def test_distribution_signing_does_not_use_deep(mac):
    """`--deep` signs nested code with the outer bundle's arguments and skips what it does not
    recognise, which is why Apple tells you not to and why the notary service rejects it."""
    src = (ROOT/'tools'/'build_release.py').read_text()
    body = src[src.index('def sign('):src.index('def notary_args(')]
    assert "'--deep'" not in body.split('--verify')[0], 'signing must walk inner code itself'
    assert "'--timestamp'" in body, 'notarisation requires a secure timestamp'
    assert "'runtime'" in body, 'the hardened runtime is required too'


def test_what_only_a_lazy_import_reaches_is_still_bundled(mac, win):
    """`workspace._attachment_context` imports `ramabana.cli` inside the function, so no scanner
    follows it to rich, pyghostty or teleprint. Attaching a file in the app said rich was not
    installed, and leaning `ramabana[all]` to `ramabana` is what took them out."""
    for m in (mac, win):
        assert {'rich', 'pyghostty', 'teleprint'} <= set(m.PACKAGES), 'reached only from cli.py'

def test_the_media_helpers_can_actually_be_imported():
    "The check the bundle cannot do for itself: the module Leela reaches for has what it needs."
    from ramabana.cli import MEDIA, Attachment, media_note, media_parts   # noqa: F401
    assert MEDIA, 'the media table is what `_attachment_context` reads'

def test_leela_asks_for_the_ramabana_extra_that_module_needs():
    "Plain `ramabana` does not carry pyghostty or teleprint, and `cli.py` imports both."
    import tomllib
    deps = tomllib.load(open(ROOT/'pyproject.toml', 'rb'))['project']['dependencies']
    assert any(d.startswith('ramabana[') and 'cli' in d for d in deps), deps


def test_both_bundles_name_what_the_inspector_imports(mac, win):
    """pandas reached the DMG only because py2app's scanner followed dhrishti's module-level import.
    Leela's server never imports dhrishti, on purpose, so nothing in Leela's own source states the
    dependency, and a scanner that stopped following it would drop the variables panel out of the
    app with no test to say so."""
    from leela.blocks.runtime.support import INSPECTOR
    for m in (mac, win):
        assert set(INSPECTOR) <= set(m.PACKAGES), f'{m.__name__} carries no {set(INSPECTOR) - set(m.PACKAGES)}'


@pytest.mark.parametrize('which', ('mac', 'win'))
def test_the_file_watcher_is_copied_whole_like_everything_imported_in_a_function(which, request):
    """`blocks/fs/watch.py` imports watchfiles inside the watch thread, so the scanner never saw it.

    The thread answers a failed import by returning, so the frozen app simply stopped following the
    disk: no traceback, no message, a tree that looked stale rather than broken. The launch test
    could not catch it either, because a watcher that never starts breaks nothing that it asserts.
    """
    assert 'watchfiles' in request.getfixturevalue(which).PACKAGES

def test_the_watcher_says_why_it_stopped_rather_than_returning_in_silence(monkeypatch, capsys):
    "It went unnoticed in every packaged build; the next time it must at least be readable."
    import builtins, threading
    from leela.blocks.fs.watch import Watcher
    real = builtins.__import__
    def no_watchfiles(name, *a, **kw):
        if name == 'watchfiles': raise ImportError('No module named watchfiles')
        return real(name, *a, **kw)
    monkeypatch.setattr(builtins, '__import__', no_watchfiles)
    w = object.__new__(Watcher)
    w.step = 0
    Watcher._run(w, [], threading.Event())
    assert 'will not follow the disk' in capsys.readouterr().out


def test_the_bundle_prefers_the_python_most_projects_are_on_not_the_newest():
    """The version here is the version the app ships, and a kernel borrows Leela's `sys.path` only
    from its own minor version. Shipping the newest would put the bundle ahead of every project and
    turn borrowing off for all of them."""
    import setup_app
    versions = [c.split('python')[-1] for c in setup_app.FRAMEWORK_CANDIDATES if 'python3.1' in c]
    for group in (versions[:3], versions[3:6], versions[6:9]):
        assert group and group[0] == '3.13', f'3.13 leads its group, got {group}'
        assert '3.14' in group and group.index('3.14') > 0, f'3.14 is offered, behind it: {group}'

def test_no_standalone_interpreter_is_offered_to_py2app():
    "uv's and pyenv's builds report an empty PYTHONFRAMEWORK; py2app cannot embed one."
    import setup_app
    for c in setup_app.FRAMEWORK_CANDIDATES:
        assert '/uv/python/' not in c and '.pyenv' not in c, c


def test_a_build_environment_on_another_python_is_rebuilt_not_reused(tmp_path, monkeypatch):
    """Changing the framework interpreter left `.app-venv` alone, so the build announced
    `framework Python: ...3.13` and then shipped 3.12 out of the environment it already had."""
    import setup_app
    venv = tmp_path/'.app-venv'
    (venv/'bin').mkdir(parents=True)
    (venv/'bin'/'python').write_text('')
    monkeypatch.setattr(setup_app, 'VENV', venv)
    monkeypatch.setattr(setup_app, 'py_version', lambda p: (3, 12) if 'app-venv' in str(p) else (3, 13))
    ran = []
    monkeypatch.setattr(setup_app, 'run', lambda *a, **k: ran.append([str(x) for x in a]))
    setup_app.build_venv('/opt/homebrew/opt/python@3.13/bin/python3.13')
    assert not (venv/'bin'/'python').exists() or any('venv' in c for c in ran[0]), \
        'the stale environment was removed and a new one asked for'
    assert ran and ran[0][1:3] == ['-m', 'venv'], ran[:1]

def test_a_build_environment_on_the_same_python_is_kept(tmp_path, monkeypatch):
    "Rebuilding it every time would add minutes to every build for nothing."
    import setup_app
    venv = tmp_path/'.app-venv'
    (venv/'bin').mkdir(parents=True)
    (venv/'bin'/'python').write_text('')
    monkeypatch.setattr(setup_app, 'VENV', venv)
    monkeypatch.setattr(setup_app, 'py_version', lambda p: (3, 13))
    ran = []
    monkeypatch.setattr(setup_app, 'run', lambda *a, **k: ran.append([str(x) for x in a]))
    setup_app.build_venv('/opt/homebrew/opt/python@3.13/bin/python3.13')
    assert not any(c[1:3] == ['-m', 'venv'] for c in ran), 'nothing was recreated'


def test_the_build_environment_installs_what_the_lock_names(tmp_path, monkeypatch):
    """pip resolves `>=` against what it finds and keeps what it already has, so `.app-venv` went on
    carrying the rishi and ramabana it was first built with while the repository moved. A build
    shipped the exact on-device corruption the tree had already fixed."""
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

def test_the_exported_requirements_live_where_git_ignores_them():
    "A generated file beside the build definition is one somebody commits by accident."
    import setup_app
    assert setup_app.VENV.name == '.app-venv'
    assert (setup_app.VENV/'app-requirements.txt').parent == setup_app.VENV


def test_a_built_bundle_records_the_commit_it_was_built_from(tmp_path):
    "Without it, an app built before a fix installs over one built after and looks identical."
    import setup_app
    bundle = tmp_path/'Leela.app'
    (bundle/'Contents'/'Resources').mkdir(parents=True)
    st = setup_app.write_stamp(bundle)
    assert setup_app.stamp_path(bundle).exists()
    back = setup_app.read_stamp(bundle)
    assert back == st and set(back) == {'commit', 'dirty', 'version', 'built'}
    assert setup_app.read_stamp(tmp_path/'Nothing.app') is None, 'a bundle with no stamp says so'

def test_the_stamp_lands_where_each_platform_keeps_it():
    "macOS hides resources inside the bundle; the Windows folder is the bundle."
    import setup_app
    assert setup_app.stamp_path('/x/Leela.app').parts[-3:] == ('Contents', 'Resources', setup_app.STAMP)
    assert setup_app.stamp_path('/x/Leela').parts[-1] == setup_app.STAMP

@pytest.mark.skipif(not APP.exists(), reason='no built app in dist/ — run setup_app.py first')
def test_a_build_refuses_to_overwrite_the_app_that_is_running(tmp_path):
    """py2app writes in place, and `python313.zip` is the running app's standard library. Replacing
    it under a live process made every import it had not yet made fail with `bad local file header`,
    naming nothing that would lead anyone back to the rebuild that did it."""
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
    """`docments` calls `inspect.getsource`, and a package reached from the zip has only `.pyc`.

    Every model resolved to `OSError: could not get source code`, the routing fell back off each
    one in turn, and the app was left unable to answer. It worked while the toolset lived in
    `ramabana`, which is copied whole; it moved to `shalya`, which was not on the list.
    """
    app = ROOT/'dist'/'Leela.app'
    if not app.is_dir(): pytest.skip('no local build; the release is built on a runner')
    lib = first(sorted((app/'Contents'/'Resources'/'lib').glob('python3.*')))
    assert lib is not None, 'the bundle has no lib/python3.x at all'
    missing = [name for name in NEEDS_SOURCE if not any((lib/name).glob('**/*.py'))]
    assert not missing, (f'{", ".join(missing)} ship without source: add them to PACKAGES in '
                         'packaging/macos/setup.py, or every tool schema raises OSError')


def test_the_built_app_matches_the_tree_it_was_built_from():
    """The bundle is derived from the tree and nothing compared them.

    Three times in one session a build was tested that predated the fix it was being tested for,
    because an installed app carries no record of where it came from.

    Skipped where there is no bundle: the release is built on a runner, so a checkout that has
    never packaged locally has nothing to be stale. It is a bundle that disagrees with the tree
    that is worth failing over.
    """
    import setup_app
    app = ROOT/'dist'/'Leela.app'
    if not app.is_dir(): pytest.skip('no local build; the release is built on a runner')
    st = setup_app.read_stamp(app)
    assert st is not None, 'dist/Leela.app has no build stamp; rebuild it'
    here = setup_app.git_stamp()
    if here is None: pytest.skip('not a git checkout')
    assert st['commit'] == here['commit'], (
        f"dist/Leela.app was built from {st['commit'][:12]} but the tree is at "
        f"{here['commit'][:12]}; rebuild before trusting it")

def test_the_runtime_the_vault_reads_a_model_id_from_is_in_the_bundle(mac):
    """`vishalakshi` imports `rishi.litert` for one model id, and that module is the litert module.
    Leaving `litert_lm` out took the vault, and with it memory, out of the packaged app: every save
    of an agent state answered 400 and the box that asked for it had no way to say why."""
    assert 'litert_lm' not in mac.HEAVY, 'the bundle carries the runtime the vault reads from'
    assert 'mlx' in mac.HEAVY and 'llama_cpp' in mac.HEAVY, 'the ones that are really optional still are'

def test_an_installed_backend_survives_a_restart():
    """`use_extras` puts the directory an optional backend is installed into on `sys.path`, and it
    was called in one place: straight after an install. A backend worked for the session that
    installed it and was gone at the next launch, which made every install look like it had failed."""
    cli = (ROOT/'leela'/'cli.py').read_text()
    body = cli[cli.index('def main('):]
    assert 'use_extras()' in body, 'the process puts the extras directory on its own path at startup'
    assert body.index('use_extras()') < body.index('serve_ide'), 'and before anything imports a backend'

#: What the bundle has to be able to import for a feature a person uses on their first day. Every one
#: of these was shipped and unusable at some point because the scanner cannot see how it is reached:
#: `cmath` through a Cython module, `ipykernel_launcher` through a `-m` string, `chardet`'s
#: accelerator as a top-level extension, `nbformat`'s schema as a data file beside `__file__`.
BUNDLED_IMPORTS = ('cmath', 'ipykernel_launcher', 'dhrishti', 'chardet', 'nbformat', 'vishalakshi', 'litert_lm')

@pytest.mark.slow
def test_the_bundle_can_import_what_its_features_need():
    """Every other check here asserts a name is on a list. This one asks the bundle's own interpreter,
    which is the only thing that knows whether a module is reachable once it is inside a zip."""
    app = ROOT/'dist'/'Leela.app'
    if not app.is_dir(): pytest.skip('dist/Leela.app is not built')
    python = app/'Contents'/'MacOS'/'python'
    if not python.exists(): pytest.skip('the bundle ships no interpreter helper')
    src = 'import ' + ', '.join(BUNDLED_IMPORTS)
    env = {'PYTHONHOME': str(app/'Contents'/'Resources'),
           'PYTHONPATH': ':'.join([str(app/'Contents'/'Resources'/'lib'/'python313.zip'),
                                   str(app/'Contents'/'Resources'/'lib'/'python3.13'),
                                   str(app/'Contents'/'Resources'/'lib'/'python3.13'/'lib-dynload')])}
    r = subprocess.run([str(python), '-c', src], capture_output=True, text=True, timeout=180, env=env)
    assert r.returncode == 0, f'the bundle cannot import what it ships:\n{r.stderr.strip()[-1500:]}'


@pytest.mark.slow
def test_the_bundle_ships_no_binary_nothing_can_reach():
    """`claude_agent_sdk` looks for its bundled CLI beside its own `__file__`, which is inside
    `python313.zip`, so `.exists()` is false however the app is started. It was 93 MB of a 205 MB
    zip, and Leela reaches the real `claude` on PATH regardless."""
    import zipfile
    app = ROOT/'dist'/'Leela.app'
    if not app.is_dir(): pytest.skip('dist/Leela.app is not built')
    z = first(sorted((app/'Contents'/'Resources'/'lib').glob('python3*.zip')))
    if not z: pytest.skip('the bundle keeps no zip')
    with zipfile.ZipFile(z) as f: names = f.namelist()
    assert any(n.startswith('claude_agent_sdk/') for n in names), 'the SDK itself is still wanted'
    assert not [n for n in names if n.startswith('claude_agent_sdk/_bundled/')], \
        'the post-build step stopped stripping the unreachable binary'


@pytest.mark.slow
def test_the_browser_driver_is_a_file_the_app_can_execute():
    """`playwright` and `patchright` drive a browser by *running* `driver/node`, and a file inside
    `python313.zip` cannot be run, so fossick's browser fetching failed in the packaged app and
    nowhere else. Both are grafted onto disk, and the two identical Node binaries share one copy."""
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
