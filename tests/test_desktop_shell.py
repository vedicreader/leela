"The native window: what it chooses, what it refuses, and that it really opens."

from __future__ import annotations

import importlib.util, os, shutil, subprocess, sys, threading, time

import pytest

import leela_app
from leela import desktop

def test_each_platform_gets_the_webview_its_os_already_ships():
    assert desktop.backend('darwin') == 'cocoa'
    assert desktop.backend('win32') == 'edgechromium'
    assert desktop.backend('linux') == 'gtk'
    assert desktop.backend('sunos5') is None

def test_an_unsupported_platform_is_refused_with_a_reason_rather_than_a_traceback():
    ok, why = desktop.shell_ready('sunos5')
    assert not ok and 'sunos5' in why

def test_a_missing_pywebview_is_reported_as_missing(monkeypatch):
    "The frozen app falls back to Chrome on this answer, so it must be an answer, not a raise."
    monkeypatch.setitem(sys.modules, 'webview', None)
    ok, why = desktop.shell_ready('darwin')
    assert not ok and 'pywebview' in why

def test_the_window_size_can_be_set_from_the_environment(monkeypatch):
    monkeypatch.setenv('LEELA_WINDOW_SIZE', '1600x1000')
    assert desktop.window_size() == (1600, 1000)

@pytest.mark.parametrize('spec', ['', 'wide', '10x10', '1600', '1600x'])
def test_a_size_that_would_produce_an_unusable_window_falls_back_to_the_default(spec):
    assert desktop.window_size(spec) == desktop.DEFAULT_SIZE

def test_waiting_for_the_server_gives_up_rather_than_hanging_forever():
    # Port 1 on loopback: nothing listens, and connecting fails immediately.
    started = time.monotonic()
    assert desktop.wait_for_http('http://127.0.0.1:1/', timeout=.4) is False
    assert time.monotonic() - started < 5

def test_waiting_succeeds_as_soon_as_the_port_answers():
    import http.server
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), http.server.BaseHTTPRequestHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        # A bare BaseHTTPRequestHandler answers 501, which is still proof of a live server --
        # the window is about to load a URL, not to check a status code.
        assert desktop.wait_for_http(f'http://127.0.0.1:{srv.server_address[1]}/', timeout=5)
    finally: srv.shutdown()

def test_a_chromeless_machine_costs_the_inline_browser_and_not_the_workspace(monkeypatch, capsys):
    "`start_cdp` is called during startup; a raise there would take the whole app down."
    import fossick.cdp
    monkeypatch.setattr(fossick.cdp, '_debug_ready', lambda *a, **k: False)
    monkeypatch.setattr(fossick.cdp, 'cdp_setup',
                        lambda **kw: (_ for _ in ()).throw(FileNotFoundError('no chrome')))
    desktop.start_cdp(port=1, wait=True, timeout=5)
    assert 'inline browser unavailable' in capsys.readouterr().out

def test_a_desktop_launch_asks_for_one_workspace_per_folder_on_an_ephemeral_gateway():
    args = leela_app.leela_args(5123, ['/tmp'], ('--shell', 'none'))
    assert args[:5] == ['--app', '--port', '5123', '--gateway-port', '0']
    assert args[5:] == ['--shell', 'none', '/tmp']

def test_the_port_moves_out_of_the_way_of_a_leela_already_running():
    import socket
    with socket.socket() as held:
        held.bind(('127.0.0.1', 0))
        taken = held.getsockname()[1]
        held.listen(1)
        got = leela_app.free_port(taken)
    assert got != taken and got > 0

def test_only_directories_are_taken_as_folders_to_open(tmp_path):
    "A double-click passes no arguments; a Finder drop can pass a file, which is not a root."
    f = tmp_path/'note.md'; f.write_text('x')
    assert leela_app.folders([str(tmp_path), str(f), '--nonsense']) == [str(tmp_path)]

def test_without_a_webview_the_app_opens_in_chrome_rather_than_refusing(monkeypatch):
    "The fallback keeps a machine with no WebView2 runtime from having an app that never opens."
    calls = []
    monkeypatch.setattr(leela_app, 'serve', lambda args, background=False: calls.append(args))
    monkeypatch.setattr('leela.desktop.shell_ready', lambda *a: (False, 'no webview here'))
    monkeypatch.setattr(leela_app.sys, 'argv', ['leela_app.py'])
    leela_app.run()
    assert calls and '--shell' in calls[0] and calls[0][calls[0].index('--shell') + 1] == 'chrome'

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
    """It is an Objective-C subclass, so `super().init()` finds nothing and registration raised
    `'super' object has no attribute 'init'` on every launch. Nothing opened a folder dropped on
    the Dock or chosen through Open With, and the failure was one printed line."""
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
    """pywebview stops the run loop when its last window closes, so Leela vanished from the Dock
    while every other Mac app stays there. Both delegates are subclassed, because an Objective-C
    method cannot be reassigned once its class is built."""
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

def test_a_pywebview_that_moved_on_leaves_the_old_behaviour(monkeypatch, capsys):
    "Patching a dependency's internals must never be what stops the app from starting."
    import builtins
    from leela.desktop import keep_running_in_dock
    real = builtins.__import__
    def blocked(name, *a, **kw):
        if 'cocoa' in name: raise ImportError('pywebview moved on')
        return real(name, *a, **kw)
    monkeypatch.setattr(builtins, '__import__', blocked)
    assert keep_running_in_dock() is False
    assert 'quit Leela' in capsys.readouterr().out


@pytest.mark.skipif(sys.platform != 'darwin', reason='the Cocoa shell is macOS only')
def test_reopening_brings_back_one_window_and_not_every_one_you_closed():
    """Four windows closed one at a time should not all come back at once: the one closed most
    recently is what a Dock click is asking for."""
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

@pytest.mark.skipif(sys.platform != 'darwin', reason='NSMenu is macOS only')
def test_the_dock_menu_offers_recent_folders_and_opens_one():
    "A Dock menu is a shortcut, so it is capped, and an empty one says so rather than being blank."
    pytest.importorskip('AppKit')
    from leela.desktop import DOCK_RECENT, dock_menu
    opened = []
    rows = [{'name': f'p{i}', 'path': f'/tmp/p{i}'} for i in range(DOCK_RECENT + 5)]
    menu = dock_menu(opened.append, recent=rows)
    assert menu.numberOfItems() == DOCK_RECENT, 'the Dock menu is not a file browser'
    first = menu.itemAtIndex_(0)
    assert first.title() == 'p0' and first.toolTip() == '/tmp/p0'
    first.target().openRecent_(first)
    assert opened == ['/tmp/p0'], 'a row opens the folder it names'
    empty = dock_menu(None, recent=[])
    assert empty.numberOfItems() == 1 and not empty.itemAtIndex_(0).isEnabled()


@pytest.mark.skipif(sys.platform != 'darwin', reason='the Cocoa shell is macOS only')
def test_installing_the_dock_behaviour_twice_is_not_an_error():
    "An Objective-C class name is global, so building the delegates twice would raise."
    pytest.importorskip('webview.platforms.cocoa')
    from webview.platforms.cocoa import BrowserView
    from leela.desktop import keep_running_in_dock
    was = BrowserView.WindowDelegate, BrowserView.AppDelegate
    try: assert [keep_running_in_dock() for _ in range(3)] == [True, True, True]
    finally: BrowserView.WindowDelegate, BrowserView.AppDelegate = was
