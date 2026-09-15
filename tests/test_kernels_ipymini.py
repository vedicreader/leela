"Tests for the optional ipymini launcher."

from __future__ import annotations
import asyncio, sys, warnings
import pytest

from leela.blocks.runtime.kernels import Kernel, KernelPool, _spec, bootstrap_src, ipymini_available, output_text

def test_the_kernel_spec_and_bootstrap_follow_the_chosen_launcher():
    import dhrishti
    from leela import cli
    s = _spec()
    assert s.argv == [sys.executable, '-m', 'ipykernel_launcher', '-f', '{connection_file}']
    assert s.metadata['supported_encryption'] == 'curve'
    s = _spec(kernel='ipymini')
    assert s.argv == [sys.executable, '-Xfrozen_modules=off', '-m', 'ipymini', '-f', '{connection_file}']
    assert bootstrap_src(kernel='ipymini') == bootstrap_src(kernel='ipykernel')
    src = bootstrap_src()
    assert 'set_kernel_backend' not in src
    assert 'get_ipython' not in src
    assert str(__import__('pathlib').Path(dhrishti.__file__).resolve()) in src
    assert "spec_from_file_location('dhrishti'" in src
    assert "del sys.modules[_n]" in src
    k = Kernel()
    assert k.kernel_kind == 'ipykernel'
    if not ipymini_available(): pytest.skip('ipymini not installed')
    k = Kernel(kernel='ipymini')
    assert k.kernel_kind == 'ipymini'
    k = Kernel(); k.kernel = 'ipymini'
    with pytest.raises(RuntimeError, match='requires an ipykernel'):
        asyncio.run(k.debug_request('initialize'))
    k = Kernel(kernel='definitely-not-a-kernel')
    assert k.kernel_kind == 'ipykernel'
    with pytest.raises(SystemExit):
        cli.main(['--kernel', 'nonesuch'])









def test_pool_default_kernel_forwarded(monkeypatch):
    "KernelPool.default_kernel is what Kernel() gets when the caller doesn't say."
    seen = {}
    class Fake:
        def __init__(self, **kw): seen.update(kw); self.alive = False
        def touch(self): return self          # the pool stamps every kernel it hands out
        async def start(self): return self
    #: `kunda.pool` imports `Kernel` into its own namespace and `_class_for` reads it there, so
    #: patching Leela's re-export patched a name the pool never looks at.
    monkeypatch.setattr('kunda.pool.Kernel', Fake)
    pool = KernelPool(default_kernel='ipymini')
    asyncio.new_event_loop().run_until_complete(pool.get('k'))
    assert seen['kernel'] == 'ipymini'

def test_a_pool_and_its_workspace_stay_usable_around_a_bad_kernel():
    from leela.workspace import Workspace
    outs = [{'output_type': 'display_data', 'data': {
        'text/markdown': '**rendered**', 'text/plain': '<IPython.display.Markdown object>'}}]
    assert output_text(outs) == '**rendered**'
    class Manager:
        has_kernel = True
    kernel = Kernel()
    kernel.km = Manager()
    assert not kernel.alive
    assert asyncio.run(Kernel().stop()) == {
        'ok': False, 'forced': False, 'note': 'nothing is running'}
    pool = KernelPool(default_kernel='bogus')
    assert pool.default_kernel == 'ipykernel'
    ws = Workspace(kernel='ipymini')
    assert ws.kernel_kind == 'ipymini'
    assert callable(ws.kernel)
    assert ws.pool.default_kernel in ('ipymini', 'ipykernel')
    assert Workspace().kernel_kind == 'ipykernel'


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

def test_step_in_source_maps_back_to_the_notebook_definition_cell():
    async def run():
        k = Kernel(inspect=False, kernel='ipykernel'); await k.start()
        stopped = asyncio.Event()
        definition = 'def helper(values):\n    first = values[0]\n    return first + 3'
        call = 'seed = [4, 5]\ny = helper(seed)\nprint(y)'
        try:
            assert (await k.execute(definition)).ok
            await k.debug_start(call, [2], [('definition-cell', definition), ('call-cell', call)])
            def event(row):
                if row.get('event') == 'stopped': stopped.set()
            task = asyncio.create_task(k.execute(call, on_debug=event))
            await asyncio.wait_for(stopped.wait(), 15); stopped.clear()
            await k.debug_control('stepIn')
            await asyncio.wait_for(stopped.wait(), 15)
            state = await k.debug_state()
            assert k._debug_sources[state['frames'][0]['source']['path']] == 'definition-cell'
            assert any(v['name'] == 'values' and v['value'] == '[4, 5]' for v in state['variables'])
            await k.debug_control('continue'); assert (await task).text == '7\n'
        finally:
            try: await k.debug_stop()
            except Exception: pass
            await k.shutdown()
    asyncio.run(run())

def test_collect_forwards_unparented_debug_events_without_losing_cell_output():
    class Manager:
        has_kernel = True
    class Client:
        def __init__(self):
            self.messages = [
                {'parent_header': {}, 'header': {'msg_type': 'debug_event'},
                 'content': {'event': 'stopped', 'body': {'threadId': 7}}},
                {'parent_header': {'msg_id': 'm'}, 'header': {'msg_type': 'stream'},
                 'content': {'name': 'stdout', 'text': 'done\n'}},
                {'parent_header': {'msg_id': 'm'}, 'header': {'msg_type': 'status'},
                 'content': {'execution_state': 'idle'}},
            ]
        async def get_iopub_msg(self, timeout=None): return self.messages.pop(0)
    k = Kernel(); k.km, k.kc = Manager(), Client()
    events = []
    outs = asyncio.run(k._collect('m', on_debug=events.append))
    assert events[0]['event'] == 'stopped' and k._debug_thread == 7
    assert outs[0]['text'] == 'done\n'

def test_display_id_updates_replace_streaming_markdown_in_place():
    class Manager:
        has_kernel = True
    class Client:
        def __init__(self):
            self.messages = [
                {'parent_header': {'msg_id': 'm'}, 'header': {'msg_type': 'display_data'},
                 'content': {'data': {'text/markdown': 'first'}, 'metadata': {},
                             'transient': {'display_id': 'rishi'}}},
                {'parent_header': {'msg_id': 'm'}, 'header': {'msg_type': 'update_display_data'},
                 'content': {'data': {'text/markdown': 'final'}, 'metadata': {},
                             'transient': {'display_id': 'rishi'}}},
                {'parent_header': {'msg_id': 'm'}, 'header': {'msg_type': 'status'},
                 'content': {'execution_state': 'idle'}},
            ]
        async def get_iopub_msg(self, timeout=None): return self.messages.pop(0)
    k = Kernel(); k.km, k.kc = Manager(), Client()
    events = []
    outs = asyncio.run(k._collect('m', on_output=events.append))
    assert len(outs) == 1
    assert outs[0]['data']['text/markdown'] == 'final'
    assert events[0]['_display_id'] == 'rishi' and not events[0]['_update']
    assert events[1]['_display_id'] == 'rishi' and events[1]['_update']

def test_concurrent_pool_gets_share_one_start(monkeypatch):
    "Autocomplete, variables and the kernel pill all ask at boot; that must launch one process."
    made = []
    class Fake:
        alive = False
        def __init__(self, **kw): made.append(self)
        def touch(self): return self          # the pool stamps every kernel it hands out
        async def start(self):
            await asyncio.sleep(0.02)
            self.alive = True
            return self
    monkeypatch.setattr('kunda.pool.Kernel', Fake)   # the name `_class_for` reads
    async def go():
        pool = KernelPool()
        got = await asyncio.gather(*[pool.get('project') for _ in range(5)])
        return got
    got = asyncio.run(go())
    assert len(made) == 1 and all(k is made[0] for k in got)

def test_pool_does_not_expose_a_half_started_kernel(monkeypatch):
    "A manager can have a process before its client exists; later requests must await start()."
    process_started, finish_start = asyncio.Event(), asyncio.Event()
    class Fake:
        def __init__(self, **kw): self.process_alive, self.kc = False, None
        # Stamped before `start`, so without it this hangs on an event `start` never reaches.
        def touch(self): return self
        @property
        def alive(self): return self.process_alive
        async def start(self):
            self.process_alive = True
            process_started.set()
            await finish_start.wait()
            self.kc = object()
            return self
    monkeypatch.setattr('kunda.pool.Kernel', Fake)   # the name `_class_for` reads
    async def go():
        pool = KernelPool()
        first = asyncio.create_task(pool.get('project'))
        await process_started.wait()
        second = asyncio.create_task(pool.get('project'))
        await asyncio.sleep(0)
        assert not second.done()
        finish_start.set()
        return await first, await second
    first, second = asyncio.run(go())
    assert first is second and first.kc is not None


def test_pool_peek_hides_a_kernel_until_start_is_complete(monkeypatch):
    started, finish = asyncio.Event(), asyncio.Event()
    class Fake:
        def __init__(self, **kw): self.alive = False
        def touch(self): return self          # the pool stamps every kernel before it starts it
        async def start(self):
            started.set()
            await finish.wait()
            self.alive = True
            return self
    monkeypatch.setattr('kunda.pool.Kernel', Fake)   # the name `_class_for` reads
    async def go():
        pool = KernelPool()
        pending = asyncio.create_task(pool.get('project'))
        await started.wait()
        assert pool.peek('project') is None
        finish.set()
        kernel = await pending
        assert pool.peek('project') is kernel
    asyncio.run(go())

def test_stop_forces_restart_when_execution_ignores_interrupt(monkeypatch):
    async def go():
        k = Kernel()
        calls = []
        async def interrupt(): calls.append('interrupt')
        async def restart(): calls.append('restart')
        monkeypatch.setattr(k, 'interrupt', interrupt)
        monkeypatch.setattr(k, 'restart', restart)
        task = asyncio.create_task(asyncio.sleep(30))
        k._exec_task = task
        result = await k.stop(timeout=0.01)
        assert result['ok'] and result['forced']
        assert calls == ['interrupt', 'restart'] and task.cancelled()
    asyncio.run(go())



def test_fallback_when_ipymini_missing(monkeypatch):
    "Asking for ipymini when it isn't installed warns and falls back."
    monkeypatch.setattr('kunda.kernel.ipymini_available', lambda: False)   # where `Kernel` reads it
    with warnings.catch_warnings(record=True) as ws:
        warnings.simplefilter('always')
        k = Kernel(kernel='ipymini')
    assert k.kernel_kind == 'ipykernel'
    assert any('ipymini' in str(w.message).lower() for w in ws)

def test_cli_default_kernel_is_ipykernel(monkeypatch):
    from leela import cli
    seen = {}
    def fake_run(roots, **kw): seen.update(kw); seen['_roots'] = roots
    monkeypatch.setattr('leela.app.serve_ide', fake_run)
    cli.main([])
    assert seen['kernel'] == 'ipykernel'

def test_cli_ipymini_flag(monkeypatch):
    from leela import cli
    seen = {}
    def fake_run(roots, **kw): seen.update(kw)
    monkeypatch.setattr('leela.app.serve_ide', fake_run)
    cli.main(['--kernel', 'ipymini'])
    assert seen['kernel'] == 'ipymini'


def test_cli_refuses_non_loopback_bind_before_starting_server(monkeypatch):
    from leela import cli
    monkeypatch.setattr('leela.app.serve_ide', lambda *a, **k: pytest.fail('server should not start'))
    with pytest.raises(SystemExit):
        cli.main(['--host', '0.0.0.0'])

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
