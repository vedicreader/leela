"The desktop build definitions, checked without building anything."

from __future__ import annotations

import importlib.util, json, subprocess, sys
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
    mark = ROOT/'packaging'/'assets'/'leela-mark.png'
    assert mark.is_file() and mark.stat().st_size > 1000, 'the artwork itself is the source'
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
    "`Leela.icns` is built, not committed, and the workflow installs the extras and nothing else."
    import tomllib
    extras = tomllib.load(open(ROOT/'pyproject.toml', 'rb'))['project']['optional-dependencies']
    for which in ('macapp', 'windows'):
        assert any('pillow' in d.lower() for d in extras[which]), f'{which} cannot build icons'

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
    """The favicon ships in the wheel, which has no build step, so it is committed like the JS
    bundles rather than drawn at install. Committed and generated means it can drift."""
    pytest.importorskip('PIL')
    import tools.build_icons as icons
    assert icons.FAVICON.read_text() == icons.favicon(), \
        'leela/static/favicon.svg is stale; run python tools/build_icons.py'

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

def test_the_icon_generator_is_reproducible(tmp_path, monkeypatch):
    "The committed PNG must be the one the generator makes, or the two silently diverge."
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
        body = urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=30).read().decode()
        assert 'lee-ide' in body, f'served a page without the IDE bundle:\n{body[:500]}'
        # A page proves the server imports. It does not prove the *kernel* does, and it did not:
        # pygments loads a style by importing its name, none were bundled, `import IPython` died in
        # the kernel process, and every cell failed on a gateway read timeout instead.
        req = urllib.request.Request(f'http://127.0.0.1:{port}/exec',
                                     data=json.dumps({'code': 'import IPython; print(6*7)'}).encode(),
                                     headers={'Content-Type': 'application/json'})
        ran = urllib.request.urlopen(req, timeout=240).read().decode()
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
