import json
from leela.blocks.agent.models import delete_model,load_models,save_model
from leela.agent.core import resolve


def test_huggingface_urls_are_saved_and_registered(tmp_path):
    p=tmp_path/'models.json'
    row=save_model({'name':'ornith-test','model_id':'https://huggingface.co/litert-community/Ornith-1.0-9B',
                    'runtime':'litert','ctx':128_000},p)
    assert row['model_id']=='litert-community/Ornith-1.0-9B'
    assert resolve('ornith-test').runtime=='litert'
    assert load_models(p)[0]['name']=='ornith-test'
    assert json.loads(p.read_text())[0]['ctx']==128_000


def test_hosted_model_ids_persist_without_secrets(tmp_path):
    p=tmp_path/'models.json'
    save_model({'name':'new-api-model','model_id':'openai/new-api-model','runtime':'remote','ctx':200_000,
                'base_url':'https://api.example.test/v1','api_key_env':'EXAMPLE_API_KEY'},p)
    spec=resolve('new-api-model')
    assert spec.model_id=='openai/new-api-model' and spec.config['base_url'].endswith('/v1')
    assert 'EXAMPLE_API_KEY' in p.read_text() and 'secret-value' not in p.read_text()
    delete_model('new-api-model',p)
    assert load_models(p)==[]
