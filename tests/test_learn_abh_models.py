import socket, threading, time

import pytest
from starlette.routing import Match, Mount
from starlette.testclient import TestClient

from leela.app import ide_app
from leela.blocks.learn import host
from ramabana.core import ModelSpec
from tests.fakemodel import install
from tools.s2_native_pilot import PLAN

# Every task that the mounted paths below may route through `Router.for_`.
TASKS = frozenset('grade hint lesson note plan question'.split())
GRADE = r'{"correct": true, "grade": 10, "feedback": "Correct.", "first_error": "", "misconception": ""}'
QUESTION = r'{"question": "What does a fraction name?", "answer": "Equal parts.", "core": "A fraction names equal parts.", "rubric": ["Equal parts."]}'


def _reply(job):
    return dict(grade=GRADE, question=QUESTION, plan=PLAN, extract=PLAN).get(job, 'A short, clear tutor reply.')


def _hosted(app):
    return next(r.app for r in app.router.routes if isinstance(r, Mount) and isinstance(r.app, host.Hosted))


def _start(s):
    s['cl'].post('/learn/abh/open')
    s['cl'].post(f"/w/{s['jid']}/start")
    s['cl'].get(f"/w/{s['jid']}/0?pane=1")
    s['cl'].get(f"/w/{s['jid']}/0/check")
    s['calls'].clear(); s['jobs'].clear(); s['routed'].clear()


@pytest.fixture
def served(ws, monkeypatch):
    "A mounted Abhyasa app over an isolated learning store and hosted scripted backend."
    import abhyasa.models as models
    import abhyasa.path as path
    from abhyasa.agent_tools import create_walk
    from abhyasa.learner import temp_learning

    lr = temp_learning()
    monkeypatch.setattr(host, 'learn_store', lambda ws, vault=None, write=False: ('test', lr))
    monkeypatch.setattr(host, 'HOSTS', ('testserver',))
    made = create_walk(lr, lambda p, sp='': PLAN, 'fractions', settings={})
    jid = made['walk']
    for step in lr.journey(jid).steps:
        lr.update(step['slug'], core='A fraction names equal parts of a whole.')
        lr.walk_slug(jid, step['slug'], check={**step['check'], 'q': 'What does a fraction name?'})
    be = install(ws, [], spec=ModelSpec('learn-hosted', 'remote', 'scripted/model', ctx=8000))
    be.supports_deadline = True
    calls, jobs, routed, forbidden = [], [], [], []
    def oneshot(prompt, sp, max_tokens, deadline=None):
        calls.append((prompt, sp)); return _reply(jobs[-1])
    be._oneshot = oneshot
    ws.ai._be = ws.ai._be_or_none = lambda job='turn': jobs.append(job) or be
    def own(*a, **kw):
        forbidden.append(a); raise AssertionError('hosted Learn bypassed Leela Assistant.oneshot')
    for mod, names in ((models, ('ramabana_agent', 'ramabana_oneshot', 'ramabana_stream', 'model_ask', 'ramabana_worker', 'ramabana_lead')),
                       (path, ('ramabana_lead', 'ramabana_worker'))):
        for name in names:
            if hasattr(mod, name): monkeypatch.setattr(mod, name, own)
    connect = socket.socket.connect
    def local(self, address):
        name = address[0] if isinstance(address, tuple) else ''
        if name not in ('127.0.0.1', '::1', 'localhost'): raise AssertionError(f'non-loopback connection: {address!r}')
        return connect(self, address)
    monkeypatch.setattr(socket.socket, 'connect', local)
    original = models.Router.for_
    def seen(self, task, *a, **kw):
        routed.append(task)
        assert task in TASKS, f'unlisted Router task: {task}'
        return original(self, task, *a, **kw)
    monkeypatch.setattr(models.Router, 'for_', seen)
    app, cl = ide_app(ws), None
    cl = TestClient(app)
    yield dict(app=app, cl=cl, lr=lr, jid=jid, be=be, calls=calls, jobs=jobs, routed=routed, forbidden=forbidden, ws=ws)
    cl.close()
    _hosted(app).stop()


@pytest.mark.parametrize('route, data, tasks', [
    ('answer', dict(answer='Equal parts of a whole.', confidence=70), ['grade']),
    ('hint', {}, ['hint']),
    ('giveup', dict(confidence=0), ['lesson']),
    ('note', {}, []),
])
def test_hosted_walk_model_routes_use_only_leela_oneshot(served, route, data, tasks):
    s = served; _start(s)
    url = f"/w/{s['jid']}/0/{route}"
    r = s['cl'].get(url) if route == 'note' else s['cl'].post(url, data=data)
    assert r.status_code == 200, r.text[:300]
    assert s['jobs'] == tasks and len(s['calls']) == len(tasks), (s['jobs'], s['calls'])
    assert set(s['routed']) <= TASKS and not s['forbidden']


def test_hosted_agent_tools_share_task_registry(served):
    from abhyasa.agent_tools import create_walk, record_attempt
    from leela.blocks.learn.tools import learn_ask

    s = served
    ask = learn_ask(s['ws'].ai, 'plan')
    made = create_walk(s['lr'], ask, 'fractions through the agent pane', settings={})
    assert made['status'] == 'ok' and s['jobs'] == ['plan']
    ask = learn_ask(s['ws'].ai, 'grade')
    made = record_attempt(s['lr'], s['jid'], 0, 'Equal parts.', 'agent-grade', ask, settings={})
    assert made['status'] == 'ok' and s['jobs'][-1] == 'grade'
    assert set(s['routed']) <= TASKS and not s['forbidden']


@pytest.mark.parametrize('vault_pii', ['redact', 'refuse'])
def test_hosted_answer_obeys_pii_before_the_backend_and_keeps_original_attempt(served, vault_pii):
    s = served; _start(s); s['ws'].vault_pii = vault_pii
    address = 'jane.doe@example.com'
    r = s['cl'].post(f"/w/{s['jid']}/0/answer", data=dict(answer=address, confidence=70))
    if vault_pii == 'redact':
        assert r.status_code == 200, r.text[:300]
        assert len(s['calls']) == 1 and address not in s['calls'][0][0]
        assert any(a.answer == address for a in s['lr'].attempts(limit=None))
    else:
        assert r.status_code == 403 and 'privacy setting blocks it' in r.text, r.text[:300]
        assert not s['calls']
    assert not s['forbidden']


def test_hosted_stop_is_bounded_while_a_model_call_blocks(served):
    s = served; _start(s)
    entered, release = threading.Event(), threading.Event()
    def block(prompt, sp, max_tokens, deadline=None):
        entered.set(); release.wait(5); return GRADE
    s['be']._oneshot = block
    t = threading.Thread(target=lambda: s['cl'].post(f"/w/{s['jid']}/0/answer", data=dict(answer='Equal parts.', confidence=70)))
    t.start(); assert entered.wait(2)
    began = time.monotonic(); _hosted(s['app']).stop()
    assert time.monotonic() - began < 1.5
    release.set(); t.join(3)


GAPS = GRADE.replace('"misconception"', '"gaps": ["common denominators"], "misconception"')


def _window(ws, lr, monkeypatch, vault_pii):
    "One more Leela window over the same Learn store: its own assistant, backend and privacy setting."
    ws.vault_pii = vault_pii
    be = install(ws, [], spec=ModelSpec(f'win-{vault_pii}', 'remote', 'scripted/model', ctx=8000))
    be.supports_deadline = True
    calls = []
    be._oneshot = lambda prompt, sp, max_tokens, deadline=None: calls.append(prompt) or (GAPS if 'Return JSON' not in prompt and 'grade' in prompt.lower() else GRADE)
    ws.ai._be = ws.ai._be_or_none = lambda job='turn': be
    app = ide_app(ws)
    return dict(app=app, cl=TestClient(app), ws=ws, calls=calls, h=_hosted(app))


def _two(served, request, monkeypatch, key=lambda ws, make=False: 'one-learn-vault'):
    from leela.workspace import Workspace
    from tests.conftest import fixture_dir
    s = served
    monkeypatch.setattr(host, 'learn_key', key)
    a = _window(s['ws'], s['lr'], monkeypatch, 'redact')
    b = _window(Workspace(roots=[fixture_dir(request)], port=8001), s['lr'], monkeypatch, 'refuse')
    return a, b


def test_two_windows_share_one_app_and_each_answers_through_its_own_workspace(served, request, monkeypatch):
    s = served
    a, b = _two(s, request, monkeypatch)
    try:
        assert a['cl'].post('/learn/abh/open').status_code == 200 and b['cl'].post('/learn/abh/open').status_code == 200
        assert a['h'].app is b['h'].app and a['h'].app is not None
        a['cl'].post(f"/w/{s['jid']}/start"); a['cl'].get(f"/w/{s['jid']}/0?pane=1"); a['cl'].get(f"/w/{s['jid']}/0/check")
        a['calls'].clear()
        address = 'jane.doe@example.com'
        r = b['cl'].post(f"/w/{s['jid']}/0/answer", data=dict(answer=address, confidence=70))
        assert r.status_code == 403 and not a['calls'] and not b['calls']
        r = a['cl'].post(f"/w/{s['jid']}/0/answer", data=dict(answer=address, confidence=70))
        assert r.status_code == 200 and a['calls'] and not b['calls'] and all(address not in c for c in a['calls'])
    finally:
        a['h'].stop(); b['h'].stop(); b['cl'].close(); a['cl'].close()


def test_a_background_pool_job_uses_the_workspace_that_submitted_it(served, request, monkeypatch):
    s = served
    a, b = _two(s, request, monkeypatch)
    try:
        a['cl'].post('/learn/abh/open')
        app = a['h'].app
        pool = app.state.svc['pool']
        for w in (a, b):
            with host.using(w['ws']): pool.submit(lambda: host.learn_ask(host._Live(), 'extract')('background')).result(3)
        assert len(a['calls']) == 1 and len(b['calls']) == 1
    finally:
        a['h'].stop(); b['h'].stop(); b['cl'].close(); a['cl'].close()


def test_a_second_window_with_another_learn_vault_rebuilds_the_app(served, request, monkeypatch):
    s = served
    keys = {'a': 'vault-a'}
    a, b = _two(s, request, monkeypatch, lambda ws, make=False: keys['a'])
    try:
        a['cl'].post('/learn/abh/open')
        first = a['h'].app
        a['cl'].post('/learn/abh/open')
        assert a['h'].app is first, 'the same vault keeps the one app'
        keys['a'] = 'vault-b'
        assert a['cl'].get('/learn/abh/you/strengths').status_code == 409, 'a window on another vault must open first'
        assert b['cl'].post('/learn/abh/open').status_code == 200
        assert b['h'].app is not first and first.state.stopped is True and not getattr(b['h'].app.state, 'stopped', False)
        assert a['h'].app is b['h'].app and a['cl'].get('/learn/abh/you/strengths').status_code == 200
    finally:
        a['h'].stop(); b['h'].stop(); b['cl'].close(); a['cl'].close()
