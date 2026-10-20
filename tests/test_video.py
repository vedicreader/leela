"generate_video asks Ramabana's `video` job, never a provider by name. Nothing here calls the network."
import json, os
import httpx, pytest
from ramabana.setup import config_path
from leela.blocks.agent.video import VideoJobs, video_tools

AZ = 'https://res.openai.azure.com/openai/v1'
KEYS = ('GEMINI_API_KEY', 'GOOGLE_API_KEY', 'OPENAI_API_KEY', 'AZURE_OPENAI_API_KEY', 'LEELA_MODEL_VIDEO', 'RAMABANA_MODEL_VIDEO')

@pytest.fixture
def net(monkeypatch):
    "Every request httpx is asked for, answered from `net.answers` by `(method, url)`."
    for k in KEYS: monkeypatch.delenv(k, raising=False)
    sent, answers = [], {}
    def call(method):
        def f(url, **kw):
            sent.append(dict(method=method, url=str(url), **kw))
            code, body = answers[(method, str(url))]
            req = httpx.Request(method, url)
            return httpx.Response(code, content=body, request=req) if isinstance(body, bytes) else httpx.Response(code, json=body, request=req)
        return f
    monkeypatch.setattr(httpx, 'post', call('POST')); monkeypatch.setattr(httpx, 'get', call('GET'))
    class Net: pass
    n = Net(); n.sent, n.answers = sent, answers
    return n

def _tools(tmp_path):
    gen, status, _ = video_tools(None, session=str(tmp_path), jobs=(jobs := VideoJobs(tmp_path/'video-jobs.json')))
    return gen, status, jobs

def test_no_video_model_says_how_to_add_one_and_calls_nobody(net, tmp_path):
    "With no Gemini key the job's default cannot run; the tool named the missing key and nothing else, and no provider stood in."
    gen, _, jobs = _tools(tmp_path)
    out = gen('a kettle boiling')
    assert out.startswith('ERROR: video generation is not set up') and 'GEMINI_API_KEY' in out, out
    assert '[jobs] video' in out and str(config_path()) in out and '+ model' in out
    assert net.sent == [] and jobs.all() == []

def test_a_model_that_makes_no_video_is_refused(net, tmp_path, monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'gk')
    config_path().write_text('[jobs]\nvideo = "gemini/gemini-2.5-flash"\n')
    gen, _, jobs = _tools(tmp_path)
    out = gen('a kettle boiling')
    assert 'gemini/gemini-2.5-flash makes no video' in out and '[jobs] video' in out, out
    assert net.sent == [] and jobs.all() == []

def test_the_configured_video_model_gets_the_request_with_its_own_key(net, tmp_path, monkeypatch):
    "An Azure sora-2 named in config.toml: the request, the poll and the download all go to Azure, and the key never reaches the job file."
    monkeypatch.setenv('AZURE_OPENAI_API_KEY', 'azk')
    config_path().write_text(f'[model."az-sora"]\nmodel_id = "sora-2"\nbase_url = "{AZ}"\n[jobs]\nvideo = "az-sora"\n')
    net.answers[('POST', f'{AZ}/videos')] = 200, {'id': 'vid_1', 'status': 'queued'}
    gen, status, jobs = _tools(tmp_path)
    assert 'started on az-sora' in gen('a kettle boiling', seconds=10)
    p = net.sent[0]
    assert p['headers'] == {'Authorization': 'Bearer azk'} and p['files']['model'] == (None, 'sora-2') and p['files']['seconds'] == (None, '8')
    row = jobs.get('')
    assert (row['model'], row['api'], row['op']) == ('az-sora', 'openai', 'vid_1') and 'azk' not in jobs.path.read_text()
    net.answers[('GET', f'{AZ}/videos/vid_1')] = 200, {'id': 'vid_1', 'status': 'in_progress'}
    assert status().endswith('still generating')
    net.answers[('GET', f'{AZ}/videos/vid_1')] = 200, {'id': 'vid_1', 'status': 'completed'}
    net.answers[('GET', f'{AZ}/videos/vid_1/content')] = 200, b'mp4 bytes'
    assert ' done ' in status().replace('·', ' ')
    assert open(jobs.get('')['path'], 'rb').read() == b'mp4 bytes'
    assert {s['url'].split('/openai/v1')[0] for s in net.sent} == {'https://res.openai.azure.com'}, 'Azure, and nowhere else'

def test_a_failed_job_keeps_the_providers_reason(net, tmp_path, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'ok')
    config_path().write_text('[jobs]\nvideo = "openai/sora-2"\n')
    net.answers[('POST', 'https://api.openai.com/v1/videos')] = 200, {'id': 'v2'}
    net.answers[('GET', 'https://api.openai.com/v1/videos/v2')] = 200, {'status': 'failed', 'error': {'message': 'moderation blocked'}}
    gen, status, jobs = _tools(tmp_path)
    gen('a kettle')
    assert 'moderation blocked' in status() and jobs.get('')['state'] == 'failed'

def test_a_gemini_job_polls_with_the_key_and_downloads_without_handing_it_on(net, tmp_path, monkeypatch):
    "Veo's download redirects to storage; the key went down the redirect with it."
    monkeypatch.setenv('GOOGLE_API_KEY', 'gk')
    G = 'https://generativelanguage.googleapis.com/v1beta'
    net.answers[('POST', f'{G}/models/veo-3.0-generate-001:predictLongRunning')] = 200, {'name': 'models/veo/operations/op1'}
    gen, status, jobs = _tools(tmp_path)
    assert 'started on gemini/veo-3.0-generate-001' in gen('a kettle', seconds=5)
    assert net.sent[0]['json']['parameters'] == {'durationSeconds': 4} and net.sent[0]['headers'] == {'x-goog-api-key': 'gk'}
    uri = f'{G}/files/f1:download?alt=media'
    net.answers[('GET', f'{G}/models/veo/operations/op1')] = 200, {'done': True, 'response': {'generateVideoResponse': {'generatedSamples': [{'video': {'uri': uri}}]}}}
    net.answers[('GET', uri)] = 200, b'veo bytes'
    assert ' done ' in status().replace('·', ' ')
    assert net.sent[-1]['headers'] == {'x-goog-api-key': 'gk'}
    gen('again'); jid = jobs.get('')['id']
    net.answers[('GET', 'https://storage.example.com/v.mp4')] = 200, b'stored'
    def redirected(url, **kw):
        net.sent.append(dict(method='GET', url=str(url), **kw))
        if str(url) == uri: return httpx.Response(302, headers={'location': 'https://storage.example.com/v.mp4'}, request=httpx.Request('GET', url))
        code, body = net.answers[('GET', str(url))]
        return httpx.Response(code, content=body, request=httpx.Request('GET', url)) if isinstance(body, bytes) else httpx.Response(code, json=body, request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx, 'get', redirected)
    assert ' done ' in status(jid).replace('·', ' ')
    last = net.sent[-1]
    assert last['url'] == 'https://storage.example.com/v.mp4' and not last.get('headers'), 'the key stays with Google'

def test_a_job_whose_route_went_away_stays_running(net, tmp_path, monkeypatch):
    "A key unset or config.toml edited after a job started: the job cannot be checked, which is not a failure."
    monkeypatch.setenv('GEMINI_API_KEY', 'gk')
    jobs = VideoJobs(tmp_path/'video-jobs.json')
    jobs.add(model='veo-3.0-generate-001', prompt='old', op='models/veo/operations/op0', seconds=8)   # a row from before routing
    _, status, _ = video_tools(None, session=str(tmp_path), jobs=jobs)
    net.answers[('GET', 'https://generativelanguage.googleapis.com/v1beta/models/veo/operations/op0')] = 200, {'done': False}
    assert status().endswith('still generating'), 'an old row is polled as the Gemini job it was'
    monkeypatch.delenv('GEMINI_API_KEY')
    out = status()
    assert 'could not be checked' in out and 'GEMINI_API_KEY' in out and jobs.get('')['state'] == 'running'
    monkeypatch.setenv('OPENAI_API_KEY', 'ok')
    jobs.add(model='openai/sora-2', api='gemini', prompt='moved', op='x', seconds=8)
    assert 'now goes to the openai API' in status() and jobs.get('')['state'] == 'running'
