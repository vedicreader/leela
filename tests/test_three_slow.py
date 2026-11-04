"A rupaka `scene` in a notebook loads three.js from beside lee-rupaka.js and draws its canvas."
import asyncio, json, shutil, tempfile
from pathlib import Path
import pytest

pytestmark = pytest.mark.slow

pytest.importorskip('playwright.async_api')
from playwright.async_api import async_playwright   # noqa: E402

from test_web_slow import _free_port, _serve, _started, fake_model   # noqa: E402
from leela.workspace import Workspace   # noqa: E402

SHOTS = Path(__file__).parents[1]/'target'/'rupaka'
HOST = '.lee-cell[data-i="0"] .lee-md-cell .lee-rupaka'
FACTS = r"""(s) => { const r = document.querySelector(s)?.shadowRoot, st = r?.querySelector('[data-rk-gl]');
  return st && {gl: st.dataset.rkGl, canvas: !!st.querySelector('canvas.gl'), text: r.textContent, three: !!window.RupakaTHREE,
    src: [...document.scripts].map(x => x.src).find(x => /\/three\.js/.test(x))}; }"""

async def _scene(root, nb):
    ws = Workspace(roots=[str(root)], approvals='auto')
    fake_model(ws)
    port = _free_port(); srv = _serve(ws, port); await _started(srv)
    try:
        async with async_playwright() as pw:
            b = await pw.chromium.launch(headless=True, args=['--mute-audio'])
            try:
                pg = await b.new_page(viewport={'width': 1280, 'height': 900})
                await pg.goto(f'http://127.0.0.1:{port}/', wait_until='networkidle')
                await pg.wait_for_function('window.lee && lee.keys.length')
                await pg.evaluate(f'leeOpenFile({str(nb)!r})')
                await pg.wait_for_function(f'(s) => ["ready", "error"].includes(document.querySelector(s)?.shadowRoot?.querySelector("[data-rk-gl]")?.dataset.rkGl)', arg=HOST, timeout=30000)
                got = await pg.evaluate(FACTS, HOST)
                SHOTS.mkdir(parents=True, exist_ok=True)
                await pg.locator(HOST).screenshot(path=str(SHOTS/'scene.png'))
                return got
            finally: await b.close()
    finally:
        srv.should_exit = True
        ws.shutdown_now()

def test_a_scene_demo_loads_three_js_and_draws_a_canvas():
    import rupaka
    spec = json.loads((Path(rupaka.__file__).parent/'blocks/scene/example.json').read_text())
    root = Path(tempfile.mkdtemp()).resolve()
    try:
        nb = root/'scene.ipynb'
        cells = [{'cell_type': 'markdown', 'id': 'c0', 'metadata': {}, 'source': ['```rupaka\n' + json.dumps(spec) + '\n```\n']}]
        nb.write_text(json.dumps({'cells': cells, 'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
        got = asyncio.run(_scene(root, nb))
    finally: shutil.rmtree(root, ignore_errors=True)
    assert 'did not load' not in got['text'] and 'could not load' not in got['text'], got['text'][:300]
    assert got['three'] and '/leestatic/three.js?v=' in got['src'], got
    assert got['gl'] == 'ready' and got['canvas'], got
