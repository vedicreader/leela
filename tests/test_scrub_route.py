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

def test_the_worker_environment_holds_none_of_the_servers_secrets(rig, monkeypatch):
    client, ws, p, live, tick, run, on = rig
    monkeypatch.setenv('LEELA_FAKE_SECRET', 'hunter2'); monkeypatch.setenv('OPENAI_API_KEY', 'sk-fake')
    on(); assert text(tick('print(1)', first=True)) == '1\n'
    import psutil
    env = psutil.Process(next(iter(scrubrun.WORKERS.values())).proc.pid).environ()
    assert 'hunter2' not in str(env) and 'sk-fake' not in str(env) and set(env) <= {'PATH', 'LANG', 'HOME', 'MPLCONFIGDIR', 'MPLBACKEND', 'LEELA_SCRUB_MEMORY', 'OMP_NUM_THREADS', 'SYSTEMROOT', '__CF_USER_TEXT_ENCODING', 'LC_CTYPE'}, sorted(env)

def test_a_format_walk_to_the_environment_is_refused_before_it_reaches_the_worker(rig, monkeypatch):
    client, ws, p, live, tick, run, on = rig
    monkeypatch.setenv('LEELA_FAKE_SECRET', 'hunter2'); on()
    src = "f = lambda: 1\nprint('{0.' + '__globals__[__builtins__][__import__](os).environ}'.format(f))"
    assert tick(src, first=True)['refused'] and tick("print('{0.__class__}'.format(1))")['refused']

def test_a_notebook_file_cannot_turn_live_scrub_on(tmp_path):
    "Metadata `scrub.live` in a file is dropped on load, and the route answers `off` until the owner's own action in this session."
    q = tmp_path/'evil.ipynb'
    nbj = {'nbformat': 4, 'nbformat_minor': 5, 'metadata': {}, 'cells': [{'cell_type': 'code', 'id': 'abcd1234', 'metadata': {'scrub': {'live': True}}, 'source': 'x = 1', 'outputs': [], 'execution_count': None}]}
    q.write_text(json.dumps(nbj))
    assert 'scrub' not in Notebook.load(q)[0].extra and 'scrub' not in Cell.from_nb(nbj['cells'][0]).extra
    ws = Workspace(roots=[tmp_path], approvals='auto', python=sys.executable); ws.open(q)
    try:
        with TestClient(ide_app(ws)) as client:
            client.get('/tab/state')
            tab, live, lock = ws.docstore.owner(str(q))
            body = dict(path=str(q), id=live[0].id, source='x = 2\nprint(x)', first=True)
            assert client.post('/nb/scrub/run', json=body).json() == {'ok': False, 'off': True}
            assert client.post('/nb/edit', json=dict(path=str(q), op='scrub_live', i=0, id=live[0].id, on='yes')).json()['ok']
            assert client.post('/nb/scrub/run', json=body).json().get('off') is True
            assert client.post('/nb/edit', json=dict(path=str(q), op='scrub_live', i=0, id=live[0].id, on=True)).json()['ok']
            assert text(client.post('/nb/scrub/run', json=body).json()) == '2\n'
    finally:
        scrubrun.close_all(); ws.shutdown_now()

def test_a_tick_body_that_is_not_json_or_not_an_object_is_a_400(rig):
    client, ws, p, live, tick, run, on = rig
    for path in ('/nb/scrub/run', '/nb/scrub/warm'):
        for raw in (b'not json', b'[1]', b'"x"', b''): assert client.post(path, content=raw, headers={'content-type': 'application/json'}).status_code == 400, (path, raw)

def test_the_client_cannot_stretch_the_limit_of_a_warm_worker(rig, monkeypatch):
    client, ws, p, live, tick, run, on = rig
    on(); monkeypatch.setattr(nbapp, 'SCRUB_LIMIT', 0.6); monkeypatch.setattr(nbapp, 'SCRUB_FIRST', 20)
    assert text(tick('print(1)', first=True)) == '1\n'
    t = time.monotonic(); r = tick('import decimal\nint(decimal.Decimal("1e1000000"))', first=True)
    assert r.get('slow') and time.monotonic() - t < 5, r

def test_a_worker_that_changes_python_does_not_kill_a_tick_in_flight():
    import asyncio
    async def go():
        scrubrun.close_all()
        old = scrubrun.worker_for('k', sys.executable)
        t = asyncio.ensure_future(old.run('import time\ntime.sleep(0.5)\n"done"', {}, 10)); await asyncio.sleep(0.3)
        new = scrubrun.worker_for('k', sys.executable + '3'); assert new is not old
        r = await t
        assert r['result'] == "'done'", r
        assert old.proc is None and old.dir is None
        scrubrun.close_all()
    asyncio.run(go())

def test_a_cancelled_tick_does_not_leave_its_answer_for_the_next_request():
    "A client that disconnects mid-tick must not make the next tick read that tick's late reply."
    import asyncio
    async def go():
        w = scrubrun.Worker(sys.executable); await w.start()
        t = asyncio.ensure_future(w.run("import time\ntime.sleep(0.6)\n'ANSWER-A'", {}, 5)); await asyncio.sleep(0.2); t.cancel()
        with pytest.raises(asyncio.CancelledError): await t
        assert not w.alive
        for want in ('B', 'C'):
            r = await w.run(repr(want), {}, 5); assert want in r['result'], r
        w.close()
    asyncio.run(go())

def test_a_reply_for_another_request_ends_the_worker_and_answers_died(monkeypatch):
    import asyncio
    async def go():
        w = scrubrun.Worker(sys.executable); await w.start()
        w.seq = 10; real = json.dumps
        monkeypatch.setattr(scrubrun.json, 'dumps', lambda o, *a, **k: real({**o, 'id': 99} if 'source' in o else o, *a, **k))
        r = await w.run("'x'", {}, 5)
        assert r == {'died': True} and not w.alive
        w.close()
    asyncio.run(go())
