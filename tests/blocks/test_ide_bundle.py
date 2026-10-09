"""What the client's bundles must hold true, whatever the modules say."""

from __future__ import annotations
import re, sys
from collections import Counter
from pathlib import Path
from fastcore.all import L

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
import build_ide_js as builder                                              # noqa: E402

DECL = re.compile(r'^(?:async\s+)?(?:function|const|let|class)\s+([A-Za-z_$][\w$]*)', re.M)

def test_every_bundle_is_its_modules_concatenated():
    for name in builder.LAYERS:
        assert (builder.OUTDIR/name).read_text() == builder.bundle(name), \
            f'{name} is stale; run python tools/build_ide_js.py'

def test_the_order_is_complete_and_names_nothing_that_is_not_there():
    "A module added to a block but left out of `LAYERS` would silently never load."
    assert builder.missing() == []
    assert builder.orphans() == []


def test_no_bundle_reads_a_later_bundles_declaration_at_load_time():
    """The failure this prevents is not graceful: the throw aborts the rest of that bundle, so every `let` after it stays in its temporal dead zone and the shell paints but does nothing."""
    mods = builder.modules()
    at, bundle_of = {}, {}
    for i, (name, names) in enumerate(builder.LAYERS.items()):
        for n in names: bundle_of[str(builder.PKG/n)] = i
    for i, p in enumerate(mods):
        for m in re.finditer(r'^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)', p.read_text(), re.M):
            at.setdefault(m.group(1), i)
    bad = []
    for i, p in enumerate(mods):
        for ln, line in enumerate(p.read_text().split('\n'), 1):
            m = (re.match(r'^\s+[A-Za-z_$][\w$]*\s*:\s*([A-Za-z_$][\w$]*),?\s*$', line)
                 or re.match(r'^ACTIONS(?:\.\w+|\[[^\]]+\])\s*=\s*([A-Za-z_$][\w$]*)\s*;?\s*$', line))
            if not m: continue
            j = at.get(m.group(1))
            if j is not None and bundle_of[str(mods[j])] > bundle_of[str(p)]:
                bad.append(f'{p.name}:{ln} reads {m.group(1)!r} from a later bundle')
    assert bad == [], bad


def test_no_name_is_declared_in_two_modules():
    "One shared scope, so the second declaration wins and the first silently stops existing."
    decls = L(builder.modules()).map(lambda p: set(DECL.findall(p.read_text())))
    dupes = sorted(n for n, c in Counter(n for s in decls for n in s).items() if c > 1)
    assert dupes == [], f'declared in more than one module: {dupes}'


def test_the_built_editor_bundle_matches_its_source():
    """`lee-cm6.js` is committed, so a change to `frontend/editor.js` that was never built is a lie."""
    bundle = (ROOT/'leela'/'vendor'/'lee-cm6.js').read_text()
    assert 'ResizeObserver' in bundle, 'rebuild with frontend/node_modules/@esbuild/*/bin/esbuild'
    from tests.assets import cm_exports
    assert {'undo', 'redo'} <= cm_exports()


