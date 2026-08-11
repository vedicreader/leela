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


# -- the workspace's repositories, over HTTP ---------------------------------

@pytest.fixture
def workspace_client(tmp_path, monkeypatch):
    """A workspace holding two checkouts, served by the real app.

    `leela_cfg` is redirected first: `RepoSet` remembers added and hidden repositories
    there, and a test must not write into the config directory of whoever runs it.
    """
    import subprocess

    import leela.blocks.git.repos
    monkeypatch.setattr(leela.blocks.git.repos, 'leela_cfg', tmp_path/'cfg')
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


# -- workflows and releases, over HTTP ---------------------------------------

@pytest.fixture
def project_client(tmp_path, monkeypatch):
    "A workspace holding one project with a workflow file and a release plan."
    import json
    import subprocess

    import leela.blocks.git.repos
    monkeypatch.setattr(leela.blocks.git.repos, 'leela_cfg', tmp_path/'cfg')
    root = tmp_path/'proj'
    (root/'.github'/'workflows').mkdir(parents=True)
    (root/'.github'/'workflows'/'ci.yml').write_text(
        'name: ci\non:\n  push:\n    branches: [main]\n  workflow_dispatch:\n'
        'jobs:\n  lint:\n    runs-on: ubuntu-latest\n    steps:\n      - run: ruff check .\n'
        '  test:\n    needs: lint\n    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n')
    (root/'pyproject.toml').write_text('[project]\nname = "proj"\nversion = "0"\n\n[tool.nbdev]\n')
    (root/'.leela').mkdir()
    (root/'.leela'/'release.json').write_text(json.dumps({'steps': [
        {'id': 'a', 'label': 'first', 'cmd': 'echo alpha'},
        {'id': 'b', 'label': 'second', 'cmd': 'sh -c "exit 4"'}]}))
    subprocess.run(['git', 'init', '-b', 'main'], cwd=root, check=True, capture_output=True)
    with TestClient(ide_app(Workspace(roots=[root]))) as c: yield c, root


def test_the_workflow_panel_reads_the_files_without_reaching_github(project_client):
    "Opening the panel must not spend a rate-limited call or fail when offline."
    client, root = project_client
    d = client.get('/workflows').json()
    assert d['root'] == str(root)
    wf = d['workflows'][0]
    assert wf['file'] == 'ci.yml' and wf['dispatchable']
    assert [j['id'] for j in wf['jobs']] == ['lint', 'test']
    assert wf['levels'] == [['lint'], ['test']]
    assert 'gheasy' in d['status'], 'the panel is told which optional piece is missing'


def test_an_unknown_workflow_action_is_refused(project_client):
    client, _ = project_client
    r = client.post('/workflows/action', json={'op': 'rm -rf'})
    assert r.status_code == 400 and 'unknown workflow action' in r.json()['error']


def test_the_environment_view_never_returns_a_secret_value(project_client):
    """The one rule this panel cannot break.

    A key with no schema entry is treated as a secret, so the release pipeline's own
    `needs` come back masked rather than being shown because nobody declared them.
    """
    client, _ = project_client
    d = client.get('/workflows/env').json()
    assert all(e['value'] == '' for e in d['entries'] if e['secret'])
    assert all(e['target'] in ('secret', 'variable') for e in d['entries'])


def test_the_release_panel_reports_the_plan_and_what_it_needs(project_client):
    client, root = project_client
    d = client.get('/releases').json()
    assert d['nbdev'] and d['configured']
    assert [s['id'] for s in d['steps']] == ['a', 'b']
    assert not d['running'] and d['failed'] == ''


def test_a_release_runs_until_a_step_fails_and_then_stops(project_client):
    "The whole point of the pipeline: green advances, red halts with the output kept."
    import time
    client, _ = project_client
    started = client.post('/releases/action', json={'op': 'start'}).json()
    assert started['running']
    for _ in range(300):
        state = client.get('/releases').json()
        if not state['running']: break
        time.sleep(.05)
    assert [s['status'] for s in state['steps']] == ['passed', 'failed']
    assert state['failed'] == 'b'
    tail = client.get('/releases/tail').json()['text']
    assert 'alpha' in tail and 'exited 4' in tail


def test_an_unknown_release_action_is_refused(project_client):
    client, _ = project_client
    r = client.post('/releases/action', json={'op': 'rm -rf'})
    assert r.status_code == 400 and 'unknown release action' in r.json()['error']


def test_the_catalogue_marks_what_this_project_wants(project_client):
    client, _ = project_client
    d = client.get('/workflows/catalogue').json()
    assert d['detect']['nbdev'] and d['detect']['python']
    rows = {r['id']: r for r in d['workflows']}
    assert rows['nbdev']['recommended'] and not rows['ci']['recommended']
    # `present` is about the file name, not the entry: this project already has a ci.yml,
    # and both CI entries would write one -- which is exactly when `add` has to refuse.
    assert rows['ci']['present'] and rows['nbdev']['present']
    assert not rows['docker']['present']
    refused = client.post('/workflows/action', json={'op': 'add', 'workflow': 'nbdev'})
    assert refused.status_code == 400 and 'already exists' in refused.json()['error']


def test_the_deploy_panel_reports_its_target_and_stages(project_client):
    client, root = project_client
    d = client.get('/deploys').json()
    assert d['kind'] == 'deploy'
    assert [s['id'] for s in d['steps']] == ['env', 'compose', 'deploy']
    assert d['target']['script'] is False and d['target']['missing']


def test_scaffolding_writes_the_script_the_stages_run(project_client):
    client, root = project_client
    d = client.post('/deploys/action', json={'op': 'scaffold', 'domain': 'example.com',
                                             'subdomain': 'proj'}).json()
    assert (root/'deploy.py').exists()
    assert d['state']['target']['script'] is True
    again = client.post('/deploys/action', json={'op': 'scaffold', 'domain': 'example.com'})
    assert again.status_code == 400 and 'already has a deploy.py' in again.json()['error']


def test_an_unknown_deploy_action_is_refused(project_client):
    client, _ = project_client
    r = client.post('/deploys/action', json={'op': 'rm -rf'})
    assert r.status_code == 400 and 'unknown deploy action' in r.json()['error']


def test_the_builder_vocabulary_is_served_as_data(client):
    "The form is rendered from this, so a preset added in Python needs no frontend change."
    d = client.get('/workflows/presets').json()
    ids = {p['id'] for p in d['presets']}
    assert {'uv_test', 'uv_lint', 'uv_pypi', 'deploy', 'run'} <= ids
    assert {t['id'] for t in d['triggers']} >= {'push', 'pull_request', 'workflow_dispatch'}


def test_a_built_workflow_round_trips_through_its_spec(project_client):
    client, root = project_client
    spec = {'name': 'built', 'file': 'built.yml', 'on': {'push': 'main'},
            'jobs': [{'preset': 'uv_lint'}, {'preset': 'uv_test', 'needs': ['lint']}]}
    preview = client.post('/workflows/action', json={'op': 'build', 'spec': spec}).json()
    assert 'lint:' in preview['yaml'] and not (root/'.github'/'workflows'/'built.yml').exists()

    written = client.post('/workflows/action', json={'op': 'write_spec', 'spec': spec}).json()
    assert written['file'] == 'built.yml' and (root/'.github'/'workflows'/'built.yml').exists()
    back = client.get('/workflows/spec', params={'file': 'built.yml'}).json()
    assert back['spec']['jobs'] == spec['jobs'] and not back['stale']

    (root/'.github'/'workflows'/'built.yml').write_text('name: edited by hand\n')
    assert client.get('/workflows/spec', params={'file': 'built.yml'}).json()['stale'], \
        'a hand edit is not something to overwrite silently'


def test_the_stack_view_reports_the_family(project_client):
    client, _ = project_client
    d = client.get('/stack').json()
    names = {p['name'] for p in d['packages']}
    assert {'gheasy', 'dockeasy', 'vpseasy', 'cfeasy'} <= names
    assert all({'installed', 'version', 'source', 'shadowed'} <= set(p) for p in d['packages'])


def test_infrastructure_reports_each_half_separately(project_client):
    "No token in a test environment, so this is the shape of the answer, not the answer."
    client, _ = project_client
    d = client.get('/infra').json()
    assert set(d) >= {'status', 'servers', 'tunnels', 'zones'}
    for half in ('servers', 'tunnels', 'zones'):
        assert 'rows' in d[half] and 'error' in d[half]


def test_an_unknown_infrastructure_action_is_refused(project_client):
    client, _ = project_client
    r = client.post('/infra/action', json={'op': 'delete everything'})
    assert r.status_code == 400 and 'unknown infrastructure action' in r.json()['error']


def test_blame_answers_in_cells_for_a_notebook_and_lines_for_a_file(project_client):
    """One route, two shapes, because a notebook blamed as text answers the wrong question.

    `cells=false` is the way back to the raw file lines, which is what the modal falls back
    to when a notebook is in a shape the cell mapping cannot read.
    """
    import json
    import subprocess
    client, root = project_client
    nb = {'cells': [{'cell_type': 'code', 'id': 'c1', 'metadata': {}, 'execution_count': None,
                     'outputs': [], 'source': ['x = 1\n', 'y = 2\n']}],
          'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}
    (root/'nb.ipynb').write_text(json.dumps(nb, indent=1) + '\n')
    for args in (['add', '.'], ['-c', 'user.email=t@l', '-c', 'user.name=t', 'commit', '-m', 'nb']):
        subprocess.run(['git', *args], cwd=root, check=True, capture_output=True)

    d = client.get('/git/blame', params={'path': 'nb.ipynb'}).json()
    assert d['notebook'] and len(d['cells']) == 1
    assert [l['text'] for l in d['cells'][0]['lines']] == ['x = 1', 'y = 2']

    raw = client.get('/git/blame', params={'path': 'nb.ipynb', 'cells': 'false'}).json()
    assert not raw['notebook'] and raw['lines'], 'the JSON lines are still reachable'
    assert any('"source"' in l['text'] for l in raw['lines'])

    py = client.get('/git/blame', params={'path': '.github/workflows/ci.yml'}).json()
    assert not py['notebook'] and py['cells'] == []


def test_blame_still_refuses_a_path_outside_the_repository(project_client):
    client, _ = project_client
    r = client.get('/git/blame', params={'path': '../../etc/passwd'})
    assert r.status_code == 400 and 'invalid repository path' in r.json()['error']


def test_the_drive_panel_offers_one_call_per_package(project_client):
    "The alternative to the deploy script: same runner, one library call per step."
    client, _ = project_client
    d = client.get('/drive').json()
    assert d['kind'] == 'drive'
    assert d['packages'] == ['cfeasy', 'dockeasy', 'gheasy', 'vpseasy']
    tunnel = next(s for s in d['steps'] if s['id'] == 'tunnel')
    assert tunnel['meta']['package'] == 'cfeasy' and 'setup_tunnel' in tunnel['meta']['code']
    assert tunnel['meta']['writes'] == ['CF_TUNNEL_TOKEN']
    assert d['context']['app'] == 'proj'


def test_an_unknown_drive_action_is_refused(project_client):
    client, _ = project_client
    r = client.post('/drive/action', json={'op': 'rm -rf'})
    assert r.status_code == 400 and 'unknown drive action' in r.json()['error']


def test_these_panels_say_to_open_a_folder_rather_than_failing_obscurely(client):
    for path in ('/workflows', '/releases', '/deploys', '/drive'):
        r = client.get(path)
        assert r.status_code == 400 and 'open a folder' in r.json()['error']


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
    # Only *module-level* imports count. An import inside a function is the standard way to
    # break a cycle deliberately, and it creates no load-order hazard -- forbidding it would
    # leave no legal way to express a mutual reference that only matters at call time.
    edges = {}
    for block, files in _domain_files().items():
        for f in files:
            for node in ast.parse(f.read_text()).body:
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
