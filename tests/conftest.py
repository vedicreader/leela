"Deterministic workspace and kernel fixtures for the IDE tests."

import os as _os
import pathlib as _pathlib
import tempfile as _tempfile

TEST_CONFIG_HOME = _os.environ.get('LEELA_TEST_CONFIG_HOME')
if not TEST_CONFIG_HOME:
    TEST_CONFIG_HOME = _tempfile.mkdtemp(prefix='leela-test-cfg-')
    _os.environ['LEELA_TEST_CONFIG_HOME'] = TEST_CONFIG_HOME
_os.environ['XDG_CONFIG_HOME'] = TEST_CONFIG_HOME

import asyncio
import socket as _socket
import threading
import time as _time
from contextlib import contextmanager

import pytest

from leela.app import ide_app
from leela.blocks.runtime.kernels import ExecOutcome, KernelPool
from leela.workspace import Workspace

FIXTURES = 'fixtures'

def fixture_dir(request):
    "The fixture project, as an absolute path. Tests open folders, not files."
    return str((request.path.parent / FIXTURES).resolve())

CREDENTIAL_KEYS = ('HCLOUD_TOKEN CLOUDFLARE_API_TOKEN CF_API_TOKEN CF_TUNNEL_TOKEN GITHUB_TOKEN GH_TOKEN '
    'OPENAI_API_KEY ANTHROPIC_API_KEY GEMINI_API_KEY GOOGLE_API_KEY CURSOR_API_KEY CODEX_AUTH_TOKEN '
    'AWS_ACCESS_KEY AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN').split()

@pytest.fixture(autouse=True)
def _isolate_credentials(monkeypatch):
    "Run as if none of the machine's real credentials were exported; a test that needs one sets it."
    for key in CREDENTIAL_KEYS: monkeypatch.delenv(key, raising=False)

@pytest.fixture(autouse=True)
def _isolate_vault(monkeypatch, tmp_path_factory):
    "Keep vault I/O out of ~/.vishalakshi and skip real encoders in the suite."
    vault = _pathlib.Path(TEST_CONFIG_HOME)/'vaults'/tmp_path_factory.mktemp('v').name
    vault.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(vault/'vault.db'))
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')

ROWS = {
    'groups': [{
        'label': '',
        'nodes': [
            {'name': 'df', 'type': 'DataFrame', 'value': 'DataFrame [5×2]', 'shape': '(5, 2)',
             'is_container': True, 'is_grid': True, 'accessor': ['df']},
            {'name': 'df_norm', 'type': 'DataFrame', 'value': 'DataFrame [5×2]', 'shape': '(5, 2)',
             'is_container': True, 'is_grid': True, 'accessor': ['df_norm']},
            {'name': 'total', 'type': 'int', 'value': '42', 'shape': None,
             'is_container': False, 'is_grid': False, 'accessor': ['total']},
        ],
    }],
}

DOCSTRING = ('Type:        DataFrame\n'
             'String form: <the frame>\n'
             'Docstring:   Two-dimensional, size-mutable, potentially heterogeneous tabular data.')

class FakeKernel:
    "Enough of `leela.blocks.runtime.kernels.Kernel` for browser tests, with stable answers."
    alive = True
    base = 'http://127.0.0.1:8000'
    pid = 4242
    boot_error = None
    token = None
    kernel_kind = 'ipykernel'
    async def api(self, path, params=None, timeout=15):
        if path.endswith('/api/rows'): return ROWS
        if path.endswith('/api/expand'): return []
        if path.endswith('/api/transcript'): return {'cells': []}
        return None
    async def execute(self, code, **kw):
        "Runs nothing. Known names echo, anything else is the NameError the tests want to see."
        code = (code or '').strip()
        known = {n['name'] for g in ROWS['groups'] for n in g['nodes']}
        if code in known: return ExecOutcome(ok=True, execution_count=1, outputs=[
            {'output_type': 'execute_result', 'execution_count': 1, 'metadata': {},
             'data': {'text/plain': f'<{code}>'}}])
        return ExecOutcome(ok=False, execution_count=1, error=f"NameError: name '{code}' is not defined")
    async def complete(self, code, pos):
        head = (code or '')[:pos]
        word = head.split()[-1] if head.split() else ''
        ms = sorted(n['name'] for g in ROWS['groups'] for n in g['nodes'] if n['name'].startswith(word))
        return {'from': pos - len(word), 'matches': ms}
    async def inspect_obj(self, code, pos, detail=0):
        return DOCSTRING if 'df' in (code or '') else ''
    async def names(self, scope='live', profile='full'):
        return [n['name'] for g in ROWS['groups'] for n in g['nodes']]
    async def interrupt(self): pass
    async def restart(self): pass
    async def shutdown(self): pass

@pytest.fixture
def ws(request, monkeypatch):
    "A workspace over the fixture project, whose kernels are all `FakeKernel`."
    async def _get(self, key, **kw): return self.kernels.setdefault(key, FakeKernel())
    monkeypatch.setattr(KernelPool, 'get', _get)
    monkeypatch.setattr(KernelPool, 'peek', lambda self, key: self.kernels.get(key))
    monkeypatch.setattr(KernelPool, 'close_all', lambda self: asyncio.sleep(0))
    return Workspace(roots=[fixture_dir(request)], port=8000)

@contextmanager
def serve(ws):
    "The real app on a background thread, so Playwright can drive it like any other site."
    import uvicorn
    with _socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(ide_app(ws), host='127.0.0.1', port=port, log_level='error'))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started: break
        _time.sleep(.02)
    try: yield f'http://127.0.0.1:{port}'
    finally:
        server.should_exit = True
        thread.join(timeout=3)
