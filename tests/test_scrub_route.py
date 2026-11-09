"A scrub tick runs a cell lightly, stops it softly, and never restarts the kernel."
import asyncio, sys
import pytest
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.blocks.nb import app as nbapp
from leela.blocks.nb.nb import Cell, Notebook
from leela.workspace import Workspace

@pytest.fixture
def rig(tmp_path):
    p = tmp_path/'s.ipynb'
    cell = Cell(source='x = 3\nprint(x*2)')
    Notebook([cell]).save(p)
    ws = Workspace(roots=[tmp_path], approvals='auto', python=sys.executable)
    ws.open(p)
    try:
        with TestClient(ide_app(ws)) as client:
            client.get('/tab/state')
            tab, live, lock = ws.docstore.owner(str(p))
            tick = lambda source, **kw: client.post('/nb/scrub/run', json=dict(path=str(p), i=0, id=live[0].id, source=source, **kw)).json()
            yield client, ws, p, live, lock, tick
    finally: ws.shutdown_now()

def test_a_tick_runs_the_cell_and_returns_its_outputs(rig):
    client, ws, p, live, lock, tick = rig
    r = tick('x = 4\nprint(x*2)', first=True)
    assert r['ok'] and r['outputs'][0]['text'] == '8\n', r
    assert tick('x = 5\nprint(x*2)')['outputs'][0]['text'] == '10\n'

def test_a_tick_skips_every_effect_of_a_full_run(rig, monkeypatch):
    "A full run counts, files, marks dirty, locks a prediction, notes the origin and fetches value rows; a tick does none of them."
    client, ws, p, live, lock, tick = rig
    seen = []
    real_lock = nbapp.lock
    async def extras(k, c): seen.append('extras'); return None, None
    monkeypatch.setattr(nbapp, 'lock', lambda *a, **k: seen.append('lock') or real_lock(*a, **k))
    monkeypatch.setattr(nbapp, 'cell_extras', extras)
    monkeypatch.setattr(ws.origins, 'cell', lambda *a, **k: seen.append('origin'))
    live.dirty = False
    r = tick(live[0].source)
    assert r['ok'] and seen == [] and live[0].execution_count is None and live.dirty is False, (seen, live[0].execution_count, live.dirty)
    full = client.post('/nb/run', json=dict(path=str(p), i=0, id=live[0].id, source='x = 1')).json()
    assert full['cell']['execution_count'] == 1 and {'origin', 'lock', 'extras'} <= set(seen), seen

def test_a_tick_refuses_an_unsafe_cell_before_running_anything(rig, tmp_path):
    client, ws, p, live, lock, tick = rig
    r = tick("open('leak.txt', 'w').write('x')")
    assert r['ok'] is False and r['refused'] and not (tmp_path/'leak.txt').exists() and live[0].execution_count is None
    assert 'safe list' in tick('import os')['refused']

def test_a_tick_while_a_run_holds_the_lock_is_busy_not_queued(rig):
    import threading, time
    client, ws, p, live, lock, tick = rig
    got = []
    t = threading.Thread(target=lambda: got.append(tick('import time\ntime.sleep(1)', first=True))); t.start()
    time.sleep(0.4)
    try: r = tick('x = 1')
    finally: t.join()
    assert r == {'ok': False, 'busy': True} and got[0]['ok']

def test_a_run_over_the_limit_is_interrupted_softly_and_the_kernel_keeps_its_names(rig, monkeypatch):
    client, ws, p, live, lock, tick = rig
    monkeypatch.setattr(nbapp, 'SCRUB_LIMIT', 0.5)
    assert tick('keep = 42\nprint(keep)', first=True)['ok']
    r = tick('import time\nt = time.time()\nwhile time.time() - t < 30: pass')
    assert r['slow'] and not r.get('stuck'), r
    r = tick('print(keep + 1)', first=True)
    assert r['ok'] and r['outputs'][0]['text'] == '43\n', 'the kernel was restarted and lost its names'

def test_an_interrupt_the_kernel_ignores_ends_the_tick_as_stuck_and_never_restarts_it(rig, monkeypatch):
    client, ws, p, live, lock, tick = rig
    class Deaf:
        alive = True; restarted = stopped = False; interrupts = 0
        async def execute(self, code, on_output=None, **kw): await asyncio.sleep(6); return type('R', (), dict(outputs=[], execution_count=1, lost=False, reason=None))()
        async def interrupt(self): self.interrupts += 1
        async def restart(self): self.restarted = True
        async def stop(self, timeout=2.0): self.stopped = True
    k = Deaf()
    async def runtime(tab=None): return k
    monkeypatch.setattr(ws, 'runtime', runtime)
    monkeypatch.setattr(nbapp, 'SCRUB_LIMIT', 0.3); monkeypatch.setattr(nbapp, 'SCRUB_GRACE', 0.3)
    r = tick('x = 1')
    assert r['slow'] and r['stuck'] and k.interrupts == 1 and not k.restarted and not k.stopped, (r, k.interrupts)
