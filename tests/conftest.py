"""Deterministic workspace and kernel fixtures for the IDE tests."""

# -- config isolation, before leela is imported ------------------------------
# `leela_cfg` is computed at import (`leela/__init__.py`), and modules bind it at import
# too -- `settings.py` derives `USER_SETTINGS_FILE` there and never looks again. So the
# environment has to be set *here*, above the imports; monkeypatching `leela.leela_cfg`
# afterwards would leave every module that already captured it pointing at the real
# directory.
#
# Without this, anything that builds a `Workspace` writes into the developer's own
# `~/.config/leela`: `Workspace.__init__` builds memory with no path, so `memory_path(None)`
# resolves to the real `memory/web.db`, and `/agent/memory/save` appends a row that is never
# cleaned up. One run of the suite left fifteen copies of a test's note in a real user's
# memory panel, plus a journal per run, `workspace.json` and `agent-history.jsonl`.
#
# The dir is remembered in `LEELA_TEST_CONFIG_HOME` rather than recomputed, because pytest
# imports this file as `conftest` and a test importing `tests.conftest` gets a second module
# object -- so a bare `mkdtemp()` here runs twice and the two copies disagree about where the
# config went. Reading `XDG_CONFIG_HOME` back instead would be worse: a developer with it
# legitimately set would silently get their real directory, which is the bug being fixed.
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

FIXTURES = 'fixtures'          # relative to this file; kept short so it renders the same everywhere


def fixture_dir(request):
    "The fixture project, as an absolute path. Tests open folders, not files."
    return str((request.path.parent / FIXTURES).resolve())


#: Credentials a developer's shell really does export. Every test that asks "is this
#: configured?" means the store it was handed, not this machine -- and `Infra.token`,
#: `EnvStore.get` and `auth_status` all read `os.environ` as a legitimate source, so with
#: these set the suite tests the developer's account. One of them made a live Hetzner call.
CREDENTIAL_KEYS = ('HCLOUD_TOKEN CLOUDFLARE_API_TOKEN CF_API_TOKEN CF_TUNNEL_TOKEN GITHUB_TOKEN GH_TOKEN '
    'OPENAI_API_KEY ANTHROPIC_API_KEY GEMINI_API_KEY GOOGLE_API_KEY CURSOR_API_KEY CODEX_AUTH_TOKEN '
    'AWS_ACCESS_KEY AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN').split()


@pytest.fixture(autouse=True)
def _isolate_credentials(monkeypatch):
    "Run as if none of the machine's real credentials were exported; a test that needs one sets it."
    for key in CREDENTIAL_KEYS: monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _isolate_vault(monkeypatch, tmp_path_factory):
    """Keep vault I/O out of ~/.vishalakshi and skip real encoders in the suite.

    Under `TEST_CONFIG_HOME`, not a bare tmp dir: `test_config_isolation` asserts that everything
    derived from the config dir stays inside it, and the vault is now one of those things. A
    per-test subdirectory, so one test's shelves are never another's.
    """
    vault = _pathlib.Path(TEST_CONFIG_HOME)/'vaults'/tmp_path_factory.mktemp('v').name
    vault.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(vault/'vault.db'))
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')


# The namespace every test sees in the variable panel. Shaped exactly like the payload
# `/api/rows` returns, so the panel's own grouping and formatting are what is under test.
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
    """Enough of `leela.blocks.runtime.kernels.Kernel` for browser tests, with stable answers."""
    alive = True
    base = 'http://127.0.0.1:8000'
    pid = 4242
    boot_error = None
    token = None
    kernel_kind = 'ipykernel'      # what the kernel picker reports as running

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
