"The native window: what it chooses, what it refuses, and that it really opens."

from __future__ import annotations

import importlib.util, os, shutil, subprocess, sys, threading, time

import pytest

import leela_app
from tests.assets import agent_modules, read
from leela import desktop

def test_the_pipeline_terminal_is_keyed_by_the_package_it_watches():
    """A browser test covers the behaviour; this catches a silent revert without paying for one.

    `openReleaseTerm` keyed its record by kind alone, so one `release` terminal served every
    package and showed whichever one it was opened with first.
    """
    for f in ('leela/blocks/term/dock.js', 'leela/static/lee-ide.js'):
        js = read(f)
        body = js.split('async function openReleaseTerm')[1].split('\nasync function')[0]
        assert 'const id = kind,' not in body, f
        assert '`${kind}:${at}`' in body, f

def test_each_platform_gets_the_webview_its_os_already_ships():
    assert desktop.backend('darwin') == 'cocoa'
    assert desktop.backend('win32') == 'edgechromium'
    assert desktop.backend('linux') == 'gtk'
    assert desktop.backend('sunos5') is None

def test_the_system_text_checker_is_turned_off_before_a_window_can_ask(monkeypatch):
    """WKWebView hands a `contenteditable` to NSSpellChecker where a browser does not, so the
    packaged app curled quotes and corrected identifiers behind CodeMirror's back. Written to
    Leela's own defaults domain, so nothing outside Leela changes.
    """
    written = {}
    class Defaults:
        def setBool_forKey_(self, value, key): written[key] = value
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setitem(sys.modules, 'Foundation',
                        type('F', (), {'NSUserDefaults': type('D', (), {
                            'standardUserDefaults': staticmethod(lambda: Defaults())})})())
    assert desktop.quiet_text_substitution() is True
    assert set(written) == set(desktop.NO_SUBSTITUTION)
    assert not any(written.values())
    # Inline prediction is taken with Tab, so it ate the Tab meant for the completion list.
    assert 'NSAutomaticInlinePredictionEnabled' in written

def test_the_text_checker_is_a_mac_question_and_nothing_else_is_asked(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'linux')
    assert desktop.quiet_text_substitution() is False

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

def test_the_port_a_window_is_served_from_is_the_same_one_next_launch():
    """A window's origin is `http://<slug>.localhost:<port>`. The port used to fall back to
    whatever the OS handed out, so a launch that could not have 5001 got a new origin and found
    every per-origin thing the browser had kept for it empty: the theme reset on every reopen."""
    import socket
    ladder = range(5001, 5011)
    assert leela_app.free_port(ports=ladder) in ladder
    # Same answer every time, which is the whole property.
    assert len({leela_app.free_port(ports=ladder) for _ in range(5)}) == 1
    with socket.socket() as a, socket.socket() as b:
        for s, p in ((a, 5001), (b, 5002)):
            try: s.bind(('127.0.0.1', p)); s.listen(1)
            except OSError: pytest.skip(f'{p} is held by something else on this machine')
        assert leela_app.free_port(ports=ladder) == 5003, 'it steps down the ladder, it does not jump'
        assert leela_app.free_port(ports=ladder) == 5003


def test_a_full_ladder_still_starts_rather_than_refusing():
    "A moving origin is a worse day than no app at all, so the OS fallback stays."
    got = leela_app.free_port(preferred=5001, ports=range(0, 0))
    assert got > 0

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
    assert 'quit leela' in capsys.readouterr().out


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
def test_the_dock_menu_offers_recent_folders_and_opens_one(tmp_path, monkeypatch):
    """`recent_folders` gives paths, not dicts. Indexing them as dicts raised, the handler caught
    it, and the Dock menu never appeared -- so this drives the real function and not a shape I
    invented for the test."""
    pytest.importorskip('AppKit')
    import leela.core.projects as projects
    from leela.desktop import DOCK_RECENT, dock_menu
    made = []
    for i in range(DOCK_RECENT + 5):
        d = tmp_path/f'p{i}'; d.mkdir(); made.append(str(d))
    monkeypatch.setattr(projects, 'SESSION', tmp_path/'session.json')
    projects.remember(made)
    opened = []
    menu = dock_menu(opened.append)                      # no injected rows: the real list
    assert menu.numberOfItems() == DOCK_RECENT, 'the Dock menu is not a file browser'
    first = menu.itemAtIndex_(0)
    assert first.title() == os.path.basename(first.toolTip()), 'the row is named after its folder'
    first.target().openRecent_(first)
    assert opened == [first.toolTip()], 'a row opens the folder it names'

@pytest.mark.skipif(sys.platform != 'darwin', reason='NSMenu is macOS only')
def test_a_dock_menu_with_no_history_says_so(monkeypatch, tmp_path):
    "A blank menu reads as broken; one disabled row reads as empty."
    pytest.importorskip('AppKit')
    import leela.core.projects as projects
    from leela.desktop import dock_menu
    monkeypatch.setattr(projects, 'SESSION', tmp_path/'none.json')
    menu = dock_menu(None)
    assert menu.numberOfItems() == 1 and not menu.itemAtIndex_(0).isEnabled()


def test_a_folder_is_never_opened_on_the_thread_running_the_gui():
    """`webview.create_window` builds nothing at all when it is called from the main thread once
    `webview.start` owns it, so a folder from the Dock or from Finder made a window that was not
    one and then hung waiting for it to load."""
    seen, done = [], threading.Event()
    def note(path): seen.append((path, threading.current_thread().name)); done.set()
    desktop.off_main_thread(note, 'leela-open-folder')('/tmp/somewhere')
    assert done.wait(5), 'the handler never ran'
    path, where = seen[0]
    assert path == '/tmp/somewhere'
    assert where != 'MainThread' and where == 'leela-open-folder', where

def test_a_folder_already_open_raises_its_window_rather_than_opening_a_second(monkeypatch):
    "Two windows on one folder would be two kernels and two journals writing the same files."
    made, shown = [], []
    class FakeWindow:
        def __init__(self, title): self.title = title
        def show(self): shown.append(self.title)
        def load_url(self, url): self.url = url
        def load_html(self, html): self.url = None
    monkeypatch.setattr('kavacha.window._windows', {})
    monkeypatch.setattr('kavacha.window.make_window', lambda title='leela', size=None:
                        made.append(title) or FakeWindow(title))
    monkeypatch.setattr('kavacha.window.wait_for_http', lambda url, timeout=90: True)
    first = desktop.open_window('http://one.localhost:5001/', 'leela — one', key='one')
    again = desktop.open_window('http://one.localhost:5001/', 'leela — one', key='one')
    assert made == ['leela — one'], 'the second ask built nothing'
    assert again is first and shown == ['leela — one'], 'it raised the window there already was'

def test_a_window_that_never_answers_says_so_rather_than_showing_the_splash_forever(monkeypatch):
    shown = []
    class FakeWindow:
        def load_url(self, url): shown.append(('url', url))
        def load_html(self, html): shown.append(('html', html))
    monkeypatch.setattr('kavacha.window._windows', {})
    monkeypatch.setattr('kavacha.window.make_window', lambda title='leela', size=None: FakeWindow())
    monkeypatch.setattr('kavacha.window.wait_for_http', lambda url, timeout=90: False)
    desktop.open_window('http://gone.localhost:5001/', 'leela — gone', key='gone')
    assert shown[0][0] == 'html' and 'did not answer' in shown[0][1]

def test_the_page_can_ask_the_native_shell_for_a_window(monkeypatch):
    "pywebview runs every `js_api` call on a thread of its own, which is where a window may be built."
    asked = []
    api = desktop.ShellApi()
    monkeypatch.setattr(api, 'on_open_folder', lambda p: asked.append(p))
    assert api.open_folder('/tmp/here') is True and asked == ['/tmp/here']
    assert desktop.ShellApi().open_folder('/tmp/here') is False, 'and says so when nothing is wired'
    assert api.open_folder('') is False, 'an empty path opens nothing'


@pytest.mark.skipif(sys.platform != 'darwin', reason='the Cocoa menu bar is macOS only')
def test_the_menu_bar_is_in_the_order_macos_expects():
    "pywebview puts its own View and Edit first, which no Mac app does. Ours are the only ones."
    import webview
    from leela.blocks.keys.menus import BAR
    bar = desktop.menus()
    assert [m.title for m in bar] == [t for t, _ in BAR]
    assert bar[0].title == '__app__', 'the Leela menu is spliced into the app menu, not a second one'
    assert [m.title for m in bar[1:]] == ['File', 'Edit', 'View', 'Run', 'Tools', 'Debug',
                                          'Window', 'Help']
    assert webview.settings['SHOW_DEFAULT_MENUS'] is False, 'or pywebview inserts its own first'
    assert all(m.items for m in bar), 'no menu is empty'

def test_the_menu_bar_names_only_actions_the_keymap_declares():
    "A row naming nothing is a menu item that quietly does nothing when it is picked."
    from leela.core.keys import KEYS
    from leela.blocks.keys.menus import BAR, MenuItem
    known = set(KEYS.attrgot('action'))
    named = {r.action for _, rows in BAR for r in rows if isinstance(r, MenuItem) and r.action}
    assert named - known == set()

def test_the_menu_bar_names_only_actions_the_client_can_dispatch():
    """`leeAct` answers `no handler for …` for anything absent from its table, so being in the
    keymap is necessary and not sufficient."""
    from leela.blocks.keys.menus import BAR, MenuItem
    # Two ways in: the table in `actions.js`, and `ACTIONS.name =` from a block that owns the action.
    js = read('leela/static/lee-core.js') + read('leela/static/lee-ide.js') + \
        agent_modules()
    named = lambda a: f'  {a}:' in js or f'ACTIONS.{a} =' in js or f'ACTIONS.{a}=' in js
    missing = sorted({r.action for _, rows in BAR for r in rows
                      if isinstance(r, MenuItem) and r.action and not named(r.action)})
    assert missing == [], missing

def test_the_debug_menu_calls_functions_that_are_really_on_the_page():
    "`evaluate_js` runs in global scope, so a module-scope name is not reachable from a menu."
    from leela.blocks.keys.menus import BAR, Js
    from leela.core.web import IDE_BUNDLES
    # every bundle the page loads, not two of the three: all of them run in the same global scope,
    # so a menu row naming something in the agent's modules was failing a check about reachability
    # the bundles plus the agent's modules: they are served separately now but share one global
    served = ''.join(read(f'leela/static/{b}') for b in IDE_BUNDLES) + agent_modules()
    for _, rows in BAR:
        for r in rows:
            if not isinstance(r, Js): continue
            name = r.expr.split('(')[0]
            assert f'window.{name} =' in served or f'window.{name}=' in served, r.expr

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

def test_a_menu_row_takes_no_chord_that_would_be_stolen_from_the_page():
    """A key equivalent is consulted before the keystroke reaches the web view. Binding the files
    pane's bare `n` would fire New File every time the letter n was typed anywhere."""
    assert desktop.menu_chord('new_file') is None, 'bare letter, and files-scoped'
    assert desktop.menu_chord('run_cell') is None, 'editor-scoped: a menu cannot express scope'
    assert desktop.menu_chord('quit') is None, 'unbound'
    assert desktop.menu_chord('palette') == ('p', desktop.CMD | desktop.SHIFT), 'global, modified'
    assert desktop.menu_chord('settings') == (',', desktop.CMD)

def test_every_chord_the_menu_bar_installs_is_global_and_modified():
    "The rule, over the real table rather than a chosen example."
    from leela.core.keys import lookup
    from leela.blocks.keys.menus import BAR, MenuItem
    for _, rows in BAR:
        for r in rows:
            if not (isinstance(r, MenuItem) and r.action): continue
            if desktop.menu_chord(r.action) is None: continue
            k = lookup(r.action)
            assert k.scope == 'global', f'{r.action} is {k.scope}-scoped and took a chord'
            assert set(k.keys[0].split('+')[:-1]) & {'mod', 'cmd', 'ctrl', 'alt', 'opt', 'hyper'}, \
                f'{r.action} took a bare chord'

def test_picking_a_menu_row_runs_the_action_in_the_window_that_has_focus(monkeypatch):
    "One bar serves every window, so the row cannot be bound to the window it was built with."
    ran = []
    class FakeWindow:
        def evaluate_js(self, js): ran.append(js)
    monkeypatch.setattr(desktop.webview if hasattr(desktop, 'webview') else desktop, 'x', 0,
                        raising=False)
    import webview
    monkeypatch.setattr(webview, 'active_window', lambda: FakeWindow())
    bar, specs = desktop.menu_bar()
    save = next(i for i in bar[1].items if getattr(i, 'title', '') == 'Save')
    save.function()
    assert ran == ['leeAct("save")']
    monkeypatch.setattr(webview, 'active_window', lambda: None)
    save.function()
    assert ran == ['leeAct("save")'], 'no focused window, nothing run, nothing raised'

def test_the_standard_rows_are_left_to_appkit_rather_than_reimplemented():
    "Cut, Copy, Paste and Select All work by reaching the responder chain, not by running JS."
    from leela.blocks.keys.menus import BAR, Std
    std = {r.title: r for _, rows in BAR for r in rows if isinstance(r, Std)}
    assert {'Cut', 'Copy', 'Paste', 'Select All'} <= set(std)
    assert std['Cut'].selector == 'cut:' and std['Cut'].key == 'x'
    assert 'Enter Full Screen' in std, 'turning pywebview off takes its View menu with it'
    assert std['Enter Full Screen'].selector == 'toggleFullScreen:'
    assert {'Minimize', 'Zoom', 'Bring All to Front'} <= set(std), 'a Window menu macOS recognises'

def test_the_menu_bar_is_a_no_op_off_macos(monkeypatch):
    monkeypatch.setattr('kavacha.window.sys.platform', 'linux')
    assert desktop.menus() == []

def test_nothing_opens_a_window_the_app_cannot_open():
    """A scripted `window.open` is `WKNavigationTypeOther`, and pywebview's delegate only acts on a
    link activation, so in the packaged app it opens nothing and returns null. Four git and workspace
    buttons took the bare form and failed silently. `openExternal` is the one place that checks the
    return value and asks the server for a real browser instead."""
    js = read('leela/static/lee-core.js') + read('leela/static/lee-ide.js') + agent_modules()
    calls = [l.strip() for l in js.splitlines() if 'window.open(' in l]
    assert calls, 'the guarded form went missing rather than the guard'
    for line in calls:
        assert 'inDesktopShell()' in line or 'openExternal(' in line, \
            f'a window this app cannot open: {line[:120]}'

def test_an_external_link_never_navigates_the_app_window_away():
    """pywebview injects its bridge asynchronously, so `window.pywebview` is undefined for the first
    moment of the packaged app's life. A markdown link clicked in that window took the browser
    branch, which in WKWebView means the app's own window navigates to the site with no back."""
    js = read('leela/static/lee-core.js')
    assert 'const inDesktopShell = () => Boolean(window.pywebview || lee.inShell)' in js
    handler = js.split('function routeMarkdownLinks')[1].split('\n}')[0]
    assert 'if (!window.pywebview) return;' not in handler, 'the synchronous look is the bug'
    assert handler.index('e.preventDefault()') < handler.index('inDesktopShell()'), \
        'the default is stopped before the question is asked, so an unsettled bridge cannot navigate'
    assert 'openExternal(href)' in handler, 'a blocked or refused window still opens, via the server'
    assert 'lee.inShell = inShell()' in read('leela/blocks/workspace/projects.js'), \
        'nothing settles the flag `inDesktopShell` reads'


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
    """The probe asks through the route an attach would use. A `leela` started without `--app` has
    no hub and 404s there, and attaching to it would have opened nothing and said nothing."""
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


def test_a_second_launch_opens_windows_on_the_running_leela_instead_of_a_second_server(monkeypatch):
    """One server means one origin, so what the first copy saved is what the second reads. It was
    starting a second server on another port, which is a different origin and an empty one."""
    opened, served = [], []
    monkeypatch.setattr(leela_app, 'running_leela', lambda *a, **k: 5001)
    monkeypatch.setattr(leela_app, 'serve', lambda *a, **k: served.append(a))
    monkeypatch.setattr(leela_app, 'hub_open', lambda port, d, host=None: (
        {'ok': True, 'id': 'proj', 'name': 'proj', 'url': f'http://proj.localhost:{port}/'}
        if 'good' in str(d) else {'ok': False, 'error': 'not a folder'}))
    monkeypatch.setattr('leela.desktop.run_shell',
                        lambda urls, **kw: opened.append((list(urls), kw.get('titles'), kw.get('keys'))))
    leela_app.attach(5001, ['/w/good', '/w/bad'])
    assert served == [], 'no second server'
    urls, titles, keys = opened[0]
    assert urls == ['http://proj.localhost:5001/'], 'the window points at the running server'
    assert titles == ['leela — proj'] and keys == ['proj']
    # A folder the running copy refuses does not take the others down with it.
    assert len(urls) == 1


def test_attaching_to_a_copy_that_opens_nothing_says_so_rather_than_showing_a_blank_window(monkeypatch):
    said = []
    monkeypatch.setattr(leela_app, 'hub_open', lambda *a, **k: {'ok': False, 'error': 'not a folder'})
    monkeypatch.setattr('leela.desktop.run_shell', lambda *a, **k: said.append('opened a window'))
    monkeypatch.setattr('builtins.print', lambda *a, **k: said.append(' '.join(map(str, a))))
    leela_app.attach(5001, ['/w/bad'])
    assert not any(s == 'opened a window' for s in said)
    assert any('opened none of these folders' in s for s in said), said
