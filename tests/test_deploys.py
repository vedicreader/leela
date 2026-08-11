"""The deploy pipeline: where it goes, what it is missing, and the first `deploy.py`.

The running is `tests/test_releases.py`'s subject -- both are the same `Pipeline`. What is
here is the deploy-shaped part: the target read from the same store the stages will read,
and the scaffold, which has to produce a script that imports the four libraries it claims to
and a workflow that matches the schema it wrote.
"""

import ast

import pytest

from leela.deploys import DEPLOY_KEYS, Deploy, DeployError, deploy_template


def project(root, name='app'):
    root.mkdir(parents=True, exist_ok=True)
    (root/'pyproject.toml').write_text(f'[project]\nname = "{name}"\nversion = "0"\n')
    return root


def test_the_default_stages_are_the_projects_own_deploy_script(tmp_path):
    "Leela runs `deploy.py`, it does not drive vpseasy from inside the editor."
    state = Deploy(project(tmp_path/'p')).state()
    assert [s['cmd'] for s in state['steps']] == ['python deploy.py env', 'python deploy.py compose',
                                                  'python deploy.py deploy']
    assert state['kind'] == 'deploy'
    assert 'HCLOUD_TOKEN' in state['steps'][-1]['needs']


def test_the_target_reports_what_is_missing_before_anything_runs(tmp_path):
    t = Deploy(project(tmp_path/'p')).target()
    assert not t['script'] and not t['compose']
    assert set(t['missing']) >= {'HCLOUD_TOKEN', 'CLOUDFLARE_API_TOKEN'}
    assert t['keys']['HCLOUD_TOKEN'] is True and t['keys']['PORT'] is False, 'secret vs variable'


def test_the_scaffold_writes_a_script_that_imports_the_libraries_it_claims(tmp_path):
    root = project(tmp_path/'p', 'kalpa')
    out = Deploy(root).scaffold(domain='example.com', subdomain='kalpa')
    text = (root/'deploy.py').read_text()
    ast.parse(text)                                     # it has to be a Python file
    for imported in ('from dockeasy import', 'from cfeasy import CF', 'from vpseasy import'):
        assert imported in text
    for cmd in ('env', 'compose', 'deploy', 'nuke'):
        assert f"cmd == '{cmd}'" in text
    assert 'kalpa.example.com' in text, "the host is this project's, not a placeholder"
    assert any(p.endswith('deploy.py') for p in out['written'])
    assert Deploy(root).target()['script']


def test_the_scaffold_declares_the_schema_and_the_workflow_together(tmp_path):
    """The three files have to agree: the workflow's `env:` is the schema it just wrote.

    Writing the script without the schema leaves a deploy that CI cannot run, which is the
    failure this exists to prevent.
    """
    pytest.importorskip('gheasy')
    root = project(tmp_path/'p')
    Deploy(root).scaffold(domain='example.com')
    from gheasy.core import GheasyConfig
    schema = GheasyConfig.load(str(root)).env_schema
    assert set(schema) >= set(DEPLOY_KEYS)
    workflow = (root/'.github'/'workflows'/'deploy.yml').read_text()
    for key, default in DEPLOY_KEYS.items():
        assert f'{key}: ${{{{ {"secrets" if default is None else "vars"}.{key} }}}}' in workflow


def test_a_deploy_script_is_not_overwritten_by_accident(tmp_path):
    root = project(tmp_path/'p')
    (root/'deploy.py').write_text('# mine\n')
    with pytest.raises(DeployError, match='already has a deploy.py'):
        Deploy(root).scaffold(domain='example.com')
    assert (root/'deploy.py').read_text() == '# mine\n'
    Deploy(root).scaffold(domain='example.com', force=True)
    assert 'vpseasy' in (root/'deploy.py').read_text()


def test_a_deploy_needs_somewhere_to_go(tmp_path):
    with pytest.raises(DeployError, match='domain is required'):
        Deploy(project(tmp_path/'p')).scaffold(domain='')


def test_the_template_names_the_apex_when_there_is_no_subdomain():
    assert "host = 'example.com'" in deploy_template('app', 'example.com', '')
    assert "host = 'app.example.com'" in deploy_template('app', 'example.com', 'app')
