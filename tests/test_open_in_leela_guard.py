"""Only Leela's own learn redirect grants a same-site IDE navigation."""

import pytest
from starlette.responses import PlainTextResponse, RedirectResponse
from starlette.testclient import TestClient

import leela.hub as hub
from leela.hub import LoopbackHostGuard
from learn_data import JID, rig  # noqa: F401


NAV = {'sec-fetch-site': 'same-site', 'sec-fetch-mode': 'navigate', 'sec-fetch-dest': 'document'}


@pytest.fixture
def client():
    async def app(scope, receive, send):
        response = RedirectResponse('/', 303) if scope['path'] == '/learn' else PlainTextResponse('IDE')
        await response(scope, receive, send)
    return TestClient(LoopbackHostGuard(app), base_url='http://127.0.0.1:5011')


def test_open_in_leela_redirect_allows_the_browser_navigation(client):
    redirect = client.get('/learn?go=1', headers=NAV, follow_redirects=False)
    assert redirect.status_code == 303 and redirect.headers['location'] == '/'
    # The redirect retains same-site metadata: Abhyasa is on another local port.
    response = client.get('/', headers=NAV)
    assert response.status_code == 200, response.text
    assert response.text == 'IDE'
    assert client.get('/', headers=NAV).status_code == 421, 'the grant is single-use'


@pytest.mark.parametrize('method,path,headers', [
    ('POST', '/', NAV), ('PUT', '/', NAV), ('DELETE', '/', NAV), ('HEAD', '/', NAV),
    ('GET', '/', {**NAV, 'sec-fetch-mode': 'cors'}),
    ('GET', '/', {**NAV, 'sec-fetch-mode': 'no-cors'}),
    ('GET', '/', {**NAV, 'sec-fetch-dest': 'iframe'}),
    ('GET', '/', {**NAV, 'sec-fetch-site': 'cross-site'}),
    ('GET', '/dev/start', NAV), ('GET', '/learn/lookup', NAV),
    ('GET', '/', {**NAV, 'host': 'evil.example'}),
    ('GET', '/', {**NAV, 'origin': 'https://evil.example'}),
])
def test_redirect_grant_does_not_admit_other_requests(client, method, path, headers):
    assert client.get('/learn', headers=NAV, follow_redirects=False).status_code == 303
    assert client.request(method, path, headers=headers).status_code == 421


def test_bare_same_site_navigation_still_needs_a_redirect(client):
    assert client.get('/', headers=NAV).status_code == 421


def test_redirect_grant_expires(client, monkeypatch):
    now = hub.time.monotonic()
    assert client.get('/learn', headers=NAV, follow_redirects=False).status_code == 303
    monkeypatch.setattr(hub.time, 'monotonic', lambda: now + 31)
    assert client.get('/', headers=NAV).status_code == 421


def test_redirect_grant_is_bound_to_the_destination_port(client):
    assert client.get('/learn', headers=NAV, follow_redirects=False).status_code == 303
    assert client.get('/', headers={**NAV, 'host': '127.0.0.1:5012'}).status_code == 421


def test_non_redirect_learn_page_does_not_grant_navigation():
    async def app(scope, receive, send):
        await PlainTextResponse('Learn page')(scope, receive, send)
    c = TestClient(LoopbackHostGuard(app), base_url='http://127.0.0.1:5011')
    assert c.get('/learn', headers=NAV).status_code == 200
    assert c.get('/', headers=NAV).status_code == 421


def test_real_learn_redirect_reaches_the_ide(rig):
    c = TestClient(LoopbackHostGuard(rig[0].app), base_url='http://127.0.0.1:5011')
    response = c.get(f'/learn?walk={JID}&step=0&go=1', headers=NAV)
    assert [r.status_code for r in response.history] == [303]
    assert response.url.path == '/' and response.status_code == 200
