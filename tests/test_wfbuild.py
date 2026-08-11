"""The builder: a spec in, gheasy's YAML out.

What is worth testing is not the YAML -- gheasy's presets are gheasy's to get right -- but
the translation. A form produces partial, duplicated and contradictory specs all day long,
and each of those has one correct reading.
"""

import pytest

from leela.wfbuild import PRESETS, TRIGGERS, compose, load_spec, preset_rows, save_spec

pytestmark = pytest.mark.skipif(__import__('importlib.util', fromlist=['x']).find_spec('gheasy') is None,
                                reason='the builder composes with gheasy')


def yaml_of(spec, **kw): return compose(spec, **kw)


def test_the_vocabulary_is_data_so_the_form_needs_no_frontend_change():
    rows = preset_rows()
    assert rows['presets'] is PRESETS and rows['triggers'] is TRIGGERS
    for p in PRESETS:
        assert {'id', 'job', 'name', 'doc', 'options'} <= set(p)
        for o in p['options']:
            assert o['type'] in ('text', 'list', 'lines', 'flag'), f"{p['id']}.{o['key']}"
            assert 'default' in o and 'label' in o


def test_triggers_come_out_in_the_shape_the_file_format_wants():
    text = yaml_of({'name': 'ci', 'on': {'push': 'main, release', 'workflow_dispatch': True,
                                         'release': True, 'schedule': '0 9 * * 1'}, 'jobs': []})
    assert 'branches:\n      - main\n      - release' in text
    assert 'workflow_dispatch:' in text
    assert 'types:\n      - published' in text
    assert "cron: 0 9 * * 1" in text or "- cron: '0 9 * * 1'" in text or '0 9 * * 1' in text


def test_a_workflow_with_no_triggers_gets_a_run_button_rather_than_never_running():
    "A file that nothing can start is a file that silently does nothing."
    assert 'workflow_dispatch' in yaml_of({'name': 'ci', 'on': {}, 'jobs': []})


def test_jobs_wire_up_by_needs():
    text = yaml_of({'name': 'ci', 'on': {'push': 'main'},
                    'jobs': [{'preset': 'uv_lint'},
                             {'preset': 'uv_test', 'needs': ['lint']},
                             {'preset': 'uv_pypi', 'needs': ['test']}]})
    assert text.index('lint:') < text.index('test:') < text.index('publish:')
    assert text.count('needs:') == 2


def test_two_jobs_of_the_same_kind_do_not_collide():
    """A duplicate job id is a file GitHub rejects, for a reason the person who clicked
    "add job" twice could not be expected to see."""
    text = yaml_of({'name': 'ci', 'on': {'push': 'main'},
                    'jobs': [{'preset': 'run', 'options': {'cmds': 'echo one'}},
                             {'preset': 'run', 'options': {'cmds': 'echo two'}}]})
    assert '  run:' in text and '  run2:' in text
    assert 'echo one' in text and 'echo two' in text


def test_options_reach_the_preset():
    text = yaml_of({'name': 'ci', 'on': {'push': 'main'},
                    'jobs': [{'preset': 'uv_test',
                              'options': {'test_cmd': 'pytest -x', 'python_versions': '3.11, 3.12'}}]})
    assert 'uv run pytest -x' in text
    assert "- '3.11'" in text and "- '3.12'" in text


def test_the_deploy_job_renders_the_schema_it_is_given():
    text = yaml_of({'name': 'deploy', 'on': {'push': 'main'}, 'jobs': [{'preset': 'deploy'}]},
                   schema={'DOMAIN': None, 'PORT': '5001'}, app='kalpa')
    assert 'DOMAIN: ${{ secrets.DOMAIN }}' in text and 'PORT: ${{ vars.PORT }}' in text
    assert 'DEPLOY_KEY' in text and 'python deploy.py deploy' in text
    assert 'SERVER_NAME:-kalpa' in text


def test_an_unknown_preset_is_ignored_rather_than_breaking_the_file():
    text = yaml_of({'name': 'ci', 'on': {'push': 'main'},
                    'jobs': [{'preset': 'nonsense'}, {'preset': 'uv_test'}]})
    assert 'test:' in text and 'nonsense' not in text


def test_the_spec_is_kept_beside_the_file_it_produced(tmp_path):
    "Reading YAML back into a spec is lossy, so the builder reopens what you built."
    spec = {'name': 'ci', 'on': {'push': 'main'}, 'jobs': [{'preset': 'uv_test'}]}
    save_spec(tmp_path, 'ci.yml', spec)
    assert load_spec(tmp_path, 'ci.yml') == spec
    assert load_spec(tmp_path, 'other.yml') is None
