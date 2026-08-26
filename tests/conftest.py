"Deterministic workspace and kernel fixtures for the IDE tests."

import os as _os
import pathlib as _pathlib
import tempfile as _tempfile

TEST_CONFIG_HOME = _os.environ.get('LEELA_TEST_CONFIG_HOME')
if not TEST_CONFIG_HOME:
    TEST_CONFIG_HOME = _tempfile.mkdtemp(prefix='leela-test-cfg-')
    _os.environ['LEELA_TEST_CONFIG_HOME'] = TEST_CONFIG_HOME
_os.environ['XDG_CONFIG_HOME'] = TEST_CONFIG_HOME

#: Where a person's real conversations, keymap and settings live. No test may resolve to it. The
#: env var above is not enough on its own: `leela_cfg` is bound at import, so a module that was
#: imported before this file ran would still hold the real path, and one truncating write to
#: `ai.history_path` is then a person's whole conversation log.
REAL_CONFIG_HOME = _pathlib.Path.home()/'.config'/'leela'

import asyncio
import socket as _socket
import sys as _sys
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
def cfg_home(monkeypatch, tmp_path_factory):
    """A config dir per test, and never the real one.

    One dir for the whole session was not isolation: a test that wrote `agent-history.jsonl`
    truncated the log every other test read, which is why one of them could pass alone and fail
    in the suite. And `leela_cfg` is a module-level name in every module that imported it, so the
    environment variable alone does not move it -- each binding is repointed here.

    Beside `tmp_path`, never inside it: a test whose project root is `tmp_path` walks it, and a
    config dir in there is a file that project does not have.
    """
    cfg = tmp_path_factory.mktemp('cfg')/'leela'
    cfg.mkdir(parents=True, exist_ok=True)
    # `XDG_CONFIG_HOME` stays where the top of this file put it: it is already a temp dir, and
    # libraries Leela composes read it once at import, so moving it mid-session only makes Leela
    # and dhrishti disagree about a path neither of them is at risk of writing to.
    monkeypatch.setenv('LEELA_KEYMAP', str(cfg/'keys.json'))
    for name, module in list(_sys.modules.items()):
        if name.split('.')[0] != 'leela': continue
        if getattr(module, 'leela_cfg', None) is None: continue
        monkeypatch.setattr(module, 'leela_cfg', _pathlib.Path(cfg), raising=False)
    import leela
    assert REAL_CONFIG_HOME not in _pathlib.Path(leela.leela_cfg).parents
    assert _pathlib.Path(leela.leela_cfg) != REAL_CONFIG_HOME
    return cfg

@pytest.fixture(autouse=True)
def _no_backup_threads(monkeypatch):
    """No test schedules real backups.

    `ide_app` starts a daemon that takes a copy whenever one is due, and nothing stops it. Across a
    suite that builds the app hundreds of times, those threads outlive the tests that made them and
    fire into whichever config dir the current test is using, which is how a listing asserted to be
    empty came back holding somebody else's copy.
    """
    from leela.core import backups
    monkeypatch.setattr(backups, 'schedule_backups', lambda *a, **k: (lambda: None))

@pytest.fixture(autouse=True)
def _sessions_off_the_repo(tmp_path_factory):
    """No test writes an agent transcript into the checked-out repository.

    `dhrishti`'s logging directories are process-global and default to relative paths, so a session
    logs into whatever the working directory happens to be, and `test_leela_can_redirect_both_
    transcript_streams` restores those relative defaults in its `finally`.

    This covers the pytest process only. A kernel is another process and logs into the folder its
    workspace is rooted at, which is correct and is why a test roots one at a temp copy rather than
    at `tests/fixtures`.
    """
    from dhrishti.runtime import set_logging
    root = tmp_path_factory.mktemp('sessions')
    set_logging(dir=root/'_leela_sessions', agent_dir=root/'_leela_agent_sessions')
    yield
    set_logging(dir=root/'_leela_sessions', agent_dir=root/'_leela_agent_sessions')

@pytest.fixture(autouse=True)
def _no_warm_probes(monkeypatch):
    """No test asks the machine what it holds behind its own back.

    `ide_app` warms the model probes on a startup thread, and a suite that builds the app hundreds
    of times leaves those threads running long after the test that made them. One gathers a catalog
    under one test's environment and writes it in under the next test's, so a picker patched to
    offer `gpt-4.1` was served a catalog with no OpenAI in it at all, at whatever interval the
    thread happened to finish on.
    """
    from leela import app
    monkeypatch.setattr(app, '_warm_probes', lambda: None)

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


@pytest.fixture(autouse=True)
def _cold_probes():
    """No test inherits another's answer about what is installed or who is signed in.

    `probed` caches machine state for the life of the process, which is what a picker on the boot
    path needs and what a suite must not carry between tests: one that patches `available_models`
    was otherwise served the catalog a previous test had already cached.
    """
    from leela.blocks.agent.models import forget_probes
    forget_probes()
    yield
    forget_probes()
