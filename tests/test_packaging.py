"The desktop build definitions, checked without building anything."

from __future__ import annotations

import importlib.util, subprocess, sys
from pathlib import Path

import pytest

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
    doc, = mac.PLIST['CFBundleDocumentTypes']
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
    """
    import urllib.request
    from leela.desktop import wait_for_http

    env = {**__import__('os').environ, 'LEELA_HEADLESS_SMOKE': '1', 'LEELA_WINDOW_SIZE': '900x600'}
    proc = subprocess.Popen([str(APP), str(tmp_path)], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        port = _port_from(proc)
        assert port, 'the app never reported a port'
        assert wait_for_http(f'http://127.0.0.1:{port}/', timeout=90)
        body = urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=20).read().decode()
        assert 'lee-ide' in body
    finally:
        proc.terminate()
        try: proc.wait(timeout=20)
        except subprocess.TimeoutExpired: proc.kill()

def _port_from(proc, tries=400):
    "Read the `leela  http://127.0.0.1:PORT` line the server prints on startup."
    import re
    for _ in range(tries):
        line = proc.stdout.readline()
        if not line: return None
        if (m := re.search(r'127\.0\.0\.1:(\d+)', line)): return int(m.group(1))
    return None

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
