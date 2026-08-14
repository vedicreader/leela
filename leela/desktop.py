"""The native desktop shell: a pywebview window over Leela's own loopback server.

The window is the application. The persistent CDP Chrome that `leela.blocks.browser`
screencasts into the workspace runs *beside* it rather than inside it, so a page opened from
research is a tab in Leela instead of a second app to switch to, and the profile it
accumulates is the one `fossick` already uses. Cocoa refuses to create a window off the main
thread, so the server runs on a daemon thread and the shell owns `main()` -- which is why
`leela_app.py`, the script py2app and py2exe freeze, exists at all.
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

# pywebview's own name for each platform's webview: WKWebView through pyobjc, the Edge/Chromium
# WebView2 runtime through pythonnet, and WebKitGTK. Linux is not a release target, but is
# where the shell is developed and tested.
BACKENDS = {'darwin': 'cocoa', 'win32': 'edgechromium', 'linux': 'gtk'}

# Only ever the very first window -- Leela remembers the pane layout itself -- so it wants the
# file tree, editor and variable panel all on screen at first paint.
DEFAULT_SIZE = (1440, 900)
MIN_SIZE = (900, 560)

# The window's own web storage. `private_mode=False` plus a stable path is what keeps
# `localStorage` -- the pane layout, the recent-files order, the editor preferences -- from
# being wiped between launches, exactly as a browser profile would.
STORAGE = leela_cfg/'webview'


class ShellApi:
    "What the page may ask the native window for, as `window.pywebview.api.*`."
    # Only the things a web page genuinely cannot do for itself, which is a list of one: a
    # browser file input yields file contents, never a directory path, so without this the only
    # way to open a project in a packaged app is to type its path.

    def pick_folder(self):
        "The platform's own folder chooser. Returns a path, or None if it was cancelled."
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
        # A 4xx/5xx raises HTTPError but proves the port is live, which is the only question.
        except urllib.error.HTTPError: return True
        except Exception: time.sleep(interval)
    return False


EAGER_CDP = 'LEELA_CDP_EAGER'


def start_cdp(port=9223, headless=True, wait=False, timeout=None, profile=None):
    """Bring up the persistent CDP Chrome the inline browser renders into, on a thread.

    Never waited on by default: Chrome takes a second or two and no part of opening the
    workspace needs it. `profile` defaults to fossick's own, which is the point -- its cookies
    are why a page reads here and not through a plain fetch -- and Chrome allows one process
    per profile, so anything wanting a *second* browser (screenshots, tests) must name its own.
    """
    def boot():
        try:
            from fossick.cdp import _debug_ready, cdp_setup
            from fossick.core import syncy
            if _debug_ready(port): return
            syncy(cdp_setup(port=port, headless=headless, timeout=timeout,
                            user_data_dir=profile))
        # A missing or unstartable Chrome costs the inline browser, not the workspace;
        # `leela.blocks.browser` reports it again, in the panel, when someone asks for a page.
        except Exception as e: print(f'  inline browser unavailable: {errstr(e)}')

    t = threading.Thread(target=boot, daemon=True, name='leela-cdp-boot')
    t.start()
    if wait: t.join(timeout or 30)
    return t


def warm_cdp(port=9223, profile=None):
    """Start Chrome at launch only if `$LEELA_CDP_EAGER` asks for it.

    Off by default, and the default is the point: a headless Chrome is several hundred
    megabytes across a dozen processes -- more than the workspace beside it -- and most
    sessions never open a web tab, so the first page that needs one starts it and pays.
    """
    if os.environ.get(EAGER_CDP, '').strip() not in ('1', 'true', 'yes'): return None
    return start_cdp(port, headless=True, profile=profile)


def window_size(spec=None):
    "`WIDTHxHEIGHT` from `spec` or `$LEELA_WINDOW_SIZE`, else the default."
    spec = spec or os.environ.get('LEELA_WINDOW_SIZE', '')
    try:
        w, h = (int(n) for n in str(spec).lower().split('x', 1))
        # Smaller than the minimum is a typo, not a request, and pywebview would honour it.
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


def run_shell(urls, titles=(), url_wait=90, gui=None, icon=None, size=None, on_ready=None,
              on_open_folder=None):
    """Open one native window per workspace URL and run the GUI loop until they all close.

    Blocks, and must be called on the main thread. Each window opens immediately on a splash
    document and swaps to its real URL once the server answers, so a slow first import shows a
    window rather than a bouncing dock icon. `on_open_folder(path)` is called when the desktop
    hands the *running* application a folder -- dropped on the Dock icon, or opened with it
    from Finder -- which without it goes nowhere: macOS delivers it to the process that is
    already running instead of starting another one.
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


def watch_open_events(on_folder):
    """Answer the `odoc` Apple Event the Finder sends a Leela that is already running.

    macOS only, and best-effort. Opening a folder with a running application starts no second
    copy and goes through no argv, and a process that does not answer the event simply ignores
    the request -- registering this handler is what turns "Open With → Leela" and a Dock-icon
    drop into a folder appearing in the workspace. Windows has no equivalent to answer:
    Explorer starts a new process with the path in argv, which `leela_app.folders()` reads.
    """
    if sys.platform != 'darwin': return None
    try: from Foundation import NSAppleEventManager, NSURL
    except ImportError: return None

    def code(s): return int.from_bytes(s.encode(), 'big')   # a four-character code, as an int

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
