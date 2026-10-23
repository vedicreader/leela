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
    src = '<img src="images/dot.png">\n\n![d](images/dot.png)\n\n![a](attachment:a.png)\n'
    p.write_text(json.dumps({'cells': [{'cell_type': 'markdown', 'source': src.splitlines(True), 'metadata': {}, 'id': 'c0',
        'attachments': {'a.png': {'image/png': base64.b64encode(DOT).decode()}}}],
        'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    async def go(pg):
        await pg.evaluate(f'leeOpenFile({str(p)!r})')
        await pg.wait_for_function(f'(({IMGS})()).length === 3')
        try: await pg.wait_for_function(f'(({IMGS})()).every(i => i.done && i.w > 0)', timeout=5000)
        except Exception: pass
        return await pg.evaluate(IMGS)
    got = _run(go, roots=[tmp_path])
    folder = str(tmp_path/'images'/'dot.png')
    assert all(i['w'] > 0 for i in got), got
    assert all(folder in __import__('urllib.parse').parse.unquote(i['src']) for i in got[:2]), got
    assert got[2]['src'].startswith('data:image/png;base64,'), got
