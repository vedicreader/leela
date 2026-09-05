#!/usr/bin/env python
"""Concatenate the client's modules and block stylesheets into what `leela/app.py` serves.

The modules live with the feature they belong to: `leela/blocks/<block>/*.js` beside that block's
Python, and the shared vocabulary in `leela/static/js/`. `LAYERS` is their load order, and the only
place it is written down. The bundles are generated and committed, so install has no build step.
`--check` fails when a bundle and its modules have drifted.
"""
from __future__ import annotations
import sys
from fastcore.all import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from leela.core.web import IDE_BUNDLES, IDE_SHEETS

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
        'blocks/editor/markdown.js', 'blocks/editor/tabs.js', 'blocks/editor/mount.js',
        'blocks/nb/cells.js', 'blocks/nb/motion.js', 'blocks/nb/prompt.js',
        'blocks/runs/runfile.js', 'blocks/runtime/kernel.js', 'blocks/keys/bind.js',
        'static/js/focus.js', 'blocks/nb/diffs.js', 'blocks/runtime/exec.js',
        'blocks/vars/vars.js'
    ],
    'lee-agent.js': [
        'blocks/agent/host.js', 'blocks/agent/panel.js', 'blocks/agent/budgets.js', 'blocks/agent/memory.js',
        'blocks/agent/live.js', 'blocks/agent/approvals.js', 'blocks/agent/steer.js',
        'blocks/agent/media.js'
    ],
    'lee-ide.js': [
        'blocks/tabs/agentreload.js', 'blocks/term/terminal.js', 'blocks/runs/logs.js', 'blocks/term/dock.js', 'blocks/settings/prefs.js',
        'blocks/git/cwd.js', 'blocks/editor/gutter.js', 'blocks/git/state.js',
        'blocks/git/views.js', 'blocks/workflows/workflows.js', 'blocks/workflows/builder.js',
        'blocks/pipelines/releases.js', 'blocks/pipelines/deploys.js', 'blocks/drive/drive.js',
        'blocks/git/panel.js', 'blocks/git/branchmenu.js', 'blocks/git/conflictpanes.js',
        'blocks/git/blame.js', 'blocks/research/research.js', 'static/js/overlays.js',
        'blocks/search/search.js', 'blocks/search/find.js', 'blocks/search/similar.js', 'blocks/runs/config.js',
        'blocks/keys/palette.js', 'blocks/fs/files.js', 'blocks/editor/split.js',
        'static/js/boot.js', 'blocks/refactor/refactor.js', 'blocks/refactor/move.js',
        'blocks/git/conflictfiles.js', 'blocks/git/conflictcells.js',
        'blocks/vault/reader.js', 'blocks/git/branchbar.js', 'blocks/browser/browser.js',
        'blocks/workspace/projects.js'
    ],
}

#: served stylesheet -> the block-authored sheets it is built from, in order. A block's CSS lives
#: with the block, the way its JS does; `leela/static` is where the built copy is served from. The
#: agent's bridge comes first: it declares the `--val-*` tokens the rules after it read.
SHEETS = {'lee-agent.css': ['blocks/agent/tokens.lee.css', 'blocks/agent/agent.css']}

assert tuple(LAYERS) == IDE_BUNDLES, f'{tuple(LAYERS)} is not what `core.web` serves: {IDE_BUNDLES}'
assert tuple(SHEETS) == IDE_SHEETS, f'{tuple(SHEETS)} is not what `core.web` serves: {IDE_SHEETS}'

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

def sheets(name=None):
    "Every block-authored stylesheet path, or one served sheet's, in order."
    names = SHEETS[name] if name else [s for ss in SHEETS.values() for s in ss]
    return [PKG/s for s in names]

def missing():
    "Modules and sheets the order names but the tree does not have."
    return [p for p in modules() + sheets() if not p.is_file()]

def orphans():
    "Modules the tree has but the order does not name, which would silently never load."
    named = {p.resolve() for p in modules()}
    named |= {p.resolve() for p in sheets()}
    found = {p.resolve() for p in (*(PKG/'static'/'js').glob('*.js'), *PKG.glob('blocks/*/*.js'),
                                   *PKG.glob('blocks/*/*.css'))}
    return sorted(found - named)

def build(check=False):
    if gone := missing(): raise SystemExit(f'named but absent: {[p.name for p in gone]}')
    if extra := orphans(): raise SystemExit(f'present but unnamed: {[str(p.relative_to(PKG)) for p in extra]}')
    for name in tuple(LAYERS) + tuple(SHEETS):
        text = bundle(name) if name in LAYERS else ''.join(_text(p) for p in sheets(name))
        out = OUTDIR/name
        if check:
            if not out.is_file(): raise SystemExit(f'{name} has never been built')
            if out.read_text() != text: raise SystemExit(f'{name} is stale; run python tools/build_ide_js.py')
        else: out.write_text(text)
    n, verb = len(modules()), 'match' if check else 'built from'
    print(f'{len(LAYERS)} bundle(s) {verb} {n} modules: ' +
          ', '.join(f'{k} ({len(v)})' for k, v in LAYERS.items()) +
          f'; {len(SHEETS)} sheet(s) from {len(sheets())}')

if __name__ == '__main__': build(check='--check' in sys.argv)
