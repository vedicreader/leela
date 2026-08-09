"""File-language detection and the browser's bundled syntax modes stay aligned."""

from leela.fs import lang_for

from tests.assets import EDITOR, JS as CLIENT


def test_common_project_languages_are_detected_from_paths():
    expected = {
        'pyproject.toml': 'toml', 'app.js': 'javascript', 'worker.mjs': 'javascript',
        'view.jsx': 'jsx', 'app.ts': 'typescript', 'view.tsx': 'tsx',
        'config.yaml': 'yaml', 'data.json': 'json', 'settings.jsonc': 'json',
        'main.rs': 'rust', 'main.go': 'go', 'Main.java': 'java', 'lib.cpp': 'cpp',
        'layout.xml': 'xml', 'local.properties': 'properties', 'script.sh': 'bash',
        'Dockerfile': 'bash', 'Cargo.lock': 'toml',
    }
    assert {name: lang_for(name) for name in expected} == expected


def test_codemirror_bundle_declares_every_detected_syntax_family():
    for language in ('toml', 'javascript', 'typescript', 'jsx', 'tsx', 'yaml', 'json',
                     'bash', 'rust', 'go', 'java', 'cpp', 'xml', 'properties'):
        assert language in EDITOR
    assert 'StreamLanguage.define(toml)' in EDITOR
    assert 'StreamLanguage.define(shell)' in EDITOR


def test_tagged_markdown_fences_support_non_python_languages_without_becoming_executable():
    assert "toml: 'toml'" in CLIENT and "yml: 'yaml'" in CLIENT and "jsonc: 'json'" in CLIENT
    assert '!CODE_LANGS[named]' in CLIENT
    assert "python && el.classList.contains('lee-reply')" in CLIENT
