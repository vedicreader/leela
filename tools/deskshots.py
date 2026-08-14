"""Capture the desktop app: the native window, and a live page inside a Leela tab.

Two captures, because the feature has two halves that no single screenshot shows.

`desktop-window.png` is the real thing -- `leela.desktop.run_shell` opening a real pywebview
window over a real server, photographed off the X display with ffmpeg. It is the only picture
that can show that Leela is an application rather than a browser tab, so it is taken the
awkward way rather than faked with a page screenshot and a drawn frame.

`desktop-inline-browser.png` is a Leela tab holding a page that a separate headless Chrome is
rendering, streamed in over `/browser/ws`. Playwright takes this one at 2x against the same
server the app runs, which is sharper than an X grab and is the same bargain `tools/webshots.py`
makes: a real server, the real client, and a capture that is empty if the feature is broken.

    python tools/deskshots.py              # both, under Xvfb if there is no DISPLAY
    python tools/deskshots.py --window     # just the native window
    python tools/deskshots.py --inline     # just the inline browser
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT = ROOT/'docs'/'screenshots'
PORT = 5178
# The page the inline browser is pointed at. Fossick's own CDP documentation: the API this
# feature is built on, read inside the thing it is built into.
DEMO_URL = os.environ.get('LEELA_SHOT_URL', 'https://vedicreader.github.io/fossick/cdp.html')
CDP_PORT = 9411
# A profile of its own, not fossick's. Chrome allows one process per user-data-dir, so a
# capture run must not fight with the browser the developer is actually using -- and a shot
# should not be able to include somebody's logged-in tabs.
CDP_PROFILE = ROOT/'build'/'shot-chrome'


def serve(ws, port=PORT):
    "The real app on a background thread, as `tools/webshots.py` does it."
    import uvicorn
    from leela.app import ide_app
    srv = uvicorn.Server(uvicorn.Config(ide_app(ws), host='127.0.0.1', port=port,
                                        log_level='error'))
    threading.Thread(target=srv.run, daemon=True).start()
    return srv


def workspace(cdp_port=CDP_PORT):
    "A workspace over Leela's own source, with kernels stubbed so nothing is launched."
    from tools.shots import fake_kernels
    from leela.workspace import Workspace
    fake_kernels()
    ws = Workspace(roots=[], approvals='auto', cdp_port=cdp_port)
    ws.browser.profile = str(CDP_PROFILE)
    ws.add_root(str(ROOT/'leela'))
    return ws


# -- the native window --------------------------------------------------------
WINDOW_SCRIPT = '''
import sys, urllib.parse, urllib.request
sys.path.insert(0, {root!r})
from tools.deskshots import serve, workspace
from leela.desktop import run_shell, start_cdp, wait_for_http

ws = workspace(cdp_port={cdp})
url = {url!r}
if not url: ws.open({open_file!r})
serve(ws, {port})
base = 'http://127.0.0.1:{port}/'
wait_for_http(base, timeout=90)
if url:
    # Through the route, exactly as clicking a research result does. Opening it in-process
    # instead would make the CDP connection on this thread's throwaway loop, and a websocket
    # belongs to the loop that created it -- the server would then be holding a dead one.
    start_cdp({cdp}, headless=True, wait=True, timeout=90, profile={profile!r})
    urllib.request.urlopen(base + 'browser/open?url=' + urllib.parse.quote(url, safe=''),
                           timeout=120).close()
run_shell([base], titles=['leela — leela'], gui={gui!r}, size=({w}, {h}))
'''


def window_shot(out=None, size=(1440, 900), seconds=14, url=None):
    """Open the shell for real and photograph the window it draws.

    A subprocess because `webview.start` never returns, and under `xvfb-run` when there is no
    display, so this works the same on a laptop and in a container.
    """
    out = Path(out or OUT/('desktop-window-browser.png' if url else 'desktop-window.png'))
    if not shutil.which('ffmpeg'): raise SystemExit('capturing the window needs ffmpeg')
    w, h = size
    script = ROOT/'build'/'deskshot-window.py'
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(WINDOW_SCRIPT.format(root=str(ROOT), port=PORT + 1, w=w, h=h, url=url,
                                           cdp=CDP_PORT, profile=str(CDP_PROFILE),
                                           gui=None if os.environ.get('DISPLAY') else 'gtk',
                                           open_file=str(ROOT/'leela'/'desktop.py')))
    argv = [sys.executable, str(script)]
    display = os.environ.get('DISPLAY')
    if not display:
        display = ':97'
        argv = ['xvfb-run', '-n', '97', f'--server-args=-screen 0 {w + 160}x{h + 160}x24'] + argv
    screen = (w + 160, h + 160)
    app = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                           env={**os.environ, 'DISPLAY': display})
    try:
        # The window has to exist, load the workspace, and finish its first paint. The client
        # mounts the editor only after `/tab/state`, so this is not instant even locally.
        time.sleep(seconds)
        out.parent.mkdir(parents=True, exist_ok=True)
        # Ask X where the window ended up and grab exactly that, rather than photographing
        # the whole screen and guessing afterwards which pixels were wallpaper.
        box = _window_box(display) or (0, 0, *screen)
        gw, gh = box[2] - box[0], box[3] - box[1]
        grab = subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'x11grab',
                               '-video_size', f'{gw}x{gh}', '-i', f'{display}+{box[0]},{box[1]}',
                               '-frames:v', '1', str(out)], capture_output=True, text=True)
        if grab.returncode: raise SystemExit(f'ffmpeg failed: {grab.stderr.strip()}')
    finally:
        app.terminate()
        try: app.wait(timeout=15)
        except subprocess.TimeoutExpired: app.kill()
    print(out)
    return out


def _window_box(display, name='leela'):
    "Where the app window is on `display`, so the wallpaper around it can be cropped off."
    try:
        wid = subprocess.run(['xdotool', 'search', '--name', name],
                             capture_output=True, text=True, timeout=20,
                             env={**os.environ, 'DISPLAY': display}).stdout.split()
        if not wid: return None
        info = subprocess.run(['xwininfo', '-id', wid[-1]], capture_output=True, text=True,
                              timeout=20, env={**os.environ, 'DISPLAY': display}).stdout
        at = dict(l.strip().split(':', 1) for l in info.splitlines() if ':' in l)
        x, y = int(at['Absolute upper-left X']), int(at['Absolute upper-left Y'])
        w, h = int(at['Width']), int(at['Height'])
        # Upwards from the client area to include the title bar the window manager drew:
        # the frame is part of "this is an application", which is what the shot is for.
        return (max(0, x - 1), max(0, y - 30), x + w + 1, y + h + 1)
    except Exception: return None


# -- the inline browser -------------------------------------------------------
async def inline_shot(url=DEMO_URL, out=None):
    "Open `url` as a Leela tab and photograph the workspace with the page live inside it."
    out = Path(out or OUT/'desktop-inline-browser.png')
    OUT.mkdir(parents=True, exist_ok=True)
    from leela.desktop import start_cdp, wait_for_http

    ws = workspace()
    serve(ws)
    if not wait_for_http(f'http://127.0.0.1:{PORT}/', timeout=60):
        raise SystemExit('the workspace never came up')
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
        # The canvas stays blank until the first screencast frame is decoded and drawn, so the
        # wait is for pixels rather than for a timeout to expire.
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


def main(argv=None):
    p = argparse.ArgumentParser(prog='deskshots', description=__doc__.splitlines()[0])
    p.add_argument('--window', action='store_true', help='only the native window')
    p.add_argument('--inline', action='store_true', help='only the inline browser')
    p.add_argument('--both-at-once', action='store_true',
                   help='only the native window with a live page inside it')
    p.add_argument('--url', default=DEMO_URL, help='the page to show inline')
    a = p.parse_args(argv)
    picked = a.window or a.inline or a.both_at_once
    if a.window or not picked: window_shot()
    if a.both_at_once or not picked: window_shot(url=a.url, seconds=18)
    if a.inline or not picked: asyncio.run(inline_shot(a.url))


if __name__ == '__main__': main()
