import builtins, json, shutil, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
import pytest
from fastcore.basics import AttrDict
from starlette.testclient import TestClient
from abhyasa.store import Learning
import abhyasa.demo  # adds Learning.demo and Learning.demos
from leela.app import ide_app
from leela.blocks.memory.memory import Memory
from leela.blocks.nb.lesson import demo_gate, fence, lesson_notebook
from leela.blocks.nb.nb import Cell, Notebook, src_hash
from leela.workspace import Workspace

ROOT = Path(__file__).parents[1]
GATE = dict(type='gate', id='g1', prompt='What is half of 8?', options=[2, 4, 6], answer={'is': 4}, why='Why?')
def spec(id='halves', gate=GATE): return dict(id=id, blocks=[dict(type='stack', blocks=[dict(type='row', blocks=[gate])])])
DEMO = spec()
EXERCISE = dict(task='Double a number.', fname='double', stub='def double(x):\n    pass', uses=[],
                tests=[dict(say='Two', test='assert double(2) == 4', shown=True)])

@pytest.fixture
def serve(tmp_path, monkeypatch):
    "Open a notebook in a test workspace; `opened` lists the shelves opened, every one under `tmp_path`."
    opened, original = [], Memory._store
    def guarded(self, name):
        assert self.path.resolve().is_relative_to(tmp_path.resolve()), self.path
        opened.append(name)
        return original(self, name)
    monkeypatch.setattr(Memory, '_store', guarded)
    monkeypatch.setenv('HOME', str(tmp_path/'home'))
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'vault.db'))
    with ExitStack() as stack:
        def go(nb):
            p = tmp_path/'lesson.ipynb'; nb.save(p)
            ws = Workspace(roots=[tmp_path], approvals='auto', python=sys.executable)
            monkeypatch.setattr(ws, 'memory', Memory(path=tmp_path/'vault.db', offline=True))
            ws.open(p)
            stack.callback(ws.shutdown_now)
            c = stack.enter_context(TestClient(ide_app(ws)))
            c.get('/tab/state')
            return AttrDict(c=c, ws=ws, p=p, nb=ws.docstore.doc_for(ws.tab), opened=opened)
        yield go

def lesson(*sources, exercise=None, step=None):
    nb = lesson_notebook('Halves', exercise=exercise, step=step)
    nb[1].source = '\n\n'.join(sources) if sources else fence(DEMO)
    return nb

@pytest.fixture
def rig(serve): return serve(lesson())

def post(r, i=1, gate='g1', demo='halves', src=None, path=None, **kw):
    cell = r.nb[i] if isinstance(i, int) else None
    body = dict(path=str(path or r.p), cell_id=cell.id if cell else i, demo=demo, gate=gate,
                src=src_hash(cell.source) if src is None and cell else src, **kw)
    return r.c.post('/lesson/predict', json=body)

def shelf(r): return Learning(r.ws.memory._store('learning'))
def attempts(r, slug='halves'): return list(shelf(r).attempts(slug, limit=10000))

def test_predict_ok_is_server_side_and_once(rig):
    r = post(rig, picked=2, why='', ok=True, ans=2)            # the page says right; 2 is wrong
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d['ok'], d['logged']) == (True, True) and d['message'].startswith('Saved to your learning shelf. '), d
    assert post(rig, picked=4, why='half').json() == {'ok': True, 'logged': False}   # "try again" logs nothing
    rows = attempts(rig)
    assert len(rows) == 1
    a = rows[0]
    assert (a.kind, a.method, bool(a.correct), a.answer, a.expected, a.question) == ('demo', 'demo', False, '2', '4', 'What is half of 8?')
    assert a.notebook == str(rig.p) and a.gate == 'g1' and a.demo == 'halves' and not {'walk', 'step', 'from', 'app'} & set(a)
    assert a.card_key == f'{rig.nb[1].id}:{src_hash(rig.nb[1].source)}:halves:g1'
    c = shelf(rig).concept('halves')
    assert c.seen == 1 and c.due > time.time() and 'kind' not in c
    d = shelf(rig).demo('halves')
    assert (d.concept, d.by, d.stats) == ('halves', 'leela:lesson', {'shown': 1, 'right': 0})
    assert set(rig.opened) == {'learning'}

def test_predict_in_a_walk_lesson_carries_the_walk_meta(serve):
    r = serve(lesson(step=dict(walk='attention-ab12', step=1, section='', text='Half of it.', note='')))
    assert post(r, picked=4, why='half').json()['logged']
    a = attempts(r)[0]
    assert (a.kind, a.walk, a.step, a['from'], a.app, a.notebook) == ('demo', 'attention-ab12', 1, 'attention-ab12/1', 'leela', str(r.p)) and 'section' not in a

def test_predict_compares_as_the_runtime_does(serve):
    g = dict(GATE, options=['4', 5], answer={'is': 4.0})
    r = serve(lesson(fence(spec(gate=g))))
    assert post(r, picked='4').json()['logged']
    a = attempts(r)[0]
    assert bool(a.correct) and a.feedback == 'The answer is 4.'

def test_predict_forged_ok_is_ignored(rig):
    assert post(rig, picked=6, ok=True, ans=6).json()['logged']
    assert not attempts(rig)[0].correct

def test_predict_refuses_a_gate_that_is_not_in_the_cell(rig):
    r = post(rig, gate='nope', picked=4)
    assert r.status_code == 400 and 'no gate' in r.json()['error']
    assert post(rig, i='missing', picked=4).status_code == 400
    assert post(rig, i=0, picked=4).status_code == 400              # a cell with no demo
    assert post(rig, demo='other', picked=4).status_code == 400     # the gate is in another demo
    assert attempts(rig) == []

def test_predict_in_a_plain_notebook_does_not_open_the_store(serve):
    r = serve(Notebook([Cell(source=fence(DEMO), cell_type='markdown')]))
    assert post(r, i=0, picked=4).json() == {'ok': True, 'logged': False}
    for meta in ({}, {'lesson': {}}, {'lesson': 'Halves'}, {'lesson': {'name': ''}}):
        r.nb.meta = meta
        assert post(r, i=0, picked=4).json() == {'ok': True, 'logged': False}
    assert r.opened == []

def test_predict_in_an_exercise_lesson(serve):
    r = serve(lesson(exercise=EXERCISE))
    assert len(r.nb.cells) == 7
    assert post(r, picked=4).json()['logged']
    assert len(attempts(r)) == 1

def test_predict_finds_a_nested_gate():
    deep = dict(id='deep', blocks=[dict(type='stack', blocks=[dict(type='row', blocks=[dict(type='stack', blocks=[
        dict(type='caption', text='x'), dict(GATE, id='g9')])])])])
    cell = Cell(source=fence(deep), cell_type='markdown')
    s, g = demo_gate(cell, 'deep', 'g9')
    assert s['id'] == 'deep' and g['prompt'] == 'What is half of 8?'

def test_predict_reads_tilde_fences_and_skips_bad_ones():
    tilde = '~~~rupaka\n' + json.dumps(DEMO) + '\n~~~'
    for src in (f'```rupaka\n{{nope\n```\n\n{tilde}', f'{fence(DEMO)}\n\n```rupaka\n{{nope\n```',
                '```rupaka\nnull\n```\n\n```rupaka\n[1]\n```\n\n```rupaka\n{"id": "halves", "blocks": 3}\n```\n\n' + fence(DEMO)):
        assert demo_gate(Cell(source=src, cell_type='markdown'), 'halves', 'g1')[1]['id'] == 'g1', src
    for src in ('```rupaka\n{nope\n```', '```json\n' + json.dumps(DEMO) + '\n```'):
        with pytest.raises(ValueError, match='no gate'): demo_gate(Cell(source=src, cell_type='markdown'), 'halves', 'g1')
    with pytest.raises(ValueError, match='no gate'): demo_gate(Cell(source=fence(DEMO)), 'halves', 'g1')   # a code cell

def test_predict_two_fences(serve):
    other = spec('quarters', dict(GATE, id='g2', prompt='Quarter of 8?', answer={'is': 2}))
    r = serve(lesson(fence(DEMO), fence(other)))
    assert post(r, picked=4).json()['logged'] and post(r, demo='quarters', gate='g2', picked=2).json()['logged']
    rows = {a.gate: a for a in attempts(r)}
    assert (rows['g1'].demo, rows['g2'].demo, bool(rows['g2'].correct)) == ('halves', 'quarters', True)

def test_predict_reused_gate_id_is_decided_by_the_demo(serve):
    r = serve(lesson(fence(DEMO), fence(spec('again', dict(GATE, answer={'is': 6})))))
    assert post(r, demo='again', picked=6).json()['logged']
    a = attempts(r)[0]
    assert a.demo == 'again' and bool(a.correct) and a.card_key.endswith(':again:g1')

@pytest.mark.parametrize('sources', [(fence(DEMO), fence(DEMO)), (fence(dict(DEMO, blocks=DEMO['blocks']*2)),)], ids=['same-fence-twice', 'same-gate-twice'])
def test_predict_refuses_an_ambiguous_gate(serve, sources):
    r = serve(lesson(*sources))
    res = post(r, picked=4)
    assert res.status_code == 400 and 'more than one gate' in res.json()['error'], res.text
    assert r.opened == []

def test_predict_edited_cell_logs_again_and_a_stale_src_is_409(rig):
    old = src_hash(rig.nb[1].source)
    assert post(rig, picked=2).json()['logged']
    new = rig.nb[1].source + '\n\nHalve it.'
    assert rig.c.post('/nb/edit', json=dict(path=str(rig.p), op='source', i=1, source=new)).json()['ok']
    stale = post(rig, picked=4, src=old)
    assert stale.status_code == 409 and stale.json()['error'] == 'This demo changed. Run the cell again, then try.'
    assert post(rig, picked=4, src='').status_code == 409
    assert post(rig, picked=4).json()['logged']
    keys = {a.card_key for a in attempts(rig)}
    assert keys == {f'{rig.nb[1].id}:{old}:halves:g1', f'{rig.nb[1].id}:{src_hash(new)}:halves:g1'}
    assert [d.stats for d in shelf(rig).demos()] == [{'shown': 2, 'right': 1}]

def test_predict_edited_demo_reuses_its_shelf_demo(rig):
    assert post(rig, picked=4).json()['logged']
    new = fence(spec(gate=dict(GATE, prompt='What is 8 / 2?')))
    assert rig.c.post('/nb/edit', json=dict(path=str(rig.p), op='source', i=1, source=new)).json()['ok']
    assert post(rig, picked=4).json()['logged']
    ds = shelf(rig).demos()
    assert len(ds) == 1 and ds[0].slug == 'halves' and ds[0].stats == {'shown': 2, 'right': 2}
    assert ds[0].spec['blocks'][0]['blocks'][0]['blocks'][0]['prompt'] == 'What is 8 / 2?'
    assert sorted(a.question for a in attempts(rig)) == ['What is 8 / 2?', 'What is half of 8?']

def test_predict_an_edit_to_another_cell_does_not_block(rig):
    assert rig.c.post('/nb/edit', json=dict(path=str(rig.p), op='source', i=3, source='print(1)')).json()['ok']
    assert post(rig, picked=4).json()['logged']

def test_predict_renamed_copy_is_the_same_attempt(rig, tmp_path):
    assert post(rig, picked=4).json()['logged']
    copy = tmp_path/'copy.ipynb'
    shutil.copy(rig.p, copy)
    rig.ws.open(copy)
    rig.c.get('/tab/state')
    assert post(rig, picked=4, path=copy).json() == {'ok': True, 'logged': False}
    rows = attempts(rig)
    assert len(rows) == 1 and rows[0].notebook == str(rig.p)

def test_predict_state_path_answer_files_the_page_values(serve):
    r = serve(lesson(fence(spec(gate=dict(GATE, answer='half')))))
    assert post(r, picked=6, ans=6, ok=True, why='Half of 12.').json()['logged']
    a = attempts(r)[0]
    assert (bool(a.correct), a.answer, a.expected, a.thinking) == (True, '6', '6', 'Half of 12.')

@pytest.mark.parametrize('kw', [{}, dict(ans=4), dict(ans=4, ok='true'), dict(ans=4, ok=1), dict(ans=[4], ok=True), dict(ans={'is': 4}, ok=False)])
def test_predict_state_path_refuses_a_bad_verdict(serve, kw):
    r = serve(lesson(fence(spec(gate=dict(GATE, answer='half')))))
    res = post(r, picked=4, **kw)
    assert res.status_code == 400 and res.json()['error'].startswith('This check needs '), res.text
    assert r.opened == []

def test_predict_refuses_a_demo_without_an_id(serve):
    r = serve(lesson(fence(spec(id=''))))
    res = post(r, demo='', picked=4)
    assert res.status_code == 400 and res.json()['error'] == 'This demo has no id. Give it one, then try.'
    assert r.opened == []

@pytest.mark.parametrize('failure', ['missing', 'locked'])
def test_predict_reports_store_failure_and_allows_retry(rig, monkeypatch, failure):
    with monkeypatch.context() as patch:
        if failure == 'missing':
            original = builtins.__import__
            def unavailable(name, *args, **kwargs):
                if name == 'abhyasa.store': raise ModuleNotFoundError("No module named 'abhyasa'", name='abhyasa')
                return original(name, *args, **kwargs)
            patch.setattr(builtins, '__import__', unavailable)
        else:
            def locked(*args): raise PermissionError('locked')
            patch.setattr(Memory, '_store', locked)
        r = post(rig, picked=4)
        assert r.status_code == 400, r.text
        assert r.json()['error'] == ('Saving cards needs abhyasa. Install abhyasa, then try again.' if failure == 'missing'
                                     else 'The learning vault is locked or unreadable. PermissionError: locked')
    assert post(rig, picked=4).json()['logged'] and len(attempts(rig)) == 1

@pytest.mark.parametrize('failure', ['record', 'update'])
def test_predict_rolls_back_a_failed_attempt(rig, monkeypatch, failure):
    with monkeypatch.context() as patch:
        def failed(*args, **kwargs): raise OSError('write refused')
        patch.setattr(Learning, failure, failed)
        assert post(rig, picked=4).status_code == 400
    assert attempts(rig) == []
    assert post(rig, picked=4).json()['logged']
    assert len(attempts(rig)) == 1 and shelf(rig).concept('halves').seen == 1 and shelf(rig).demo('halves').stats['shown'] == 1

def test_simultaneous_predictions_log_once(rig):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: post(rig, picked=4), range(2)))
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    assert sorted(r.json()['logged'] for r in results) == [False, True] and len(attempts(rig)) == 1

@pytest.mark.parametrize('text', ['', 'plain', 'naïve 半分 \U0001f600\n```rupaka\n{}\n```'])
def test_page_hash_matches_src_hash(text):
    node = shutil.which('node')
    if not node: pytest.skip('node is not installed')
    harness = '''const vm = require('vm'), fs = require('fs'), ctx = {crypto, TextEncoder, console}; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8').match(/^const srcHash = .*;$/m)[0] + '; globalThis.srcHash = srcHash;', ctx);
ctx.srcHash(process.argv[2]).then(h => console.log(h));'''
    r = subprocess.run([node, '-e', harness, str(ROOT/'leela/static/js/core.js'), text], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == src_hash(text)

def test_lesson_predict_holds_the_gate_until_the_server_answers():
    "lessonPredict holds a rupaka 0.0.2 gate, settles it from the server's answer, and leaves a gate without `settle` alone."
    node = shutil.which('node')
    if not node: pytest.skip('node is not installed')
    harness = r'''const vm = require('vm'), fs = require('fs'), src = fs.readFileSync(process.argv[1], 'utf8');
const fn = src.slice(src.indexOf('async function lessonPredict'), src.indexOf('\n}\n', src.indexOf('async function lessonPredict')) + 3);
const ctx = {lee: {path: '/n.ipynb', nbQueue: Promise.resolve()}, srcHash: async s => 'h:' + s, said: [], reply: null};
ctx.status = (t, k) => ctx.said.push([k, t]);
ctx.post = async () => { const r = ctx.reply; if (r instanceof Error) throw r; return r; };
vm.createContext(ctx); vm.runInContext(fn + '; globalThis.lessonPredict = lessonPredict;', ctx);
const event = (source, withSettle) => { const ev = {held: false, settled: []};
  const host = {classList: {contains: c => c === 'lee-rupaka'}, leeSource: source}, cell = {matches: s => s.startsWith('.lee-cell'), dataset: {id: 'c1'}};
  ev.composedPath = () => [host, cell]; ev.preventDefault = () => { ev.held = true; };
  ev.detail = {demo: 'd', gate: 'g1', picked: 4, ans: 4, ok: true, why: ''};
  if (withSettle) ev.detail.settle = (...a) => ev.settled.push(a);
  return ev; };
const err = (status, body) => Object.assign(new Error(body?.error || status), {body});
(async () => { const out = {};
  for (const [name, reply, source, withSettle] of [
      ['logged', {ok: true, logged: true, message: 'Saved.'}, 'x', true], ['repeat', {ok: true, logged: false}, 'x', true],
      ['conflict', err('Conflict', {ok: false, error: 'This demo changed. Run the cell again, then try.'}), 'x', true],
      ['html', err('Bad Gateway', '<html>'), 'x', true], ['network', new TypeError('Failed to fetch'), 'x', true],
      ['old', {ok: true, logged: true, message: 'Saved.'}, 'x', false], ['old-error', new TypeError('Failed to fetch'), 'x', false],
      ['not-ours', {ok: true}, null, true]]) {
    ctx.reply = reply; ctx.said = []; const ev = event(source, withSettle), p = ctx.lessonPredict(ev), heldAtOnce = ev.held; await p;
    out[name] = {heldAtOnce, settled: ev.settled, said: ctx.said}; }
  console.log(JSON.stringify(out)); })();'''
    r = subprocess.run([node, '-e', harness, str(ROOT/'leela/blocks/nb/lesson.js')], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    got, retry = json.loads(r.stdout), 'Leela did not save this. Try again.'
    said = {k: got[k].pop('said') for k in got}
    assert said['conflict'] == [['err', 'This demo changed. Run the cell again, then try.']]
    assert said['html'] == said['network'] == said['old-error'] == [['err', retry]], 'the toast says what the gate says, never Failed to fetch'
    assert said['logged'] == said['old'] == [['ok', 'Saved.']]
    assert got['logged'] == got['repeat'] == {'heldAtOnce': True, 'settled': [[True]]}
    assert got['conflict'] == {'heldAtOnce': True, 'settled': [[False, 'This demo changed. Run the cell again, then try.']]}
    assert got['html'] == got['network'] == {'heldAtOnce': True, 'settled': [[False, retry]]}
    assert got['old'] == got['old-error'] == got['not-ours'] == {'heldAtOnce': False, 'settled': []}
