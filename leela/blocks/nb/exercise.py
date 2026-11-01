import asyncio, json
from . import check
from .check import SAFE_NAMES, safe_test, validate_exercise
from ...core.web import off_loop
from ..learn import tools
from ..learn.tools import library_check, tool_dir, tool_names
from .nb import Cell, fresh_exercise_state, run_watched, src_hash

def validate_exercise_spec(spec):
    if not isinstance(spec, dict): validate_exercise(spec)
    rows = spec.get('tests')
    tests = [t.get('test') if isinstance(t, dict) else None for t in rows] if isinstance(rows, list) else rows
    clean = validate_exercise({k: spec.get(k) for k in ('task', 'fname', 'stub')} | {'tests': tests})
    rows = [{k: t.get(k) for k in ('say', 'test', 'shown')} for t in rows]
    for t in rows:
        say = t['say']
        if not (isinstance(say, str) and say.strip() and len(say) <= 200 and say.isprintable()):
            raise ValueError('`say` must be a short plain string (1 to 200 characters)')
        if type(t['shown']) is not bool: raise ValueError('`shown` must be a bool')
    uses = spec.get('uses', [])
    if not isinstance(uses, list) or any(not isinstance(u, str) for u in uses):
        raise ValueError('`uses` must be a list of strings')
    if (env := spec.get('env')) is not None:
        try: tool_dir(env)
        except ValueError: raise ValueError('`env` must be the 16 character key of a tool environment') from None
    if (req := spec.get('requires')) is not None:
        try: req = tool_names(req)
        except ValueError as e: raise ValueError(f'`requires` must list 1 to 5 package names ({e})') from None
    return ({k: clean[k] for k in ('task', 'fname', 'stub')} | dict(tests=rows, uses=list(uses)) | ({} if env is None else dict(env=env))
            | ({} if req is None else dict(requires=req)))

def exercise_cells(spec):
    spec = validate_exercise_spec(spec)
    code = Cell(source=spec['stub'], extra={'exercise': dict(v=1, fname=spec['fname'], uses=spec['uses'], tests=spec['tests'],
        state=fresh_exercise_state(), **{k: spec[k] for k in ('env', 'requires') if k in spec})})
    lines = [t['test'] if t['shown'] else t['say'] for t in spec['tests']]
    task = Cell(source=spec['task'] + '\n\n' + '\n\n'.join(lines), cell_type='markdown',
        extra={'exercise': {'role': 'task', 'for': code.id}})
    return [task, code]

HARNESS = r'''import ast, builtins, contextlib, io, json, signal, threading, time
try:
    fname, tests, names, budget = json.loads(PAYLOAD)
    deadline, stopped = time.monotonic() + budget, False
    safe = {n: getattr(builtins, n) for n in names if hasattr(builtins, n)}
    fn = __leela_exercise_ns.get(fname)
    result = {'found': callable(fn), 'checks': []}
    def boom(*_): raise TimeoutError()
    for i, t in enumerate(tests if result['found'] else []):
        row = dict(i=i, status='pass', got=None, error=None)
        remaining = deadline - time.monotonic()
        if stopped or remaining <= 0:
            result['checks'].append(dict(i=i, status='timeout', got=None, error='TimeoutError'))
            continue
        scope = {'__builtins__': safe, fname: fn}
        timed = threading.current_thread() is threading.main_thread()
        if timed:
            old = signal.signal(signal.SIGALRM, boom)
            signal.setitimer(signal.ITIMER_REAL, min(2., remaining))
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                tree = ast.parse(t)
                expr = tree.body[0].test
                capture = (isinstance(expr, ast.Compare) and len(expr.ops) == 1
                    and isinstance(expr.ops[0], ast.Eq) and isinstance(expr.left, ast.Call))
                if capture:
                    expr.left = ast.NamedExpr(target=ast.Name(id='__leela_exercise_got', ctx=ast.Store()), value=expr.left)
                    ast.fix_missing_locations(tree)
                try: exec(compile(tree, '<exercise>', 'exec'), scope)
                except AssertionError:
                    row['status'] = 'fail'
                    if capture and '__leela_exercise_got' in scope: row['got'] = repr(scope['__leela_exercise_got'])[:200]
        except KeyboardInterrupt:
            stopped = True
            row.update(status='timeout', got=None, error='TimeoutError')
        except TimeoutError: row.update(status='timeout', got=None, error='TimeoutError')
        except BaseException as e: row.update(status='error', got=None, error=type(e).__name__)
        finally:
            if timed:
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, old)
        result['checks'].append(row)
    print(json.dumps(result))
finally: globals().clear()
'''

def _as_checked(r):
    "`r` with `timeout` for a stopped run only, and no checks when the function is missing. A test that timed out keeps its `timeout` status on its row."
    return r if 'checks' not in r else {**r, 'timeout': False} | ({} if r['found'] else dict(checks=[]))

def check_solution(spec, solution, timeout=10):
    "`run_isolated` reports for `solution` and the stub, each in a closed process of `timeout` seconds; with `env`, `library_check` in that tool environment."
    spec = validate_exercise_spec(spec)
    if not isinstance(solution, str): raise ValueError('`solution` must be Python source text')
    tests = [t['test'] for t in spec['tests']]
    run = ((lambda src: library_check(spec, src, spec['env'])) if 'env' in spec else
           lambda src: _as_checked(check.run_isolated('assert', spec['fname'], src, tests, total=timeout, sandbox=True)))
    return {k: run(src) for k, src in (('solution', solution), ('stub', spec['stub']))}

async def run_checks(k, fname, tests, timeout=10):
    if not isinstance(fname, str) or not fname.isidentifier() or fname.startswith('_'):
        raise ValueError('`fname` must be a plain function name')
    if not isinstance(tests, list) or not tests or any(not isinstance(t, str) or not safe_test(t, fname) for t in tests):
        raise ValueError('`tests` must contain plain asserts on the function')
    payload = json.dumps([fname, tests, list(SAFE_NAMES), timeout])
    body = HARNESS.replace('PAYLOAD', repr(payload))
    snippet = f"exec({body!r}, {{'__builtins__': __builtins__, '__leela_exercise_ns': globals()}})"
    try: r = await asyncio.wait_for(k.execute(snippet, silent=True, store_history=False), timeout + 1)
    except asyncio.TimeoutError: return {'timeout': True}
    text = ''.join(o.get('text', '') for o in r.outputs if o.get('output_type') == 'stream')
    try: return json.loads(text.strip().splitlines()[-1])
    except (IndexError, ValueError): return {'error': 'the kernel sent no check result'}

#: Seconds the checks of one press of Check share.
BUDGET = 10
#: What the page and the agent both say, so a learner and the tutor read the same words.
JUDGE = {
    'pass': 'Passes.', 'fail': 'Does not match yet.', 'error': 'Raised an error.', 'timeout': 'Took too long.',
    'missing': 'No function named {fname} is defined yet. Run the cell that defines it.',
    'raised': 'The cell raised an error, so no check ran.', 'stuck': 'The checks ran out of time.',
    'broken': 'The checks could not run.', 'done': '{passed} of {total} checks pass.',
    'not_exercise': 'That cell is not an exercise.', 'stale': 'This page is out of date with the notebook. Reload it.',
    'busy': 'Another run is in progress. Try again when it finishes.',
    'no_env': 'This lesson needs its tool environment. Make it again from the lesson.',
    'rebuilding': 'Leela is making the tool environment for this lesson again.',
    'unchecked': 'Call check_exercise first: this code has not been checked since it last changed.'}

class Refused(ValueError): pass

def exercise_meta(c):
    "The `extra.exercise` of an exercise code cell, else None."
    ex = c.extra.get('exercise')
    return ex if c.cell_type == 'code' and isinstance(ex, dict) and 'tests' in ex else None

def _verdict(meta, c, res, raised):
    rows, tests = res.get('checks', []), meta['tests']
    state = ('raised' if raised else 'stuck' if res.get('timeout') else 'broken' if res.get('error')
             else 'missing' if not res.get('found') else 'done')
    checks = []
    for t, r in zip(tests, rows):
        status, got = r['status'], r.get('got')
        msg = JUDGE[status]
        if status == 'fail' and t['shown'] and got is not None: msg += f' It returned {got}.'
        checks.append(dict(i=r['i'], say=t['say'], shown=t['shown'], test=t['test'], status=status, got=got, error=r.get('error'), message=msg))
    passed = sum(r['status'] == 'pass' for r in checks)
    return dict(id=c.id, source=c.source, state=state, passed=passed, total=len(tests), checks=checks,
                summary=JUDGE[state].format(fname=meta['fname'], passed=passed, total=len(tests)))

def _rebuild(meta, nb, jobs):
    "The refusal for a missing tool environment: with `requires` and `jobs`, a `tool_env` job makes it again and `meta` names its key."
    try: names = tool_names(meta.get('requires'))
    except ValueError: names = None
    if not names or jobs is None: return Refused(JUDGE['no_env'])
    if not tools.shutil.which('uv'): return Refused(tools.NO_UV)
    if (key := tools.tool_key(names)) != meta['env']: meta['env'], nb.dirty = key, True
    tools.start_tool_job(jobs, names)
    return Refused(JUDGE['rebuilding'])

async def check_cell(nb, c, lock, runtime, jobs=None):
    "Check the learner's exercise cell: with `env`, its source in `library_check`; else the cell, then its checks, in the live kernel. `Refused` for no exercise, a held `lock` or a missing tool environment, which `jobs` makes again from `requires`."
    if not (meta := exercise_meta(c)): raise Refused(JUDGE['not_exercise'])
    if lock.locked(): raise Refused(JUDGE['busy'])
    async with lock:
        h = src_hash(c.source)
        if key := meta.get('env'):
            try: res, raised = await off_loop(library_check, meta, c.source, key), False
            except ValueError:
                meta.setdefault('state', fresh_exercise_state()).update(passed=False, last=None)
                nb.dirty = True
                raise _rebuild(meta, nb, jobs) from None
        else:
            k = await runtime()
            h = src_hash(c.source)
            c, _ = await run_watched(nb, c, k)
            raised = c.has_error
            res = {} if raised else await run_checks(k, meta['fname'], [t['test'] for t in meta['tests']], BUDGET)
    v = _verdict(meta, c, res, raised)
    if src_hash(c.source) == h:
        done = v['state'] == 'done' and v['passed'] == v['total']
        s = meta.setdefault('state', fresh_exercise_state())
        s.update(checks=s.get('checks', 0) + 1, passed=done, last=dict(hash=h, state=v['state'], passed=v['passed'], total=v['total']))
        nb.dirty = True
    return v

def grade_cell(nb, c, lock, score, note):
    "Store the agent's 0-10 grade on the source `check_cell` last ran; `Refused` for a bad grade, changed code or a held `lock`."
    if not (meta := exercise_meta(c)): raise Refused(JUDGE['not_exercise'])
    if lock.locked(): raise Refused(JUDGE['busy'])
    if type(score) is not int or not 0 <= score <= 10: raise Refused('`score` must be a whole number from 0 to 10.')
    note = note.strip() if isinstance(note, str) else ''
    if not (note and len(note) <= 200 and note.isprintable()): raise Refused('`note` must be one plain line of 1 to 200 characters.')
    squash = lambda s: ''.join(s.split())
    if any(squash(t['test']) in squash(note) for t in meta['tests'] if not t['shown']): raise Refused('`note` must not quote a hidden test.')
    h = src_hash(c.source)
    if (meta.get('state', {}).get('last') or {}).get('hash') != h: raise Refused(JUDGE['unchecked'])
    meta['state']['grade'] = dict(score=score, note=note, hash=h)
    nb.dirty = True
    return meta['state']

def public_verdict(v):
    "What the page may see of `check_cell`: a hidden check keeps its label and status, never its test or what it returned."
    checks = [dict(i=r['i'], say=r['say'], status=r['status'], message=r['message'], **({'got': r['got']} if r['shown'] and r['got'] is not None else {}))
              for r in v['checks']]
    return dict(ok=True, state=v['state'], summary=v['summary'], passed=v['passed'], total=v['total'], checks=checks)
