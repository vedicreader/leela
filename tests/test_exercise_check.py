import asyncio, io, json, time
from contextlib import redirect_stdout
import pytest
from leela.blocks.nb.exercise import run_checks
from leela.blocks.runtime.kernels import ExecOutcome

class CheckKernel:
    def __init__(self, source='def double(x): return x*2'):
        self.ns, self.sent = {}, []
        exec(source, self.ns)
    async def execute(self, code, **kw):
        self.sent.append((code, kw))
        out = io.StringIO()
        with redirect_stdout(out): exec(code, self.ns)
        text = out.getvalue()
        return ExecOutcome(ok=True, outputs=[dict(output_type='stream', name='stdout', text=text[:9]),
            dict(output_type='stream', name='stdout', text=text[9:])])

def test_pass_fail_got_and_silent_execution():
    k = CheckKernel()
    before = set(k.ns)
    r = asyncio.run(run_checks(k, 'double', ['assert double(2) == 4', 'assert double(2) == 987654321']))
    assert r == dict(found=True, checks=[dict(i=0, status='pass', got=None, error=None),
        dict(i=1, status='fail', got='4', error=None)])
    assert '987654321' not in json.dumps(r)
    assert k.sent[0][1] == dict(silent=True, store_history=False)
    assert set(k.ns) == before

@pytest.mark.parametrize('source, status, error', [
    ('def double(x): raise ValueError("private expected 987654321")', 'error', 'ValueError'),
    ('def double(x): raise SystemExit("987654321")', 'error', 'SystemExit'),
    ('def double(x): return 4', 'fail', None)])
def test_errors_do_not_reveal_test_values(source, status, error):
    k = CheckKernel(source)
    r = asyncio.run(run_checks(k, 'double', ['assert double(2) == 987654321, "987654321"']))
    assert r['checks'][0]['status'] == status and r['checks'][0]['error'] == error
    assert '987654321' not in json.dumps(r)
    assert not any(n.startswith('__leela_exercise') for n in k.ns)

@pytest.mark.parametrize('outputs', [[], [dict(output_type='stream', name='stdout', text='not json\n')],
                                     [dict(output_type='error', ename='NameError', evalue='x', traceback=[])]])
def test_a_kernel_that_sends_no_result_line_gives_a_plain_error(outputs):
    "A kernel that printed nothing parseable crashed the check with a JSON or index error."
    class SilentKernel:
        async def execute(self, code, **kw): return ExecOutcome(ok=True, outputs=outputs)
    assert asyncio.run(run_checks(SilentKernel(), 'double', ['assert double(2) == 4'])) == {'error': 'the kernel sent no check result'}

def test_missing_function():
    k = CheckKernel('x = 1')
    assert asyncio.run(run_checks(k, 'double', ['assert double(2) == 4'])) == dict(found=False, checks=[])

def test_timeout():
    class WaitingKernel:
        async def execute(self, code, **kw):
            assert kw == dict(silent=True, store_history=False)
            await asyncio.sleep(10)
    assert asyncio.run(run_checks(WaitingKernel(), 'double', ['assert double(2) == 4'], timeout=.01)) == {'timeout': True}

def test_clips_got_and_handles_non_equality():
    k = CheckKernel('def double(x): return "x"*500')
    r = asyncio.run(run_checks(k, 'double', ['assert double(2) == "no"', 'assert len(double(2)) > 0']))
    assert len(r['checks'][0]['got']) == 200
    assert r['checks'][1] == dict(i=1, status='pass', got=None, error=None)

def test_printing_function_still_emits_one_json_line():
    k = CheckKernel('def double(x):\n    print("not json")\n    return x*2')
    r = asyncio.run(run_checks(k, 'double', ['assert double(2) == 4']))
    assert r['checks'][0]['status'] == 'pass'


def test_total_budget_marks_remaining_tests_timeout():
    k = CheckKernel('import time\ncalls = []\ndef double(x):\n    calls.append(x)\n    time.sleep(.2)\n    return x*2')
    started = time.monotonic()
    r = asyncio.run(run_checks(k, 'double', ['assert double(2) == 4']*12, timeout=.1))
    assert time.monotonic() - started < 1.1
    assert len(r['checks']) == 12 and all(c['status'] == 'timeout' for c in r['checks'])
    assert k.ns['calls'] == [2]

def test_keyboard_interrupt_stops_the_run():
    k = CheckKernel('calls = []\ndef double(x):\n    calls.append(x)\n    raise KeyboardInterrupt()')
    r = asyncio.run(run_checks(k, 'double', ['assert double(2) == 4']*3))
    assert k.ns['calls'] == [2]
    assert r == dict(found=True, checks=[dict(i=i, status='timeout', got=None, error='TimeoutError') for i in range(3)])

def test_safe_names_come_from_abhyasa():
    from abhyasa.nb import SAFE_NAMES
    k = CheckKernel()
    asyncio.run(run_checks(k, 'double', ['assert double(2) == 4']))
    assert json.dumps(list(SAFE_NAMES)) in k.sent[0][0]
