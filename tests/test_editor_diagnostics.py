"""Editable CodeMirror surfaces show compiler errors and warnings without a third-party linter."""

from pathlib import Path

from starlette.testclient import TestClient

from leela.app import _python_diagnostics, ide_app
from leela.workspace import Workspace

ROOT = Path(__file__).resolve().parents[1]
EDITOR = (ROOT / 'frontend/editor.js').read_text()
PACKAGE = (ROOT / 'frontend/package.json').read_text()


def test_python_compiler_reports_precise_syntax_errors():
    source = 'answer = 1\nif True print(answer)\n'
    diagnostics = _python_diagnostics(source, 'draft.py')

    assert len(diagnostics) == 1
    error = diagnostics[0]
    assert error['severity'] == 'error'
    assert error['source'] == 'Python'
    assert error['code'] == 'SyntaxError'
    assert error['message'] == 'invalid syntax'
    assert source[error['from']:error['to']]
    assert error['from'] >= source.index('if True')


def test_python_compiler_reports_warnings_and_never_executes_source():
    warnings = _python_diagnostics('value is 1\nraise RuntimeError("must not run")\n')

    assert len(warnings) == 1
    warning = warnings[0]
    assert warning['severity'] == 'warning'
    assert warning['code'] == 'SyntaxWarning'
    assert 'Did you mean "=="?' in warning['message']


def test_lint_endpoint_checks_unsaved_python_without_an_external_linter():
    with TestClient(ide_app(Workspace(roots=[]))) as client:
        response = client.post('/lint', json={'lang': 'python', 'code': 'if True print(1)'})

    assert response.status_code == 200
    assert response.json()['diagnostics'][0]['severity'] == 'error'


def test_codemirror_lint_source_covers_errors_warnings_and_readonly_surfaces():
    assert '"@codemirror/lint"' in PACKAGE
    assert 'import {linter} from "@codemirror/lint"' in EDITOR
    assert 'node.type.isError' in EDITOR
    assert 'severity: "error"' in EDITOR
    assert 'data.diagnostics' in EDITOR
    assert 'readOnly || !lang' in EDITOR
    assert 'return linter(source, {delay: 400})' in EDITOR
