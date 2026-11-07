"The closed learner-code runner, ported with its code from abhyasa 0.0.15 `tests/test_check.py` (abhyasa commit 004ebee^)."
import builtins
import json
import os
import subprocess
import sys
import threading
import time

import pytest

from leela.blocks.nb import check
from leela.blocks.nb.check import SAFE_BUILTINS, Report, public, run_asserts, safe_test, time_limit, validate_exercise




def test_safe_tests_and_dict_validation():
    assert safe_test('assert f(2) == 4', 'f')
    assert not safe_test("assert __import__('os')", 'f')
    tests = ['assert f(2) == 4', dict(test='assert f(3) == 6', say='three', hidden=True)]
    exercise = dict(task='Double a number.', fname='f', stub='def f(x): ...', tests=tests)
    assert validate_exercise(exercise).tests == tests
    with pytest.raises(ValueError, match='plain assert'):
        validate_exercise(dict(exercise, tests=[dict(test='import os', say='', hidden=True)]))
    for bad in ({}, {'test': 3}, {'test': 'assert f(1)', 'say': 3}, {'test': 'assert f(1)', 'hidden': 'yes'}):
        with pytest.raises(ValueError): validate_exercise(dict(exercise, tests=[bad]))


def test_report_and_statuses():
    report = run_asserts(lambda x: 2 * x, 'f', ['assert f(2) == 4', dict(test='assert f(3) == 7', say='Three')])
    assert isinstance(report, Report)
    assert report.found and not report.timeout and not report.passed
    assert [c.status for c in report.checks] == ['pass', 'fail']
    assert [c.got for c in report.checks] == ['4', '6']
    assert report.checks[1].label == 'Three'
    assert report.checks[1].error.startswith('AssertionError:')
    assert all(c.ms >= 0 for c in report.checks)
    assert run_asserts(lambda: 1, 'f', ['assert f() == 1']).passed
    missing = run_asserts(None, 'f', ['assert f() == 1'])
    assert not missing.found and not missing.passed


def test_error_and_hidden_public():
    def broken(): raise ValueError('private-expected-83912')
    shown = run_asserts(broken, 'f', ['assert f() == 0'])
    assert shown.checks[0].status == 'error'
    assert shown.checks[0].error == 'ValueError: private-expected-83912'
    text = "assert f() == 'private-expected-83912'"
    hidden = run_asserts(lambda: 'actual', 'f', [dict(test=text, say='Secret case', hidden=True)])
    assert hidden.checks[0].status == 'fail'
    assert hidden.checks[0].error == 'AssertionError'
    page = public(hidden)
    payload = json.dumps(page)
    assert text not in payload and 'private-expected-83912' not in payload
    assert set(page) == {'v', 'found', 'timeout', 'checks'} and page['v'] == 1
    assert set(page['checks'][0]) == {'i', 'label', 'status', 'got', 'error', 'hidden', 'ms'}
    private_error = run_asserts(broken, 'f', [dict(test='assert f() == 0', hidden=True)])
    assert private_error.checks[0].error == 'ValueError'
    assert 'private-expected-83912' not in json.dumps(public(private_error))


def test_output_is_captured(capsys):
    def noisy():
        print('do not publish')
        print('do not publish', file=sys.stderr)
        return 1
    report = run_asserts(noisy, 'f', ['assert f() == 1'])
    assert report.passed
    out = capsys.readouterr()
    assert out.out == out.err == ''
    assert 'do not publish' not in json.dumps(public(report))


def test_single_call_and_clipping():
    calls = []
    def once():
        calls.append(1)
        return 'x' * 400
    report = run_asserts(once, 'f', ["assert f() == 'other'"])
    assert calls == [1]
    assert len(report.checks[0].got) <= 200
    def broken(): raise ValueError('x' * 400)
    assert len(run_asserts(broken, 'f', ['assert f() == 1']).checks[0].error) <= 200


def test_total_budget():
    calls = []
    def slow():
        calls.append(1)
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline: time.sleep(.005)
        return 1
    started = time.monotonic()
    report = run_asserts(slow, 'f', ['assert f() == 1'] * 12, secs=.08, total=.22)
    elapsed = time.monotonic() - started
    assert .15 <= elapsed < .8
    assert report.timeout and not report.passed
    assert all(c.status == 'timeout' for c in report.checks)
    assert len(calls) <= 3


def test_worker_timeout():
    result = []
    def bounded_loop():
        deadline, iterations = time.monotonic() + 1., 0
        while time.monotonic() < deadline:
            iterations += 1
    def work():
        started = time.monotonic()
        try:
            with time_limit(.2): bounded_loop()
        except TimeoutError: result.append(time.monotonic() - started)
    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(1.5)
    assert not worker.is_alive()
    assert len(result) == 1 and .1 <= result[0] < .8


def test_main_timeout_and_cleanup():
    with pytest.raises(TimeoutError):
        with time_limit(.02): time.sleep(1)   # not a busy `while` loop: on Python 3.13, the alarm error can skip the `with` there
    with time_limit(.5): pass   # room for a slow machine; the sleep shows that the timer is gone
    time.sleep(.6)


def test_worker_timer_cancelled():
    result = []
    def work():
        with time_limit(.5): pass
        time.sleep(.6)
        result.append('finished')
    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(2)
    assert not worker.is_alive() and result == ['finished']


def test_keyboard_interrupt_stops_run():
    calls = []
    def interrupted():
        calls.append(1)
        raise KeyboardInterrupt
    report = run_asserts(interrupted, 'f', ['assert f() == 1'] * 3)
    assert calls == [1]
    assert report.timeout and not report.passed
    assert [c.status for c in report.checks] == ['timeout'] * 3














def test_parse():
    for text in ('', 'not JSON', '[]', 'null', '{"other": 1}'):
        assert check.parse(text) == {'error': 'no check result'}
    result = {'v': 1, 'found': True, 'timeout': False, 'checks': []}
    assert check.parse('noise\n' + json.dumps(result) + '\nmore noise\n') == result
    assert check.parse(json.dumps(result) + '\n' + json.dumps(dict(result, found=False)))['found'] is False


def test_run_isolated():
    tests = ['assert f(3) == 6']
    result = check.run_isolated('assert', 'f', 'def f(n):\n print("noise")\n return n * 2', tests)
    assert result['found'] and result['checks'][0]['status'] == 'pass'
    result = check.run_isolated('assert', 'f', 'def f(n): return n', tests)
    assert result['checks'][0]['status'] == 'fail' and result['checks'][0]['got'] == '3'
    started = time.monotonic()
    assert check.run_isolated('assert', 'f', 'while True: pass', [], total=.1) == {'timeout': True}
    assert time.monotonic() - started < 8   # the short `total` stops it, not the 10 s default (a busy machine can add some seconds)


def test_hostile_code_does_not_pass_or_hang():
    tests = ['assert f(2) == 4']
    t = time.monotonic()
    assert check.run_isolated('assert', 'f', 'while True: pass\ndef f(n): return n * 2', tests, total=1.) == {'timeout': True}
    assert time.monotonic() - t < 4
    fake = 'import json, os\nprint(json.dumps({"v": 1, "found": True, "timeout": False, "checks": [{"status": "pass"}]}))\nos._exit(0)'
    assert check.run_isolated('assert', 'f', fake, tests).get('checks') in (None, [])
    net = 'import socket\ndef f(n):\n    socket.create_connection(("example.org", 80), 1)\n    return n * 2'
    r = check.run_isolated('assert', 'f', net, tests)
    assert r['checks'][0]['status'] == 'error'
    w = check.run_isolated('assert', 'f', 'open("/tmp/leela-check-should-not-exist", "w")\ndef f(n): return n * 2', tests)
    assert not os.path.exists('/tmp/leela-check-should-not-exist')
    assert (w.get('checks') or [{}])[0].get('status') != 'pass'


def test_future_import_stays_first():
    r = check.run_isolated('assert', 'f', 'from __future__ import annotations\ndef f(n: int) -> int: return n * 2', ['assert f(2) == 4'])
    assert r['checks'][0]['status'] == 'pass'


def test_code_on_the_line_of_a_future_import_is_refused():
    "Code after a `;` on the future line must not run before the guard. The runner refuses it."
    for head in ('from __future__ import annotations', '"doc"'):
        src = f'{head}; import socket; S = socket.socket()\ndef f(n): return "made-socket-before-guard"'
        r = check.run_isolated('assert', 'f', src, ['assert f(2) == 4'])
        assert 'checks' not in r and 'own line' in r['error'], r
    head, body = check._split_future('"doc"\nfrom __future__ import (\n    annotations)\nfrom __future__ import division\nx = 1\n')
    assert (head, body) == ('"doc"\nfrom __future__ import (\n    annotations)\nfrom __future__ import division', 'x = 1\n')


def test_a_signal_that_is_not_a_limit_is_no_result():
    stop = 'import os, signal\nos.kill(os.getpid(), signal.SIGTERM)\ndef f(n): return n * 2'
    assert check.run_isolated('assert', 'f', stop, ['assert f(2) == 4']) == {'error': 'no check result'}


@pytest.mark.skipif(not hasattr(os, 'killpg'), reason='process groups are POSIX only')
def test_a_child_process_that_keeps_the_output_open_does_not_hang(tmp_path):
    "The audit hook refuses new processes, so this runs without it. The time limit stops the whole process group."
    pidfile = tmp_path/'pid'
    src = f'import subprocess\np = subprocess.Popen(["sleep", "30"])\nopen({str(pidfile)!r}, "w").write(str(p.pid))\ndef f(n): return n * 2'
    t = time.monotonic()
    assert check.run_isolated('assert', 'f', src, ['assert f(2) == 4'], total=1., sandbox=False) == {'timeout': True}
    assert time.monotonic() - t < 5
    pid, end = int(pidfile.read_text()), time.monotonic() + 3
    while time.monotonic() < end:
        try: os.kill(pid, 0)
        except ProcessLookupError: break
        time.sleep(.05)
    else: pytest.fail(f'the child process {pid} still runs')


def test_public_hides_a_passing_hidden_tests_expected_value():
    def double(n): return n * 2
    page = json.dumps(public(run_asserts(double, 'double', [dict(test='assert double(-123) == -246', say='Negative', hidden=True)])))
    assert '-246' not in page and '-123' not in page


def test_system_exit_in_the_learners_function_is_an_error_not_an_escape():
    def quits(n): raise SystemExit(3)
    report = run_asserts(quits, 'quits', ['assert quits(1) == 1', dict(test='assert quits(2) == 2', hidden=True)])
    assert [c.status for c in report.checks] == ['error', 'error']
    assert report.checks[1].error == 'SystemExit'


@pytest.fixture
def target():
    "A spare process that hostile code tries to stop. It is not the test process, so a red test cannot stop pytest."
    t = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
    yield t
    t.kill(); t.wait()


@pytest.mark.parametrize('exe', ['real', 'missing'])
def test_hostile_code_cannot_signal_other_processes(target, exe, monkeypatch):
    "The audit hook refuses os.kill, os.killpg and signal.pthread_kill. With a missing sandbox-exec, the hook alone must do it."
    if exe == 'missing': monkeypatch.setattr(check, 'SANDBOX_EXEC', '/missing/sandbox-exec')
    for call in (f'os.kill({target.pid}, 9)', f'os.killpg({target.pid}, 9)', 'os.kill(os.getppid(), 0)',
                 'signal.pthread_kill(threading.main_thread().ident, 0)'):
        src = f'import os, signal, threading\ndef f(n):\n    {call}\n    return n * 2'
        r = check.run_isolated('assert', 'f', src, ['assert f(2) == 4'])
        assert r['checks'][0]['status'] == 'error' and 'PermissionError' in r['checks'][0]['error'], (call, r)
    time.sleep(.2)
    assert target.poll() is None


@pytest.mark.skipif(not os.path.exists(check.SANDBOX_EXEC), reason='macOS sandbox-exec only')
def test_the_profile_alone_refuses_a_signal_to_another_process(target):
    code = f'import os, signal\nsignal.signal(15, lambda *a: print("self"))\nos.kill(os.getpid(), 15)\nos.kill({target.pid}, 9)'
    p = subprocess.run([check.SANDBOX_EXEC, '-p', check.SANDBOX_PROFILE, '-D', 'TMP=/nonexistent', sys.executable, '-I', '-B', '-c', code],
                       capture_output=True, text=True, timeout=20)
    time.sleep(.2)
    assert 'self' in p.stdout and 'PermissionError' in p.stderr and target.poll() is None


FORGE = '''
import json, os, re
def _forge(text):
    "Send a false all-pass report with each nonce found in `text`, on stdout and on each open fd, then stop."
    for n in set(re.findall(r'[0-9a-f]{16}', text)) | {None}:
        line = json.dumps({"nonce": n, "v": 1, "found": True, "timeout": False,
                           "checks": [{"i": 0, "label": "x", "status": "pass", "got": None, "error": "", "hidden": False, "ms": 0}]})
        print(line, flush=True)
        for fd in range(1, 64):
            try: os.write(fd, ("\\n" + line + "\\n").encode())
            except OSError: pass
    os._exit(0)
'''
WRONG = '\ndef f(n): return n\n'


def no_pass(r): return not any(c.get('status') == 'pass' for c in r.get('checks') or [])


def test_a_patched_json_dumps_does_not_fake_a_pass():
    src = ('import json\n_d = json.dumps\n'
           'json.dumps = lambda o, **k: _d({**o, "checks": [{**c, "status": "pass"} for c in o["checks"]]} if isinstance(o, dict) and "checks" in o else o, **k)'
           + WRONG)
    r = check.run_isolated('assert', 'f', src, ['assert f(2) == 4'])
    assert r['checks'][0]['status'] == 'fail', r


def test_a_patched_print_does_not_fake_a_pass():
    src = 'import builtins\n_p = builtins.print\nbuiltins.print = lambda *a, **k: _p(*(str(x).replace(\'"fail"\', \'"pass"\') for x in a), **k)' + WRONG
    r = check.run_isolated('assert', 'f', src, ['assert f(2) == 4'])
    assert r['checks'][0]['status'] == 'fail', r


def test_the_nonce_is_not_in_the_code_constants():
    src = FORGE + '''
import sys
def _consts(c): return ''.join(repr(k) + (_consts(k) if hasattr(k, 'co_consts') else '') for k in c.co_consts)
text = ''
try: text += _consts(sys._getframe().f_code)
except Exception: pass
for v in list(globals().values()):
    try: text += _consts(v.__code__)
    except Exception: pass
_forge(text)
''' + WRONG
    assert no_pass(check.run_isolated('assert', 'f', src, ['assert f(2) == 4']))


@pytest.mark.parametrize('where', ['body', 'test'])
def test_a_frame_walk_does_not_find_the_nonce(where):
    "The code walks up the frames from the body and from a call in a test, and reads every local and constant that it finds."
    walk = '''
import sys, gc
def _walk(f):
    text = ''
    while f is not None:
        text += repr(f.f_code.co_consts) + repr(dict(f.f_locals)) + repr({k: v for k, v in f.f_globals.items() if k != "__builtins__"})
        f = f.f_back
    return text
def _all():
    text = ''
    try: text += _walk(sys._getframe())
    except Exception: pass
    try: 1 / 0
    except Exception as e:
        try: text += _walk(e.__traceback__.tb_frame)
        except Exception: pass
    def g(): yield
    try: text += _walk(g().gi_frame)
    except Exception: pass
    try: text += ''.join(map(repr, gc.get_objects()))
    except Exception: pass
    try: text += ''.join(_walk(f) for f in sys._current_frames().values())
    except Exception: pass
    _forge(text)
'''
    src = FORGE + walk + ('_all()\ndef f(n): return n\n' if where == 'body' else 'def f(n):\n    _all()\n    return n\n')
    assert no_pass(check.run_isolated('assert', 'f', src, ['assert f(2) == 4']))


def test_a_signal_handler_frame_does_not_find_the_nonce():
    "A signal handler gets the frame that runs. The code walks up from it in the body and in a test."
    src = FORGE + '''
import signal
def _h(sig, f):
    text = ''
    while f is not None:
        text += repr(f.f_code.co_consts) + repr(dict(f.f_locals))
        f = f.f_back
    _forge(text)
signal.signal(signal.SIGUSR1, _h)
def f(n):
    signal.raise_signal(signal.SIGUSR1)
    return n
'''
    assert no_pass(check.run_isolated('assert', 'f', src, ['assert f(2) == 4']))


def test_patched_runner_modules_do_not_fake_a_pass():
    "Patches to ast, contextlib and builtins in the body do not change how the runner reads and runs the tests."
    patches = ['import ast\n_o = ast.parse\nast.parse = lambda s, *a, **k: _o("assert True")',
               'import builtins\nbuiltins.exec = lambda *a, **k: None',
               'import builtins\n_c = builtins.compile\nbuiltins.compile = lambda s, *a, **k: _c("assert True" if isinstance(s, str) else s, *a, **k)',
               'import contextlib\ncontextlib._GeneratorContextManager.__exit__ = lambda *a: True\ncontextlib._RedirectStream.__exit__ = lambda *a: True']
    for p in patches:
        r = check.run_isolated('assert', 'f', p + '\ndef f(n):\n    while True: pass\n', ['assert f(2) == 4'], total=3.)
        assert no_pass(r), (p, r)


def test_home_is_the_work_folder():
    "Leela's tests rely on this: in the closed process, HOME and `~` are the temporary work folder."
    src = 'import os\ndef f():\n    return os.environ.get("HOME") == os.getcwd() == os.path.expanduser("~")'
    for sandbox in (True, False):
        r = check.run_isolated('assert', 'f', src, ['assert f() == True'], sandbox=sandbox)
        assert r.get('checks') and r['checks'][0]['status'] == 'pass', (sandbox, r)


def _peak_mb():
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / 2**20 if sys.platform == 'darwin' else peak / 2**10   # bytes on macOS, KB on Linux


@pytest.mark.parametrize('src', ['while True: print("x" * 10000)\ndef f(n): return n * 2',
                                 'import sys\ndef f(n):\n    while True: print("x" * 10000, file=sys.__stderr__)\n    return n * 2'])
def test_loud_output_keeps_parent_memory_small(src):
    "A learner function that prints a lot until the time limit: the parent keeps only a little of it, and the check does not pass."
    start = _peak_mb()
    r = check.run_isolated('assert', 'f', src, ['assert f(2) == 4'], total=2.)
    assert _peak_mb() - start < 200
    assert r.get('timeout') or r.get('error') or all(c['status'] != 'pass' for c in r['checks']), r


def test_drain_keeps_a_capped_part():
    "The reader keeps at most `cap` bytes of a pipe, reads it to its end, and notes that there was more."
    r, w = os.pipe()
    got = check._drain(r, 1000)
    os.write(w, b'a' * 5000); os.close(w)
    got.thread.join(2)
    assert bytes(got.data) == b'a' * 1000 and got.over
    os.close(r)
    r, w = os.pipe()
    got = check._drain(r, 1000)
    os.write(w, b'ok'); os.close(w)
    got.thread.join(2)
    assert bytes(got.data) == b'ok' and not got.over
    os.close(r)


def test_feed_takes_a_closed_file():
    "Writing the code to a child that already closed its input does not raise in the parent."
    r, w = os.pipe(); os.close(r)
    f = os.fdopen(w, 'wb'); f.close()
    check._feed(f, b'print(1)')



def test_only_the_assert_kind_runs():
    with pytest.raises(ValueError, match="kind must be 'assert'"): check.run_isolated('cell', 'f', 'def f(): pass', [])


def test_the_limits_are_abhyasa_0015_defaults():
    assert (check.TEST_SECONDS, check.RUN_SECONDS, check.FILE_MB) == (2., 10., 10)
