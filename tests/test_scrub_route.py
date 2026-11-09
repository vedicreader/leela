"A live scrub tick runs a copy of the cell in a separate process, and never touches the kernel."
import json, sys, time
import pytest
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.blocks.nb import app as nbapp, scrubrun
from leela.blocks.nb.nb import Cell, Notebook
from leela.workspace import Workspace

@pytest.fixture
def rig(tmp_path):
    p = tmp_path/'s.ipynb'
    Notebook([Cell(source='x = 3\nprint(x*2)')]).save(p)
    ws = Workspace(roots=[tmp_path], approvals='auto', python=sys.executable)
    ws.open(p)
    try:
        with TestClient(ide_app(ws)) as client:
            client.get('/tab/state')
            tab, live, lock = ws.docstore.owner(str(p))
            cid = live[0].id
            tick = lambda source, **kw: client.post('/nb/scrub/run', json=dict(path=str(p), id=cid, source=source, **kw)).json()
            run = lambda source: client.post('/nb/run', json=dict(path=str(p), i=0, id=cid, source=source)).json()
            on = lambda v=True: client.post('/nb/edit', json=dict(path=str(p), op='scrub_live', i=0, id=cid, on=v)).json()
            yield client, ws, p, live, tick, run, on
    finally:
        scrubrun.close_all()
        ws.shutdown_now()

def text(r): return ''.join(o.get('text', '') for o in r['outputs'])

def test_live_scrub_is_off_until_a_cell_opts_in_and_the_choice_is_kept_in_its_metadata(rig):
    client, ws, p, live, tick, run, on = rig
    assert tick('x = 4\nprint(x*2)') == {'ok': False, 'off': True}
    assert on()['ok'] and live[0].extra['scrub'] == {'live': True}
    assert text(tick('x = 4\nprint(x*2)', first=True)) == '8\n'
    assert on(False)['ok'] and 'scrub' not in live[0].extra and tick('x = 1')['off']

def test_a_tick_needs_text_for_its_source_and_never_runs_the_stored_source(rig):
    client, ws, p, live, tick, run, on = rig
    on()
    for body in ({}, {'source': None}, {'source': 5}, {'source': ['x = 1']}):
        r = client.post('/nb/scrub/run', json=dict(path=str(p), id=live[0].id, **body))
        assert r.status_code == 400, body
    assert live[0].execution_count is None and not live[0].outputs

def test_a_tick_records_nothing_in_the_kernel(rig):
    client, ws, p, live, tick, run, on = rig
    on(); run('keep = 1')
    count, outs = live[0].execution_count, list(live[0].outputs)
    r = tick('x = 4\nwhoops = 9\nprint(x*2)', first=True)
    assert text(r) == '8\n'
    assert live[0].execution_count == count and live[0].outputs == outs
    got = run("print('x' in dir(), 'whoops' in dir(), keep)")
    assert got['cell']['outputs'][0]['text'] == 'False False 1\n'
    assert got['cell']['execution_count'] == count + 1, 'a tick must not use an execution number'

def test_a_cell_reads_a_copy_of_the_plain_data_of_other_cells(rig):
    client, ws, p, live, tick, run, on = rig
    on(); run('import numpy as np, pandas as pd\ndata = [1, 2, 3]\nn = 7\narr = np.arange(4.)\ndf = pd.DataFrame({"a": [1, 2], "b": [0.5, 1.5]})')
    assert text(tick('print(sum(data) * n, arr.sum(), df["b"].sum())', first=True)) == '42 6.0 2.0\n'
    assert tick('arr += 1')['refused'] and tick('data.append(9)')['refused']
    got = run("print(data, arr.tolist(), df['a'].tolist())")['cell']['outputs'][0]['text']
    assert got == '[1, 2, 3] [0.0, 1.0, 2.0, 3.0] [1, 2]\n'

def test_a_name_that_is_not_plain_data_ends_the_tick_with_the_reason(rig):
    client, ws, p, live, tick, run, on = rig
    on(); run('class P:\n    def __repr__(s): raise SystemExit\np = P()\nimport collections\nq = collections.deque([1])\ndef gen():\n    yield 1\ng = gen()')
    for name in ('p', 'g', 'q'):
        r = tick(f'print(len({name}))' if name == 'q' else f'print({name})', first=True)
        assert r['ok'] is False and 'not plain data' in r['refused'] and f' {name} ' in r['refused'], r
    assert run('print(next(g), len(q))')['cell']['outputs'][0]['text'] == '1 1\n'

def test_a_tick_over_the_limit_kills_the_worker_and_the_kernel_keeps_its_names(rig, monkeypatch):
    client, ws, p, live, tick, run, on = rig
    on(); run('keep = 42')
    monkeypatch.setattr(nbapp, 'SCRUB_LIMIT', 0.6)
    assert text(tick('print(1)', first=True)) == '1\n'
    t = time.monotonic()
    r = tick('import decimal\nint(decimal.Decimal("1e1000000"))')
    assert r.get('slow') and time.monotonic() - t < 3, r
    r = tick('print(2)', first=True)
    assert text(r) == '2\n'
    assert run('print(keep)')['cell']['outputs'][0]['text'] == '42\n'

def test_a_tick_that_eats_memory_is_killed_without_hurting_the_server(rig, monkeypatch):
    client, ws, p, live, tick, run, on = rig
    on(); run('keep = 42')
    monkeypatch.setattr(scrubrun, 'memory_cap', lambda: 300_000_000)
    monkeypatch.setattr(nbapp, 'SCRUB_FIRST', 20)
    r = tick('s = "x" * 1000\nfor i in range(30):\n    s = s + s\nprint(len(s))', first=True)
    assert r.get('memory') or r.get('died') or r.get('error') is None and not r.get('ok'), r
    assert text(tick('print(3)', first=True)) == '3\n'
    assert run('print(keep)')['cell']['outputs'][0]['text'] == '42\n'

def test_a_tick_that_writes_a_file_is_refused(rig, tmp_path):
    client, ws, p, live, tick, run, on = rig
    on()
    assert tick("open('leak.txt', 'w').write('x')")['refused'] and not (tmp_path/'leak.txt').exists()

def test_the_worker_runs_in_an_empty_folder_with_no_proxy_in_its_environment_and_dies_with_its_tab(rig, monkeypatch):
    client, ws, p, live, tick, run, on = rig
    monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:1')
    on()
    assert text(tick('print(1)', first=True)) == '1\n'
    w = next(iter(scrubrun.WORKERS.values()))
    import os, psutil
    env = psutil.Process(w.proc.pid).environ()
    assert os.listdir(w.dir) == [] or all(not f.endswith(('.txt', '.csv')) for f in os.listdir(w.dir))
    assert not any(k.lower().endswith('_proxy') for k in env) and psutil.Process(w.proc.pid).cwd() == os.path.realpath(w.dir)
    pid = w.proc.pid; scrubrun.close_all()
    for _ in range(40):
        if not psutil.pid_exists(pid): break
        try:
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE: break
        except psutil.NoSuchProcess: break
        time.sleep(0.1)
    else: raise AssertionError('the worker is still alive')

def test_the_worker_has_no_network_in_the_best_effort_way_it_can():
    import subprocess
    code = ("import importlib.util as u\n"
            f"s = u.spec_from_file_location('w', {str(scrubrun.HERE/'scrubworker.py')!r}); w = u.module_from_spec(s); s.loader.exec_module(w); w.no_network()\n"
            "import socket\n"
            "try: socket.socket().connect(('127.0.0.1', 9)); print('connected')\n"
            "except OSError as e: print('refused', e)\n")
    r = subprocess.run([sys.executable, '-I', '-c', code], capture_output=True, text=True, timeout=30)
    assert r.stdout.startswith('refused the network is off'), (r.stdout, r.stderr)
