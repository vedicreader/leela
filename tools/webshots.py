"""Capture the browser frontend mid-stream.

A real server, the real client JS, the real SSE endpoint, and a scripted model that emits one word
at a time so the capture catches a turn in flight. If the events do not arrive, the page stays
empty and the capture shows it.

    python tools/webshots.py         # writes docs/screenshots/web-stream-*.png
"""

from __future__ import annotations
import asyncio, os, sys, threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.isolate import isolate; isolate()   # never the person's real stores

from leela.blocks.runtime.kernels import KernelPool                       # noqa: E402
from leela.app import ide_app                          # noqa: E402
from leela.workspace import Workspace                      # noqa: E402
from tests.fakemodel import Step, install                  # noqa: E402
from tools.shots import NB, STEPS, fake_kernels           # noqa: E402

OUT = Path(__file__).resolve().parent.parent/'docs'/'screenshots'
ROOT = Path(__file__).resolve().parent.parent
PORT = 5177
CHROME = None  # playwright's bundled chromium; set to an absolute path to override


def serve(ws):
    "Run the real app on a background thread, so Playwright can drive it like any other site."
    import uvicorn
    app = ide_app(ws)
    cfg = uvicorn.Config(app, host='127.0.0.1', port=PORT, log_level='error')
    srv = uvicorn.Server(cfg)
    threading.Thread(target=srv.run, daemon=True).start()
    return srv


async def shoot():
    OUT.mkdir(parents=True, exist_ok=True)
    fake_kernels()
    ws = Workspace(roots=[], approvals='auto')
    ws.add_root(str(ROOT/'leela'))
    (nbp := ROOT/'leela'/'_shot.ipynb').write_text(NB)
    ws.open(str(nbp))
    install(ws, STEPS, token_delay=0.03)
    serve(ws)
    await asyncio.sleep(1.5)

    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        launch = {'executable_path': CHROME} if CHROME else {}
        b = await pw.chromium.launch(**launch)
        pg = await b.new_page(viewport={'width': 1600, 'height': 950}, device_scale_factor=2)
        await pg.goto(f'http://127.0.0.1:{PORT}/', wait_until='networkidle')
        await pg.wait_for_timeout(800)
        # Project-runtime prompts are useful in the IDE, but they steal the shot.
        await pg.evaluate("document.querySelectorAll('.lee-modal').forEach(m => m.remove())")

        # Cursor theme evidence: agent + files chrome before the prompt is filled.
        await pg.evaluate("applyTheme('cursor')")
        await pg.evaluate("leeAct('focus_agent')")
        await pg.wait_for_timeout(250)
        await pg.screenshot(path=str(OUT/'web-theme-cursor.png'))

        await pg.evaluate("leeAct('focus_agent')")
        await pg.fill('#agentprompt', 'where is approval handled, and how does the reason get back to the model?')
        await pg.evaluate("leeAct('agent_send')")

        await pg.wait_for_timeout(1700)
        await pg.evaluate("document.querySelectorAll('.lee-modal').forEach(m => m.remove())")
        await pg.screenshot(path=str(OUT/'web-stream-1-tools.png'))

        await pg.wait_for_timeout(1600)
        await pg.screenshot(path=str(OUT/'web-stream-2-answer.png'))

        for _ in range(60):
            await pg.wait_for_timeout(200)
            if not ws.ai.busy: break
        await pg.wait_for_timeout(600)
        await pg.evaluate("document.querySelectorAll('.lee-modal').forEach(m => m.remove())")
        await pg.screenshot(path=str(OUT/'web-stream-3-done.png'))

        # Memory sources view, vault-backed research memory.
        await pg.evaluate("document.querySelectorAll('.lee-modal').forEach(m => m.remove())")
        await pg.click('[data-right="memory"]')
        await pg.click('[data-memory-view="sources"]')
        await pg.wait_for_timeout(800)
        await pg.screenshot(path=str(OUT/'web-memory-sources.png'))

        log = (await pg.inner_text('#agentlog')).strip()
        await b.close()

    nbp.unlink(missing_ok=True)
    for n in ('web-theme-cursor', 'web-stream-1-tools', 'web-stream-2-answer', 'web-stream-3-done', 'web-memory-sources'):
        print(OUT/f'{n}.png')
    print('\n--- #agentlog ---')
    print(log[:1200])
    return log


if __name__ == '__main__':
    asyncio.run(shoot())
