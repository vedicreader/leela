"`serve_ide` actually starting, for both shapes of workspace: a real port, a real uvicorn."

from __future__ import annotations

import json, socket, threading, urllib.error, urllib.request

import pytest

from leela.app import serve_ide
from leela.desktop import wait_for_http

pytestmark = pytest.mark.usefixtures('_fake_kernels')

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
    host = urllib.parse.urlsplit(r['url']).netloc
    assert get(f'http://127.0.0.1:{port}/', host=host).status == 200
    tab = json.loads(get(f'http://127.0.0.1:{port}/tab/state', host=host).read())
    assert tab['kind'] == 'image' and tab['path'] == str(png.resolve())
    r = hub_open(docx)
    assert r['ok'] and r['id'] == 'loose' and r['url'] == f'http://{host}/', 'the second drop goes to the same window, whose page shows the new tab'
    assert json.loads(get(f'http://127.0.0.1:{port}/tab/state', host=host).read())['path'] == str(docx.resolve())
