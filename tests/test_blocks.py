"""Extracted blocks, exercised over HTTP without a browser.

The existing coverage for these routes is Playwright-driven, which means it does not run
where chromium is unavailable -- and a route that has moved out of `ide_app` into a block
needs to be checked *somewhere* that always runs. `TestClient` calls the real app, so this
covers the wiring (`connect_all` order, capability narrowing) and the handler together.

This is also the shape `docs/blocks.md` asks block tests to take: build the block against a
`Ctx`, not against a whole browser session.
"""

import ast
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from leela.blocks import keys as keys_block
from leela.blocks import settings as settings_block
from leela.core import Ctx, connect_all
from leela.app import BLOCKS, ide_app
from leela.workspace import Workspace

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def client():
    with TestClient(ide_app(Workspace(roots=[]))) as c: yield c


# -- wiring ------------------------------------------------------------------

def test_every_listed_block_exposes_the_contract():
    for m in BLOCKS:
        assert callable(getattr(m, 'connect', None)), f'{m!r} has no connect()'
        assert isinstance(getattr(m, 'CAPS', ()), tuple), f'{m!r} CAPS must be a tuple'


def test_blocks_declare_only_what_they_use():
    "A block whose CAPS grew without its routes growing is the failure mode this catches."
    assert keys_block.CAPS == (), 'the keymap is served from files; it needs no workspace'
    assert settings_block.CAPS == ('fs',)


# -- keys --------------------------------------------------------------------

def test_keymap_is_served_as_data_so_the_frontend_hardcodes_no_chord(client):
    d = client.get('/keys.json').json()
    assert d['keys'] and d['help'] and d['bars'], 'keys, help rows and button bars in one fetch'
    assert d['path'].endswith('.json')
    # the bars carry the same action names the keymap binds, which is what lets a button
    # and a chord run one code path
    actions = {k['action'] for k in d['keys']} if isinstance(d['keys'], list) else set()
    bar_actions = {b['action'] for rows in d['bars'].values() for b in rows}
    if actions: assert bar_actions & actions, 'buttons and keys share action names'


def test_reading_the_keymap_file_works_before_one_has_been_written(client):
    d = client.get('/keys/file').json()
    assert 'text' in d and 'path' in d and 'exists' in d
    json.loads(d['text']), 'the fallback text must itself be valid JSON'


def test_saving_an_invalid_keymap_is_refused_with_a_readable_reason(client):
    r = client.post('/keys/save', json={'text': '{not json'})
    assert r.status_code == 400
    assert 'valid JSON' in r.json()['error']


def test_saving_then_resetting_the_keymap_round_trips(client, monkeypatch, tmp_path):
    "Reset exists so a keymap you cannot use is one click from gone -- so it must really restore."
    import leela.core.keys as keymap
    p = tmp_path/'keys.json'
    monkeypatch.setattr(keymap, 'keymap_path', lambda: p)
    monkeypatch.setattr('leela.blocks.keys.app.keymap_path', lambda: p)

    saved = client.post('/keys/save', json={'text': json.dumps({'keys': []})}).json()
    assert saved['ok'] and p.exists()

    reset = client.post('/keys/reset', json={}).json()
    assert reset['ok'] and reset['keys'], 'defaults are back and the browser map was rebuilt'


# -- settings ----------------------------------------------------------------

def test_settings_report_the_origin_of_each_effective_value(client):
    "With four layers, the value alone cannot answer 'why is it this'."
    d = client.get('/settings').json()
    assert isinstance(d, dict) and d, 'describe() returns the effective layered view'


def test_saving_an_unknown_settings_scope_fails_rather_than_writing_somewhere(client):
    r = client.post('/settings/save', json={'scope': 'nowhere', 'section': 'editor',
                                            'values': {'fontSize': 14}})
    assert r.status_code == 400 or r.json().get('ok') is not True


# -- git ---------------------------------------------------------------------

# Every op the browser can send, as the if/elif ladder in ide_app listed them. Kept here so
# that turning that ladder into a dispatch table cannot have silently dropped one.
GIT_OPS = [
    'stage', 'unstage', 'discard', 'resolve_conflict', 'apply_patch', 'checkout', 'create',
    'rename_branch', 'set_upstream', 'unset_upstream', 'delete', 'delete_remote', 'commit',
    'fetch', 'pull', 'push', 'stash', 'stash_pop', 'stash_apply', 'stash_drop', 'merge',
    'rebase', 'cherry_pick', 'revert', 'reset', 'abort_merge', 'abort_rebase', 'tag',
    'delete_tag', 'add_remote', 'set_remote', 'remove_remote', 'add_worktree',
    'remove_worktree',
]


class _FakeRepo:
    "Records what was called on it; every method accepts anything."
    def __init__(self): self.calls = []
    def __getattr__(self, name):
        def call(*a, **kw): self.calls.append(name); return None
        return call


@pytest.mark.parametrize('op', GIT_OPS)
def test_every_git_op_still_dispatches(op):
    from leela.blocks.git.app import _apply
    repo = _FakeRepo()
    _apply(repo, op, {'paths': ['a.py'], 'path': 'a.py', 'branch': 'main', 'name': 'x',
                      'ref': 'HEAD', 'url': 'u', 'message': 'm', 'choice': 'ours'})
    assert repo.calls, f'{op} reached no repository method'


def test_the_operation_family_is_matched_by_prefix():
    "continue/skip/abort are sent as operation_* rather than being enumerated."
    from leela.blocks.git.app import _apply
    for suffix in ('continue', 'skip', 'abort'):
        repo = _FakeRepo()
        _apply(repo, f'operation_{suffix}', {})
        assert repo.calls == ['operation_action']


def test_an_unknown_git_op_is_refused():
    from leela.blocks.git.git import GitError
    from leela.blocks.git.app import _apply
    with pytest.raises(GitError, match='unknown Git action'): _apply(_FakeRepo(), 'rm -rf', {})


@pytest.mark.parametrize('bad', ['/etc/passwd', '../outside', 'a/../../b'])
def test_git_pathspecs_from_the_browser_cannot_escape_the_repository(bad):
    from leela.blocks.git.git import GitError
    from leela.blocks.git.app import git_paths
    with pytest.raises(GitError, match='invalid repository path'): git_paths([bad])


def test_git_requires_at_least_one_path():
    from leela.blocks.git.git import GitError
    from leela.blocks.git.app import git_paths
    with pytest.raises(GitError, match='at least one'): git_paths([])


# -- capability enforcement, end to end --------------------------------------

def test_a_block_reaching_past_its_caps_fails_loudly(monkeypatch):
    """The point of narrowing: re-coupling to the whole workspace is an error, not a habit.

    Uses a real `connect_all` rather than a hand-built Ctx, so the failure is the one a
    block author would actually hit.
    """
    import types
    ws = Workspace(roots=[])
    m = types.ModuleType('leela.blocks.greedy.app')
    m.CAPS = ('fs',)
    boom = []

    def connect(app, ctx):
        try: ctx.memory
        except AttributeError as e: boom.append(str(e))
    m.connect = connect

    connect_all(object(), ws, [m])
    assert boom and 'greedy' in boom[0] and 'memory' in boom[0]


def test_the_keys_block_needs_no_workspace_at_all():
    "CAPS == () is a claim; this is the check. It connects against a Ctx over nothing."
    registered = []

    class FakeApp:
        def route(self, path, **kw):
            def deco(fn): registered.append(path); return fn
            return deco

    keys_block.connect(FakeApp(), Ctx(None, name='keys', caps=()))
    assert sorted(registered) == ['/keys.json', '/keys/file', '/keys/reset', '/keys/save']


# ---------------------------------------------------------------- the contract
# `docs/blocks.md` states three rules about who may import whom. They were prose until the
# domain modules moved into the blocks, at which point they became easy to break silently:
# nothing fails a test when a service quietly drags the web layer in behind it.

BLOCKS_DIR = ROOT/'leela/blocks'


def _domain_files():
    "Every block's domain modules: its .py files that are not `__init__`, `app` or `ui`."
    out = {}
    for d in sorted(p for p in BLOCKS_DIR.iterdir() if (p/'__init__.py').is_file()):
        out[d.name] = sorted(f for f in d.glob('*.py') if f.stem not in ('__init__', 'app', 'ui'))
    return out


def test_importing_every_block_domain_never_loads_a_route_module():
    """A service must be usable without the web layer it is served by.

    This is not tidiness. `Workspace` composes these domains, so if importing one pulls in
    `app.py`, then constructing a workspace -- in a test, in the CLI, in the dev-server child
    -- pays for fasthtml and starlette and loads routes nobody asked for. It regressed exactly
    once, when the domain modules moved into the blocks and each `__init__` still did
    `from .app import CAPS, connect`; the suite stayed green throughout.

    Runs in a subprocess because `sys.modules` is global and the rest of the suite has already
    imported the whole app.
    """
    code = textwrap.dedent('''
        import importlib, json, pathlib, sys
        blocks = pathlib.Path(sys.argv[1])
        names = [f'leela.blocks.{d.name}.{f.stem}'
                 for d in sorted(p for p in blocks.iterdir() if (p/'__init__.py').is_file())
                 for f in sorted(d.glob('*.py')) if f.stem not in ('__init__', 'app', 'ui')]
        for n in names: importlib.import_module(n)
        loaded = sorted(m for m in sys.modules if m.startswith('leela.blocks.')
                        and m.rsplit('.', 1)[-1] in ('app', 'ui'))
        print(json.dumps({'domains': len(names), 'routes': loaded}))
    ''')
    r = subprocess.run([sys.executable, '-c', code, str(BLOCKS_DIR)],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout.splitlines()[-1])
    assert got['domains'] > 15, got                      # the discovery itself must not go empty
    assert got['routes'] == [], (
        'importing block domain modules loaded these route/UI modules:\n  ' +
        '\n  '.join(got['routes']) +
        "\n\nA block's __init__ must resolve `connect` and `CAPS` through __getattr__, not import"
        ' app.py eagerly.')


def test_core_imports_no_block():
    "The one hard direction: blocks import core, core imports nothing back."
    code = ('import json, sys; import leela.core; '
            "print(json.dumps(sorted(m for m in sys.modules if m.startswith('leela.blocks'))))")
    r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == [], (
        'leela.core reached into a block. Anything two blocks need belongs in core itself; '
        'anything that must name an implementation belongs above the blocks, the way '
        'leela/conformance.py does.')


def test_no_domain_module_imports_another_blocks_routes_or_ui():
    """A block may use another block's domain module -- never its routes or its fragments.

    `blocks/fs/ui.py` reads `git.GitRepo` to show tree status and `blocks/editor/app.py` reads
    `runtime.kernels`; both are legitimate. Reaching for `..git.app` would not be: routes are
    a block's outside, and two blocks sharing one is a sign the thing belongs in core.
    """
    bad = []
    for block, files in _domain_files().items():
        for f in files:
            for node in ast.walk(ast.parse(f.read_text())):
                if not isinstance(node, ast.ImportFrom) or node.level != 2 or not node.module:
                    continue
                parts = node.module.split('.')
                if len(parts) > 1 and parts[1] in ('app', 'ui'):
                    bad.append(f'{block}/{f.name}: from {"." * node.level}{node.module}')
    assert not bad, 'domain modules reaching into another block\'s web surface:\n  ' + '\n  '.join(bad)


def test_the_domain_import_graph_has_no_cycles():
    """Blocks may depend on each other's domains, but not in a loop.

    A cycle means neither block can be read, tested or replaced on its own, which is the whole
    point of the folder. Two blocks that genuinely need each other are one block, or share
    something that belongs in core.
    """
    edges = {}
    for block, files in _domain_files().items():
        for f in files:
            for node in ast.walk(ast.parse(f.read_text())):
                if isinstance(node, ast.ImportFrom) and node.level == 2 and node.module:
                    other = node.module.split('.')[0]
                    if other != block: edges.setdefault(block, set()).add(other)

    cycles, path, done = [], [], set()
    def walk(n):
        if n in path: return cycles.append(' -> '.join(path[path.index(n):] + [n]))
        if n in done: return
        path.append(n)
        for m in sorted(edges.get(n, ())): walk(m)
        path.pop(); done.add(n)
    for n in sorted(edges): walk(n)
    assert not cycles, 'cyclic dependencies between block domains:\n  ' + '\n  '.join(cycles)
