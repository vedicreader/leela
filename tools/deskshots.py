"""Capture the desktop app: the native window, and a live page inside a Leela tab.

`desktop-window.png` is photographed off the X display with ffmpeg, the only shot that can show
Leela as an application. `desktop-inline-browser.png` is taken at 2x by Playwright.

    python tools/deskshots.py              # both, under Xvfb if there is no DISPLAY
    python tools/deskshots.py --window     # just the native window
    python tools/deskshots.py --inline     # just the inline browser
"""
from __future__ import annotations
import argparse, asyncio, os, shutil, subprocess, sys, threading, time
from fastcore.all import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT = ROOT/'docs'/'screenshots'
PORT = 5178
DEMO_URL = os.environ.get('LEELA_SHOT_URL', 'https://vedicreader.github.io/fossick/cdp.html')
CDP_PORT = 9411
# Chrome allows one process per user-data-dir, so a capture must not fight the developer's own
# browser or include their logged-in tabs.
CDP_PROFILE = ROOT/'build'/'shot-chrome'

def serve(ws, port=PORT):
    "The real app on a background thread, as `tools/webshots.py` does it."
    import uvicorn
    from leela.app import ide_app
    srv = uvicorn.Server(uvicorn.Config(ide_app(ws), host='127.0.0.1', port=port, log_level='error'))
    threading.Thread(target=srv.run, daemon=True).start()
    return srv

def workspace(cdp_port=CDP_PORT, roots=True):
    "A workspace over Leela's own source, kernels stubbed; `roots=False` is the first-launch state."
    from tools.shots import fake_kernels
    from leela.workspace import Workspace
    fake_kernels()
    ws = Workspace(roots=[], approvals='auto', cdp_port=cdp_port)
    ws.browser.profile = str(CDP_PROFILE)
    if roots: ws.add_root(str(ROOT/'leela'))
    return ws

WINDOW_SCRIPT = '''
import sys, urllib.parse, urllib.request
sys.path.insert(0, {root!r})
from tools.deskshots import serve, workspace
from leela.desktop import run_shell, start_cdp, wait_for_http

ws = workspace(cdp_port={cdp}, roots={roots!r})
url = {url!r}
if not url and {roots!r}: ws.open({open_file!r})
serve(ws, {port})
base = 'http://127.0.0.1:{port}/'
wait_for_http(base, timeout=90)
if url:
    # Through the route. In-process, the CDP websocket would belong to this thread's throwaway
    # loop, and the server would be left holding a dead one.
    start_cdp({cdp}, headless=True, wait=True, timeout=90, profile={profile!r})
    urllib.request.urlopen(base + 'browser/open?url=' + urllib.parse.quote(url, safe=''),
                           timeout=120).close()
run_shell([base], titles=['leela — leela'], gui={gui!r}, size=({w}, {h}))
'''

def window_shot(out=None, size=(1440, 900), seconds=14, url=None, roots=True, name=None):
    "Open the shell for real and photograph the window it draws."
    # A subprocess because `webview.start` never returns. Under `xvfb-run` when there is no
    # display, so a laptop and a container do the same thing.
    out = Path(out or OUT/(name or ('desktop-window-browser.png' if url else 'desktop-window.png')))
    if not shutil.which('ffmpeg'): raise SystemExit('capturing the window needs ffmpeg')
    w, h = size
    script = ROOT/'build'/'deskshot-window.py'
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(WINDOW_SCRIPT.format(root=str(ROOT), port=PORT + 1, w=w, h=h, url=url,
                                           cdp=CDP_PORT, profile=str(CDP_PROFILE), roots=roots,
                                           gui=None if os.environ.get('DISPLAY') else 'gtk',
                                           open_file=str(ROOT/'leela'/'desktop.py')))
    argv = [sys.executable, str(script)]
    if not (display := os.environ.get('DISPLAY')):
        display = ':97'
        argv = ['xvfb-run', '-n', '97', f'--server-args=-screen 0 {w + 160}x{h + 160}x24'] + argv
    app = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                           env={**os.environ, 'DISPLAY': display})
    try:
        # The client mounts the editor only after `/tab/state`, so the first paint is not
        # instant even locally.
        time.sleep(seconds)
        out.parent.mkdir(parents=True, exist_ok=True)
        x0, y0, x1, y1 = _window_box(display) or (0, 0, w + 160, h + 160)
        grab = subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'x11grab',
                               '-video_size', f'{x1 - x0}x{y1 - y0}', '-i', f'{display}+{x0},{y0}',
                               '-frames:v', '1', str(out)], capture_output=True, text=True)
        if grab.returncode: raise SystemExit(f'ffmpeg failed: {grab.stderr.strip()}')
    finally:
        app.terminate()
        try: app.wait(timeout=15)
        except subprocess.TimeoutExpired: app.kill()
    print(out)
    return out

def _x(display, *args, timeout=20):
    "stdout of an X client run against `display`."
    return subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, 'DISPLAY': display}).stdout

def _window_box(display, name='leela'):
    "Where the app window is on `display`, so the wallpaper around it can be cropped off."
    try:
        if not (wid := _x(display, 'xdotool', 'search', '--name', name).split()): return None
        info = _x(display, 'xwininfo', '-id', wid[-1])
        at = dict(l.strip().split(':', 1) for l in info.splitlines() if ':' in l)
        x, y = int(at['Absolute upper-left X']), int(at['Absolute upper-left Y'])
        w, h = int(at['Width']), int(at['Height'])
        # Upwards from the client area to include the title bar, which is part of showing
        # this is an application.
        return (max(0, x - 1), max(0, y - 30), x + w + 1, y + h + 1)
    except Exception: return None

async def inline_shot(url=DEMO_URL, out=None):
    "Open `url` as a Leela tab and photograph the workspace with the page live inside it."
    out = Path(out or OUT/'desktop-inline-browser.png')
    OUT.mkdir(parents=True, exist_ok=True)
    from leela.desktop import start_cdp, wait_for_http

    ws = workspace()
    serve(ws)
    if not wait_for_http(f'http://127.0.0.1:{PORT}/', timeout=60): raise SystemExit('the workspace never came up')
    start_cdp(CDP_PORT, headless=True, wait=True, timeout=60, profile=str(CDP_PROFILE))
    if not await ws.browser.alive(): raise SystemExit(f'no browser: {ws.browser.note}')

    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={'width': 1600, 'height': 950}, device_scale_factor=2)
        await pg.goto(f'http://127.0.0.1:{PORT}/', wait_until='networkidle')
        await pg.evaluate("document.querySelectorAll('.lee-modal').forEach(m => m.remove())")
        await pg.evaluate('leePane("right", false)')      # the page is the subject, not the agent
        await pg.evaluate(f'leeOpenWeb({url!r})')
        await pg.wait_for_selector('.lee-webcanvas', timeout=60_000)
        await _painted(pg)
        await pg.evaluate("document.querySelectorAll('.lee-modal').forEach(m => m.remove())")
        await pg.evaluate("status('')")     # the transient toast is not part of the feature
        await pg.wait_for_timeout(400)
        await pg.screenshot(path=str(out))
        note = await pg.input_value('.lee-weburl')
        await b.close()
    await ws.browser.close()
    print(f'{out}  (address bar: {note})')
    return out

async def _painted(pg, timeout=40):
    "Wait until the canvas has something other than one flat colour on it."
    js = """() => { const c = document.querySelector('.lee-webcanvas');
      if (!c || !c.width) return false;
      const d = c.getContext('2d').getImageData(0, 0, c.width, Math.min(c.height, 200)).data;
      for (let i = 4; i < d.length; i += 4) if (d[i] !== d[0]) return true;
      return false; }"""
    for _ in range(timeout * 4):
        if await pg.evaluate(js): return await pg.wait_for_timeout(1200)
        await pg.wait_for_timeout(250)
    raise SystemExit('the inline browser never painted a frame')

def seed_recent():
    "Give the welcome screen something to offer: an empty one is true of one launch ever."
    from leela.core import projects
    for d in (ROOT, ROOT/'leela', ROOT/'docs'):
        if d.is_dir(): projects.note_folder(str(d))
    projects.remember([])          # nothing open: this is the first-launch screen

def main(argv=None):
    p = argparse.ArgumentParser(prog='deskshots', description=__doc__.splitlines()[0])
    p.add_argument('--window', action='store_true', help='only the native window')
    p.add_argument('--inline', action='store_true', help='only the inline browser')
    p.add_argument('--both-at-once', action='store_true', help='only the native window with a live page inside it')
    p.add_argument('--welcome', action='store_true', help='only the window as it opens with no folder yet')
    p.add_argument('--url', default=DEMO_URL, help='the page to show inline')
    a = p.parse_args(argv)
    picked = a.window or a.inline or a.both_at_once or a.welcome
    if a.window or not picked: window_shot()
    if a.welcome or not picked:
        seed_recent()
        window_shot(roots=False, name='desktop-welcome.png')
    if a.both_at_once or not picked: window_shot(url=a.url, seconds=18)
    if a.inline or not picked: asyncio.run(inline_shot(a.url))

if __name__ == '__main__': main()
