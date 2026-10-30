"Terminal keys: Option as Meta, the theme hint in the pty environment, and Escape in a full-screen pane."
import json, re, shutil, subprocess
from pathlib import Path
import pytest
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.blocks.term.term import colorfgbg
from leela.core.keys import lookup, web_keymap
from leela.workspace import Workspace

ROOT = Path(__file__).parents[1]
TERM_JS, TERMINAL_JS, KEYMAP_JS = ROOT/'frontend/term.js', ROOT/'leela/blocks/term/terminal.js', ROOT/'leela/blocks/keys/keymap.js'

STUBS = r'''
globalThis.window = globalThis;
const store = new Map(), listeners = {};
globalThis.localStorage = {getItem: k => store.has(k) ? store.get(k) : null, setItem: (k, v) => store.set(k, String(v))};
globalThis.document = {documentElement: {dataset: {mode: 'light'}}, addEventListener: (t, f) => (listeners[t] ||= []).push(f)};
globalThis.matchMedia = () => ({matches: false});
globalThis.requestAnimationFrame = f => f();
globalThis.$ = () => null; globalThis.$$ = () => [];
globalThis.status = () => {}; globalThis.post = async () => ({});
globalThis.lee = {terms: new Map(), prefs: {}};
globalThis.prefGet = (s, k, d) => lee.prefs[s]?.[k] ?? d;
globalThis.prefSet = async (s, k, v) => { lee.prefs = {...lee.prefs, [s]: {...lee.prefs[s], [k]: v}}; };
globalThis.Terminal = class { constructor(o) { this.options = {...o}; this.cols = 80; this.rows = 24; this.csi = {};
    this.parser = {registerCsiHandler: (id, f) => { this.csi[(id.prefix || '') + id.final] = f; }}; }
  attachCustomKeyEventHandler(f) { this.keyFn = f; }
  loadAddon() {} open() {} onData() {} focus() {} clear() {} dispose() {} };
globalThis.FitAddon = class { fit() {} };
globalThis.getComputedStyle = () => ({getPropertyValue: () => ''});
globalThis.location = {protocol: 'http:', host: 'x'};
globalThis.sent = [];
globalThis.WebSocket = class { constructor() { this.readyState = 1; globalThis.lastSocket = this; } send(d) { sent.push(d); } close() {} };
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
'''


def _node(expr):
    "Evaluate `expr` in node with the real `term.js` (imports stripped) and `terminal.js` loaded on a stub page."
    if not shutil.which('node'): pytest.skip('node is not installed')
    term = re.sub(r'^import .*$', '', TERM_JS.read_text(), flags=re.M)
    src = STUBS + term + '\n' + TERMINAL_JS.read_text() + f'\nprocess.stdout.write(JSON.stringify({expr}));\n'
    out = subprocess.run(['node', '-'], input=src, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_option_is_meta_by_default_and_the_toggle_reaches_open_and_new_terminals():
    got = _node("""(() => {
      const make = () => LeeTerm.create({}, {token: 't', id: 'a'});
      const a = make(); lee.terms.set('a', {view: a});
      const first = a.term.options.macOptionIsMeta;
      a.ws.onopen(); const hello = JSON.parse(sent.at(-1));
      leeTermOptionMeta(false);
      return {first, open: a.term.options.macOptionIsMeta, later: make().term.options.macOptionIsMeta,
              saved: lee.prefs.terminal.macOptionIsMeta, mode: hello.mode};
    })()""")
    assert got == {'first': True, 'open': False, 'later': False, 'saved': False, 'mode': 'light'}


def test_shift_enter_and_cmd_a_reach_a_program_only_while_it_has_pushed_the_kitty_keyboard_mode():
    "A shell keeps xterm's keys; a prompt that pushes `CSI > 1 u` gets them as `CSI u`, as in Ghostty or kitty."
    got = _node("""(() => {
      const x = LeeTerm.create({}, {token: 't', id: 'k'}).term;
      const key = (o, type = 'keydown') => x.keyFn({type, key: '', shiftKey: false, metaKey: false, ctrlKey: false,
        altKey: false, ...o, preventDefault() {}});
      const bytes = () => sent.splice(0).filter(b => typeof b !== 'string').map(b => new TextDecoder().decode(b));
      const se = {key: 'Enter', shiftKey: true}, ca = {key: 'a', metaKey: true};
      sent.splice(0);
      const off = [key(se), key(ca)], offBytes = bytes();
      x.csi['?u']([]); const askedOff = bytes();
      x.csi['>u']([1]);
      const on = [key(se), key(ca), key(se, 'keyup'), key({key: 'Enter'})], onBytes = bytes();
      x.csi['?u']([]); const askedOn = bytes();
      x.csi['<u']([]);
      return {off, offBytes, askedOff, on, onBytes, askedOn, popped: key(se), poppedBytes: bytes()};
    })()""")
    assert got == {'off': [True, True], 'offBytes': [], 'askedOff': ['\x1b[?0u'],
                   'on': [False, False, False, True], 'onBytes': ['\x1b[13;2u', '\x1b[97;9u'], 'askedOn': ['\x1b[?1u'],
                   'popped': True, 'poppedBytes': []}


def test_escape_with_terminal_focus_reaches_the_terminal_and_the_chord_leaves_full_screen():
    got = _node("""(() => {
      const esc = target => { let stopped = false;
        listeners.keydown[0]({key: 'Escape', target, composedPath: () => [target], preventDefault() { stopped = true; }, stopPropagation() {}});
        return stopped; };
      const inTerm = {matches: s => s.includes('.xterm')}, elsewhere = {matches: () => false};
      localStorage.setItem('lee-expand', 'bottom:full');
      const toTerm = esc(inTerm), stillFull = leeExpandState().mode;
      const toIde = esc(elsewhere), after = leeExpandState().mode;
      localStorage.setItem('lee-expand', 'bottom:full'); leeLeaveFullScreen();
      const chord = leeExpandState().mode;
      lee.keys = [{action: 'leave_full_screen', key: 'mod+shift+e'}]; globalThis.displayChord = s => s;
      const said = []; globalThis.status = m => said.push(m);
      localStorage.setItem('lee-expand', ''); leeExpandPane('bottom'); leeExpandPane('bottom');
      return {toTerm, stillFull, toIde, after, chord, said};
    })()""")
    said = got.pop('said')
    assert got == {'toTerm': False, 'stillFull': 'full', 'toIde': True, 'after': '', 'chord': ''}
    assert 'mod+shift+e' in said[-1], 'entering full screen says how to leave it'


def test_the_leave_full_screen_chord_is_a_global_binding_the_terminal_lets_through():
    k = lookup('leave_full_screen')
    assert k and k.scope == 'global' and k.key and 'escape' not in k.key.split('+')
    assert re.search(r'leave_full_screen:\s*\(\) => leeLeaveFullScreen\(\)', (ROOT/'leela/static/js/actions.js').read_text())
    chord = next(r for r in web_keymap() if r['action'] == 'leave_full_screen')['chords'][0]
    stub = ("Object.defineProperty(globalThis, 'navigator', {value: {platform: 'MacIntel'}, configurable: true});"
            "globalThis.Element = class {}; globalThis.MD_KEYS = {}; globalThis.window = globalThis;"
            "globalThis.document = {title: '', addEventListener() {}}; globalThis.addEventListener = () => {};"
            f"globalThis.lee = {{scope: 'editor', keys: {json.dumps(web_keymap())}}};\n")
    ev = {'key': chord['key'], 'code': chord['code'], 'metaKey': chord['mod'], 'ctrlKey': chord['ctrl'],
          'altKey': chord['alt'], 'shiftKey': chord['shift'], 'composedPath': None, 'target': {}}
    if not shutil.which('node'): pytest.skip('node is not installed')
    src = stub + KEYMAP_JS.read_text() + f"\nconst e = {json.dumps(ev)}; e.composedPath = () => [];" \
        "\nprocess.stdout.write(JSON.stringify(findBinding(e, 'term')?.binding.action));\n"
    out = subprocess.run(['node', '-'], input=src, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == 'leave_full_screen'


def test_a_terminal_started_by_the_ide_carries_the_themes_colorfgbg(tmp_path):
    "`COLORFGBG` is how a program inside tmux learns the background, and tmux cannot answer for it."
    settings = tmp_path/'.leela'/'settings.json'
    settings.parent.mkdir()
    settings.write_text(json.dumps({'terminal': {'shell': '/bin/sh', 'shellArgs': ['-c', 'echo FG=$COLORFGBG'], 'loginShell': False}}))
    assert colorfgbg('system') is None and colorfgbg(['light']) is None, 'only a resolved mode names a value'
    ws = Workspace(roots=[tmp_path])
    def seen(c, info, mode):
        with c.websocket_connect('/term/ws') as sock:
            sock.send_json({'token': info['token'], 'kind': 'shell', 'id': f'fg-{mode}', 'cwd': str(tmp_path),
                            'cols': 80, 'rows': 24, 'mode': mode})
            got = b''
            for _ in range(20):
                m = sock.receive()
                if 'bytes' not in m: break
                got += m['bytes']
                if (hit := re.search(rb'FG=([^\r\n]*)\r?\n', got)): return hit[1].decode()
    with TestClient(ide_app(ws)) as c:
        info = c.get('/term/info').json()
        if not info['enabled']: pytest.skip(info['why'])
        try: assert (seen(c, info, 'light'), seen(c, info, 'dark')) == ('0;15', '15;0')
        finally: ws.terms.close_all()