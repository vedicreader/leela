"""Tests for the optional ipymini launcher.

The heavy tests (actual kernel start + concurrent-execute race) are gated behind
`importorskip('ipymini')` so the default suite stays fast and works without the extra
installed. The unit tests below run without ipymini.
"""

from __future__ import annotations
import asyncio, sys, warnings
import pytest

from leela.kernels import Kernel, KernelPool, _spec, bootstrap_src, ipymini_available


# -- unit tests: no live kernel, no ipymini required ---------------------------------

def test_spec_ipykernel_default():
    s = _spec()
    assert s.argv == [sys.executable, '-m', 'ipykernel_launcher', '-f', '{connection_file}']

def test_spec_ipymini_argv():
    s = _spec(kernel='ipymini')
    assert s.argv == [sys.executable, '-Xfrozen_modules=off', '-m', 'ipymini', '-f', '{connection_file}']

def test_bootstrap_src_carries_ipymini_flag():
    "ipymini bootstrap stashes _kernel_backend on the inspect server."
    assert '_kernel_backend' in bootstrap_src(kernel='ipymini')
    assert "'True'" in bootstrap_src(kernel='ipymini') or 'True' in bootstrap_src(kernel='ipymini')
    # ipykernel bootstrap does not stash anything.
    src = bootstrap_src(kernel='ipykernel')
    assert 'False' in src

def test_kernel_kind_default_ipykernel():
    k = Kernel()
    assert k.kernel_kind == 'ipykernel'

def test_kernel_kind_ipymini_selected():
    if not ipymini_available(): pytest.skip('ipymini not installed')
    k = Kernel(kernel='ipymini')
    assert k.kernel_kind == 'ipymini'

def test_unknown_kernel_falls_back():
    k = Kernel(kernel='definitely-not-a-kernel')
    assert k.kernel_kind == 'ipykernel'

def test_pool_default_kernel_forwarded(monkeypatch):
    "KernelPool.default_kernel is what Kernel() gets when the caller doesn't say."
    seen = {}
    class Fake:
        def __init__(self, **kw): seen.update(kw); self.alive = False
        async def start(self): return self
    monkeypatch.setattr('leela.kernels.Kernel', Fake)
    pool = KernelPool(default_kernel='ipymini')
    asyncio.new_event_loop().run_until_complete(pool.get('k'))
    assert seen['kernel'] == 'ipymini'

def test_pool_ignores_bad_default():
    pool = KernelPool(default_kernel='bogus')
    assert pool.default_kernel == 'ipykernel'

def test_fallback_when_ipymini_missing(monkeypatch):
    "Asking for ipymini when it isn't installed warns and falls back."
    monkeypatch.setattr('leela.kernels.ipymini_available', lambda: False)
    with warnings.catch_warnings(record=True) as ws:
        warnings.simplefilter('always')
        k = Kernel(kernel='ipymini')
    assert k.kernel_kind == 'ipykernel'
    assert any('ipymini' in str(w.message).lower() for w in ws)


# -- CLI wiring ---------------------------------------------------------------------

def test_cli_default_kernel_is_ipykernel(monkeypatch):
    import argparse
    from leela import cli
    seen = {}
    def fake_run(roots, **kw): seen.update(kw); seen['_roots'] = roots
    monkeypatch.setattr('leela.tui.app.run', fake_run)
    cli.main([])
    assert seen['kernel'] == 'ipykernel'

def test_cli_ipymini_flag(monkeypatch):
    from leela import cli
    seen = {}
    def fake_run(roots, **kw): seen.update(kw)
    monkeypatch.setattr('leela.tui.app.run', fake_run)
    cli.main(['--kernel', 'ipymini'])
    assert seen['kernel'] == 'ipymini'

def test_cli_rejects_unknown_kernel():
    from leela import cli
    with pytest.raises(SystemExit):
        cli.main(['--kernel', 'nonesuch'])


# -- live-kernel tests, gated on ipymini ---------------------------------------------

pytestmark_live = pytest.mark.skipif(not ipymini_available(),
                                     reason='ipymini not installed')


def _run(coro):
    "Drive an async coroutine from a sync test, isolated event loop."
    return asyncio.new_event_loop().run_until_complete(coro)


@pytestmark_live
def test_ipymini_starts_and_bootstraps_inspector(tmp_path):
    "A live ipymini kernel launches, bootstraps the inspector, and answers /api/rows."
    async def go():
        k = Kernel(kernel='ipymini', name='ipymini-test', cwd=str(tmp_path))
        try:
            await k.start(timeout=90)
            assert k.alive
            assert k.kernel_kind == 'ipymini'
            # bootstrap ok
            assert k.boot_error is None, k.boot_error
            assert k.base is not None
            # define a var, then read it via the inspector's HTTP surface
            r = await k.execute('x_marker = 42', silent=False)
            assert r.ok, r.error
            names = await k.names()
            assert 'x_marker' in names
        finally:
            await k.shutdown()
    _run(go())


@pytestmark_live
def test_ipymini_agent_exec_runs_while_cell_sleeps(tmp_path):
    """Under ipymini, /agent/api/exec should return while a long cell is awaiting with unlock().

    Baseline: this test also demonstrates that /api/rows keeps answering (unchanged from
    ipykernel). Together they lock in the concurrency behaviour we added ipymini for.
    """
    import time, httpx
    async def go():
        k = Kernel(kernel='ipymini', name='ipymini-race', cwd=str(tmp_path))
        try:
            await k.start(timeout=90)
            # Kick off a cell that awaits ~2s while calling unlock() so the kernel can
            # service other work. We do this on a background task; don't await the
            # execute here.
            long_code = (
                'import asyncio\n'
                'async def _busy():\n'
                '    ip = get_ipython()\n'
                '    ip.kernel.unlock()\n'
                '    await asyncio.sleep(2.0)\n'
                '    return "done"\n'
                '_result = await _busy()\n'
            )
            busy = asyncio.create_task(k.execute(long_code, timeout=30))
            await asyncio.sleep(0.4)  # let the cell start and hit unlock()

            # While it's sleeping, hit /agent/api/exec and /api/rows over HTTP.
            headers = {'X-Leela-Token': k.token} if k.token else {}
            async with httpx.AsyncClient(base_url=k.base, headers=headers, timeout=10) as c:
                t0 = time.monotonic()
                rows = await c.get('/api/rows')
                rt = time.monotonic() - t0
                assert rows.status_code == 200
                # inspector must answer quickly - a background thread, not shell-queued
                assert rt < 1.5, f'/api/rows took {rt:.2f}s'

                t0 = time.monotonic()
                aex = await c.get('/agent/api/exec', params={'code': 'agent_var = 7'})
                at = time.monotonic() - t0
                assert aex.status_code == 200
                body = aex.json()
                assert body.get('ok'), body
                # the agent exec runs on the HTTP thread inside the kernel; it must not
                # be blocked by the sleeping cell.
                assert at < 1.5, f'/agent/api/exec took {at:.2f}s while cell slept'

            await busy  # let the cell finish
        finally:
            await k.shutdown()
    _run(go())
