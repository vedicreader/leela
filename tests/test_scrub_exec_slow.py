"Every snippet of the second review that the syntax check lets through, run through the real worker against made-up objects of another cell: the kernel's objects never change."
import json, sys, time
from pathlib import Path
import pytest
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.blocks.nb import app as nbapp, scrubrun
from leela.blocks.nb.nb import Cell, Notebook
from leela.workspace import Workspace

pytestmark = pytest.mark.slow
pytest.importorskip('numpy'); pytest.importorskip('pandas'); pytest.importorskip('matplotlib')

CASES = json.loads((Path(__file__).parent/'scrub_corpus2.json').read_text())
NONPLAIN = {'spy', 'sess', 'fn', 'gen', 'q', 'ax'}

SETUP = '''
import numpy as np, pandas as pd, matplotlib, queue
matplotlib.use('Agg')
import matplotlib.pyplot as plt
REC = []
class Spy:
    def __repr__(s): REC.append('repr'); return 'Spy'
    __str__ = __repr__
    def __len__(s): REC.append('len'); return 3
    def __getitem__(s, k): REC.append('getitem'); return 1
    def __add__(s, o): REC.append('add'); return 1
    def __bool__(s): REC.append('bool'); return True
    def __iter__(s): REC.append('iter'); return iter([])
    def __eq__(s, o): REC.append('eq'); return True
    __hash__ = lambda s: 1
    def get(s, *a): REC.append('get'); return 1
    def head(s, *a): REC.append('head'); return 1
    values = property(lambda s: REC.append('values'))
def fn(*a, **k): REC.append('fn')
def gen_():
    yield 1; yield 2; yield 3
fig, ax = plt.subplots()
spy = Spy(); sess = Spy(); lst = [1, 2, 3]; arr = np.array([4., 9., 16.]); gen = gen_(); q = queue.Queue(); q.put('item1'); q.put('item2')
df = pd.DataFrame({'a': [1, 2]}); m2 = np.eye(2) * 2; m3 = np.zeros((2, 2)); o0 = np.array(0.); keep = 'ORIGINAL'; data = 'ORIGINAL'
STATE0 = dict(lst=list(lst), arr=arr.copy(), q=q.qsize(), m3=m3.copy(), o0=o0.copy(), lines=len(ax.lines), texts=len(ax.texts), figs=len(plt.get_fignums()), df=df.copy(), m2=m2.copy())
'''
CHECK = '''
bad = []
if set(REC) - {'len', 'repr'}: bad.append(('hooks ran', sorted(set(REC))))   # the variables panel reads len and repr after every ordinary run
if lst != STATE0['lst']: bad.append('lst')
if not np.array_equal(arr, STATE0['arr']): bad.append('arr')
if q.qsize() != STATE0['q']: bad.append('queue')
if not np.array_equal(m3, STATE0['m3']) or not np.array_equal(o0, STATE0['o0']) or not np.array_equal(m2, STATE0['m2']): bad.append('arrays')
if len(ax.lines) != STATE0['lines'] or len(ax.texts) != STATE0['texts'] or len(plt.get_fignums()) != STATE0['figs']: bad.append('axes or figures')
if not df.equals(STATE0['df']): bad.append('df')
if list(gen) != [1, 2, 3]: bad.append('generator drained')
if keep != 'ORIGINAL' or data != 'ORIGINAL' or pd is not __import__('pandas') or np is not __import__('numpy'): bad.append('names')
if any(n in globals() for n in ('sum', 'max', 'min', 'y', 'v', 'h', 'b')): bad.append('new names')
print('unchanged' if not bad else bad)
'''

def test_the_snippets_the_check_accepts_never_change_the_kernel(tmp_path, monkeypatch):
    p = tmp_path/'s.ipynb'
    Notebook([Cell(source='x = 1')]).save(p)
    ws = Workspace(roots=[tmp_path], approvals='auto', python=sys.executable)
    ws.open(p)
    monkeypatch.setattr(nbapp, 'SCRUB_LIMIT', 0.8); monkeypatch.setattr(nbapp, 'SCRUB_FIRST', 4)
    monkeypatch.setattr(scrubrun, 'memory_cap', lambda: 400_000_000)
    try:
        with TestClient(ide_app(ws)) as client:
            client.get('/tab/state')
            tab, live, lock = ws.docstore.owner(str(p)); cid = live[0].id
            body = lambda **k: dict(path=str(p), id=cid, **k)
            assert client.post('/nb/edit', json=body(op='scrub_live', i=0, on=True)).json()['ok']
            ran = client.post('/nb/run', json=body(i=0, source=SETUP)).json()
            assert ran['ok'], ran['cell']['outputs']
            accepted = [c for c in CASES if c['want'] == 'accept']
            assert len(accepted) > 70
            slow, outcome = [], {}
            for c in accepted:
                t = time.monotonic()
                r = client.post('/nb/scrub/run', json=body(source=c['src'], first=False)).json()
                outcome[c['name']] = r
                if r.get('slow') or r.get('memory') or r.get('died'): slow.append((c['name'], time.monotonic() - t))
                if set(c['names']) & NONPLAIN:
                    assert r.get('ok') is False and 'not plain data' in r.get('refused', ''), (c['name'], r)
            assert all(dt < 4 for _, dt in slow), slow
            assert {n for n, _ in slow} >= {'decimal_int'}, slow
            chk = client.post('/nb/run', json=body(i=0, source=CHECK)).json()
            assert chk['cell']['outputs'][0]['text'] == 'unchanged\n', chk['cell']['outputs']
            alive = client.post('/nb/run', json=body(i=0, source='print(keep)')).json()
            assert alive['cell']['outputs'][0]['text'] == 'ORIGINAL\n'
            plain = [n for n, r in outcome.items() if 'outputs' in r]
            assert len(plain) > 20, plain
    finally:
        scrubrun.close_all(); ws.shutdown_now()
