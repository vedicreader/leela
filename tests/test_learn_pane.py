import json, re, shutil, subprocess, sys
from pathlib import Path
import pytest
from leela.blocks.learn.learn import is_local, pane_url
from learn_data import JID, rig  # noqa: F401

ROOT = Path(__file__).parents[1]
PANE_JS = ROOT/'leela'/'blocks'/'learn'/'pane.js'
GOOD = ['/learn?walk=a-1&step=0', '/learn/lookup?q=Agent', '/learn?pane=0&walk=a-1#x']
BAD = ['https://evil.example/x', '//evil.example', '/\\evil.example', 'javascript:alert(1)', 'w/g', '', None, '/learn\x00x', '/learn\nx']

def test_is_local_matches_abhyasa():
    from abhyasa.core.pane import is_local as theirs, pane_url as their_url
    for u in GOOD + BAD: assert is_local(u) == theirs(u) and pane_url(u) == their_url(u), u
    assert pane_url('/learn?walk=a-1') == '/learn?walk=a-1&pane=1' and pane_url('//evil.example') is None
    src = (ROOT/'leela'/'blocks'/'learn'/'learn.py').read_text()
    assert "# a copy of abhyasa.core.pane.is_local: abhyasa.core imports abhyasa's web UI (leela-reuse.md 5)" in src
    imports = re.compile(r'^\s*(from|import)\s+abhyasa\.core\b', re.M)
    assert not [p for p in (ROOT/'leela').rglob('*.py') if imports.search(p.read_text())]   # runtime code never imports it

HARNESS = r'''
const [src, cases] = [require('fs').readFileSync(process.argv[1], 'utf8'), JSON.parse(process.argv[2])];
const events = [], posted = [], listens = [], st = {at: [], opened: [], closed: 0};
global.location = {origin: 'http://127.0.0.1:5011', pathname: '/learn', search: '?walk=a-1&pane=1&step=0', hash: '#f'};
global.document = {dispatchEvent: e => events.push([e.type, e.detail]), documentElement: {classList: {contains: () => false}},
  addEventListener: (t, f) => listens.push(t), title: 'Softmax',
  querySelector: s => s === '[data-rh-trail]' ? {dataset: {rhTrail: '[["Attention", "/learn?walk=a-1"]]'}} : null};
global.CustomEvent = class { constructor(t, o) { this.type = t; this.detail = o.detail; } };
global.window = {parent: {postMessage: (m, o) => posted.push([m, o])}};
eval(src);
const frame = {contentWindow: {}};
const host = {frame, trail: [], at: (u, t, trail) => st.at.push([u, t, trail]), open: u => st.opened.push(u), close: () => st.closed++};
const m = (data, origin = location.origin, source = frame.contentWindow) => leePaneMessage({data, origin, source}, host);
const took = [
  m({type: 'rh:at', url: '/learn?walk=a-1&step=0', title: 'Softmax', trail: []}),
  m({type: 'rh:at', url: 'https://evil.example/'}),
  m({type: 'rh:at', url: '/learn', trail: [['Walk', '//evil.example']]}),
  m({type: 'rh:at', url: '/learn', trail: 'Walk'}),
  m({type: 'rh:at', url: '/learn', title: {toString: () => 'x'}}),
  m({type: 'rh:open', url: '//evil.example'}),
  m({type: 'rh:close'}, 'http://evil.example'),
  m({type: 'rh:close'}, location.origin, {}),
  m(undefined), m(null), m('rh:close'), m(['rh:close']), m({type: 'rh:zoom'}), m({type: 'rh:close', level: 2}), m({type: 'rh:close', level: '1'}),
  m({type: 'rh:done', slug: '<img src=x onerror=alert(1)>', outcome: 'passed'}),
  m({type: 'rh:at', url: '/learn/lookup?q=Softmax', title: 'Lookup', trail: [['Attention', '/learn?walk=a-1'], ['Softmax', '/learn?walk=a-1&step=0']]}),
  m({type: 'rh:close', level: 1}),
  m({type: 'rh:at', url: '/learn?walk=a-1&step=0', title: 'Softmax', trail: [['Attention', '/learn?walk=a-1']]}),
  m({type: 'rh:close', level: 1}),
  m({type: 'rh:at', url: '/learn?walk=a-1', title: 'Attention', trail: []}),
  m({type: 'rh:close', level: 1}),
  m({type: 'rh:open', url: '/learn?topic=Softmax'}),
  m({type: 'rh:close'}),
  leePaneMessage({data: {type: 'rh:close'}, origin: location.origin, source: undefined}, {frame: null}),
  leePaneMessage({data: {type: 'rh:close'}, origin: location.origin, source: undefined}, null),
];
const key = (k, t) => leePaneKey({key: k, target: t, preventDefault() {}});
const plain = {isContentEditable: false, matches: () => false}, input = {isContentEditable: false, matches: () => true};
key('Escape', input); key('Escape', {isContentEditable: true, matches: () => false}); key('a', plain);
const before = posted.length; key('Escape', plain); const esc = posted.slice(before);
leePaneAt();
console.log(JSON.stringify({took, st, events, esc, at: posted.at(-1), listens,
  here: leePaneHere(location), own: leeOwnURL('/learn?walk=a-1&pane=1&step=0#f'),
  local: cases.map(leeIsLocal), panes: cases.map(leePaneURL),
  saved: ['', 'null', '{bad', '7', '[]', '{"page": "//evil.example"}', '{"page": 5}', '{"page": "/learn?walk=a-1&pane=1", "title": "Softmax", "direction": "horizontal"}',
          '{"page": "/learn", "title": 3, "direction": "x"}', '{"path": "/a.py", "direction": "vertical"}', '{"path": ""}'].map(leeSavedSplit)}));
'''

def harness():
    node = shutil.which('node')
    if not node: pytest.skip('node is not installed')
    r = subprocess.run([node, '-e', HARNESS, str(PANE_JS), json.dumps(GOOD + BAD)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)

def test_pane_host_takes_only_its_own_frame():
    out = harness()
    assert out['took'] == [True] + [False] * 14 + [True] * 9 + [False, False]
    assert out['st']['at'][0] == ['/learn?walk=a-1&step=0', 'Softmax', []]   # the URL without pane=1
    assert len(out['st']['at']) == 4
    assert out['st']['opened'] == ['/learn?walk=a-1&step=0', '/learn?walk=a-1', '/learn?topic=Softmax']   # back one level each time
    assert out['st']['closed'] == 2                                                                    # an empty trail closes
    assert out['events'] == [['abhyasa:rh-done', {'slug': '<img src=x onerror=alert(1)>', 'outcome': 'passed'}]]   # data only

def test_a_page_in_the_pane_reports_where_it_is_and_asks_to_go_back():
    out = harness()
    origin = 'http://127.0.0.1:5011'
    assert out['listens'] == ['DOMContentLoaded']                          # no wiring at load
    assert out['here'] == out['own'] == '/learn?walk=a-1&step=0#f'          # without the pane key, with the fragment
    assert out['at'] == [{'type': 'rh:at', 'url': '/learn?walk=a-1&step=0#f', 'title': 'Softmax', 'trail': [['Attention', '/learn?walk=a-1']]}, origin]
    assert out['esc'] == [[{'type': 'rh:close', 'level': 1}, origin]]       # Esc in a text box or contenteditable sends nothing

def test_the_js_rules_match_the_python_rules():
    out = harness()
    assert out['local'] == [is_local(u) for u in GOOD + BAD] and out['panes'] == [pane_url(u) for u in GOOD + BAD]

def test_a_stored_split_is_read_with_care():
    assert harness()['saved'] == [None, None, False, False, False, False, False,
        {'page': '/learn?walk=a-1', 'title': 'Softmax', 'direction': 'horizontal'}, {'page': '/learn', 'title': '', 'direction': 'vertical'},
        {'path': '/a.py', 'direction': 'vertical'}, None]

def test_pane_js_is_in_the_ide_bundle_and_keeps_leela_names():
    sys.path.insert(0, str(ROOT/'tools'))
    import build_ide_js as builder
    ide, src = builder.LAYERS['lee-ide.js'], PANE_JS.read_text()
    assert ide.index('blocks/learn/pane.js') > ide.index('blocks/term/terminal.js')
    assert not re.search(r'^(const|let|var|class)\b', src, re.M)            # top-level function declarations only
    assert not re.search(r'function leePane\b', src) and 'leeSidePage' in src
    assert re.search(r'\.lee-editor-secondary iframe\s*\{[^}]*height', (ROOT/'leela'/'static'/'lee-ide.css').read_text())

def test_a_page_in_the_pane_has_no_chrome(rig):
    c = rig[0]
    r = c.get(f'/learn?walk={JID}&step=0&pane=1')
    src = re.search(r'<script src="(/leestatic/lee-pane\.js\?v=\d+)"', r.text)
    assert r.status_code == 200 and 'class="in-pane"' in r.text and src and 'id="tabbar"' not in r.text
    t = c.get(f'/learn?walk={JID}&step=0').text
    assert 'in-pane' not in t and 'pane.js' not in t
    js = c.get(src[1])
    assert js.status_code == 200 and 'javascript' in js.headers['content-type'] and js.text == PANE_JS.read_text()
