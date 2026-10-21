"Deterministic workspace and kernel fixtures for the IDE tests."

import os as _os
import pathlib as _pathlib
import shutil as _shutil
import tempfile as _tempfile

TEST_CONFIG_HOME = _os.environ.get('LEELA_TEST_CONFIG_HOME')
_MADE_HERE = not TEST_CONFIG_HOME
if _MADE_HERE:
    TEST_CONFIG_HOME = _tempfile.mkdtemp(prefix='leela-test-cfg-')
    _os.environ['LEELA_TEST_CONFIG_HOME'] = TEST_CONFIG_HOME
_os.environ['XDG_CONFIG_HOME'] = TEST_CONFIG_HOME
#: No orphan sweep thread unless a test asks for one with `Jobs.sweep(seconds)`.
_os.environ['LEELA_JOB_SWEEP'] = '0'

#: Where a person's real conversations, keymap and settings live. No test may resolve to it. The
#: env var above is not enough on its own: `leela_cfg` is bound at import, so a module that was
#: imported before this file ran would still hold the real path, and one truncating write to
#: `ai.history_path` is then a person's whole conversation log.
REAL_CONFIG_HOME = _pathlib.Path.home()/'.config'/'leela'

def pytest_sessionfinish(session):
    if _MADE_HERE: _shutil.rmtree(TEST_CONFIG_HOME, ignore_errors=True)

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

def history_file(ws):
    """The conversation log, checked before a test replaces it."""
    p = _pathlib.Path(ws.ai.history_path)
    assert REAL_CONFIG_HOME not in p.parents and _pathlib.Path.home() not in p.parents, \
        f'refusing to write a test conversation log to {p}'
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def needs_runtime(name):
    "Skip where `name` is a runtime this machine lacks. `sonnet` resolves through `claude` (Claude Code), which CI does not have."
    from leela.agent.core import runtime_available
    return pytest.mark.skipif(not runtime_available(name), reason=f'the {name} runtime is not installed here')

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
def _curated_models_only(monkeypatch):
    "ramabana 0.1.42 lists models live from a provider once a key is set; a test that sets one must not wait on the network."
    import ramabana.models as rm
    monkeypatch.setattr(rm, 'LIVE', {})     # a test that wants a listing sets its own

@pytest.fixture(autouse=True)
def cfg_home(monkeypatch, tmp_path_factory):
    """A config dir per test, and never the real one."""
    cfg = tmp_path_factory.mktemp('cfg')/'leela'
    cfg.mkdir(parents=True, exist_ok=True)
    # `XDG_CONFIG_HOME` stays where the top of this file put it: it is already a temp dir, and
    # libraries Leela composes read it once at import, so moving it mid-session only makes Leela
    # and dhrishti disagree about a path neither of them is at risk of writing to.
    monkeypatch.setenv('LEELA_KEYMAP', str(cfg/'keys.json'))
    monkeypatch.setenv('RAMABANA_CONFIG', str(cfg.parent/'ramabana-config.toml'))   # ramabana's one file per machine
    for name, module in list(_sys.modules.items()):
        if name.split('.')[0] != 'leela': continue
        if getattr(module, 'leela_cfg', None) is None: continue
        monkeypatch.setattr(module, 'leela_cfg', _pathlib.Path(cfg), raising=False)
    from leela.core import projects
    for name, f in (('SESSION', 'desktop.json'), ('DEFAULT_SESSION', 'desktop.json'), ('SERVING', 'serving.json')):
        monkeypatch.setattr(projects, name, cfg/f)
    import leela
    assert REAL_CONFIG_HOME not in _pathlib.Path(leela.leela_cfg).parents
    assert _pathlib.Path(leela.leela_cfg) != REAL_CONFIG_HOME
    return cfg

@pytest.fixture(autouse=True)
def _no_backup_threads(monkeypatch):
    """No test schedules real backups."""
    from leela.core import backups
    monkeypatch.setattr(backups, 'schedule_backups', lambda *a, **k: (lambda: None))

@pytest.fixture(autouse=True)
def _sessions_off_the_repo(tmp_path_factory):
    """No test writes an agent transcript into the checked-out repository."""
    from dhrishti.runtime import set_logging
    root = tmp_path_factory.mktemp('sessions')
    set_logging(dir=root/'_leela_sessions', agent_dir=root/'_leela_agent_sessions')
    yield
    set_logging(dir=root/'_leela_sessions', agent_dir=root/'_leela_agent_sessions')

@pytest.fixture(autouse=True)
def _no_lsp_reaper(monkeypatch):
    """No test leaves a language-server reaper thread behind; the reaper's own test starts one."""
    from leela.workspace import Workspace
    monkeypatch.setattr(Workspace, '_start_reaper', lambda self: None)

@pytest.fixture(autouse=True)
def _no_warm_probes(monkeypatch):
    """No test asks the machine what it holds behind its own back."""
    from leela import app
    monkeypatch.setattr(app, '_warm_probes', lambda: None)

@pytest.fixture(autouse=True)
def _isolate_vault(monkeypatch, tmp_path_factory):
    "Keep vault I/O out of ~/.vishalakshi and skip real encoders in the suite."
    #: Keyed by worker as well as by name. `mktemp` numbers from zero inside each xdist worker, so
    #: the basename alone gave all four of them `vaults/v0` and one `vault.db`; a shelf is named
    #: for the workspace root, and two workers ingesting into `proj` counted each other's documents.
    worker = _os.environ.get('PYTEST_XDIST_WORKER', 'master')
    vault = _pathlib.Path(TEST_CONFIG_HOME)/'vaults'/worker/tmp_path_factory.mktemp('v').name
    vault.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(vault/'vault.db'))
    # The search telemetry vault is a second file, and a route that records one search session
    # would otherwise write into the person's own `~/.vishalakshi`.
    monkeypatch.setenv('LEELA_SEARCH_VAULT', str(vault/'search.db'))
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
def _no_local_engine_loads(request, monkeypatch):
    "Fake the local engine so a fast test switching model checks routing, not multi-GB weights; slow tests load the real one."
    if request.node.get_closest_marker('slow'): return
    try: from rishi.litert import LitertChat
    except Exception: return
    class _FakeEngine:
        def close(self): pass
        def create_conversation(self, *a, **kw):
            raise RuntimeError('a faked local engine cannot run a turn; mark the test slow to load the real one')
    monkeypatch.setattr(LitertChat, 'create_engine', classmethod(lambda cls, *a, **kw: _FakeEngine()))

@pytest.fixture(autouse=True)
def _cold_probes():
    """No test inherits another's answer about what is installed or who is signed in."""
    from leela.blocks.agent.models import forget_probes
    forget_probes()
    yield
    forget_probes()


@pytest.fixture(autouse=True)
def _asks_time_out_quickly(monkeypatch):
    "An approval nobody answers waits two seconds under pytest, not ramabana's default; a test naming its own timeout keeps it."
    from ramabana.agent import Approvals
    orig = Approvals.__init__
    def init(self, *a, **kw):
        kw.setdefault('timeout', 2)
        return orig(self, *a, **kw)
    monkeypatch.setattr(Approvals, '__init__', init)

@pytest.fixture(autouse=True)
def _claude_on_path(request, monkeypatch):
    "Resolve the default turn model as if Claude Code were installed, so a fast test runs the same with or without it; a launch still needs the real binary."
    if request.node.get_closest_marker('slow') or request.node.get_closest_marker('no_claude'): return
    import ramabana.core as rc
    monkeypatch.setattr(rc, '_claude_available', lambda: True)
