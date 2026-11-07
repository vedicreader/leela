import json, shutil, subprocess
from pathlib import Path
import pytest

ROOT = Path(__file__).parents[1]
FAKE = r'''
const vm = require('vm'), fs = require('fs');
class El {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.className = ''; this.textContent = ''; this.disabled = false; }
  appendChild(c) { this.children.push(c); return c; }
  replaceChildren(...kids) { this.children = kids; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  all() { return [this, ...this.children.flatMap(c => c.all())]; }
  set innerHTML(v) { throw Error('server text must not use innerHTML'); }
}
const text = e => e.all().map(x => x.textContent).filter(Boolean).join(' ');
'''
HARNESS = FAKE + r'''
const out = [];
for (const {cell, result} of JSON.parse(process.argv[2])) {
  const host = new El('div');
  const ctx = {console, CSS: {escape: s => s}, lee: {tabKey: 't', cells: [cell], exerciseResults: new Map()},
    document: {createElement: t => new El(t)}, $: () => host};
  ctx.window = ctx; vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
  if (result) ctx.lee.exerciseResults.set('t:' + cell.id, {result});
  ctx.renderExercise(cell, host);
  const all = host.all(), has = cls => all.filter(e => e.className.split(' ').includes(cls));
  out.push({
    rows: has('lee-ex-row').map(e => ({status: e.attrs['data-status'], text: text(e), mark: text(has('lee-ex-mark').find(m => e.all().includes(m)))})),
    grade: has('lee-ex-grade').map(text), stale: has('lee-ex-note').map(text), summary: has('lee-ex-summary').map(text),
    buttons: all.filter(e => e.tag === 'button').map(e => ({text: e.textContent, label: e.attrs['aria-label'], type: e.type, disabled: e.disabled})),
    tutor: result ? ctx.exerciseTutorMessage(cell, result) : '',
  });
}
console.log(JSON.stringify(out));
'''

TESTS = [dict(say='A positive number', shown=True), dict(say='A negative number', shown=False), dict(say='<img onerror=bad>', shown=False)]
GRADE = dict(score=8, note='Clear and short.', hash='abc')
CHECKS = [dict(i=0, say='A positive number', status='pass', message='Passes.'),
          dict(i=1, say='A negative number', status='fail', message='Does not match yet.'),
          dict(i=2, say='<img onerror=bad>', status='timeout', message='Took too long.')]
SHOWN_FAIL = dict(i=0, say='A positive number', status='fail', message='Does not match yet. It returned 999777.', got='999777')

def cell(**kw): return dict(id='code', cell_type='code', source='x', graded_current=True,
                            extra=dict(exercise=dict(tests=TESTS, state=dict(grade=GRADE)))) | kw
def result(checks, **kw): return dict(state='done', summary='1 of 3 checks pass.', passed=1, total=3, source='x', checks=checks, **kw)

CHECKING = FAKE + r'''
const [cell, verdict, fail] = JSON.parse(process.argv[2]), host = new El('div'), calls = [], busy = [], view = {doc: cell.source};
const ctx = {console, CSS: {escape: s => s}, lee: {tabKey: 't', cells: [cell], editors: new Map([[cell.id, view]]), path: 'n.ipynb', exerciseResults: new Map()},
  document: {createElement: t => new El(t)}, $: s => s.startsWith('.lee-exercise') ? host : s.startsWith('#g-') ? {} : null,
  LeeCM: {getDoc: v => v.doc}, ensureCellMounted: () => view, renderOutputs() {}, setCellState() {}, status() {}, leeVars() {},
  nextSeq: () => 7, seenRow: () => ({}), saveTab: async () => true, autoSaveEnabled: () => false, withPython: go => go(),
  post: async (url, body) => { calls.push([url, body]); busy.push(host.all().find(e => e.tag === 'button').attrs['aria-busy'], cell.running); if (fail) throw Error(fail); view.doc = 'typed meanwhile'; return {...verdict, cell: {...cell, source: body.source, execution_count: 3}}; }};
ctx.window = ctx; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
const first = ctx.checkExercise(cell.id); ctx.checkExercise(cell.id);
first.then(() => {
  const all = host.all(), has = cls => all.filter(e => e.className.split(' ').includes(cls)).map(text);
  console.log(JSON.stringify({calls, busy, running: cell.running, source: cell.source, graded: cell.graded_current, rows: has('lee-ex-row').length,
    stale: has('lee-ex-note'), error: has('lee-ex-error'), ask: all.filter(e => e.tag === 'button')[1].disabled}));
});
'''

def checking(cell, verdict, fail=''):
    node = shutil.which('node')
    if not node: pytest.skip('node is not installed')
    r = subprocess.run([node, '-e', CHECKING, str(ROOT/'leela/blocks/nb/exercise.js'), json.dumps([cell, verdict, fail])], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])

def test_check_sends_the_live_source_once_and_keeps_what_was_typed_while_it_ran():
    got = checking(cell(source='attempt'), result(CHECKS))
    assert len(got['calls']) == 1
    url, body = got['calls'][0]
    assert url == '/exercise/check' and body == dict(i=0, id='code', path='t', source='attempt', seq=7)
    assert got['busy'] == ['true', True] and got['running'] is False
    assert got['source'] == 'typed meanwhile' and got['graded'] is False and got['rows'] == 3
    assert 'out of date' in got['stale'][0].lower() and got['ask'] is True

def test_a_refused_check_shows_why_and_leaves_the_cell_free():
    got = checking(cell(source='attempt'), result(CHECKS), fail='Another run is in progress.')
    assert got['error'] == ['Another run is in progress.'] and got['rows'] == 0 and got['running'] is False

def render(*cases):
    node = shutil.which('node')
    if not node: pytest.skip('node is not installed')
    r = subprocess.run([node, '-e', HARNESS, str(ROOT/'leela/blocks/nb/exercise.js'), json.dumps(cases)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])

def test_the_list_shows_a_mark_a_label_and_the_message_per_check_and_never_a_hidden_got():
    page, = render(dict(cell=cell(), result=result([SHOWN_FAIL, *CHECKS[1:]])))
    assert [r['status'] for r in page['rows']] == ['fail', 'fail', 'timeout']
    assert [r['mark'] for r in page['rows']] == ['✗', '✗', '…']
    shown, hidden, odd = [r['text'] for r in page['rows']]
    assert 'A positive number' in shown and 'It returned 999777.' in shown
    assert 'A negative number' in hidden and 'returned' not in hidden
    assert odd.startswith('…') and '<img onerror=bad>' in odd
    assert page['summary'] == ['1 of 3 checks pass.']
    passing, = render(dict(cell=cell(), result=result(CHECKS[:1])))[0]['rows']
    assert passing['status'] == 'pass' and passing['mark'] == '✓' and 'Passes.' in passing['text']

def test_the_grade_shows_for_the_graded_source_and_is_hidden_for_an_earlier_one():
    current, earlier, none = render(dict(cell=cell(), result=None), dict(cell=cell(graded_current=False), result=None),
                                    dict(cell=dict(cell(), extra=dict(exercise=dict(tests=TESTS, state={}))), result=None))
    assert current['grade'] == ['Grade 8/10. Clear and short.']
    assert earlier['grade'] == [] and none['grade'] == []

def test_the_buttons_are_labelled_and_a_result_for_changed_code_is_marked_and_not_sent_to_the_tutor():
    fresh, edited, never = render(dict(cell=cell(), result=result(CHECKS)), dict(cell=cell(source='y'), result=result(CHECKS)), dict(cell=cell(), result=None))
    for page in (fresh, edited, never):
        check, ask = page['buttons']
        assert check['text'] == 'Check' and check['label'] == 'Check my code' and check['type'] == 'button' and not check['disabled']
        assert ask['text'] == 'Ask the tutor' and ask['label'].startswith('Ask the tutor') and ask['type'] == 'button'
    assert [p['buttons'][1]['disabled'] for p in (fresh, edited, never)] == [False, True, True]
    assert fresh['stale'] == [] and 'out of date' in edited['stale'][0].lower() and never['stale'] == []
    assert never['rows'] == []
    for label in ('A positive number', 'A negative number', '1 of 3 checks pass.', 'cell 1 (id code)'): assert label in fresh['tutor']
