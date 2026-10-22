"The next keystroke after accepting a kernel completion lands at the caret, in a notebook cell and in a file."

import pytest

pytestmark = pytest.mark.slow

import asyncio, json, sys
from pathlib import Path

pytest.importorskip('playwright.async_api')
from playwright.async_api import async_playwright   # noqa: E402

from test_web_slow import _serve, _free_port, _started, _launch, fake_model   # noqa: E402
from leela.workspace import Workspace   # noqa: E402

HEAD = 'from fastdownload import download_url\ndest = "bird.jpg"\ndownload_url(urls[0], dest, show_progress=False)\n'
TAIL = 'im = Image.open(dest)'
VIEW = "const v = lee.editors.get(lee.cells?.[0]?.id) || lee.editors.get('file');"
LISTED = '.cm-tooltip-autocomplete .cm-completionLabel'

def _nb(path, source):
    cell = {'cell_type': 'code', 'id': 'c1', 'metadata': {}, 'execution_count': None, 'outputs': [], 'source': source}
    meta = {'kernelspec': {'name': 'python3', 'display_name': 'Python 3', 'language': 'python'}}
    path.write_text(json.dumps({'cells': [cell], 'metadata': meta, 'nbformat': 4, 'nbformat_minor': 5}))

async def _browser(pw, name):
    if name == 'chromium': return await _launch(pw)
    try: return await pw.webkit.launch()
    except Exception as e: pytest.skip(f'no webkit for playwright: {e}')

async def _real_page(fn, root, browser='chromium'):
    (root/'.venv').symlink_to(Path(sys.prefix))
    ws = Workspace(roots=[str(root)], approvals='auto')
    fake_model(ws)
    port = _free_port(); srv = _serve(ws, port); await _started(srv)
    try:
        async with async_playwright() as pw:
            b = await _browser(pw, browser)
            try:
                pg = await b.new_page()
                await pg.goto(f'http://127.0.0.1:{port}/', wait_until='networkidle')
                await pg.wait_for_function('window.lee && lee.keys.length')
                return await fn(pg)
            finally: await b.close()
    finally:
        srv.should_exit = True
        ws.shutdown_now()

async def _accept_then_type(pg, path, line, how, typed, name):
    await pg.evaluate('p => leeOpenFile(p)', str(path))
    await pg.wait_for_selector('.cm-content')
    await pg.evaluate(f"""n => {{ {VIEW} v.focus(); v.dispatch({{selection: {{anchor: v.state.doc.line(n).to}}}}); }}""", line)
    await pg.keyboard.type(typed)
    await pg.wait_for_selector(LISTED, timeout=60000)
    if how == 'enter':
        while name not in await pg.eval_on_selector('.cm-tooltip-autocomplete li[aria-selected=true]', 'e => e.textContent'):
            await pg.keyboard.press('ArrowDown')
        await pg.wait_for_timeout(100)   # CodeMirror ignores Enter for 75ms after the list opens
        await pg.keyboard.press('Enter')
    else: await pg.locator('.cm-tooltip-autocomplete li', has_text=name).first.click()
    await pg.keyboard.type('(')
    await pg.wait_for_timeout(1500)
    return await pg.evaluate(f"""() => {{ {VIEW} const s = v.state, h = s.selection.main.head, ln = s.doc.lineAt(h);
      return {{head: h, line: ln.number, col: h - ln.from, text: ln.text}}; }}""")

@pytest.mark.parametrize('browser', ['chromium', 'webkit'])
@pytest.mark.parametrize('how', ['enter', 'click'])
@pytest.mark.parametrize('kind', ['multi', 'single', 'py'])
def test_next_keystroke_after_accepting_a_completion_lands_at_the_caret(tmp_path, kind, how, browser):
    src, line = ('', 1) if kind == 'single' else (HEAD + '\n' + TAIL, 4)
    typed, name = ('prin', 'print') if kind == 'single' else ('down', 'download_url')
    path = tmp_path / ('t.py' if kind == 'py' else 't.ipynb')
    if kind == 'py': path.write_text(src)
    else: _nb(path, src)
    out = asyncio.run(_real_page(lambda pg: _accept_then_type(pg, path, line, how, typed, name), tmp_path, browser))
    assert out['text'].startswith(name + '('), out
    assert out['line'] == line and out['col'] == len(name + '('), out
