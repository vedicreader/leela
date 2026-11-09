import json, sys
from copy import deepcopy
from types import SimpleNamespace as NS

import pytest
from starlette.routing import Mount
from starlette.testclient import TestClient

from leela.app import ide_app
from leela.blocks.learn import host, speech
from leela.blocks.settings import settings as S
from leela.blocks.settings.settings import Settings, register_section
from leela.blocks.learn.app import learn_rows

KEY = 'OPENAI_API_KEY'


class FakeJobs:
    def __init__(self): self.rows, self.stopped = [], False
    def all(self, limit=40, kind=None): return [j for j in self.rows if j.kind == kind]
    def alive(self, j): return True
    def start(self, kind, target='', **params):
        j = NS(id=f'{kind}-{len(self.rows)}', kind=kind, target=target, params=params, active=True)
        self.rows.append(j); return j
    def stopping(self, jid): return self.stopped


@pytest.fixture
def eng(monkeypatch, tmp_path):
    "`abhyasa.models` with a fake engine and no cache, and the told-once memory empty."
    import abhyasa.models as m
    calls = []
    monkeypatch.setattr(m, 'transcribe', lambda audio, engine=None, hint='', model=None: calls.append((engine, model, hint)) or 'hello')
    monkeypatch.setattr(m, 'cached', lambda model: True)
    ok = tmp_path/'complete'; ok.write_text('')
    monkeypatch.setattr(speech, '_marker', lambda model: ok)
    monkeypatch.setattr(m, 'openai_key', lambda: (_ for _ in ()).throw(AssertionError('a key file was read')))
    monkeypatch.setattr(speech, 'TOLD', set())
    monkeypatch.delenv(KEY, raising=False)
    return NS(m=m, calls=calls)


def test_speech_rows_are_a_group_of_the_learn_section_and_match_abhyasas_defaults(monkeypatch):
    from abhyasa.learner import SETTINGS
    rows = learn_rows()
    sp = [r for r in rows if r['group'] == 'speech']
    assert [r['key'] for r in sp] == [f'speech.{k}' for k in ('engine', 'model', 'segment', 'pause', 'longest')]
    for r in sp:
        a = SETTINGS['stt.' + r['key'].split('.')[1]]
        assert r['dflt'] == a.dflt and r['kind'] in (a.kind, 'choice') and r['lo'] == a.lo
    assert not [r for r in rows if r['key'].split('.')[0] in ('stt', 'voice')]


def test_speech_settings_save_validate_and_stay_user_only(monkeypatch, tmp_path):
    for n in ('DEFAULT_SETTINGS', '_ENUMS', '_RANGES', 'USER_ONLY', 'SECTIONS'): monkeypatch.setattr(S, n, deepcopy(getattr(S, n)))
    register_section('learn', learn_rows(), 'abhyasa')
    (tmp_path/'proj'/'.leela').mkdir(parents=True)
    (tmp_path/'proj'/'.leela'/'settings.json').write_text(json.dumps({'learn': {'speech.engine': 'openai'}}))
    s = Settings(tmp_path/'proj', user_path=tmp_path/'user.json')
    assert s.effective()['learn']['speech.engine'] == 'mlx'
    with pytest.raises(ValueError): s.save('user', 'learn', {'speech.engine': 'whisperx'})
    with pytest.raises(ValueError): s.save('user', 'learn', {'speech.pause': 50})
    assert s.save('user', 'learn', {'speech.engine': 'openai', 'speech.pause': '900'})['effective']['learn']['speech.engine'] == 'openai'
    v = speech.speech_values(cur=s.effective()['learn'])
    assert v == {'stt.engine': 'openai', 'stt.model': '', 'stt.segment': True, 'stt.pause': 900, 'stt.longest': 12}
    s.reset('user', 'learn')
    assert speech.speech_values(cur=s.effective()['learn'])['stt.engine'] == 'mlx'


def test_transcribe_uses_leelas_engine_and_model_and_reads_no_abhyasa_file(eng, monkeypatch):
    import abhyasa.learner as lr
    monkeypatch.setattr(lr, '_path', lambda: (_ for _ in ()).throw(AssertionError('the Abhyasa settings file was read')))
    monkeypatch.setattr(speech, 'speech_values', lambda root=None, cur=None: {'stt.engine': 'mlx', 'stt.model': 'mlx-community/x', 'stt.segment': True, 'stt.pause': 700, 'stt.longest': 12})
    assert speech.make_transcribe(FakeJobs())(b'wav', hint='names') == 'hello'
    assert eng.calls == [('mlx', 'mlx-community/x', 'names')]


def test_a_model_not_on_the_machine_starts_one_visible_job_and_says_so(eng, monkeypatch):
    monkeypatch.setattr(eng.m, 'cached', lambda model: False)
    jobs = FakeJobs()
    t = speech.make_transcribe(jobs)
    for _ in range(2):
        with pytest.raises(RuntimeError, match='not on this Mac yet.*job card'): t(b'wav')
    assert [(j.kind, j.target, j.params) for j in jobs.rows] == [('speech_model', eng.m.DFLT_STT, {'_cancel': True})] and not eng.calls


def test_a_half_finished_download_is_not_ready_and_restarts_its_job(eng, monkeypatch, tmp_path):
    import huggingface_hub, huggingface_hub.constants as hc
    monkeypatch.setattr(hc, 'HF_HUB_CACHE', str(tmp_path/'hf'))
    monkeypatch.setattr(speech, '_marker', lambda model: tmp_path/'hf'/f"models--{model.replace('/', '--')}"/'.complete')
    model = eng.m.DFLT_STT
    (tmp_path/'hf'/f"models--{model.replace('/', '--')}").mkdir(parents=True)
    jobs, t = FakeJobs(), speech.make_transcribe(FakeJobs())
    def dies(model, tqdm_class=None): raise OSError('connection lost')
    monkeypatch.setattr(huggingface_hub, 'snapshot_download', dies)
    monkeypatch.setattr(eng.m, 'model_size', lambda model: 0)
    assert not speech.complete(model)
    with pytest.raises(OSError): speech.download(model, lambda **kw: None, lambda: False)
    assert not speech.complete(model)
    why = speech.blocker(jobs, {'stt.engine': 'mlx', 'stt.model': ''}); assert 'not on this Mac yet' in why
    jobs.rows[0].active = False
    speech.blocker(jobs, {'stt.engine': 'mlx', 'stt.model': ''})
    assert [j.kind for j in jobs.rows] == ['speech_model', 'speech_model']
    monkeypatch.setattr(huggingface_hub, 'snapshot_download', lambda model, tqdm_class=None: None)
    assert speech.download(model, lambda **kw: None, lambda: False) == {'model': model} and speech.complete(model)
    assert speech.blocker(jobs, {'stt.engine': 'mlx', 'stt.model': ''}) == ''


def test_the_download_card_goes_to_the_workspace_of_the_call_not_the_first_one(eng, monkeypatch):
    monkeypatch.setattr(eng.m, 'cached', lambda model: False)
    a, b = (NS(jobs=FakeJobs(), project_root=None) for _ in range(2))
    t = speech.make_transcribe(a.jobs)
    for ws in (a, b, b):
        with host.using(ws), pytest.raises(RuntimeError, match='job card'): t(b'wav')
    assert [len(a.jobs.rows), len(b.jobs.rows)] == [1, 1]
    with pytest.raises(RuntimeError, match='job card'): t(b'wav')
    assert len(a.jobs.rows) == 1


def test_openai_needs_the_key_from_environment_and_says_where_audio_goes_once(eng, monkeypatch):
    monkeypatch.setattr(speech, 'speech_values', lambda root=None, cur=None: {'stt.engine': 'openai', 'stt.model': '', 'stt.segment': True, 'stt.pause': 700, 'stt.longest': 12})
    t = speech.make_transcribe(FakeJobs())
    with pytest.raises(RuntimeError, match=KEY): t(b'wav')
    monkeypatch.setenv(KEY, 'sk-test-1234')
    with pytest.raises(RuntimeError, match='audio goes to OpenAI'): t(b'wav')
    assert t(b'wav') == 'hello' and t(b'wav') == 'hello' and [c[0] for c in eng.calls] == ['openai', 'openai']
    assert not speech.blocker(FakeJobs(), {'stt.engine': 'mlx', 'stt.model': ''})


def test_an_engine_error_and_a_missing_package_reach_the_caller_in_words(eng, monkeypatch):
    def boom(audio, engine=None, hint='', model=None): raise ValueError('bad clip')
    monkeypatch.setattr(eng.m, 'transcribe', boom)
    with pytest.raises(ValueError, match='bad clip'): speech.make_transcribe(FakeJobs())(b'wav')
    def nomod(audio, engine=None, hint='', model=None): raise ModuleNotFoundError("No module named 'mlx_audio'", name='mlx_audio')
    monkeypatch.setattr(eng.m, 'transcribe', nomod)
    with pytest.raises(RuntimeError, match='mlx_audio package.*leela\\[local\\]'): speech.make_transcribe(FakeJobs())(b'wav')


def fake_hub(monkeypatch, steps, size=8 << 20):
    import abhyasa.models as m, huggingface_hub
    got = [0]
    def snap(model, tqdm_class=None):
        bar = tqdm_class(total=steps, disable=True)
        for _ in range(steps):
            got[0] += size // steps; bar.update(1)
    monkeypatch.setattr(huggingface_hub, 'snapshot_download', snap)
    monkeypatch.setattr(m, 'model_size', lambda model: size)
    monkeypatch.setattr(m, 'cache_bytes', lambda model: got[0])


def test_the_download_job_reports_progress_and_finishes(monkeypatch):
    fake_hub(monkeypatch, 4)
    seen = []
    assert speech.download('m/x', lambda **kw: seen.append(kw), lambda: False) == {'model': 'm/x'}
    assert [round(k['progress'], 2) for k in seen] == [.28, .5, .73, .95] and seen[-1]['current'] == '8 of 8 MB'


def test_stopping_the_download_job_ends_it_cancelled(monkeypatch):
    fake_hub(monkeypatch, 4)
    n = []
    assert speech.download('m/x', lambda **kw: n.append(kw), lambda: len(n) >= 2) == {'cancelled': True} and len(n) == 2


@pytest.fixture
def cl(ws, eng, monkeypatch):
    monkeypatch.setattr(host, 'HOSTS', ('testserver',))
    app = ide_app(ws)
    with TestClient(app) as c:
        yield c, eng
    for h in app.router.routes:
        if isinstance(h, Mount) and isinstance(h.app, host.Hosted): h.app.stop()


def events(c, did):
    with c.stream('GET', f'/speech/events/{did}') as r:
        return [json.loads(l[6:]) for l in r.iter_lines() if l.startswith('data: ')]


def test_a_posted_segment_gives_text_through_leelas_dictation_routes(cl):
    c, eng = cl
    from abhyasa.models import silence
    assert c.post('/speech/ready').json() == {'ok': True}
    r = c.post('/speech/start').json()
    assert r['ok'] and r['pause'] == 700 and r['segment'] is True
    did = r['id']
    assert c.post(f'/speech/seg/{did}?seq=0', content=silence()).json()['ok']
    assert c.post(f'/speech/seg/{did}?seq=1', content=silence()).json()['ok']
    assert c.post(f'/speech/stop/{did}?n=2').json() == {'ok': True}
    assert events(c, did) == [dict(seq=0, text='hello'), dict(seq=1, text='hello'), dict(done=True)]


def test_stopping_before_any_segment_ends_the_dictation_with_no_text(cl):
    c, _ = cl
    did = c.post('/speech/start').json()['id']
    assert c.post(f'/speech/stop/{did}?n=0').json() == {'ok': True}
    assert events(c, did) == [dict(done=True)]


def test_an_engine_error_reaches_the_event_stream(cl, monkeypatch):
    c, eng = cl
    def boom(audio, engine=None, hint='', model=None): raise ValueError('bad clip')
    monkeypatch.setattr(eng.m, 'transcribe', boom)
    did = c.post('/speech/start').json()['id']
    c.post(f'/speech/seg/{did}?seq=0', content=b'x'); c.post(f'/speech/stop/{did}?n=1')
    assert events(c, did)[0] == dict(seq=0, text='', error='bad clip')


def test_unknown_dictation_ids_answer_404(cl):
    c, _ = cl
    assert c.post('/speech/seg/nope?seq=0', content=b'x').status_code == 404
    assert c.post('/speech/stop/nope?n=0').status_code == 404
    assert c.get('/speech/events/nope').status_code == 404


def test_ready_says_why_and_starts_the_download_when_the_model_is_missing(cl, ws, monkeypatch):
    c, eng = cl
    monkeypatch.setattr(eng.m, 'cached', lambda model: False)
    import threading
    go = threading.Event()
    monkeypatch.setattr(speech, 'download', lambda model, report, stopping: go.wait(10) and {'model': model})
    r = c.post('/speech/ready')
    assert r.status_code == 409 and not r.json()['ok'] and 'job card' in r.json()['say']
    assert c.post('/speech/ready').status_code == 409
    go.set()
    import time
    for _ in range(200):
        if not [j for j in ws.jobs.all(kind='speech_model') if j.active]: break
        time.sleep(.05)
    assert [(j.status, j.target) for j in ws.jobs.all(kind='speech_model')] == [('complete', eng.m.DFLT_STT)]


def test_the_hosted_abhyasa_app_gets_the_same_transcribe_and_no_warm_up(ws, eng, monkeypatch):
    seen = {}
    import abhyasa.app as app
    monkeypatch.setattr(app, 'mk_app', lambda lr, ask, **kw: seen.update(kw) or object())
    monkeypatch.setattr(host, 'learn_store', lambda ws, vault=None, write=False: ('t', None))
    host.abhyasa_app(ws, ai=object())
    assert seen['warm_speech'] is False and seen['transcribe'](b'wav', hint='h') == 'hello' and eng.calls[0][2] == 'h'


def test_a_voice_route_of_the_hosted_app_reads_leelas_speech_settings(ws, monkeypatch):
    import asyncio
    from abhyasa.learner import val
    got = {}
    async def echo(scope, receive, send): got.update(pause=val('stt.pause'), walks=val('walks.steps'))
    monkeypatch.setattr(host, 'learn_settings', lambda ws: {'speech.pause': 1500, 'walks.steps': 3})
    asyncio.run(host.Hosted(ws)._serve(echo, dict(type='http', method='POST', path='/voice/start', headers=[]), None, None))
    assert got == {'pause': 1500, 'walks': 3}


def test_the_mac_bundle_may_use_the_microphone():
    import plistlib
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]/'packaging'/'macos'
    assert plistlib.loads((root/'entitlements.plist').read_bytes())['com.apple.security.device.audio-input'] is True
    assert "'NSMicrophoneUsageDescription'" in (root/'setup.py').read_text()


def test_a_posted_wav_segment_gives_text_through_the_mounted_abhyasa_app(ws, eng, monkeypatch):
    from abhyasa.learner import temp_learning
    from abhyasa.models import silence
    monkeypatch.setattr(host, 'learn_store', lambda ws, vault=None, write=False: ('test', temp_learning()))
    monkeypatch.setattr(host, 'HOSTS', ('testserver',))
    app = ide_app(ws)
    try:
        with TestClient(app) as c:
            assert c.post('/learn/abh/open').json()['ok']
            r = c.post('/learn/abh/voice/start').json()
            assert r['pause'] == 700 and r['segment'] is True
            did = r['id']
            assert c.post(f'/learn/abh/voice/seg/{did}?seq=0', content=silence()).json()['ok']
            assert c.post(f'/learn/abh/voice/stop/{did}?n=1').json() == {'ok': True}
            with c.stream('GET', f'/learn/abh/voice/events/{did}') as s:
                got = [json.loads(l[6:]) for l in s.iter_lines() if l.startswith('data: ')]
            assert got == [dict(seq=0, text='hello'), dict(done=True)] and eng.calls == [('mlx', eng.m.DFLT_STT, '')]
            h = next(r.app for r in app.router.routes if isinstance(r, Mount) and isinstance(r.app, host.Hosted))
            assert h.app.state.svc['speech'].status == 'not loaded'
    finally:
        for h in app.router.routes:
            if isinstance(h, Mount) and isinstance(h.app, host.Hosted): h.app.stop()
