"""Can a sub-agent look at the user's live variables while the user is busy?

Written after measuring rather than before, because the measurement contradicted the
obvious guess. The guess was that ipymini's subshell is what lets an agent reach the
kernel during a running cell. It is not: leela already serves its inspector from an HTTP
server *inside* the kernel process, so an agent request never goes near the shell queue a
cell is holding. That was true before ipymini and stays true after it.

What was actually missing was much simpler. `subagent.read_only` strips every write tool,
`run_python` is a write tool, and there was no read-only execution tool — so a sub-agent
had no way to touch the live namespace at all. `inspect_python` is that tool, and these
tests are the evidence for what it can and cannot do:

- against a cell that yields (any `await`, any I/O — most of what a notebook waits on) an
  inspection answers in tens of milliseconds, under **both** kernels;
- against a CPU-bound loop holding the GIL it *still* answers in about the same time,
  because CPython hands the GIL over every few milliseconds — only the very first call,
  which builds the session, is slow enough to notice;
- several inspections overlap rather than queue;
- and nothing a sub-agent runs can change what the user has.

Everything skips without ipymini so the comparison can be made; the single-kernel
behaviour is asserted for ipykernel too, since that is what most people run.
"""

import asyncio
import time

import pytest

from leela.kernels import Kernel, ipymini_available

KINDS = ['ipykernel'] + (['ipymini'] if ipymini_available() else [])

# A cell that binds something worth inspecting, then waits in a way that yields the GIL.
YIELDING = (
    'import asyncio, pandas as pd\n'
    'df = pd.DataFrame({"a": range(200), "b": range(200)})\n'
    'async def _hold():\n'
    '    ip = get_ipython()\n'
    '    if hasattr(ip.kernel, "unlock"): ip.kernel.unlock()\n'
    '    await asyncio.sleep(3.0)\n'
    'await _hold()\n'
)

# The same, but spinning: nothing else in the process gets a fair share of the interpreter.
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


async def _inspect(k, code, timeout=20):
    """One `/agent/api/exec` in the isolated scope: exactly what `Host.inspect_python` does.

    Driven over HTTP rather than through the harness because the harness would only be
    forwarding, and the question here is entirely about the kernel underneath it.
    """
    import httpx
    async with httpx.AsyncClient(base_url=k.base, timeout=timeout) as c:
        t0 = time.monotonic()
        r = await c.get('/agent/api/exec', params={'code': code, 'scope': 'isolated'})
        return time.monotonic() - t0, r.json()


async def _warm(k):
    "First call builds the agent session and imports the sandbox; that cost is not the measurement."
    await _inspect(k, '1')


@pytest.mark.parametrize('kind', KINDS)
def test_an_inspection_runs_beside_a_yielding_cell(tmp_path, kind):
    """The capability sub-agents needed, and leela already had the architecture for.

    Asserted for both kernels on purpose: the in-kernel HTTP inspector is what makes this
    work, so it is not an ipymini feature and should not be sold as one.
    """
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
    """The surprising one, and the reason these tests were written after measuring.

    A cell holding the GIL in a tight loop was the case I expected to lose: no subshell can
    make a spinning interpreter share. It does not lose, because CPython hands the GIL over
    every few milliseconds and a warm inspection is microseconds of work. What *is* slow is
    the very first call, which has to build the agent session and import the sandbox while
    competing with the loop — so the warm-up is done before the cell starts, exactly as a
    real session would have done it on some earlier question.
    """
    async def go():
        k = await _kernel(tmp_path, kind, port=8620)
        try:
            await _warm(k)
            busy = asyncio.create_task(k.execute(SPINNING, timeout=30))
            await asyncio.sleep(1.0)
            dt, out = await _inspect(k, 'df.shape', timeout=15)
            assert out.get('ok'), out
            assert '(200, 2)' in str(out.get('result') or out.get('stdout')), out
            assert dt < 1.0, f'{kind}: a warm inspection took {dt:.2f}s against a spinning cell'
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
    """Why a sub-agent is allowed to run code at all.

    The isolated scope seeds the owner's state into a throwaway sandbox and discards every
    write. Without that, "sub-agents can reach the kernel" would mean "agents nobody is
    watching are racing on your variables", which is a worse feature than not having one.
    """
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


def test_a_subagent_is_given_inspect_python_and_no_write_tools():
    "The harness half: `read_only` must keep the one execution tool that is safe to delegate."
    from leela.agent.subagent import NO_SUB, read_only
    from leela.agent.tools import WRITE_TOOLS

    class Fake:
        def __init__(self, n): self.__name__ = n
    tools = [Fake(n) for n in ('search_code', 'view_file', 'inspect_python', 'run_python',
                               'edit_file', 'delegate_search', 'delegate_parallel')]
    names = {t.__name__ for t in read_only(tools)}
    assert 'inspect_python' in names
    assert not (names & WRITE_TOOLS), 'a sub-agent must not be able to write'
    assert not (names & NO_SUB), 'a sub-agent must not spawn sub-agents of its own'


def test_the_briefing_says_what_is_true_of_both_kernels():
    """The briefing promises concurrency unconditionally, because it is unconditionally true.

    An earlier version made the promise only under ipymini and warned the model to keep
    inspections short otherwise. The tests above are why that was removed: the concurrency
    comes from leela's in-kernel inspector, so the warning was advice for a problem that
    does not exist, and it would have made the agent avoid a tool that works.
    """
    from leela.agent.chat import system_prompt
    from leela.agent.host import NullHost

    class Mini(NullHost): kernel_kind = 'ipymini'
    for h in (Mini(['/x']), NullHost(['/x'])):
        sp = system_prompt(h, [])
        assert "while one of the user's cells is still running" in sp
        assert 'one thing at a time' not in sp
    assert 'subshell' in system_prompt(Mini(['/x']), [])
    assert 'subshell' not in system_prompt(NullHost(['/x']), [])


@pytest.mark.parametrize('kind', KINDS[:1])
def test_the_isolated_sandbox_is_narrower_than_it_looks(tmp_path, kind):
    """The boundary, measured, because it changes what the tool is good for.

    `inspect_python` runs in safepyrun's allowlist sandbox, and the allowlist is strict:
    attribute reads and builtins go through, but most *library method calls* are refused by
    fastaudit — `df.shape` and `len(df)` work, `list(df.columns)` and `df.head(2).to_dict()`
    do not. So the tool answers "what shape / how many / what type", not "show me the data".

    Written down as a test because the alternative is an agent that discovers it one failed
    call at a time, and because loosening it is a real design decision (a per-sub-agent
    overlay session would allow real calls at the cost of a scratch layer to manage) rather
    than something to slip in.
    """
    async def go():
        k = await _kernel(tmp_path, kind, port=8680)
        try:
            await k.execute('import pandas as pd\n'
                            'df = pd.DataFrame({"a": range(200), "b": range(200)})\n', timeout=20)
            for code in ('df.shape', 'len(df)', 'df.size'):
                _, out = await _inspect(k, code)
                assert out.get('ok'), f'{code} should be allowed: {out}'
            for code in ('list(df.columns)', 'df.head(2).to_dict()'):
                _, out = await _inspect(k, code)
                assert not out.get('ok'), f'{code} is allowed now; update the docstring on inspect_python'
                assert 'sandbox' in str(out.get('error')).lower(), out
        finally:
            await k.shutdown()
    _run(go())
