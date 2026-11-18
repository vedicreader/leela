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

async def _page(fn, root, browser='chromium', workspace=None):
    "Serve a workspace on `root` with a vault in it, open it in `browser`, and hand the page to `fn`."
    ws = workspace or Workspace(roots=[str(root)], approvals='auto')
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

def test_lesson_gate_stays_done_after_a_reload(tmp_path):
    "A gate locked in a lesson comes back done after a reload, with the same pick, and the scene it hid shows."
    from leela.blocks.nb.lesson import lesson_notebook
    nb = lesson_notebook('Planes')
    nb[1].source = 'Predict first.\n\n' + fence(GATED)
    path = tmp_path/'planes.ipynb'; nb.save(path)
    demo = '.lee-cell[data-i="1"] .lee-md-cell .lee-rupaka'
    async def go(pg):
        await _open(pg, path)
        h = pg.locator(demo)
        await h.locator('button.go').wait_for()
        await h.locator('.opts button', has_text='At a point').dispatch_event('click')   # WebKit misses a pointer click in a shadow root in headless runs
        async with pg.expect_response('**/lesson/predict') as got: await h.locator('button.go').click()
        assert (await (await got.value).json())['logged']
        await h.locator('p.verdict').wait_for()
        await pg.reload(wait_until='networkidle')
        await pg.wait_for_function('window.lee && lee.keys.length')
        if not await pg.locator(demo).count(): await _open(pg, path)
        h = pg.locator(demo)
        await h.locator('p.verdict').wait_for()
        assert (await h.locator('p.verdict').inner_text()).startswith('You said At a point.')
        assert await h.locator('button.go').is_hidden()
        assert await h.evaluate('h => [...h.shadowRoot.children].find(n => n.rupaka).rupaka.st.gate.meet') == 'done'
        await pg.wait_for_function(f"document.querySelector({demo!r}).shadowRoot.querySelector('[data-rk-gl]')?.clientWidth > 0")
        other = tmp_path/'other.py'; other.write_text('x = 1\n')
        await _open(pg, other); await pg.wait_for_function(f'!document.querySelector({demo!r})')
        await pg.wait_for_timeout(500)
        await _open(pg, path)
        h = pg.locator(demo)
        await pg.wait_for_function(f"document.querySelector({demo!r})?.shadowRoot.querySelector('[data-rk-gl]')?.dataset.rkStill === '1'")
        px = await h.evaluate(PIXELS)
        assert not px['lost'] and px['ink'] > 500, px   # the scene behind a restored gate draws again after a tab switch
        assert (await h.locator('p.verdict').inner_text()).startswith('You said At a point.')
    asyncio.run(_page(go, tmp_path))

@pytest.mark.parametrize('lesson', [False, True])
def test_notebook_rupaka_inputs_survive_reload(tmp_path, lesson):
    from rupaka import __file__ as rupaka_file
    from leela.blocks.nb.nb import Cell, Notebook
    spec = json.loads((Path(rupaka_file).parent/'demos'/'throw-angle.json').read_text())
    path = tmp_path/'throw.ipynb'
    i = 1 if lesson else 0
    if lesson:
        from leela.blocks.nb.lesson import lesson_notebook
        nb = lesson_notebook('Throw'); nb[i].source = fence(spec)
    else: nb = Notebook([Cell(cell_type='markdown', source=fence(spec))])
    nb.save(path)
    demo = f'.lee-cell[data-i="{i}"] .lee-md-cell .lee-rupaka'
    async def go(pg):
        await _open(pg, path)
        h = pg.locator(demo)
        await h.locator('input[type=range]').first.wait_for()
        await h.locator('.opts button', has_text='60').dispatch_event('click')
        async with pg.expect_response('**/lesson/predict'): await h.locator('button.go').click()
        await h.locator('p.verdict').wait_for()
        async with pg.expect_response(lambda r: r.url.endswith('/nb/edit') and r.request.post_data_json.get('op') == 'rupaka_inputs', timeout=5000) as got:
            await h.locator('input[type=range]').first.evaluate("e => { e.value = '60'; e.dispatchEvent(new Event('input', {bubbles: true})); e.dispatchEvent(new Event('change', {bubbles: true})); }")
        response = await got.value
        assert response.status == 200, await response.text()
        assert await h.evaluate('h => Rupaka.state([...h.shadowRoot.children].find(n => n.rupaka)).a') == 60
        saved = await pg.request.post(pg.url.rstrip('/') + '/nb/save', data={'path': str(path)})
        assert saved.ok, await saved.text()
        assert Notebook.load(path)[i].extra['rupaka']['throw-angle']['inputs']['a'] == 60
        await pg.reload(wait_until='networkidle')
        await pg.wait_for_function('window.lee && lee.keys.length')
        if not await pg.locator(demo).count(): await _open(pg, path)
        h = pg.locator(demo)
        await h.locator('input[type=range]').first.wait_for()
        if lesson:
            await h.locator('p.verdict').wait_for()
            assert await h.evaluate('h => [...h.shadowRoot.children].find(n => n.rupaka).rupaka.st.gate.g') == 'done'
            assert await h.evaluate('h => Rupaka.state([...h.shadowRoot.children].find(n => n.rupaka)).a') == 60
        else:
            assert await h.evaluate('h => [...h.shadowRoot.children].find(n => n.rupaka).rupaka.st.gate.g') == 'open'
            assert await h.evaluate('h => Rupaka.state([...h.shadowRoot.children].find(n => n.rupaka)).a') == spec['state']['a'] == 30
            assert await h.locator('.rk-slider').first.evaluate("e => e.classList.contains('rk-locked')")
            await h.locator('.rk-locknote', has_text='Locked until you lock in your prediction.').wait_for()
            assert not await h.locator('.rk-plot path.gh').get_attribute('d')
            await h.locator('input[type=range]').first.evaluate("e => { e.value = '60'; e.dispatchEvent(new Event('input', {bubbles: true})); }")
            assert await h.evaluate('h => Rupaka.state([...h.shadowRoot.children].find(n => n.rupaka)).a') == 30
            async with pg.expect_response(lambda r: r.url.endswith('/nb/edit') and r.request.post_data_json.get('op') == 'rupaka_inputs') as got:
                await h.locator('input[type=range]').nth(1).evaluate("e => { e.value = '0.75'; e.dispatchEvent(new Event('input', {bubbles: true})); }")
            assert (await (await got.value).json())['record']['inputs']['a'] == 60
            await h.locator('.opts button', has_text='60').dispatch_event('click')
            await pg.route('**/lesson/predict', lambda route: route.fulfill(status=503, json={'error': 'Try again.'}))
            async with pg.expect_response('**/lesson/predict'): await h.locator('button.go').click()
            await h.locator('p.note', has_text='Try again.').wait_for()
            assert await h.evaluate('h => [...h.shadowRoot.children].find(n => n.rupaka).rupaka.st.gate.g') == 'open'
            assert await h.evaluate('h => Rupaka.state([...h.shadowRoot.children].find(n => n.rupaka)).a') == 30
            assert await h.locator('.rk-slider').first.evaluate("e => e.classList.contains('rk-locked')")
            await pg.unroute('**/lesson/predict')
            async with pg.expect_response('**/lesson/predict'): await h.locator('button.go').click()
            await h.locator('p.verdict').wait_for()
            assert await h.evaluate('h => Rupaka.state([...h.shadowRoot.children].find(n => n.rupaka)).a') == 60
            assert not await h.locator('.rk-slider').first.evaluate("e => e.classList.contains('rk-locked')")
    asyncio.run(_page(go, tmp_path))


@pytest.mark.parametrize('browser', ['webkit', 'chromium'])
def test_scene_draws_and_draws_again_after_a_tab_switch(tmp_path, browser):
    "A scene draws pixels in WebKit and Chromium, and still draws after its notebook leaves the page and comes back, which used to leave a dead WebGL context."
    nbp, other = tmp_path/'scene.ipynb', tmp_path/'other.py'
    nbp.write_text(json.dumps({'cells': [{'cell_type': 'markdown', 'id': 'c0', 'metadata': {}, 'source': fence(dict(UNGATED, state=dict(step=2)))}],
                               'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    other.write_text('x = 1\n')
    demo = '.lee-cell[data-i="0"] .lee-md-cell .lee-rupaka'
    async def drawn(pg):
        await pg.wait_for_function(f"document.querySelector({demo!r})?.shadowRoot.querySelector('[data-rk-gl]')?.dataset.rkStill === '1'")
        await pg.wait_for_timeout(300)
        return await pg.locator(demo).evaluate(PIXELS)
    async def go(pg):
        await _open(pg, nbp)
        px = await drawn(pg)
        assert not px['lost'] and px['ink'] > 500, px
        await _open(pg, other); await pg.wait_for_function(f'!document.querySelector({demo!r})')
        await pg.wait_for_timeout(500)
        await _open(pg, nbp)
        px = await drawn(pg)
        assert not px['lost'] and px['ink'] > 500, px
        await pg.evaluate('leeCloseTab()'); await pg.wait_for_function(f'!document.querySelector({demo!r})')
        await _open(pg, nbp)
        px = await drawn(pg)
        assert not px['lost'] and px['ink'] > 500, px
    asyncio.run(_page(go, tmp_path, browser))


def test_notebook_rupaka_prose_edit_keeps_host_and_saves_current_source(tmp_path):
    from leela.blocks.nb.nb import Cell, Notebook, src_hash
    spec = dict(rupaka=1, id='angle', state=dict(a=30), blocks=[dict(type='slider', bind='a', min=10, max=80)])
    path = tmp_path/'prose.ipynb'
    nb = Notebook([Cell(cell_type='markdown', source='Before.\n\n' + fence(spec))]); nb.save(path)
    demo = '.lee-cell[data-i="0"] .lee-md-cell .lee-rupaka'
    async def go(pg):
        await _open(pg, path)
        h = pg.locator(demo)
        await h.locator('input[type=range]').wait_for()
        await h.evaluate("h => { window.keptDemo = h; Rupaka.set([...h.shadowRoot.children].find(n => n.rupaka), {a: 60}); }")
        source = 'After.\n\n' + fence(spec)
        await pg.evaluate("source => { const c = lee.cells[0]; editMarkdownCell(0); LeeCM.setDoc(lee.editors.get(c.id), source); showRenderedMarkdown(c); }", source)
        await pg.wait_for_function("document.querySelector('.lee-md-cell').textContent.includes('After.')")
        await pg.wait_for_function(f"document.querySelector({demo!r})?.shadowRoot.querySelector('input[type=range]')")
        assert await h.evaluate('h => h === window.keptDemo')
        assert await h.evaluate('h => Rupaka.state([...h.shadowRoot.children].find(n => n.rupaka)).a') == 60
        async with pg.expect_response(lambda r: r.url.endswith('/nb/edit') and r.request.post_data_json.get('op') == 'rupaka_inputs') as got:
            await h.locator('input[type=range]').evaluate("e => { e.value = '65'; e.dispatchEvent(new Event('input', {bubbles: true})); }")
        response = await got.value
        assert response.status == 200, await response.text()
        assert response.request.post_data_json['src'] == src_hash(source)
        assert (await response.json())['record']['inputs']['a'] == 65
    asyncio.run(_page(go, tmp_path))


def test_notebook_retained_trials_reload_and_show(tmp_path):
    from rupaka.spec import gallery
    from leela.blocks.nb.lesson import lesson_notebook
    from leela.blocks.nb.nb import Notebook
    spec = gallery()['throw-angle']
    nb = lesson_notebook('Throw'); nb[1].source = fence(spec)
    path = tmp_path/'trials.ipynb'; nb.save(path)
    ws = Workspace(roots=[tmp_path], approvals='auto')
    demo = '.lee-cell[data-i="1"] .lee-md-cell .lee-rupaka'
    async def go(pg):
        await _open(pg, path)
        h = pg.locator(demo)
        await h.locator('button.go').wait_for()
        keep = h.get_by_role('button', name='Keep this run', exact=True)
        await keep.wait_for(timeout=5000)
        assert await keep.is_disabled()
        await h.locator('.opts button', has_text='60').dispatch_event('click')
        async with pg.expect_response('**/lesson/predict'): await h.locator('button.go').click()
        await h.locator('p.verdict').wait_for()
        for angle in (30, 60):
            if angle == 60:
                await h.locator('input[type=range]').first.evaluate("e => {e.value = '60'; e.dispatchEvent(new Event('input', {bubbles: true}));}")
            async with pg.expect_response(lambda r: r.url.endswith('/nb/edit') and r.request.post_data_json.get('op') == 'rupaka_trial') as got:
                await keep.click()
            response = await got.value
            assert response.status == 200, await response.text()
        assert await pg.evaluate('saveTab(true)')
        trials = Notebook.load(path)[1].extra['rupaka']['throw-angle']['trials']
        assert [t['inputs']['a'] for t in trials] == [30, 60]
        await pg.reload(wait_until='networkidle')
        await pg.wait_for_function('window.lee && lee.keys.length')
        if not await pg.locator(demo).count(): await _open(pg, path)
        rows = h.locator('.lee-rupaka-trial')
        await rows.nth(1).wait_for()
        text = await rows.all_text_contents()
        assert 'Run 1' in text[0] and '30' in text[0] and '35.3' in text[0], text
        assert 'Run 2' in text[1] and '60' in text[1] and '35.3' in text[1], text
        await rows.nth(0).get_by_role('button', name='Show run 1').click()
        async with pg.expect_response(lambda r: r.url.endswith('/nb/edit') and r.request.post_data_json.get('op') == 'rupaka_inputs') as got:
            await rows.nth(1).get_by_role('button', name='Show run 2').click()
        assert (await got.value).status == 200
        assert await h.locator('input[type=range]').first.input_value() == '60'
        assert await pg.evaluate('saveTab(true)')
        assert Notebook.load(path)[1].extra['rupaka']['throw-angle']['trials'] == trials
        from leela.blocks.agent.ai import _session_tools
        tools = {f.__name__: f for f in _session_tools(ws.inline_ai.host)}
        rev = Notebook.load(path)[1].extra['rupaka']['throw-angle']['rev']
        result = json.loads(await asyncio.to_thread(tools['set_demo_inputs'], str(path), nb[1].id, 'throw-angle', {'a': 75}, rev))
        assert result['ok'], result
        await pg.evaluate('p => mountTab(p)', str(path))
        await pg.wait_for_function(f"(() => {{ const h = document.querySelector({demo!r}); return h?.shadowRoot?.querySelector('input[type=range]')?.value === '75'; }})()", timeout=5000)
        async with pg.expect_response(lambda r: r.url.endswith('/nb/edit') and r.request.post_data_json.get('op') == 'rupaka_trial') as got:
            await h.get_by_role('button', name='Keep this run', exact=True).click()
        assert (await got.value).status == 200
        await pg.evaluate('lee.nbQueue')
        assert await pg.evaluate('saveTab(true)')
        assert [t['inputs']['a'] for t in Notebook.load(path)[1].extra['rupaka']['throw-angle']['trials']] == [30, 60, 75]
    asyncio.run(_page(go, tmp_path, workspace=ws))
