"A notebook markdown cell draws images relative to the notebook's folder."

import base64, json
import pytest

pytestmark = pytest.mark.slow

pytest.importorskip('playwright.async_api')

from test_web_slow import _run   # noqa: E402

DOT = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')
IMGS = r"""() => [...document.querySelectorAll('.lee-cell[data-i="0"] .lee-md-cell img')]
  .map(i => ({src: i.getAttribute('src'), w: i.naturalWidth, done: i.complete}))"""


def test_markdown_cell_images_resolve_against_the_notebook(tmp_path):
    (tmp_path/'images').mkdir(); (tmp_path/'images'/'dot.png').write_bytes(DOT)
    p = tmp_path/'pics.ipynb'
    src = '<img src="images/dot.png">\n\n![d](images/dot.png)\n\n![a](attachment:a.png)\n\n![m](attachment:missing.png)\n'
    p.write_text(json.dumps({'cells': [{'cell_type': 'markdown', 'source': src.splitlines(True), 'metadata': {}, 'id': 'c0',
        'attachments': {'a.png': {'image/png': base64.b64encode(DOT).decode()}}}],
        'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    async def go(pg):
        raw = []
        pg.on('request', lambda r: raw.append(r.url) if '/file/raw' in r.url else None)
        await pg.evaluate(f'leeOpenFile({str(p)!r})')
        await pg.wait_for_function(f'(({IMGS})()).length === 4')
        try: await pg.wait_for_function(f'(({IMGS})()).slice(0, 3).every(i => i.done && i.w > 0)', timeout=5000)
        except Exception: pass
        return await pg.evaluate(IMGS), raw
    got, raw = _run(go, roots=[tmp_path])
    folder = str(tmp_path/'images'/'dot.png')
    assert all(i['w'] > 0 for i in got[:3]), got
    assert got[3]['src'] == 'attachment:missing.png', 'a missing attachment became a request'
    assert raw and not [u for u in raw if 'missing' in u], raw
    assert all(folder in __import__('urllib.parse').parse.unquote(i['src']) for i in got[:2]), got
    assert got[2]['src'].startswith('data:image/png;base64,'), got


def test_markdown_images_with_spaces_and_unicode_in_their_paths(tmp_path):
    """URL's `pathname` is percent-encoded, so `a b.png` was asked for as a file named `a%20b.png`."""
    d = tmp_path.resolve()/'Notes 9.46 am'; d.mkdir()
    names = ['Screenshot 2026-11-04 at 9.46.03 am.png', 'my pic.png', 'café.png']
    for n in names: (d/n).write_bytes(DOT)
    p = d/'pics.ipynb'
    src = f'<img src="{names[0]}">\n\n![s](my%20pic.png)\n\n![c](caf%C3%A9.png)\n\n![m](<{names[1]}>)\n'
    p.write_text(json.dumps({'cells': [{'cell_type': 'markdown', 'source': src.splitlines(True), 'metadata': {}, 'id': 'c0'}],
        'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    async def go(pg):
        await pg.evaluate('p => leeOpenFile(p)', str(p))
        await pg.wait_for_function(f'(({IMGS})()).length === 4')
        try: await pg.wait_for_function(f'(({IMGS})()).every(i => i.done && i.w > 0)', timeout=5000)
        except Exception: pass
        return await pg.evaluate(IMGS)
    got = _run(go, roots=[d])
    assert len(got) == 4 and all(i['w'] > 0 for i in got), got
