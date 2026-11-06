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
