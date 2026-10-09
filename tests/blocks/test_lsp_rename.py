"""`/lsp/rename` builds the workspace rename from references, not from the server's rename edit."""

from __future__ import annotations

from urllib.parse import quote

from starlette.testclient import TestClient

from leela.app import ide_app
from leela.workspace import Workspace


def uri(p): return 'file://' + quote(str(p))


def ref(p, line, start, end):
    "One `textDocument/references` row, in the shape pyright returns."
    return {'uri': uri(p), 'range': {'start': {'line': line, 'character': start},
                                     'end': {'line': line, 'character': end}}}


class FakeLsp:
    "A language server that answers references and nothing else."
    server, lang, available, alive, note = 'fake', 'python', True, True, ''
    def __init__(self, refs=()): self.refs = list(refs)
    def request(self, method, path, text, line=0, character=0, extra=None, timeout=5):
        if method == 'textDocument/references': return self.refs
        raise RuntimeError(f'unexpected {method}')


def build(tmp_path, refs=()):
    ws = Workspace(roots=[tmp_path], port=8000)
    lsp = FakeLsp(refs)
    ws.lsp_for = lambda lang='python': lsp
    return TestClient(ide_app(ws)), ws, lsp


def project(tmp_path):
    "core.py defines `area`, use.py imports and calls it, shadow.py has an unrelated `C.area`."
    (tmp_path/'core.py').write_text('def area(r): return r\n')
    (tmp_path/'use.py').write_text('from core import area\n\nprint(area(2))\n')
    (tmp_path/'shadow.py').write_text('class C:\n    def area(self): return 1\n')
    return [ref(tmp_path/'core.py', 0, 4, 8),
            ref(tmp_path/'use.py', 0, 17, 21),
            ref(tmp_path/'use.py', 2, 6, 10)]


def test_a_rename_reaches_every_file_the_references_name(tmp_path):
    refs = project(tmp_path)
    c, ws, lsp = build(tmp_path, refs)
    r = c.post('/lsp/rename', json={'path': str(tmp_path/'core.py'), 'text': (tmp_path/'core.py').read_text(),
                                    'line': 0, 'character': 4, 'newName': 'surface', 'apply': True})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d['applied'] is True
    assert {f['path']: f['edits'] for f in d['files']} == {
        str(tmp_path/'core.py'): 1, str(tmp_path/'use.py'): 2}
    assert (tmp_path/'core.py').read_text() == 'def surface(r): return r\n'
    assert (tmp_path/'use.py').read_text() == 'from core import surface\n\nprint(surface(2))\n'


def test_a_reference_outside_the_open_roots_is_counted_and_not_written(tmp_path, monkeypatch):
    "Renaming a symbol a dependency also uses must not rewrite the dependency."
    outside = tmp_path.parent/'outside_root.py'
    outside.write_text('area = 1\n')
    refs = project(tmp_path) + [ref(outside, 0, 0, 4)]
    c, ws, lsp = build(tmp_path, refs)
    d = c.post('/lsp/rename', json={'path': str(tmp_path/'core.py'), 'text': (tmp_path/'core.py').read_text(),
                                    'line': 0, 'character': 4, 'newName': 'surface', 'apply': True}).json()
    assert d['outside'] == 1
    assert outside.read_text() == 'area = 1\n'
    assert {f['path'] for f in d['files']} == {str(tmp_path/'core.py'), str(tmp_path/'use.py')}
