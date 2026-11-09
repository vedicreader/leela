"Hosted Abhyasa routes sit under Leela's origin: Leela's own guard, Abhyasa's `LocalOnly` and the file rules must hold for each of them."
import re
import pytest
from starlette.routing import Mount
from starlette.testclient import TestClient

from leela import leela_cfg
from leela.hub import LoopbackHostGuard
from leela.blocks.learn import host
from tests.test_learn_host import served, ORIG_HOSTS   # noqa: F401  (the fixture)

BASE = 'http://127.0.0.1:5001'
ME = 'http://127.0.0.1:5001'
REFUSED = (403, 421)   # the guard turns a foreign Host or site away with 421, a foreign Origin on a change with 403
CROSS = [dict(Origin='https://evil.example', **{'Sec-Fetch-Site': 'cross-site'}), {'Origin': 'https://evil.example'}, {'Sec-Fetch-Site': 'cross-site'}]
REBIND = ['evil.example', 'localhost.evil.example', '127.0.0.1.evil.example']
OWN = {'Origin': ME, 'Sec-Fetch-Site': 'same-origin'}


@pytest.fixture(params=['guarded', 'bare'])
def sec(request, served, monkeypatch):
    "The hosted app opened; `guarded` is how `serve_ide` runs it (Leela's guard outside), `bare` is only Hosted and `LocalOnly`."
    monkeypatch.setattr(host, 'HOSTS', ORIG_HOSTS)
    app = served['app']
    outer = LoopbackHostGuard(app) if request.param == 'guarded' else app
    cl = TestClient(outer, base_url=BASE)
    assert cl.post('/learn/abh/open', headers=OWN).json()['ok']
    yield dict(served, cl=cl, mode=request.param)
    cl.close()


def hosted(app):
    return next(r for r in reversed(app.router.routes) if isinstance(r, Mount)).app


def routes(s):
    "(method, path) of each route of the built Abhyasa app."
    app = hosted(s['app']).live()
    return [(m, r.path) for r in app.router.routes if hasattr(r, 'methods') for m in sorted(set(r.methods) - {'HEAD'})]


def fill(path): return re.sub(r'\{[^}]*\}', 'x', path)


def test_each_route_has_a_group(sec):
    got = {}
    for m, p in routes(sec): got.setdefault(group(m, p), []).append((m, p))
    assert len(sum(got.values(), [])) > 150 and not got.get('?')
    assert {'static', 'settings', 'files', 'model', 'write', 'read'} <= set(got)


def group(m, p):
    "The first rule that fits: what the route can reach."
    if p.startswith('/{fname'): return 'static'
    if p.startswith(('/assets', '/vendor', '/rupaka', '/favicon')) or re.search(r'\.(png|html|mjs|js|css|json)$|/img|/fig$', p): return 'serve'
    if p.startswith('/settings') or p == '/keys/float': return 'settings'
    if re.search(r'^/learn/(file|files|pick|walk-source|read)$|^/walk/(attach|new|unfile)$|^/add$|/notebook$|/data', p): return 'files'
    if m == 'POST' and re.search(r'^/voice|/(answer|hint|giveup|teach|predict|ask|ladder|improve|replan|fill|again|leela|check|start|slide|beat)$|^/start$|^/demo|^/rh|^/talk/new', p): return 'model'
    if m == 'POST': return 'write'
    return 'read'


# (a) a cross-site POST is refused for each kind of state change
POSTS = ['/w/{jid}/0/answer', '/w/{jid}/edit', '/learn/files', '/learn/walk-source', '/settings/value', '/settings/key', '/voice/stt', '/demo/x/predict', '/walk/new', '/learn/abh/open']


@pytest.mark.parametrize('hdr', CROSS)
@pytest.mark.parametrize('path', POSTS)
def test_a_cross_site_post_is_refused(sec, path, hdr):
    s = sec
    r = s['cl'].post(path.format(jid=s['jid']), data=dict(answer='x', confidence=70, jid=s['jid'], q='~/x'), headers=hdr)
    assert r.status_code in REFUSED and not s['calls'] and not s['lr'].attempts()


def test_leela_makes_the_same_decision_for_its_own_route(sec):
    "The same headers, a Leela route and an Abhyasa route: both refused, and both let the same-origin request in."
    if sec['mode'] != 'guarded': pytest.skip('Leela routes carry no guard without `serve_ide`')
    cl = sec['cl']
    for hdr in CROSS + [{'Origin': 'http://127.0.0.1:9999'}, {'Origin': 'http://127.0.0.1:9999', 'Sec-Fetch-Site': 'same-site'}]:
        own, abh = cl.post('/keys/save', data={}, headers=hdr), cl.post(f"/w/{sec['jid']}/0/hint", data={}, headers=hdr)
        assert own.status_code == abh.status_code in REFUSED, hdr
    assert cl.post('/keys/save', json={}, headers=OWN).status_code not in REFUSED
    assert cl.post(f"/w/{sec['jid']}/0/hint", data={}, headers=OWN).status_code not in REFUSED


# (b) DNS rebinding
@pytest.mark.parametrize('name', REBIND)
@pytest.mark.parametrize('method', ['GET', 'POST'])
def test_a_rebinding_host_is_refused(sec, name, method):
    s = sec
    for path in (f"/w/{s['jid']}/0", '/jobs.json', '/learn/read?q=~', '/learn/abh/jobs.json'):
        r = s['cl'].request(method, path, headers={'Host': name, 'Origin': f'http://{name}'} if method == 'POST' else {'Host': name})
        assert r.status_code in REFUSED, (path, r.text[:80])
        assert 'fraction' not in r.text and not s['calls']


# (c) another port on the same machine
@pytest.mark.parametrize('hdr', [{'Origin': 'http://127.0.0.1:9999'}, {'Origin': 'http://127.0.0.1:9999', 'Sec-Fetch-Site': 'same-site'}, {'Origin': 'http://localhost:5001'}])
@pytest.mark.parametrize('path', ['/w/{jid}/0/answer', '/settings/value', '/learn/files'])
def test_a_post_from_another_port_is_refused(sec, path, hdr):
    r = sec['cl'].post(path.format(jid=sec['jid']), data=dict(answer='x', confidence=70), headers=hdr)
    assert r.status_code in REFUSED and not sec['calls'] and not sec['lr'].attempts()


def test_the_page_of_the_owner_is_not_refused(sec):
    r = sec['cl'].post(f"/w/{sec['jid']}/0/answer", data=dict(answer='x', confidence=70), headers=OWN)
    assert r.status_code not in REFUSED


# (e) a GET cannot start anything for another site
FRAME = [{'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Dest': 'iframe', 'Sec-Fetch-Mode': 'navigate'},
         {'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Dest': 'document', 'Sec-Fetch-Mode': 'navigate'},
         {'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Dest': 'image', 'Sec-Fetch-Mode': 'no-cors'}]


@pytest.mark.parametrize('hdr', FRAME)
def test_no_get_route_answers_another_site(sec, hdr):
    s = sec
    gets = [p for m, p in routes(s) if m == 'GET' and not p.startswith('/{fname')]
    assert len(gets) > 90
    left = [(p, r.status_code) for p in gets if (r := s['cl'].get(host.BASE + fill(p), headers=hdr)).status_code not in REFUSED]
    assert not left


# (f) other sites cannot frame an Abhyasa page
@pytest.mark.parametrize('path', ['/w/{jid}/0?pane=1', '/learn/abh/', '/learn/abh/jobs.json', '/assets/x', '/learn/abh/w/{jid}'])
def test_a_hosted_page_cannot_be_framed(sec, path):
    r = sec['cl'].get(path.format(jid=sec['jid']), headers=OWN)
    assert "frame-ancestors 'self'" in r.headers.get('content-security-policy', ''), (r.status_code, dict(r.headers))
    assert r.headers.get('x-frame-options', '').upper() == 'SAMEORIGIN'


# (g) the static route stays shut
@pytest.fixture
def folder(tmp_path, monkeypatch):
    (tmp_path/'c').mkdir(); (tmp_path/'v'/'a').mkdir(parents=True); (tmp_path/'w'/'a').mkdir(parents=True)
    for p in ('secret.txt', 'c/inner.txt', 'v/a/deep.txt', 'w/a/deep.html', 'secret.yaml'): (tmp_path/p).write_text('TOP-SECRET')
    monkeypatch.chdir(tmp_path)
    return tmp_path


PATHS = ['/secret.txt', '/secret.yaml', '/c/inner.txt', '/v/a/deep.txt', '/w/a/deep.html', '/v/%2e%2e/secret.txt', '/v/..%2fsecret.txt', '/c/%2e%2e%2fsecret.txt',
         '/c/../secret.txt', '/v/a/../../secret.txt', '/assets/..%2f..%2fsecret.txt', '/assets/%2e%2e/secret.txt', '/vendor/../secret.txt', '/vendor/%2e%2e/secret.txt',
         '/rupaka/..%2fsecret.txt', '/w/%2e%2e/secret.txt', '/w/..%5csecret.txt', '/%2e%2e/secret.txt', '//secret.txt']


@pytest.mark.parametrize('pre', ['', '/learn/abh'])
@pytest.mark.parametrize('path', PATHS)
def test_the_static_route_does_not_serve_the_working_folder(sec, folder, path, pre):
    r = sec['cl'].get(pre + path, headers=OWN)
    assert 'TOP-SECRET' not in r.text


# (h) the folder rules
@pytest.fixture
def home(tmp_path, monkeypatch):
    h, out = tmp_path/'home', tmp_path/'outside'
    (h/'docs').mkdir(parents=True); out.mkdir(); (h/'.hid').mkdir()
    (out/'secret.md').write_text('TOP-SECRET'); (h/'docs'/'ok.md').write_text('fine')
    (h/'link').symlink_to(out, target_is_directory=True)
    (h/'docs'/'leak.md').symlink_to(out/'secret.md')
    monkeypatch.setenv('HOME', str(h))
    return h, out


def test_the_filing_rules_keep_to_the_home_folder(home):
    from abhyasa.sources import file_why, folder_why
    h, out = home
    assert folder_why(str(h/'docs')) == ''
    for bad in ('/etc', '/', str(out), str(h/'link'), str(h/'.hid'), str(h), '~/../outside'): assert folder_why(bad), bad
    assert file_why(str(h/'docs'/'ok.md')) == ''
    for bad in ('/etc/hosts', str(out/'secret.md'), str(h/'docs'/'leak.md')): assert file_why(bad), bad


@pytest.mark.parametrize('q', ['/etc', '/', '@OUT', '@LINK', '~/../outside', '~/.hid'])
def test_adding_a_source_refuses_a_folder_outside_home(sec, home, q):
    h, out = home
    q = {'@OUT': str(out), '@LINK': str(h/'link')}.get(q, q)
    s = sec
    r = s['cl'].post('/learn/walk-source', data=dict(jid=s['jid'], q=q), headers=OWN)
    assert 'TOP-SECRET' not in r.text and r.status_code < 500
    assert not (s['lr'].journey(s['jid']).get('filing') or ())


# (i) settings and keys are Leela's
WRITES = [('/settings/value', dict(name='links.pages', value='9')), ('/settings/default', dict(name='links.pages')), ('/settings/key', dict(key='sk-abcdefgh1234')),
          ('/settings/model', dict(task='default', model='x/y')), ('/settings/look', dict(theme='x', mode='dark')), ('/settings/prompt', dict(name='x', text='x')),
          ('/settings/use', dict(engine='openai', model='x')), ('/settings/get', dict(model='x/y')), ('/settings/voice', dict(engine='x')), ('/keys/float', dict(on='1')),
          ('/settings/model/test', dict(task='default', model='x'))]


@pytest.mark.parametrize('path,data', WRITES)
def test_a_hosted_settings_write_answers_404_and_writes_nothing(sec, path, data):
    cfg = leela_cfg/host.STATE
    before = sorted(p.name for p in cfg.glob('*')) if cfg.exists() else []
    r = sec['cl'].post(path, data=data, headers=OWN)
    assert r.status_code == 404
    assert sorted(p.name for p in cfg.glob('*')) == before and not (cfg/'keys.env').exists()


@pytest.mark.parametrize('path', ['/settings/chip?task=ask', '/settings/catalog'])
def test_the_model_chip_stays(sec, path):
    assert sec['cl'].get(path, headers=OWN).status_code != 404
