import pytest
from starlette.routing import Match, Mount
from starlette.testclient import TestClient

from leela.app import ide_app
from leela.blocks.learn import host
from tests.fakemodel import install
from tools.s2_native_pilot import PLAN
from ramabana.core import ModelSpec

ORIG_HOSTS = host.HOSTS
GRADE = r'{"correct": true, "grade": 10, "feedback": "Correct.", "first_error": "", "misconception": ""}'
CLASH = [('GET', '/'), ('GET', '/learn'), ('GET', '/search'), ('GET', '/settings'), ('GET', '/keys.json'), ('POST', '/keys/save')]


@pytest.fixture
def served(ws, monkeypatch):
    "Leela's app over a temp Learn store with a walk whose first step has a check, and a scripted backend behind `ai.oneshot`."
    from abhyasa.agent_tools import create_walk
    from abhyasa.learner import temp_learning
    lr = temp_learning()
    monkeypatch.setattr(host, 'learn_store', lambda ws, vault=None, write=False: ('test', lr))
    monkeypatch.setattr(host, 'HOSTS', ('testserver',))
    made = create_walk(lr, lambda p, sp='': PLAN, 'fractions', settings={})
    assert made['status'] == 'ok'
    jid = made['walk']
    for step, q in zip(lr.journey(jid).steps, ('What does a fraction name?', 'How do you add fractions?')):
        lr.update(step['slug'], core='A fraction names equal parts of a whole.')
        lr.walk_slug(jid, step['slug'], note_none=True, check={**step['check'], 'q': q})
    be = install(ws, [], spec=ModelSpec('grade-hosted', 'remote', 'scripted/model', ctx=8000))
    calls, routed = [], []
    be.supports_deadline = True
    be._oneshot = lambda prompt, sp, max_tokens, deadline=None: calls.append(prompt) or GRADE
    ws.ai._be = ws.ai._be_or_none = lambda job='turn': routed.append(job) or be
    app = ide_app(ws)
    cl = TestClient(app)
    yield dict(app=app, cl=cl, lr=lr, jid=jid, calls=calls, routed=routed, ws=ws)
    cl.close()
    for h in app.router.routes:
        if isinstance(h, Mount) and isinstance(h.app, host.Hosted): h.app.stop()


def owner(app, method, path):
    scope = dict(type='http', method=method, path=path, root_path='', headers=[], query_string=b'')
    return next(r for r in app.router.routes if r.matches(scope)[0] == Match.FULL)


def test_leela_routes_win_every_clash(served):
    app = served['app']
    assert isinstance(app.router.routes[-1], Mount) and app.router.routes[-1].path == ''
    for method, path in CLASH:
        assert not isinstance(owner(app, method, path), Mount), (method, path)
    r = served['cl'].get('/')
    assert r.status_code == 200 and 'abhyasa_session' not in r.cookies and 'id="check"' not in r.text
    assert served['cl'].get('/keys.json').status_code in (200, 400, 403, 404)
    assert served['cl'].get('/learn').headers.get('hx-redirect') is None


def start(s):
    cl, jid = s['cl'], s['jid']
    assert cl.post('/learn/abh/open').json() == {'ok': True, 'base': '/learn/abh'}
    cl.post(f'/w/{jid}/start')
    page = cl.get(f'/w/{jid}/0?pane=1')
    cl.get(f'/w/{jid}/0/check')
    return page


def test_an_abhyasa_route_answers_with_abhyasa_step_page(served):
    r = start(served)
    assert r.status_code == 200 and 'id="check"' in r.text


@pytest.mark.parametrize('hdr', [{'Origin': 'http://evil.example'}, {'Sec-Fetch-Site': 'cross-site'}])
def test_a_cross_site_post_to_an_abhyasa_route_is_refused(served, hdr):
    s = served
    r = s['cl'].post(f"/w/{s['jid']}/0/answer", data=dict(answer='x', confidence=70), headers=hdr)
    assert r.status_code == 403 and not s['calls'] and not s['lr'].attempts()


def test_leela_and_abhyasa_keep_their_own_cookies(served):
    from abhyasa.app import SESSION_COOKIE
    s = served; cl = s['cl']
    assert SESSION_COOKIE == 'abhyasa_session'
    mw = [m for m in s['app'].user_middleware if m.cls.__name__ == 'SessionMiddleware']
    leela_cookie = mw[0].kwargs['session_cookie'] if mw else 'session_'
    assert leela_cookie != SESSION_COOKIE
    cl.get('/')
    before = dict(cl.cookies)
    start(s)
    after = dict(cl.cookies)
    assert {k: v for k, v in before.items() if k != SESSION_COOKIE} == {k: v for k, v in after.items() if k != SESSION_COOKIE}
    cl.get('/')
    assert {k: v for k, v in dict(cl.cookies).items() if k != SESSION_COOKIE} == {k: v for k, v in before.items() if k != SESSION_COOKIE}


def test_an_answer_through_the_abhyasa_route_goes_through_oneshot(served):
    s = served; cl = s['cl']; lr = s['lr']
    start(s)
    r = cl.post(f"/w/{s['jid']}/0/answer", data=dict(answer='Equal parts of a whole.', confidence=70))
    assert r.status_code == 200, r.text[:300]
    assert s['calls'] and 'grade' in s['routed'], (s['calls'], s['routed'])
    assert lr.attempts()
    n = len(s['calls'])
    s['ws'].vault_pii = 'refuse'
    cl.post(f"/w/{s['jid']}/0/answer", data=dict(answer='jane.doe@example.com', confidence=70))
    assert len(s['calls']) == n


def test_building_the_hosted_app_starts_no_speech_and_no_second_agent(served, monkeypatch):
    import abhyasa.models as models, abhyasa.path as path
    def own(*a, **kw): raise AssertionError('the hosted app made a model call of its own')
    for n in ('ramabana_agent', 'ramabana_oneshot', 'model_ask'): monkeypatch.setattr(models, n, own)
    monkeypatch.setattr(path, 'ramabana_lead', own)
    s = served
    start(s)
    h = next(r.app for r in s['app'].router.routes if isinstance(r, Mount) and isinstance(r.app, host.Hosted))
    assert h.app.state.svc['speech'].status == 'not loaded'
    s['cl'].post(f"/w/{s['jid']}/0/answer", data=dict(answer='Equal parts of a whole.', confidence=70))
    assert s['calls']


def test_one_answer_path_for_the_route_and_the_agent_tool(served):
    from abhyasa.agent_tools import record_attempt, walk_state
    from leela.blocks.learn.tools import learn_ask
    s = served; cl = s['cl']; lr = s['lr']; jid = s['jid']
    start(s)
    cl.post(f'/w/{jid}/0/answer', data=dict(answer='Equal parts of a whole.', confidence=70))
    slug = lr.journey(jid).steps[0]['slug']
    viaroute = [a for a in lr.attempts(slug, limit=None)]
    assert len(viaroute) == 1
    ask = learn_ask(s['ws'].ai, 'grade')
    again = record_attempt(lr, jid, 0, 'Equal parts again.', 'agent-0', ask, settings={})
    assert again['error'] == 'attempt_conflict', 'the agent tool sees the answer the route stored'
    r = record_attempt(lr, jid, 1, 'Add the tops over a common bottom.', 'agent-1', ask, settings={})
    assert r['status'] == 'ok', (r.get('error'), r.get('data'))
    slug1 = lr.journey(jid).steps[1]['slug']
    assert len(lr.attempts(slug, limit=None)) == 1 and [a.get('attempt_id') for a in lr.attempts(slug1, limit=None)] == ['agent-1']
    st = walk_state(lr, jid, settings={})
    assert st['status'] == 'ok'
    done = [x['i'] for x in st['data']['steps'] if x.get('status') not in ('open', 'unseen', 'pending', None, '')]
    assert {0, 1} <= set(done), st['data']['steps']
    page = cl.get(f'/w/{jid}/1?pane=1')
    assert page.status_code == 200

def test_the_hosted_app_gets_a_copy_of_the_scope(monkeypatch):
    "Abhyasa's session middleware assigns `scope['session']`; on a shared dict that replaces the session Leela's middleware holds."
    import asyncio
    async def run(scope, receive, send): scope['session'] = {'abhyasa': 1}; scope['path_params'] = 'inner'
    from starlette.routing import Route
    class Inner:
        router = type('R', (), dict(routes=[Route('/w/{x}', run)]))
        async def __call__(self, *a): await run(*a)
    inner = Inner()
    monkeypatch.setattr(host, 'learn_key', lambda ws, make=False: 'k')
    monkeypatch.setattr(host, 'learn_settings', lambda ws: {})
    monkeypatch.setattr(host, 'HOSTS', ('testserver',))
    box = host.Shared(); box.app, box.key = inner, 'k'
    h = host.Hosted(None, reg=box)
    outer = dict(type='http', method='GET', path='/w/x', headers=[(b'host', b'testserver')], session={'leela': 1})
    async def go(): await h(outer, None, None)
    asyncio.run(go())
    assert outer['session'] == {'leela': 1} and 'path_params' not in outer


def test_a_leela_route_keeps_its_405_for_the_wrong_method(served):
    "Starlette takes a later full match over an earlier partial one, so a catch-all mount would answer for `GET /fs/add_root`."
    r = served['cl'].get('/fs/add_root')
    assert r.status_code == 405, (r.status_code, r.text[:100])


def test_the_app_is_built_by_open_only_and_stopped_on_shutdown(served):
    import asyncio
    s = served; cl = s['cl']
    h = next(r.app for r in s['app'].router.routes if isinstance(r, Mount) and isinstance(r.app, host.Hosted))
    cl.get('/'); cl.get('/learn')
    for path in ('/robots.txt', '/typo', '/w/x/0', '/assets/x.js', '/learn/abh/robots.txt'):
        assert cl.get(path).status_code in (404, 409), path
        assert h.app is None, f'{path} built the Abhyasa app'
    start(s)
    assert h.app is not None and not getattr(h.app.state, 'stopped', False)
    app = h.app
    stop = next(f for f in s['app'].lifespan.shutdown if f.__name__ == 'stop')
    asyncio.run(stop())
    assert app.state.stopped is True and h.app is None


def test_before_open_the_prefix_route_says_learn_not_open(served):
    r = served['cl'].get('/learn/abh/search')
    assert r.status_code == 409 and r.json() == {'ok': False, 'error': 'learn_not_open'}


def test_after_open_only_abhyasa_routes_pass_and_the_prefix_reaches_clashing_pages(served):
    s = served; cl = s['cl']; start(s)
    assert cl.get('/robots.txt').status_code == 404 and cl.get('/typo').status_code == 404 and cl.get('/learn/abh/typo').status_code == 404
    assert cl.get('/you/strengths').status_code == 200 and cl.get('/learn/abh/you/strengths').status_code == 200
    assert cl.get(f"/learn/abh/w/{s['jid']}/0?pane=1").status_code == 200
    r = cl.get('/learn/abh/', follow_redirects=False)
    assert r.status_code in (200, 302, 303)
    assert cl.get('/learn/abh/search').status_code != 409 and cl.get('/search').status_code != 409


def test_a_slug_host_is_accepted_and_a_foreign_host_refused(served, monkeypatch):
    monkeypatch.setattr(host, 'HOSTS', ORIG_HOSTS)
    app = served['app']
    at = lambda name: TestClient(app, base_url=f'http://{name}')
    for name, code in (('alpha.localhost', 200), ('localhost', 200), ('evil.example', 403), ('localhost.evil.example', 403)):
        assert at(name).post('/learn/abh/open').status_code == code, name
    cl = at('alpha.localhost')
    assert cl.get('/you/strengths').status_code == 200 and cl.get('/learn/abh/you/strengths').status_code == 200
    for path in ('/you/strengths', '/learn/abh/you/strengths'): assert cl.get(path, headers={'Host': 'evil.example'}).status_code == 403


DOC = {'Sec-Fetch-Dest': 'document', 'Accept': 'text/html'}
SHELL = ('class="brand"', 'aria-label="Main"', 'class="gear', 'Caps+E', 'Keys:')


@pytest.mark.parametrize('path', ['/learn/abh/', '/learn/abh/w/nope/0', '/learn/abh/w/nope/0?pane=1', '/learn/abh/?pane=1', '/learn/abh/no-such-page'])
def test_a_page_opened_on_its_own_never_shows_abhyasas_shell(served, path):
    s = served; start(s)
    r = s['cl'].get(path, headers=DOC)
    assert r.status_code in (200, 404) and 'lee-learn' in r.text, r.text[:300]
    assert not any(x in r.text for x in SHELL) and 'abhyasa' not in r.text.lower().replace('/learn/abh/', ''), r.text[:600]


def test_a_page_the_tab_asks_for_still_comes_from_abhyasa(served):
    s = served; start(s)
    r = s['cl'].get('/learn/abh/you/strengths?pane=1', headers={'HX-Request': 'true'})
    assert r.status_code == 200 and 'lee-learn' not in r.text
    assert s['cl'].get('/learn/abh/nav/extra?path=/').status_code == 200


def test_a_page_opened_on_its_own_before_learn_opens_gets_the_box(served):
    r = served['cl'].get('/learn/abh/w/x/0', headers=DOC)
    assert r.status_code == 404 and 'lee-learn' in r.text and not any(x in r.text for x in SHELL)
