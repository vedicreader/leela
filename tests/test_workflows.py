"Workflows: reading them, building them, and the jobs they become."

import pytest
from leela.blocks.workflows.workflows import WorkflowError, Workflows, levels
import time
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.blocks.vault.jobs import JobError, Jobs
from leela.workspace import Workspace
from leela.blocks.workflows.wfbuild import PRESETS, TRIGGERS, compose, load_spec, preset_rows, save_spec

def fastship_recipe():
    """Skip unless the installed gheasy carries the fastship release recipe.

    Both halves of it are gheasy's to write -- the standalone `fastship_release` and the
    `fastship_release_job` on the builder -- and no published gheasy has them yet. Leela asks for
    the recipe and says what is missing when it is absent; it does not keep a copy of one.
    """
    pytest.importorskip('gheasy')
    from gheasy.workflow import WorkflowBuilder
    import gheasy.workflow as w
    if not (hasattr(w, 'fastship_release') and hasattr(WorkflowBuilder, 'fastship_release_job')):
        pytest.skip('this gheasy has no fastship release recipe; needs gheasy >= 0.0.8')

def workflow(root, name='ci.yml', text=''):
    d = root/'.github'/'workflows'
    d.mkdir(parents=True, exist_ok=True)
    (d/name).write_text(text)
    return d/name

CI = """
name: build and ship
on:
  push:
    branches: [main, release]
  workflow_dispatch:
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Ruff
        run: ruff check .
  test:
    needs: lint
    runs-on: ubuntu-latest
    steps:
      - name: Test
        run: pytest
  publish:
    needs: [test, lint]
    environment:
      name: pypi
    if: github.event_name == 'release'
    runs-on: ubuntu-latest
    steps:
      - name: Publish
        run: uv publish
"""

def test_a_workflow_becomes_jobs_edges_and_triggers(tmp_path):
    workflow(tmp_path, text=CI)
    wf = Workflows(tmp_path).parsed()[0]
    assert not wf['error'] and wf['name'] == 'build and ship'
    assert wf['dispatchable'], 'the panel offers a run button only when the file allows one'
    push = next(t for t in wf['triggers'] if t['event'] == 'push')
    assert push['detail'] == 'branches: main, release'
    jobs = {j['id']: j for j in wf['jobs']}
    assert jobs['publish']['needs'] == ['test', 'lint']
    assert jobs['publish']['environment'] == 'pypi'
    assert jobs['publish']['if'] == "github.event_name == 'release'"
    assert [s['name'] for s in jobs['lint']['steps']] == ['actions/checkout@v4', 'Ruff']

def test_on_is_read_even_though_yaml_turns_it_into_a_boolean(tmp_path):
    "The sharpest edge in the format: YAML 1.1 parses a bare `on:` key as `True`."
    workflow(tmp_path, text='name: x\non: [push]\njobs: {}\n')
    wf = Workflows(tmp_path).parsed()[0]
    assert [t['event'] for t in wf['triggers']] == ['push']

def test_a_workflow_is_drawn_as_jobs_and_the_edges_between_them():
    jobs = [{'id': 'a', 'needs': []}, {'id': 'b', 'needs': ['a']},
            {'id': 'c', 'needs': []}, {'id': 'd', 'needs': ['b', 'c']}]
    assert levels(jobs) == [['a', 'c'], ['b'], ['d']]
    jobs = [{'id': 'a', 'needs': ['b']}, {'id': 'b', 'needs': ['a']}, {'id': 'ok', 'needs': []}]
    rows = levels(jobs)
    assert rows[0] == ['ok'] and sorted(rows[-1]) == ['a', 'b']



def test_a_broken_file_reports_its_error_instead_of_losing_the_others(tmp_path):
    workflow(tmp_path, 'good.yml', CI)
    workflow(tmp_path, 'broken.yml', 'name: x\n  bad indent: [\n')
    rows = {w['file']: w for w in Workflows(tmp_path).parsed()}
    assert rows['broken.yml']['error'] and not rows['good.yml']['error']

def test_a_project_with_no_workflows_is_empty_not_an_error(tmp_path):
    assert Workflows(tmp_path).parsed() == []

def test_status_says_which_piece_is_missing(tmp_path):
    "Three different failures need three different things done about them."
    st = Workflows(tmp_path).status()
    assert set(st) >= {'gheasy', 'dockeasy', 'repo', 'token', 'gh_cli', 'why'}
    if st['gheasy']:
        assert st['repo'] == '' and 'no GitHub remote' in st['why']
    else:
        assert 'gheasy' in st['why'], 'the message has to say what to install'

def test_generating_without_a_gheasy_config_is_refused_clearly(tmp_path):
    with pytest.raises(WorkflowError, match='no .gheasy/config.json|leela\\[github\\]'):
        Workflows(tmp_path).generate()

def test_pushing_env_needs_a_declared_schema(tmp_path):
    "gheasy's rule, kept: an undeclared key is not guessed at."
    pytest.importorskip('gheasy')
    with pytest.raises(WorkflowError, match='env_schema|GitHub CLI'):
        Workflows(tmp_path).push_env({'A': '1'}, ['A'])

def test_the_docker_answer_never_raises(tmp_path):
    "The panel asks this on every open; an undetectable project is an answer, not a failure."
    row = Workflows(tmp_path).docker()
    assert row['dockerfile'] is False
    assert row['why'] or row['base'], 'either it detected something or it said why not'

def test_the_catalogue_recommends_from_what_the_project_is(tmp_path):
    "The one judgement neither gheasy nor dockeasy can make for you."
    pytest.importorskip('gheasy')
    root = tmp_path/'p'
    root.mkdir()
    (root/'pyproject.toml').write_text('[project]\nname = "p"\nversion = "0"\n\n[tool.nbdev]\n')
    rows = {r['id']: r for r in Workflows(root).catalogue()['workflows']}
    assert rows['nbdev']['recommended'] and not rows['ci']['recommended'], 'nbdev CI, not plain CI'
    assert not rows['pages']['recommended'], 'no node build here'
    assert all(not r['present'] for r in rows.values())

def test_a_python_package_that_is_not_nbdev_is_offered_the_fastship_release(tmp_path):
    "The gheasy catalogue in the panel: fastship's release for a package nbdev does not own."
    pytest.importorskip('gheasy')
    root = tmp_path/'p'
    root.mkdir()
    (root/'pyproject.toml').write_text('[project]\nname = "p"\nversion = "0"\n\n'
                                       '[build-system]\nrequires = ["hatchling"]\n')
    cat = Workflows(root).catalogue()
    assert cat['detect']['fastship'] and not cat['detect']['nbdev']
    rows = {r['id']: r for r in cat['workflows']}
    assert rows['fastship']['recommended'] and rows['fastship']['file'] == 'release.yml'
    assert not rows['pypi']['recommended'], 'the fastship release publishes; the release-event one would double up'
    assert not rows['nbdev']['recommended']
    nb = tmp_path/'nb'
    nb.mkdir()
    (nb/'pyproject.toml').write_text('[project]\nname = "n"\nversion = "0"\n\n[tool.nbdev]\n')
    nbrows = {r['id']: r for r in Workflows(nb).catalogue()['workflows']}
    assert not nbrows['fastship']['recommended'], 'nbdev releases with nbdev'

def test_the_fastship_release_previews_and_writes_as_release_yml(tmp_path):
    fastship_recipe()
    root = tmp_path/'p'
    root.mkdir()
    (root/'pyproject.toml').write_text('[project]\nname = "p"\nversion = "0"\n')
    wf = Workflows(root)
    text = wf.preview('fastship')
    assert 'v*' in text and 'gh release create' in text and 'gh-action-pypi-publish' in text
    assert not wf.files(), 'previewing writes nothing'
    assert wf.add('fastship')['path'].endswith('release.yml')
    parsed = wf.parsed()[0]
    assert [j['id'] for j in parsed['jobs']] == ['test', 'release']
    assert any(t['event'] == 'push' and 'v*' in t['detail'] for t in parsed['triggers'])

def test_a_catalogue_entry_previews_before_it_is_written(tmp_path):
    pytest.importorskip('gheasy')
    root = tmp_path/'p'
    root.mkdir()
    (root/'pyproject.toml').write_text('[project]\nname = "p"\nversion = "0"\n\n[tool.nbdev]\n')
    wf = Workflows(root)
    text = wf.preview('nbdev')
    assert 'nbdev_test' in text and 'name:' in text
    assert not wf.files(), 'previewing writes nothing'
    written = wf.add('nbdev')
    assert written['path'].endswith('ci.yml')
    parsed = wf.parsed()[0]
    assert [j['id'] for j in parsed['jobs']] == ['test'], 'and it reads back as a workflow'
    with pytest.raises(WorkflowError, match='already exists'):
        wf.add('nbdev')

def test_the_deploy_workflow_is_the_projects_schema_rendered(tmp_path):
    "lego's `gen_deploy_workflow`, with the key list read rather than written down."
    pytest.importorskip('gheasy')
    from gheasy.core import GheasyConfig
    root = tmp_path/'p'
    root.mkdir()
    (root/'pyproject.toml').write_text('[project]\nname = "p"\nversion = "0"\n')
    GheasyConfig(app='p', env_schema={'DOMAIN': None, 'PORT': '5001'}).save(str(root))
    text = Workflows(root).preview('deploy')
    assert 'DOMAIN: ${{ secrets.DOMAIN }}' in text
    assert 'PORT: ${{ vars.PORT }}' in text
    assert 'DEPLOY_KEY: ${{ secrets.DEPLOY_KEY }}' in text
    assert 'python deploy.py deploy' in text

class _AsyncOps:
    "ghapi 2's default client: every operation is a coroutine function."
    async def list_repo_secrets(self, **kw): return {'secrets': [{'name': 'A', 'updated_at': 'x'}]}
    async def list_repo_variables(self, **kw): return {'variables': [{'name': 'B', 'value': '1'}]}
    async def list_workflow_runs_for_repo(self, **kw): return {'workflow_runs': [{'id': 1}]}

class _SyncOps:
    def list_repo_secrets(self, **kw): return {'secrets': [{'name': 'A', 'updated_at': 'x'}]}
    def list_repo_variables(self, **kw): return {'variables': [{'name': 'B', 'value': '1'}]}
    def list_workflow_runs_for_repo(self, **kw): return {'workflow_runs': [{'id': 1}]}

class _Api:
    def __init__(self, sync=False): self.actions = _SyncOps() if sync else _AsyncOps()

class _Core:
    "As much of gheasy.core as `Workflows._api` uses, over a client that is async by default."
    GhApi = staticmethod(lambda owner=None, repo=None, token=None, sync=False: _Api(sync=sync))
    gh_token = staticmethod(lambda: 'token')
    gh_api = staticmethod(lambda token, path: ('o', 'r', _Api()))

def test_github_calls_get_the_synchronous_client(tmp_path, monkeypatch):
    "Left async, every call returns a coroutine and Environment's refresh raises on `.get`."
    monkeypatch.setattr('pullup.workflows._gheasy', lambda: _Core)
    wf = Workflows(tmp_path)
    assert wf.remote_env() == {'secrets': [{'name': 'A', 'updated_at': 'x'}],
                               'variables': [{'name': 'B', 'value': '1', 'updated_at': ''}]}
    assert [r['id'] for r in wf.runs()] == [1]

OPENAPI = '''openapi: 3.0.0
info: {title: Widgets, version: "2.1"}
paths:
  /widgets:
    get: {operationId: listWidgets, summary: List widgets, tags: [widgets]}
    post: {operationId: makeWidget, summary: Create a widget, tags: [widgets]}
  /widgets/{id}:
    get:
      operationId: getWidget
      summary: One widget
      tags: [widgets]
      parameters: [{name: id, in: path, required: true}]
'''

DISCOVERY = '''{"discoveryVersion": "v1", "title": "Drive", "version": "v3",
  "baseUrl": "https://www.googleapis.com/drive/v3/",
  "resources": {"files": {"methods": {
    "list": {"id": "drive.files.list", "path": "files", "httpMethod": "GET"},
    "get": {"id": "drive.files.get", "path": "files/{fileId}", "httpMethod": "GET",
            "parameters": {"fileId": {"type": "string", "required": true, "location": "path"}}}}}}}
'''

@pytest.fixture
def proj(tmp_path):
    p = tmp_path/'proj'
    (p/'src').mkdir(parents=True)
    (p/'notes.md').write_text('# Notes\n\nDurable prose about recall and ranking.\n')
    (p/'minute.md').write_text('# Minute\n\nSigned by Dr Charles Babbage.\n')
    (p/'src'/'m.py').write_text('def f(x):\n    return x + 1\n')
    (p/'api.yaml').write_text(OPENAPI)
    (p/'drive.json').write_text(DISCOVERY)
    return p

@pytest.fixture
def ws(proj): return Workspace(roots=[proj])

def _finish(jobs, jid, tries=200):
    for _ in range(tries):
        j = jobs.get(jid)
        if not j.active: return j
        time.sleep(0.05)
    raise AssertionError(f'job {jid} never finished: {jobs.get(jid).dict()}')

def _run(ws, kind, target=''): return _finish(ws.jobs, ws.jobs.start(kind, target).id)

def test_the_three_clip_kinds_each_store_the_shape_that_suits_them(ws, proj):
    "A document is prose, a codebase is a pointer, a spec is one section per operation."
    job = _run(ws, 'clip', str(proj))
    assert job.status == 'complete' and job.progress == 1.0
    assert len(job.result['files']) == 2, 'the markdown; .py and .json are not documents'
    assert 'titled names' in job.result['pii']['covers'], 'the badge never claims more'
    assert job.result['pii']['kinds'].get('person') == 1, 'Dr Charles Babbage, from minute.md'
    assert ws.memory.search('recall and ranking')
    before = ws.memory.shelves()[0]['docs']
    job = _run(ws, 'clip_codebase', str(proj))
    assert job.status == 'complete' and job.result['types']['.py'] == 1
    assert ws.memory.shelves()[0]['docs'] == before + 1, 'one pointer, not one document per file'
    titles = [d['title'] for d in ws.memory.documents()]
    assert any(t.startswith('Codebase: ') for t in titles)
    assert 'm.py' not in titles, 'the source itself did not land in the shelf'
    job = _run(ws, 'clip_api_spec', str(proj/'api.yaml'))
    assert job.status == 'complete', job.error
    assert (job.result['title'], job.result['operations']) == ('Widgets', 3)
    body = str(ws.memory.exact_text(_titled(ws, 'API: Widgets')))
    for want in ('## GET /widgets', '## POST /widgets', '## GET /widgets/{id}', 'required: id'):
        assert want in body, f'{want} is not addressable on its own'
    job = _run(ws, 'clip_api_spec', str(proj/'drive.json'))
    assert job.status == 'complete', job.error
    assert (job.result['title'], job.result['operations']) == ('Drive', 2)
    assert 'files/{fileId}' in str(ws.memory.exact_text(_titled(ws, 'API: Drive')))

def _titled(ws, prefix):
    d = next(d for d in ws.memory.documents() if str(d['title']).startswith(prefix))
    return d.get('doc_id') or d.get('id')

def test_a_job_row_survives_a_restart_a_failure_and_an_L(tmp_path):
    "What the row guarantees, without a workspace."
    from fastcore.all import L
    jobs = Jobs(tmp_path/'jobs.db')
    fails = {'now': True}
    def flaky(job, report):
        if fails['now']: raise ValueError('the disk was not there')
        return dict(results=L([dict(status='ok'), dict(status='ok')]))
    jobs.register('resumable', lambda job, report: dict(ok=True))
    jobs.register('oneshot', lambda job, report: dict(ok=True))
    jobs.register('flaky', flaky)
    a, b = jobs.new('resumable', 'x', _resume={'done': ['one']}), jobs.new('oneshot', 'y')
    for j in (a, b): jobs.update(j.id, status='running')
    fresh = Jobs(tmp_path/'jobs.db')
    fresh._handlers = dict(jobs._handlers)
    got = fresh.recover()
    assert (got['resumed'], got['failed']) == ([a.id], [b.id])
    assert 'restart' in fresh.get(b.id).error
    assert _finish(fresh, a.id).status == 'complete'
    j = _finish(jobs, jobs.start('flaky').id)
    assert j.status == 'error'
    assert j.error == 'ValueError: the disk was not there', 'the type name appears once'
    fails['now'] = False
    j = _finish(jobs, jobs.launch(j.id).id)
    assert j.result['results'] == [dict(status='ok')] * 2, 'stored as rows, not as a repr'
    with pytest.raises(JobError): jobs.new('nosuchkind')

def test_a_script_runs_with_no_shell_and_reports_its_exit(ws):
    "`shlex` splits the target, so a quoted argument stays one argument and `;` is not a command."
    import sys
    j = _run(ws, 'script', f'{sys.executable} -c "print(6*7)"')
    assert j.status == 'complete', j.error
    assert '42' in j.result['stdout'] and j.result['argv'][-1] == 'print(6*7)'
    j = _run(ws, 'script', f'{sys.executable} -c "raise SystemExit(3)"')
    assert j.status == 'error' and 'exited 3' in j.error

def test_the_clip_surface_is_forms_and_the_progress_loop_ends_itself(ws, proj):
    "Every action posts and swaps in what it changed, so the browser holds no state."
    with TestClient(ide_app(ws)) as c:
        assert c.get('/vault/panel').status_code == 200
        r = c.post('/clip', data=dict(target=str(proj/'notes.md'), kind='clip'))
        assert r.status_code == 200 and 'hx-get' in r.text.lower()
        jid = ws.jobs.all()[0].id
        assert _finish(ws.jobs, jid).status == 'complete'
        assert 'hx-get' not in c.get(f'/jobs/{jid}').text.lower(), 'a finished card asks for nothing'
        watched = c.post('/vault/watch', data=dict(target='read the notes', action='remind', every='1d'))
        assert watched.status_code == 200 and len(ws.memory.watches()) == 1
        gone = c.post('/vault/unwatch', data=dict(watch_id=ws.memory.watches()[0]['id']))
        assert gone.status_code == 200 and ws.memory.watches() == []
        assert c.post('/vault/watch', data=dict(target=' ', action='remind')).status_code == 400

def test_a_judgement_round_trips_from_the_row_that_carried_it(ws, proj):
    "The tidy row posts `noisy` as a form string, and `keep` must not arrive as `drop`."
    with TestClient(ide_app(ws)) as c:
        ws.memory.clip([proj/'notes.md'])
        doc = (ws.memory.documents() or [{}])[0]
        did = doc.get('doc_id') or doc.get('id')
        assert 'vaulttidy' in c.get('/vault/tidy/list').text
        dropped = c.post('/vault/noisy', data=dict(doc=did, noisy='true'))
        assert dropped.status_code == 200 and 'dropped from search' in dropped.text
        assert ws.memory._open().marks(did).get('noisy') == 1
        kept = c.post('/vault/noisy', data=dict(doc=did, noisy='false'))
        assert kept.status_code == 200 and 'kept' in kept.text
        assert ws.memory._open().marks(did).get('noisy') == 0, 'keep must clear, not set'
        badge = c.get('/vault/pii/badge', params=dict(doc=did))
        assert badge.status_code == 200 and 'lee-pii' in badge.text

def yaml_of(spec, **kw): return compose(spec, **kw)

@pytest.mark.skipif(__import__('importlib.util', fromlist=['x']).find_spec('gheasy') is None, reason='the builder composes with gheasy')
def test_the_vocabulary_is_data_so_the_form_needs_no_frontend_change():
    rows = preset_rows()
    assert rows['presets'] is PRESETS and rows['triggers'] is TRIGGERS
    for p in PRESETS:
        assert {'id', 'job', 'name', 'doc', 'options'} <= set(p)
        for o in p['options']:
            assert o['type'] in ('text', 'list', 'lines', 'flag'), f"{p['id']}.{o['key']}"
            assert 'default' in o and 'label' in o

@pytest.mark.skipif(__import__('importlib.util', fromlist=['x']).find_spec('gheasy') is None, reason='the builder composes with gheasy')
def test_a_built_spec_becomes_the_yaml_gheasy_would_have_written():
    text = yaml_of({'name': 'ci', 'on': {'push': 'main, release', 'workflow_dispatch': True,
                                         'release': True, 'schedule': '0 9 * * 1'}, 'jobs': []})
    assert 'branches:\n      - main\n      - release' in text
    assert 'workflow_dispatch:' in text
    assert 'types:\n      - published' in text
    assert "cron: 0 9 * * 1" in text or "- cron: '0 9 * * 1'" in text or '0 9 * * 1' in text
    assert 'workflow_dispatch' in yaml_of({'name': 'ci', 'on': {}, 'jobs': []})
    text = yaml_of({'name': 'ci', 'on': {'push': 'main'},
                    'jobs': [{'preset': 'uv_lint'},
                             {'preset': 'uv_test', 'needs': ['lint']},
                             {'preset': 'uv_pypi', 'needs': ['test']}]})
    assert text.index('lint:') < text.index('test:') < text.index('publish:')
    assert text.count('needs:') == 2
    text = yaml_of({'name': 'ci', 'on': {'push': 'main'},
                    'jobs': [{'preset': 'run', 'options': {'cmds': 'echo one'}},
                             {'preset': 'run', 'options': {'cmds': 'echo two'}}]})
    assert '  run:' in text and '  run2:' in text
    assert 'echo one' in text and 'echo two' in text
    text = yaml_of({'name': 'ci', 'on': {'push': 'main'},
                    'jobs': [{'preset': 'uv_test',
                              'options': {'test_cmd': 'pytest -x', 'python_versions': '3.11, 3.12'}}]})
    assert 'uv run pytest -x' in text
    assert "- '3.11'" in text and "- '3.12'" in text
    text = yaml_of({'name': 'deploy', 'on': {'push': 'main'}, 'jobs': [{'preset': 'deploy'}]},
                   schema={'DOMAIN': None, 'PORT': '5001'}, app='kalpa')
    assert 'DOMAIN: ${{ secrets.DOMAIN }}' in text and 'PORT: ${{ vars.PORT }}' in text
    assert 'DEPLOY_KEY' in text and 'python deploy.py deploy' in text
    assert 'SERVER_NAME:-kalpa' in text
    text = yaml_of({'name': 'ci', 'on': {'push': 'main'},
                    'jobs': [{'preset': 'nonsense'}, {'preset': 'uv_test'}]})
    assert 'test:' in text and 'nonsense' not in text
    # A tag trigger and a branch trigger share one `push:` block, and the tag default is what
    # `ship-release` pushes.
    text = yaml_of({'name': 'release', 'on': {'tags': 'v*'}, 'jobs': []})
    assert 'tags:\n      - v*' in text and 'branches:' not in text
    text = yaml_of({'name': 'both', 'on': {'push': 'main', 'tags': True}, 'jobs': []})
    assert 'branches:\n      - main' in text and 'tags:\n      - v*' in text

def test_the_fastship_job_is_gheasys_own_recipe():
    "Leela only asks for it, so what it renders is gheasy's to assert. See `fastship_recipe`."
    fastship_recipe()
    text = yaml_of({'name': 'release', 'on': {'tags': 'v*'}, 'jobs': [{'preset': 'fastship'}]})
    assert 'gh release create' in text and 'gh-action-pypi-publish' in text
    assert 'contents: write' in text and 'id-token: write' in text








@pytest.mark.skipif(__import__('importlib.util', fromlist=['x']).find_spec('gheasy') is None, reason='the builder composes with gheasy')
def test_the_spec_is_kept_beside_the_file_it_produced(tmp_path):
    "Reading YAML back into a spec is lossy, so the builder reopens what you built."
    spec = {'name': 'ci', 'on': {'push': 'main'}, 'jobs': [{'preset': 'uv_test'}]}
    save_spec(tmp_path, 'ci.yml', spec)
    assert load_spec(tmp_path, 'ci.yml') == spec
    assert load_spec(tmp_path, 'other.yml') is None
