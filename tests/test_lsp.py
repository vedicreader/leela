from leela.lsp import PyrightService


def test_pyright_is_optional_and_reports_status(tmp_path, monkeypatch):
    monkeypatch.setattr('shutil.which', lambda name: None)
    service = PyrightService(tmp_path)
    assert not service.available and not service.start()
    rows, note = service.diagnostics(tmp_path/'a.py', 'x: int = "bad"')
    assert rows == [] and 'not installed' in note
