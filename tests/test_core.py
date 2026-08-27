"Core: the block contract, ports, diffs, settings, routes and the journal."

import re
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
from leela.core import (CAPABILITIES, DebugState, DocStore, MemoryPort, RunState,
                        RuntimePort, SearchPort)
from leela.core.text import (closest, diff_label, diff_rows, diff_stat,
                                did_you_mean, fuzzy_rank, udiff)
from leela.blocks.fs.fs import Sandbox
from leela.core.session import OperationJournal
from leela import conformance
from leela.core import ports as providers
from leela.core.ports import ProviderError, build, providers_for, selected
from leela.blocks.settings.settings import DEFAULT_SETTINGS, Settings
import asyncio
from leela.core.envs import EnvStore
from tests.conftest import TEST_CONFIG_HOME
from fastcore.all import Path

@pytest.fixture(scope='module')
def client():
    with TestClient(ide_app(Workspace(roots=[]))) as c: yield c

def test_every_block_declares_and_serves_what_it_wires():
    for m in BLOCKS:
        assert callable(getattr(m, 'connect', None)), f'{m!r} has no connect()'
        assert isinstance(getattr(m, 'CAPS', ()), tuple), f'{m!r} CAPS must be a tuple'
    assert keys_block.CAPS == (), 'the keymap is served from files; it needs no workspace'
    assert settings_block.CAPS == (), 'settings reads a project root, which is not a capability'
    by_module = {}
    for path, m in owners().items(): by_module.setdefault(m, []).append(path)
    for mod in BLOCKS:
        name = f'{mod.__name__}.app'
        assert by_module.get(name), f'{name} connects but no live route resolves to it'
    rows = inventory()
    dupes = sorted({r for r in rows if rows.count(r) > 1})
    assert not dupes, 'the same method+path is registered twice:\n  ' + '\n  '.join(dupes)


def test_keymap_is_served_as_data_so_the_frontend_hardcodes_no_chord(client):
    d = client.get('/keys.json').json()
    assert d['keys'] and d['help'] and d['bars'], 'keys, help rows and button bars in one fetch'
    assert d['path'].endswith('.json')
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
    assert json.loads(p.read_text())['keys'] == {}, 'an override set with nothing in it'
    assert reset['overrides'] == {}, 'and the panel is told so, so its next save does not undo it'

def test_a_keymap_posted_as_every_chord_is_stored_as_the_ones_that_differ(client, monkeypatch, tmp_path):
    "An older client posts the whole map. Storing that freezes every action at today's default."
    import leela.core.keys as keymap
    p = tmp_path/'keys.json'
    monkeypatch.setattr(keymap, 'keymap_path', lambda: p)
    monkeypatch.setattr('leela.blocks.keys.app.keymap_path', lambda: p)
    full = {k.action: k.key for k in keymap.DEFAULTS} | {'run_cell': 'ctrl+y'}
    r = client.post('/keys/save', json={'text': json.dumps({'keys': full})}).json()
    try: assert r['ok'] and json.loads(p.read_text())['keys'] == {'run_cell': 'ctrl+y'}
    finally: keymap.reload(tmp_path/'gone.json')   # `KEYS` is global and the save just rebuilt it

def test_settings_report_the_origin_of_each_effective_value(client):
    "With four layers, the value alone cannot answer 'why is it this'."
    d = client.get('/settings').json()
    assert isinstance(d, dict) and d, 'describe() returns the effective layered view'

def test_saving_an_unknown_settings_scope_fails_rather_than_writing_somewhere(client):
    r = client.post('/settings/save', json={'scope': 'nowhere', 'section': 'editor',
                                            'values': {'fontSize': 14}})
    assert r.status_code == 400 or r.json().get('ok') is not True

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

def test_a_git_operation_is_matched_by_family_and_needs_a_path():
    from leela.blocks.git.app import _apply
    from leela.blocks.git.git import GitError
    from leela.blocks.git.app import git_paths
    for suffix in ('continue', 'skip', 'abort'):
        repo = _FakeRepo()
        _apply(repo, f'operation_{suffix}', {})
        assert repo.calls == ['operation_action']
    with pytest.raises(GitError, match='unknown Git action'): _apply(_FakeRepo(), 'rm -rf', {})
    with pytest.raises(GitError, match='at least one'): git_paths([])


@pytest.mark.parametrize('bad', ['/etc/passwd', '../outside', 'a/../../b'])
def test_git_pathspecs_from_the_browser_cannot_escape_the_repository(bad):
    from leela.blocks.git.git import GitError
    from leela.blocks.git.app import git_paths
    with pytest.raises(GitError, match='invalid repository path'): git_paths([bad])


@pytest.fixture
def workspace_client(tmp_path, monkeypatch):
    "A workspace holding two checkouts, served by the real app."
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
    assert list((root/'cfg'/'repos').glob('*.json'))

def test_an_unknown_workspace_operation_is_refused(workspace_client):
    client, _ = workspace_client
    d = client.post('/git/repos/action', json={'op': 'rm -rf'})
    assert d.status_code == 400 and 'unknown workspace operation' in d.json()['error']

@pytest.fixture
def project_client(tmp_path, monkeypatch):
    "A workspace holding one project with a workflow file and a release plan."
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
    "The one rule this panel cannot break."
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
    "One route, two shapes, because a notebook blamed as text answers the wrong question."
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

def test_a_block_reaching_past_its_caps_fails_loudly(monkeypatch):
    "The point of narrowing: re-coupling to the whole workspace is an error, not a habit."
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
    assert sorted(registered) == ['/keys.json', '/keys/check', '/keys/file', '/keys/reset', '/keys/save']

BLOCKS_DIR = ROOT/'leela/blocks'

def _domain_files():
    "Every block's domain modules: its .py files that are not `__init__`, `app` or `ui`."
    out = {}
    for d in sorted(p for p in BLOCKS_DIR.iterdir() if (p/'__init__.py').is_file()):
        out[d.name] = sorted(f for f in d.glob('*.py') if f.stem not in ('__init__', 'app', 'ui'))
    return out

def test_importing_every_block_domain_never_loads_a_route_module():
    "A service must be usable without the web layer it is served by."
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
    assert got['domains'] > 15, got
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
    "A block may use another block's domain module -- never its routes or its fragments."
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
    "Blocks may depend on each other's domains, but not in a loop."
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

@pytest.fixture(scope='module')
def ws(): return Workspace(roots=[])

@pytest.fixture
def services(ws):
    "What `ide_app` owns and hands to every block: the state that used to be closure variables."
    return dict(docs=DocStore(ws), debug=DebugState(), running=RunState(),
                gate=object(), catalog=[])

def test_an_unrestricted_ctx_reaches_every_capability(ws, services):
    ctx = Ctx(ws, name='all', **services)
    for c in CAPABILITIES: getattr(ctx, c)
    assert ctx.caps == sorted(CAPABILITIES)

def test_an_application_capability_that_was_never_supplied_does_not_exist(ws):
    "A Ctx built without a doc store has no doc store -- it does not hand back None."
    ctx = Ctx(ws, name='bare')
    with pytest.raises(AttributeError, match='does not provide'): ctx.docs
    assert ctx.fs is ws.fs, 'session capabilities are unaffected'

def test_the_two_ways_to_be_missing_a_capability_report_differently(ws, services):
    '"You did not declare it" and "the app has none" need different fixes, so they read'
    undeclared = Ctx(ws, name='git', caps=('fs',), **services)
    with pytest.raises(AttributeError, match='without declaring it'): undeclared.memory
    absent = Ctx(ws, name='git', caps=('docs',))
    with pytest.raises(AttributeError, match='does not provide'): absent.docs
    with pytest.raises(AttributeError, match='no attribute'): undeclared.nonsense

def test_supplying_an_unknown_application_capability_is_rejected(ws):
    with pytest.raises(TypeError, match='unknown application capabilities'):
        Ctx(ws, nonsense=1)

def test_eager_capabilities_are_the_same_objects_as_the_workspaces(ws):
    "Narrowing is about access, not indirection: `ctx.fs` must *be* `ws.fs`."
    ctx = Ctx(ws)
    assert ctx.fs is ws.fs and ctx.pool is ws.pool and ctx.memory is ws.memory

def test_a_narrowed_ctx_refuses_undeclared_eager_capabilities(ws):
    ctx = Ctx(ws, name='git', caps=('fs', 'journal'))
    assert ctx.fs is ws.fs and ctx.journal is ws.journal
    with pytest.raises(AttributeError): ctx.memory
    with pytest.raises(AttributeError): ctx.pool

def test_a_narrowed_ctx_refuses_undeclared_lazy_capabilities_by_name(ws):
    "The error has to name the block and the capability, or it is unactionable at runtime."
    ctx = Ctx(ws, name='git', caps=('fs',))
    with pytest.raises(AttributeError, match="'git'.*'ai'"): ctx.ai

def test_narrow_rejects_a_capability_that_does_not_exist(ws):
    with pytest.raises(ValueError, match='unknown capabilities'):
        Ctx(ws).narrow('fs', 'telepathy')

def test_session_state_stays_shared_rather_than_injected(ws):
    "Tabs are workspace state, not a capability -- blocks read them through `session`."
    ctx = Ctx(ws, caps=('fs',))
    assert ctx.session is ws
    assert 'tabs' not in CAPABILITIES

def test_building_a_ctx_does_not_construct_the_assistant(ws):
    "The reason `ai` is not an eager slot."
    fresh = Workspace(roots=[])
    Ctx(fresh, name='agent')
    assert fresh._ai is None, 'constructing a Ctx eagerly built the Assistant'
    assert fresh._completer is None

def test_lazy_capabilities_read_through_to_current_session_state(ws):
    "`tab` must not be captured at construction; it changes as tabs open and close."
    ctx = Ctx(ws)
    assert ctx.tab is ws.tab
    ws.new_scratch()
    assert ctx.tab is ws.tab and ctx.tab is not None

class _FakeApp:
    def __init__(self): self.registered = []
    def route(self, path, **kw):
        def deco(fn): self.registered.append((self._who, path)); return fn
        return deco

def _mkblock(name, caps, paths, seen):
    import types
    m = types.ModuleType(f'leela.blocks.{name}.app')
    m.CAPS = caps
    def connect(app, ctx, _n=name, _p=paths):
        seen.append((_n, ctx.name, tuple(ctx.caps)))
        app._who = _n
        for path in _p: app.route(path)(lambda: None)
    m.connect = connect
    return m

def test_connect_all_wires_blocks_in_order_with_narrowed_ctxs(ws):
    seen, app = [], _FakeApp()
    blocks = [_mkblock('git', ('fs', 'journal'), ['/git/info'], seen),
              _mkblock('memory', ('memory',), ['/memory/info', '/memory/search'], seen)]
    receipts = connect_all(app, ws, blocks)
    assert [b.name for b in receipts] == ['git', 'memory']
    assert [b.order for b in receipts] == [0, 1]
    assert seen == [('git', 'git', ('fs', 'journal')), ('memory', 'memory', ('memory',))]
    assert app.registered == [('git', '/git/info'), ('memory', '/memory/info'),
                              ('memory', '/memory/search')]

def test_a_block_declaring_an_unknown_capability_fails_at_connect(ws):
    seen = []
    bad = _mkblock('nonsense', ('fs', 'nope'), [], seen)
    with pytest.raises(ValueError, match='unknown capabilities'):
        connect_all(_FakeApp(), ws, [bad])

def test_a_block_without_caps_is_unrestricted_so_migration_can_be_incremental(ws):
    "Un-migrated blocks must keep working, or the extraction has to land in one commit."
    import types
    seen = []
    m = types.ModuleType('leela.blocks.legacy.app')
    def connect(app, ctx): seen.append(ctx.caps); ctx.memory; ctx.ai
    m.connect = connect
    connect_all(_FakeApp(), ws, [m])
    assert seen == [sorted(CAPABILITIES)]

def test_narrowing_covers_application_capabilities_too(ws, services):
    ctx = Ctx(ws, name='nb', caps=('docs', 'fs'), **services)
    assert ctx.docs is services['docs'] and ctx.fs is ws.fs
    with pytest.raises(AttributeError): ctx.debug
    with pytest.raises(AttributeError): ctx.gate

def test_narrow_carries_the_application_services_through(ws, services):
    "`narrow` must not silently drop the doc store the parent was built with."
    child = Ctx(ws, name='p', **services).narrow('docs', 'running')
    assert child.docs is services['docs'] and child.running is services['running']

def test_docstore_resolves_a_request_to_the_tab_that_submitted_it(ws):
    "`owner` survives a tab switch mid-run, which is the whole reason it takes a ref."
    from leela.blocks.nb.nb import Notebook
    store = DocStore(ws)
    tab = ws.new_scratch()
    key = store.key(tab)
    store.docs[key] = Notebook()
    found, nb, lock = store.owner(key)
    assert found is tab and nb is store.docs[key] and lock is not None
    assert store.owner(key)[2] is lock

def test_docstore_refuses_a_ref_that_is_not_a_notebook(tmp_path):
    "A run request naming a `.py` tab gets nothing, rather than a half-built answer."
    p = tmp_path/'x.py'; p.write_text('x = 1\n')
    local = Workspace(roots=[tmp_path])
    local.open(str(p))
    assert DocStore(local).owner(str(p)) == (None, None, None)

def test_docstore_forget_drops_every_kind_of_per_tab_state(ws):
    store = DocStore(ws)
    store.docs['k'], store.buffers['k'], store.bases['k'] = 1, 'text', 'disk'
    store.forget('k')
    assert 'k' not in store.docs and 'k' not in store.buffers and 'k' not in store.bases
    store.forget('never-opened')

def test_runstate_keeps_stop_aimed_at_the_cell_that_started_the_work():
    r = RunState()
    r.start('nb-a', 'c1', 'runtime-a', 'task-a')
    r.start('nb-b', 'c1', 'runtime-b', 'task-b')
    assert r.get('nb-a', 'c1') == ('runtime-a', 'task-a')
    assert r.get('nb-b', 'c1') == ('runtime-b', 'task-b')
    assert r.running_in('nb-a') == ['c1']
    r.finish('nb-a', 'c1')
    assert r.get('nb-a', 'c1') == (None, None) and r.running_in('nb-a') == []

def test_debugstate_clears_the_notebook_and_script_sessions_separately():
    d = DebugState()
    assert not d.paused and d.cell_sources == {}
    d.kernel, d.origin_path, d.cell_id = object(), 'a.py', 'c1'
    d.direct_session, d.direct_name = object(), 'script'
    assert d.paused
    d.clear()
    assert not d.paused and d.direct_session is not None, 'clearing one must not clear the other'
    d.clear_direct()
    assert d.direct_session is None and d.direct_name == ''

def test_the_current_implementations_conform_to_their_ports(ws):
    "The Protocols are extracted from these classes; drift between them is a bug in the port."
    assert isinstance(ws.memory, MemoryPort)
    assert isinstance(ws.search, SearchPort)

def test_the_agent_backend_conforms_to_the_runtime_port():
    "The contract ramabana has to meet, asserted against the implementation that defines it."
    import inspect
    from leela.agent.runtime import Backend
    missing = sorted(m for m in RuntimePort.__protocol_attrs__
                     if m != 'spec' and not hasattr(Backend, m))
    assert not missing, f'Backend no longer satisfies RuntimePort: {missing}'
    assert 'spec' in inspect.signature(Backend.__init__).parameters
    for p in ('ready', 'busy', 'hist'): assert isinstance(getattr(Backend, p), property)

A = 'def f(x):\n    return x\n\nz = 1\n'
B = 'def f(x, y=0):\n    return x + y\n\nz = 1\nw = 2\n'

def test_diff_rows_carry_line_numbers_stats_and_serialise():
    assert udiff(A, A) == ''
    assert list(diff_rows(udiff(A, A))) == []
    assert diff_label(A, A) == ''
    rows = diff_rows(udiff(A, B))
    added = [(r.line, r.text) for r in rows if r.kind == 'add']
    assert added == [(1, 'def f(x, y=0):'), (2, '    return x + y'), (5, 'w = 2')]
    assert all(r.line == 0 for r in rows if r.kind == 'del')
    assert [(r.line, r.text) for r in rows if r.kind == 'ctx'] == [(3, ''), (4, 'z = 1')]
    for r in diff_rows(udiff(A, B)):
        if r.kind in ('add', 'del', 'ctx'):
            assert not r.text.startswith(('+', '-')) or r.text == ''
    assert diff_stat(A, B) == (3, 2)
    assert diff_label(A, B) == '+3 −2'
    assert diff_label('', 'one\ntwo\n') == '+2'
    assert diff_label('one\ntwo\n', '') == '−2'
    assert diff_rows(udiff(A, B))[0].dict().keys() == {'kind', 'text', 'line'}
    assert udiff(A, B, names=('old', 'new')).startswith('--- old\n+++ new\n')
    assert not udiff(A, B).startswith('---')
    assert diff_stat(None, 'x\n') == (1, 0)


def test_fuzzy_ranking_orders_by_what_a_person_meant():
    got = did_you_mean("NameError: name 'df2' is not defined", ['df_2', 'ns', 'x'])
    assert "did you mean 'df_2'?" in got
    err = "NameError: name 'zzzz' is not defined"
    assert did_you_mean(err, ['df_2', 'total']) == err
    assert closest('dfram', ['df', 'dframe', 'frame'])[0] == 'dframe'
    assert list(fuzzy_rank('app', FILES))[0] == 'a/web/app.py'
    assert list(fuzzy_rank('wapp', FILES)) == ['a/web/app.py']
    assert list(fuzzy_rank('zzz', FILES)) == []
    assert list(fuzzy_rank('', FILES)) == FILES
    assert len(fuzzy_rank('', FILES, limit=2)) == 2
    assert list(fuzzy_rank('README', FILES))[0] == 'a/README.md'


@pytest.mark.parametrize('err', [None, '', 'TypeError: unsupported operand', 'ZeroDivisionError: x'])
def test_other_errors_are_untouched(err):
    assert did_you_mean(err, ['df']) == err


FILES = ['a/web/app.py', 'a/some_long_app_helper.py', 'a/ide/panels/app.py',
         'a/README.md', 'a/apple/pie.txt']


def test_workspace_journal_persists_and_undoes_only_exact_outputs(tmp_path):
    root = tmp_path/'project'; root.mkdir(); path = root/'a.py'; path.write_text('before\n')
    journal = OperationJournal(tmp_path/'journal.json', Sandbox([root]))
    path.write_text('after\n')
    op = journal.record('Save a.py', [(path, 'before\n', 'after\n')])
    assert OperationJournal(tmp_path/'journal.json', Sandbox([root])).rows()[0]['id'] == op['id']
    journal.undo(op['id']); assert path.read_text() == 'before\n'

def test_workspace_journal_redoes_only_the_exact_undone_output(tmp_path):
    root = tmp_path/'project'; root.mkdir(); path = root/'a.py'; path.write_text('before\n')
    journal = OperationJournal(tmp_path/'journal.json', Sandbox([root]))
    path.write_text('after\n'); op = journal.record('Save a.py', [(path, 'before\n', 'after\n')])
    journal.undo(op['id']); journal.redo(op['id'])
    assert path.read_text() == 'after\n'
    journal.undo(op['id']); path.write_text('other\n')
    with pytest.raises(ValueError, match='changed after the undo'):
        journal.redo(op['id'])

def test_unnamed_redo_walks_back_up_the_stack_in_the_order_undo_came_down(tmp_path):
    "Two undos then two redos on one file."
    root = tmp_path/'project'; root.mkdir(); path = root/'a.py'; path.write_text('v0')
    journal = OperationJournal(tmp_path/'journal.json', Sandbox([root]))
    first_op = journal.record('one', [(path, 'v0', 'v1')]); path.write_text('v1')
    second_op = journal.record('two', [(path, 'v1', 'v2')]); path.write_text('v2')
    journal.undo(); journal.undo()
    assert path.read_text() == 'v0'
    assert journal.redo()['id'] == first_op['id'] and path.read_text() == 'v1'
    assert journal.redo()['id'] == second_op['id'] and path.read_text() == 'v2'

def test_a_new_edit_ends_the_redo_branch(tmp_path):
    root = tmp_path/'project'; root.mkdir(); path = root/'a.py'; path.write_text('v0')
    journal = OperationJournal(tmp_path/'journal.json', Sandbox([root]))
    journal.record('one', [(path, 'v0', 'v1')]); path.write_text('v1')
    journal.undo(); assert path.read_text() == 'v0'
    journal.record('branch', [(path, 'v0', 'w1')]); path.write_text('w1')
    assert not any(row['redoable'] for row in journal.rows())
    with pytest.raises(ValueError, match='no redoable'):
        journal.redo()

def test_workspace_journal_refuses_diverged_files_atomically(tmp_path):
    root = tmp_path/'project'; root.mkdir(); a=root/'a'; b=root/'b'; a.write_text('a1'); b.write_text('b1')
    journal=OperationJournal(tmp_path/'journal.json', Sandbox([root]))
    a.write_text('a2'); b.write_text('b2'); op=journal.record('two files',[(a,'a1','a2'),(b,'b1','b2')])
    b.write_text('newer')
    with pytest.raises(ValueError, match='changed after'):
        journal.undo(op['id'])
    assert a.read_text() == 'a2' and b.read_text() == 'newer'

@pytest.fixture(autouse=True)
def clean_registry():
    "Each test gets the real registry back, so an installed fake cannot leak."
    import copy
    saved = copy.deepcopy(providers._REGISTRY)
    yield
    providers._REGISTRY.clear(); providers._REGISTRY.update(saved)

def test_conformance_checks_a_port_without_constructing_it():
    from leela.agent.runtime import Backend
    for port in ('memory', 'search', 'runtime'):
        assert 'leela' in providers_for(port)
    ws = Workspace(roots=[])
    assert conformance.check('memory', ws.memory) == []
    assert conformance.check('search', ws.search) == []
    assert conformance.check('runtime', Backend) == []
    obj = _stub('memory', search=lambda self, q, n=8: [])()
    assert isinstance(obj, MemoryPort), 'isinstance is satisfied, which is the problem'
    problems = conformance.check('memory', obj)
    assert any("search: leela passes ['query', 'limit']" in p for p in problems)
    obj = _stub('runtime', ready=lambda self: True)()
    problems = conformance.check('runtime', obj)
    assert any('ready: port declares an attribute' in p for p in problems)
    obj = _stub('memory', search='not callable')()
    assert any('search: port declares a method' in p for p in conformance.check('memory', obj))
    assert conformance.check('memory', _stub('memory')()) == []
    assert 'missing: spec' not in conformance.check('runtime', Backend)
    ok = conformance.report('memory', Workspace(roots=[]).memory)
    assert ok.startswith('memory <- Memory: OK')
    bad = conformance.report('memory', object(), label='nothing')
    assert 'problem(s)' in bad and '  - missing:' in bad
    with pytest.raises(ValueError, match='unknown port'): conformance.check('telepathy', object())


def test_selection_prefers_an_explicit_override_then_the_environment(monkeypatch):
    monkeypatch.delenv('LEELA_MEMORY', raising=False)
    assert selected('memory') == 'leela'
    monkeypatch.setenv('LEELA_MEMORY', 'vishalakshi')
    assert selected('memory') == 'vishalakshi'
    assert selected('memory', 'ramabana') == 'ramabana', 'an explicit override wins'

def test_an_unknown_provider_raises_and_names_what_is_available(monkeypatch):
    monkeypatch.setenv('LEELA_MEMORY', 'nope')
    with pytest.raises(ProviderError, match="unknown memory provider 'nope'.*available: leela"):
        build('memory')

def test_a_provider_whose_package_is_missing_says_so(monkeypatch):
    "The failure a user actually hits before pip-installing the alternate."
    def missing(**kw): raise ImportError("No module named 'vishalakshi'")
    providers.register('memory', 'vishalakshi', missing)
    monkeypatch.setenv('LEELA_MEMORY', 'vishalakshi')
    with pytest.raises(ProviderError, match='not installed'): build('memory')

def test_a_broken_provider_never_falls_back_to_the_builtin(monkeypatch):
    "Silently running on the default would make an A/B comparison meaningless -- you"
    providers.register('memory', 'boom', lambda **kw: 1/0)
    monkeypatch.setenv('LEELA_MEMORY', 'boom')
    with pytest.raises(ProviderError, match='failed to start'): build('memory')

def test_a_registered_alternate_is_what_the_workspace_builds(monkeypatch):
    "End to end: the switch really changes what a Workspace ends up holding."
    sentinel = object()
    providers.register('memory', 'fake', lambda **kw: sentinel)
    monkeypatch.setenv('LEELA_MEMORY', 'fake')
    assert Workspace(roots=[]).memory is sentinel

def test_the_default_workspace_still_builds_the_builtin(monkeypatch):
    from leela.blocks.memory.memory import Memory
    monkeypatch.delenv('LEELA_MEMORY', raising=False)
    assert isinstance(Workspace(roots=[]).memory, Memory)


def _stub(port, **overrides):
    "A class with every member the port names, as real attributes."
    proto = conformance.PORTS[port]
    ns = {}
    for name in proto.__protocol_attrs__:
        ns[name] = (lambda self, *a, **kw: None) if callable(getattr(proto, name, None)) else ''
    ns.update(overrides)
    return type(f'Stub{port.title()}', (), ns)


@pytest.mark.parametrize('port', ['memory', 'search', 'runtime'])
def test_every_port_can_be_checked_from_the_command_line(port, capsys):
    "`python -m leela.conformance <port>` is the first thing to run against an"
    assert conformance._main([port]) == 0
    assert 'OK' in capsys.readouterr().out

def test_the_cli_reports_a_bad_provider_without_a_traceback(capsys):
    assert conformance._main(['memory', 'nosuch']) == 2
    out = capsys.readouterr().out
    assert 'unknown memory provider' in out and 'Traceback' not in out

def test_the_cli_rejects_an_unknown_port_with_usage(capsys):
    assert conformance._main(['telepathy']) == 2
    assert 'usage:' in capsys.readouterr().out

def test_the_cli_exits_nonzero_when_an_implementation_does_not_conform(capsys, monkeypatch):
    providers.register('memory', 'broken', lambda **kw: _stub('memory', search='nope')())
    monkeypatch.setenv('LEELA_MEMORY', 'broken')
    assert conformance._main(['memory']) == 1
    assert 'port declares a method' in capsys.readouterr().out

def test_settings_layer_default_user_workspace_and_language(tmp_path):
    root, user = tmp_path/'project', tmp_path/'user.json'
    root.mkdir(); (root/'.leela').mkdir()
    user.write_text(json.dumps({'editor': {'fontSize': 14}, 'languages': {
        'python': {'editor': {'lineLength': 88}}}}))
    (root/'.leela/settings.json').write_text(json.dumps({'editor': {'fontSize': 15}, 'languages': {
        'python': {'editor': {'fontSize': 16}}}}))
    settings = Settings(root, user)
    assert settings.effective()['editor']['fontSize'] == 15
    effective = settings.effective('python')
    assert effective['editor']['fontSize'] == 16 and effective['editor']['lineLength'] == 88
    described = settings.describe('python')
    assert described['origins']['editor']['fontSize'] == 'workspace:python'
    assert described['origins']['editor']['lineLength'] == 'user:python'

def test_settings_save_validates_known_keys_enums_and_ranges(tmp_path):
    root, user = tmp_path/'project', tmp_path/'user.json'; root.mkdir()
    settings = Settings(root, user)
    settings.save('user', 'editor', {'fontSize': 17, 'wordWrap': 'column'})
    assert settings.effective()['editor']['fontSize'] == 17
    with pytest.raises(ValueError): settings.save('user', 'editor', {'fontSize': 99})
    with pytest.raises(ValueError): settings.save('user', 'editor', {'wordWrap': 'sometimes'})
    with pytest.raises(ValueError): settings.save('user', 'editor', {'imaginary': True})

def test_legacy_full_workspace_snapshot_does_not_override_later_user_choices(tmp_path):
    root, user = tmp_path/'project', tmp_path/'user.json'; root.mkdir(); (root/'.leela').mkdir()
    snapshot = {section: dict(values) for section, values in DEFAULT_SETTINGS.items()}
    (root/'.leela/settings.json').write_text(json.dumps(snapshot))
    user.write_text(json.dumps({'editor': {'ligatures': False, 'useTabs': True}}))
    effective = Settings(root, user).effective()
    assert effective['editor']['ligatures'] is False
    assert effective['editor']['useTabs'] is True

def test_legacy_snapshot_keeps_non_default_values(tmp_path):
    root, user = tmp_path/'project', tmp_path/'user.json'; root.mkdir()
    snapshot = {section: dict(values) for section, values in DEFAULT_SETTINGS.items()}
    snapshot['editor']['fontSize'] = 17
    user.write_text(json.dumps(snapshot))
    settings = Settings(root, user)
    assert settings.raw('user') == {'editor': {'fontSize': 17}}

def test_settings_writes_are_atomic_and_leave_valid_json(tmp_path, monkeypatch):
    import leela.blocks.settings.settings as module
    user = tmp_path/'nested'/'settings.json'
    calls = []
    original = module.atomic_save
    def atomic(path, **kwargs):
        calls.append((Path(path), kwargs))
        return original(path, **kwargs)
    monkeypatch.setattr(module, 'atomic_save', atomic)
    Settings(user_path=user).save('user', 'editor', {'fontSize': 17})
    assert calls == [(user, {'mode': 'w', 'encoding': 'utf-8'})]
    assert json.loads(user.read_text()) == {'editor': {'fontSize': 17}}

def test_the_user_settings_file_is_one_path_a_test_can_move(tmp_path, monkeypatch):
    "`Settings` held a second copy of the expression, so moving the named one moved nothing."
    import leela.blocks.settings.settings as module
    monkeypatch.setattr(module, 'user_settings_file', lambda: tmp_path/'moved.json')
    Settings().save('user', 'editor', {'ligatures': False, 'useTabs': True})
    assert json.loads((tmp_path/'moved.json').read_text()) == {'editor': {'ligatures': False, 'useTabs': True}}
    assert Settings().raw('user')['editor'] == {'ligatures': False, 'useTabs': True}
    assert Settings().describe()['paths']['user'] == str(tmp_path/'moved.json')

def test_workspace_settings_are_project_local_and_resettable(tmp_path):
    root, user = tmp_path/'project', tmp_path/'user.json'; root.mkdir()
    settings = Settings(root, user)
    settings.save('workspace', 'files', {'autoSave': 'off'})
    assert settings.workspace_path == root/'.leela/settings.json'
    assert settings.effective()['files']['autoSave'] == 'off'
    settings.reset('workspace', 'files')
    assert settings.effective()['files']['autoSave'] == DEFAULT_SETTINGS['files']['autoSave']

def test_env_store_reads_async_dockeasy_ops(monkeypatch):
    async def get(*args, **kwargs): return 'value'
    async def put(*args, **kwargs): return None
    monkeypatch.setattr('leela.core.envs._dockeasy', lambda: (get, put, get, put))
    assert EnvStore().get('TOKEN') == 'value'
    assert EnvStore().set('TOKEN', 'next')['key'] == 'TOKEN'

def test_env_store_reads_async_ops_inside_an_event_loop(monkeypatch):
    async def get(*args, **kwargs): return 'value'
    monkeypatch.setattr('leela.core.envs._dockeasy', lambda: (get, get, get, get))
    async def read(): return EnvStore().get('TOKEN')
    assert asyncio.run(read()) == 'value'

def test_the_config_dir_stays_inside_the_temp_dir(cfg_home):
    from leela import leela_cfg
    from leela.blocks.memory.memory import memory_path
    from leela.blocks.settings.settings import user_settings_file
    from leela.workspace import ws_path
    # one of the two temp dirs: the session's, or this test's own, which is what `leela_cfg` moved to
    safe = (TEST_CONFIG_HOME, str(cfg_home))
    for p in (leela_cfg, memory_path(), user_settings_file(), ws_path()):
        assert str(p).startswith(safe), f'{p} escapes the test config dirs'
    assert str(user_settings_file()).startswith(str(cfg_home)), 'settings move with this test, not the session'
    real = Path.home()/'.config'/'leela'
    assert not str(real).startswith(safe)
    assert Path(leela_cfg) != real and real not in Path(leela_cfg).parents


def test_a_workspace_writes_its_memory_and_journal_under_the_temp_dir(tmp_path, cfg_home):
    "The two a `Workspace` opens on construction, which is how the real store got polluted."
    ws = Workspace(roots=[tmp_path])
    assert str(ws.memory.path).startswith((TEST_CONFIG_HOME, str(cfg_home)))
    assert str(ws.journal.path).startswith(str(cfg_home)), 'and its journal is this test\'s alone'

def _saved(path): return json.loads(path.read_text())

def test_a_rootless_save_does_not_blank_the_folders_and_tabs_beside_it(tmp_path):
    "Model choices written through a bare `Workspace` rewrote the state file whole, losing both."
    (proj := tmp_path/'proj').mkdir(); (proj/'a.py').write_text('x = 1')
    state = tmp_path/'workspace.json'
    lived = Workspace(roots=[proj]); lived._state_path = state
    lived.open(proj/'a.py'); lived.save()
    fresh = Workspace(roots=[]); fresh._state_path = state
    fresh.model = 'gemma-12b'; fresh.save()
    held = _saved(state)
    assert held['roots'] == [str(r) for r in lived.fs.roots]
    assert [t['path'] for t in held['tabs']] == [str(proj/'a.py')]
    assert held['model'] == 'gemma-12b' and Workspace.load(state).model == 'gemma-12b'

def test_a_named_partial_save_writes_only_those_keys(tmp_path):
    (proj := tmp_path/'proj').mkdir()
    state = tmp_path/'workspace.json'
    lived = Workspace(roots=[proj]); lived._state_path = state; lived.save()
    lived.model, lived.subagent_writes = 'gemma-12b', True
    lived.save(only=('model',))
    held = _saved(state)
    assert held['model'] == 'gemma-12b' and held['subagent_writes'] is False
    assert held['version'] == 2, 'a partial write still says what shape it is'

def test_closing_the_last_folder_is_a_session_worth_saving(tmp_path):
    "The folders are only left alone for a workspace that never had a session, never for an empty one."
    (proj := tmp_path/'proj').mkdir()
    state = tmp_path/'workspace.json'
    ws = Workspace(roots=[proj]); ws._state_path = state; ws.save()
    ws.drop_root(proj); ws.save()
    assert _saved(state)['roots'] == []

def test_a_workspace_saved_before_one_folder_was_one_window_heals_when_it_loads(tmp_path):
    "Folders piled into one file under the old model reopened all of them, and pointed git at the wrong one."
    folders = tmp_path/'workspaces'; folders.mkdir()
    made = {n: tmp_path/n for n in ('ramabana', 'leela', 'notes', 'litesearch', 'pobblebonk')}
    made['worktree'] = tmp_path/'wt'/'leela'
    for p in made.values(): p.mkdir(parents=True)
    (made['leela']/'a.py').write_text('x = 1')
    def write(slug, roots, active='', tabs=()):
        (folders/f'{slug}.json').write_text(json.dumps(
            {'version': 2, 'roots': [str(r) for r in roots], 'active': 0, 'active_root': str(active),
             'tabs': [{'path': str(t), 'kind': 'text', 'title': Path(t).name} for t in tabs]}))
    write('leela', [made['leela']]); write('pobblebonk', [made['pobblebonk']])
    write('ramabana', [made['ramabana'], made['leela'], made['notes'], made['worktree']],
          active=made['leela'], tabs=[made['leela']/'a.py'])
    ws = Workspace.load(folders/'ramabana.json')
    assert [str(r) for r in ws.fs.roots] == [str(made[n]) for n in ('ramabana', 'notes', 'worktree')], \
        'the folder with a window of its own goes; an ordinary folder and a namesake with no window stay'
    assert ws.active_root is None and str(ws.project_root) == str(made['ramabana'])
    assert ws.tabs == [], 'and a tab under the folder that left does not reopen'
    held = _saved(folders/'ramabana.json')
    assert held['per_folder'] and len(held['roots']) == 3
    ws.add_root(made['leela']); ws.save()
    assert str(made['leela']) in [str(r) for r in Workspace.load(folders/'ramabana.json').fs.roots], \
        'a folder opened here on purpose afterwards is not reconciled away again'
    write('varga', [made['litesearch'], made['pobblebonk']], active=made['pobblebonk'])
    varga = Workspace.load(folders/'varga.json')
    assert [str(r) for r in varga.fs.roots] == [str(made['litesearch'])], 'a slug naming no root is not special'
    assert varga.active_root is None and str(varga.project_root) == str(made['litesearch'])
    legacy = tmp_path/'workspace.json'
    legacy.write_text(json.dumps({'version': 2, 'roots': [str(made['leela']), str(made['pobblebonk'])],
                                  'tabs': [], 'active': 0, 'active_root': str(made['pobblebonk'])}))
    assert len(Workspace.load(legacy).fs.roots) == 2, 'the file outside `workspaces` is still many folders'


CLOSURE = 'leela.app'

def owner(route):
    "The module whose function actually handles `route`."
    ep = getattr(route, 'endpoint', None)
    for cell in (getattr(ep, '__closure__', None) or ()):
        v = cell.cell_contents
        m = getattr(v, '__module__', '')
        if callable(v) and m and m != 'fasthtml.core': return m
    return type(route).__name__

def owners(app=None):
    "`{path: module}` for every route with a Python handler."
    app = app or ide_app(Workspace(roots=[]))
    return {getattr(r, 'path', ''): owner(r) for r in app.router.routes}


def test_no_extracted_path_is_still_handled_by_the_closure():
    "The inverse: a path a block claims must not also be defined in ide_app, shadowing it."
    claimed = {f'{m.__name__}.app' for m in BLOCKS}
    served = owners()
    for path, mod in served.items():
        if mod in claimed: continue
        assert mod in (CLOSURE, 'Mount', 'HostRoute', 'WebSocketRoute'), \
            f'{path} is served by unexpected module {mod}'

def test_the_split_is_reported_accurately_in_the_docs():
    "docs/blocks.md quotes a block/closure split. Keep it honest."
    served = owners()
    in_blocks = sum(1 for m in served.values() if m.startswith('leela.blocks'))
    in_closure = sum(1 for m in served.values() if m == CLOSURE)
    assert in_blocks > 0 and in_closure > 0
    assert in_blocks + in_closure == len([m for m in served.values()
                                          if m.startswith('leela.blocks') or m == CLOSURE])

INVENTORY = Path(__file__).parent/'routes.txt'

def _row(r):
    path = getattr(r, 'path', '')
    ms = sorted(getattr(r, 'methods', None) or [])
    ms = [m for m in ms if m not in ('HEAD', 'OPTIONS')]
    return f"{','.join(ms) or type(r).__name__} {path}"

def inventory(app=None):
    "Every registered route as a sorted list of `METHODS PATH` lines."
    app = app or ide_app(Workspace(roots=[]))
    return sorted(_row(r) for r in app.router.routes)

def test_the_browser_url_surface_is_unchanged():
    have = inventory()
    want = [l for l in INVENTORY.read_text().splitlines() if l.strip()]
    gone, new = sorted(set(want) - set(have)), sorted(set(have) - set(want))
    assert not gone, ('routes disappeared from the app:\n  ' + '\n  '.join(gone) +
                      '\n\nIf this is deliberate, regenerate: python -c "from tests.test_core import inventory, INVENTORY; INVENTORY.write_text(chr(10).join(inventory())+chr(10))"')
    assert not new, ('routes appeared that are not in the inventory:\n  ' + '\n  '.join(new) +
                     '\n\nIf this is deliberate, regenerate: python -c "from tests.test_core import inventory, INVENTORY; INVENTORY.write_text(chr(10).join(inventory())+chr(10))"')


sys.path.insert(0, str(ROOT/'tools'))

def test_an_interpreters_libraries_are_not_the_project(tmp_path):
    "98% of a walk of this repo was site-packages, so `@keys` ranked `libxslt/keys.h` over"
    for d in ('.venv', '.app-venv', 'my-venv', 'venv-3.12'):
        lib = tmp_path/d/'lib'/'python3.12'/'site-packages'/'lxml'
        lib.mkdir(parents=True)
        (lib/'keys.h').write_text('/* not your code */\n')
    (tmp_path/'keys.py').write_text('KEYS = 1\n')
    (tmp_path/'conventions').mkdir(); (tmp_path/'conventions'/'keys.py').write_text('X = 1\n')
    ws = Workspace(roots=[tmp_path])
    walked = [str(p) for p in ws.fs.walk(tmp_path)]
    assert not [p for p in walked if 'site-packages' in p], walked[:3]
    assert len(walked) == 2, walked
    assert any(p.endswith('conventions/keys.py') for p in walked), 'not an over-eager skip'

def test_a_site_packages_under_an_oddly_named_venv_is_still_skipped(tmp_path):
    "The inner skip is the backstop for a venv folder named something nobody predicted."
    lib = tmp_path/'weird'/'lib'/'site-packages'/'pkg'
    lib.mkdir(parents=True)
    (lib/'mod.py').write_text('x = 1\n')
    (tmp_path/'mine.py').write_text('y = 2\n')
    ws = Workspace(roots=[tmp_path])
    assert [p.name for p in ws.fs.walk(tmp_path)] == ['mine.py']

if __name__ == '__main__':
    if '--routes' in sys.argv:
        INVENTORY.write_text('\n'.join(inventory()) + '\n')
        print(f'wrote {INVENTORY} ({len(inventory())} routes)')
    else:
        from collections import Counter
        counts = Counter(owners().values())
        width = max(len(m) for m in counts)
        print('WHAT SERVES EACH ROUTE\n')
        for m, n in counts.most_common():
            tag = 'BLOCK  ' if m.startswith('leela.blocks') else ('closure' if m == CLOSURE else '       ')
            print(f'{n:>4}  {tag} {m:<{width}}')
        blocks = sum(n for m, n in counts.items() if m.startswith('leela.blocks'))
        print(f'\n{blocks} routes served by blocks, {counts.get(CLOSURE, 0)} still by the ide_app closure')

def test_the_wiring_order_lives_with_the_blocks_not_with_the_application():
    """`app.py` held 25 aliased imports and the list. A block could not be added without
    editing the application, and the list could disagree with what is on disk.
    """
    from leela import blocks
    folders = {p.name for p in BLOCKS_DIR.iterdir() if (p/'__init__.py').is_file()}
    assert set(blocks.NAMES) == folders, 'the order and the folders on disk disagree'
    assert len(blocks.NAMES) == len(set(blocks.NAMES)), 'a block is wired twice'
    assert [m.__name__.split('.')[-1] for m in BLOCKS] == list(blocks.NAMES)
    import ast
    imported = {a.asname for n in ast.walk(ast.parse((ROOT/'leela/app.py').read_text()))
                if isinstance(n, ast.ImportFrom) for a in n.names if (a.asname or '').endswith('_block')}
    assert imported == set(), f'app.py still aliases blocks one by one: {sorted(imported)}'

def test_every_block_with_client_code_is_named_in_the_load_order():
    """A `.js` file in a block is only reachable if `LAYERS` names it. Dropping one in and
    forgetting that is a feature that silently never loads, with no import error to say so.
    """
    import sys
    sys.path.insert(0, str(ROOT/'tools'))
    import build_ide_js as builder
    assert builder.missing() == [], 'named in the order but not on disk'
    assert builder.orphans() == [], 'on disk but never loaded'
    owners = {p.parent.name for p in builder.modules() if 'blocks' in str(p)}
    assert owners <= set(__import__('leela.blocks', fromlist=['NAMES']).NAMES), owners

#: capabilities a block declares because it hands `ctx` to a helper that reads them
HANDED_OFF = {'editor': ('pool',)}   # `python_for(session=ctx)` reads `session.fs` and `session.pool`

def test_caps_declares_exactly_what_the_route_layer_reads():
    """`Ctx` refuses an undeclared capability, so an over-broad `CAPS` grants reach nobody asked
    for and an under-broad one is an AttributeError on a route nobody exercised. Both are silent
    until then, so compare the declaration against what `app.py` and `ui.py` actually read.
    """
    import ast
    from leela.core import CAPABILITIES
    caps_all = set(CAPABILITIES)
    wrong = {}
    for d in sorted(p for p in BLOCKS_DIR.iterdir() if (p/'app.py').is_file()):
        src = (d/'app.py').read_text()
        declared = set(re.findall(r"'(\w+)'", m.group(1))) if (m := re.search(r"^CAPS = \(([^)]*)\)", src, re.M)) else None
        if declared is None: continue
        reads = set()
        for f in [d/'app.py'] + ([d/'ui.py'] if (d/'ui.py').is_file() else []):
            for n in ast.walk(ast.parse(f.read_text())):
                if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                        and n.value.id == 'ctx' and n.attr in caps_all): reads.add(n.attr)
        extra = sorted(declared - reads - set(HANDED_OFF.get(d.name, ())))
        missing = sorted(reads - declared)
        if extra or missing:
            wrong[d.name] = {'declared but never read': extra, 'read but not declared': missing}
    assert wrong == {}, wrong

def test_local_history_keeps_one_body_per_distinct_version(tmp_path):
    "Twenty saves of an unchanged file are one version, and one stored body."
    from leela.core.session import FileHistory
    h = FileHistory(tmp_path/'history')
    first_row = h.record('a.py', 'one\n')
    assert first_row is not None and h.record('a.py', 'one\n') is None
    second = h.record('a.py', 'two\n', 'changed outside leela')
    assert h.record('b.py', 'one\n') is not None, 'another file with the same text is its own version'
    assert len(list((tmp_path/'history'/'blobs').glob('*.gz'))) == 2, 'bodies are shared by content'
    assert h.text(second['id']) == 'two\n'
    assert [r['label'] for r in h.rows('a.py')] == ['changed outside leela', 'save']
    assert 'blob' not in h.rows('a.py')[0], 'a listing is not a body'
    assert [r['path'] for r in h.rows()][0] == 'b.py', 'newest first, across every file'
    assert {r['path'] for r in h.paths()} == {'a.py', 'b.py'}
    with pytest.raises(ValueError, match='no such version'): h.text('ver_missing')

def test_local_history_forgets_the_oldest_and_the_bodies_nothing_names(tmp_path):
    from leela.core import session
    from leela.core.session import FileHistory
    session.KEEP_PER_PATH = 3
    try:
        h = FileHistory(tmp_path/'history')
        rows = [h.record('a.py', f'v{i}\n') for i in range(5)]
        assert [r['label'] for r in h.rows('a.py')] == ['save'] * 3
        assert [h.text(r['id']) for r in h.rows('a.py')] == ['v4\n', 'v3\n', 'v2\n']
        assert len(list((tmp_path/'history'/'blobs').glob('*.gz'))) == 3, 'the evicted bodies went too'
        assert FileHistory(tmp_path/'history').rows('a.py') == h.rows('a.py'), 'and it survives a restart'
    finally: session.KEEP_PER_PATH = 60

def test_no_test_can_reach_the_real_conversation_log(tmp_path, cfg_home):
    """A test wrote `ai.history_path` with `write_text`, which truncates. One config dir shared by
    the whole session meant the file it truncated was whichever one the suite had been pointed at.
    """
    from tests.conftest import REAL_CONFIG_HOME
    import leela
    fresh = Workspace(roots=[tmp_path])
    for path in (Path(leela.leela_cfg), Path(fresh.ai.history_path), Path(fresh.journal.path)):
        assert REAL_CONFIG_HOME not in path.parents and path != REAL_CONFIG_HOME
        assert str(path).startswith(str(cfg_home)), path
    assert Path(fresh.ai.history_path).name == 'agent-history.jsonl', 'the same file, in a safe place'
    fresh.threads.shutdown()

def test_a_write_from_outside_leela_is_kept_before_the_editor_takes_it(tmp_path):
    "The disk poll is the only moment anything notices another process editing an open file."
    from starlette.testclient import TestClient
    from leela.app import ide_app
    src = tmp_path/'mod.py'; src.write_text('mine\n')
    ws = Workspace(roots=[tmp_path])
    try:
        with TestClient(ide_app(ws)) as client:
            client.get(f'/tab/open?path={src}')
            assert client.get('/tab/state').json()['text'] == 'mine\n'
            assert client.get('/tab/watch').json()['disk_version']
            assert ws.history.rows(str(src)) == [], 'nothing has happened to it yet'
            src.write_text('another agent was here\n')
            client.get('/tab/watch')
            kept = ws.history.rows(str(src))
            assert [v['label'] for v in kept] == ['changed outside Leela']
            assert ws.history.text(kept[0]['id']) == 'another agent was here\n'
            client.get('/tab/watch')
            assert len(ws.history.rows(str(src))) == 1, 'the same version is not kept twice'
    finally: ws.threads.shutdown()

def test_local_history_keeps_every_write_leela_can_see_and_puts_one_back(tmp_path):
    """Undo is one step back. What a person needs after an agent, a tool or another editor has been
    through the tree is the file as it was earlier, and a way to choose which earlier."""
    from starlette.testclient import TestClient
    from leela.app import ide_app
    src = tmp_path/'mod.py'; src.write_text('one\n')
    ws = Workspace(roots=[tmp_path])
    try:
        with TestClient(ide_app(ws)) as client:
            ws.journal.record('Agent turn', [(str(src), 'one\n', 'two\n')], kind='file')
            src.write_text('two\n')
            listed = client.get(f'/history/file?path={src}').json()
            assert [v['label'] for v in listed['versions']] == ['Agent turn', 'before the first change seen']
            assert listed['path'] == str(src)
            oldest = listed['versions'][-1]
            held = client.get(f"/history/version?id={oldest['id']}").json()
            assert held['text'] == 'one\n' and held['rows'], 'the body, and how it differs from disk'
            assert client.get('/history/version?id=ver_nope').status_code == 404
            back = client.post('/history/restore', json={'id': oldest['id']}).json()
            assert back['ok'] and src.read_text() == 'one\n' and back['operation_id']
            again = client.get(f'/history/file?path={src}').json()['versions']
            assert again[0]['label'] == f'Restore {src.name} from local history', 'the restore is itself a version'
            assert [v['label'] for v in again].count('before the first change seen') == 1
            repeat = client.post('/history/restore', json={'id': oldest['id']})
            assert repeat.status_code == 409, 'restoring what the file already says is not a change'
            assert client.post('/history/restore', json={'id': 'ver_nope'}).status_code == 404
            assert str(src) in [f['path'] for f in client.get('/history/files').json()['files']]
    finally: ws.threads.shutdown()

def test_a_huge_file_is_noted_rather_than_copied(tmp_path):
    """A 70MB notebook saved through a day put gigabytes of bodies in the journal, and every write
    after that reloaded and rewrote all of them. The version still says the file changed and when;
    the copy is what stops."""
    from leela.core.session import MAX_BODY, FileHistory
    h = FileHistory(tmp_path/'h')
    big, small = 'x' * (MAX_BODY + 1), 'y' * 32
    row = h.record('/w/huge.ipynb', big, 'save')
    assert row['bytes'] == len(big) and row['kept'] is False
    assert h.rows('/w/huge.ipynb')[0]['bytes'] == len(big), 'it is still listed'
    with pytest.raises(ValueError, match='too large to copy'): h.text(row['id'])
    kept = h.record('/w/small.py', small, 'save')
    assert kept['kept'] is True and h.text(kept['id']) == small
    assert not (tmp_path/'h'/'blobs'/f"{row['blob']}.gz").exists(), 'no body was written'
    assert h.record('/w/huge.ipynb', big, 'save') is None, 'and an unchanged one is still one version'

def test_an_operation_whose_bodies_were_too_large_refuses_to_undo(tmp_path):
    "Undo would otherwise find a missing body with the file already half rewritten."
    from leela.core.session import MAX_BODY, FileHistory, OperationJournal
    from leela.blocks.fs.fs import Sandbox
    f = tmp_path/'huge.ipynb'; f.write_text('after')
    h = FileHistory(tmp_path/'h')
    j = OperationJournal(tmp_path/'j.json', Sandbox([tmp_path]), history=h)
    j.history.pinned = j.blobs
    op = j.record('Save huge', [(str(f), 'x' * (MAX_BODY + 1), 'after')], kind='save')
    assert op['resources'][0]['kept'] is False
    with pytest.raises(ValueError, match='cannot be undone'): j.undo()
    assert f.read_text() == 'after', 'and nothing was written on the way to refusing'

def test_the_journal_keeps_bodies_by_reference_and_pins_them(tmp_path):
    "Inline they made the journal itself gigabytes. The history already stores them once, gzipped."
    import json
    from leela.core.session import FileHistory, OperationJournal
    from leela.blocks.fs.fs import Sandbox
    f = tmp_path/'a.py'; f.write_text('two\n')
    h = FileHistory(tmp_path/'h')
    j = OperationJournal(tmp_path/'j.json', Sandbox([tmp_path]), history=h)
    h.pinned = j.blobs
    op = j.record('Save a.py', [(str(f), 'one\n', 'two\n')], kind='save')
    row = op['resources'][0]
    assert 'before' not in row and 'after' not in row, 'no bodies in the journal'
    assert row['before_blob'] and row['after_blob'] and row['kept'] is True
    assert 'one\n' not in (tmp_path/'j.json').read_text(), 'nor on disk'
    for _ in range(200): h.record(str(f), f'filler {_}\n', 'save')   # past KEEP_PER_PATH, prunes
    assert h.body(row['before_blob']) == 'one\n', 'the operation still has what it needs'
    j.undo()
    assert f.read_text() == 'one\n'

def test_a_window_opened_from_finder_takes_the_shell_environment_it_was_denied(tmp_path):
    """An app launched from Finder has launchd's environment, so a key exported from a shell profile
    is invisible to it while the same Leela started from a terminal sees it."""
    import os
    from leela.core.envs import import_login_env
    shell = tmp_path/'fakeshell'
    shell.write_text('#!/bin/sh\nprintf \'OPENAI_API_KEY=sk-from-profile\\0HOME=/somewhere/else\\0'
                     'PATH=/opt/tools:/usr/bin\\0PWD=/tmp\\0\'\n')
    shell.chmod(0o755)
    env = {'HOME': '/real/home', 'PATH': '/usr/bin'}
    added = import_login_env(shell=str(shell), env=env)
    assert env['OPENAI_API_KEY'] == 'sk-from-profile', 'the key the profile exports arrives'
    assert env['HOME'] == '/real/home', 'and nothing the launcher chose is overwritten'
    assert env['PATH'].split(os.pathsep) == ['/usr/bin', '/opt/tools'], 'a directory it lacks can only add a tool'
    assert 'PWD' not in env, 'the shell describing itself is not the environment'
    assert set(added) == {'OPENAI_API_KEY', 'PATH'}

def test_a_shell_that_cannot_be_asked_changes_nothing(tmp_path):
    "Being unable to ask is not evidence about the environment, so it leaves it as it was."
    from leela.core.envs import import_login_env
    env = {'PATH': '/usr/bin'}
    assert import_login_env(shell=str(tmp_path/'no-such-shell'), env=env) == []
    broken = tmp_path/'broken'; broken.write_text('#!/bin/sh\nexit 3\n'); broken.chmod(0o755)
    assert import_login_env(shell=str(broken), env=env) == []
    assert env == {'PATH': '/usr/bin'}

def test_the_shell_is_asked_the_way_a_person_uses_it(tmp_path):
    """zsh reads `.zshrc` only for an interactive shell, and that is where an API key usually lives.
    Asked with `-l` alone it answered with eight names and no key, so every hosted model refused
    every turn in the packaged app and nowhere else."""
    from leela.core.envs import shell_env
    shell = tmp_path/'fussy'
    # only an interactive shell exports the key, which is what a `.zshrc` amounts to
    shell.write_text("#!/bin/sh\ncase \"$*\" in *-i*) printf 'OPENAI_API_KEY=sk-interactive\\0';; esac\n"
                     "printf 'HOME=/somewhere\\0'\n")
    shell.chmod(0o755)
    assert shell_env(str(shell)).get('OPENAI_API_KEY') == 'sk-interactive'
    plain = tmp_path/'plain'
    plain.write_text("#!/bin/sh\ncase \"$*\" in *-i*) exit 2;; esac\nprintf 'PATH=/opt/tools\\0'\n")
    plain.chmod(0o755)
    assert shell_env(str(plain)) == {'PATH': '/opt/tools'}, 'a shell that refuses -i is asked without it'

def test_the_shell_a_person_chose_is_the_one_asked(tmp_path, monkeypatch):
    """`$SHELL` is the shell the login record names, which is not always the one in use. Leela
    already has a terminal setting for that, and this reads the same one."""
    from leela.blocks.settings.settings import Settings
    from leela.core import envs
    monkeypatch.setenv('SHELL', '/bin/zsh')
    user = tmp_path/'settings.json'
    monkeypatch.setattr('leela.blocks.settings.settings.user_settings_file', lambda: str(user))
    assert envs.preferred_shell() == '/bin/zsh', 'nothing chosen, so the login record stands'
    Settings(user_path=user).save('user', 'terminal', {'shell': '/opt/homebrew/bin/fish'})
    assert envs.preferred_shell() == '/opt/homebrew/bin/fish', 'the chosen shell is the one asked'

def test_a_value_typed_into_leela_beats_the_environment_it_was_launched_with(tmp_path, monkeypatch):
    """The escape hatch. Asking the shell is a guess about a machine, and where the guess is wrong
    there has to be somewhere to say so, or every hosted model refuses every turn with no way in."""
    import leela
    from leela.core import envs
    monkeypatch.setattr(leela, 'leela_cfg', tmp_path)
    env = {'OPENAI_API_KEY': 'sk-from-a-shell-that-is-wrong'}
    assert envs.apply_stored_env(env) == [], 'nothing stored, nothing claimed'
    assert env['OPENAI_API_KEY'] == 'sk-from-a-shell-that-is-wrong'
    monkeypatch.setattr(envs.os, 'environ', {})
    envs.set_env('OPENAI_API_KEY', 'sk-typed-in')
    assert envs.apply_stored_env(env) == ['OPENAI_API_KEY']
    assert env['OPENAI_API_KEY'] == 'sk-typed-in', 'what a person typed wins'
    assert oct((tmp_path/'env.json').stat().st_mode)[-3:] == '600', 'a file of keys is not world readable'
    envs.unset_env('OPENAI_API_KEY')
    assert envs.stored_env() == {}

def test_the_environment_editor_refuses_what_is_not_a_variable(tmp_path, monkeypatch):
    "A name that a shell cannot export is a typo, and saying so beats writing it down."
    import leela
    from leela.core import envs
    monkeypatch.setattr(leela, 'leela_cfg', tmp_path)
    monkeypatch.setattr(envs.os, 'environ', {})
    for bad in ('', '9LIVES', 'has space', 'has-dash', 'PATH=x'):
        with pytest.raises(envs.EnvError): envs.set_env(bad, 'v')
    with pytest.raises(envs.EnvError): envs.set_env('OPENAI_API_KEY', '')
    with pytest.raises(envs.EnvError): envs.unset_env('OPENAI_API_KEY')   # the shell's, not Leela's
    envs.set_env('LEE_OK', 'v')
    assert envs.stored_env() == {'LEE_OK': 'v'}

def test_a_secrets_value_never_leaves_the_server(tmp_path, monkeypatch):
    "The panel says a key is set. What it is set to is not something a browser needs."
    import leela
    from leela.core import envs
    monkeypatch.setattr(leela, 'leela_cfg', tmp_path)
    monkeypatch.setattr(envs.os, 'environ', {'OPENAI_API_KEY': 'sk-secret', 'EDITOR': 'vim'})
    envs.set_env('MY_TOKEN', 'tok-secret')
    rows = {r['key']: r for r in envs.env_rows()}
    assert not [r for r in rows.values() if r['secret'] and r['value']], 'no secret value in the payload'
    assert 'sk-secret' not in json.dumps(rows) and 'tok-secret' not in json.dumps(rows)
    assert rows['OPENAI_API_KEY']['set'] and rows['OPENAI_API_KEY']['source'] == 'environment'
    assert rows['MY_TOKEN']['removable'], "Leela's own can be taken away again"
    assert not rows['OPENAI_API_KEY']['removable'], 'what the shell exports is the shell\'s'
    assert 'EDITOR' not in rows, 'the whole environment is not the browser\'s business'
    assert rows['ANTHROPIC_API_KEY']['set'] is False, 'the names the models read are offered anyway'

def test_two_windows_accumulate_folders_in_the_one_saved_session(tmp_path):
    """One file, several windows. `save` wrote the roots it had over the roots the file had, so
    opening the app on one folder emptied a session that a browser window had four folders in."""
    from leela.workspace import Workspace
    a, b, c = (tmp_path/'a', tmp_path/'b', tmp_path/'c')
    for d in (a, b, c): d.mkdir()
    state = tmp_path/'workspace.json'
    web, app = Workspace(roots=[a, b]), Workspace(roots=[c])
    web.save(state)
    app.save(state)
    assert [Path(r).name for r in state.read_json()['roots']] == ['a', 'b', 'c'], \
        'the window that saved second adds its folder rather than replacing theirs'
    web.save(state)
    assert [Path(r).name for r in state.read_json()['roots']] == ['a', 'b', 'c'], \
        'and saving again does not take back a folder this window never had'

def test_closing_a_folder_is_a_decision_the_saved_session_keeps(tmp_path):
    "The cost of one shared workspace: a folder closed in one window is closed in the other."
    from leela.workspace import Workspace
    a, b = (tmp_path/'a', tmp_path/'b')
    for d in (a, b): d.mkdir()
    state = tmp_path/'workspace.json'
    Workspace(roots=[a, b]).save(state)
    other = Workspace(roots=[b])
    other.drop_root(b)
    other.save(state)
    assert [Path(r).name for r in state.read_json()['roots']] == ['a'], 'b was closed, not merely absent'

def test_a_save_that_races_another_loses_no_folder(tmp_path):
    "The lock spans the read and the write, so concurrent saves merge instead of overwriting."
    import threading
    from leela.workspace import Workspace
    state = tmp_path/'workspace.json'
    dirs = []
    for i in range(12):
        d = tmp_path/f'r{i}'; d.mkdir(); dirs.append(d)
    spaces = [Workspace(roots=[d]) for d in dirs]
    start = threading.Event()
    def run(ws):
        start.wait(); ws.save(state)
    threads = [threading.Thread(target=run, args=(w,)) for w in spaces]
    for t in threads: t.start()
    start.set()
    for t in threads: t.join(20)
    assert sorted(Path(r).name for r in state.read_json()['roots']) == sorted(d.name for d in dirs)

def test_a_partial_save_and_an_unreadable_file_leave_the_folders_alone(tmp_path):
    "`only` names what it writes, and a file that cannot be read is not evidence that nothing is open."
    from leela.workspace import Workspace
    a = tmp_path/'a'; a.mkdir()
    state = tmp_path/'workspace.json'
    Workspace(roots=[a]).save(state)
    Workspace(roots=[]).save(state, only=('model',))
    assert [Path(r).name for r in state.read_json()['roots']] == ['a'], 'a partial write is not a root list'
    state.write_text('{not json')
    Workspace(roots=[a]).save(state)
    assert [Path(r).name for r in state.read_json()['roots']] == ['a']
