#!/usr/bin/env python3
"The entry point py2app and py2exe freeze. See `docs/desktop.md`."

from __future__ import annotations

import asyncio, os, sys, threading

from fastcore.all import Path, first, is_port_free
from fastcore.net import free_port as any_port

__all__ = ['free_port', 'folders', 'leela_args', 'serve', 'main', 'run', 'open_folder',
           'titles_for']

HOST = '127.0.0.1'

# Only when frozen: a normal install has one environment and installs into it, and an extras
# directory left over from running the app would then shadow it. See `leela.use_extras`.
if getattr(sys, 'frozen', False):
    from leela import use_extras, use_login_path, use_utf8
    from leela.core.envs import apply_stored_env, import_login_env
    use_extras()
    use_utf8()            # no LANG means an ASCII default, and importing rishi.claude then raises
    use_login_path()      # Finder starts an app with almost no PATH, so git and claude go missing
    # And the rest of the environment with it. A window opened from Finder has launchd's, so a key
    # exported from a shell profile is missing and every hosted model refuses the turn. This is the
    # entry the bundle freezes; `leela.cli` is the terminal's and does the same for itself.
    if os.environ.get('LEELA_SHELL_ENV', '1') != '0': import_login_env()
    apply_stored_env()    # last, and winning: what a person typed into Leela beats a wrong shell

def free_port(preferred=5001):
    "`preferred` if nothing holds it, else whatever the OS hands out."
    return preferred if is_port_free(preferred, HOST) else any_port(HOST)

def folders(argv=None):
    "Directory arguments passed to the app; a Finder/Explorer launch supplies none."
    return [a for a in (sys.argv[1:] if argv is None else argv) if os.path.isdir(a)]

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
    from leela.desktop import last_folder, remember, run_shell, shell_ready, warm_cdp
    from leela.hub import assign_slugs
    # One window. The rest stay in `recent`, which the Dock menu and welcome screen offer.
    dirs = remember(folders() or last_folder())
    port = free_port()
    cdp_port = int(os.environ.get('LEELA_CDP_PORT', 9223))
    ok, why = shell_ready()
    if not ok:
        print(f'leela: {why}; opening the workspace in Chrome instead')
        return serve(leela_args(port, dirs, ('--shell', 'chrome', '--cdp-port', str(cdp_port))))

    serve(leela_args(port, dirs, ('--shell', 'none', '--cdp-port', str(cdp_port))), background=True)
    warm_cdp(cdp_port)          # a no-op unless `$LEELA_CDP_EAGER` asks for Chrome up front
    # One window per workspace: a single window on the bare loopback host would strand the rest.
    # Slugged here as well as in the server because both read one remembered assignment per folder.
    slugs = assign_slugs([Path(d).expanduser().resolve() for d in dirs]) if dirs else ['leela']
    urls = ([f'http://{s}.localhost:{port}/' for s in slugs] if dirs
            else [f'http://127.0.0.1:{port}/'])
    run_shell(urls, titles=titles_for(dirs), keys=slugs, icon=_icon(),
              on_open_folder=lambda p: open_folder(port, p))

def titles_for(dirs):
    "One window title per workspace, named after its folder."
    return [f'leela — {Path(d).name}' for d in dirs] or ['leela']

def open_folder(port, path, host=HOST):
    "Give a folder a workspace and a window of its own, through the running server\'s own route."
    import json, urllib.error, urllib.parse, urllib.request
    from leela.desktop import open_window
    from leela.hub import OPEN_PATH
    url = f'http://{host}:{port}{OPEN_PATH}?path=' + urllib.parse.quote(str(path), safe='')
    try:
        with urllib.request.urlopen(url, timeout=60) as r: d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return print(f'  could not open {path}: {_why(e)}')
    except Exception as e:
        return print(f'  could not open {path}: {type(e).__name__}: {e}')
    if not d.get('ok'): return print(f"  could not open {path}: {d.get('error')}")
    return open_window(d['url'], f"leela — {d['name']}", key=d['id'])

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
