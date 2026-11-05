"Rupaka demos in a browser: in a .md preview, after a reload, and drawn in WebKit, the engine of the desktop window."

import pytest

pytestmark = pytest.mark.slow

import asyncio, json
from pathlib import Path

pytest.importorskip('playwright.async_api')
from playwright.async_api import async_playwright   # noqa: E402

from test_web_slow import _serve, _free_port, _started, fake_model, CHROMIUM   # noqa: E402
from leela.blocks.memory.memory import Memory   # noqa: E402
from leela.workspace import Workspace   # noqa: E402

SCENE = dict(type='scene', bind='step', label='Two planes', height=240, steps=['The disc.', 'The ball.'],
             blocks=[dict(type='body', id='disc', kind='cylinder', size=[3.2, .05]), dict(type='body', id='ball', kind='sphere', size=[.6], step=2)])
GATE = dict(type='gate', id='meet', prompt='Where do the planes meet?', options=['In a line', 'At a point'], answer={'is': 'In a line'})
UNGATED = dict(rupaka=1, id='planes', state=dict(step=1), blocks=[SCENE])
GATED = dict(rupaka=1, id='planes-gated', state=dict(step=1), blocks=[GATE, dict(SCENE, after='meet')])
def fence(spec): return f'```rupaka\n{json.dumps(spec)}\n```\n'

#: The scene's pixels in host `h`: whether its WebGL context is lost, and how many pixels are not near white. The renderer keeps its drawing buffer.
PIXELS = """h => { const cv = h.shadowRoot.querySelector('[data-rk-gl] canvas'), g = cv?.getContext('webgl2');
  if (!g || g.isContextLost()) return {lost: true, ink: 0};
  const w = g.drawingBufferWidth, ht = g.drawingBufferHeight, b = new Uint8Array(w * ht * 4); let ink = 0;
  g.readPixels(0, 0, w, ht, g.RGBA, g.UNSIGNED_BYTE, b);
  for (let i = 0; i < b.length; i += 4) if (b[i + 3] && b[i] + b[i + 1] + b[i + 2] < 720) ink++;
  return {lost: false, ink, gl: h.shadowRoot.querySelector('[data-rk-gl]').dataset.rkGl}; }"""

async def _launch(pw, browser):
    try:
        if browser == 'webkit': return await pw.webkit.launch(headless=True)
        return await pw.chromium.launch(headless=True, args=['--mute-audio'], **({'executable_path': CHROMIUM} if CHROMIUM else {}))
    except Exception as e: pytest.skip(f'no {browser} for playwright: {e}')

async def _page(fn, root, browser='chromium'):
    "Serve a workspace on `root` with a vault in it, open it in `browser`, and hand the page to `fn`."
    ws = Workspace(roots=[str(root)], approvals='auto')
    fake_model(ws)
    ws.memory = Memory(path=root/'vault.db', offline=True)
    port = _free_port(); srv = _serve(ws, port); await _started(srv)
    try:
        async with async_playwright() as pw:
            b = await _launch(pw, browser)
            try:
                pg = await b.new_page(viewport={'width': 1440, 'height': 1400})
                pg.set_default_timeout(15000)
                await pg.goto(f'http://127.0.0.1:{port}/', wait_until='networkidle')
                await pg.wait_for_function('window.lee && lee.keys.length')
                return await fn(pg)
            finally: await b.close()
    finally:
        srv.should_exit = True
        ws.shutdown_now()

async def _open(pg, path):
    await pg.evaluate('p => leeOpenFile(p)', str(path))

def test_md_preview_draws_rupaka_fences(tmp_path):
    "A .md file shows its rupaka fences as demos, gated or not, and again after its tab is closed and opened."
    md = tmp_path/'scenes.md'
    md.write_text(f'# Scenes\n\nUngated:\n\n{fence(UNGATED)}\nGated:\n\n{fence(GATED)}')
    hosts, raw = '#mdpreview .lee-rupaka', '#mdpreview pre > code.language-rupaka'
    async def go(pg):
        async def demos():
            await pg.wait_for_function(f'document.querySelectorAll({hosts!r}).length === 2')
            assert await pg.locator(raw).count() == 0
            await pg.wait_for_function(f"document.querySelector({hosts!r}).shadowRoot.querySelector('[data-rk-gl]')?.dataset.rkGl === 'ready'")
            assert await pg.locator(hosts).nth(1).locator('button.go').count() == 1   # the gated one waits for its gate
        await _open(pg, md)
        await demos()
        await pg.evaluate('leeCloseTab()')
        await pg.wait_for_function(f'!document.querySelector({hosts!r})')
        await _open(pg, md)
        await demos()
    asyncio.run(_page(go, tmp_path))
