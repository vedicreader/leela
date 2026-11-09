"Hosted Learn keeps Abhyasa's files in Leela's config folder and never reads the folder of a standalone Abhyasa."
import builtins, io, os
import pytest
from leela.blocks.learn import host, speech
from tests.test_learn_host import served, start   # noqa: F401

SECRET = 'sk-sentinel-SECRET-7731'


@pytest.fixture
def sentinel(tmp_path, monkeypatch):
    d = tmp_path/'standalone'; d.mkdir()
    (d/'settings.json').write_text('{"stt": {"engine": "openai", "model": "sentinel-model"}}')
    (d/'keys.env').write_text(f'export OPENAI_API_KEY="{SECRET}"\n'); (d/'keys.env').chmod(0o600)
    (d/'.sesskey').write_text('sentinel-session-key')
    monkeypatch.setenv('ABHYASA_CONFIG', str(d)); monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.setattr(host, 'leela_cfg', tmp_path/'leela'); monkeypatch.setattr(speech, 'leela_cfg', tmp_path/'leela')
    return d


@pytest.fixture
def spy(sentinel, monkeypatch):
    seen = []
    def watch(f):
        def w(p, *a, **kw):
            if str(p).startswith(str(sentinel)): seen.append(str(p))
            return f(p, *a, **kw)
        return w
    monkeypatch.setattr(os, 'stat', watch(os.stat)); monkeypatch.setattr(io, 'open', watch(io.open)); monkeypatch.setattr(builtins, 'open', watch(builtins.open))
    return seen


def test_hosted_requests_never_read_the_standalone_folder(served, sentinel, spy, tmp_path):
    before = {p.name: p.read_text() for p in sentinel.iterdir()}; spy.clear()
    s = served; cl = s['cl']
    r = start(s)
    assert r.status_code == 200 and 'id="check"' in r.text
    assert cl.post(f"/w/{s['jid']}/0/answer", data=dict(answer='Equal parts of a whole.', confidence=70)).status_code == 200
    assert SECRET not in cl.get('/settings').text and 'sentinel-model' not in cl.get('/settings').text
    assert not spy, spy
    assert {p.name: p.read_text() for p in sentinel.iterdir()} == before
    assert (tmp_path/'leela'/host.STATE/'.sesskey').exists()


def test_the_speech_key_is_the_environment_key_and_no_key_file_is_read(served, sentinel, spy, monkeypatch):
    import abhyasa.models as models
    sent = {}
    def post(url, headers, data, files, timeout): sent.update(headers); return type('R', (), dict(raise_for_status=lambda s: None, json=lambda s: dict(text='said')))()
    monkeypatch.setattr(models, 'http_post', post)
    monkeypatch.setattr(speech, 'speech_values', lambda root=None, cur=None: {'stt.engine': 'openai', 'stt.model': 'gpt-4o-mini-transcribe'})
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-from-leela-environment')
    monkeypatch.setattr(speech, 'TOLD', {'openai'})   # the notice of OpenAI was shown
    spy.clear()
    assert speech.make_transcribe(served['ws'].jobs)(b'RIFFxxxx') == 'said'
    assert sent['Authorization'] == 'Bearer sk-from-leela-environment' and not spy, spy
    monkeypatch.delenv('OPENAI_API_KEY')
    assert models.openai_key()[0] == SECRET   # outside Leela's call the standalone key file still serves a standalone Abhyasa
