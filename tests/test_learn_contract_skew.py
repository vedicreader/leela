"A Leela run against an Abhyasa that is too old, too new for nothing, or not installed: Learn says why and everything else works."
import sys
from copy import deepcopy

import pytest
from starlette.routing import Mount
from starlette.testclient import TestClient

from leela.app import ide_app
from leela.blocks.agent.threads import TurnError
from leela.blocks.learn import host
from leela.blocks.learn.tools import HOST_API_NEEDED, contract_missing, host_line
from leela.blocks.settings import settings as S
from tests.fakemodel import WIDE, install


def no_attr(mp):
    import abhyasa.learner
    mp.delattr(abhyasa.learner, 'use_settings')

def old_api(mp):
    import abhyasa.core.hostapi as h
    mp.setattr(h, 'HOST_API', HOST_API_NEEDED - 1)

def no_api(mp): mp.delattr('abhyasa.core.hostapi.HOST_API')

def no_abhyasa(mp): mp.setitem(sys.modules, 'abhyasa.core.hostapi', None)

SKEW = {'attr': (no_attr, "abhyasa.learner.use_settings"), 'low': (old_api, f'Abhyasa too old: needs host API {HOST_API_NEEDED}, has {HOST_API_NEEDED - 1}'),
        'none': (no_api, f'Abhyasa too old: needs host API {HOST_API_NEEDED}, has none'), 'absent': (no_abhyasa, f'Abhyasa too old: needs host API {HOST_API_NEEDED}, has none')}

@pytest.fixture(params=list(SKEW))
def skew(request, monkeypatch):
    for n in ('DEFAULT_SETTINGS', '_ENUMS', '_RANGES', 'USER_ONLY', 'SECTIONS'): monkeypatch.setattr(S, n, deepcopy(getattr(S, n)))
    S.SECTIONS.pop('learn', None)
    fn, line = SKEW[request.param]; fn(monkeypatch)
    return line

@pytest.fixture
def cl(ws, skew, monkeypatch):
    monkeypatch.setattr(host, 'HOSTS', ('testserver',))
    install(ws, [], spec=WIDE)
    app = ide_app(ws)
    with TestClient(app) as c: yield c
    for h in app.router.routes:
        if isinstance(h, Mount) and isinstance(h.app, host.Hosted): h.app.stop()


def test_the_contract_check_names_the_gap(skew):
    assert skew in ' '.join(contract_missing())

def test_learn_mode_refuses_with_the_line(ws, skew, monkeypatch):
    install(ws, [], spec=WIDE)
    t = ws.threads.active
    with pytest.raises(TurnError) as e: t.set_learn_mode(True)
    assert e.value.code == 'contract_missing' and skew in e.value.message and not t.ai.learn_mode
    assert t.set_learn_mode(False)['ok']

def test_open_answers_a_clear_503_with_the_same_line(cl, skew):
    r = cl.post('/learn/abh/open')
    assert r.status_code == 503 and r.json()['ok'] is False and skew in r.json()['error']

def test_leela_and_its_other_features_still_work(cl, skew):
    assert cl.get('/agent/threads').json()['learn_missing'] and skew in ' '.join(cl.get('/agent/threads').json()['learn_missing'])
    assert cl.get('/workspace/info').status_code == 200
    r = cl.get('/settings')
    assert r.status_code == 200 and 'learn' not in S.SECTIONS
    assert cl.get('/vault/panel').status_code == 200
    r = cl.post('/agent/learn-mode', json={'on': True})
    assert r.json()['code'] == 'contract_missing' and skew in r.json()['message']

def test_a_current_abhyasa_has_no_line_and_gets_its_section(ws, monkeypatch):
    for n in ('DEFAULT_SETTINGS', '_ENUMS', '_RANGES', 'USER_ONLY', 'SECTIONS'): monkeypatch.setattr(S, n, deepcopy(getattr(S, n)))
    S.SECTIONS.pop('learn', None)
    assert host_line() == '' and contract_missing() == []
    assert ide_app(ws) and 'learn' in S.SECTIONS
