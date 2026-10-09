"Tests for the optional ipymini launcher."

from __future__ import annotations
import asyncio
import pytest

from leela.blocks.runtime.kernels import Kernel, ipymini_available

def test_real_ipykernel_debugger_stops_and_exposes_locals():
    "The Jupyter Debug Protocol seam, including the control channel and unparented stop event."
    async def run():
        k = Kernel(inspect=False, kernel='ipykernel')
        await k.start()
        stopped = asyncio.Event()
        try:
            code = 'x = [4, 5]\ny = x[0] + 3\nprint(y)'
            assert await k.debug_start(code, [2], [('cell-before', 'helper = 1'), ('cell-current', code)]) == [2]
            assert {'cell-before', 'cell-current'} <= set(k._debug_sources.values())
            def event(row):
                if row.get('event') == 'stopped': stopped.set()
            task = asyncio.create_task(k.execute(code, on_debug=event))
            await asyncio.wait_for(stopped.wait(), 15)
            state = await k.debug_state()
            assert state['paused'] and state['frames'][0]['line'] == 2
            x = next(v for v in state['variables'] if v['name'] == 'x')
            assert x['value'] == '[4, 5]' and x['variablesReference']
            children = await k.debug_variables(x['variablesReference'])
            assert any(v['name'] == '0' and v['value'] == '4' for v in children)
            evaluated = await k.debug_evaluate('x[1] * 10', state['frame_id'])
            assert evaluated['result'] == '50'
            completed = await k.debug_complete('x.co', 4, state['frame_id'])
            assert 'copy' in completed['matches']
            await k.debug_control('continue')
            result = await asyncio.wait_for(task, 15)
            assert result.ok and result.text == '7\n'
        finally:
            try: await k.debug_stop()
            except Exception: pass
            await k.shutdown()
    asyncio.run(run())

pytestmark = pytest.mark.slow

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
            assert k.boot_error is None, k.boot_error
            assert k.base is not None
            r = await k.execute('x_marker = 42', silent=False)
            assert r.ok, r.error
            names = await k.names()
            assert 'x_marker' in names
        finally:
            await k.shutdown()
    _run(go())

@pytestmark_live
def test_ipymini_agent_exec_runs_while_cell_sleeps(tmp_path):
    "Under ipymini, /agent/api/exec should return while a long cell is awaiting with unlock()."
    import time, httpx2 as httpx
    async def go():
        k = Kernel(kernel='ipymini', name='ipymini-race', cwd=str(tmp_path))
        try:
            await k.start(timeout=90)
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
            await asyncio.sleep(0.4)
            headers = {'X-Dhrishti-Token': k.token} if k.token else {}
            async with httpx.AsyncClient(base_url=k.base, headers=headers, timeout=10) as c:
                t0 = time.monotonic()
                rows = await c.get('/api/rows')
                rt = time.monotonic() - t0
                assert rows.status_code == 200
                assert rt < 1.5, f'/api/rows took {rt:.2f}s'
                t0 = time.monotonic()
                aex = await c.get('/agent/api/exec', params={'code': 'agent_var = 7'})
                at = time.monotonic() - t0
                assert aex.status_code == 200
                body = aex.json()
                assert body.get('ok'), body
                assert at < 1.5, f'/agent/api/exec took {at:.2f}s while cell slept'
            await busy
        finally:
            await k.shutdown()
    _run(go())
