import shutil, subprocess
from pathlib import Path
import pytest

NB = Path(__file__).parents[1]/'leela'/'blocks'/'nb'

LESSON = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const [file, scenario] = process.argv.slice(1);
class El {
  constructor(tag) { this.tag = tag; this.children = []; this.style = {}; this.dataset = {}; this.attrs = {}; this.textContent = ''; this.className = ''; this.hidden = false; this.disabled = false; this.parent = null;
    this.classList = {contains: c => this.className.split(' ').includes(c)}; }
  append(...n) { for (const c of n) { c.parent = this; this.children.push(c); } }
  appendChild(c) { this.append(c); return c; }
  replaceChildren(...n) { this.children = []; this.append(...n); }
  after(c) { const p = this.parent; c.parent = p; p.children.splice(p.children.indexOf(this) + 1, 0, c); }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(c => c !== this); this.parent = null; }
  setAttribute(k, v) { this.attrs[k] = v; }
  getRootNode() { let n = this; while (n.parent) n = n.parent; return n; }
  matches() { return false; }
  all(pred, out = []) { for (const c of this.children) { if (pred(c)) out.push(c); c.all(pred, out); } return out; }
}
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const RETRY = 'Leela did not save this. Try again.', LATE = 'This demo changed while saving. Try again.', OK = {ok: true, logged: true, message: 'Saved.'};
const tick = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); await new Promise(r => setTimeout(r, 0)); };
const bodyOf = (ctx, url, n = 0) => ctx.posts.filter(p => p[0] === url)[n]?.[1];
const urls = ctx => ctx.posts.map(p => p[0]);
function make(store = new Map(), storage = true) {
  const ctx = {posts: [], said: [], mounts: [], replies: {}, calls: [], prompt: {value: ''}};
  Object.assign(ctx, {AbortController, console: {warn() {}}, CSS: {escape: s => s}, document: {createElement: t => new El(t), addEventListener() {}},
    lee: {path: '/n.ipynb', tabKey: 'tab', nbQueue: Promise.resolve(), cells: [{id: 'c1', cell_type: 'markdown', extra: {lesson: {}}}]},
    srcHash: async s => 'h:' + s, status: (t, k) => ctx.said.push([k, t]), $: sel => sel === '#agentprompt' ? ctx.prompt : null, $$: () => [],
    leeAct() {}, sendAgent() { ctx.calls.push('agent'); },
    Rupaka: {state: h => JSON.parse(JSON.stringify(h.rupaka.inputs)), mount: (el, spec) => { el.rupaka = {inputs: {}, st: {gate: {}}}; ctx.mounts.push(spec); }, settle: () => true},
    rupakaMount: (el, spec, opts) => ctx.Rupaka.mount(el, spec, opts)});   // core.js's, which this file runs without
  ctx.sessionStorage = storage ? {getItem: k => store.has(k) ? store.get(k) : null, setItem: (k, v) => { store.set(k, v); }}
    : {getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); }};
  ctx.post = async (url, body) => {
    ctx.posts.push([url, JSON.parse(JSON.stringify(body))]);
    const q = ctx.replies[url] || [{ok: true}], r = q.length > 1 ? q.shift() : q[0], v = typeof r === 'function' ? await r(body) : r;
    if (v instanceof Error) throw v; return v; };
  vm.createContext(ctx); vm.runInContext(fs.readFileSync(file, 'utf8'), ctx);
  return ctx;
}
function stage(ctx, source = 'x', inputs = {a: 30, t: .5}) {
  const host = new El('div'); host.className = 'lee-rupaka'; host.leeSource = source;
  const shadow = host.shadowRoot = new El('#shadow'); shadow.host = host;
  const inner = new El('div'); inner.rupaka = {inputs, st: {gate: {g: 'open'}}}; shadow.append(inner);
  const strip = new El('div'); shadow.append(strip);
  const cell = {matches: s => s.startsWith('.lee-cell'), dataset: {id: 'c1'}};
  const event = (via, detail = {}, settle = true) => {
    const ev = {settled: [], held: false, detail: {demo: 'throw-angle', gate: 'g', picked: 60, ans: 60, ok: true, why: '', ...detail},
      composedPath: () => [...via, shadow, host, cell], preventDefault() { ev.held = true; }};
    if (settle) ev.detail.settle = (...a) => ev.settled.push(a);
    return ev; };
  return {host, shadow, inner, strip, cell, event};
}
const CREATED = {ok: true, transfer_id: 't1', spec: {id: 'throw-angle-new', blocks: []}};
async function transfer(ctx, s) {
  ctx.ack = () => ({ok: true, aided: false, correct: true, message: 'Right.'});
  ctx.replies['/lesson/transfer'] = [body => body.transfer_id ? ctx.ack(body) : CREATED];
  const offer = ctx.lessonTransferOffer(s.inner, {id: 'throw-angle'}, {src: 'h:x'}, () => ctx.lee.cells[0]);
  s.strip.append(offer.button); offer.paint(true); await offer.button.onclick();
  const box = s.shadow.all(c => c.className === 'lee-rupaka-transfer')[0], q = box.all(c => c.rupaka)[0];
  const lock = (picked = 70) => s.event([q, box], {demo: 'throw-angle-new', gate: 't', picked, ans: 70});
  const submits = () => ctx.posts.filter(p => p[0] === '/lesson/transfer' && p[1].transfer_id).map(p => p[1]);
  return {offer, box, q, lock, submits};
}
const SCENARIOS = {
  async evidence() {
    const store = new Map(), ctx = make(store), s = stage(ctx);
    ctx.replies['/lesson/predict'] = [new TypeError('Failed to fetch'), OK];
    let release; ctx.lee.nbQueue = new Promise(r => { release = r; });
    const first = s.event([s.inner]), p = ctx.lessonPredict(first);
    s.inner.rupaka.inputs.a = 75; release(); await p;
    const one = bodyOf(ctx, '/lesson/predict', 0);
    assert.deepStrictEqual(one.inputs, {a: 30, t: .5}); assert.match(one.evidence_id, UUID); assert.deepStrictEqual(one.assistance, []);
    assert.deepStrictEqual(first.settled, [[false, RETRY]]);
    const again = s.event([s.inner]); await ctx.lessonPredict(again);
    assert.equal(bodyOf(ctx, '/lesson/predict', 1).evidence_id, one.evidence_id); assert.deepStrictEqual(again.settled, [[true]]);
    const other = stage(ctx, 'y'); await ctx.lessonPredict(other.event([other.inner]));
    assert.notEqual(bodyOf(ctx, '/lesson/predict', 2).evidence_id, one.evidence_id);
    const reload = make(store), r = stage(reload); await reload.lessonPredict(r.event([r.inner]));
    assert.equal(bodyOf(reload, '/lesson/predict').evidence_id, one.evidence_id);
  },
  async 'storage-denied'() {
    const ctx = make(new Map(), false), s = stage(ctx);
    await ctx.lessonPredict(s.event([s.inner])); await ctx.lessonPredict(s.event([s.inner]));
    const [a, b] = [0, 1].map(n => bodyOf(ctx, '/lesson/predict', n).evidence_id);
    assert.match(a, UUID); assert.equal(a, b);
  },
  async assistance() {
    const ctx = make(), s = stage(ctx); await ctx.lessonGuide('c1', '', 'why?');
    await ctx.lessonPredict(s.event([s.inner]));
    assert.deepStrictEqual(bodyOf(ctx, '/lesson/predict').assistance, ['tutor']); assert.equal(urls(ctx).includes('/lesson/assist'), false);
  },
  async refused() {
    const ctx = make(), s = stage(ctx);
    ctx.replies['/lesson/predict'] = [{ok: false, error: 'No.'}, {}];
    const a = s.event([s.inner]), b = s.event([s.inner]); await ctx.lessonPredict(a); await ctx.lessonPredict(b);
    assert.deepStrictEqual(a.settled, [[false, 'No.']]); assert.deepStrictEqual(b.settled, [[false, RETRY]]);
    assert.deepStrictEqual(ctx.said, [['err', 'No.'], ['err', RETRY]]);
  },
  async late() {
    for (const change of ['tab', 'source']) {
      const ctx = make(), s = stage(ctx);
      ctx.replies['/lesson/predict'] = [() => { if (change === 'tab') ctx.lee.tabKey = 'other'; else s.host.leeSource = 'changed'; return {...OK, explanation: {id: 'e1', status: 'pending'}}; }];
      const ev = s.event([s.inner], {why: 'Because.'}); await ctx.lessonPredict(ev); await tick();
      assert.deepStrictEqual(ev.settled, [[false, LATE]], change); assert.deepStrictEqual(ctx.said, [], change);
      assert.equal(urls(ctx).includes('/lesson/explanation'), false, change);
    }
  },
  async explained() {
    const ctx = make(), s = stage(ctx);
    ctx.replies['/lesson/predict'] = [{...OK, explanation: {id: 'e1', status: 'pending'}}];
    ctx.replies['/lesson/explanation'] = [new TypeError('offline'), {ok: true, status: 'graded'}];
    const ev = s.event([s.inner], {why: 'Because.'}); await ctx.lessonPredict(ev); await tick();
    assert.deepStrictEqual(ev.settled, [[true]]); assert.deepStrictEqual(ctx.said, [['ok', 'Saved.']]);
    assert.deepStrictEqual(bodyOf(ctx, '/lesson/explanation'), bodyOf(ctx, '/lesson/predict'));
    const row = s.shadow.all(c => c.className === 'lee-rupaka-explain')[0], [text, retry] = row.children;
    assert.equal(text.textContent, 'Explanation: not graded yet'); assert.equal(retry.hidden, false); assert.equal(retry.textContent, 'Retry grading');
    await retry.onclick(); await tick();
    assert.equal(text.textContent, 'Explanation: graded'); assert.equal(retry.hidden, true);
    assert.equal(urls(ctx).filter(u => u === '/lesson/explanation').length, 2);
    assert.deepStrictEqual(ctx.said, [['ok', 'Saved.']]);
  },
  async 'explain-refused'() {
    const ctx = make(), s = stage(ctx);
    ctx.replies['/lesson/predict'] = [{...OK, explanation: {id: 'e1', status: 'pending'}}];
    ctx.replies['/lesson/explanation'] = [{ok: false}];
    const ev = s.event([s.inner], {why: 'Because.'}); await ctx.lessonPredict(ev); await tick();
    assert.deepStrictEqual(ev.settled, [[true]]);
    const row = s.shadow.all(c => c.className === 'lee-rupaka-explain')[0], [text, retry] = row.children;
    assert.equal(text.textContent, 'Explanation: not graded yet'); assert.equal(retry.hidden, false);
    const plain = make(), t = stage(plain); plain.replies['/lesson/predict'] = [OK];
    await plain.lessonPredict(t.event([t.inner], {why: 'Because.'})); await tick();
    assert.equal(urls(plain).includes('/lesson/explanation'), false);
  },
  async transfer() {
    const ctx = make(), s = stage(ctx), offer = ctx.lessonTransferOffer(s.inner, {id: 'throw-angle'}, {src: 'h:x'}, () => ctx.lee.cells[0]);
    assert.equal(offer.button.textContent, 'Try a new case'); offer.paint(false); assert.equal(offer.button.disabled, true);
    const other = ctx.lessonTransferOffer(s.inner, {id: 'softmax-temperature'}, {src: 'h:x'}, () => ctx.lee.cells[0]); assert.equal(other, null);
    const t = await transfer(ctx, s);
    assert.deepStrictEqual(bodyOf(ctx, '/lesson/transfer', 0), {path: '/n.ipynb', cell_id: 'c1', demo: 'throw-angle', src: 'h:x'});
    assert.equal(ctx.mounts[0].id, 'throw-angle-new'); assert.equal(s.inner.style.display, 'none'); assert.equal(s.strip.style.display, 'none'); assert.notEqual(t.box.style.display, 'none');
    ctx.ack = () => new TypeError('Failed to fetch');
    let ev = t.lock(); const p = ctx.lessonPredict(ev); assert.equal(ev.held, true); assert.deepStrictEqual(ev.settled, []); await p;
    assert.deepStrictEqual(ev.settled, [[false, RETRY]]);
    ctx.ack = () => ({ok: false, error: 'Not yet.'}); ev = t.lock(); await ctx.lessonPredict(ev); assert.deepStrictEqual(ev.settled, [[false, 'Not yet.']]);
    ctx.ack = () => ({ok: true, aided: false, correct: true, message: 'Right.'}); ev = t.lock(); await ctx.lessonPredict(ev);
    assert.deepStrictEqual(ev.settled, [[true]]); assert.deepStrictEqual(ctx.said.at(-1), ['ok', 'Right.']);
    assert.deepStrictEqual(t.submits().at(-1), {path: '/n.ipynb', cell_id: 'c1', demo: 'throw-angle', src: 'h:x', transfer_id: 't1', picked: 70, assistance: []});
    assert.equal(urls(ctx).includes('/lesson/predict'), false); assert.equal(urls(ctx).includes('/lesson/assist'), false);
  },
  async 'transfer-late'() {
    const ctx = make(), s = stage(ctx), t = await transfer(ctx, s);
    ctx.ack = () => { ctx.lee.tabKey = 'other'; return {ok: true, message: 'Right.'}; };
    const ev = t.lock(); await ctx.lessonPredict(ev);
    assert.deepStrictEqual(ev.settled, [[false, LATE]]); assert.equal(ctx.said.length, 0);
  },
  async return() {
    const ctx = make(), s = stage(ctx), t = await transfer(ctx, s);
    const back = t.box.all(c => c.textContent === 'Return to demo')[0]; let seen;
    ctx.replies['/lesson/assist'] = [new TypeError('offline'), () => { seen = s.inner.style.display; return {ok: true}; }];
    await back.onclick();
    assert.equal(s.inner.style.display, 'none'); assert.notEqual(t.box.style.display, 'none');
    assert.deepStrictEqual(bodyOf(ctx, '/lesson/assist', 0), {path: '/n.ipynb', cell_id: 'c1', kind: 'reveal'});
    await back.onclick();
    assert.equal(seen, 'none'); assert.equal(s.inner.style.display || '', ''); assert.equal(s.strip.style.display || '', ''); assert.equal(t.box.style.display, 'none');
    t.offer.paint(true); await t.offer.button.onclick();
    assert.equal(ctx.posts.filter(p => p[0] === '/lesson/transfer' && !p[1].transfer_id).length, 1);
    assert.equal(s.inner.style.display, 'none'); assert.notEqual(t.box.style.display, 'none');
    await ctx.lessonPredict(t.lock()); assert.deepStrictEqual(t.submits().at(-1).assistance, ['reveal']);
  },
  async 'tutor-guide'() {
    const ctx = make(), s = stage(ctx); await ctx.lessonGuide('c1', '', 'before the new case');
    const t = await transfer(ctx, s);
    await ctx.lessonGuide('c1', '', 'why?'); await tick();
    assert.ok(ctx.posts.some(p => p[0] === '/lesson/assist' && p[1].kind === 'tutor'));
    await ctx.lessonPredict(t.lock()); assert.deepStrictEqual(t.submits().at(-1).assistance, ['tutor']);
  },
  async 'tutor-agent'() {
    const ctx = make(), s = stage(ctx); ctx.lee.cells[0].extra.lesson.role = 'prediction';
    const t = await transfer(ctx, s), ask = {detail: {text: 'why?', demo: 'throw-angle'}, composedPath: () => [s.inner, s.shadow, s.host, s.cell], preventDefault() {}};
    await ctx.lessonAsk(ask); assert.deepStrictEqual(ctx.calls, ['agent']);
    await ctx.lessonPredict(t.lock()); assert.deepStrictEqual(t.submits().at(-1).assistance, ['tutor']);
  },
};
SCENARIOS[scenario]().catch(e => { console.error(e); process.exitCode = 1; });
'''

TRIALS = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const [file, scenario] = process.argv.slice(1);
class El {
  constructor(tag) { this.tag = tag; this.children = []; this.style = {}; this.attrs = {}; this.textContent = ''; this.parent = null; }
  append(...n) { for (const c of n) { c.parent = this; this.children.push(c); } }
  replaceChildren(...n) { this.children = []; this.append(...n); }
  after(c) { const p = this.parent; c.parent = p; p.children.splice(p.children.indexOf(this) + 1, 0, c); }
  setAttribute(k, v) { this.attrs[k] = v; }
}
const src = fs.readFileSync(file, 'utf8'), code = src.slice(src.indexOf('function rupakaTrials'), src.indexOf('const mdPaint'));
const ready = [], ctx = {document: {createElement: t => new El(t)}, console: {warn() {}}, Rupaka: {mount(el) { el.rupaka = {get: () => 1}; }, set() {}, state: () => ({})},
  rupakaMount: (el, spec, opts) => ctx.Rupaka.mount(el, spec, opts)};   // core.js's, which this slice runs without
const button = new El('button');
if (scenario === 'offer') ctx.lessonTransferOffer = (...a) => { ctx.offered = a; return {button, paint: r => ready.push(r)}; };
vm.createContext(ctx); vm.runInContext(code, ctx);
const parent = new El('div'), inner = new El('div'); parent.append(inner); inner.rupaka = {st: {gate: {g: 'open'}}, on() {}};
const record = {trials: []}, entry = {src: 'h', options: {save() {}}}, spec = {id: 'throw-angle', blocks: []};
ctx.rupakaTrials(inner, spec, entry, () => ({extra: {rupaka: {'throw-angle': record}}}));
const strip = parent.children[1];
assert.ok(strip && strip.children.length >= 3);
if (scenario === 'offer') {
  assert.ok(strip.children.includes(button)); assert.equal(ctx.offered[0], inner); assert.equal(ctx.offered[1], spec); assert.equal(ctx.offered[2], entry);
  assert.equal(ready.at(-1), false);
  inner.rupaka.st.gate.g = 'done'; entry.paint(); assert.equal(ready.at(-1), false);
  record.trials = [{n: 1, src: 'other', inputs: {}}]; entry.paint(); assert.equal(ready.at(-1), false);
  record.trials = [{n: 1, src: 'h', inputs: {}}]; entry.paint(); assert.equal(ready.at(-1), true);
  inner.rupaka.st.gate.g = 'open'; entry.paint(); assert.equal(ready.at(-1), false);
}
'''


def run(harness, path, scenario):
    node = shutil.which('node')
    if not node: pytest.skip('node is not installed')
    r = subprocess.run([node, '-e', harness, str(path), scenario], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize('scenario', ['evidence', 'storage-denied', 'assistance'])
def test_prediction_sends_stable_evidence_frozen_inputs_and_assistance(scenario):
    run(LESSON, NB/'lesson.js', scenario)


@pytest.mark.parametrize('scenario', ['refused', 'late'])
def test_prediction_reply_is_checked_and_a_late_reply_is_not_taken(scenario):
    run(LESSON, NB/'lesson.js', scenario)


@pytest.mark.parametrize('scenario', ['explained', 'explain-refused'])
def test_explanation_grades_after_the_save_and_never_fails_it(scenario):
    run(LESSON, NB/'lesson.js', scenario)


@pytest.mark.parametrize('scenario', ['transfer', 'transfer-late', 'return'])
def test_new_case_stays_off_the_prediction_route_and_settles_after_the_ack(scenario):
    run(LESSON, NB/'lesson.js', scenario)


@pytest.mark.parametrize('scenario', ['tutor-guide', 'tutor-agent'])
def test_tutor_use_since_the_new_case_is_assistance(scenario):
    run(LESSON, NB/'lesson.js', scenario)


@pytest.mark.parametrize('scenario', ['offer', 'none'])
def test_trials_strip_offers_the_new_case_after_its_paint(scenario):
    run(TRIALS, NB/'cells.js', scenario)
