from leela.blocks.fs.fs import Sandbox
from leela.blocks.refactor.refactor import replace_plan


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
