"""Reading GitHub Actions files, which is the only part of the panel that is Leela's.

Everything that talks *to* GitHub belongs to gheasy and is exercised there. What is under
test here is the reading: the traps in the file format, the graph the panel draws from it,
and the promise that a project with none of the optional packages installed still gets a
usable answer instead of a stack trace.
"""

import pytest

from leela.blocks.workflows.workflows import WorkflowError, Workflows, levels


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
    assert jobs['publish']['environment'] == 'pypi'      # the mapping form, not just the string
    assert jobs['publish']['if'] == "github.event_name == 'release'"
    assert [s['name'] for s in jobs['lint']['steps']] == ['actions/checkout@v4', 'Ruff']


def test_on_is_read_even_though_yaml_turns_it_into_a_boolean(tmp_path):
    """The sharpest edge in the format: YAML 1.1 parses a bare `on:` key as `True`.

    A reader that looks up `'on'` finds nothing, reports a workflow with no triggers, and
    hides the run button on every file in the repository.
    """
    workflow(tmp_path, text='name: x\non: [push]\njobs: {}\n')
    wf = Workflows(tmp_path).parsed()[0]
    assert [t['event'] for t in wf['triggers']] == ['push']


def test_jobs_are_laid_out_below_the_last_thing_they_wait_for():
    jobs = [{'id': 'a', 'needs': []}, {'id': 'b', 'needs': ['a']},
            {'id': 'c', 'needs': []}, {'id': 'd', 'needs': ['b', 'c']}]
    assert levels(jobs) == [['a', 'c'], ['b'], ['d']]


def test_a_needs_cycle_is_drawn_rather_than_refused():
    "GitHub rejects the file; a panel that renders nothing tells you less than one that does."
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
        assert 'leela[github]' in st['why'], 'the message has to say what to install'


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
    """The one judgement neither gheasy nor dockeasy can make for you.

    gheasy knows how to build a Docker workflow; whether this repository has anything to put
    in an image is a fact about the project, and that is all the catalogue decides.
    """
    pytest.importorskip('gheasy')
    root = tmp_path/'p'
    root.mkdir()
    (root/'pyproject.toml').write_text('[project]\nname = "p"\nversion = "0"\n\n[tool.nbdev]\n')
    rows = {r['id']: r for r in Workflows(root).catalogue()['workflows']}
    assert rows['nbdev']['recommended'] and not rows['ci']['recommended'], 'nbdev CI, not plain CI'
    assert not rows['pages']['recommended'], 'no node build here'
    assert all(not r['present'] for r in rows.values())


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
    """lego's `gen_deploy_workflow`, with the key list read rather than written down.

    A key added to `env_schema` has to appear in the workflow the next time it is generated;
    that is the whole reason for generating it rather than editing YAML.
    """
    pytest.importorskip('gheasy')
    from gheasy.core import GheasyConfig
    root = tmp_path/'p'
    root.mkdir()
    (root/'pyproject.toml').write_text('[project]\nname = "p"\nversion = "0"\n')
    GheasyConfig(app='p', env_schema={'DOMAIN': None, 'PORT': '5001'}).save(str(root))
    text = Workflows(root).preview('deploy')
    assert 'DOMAIN: ${{ secrets.DOMAIN }}' in text      # None in the schema means secret
    assert 'PORT: ${{ vars.PORT }}' in text             # a default means variable
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
    _resolve_gh_token = staticmethod(lambda: 'token')
    _gh_api = staticmethod(lambda token, path: ('o', 'r', _Api()))


def test_github_calls_get_the_synchronous_client(tmp_path, monkeypatch):
    "Left async, every call returns a coroutine and Environment's refresh raises on `.get`."
    monkeypatch.setattr('leela.blocks.workflows.workflows._gheasy', lambda: _Core)
    wf = Workflows(tmp_path)
    assert wf.remote_env() == {'secrets': [{'name': 'A', 'updated_at': 'x'}],
                               'variables': [{'name': 'B', 'value': '1', 'updated_at': ''}]}
    assert [r['id'] for r in wf.runs()] == [1]
