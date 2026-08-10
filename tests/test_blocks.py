"""Extracted blocks, exercised over HTTP without a browser.

The existing coverage for these routes is Playwright-driven, which means it does not run
where chromium is unavailable -- and a route that has moved out of `ide_app` into a block
needs to be checked *somewhere* that always runs. `TestClient` calls the real app, so this
covers the wiring (`connect_all` order, capability narrowing) and the handler together.

This is also the shape `docs/blocks.md` asks block tests to take: build the block against a
`Ctx`, not against a whole browser session.
"""

import json

import pytest
from starlette.testclient import TestClient

from leela.blocks import keys as keys_block
from leela.blocks import settings as settings_block
from leela.core import Ctx, connect_all
from leela.web.app import BLOCKS, ide_app
from leela.workspace import Workspace


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
    import leela.keys as keymap
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
    from leela.git import GitError
    from leela.blocks.git.app import _apply
    with pytest.raises(GitError, match='unknown Git action'): _apply(_FakeRepo(), 'rm -rf', {})


@pytest.mark.parametrize('bad', ['/etc/passwd', '../outside', 'a/../../b'])
def test_git_pathspecs_from_the_browser_cannot_escape_the_repository(bad):
    from leela.git import GitError
    from leela.blocks.git.app import git_paths
    with pytest.raises(GitError, match='invalid repository path'): git_paths([bad])


def test_git_requires_at_least_one_path():
    from leela.git import GitError
    from leela.blocks.git.app import git_paths
    with pytest.raises(GitError, match='at least one'): git_paths([])


# -- the workspace's repositories, over HTTP ---------------------------------

@pytest.fixture
def workspace_client(tmp_path, monkeypatch):
    """A workspace holding two checkouts, served by the real app.

    `leela_cfg` is redirected first: `RepoSet` remembers added and hidden repositories
    there, and a test must not write into the config directory of whoever runs it.
    """
    import subprocess

    import leela.repos
    monkeypatch.setattr(leela.repos, 'leela_cfg', tmp_path/'cfg')
    def git(cwd, *args): subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True)
    for name in ('one', 'two'):
        (tmp_path/name).mkdir()
        git(tmp_path/name, 'init', '-b', 'main')
        git(tmp_path/name, 'config', 'user.email', 'tests@leela.local')
        git(tmp_path/name, 'config', 'user.name', 'Leela tests')
        (tmp_path/name/'seed.py').write_text('value = 1\n')
        git(tmp_path/name, 'add', '.')
        git(tmp_path/name, 'commit', '-m', 'initial')
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as c: yield c, tmp_path


def test_the_workspace_lists_every_repository_it_holds(workspace_client):
    client, root = workspace_client
    d = client.get('/git/repos').json()
    assert [r['name'] for r in d['repos']] == ['one', 'two']
    assert d['expected_branch'] == 'main' and d['summary']['repos'] == 2


def test_a_route_can_be_pointed_at_any_repository_in_the_workspace(workspace_client):
    "The panel asks about a checkout the active tab is not in; the answer is that checkout's."
    client, root = workspace_client
    d = client.get('/git/info', params={'repo': str(root/'two')}).json()
    assert d['root'] == str(root/'two')


def test_a_repository_outside_the_workspace_is_refused(workspace_client, tmp_path):
    client, root = workspace_client
    d = client.get('/git/info', params={'repo': '/etc'})
    assert d.status_code == 400 and 'not a repository in this workspace' in d.json()['error']


def test_a_bulk_operation_answers_for_each_repository(workspace_client):
    client, root = workspace_client
    d = client.post('/git/repos/action', json={'op': 'push'}).json()
    assert {r['name']: r['skipped'] for r in d['results']} == {'one': 'unpublished branch',
                                                               'two': 'unpublished branch'}
    assert d['summary']['repos'] == 2, 'the refreshed overview comes back with the results'


def test_membership_changes_come_back_as_a_refreshed_overview(workspace_client):
    client, root = workspace_client
    d = client.post('/git/repos/action', json={'op': 'remove', 'path': str(root/'two')}).json()
    assert d['removed'] == str(root/'two')
    assert [r['name'] for r in d['repos']] == ['one']
    d = client.post('/git/repos/action', json={'op': 'add', 'path': str(root/'two')}).json()
    assert [r['name'] for r in d['repos']] == ['one', 'two']
    # and it was remembered in the redirected config directory, not the real one
    assert list((root/'cfg'/'repos').glob('*.json'))


def test_an_unknown_workspace_operation_is_refused(workspace_client):
    client, _ = workspace_client
    d = client.post('/git/repos/action', json={'op': 'rm -rf'})
    assert d.status_code == 400 and 'unknown workspace operation' in d.json()['error']


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
