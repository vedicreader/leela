"""Capture the browser frontend mid-stream.

Same bargain as `tools/shots.py`: a real server, the real client JS, the real SSE
endpoint, and a scripted model that emits its words one at a time so the capture catches a
turn actually in flight. Playwright drives it, which also means this doubles as an
end-to-end test of the stream — if the events do not arrive, the page stays empty and the
capture shows it.

    python tools/webshots.py         # writes docs/screenshots/web-stream-*.png
"""

from __future__ import annotations
import asyncio, os, sys, threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from leela.blocks.runtime.kernels import KernelPool                       # noqa: E402
from leela.app import ide_app                          # noqa: E402
from leela.workspace import Workspace                      # noqa: E402
from tests.fakemodel import Step, install                  # noqa: E402
from tools.shots import NB, STEPS, fake_kernels           # noqa: E402

OUT = Path(__file__).resolve().parent.parent/'docs'/'screenshots'
ROOT = Path(__file__).resolve().parent.parent
PORT = 5177
CHROME = '/opt/pw-browsers/chromium-1194/chrome-linux/chrome'


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
        b = await pw.chromium.launch(executable_path=CHROME)
        pg = await b.new_page(viewport={'width': 1600, 'height': 950}, device_scale_factor=2)
        await pg.goto(f'http://127.0.0.1:{PORT}/', wait_until='networkidle')
        await pg.wait_for_timeout(800)

        await pg.fill('#agentprompt', 'where is approval handled, and how does the reason get back to the model?')
        await pg.evaluate("leeAct('agent_send')")

        await pg.wait_for_timeout(1700)
        await pg.screenshot(path=str(OUT/'web-stream-1-tools.png'))

        await pg.wait_for_timeout(1600)
        await pg.screenshot(path=str(OUT/'web-stream-2-answer.png'))

        # Settled: wait for the `done` event to have landed its status line.
        for _ in range(60):
            await pg.wait_for_timeout(200)
            if not ws.ai.busy: break
        await pg.wait_for_timeout(600)
        await pg.screenshot(path=str(OUT/'web-stream-3-done.png'))

        log = (await pg.inner_text('#agentlog')).strip()
        await b.close()

    nbp.unlink(missing_ok=True)
    for n in ('web-stream-1-tools', 'web-stream-2-answer', 'web-stream-3-done'):
        print(OUT/f'{n}.png')
    print('\n--- #agentlog ---')
    print(log[:1200])
    return log


if __name__ == '__main__':
    asyncio.run(shoot())
