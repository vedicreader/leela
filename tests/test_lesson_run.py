import json, shutil, subprocess, sys
from copy import deepcopy
from pathlib import Path
import pytest
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.blocks.nb.lesson import lesson_notebook
from leela.blocks.nb.nb import Notebook
from leela.workspace import Workspace

@pytest.fixture
def lesson_client(tmp_path):
    p = tmp_path/'lesson.ipynb'
    nb = lesson_notebook('Output')
    nb[2].source = 'Draft guess'
    nb[2].extra['lesson']['confidence'] = 30
    nb[3].source = 'print(42)'
    nb[3].extra['other'] = {'keep': True}
    nb.save(p)
    ws = Workspace(roots=[tmp_path], approvals='auto', python=sys.executable)
    ws.open(p)
    try:
        with TestClient(ide_app(ws)) as client:
            client.get('/tab/state')
            yield client, ws, p, nb
    finally: ws.shutdown_now()

@pytest.mark.parametrize('route', ['/nb/run', '/nb/run/stream'])
def test_run_locks_prediction_then_clears_only_code_lesson(lesson_client, route):
    client, ws, p, nb = lesson_client
    body = dict(path=str(p), i=3, id=nb[3].id, source=nb[3].source)
    prediction = deepcopy(nb[2].extra)
    last_count = 0
    for guess in ({'prediction': '  42\n', 'confidence': 70}, {'prediction': '42'}, {}, {'prediction': '42'}, {'prediction': ' \n\t'}):
        r = client.post(route, json={**body, **guess})
        assert r.status_code == 200, r.text
        done = (json.loads(r.text.split('event: done\ndata: ', 1)[1].split('\n\n', 1)[0])
                if route.endswith('/stream') else r.json())
        c = done['cell']
        assert done['ok'] and c['execution_count'] > last_count, done
        last_count = c['execution_count']
        expected = {'other': {'keep': True}}
        if guess.get('prediction', '').strip():
            expected['lesson'] = dict(prediction=guess['prediction'], for_count=last_count, confidence=guess.get('confidence'))
        assert c['extra'] == expected
        state = client.post('/nb/run/state', json=body).json()
        assert state['running'] is False and state['cell'] == c, state
        saved = client.post('/nb/save', json={'path': str(p)})
        assert saved.status_code == 200, saved.text
        back = Notebook.load(p)
        assert back[2].extra == prediction and back[2].source == 'Draft guess'
        assert back[3].extra == expected

@pytest.mark.parametrize('route', ['/nb/run', '/nb/run/stream'])
def test_running_prediction_markdown_keeps_its_metadata(lesson_client, route):
    client, ws, p, nb = lesson_client
    r = client.post(route, json=dict(path=str(p), i=2, id=nb[2].id))
    assert r.status_code == 200, r.text
    state = client.post('/nb/run/state', json=dict(path=str(p), id=nb[2].id)).json()
    assert state['cell']['extra'] == nb[2].extra
    assert state['cell']['execution_count'] is None

@pytest.mark.parametrize('route', ['/nb/run', '/nb/run/stream'])
def test_a_raising_cell_still_locks_its_prediction(lesson_client, route):
    client, ws, p, nb = lesson_client
    r = client.post(route, json=dict(path=str(p), i=3, id=nb[3].id, source='1 / 0', prediction='0', confidence=10))
    assert r.status_code == 200, r.text
    done = (json.loads(r.text.split('event: done\ndata: ', 1)[1].split('\n\n', 1)[0])
            if route.endswith('/stream') else r.json())
    assert not done['ok'] and done['cell']['execution_count'] is not None, done
    assert done['cell']['extra']['lesson'] == dict(prediction='0', confidence=10, for_count=done['cell']['execution_count'])

def test_agent_run_keeps_the_old_prediction_count(lesson_client, monkeypatch):
    client, ws, p, nb = lesson_client
    r = client.post('/nb/run', json=dict(path=str(p), i=3, id=nb[3].id, prediction='42', confidence=90))
    assert r.status_code == 200, r.text
    locked = r.json()['cell']
    assert locked['extra']['lesson']['for_count'] == locked['execution_count']
    saved = client.post('/nb/save', json={'path': str(p)})
    assert saved.status_code == 200, saved.text
    host, seen = ws.inline_ai.host, []
    report = host._cell_report
    def capture(path, cell, before, k=None):
        seen.append(cell)
        return report(path, cell, before, k)
    monkeypatch.setattr(host, '_cell_report', capture)
    out = host.nb_run_cell(str(p), nb[3].id, 60)
    assert 'ran cell' in out and '42' in out, out
    assert len(seen) == 1
    assert seen[0].extra['lesson'] == locked['extra']['lesson']
    assert seen[0].extra['lesson']['for_count'] != seen[0].execution_count
    assert Notebook.load(p)[3].extra['lesson'] == locked['extra']['lesson']

MOTION = Path(__file__).parents[1]/'leela'/'blocks'/'nb'/'motion.js'
RUN_HARNESS = r'''
const vm = require('vm'), fs = require('fs');
const cases = JSON.parse(process.argv[2]);
(async () => {
  const bodies = [];
  for (const row of cases) {
    const c = {id: 'code', cell_type: 'code', source: 'print(42)'};
    const prediction = {id: 'guess', cell_type: 'markdown', source: 'stored', extra: {lesson: {role: 'prediction', for: c.id, ...row.meta}}};
    const decoy = {id: 'decoy', cell_type: 'markdown', source: 'wrong', extra: {lesson: {role: 'prediction', for: 'other'}}};
    const card = {id: 'card', cell_type: 'markdown', source: 'wrong', extra: {lesson: {role: 'card', for: c.id}}};
    const editors = new Map(row.live ? [[prediction.id, {text: 'live guess'}]] : []);
    const ctx = {console, Map, Set, JSON, Math, performance, setInterval, clearInterval,
      lee: {tabKey: 'lesson', cells: [decoy, card, c, ...(row.missing ? [] : [prediction])], editors},
      LeeCM: {getDoc: v => v.text}, nextSeq: () => 1, seenRow: () => ({}), ensureCellMounted: () => null,
      $: () => ({textContent: '', classList: {add() {}, remove() {}}}),
      setCellState() {}, setCellTime() {}, status() {}, leeVars() {}, widgetWatch: async () => {},
      withPython: go => go(), postEvents: async (url, body, cb) => { bodies.push({url, body}); ctx.lee.tabKey = 'changed'; cb('done', {ok: true, cell: c}); }
    };
    ctx.window = ctx; vm.createContext(ctx);
    vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
    await ctx.runCell(2, false);
  }
  console.log(JSON.stringify(bodies));
})().catch(e => { console.error(e); process.exit(1); });
'''

def test_run_cell_posts_the_linked_live_prediction_and_optional_confidence():
    node = shutil.which('node')
    if not node: pytest.skip('node is not installed')
    cases = [dict(live=True, meta={'confidence': 70}), dict(live=False, meta={}), dict(live=False, meta={}, missing=True)]
    r = subprocess.run([node, '-e', RUN_HARNESS, str(MOTION), json.dumps(cases)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    rows = json.loads(r.stdout.strip().splitlines()[-1])
    assert all(row['url'] == '/nb/run/stream' for row in rows)
    assert rows[0]['body']['prediction'] == 'live guess' and rows[0]['body']['confidence'] == 70
    assert rows[1]['body']['prediction'] == 'stored' and 'confidence' not in rows[1]['body']
    assert not rows[2]['body'].get('prediction') and 'confidence' not in rows[2]['body']
