import asyncio, json, time
import pytest
from leela.blocks.nb.exercise import run_checks
from leela.blocks.nb.nb import Cell, Notebook
from leela.blocks.runtime.kernels import Kernel

pytestmark = pytest.mark.slow

@pytest.fixture
def kernel(tmp_path):
    return Kernel(inspect=False, kernel='ipykernel', cwd=str(tmp_path))

def test_real_checks_leave_history_and_namespace_clean(kernel):
    async def go():
        try:
            await kernel.start()
            nb = Notebook([Cell(source='def double(x): return x*2')])
            await nb.run(nb.cells[0], kernel)
            probe = 'import json; print(json.dumps({"names": sorted(get_ipython().user_ns), "history": list(In), "same": In is _ih}))'
            before = await kernel.execute(probe, silent=True, store_history=False)
            before = json.loads(before.text)
            tests = ['assert double(123456789) == 246913578', 'assert double(-987654321) == -5']
            r = await run_checks(kernel, 'double', tests)
            assert [c['status'] for c in r['checks']] == ['pass', 'fail'] and r['checks'][1]['got'] == '-1975308642'
            after = await kernel.execute(probe, silent=True, store_history=False)
            after = json.loads(after.text)
            assert after == before and after['same']
            assert not any(n.startswith('__leela_exercise') for n in after['names'])
            assert all(t not in '\n'.join(after['history']) for t in tests)
        finally: await kernel.shutdown()
    asyncio.run(go())

def test_twelve_slow_tests_share_one_budget(kernel):
    async def go():
        try:
            await kernel.start()
            await kernel.execute('import time\ncalls = []\ndef slow(x):\n    calls.append(x)\n    time.sleep(.25)\n    return x*2')
            started = time.monotonic()
            r = await run_checks(kernel, 'slow', ['assert slow(2) == 4']*12, timeout=.4)
            assert time.monotonic() - started < 1.4
            assert len(r['checks']) == 12
            assert r['checks'][0]['status'] == 'pass'
            assert all(c['status'] == 'timeout' for c in r['checks'][1:])
            assert (await kernel.execute('print(len(calls))', silent=True, store_history=False)).text.strip() == '2'
        finally: await kernel.shutdown()
    asyncio.run(go())

def test_interrupt_stops_real_kernel_checks(kernel):
    async def go():
        try:
            await kernel.start()
            await kernel.execute('calls = []\ndef interrupted(x):\n    calls.append(x)\n    raise KeyboardInterrupt()')
            r = await run_checks(kernel, 'interrupted', ['assert interrupted(2) == 4']*12)
            assert len(r['checks']) == 12 and all(c['status'] == 'timeout' for c in r['checks'])
            assert (await kernel.execute('print(len(calls))', silent=True, store_history=False)).text.strip() == '1'
        finally: await kernel.shutdown()
    asyncio.run(go())

def test_endless_function_times_out_within_twelve_seconds(kernel):
    async def go():
        try:
            await kernel.start()
            await kernel.execute('def endless(x):\n    while True: pass')
            started = time.monotonic()
            r = await run_checks(kernel, 'endless', ['assert endless(1) == 2'])
            assert time.monotonic() - started < 12
            assert r == dict(found=True, checks=[dict(i=0, status='timeout', got=None, error='TimeoutError')])
            assert (await kernel.execute('print(6*7)', silent=True, store_history=False)).text.strip() == '42'
        finally: await kernel.shutdown()
    asyncio.run(go())
