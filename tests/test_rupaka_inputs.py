import json, shutil, subprocess
from pathlib import Path
import pytest
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.blocks.nb.nb import Cell, Notebook, src_hash
from leela.workspace import Workspace

SPEC = dict(rupaka=1, id='throw-angle', state=dict(a=30, t=.5), blocks=[])

@pytest.fixture
def demo(tmp_path):
    path = tmp_path/'throw.ipynb'
    nb = Notebook([Cell(cell_type='markdown', source=f'```rupaka\n{json.dumps(SPEC)}\n```',
                        extra={'other': {'keep': True}, 'rupaka': {'other-demo': {'v': 9, 'keep': True}}})])
    nb.save(path)
    ws = Workspace(roots=[tmp_path]); ws.open(path)
    with TestClient(ide_app(ws)) as client:
        client.get('/tab/state')
        body = dict(op='rupaka_inputs', path=str(path), i=0, id=nb[0].id, demo=SPEC['id'], src=src_hash(nb[0].source), rev=0, inputs={'a': 60, 't': .5})
        yield client, path, body, nb

def test_inputs_save_and_round_trip(demo):
    client, path, body, nb = demo
    r = client.post('/nb/edit', json=body)
    assert r.status_code == 200, r.text
    record = dict(v=1, src=body['src'], rev=1, inputs=body['inputs'])
    assert r.json()['record'] == record
    extra = {'other': {'keep': True}, 'rupaka': {**nb[0].extra['rupaka'], SPEC['id']: record}}
    assert r.json()['cells'][0]['extra'] == extra
    saved = client.post('/nb/save', json={'path': str(path)})
    assert saved.status_code == 200, saved.text
    assert Notebook.load(path)[0].extra == extra
    undo = client.post('/nb/edit', json=dict(op='undo', path=str(path)))
    assert undo.status_code == 400 and 'no cell operation' in undo.json()['error']

@pytest.mark.parametrize('field,value,said', [('inputs', {'unknown': 1}, 'unknown input'), ('demo', 'missing', 'demo'),
    ('inputs', [], 'object'), ('inputs', None, 'object'), ('rev', True, 'revision'), ('rev', -1, 'revision'), ('rev', 1.0, 'revision'), ('id', None, 'cell id')])
def test_inputs_reject_invalid(demo, field, value, said):
    client, _, body, nb = demo
    r = client.post('/nb/edit', json={**body, field: value})
    assert r.status_code == 400 and said in r.json()['error'].lower(), r.text
    assert client.get('/tab/state').json()['cells'][0]['extra'] == nb[0].extra

@pytest.mark.parametrize('field,value', [('src', '000000000000'), ('rev', 1)])
def test_inputs_reject_stale_first_write(demo, field, value):
    client, _, body, _ = demo
    r = client.post('/nb/edit', json={**body, field: value})
    assert r.status_code == 409, r.text
    assert r.json()['record'] is None

def test_inputs_revision_increments_and_conflict_returns_current(demo):
    client, _, body, _ = demo
    first = client.post('/nb/edit', json=body)
    assert first.status_code == 200, first.text
    record = first.json()['record']
    for field, value in [('rev', 0), ('src', '000000000000')]:
        r = client.post('/nb/edit', json={**body, 'rev': 1, field: value, 'inputs': {'a': 45}})
        assert r.status_code == 409, r.text
        assert r.json()['record'] == record
    r = client.post('/nb/edit', json={**body, 'rev': 1, 'inputs': {'a': 45}})
    assert r.status_code == 200, r.text
    assert r.json()['record'] == dict(v=1, src=body['src'], rev=2, inputs={'a': 45})

@pytest.mark.parametrize('records', [[], {'throw-angle': {'v': 2, 'rev': 0, 'keep': True}}])
def test_inputs_preserve_unsupported_metadata(demo, records):
    client, path, body, _ = demo
    live = client.get('/tab/state').json()['cells'][0]
    assert live['extra']['other'] == {'keep': True}
    nb = Notebook.load(path); nb[0].extra['rupaka'] = records; nb.save(path)
    ws = Workspace(roots=[path.parent]); ws.open(path)
    with TestClient(ide_app(ws)) as other:
        other.get('/tab/state')
        r = other.post('/nb/edit', json=body)
        assert r.status_code == 400 and 'unsupported' in r.json()['error'].lower(), r.text
        assert other.get('/tab/state').json()['cells'][0]['extra']['rupaka'] == records

def test_inputs_require_markdown(demo):
    client, path, body, _ = demo
    r = client.post('/nb/edit', json=dict(op='type', path=str(path), i=0, cell_type='code'))
    assert r.status_code == 200, r.text
    r = client.post('/nb/edit', json=body)
    assert r.status_code == 400 and 'markdown' in r.json()['error'].lower(), r.text

CLIENT = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const file = fs.readFileSync(process.argv[1], 'utf8'), scenario = process.argv[2];
const code = file.slice(file.indexOf('const rupakaWrites'), file.indexOf('const mdCellHost'));
const timers = new Map(), requests = [], actions = [];
let tick = 0, release, refuse;
const spec = {id: 'demo', state: {a: 30}, blocks: []}, subs = [];
const inner = {rupaka: {st: {a: 30, gate: {g: 'open', h: 'open'}}, on: fn => subs.push(fn)}};
const cell = {id: 'c', source: 'source', cell_type: 'markdown', extra: {other: 1, rupaka: {demo: {v: 1, src: 'hash', rev: 4, inputs: {a: 60}}}}};
const lee = {tabKey: 'tab', path: '/nb', mountedAt: 1, cells: [cell], nbQueue: Promise.resolve(), nbVersions: new Map()};
const ctx = {lee, Map, JSON, Error, rupaka: {keys: {slider: ['bind'], body: ['show', 'to']}}, console: {warn: () => actions.push('warn')},
  api: async () => { throw new Error('manifests unavailable'); },
  srcHash: async s => s === 'changed' ? 'new-hash' : 'hash', mdSource: c => c.source,
  lessonRestore: () => async () => { actions.push('gates'); if (scenario === 'settled') inner.rupaka.st.gate.g = 'done'; },
  Rupaka: {set: (h, inputs) => { if (!Object.keys(inputs).length) return; actions.push(inputs); Object.assign(h.rupaka.st, inputs); [...subs].forEach(fn => fn()); }},
  setTimeout: fn => {timers.set(++tick, fn); return tick;}, clearTimeout: id => timers.delete(id),
  headingSynced: async () => {}, changedRows: () => [], nextSeq: () => 1, noteSeen: () => {}, markDirty: () => actions.push('dirty'),
  post: async (_, data) => {requests.push(data); return await new Promise((ok, no) => {release = ok; refuse = no;});}};
vm.createContext(ctx); vm.runInContext(code, ctx);
const paint = ctx.rupakaInputs(cell, 'source'), opts = paint.opts(spec);
const flush = async () => {const jobs = [...timers.values()]; timers.clear(); jobs.forEach(fn => fn()); for (let i = 0; i < 12; i++) await Promise.resolve();};
const record = rev => ({v: 1, src: 'hash', rev, inputs: {a: 45}});
(async () => {
  if (scenario === 'manifests-down') {
    delete ctx.rupaka.keys;
    await paint.restore(inner, spec);
    assert.equal(inner.rupaka.st.a, 30);
    assert.deepEqual(actions, ['warn']);
    return;
  }
  if (scenario === 'restore') {
    await paint.restore(inner, spec); assert.equal(actions[0], 'gates'); assert.equal(actions[1].a, 60);
    actions.length = 0; cell.extra.rupaka.demo.src = 'stale'; await paint.restore(inner, spec);
    assert.deepEqual(actions, ['gates']); assert.equal(requests.length, 0); return;
  }
  if (['gated', 'nested', 'settled', 'revive', 'manifest'].includes(scenario)) {
    spec.blocks = [{type: 'slider', bind: 'a', lock: 'g'}];
    if (scenario === 'nested') spec.blocks = [{type: 'row', after: 'h', blocks: spec.blocks}];
    if (scenario === 'manifest') spec.blocks = [{type: 'body', show: 'a', lock: 'g'}];
    const options = paint.opts(spec);
    await paint.restore(inner, spec);
    if (scenario === 'settled') { assert.equal(inner.rupaka.st.a, 60); return; }
    assert.equal(inner.rupaka.st.a, 30); assert.deepEqual(actions, ['gates']);
    options.save({a: 30}); await flush(); assert.equal(requests[0].inputs.a, 60);
    release({record: record(5), cells: [], version: 5}); await lee.nbQueue;
    if (scenario === 'revive') { subs.length = 0; inner.leeInputs(); }
    inner.rupaka.st.gate.g = 'pending'; subs.forEach(fn => fn()); assert.equal(inner.rupaka.st.a, 30);
    inner.rupaka.st.gate.g = 'open'; subs.forEach(fn => fn()); assert.equal(inner.rupaka.st.a, 30);
    inner.rupaka.st.gate.g = 'done'; subs.forEach(fn => fn());
    if (scenario === 'nested') { assert.equal(inner.rupaka.st.a, 30); inner.rupaka.st.gate.h = 'done'; subs.forEach(fn => fn()); }
    assert.equal(inner.rupaka.st.a, 60);
    options.save({a: 65}); await flush(); assert.equal(requests[1].inputs.a, 65);
    release({record: record(6), cells: [], version: 6}); await lee.nbQueue; return;
  }
  if (scenario === 'prose') {
    cell.source = 'changed';
    assert.strictEqual(ctx.rupakaInputs(cell, 'changed').opts(spec), opts);
    opts.save({a: 65}); await flush();
    assert.equal(requests[0].src, 'new-hash'); assert.equal(requests[0].inputs.a, 65);
    release({record: record(5), cells: [], version: 5}); await lee.nbQueue; return;
  }
  if (scenario === 'fence') {
    cell.source = 'changed'; ctx.rupakaInputs(cell, 'changed').opts({...spec, state: {a: 40}});
    opts.save({a: 65}); await flush(); assert.equal(requests.length, 0); return;
  }
  opts.save({a: 40}); opts.save({a: 45}); await flush();
  assert.equal(requests.length, 1); assert.equal(requests[0].inputs.a, 45); assert.equal(requests[0].rev, 4);
  if (scenario === 'prose-flight') {
    cell.source = 'changed'; ctx.rupakaInputs(cell, 'changed').opts(spec);
    release({record: record(5), cells: [], version: 5}); await lee.nbQueue;
    assert.equal(cell.extra.rupaka.demo.rev, 5);
    opts.save({a: 65}); await flush(); assert.equal(requests[1].rev, 5); assert.equal(requests[1].src, 'new-hash');
    release({record: record(6), cells: [], version: 6}); await lee.nbQueue; return;
  }
  if (scenario === 'coalesce') {
    opts.save({a: 50}); await flush(); assert.equal(requests.length, 1);
    release({record: record(5), cells: [], version: 5}); await lee.nbQueue; await flush();
    assert.equal(requests.length, 2); assert.equal(requests[1].inputs.a, 50); assert.equal(requests[1].rev, 5);
    release({record: record(6), cells: [], version: 6}); await lee.nbQueue; return;
  }
  if (scenario === 'conflict') {
    refuse({body: {kind: 'rupaka_conflict', record: record(8)}}); await lee.nbQueue;
    assert.equal(cell.extra.rupaka.demo.rev, 8); assert.deepEqual(actions, ['warn']);
    opts.save({a: 65}); await flush(); assert.equal(requests[1].rev, 8);
    release({record: record(9), cells: [], version: 9}); await lee.nbQueue; return;
  }
  if (scenario === 'tab') lee.tabKey = 'other';
  if (scenario === 'path') lee.path = '/other';
  if (scenario === 'source') cell.source = 'changed';
  if (scenario === 'remount') lee.mountedAt++;
  release({record: record(5), cells: [], version: 5}); await lee.nbQueue;
  assert.equal(cell.extra.rupaka.demo.rev, 4); assert.equal(actions.length, 0);
})().catch(e => {console.error(e); process.exitCode = 1;});
'''

@pytest.mark.parametrize('scenario', ['restore', 'manifests-down', 'gated', 'manifest', 'nested', 'settled', 'revive', 'prose', 'prose-flight', 'fence', 'coalesce', 'conflict', 'tab', 'path', 'source', 'remount'])
def test_inputs_client_contract(scenario):
    node = shutil.which('node')
    if not node: pytest.skip('node is not installed')
    path = Path(__file__).parents[1]/'leela'/'blocks'/'nb'/'cells.js'
    r = subprocess.run([node, '-e', CLIENT, str(path), scenario], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr

@pytest.mark.parametrize('prior', [False, True])
def test_inputs_survive_structural_undo_redo(demo, prior):
    client, path, body, _ = demo
    if prior:
        assert client.post('/nb/edit', json=body).status_code == 200
        body = {**body, 'rev': 1, 'inputs': {'a': 75}}
    assert client.post('/nb/edit', json=dict(op='insert', path=str(path), i=1)).status_code == 200
    saved = client.post('/nb/edit', json=body)
    assert saved.status_code == 200, saved.text
    record = saved.json()['record']
    for op, count in [('undo', 1), ('redo', 2)]:
        r = client.post('/nb/edit', json=dict(op=op, path=str(path)))
        assert r.status_code == 200, r.text
        assert len(r.json()['cells']) == count
        assert r.json()['cells'][0]['extra']['rupaka']['throw-angle'] == record
        assert client.post('/nb/save', json={'path': str(path)}).status_code == 200
        assert Notebook.load(path)[0].extra['rupaka']['throw-angle'] == record
