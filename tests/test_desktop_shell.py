"The native window: what it chooses, what it refuses, and that it really opens."

from __future__ import annotations

import importlib.util, os, shutil, subprocess, sys, threading

import pytest

import leela_app
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
    from leela.desktop import OpenHandler
    assert OpenHandler is not None, 'the class itself failed to define'
    seen = []
    h = OpenHandler.alloc().init_with(lambda e, r: seen.append((e, r)))
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
        dk.hidden_windows.clear()
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
    from leela.hub import cfg_mark
    hub, hub_port = _stub_server(json.dumps({'ok': False, 'error': 'not a folder: ', 'config': cfg_mark()}).encode(), 400)
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


def test_a_leela_on_another_config_dir_is_not_attached_to(monkeypatch, tmp_path):
    """A packaging test's app, on a temp `XDG_CONFIG_HOME`, attached to the person's running Leela and never served."""
    import json, leela
    from leela.hub import cfg_mark
    body = lambda **kw: json.dumps({'ok': False, 'error': 'not a folder: ', **kw}).encode()
    mine, mine_port = _stub_server(body(config=cfg_mark()))
    theirs, theirs_port = _stub_server(body(config=cfg_mark(tmp_path/'elsewhere')))
    old, old_port = _stub_server(body())
    try:
        assert leela_app.leela_on(mine_port) is True
        assert leela_app.leela_on(theirs_port) is False
        assert leela_app.leela_on(old_port) is False, 'a Leela with no mark serves the default dir, which this is not'
        assert leela_app.running_leela(ports=[theirs_port, old_port, mine_port]) == mine_port
        monkeypatch.setattr(leela, 'leela_cfg', leela_app.Path.home()/'.config'/'leela')
        assert leela_app.leela_on(old_port) is True, 'an upgraded app on the default dir still attaches to an older copy'
        assert leela_app.leela_on(theirs_port) is False
    finally:
        for s in (mine, theirs, old): s.shutdown()


def test_a_launch_beside_a_leela_on_another_config_dir_serves_its_own(monkeypatch, tmp_path):
    import json
    import leela.desktop
    from leela.hub import cfg_mark
    theirs, port = _stub_server(json.dumps({'ok': False, 'error': 'not a folder: ', 'config': cfg_mark(tmp_path/'x')}).encode())
    served, windows = [], []
    monkeypatch.setattr(leela.desktop, 'shell_ready', lambda: (True, 'stub'))
    monkeypatch.setattr(leela.desktop, 'last_folder', lambda: [])
    monkeypatch.setattr(leela.desktop, 'remember', lambda f: list(f))
    monkeypatch.setattr(leela.desktop, 'warm_cdp', lambda p: None)
    monkeypatch.setattr(leela.desktop, 'run_shell', lambda urls, **kw: windows.append(urls))
    monkeypatch.setattr(leela_app, 'folders', lambda a=None: [])
    monkeypatch.setattr(leela_app, 'files', lambda a=None: [])
    monkeypatch.setattr(leela_app, 'free_port', lambda *a, **k: 5099)
    monkeypatch.setattr(leela_app, 'serve', lambda args, background=False: served.append(args))
    real = leela_app.running_leela
    monkeypatch.setattr(leela_app, 'running_leela', lambda *a, **k: real(ports=[port]))
    try: leela_app.run()
    finally: theirs.shutdown()
    assert served and served[0][:3] == ['--app', '--port', '5099'], served
    assert windows == [['http://127.0.0.1:5099/']]




def test_the_page_retitles_its_own_native_window(monkeypatch):
    from types import SimpleNamespace as NS
    class W:
        def __init__(self, url): self.real_url, self.title = url, ''
        def set_title(self, t): self.title = t
    a, b = W('http://127.0.0.1:5001/'), W('http://127.0.0.1:5002/')
    monkeypatch.setitem(sys.modules, 'webview', NS(windows=[a, b], active_window=lambda: a))
    api = desktop.shell_api()
    assert api.set_title('leela — b · py', 'http://127.0.0.1:5002/#x')
    assert (a.title, b.title) == ('', 'leela — b · py')
    assert api.set_title('leela — a · agent') and a.title == 'leela — a · agent', 'no url means the focused window'
    monkeypatch.setitem(sys.modules, 'webview', NS(windows=[], active_window=lambda: None))
    assert api.set_title('leela') is False
