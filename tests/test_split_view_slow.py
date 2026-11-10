"A Markdown file and a notebook in the second pane read as a document and as a notebook."

import pytest

pytestmark = pytest.mark.slow

import asyncio, json, struct, sys, zlib
from pathlib import Path

pytest.importorskip('playwright.async_api')
from playwright.async_api import async_playwright   # noqa: E402

from test_web_slow import _serve, _free_port, _started, _launch, fake_model   # noqa: E402
from leela.workspace import Workspace   # noqa: E402

STREAM = [{'output_type': 'stream', 'name': 'stdout', 'text': 'hello 42\n'}]

def _nb(path, n=2, outputs=STREAM, text=None):
    cells = [{'cell_type': 'markdown', 'id': f'{path.stem}-m', 'metadata': {}, 'source': f'# Title {path.stem}\n\nSome *words*'}]
    cells += [{'cell_type': 'code', 'id': f'{path.stem}-{i}', 'metadata': {}, 'execution_count': i + 1, 'outputs': outputs, 'source': f'x{i} = {i}'} for i in range(n)]
    meta = {'kernelspec': {'name': 'python3', 'display_name': 'Python 3', 'language': 'python'}}
    path.write_text(json.dumps({'cells': cells, 'metadata': meta, 'nbformat': 4, 'nbformat_minor': 5}) if text is None else text)

def _png(path):
    rows = b''.join(b'\x00' + b'\xe0\x40\x40\xff' * 8 for _ in range(8))
    def ch(t, d): c = struct.pack('>I', len(d)) + t + d; return c + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + ch(b'IHDR', struct.pack('>IIBBBBB', 8, 8, 8, 6, 0, 0, 0)) + ch(b'IDAT', zlib.compress(rows)) + ch(b'IEND', b''))

def _world(root):
    root = root.resolve()
    (root/'img').mkdir(); _png(root/'img'/'a.png')
    (root/'README.md').write_text('# Reference\n\nA [link](other.md) and ![red](img/a.png)\n')
    (root/'other.md').write_text('# Other\n')
    _nb(root/'a.ipynb'); _nb(root/'b.ipynb')
    ro = root/'.venv'/'lib'/'python3.12'/'site-packages'/'pkg'; ro.mkdir(parents=True); (root/'.venv'/'bin').mkdir()
    (root/'.venv'/'bin'/'python').symlink_to(sys.executable)
    _nb(ro/'ro.ipynb')
    return root, ro/'ro.ipynb'

async def _page(fn, root):
    ws = Workspace(roots=[str(root)], approvals='auto')
    fake_model(ws)
    port = _free_port(); srv = _serve(ws, port); await _started(srv)
    try:
        async with async_playwright() as pw:
            b = await _launch(pw)
            try:
                pg = await b.new_page()
                await pg.goto(f'http://127.0.0.1:{port}/', wait_until='networkidle')
                await pg.wait_for_function('window.lee && lee.keys.length')
                await pg.wait_for_timeout(1200)
                await pg.evaluate("document.querySelector('#runtimelater')?.click()")
                return await fn(pg)
            finally: await b.close()
    finally:
        srv.should_exit = True
        ws.shutdown_now()

async def _open(pg, *paths):
    for p in paths:
        await pg.evaluate('p => leeOpenFile(p)', str(p))
        await pg.wait_for_timeout(300)

def _run(fn, tmp_path):
    root, ro = _world(tmp_path)
    return asyncio.run(_page(lambda pg: fn(pg, root, ro), root))

def test_markdown_in_the_side_pane_renders_toggles_and_remembers(tmp_path):
    async def go(pg, root, ro):
        await _open(pg, root/'README.md', root/'a.ipynb')
        await pg.evaluate('p => mountSecondary(p)', str(root/'README.md'))
        await pg.wait_for_selector('#editor2 #mdpreview2 h1')
        out = {'view': await pg.evaluate("document.querySelector('#editor2 .lee-md-stage').dataset.view"),
               'text': await pg.inner_text('#mdpreview2'),
               'img': await pg.evaluate("(async () => { const i = document.querySelector('#mdpreview2 img'); await i.decode().catch(() => 0); return i.naturalWidth })()")}
        await pg.click('#editor2 [data-md-view="edit"]')
        out['edit'] = await pg.evaluate("[document.querySelector('#editor2 .lee-md-stage').dataset.view, getComputedStyle(document.querySelector('#mdpreview2')).display]")
        await pg.evaluate('p => mountSecondary(p)', str(root/'README.md'))     # what a tab switch does
        await pg.wait_for_selector('#editor2 #mdpreview2', state='attached')
        await pg.wait_for_timeout(500)
        out['kept'] = await pg.evaluate("document.querySelector('#editor2 .lee-md-stage').dataset.view")
        out['main_untouched'] = await pg.evaluate("lee.path.endsWith('a.ipynb')")
        return out
    out = _run(go, tmp_path)
    assert out['view'] == 'rendered' and 'Reference' in out['text'] and out['img'] == 8, out
    assert out['edit'] == ['edit', 'none'] and out['kept'] == 'edit' and out['main_untouched'], out

def test_two_notebooks_are_two_notebooks(tmp_path):
    async def go(pg, root, ro):
        await _open(pg, root/'b.ipynb', root/'a.ipynb')
        await pg.evaluate('p => mountSecondary(p)', str(root/'b.ipynb'))
        await pg.wait_for_selector('#editor2 .lee-cell.code .cm-content')
        await pg.wait_for_selector('#editor2 .lee-cell.markdown .lee-md-cell h1')
        out = await pg.evaluate("""() => ({cells: document.querySelectorAll('#editor2 .lee-cell[data-nbv]').length,
          md: document.querySelector('#editor2 .lee-cell.markdown .lee-md-cell h1')?.textContent,
          out: [...document.querySelectorAll('#editor2 .lee-out')].map(x => x.textContent),
          ids: [...document.querySelectorAll('#editor2 [id]')].map(x => x.id).filter(i => /^(g|state|cm|out|mdr)-/.test(i)),
          readonly: !!document.querySelector('#editor2 [data-readonly]'), side: lee.sideNb.path.endsWith('b.ipynb')})""")
        await pg.evaluate("selectCell(1)")
        await pg.click('#editor2 .lee-cell.code >> nth=0')
        out['main_sel'] = await pg.evaluate("document.querySelectorAll('#editor2 .lee-cell.sel').length + ':' + document.querySelectorAll('#editor .lee-cell.sel').length")
        # insert into the main notebook, below the selected cell
        before = await pg.evaluate('lee.cells.length')
        await pg.evaluate("document.querySelector('#editor2 .lee-cell.code [data-act=insert]').click()")
        await pg.wait_for_function(f'lee.cells.length === {before + 1}')
        out['inserted'] = await pg.evaluate("lee.cells[2].source")
        # copy cell to the clipboard of cells, then the main selection goes to the side notebook
        await pg.evaluate("selectCell(0); cellToOther()")
        await pg.wait_for_function("lee.sideNb.cells.length === 4")
        await pg.wait_for_timeout(1500)
        out['b_on_disk'] = len(json.loads((root/'b.ipynb').read_text())['cells'])
        out['b_shown'] = await pg.evaluate("document.querySelectorAll('#editor2 .lee-cell[data-nbv]').length")
        return out
    out = _run(go, tmp_path)
    assert out['cells'] == 3 and out['md'] == 'Title b' and out['out'] == ['hello 42\n'] * 2 and not out['ids'] and not out['readonly'], out
    assert out['main_sel'].endswith(':1') and out['main_sel'].startswith('0:'), 'the side cells took the main selection'
    assert out['inserted'] == 'x0 = 0', out
    assert out['b_on_disk'] == out['b_shown'] == 4, out

def test_a_read_only_notebook_shows_cells_and_copies_but_takes_no_write(tmp_path):
    async def go(pg, root, ro):
        await _open(pg, ro, root/'a.ipynb')
        await pg.evaluate('p => mountSecondary(p)', str(ro))
        await pg.wait_for_selector('#editor2 .lee-cell.code .cm-content')
        out = await pg.evaluate("({badge: document.querySelector('#editor2 [data-readonly]')?.textContent, cells: document.querySelectorAll('#editor2 .lee-cell[data-nbv]').length, acts: [...document.querySelector('#editor2 .lee-cell.code').querySelectorAll('.lee-cbtn')].map(b => b.textContent)})")
        await pg.evaluate("selectCell(1); cellToOther()")
        await pg.wait_for_timeout(300)
        out['refused'] = await pg.inner_text('#status') if await pg.query_selector('#status') else ''
        path = str(ro)
        out['direct'] = await pg.evaluate("""p => fetch('/nb/edit', {method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({op: 'paste_many', i: 0, cells: [{cell_type: 'code', source: 'z'}], path: p, side: true})}).then(r => r.json().then(j => [r.status, j.error]))""", path)
        await pg.evaluate("document.querySelector('#editor2 .lee-cell.code [data-act=cell]').click()")
        out['clip'] = await pg.evaluate("lee.cellClipboard?.cells?.[0]?.source")
        out['text'] = len(json.loads(ro.read_text())['cells'])
        return out
    out = _run(go, tmp_path)
    assert out['badge'] == 'read only' and out['cells'] == 3 and out['acts'] == ['copy', 'copy output', 'copy cell', 'insert'], out
    assert 'read-only' in out['refused'], out
    assert out['direct'][0] >= 400 and 'read-only' in out['direct'][1], out
    assert out['clip'] == 'x0 = 0' and out['text'] == 3, out

def test_a_bad_file_a_big_notebook_and_a_closed_pane_say_so_plainly(tmp_path):
    async def go(pg, root, ro):
        _nb(root/'big.ipynb', n=400, outputs=[])
        (root/'bad.ipynb').write_text('not json')
        await _open(pg, root/'a.ipynb', root/'big.ipynb')
        await pg.evaluate("p => mountSecondary(p)", str(root/'big.ipynb'))
        await pg.wait_for_selector('#editor2 [data-side-more]')
        out = {'first': await pg.evaluate("document.querySelectorAll('#editor2 .lee-cell[data-nbv]').length")}
        await pg.click('#editor2 [data-side-more]')
        out['second'] = await pg.evaluate("document.querySelectorAll('#editor2 .lee-cell[data-nbv]').length")
        # a pane closed while its file was still loading stays closed
        await pg.evaluate("p => { mountSecondary(p); leeCloseSplit(); }", str(root/'b.ipynb'))
        await pg.wait_for_timeout(800)
        out['closed'] = await pg.evaluate("document.querySelector('#editor2').hidden && !lee.sideNb && (lee.sideViews || []).length === 0")
        # a notebook that cannot be read is said in the pane
        await pg.evaluate("p => api('/tab/open?path=' + encodeURIComponent(p), {method: 'POST'}).catch(() => 0)", str(root/'bad.ipynb'))
        await pg.evaluate("p => mountSecondary(p)", str(root/'bad.ipynb'))
        await pg.wait_for_timeout(800)
        out['bad'] = await pg.evaluate("document.querySelector('#editor2 .lee-err, #editor2')?.innerText.slice(0, 120)")
        # a learn page over a notebook leaves no editors behind
        await pg.evaluate("p => mountSecondary(p)", str(root/'big.ipynb')); await pg.wait_for_selector('#editor2 .cm-content')
        await pg.evaluate("mountPage('/learn', 'Learn')")
        out['views'] = await pg.evaluate("[(lee.sideViews || []).length, !!lee.sideObserver]")
        return out
    out = _run(go, tmp_path)
    assert out['first'] == 150 and out['second'] == 300, out
    assert out['closed'] is True and out['views'] == [0, False], out
    assert out['bad'], out

def test_swap_panes_puts_the_side_notebook_in_the_main_pane(tmp_path):
    async def go(pg, root, ro):
        await _open(pg, root/'b.ipynb', root/'a.ipynb')
        await pg.evaluate('p => mountSecondary(p)', str(root/'b.ipynb'))
        await pg.wait_for_selector('#editor2 .lee-cell')
        await pg.click('#editor2 [onclick="leeSwapSplit()"]')
        await pg.wait_for_function("lee.path.endsWith('b.ipynb') && lee.sideNb?.path.endsWith('a.ipynb')")
        return await pg.evaluate("[lee.kind, document.querySelectorAll('#editor .lee-cell').length > 0]")
    assert _run(go, tmp_path) == ['notebook', True]
