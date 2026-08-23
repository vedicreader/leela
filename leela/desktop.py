"The native desktop shell: a pywebview window over Leela's own loopback server."

from __future__ import annotations

import os, sys, threading, time

from . import errstr, leela_cfg
from .core.projects import last_folder, last_folders, recent_folders, remember, session  # noqa: F401

__all__ = ['BACKENDS', 'backend', 'shell_ready', 'wait_for_http', 'start_cdp', 'warm_cdp',
           'window_size', 'run_shell', 'keep_running_in_dock', 'dock_menu', 'DOCK_RECENT',
           'watch_open_events', 'ShellApi',
           'session', 'remember', 'last_folders', 'last_folder', 'recent_folders']

BACKENDS = {'darwin': 'cocoa', 'win32': 'edgechromium', 'linux': 'gtk'}
DEFAULT_SIZE = (1440, 900)
MIN_SIZE = (900, 560)
STORAGE = leela_cfg/'webview'
EAGER_CDP = 'LEELA_CDP_EAGER'

class ShellApi:
    "What the page may ask the native window for, as `window.pywebview.api.*`."
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
    """The two delegate subclasses, built once.

    An Objective-C class name is global to the runtime, so defining these twice raises "overriding
    existing Objective-C class" and the second call would silently fall back. They read module
    state rather than closing over it, which is what lets them be built once.
    """
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
    """Hide the last window instead of quitting, the way a Mac app behaves, and fill the Dock menu.

    Reopening shows the window closed most recently and no others: four windows closed one by one
    should not all come back at once. Cmd+Q still quits. False when pywebview has moved on, which
    leaves the old behaviour rather than refusing to start.
    """
    global _on_folder
    try:
        from webview.platforms.cocoa import BrowserView
        _on_folder = on_folder
        BrowserView.WindowDelegate, BrowserView.AppDelegate = _dock_delegates()
        return True
    except Exception as e:
        print(f'  the last window will quit Leela: {errstr(e)}')
        return False

def run_shell(urls, titles=(), url_wait=90, gui=None, icon=None, size=None, on_ready=None,
              on_open_folder=None):
    "One native window per workspace URL, until they all close. Blocks, on the main thread."
    import webview
    ok, why = shell_ready()
    if not ok: raise RuntimeError(why)
    urls = list(urls)
    if not urls: raise ValueError('the desktop shell needs at least one workspace URL')
    titles = list(titles) + [''] * (len(urls) - len(titles))
    w, h = size or window_size()
    STORAGE.mkdir(parents=True, exist_ok=True)
    api = ShellApi()
    if sys.platform == 'darwin': keep_running_in_dock(on_open_folder)   # before any window takes a delegate
    windows = [webview.create_window(t or 'leela', html=LOADING, width=w, height=h,
                                     min_size=MIN_SIZE, background_color='#171b20',
                                     text_select=True, zoomable=True, easy_drag=False,
                                     js_api=api)
               for t in titles]
    if on_open_folder is not None: watch_open_events(on_open_folder)
    def load(*_):
        "Once the GUI loop is up: wait for the server, then point each window at it."
        for window, url in zip(windows, urls):
            if wait_for_http(url, timeout=url_wait): window.load_url(url)
            else: window.load_html(_unreachable(url))
        if on_ready is None: return
        try: on_ready()
        except Exception as e: print(f'  desktop shell: {errstr(e)}')
    webview.start(load, gui=gui or why, debug=bool(os.environ.get('LEELA_WEBVIEW_DEBUG')),
                  private_mode=False, storage_path=str(STORAGE), icon=icon)

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
