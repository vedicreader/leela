"With Azure OpenAI and no Claude Code or Codex, Leela counts as set up and its default models are the ones Ramabana's CLI would use."
import pytest
import ramabana.core as core
from leela.blocks.agent import models


@pytest.fixture
def azure_only(tmp_path, monkeypatch):
    monkeypatch.setenv('RAMABANA_CONFIG', str(tmp_path/'config.toml'))
    monkeypatch.setattr(core, '_claude_available', lambda: False)
    monkeypatch.setattr(core, '_claude_login', lambda: False)
    monkeypatch.setattr(core, '_codex_login', lambda: False)
    monkeypatch.setattr(core, '_copilot_available', lambda: False)
    for k in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'GEMINI_API_KEY', 'LEELA_MODEL', 'RAMABANA_MODEL', 'LEELA_MODEL_INLINE', 'LEELA_MODEL_COMPLETION'):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv('AZURE_OPENAI_ENDPOINT', 'https://res.openai.azure.com')
    monkeypatch.setenv('AZURE_OPENAI_API_KEY', 'k')
    monkeypatch.setenv('AZURE_OPENAI_DEPLOYMENTS', 'gpt-5.4,gpt-5.4-mini')
    monkeypatch.setattr(models, 'probed', lambda key, fn, ttl=None: fn())
    return tmp_path


def test_setup_counts_azure_as_an_account(azure_only):
    plan = models.setup_plan()
    assert 'remote' in plan['ready'] and plan['done'], plan['ready']
    assert 'AZURE_OPENAI_ENDPOINT' in next(a['blurb'] for a in plan['accounts'] if a['value'] == 'remote')


def test_setup_counts_a_config_toml_model_with_its_key(azure_only, monkeypatch):
    monkeypatch.delenv('AZURE_OPENAI_ENDPOINT')
    assert 'remote' not in models.setup_plan()['ready']
    (azure_only/'config.toml').write_text('[model."az-big"]\nmodel_id = "gpt-5.4"\nbase_url = "https://res.openai.azure.com/openai/v1"\n')
    assert 'remote' in models.setup_plan()['ready']


def test_the_default_models_are_the_routings(azure_only):
    assert models.default_model('turn') == 'azure/gpt-5.4'
    assert models.settled(core.DFLT_SMALL, 'inline') == 'azure/gpt-5.4-mini'
    assert models.settled('gpt-4.1', 'completion') == 'azure/gpt-5.4-mini', 'an old workspace default that cannot run moves too'
    assert models.settled('my-choice', 'inline') == 'my-choice', 'a choice is never moved'


def test_config_toml_jobs_reach_leela(azure_only):
    (azure_only/'config.toml').write_text('[jobs]\nturn = "azure/gpt-5.4-mini"\n')
    assert models.default_model('turn') == 'azure/gpt-5.4-mini'
