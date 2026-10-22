"Refactoring and the language server behind it."

from leela.blocks.fs.fs import Sandbox
from kosha.refactor import replace_plan
from leela.blocks.lsp.lsp import PyrightService

def _plan(root, *a, **kw):
    fs = Sandbox([root])
    return replace_plan(fs.walk(), *a, read=fs.read, **kw)

def test_replace_plan_changes_text_files_and_skips_notebooks(tmp_path):
    root = tmp_path/'project'; root.mkdir()
    (root/'a.py').write_text('value = old\nold_value = old\n')
    (root/'notes.ipynb').write_text('{}')
    rows, skipped = _plan(root, 'old', 'new', word=True)
    assert len(rows) == 1 and rows[0].edits == 2
    assert rows[0].after == 'value = new\nold_value = new\n'
    assert str(root/'notes.ipynb') in skipped


def test_pyright_is_optional_and_reports_status(tmp_path, monkeypatch):
    monkeypatch.setattr('shutil.which', lambda name: None)
    # `find_server` falls back to the extras directory, which is where a frozen app installs one.
    # Stubbing PATH alone made this pass or fail on whether this machine had ever installed a
    # language server from the Tools row.
    monkeypatch.setattr('leela.extras_bin', lambda: tmp_path/'no-extras')
    service = PyrightService(tmp_path)
    assert not service.available and not service.start()
    rows, note = service.diagnostics(tmp_path/'a.py', 'x: int = "bad"')
    assert rows == [] and note
