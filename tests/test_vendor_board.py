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
WHEEL = re.search(r'wheel abhyasa-(\S+)-py3-none-any\.whl, SHA-256 ([0-9a-f]{64})', README)

def test_readme_records_the_wheel_and_the_digest_of_each_vendored_file():
    assert WHEEL, 'leela/vendor/README names no abhyasa wheel'
    for name in FILES:
        m = re.search(rf'^{re.escape(name)} SHA-256 ([0-9a-f]{{64}})$', README, re.M)
        assert m, f'leela/vendor/README has no SHA-256 for {name}'
        assert hashlib.sha256((VENDOR/name).read_bytes()).hexdigest() == m[1], f'{name} is not the file the README records'

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