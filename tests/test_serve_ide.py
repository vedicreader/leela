"`serve_ide` actually starting, for both shapes of workspace: a real port, a real uvicorn."

from __future__ import annotations

import json, socket, threading, urllib.error, urllib.request

import pytest

from leela.app import serve_ide
from leela.desktop import wait_for_http

pytestmark = pytest.mark.usefixtures('_fake_kernels', '_servers_stop')

@pytest.fixture
def _servers_stop(monkeypatch):
    "A server left up polls the keymap file of every later test on the worker, and reads it half-written."
    import uvicorn
    up = []
    def run(app, **kw):
        up.append((s := uvicorn.Server(uvicorn.Config(app, **kw)), threading.current_thread()))
        s.run()
    monkeypatch.setattr(uvicorn, 'run', run)
    yield
    for s, _ in up: s.should_exit = True
    for _, t in up: t.join(timeout=30)
    assert not any(t.is_alive() for _, t in up), 'a server outlived its test'

@pytest.fixture
def _fake_kernels(monkeypatch):
    import asyncio

    from leela.blocks.runtime.kernels import KernelPool

    class K:
        alive, base, pid, boot_error, token, kernel_kind = True, None, 1, None, None, 'ipykernel'
        async def api(self, *a, **kw): return None
        async def shutdown(self): pass

    async def get(self, key, **kw): return self.kernels.setdefault(key, K())
    monkeypatch.setattr(KernelPool, 'get', get)
    monkeypatch.setattr(KernelPool, 'peek', lambda self, key: self.kernels.get(key))
    monkeypatch.setattr(KernelPool, 'close_all', lambda self: asyncio.sleep(0))

def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

def serve(**kw):
    "Start `serve_ide` on a thread and wait for it, reporting a startup crash as one."
    port, failed = free_port(), []

    def go():
        try: serve_ide(port=port, host='127.0.0.1', transport='direct', shell='none',
                       open_ws=False, agent='off', **kw)
        except BaseException as e: failed.append(e)

    threading.Thread(target=go, daemon=True).start()
    # Polled in short slices rather than one long wait: a server that raised on startup is
    # never going to answer, and reporting the exception now beats reporting a timeout later.
    for _ in range(90):
        if failed: raise AssertionError(f'serve_ide raised on startup: {failed[0]!r}')
        if wait_for_http(f'http://127.0.0.1:{port}/', timeout=.5): return port
    raise AssertionError('the server never answered')

def get(url, host=None):
    req = urllib.request.Request(url, headers={'Host': host} if host else {})
    try: return urllib.request.urlopen(req, timeout=20)
    except urllib.error.HTTPError as e: return e


def test_app_windows_serve_one_isolated_workspace_per_folder(tmp_path):
    """The `--app` shape, which is what the desktop entry launches."""
    for name in ('alpha', 'beta'): (tmp_path/name).mkdir()
    port = serve(roots=[str(tmp_path/'alpha'), str(tmp_path/'beta')], app_window=True,
                 gateway_port=0)
    # Host-based dispatch: the workspace is chosen by the name in the Host header, which is
    # how every absolute route in the client stays valid across workspaces.
    for slug in ('alpha', 'beta'):
        r = get(f'http://127.0.0.1:{port}/', host=f'{slug}.localhost:{port}')
        assert r.status == 200
        assert slug in r.read().decode()
    assert get(f'http://127.0.0.1:{port}/', host=f'nope.localhost:{port}').status == 421


def test_a_plain_workspace_has_a_kernel_ceiling(tmp_path):
    """`RuntimeBroker` was built only inside the `--app` branch, so a plain `leela` registered no broker: `admit` never ran, `LEELA_MAX_KERNELS` never applied, and kernels accumulated without a ceiling until the machine noticed."""
    (tmp_path/'one').mkdir()
    port = serve(roots=[str(tmp_path/'one')])
    out = json.loads(get(f'http://127.0.0.1:{port}/runtime/broker').read())
    assert out['limit'] is not None, 'no broker registered, so nothing caps the kernels'
    assert out['limit'] >= 1

def test_a_post_after_a_pause_reuses_the_connection(tmp_path):
    """uvicorn's 5s keep-alive closed connections WebKit still held, and a Markdown render sent on one failed with "Load failed"."""
    import http.client, time
    port = serve(roots=[tmp_path])
    c = http.client.HTTPConnection('127.0.0.1', port, timeout=30)
    def render():
        c.request('POST', '/markdown/render', json.dumps({'text': 'x'}), {'Content-Type': 'application/json'})
        r = c.getresponse(); r.read()
        return r.status
    assert render() == 200
    time.sleep(6)
    assert render() == 200, 'the idle connection was still open'

def test_an_app_launch_with_no_folder_does_not_open_its_working_folder(tmp_path, monkeypatch):
    "The launcher starts the server in `~/Library/Application Support/Leela`; host mode took that cwd as the folder to open."
    from leela.core import host
    (cwd := tmp_path/'support').mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(host, '_host', dict(url='http://127.0.0.1:9', token='t'))
    port = serve(app_window=True, gateway_port=0)
    assert get(f'http://127.0.0.1:{port}/', host=f'leela.localhost:{port}').status == 200
    assert get(f'http://127.0.0.1:{port}/', host=f'support.localhost:{port}').status == 421

def test_a_dropped_image_and_then_a_docx_open_as_tabs_of_the_loose_window(tmp_path):
    "What the launcher's drop sends: a file in a folder no window has goes to the loose window, whose page serves it as an image tab."
    import urllib.parse, zipfile
    (d := tmp_path/'drop').mkdir()
    (png := d/'Screenshot-1104-152024.png').write_bytes(bytes.fromhex('89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de0000000c4944415478da63f8ffff3f0005fe02fea7d6a4a10000000049454e44ae426082'))
    with zipfile.ZipFile(docx := d/'notes.docx', 'w', zipfile.ZIP_DEFLATED) as z: z.writestr('word/media/x.bin', bytes(range(256)) * 64)
    port = serve(app_window=True, gateway_port=0)
    def hub_open(f):
        q = urllib.parse.urlencode(dict(path=str(d), file=str(f)))
        req = urllib.request.Request(f'http://127.0.0.1:{port}/hub/open?{q}', data=b'', method='POST')
        try: return json.loads(urllib.request.urlopen(req, timeout=60).read())
        except urllib.error.HTTPError as e: return json.loads(e.read())
    r = hub_open(png)
    assert r['ok'] and r['id'] == 'loose' and r['offer'] == str(d.resolve()), r
    site = r['url'].rstrip('/')
    assert urllib.parse.urlsplit(site).port != port, 'the loose window has a port of its own'
    assert get(site + '/').status == 200
    tab = json.loads(get(site + '/tab/state').read())
    assert tab['kind'] == 'image' and tab['path'] == str(png.resolve())
    r = hub_open(docx)
    assert r['ok'] and r['id'] == 'loose' and r['url'] == site + '/', 'the second drop goes to the same window, whose page shows the new tab'
    assert json.loads(get(site + '/tab/state').read())['path'] == str(docx.resolve())

def test_a_quit_does_not_wait_for_the_pages_streams(monkeypatch):
    "Every window holds an endless `/fs/events` stream; uvicorn waited for them, so the launcher's SIGTERM never ended the server and it was killed after 15 s."
    import uvicorn
    from leela import app as A
    seen = {}
    monkeypatch.setattr(uvicorn, 'run', lambda app, **kw: seen.update(kw))
    serve_ide(port=free_port(), host='127.0.0.1', transport='direct', shell='none', open_ws=False, agent='off')
    assert seen['timeout_graceful_shutdown'] == A.QUIT_GRACE and A.QUIT_GRACE <= 2

def test_each_workspace_has_its_own_port_and_no_page_reaches_another(tmp_path):
    "The Mac app could not reach `<slug>.localhost`, so each workspace answers on a loopback port of its own."
    import urllib.parse
    for name in ('alpha', 'beta'): (tmp_path/name).mkdir()
    port = serve(roots=[str(tmp_path/'alpha'), str(tmp_path/'beta')], app_window=True, gateway_port=0)
    sites = {s['id']: s['url'] for s in json.loads(get(f'http://127.0.0.1:{port}/app/sites').read())['sites']}
    ports = {k: urllib.parse.urlsplit(u).port for k, u in sites.items()}
    assert set(sites) == {'alpha', 'beta'} and ports['alpha'] == port and ports['beta'] != port, sites
    for slug, url in sites.items():
        r = get(url)
        assert r.status == 200 and slug in r.read().decode() and not r.headers.get_all('set-cookie'), 'no cookie: two ports on one host share them'
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **kw): return None
    try: urllib.request.build_opener(NoRedirect).open(f'http://127.0.0.1:{port}/hub/go/beta', timeout=10); assert False, 'no redirect'
    except urllib.error.HTTPError as e: assert e.code == 307 and e.headers['location'] == sites['beta']
    assert get(f'http://127.0.0.1:{port}/hub/go/nope').status == 404
    assert 'beta' in get(f'http://127.0.0.1:{port}/', host=f'beta.localhost:{port}').read().decode(), 'a saved *.localhost link still works'
    req = urllib.request.Request(sites['beta'] + 'tab/close', data=b'{}', method='POST', headers={'Origin': sites['alpha'].rstrip('/'), 'Content-Type': 'application/json'})
    try: urllib.request.urlopen(req, timeout=10); assert False, 'a page on alpha changed beta'
    except urllib.error.HTTPError as e: assert e.code == 403

def test_the_agents_browser_counts_every_workspace_port_as_leelas_own(monkeypatch, tmp_path):
    from leela.core import projects
    from leela.blocks.browser import browser
    monkeypatch.setattr(projects, 'SERVING', tmp_path/'serving.json')
    projects.now_serving('127.0.0.1', 5001, ports=[5002])
    assert browser.own_origins() == {'http://127.0.0.1:5001', 'http://127.0.0.1:5002'}
    assert projects.now_serving('127.0.0.1', 5001)['ports'] == [5002], 'a later write keeps the ports'

def test_a_file_named_with_a_narrow_space_is_served_on_its_workspaces_port(tmp_path):
    "macOS names a screen recording `… 8.11.22 am.mov`; the thin app serves each workspace on a port of its own, and the same /file/raw answers there."
    import unicodedata, urllib.parse
    for name in ('home', 'proj'): (tmp_path/name).mkdir()
    name = 'Screen Recording 2026-11-05 at 8.11.22 am.mov'
    (f := tmp_path/'proj'/name).write_bytes(b'\0' * 4096)
    port = serve(roots=[str(tmp_path/'home'), str(tmp_path/'proj')], app_window=True, gateway_port=0)
    url = next(s['url'] for s in json.loads(get(f'http://127.0.0.1:{port}/app/sites').read())['sites'] if s['id'] == 'proj')
    assert f':{port}/' not in url
    for path in (str(f), unicodedata.normalize('NFD', str(f))):
        req = urllib.request.Request(f"{url}file/raw/{urllib.parse.quote(name)}?path={urllib.parse.quote(path)}", headers={'Range': 'bytes=0-99'})
        with urllib.request.urlopen(req, timeout=20) as r:
            assert r.status == 206 and len(r.read()) == 100 and "filename*=utf-8''" in r.headers.get('content-disposition', '').lower(), r.headers
