import json, re, shutil, subprocess, sys
from pathlib import Path
import pytest
from leela.blocks.learn.learn import is_local, pane_url
from learn_data import JID, rig  # noqa: F401

ROOT = Path(__file__).parents[1]
PANE_JS = ROOT/'leela'/'blocks'/'learn'/'pane.js'
GOOD = ['/learn?walk=a-1&step=0', '/learn/lookup?q=Agent', '/learn?pane=0&walk=a-1#x']
BAD = ['https://evil.example/x', '//evil.example', '/\\evil.example', 'javascript:alert(1)', 'w/g', '', None, '/learn\x00x', '/learn\nx']

def test_pane_url_and_no_abhyasa_core():
    assert [is_local(u) for u in GOOD + BAD] == [True] * len(GOOD) + [False] * len(BAD)
    assert pane_url('/learn?walk=a-1') == '/learn?walk=a-1&pane=1' and pane_url('//evil.example') is None
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
    assert r.status_code == 200 and 'class="lee-learn-page in-pane"' in r.text and src and 'id="tabbar"' not in r.text
    t = c.get(f'/learn?walk={JID}&step=0').text
    assert 'in-pane' not in t and 'lee-pane.js' in t, 'a step page in a tab of its own loads the module for its maths, and gets no pane chrome'
    js = c.get(src[1])
    assert js.status_code == 200 and 'javascript' in js.headers['content-type'] and js.text == PANE_JS.read_text()

LINKS = r'''
const src = require('fs').readFileSync(process.argv[1], 'utf8');
global.location = {origin: 'http://127.0.0.1:5011'};
global.document = {addEventListener() {}, documentElement: {classList: {contains: c => c === 'in-pane'}}};
const posted = []; global.window = {parent: {postMessage: (m, o) => posted.push([m, o])}};
eval(src);
const frame = {contentWindow: {}}, linked = [];
const keyed = [];
const host = {frame, trail: [], link: u => linked.push(u), key: k => keyed.push(k)};
const m = (data, origin = location.origin, source = frame.contentWindow) => leePaneMessage({data, origin, source}, host);
const took = [m({type: 'rh:link', url: 'https://example.org/a?b=1'}), m({type: 'rh:link', url: 'http://example.org/'}),
  m({type: 'rh:link', url: 'https://example.org/'}, 'http://evil.example'), m({type: 'rh:link', url: 'https://example.org/'}, location.origin, {}),
  ...['javascript:alert(1)', '//evil.example', 'data:text/html,x', '/learn?walk=a-1', 'https://a.example/\n', 'https://a\\b.example', 5, null].map(url => m({type: 'rh:link', url}))];
const anchors = [];
const click = (href, mods = {}) => { const a = href == null ? null : {href: href.startsWith('/') || href.startsWith('#') ? location.origin + '/learn' + href.replace(/^#/, '#') : href};
  if (a) anchors.push(a);
  const ev = {target: {closest: () => a}, button: 0, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...mods};
  leePaneLink(ev); return ev.defaultPrevented; };
const stopped = [click('https://example.org/x'), click('/learn?walk=a-1'), click('mailto:a@b.c'), click('#f'), click(null),
                 click('https://example.org/m', {metaKey: true}), click('https://example.org/w', {button: 1})];
const keys = [m({type: 'rh:key', key: 's', code: 'KeyS', meta: true}), m({type: 'rh:key', key: 'P', code: 'KeyP', meta: true, shift: true}),
  m({type: 'rh:key', key: 'w', ctrl: true}), m({type: 'rh:key', key: 'q', meta: true}), m({type: 'rh:key', key: 's'}),
  m({type: 'rh:key', key: 's', meta: true}, 'http://evil.example'), m({type: 'rh:key', key: 's', meta: true, alt: true}), m({type: 'rh:key', key: ['s'], meta: true})];
const press = (key, mods) => { const ev = {key, code: 'Key' + key.toUpperCase(), target: {isContentEditable: false, matches: () => true}, metaKey: false, ctrlKey: false, shiftKey: false, altKey: false,
  defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...mods}; const n = posted.length; leePaneKey(ev); return [ev.defaultPrevented, posted.slice(n).map(p => p[0])]; };
const pressed = [press('s', {metaKey: true}), press('p', {metaKey: true, shiftKey: true}), press('c', {metaKey: true}), press('s', {})];
console.log(JSON.stringify({took, linked, stopped, posted, targets: anchors.map(a => a.target || ''), keys, keyed, pressed}));
'''

def test_a_web_link_in_the_pane_opens_outside_it_and_only_from_its_own_frame():
    "A link in a pane page loaded the site inside the frame; the IDE opens it instead, for its own frame and a web address only."
    node = shutil.which('node')
    if not node: pytest.skip('node is not installed')
    r = subprocess.run([node, '-e', LINKS, str(PANE_JS)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out['took'] == [True, True] + [False] * 10
    assert out['linked'] == ['https://example.org/a?b=1', 'http://example.org/']
    assert out['stopped'] == [True, False, False, False, False, False, False], 'only a plain click on a web link goes to the IDE'
    assert out['targets'] == ['_blank', '', '', '', '_blank', '_blank'], 'a modifier or middle click opens its own tab'
    assert out['posted'][0] == [{'type': 'rh:link', 'url': 'https://example.org/x'}, 'http://127.0.0.1:5011']

def test_an_ide_chord_in_the_pane_reaches_the_ide():
    "Cmd+S, Cmd+P and Cmd+W in a pane page went nowhere, or to the browser's Save Page; the page sends them to the IDE as it sends Escape."
    node = shutil.which('node')
    if not node: pytest.skip('node is not installed')
    r = subprocess.run([node, '-e', LINKS, str(PANE_JS)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out['keys'] == [True, True, True] + [False] * 5
    assert out['keyed'] == [dict(key='s', code='KeyS', metaKey=True, ctrlKey=False, shiftKey=False),
                            dict(key='P', code='KeyP', metaKey=True, ctrlKey=False, shiftKey=True), dict(key='w', code='', metaKey=False, ctrlKey=True, shiftKey=False)]
    s, p, c, plain = out['pressed']
    assert s == [True, [dict(type='rh:key', key='s', code='KeyS', meta=True, ctrl=False, shift=False)]] and p[0] and p[1][0]['shift']
    assert c == [False, []] and plain == [False, []], 'copy and plain keys stay in the page'

def test_a_safe_alignment_has_a_plain_one_before_it():
    "A WebKit before 17.6 drops `safe flex-end` whole, and the cell bar's buttons moved to the left."
    css = (ROOT/'leela'/'static'/'lee-ide.css').read_text()
    rules = [r for r in re.findall(r'\{[^{}]*\}', css) if 'safe flex-end' in r]
    assert rules and all(re.search(r'justify-content:\s*flex-end;[^}]*justify-content:\s*safe flex-end', r) for r in rules), rules
