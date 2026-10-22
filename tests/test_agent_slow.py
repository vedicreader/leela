"The agent under a real model: sub-agent fan-out and local context limits."

from __future__ import annotations
import pytest

pytestmark = pytest.mark.slow

pytestmark = pytest.mark.slow

import asyncio
import time


from leela.blocks.runtime.kernels import Kernel, ipymini_available

KINDS = ['ipykernel'] + (['ipymini'] if ipymini_available() else [])


SPINNING = (
    'import time, pandas as pd\n'
    'df = pd.DataFrame({"a": range(200), "b": range(200)})\n'
    'ip = get_ipython()\n'
    'if hasattr(ip.kernel, "unlock"): ip.kernel.unlock()\n'
    'end = time.time() + 3.0\n'
    'while time.time() < end: pass\n'
)

def _run(coro): return asyncio.new_event_loop().run_until_complete(coro)

async def _kernel(tmp_path, kind, port=8600):
    k = Kernel(name='t', cwd=str(tmp_path), agent='restricted', port=port, kernel=kind)
    await k.start()
    return k

async def _inspect(k, code, scope='isolated', timeout=20):
    "One `/agent/api/exec` in the isolated scope: exactly what `Host.inspect_python` does."
    import httpx2 as httpx
    async with httpx.AsyncClient(base_url=k.base, timeout=timeout) as c:
        t0 = time.monotonic()
        r = await c.get('/agent/api/exec', params={'code': code, 'scope': scope})
        return time.monotonic() - t0, r.json()

async def _warm(k):
    "First call builds the agent session and imports the sandbox; that cost is not the measurement."
    await _inspect(k, '1')


@pytest.mark.parametrize('kind', KINDS)
def test_even_a_spinning_cell_does_not_block_an_inspection(tmp_path, kind):
    "The surprising one, and the reason these tests were written after measuring."
    async def go():
        k = await _kernel(tmp_path, kind, port=8620)
        try:
            await _warm(k)
            busy = asyncio.create_task(k.execute(SPINNING, timeout=30))
            await asyncio.sleep(1.0)
            dt, out = await _inspect(k, 'df.shape', timeout=15)
            assert out.get('ok'), out
            assert '(200, 2)' in str(out.get('result') or out.get('stdout')), out
            assert dt < 2.0, f'{kind}: a warm inspection took {dt:.2f}s against a spinning cell'
            assert not busy.done(), 'the cell finished first, so this proved nothing'
            await busy
        finally:
            await k.shutdown()
    _run(go())


@pytest.mark.parametrize('kind', KINDS[:1])
def test_a_binding_reaches_the_user_only_when_it_is_handed_over(tmp_path, kind):
    """The whole round trip with no model in it: bind, be seen, hand over, be read by the user."""
    from leela.blocks.agent.ai import WorkspaceHost
    async def go():
        ws = Workspace(roots=[str(tmp_path)], port=8760, approvals='auto')
        k = await ws.kernel()
        try:
            await k.execute('import pandas as pd\ndf = pd.DataFrame({"a": [1, 2], "b": [3, 4]})\n', timeout=30)
            h = WorkspaceHost(ws)
            h.run_python('df_norm = (df - df.mean()) / df.std()')
            assert 'df_norm' in h.list_vars(), 'the agent cannot see its own binding'
            assert 'df_norm' not in h.owner_names(), 'and the user cannot see it yet'
            h.promote_var('df_norm')
            after = await k.execute('print(df_norm.shape)', timeout=30)
            assert '(2, 2)' in after.text, after.text
            assert 'will not be replaced' in h.promote_var('df'), 'the user owns df'
            # promotion hands the name over rather than sharing it: the owner policy covers it again
            assert 'blocked' in h.run_python('df_norm["a"] = 0')
            still = await k.execute('print(df_norm["a"].tolist())', timeout=30)
            assert '0.0, 0.0' not in still.text, still.text
        finally:
            await ws.pool.close_all()
    _run(go())


pytestmark = pytest.mark.slow

import os
from pathlib import Path


from leela.agent.core import LOCAL
from leela.blocks.nb.nb import Notebook
from leela.workspace import Workspace

MODEL_NAME = 'gemma-e4b'
MODEL_ID = LOCAL[MODEL_NAME]
REPO = Path(__file__).resolve().parents[1]
DIALOG = REPO/'tests'/'fixtures'/'dialog.ipynb'
PROMPT_CELL = 2

def _model_available():
    from rishi.litert import cached_model
    return bool(cached_model(MODEL_ID))

#: What one LiteRT engine for this model costs, measured rather than guessed: resident size climbs
#: from 123MB to 12.2GB as the fixture builds it, and a run that reached 13.4GB was OOM-killed with
#: 3.1GB still nominally free. So 16GB available is the point below which this does not finish.
#:
#: The gate used to ask only whether the bundle was cached. On a machine with the bundle and not the
#: memory, the whole file was killed part way through and reported nothing at all: not the model
#: tests it could never run, and not the nineteen kernel tests above them that pass in seconds.
MODEL_RAM_MB = 16000

def _ram_mb():
    "Memory the kernel says is available, or None where it does not say."
    try:
        for line in open('/proc/meminfo'):
            if line.startswith('MemAvailable:'): return int(line.split()[1]) // 1024
    except OSError: pass
    return None

@pytest.fixture(scope='module')
def dialog_agent(tmp_path_factory):
    if not _model_available() and os.environ.get('LEELA_RUN_RISHI_INTEGRATION') != '1':
        pytest.skip(f'{MODEL_NAME} LiteRT bundle is not cached; set LEELA_RUN_RISHI_INTEGRATION=1 to download it')
    if (free := _ram_mb()) is not None and free < MODEL_RAM_MB \
            and os.environ.get('LEELA_RUN_RISHI_INTEGRATION') != '1':
        pytest.skip(f'{free}MB available, {MODEL_NAME} needs about {MODEL_RAM_MB}MB; '
                    'set LEELA_RUN_RISHI_INTEGRATION=1 to try anyway')
    # Copied out: a real kernel logs its transcript into the folder the workspace is rooted at,
    # which was `tests/fixtures`, so running this suite wrote session notebooks into the checkout.
    import shutil
    root = tmp_path_factory.mktemp('dialog')
    dialog = root/DIALOG.name
    shutil.copy2(DIALOG, dialog)
    ws = Workspace(roots=[str(root)], inline_model=MODEL_NAME, approvals='auto')
    ws.open(dialog)
    nb = Notebook.load(dialog)
    async def prepare():
        kernel = await ws.kernel()
        result = await nb.run(1, kernel)
        assert not result.has_error
    asyncio.run(prepare())
    try: yield ws, nb
    finally:
        ws.ai.close()
        ws.inline_ai.close()
        asyncio.run(ws.pool.close_all())


def test_real_dialog_prompt_cell_completes_end_to_end(dialog_agent):
    ws, nb = dialog_agent
    chunks = list(ws.ask_cell_stream(nb, PROMPT_CELL))
    assert chunks
    assert nb[PROMPT_CELL].reply.strip()
    assert not ws.inline_ai.problems
    rows = ws.kernel_peek().api_sync('/api/rows', {'profile': 'minimal', 'sort': 'name'})
    names = {v.get('name') for g in (rows or {}).get('groups', []) for v in g.get('nodes', [])}
    assert 'df_norm' in names, 'the imperative prompt must execute and bind its requested result'
