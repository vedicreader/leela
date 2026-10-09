"The native window: what it chooses, what it refuses, and that it really opens."

from __future__ import annotations

import importlib.util, os, shutil, subprocess, sys, threading

import pytest

import leela_app
from tests.assets import read
from leela import desktop


HAVE_DISPLAY = bool(os.environ.get('DISPLAY')) or bool(shutil.which('xvfb-run'))
# The GTK binding is the distribution's `python3-gi`, which no pip install of `leela[desktop]`
# can supply, so a Linux checkout without it must skip rather than fail.
HAVE_GUI = HAVE_DISPLAY and (sys.platform != 'linux' or importlib.util.find_spec('gi'))

WINDOW_SCRIPT = '''
import json, sys, threading, time
sys.path.insert(0, %r)
import http.server, functools
from leela.desktop import run_shell

html = b"<!doctype html><title>leela test</title><h1 id=h>workspace</h1>"
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', str(len(html))); self.end_headers()
        self.wfile.write(html)
    def log_message(self, *a): pass
srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = 'http://127.0.0.1:%%d/' %% srv.server_address[1]

import webview
def report():
    time.sleep(4)
    w = webview.windows[0]
    print('RESULT ' + json.dumps({'title': w.title,
                                  'heading': w.evaluate_js("document.getElementById('h').textContent"),
                                  'url': w.get_current_url()}))
    w.destroy()
threading.Thread(target=report, daemon=True).start()
run_shell([url], titles=['leela — test'], gui='gtk')
'''

@pytest.mark.slow
@pytest.mark.skipif(not HAVE_GUI, reason='opening a window needs an X server and a webview')
def test_the_shell_opens_a_window_and_loads_the_workspace_into_it(tmp_path):
    "A real window, a real page in it. Subprocessed: `webview.start` owns the thread, once."
    script = tmp_path/'shell.py'
    script.write_text(WINDOW_SCRIPT % str(__import__('pathlib').Path(__file__).parents[1]))
    argv = [sys.executable, str(script)]
    if not os.environ.get('DISPLAY'):
        argv = ['xvfb-run', '-a', '--server-args=-screen 0 1280x900x24'] + argv
    out = subprocess.run(argv, capture_output=True, text=True, timeout=180)
    line = next((l for l in out.stdout.splitlines() if l.startswith('RESULT ')), None)
    assert line, f'no window report\nstdout:\n{out.stdout}\nstderr:\n{out.stderr}'
    import json
    got = json.loads(line[len('RESULT '):])
    assert got['title'] == 'leela — test'
    assert got['heading'] == 'workspace'          # the server's page really rendered
    assert got['url'].startswith('http://127.0.0.1:')


@pytest.mark.skipif(sys.platform != 'darwin', reason='Apple Events are macOS only')
def test_the_open_folder_handler_can_be_constructed():
    """It is an Objective-C subclass, so `super().init()` finds nothing and registration raised `'super' object has no attribute 'init'` on every launch."""
    pytest.importorskip('objc')
    from leela.desktop import _OpenHandler
    assert _OpenHandler is not None, 'the class itself failed to define'
    seen = []
    h = _OpenHandler.alloc().init_with(lambda e, r: seen.append((e, r)))
    assert h is not None, 'init_with returned None, so alloc/init did not chain'
    h.handleEvent_reply_('event', 'reply')
    assert seen == [('event', 'reply')], 'the selector must reach the python callback'


@pytest.mark.skipif(sys.platform != 'darwin', reason='the Cocoa shell is macOS only')
def test_closing_the_last_window_hides_it_rather_than_quitting():
    """pywebview stops the run loop when its last window closes, so Leela vanished from the Dock while every other Mac app stays there."""
    pytest.importorskip('webview.platforms.cocoa')
    from webview.platforms.cocoa import BrowserView
    from leela.desktop import keep_running_in_dock
    was = BrowserView.WindowDelegate, BrowserView.AppDelegate
    try:
        assert keep_running_in_dock() is True
        assert issubclass(BrowserView.WindowDelegate, was[0]) and BrowserView.WindowDelegate is not was[0]
        assert issubclass(BrowserView.AppDelegate, was[1]) and BrowserView.AppDelegate is not was[1]
        # A Dock click with nothing visible is the only way back to a hidden window.
        assert hasattr(BrowserView.AppDelegate, 'applicationShouldHandleReopen_hasVisibleWindows_')
        assert hasattr(BrowserView.AppDelegate, 'applicationDockMenu_')
    finally: BrowserView.WindowDelegate, BrowserView.AppDelegate = was


@pytest.mark.skipif(sys.platform != 'darwin', reason='the Cocoa shell is macOS only')
def test_reopening_brings_back_one_window_and_not_every_one_you_closed():
    """Four windows closed one at a time should not all come back at once: the one closed most recently is what a Dock click is asking for."""
    pytest.importorskip('webview.platforms.cocoa')
    from webview.platforms.cocoa import BrowserView
    from leela.desktop import keep_running_in_dock
    was = BrowserView.WindowDelegate, BrowserView.AppDelegate
    class FakeWindow:
        def __init__(self, n): self.n, self.hidden, self.fronted = n, False, 0
        def orderOut_(self, _): self.hidden = True
        def makeKeyAndOrderFront_(self, _): self.fronted += 1; self.hidden = False
    try:
        assert keep_running_in_dock() is True
        wd = BrowserView.WindowDelegate.alloc().init()
        ad = BrowserView.AppDelegate.alloc().init()
        import leela.desktop as dk
        dk._hidden.clear()
        ws = [FakeWindow(i) for i in range(4)]
        for w in ws: assert wd.windowShouldClose_(w) == 0, 'closing must be refused'
        assert all(w.hidden for w in ws), 'every window is hidden, not closed'
        ad.applicationShouldHandleReopen_hasVisibleWindows_(None, False)
        assert [w.fronted for w in ws] == [0, 0, 0, 1], 'only the last one closed comes back'
        ad.applicationShouldHandleReopen_hasVisibleWindows_(None, False)
        assert [w.fronted for w in ws] == [0, 0, 1, 1], 'then the one before it'
        # With something already on screen a Dock click must not conjure another window.
        ad.applicationShouldHandleReopen_hasVisibleWindows_(None, True)
        assert [w.fronted for w in ws] == [0, 0, 1, 1]
    finally: BrowserView.WindowDelegate, BrowserView.AppDelegate = was


def test_a_folder_is_never_opened_on_the_thread_running_the_gui():
    """`webview.create_window` builds nothing at all when it is called from the main thread once `webview.start` owns it, so a folder from the Dock or from Finder made a window that was not one and then hung waiting for it to load."""
    seen, done = [], threading.Event()
    def note(path): seen.append((path, threading.current_thread().name)); done.set()
    desktop.off_main_thread(note, 'leela-open-folder')('/tmp/somewhere')
    assert done.wait(5), 'the handler never ran'
    path, where = seen[0]
    assert path == '/tmp/somewhere'
    assert where != 'MainThread' and where == 'leela-open-folder', where


def test_the_menu_bar_names_only_actions_the_client_can_dispatch():
    """`leeAct` answers `no handler for …` for anything absent from its table, so being in the keymap is necessary and not sufficient."""
    from leela.blocks.keys.menus import BAR, MenuItem
    # Two ways in: the table in `actions.js`, and `ACTIONS.name =` from a block that owns the action.
    js = read('leela/static/lee-core.js') + read('leela/static/lee-ide.js') + \
        read('leela/static/lee-agent.js')
    named = lambda a: f'  {a}:' in js or f'ACTIONS.{a} =' in js or f'ACTIONS.{a}=' in js
    missing = sorted({r.action for _, rows in BAR for r in rows
                      if isinstance(r, MenuItem) and r.action and not named(r.action)})
    assert missing == [], missing

def test_the_debug_menu_calls_functions_that_are_really_on_the_page():
    "`evaluate_js` runs in global scope, so a module-scope name is not reachable from a menu."
    from leela.blocks.keys.menus import BAR, Js
    from leela.core.web import IDE_BUNDLES
    # every bundle the page loads, not two of the three: all of them run in the same global scope,
    # so a menu row naming something in `lee-agent.js` was failing a check about reachability
    bundle = ''.join(read(f'leela/static/{b}') for b in IDE_BUNDLES)
    for _, rows in BAR:
        for r in rows:
            if not isinstance(r, Js): continue
            name = r.expr.split('(')[0]
            assert f'window.{name} =' in bundle or f'window.{name}=' in bundle, r.expr

@pytest.mark.parametrize('chord,want', [
    ('mod+shift+p', ('p', desktop.CMD | desktop.SHIFT)),
    ('mod+,',       (',', desktop.CMD)),
    ('hyper+g',     ('g', desktop.CMD | desktop.CTRL | desktop.ALT | desktop.SHIFT)),
    ('alt+shift+1', ('1', desktop.ALT | desktop.SHIFT)),
    ('ctrl+`',      ('`', desktop.CTRL)),
    ('alt+shift+b hyper+left', ('b', desktop.ALT | desktop.SHIFT)),   # the first chord only
    ('hyper+left',  ('', desktop.CMD | desktop.CTRL | desktop.ALT | desktop.SHIFT)),
    ('nonsense+x',  None),
    ('',            None),
])
def test_a_leela_chord_becomes_the_key_equivalent_appkit_spells(chord, want):
    assert desktop.mac_key(chord) == want


def test_nothing_opens_a_window_the_app_cannot_open():
    """A scripted `window.open` is `WKNavigationTypeOther`, and pywebview's delegate only acts on a link activation, so in the packaged app it opens nothing and returns null."""
    js = read('leela/static/lee-core.js') + read('leela/static/lee-ide.js') + read('leela/static/lee-agent.js')
    calls = [l.strip() for l in js.splitlines() if 'window.open(' in l]
    assert calls, 'the guarded form went missing rather than the guard'
    for line in calls:
        assert 'inDesktopShell()' in line or 'openExternal(' in line, \
            f'a window this app cannot open: {line[:120]}'


def _stub_server(handler_body, status=400):
    "A one-request loopback server answering `handler_body`, and the port it took."
    import http.server, threading
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status); self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(handler_body))); self.end_headers()
            self.wfile.write(handler_body)
        def log_message(self, *a): pass
    srv = http.server.HTTPServer(('127.0.0.1', 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def test_only_a_leela_that_could_answer_an_attach_is_taken_for_one():
    """The probe asks through the route an attach would use."""
    import json
    hub, hub_port = _stub_server(json.dumps({'ok': False, 'error': 'not a folder: '}).encode(), 400)
    plain, plain_port = _stub_server(b'404 Not Found', 404)
    other, other_port = _stub_server(json.dumps({'ok': False, 'error': 'nope'}).encode(), 400)
    try:
        assert leela_app.leela_on(hub_port) is True
        assert leela_app.leela_on(plain_port) is False, 'a Leela with no hub cannot be attached to'
        assert leela_app.leela_on(other_port) is False, "somebody else's 400 is not a Leela"
        assert leela_app.leela_on(1) is False
        assert leela_app.running_leela(ports=[hub_port]) == hub_port
        assert leela_app.running_leela(ports=[plain_port]) is None
    finally:
        for s in (hub, plain, other): s.shutdown()


