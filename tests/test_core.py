"Core: the block contract, the host boundary, diffs, settings, routes and the journal."

import re
import json
import subprocess, time
import sys
from pathlib import Path
import pytest
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.workspace import Workspace
ROOT = Path(__file__).resolve().parents[1]
from leela.core.text import (closest, diff_label, diff_rows, diff_stat,
                                did_you_mean, fuzzy_rank, udiff)
from leela.blocks.fs.fs import Sandbox
from leela.core.session import OperationJournal
from leela.blocks.settings.settings import DEFAULT_SETTINGS, Settings
from tests.conftest import TEST_CONFIG_HOME
from leela.core import projects
from fastcore.all import Path

@pytest.fixture(scope='module')
def client():
    with TestClient(ide_app(Workspace(roots=[]))) as c: yield c

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

def test_a_theme_saved_to_a_language_scope_is_still_the_theme_for_every_language(tmp_path):
    "The panel saves the theme with no language. A `languages.python` theme would shadow it."
    theme = 'nord:dark:tight'
    s = Settings(root=tmp_path, user_path=tmp_path/'user.json')
    s.save('user', 'appearance', {'theme': theme}, language='')
    assert 'languages' not in s.raw('user')
    assert s.effective(language='python')['appearance']['theme'] == theme
    assert Settings(root=tmp_path, user_path=tmp_path/'user.json').effective()['appearance']['theme'] == theme

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

def test_a_repository_outside_the_workspace_is_refused(workspace_client, tmp_path):
    client, root = workspace_client
    d = client.get('/git/info', params={'repo': '/etc'})
    assert d.status_code == 400 and 'not a repository in this workspace' in d.json()['error']

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

def test_the_environment_view_never_returns_a_secret_value(project_client):
    "The one rule this panel cannot break."
    client, _ = project_client
    d = client.get('/workflows/env').json()
    assert all(e['value'] == '' for e in d['entries'] if e['secret'])
    assert all(e['target'] in ('secret', 'variable') for e in d['entries'])

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

BLOCKS_DIR = ROOT/'leela/blocks'

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
    assert diff_rows(udiff(A, B))[0].dict().keys() == {'kind', 'text', 'line', 'html'}
    assert udiff(A, B, names=('old', 'new')).startswith('--- old\n+++ new\n')
    assert not udiff(A, B).startswith('---')
    assert diff_stat(None, 'x\n') == (1, 0)


def test_diff_rows_colour_the_code_when_the_path_names_a_language():
    """Diffs were green and red text with no syntax colours; `ramabana.hl` colours them now."""
    from leela.core.web import diff_payload
    rows = diff_payload('import os\nx = 1\n', 'import os\nx = "a<b"\n', 'm.py')['rows']
    by = {r['kind']: r for r in rows}
    assert 'hl-keyword' in by['ctx']['html'] and '&lt;' in by['add']['html'] and '<b' not in by['add']['html']
    assert by['hunk']['html'] == ''
    assert all(r['html'] == '' for r in diff_payload('a', 'b')['rows']), 'no path, no colours'

def test_a_deleted_line_that_looks_like_a_header_stays_a_deletion_when_coloured():
    rows = diff_rows('@@ -1,2 +1 @@\n---x\n y', 'python')
    assert [r.kind for r in rows] == ['hunk', 'del', 'ctx']

def test_a_diff_that_cannot_be_coloured_still_paints(monkeypatch):
    import ramabana.hl
    def boom(*a, **kw): raise RuntimeError('tokenizer down')
    monkeypatch.setattr(ramabana.hl, 'diff_html', boom)
    from leela.core.web import diff_payload
    rows = diff_payload('a\n', 'b\n', 'm.py')['rows']
    assert [r['kind'] for r in rows] == ['hunk', 'del', 'add'] and all(r['html'] == '' for r in rows)

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

FILES = ['a/web/app.py', 'a/some_long_app_helper.py', 'a/ide/panels/app.py',
         'a/README.md', 'a/apple/pie.txt']

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

def test_workspace_journal_refuses_diverged_files_atomically(tmp_path):
    root = tmp_path/'project'; root.mkdir(); a=root/'a'; b=root/'b'; a.write_text('a1'); b.write_text('b1')
    journal=OperationJournal(tmp_path/'journal.json', Sandbox([root]))
    a.write_text('a2'); b.write_text('b2'); op=journal.record('two files',[(a,'a1','a2'),(b,'b1','b2')])
    b.write_text('newer')
    with pytest.raises(ValueError, match='changed after'):
        journal.undo(op['id'])
    assert a.read_text() == 'a2' and b.read_text() == 'newer'

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

def test_legacy_full_workspace_snapshot_does_not_override_later_user_choices(tmp_path):
    root, user = tmp_path/'project', tmp_path/'user.json'; root.mkdir(); (root/'.leela').mkdir()
    snapshot = {section: dict(values) for section, values in DEFAULT_SETTINGS.items()}
    (root/'.leela/settings.json').write_text(json.dumps(snapshot))
    user.write_text(json.dumps({'editor': {'ligatures': False, 'useTabs': True}}))
    effective = Settings(root, user).effective()
    assert effective['editor']['ligatures'] is False
    assert effective['editor']['useTabs'] is True

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
    for p in (projects.SESSION, projects.DEFAULT_SESSION, projects.SERVING):
        assert p.parent == cfg_home, f'{p} was fixed at import, so every worker in a run shared it'
    real = Path.home()/'.config'/'leela'
    assert not str(real).startswith(safe)
    assert Path(leela_cfg) != real and real not in Path(leela_cfg).parents

def test_the_data_dir_stays_inside_the_temp_dir():
    from fastcore.xdg import xdg_data_home
    from leela.blocks.learn.tools import tool_dir
    for p in (xdg_data_home(), tool_dir('0'*16)):
        assert str(p).startswith(TEST_CONFIG_HOME), f'{p} escapes the test config dir'

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

def test_a_saved_canvas_tab_is_dropped_and_the_active_tab_stays_the_one_it_was(tmp_path):
    "A session saved while the canvas feature existed lists a canvas tab: the rest reopens, and the saved active index is read among the tabs that survive."
    (proj := (tmp_path/'proj').resolve()).mkdir()
    for n in ('a.py', 'b.py', 'p.canvas.md'): (proj/n).write_text('x = 1')
    state = tmp_path/'workspace.json'
    state.write_text(json.dumps({'version': 2, 'roots': [str(proj)], 'active': 1, 'tabs': [
        {'path': str(proj/n), 'kind': k} for n, k in (('p.canvas.md', 'canvas'), ('a.py', 'text'), ('b.py', 'text'))]}))
    ws = Workspace.load(state)
    assert [t.path for t in ws.tabs] == [str(proj/'a.py'), str(proj/'b.py')] and ws.tab.path == str(proj/'a.py')
    again = Workspace(roots=[proj])
    assert again.reopen_saved_tabs(state) == 2 and again.tab.path == str(proj/'a.py')

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

def test_every_route_a_block_serves_runs_with_only_the_capabilities_it_declared(tmp_path):
    "`Ctx` refuses an undeclared capability, so an under-broad `CAPS` is an AttributeError on a route nobody exercised."
    (tmp_path/'a.py').write_text('x = 1\n')
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as c:
        paths = sorted({r.path for r in c.app.routes if 'GET' in (getattr(r, 'methods', None) or ())
                        and '{' not in r.path and not re.search(r'stream|events|/ws|/term|/run|/exec|/open', r.path)})
        assert len(paths) > 50, paths
        for p in paths:
            try: c.get(p)
            except Exception as e: assert 'without declaring it' not in str(e), (p, e)

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
    """Undo is one step back."""
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
    """A 70MB notebook saved through a day put gigabytes of bodies in the journal, and every write after that reloaded and rewrote all of them."""
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
    """An app launched from Finder has launchd's environment, so a key exported from a shell profile is invisible to it while the same Leela started from a terminal sees it."""
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

def test_the_shell_is_asked_the_way_a_person_uses_it(tmp_path):
    """zsh reads `.zshrc` only for an interactive shell, and that is where an API key usually lives."""
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

def test_an_empty_inherited_value_takes_the_profiles(tmp_path):
    """launchd can hand an app `OPENAI_API_KEY=`, and an empty value blocked the shell's real one."""
    from leela.core.envs import import_login_env
    shell = tmp_path/'fakeshell'
    shell.write_text("#!/bin/sh\nprintf 'OPENAI_API_KEY=sk-from-profile\\0EDITOR=\\0'\n")
    shell.chmod(0o755)
    env = {'OPENAI_API_KEY': '', 'EDITOR': 'vim'}
    assert import_login_env(shell=str(shell), env=env) == ['OPENAI_API_KEY']
    assert env == {'OPENAI_API_KEY': 'sk-from-profile', 'EDITOR': 'vim'}, 'and an empty export erases nothing'

def test_a_hung_interactive_shell_is_asked_again_as_a_login_shell(tmp_path, monkeypatch):
    """A timeout under `-i` returned nothing at all, and every key in the profile went missing."""
    from leela.core import envs
    from leela.core.envs import shell_env
    shell = tmp_path/'hangs'
    shell.write_text("#!/bin/sh\ncase \"$*\" in *-i*) exec sleep 30;; esac\nprintf 'OPENAI_API_KEY=sk-login\\0'\n")
    shell.chmod(0o755)
    # macOS scans a new executable on its first exec, and under `-n auto` that took longer than the timeout; it happens here, untimed.
    subprocess.run([str(shell)], capture_output=True, check=True)
    # The default timeout, which also bounds the login shell: on a loaded runner a healthy one took more than 3 s.
    assert shell_env(str(shell)) == {'OPENAI_API_KEY': 'sk-login'}
    asked, run = [], envs.subprocess.run
    monkeypatch.setattr(envs.subprocess, 'run', lambda argv, **kw: asked.append(argv[1:]) or run(argv, **kw))
    assert shell_env(str(shell)) == {'OPENAI_API_KEY': 'sk-login'}
    assert asked == [['-l', '-c', 'env -0']], 'a shell that hung once is not waited on again'

def test_the_shell_is_asked_without_the_bundles_interpreter_pointed_at_it(tmp_path, monkeypatch):
    """A packaged app hands every child `PYTHONHOME` and `PYTHONPATH` aimed at itself."""
    from leela.core import envs
    shell = tmp_path/'profile-runs-python'
    # what a startup file doing anything with python amounts to, once the bundle has pointed it home
    shell.write_text("#!/bin/sh\nif [ -n \"$PYTHONHOME\" ]; then exit 1; fi\n"
                     "printf 'GITHUB_TOKEN=ghp-from-the-profile\\0'\n")
    shell.chmod(0o755)
    monkeypatch.setattr('kunda.pythons.sys.frozen', True, raising=False)
    monkeypatch.setattr(envs.os, 'environ', {'PYTHONHOME': '/Leela.app/Contents/Resources',
                                             'PYTHONPATH': '/Leela.app/python313.zip'})
    assert envs.shell_env(str(shell)) == {'GITHUB_TOKEN': 'ghp-from-the-profile'}

_TTY_PROBE = '''import fcntl, os, select, sys, termios
from pathlib import Path
fcntl.ioctl(0, termios.TIOCSCTTY, 0)
from leela.core.envs import shell_env
from leela.blocks.vault.jobs import run_script
from leela.blocks.agent.ai import WorkspaceHost
from leela.workspace import Workspace
root = sys.argv[1]
os.environ['BROWSER'] = root + '/browser'
from leela.blocks.browser.app import open_tab
got = shell_env(root + '/shell')
print(got['TTY'], got['CTTY'])
print(open_tab('http://example.invalid/'), Path(root, 'opened').read_text().strip())
nb = 'import fcntl, os; print(os.isatty(0)); fcntl.fcntl(0, fcntl.F_SETFL, os.O_NONBLOCK)'
print(run_script([sys.executable, '-c', nb])['stdout'].strip())
print(WorkspaceHost(Workspace(roots=[root])).run_cmd('[ -t 0 ] && echo True || echo False; head -c 2 >/dev/null')[1].strip())
print(bool(fcntl.fcntl(0, fcntl.F_GETFL) & os.O_NONBLOCK))
print(os.read(0, 9) if select.select([0], [], [], 1)[0] else b'', flush=True)
os._exit(0)
'''

def test_no_child_leela_spawns_shares_the_terminal(tmp_path):
    """A child holding the terminal as stdin can set it non-blocking and freeze the TUI that started Leela."""
    import os, pty
    shell = tmp_path/'shell'
    # `/dev/tty` opens for anything still in the session whose controlling terminal the pty is, as `zsh -i` does
    shell.write_text("#!/bin/sh\n[ -t 0 ] && t=True || t=False\n(: </dev/tty) 2>/dev/null && c=True || c=False\n"
                     "printf \"TTY=$t\\0CTTY=$c\\0\"\n")
    browser = tmp_path/'browser'
    browser.write_text(f"#!/bin/sh\n[ -t 0 ] && t=True || t=False\necho $t > {tmp_path/'opened'}\n")
    for f in (shell, browser): f.chmod(0o755)
    import termios
    m, s = pty.openpty()
    # no echo: a session leader exits only once its terminal's output drains, and nothing reads `m`
    a = termios.tcgetattr(s); a[3] &= ~termios.ECHO; termios.tcsetattr(s, termios.TCSANOW, a)
    os.write(m, b'x\n')  # a line waiting on the terminal, which only the parent may read
    try: got = subprocess.run([sys.executable, '-c', _TTY_PROBE, str(tmp_path)], stdin=s, capture_output=True, text=True,
                              timeout=60, start_new_session=True)  # the probe's own session, the pty its terminal
    finally: os.close(s); os.close(m)
    assert got.stdout.split()[-8:] == ['False', 'False', 'True', 'False', 'False', 'False', 'False', "b'x\\n'"], got.stderr[-2000:]

def test_a_browser_webbrowser_drives_itself_is_still_its_to_open(monkeypatch):
    "macOS's `osascript` path, and any browser with a remote protocol, is left to `webbrowser`."
    import webbrowser
    from leela.blocks.browser.app import open_tab
    class Mac(webbrowser.BaseBrowser):
        def open(self, url, new=0, autoraise=True): self.got = (url, new); return True
    b = Mac('safari')
    monkeypatch.setattr(webbrowser, 'get', lambda *a: b)
    assert open_tab('https://example.com/') and b.got == ('https://example.com/', 2)

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
    """One file, several windows."""
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

def test_writing_a_notebook_back_through_the_host_keeps_it_a_notebook(tmp_path):
    """`text_at` hands out a notebook as its `# %%` document, and `write` put that back verbatim."""
    import json
    nb = tmp_path/'demo.ipynb'
    nb.write_text(json.dumps({'cells': [
        {'cell_type': 'code', 'source': ['x = 1'], 'metadata': {}, 'id': 'aaa',
         'outputs': [{'output_type': 'stream', 'name': 'stdout', 'text': ['1']}], 'execution_count': 3},
        {'cell_type': 'markdown', 'source': ['# hi'], 'metadata': {}, 'id': 'bbb'}],
        'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    ws = Workspace(roots=[tmp_path])
    try:
        host = ws.ai.host
        before = host.text_at(str(nb))
        assert before.startswith('# %% code'), 'the read side is the document, which is the whole problem'
        host.write(str(nb), before)                      # what `rollback_turn` does
        d = json.loads(nb.read_text())
        assert len(d['cells']) == 2
        assert d['cells'][0]['outputs'], 'a cell still named keeps the outputs the document dropped'
        assert d['cells'][0]['execution_count'] == 3
        assert host.text_at(str(nb)) == before, 'and the document round-trips'
        host.write(str(nb), nb.read_text())              # real notebook JSON is still written as-is
        assert json.loads(nb.read_text())['cells'][0]['outputs']
    finally: ws.threads.shutdown()

def test_the_native_window_opens_on_the_saved_themes_background():
    "A family this build lacks is the default's, a theme that follows the system gives both, and a legacy name still resolves."
    from leela.blocks.settings.settings import theme_background, theme_backgrounds
    bgs = theme_backgrounds()
    assert theme_background('ember:dark:tight') == bgs['ember']['dark']
    assert theme_background('dusk:system:relaxed') == (bgs['dusk']['light'], bgs['dusk']['dark'])
    assert theme_background('retired:dark:tight') == bgs['cursor']['dark']
    assert theme_background('cursor:bogus:x') == bgs['cursor']['light']
    assert theme_background('dark') == bgs['leela']['dark']
    assert theme_background('') == bgs['cursor']['light']




def test_undo_leaves_the_cell_that_is_running_where_it_runs():
    """Undo rebuilt every cell as a copy. The run still held the old object, so the page lost the cell's `running`, its stop
    refused ("not running") and a second run waited on the first one's lock for ever."""
    from leela.blocks.nb.nb import Cell, Notebook
    nb = Notebook(); nb.cells[0].source = 'import time; time.sleep(60)'
    run = nb.cells[0]
    nb.insert(1, Cell(source='x = 1'))                  # a structural step to undo
    run.running = True                                  # what `nb.run` sets while the kernel works on it
    at = nb.undo()
    assert at is not None and any(c is run for c in nb.cells), 'the run holds this very object'
    assert run.running and nb.cells[0].running, 'the page is told it is still running'
    nb.redo()
    assert any(c is run for c in nb.cells) and run.running
    run.running = False
    nb.undo()
    assert not any(c.running for c in nb.cells)


def test_a_step_taken_while_a_cell_runs_does_not_bring_it_back_as_running():
    "The snapshot copied `running` too: undone later, the cell looked running with no run behind it, so stop found nothing and run refused."
    from leela.blocks.nb.nb import Cell, Notebook
    nb = Notebook(); run = nb.cells[0]; run.running = True
    nb.insert(1, Cell(source='x = 1'))                  # a snapshot while the cell is running
    run.running = False                                 # the run ends
    nb.undo()
    assert not any(c.running for c in nb.cells)
    nb.redo()
    assert not any(c.running for c in nb.cells)


def _running(*srcs):
    from leela.blocks.nb.nb import Cell, Notebook
    nb = Notebook([Cell(source=s) for s in srcs])
    return nb, list(nb.cells)

def test_undoing_a_split_of_the_running_cell_gives_its_text_back():
    "Keeping the live cell whole would have kept the shortened text: the second half of the split was lost for good."
    nb, (run,) = _running('first = 1\nsecond = 2')
    run.running = True
    nb.split(0, len('first = 1\n'))
    assert [c.source for c in nb.cells] == ['first = 1\n', 'second = 2']
    nb.undo()
    assert nb.cells[0] is run and run.source == 'first = 1\nsecond = 2' and run.running and len(nb.cells) == 1

def test_undo_refuses_a_step_that_would_remove_a_running_cell_and_keeps_the_step():
    "Removed, the run held the notebook's run lock with no cell on the page to stop. Refused, the step is still there once the run ends."
    import pytest
    from leela.blocks.nb.nb import Cell, RunningCellError
    nb, (a,) = _running('a')
    nb.insert(1, Cell(source='b')); b = nb.cells[1]; b.running = True
    with pytest.raises(RunningCellError, match='cell 2, which is running'):
        nb.undo()
    assert [c.source for c in nb.cells] == ['a', 'b'] and b.running
    b.running = False
    nb.undo()
    assert [c.source for c in nb.cells] == ['a'], 'the step was kept, and now goes'

def test_the_edit_route_says_why_an_undo_is_refused(tmp_path):
    root, p = _stop_rig(tmp_path); ws = Workspace(roots=[root])
    with TestClient(ide_app(ws)) as c:
        ws.open(p); tab, nb, _ = ws.docstore.owner(str(p))
        assert c.post('/nb/edit', json={'path': str(p), 'op': 'insert', 'i': 1}).json()['ok'] is not False
        nb.cells[1].running = True
        r = c.post('/nb/edit', json={'path': str(p), 'op': 'undo'})
        assert r.status_code == 409 and 'Stop it first' in r.json()['error']
        nb.cells[1].running = False
        assert len(c.post('/nb/edit', json={'path': str(p), 'op': 'undo'}).json()['cells']) == 1

def test_two_running_cells_both_survive_an_undo():
    from leela.blocks.nb.nb import Cell
    nb, (a, b) = _running('a', 'b')
    nb.insert(2, Cell(source='c'))
    a.running = b.running = True
    nb.undo()
    assert nb.cells[0] is a and nb.cells[1] is b and a.running and b.running and len(nb.cells) == 2

def test_a_snapshot_taken_mid_run_has_no_half_streamed_output():
    from leela.blocks.nb.nb import Cell
    nb, (run,) = _running('print(1)')
    run.running, run.outputs = True, [dict(output_type='stream', name='stdout', text='partial')]
    nb.insert(1, Cell(source='x'))
    run.running, run.outputs = False, [dict(output_type='stream', name='stdout', text='whole')]
    nb.undo()
    assert nb.cells[0].outputs == [] and not nb.cells[0].running

def _stop_rig(tmp_path, cell_type='code'):
    root = Path(tmp_path).resolve()
    p = root/'n.ipynb'
    p.write_text(json.dumps({'cells': [{'cell_type': cell_type, 'id': 'a', 'metadata': {}, 'source': '1', 'outputs': [], 'execution_count': None}] if cell_type == 'code'
                             else [{'cell_type': 'code', 'id': 'a', 'metadata': {}, 'source': '1', 'outputs': [], 'execution_count': None}],
                             'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    return root, p

def test_stop_clears_a_running_mark_that_has_no_run_behind_it(tmp_path):
    root, p = _stop_rig(tmp_path); ws = Workspace(roots=[root])
    with TestClient(ide_app(ws)) as c:
        ws.open(p); tab, nb, _ = ws.docstore.owner(str(p))
        nb.cells[0].running = True
        r = c.post('/nb/interrupt', json={'path': str(p), 'id': 'a'}).json()
        assert r['ok'] and r['stopped'] == 'stale' and not nb.cells[0].running
        assert c.post('/nb/interrupt', json={'path': str(p), 'id': 'a'}).json().get('ok') is not True, 'nothing left to stop'

def test_stop_leaves_a_mark_alone_while_the_tab_counts_a_run(tmp_path):
    "A cell run through the other route has no entry of its own, but the tab counts it."
    root, p = _stop_rig(tmp_path); ws = Workspace(roots=[root])
    with TestClient(ide_app(ws)) as c:
        ws.open(p); tab, nb, _ = ws.docstore.owner(str(p))
        nb.cells[0].running, tab.running = True, 1
        assert c.post('/nb/interrupt', json={'path': str(p), 'id': 'a'}).json().get('ok') is not True
        assert nb.cells[0].running
