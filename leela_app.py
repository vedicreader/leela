#!/usr/bin/env python3
"""The entry point py2app and py2exe freeze: Leela as a desktop application.

Nothing here is a second implementation of Leela. It picks a free port, starts the ordinary
`leela --app` server on a daemon thread, and then spends the rest of its life owning the main
thread on behalf of the native window in `leela.desktop` -- an order macOS forces, since Cocoa
will not create a window anywhere else, and the reason this file exists rather than the app
bundle simply calling `leela.cli.main`. The port is chosen rather than fixed: a frozen app is
double-clicked, sometimes twice, and sometimes while a terminal `leela` already holds 5001.

    python leela_app.py              # the saved workspace, in a native window
    python leela_app.py ~/src/proj   # one folder
"""

from __future__ import annotations

import asyncio
import os
import socket
import sys
import threading

__all__ = ['free_port', 'folders', 'leela_args', 'serve', 'main', 'run']


def free_port(preferred=5001):
    "`preferred` if nothing holds it, else whatever the OS hands out."
    for port in (preferred, 0):
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(('127.0.0.1', port))
                return s.getsockname()[1]
            except OSError: continue
    raise OSError('no loopback port available')


def folders(argv=None):
    "Directory arguments passed to the app; a Finder/Explorer launch supplies none."
    args = sys.argv[1:] if argv is None else list(argv)
    return [a for a in args if os.path.isdir(a)]


def leela_args(port, dirs=(), extra=()):
    "The `leela` command line a desktop launch is."
    # `--app` for one independent workspace per folder, and `--gateway-port 0` so several
    # copies of the app can run without arguing over 8787 -- jupygate takes an ephemeral port.
    return ['--app', '--port', str(port), '--gateway-port', '0', *extra, *dirs]


def _loop_running():
    try: asyncio.get_running_loop(); return True
    except RuntimeError: return False


def serve(args, background=False):
    "Run `leela.cli.main(args)`, on this thread or a daemon one."
    # Imported at call time and reached through the module, so a test can replace
    # `leela.cli.main` and the frozen app pays for the web stack only once it is needed.
    import leela.cli

    def go(): leela.cli.main(args)

    if background or _loop_running():
        t = threading.Thread(target=go, daemon=True, name='leela-server')
        t.start()
        return t
    go()
    return None


def main():
    "Serve the workspace inline, or on a daemon thread when a loop already owns this one."
    # The server half alone, which is what embedding and the tests want; `run()` is the whole
    # application.
    return serve(leela_args(free_port(), folders()))


def run():
    """The application: server on a thread, CDP Chrome beside it, native window on this thread.

    A desktop app is double-clicked, so the folders come from three places in order: the ones
    the desktop passed (Finder's "Open With", Explorer's context menu, or a command line), the
    ones this app had open when it was last closed, and failing both, none at all -- which
    opens on the welcome screen rather than guessing.
    """
    from leela.desktop import last_folders, remember, run_shell, shell_ready, warm_cdp
    from leela.hub import workspace_urls

    dirs = remember(folders() or last_folders())
    port = free_port()
    cdp_port = int(os.environ.get('LEELA_CDP_PORT', 9223))
    ok, why = shell_ready()
    if not ok:
        # Chrome is the shell Leela shipped with before this one and is already a dependency of
        # the inline browser. Falling back to it beats refusing to open.
        print(f'leela: {why}; opening the workspace in Chrome instead')
        return serve(leela_args(port, dirs, ('--shell', 'chrome', '--cdp-port', str(cdp_port))))

    serve(leela_args(port, dirs, ('--shell', 'none', '--cdp-port', str(cdp_port))), background=True)
    warm_cdp(cdp_port)          # a no-op unless `$LEELA_CDP_EAGER` asks for Chrome up front
    # `--app` gives each folder its own workspace behind a host-dispatching hub, so each one
    # needs its own window: a single window on the bare loopback host would show the first
    # folder and silently strand the rest.
    urls = workspace_urls(dirs, port) if dirs else [f'http://127.0.0.1:{port}/']
    run_shell(urls, titles=titles_for(dirs), icon=_icon(),
              on_open_folder=lambda p: open_folder(port, p))


def titles_for(dirs):
    "One window title per workspace, named after its folder."
    return [f'leela — {os.path.basename(d)}' for d in dirs] or ['leela']


def open_folder(port, path, host='127.0.0.1'):
    "Add a folder to the running workspace, for one the desktop handed us after startup."
    # Through the HTTP route rather than the `Workspace` object, which the server owns on
    # another thread and another event loop; the in-app folder picker makes the same call.
    import urllib.parse
    import urllib.request

    from leela.desktop import remember, session
    url = f'http://{host}:{port}/fs/add_root?path=' + urllib.parse.quote(str(path), safe='')
    try:
        urllib.request.urlopen(url, timeout=30).close()
        remember(session()['folders'] + [str(path)])
    except Exception as e:
        print(f'  could not open {path}: {type(e).__name__}: {e}')


def _icon():
    "The window icon, for the backends that take one. macOS reads the bundle's ICNS instead."
    from pathlib import Path
    here = Path(getattr(sys, '_MEIPASS', '') or Path(__file__).resolve().parent)
    for c in (here/'packaging'/'assets'/'Leela.png', here/'Leela.png', here/'leela'/'Leela.png'):
        if c.is_file(): return str(c)
    return None


if __name__ == '__main__': run()
