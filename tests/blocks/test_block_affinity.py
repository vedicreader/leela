"""A block's client module should talk to its own block's routes.

This is the measurement that found `editor/gutter.js` holding the git panel's state, the
notebook's cell code filed under the editor, and `search/similar.js` calling no search route at
all. It is a heuristic, so `PURE_DOM` names the modules that legitimately make few or no server
calls, and `SHARED` maps route prefixes onto the block that serves them.
"""

from __future__ import annotations
import collections, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
import build_ide_js as builder                                              # noqa: E402

#: route prefix -> the block whose `app.py` registers it
SHARED = {
    'run': 'runs', 'dev': 'runs', 'envs': 'runs', 'runs': 'runs',
    'nb': 'nb', 'editor': 'editor', 'file': 'editor', 'markdown': 'editor',
    'tab': 'tabs', 'tabs': 'tabs', 'kernel': 'runtime', 'runtime': 'runtime',
    'exec': 'runtime', 'path': 'runtime', 'code': 'search', 'search': 'search',
    'complete': 'search', 'clusters': 'search', 'lsp': 'lsp', 'fs': 'fs', 'files': 'fs',
    'agent': 'agent', 'git': 'git', 'cwd': 'git', 'vault': 'vault', 'clip': 'vault',
    'memory': 'memory', 'research': 'research', 'term': 'term', 'browser': 'browser',
    'workflows': 'workflows', 'releases': 'pipelines', 'deploys': 'pipelines',
    'infra': 'pipelines', 'pipeline': 'pipelines', 'drive': 'drive', 'settings': 'settings',
    'keys': 'keys', 'vars': 'vars', 'refactor': 'refactor', 'replace': 'refactor',
    'workspace': 'workspace', 'project': 'workspace', 'debug': 'debug', 'stack': 'stack',
    'packages': 'stack', 'history': 'refactor', 'jobs': 'vault', 'screen': 'keys',
    'release': 'pipelines', 'backups': 'settings',
    'leestatic': None, 'home': None, 'diff': None, 'lint': None,
}

#: a panel one block owns over another block's data, the way `git/panel.js` is a view over git
CROSS_BLOCK_VIEWS = {'blocks/agent/memory.js': 'the agent panel\'s workbench over the vault'}

#: modules that render or manipulate the DOM and are not expected to call their own routes
PURE_DOM = {'cells.js', 'gutter.js', 'conflictpanes.js', 'conflictfiles.js', 'terminal.js',
            'keymap.js', 'boot.js', 'core.js', 'focus.js', 'overlays.js', 'actions.js',
            'views.js', 'state.js', 'palette.js', 'split.js', 'tabs.js', 'mount.js',
            'markdown.js', 'media.js', 'panel.js', 'blame.js', 'builder.js', 'projects.js', 'find.js',
            'diffs.js', 'motion.js', 'prompt.js', 'exec.js', 'runfile.js', 'reload.js'}

def owners(text):
    "block -> how many route calls this text makes to that block."
    got = collections.Counter()
    for pref in re.findall(r"['\"`]/([a-z0-9_-]+)/", text):
        blk = SHARED.get(pref, pref)
        if blk: got[blk] += 1
    return got

def test_every_route_prefix_the_client_calls_maps_to_a_known_block():
    "An unmapped prefix means the table below has gone stale, not that the client is wrong."
    from leela.blocks import NAMES
    unknown = set()
    for p in builder.modules():
        for pref in re.findall(r"['\"`]/([a-z0-9_-]+)/", p.read_text()):
            blk = SHARED.get(pref, pref)
            if blk and blk not in NAMES: unknown.add(pref)
    assert unknown == set(), f'route prefixes with no block: {sorted(unknown)}'

def test_a_blocks_client_module_talks_mostly_to_its_own_routes():
    wrong = []
    for p in builder.modules():
        rel = str(p.relative_to(builder.PKG))
        if 'blocks' not in str(p) or p.name in PURE_DOM or rel in CROSS_BLOCK_VIEWS: continue
        blk = p.parent.name
        got = owners(p.read_text())
        mine, others = got.get(blk, 0), sum(v for k, v in got.items() if k != blk)
        if others > mine:
            top = ', '.join(f'{k}({v})' for k, v in got.most_common(3) if k != blk)
            wrong.append(f'{blk}/{p.name}: own={mine} but {top}')
    assert wrong == [], 'client modules filed under the wrong block:\n  ' + '\n  '.join(wrong)

def test_every_keymap_action_has_a_dispatch_entry():
    """A named command with no `ACTIONS` entry is a menu row and a chord that do nothing.
    `leeAct` answers 'no handler for x' at the status line, which is easy to miss.
    """
    import ast as _ast
    from leela.core.keys import KEYS
    src = next(p for p in builder.modules() if p.name == 'actions.js').read_text()
    lines = src.split('\n')
    start = next(i for i, l in enumerate(lines) if l.startswith('const ACTIONS = {'))
    end = next(i for i, l in enumerate(lines) if i > start and l.startswith('};'))
    entries = set(re.findall(r'^\s+([A-Za-z_$][\w$]*)\s*:', '\n'.join(lines[start:end + 1]), re.M))
    entries |= set(re.findall(r"ACTIONS\['([\w]+)'\s*\+", src))          # the tab_N family
    for p2 in builder.modules():                                     # and the later assignments
        t = p2.read_text()
        entries |= set(re.findall(r'ACTIONS\.(\w+)\s*=', t))
        entries |= set(re.findall(r"ACTIONS\['(\w+)'\]\s*=", t))
    dynamic = {'tab'}
    missing = sorted(a for a in {k.action for k in KEYS} if a not in entries
                     and not any(a.startswith(d) for d in dynamic))
    assert missing == [], f'named commands with no dispatch entry: {missing}'
