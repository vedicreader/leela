#!/usr/bin/env python
"""Drive a canvas through the real IDE in a browser, and photograph each step.

Serves `ide_app` on a free port, then uses Playwright to do what a person does: find the command,
name the document, watch it open in a tab, trust it, run it, and ask the helper for a change. The
model is whatever `--model` names; `claude-haiku-4-5` goes through the Claude Code backend rishi
already talks to, so the helper in the margin is the real one rather than the stand-in.
"""
from __future__ import annotations
import argparse, asyncio, socket, threading, time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from leela.app import ide_app
from leela.workspace import Workspace

OUT = Path(__file__).resolve().parent.parent/'media'/'canvas-ide'
SHOT = 0

def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); return s.getsockname()[1]

def serve(ws, port):
    import uvicorn
    cfg = uvicorn.Config(ide_app(ws), host='127.0.0.1', port=port, log_level='error')
    srv = uvicorn.Server(cfg)
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(100):
        with socket.socket() as s:
            if s.connect_ex(('127.0.0.1', port)) == 0: return srv
        time.sleep(.1)
    raise RuntimeError('the app never came up')

async def shot(page, name, note=''):
    global SHOT
    SHOT += 1
    await page.wait_for_timeout(500)
    p = OUT/f'{SHOT:02d}-{name}.png'
    await page.screenshot(path=str(p))
    print(f'  {p.name}{"  · " + note if note else ""}')
    return p

async def drive(url, root, model):
    from playwright.async_api import async_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        #: The environment ships one Chromium; this Playwright pins a different build number and
        #: would otherwise try to download its own.
        exe = next((str(x) for x in (Path('/opt/pw-browsers/chromium-1194/chrome-linux/chrome'),
                                     Path('/opt/pw-browsers/chromium/chrome-linux/chrome'))
                    if x.exists()), None)
        b = await pw.chromium.launch(executable_path=exe, args=['--no-sandbox'])
        page = await (await b.new_context(viewport={'width': 1500, 'height': 950})).new_page()
        page.on('console', lambda m: print('   [console]', m.type, m.text[:160])
                if m.type == 'error' else None)
        await page.goto(url, wait_until='networkidle')
        await page.wait_for_timeout(2500)

        await shot(page, 'ide-open', 'the workspace, with the file tree on the left')

        # 1. the command is discoverable without knowing it exists
        await page.keyboard.press('Control+Shift+P')
        await page.wait_for_selector('#cp', timeout=5000)
        await page.fill('#cp', 'canvas')
        await shot(page, 'palette-new-canvas', 'the command palette knows the word')
        await page.keyboard.press('Escape')

        # 2. the Files strip carries it too
        await shot(page, 'files-toolbar', 'the +canvas button beside +file and +nb')

        # 3. make one, the way a person does: pick where it goes, then press the button
        await page.click('#filetree .lee-node', button='left')
        await page.wait_for_timeout(400)
        await shot(page, 'folder-selected', 'the folder the new document lands in')
        await page.click('.lee-bar-files [data-action="new_canvas"]')
        await page.wait_for_selector('.lee-modal input', timeout=5000)
        await page.fill('.lee-modal input', 'pricing-a-run')
        await shot(page, 'name-the-document', 'the suffix is added, so a bare name is enough')
        await page.keyboard.press('Enter')
        await page.wait_for_timeout(3500)
        await shot(page, 'canvas-tab-open', 'the starter document, open in a tab of its own')

        frame = page.frame_locator('iframe.lee-canvasframe')

        # 4. the code waits behind one deliberate click
        await shot(page, 'trust-banner', 'markdown from anywhere runs nothing until asked')
        try:
            await frame.locator('#cv-trust-run').click(timeout=8000)
            await page.wait_for_timeout(6000)
        except Exception as e: print('   trust:', e)
        await shot(page, 'after-run', 'the cell has run in the workspace kernel')

        # 5. an IDE chord still works with the canvas focused
        try:
            await frame.locator('#cv-doc').click(timeout=4000)
            await page.wait_for_timeout(400)
            await page.keyboard.press('Control+Shift+P')
            await page.wait_for_selector('#cp', timeout=4000)
            await shot(page, 'chord-through-frame', 'the palette, opened from inside the canvas')
            await page.keyboard.press('Escape')
        except Exception as e: print('   chord:', e)

        # 6. ask the helper for a change, and watch it edit the document
        try:
            await frame.locator('#cv-askform input').fill(
                'Add a note under the cost cell explaining what the number means.')
            await shot(page, 'ask-the-helper', f'the margin helper, running {model}')
            await frame.locator('#cv-askform input').press('Enter')
            await page.wait_for_timeout(60000)
            await shot(page, 'helper-answered', 'the turn, its steps, and what it wrote back')
        except Exception as e: print('   helper:', e)

        # 7. saved back to the file the tab names
        await page.keyboard.press('Control+s')
        await page.wait_for_timeout(2500)
        await shot(page, 'saved', 'mod+s reaches the canvas, which owns its own save')
        await b.close()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='')
    ap.add_argument('--model', default='claude-haiku-4-5')
    ap.add_argument('--fresh', action='store_true', help='empty the project first, so a rerun repeats')
    a = ap.parse_args()
    root = Path(a.root).resolve() if a.root else Path.cwd()
    if a.fresh:
        import shutil, subprocess
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True)
        (root/'README.md').write_text('# demo project\n')
        subprocess.run(['git', 'init', '-q', str(root)], check=False)
    #: `auto`: the approval card renders in the agent pane, not the canvas margin, so a
    #: guided turn would stall out of sight of the person who asked it.
    ws = Workspace(roots=[str(root)], model=a.model, approvals='auto')
    note = ws.ai.start()
    print(f'model {a.model}: ready={ws.ai.ready}' + ('' if ws.ai.ready else f' ({note})'))
    port = free_port()
    serve(ws, port)
    url = f'http://127.0.0.1:{port}/'
    print(f'serving {root} at {url}')
    asyncio.run(drive(url, root, a.model))

if __name__ == '__main__': main()
