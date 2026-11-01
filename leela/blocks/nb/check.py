"Run a learner's function and its assert tests in a closed process: abhyasa 0.0.15 `abhyasa/check.py` (abhyasa commit 004ebee^), which abhyasa removed."
__all__ = ['SAFE_BUILTINS', 'TEST_SECONDS', 'RUN_SECONDS', 'FILE_MB', 'SANDBOX_EXEC', 'SANDBOX_PROFILE', 'OUTPUT_KEEP', 'RESULT_MAX',
           'validate_exercise', 'time_limit', 'Report', 'public', 'run_asserts', 'parse', 'run_isolated', 'SAFE_NAMES', 'SAFE_NODES', 'safe_test']
import ast, builtins, ctypes, inspect, io, json, os, re, signal, subprocess, sys, threading, time
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from fastcore.basics import AttrDict, adict, stop
from abhyasa.contract import SAFE_NAMES, SAFE_NODES, safe_test, check_exercise
SAFE_BUILTINS = {n: getattr(builtins, n) for n in SAFE_NAMES if hasattr(builtins, n)}
TEST_SECONDS, RUN_SECONDS, FILE_MB = 2., 10., 10   # abhyasa 0.0.15's `runner.per_test`, `runner.total` and `runner.file_mb` defaults

def validate_exercise(r) -> AttrDict:
    "Check the model's exercise and raise `ValueError` with the reason if invalid (`contract.check_exercise`)."
    return AttrDict(check_exercise(r))

@contextmanager
def time_limit(secs:float=TEST_SECONDS):
    "Raise `TimeoutError` after `secs`; worker threads cannot interrupt blocked C calls."
    if secs <= 0: raise TimeoutError('the test has no time left')
    if threading.current_thread() is threading.main_thread():
        def boom(*_): raise TimeoutError(f'the test ran longer than {secs:g} s')
        old = signal.signal(signal.SIGALRM, boom)
        try:
            signal.setitimer(signal.ITIMER_REAL, secs)
            yield
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old)
        return
    ident, lock, active = threading.get_ident(), threading.Lock(), True
    def expire():
        with lock:
            if not active: return
            changed = ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(ident), ctypes.py_object(TimeoutError))
            if changed > 1:
                ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(ident), ctypes.c_void_p())
    timer = threading.Timer(secs, expire)
    timer.daemon = True
    try:
        timer.start()
        yield
    finally:
        with lock:
            active = False
            timer.cancel()
        timer.join()

class Report(AttrDict):
    "Results for one learner function."
    @property
    def passed(self):
        return self.found and bool(self.checks) and all(c.status == 'pass' for c in self.checks)

def public(report) -> dict:
    "Return page-safe results without test source or expected values."
    checks = []
    for c in report.checks:
        error = c.error.split(':', 1)[0] if c.hidden else c.error
        got = None if c.hidden and c.status == 'pass' else c.got   # a hidden test that passes returned its expected value
        checks.append(dict(i=c.i, label=c.label, status=c.status, got=got, error=error, hidden=c.hidden, ms=c.ms))
    return dict(v=1, found=report.found, timeout=report.timeout, checks=checks)

def run_asserts(fn, fname, tests, *, secs=TEST_SECONDS, total=RUN_SECONDS) -> Report:
    "Run tests with per-test and total time limits, capturing output and actual values."
    report = Report(found=callable(fn), timeout=False, checks=[])
    deadline, stopped = time.monotonic() + total, False
    for i, spec in enumerate(tests):
        t = spec if isinstance(spec, str) else spec['test']
        hidden = False if isinstance(spec, str) else spec.get('hidden', False)
        label = '' if isinstance(spec, str) else spec.get('say', '')
        check = AttrDict(i=i, label=label or f'Test {i + 1}', status='pass', got=None, error='', hidden=hidden, ms=0.)
        started = time.monotonic()
        remaining = deadline - started
        if stopped or remaining <= 0:
            check.status, check.error = 'timeout', 'TimeoutError' if hidden else 'TimeoutError: the run stopped or spent its budget'
        else:
            env = {'__builtins__': SAFE_BUILTINS, fname: fn}
            try:
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), time_limit(min(secs, remaining)):
                    if not safe_test(t, fname): raise ValueError('the test is not one safe assert')
                    tree = ast.parse(t)
                    condition = tree.body[0].test
                    capture = (isinstance(condition, ast.Compare) and len(condition.ops) == 1
                               and isinstance(condition.ops[0], ast.Eq) and isinstance(condition.left, ast.Call))
                    if capture:
                        condition.left = ast.NamedExpr(target=ast.Name(id='_abhyasa_actual', ctx=ast.Store()), value=condition.left)
                        ast.fix_missing_locations(tree)
                    try: exec(compile(tree, '<learner test>', 'exec'), env)
                    except (TimeoutError, KeyboardInterrupt): raise
                    except (Exception, SystemExit) as e:
                        check.status = 'fail' if isinstance(e, AssertionError) else 'error'
                        check.error = type(e).__name__ if hidden else f'{type(e).__name__}: {e}'[:200]
                    if capture and '_abhyasa_actual' in env: check.got = repr(env['_abhyasa_actual'])[:200]
            except KeyboardInterrupt:
                stopped = True
                check.status, check.error = 'timeout', 'KeyboardInterrupt' if hidden else 'KeyboardInterrupt: the run stopped'
            except TimeoutError:
                check.status, check.error = 'timeout', 'TimeoutError' if hidden else 'TimeoutError: the test ran out of time'
            except (Exception, SystemExit) as e:
                check.status = 'error'
                check.error = type(e).__name__ if hidden else f'{type(e).__name__}: {e}'[:200]
        check.ms = (time.monotonic() - started) * 1000
        report.timeout |= check.status == 'timeout'
        report.checks.append(check)
    return report

def _runner(kind, fname, tests, *, secs=None, total=None, setup=(), nonce:str=None) -> tuple:
    "The source that defines the runner and its test data, and the line that runs the checks and sets `result`."
    secs, total = float(secs or TEST_SECONDS), float(total or RUN_SECONDS)
    if kind != 'assert': raise ValueError("kind must be 'assert'")
    dependencies = [stop, adict, AttrDict, time_limit, public]
    runners = [safe_test, run_asserts]
    data = json.dumps(dict(fname=fname, tests=tests, secs=secs, total=total, setup=list(setup), safe_names=SAFE_NAMES, nonce=nonce))
    parts = [
        'import ast, builtins, ctypes, io, json, signal, threading, time',
        'from contextlib import contextmanager, redirect_stdout, redirect_stderr',
        f'data = json.loads({data!r})',
        'SAFE_NAMES = tuple(data["safe_names"])',
        'SAFE_BUILTINS = {n: getattr(builtins, n) for n in SAFE_NAMES if hasattr(builtins, n)}',
        'SAFE_NODES = (' + ', '.join(f'ast.{node.__name__}' for node in SAFE_NODES) + ',)',
        f'TEST_SECONDS = {secs!r}', f'RUN_SECONDS = {total!r}',
        *(inspect.getsource(obj) for obj in dependencies),
        'class Report(AttrDict):\n' + inspect.getsource(Report.passed.fget),
        *(inspect.getsource(obj) for obj in runners),
    ]
    return '\n'.join(parts), 'result = run_asserts(_ns.get(data["fname"]), data["fname"], data["tests"], secs=data["secs"], total=data["total"])'

def parse(text, nonce:str=None) -> dict:
    "Read the last public check JSON line, or return a missing-result error. With `nonce`, only a line with that nonce counts."
    for line in reversed(text.splitlines()):
        try: result = json.loads(line)
        except (ValueError, TypeError): continue
        if nonce is not None and not (isinstance(result, dict) and result.get('nonce') == nonce): continue
        if (isinstance(result, dict) and result.get('v') == 1
            and isinstance(result.get('found'), bool) and isinstance(result.get('timeout'), bool)
            and isinstance(result.get('checks'), list)): return {k: v for k, v in result.items() if k != 'nonce'}
        return {'error': 'no check result'}
    return {'error': 'no check result'}

def _guard(tmp, unix=False):
    "Add an audit hook that refuses the network, ctypes libraries, new processes, signals to other processes, frame and object walks (`logging` does not walk frames), and file changes outside the folder `tmp`; with `unix`, allow a local socket pair."
    import os, sys, socket, ctypes
    import logging
    logging._srcfile = None   # `logging` then skips its frame walk, which the hook refuses
    writes = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
    walks = ('sys._getframe', 'sys._current_frames', 'sys.settrace', 'sys.setprofile', 'gc.get_objects', 'gc.get_referrers', 'gc.get_referents')
    def outside(p): return isinstance(p, (str, bytes, os.PathLike)) and not os.path.realpath(os.fsdecode(p)).startswith(tmp + os.sep)
    def hook(event, args):
        if event.startswith(('ctypes.dlopen', 'ctypes.dlsym')) or event in ('os.kill', 'os.killpg', 'signal.pthread_kill', *walks):
            raise PermissionError(f'{event} is not allowed')
        if event == 'object.__getattr__' and args[1] in ('tb_frame', 'gi_frame', 'cr_frame', 'ag_frame'):
            raise PermissionError(f'{args[1]} is not allowed')
        if unix and event == 'socket.__new__' and args[1] == socket.AF_UNIX: return
        if event.startswith(('socket.', 'os.exec', 'os.posix_spawn', 'os.fork')) or event in ('subprocess.Popen', 'os.system'):
            raise PermissionError(f'{event} is not allowed')
        if event == 'open' and ((isinstance(args[1], str) and any(m in args[1] for m in 'wax+')) or args[2] & writes) and outside(args[0]):
            raise PermissionError(f'writing to {args[0]} is not allowed')
        if event in ('os.remove', 'os.rename', 'os.rmdir', 'os.mkdir', 'os.truncate', 'os.symlink', 'os.link', 'shutil.rmtree') and any(map(outside, args)):
            raise PermissionError(f'{event} outside the work folder is not allowed')
    ctypes.pythonapi.PyThreadState_SetAsyncExc   # the timer needs this symbol: look it up now, before the hook
    sys.addaudithook(hook)

SANDBOX_EXEC = '/usr/bin/sandbox-exec'
SANDBOX_PROFILE = """(version 1)
(allow default)
(deny network*)
(deny process-fork)
(deny signal)
(allow signal (target self))
(deny file-write*)
(allow file-write* (subpath (param "TMP")) (literal "/dev/null"))"""

def _limits(total) -> str:
    "Code that limits the process to `total + 1` s of CPU time and to files of `FILE_MB` MB, when the system has the `resource` module."
    cpu, big = int(total) + 1, FILE_MB * 2**20
    return (f'try:\n    import resource\n    resource.setrlimit(resource.RLIMIT_CPU, ({cpu}, {cpu + 1}))\n'
            f'    resource.setrlimit(resource.RLIMIT_FSIZE, ({big}, {big}))\n    del resource\nexcept ImportError: pass\n')

def _split_future(source) -> tuple:
    "The docstring and the `from __future__` imports at the start of `source`, and the code after them. Refuse code on the same line as one of them."
    try: tree = ast.parse(source)
    except (SyntaxError, ValueError): return '', source
    k = 0
    for i, s in enumerate(tree.body):
        if not ((isinstance(s, ast.ImportFrom) and s.module == '__future__') or
                (i == 0 and isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str))): break
        k = i + 1
    if not k: return '', source
    if k < len(tree.body) and tree.body[k].lineno <= tree.body[k - 1].end_lineno:
        raise ValueError('Put the docstring and each `from __future__` import on its own line.')
    lines = re.findall(r'.*?(?:\r\n|\r|\n)|.+\Z', source, re.S)   # the same line breaks as `ast`
    return '\n'.join(ast.get_source_segment(source, s) for s in tree.body[:k]), ''.join(lines[tree.body[k - 1].end_lineno:])

def _start(defs, call, nonce_fd, out_fd, guard=None):
    "Before the learner code runs: keep the real functions, private copies of `ast` and `contextlib`, and the nonce in a worker thread, call `guard`, and return the locks that start the checks and show their end."
    import _thread, builtins, importlib.util, json, os, types
    real = dict(vars(builtins))   # the runner uses these, also when the learner code changes `builtins`
    def fresh(name):
        spec = importlib.util.find_spec(name)
        m = importlib.util.module_from_spec(spec)
        m.__builtins__ = real
        spec.loader.exec_module(m)
        return m
    mods = dict(ast=fresh('ast'), contextlib=fresh('contextlib'), builtins=types.ModuleType('builtins'))
    vars(mods['builtins']).update(real)
    imp = real['__import__']
    real['__import__'] = lambda name, *a, **k: mods.get(name) or imp(name, *a, **k)
    dumps, write, close, run = json.dumps, os.write, os.close, builtins.exec
    nonce = os.read(nonce_fd, 64).decode()
    close(nonce_fd)
    space = {'__builtins__': real, '_ns': globals()}
    run(defs, space)
    go, done = _thread.allocate_lock(), _thread.allocate_lock()
    go.acquire(); done.acquire()
    def work():
        try:
            go.acquire()
            run(call, space)
            write(out_fd, ('\n' + dumps({'nonce': nonce, **space['public'](space['result'])}) + '\n').encode())
        except BaseException: pass
        finally: done.release()
    if guard: guard()
    _thread.start_new_thread(work, ())
    return go, done

OUTPUT_KEEP, RESULT_MAX = 64 * 2**10, 2**20   # bytes of stdout and of stderr that the parent keeps; the largest report it reads

def _drain(fd, cap) -> AttrDict:
    "Start a thread that reads `fd` to its end in chunks, keeps at most `cap` bytes in `data`, and sets `over` when there was more."
    got = AttrDict(data=bytearray(), over=False)
    def read():
        try:
            for b in iter(lambda: os.read(fd, 1 << 16), b''):
                room = cap - len(got.data)
                if len(b) > room: got.over = True
                if room > 0: got.data += b[:room]
        except OSError: pass
    got.thread = threading.Thread(target=read, daemon=True)
    got.thread.start()
    return got

def _feed(f, data):
    "Write `data` to the file `f` and close it. A process that stopped early does not stop the parent."
    try: f.write(data); f.close()
    except (OSError, ValueError): pass   # a closed pipe, or a file that is closed already

_GO = 'try: _go[0].release()\nexcept RuntimeError: pass\n_go[1].acquire()\n'   # the last lines: start the checks and wait for them

def run_isolated(kind, fname, source, tests, *, total=None, setup=(), sandbox=True, python=None, unix=False) -> dict:
    "Run `source` and its checks in a closed process with no network, using `python` (default `sys.executable`); with `unix`, it can use a local socket pair. `total` defaults to `RUN_SECONDS`, and each test gets `TEST_SECONDS`."
    import tempfile
    try: head, body = _split_future(source)
    except ValueError as e: return {'error': str(e)}
    nonce, total = os.urandom(8).hex(), float(total or RUN_SECONDS)
    defs, call = _runner(kind, fname, tests, secs=TEST_SECONDS, total=total, setup=setup)
    with tempfile.TemporaryDirectory() as tmp:
        tmp, cmd = os.path.realpath(tmp), [python or sys.executable, '-I', '-B']
        if sandbox and sys.platform == 'darwin' and os.path.exists(SANDBOX_EXEC): cmd = [SANDBOX_EXEC, '-p', SANDBOX_PROFILE, '-D', f'TMP={tmp}', *cmd]
        nr, nw = os.pipe()   # the nonce goes in on one pipe and the report comes out on the other, never on stdout
        rr, rw = os.pipe()
        os.write(nw, nonce.encode()); os.close(nw)
        guard = f'lambda: _guard({tmp!r}, {unix!r})' if sandbox else 'None'
        pre = (_limits(total) + inspect.getsource(_guard) + inspect.getsource(_start)
               + f'_go = _start({defs!r}, {call!r}, {nr}, {rw}, {guard})\ndel _start, _guard\n')
        code = f'{head}\n{pre}{body}\n{_GO}'
        res = _drain(rr, RESULT_MAX)
        try:
            try: p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=tmp,
                                      env={'PATH': os.defpath, 'HOME': tmp}, start_new_session=True, pass_fds=(nr, rw))
            finally: os.close(nr); os.close(rw)
            outs = [_drain(f.fileno(), OUTPUT_KEEP) for f in (p.stdout, p.stderr)]
            threading.Thread(target=_feed, args=(p.stdin, code.encode()), daemon=True).start()
            with p:
                end = time.monotonic() + total + 2
                try:   # wait for the end of the output, as `communicate` does, and then for the process
                    for o in outs: o.thread.join(max(end - time.monotonic(), 0))
                    if any(o.thread.is_alive() for o in outs): raise subprocess.TimeoutExpired(cmd, total + 2)
                    p.wait(timeout=max(end - time.monotonic(), 0))
                except subprocess.TimeoutExpired:   # stop the whole group: a process that the code started can keep the output open
                    try: os.killpg(p.pid, signal.SIGKILL)
                    except (AttributeError, ProcessLookupError): p.kill()
                    p.wait()
                    return {'timeout': True}
                finally:
                    for o in outs: o.thread.join(1)
        except OSError: return {'error': 'no check result'}   # `python` cannot start
        finally:
            res.thread.join(1)
            if not res.thread.is_alive(): os.close(rr)
    if -p.returncode in (getattr(signal, 'SIGXCPU', None), getattr(signal, 'SIGKILL', None)): return {'timeout': True}
    if p.returncode < 0: return {'error': 'no check result'}
    return {'error': 'check result too large'} if res.over else parse(res.data.decode('utf-8', 'replace'), nonce)
