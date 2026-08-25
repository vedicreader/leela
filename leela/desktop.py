"The native desktop shell: a pywebview window over Leela's own loopback server."

from __future__ import annotations

import os, sys, threading, time

from . import errstr, leela_cfg
from .core.projects import last_folder, last_folders, recent_folders, remember, session  # noqa: F401

__all__ = ['BACKENDS', 'backend', 'shell_ready', 'wait_for_http', 'start_cdp', 'warm_cdp',
           'window_size', 'run_shell', 'keep_running_in_dock', 'dock_menu', 'DOCK_RECENT',
           'watch_open_events', 'ShellApi', 'shell_api', 'make_window', 'open_window',
           'off_main_thread', 'menus', 'menu_bar', 'mac_key', 'menu_chord',
           'session', 'remember', 'last_folders', 'last_folder', 'recent_folders']

BACKENDS = {'darwin': 'cocoa', 'win32': 'edgechromium', 'linux': 'gtk'}
DEFAULT_SIZE = (1440, 900)
MIN_SIZE = (900, 560)
STORAGE = leela_cfg/'webview'
EAGER_CDP = 'LEELA_CDP_EAGER'

class ShellApi:
    "What the page may ask the native window for, as `window.pywebview.api.*`."
    #: Set by `run_shell`. Takes a folder and gives it a window of its own.
    on_open_folder = None
    def open_folder(self, path):
        "Open a folder in a window of its own. pywebview runs every `js_api` call on its own thread."
        if not path or self.on_open_folder is None: return False
        self.on_open_folder(str(path))
        return True
    def pick_folder(self):
        "The platform's own folder chooser. A path, or None if it was cancelled."
        import webview
        if (window := webview.active_window()) is None: return None
        try: picked = window.create_file_dialog(webview.FileDialog.FOLDER)
        except Exception as e:
            print(f'  folder dialog: {errstr(e)}')
            return None
        return str(picked[0]) if picked else None
    def recent(self):
        "The recent folder list, so the welcome screen has it before the server is up."
        return recent_folders()

def backend(platform=None):
    "pywebview's GUI name for `platform`, or None where Leela has no supported webview."
    return BACKENDS.get(platform or sys.platform)

def shell_ready(platform=None):
    "`(ok, why)`: whether a native window can be opened here, and what is missing if not."
    gui = backend(platform)
    if gui is None: return False, f'no native webview backend for {platform or sys.platform}'
    try: import webview  # noqa: F401
    except ImportError as e: return False, f'pywebview is not installed ({errstr(e)})'
    return True, gui

def wait_for_http(url, timeout=60, interval=.1):
    "Block until `url` answers, or `timeout` passes. True if the server came up."
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=.5).close()
            return True
        except urllib.error.HTTPError: return True   # a 4xx proves the port is live
        except Exception: time.sleep(interval)
    return False

def start_cdp(port=9223, headless=True, wait=False, timeout=None, profile=None):
    "Bring up the persistent CDP Chrome the inline browser renders into, on a thread."
    def boot():
        try:
            from fossick.cdp import _debug_ready, cdp_setup
            from fossick.core import syncy
            if _debug_ready(port): return
            syncy(cdp_setup(port=port, headless=headless, timeout=timeout, user_data_dir=profile))
        except Exception as e: print(f'  inline browser unavailable: {errstr(e)}')
    t = threading.Thread(target=boot, daemon=True, name='leela-cdp-boot')
    t.start()
    if wait: t.join(timeout or 30)
    return t

def warm_cdp(port=9223, profile=None):
    "Start Chrome at launch only if `$LEELA_CDP_EAGER` asks for it. See `docs/desktop.md`."
    if os.environ.get(EAGER_CDP, '').strip() not in ('1', 'true', 'yes'): return None
    return start_cdp(port, headless=True, profile=profile)

def window_size(spec=None):
    "`WIDTHxHEIGHT` from `spec` or `$LEELA_WINDOW_SIZE`, else the default."
    spec = spec or os.environ.get('LEELA_WINDOW_SIZE', '')
    try:
        w, h = (int(n) for n in str(spec).lower().split('x', 1))
        if w >= MIN_SIZE[0] and h >= MIN_SIZE[1]: return w, h
    except (ValueError, TypeError): pass
    return DEFAULT_SIZE

LOADING = """<!doctype html><meta charset=utf-8><title>leela</title>
<style>html,body{height:100%;margin:0;background:#171b20;color:#f4f7f9;
font:15px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
display:flex;align-items:center;justify-content:center}
div{text-align:center;opacity:.85}b{display:block;font-size:34px;letter-spacing:-.02em;margin-bottom:10px}
i{font-style:normal;font-size:13px;opacity:.6}</style>
<div><b>leela</b><i>starting the workspace…</i></div>"""

def _unreachable(url):
    "The same splash, saying why nothing arrived."
    return (LOADING.replace('starting the workspace…', f'the workspace at {url} did not answer')
                   .replace('<i>', '<i style="color:#e06c75">'))

DOCK_RECENT = 8          #: rows on the Dock menu, which is a shortcut and not a file browser

_dock_target = None

def _recent_target(on_folder):
    "One for the life of the app: a menu holds no reference to a Python object, so this must."
    global _dock_target
    if _dock_target is None: _dock_target = _RecentTarget.alloc().init_with(on_folder)
    return _dock_target

def dock_menu(on_folder, recent=None):
    "The Dock's own menu: the folders you last had open, newest first. `recent_folders` gives paths."
    from AppKit import NSMenu, NSMenuItem
    rows = list(recent_folders() if recent is None else recent)[:DOCK_RECENT]
    menu = NSMenu.alloc().init()
    if not rows:
        menu.addItem_(_disabled('No recent folders'))
        return menu
    target = _recent_target(on_folder)
    for path in rows:
        path = str(path)
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            os.path.basename(path.rstrip('/')) or path, b'openRecent:', '')
        item.setToolTip_(path)
        item.setRepresentedObject_(path)
        item.setTarget_(target)
        menu.addItem_(item)
    return menu

def _disabled(title):
    from AppKit import NSMenuItem
    item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, '')
    item.setEnabled_(False)
    return item

_hidden, _on_folder, _delegates = [], None, None

def _dock_delegates():
    "The two delegate subclasses. Built once: an Objective-C class name is global to the runtime."
    global _delegates
    if _delegates is not None: return _delegates
    from Foundation import NO, YES
    from webview.platforms.cocoa import BrowserView
    class Windows(BrowserView.WindowDelegate):
        def windowShouldClose_(self, window):
            window.orderOut_(None)
            if window in _hidden: _hidden.remove(window)
            _hidden.append(window)
            return NO
    class App(BrowserView.AppDelegate):
        def applicationShouldHandleReopen_hasVisibleWindows_(self, app, visible):
            if not visible and _hidden: _hidden.pop().makeKeyAndOrderFront_(None)
            return YES
        def applicationDockMenu_(self, app):
            try: return dock_menu(_on_folder)
            except Exception as e: print(f'  dock menu: {errstr(e)}'); return None
    _delegates = (Windows, App)
    return _delegates

def keep_running_in_dock(on_folder=None):
    "Hide the last window rather than quit, and fill the Dock menu. Reopen shows one window. Cmd+Q quits."
    global _on_folder
    try:
        from webview.platforms.cocoa import BrowserView
        _on_folder = on_folder
        BrowserView.WindowDelegate, BrowserView.AppDelegate = _dock_delegates()
        return True
    except Exception as e:
        print(f'  the last window will quit Leela: {errstr(e)}')
        return False

#: Everything but the title and the size, so a window opened at launch and one opened an hour
#: later are the same window.
WINDOW_KW = dict(min_size=MIN_SIZE, background_color='#171b20', text_select=True, zoomable=True,
                 easy_drag=False)

_api = None
#: Which window is showing which workspace, so a folder already open is raised, not opened twice.
_windows = {}

def shell_api():
    "The one `ShellApi` every window shares."
    global _api
    if _api is None: _api = ShellApi()
    return _api

def make_window(title='leela', size=None):
    "A window on the splash, waiting for a URL."
    import webview
    w, h = size or window_size()
    STORAGE.mkdir(parents=True, exist_ok=True)
    return webview.create_window(title or 'leela', html=LOADING, width=w, height=h,
                                 js_api=shell_api(), **WINDOW_KW)

def off_main_thread(fn, name='leela-shell'):
    "Run `fn(arg)` on a thread of its own; `create_window` builds nothing on the main thread."
    def go(arg): threading.Thread(target=fn, args=(arg,), daemon=True, name=name).start()
    return go

def open_window(url, title='leela', key=None, url_wait=90):
    "A window on `url`, raised rather than opened twice when `key` already has one."
    if key and (window := _windows.get(key)) is not None:
        try: window.show()      # cocoa's `show` is a `callAfter`, so any thread may ask
        except Exception as e: print(f'  could not raise the window for {title}: {errstr(e)}')
        return window
    window = make_window(title)
    if key: _windows[key] = window
    _point(window, url, url_wait)
    return window

def _point(window, url, url_wait=90):
    "Wait for the server, then show the workspace. A window that never answers says so."
    if wait_for_http(url, timeout=url_wait): window.load_url(url)
    else: window.load_html(_unreachable(url))

def run_shell(urls, titles=(), url_wait=90, gui=None, icon=None, size=None, on_ready=None,
              on_open_folder=None, keys=()):
    "One native window per workspace URL, until they all close. Blocks, on the main thread."
    import webview
    ok, why = shell_ready()
    if not ok: raise RuntimeError(why)
    urls = list(urls)
    if not urls: raise ValueError('the desktop shell needs at least one workspace URL')
    titles = list(titles) + [''] * (len(urls) - len(titles))
    keys = list(keys) + [None] * (len(urls) - len(keys))
    # Every native caller reaches this on the main thread, and none of them may build a window there.
    open_folder = off_main_thread(on_open_folder, 'leela-open-folder') if on_open_folder else None
    shell_api().on_open_folder = open_folder
    if sys.platform == 'darwin': keep_running_in_dock(open_folder)  # before any window takes a delegate
    windows = [make_window(t, size) for t in titles]
    for key, window in zip(keys, windows):
        if key: _windows[key] = window
    if open_folder is not None: watch_open_events(open_folder)
    def load(*_):
        "Once the GUI loop is up: wait for the server, then point each window at it."
        for window, url in zip(windows, urls): _point(window, url, url_wait)
        if on_ready is None: return
        try: on_ready()
        except Exception as e: print(f'  desktop shell: {errstr(e)}')
    # One list, shared: pywebview rebuilds the bar whenever the focused window's menu is not the
    # one it built last, and a window opened for a folder later has no menu of its own.
    bar = menus()
    webview.start(load, gui=gui or why, debug=bool(os.environ.get('LEELA_WEBVIEW_DEBUG')),
                  private_mode=False, storage_path=str(STORAGE), icon=icon, menu=bar)

def menus():
    "The menu bar, or an empty bar off macOS. Its own function so a test can build one."
    if sys.platform != 'darwin': return []
    try:
        import webview
        webview.settings['SHOW_DEFAULT_MENUS'] = False   # ours are in the order macOS expects
        bar, specs = menu_bar()
        install_menu_patch(specs)
        return bar
    except Exception as e:
        print(f'  no menu bar: {errstr(e)}')
        return []

def watch_open_events(on_folder):
    "Answer the `odoc` Apple Event Finder sends a running Leela. macOS only, best-effort."
    if sys.platform != 'darwin': return None
    try: from Foundation import NSAppleEventManager, NSURL
    except ImportError: return None
    def code(s): return int.from_bytes(s.encode(), 'big')
    def handle(event, _reply):
        try:
            items = event.paramDescriptorForKeyword_(code('----'))
            for i in range(1, (items.numberOfItems() or 0) + 1):
                url = items.descriptorAtIndex_(i).stringValue()
                if not url: continue
                p = NSURL.URLWithString_(url).path() if url.startswith('file:') else url
                if p and os.path.isdir(str(p)): on_folder(str(p))
        except Exception as e: print(f'  open-folder event: {errstr(e)}')
    try:
        mgr = NSAppleEventManager.sharedAppleEventManager()
        mgr.setEventHandler_andSelector_forEventClass_andEventID_(
            _OpenHandler.alloc().init_with(handle), b'handleEvent:reply:',
            code('aevt'), code('odoc'))
        return handle
    except Exception as e:
        print(f'  could not register the open-folder handler: {errstr(e)}')
        return None

try:                                     # pragma: no cover - macOS only
    import objc
    from Foundation import NSObject
    class _RecentTarget(NSObject):
        "What a Dock menu row fires at. `objc.super`, as `_OpenHandler` needs for the same reason."
        def init_with(self, fn):
            self = objc.super(_RecentTarget, self).init()
            if self is None: return None
            self._fn = fn
            return self
        def openRecent_(self, sender):
            path = sender.representedObject()
            if self._fn and path: self._fn(str(path))

    class _OpenHandler(NSObject):
        "An Apple Event handler must be a selector on an Objective-C object."
        def init_with(self, fn):
            # `objc.super`, not `super()`: the builtin has no `init` to find on an ObjC class, so
            # registration raised and nothing opened a folder dropped on the Dock or picked in Finder.
            self = objc.super(_OpenHandler, self).init()
            if self is None: return None
            self._fn = fn
            return self
        def handleEvent_reply_(self, event, reply): self._fn(event, reply)
except Exception:                        # pragma: no cover - everywhere else
    _OpenHandler = _RecentTarget = None


# The Mac menu bar. pywebview builds it; what is added here is the ordering, the chords it has no
# support for, and the rows AppKit implements itself. See `docs/desktop.md`.

CMD, CTRL, ALT, SHIFT = 1 << 20, 1 << 18, 1 << 19, 1 << 17
_MODS = {'mod': CMD, 'cmd': CMD, 'ctrl': CTRL, 'alt': ALT, 'opt': ALT, 'shift': SHIFT,
         'hyper': CMD | CTRL | ALT | SHIFT}
#: AppKit spells these as private-use unichars, not as their names.
_NAMED = {'up': '', 'down': '', 'left': '', 'right': '',
          'pageup': '', 'pagedown': '', 'home': '', 'end': '',
          'delete': '', 'enter': '\r', 'return': '\r', 'tab': '\t', 'space': ' ',
          'backspace': '\x08', 'escape': '\x1b'}

def mac_key(chord):
    "`(keyEquivalent, modifierMask)` for one Leela chord, or None when AppKit cannot spell it."
    parts = str(chord or '').split()[0].split('+') if chord else []
    if not parts or not parts[-1]: return None
    mask, base = 0, parts[-1]
    for p in parts[:-1]:
        if (m := _MODS.get(p.lower())) is None: return None
        mask |= m
    if len(base) == 1 and base.isupper(): mask |= SHIFT
    base = _NAMED.get(base.lower(), base.lower())
    if len(base) != 1: return None
    return base, mask

def menu_chord(action):
    """The chord to put on a menu row, or None to leave it bare.

    A key equivalent is consulted before the keystroke reaches the web view, so anything installed
    here is taken away from the page. Only a global action with a modifier is safe: a scoped one
    would fire outside its scope, and a bare letter would fire while you were typing it.
    """
    from .core.keys import lookup
    k = lookup(action)
    if k is None or not k.bound or k.scope != 'global': return None
    first = k.keys[0]
    if not (set(first.split('+')[:-1]) & {'mod', 'cmd', 'ctrl', 'alt', 'opt', 'hyper'}): return None
    return mac_key(first)

def _title(row):
    from .core.keys import lookup
    k = lookup(row.action)
    t = (k.label if k and k.label else row.action.replace('_', ' '))
    return t[:1].upper() + t[1:]

def menu_bar(run=None):
    "pywebview menus for `BAR`, plus the table `_decorate` needs to finish them off AppKit-side."
    from webview.menu import Menu, MenuAction, MenuSeparator
    from .blocks.keys.menus import BAR, Js, MenuItem, Std
    run = run or _menu_run
    menus, specs = [], {}
    for title, rows in BAR:
        items = []
        for row in rows:
            if isinstance(row, MenuItem) and not row.action: items.append(MenuSeparator()); continue
            if isinstance(row, Std):
                specs[(title, row.title)] = row
                items.append(MenuAction(row.title, lambda: None))
            elif isinstance(row, Js):
                items.append(MenuAction(row.title, (lambda e: lambda: run(e))(row.expr)))
            else:
                name = _title(row)
                specs[(title, name)] = row
                items.append(MenuAction(name, (lambda a: lambda: run(f'leeAct("{a}")'))(row.action)))
        menus.append(Menu(title, items))
    return menus, specs

def _menu_run(js):
    "Run one expression in the window that has focus. pywebview already calls this off the main thread."
    import webview
    if (window := webview.active_window()) is None: return
    try: window.evaluate_js(js)
    except Exception as e: print(f'  menu: {errstr(e)}')

_menu_patched = False

def install_menu_patch(specs):
    """Finish each item off as AppKit needs it, wherever pywebview builds the bar.

    It rebuilds on every focus change to a window whose menu differs, so anything done once to the
    bar after start is thrown away. This wraps the one method both rebuild paths go through.
    """
    global _menu_patched
    if _menu_patched: return False
    try:
        from webview.platforms.cocoa import BrowserView
    except Exception as e:
        print(f'  no menu bar: {errstr(e)}')
        return False
    original = BrowserView._recreate_menus
    def recreate(self, user_menu):
        main = original(self, user_menu)
        try: _decorate(main, specs)
        except Exception as e: print(f'  menu bar: {errstr(e)}')
        return main
    BrowserView._recreate_menus = recreate
    _menu_patched = True
    return True

def _decorate(main, specs):
    "Chords onto the rows that may have one, and the responder chain onto the rows AppKit owns."
    import AppKit
    from .blocks.keys.menus import Std
    for i in range(main.numberOfItems()):
        sub = main.itemAtIndex_(i).submenu()
        if sub is None: continue
        title = str(sub.title())
        for j in range(sub.numberOfItems()):
            item = sub.itemAtIndex_(j)
            spec = specs.get((title, str(item.title())))
            if spec is None: continue
            if isinstance(spec, Std):
                item.setTarget_(None)          # nil target is what walks the responder chain
                item.setAction_(spec.selector)
                got = mac_key(f'{spec.mods}+{spec.key}') if spec.key else None
            else: got = menu_chord(spec.action)
            if got: item.setKeyEquivalent_(got[0]); item.setKeyEquivalentModifierMask_(got[1])
        if title == 'Window': AppKit.NSApp().setWindowsMenu_(sub)
