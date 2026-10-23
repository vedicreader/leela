"ipywidgets in a notebook cell: drawn live, in step with the kernel, and the text repr wherever a widget cannot be live."

import asyncio, json, sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

pytest.importorskip('playwright.async_api')
pytest.importorskip('ipywidgets')
from playwright.async_api import async_playwright   # noqa: E402

from test_web_slow import _serve, _free_port, _started, fake_model   # noqa: E402
from test_completion_caret_slow import _browser   # noqa: E402
from leela.workspace import Workspace   # noqa: E402

BADGE = 'interactive widget: run the cell'
THIRD = r'''from ipywidgets import DOMWidget
from traitlets import Unicode
class Far(DOMWidget):
    _model_name, _model_module, _model_module_version = Unicode('FarModel').tag(sync=True), Unicode('far-widgets').tag(sync=True), Unicode('1.0.0').tag(sync=True)
    _view_name, _view_module, _view_module_version = Unicode('FarView').tag(sync=True), Unicode('far-widgets').tag(sync=True), Unicode('1.0.0').tag(sync=True)
Far()'''
LIVE = ['from ipywidgets import IntSlider, Dropdown, Text\ns = IntSlider(value=3, max=10); s',
        's.value', 's.value = 7',
        "seen = []\nd = Dropdown(options=['a', 'b', 'c'], value='a'); d.observe(lambda ch: seen.append(ch['new']), names='value'); d",
        'seen', 't = Text(); t', 't.value', THIRD]
OUT = ['from ipywidgets import Output, Button\nfrom IPython.display import display, clear_output\no = Output(); display(o)',
       "with o:\n    print('x'); clear_output(); print('y')",
       "b = Button(description='go'); b.on_click(lambda _: print('clicked')); b", '1 + 1']

def _nb(path, srcs, outputs=None):
    cells = [{'cell_type': 'code', 'id': f'c{i}', 'metadata': {}, 'execution_count': None, 'outputs': (outputs or {}).get(i, []), 'source': s}
             for i, s in enumerate(srcs)]
    meta = {'kernelspec': {'name': 'python3', 'display_name': 'Python 3', 'language': 'python'}}
    path.write_text(json.dumps({'cells': cells, 'metadata': meta, 'nbformat': 4, 'nbformat_minor': 5}))

async def _page(fn, root, browser, transport):
    "Serve `root` on `transport`, open it in `browser`, and hand `fn` the page and the console errors it collects."
    from leela.blocks.runtime.kernels import GatewayService
    (root/'.venv').symlink_to(Path(sys.prefix))
    gw = GatewayService(port=0).start() if transport == 'gateway' else None
    ws = Workspace(roots=[str(root)], approvals='auto', python=sys.executable, transport=transport, **({'gateway': gw} if gw else {}))
    fake_model(ws)
    port = _free_port(); srv = _serve(ws, port); await _started(srv)
    errors = []
    try:
        async with async_playwright() as pw:
            b = await _browser(pw, browser)
            try:
                pg = await b.new_page()
                pg.on('console', lambda m: m.type == 'error' and errors.append(m.text))
                pg.on('pageerror', lambda e: errors.append(str(e)))
                pg.on('response', lambda r: r.status >= 400 and errors.append(f'{r.status} {r.request.method} {r.url}'))
                await pg.goto(f'http://127.0.0.1:{port}/', wait_until='networkidle')
                await pg.wait_for_function('window.lee && lee.keys.length')
                return await fn(pg, errors)
            finally: await b.close()
    finally:
        srv.should_exit = True
        ws.shutdown_now()
        if gw: gw.stop()

async def _open(pg, path, n):
    await pg.evaluate('p => leeOpenFile(p)', str(path))
    await pg.wait_for_function(f'() => lee.cells?.length === {n} && document.querySelectorAll(".lee-cell").length === {n}')

async def _run(pg, i):
    "Run cell `i` and return its last `text/plain`."
    r = await pg.evaluate('i => runCell(i)', i)
    assert r['ok'], r
    return await pg.evaluate('i => (lee.cells[i].outputs || []).map(o => (o.data || {})["text/plain"] || o.text || "").join("")', i)

VIEWS = r"""([id, sel]) => { const hosts = [...document.querySelectorAll(`#out-${id} .lee-widget`)];
  return {n: hosts.length, found: hosts.filter(h => h.shadowRoot?.querySelector(sel)).length,
    inner: hosts.map(h => [...(h.shadowRoot?.querySelectorAll(sel) || [])].map(e => e.textContent).join('')).join(''),
    text: hosts.map(h => h.textContent + '|' + (h.shadowRoot?.textContent || '')).join('')}; }"""

async def _views(pg, cell, sel):
    return await pg.evaluate(VIEWS, [cell, sel])

async def _until(pg, cell, sel, want, secs=30):
    for _ in range(int(secs * 4)):
        v = await _views(pg, cell, sel)
        if want(v): return v
        await pg.wait_for_timeout(250)
    outs = await pg.evaluate('id => lee.cells.find(c => c.id === id)?.outputs', cell)
    raise AssertionError(f'{cell} {sel}: {v}; outputs {outs}')

@pytest.mark.parametrize('transport', ['gateway', 'direct'])
@pytest.mark.parametrize('browser', ['chromium', 'webkit'])
def test_live_widgets_follow_the_kernel_and_keep_the_keyboard(tmp_path, browser, transport):
    """`application/vnd.jupyter.widget-view+json` drew as its `text/plain` repr, so no widget could be used in a cell."""
    p = tmp_path/'live.ipynb'; _nb(p, LIVE)
    async def go(pg, errors):
        out = {}
        await _open(pg, p, len(LIVE))
        await _run(pg, 0)
        await _until(pg, 'c0', '.noUi-handle', lambda v: v['found'] == 1, secs=90)   # the first run starts the kernel
        sel = await pg.evaluate('() => lee.sel')
        await pg.locator('#out-c0 .noUi-handle').focus()
        await pg.keyboard.press('ArrowRight'); await pg.keyboard.press('ArrowRight')
        await pg.wait_for_timeout(500)
        out['sel_after_arrows'] = (sel, await pg.evaluate('() => lee.sel'))
        out['value_after_arrows'] = await _run(pg, 1)
        await _run(pg, 2)
        out['readout'] = (await _until(pg, 'c0', '.widget-readout', lambda v: '7' in v['text']))['text']
        await _run(pg, 3)
        await _until(pg, 'c3', 'select', lambda v: v['found'] == 1)
        await pg.locator('#out-c3 select').select_option('b')
        await pg.wait_for_timeout(500)
        out['seen'] = await _run(pg, 4)
        await _run(pg, 5)
        await _until(pg, 'c5', 'input', lambda v: v['found'] == 1)
        await pg.locator('#out-c5 input').click()
        sel = await pg.evaluate('() => lee.sel')
        await pg.keyboard.type('jk')
        for k in 'IBG': await pg.keyboard.press(f'Shift+{k}')   # RISE's slide chords in command mode
        await pg.wait_for_timeout(500)
        out['sel_after_typing'] = (sel, await pg.evaluate('() => lee.sel'))
        out['typed'] = await _run(pg, 6)
        await _run(pg, 7)
        out['third'] = (await _until(pg, 'c7', 'div', lambda v: 'not available' in v['text']))['text']
        await _run(pg, 0)
        out['rerun'] = await _until(pg, 'c0', '.noUi-handle', lambda v: v['found'] == 1)
        await pg.reload(wait_until='networkidle')
        await pg.wait_for_function('window.lee && lee.keys.length && lee.cells?.length')
        out['reload'] = await _until(pg, 'c0', '.noUi-handle', lambda v: v['found'] == 1)
        await pg.evaluate("() => post('/kernel/restart')")
        out['restart'] = await _until(pg, 'c0', '.noUi-handle', lambda v: v['found'] == 0 and BADGE in v['text'])
        return out
    out = asyncio.run(_page(go, tmp_path, browser, transport))
    assert out['sel_after_arrows'][0] == out['sel_after_arrows'][1], out
    assert out['value_after_arrows'] == '5', out
    assert '7' in out['readout'], out
    assert out['seen'] == "['b']", out
    assert out['sel_after_typing'][0] == out['sel_after_typing'][1] and out['typed'] == "'jkIBG'", out
    assert 'far-widgets' in out['third'], out
    assert out['rerun']['n'] == 1 and out['reload']['n'] == 1 and out['restart']['n'] == 1, out

@pytest.mark.parametrize('transport', ['gateway', 'direct'])
def test_an_output_widget_holds_what_it_captures_and_callbacks_print_under_their_cell(tmp_path, transport):
    """Captured output had nowhere to go but the cell that ran last, and a button's prints landed in whichever cell ran most recently."""
    p = tmp_path/'out.ipynb'; _nb(p, OUT)
    async def go(pg, errors):
        out = {}
        await _open(pg, p, len(OUT))
        await _run(pg, 0)
        await _run(pg, 1)
        out['captured'] = await _until(pg, 'c0', '.widget-output', lambda v: 'y' in v['inner'], secs=90)
        out['cell1'] = await pg.evaluate('() => lee.cells[1].outputs')
        await _run(pg, 2)
        await _until(pg, 'c2', 'button', lambda v: v['found'] == 1)
        await _run(pg, 3)
        await pg.locator('#out-c2 button').click()
        await pg.wait_for_function('() => document.querySelector("#out-c2 .lee-widget-log")?.textContent.includes("clicked")', timeout=15000)
        out['elsewhere'] = await pg.evaluate('() => [0, 1, 3].map(i => document.getElementById("out-" + lee.cells[i].id).textContent)')
        await pg.evaluate('() => saveTab(true)')
        return out
    out = asyncio.run(_page(go, tmp_path, 'chromium', transport))
    assert out['captured']['n'] == 1 and out['captured']['inner'].strip() == 'y', out
    assert not [o for o in out['cell1'] if o.get('output_type') == 'stream'], out
    assert not any('clicked' in t for t in out['elsewhere']), out
    saved = json.loads(p.read_text())
    streams = [o for c in saved['cells'] for o in c['outputs'] if o.get('output_type') == 'stream']
    assert not streams and 'widgets' not in saved['metadata'], (streams, saved['metadata'])

@pytest.mark.parametrize('browser', ['chromium', 'webkit'])
def test_a_saved_widget_without_a_kernel_shows_its_repr_and_a_badge(tmp_path, browser):
    """A saved notebook's widget outputs drew as bare text with nothing saying they were live once."""
    view = {'output_type': 'display_data', 'metadata': {}, 'data': {
        'text/plain': 'IntSlider(value=3, max=10)',
        'application/vnd.jupyter.widget-view+json': {'model_id': 'f00d', 'version_major': 2, 'version_minor': 0}}}
    p = tmp_path/'saved.ipynb'; _nb(p, ['s'], {0: [view]})
    async def go(pg, errors):
        await _open(pg, p, 1)
        v = await _until(pg, 'c0', 'div', lambda v: BADGE in v['text'], secs=15)
        await pg.wait_for_timeout(500)
        return v, errors, await pg.evaluate('() => !!window.LeeWidgets')
    v, errors, loaded = asyncio.run(_page(go, tmp_path, browser, 'direct'))
    assert v['n'] == 1 and 'IntSlider(value=3, max=10)' in v['text'], v
    # `/agent/resume` and `/git/notebook` answer 400 here with or without widgets: no conversation, and no repository.
    mine = [e for e in errors if not e.startswith('Failed to load resource') and not any(r in e for r in ('/agent/resume', '/git/notebook'))]
    assert not mine and not loaded, (errors, loaded)
