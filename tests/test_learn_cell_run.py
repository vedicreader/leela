"POST /learn/cell/run: one private kernel for the Learn tab, state shared inside a step, a time limit, caps, and the guard."
import ast, contextlib, io, json
import pytest
from starlette.testclient import TestClient

from leela.app import ide_app
from leela.blocks.learn import cellrun
from leela.blocks.runtime.kernels import ExecOutcome, KernelPool
from leela.hub import LoopbackHostGuard

BASE = 'http://127.0.0.1:5001'
OWN = {'Origin': BASE, 'Sec-Fetch-Site': 'same-origin'}


class ExecKernel:
    "A kernel that runs the code in this process, with the parts of the `Kernel` API that the route uses."
    alive = True
    def __init__(self): self.ns, self.restarts, self.interrupts, self.codes = {}, 0, 0, []
    async def execute(self, code, silent=False, store_history=True, on_output=None, timeout=None, **kw):
        self.codes.append(code)
        if 'while True' in code: return ExecOutcome(ok=False, error=f'timed out after {timeout}s')
        buf, outs = io.StringIO(), []
        try:
            tree = ast.parse(code)
            last = tree.body.pop() if tree.body and isinstance(tree.body[-1], ast.Expr) else None
            with contextlib.redirect_stdout(buf):
                exec(compile(tree, '<cell>', 'exec'), self.ns)
                val = eval(compile(ast.Expression(last.value), '<cell>', 'eval'), self.ns) if last else None
        except Exception as e:
            if buf.getvalue(): outs.append(dict(output_type='stream', name='stdout', text=buf.getvalue()))
            outs.append(dict(output_type='error', ename=type(e).__name__, evalue=str(e), traceback=['\x1b[31m---\x1b[0m', 'Cell In[1], line 1', f'{type(e).__name__}: {e}']))
            return ExecOutcome(ok=False, outputs=outs, error=f'{type(e).__name__}: {e}')
        if buf.getvalue(): outs.append(dict(output_type='stream', name='stdout', text=buf.getvalue()))
        if val is not None: outs.append(dict(output_type='execute_result', data={'text/plain': repr(val)}, metadata={}))
        return ExecOutcome(ok=True, outputs=outs)
    async def interrupt(self): self.interrupts += 1
    async def restart(self): self.ns, self.restarts = {}, self.restarts + 1


@pytest.fixture
def cell(ws, monkeypatch):
    k = ExecKernel()
    async def _get(self, key, **kw): assert key == cellrun.KEY; return k
    monkeypatch.setattr(KernelPool, 'get', _get)
    app = ide_app(ws)
    cl = TestClient(app, base_url=BASE)
    yield type('C', (), dict(k=k, cl=cl, app=app, run=lambda self, code, step='0', **kw: cl.post('/learn/cell/run', json=dict(code=code, id='c', walk='w', step=step, **kw), headers=OWN).json()))()
    cl.close()


def test_a_run_gives_output_the_last_value_and_the_watched_names(cell):
    r = cell.run("x = 3\nprint('hi')\nx * 2", watch=['x', 'nope', 'not a name'])
    assert r['ok'] and r['stdout'] == 'hi\n' and r['result'] == '6' and r['watch'] == {'x': '3'} and r['id'] == 'c' and r['error'] is None and not r['timed_out']
    assert not any('not a name' in c for c in cell.k.codes)


def test_cells_of_one_step_share_variables_and_a_new_step_starts_afresh(cell):
    cell.run('x = 3'); assert cell.run('x + 1')['result'] == '4'
    assert cell.k.restarts == 0
    r = cell.run('x', step='1')
    assert not r['ok'] and r['error']['name'] == 'NameError' and cell.k.restarts == 1
    assert cell.run('y = 5', step='1')['ok'] and cell.run('y', step='1')['result'] == '5' and cell.k.restarts == 1


def test_reset_starts_the_kernel_afresh(cell):
    cell.run('x = 3'); r = cell.run('', reset=True)
    assert r['ok'] and cell.k.restarts == 1 and not cell.run('x')['ok']


def test_an_error_gives_a_short_traceback_with_no_colour_codes(cell):
    r = cell.run('1 / 0')
    assert not r['ok'] and r['error']['name'] == 'ZeroDivisionError' and 'division' in r['error']['msg']
    assert len(r['error']['tb']) <= cellrun.TB_LINES and '\x1b' not in json.dumps(r) and r['watch'] == {}


def test_code_that_never_ends_stops_at_the_time_limit_and_the_kernel_goes_on(cell):
    r = cell.run('while True: pass')
    assert r['timed_out'] and not r['ok'] and cell.k.interrupts == 1
    assert [c for c in cell.k.codes if 'while True' in c] and cell.run('1 + 1')['result'] == '2'
    assert cellrun.TIMEOUT == 5.


def test_output_has_caps(cell):
    r = cell.run("print('a' * 100000)")
    assert len(r['stdout']) < cellrun.OUT_MAX + 50 and 'cut' in r['stdout']
    assert cell.cl.post('/learn/cell/run', json=dict(code='x' * (cellrun.CODE_MAX + 1)), headers=OWN).status_code == 413
    r = cellrun.shape(ExecOutcome(outputs=[dict(output_type='display_data', data={'image/png': 'AAAA'}) for _ in range(6)] + [dict(output_type='display_data', data={'image/png': 'A' * (cellrun.IMG_MAX + 1)})]))
    assert len(r['images']) == cellrun.IMGS


def test_a_bad_body_is_refused(cell):
    assert cell.cl.post('/learn/cell/run', content='[1]', headers=OWN).status_code == 400
    assert cell.cl.post('/learn/cell/run', json=dict(code=5), headers=OWN).status_code == 400


@pytest.mark.parametrize('hdr', [{'Sec-Fetch-Site': 'cross-site'}, {'Origin': 'https://evil.example', 'Sec-Fetch-Site': 'cross-site'}, {'Origin': 'https://evil.example'},
                                 {'Origin': 'http://127.0.0.1:3000', 'Sec-Fetch-Site': 'same-site'}])
def test_a_post_from_another_site_runs_nothing(cell, hdr):
    cl = TestClient(LoopbackHostGuard(cell.app), base_url=BASE)
    r = cl.post('/learn/cell/run', json=dict(code='x = 1', walk='w', step='0'), headers=hdr)
    assert r.status_code in (403, 421) and not cell.k.codes
    assert cl.post('/learn/cell/run', json=dict(code='x = 1', walk='w', step='0'), headers=OWN).status_code == 200 and cell.k.codes


def test_a_foreign_host_runs_nothing(cell):
    cl = TestClient(LoopbackHostGuard(cell.app), base_url='http://evil.example')
    assert cl.post('/learn/cell/run', json=dict(code='x = 1'), headers=OWN).status_code in (403, 421) and not cell.k.codes
