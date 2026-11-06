"A conversation nobody gave a model moves to the one ready here, as ramabana's CLI moves it; with none ready the turn is refused and the only download is one the person starts."
import time
import pytest
import ramabana.core as core
from fastcore.xml import to_xml
from leela.blocks.agent import models
from tests.test_azure_models import bare   # noqa: F401  a machine with nothing signed in


@pytest.fixture
def codex(bare, monkeypatch):
    "Codex signed in, with every model built on a fake backend so no turn reaches the network."
    import ramabana.agent as ra
    from ramabana.testing import FakeBackend
    monkeypatch.setattr(ra, 'make_backend', lambda spec, **kw: FakeBackend(spec, replies=['hi'], **kw))
    ready = {'on': True}
    monkeypatch.setattr(core, '_codex_login', lambda: ready['on'])
    return ready

def _panel(ws):
    from leela.app import _agent_panel
    return to_xml(_agent_panel(ws))


def test_a_new_conversation_moves_to_codex_and_the_pane_says_so(ws, codex):
    t = ws.threads.active
    want = core.ready_turn()
    assert want.startswith('codex/') and t.ai.model.name == want, t.ai.model.name
    assert t.moved.startswith(f'{core.DFLT_TURN} cannot run here') and want in t.moved
    html = _panel(ws)
    assert 'data-moved' in html and want in html and 'cannot run here</strong>' not in html, 'the welcome names the move, not a refusal'
    assert models.default_model('turn') == want, 'the picker shows the model the conversation runs on'


def test_a_model_the_person_chose_is_never_moved(ws, codex):
    ws.model = core.DFLT_TURN
    t = ws.threads.active
    assert t.ai.model.name == core.DFLT_TURN and t.moved == ''
    assert 'data-moved' not in _panel(ws) and 'cannot run here' in _panel(ws)


def test_a_sign_in_after_the_conversation_began_moves_its_next_turn(ws, codex):
    codex['on'] = False
    t = ws.threads.active
    assert t.ai.model.name == core.DFLT_TURN and t.moved == ''
    codex['on'] = True
    out = t.runner.start('hello')
    assert out['moved'] == t.moved and t.ai.model.name == core.ready_turn(), out


def test_with_nothing_ready_the_turn_is_refused_and_gemma_is_offered(ws, bare):
    from starlette.testclient import TestClient
    from leela.app import ide_app
    with TestClient(ide_app(ws)) as c:
        r = c.post('/agent/turn', json={'prompt': 'Say hi'})
    msg = r.json()['message']
    assert r.status_code == 409 and 'cannot run here' in msg, msg
    assert 'gemma-e2b runs here;' not in msg and 'gemma-e2b runs here after a 3.5 GB download' in msg, 'no claim that a model with no weights runs'
    html = _panel(ws)
    assert 'Download Gemma 4 E2B (3.5 GB) to run on this Mac' in html and 'data-download="gemma-e2b"' in html
    row = models.setup_plan()['offline'][0]
    assert (row['value'], row['size'], row['available']) == ('gemma-e2b', '3.5 GB', False)


def test_gemma_on_disk_is_where_the_turn_goes_and_nothing_offers_a_download(ws, bare, hf_cache):
    hf_cache('gemma-e2b')
    t = ws.threads.active
    assert t.ai.model.name == 'gemma-e2b' and 'gemma-e2b' in t.moved
    plan = models.setup_plan()
    assert plan['done'] and plan['offline'][0]['available']
    assert 'data-download' not in _panel(ws)


def _wait(name, secs=5):
    end = time.time() + secs
    while time.time() < end and models.install_state(name).get('state') == 'running': time.sleep(.02)
    return models.install_state(name)

def test_the_download_runs_only_when_asked_and_reports_how_it_ended(bare, hf_cache, monkeypatch):
    import rishi.litert as lt
    asked = []
    monkeypatch.setattr(lt, 'get_model', lambda mid, *a, **kw: (asked.append(mid), hf_cache('gemma-e2b')))
    models.setup_plan(); models.providers()
    assert asked == [], 'drawing the setup panel downloads nothing'
    assert models.install_runtime('gemma-e2b')['state'] == 'running'
    st = _wait('gemma-e2b')
    assert asked == [core.LOCAL['gemma-e2b']] and st['state'] == 'ok' and st['available'], st
    assert core.weights_here('gemma-e2b') and models.setup_plan()['offline'][0]['available'], 'no stale probe says it is missing'

def test_a_download_that_fails_says_why(bare, monkeypatch):
    import rishi.litert as lt
    def offline(*a, **kw): raise OSError('no network')
    monkeypatch.setattr(lt, 'get_model', offline)
    models.install_runtime('gemma-e2b')
    st = _wait('gemma-e2b')
    assert st['state'] == 'error' and 'no network' in st['log'] and not st['available'], st
