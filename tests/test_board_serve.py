"The screen guide's board, served from Leela's own rupaka (`rupaka.board`), with its pens and the hand font of its paper."
import re
from test_lesson_predict import lesson, serve  # noqa: F401

def test_the_page_names_the_board_files_and_the_app_serves_them_from_rupaka(serve):
    from rupaka.board import assets, bundle
    r = serve(lesson())
    page = r.c.get('/').text
    metas = dict(re.findall(r'<meta[^>]*?name="(lee-(?:board|texparts)-[a-z]+)"[^>]*?content="([^"]+)"', page))
    assert set(metas) == {'lee-board-src', 'lee-board-css', 'lee-texparts-src', 'lee-board-assets'}, metas
    assert metas['lee-board-assets'] == '/leeboard/libs/'
    for key, want, kind in (('lee-board-src', bundle('js'), 'javascript'), ('lee-board-css', bundle('css'), 'css'), ('lee-texparts-src', assets().tex.read_text(), 'javascript')):
        got = r.c.get(metas[key])
        assert got.status_code == 200 and kind in got.headers['content-type'] and got.text == want, key
    assert 'window.rupakaBoard' in r.c.get(metas['lee-board-src']).text
    for lib in ('rough.js', 'perfect-freehand.mjs'):
        got = r.c.get(metas['lee-board-assets'] + lib)
        assert got.status_code == 200 and 'javascript' in got.headers['content-type'] and got.content == (assets().libs/lib).read_bytes(), lib

def test_no_board_file_is_vendored_any_more():
    from pathlib import Path
    v = Path(__file__).parents[1]/'leela/vendor'
    assert not [p.name for p in (v/'lee-board.js', v/'lee-board.css', v/'lee-texparts.js', v/'board') if p.exists()]

def test_the_ide_serves_the_hand_font_of_the_board_from_its_own_rupaka(tmp_path):
    "The board's paper uses Patrick Hand; abhyasa serves it from rupaka's `font_css`, and Leela must too."
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.core.web import hand_url
    from leela.workspace import Workspace
    ws = Workspace(roots=[tmp_path])
    try:
        with TestClient(ide_app(ws), base_url='http://127.0.0.1:5011') as c:
            assert f'href="{hand_url()}"' in c.get('/').text
            css = c.get(hand_url())
            assert css.status_code == 200 and css.headers['content-type'].startswith('text/css')
            assert css.text.count('@font-face') == 2 and all("'Patrick Hand'" in l for l in css.text.splitlines())
            font = c.get('/leefonts/patrick-hand-latin-400-normal.woff2')
            assert 'url(/leefonts/patrick-hand-latin-400-normal.woff2)' in css.text and font.status_code == 200 and font.content[:4] == b'wOF2'
    finally: ws.shutdown_now()
