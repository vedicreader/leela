#!/usr/bin/env python
"""Concatenate the client's modules into the bundles `leela/app.py` serves.

The modules live with the feature they belong to: `leela/blocks/<block>/*.js` beside that block's
Python, and the shared vocabulary in `leela/static/js/`. `LAYERS` is their load order, and the only
place it is written down. The bundles are generated and committed, so install has no build step.
`--check` fails when a bundle and its modules have drifted.
"""
from __future__ import annotations
import sys
from collections import defaultdict
from fastcore.all import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from jsdecls import declared
from leela.core.web import IDE_BUNDLES

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT/'leela'
OUTDIR = PKG/'static'

#: bundle -> its modules, in load order. Three script tags share one lexical scope and run in
#: document order: `lee-core.js` declares `lee`, `$` and `esc` for every later module. Splitting
#: further is safe as long as nothing a bundle evaluates at load time names a function a later
#: bundle declares. See `test_ide_bundle.py`.
LAYERS = {
    'lee-core.js': [
        'static/js/core.js', 'blocks/keys/keymap.js', 'static/js/actions.js',
        'blocks/editor/markdown.js', 'blocks/editor/tabs.js', 'blocks/learn/walk.js', 'blocks/editor/mount.js',
        'blocks/nb/cells.js', 'blocks/nb/scrub.js', 'blocks/nb/bridge.js', 'blocks/nb/lesson.js', 'blocks/nb/exercise.js', 'blocks/nb/widgets.js', 'blocks/nb/motion.js', 'blocks/nb/prompt.js', 'blocks/nb/slides.js', 'blocks/nb/present.js',
        'blocks/runs/runfile.js', 'blocks/runtime/kernel.js', 'blocks/keys/bind.js',
        'static/js/focus.js', 'blocks/nb/diffs.js', 'blocks/runtime/exec.js',
        'blocks/vars/vars.js', 'blocks/vars/trace.js'
    ],
    'lee-agent.js': [
        'blocks/agent/panel.js', 'blocks/agent/budgets.js', 'blocks/agent/memory.js',
        'blocks/agent/live.js', 'blocks/agent/approvals.js', 'blocks/agent/steer.js',
        'blocks/agent/media.js', 'blocks/agent/reload.js'
    ],
    'lee-ide.js': [
        'blocks/term/terminal.js', 'blocks/learn/pane.js', 'blocks/modes/mode.js', 'blocks/runs/logs.js', 'blocks/term/dock.js', 'blocks/settings/prefs.js', 'blocks/settings/update.js',
        'blocks/git/cwd.js', 'blocks/editor/gutter.js', 'blocks/git/state.js',
        'blocks/git/views.js', 'blocks/workflows/workflows.js', 'blocks/workflows/builder.js',
        'blocks/pipelines/releases.js', 'blocks/pipelines/deploys.js', 'blocks/drive/drive.js',
        'blocks/git/panel.js', 'blocks/git/branchmenu.js', 'blocks/git/conflictpanes.js',
        'blocks/git/blame.js', 'blocks/research/research.js', 'static/js/overlays.js',
        'blocks/search/search.js', 'blocks/search/find.js', 'blocks/search/similar.js', 'blocks/runs/config.js',
        'blocks/keys/palette.js', 'blocks/fs/files.js', 'blocks/fs/office.js', 'blocks/editor/split.js',
        'static/js/boot.js', 'blocks/refactor/refactor.js', 'blocks/refactor/move.js',
        'blocks/git/conflictfiles.js', 'blocks/git/conflictcells.js',
        'blocks/vault/home.js', 'blocks/vault/doc.js', 'blocks/vault/review.js', 'blocks/git/branchbar.js', 'blocks/browser/browser.js',
        'blocks/workspace/projects.js', 'blocks/learn/review.js', 'blocks/learn/agentlink.js'
    ],
}

#: copy -> the one module it is, for a page outside the IDE that loads that module alone. The wheel ships no block module.
#: modules a Learn surface loads by itself, so no bundle names them.
SERVED = {'blocks/learn/learn-demo.js', 'blocks/learn/home.js', 'blocks/learn/dictate.js', 'blocks/learn/walkpage.js', 'blocks/learn/learn-talk.js', 'blocks/learn/learn-cell.js'}

ALONE = {'lee-pane.js': 'blocks/learn/pane.js', 'lee-slides.js': 'blocks/nb/slides.js'}

assert tuple(LAYERS) == IDE_BUNDLES, f'{tuple(LAYERS)} is not what `core.web` serves: {IDE_BUNDLES}'

def modules(bundle=None):
    "Every module path, or one bundle's, in load order."
    names = LAYERS[bundle] if bundle else [m for ms in LAYERS.values() for m in ms]
    return [PKG/m for m in names]

def _text(p):
    "One module's source, newline-terminated: without it its last line fuses into the next module."
    t = p.read_text()
    return t if t.endswith('\n') else t + '\n'

def bundle(name):
    "One bundle's concatenated text."
    return ''.join(_text(p) for p in modules(name))

def missing():
    "Modules the order names but the tree does not have."
    return [p for p in modules() if not p.is_file()]

def orphans():
    "Modules the tree has but the order does not name, which would silently never load."
    named = {p.resolve() for p in modules()}
    found = {p.resolve() for p in (*(PKG/'static'/'js').glob('*.js'), *PKG.glob('blocks/*/*.js'))}
    return sorted(found - named - {(PKG/m).resolve() for m in SERVED})

#: pages and the modules they share one lexical scope with: the IDE loads all three bundles, and a Learn surface may load the served modules beside them.
PAGES = {'the IDE page': lambda: [*modules(), *(PKG/m for m in sorted(SERVED))], 'lee-pane.js': lambda: [PKG/ALONE['lee-pane.js']], 'lee-slides.js': lambda: [PKG/ALONE['lee-slides.js']]}

def dupes():
    "Top-level names declared twice on one page: one line each, with both files and lines."
    out = []
    for page, mods in PAGES.items():
        seen = defaultdict(list)
        for p in mods():
            for n, l in declared(p.read_text()): seen[n].append(f'{p.relative_to(PKG)}:{l}')
        out += [f'`{n}` is declared twice on {page}: {" and ".join(v)}' for n, v in seen.items() if len(v) > 1]
    return out

def build(check=False):
    if bad := dupes(): raise SystemExit('duplicate top-level declaration (the page would fail to load):\n' + '\n'.join(bad))
    if gone := missing(): raise SystemExit(f'named but absent: {[p.name for p in gone]}')
    if extra := orphans(): raise SystemExit(f'present but unnamed: {[str(p.relative_to(PKG)) for p in extra]}')
    plan = [(name, bundle(name), OUTDIR/name) for name in LAYERS] + [(name, _text(PKG/m), OUTDIR/name) for name, m in ALONE.items()]
    for name, text, out in plan:
        if check:
            if not out.is_file(): raise SystemExit(f'{name} has never been built')
            if out.read_text() != text: raise SystemExit(f'{name} is stale; run python tools/build_ide_js.py')
        else: out.write_text(text)
    n = len(modules())
    verb = 'match' if check else 'built from'
    print(f'{len(LAYERS)} bundle(s) and {len(ALONE)} copy {verb} {n} modules: ' +
          ', '.join(f'{k} ({len(v)})' for k, v in LAYERS.items()))

if __name__ == '__main__': build(check='--check' in sys.argv)
