import hashlib, re, subprocess
from pathlib import Path
import pytest
from test_lesson_predict import lesson, serve  # noqa: F401

ROOT = Path(__file__).parents[1]
VENDOR = ROOT/'leela/vendor'
ABHYASA = ROOT.parent/'abhyasa'
FILES = {'lee-texparts.js': 'abhyasa/core/texparts.js', 'lee-board.js': 'abhyasa/core/board.js', 'lee-board.css': 'abhyasa/core/board.css',
         'board/rough.js': 'abhyasa/core/vendor/rough.js', 'board/perfect-freehand.mjs': 'abhyasa/core/vendor/perfect-freehand.mjs'}
README = (VENDOR/'README').read_text()
COMMIT = re.search(r'abhyasa commit ([0-9a-f]{40})', README)

def test_readme_records_the_commit_and_the_digest_of_each_vendored_file():
    assert COMMIT, 'leela/vendor/README names no abhyasa commit'
    for name in FILES:
        m = re.search(rf'^{re.escape(name)} SHA-256 ([0-9a-f]{{64}})$', README, re.M)
        assert m, f'leela/vendor/README has no SHA-256 for {name}'
        assert hashlib.sha256((VENDOR/name).read_bytes()).hexdigest() == m[1], f'{name} is not the file the README records'
    assert 'wheel' in README.split('abhyasa commit')[1].split('\n\n')[0], 'the README must say the 0.0.14 wheel is the later source'

def test_vendored_files_equal_abhyasa_at_the_recorded_commit():
    assert COMMIT, 'leela/vendor/README names no abhyasa commit'
    if not (ABHYASA/'.git').exists(): pytest.skip(f'no abhyasa checkout at {ABHYASA}; once 0.0.14 is released the wheel is the source to compare')
    git = lambda *a: subprocess.run(['git', '-C', str(ABHYASA), *a], capture_output=True)
    if git('cat-file', '-e', f'{COMMIT[1]}^{{commit}}').returncode: pytest.skip(f'abhyasa checkout at {ABHYASA} has no commit {COMMIT[1]}')
    for name, src in FILES.items():
        shown = git('show', f'{COMMIT[1]}:{src}')
        assert shown.returncode == 0, shown.stderr
        assert (VENDOR/name).read_bytes() == shown.stdout, f'{name} differs from {src} at {COMMIT[1][:7]}'

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