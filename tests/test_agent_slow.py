"The agent under a real model: sub-agent fan-out and local context limits."

from __future__ import annotations
import pytest

pytestmark = pytest.mark.slow

pytestmark = pytest.mark.slow

import asyncio
import time


from leela.blocks.runtime.kernels import Kernel, ipymini_available

KINDS = ['ipykernel'] + (['ipymini'] if ipymini_available() else [])

YIELDING = (
    'import asyncio, pandas as pd\n'
    'df = pd.DataFrame({"a": range(200), "b": range(200)})\n'
    'async def _hold():\n'
    '    ip = get_ipython()\n'
    '    if hasattr(ip.kernel, "unlock"): ip.kernel.unlock()\n'
    '    await asyncio.sleep(3.0)\n'
    'await _hold()\n'
)

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
def test_an_inspection_runs_beside_a_yielding_cell(tmp_path, kind):
    "The capability sub-agents needed, and leela already had the architecture for."
    async def go():
        k = await _kernel(tmp_path, kind)
        try:
            assert k.base, f'inspector did not start: {k.boot_error}'
            await _warm(k)
            busy = asyncio.create_task(k.execute(YIELDING, timeout=30))
            await asyncio.sleep(1.0)
            dt, out = await _inspect(k, 'df.shape')
            assert out.get('ok'), out
            assert '(200, 2)' in str(out.get('result') or out.get('stdout')), out
            assert dt < 1.0, f'{kind}: the inspection waited {dt:.2f}s instead of running beside the cell'
            assert not busy.done(), 'the cell finished first, so this proved nothing'
            await busy
        finally:
            await k.shutdown()
    _run(go())

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

@pytest.mark.parametrize('kind', KINDS)
def test_several_inspections_overlap_rather_than_queue(tmp_path, kind):
    "Parallel fan-out is only worth anything if four inspections cost about what one does."
    async def go():
        k = await _kernel(tmp_path, kind, port=8640)
        try:
            await _warm(k)
            busy = asyncio.create_task(k.execute(YIELDING, timeout=30))
            await asyncio.sleep(1.0)
            t0 = time.monotonic()
            one, _ = await _inspect(k, 'df.shape')
            t0 = time.monotonic()
            outs = await asyncio.gather(*[_inspect(k, c) for c in
                                          ('df.shape', 'df.ndim', 'len(df)', 'df.size')])
            four = time.monotonic() - t0
            assert all(o.get('ok') for _, o in outs), outs
            assert four < max(1.0, one * 4), f'{kind}: four took {four:.2f}s against one at {one:.2f}s; they queued'
            assert not busy.done()
            await busy
        finally:
            await k.shutdown()
    _run(go())

@pytest.mark.parametrize('kind', KINDS)
def test_an_inspection_cannot_change_what_the_user_has(tmp_path, kind):
    "Why a sub-agent is allowed to run code at all."
    async def go():
        k = await _kernel(tmp_path, kind, port=8660)
        try:
            await k.execute('keep = 1\n', timeout=20)
            _, out = await _inspect(k, 'keep = 999\nkeep')
            assert out.get('ok'), out
            after = await k.execute('print(keep)', timeout=20)
            assert '1' in after.text and '999' not in after.text, after.text
        finally:
            await k.shutdown()
    _run(go())

def test_the_briefing_says_what_is_true_of_both_kernels():
    """Leela runs each inspection in the kernel's own subshell, on either launcher, so its briefing says so on either launcher."""
    from leela.agent.agent import system_prompt
    from leela.blocks.agent.ai import WorkspaceHost
    from leela.workspace import Workspace
    phrase = "while one of the user's cells is still running"
    for kind in ('ipykernel', 'ipymini'):
        host = WorkspaceHost(Workspace(roots=[], kernel=kind))
        assert host.concurrent, kind
        assert phrase in system_prompt(host, []), kind

@pytest.mark.parametrize('kind', KINDS)
def test_overlay_gives_the_real_interpreter_while_a_cell_runs(tmp_path, kind):
    "The scope that makes `inspect_python` worth having, and the one I got wrong first."
    async def go():
        k = await _kernel(tmp_path, kind, port=8680)
        try:
            await k.execute('import pandas as pd\n'
                            'df = pd.DataFrame({"a": range(200), "b": range(200)})\n', timeout=20)
            await _inspect(k, '1', 'overlay')
            busy = asyncio.create_task(k.execute(YIELDING, timeout=40))
            await asyncio.sleep(1.0)
            for code in ('list(df.columns)', 'df.head(2).to_dict()'):
                dt, out = await _inspect(k, code, 'overlay')
                assert out.get('ok'), f'{kind}: overlay should allow {code}: {out}'
                assert dt < 1.5, f'{kind}: {code} took {dt:.2f}s beside a running cell'
                _, sandboxed = await _inspect(k, code, 'isolated')
                assert sandboxed.get('ok'), f'{kind}: isolated should allow {code}: {sandboxed}'
            assert not busy.done(), 'the cell finished first, so this proved nothing'
            await busy
        finally:
            await k.shutdown()
    _run(go())

@pytest.mark.parametrize('kind', KINDS)
def test_overlay_names_persist_but_the_owners_do_not_move(tmp_path, kind):
    "Overlay is a *layer*, and that is the whole reason it is safe to offer."
    async def go():
        k = await _kernel(tmp_path, kind, port=8700)
        try:
            await k.execute('seed = 1\nimport pandas as pd\n'
                            'df = pd.DataFrame({"a": range(200), "b": range(200)})\n', timeout=20)
            await _inspect(k, '1', 'overlay')
            busy = asyncio.create_task(k.execute(YIELDING, timeout=40))
            await asyncio.sleep(1.0)
            _, mk = await _inspect(k, 'agent_tmp = len(df) * 2', 'overlay')
            assert mk.get('ok'), mk
            _, got = await _inspect(k, 'agent_tmp', 'overlay')
            assert '400' in str(got.get('result') or got.get('stdout')), got
            _, shadow = await _inspect(k, 'seed = 999', 'overlay')
            assert shadow.get('ok'), shadow
            assert not busy.done()
            await busy
            after = await k.execute('print(seed)', timeout=20)
            assert '1' in after.text and '999' not in after.text, (
                f"the agent moved the owner's variable: {after.text!r}")
        finally:
            await k.shutdown()
    _run(go())

@pytest.mark.parametrize('kind', KINDS)
def test_overlay_still_refuses_to_touch_what_the_user_made(tmp_path, kind):
    "The AST policy, which is what stands in for the sandbox once the sandbox is gone."
    async def go():
        k = await _kernel(tmp_path, kind, port=8720)
        try:
            await k.execute('vals = [1, 2, 3]\n', timeout=20)
            for code in ('vals.append(4)', 'del vals', 'vals[0] = 9'):
                _, out = await _inspect(k, code, 'overlay')
                assert not out.get('ok'), f'overlay allowed {code}: {out}'
                assert 'blocked' in str(out.get('error')).lower(), out
            after = await k.execute('print(vals)', timeout=20)
            assert '[1, 2, 3]' in after.text, after.text
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
            assert h.promote_var('df_norm') == "df_norm is now in the user's namespace"
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

def test_a_host_can_refuse_overlay():
    "`--agent-scope isolated` is the setting for a machine where even a scratch layer is unwanted."
    from leela.blocks.agent.ai import WorkspaceHost
    assert WorkspaceHost(Workspace(roots=[])).scopes == ('isolated', 'overlay')
    assert WorkspaceHost(Workspace(roots=[], agent_scope='isolated')).scopes == ('isolated',)

@pytest.mark.parametrize('kind', KINDS[:1])
def test_the_isolated_sandbox_is_narrower_than_it_looks(tmp_path, kind):
    "The boundary, measured, because it changes what the tool is good for."
    async def go():
        k = await _kernel(tmp_path, kind, port=8680)
        try:
            await k.execute('import pandas as pd\n'
                            'df = pd.DataFrame({"a": range(200), "b": range(200)})\n', timeout=20)
            for code in ('df.shape', 'len(df)', 'df.size', 'list(df.columns)', 'df.head(2).to_dict()'):
                _, out = await _inspect(k, code)
                assert out.get('ok'), f'{code} should be allowed: {out}'
            _, wrote = await _inspect(k, 'df["a"] = -1')
            assert not wrote.get('ok') and 'cannot modify owner' in str(wrote.get('error')).lower(), wrote
        finally:
            await k.shutdown()
    _run(go())

pytestmark = pytest.mark.slow

import os
from pathlib import Path


from leela.agent.core import LOCAL, local_ctx
from leela.blocks.nb.nb import Notebook
from leela.workspace import Workspace

MODEL_NAME = 'gemma-e4b'
MODEL_ID = LOCAL[MODEL_NAME]
REPO = Path(__file__).resolve().parents[1]
DIALOG = REPO/'tests'/'fixtures'/'dialog.ipynb'
PROMPT_CELL = 2

def _model_available():
    from rishi.litert import _cached_model
    return bool(_cached_model(MODEL_ID))

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

def test_real_dialog_prompt_uses_a_16k_litert_engine(dialog_agent):
    ws, nb = dialog_agent
    backend = ws.inline_ai.backend
    assert backend.start() is not None
    assert local_ctx(MODEL_NAME) == 16384
    assert backend.chat.ctx_limit == 16384
    assert backend.chat.engine.max_num_tokens == 16384
    # rishi builds the config when it makes the conversation, so `_conv_kw` no longer carries it.
    cfg = backend.chat._conv_kw.get('constrained_decoding_config') or backend.chat._constrained()
    assert getattr(cfg, 'enable', False)
    assert {'run_python', 'inspect_python'} <= {t.__name__ for t in backend.tools}
    cell = nb[PROMPT_CELL]
    message = ws.inline_ai.compose(
        cell.source,
        context=nb.context(PROMPT_CELL, since=nb.prompt_start(PROMPT_CELL)),
        context_path=nb.path,
    )
    # Measured, not inherited: 56 tool schemas and a 2267-token briefing. The inline path is
    # deliberately this large. litert-lm dropped and duplicated tokens past a 2048-token
    # prefill until rishi 0.1.30 stopped its GPU backend defaulting to FLOAT16 activations,
    # and the tool set was cut to 6 for one afternoon over it. See `docs/regressions.md`.
    assert 5600 <= backend.pending_tokens(message) <= 6200
    assert backend.fits(message)

def test_real_dialog_prompt_cell_completes_end_to_end(dialog_agent):
    ws, nb = dialog_agent
    chunks = list(ws.ask_cell_stream(nb, PROMPT_CELL))
    assert chunks
    assert nb[PROMPT_CELL].reply.strip()
    assert 'the assistant failed' not in nb[PROMPT_CELL].reply
    assert 'produced no event' not in nb[PROMPT_CELL].reply
    assert not ws.inline_ai.problems
    rows = ws.kernel_peek().api_sync('/api/rows', {'profile': 'minimal', 'sort': 'name'})
    names = {v.get('name') for g in (rows or {}).get('groups', []) for v in g.get('nodes', [])}
    assert 'df_norm' in names, 'the imperative prompt must execute and bind its requested result'
