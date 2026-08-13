"The served `lee-ide.js` is generated: it must equal its `static/js/` modules."

import sys

from fastcore.all import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT/'tools'))

import build_ide_js as builder  # noqa: E402


def test_every_module_is_listed_in_the_manifest():
    "A module absent from the manifest would silently vanish from the served bundle."
    listed = {p.name for p in builder.modules()}
    assert listed == {p.name for p in builder.JS.glob('*.js')}


def test_the_committed_bundle_matches_its_modules():
    "Editing lee-ide.js directly is the drift this catches; edit the module and rebuild."
    assert builder.OUT.read_text() == builder.bundle(), 'run python tools/build_ide_js.py'


def test_the_bundle_defines_the_entry_points_the_server_renders():
    "app.py renders onclick=leeAct(...) and friends; the split must keep them all present."
    js = builder.OUT.read_text()
    for fn in ('function leeAct', 'function leeLeft', 'function leeRight', 'function leePane'): assert fn in js, fn
