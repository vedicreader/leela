import json, shutil, subprocess
from pathlib import Path
import pytest

ROOT = Path(__file__).parents[1]
HARNESS = r'''const vm = require('vm'), fs = require('fs'), [core, texparts] = process.argv.slice(1);
const src = fs.readFileSync(core, 'utf8'), code = src.slice(src.indexOf('const katexLoad'), src.indexOf('const rupakaRendered')), tex = require(texparts);
const make = ({parts = true, lesson = true} = {}) => {
  const renders = [], window = {katex: {render: (t, m, o) => renders.push([t, m, o])}};
  if (parts) window.abhyasaTex = tex;
  const ctx = {window, renders, console: {warn() {}}, setTimeout, lessonNotebook: () => lesson, $: () => null,
    $$: (sel, root) => sel.includes(':not') ? root.ms.filter(m => !m.dataset.mathed) : root.ms,
    document: {head: {appendChild(n) { if (n.src) setTimeout(() => n.onerror()); }}, createElement: () => ({remove() {}})}};
  vm.createContext(ctx); vm.runInContext(code, ctx); return ctx;
};
const math = (t, display = false) => ({textContent: t, dataset: {}, isConnected: true, classList: {contains: c => display && c === 'display'}});
const host = (ms, md = true) => ({ms, matches: s => md && s === '.lee-md-cell', closest: s => s === '.lee-cell[data-id]' ? {dataset: {i: '2', id: 'x'}} : null});
(async () => { const r = {};
  let c = make(), ms = [math('q=\\bar\\alpha_t'), math('x_t', true)];
  await c.renderMath(host(ms));
  r.lesson = {tex: c.renders.map(x => x[0]), trust: c.renders.map(x => x[2].trust === tex.trust), display: c.renders.map(x => x[2].displayMode),
              ids: ms.map(m => m.dataset.guideId), parts: ms.map(m => JSON.parse(m.dataset.parts ?? '[]'))};
  r.rule = [tex.trust({command: '\\htmlId', id: 'g-1-2'}), tex.trust({command: '\\htmlId', id: 'x'}), tex.trust({command: '\\href', id: 'g-1-2'})];
  for (const [name, o, md] of [['outside', {}, false], ['notLesson', {lesson: false}, true], ['noParts', {parts: false}, true]]) {
    c = make(o); ms = [math('a_t')]; await c.renderMath(host(ms, md));
    r[name] = {tex: c.renders[0][0], trust: c.renders[0][2].trust, parts: ms[0].dataset.parts ?? null, id: ms[0].dataset.guideId ?? null};
  }
  console.log(JSON.stringify(r)); })();'''

def test_lesson_formulas_carry_their_parts_and_trust_only_our_ids():
    node = shutil.which('node')
    if not node: pytest.skip('node is not installed')
    r = subprocess.run([node, '-e', HARNESS, str(ROOT/'leela/static/js/core.js'), str(ROOT/'leela/vendor/lee-texparts.js')], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    les = got['lesson']
    assert all(t.count(r'\htmlId{g-3001-') + t.count(r'\htmlId{g-3002-') for t in les['tex']), 'ids carry the cell: two cells never share a part id'
    assert r'\htmlId{g-3001-1}{\bar\alpha_t}' in les['tex'][0] and les['trust'] == [True, True] and les['display'] == [False, True] and les['ids'] == ['f1', 'f2']
    assert r'\bar\alpha_t' in [p[0] for p in les['parts'][0]] and all(i.startswith('g-3001-') for _, i in les['parts'][0]) and all(i.startswith('g-3002-') for _, i in les['parts'][1])
    assert got['rule'] == [True, False, False]
    for name in ('outside', 'notLesson'):
        assert got[name] == dict(tex='a_t', trust=False, parts=None, id=None), name
    assert got['noParts'] == dict(tex='a_t', trust=False, parts=None, id='f1'), 'a lesson formula keeps its id for the guide when texparts did not load, and has no parts'