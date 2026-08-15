"""Record the IDE showcase: a walkthrough video plus key stills for the README.

A real server, the real client, a scripted model, and kernels that answer with live
variables. Playwright drives and records. ffmpeg turns the webm into an mp4.

    python tools/showcase.py
    python tools/showcase.py --stills   # screenshots only
    python tools/showcase.py --video    # video only
"""
from __future__ import annotations
import asyncio, shutil, subprocess, sys, threading, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from leela.blocks.runtime.kernels import KernelPool
from leela.app import ide_app
from leela.workspace import Workspace
from tests.conftest import FakeKernel
from tests.fakemodel import Step, install

OUT = ROOT/'docs'/'screenshots'
MEDIA = ROOT/'docs'/'media'
PORT = 5188
NB = '''{
 "cells": [
  {"cell_type": "markdown", "id": "m1", "metadata": {},
   "source": ["# Approvals\\n\\nAsk the agent where write approval is handled, then watch the turn."]},
  {"cell_type": "code", "id": "c1", "metadata": {}, "outputs": [], "execution_count": null,
   "source": ["import pandas as pd\\n\\ndf = pd.DataFrame({\\n    'x': range(5),\\n    'y': [i*i for i in range(5)]\\n})\\ndf_norm = (df - df.mean()) / df.std()\\ntotal = int(df.y.sum())\\ndf_norm.head()"]}
 ],
 "metadata": {"kernelspec": {"name": "python3", "language": "python", "display_name": "Python 3"}},
 "nbformat": 4, "nbformat_minor": 5
}'''
STEPS = [
    Step(pause=0.2, text='Looking through the workspace for where write approvals land.'),
    Step(tool=('search_code', {'query': 'approval'})),
    Step(pause=0.4, text='Approvals queue through the web HITL path. A refusal returns to the model with the reason, so the turn can steer.'),
    Step(pause=0.25, text='Edit the card, read the dry-run diff, approve, reject with steering, retry, or roll it back.'),
]

def fake_kernels():
    "Real FakeKernel answers so Variables and the agent look alive."
    async def _get(self, key, **kw):
        k = self.kernels.get(key)
        if k is None:
            k = FakeKernel()
            self.kernels[key] = k
        return k
    KernelPool.get = _get
    KernelPool.peek = lambda self, key: self.kernels.get(key)
    KernelPool.close_all = lambda self: asyncio.sleep(0)

def serve(ws, port=PORT):
    import uvicorn
    srv = uvicorn.Server(uvicorn.Config(ide_app(ws), host='127.0.0.1', port=port, log_level='error'))
    threading.Thread(target=srv.run, daemon=True).start()
    return srv

async def wait_http(url, timeout=60):
    import urllib.request
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            urllib.request.urlopen(url, timeout=2).close(); return True
        except Exception: await asyncio.sleep(0.25)
    return False

async def clear_modals(pg):
    await pg.evaluate("document.querySelectorAll('.lee-modal').forEach(m => m.remove())")

async def shot(pg, name, *, wipe=False):
    "Still of the page. `wipe` drops leftover setup dialogs; leave it off for palette/search."
    if wipe: await clear_modals(pg)
    path = OUT/f'{name}.png'
    await pg.screenshot(path=str(path))
    print(path)
    return path

async def pause(pg, ms=700): await pg.wait_for_timeout(ms)

async def wait_idle(ws, pg, timeout=45):
    "Block until the scripted turn finishes streaming."
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not getattr(ws.ai, 'busy', False): return
        await pause(pg, 250)

async def tour(pg, ws, stills=True):
    "Drive the IDE through the moments the README wants to show."
    await pg.goto(f'http://127.0.0.1:{PORT}/', wait_until='networkidle')
    await pause(pg, 1200)
    await clear_modals(pg)
    await pg.evaluate("applyTheme('cursor')")
    await pause(pg, 700)
    if stills: await shot(pg, 'web-theme-cursor', wipe=True)

    # Files + editor open on a real source file.
    await pg.evaluate("leeAct('focus_files')")
    await pause(pg, 800)
    await pg.evaluate(f"leeOpenFile({str(ROOT/'leela'/'desktop.py')!r})")
    await pause(pg, 1600)
    if stills: await shot(pg, 'web-editor', wipe=True)
    await pause(pg, 900)

    # Notebook tab back in view for the agent turn.
    tabs = await pg.eval_on_selector_all('.lee-tab', 'els => els.map((e,i)=>({i, name: e.querySelector(\'.lee-tab-name\')?.textContent||\'\'}))')
    nb = next((t for t in tabs if (t.get('name') or '').endswith('.ipynb')), None)
    if nb is not None:
        await pg.evaluate(f"htmxPost('/tab/select?i=' + {nb['i']})")
        await pause(pg, 1000)

    # Agent turn mid-stream.
    await pg.evaluate("leeAct('focus_agent')")
    await pause(pg, 500)
    await pg.fill('#agentprompt', 'where is write approval handled, and how does a refusal get back to the model?')
    await pause(pg, 700)
    await pg.evaluate("leeAct('agent_send')")
    await pause(pg, 2200)
    if stills: await shot(pg, 'web-stream-1-tools')
    await pause(pg, 2000)
    if stills: await shot(pg, 'web-stream-2-answer')
    await wait_idle(ws, pg)
    await pause(pg, 1200)
    await clear_modals(pg)
    if stills: await shot(pg, 'web-stream-3-done')
    await pause(pg, 1000)

    # Live variables from the stubbed inspector.
    await pg.evaluate("leeAct('focus_vars')")
    await pause(pg, 1200)
    if stills: await shot(pg, 'web-variables')
    await pause(pg, 900)

    # Memory sources — do not wipe modals that are not up.
    await pg.click('[data-right="memory"]')
    try: await pg.click('[data-memory-view="sources"]', timeout=3000)
    except Exception: pass
    await pause(pg, 1100)
    if stills: await shot(pg, 'web-memory-sources')
    await pause(pg, 800)

    # Source control panel.
    await pg.evaluate("leeAct('panel_git')")
    await pause(pg, 1500)
    if stills: await shot(pg, 'web-git')
    await pause(pg, 900)

    # Command palette — wait for the dialog; it *is* the shot.
    await pg.evaluate("leeAct('focus_files')")
    await pause(pg, 500)
    await clear_modals(pg)
    await pg.evaluate("leeAct('palette')")
    await pg.wait_for_selector('#cp', timeout=5000)
    await pg.fill('#cp', 'search')
    await pause(pg, 1400)
    if stills: await shot(pg, 'web-palette')
    await pg.keyboard.press('Escape')
    await pause(pg, 700)

    # Code search overlay.
    await clear_modals(pg)
    await pg.evaluate("leeAct('code_search')")
    await pg.wait_for_selector('#cs', timeout=5000)
    await pg.fill('#cs', 'Workspace')
    await pause(pg, 2200)
    if stills: await shot(pg, 'web-search')
    await pg.keyboard.press('Escape')
    await pause(pg, 700)

    # Bottom dock: exec.
    await clear_modals(pg)
    await pg.evaluate("leeAct('focus_exec')")
    await pause(pg, 1200)
    if stills: await shot(pg, 'web-exec')
    await pause(pg, 1000)

    # Composer ending: notebook + finished agent turn.
    await pg.evaluate("leeAct('focus_agent')")
    await pause(pg, 1600)
    if nb is not None:
        await pg.evaluate(f"htmxPost('/tab/select?i=' + {nb['i']})")
        await pause(pg, 1200)
    if stills: await shot(pg, 'showcase-end')
    await pause(pg, 2800)

async def run(*, stills=True, video=True):
    OUT.mkdir(parents=True, exist_ok=True)
    MEDIA.mkdir(parents=True, exist_ok=True)
    fake_kernels()
    ws = Workspace(roots=[], approvals='auto')
    ws.add_root(str(ROOT/'leela'))
    nbp = ROOT/'leela'/'_shot.ipynb'
    nbp.write_text(NB)
    ws.open(str(nbp))
    install(ws, STEPS, token_delay=0.028)
    serve(ws)
    if not await wait_http(f'http://127.0.0.1:{PORT}/'): raise SystemExit('IDE never came up')

    from playwright.async_api import async_playwright
    rec = MEDIA/'showcase-raw'
    if video and rec.exists(): shutil.rmtree(rec)
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        ctx_kw = dict(viewport={'width': 1600, 'height': 950}, device_scale_factor=2)
        if video: ctx_kw['record_video_dir'] = str(rec)
        if video: ctx_kw['record_video_size'] = {'width': 1600, 'height': 950}
        ctx = await b.new_context(**ctx_kw)
        pg = await ctx.new_page()
        try:
            await tour(pg, ws, stills=stills)
        finally:
            await ctx.close(); await b.close()

    nbp.unlink(missing_ok=True)
    if video:
        webms = sorted(rec.glob('*.webm')) if rec.exists() else []
        if not webms: raise SystemExit('playwright wrote no video')
        mp4 = MEDIA/'leela-showcase.mp4'
        # H.264 + faststart so GitHub and browsers can stream it.
        cmd = ['ffmpeg', '-y', '-i', str(webms[0]), '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
               '-movflags', '+faststart', '-crf', '23', '-preset', 'medium', str(mp4)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode: raise SystemExit(r.stderr[-800:] or 'ffmpeg failed')
        shutil.rmtree(rec, ignore_errors=True)
        print(mp4, f'({mp4.stat().st_size/1e6:.1f} MB)')
        # A short poster frame for the README when autoplay is unwanted.
        poster = OUT/'showcase-poster.png'
        subprocess.run(['ffmpeg', '-y', '-ss', '3', '-i', str(mp4), '-frames:v', '1', str(poster)],
                       capture_output=True, check=False)
        if poster.exists(): print(poster)

def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(prog='showcase', description=__doc__.splitlines()[0])
    p.add_argument('--stills', action='store_true')
    p.add_argument('--video', action='store_true')
    a = p.parse_args(argv)
    both = not (a.stills or a.video)
    asyncio.run(run(stills=both or a.stills, video=both or a.video))

if __name__ == '__main__': main()
