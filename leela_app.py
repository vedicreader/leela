#!/usr/bin/env python3
"The entry point py2app and py2exe freeze. See `docs/desktop.md`."

from __future__ import annotations

import asyncio, os, sys, threading, time

from fastcore.all import Path, first, is_port_free
from fastcore.net import free_port as any_port

__all__ = ['free_port', 'running_leela', 'leela_on', 'folders', 'files', 'leela_args', 'serve', 'main',
           'run', 'attach', 'hub_open', 'open_folder', 'open_file', 'confirm', 'titles_for', 'HOME_KEY']

HOST = '127.0.0.1'
#: The window on the bare loopback host. A slug is `[a-z0-9-]+`, so a colon keeps this from ever being a folder's window key.
HOME_KEY = 'leela:home'

# Only when frozen: a normal install has one environment and installs into it, and an extras
# directory left over from running the app would then shadow it. See `leela.use_extras`.
if getattr(sys, 'frozen', False):
    from leela import seal_bundle, use_extras, use_login_path, use_utf8
    seal_bundle()         # first: nothing may write into the signed bundle, and pyskills writes at import
    from leela.core.envs import apply_stored_env, import_login_env
    use_extras()
    use_utf8()            # no LANG means an ASCII default, and importing rishi.claude then raises
    use_login_path()      # Finder starts an app with almost no PATH, so git and claude go missing
    # A Finder launch has launchd's environment, so a key from a shell profile is missing and every hosted model refuses the turn. `leela.cli` does the same for the terminal.
    if os.environ.get('LEELA_SHELL_ENV', '1') != '0': import_login_env()
    apply_stored_env()    # last, and winning: what a person typed into Leela beats a wrong shell

#: The ladder a window is served from. Fixed, not OS-assigned: a moving port moves the `http://<slug>.localhost:<port>` origin, and the browser keeps nothing per origin at the new one.
from leela import PORT
from leela.core.projects import title_folder, window_title
PORTS = range(PORT, PORT+10)

def leela_on(port, host=HOST, timeout=.6):
    "Whether `port` holds a Leela on this config dir that can be attached to, asked through the attach route so a yes means the hub answers, not that something Leela-shaped listens."
    import json, urllib.error, urllib.request
    from leela.hub import OPEN_PATH, cfg_mark
    try:
        with urllib.request.urlopen(f'http://{host}:{port}{OPEN_PATH}', timeout=timeout) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        if e.code != 400: return False        # somebody else's refusal
        body = e.read()
    except Exception: return False
    try: d = json.loads(body)
    except ValueError: return False
    if not (isinstance(d, dict) and d.get('ok') is False and 'not a folder' in str(d.get('error', ''))): return False
    # A Leela from before the mark serves the default dir, as nearly every running copy does.
    return d.get('config', cfg_mark(Path.home()/'.config'/'leela')) == cfg_mark()

def running_leela(ports=PORTS, host=HOST):
    "The port a Leela is already answering on, or None."
    return first(p for p in ports if not is_port_free(p, host) and leela_on(p, host))

def free_port(preferred=PORT, ports=PORTS, host=HOST):
    "The first free port on the ladder. Deterministic, so a relaunch lands where the first did; OS-assigned fallback only when the whole ladder is taken."
    rungs = [preferred, *(p for p in ports if p != preferred)]
    return first(p for p in rungs if is_port_free(p, host)) or any_port(host)

def folders(argv=None):
    "Directory arguments passed to the app; a Finder/Explorer launch supplies none."
    return [a for a in (sys.argv[1:] if argv is None else argv) if os.path.isdir(a)]

def files(argv=None):
    "File arguments passed to the app: `open -a Leela --args f`, or a path on the command line."
    return [os.path.abspath(a) for a in (sys.argv[1:] if argv is None else argv) if os.path.isfile(a)]

def leela_args(port, dirs=(), extra=()):
    "The `leela` command line a desktop launch is. `--gateway-port 0`: several copies may run."
    return ['--app', '--port', str(port), '--gateway-port', '0', *extra, *dirs]

def _loop_running():
    try: asyncio.get_running_loop(); return True
    except RuntimeError: return False

def serve(args, background=False):
    "Run `leela.cli.main(args)`, on this thread or a daemon one. Imported at call time."
    import leela.cli
    def go(): leela.cli.main(args)
    if background or _loop_running():
        t = threading.Thread(target=go, daemon=True, name='leela-server')
        t.start()
        return t
    go()
    return None

def main():
    "The server half alone: inline, or on a daemon thread when a loop owns this one."
    return serve(leela_args(free_port(), folders()))

def run():
    "The application: server on a thread, CDP Chrome beside it, native window on this one."
    from leela.desktop import last_folder, remember, run_shell, shell_api, shell_ready, warm_cdp
    from leela.hub import assign_slugs, grant, set_confirmer, workspace_urls
    given = files()
    # One window. The rest stay in `recent`, which the Dock menu and welcome screen offer. A file adds no folder: it opens where one is open, else in the loose window with an offer.
    want = folders() or last_folder()
    cdp_port = int(os.environ.get('LEELA_CDP_PORT', 9223))
    ok, why = shell_ready()
    # A second launch is a window, not a second Leela: one server means one origin, so what the
    # first copy saved is what this one reads. It is also the only way two windows share kernels.
    live = running_leela() if ok else None
    # Nothing to open leaves the saved open set alone: `remember([])` would erase it.
    if live is not None and not want: return attach(live, [], files=given)
    dirs = remember(want)
    if live is not None: return attach(live, dirs, files=given)
    port = free_port()
    if not ok:
        print(f'leela: {why}; opening the workspace in Chrome instead')
        return serve(leela_args(port, dirs, ('--shell', 'chrome', '--cdp-port', str(cdp_port))))

    # The server runs in this process, so the question it asks before adding a folder is a dialog here, and a folder picked here is trusted.
    set_confirmer(lambda q: confirm(q, port))
    shell_api().on_picked = grant
    serve(leela_args(port, dirs, ('--shell', 'none', '--cdp-port', str(cdp_port))), background=True)
    warm_cdp(cdp_port)          # a no-op unless `$LEELA_CDP_EAGER` asks for Chrome up front
    # One window per workspace: a single window on the bare loopback host would strand the rest.
    # Slugged here as well as in the server because both read one remembered assignment per folder.
    slugs = assign_slugs([Path(d).expanduser().resolve() for d in dirs]) if dirs else [HOME_KEY]
    # The main port sends each window on to its workspace's own port, which the server picks when it builds it.
    urls = workspace_urls(dirs, port) if dirs else [f'http://127.0.0.1:{port}/']
    run_shell(urls, titles=titles_for(dirs), keys=slugs, icon=_icon(), **_hooks(port, given))

def attach(port, dirs, host=HOST, files=()):
    "Windows on the Leela already serving `port`. Opens through its own route so the slug and URL are the ones it assigned; a refused folder is reported and the rest still open."
    from leela.desktop import run_shell
    if not dirs:
        return run_shell([f'http://{host}:{port}/'], titles=[window_title()], keys=[HOME_KEY], icon=_icon(),
                         **_hooks(port, files))
    rows = []
    for d in dirs:
        got = hub_open(port, d, host)
        if got.get('ok'): rows.append(got)
        else: print(f"  could not open {d}: {got.get('error')}")
    if not rows: return print('leela: the running copy opened none of these folders')
    urls, titles = [r['url'] for r in rows], [window_title(r['name']) for r in rows]
    run_shell(urls, titles=titles, keys=[r['id'] for r in rows], icon=_icon(), **_hooks(port, files))

def _hooks(port, files=()):
    "What `run_shell` needs to take a folder or a file from Finder or the Dock, and to open the files named on the command line once the windows are up. A folder the page asks for is not trusted."
    from leela.desktop import shell_api
    shell_api().on_page_folder = lambda p: open_folder(port, p, trusted=False)
    kw = dict(on_open_folder=lambda p: open_folder(port, p), on_open_file=lambda p: open_file(port, p))
    if files: kw['on_ready'] = lambda: [open_file(port, f) for f in files]
    return kw

def titles_for(dirs):
    "One window title per workspace, named after its folder."
    return [window_title(title_folder(d)) for d in dirs] or [window_title()]

def hub_open(port, path, host=HOST, timeout=600, file='', folder=False):
    "Ask the server on `port` to serve `path` as a workspace, and with `file` to open it there; a file adds no folder unless `folder`. Returns its row, or the reason not; `down` marks a server that did not answer. The server may ask the person first, so the wait is long."
    import json, socket, urllib.error, urllib.parse, urllib.request
    from leela.hub import OPEN_PATH
    url = f'http://{host}:{port}{OPEN_PATH}?path=' + urllib.parse.quote(str(path), safe='')
    if file: url += '&file=' + urllib.parse.quote(str(file), safe='')
    if folder: url += '&folder=1'
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=b'', method='POST'), timeout=timeout) as r: return json.loads(r.read())
    except urllib.error.HTTPError as e: return {'ok': False, 'error': _why(e)}
    # a question nobody answered in time is not a server still starting: retrying would ask again
    except (TimeoutError, socket.timeout) as e: return {'ok': False, 'error': f'no answer in {timeout} s: {e}'}
    except Exception as e: return {'ok': False, 'down': True, 'error': f'{type(e).__name__}: {e}'}

def open_folder(port, path, host=HOST, trusted=True):
    "Give a folder a workspace and a window of its own, through the running server\'s own route. Trusted, from Finder or the Dock, it is let in with no question when the server runs in this process."
    from leela.desktop import open_window
    from leela.hub import grant
    if trusted: grant(path)
    d = hub_open(port, path, host)
    if not d.get('ok'): return print(f"  could not open {path}: {d.get('error')}")
    return open_window(d['url'], window_title(d['name']), key=d['id'])

def open_file(port, path, host=HOST, wait=60, every=.5):
    "Open one file Finder or the command line handed over, in the workspace it belongs to. A server still starting is waited for, up to `wait` seconds."
    from leela.core.projects import loose_root, workspace_for
    from leela.desktop import open_window
    d = workspace_for(path) or loose_root()
    end = time.monotonic() + wait
    while (got := hub_open(port, d, host, file=path)).get('down') and time.monotonic() < end: time.sleep(every)
    # Shown in the loose window, the file is offered there. Refused there too (a key file, one too large), the server asks before it adds the folder.
    if not got.get('ok') and (o := got.get('offer')) and not got.get('declined'):
        got = hub_open(port, o, host, file=path, folder=True)
        if got.get('declined'): return None
    if not got.get('ok'): return _tell(f"Leela could not open {path}: {got.get('error')}")
    return open_window(got['url'], window_title('loose' if str(loose_root()) in (str(d), got.get('root')) else got['name']), key=got['id'])

def _tell(msg):
    "Say `msg` in a native dialog when a window can show one, and on the terminal either way."
    print(f'  {msg}')
    try:
        import webview
        webview.windows[0].create_confirmation_dialog('Leela', msg)
    except Exception: pass

def confirm(msg, port, wait=10, every=.1):
    "Ask `msg` in a native dialog on the window in front, and say whether the answer was yes. With no window, the home window opens first; `NoWindow` when none comes."
    import webview
    from leela.desktop import open_window
    from leela.hub import NoWindow
    shown = webview.active_window() or first(webview.windows)
    if shown is None:
        open_window(f'http://{HOST}:{port}/', 'leela', key=HOME_KEY)
        end = time.monotonic() + wait
        while (shown := first(webview.windows)) is None and time.monotonic() < end: time.sleep(every)
    if shown is None: raise NoWindow('No Leela window is open to ask in.')
    # a closed window is only hidden; the question must be where the person can see it
    if webview.active_window() is None: shown.show()
    return bool(shown.create_confirmation_dialog('Leela', msg))

def _why(e):
    "What a refusal said, which is the point of it. A 4xx still carries its body."
    import json
    try: return json.loads(e.read()).get('error') or str(e)
    except Exception: return str(e)

def _icon():
    "The window icon, for the backends that take one. macOS reads the bundle's ICNS instead."
    here = Path(getattr(sys, '_MEIPASS', '') or Path(__file__).resolve().parent)
    found = first(str(c) for c in (here/'packaging'/'assets'/'Leela.png', here/'Leela.png',
                                   here/'leela'/'Leela.png') if c.is_file())
    # It is generated, not committed, and it went missing once with nothing to show for it but a
    # window wearing the default icon.
    if not found: print('  no window icon; run tools/build_icons.py')
    return found

if __name__ == '__main__': run()
