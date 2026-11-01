import hashlib, re, tomllib
from importlib.metadata import version
from pathlib import Path
import abhyasa
from test_lesson_predict import lesson, serve  # noqa: F401

ROOT = Path(__file__).parents[1]
VENDOR = ROOT/'leela/vendor'
SITE = Path(abhyasa.__file__).parents[1]
FILES = {'lee-texparts.js': 'abhyasa/core/texparts.js', 'lee-board.js': 'abhyasa/core/board.js', 'lee-board.css': 'abhyasa/core/board.css',
         'board/rough.js': 'abhyasa/core/vendor/rough.js', 'board/perfect-freehand.mjs': 'abhyasa/core/vendor/perfect-freehand.mjs'}
README = (VENDOR/'README').read_text()
WHEEL = re.search(r'wheel abhyasa-(\S+)-py3-none-any\.whl, SHA-256 (\S+?)[.,]? ', README)

def test_readme_records_the_wheel_and_the_digest_of_each_vendored_file():
    assert WHEEL, 'leela/vendor/README names no abhyasa wheel'
    for name in FILES:
        m = re.search(rf'^{re.escape(name)} SHA-256 ([0-9a-f]{{64}})$', README, re.M)
        assert m, f'leela/vendor/README has no SHA-256 for {name}'
        assert hashlib.sha256((VENDOR/name).read_bytes()).hexdigest() == m[1], f'{name} is not the file the README records'

def test_readme_records_the_digest_of_the_wheel():
    assert WHEEL and re.fullmatch(r'[0-9a-f]{64}', WHEEL[2]), f'leela/vendor/README has no SHA-256 for abhyasa-{WHEEL and WHEEL[1]}-py3-none-any.whl yet: fill it in at the release'

def test_abhyasa_is_pinned_to_the_vendored_wheel():
    assert WHEEL, 'leela/vendor/README names no abhyasa wheel'
    deps = tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['dependencies']
    assert f'abhyasa=={WHEEL[1]}' in deps, f'pyproject.toml must pin abhyasa=={WHEEL[1]}, the wheel the board is vendored from'
    assert version('abhyasa') == WHEEL[1], f'installed abhyasa {version("abhyasa")}, vendored from {WHEEL[1]}'

def test_vendored_files_equal_the_installed_wheel():
    for name, src in FILES.items():
        assert (VENDOR/name).read_bytes() == (SITE/src).read_bytes(), f'{name} differs from {src} in abhyasa {version("abhyasa")}: copy it again (leela/vendor/README)'

def test_the_page_names_the_board_files_and_the_app_serves_them_as_javascript(serve):
    r = serve(lesson())
    page = r.c.get('/').text
    metas = dict(re.findall(r'<meta[^>]*?name="(lee-(?:board|texparts)-[a-z]+)"[^>]*?content="([^"]+)"', page))
    assert set(metas) == {'lee-board-src', 'lee-board-css', 'lee-texparts-src', 'lee-board-assets'}, metas
    assert metas['lee-board-assets'].endswith('/') and '?' not in metas['lee-board-assets']
    for key in ('lee-board-src', 'lee-board-css', 'lee-texparts-src'): assert r.c.get(metas[key]).status_code == 200, key
    for lib, kind in (('rough.js', 'javascript'), ('perfect-freehand.mjs', 'javascript')):
        got = r.c.get(metas['lee-board-assets'] + lib)
        assert got.status_code == 200 and kind in got.headers['content-type'], (lib, got.headers['content-type'])

def test_the_ide_serves_the_hand_font_of_the_board_from_its_own_rupaka(tmp_path):
    "The new board's paper uses Patrick Hand; abhyasa serves it from rupaka's `font_css`, and Leela must too."
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
