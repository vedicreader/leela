"The native Learn work must be in the frozen apps. Static: nothing is built."

from __future__ import annotations

import ast, importlib.util, plistlib, sys, tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT/'leela'
sys.path.insert(0, str(ROOT/'tools'))
import build_ide_js
from leela.blocks.learn import surfaces

def load(rel):
    spec = importlib.util.spec_from_file_location(f'pkg_{Path(rel).parent.name}', ROOT/rel)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

@pytest.fixture(scope='module')
def mac(): return load('packaging/macos/setup.py')

@pytest.fixture(scope='module')
def win(): return load('packaging/windows/setup.py')

WHEEL = tomllib.loads((ROOT/'pyproject.toml').read_text())['tool']['hatch']['build']['targets']['wheel']

def in_wheel(p):
    "Whether the wheel carries `p`: not under an exclude pattern, or forced in."
    rel = str(Path(p).resolve().relative_to(ROOT))
    if rel in WHEEL.get('force-include', {}): return True
    return not any(Path(rel).match(x) or rel.startswith(x + '/') for x in WHEEL['exclude'])

NEW_BUNDLED = ['blocks/learn/walk.js', 'blocks/learn/agentlink.js', 'blocks/learn/pane.js', 'blocks/learn/review.js', 'blocks/nb/scrub.js', 'blocks/nb/tracelens.js',
               'blocks/nb/bridge.js', 'blocks/vars/trace.js', 'blocks/modes/mode.js']
PATH_RUN = ['scrubworker.py', 'scrubwire.py', 'scrub.py', 'scrubrun.py']

def test_every_new_module_is_in_a_bundle_and_the_bundles_are_current():
    "A wheel carries no block module, only the bundles: a module no bundle names never reaches the app."
    named = {str(p.relative_to(PKG)) for p in build_ide_js.modules()}
    for m in NEW_BUNDLED:
        assert (PKG/m).is_file(), m
        assert m in named, f'{m} is in no bundle'
    assert not build_ide_js.missing() and not build_ide_js.orphans()
    build_ide_js.build(check=True)

def test_every_file_a_learn_page_loads_exists_and_reaches_the_wheel():
    "`/learn/abh-asset` finds each name in Leela's `learn/` folder or Abhyasa's: the wheel drops `blocks/*/*.js`, so a served module must be forced in."
    abh = Path(importlib.util.find_spec('abhyasa').origin).parent
    for name in sorted(surfaces.known()):
        p = surfaces.asset(name)
        assert p, f'{name} is named by a surface and found nowhere'
        if PKG in p.parents: assert in_wheel(p), f'{name} is in the tree and not in the wheel'
        else: assert abh in p.parents, f'{name} is in neither Leela nor Abhyasa'
    for f in ('abh.css', 'home.css', 'learn-cell.css', 'learn-graph.css', 'learn-talk.css'): assert in_wheel(PKG/'blocks'/'learn'/f), f

def test_the_wheel_forces_in_exactly_the_served_modules():
    forced = set(WHEEL['force-include'])
    assert forced == {f'leela/{m}' for m in build_ide_js.SERVED}
    assert all(WHEEL['force-include'][k] == k for k in forced)

def test_the_wheel_and_the_old_app_carry_the_static_bundles():
    "The thin app installs the wheel, the py2app app copies `leela/static`; both need every rebuilt bundle."
    from leela.core.web import IDE_BUNDLES
    for b in (*IDE_BUNDLES, 'lee-pane.js', 'lee-slides.js', 'lee-ide.css'): assert in_wheel(PKG/'static'/b), b

@pytest.mark.parametrize('which', ['mac', 'win'])
def test_the_frozen_app_copies_leela_and_the_learn_packages_whole(which, request):
    "Whole, so the scrub worker's `.py` files exist on disk and abhyasa's blocks, demos and assets are not left in a zip."
    for n in ('leela', 'abhyasa', 'rupaka', 'dhrishti', 'kunda'): assert n in request.getfixturevalue(which).PACKAGES, n

def test_the_scrub_worker_is_a_script_that_stands_alone():
    "`scrubrun` starts `scrubworker.py` by path on the notebook's Python, which loads `scrub` and `scrubwire` by path, so none may import Leela."
    for f in PATH_RUN[:3]:
        p = PKG/'blocks'/'nb'/f
        assert p.is_file(), f
        for n in ast.walk(ast.parse(p.read_text())):
            if isinstance(n, ast.ImportFrom): assert n.level == 0 and not (n.module or '').startswith('leela'), f'{f} imports {n.module}'
            if isinstance(n, ast.Import): assert not any(a.name.startswith('leela') for a in n.names), f
    assert (PKG/'blocks'/'nb'/'scrubrun.py').is_file()
    for f in PATH_RUN: assert in_wheel(PKG/'blocks'/'nb'/f), f

def test_the_scrub_worker_never_runs_on_the_apps_own_interpreter_alone():
    "In a py2app bundle `sys.executable` is the app and cannot run a script; the route asks the workspace for the tab's own Python first."
    src = (PKG/'blocks'/'nb'/'app.py').read_text()
    assert 'ws.user_python(' in src and 'except Exception: return sys.executable' in src

def test_lazy_imports_of_the_learn_libraries_resolve():
    "A static freezer misses an import made in a function; these are the ones Leela makes by name, so a rename in a library fails here."
    seen = set()
    for p in PKG.rglob('*.py'):
        for n in ast.walk(ast.parse(p.read_text())):
            if isinstance(n, ast.ImportFrom) and n.level == 0 and (n.module or '').split('.')[0] in ('abhyasa', 'rupaka'):
                seen.add(n.module)
                for a in n.names:
                    sub = f'{n.module}.{a.name}'
                    try:
                        if importlib.util.find_spec(sub): seen.add(sub)
                    except ModuleNotFoundError: pass
    assert 'abhyasa.agent_tools' in seen and 'abhyasa.contract' in seen and 'rupaka.board' in seen
    for m in sorted(seen): assert importlib.util.find_spec(m) is not None, m
    from abhyasa.blocks import NAMES
    for n in NAMES: assert importlib.util.find_spec(f'abhyasa.blocks.{n}') is not None, n

def test_abhyasa_data_the_pages_read_is_in_the_package():
    "The package folder holds the whole wheel (`packages = [\"abhyasa\"]`), so a file must be under it."
    root = Path(importlib.util.find_spec('abhyasa').origin).parent
    for f in ('core/vendor/d3.min.js', 'core/stage.js', 'core/grip.js', 'core/base.css', 'core/pane.css', 'core/edit.css', 'core/stage.css'): assert (root/f).is_file(), f
    assert list((root/'core'/'fonts').iterdir()) and list((root/'blocks').glob('*/*.css'))

@pytest.mark.parametrize('which', ['mac', 'win'])
def test_the_local_speech_stack_is_not_bundled_and_says_so(which, request):
    "`mlx_audio` comes with `leela[local]`; the frozen app leaves it out and the page shows the plain install message."
    mod = request.getfixturevalue(which)
    if which == 'mac': assert 'mlx_audio' in mod.HEAVY and 'mlx_audio' in mod.EXCLUDES
    assert 'mlx_audio' not in mod.PACKAGES
    assert 'Install leela[local]' in (PKG/'blocks'/'learn'/'speech.py').read_text()

def test_the_microphone_is_allowed_in_the_old_app_and_the_thin_app(mac):
    ents = plistlib.loads((ROOT/'packaging'/'macos'/'entitlements.plist').read_bytes())
    assert ents['com.apple.security.device.audio-input'] is True
    assert ents['com.apple.security.cs.allow-unsigned-executable-memory'] is True
    assert ents['com.apple.security.cs.disable-library-validation'] is True and len(ents) == 3
    assert 'dictate' in mac.PLIST['NSMicrophoneUsageDescription']
    rel = (ROOT/'tools'/'build_release.py').read_text()
    assert "ROOT/'packaging'/'macos'/'entitlements.plist'" in rel and 'kavacha.sign(app, identity, ENTITLEMENTS' in rel
    from kavacha.thin import Thin
    t = Thin.load(ROOT)
    assert t.entitlements == {'com.apple.security.device.audio-input': True}
    assert t.info_plist()['NSMicrophoneUsageDescription'] == mac.PLIST['NSMicrophoneUsageDescription']
