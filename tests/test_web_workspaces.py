import asyncio
from pathlib import Path
from unittest.mock import Mock

import pytest

from leela.kernels import RuntimeBroker, KernelPool
from leela.web.cdp import cdp_ready, open_cdp_app
from leela.hub import LoopbackHostGuard, WorkspaceHub, WorkspaceSite, workspace_slug


def test_workspace_slugs_are_dns_safe_and_unique():
    first = workspace_slug('My Project')
    second = workspace_slug('My Project', [first])
    assert first == 'my-project' and second == 'my-project-2'


def test_workspace_hub_dispatches_by_localhost_subdomain():
    seen = []

    async def app_a(scope, receive, send): seen.append(('a', scope['leela.workspace_id']))
    async def app_b(scope, receive, send): seen.append(('b', scope['leela.workspace_id']))

    hub = WorkspaceHub([WorkspaceSite('alpha', 'Alpha', '/a', app_a),
                        WorkspaceSite('beta', 'Beta', '/b', app_b)], 5001)
    scope = {'type': 'http', 'headers': [(b'host', b'beta.localhost:5001')]}
    asyncio.run(hub(scope, Mock(), Mock()))
    assert seen == [('b', 'beta')]
    assert hub.catalog()[0]['url'] == 'http://alpha.localhost:5001/'


def test_workspace_hub_rejects_unknown_hosts_instead_of_opening_default_workspace():
    called, messages = [], []

    async def app(scope, receive, send): called.append(scope)
    async def send(message): messages.append(message)

    hub = WorkspaceHub([WorkspaceSite('alpha', 'Alpha', '/a', app)], 5001)
    scope = {'type': 'http', 'headers': [(b'host', b'attacker.example:5001')]}
    asyncio.run(hub(scope, Mock(), send))
    assert not called
    assert messages[0]['status'] == 421


def test_loopback_guard_rejects_dns_rebinding_and_cross_site_browser_requests():
    called = []
    async def app(scope, receive, send): called.append(scope)

    async def run(headers):
        messages = []
        async def send(message): messages.append(message)
        await LoopbackHostGuard(app)({'type': 'http', 'headers': headers}, Mock(), send)
        return messages

    rebound = asyncio.run(run([(b'host', b'attacker.example:5001')]))
    cross_site = asyncio.run(run([(b'host', b'localhost:5001'),
                                  (b'origin', b'https://attacker.example'),
                                  (b'sec-fetch-site', b'cross-site')]))
    assert rebound[0]['status'] == cross_site[0]['status'] == 421
    assert not called


def test_runtime_broker_refuses_a_thirteenth_heap_without_evicting_live_state(monkeypatch):
    broker = RuntimeBroker(max_kernels=1)
    pool = KernelPool(broker=broker)
    alive = Mock(alive=True, pid=42, kernel_kind='ipykernel', cwd='/project')
    pool.kernels['first'] = alive
    with pytest.raises(RuntimeError, match='kernel limit reached'):
        asyncio.run(broker.admit(pool, 'second'))
    assert pool.kernels['first'] is alive


def test_cdp_ready_reads_the_active_debug_endpoint(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'{"webSocketDebuggerUrl":"ws://127.0.0.1/devtools/browser/x"}'
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **k: Response())
    assert cdp_ready(9223)['webSocketDebuggerUrl'].startswith('ws://')


def test_open_cdp_app_reuses_fossicks_profile(monkeypatch, tmp_path):
    monkeypatch.setattr('leela.web.cdp.cdp_ready', lambda port: {'webSocketDebuggerUrl': 'ws://active'})
    monkeypatch.setattr('fossick.cdp.chrome_bin', lambda: '/chrome')
    launched = []
    monkeypatch.setattr('subprocess.Popen', lambda args, **kw: launched.append((args, kw)) or Mock())

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'[{"id":"target-1","url":"http://alpha.localhost:5001/"}]'
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **k: Response())
    result = open_cdp_app('http://alpha.localhost:5001/', user_data_dir=tmp_path)
    assert result['reused'] and result['target'] == 'target-1'
    assert '--app=http://alpha.localhost:5001/' in launched[0][0]
    assert f'--user-data-dir={tmp_path}' in launched[0][0]
