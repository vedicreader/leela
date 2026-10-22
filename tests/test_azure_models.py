"No provider is chosen for a person: with no runnable model Leela lists the providers and the form that adds one, and a configured hosted model counts as set up."
import pytest
import ramabana.core as core
from leela.blocks.agent import models


@pytest.fixture
def bare(tmp_path, monkeypatch):
    monkeypatch.setenv('RAMABANA_CONFIG', str(tmp_path/'config.toml'))
    monkeypatch.setattr(core, '_claude_available', lambda: False)
    monkeypatch.setattr(core, '_claude_login', lambda: False)
    monkeypatch.setattr(core, '_codex_login', lambda: False)
    monkeypatch.setattr(core, '_copilot_available', lambda: False)
    for k in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'GEMINI_API_KEY', 'OPENROUTER_API_KEY', 'AWS_BEARER_TOKEN_BEDROCK', 'LEELA_MODEL',
              'RAMABANA_MODEL', 'LEELA_MODEL_INLINE', 'LEELA_MODEL_COMPLETION', 'AZURE_OPENAI_ENDPOINT', 'AZURE_OPENAI_API_KEY'):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(models, 'probed', lambda key, fn, ttl=None: fn())
    return tmp_path


def test_azure_credentials_alone_choose_nothing(bare, monkeypatch):
    monkeypatch.setenv('AZURE_OPENAI_ENDPOINT', 'https://res.openai.azure.com')
    monkeypatch.setenv('AZURE_OPENAI_API_KEY', 'k')
    assert 'remote' not in models.setup_plan()['ready'], 'a credential with no model named is not a model'
    assert models.default_model('turn') == core.DFLT_TURN and models.unavailable(core.DFLT_TURN)
    assert next(p for p in models.providers() if p['key'] == 'azure')['ready']


def test_a_configured_hosted_model_counts_as_set_up(bare, monkeypatch):
    monkeypatch.setenv('AWS_BEARER_TOKEN_BEDROCK', 'k')
    (bare/'config.toml').write_text('[model."bedrock-gpt"]\nmodel_id = "openai.gpt-5.4"\nbase_url = "https://bedrock-mantle.us-east-1.api.aws/v1"\n'
                                    'api_key_env = "AWS_BEARER_TOKEN_BEDROCK"\n[jobs]\nturn = "bedrock-gpt"\n')
    assert 'remote' in models.setup_plan()['ready']
    assert models.default_model('turn') == 'bedrock-gpt' and not models.unavailable('bedrock-gpt'), 'config.toml [jobs] reaches Leela'


def test_a_missing_key_points_at_the_form(bare):
    (bare/'config.toml').write_text('[model."az-big"]\nmodel_id = "gpt-5.4"\nbase_url = "https://res.openai.azure.com/openai/v1"\n')
    why = models.unavailable('az-big')
    assert 'AZURE_OPENAI_API_KEY' in why and '+ model' in why, why


def test_the_agent_pane_lists_the_providers_when_nothing_runs(bare, tmp_path):
    from leela.app import _agent_panel
    from leela.workspace import Workspace
    from fasthtml.common import to_xml
    ws = Workspace(roots=[tmp_path]); ws._state_path = tmp_path/'ws.json'
    html = to_xml(_agent_panel(ws))
    assert 'data-providers' in html and 'AWS Bedrock' in html and 'Azure OpenAI' in html and 'leeAddModel()' in html
