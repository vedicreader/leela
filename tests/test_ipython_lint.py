"Notebook cells written with shell escapes and magics: no editor diagnostics for the IPython lines."
import pytest
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.blocks.nb.nb import mask_ipython
from leela.workspace import Workspace

CELL = '!echo hi\n%cd sub\nx = 1 +'

@pytest.mark.parametrize('src', [
    '! git clone --depth 1 https://a.b/c\n%cd sub/results\nx = undefined_name',
    'files = !ls\nx = %timeit -o f()\ny = 2',
    'foo.bar?\n??baz\n?qux\nz = 1',
    '!pip install \\\n  numpy\nok = 1',
    'if a:\n    !ls\n    %pwd',
    '%%bash\necho hi\nls',
    '%%time\nx = 1',
    's = "!not magic"  # %nor this',
    '!x\r\ny = 1\r\n',
])
def test_masking_keeps_every_offset_and_leaves_python_compilable(src):
    out = mask_ipython(src)
    assert len(out) == len(src) and out.splitlines(True) != [] and [len(l) for l in out.splitlines(True)] == [len(l) for l in src.splitlines(True)]
    compile(out, '<cell>', 'exec')
    assert mask_ipython('x = undefined_name\n') == 'x = undefined_name\n'

def test_a_cell_magic_other_than_python_sends_no_python():
    assert not mask_ipython('%%bash\necho hi').strip() and mask_ipython('%%time\nx = 1').endswith('x = 1')

def lint(tmp_path, path):
    c = TestClient(ide_app(Workspace(roots=[tmp_path], port=8000)))
    return c.post('/lint', json={'code': CELL, 'lang': 'python', 'path': path}).json()['diagnostics']

def test_lint_of_a_notebook_cell_reports_only_the_real_error(tmp_path):
    rows = lint(tmp_path, str(tmp_path/'a.ipynb'))
    line3 = CELL.index('x = 1')
    assert rows and all(r['from'] >= line3 for r in rows), rows
    assert any(r['severity'] == 'error' for r in rows)

def test_lint_of_a_py_file_still_flags_the_escape(tmp_path):
    assert lint(tmp_path, '')[0]['from'] == 0