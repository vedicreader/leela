"rupaka demos in notebooks: the vendored bundle, the fence the server hands back, and the client's routing of fences, outputs and keys."
import json, shutil, subprocess
from pathlib import Path
import pytest
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.workspace import Workspace

ROOT = Path(__file__).parents[1]/'leela'
SPEC = {'blocks': [{'type': 'text', 'text': 'hi'}]}

def test_the_vendored_rupaka_is_the_version_the_readme_pins():
    "A stale or half-copied vendor file fails here, not in a user's notebook."
    import rupaka
    from rupaka.render import bundle
    v = rupaka.__version__
    assert f'rupaka-{v}-py3-none-any.whl' in (ROOT/'vendor'/'README').read_text()
    for kind in ('js', 'css'): assert (ROOT/'vendor'/f'lee-rupaka.{kind}').read_text() == bundle(kind), f'lee-rupaka.{kind} is not the {v} wheel: write it again (leela/vendor/README)'

@pytest.mark.parametrize('hl', ['spans', None])
def test_a_rupaka_fence_reaches_the_browser_as_a_language_class(monkeypatch, hl):
    "The client finds fences by `code.language-rupaka`; mdhtml has no such language, so it must leave the text alone."
    import leela.app
    monkeypatch.setattr(leela.app, 'MD_HIGHLIGHT', hl)
    text = '```rupaka\n' + json.dumps(SPEC) + '\n```\n'
    with TestClient(ide_app(Workspace(roots=[]))) as c:
        html = c.post('/markdown/render', json={'text': text, 'allow_raw': True}).json()['html']
    assert 'class="language-rupaka"' in html and '<pre><code' in html and json.dumps(SPEC) in html.replace('&quot;', '"')

# core.js's rupaka block, cells.js's outputEl and keymap.js's eventContext in Node, with a small fake DOM that records.
HARNESS = r'''
const vm = require('vm'), fs = require('fs');
const [root, scenario] = [process.argv[1], process.argv[2]];
const read = p => fs.readFileSync(root + '/' + p, 'utf8');
const grab = (src, name) => { const m = src.match(new RegExp('^function ' + name + '\\b[\\s\\S]*?^}\\n', 'm')); return m ? m[0] : ''; };
const core = read('static/js/core.js'), a = core.indexOf('const RUPAKA_MIME'), b = core.indexOf('/* This copies an answer');
const cells = read('blocks/nb/cells.js'), keymap = read('blocks/keys/keymap.js');
const calls = {mount: [], frame: [], load: 0, css: 0};
class N {
  constructor(tag) { this.tag = tag; this.children = []; this.parentElement = null; this.className = ''; this.dataset = {}; this.textContent = ''; this.events = [];
    this.classList = {add: c => { this.className = (this.className + ' ' + c).trim(); }}; }
  get nextElementSibling() { const s = this.parentElement?.children; return s ? s[s.indexOf(this) + 1] || null : null; }
  get isConnected() { let n = this; while (n.parentElement) n = n.parentElement; return !!n.root; }
  matches(sel) { const cl = this.className.split(/\s+/); return sel.split(',').some(s => cl.includes(s.trim().slice(1))); }
  remove() { const s = this.parentElement?.children; if (s) s.splice(s.indexOf(this), 1); this.parentElement = null; }
  append(...ns) { for (const n of ns) { n.remove(); n.parentElement = this; this.children.push(n); } }
  prepend(...ns) { this.append(...ns); }
  after(n) { n.remove(); const s = this.parentElement.children; s.splice(s.indexOf(this) + 1, 0, n); n.parentElement = this.parentElement; }
  replaceWith(n) { const p = this.parentElement, s = p.children; n.remove(); s.splice(s.indexOf(this), 1, n); n.parentElement = p; this.parentElement = null; }
  replaceChildren() { for (const c of this.children) c.parentElement = null; this.children = []; }
  querySelectorAll() { return []; }
  attachShadow() { const r = this.shadowRoot = new N('#shadow'); r.adoptedStyleSheets = []; return r; }
  dispatchEvent(e) { calls.events = (calls.events || []).concat(e.type); return true; }
}
const walk = n => n.children.flatMap(c => [c, ...walk(c)]);
const body = new N('body'); body.root = true;
const head = new N('head'); head.appendChild = n => { calls.load++; setTimeout(() => { ctx.Rupaka = {mount: (h, s) => calls.mount.push(s)}; n.onload(); }, 0); };
const ctx = {
  console, setTimeout, Map, Set, JSON, Promise, Error, Object, String, Element: N, CustomEvent: class { constructor(type) { this.type = type; } },
  window: null, document: {createElement: t => new N(t), head, body},
  CSSStyleSheet: class { replaceSync() {} },
  fetch: async () => { calls.css++; return {ok: true, text: async () => '.rk{}'}; },
  $: () => null, $$: (sel, el) => walk(el).filter(n => n.tag === 'code' && n.className.includes('language-rupaka') && n.parentElement.tag === 'pre'),
  outputTone: () => 'output', WIDGET_MIME: 'w', PLOTLY_MIME: 'p', MAX_OUTPUT_CHARS: 60000, stripAnsi: s => s, outputText() {}, nbBase: () => '', renderMarkdown() {},
  widgetEl: () => 'widget', sandboxFrame: (d, html) => { calls.frame.push(html); return d; }, lee: {present: false, scope: 'editor'},
};
ctx.window = ctx; ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(core.slice(a, b) + grab(cells, 'rupakaEl') + grab(cells, 'outputEl') + grab(keymap, 'eventContext'), ctx);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const fence = (el, text) => { el.replaceChildren(); const pre = new N('pre'), code = new N('code'); code.className = 'language-rupaka'; code.textContent = text; pre.append(code); el.append(pre); return pre; };
const errs = el => el.children.filter(c => c.className.includes('lee-rk-err'));
const SCEN = {
  async mime() {
    const spec = {blocks: []}, o = {output_type: 'display_data', data: {'application/vnd.rupaka+json': spec, 'text/html': '<div></div><script>1</script>'}};
    const d = ctx.outputEl(o); const early = calls.mount.length; await sleep(20);
    return {frame: calls.frame, early, mount: calls.mount, host: d.children.map(c => c.className), events: calls.events};
  },
  async badfence() {
    const el = new N('div'); body.append(el); const out = [];
    fence(el, '{nope'); ctx.rupakaFences(el, 'md:c1'); out.push([errs(el).length, el.children.length]);
    fence(el, '{nope'); ctx.rupakaFences(el, 'md:c1'); ctx.rupakaFences(el, 'md:c1'); out.push([errs(el).length, el.children.length, el.children[0].tag]);
    await sleep(20); return {out, load: calls.load};
  },
  async keepfence() {
    const el = new N('div'); body.append(el), text = JSON.stringify({blocks: []});
    fence(el, text); ctx.rupakaFences(el, 'md:c1'); await sleep(20);
    const first = el.children[0]; fence(el, text); ctx.rupakaFences(el, 'md:c1');
    return {same: el.children[0] === first, class: first.className, mount: calls.mount.length, css: calls.css, load: calls.load};
  },
  async loadfail() {
    ctx.fetch = async () => (calls.css++, {ok: false, status: 404, statusText: 'Not Found'});
    const el = new N('div'); body.append(el), text = JSON.stringify({blocks: []});
    for (let i = 0; i < 3; i++) { fence(el, text); ctx.rupakaFences(el, 'md:c1'); await sleep(20); }
    return {errs: errs(el).length, load: calls.load, css: calls.css, text: errs(el)[0]?.textContent};
  },
  async keys() {
    const btn = new N('button'), host = new N('div'), cell = new N('div'); host.className = 'lee-rupaka'; cell.className = 'lee-cell';
    return {ctx: ctx.eventContext({composedPath: () => [btn, host, cell], target: cell})};
  },
};
SCEN[scenario]().then(r => console.log(JSON.stringify(r)), e => { console.error(e.stack || e); process.exit(1); });
'''

def _run(scenario):
    node = shutil.which('node')
    if not node: pytest.skip('node is not installed')
    r = subprocess.run([node, '-e', HARNESS, str(ROOT), scenario], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])

def test_the_rupaka_mime_is_drawn_not_sent_to_the_html_fallbacks_frame():
    out = _run('mime')
    assert out['frame'] == [], 'the <script> in text/html sent the output to a sandbox frame'
    assert out['early'] == 0 and out['mount'] == [{'blocks': []}], out
    assert out['host'] == ['lee-rupaka'] and 'lee-markdown-rendered' in out['events'], out

def test_a_bad_fence_keeps_its_code_and_gains_one_error_line_however_often_it_is_rendered():
    out = _run('badfence')
    assert out['out'] == [[1, 2], [1, 2, 'pre']] and out['load'] == 0, out

def test_a_rerendered_fence_gets_back_the_demo_already_mounted():
    out = _run('keepfence')
    assert out['same'] and out['class'] == 'lee-rupaka' and out['mount'] == 1 and out['css'] == 1 and out['load'] == 1, out

def test_a_bundle_that_will_not_load_is_one_error_line_and_one_request_of_each_file():
    out = _run('loadfail')
    assert out['errs'] == 1 and out['text'].startswith('rupaka: rupaka.css: 404') and out['load'] == out['css'] == 1, out

def test_keys_inside_a_rupaka_demo_do_not_reach_the_cell():
    assert _run('keys')['ctx'] == 'widget'