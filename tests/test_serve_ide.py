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

def test_a_plain_workspace_serves_the_folders_it_was_given(tmp_path):
    (tmp_path/'one').mkdir()
    port = serve(roots=[str(tmp_path/'one')])
    body = get(f'http://127.0.0.1:{port}/').read().decode()
    assert 'lee-ide' in body and 'one' in body

def test_app_windows_serve_one_isolated_workspace_per_folder(tmp_path):
    """The `--app` shape, which is what the desktop entry launches.

    Each folder gets its own `Workspace` behind a host-dispatching hub, so this is also the
    branch that goes through `Workspace.load` with every argument `serve_ide` forwards.
    """
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

def test_the_cdp_port_reaches_the_workspaces_browser(tmp_path):
    "The inline browser reads its port off the `Workspace`, through both construction paths."
    (tmp_path/'one').mkdir()
    port = serve(roots=[str(tmp_path/'one')], app_window=True, cdp_port=9876, gateway_port=0)
    d = get(f'http://127.0.0.1:{port}/browser/ready', host=f'one.localhost:{port}')
    assert json.load(d)['port'] == 9876

def test_a_desktop_launch_with_no_folder_does_not_open_your_home_directory(monkeypatch):
    "`leela` from a shell means here; a double-clicked app has no here, and used to guess."
    monkeypatch.setattr('sys.frozen', True, raising=False)
    port = serve(roots=[])
    body = get(f'http://127.0.0.1:{port}/').read().decode()
    assert 'Open a folder' in body
    assert json.load(get(f'http://127.0.0.1:{port}/workspace/info'))['roots'] == []

def test_a_plain_workspace_has_a_kernel_ceiling(tmp_path):
    """`RuntimeBroker` was built only inside the `--app` branch, so a plain `leela` registered no
    broker: `admit` never ran, `LEELA_MAX_KERNELS` never applied, and kernels accumulated without
    a ceiling until the machine noticed."""
    (tmp_path/'one').mkdir()
    port = serve(roots=[str(tmp_path/'one')])
    out = json.loads(get(f'http://127.0.0.1:{port}/runtime/broker').read())
    assert out['limit'] is not None, 'no broker registered, so nothing caps the kernels'
    assert out['limit'] >= 1
