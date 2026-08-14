"""The native desktop shell: a pywebview window over Leela's own loopback server.

A packaged Leela has three moving parts in one process tree. The FastHTML server holds a
loopback port; a pywebview window is the only thing the user ever sees; and beside them --
not inside them -- runs the persistent CDP Chrome that `leela.blocks.browser` screencasts
into the workspace. The window is the application. Chrome is a rendering engine Leela
drives, so a page opened from research is a tab in Leela rather than a second app to
switch to, and the profile it accumulates (logins, cookies) is the same one `fossick`
already uses from the command line.

The split is not a preference. Cocoa refuses to create a window off the main thread, so the
server runs on a daemon thread and the shell owns `main()`. `leela_app.py` -- the script
py2app and py2exe freeze -- exists to arrange exactly that.
"""

from __future__ import annotations

import os
import sys
import threading
import time

from . import errstr, leela_cfg
# The folder memory lives in `core` because the server writes it too -- adding a root in the
# app is the same event as launching with one. Re-exported here because it is a desktop idea.
from .core.projects import last_folders, recent_folders, remember, session  # noqa: F401

__all__ = ['BACKENDS', 'backend', 'shell_ready', 'wait_for_http', 'start_cdp', 'warm_cdp',
           'window_size', 'run_shell', 'watch_open_events', 'ShellApi',
           'session', 'remember', 'last_folders', 'recent_folders']

# pywebview's own name for each platform's webview. macOS gets WKWebView through pyobjc,
# Windows gets the Edge/Chromium WebView2 runtime through pythonnet, and Linux -- which is
# not a release target, but is where the shell is developed and tested -- gets WebKitGTK.
BACKENDS = {'darwin': 'cocoa', 'win32': 'edgechromium', 'linux': 'gtk'}

# Small enough for a laptop, large enough that the file tree, editor and variable panel are
# all on screen at first paint. Leela remembers the pane layout itself, so this is only ever
# the very first window.
DEFAULT_SIZE = (1440, 900)
MIN_SIZE = (900, 560)

# The window's own web storage. `private_mode=False` plus a stable path is what keeps
# `localStorage` -- which is where Leela puts the pane layout, the recent-files order and the
# editor preferences -- from being wiped between launches, exactly as a browser profile would.
STORAGE = leela_cfg/'webview'

class ShellApi:
    """What the page may ask the native window for, as `window.pywebview.api.*`.

    Only the things a web page genuinely cannot do for itself. A folder picker is the whole
    list: a browser file input yields file contents, never a directory path, so without this
    the only way to open a project in a packaged app is to type its path.
    """

    def pick_folder(self):
        "The platform's own folder chooser. Returns a path, or None if it was cancelled."
        import webview
        window = webview.active_window()
        if window is None: return None
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
    "`(ok, why)` -- whether a native window can be opened here, and what is missing if not."
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
        # Any answer at all means the port is live: a 4xx/5xx raises HTTPError but proves the
        # server is listening, which is the only question being asked here.
        except urllib.error.HTTPError: return True
        except Exception: time.sleep(interval)
    return False


EAGER_CDP = 'LEELA_CDP_EAGER'


def start_cdp(port=9223, headless=True, wait=False, timeout=None, profile=None):
    """Bring up the persistent CDP Chrome the inline browser renders into.

    Started on a thread and never waited on by default: Chrome takes a second or two, and no
    part of opening the workspace needs it. The first inline tab pays whatever is left.

    `profile` defaults to fossick's own, which is the point -- its cookies are why a page
    reads here and not through a plain fetch. Chrome allows one process per profile, so
    anything wanting a *second* browser (the screenshot tooling, the tests) must name its own.
    """
    def boot():
        try:
            from fossick.cdp import _debug_ready, cdp_setup
            from fossick.core import syncy
            if _debug_ready(port): return
            syncy(cdp_setup(port=port, headless=headless, timeout=timeout,
                            user_data_dir=profile))
        except Exception as e:
            # A missing or unstartable Chrome costs the inline browser, not the workspace.
            # `leela.blocks.browser` reports the same failure again, in the panel, when
            # someone actually asks for a page.
            print(f'  inline browser unavailable: {errstr(e)}')

    t = threading.Thread(target=boot, daemon=True, name='leela-cdp-boot')
    t.start()
    if wait: t.join(timeout or 30)
    return t


def warm_cdp(port=9223, profile=None):
    """Start Chrome at launch only if asked to. Off by default, and the default is the point.

    A headless Chrome is several hundred megabytes across a dozen processes -- far more than
    the workspace it would be sitting beside -- and most sessions never open a web tab. So it
    is started by the first page that needs one, which `Browser` already does, and the couple
    of seconds that costs is paid by the person who asked for a page rather than by everyone.
    Set `$LEELA_CDP_EAGER=1` to trade the memory back for that latency.
    """
    if os.environ.get(EAGER_CDP, '').strip() not in ('1', 'true', 'yes'): return None
    return start_cdp(port, headless=True, profile=profile)


def window_size(spec=None):
    "`WIDTHxHEIGHT` from `spec` or `$LEELA_WINDOW_SIZE`, else the default."
    spec = spec or os.environ.get('LEELA_WINDOW_SIZE', '')
    try:
        w, h = (int(n) for n in str(spec).lower().split('x', 1))
        # A window smaller than the minimum is a typo, not a request; pywebview would honour
        # it and hand back something unusable.
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


def run_shell(urls, titles=(), url_wait=90, gui=None, icon=None, size=None, on_ready=None,
              on_open_folder=None):
    """Open one native window per workspace URL and run the GUI loop until they all close.

    Blocks, and must be called on the main thread. Each window opens immediately on a splash
    document and swaps to its real URL once the server answers, so a slow first import shows
    a window rather than a bouncing dock icon.

    `on_open_folder(path)` is called when the desktop hands the *running* application a folder
    -- dropped on the Dock icon, or opened with it from Finder. Without it, the second folder
    you open goes nowhere, because macOS delivers it to the process that is already running
    instead of starting another one.
    """
    import webview

    ok, why = shell_ready()
    if not ok: raise RuntimeError(why)
    urls = list(urls)
    if not urls: raise ValueError('the desktop shell needs at least one workspace URL')
    titles = list(titles) + [''] * (len(urls) - len(titles))
    w, h = size or window_size()
    STORAGE.mkdir(parents=True, exist_ok=True)

    api = ShellApi()
    windows = [webview.create_window(t or 'leela', html=LOADING, width=w, height=h,
                                     min_size=MIN_SIZE, background_color='#171b20',
                                     text_select=True, zoomable=True, easy_drag=False,
                                     js_api=api)
               for t in titles]
    if on_open_folder is not None: watch_open_events(on_open_folder)

    def load(*_):
        "Runs once the GUI loop is up: wait for the server, then point each window at it."
        for window, url in zip(windows, urls):
            if wait_for_http(url, timeout=url_wait): window.load_url(url)
            else: window.load_html(_unreachable(url))
        if on_ready is not None:
            try: on_ready()
            except Exception as e: print(f'  desktop shell: {errstr(e)}')

    webview.start(load, gui=gui or why, debug=bool(os.environ.get('LEELA_WEBVIEW_DEBUG')),
                  private_mode=False, storage_path=str(STORAGE), icon=icon)


def _unreachable(url):
    return (LOADING.replace('starting the workspace…',
                            f'the workspace at {url} did not answer')
                   .replace('<i>', '<i style="color:#e06c75">'))


def watch_open_events(on_folder):
    """Answer the desktop when it hands a running Leela a folder to open.

    macOS only, and best-effort. Opening a folder with an application that is already running
    does not start a second copy and does not go through argv: the Finder sends the running
    process an `odoc` Apple Event, and a process that does not answer one simply ignores the
    request. Registering the handler is what turns "Open With → Leela" and a Dock-icon drop
    into a folder appearing in the workspace.

    Windows has no equivalent to answer -- Explorer starts a new process with the path in
    argv, which `leela_app.folders()` already reads.
    """
    if sys.platform != 'darwin': return None
    try:
        from Foundation import NSAppleEventManager, NSURL          # noqa: F401
        from AppKit import NSApplication                            # noqa: F401
    except ImportError:
        return None

    # 'aevt'/'odoc' — the Open Documents event, as four-character codes packed into ints.
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
    from Foundation import NSObject

    class _OpenHandler(NSObject):
        "An Objective-C object, because an Apple Event handler must be a selector on one."

        def init_with(self, fn):
            self = super().init()
            self._fn = fn
            return self

        def handleEvent_reply_(self, event, reply): self._fn(event, reply)
except Exception:                        # pragma: no cover - everywhere else
    _OpenHandler = None
