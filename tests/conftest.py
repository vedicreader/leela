"""Deterministic workspace and kernel fixtures for the IDE tests."""

import asyncio
import pytest

from leela.kernels import ExecOutcome, KernelPool
from leela.workspace import Workspace

FIXTURES = 'fixtures'          # relative to this file; kept short so it renders the same everywhere


def fixture_dir(request):
    "The fixture project, as an absolute path. Tests open folders, not files."
    return str((request.path.parent / FIXTURES).resolve())


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
    """Enough of `leela.kernels.Kernel` for browser tests, with stable answers."""
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
