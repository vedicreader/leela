"Refactoring and the language server behind it."

from leela.blocks.fs.fs import Sandbox
from leela.blocks.refactor.refactor import replace_plan
import pytest
from leela.blocks.refactor.python import extract, inline
from leela.blocks.lsp.lsp import PyrightService

def test_replace_plan_changes_text_files_and_skips_notebooks(tmp_path):
    root = tmp_path/'project'; root.mkdir()
    (root/'a.py').write_text('value = old\nold_value = old\n')
    (root/'notes.ipynb').write_text('{}')
    rows, skipped = replace_plan(Sandbox([root]), 'old', 'new', word=True)
    assert len(rows) == 1 and rows[0].edits == 2
    assert rows[0].after == 'value = new\nold_value = new\n'
    assert str(root/'notes.ipynb') in skipped

def test_replace_plan_accepts_regex_and_rejects_invalid_patterns(tmp_path):
    root = tmp_path/'project'; root.mkdir(); (root/'a.txt').write_text('a1 a22')
    rows, _ = replace_plan(Sandbox([root]), r'a(\d+)', r'b\1', regex=True)
    assert rows[0].after == 'b1 b22'
    try: replace_plan(Sandbox([root]), '(', '', regex=True)
    except ValueError as e: assert 'invalid regular expression' in str(e)
    else: assert False

def test_literal_replacement_backslashes_are_not_regex_escapes(tmp_path):
    root = tmp_path/'project'; root.mkdir(); (root/'a.txt').write_text('root = HERE\n')
    rows, _ = replace_plan(Sandbox([root]), 'HERE', 'C:\\new\\1')
    assert rows[0].after == 'root = C:\\new\\1\n'

def test_replace_plan_skips_files_that_did_not_decode_cleanly(tmp_path):
    root = tmp_path/'project'; root.mkdir()
    (root/'legacy.txt').write_bytes(b'caf\xe9 old\n')
    rows, skipped = replace_plan(Sandbox([root]), 'old', 'new')
    assert not rows and str(root/'legacy.txt') in skipped

def test_extract_and_inline_are_each_others_undo():
    src = 'total = price * qty\n'
    row = extract('a.py', src, 8, 19, 'variable', 'amount')
    assert row.after == 'amount = price * qty\ntotal = amount\n'
    with pytest.raises(ValueError, match='literal'):
        extract('a.py', 'x = value\n', 4, 9, 'constant', 'default')
    src = 'x = 1\ny = compute(x)\n'
    with pytest.raises(ValueError, match='complete statement lines'):
        extract('a.py', src, src.index('compute'), src.index(')') + 1, 'function', 'f')
    src = 'value = 1\nprint(len(value))\n'
    row = extract('a.py', src, src.index('print'), len(src), 'function', 'show')
    assert row.after == 'value = 1\ndef show(value):\n    print(len(value))\n\nshow(value)\n'
    src = 'total = price * qty\n'
    out = extract('a.py', src, 8, 19, 'variable', 'amount').after
    assert inline('a.py', out, out.index('amount')).after == 'total = (price * qty)\n'
    src = 'amount = price * qty\ntotal = amount\nprint(amount)\n'
    row = inline('a.py', src, src.index('amount'))
    assert row.after == 'total = (price * qty)\nprint((price * qty))\n' and row.edits == 2
    src = 'x = a if b else c\nprint(x * 2)\n'
    assert inline('a.py', src, 0).after == 'print((a if b else c) * 2)\n'
    src = 'n = 3\nprint(n)\n'
    assert inline('a.py', src, src.index('n)')).after == 'print(3)\n'
    with pytest.raises(ValueError, match='cursor on a variable'): inline('a.py', 'x = 1\n', 4)









@pytest.mark.parametrize('src,pos,why', [
    ('x = 1\nx = 2\nprint(x)\n', 0, 'exactly once'),
    ('for x in items:\n    print(x)\n', 4, 'exactly once'),
    ('x = 1\nglobal x\n', 0, 'global or nonlocal'),
    ('x = 1; print(x)\n', 0, 'lines of its own'),
    ('x = 1  # keep\nprint(x)\n', 0, 'lines of its own'),
    ('x = 1\n', 0, 'never read'),
])
def test_inline_refuses_what_it_cannot_reverse(src, pos, why):
    with pytest.raises(ValueError, match=why): inline('a.py', src, pos)


def test_pyright_is_optional_and_reports_status(tmp_path, monkeypatch):
    monkeypatch.setattr('shutil.which', lambda name: None)
    service = PyrightService(tmp_path)
    assert not service.available and not service.start()
    rows, note = service.diagnostics(tmp_path/'a.py', 'x: int = "bad"')
    assert rows == [] and 'not installed' in note
