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
    def __init__(self, refs=(), rename=None): self.refs, self.rename, self.asked = list(refs), rename, []
    def request(self, method, path, text, line=0, character=0, extra=None, timeout=5):
        self.asked.append(method)
        if method == 'textDocument/references': return self.refs
        if method == 'textDocument/rename': return self.rename
        raise RuntimeError(f'unexpected {method}')


def build(tmp_path, refs=(), rename=None):
    ws = Workspace(roots=[tmp_path], port=8000)
    lsp = FakeLsp(refs, rename)
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


def test_a_same_named_method_on_another_class_is_left_alone(tmp_path):
    "The server resolved the symbol, so `C.area` is never in the references and never rewritten."
    refs = project(tmp_path)
    c, ws, lsp = build(tmp_path, refs)
    c.post('/lsp/rename', json={'path': str(tmp_path/'core.py'), 'text': (tmp_path/'core.py').read_text(),
                                'line': 0, 'character': 4, 'newName': 'surface', 'apply': True})
    assert (tmp_path/'shadow.py').read_text() == 'class C:\n    def area(self): return 1\n'


def test_the_route_asks_for_references_rather_than_the_servers_rename(tmp_path):
    "pyright answers rename for one file. A rename that trusted it would miss every other file."
    refs = project(tmp_path)
    c, ws, lsp = build(tmp_path, refs, rename={'documentChanges': [{'textDocument': {'uri': uri(tmp_path/'core.py')},
                                                                   'edits': [{'range': refs[0]['range'], 'newText': 'surface'}]}]})
    c.post('/lsp/rename', json={'path': str(tmp_path/'core.py'), 'text': (tmp_path/'core.py').read_text(),
                                'line': 0, 'character': 4, 'newName': 'surface'})
    assert 'textDocument/references' in lsp.asked
    assert 'textDocument/rename' not in lsp.asked


def test_a_preview_writes_nothing(tmp_path):
    refs = project(tmp_path)
    c, ws, lsp = build(tmp_path, refs)
    d = c.post('/lsp/rename', json={'path': str(tmp_path/'core.py'), 'text': (tmp_path/'core.py').read_text(),
                                    'line': 0, 'character': 4, 'newName': 'surface'}).json()
    assert d['applied'] is False
    assert d['files'][0]['after'] != d['files'][0]['before']
    assert (tmp_path/'core.py').read_text() == 'def area(r): return r\n'


def test_an_applied_rename_is_one_undoable_journal_entry(tmp_path):
    refs = project(tmp_path)
    c, ws, lsp = build(tmp_path, refs)
    c.post('/lsp/rename', json={'path': str(tmp_path/'core.py'), 'text': (tmp_path/'core.py').read_text(),
                                'line': 0, 'character': 4, 'newName': 'surface', 'apply': True})
    op = ws.journal.operations[-1]
    assert op['kind'] == 'rename-symbol'
    assert op['label'] == 'Rename to surface'
    assert {r['path'] for r in op['resources']} == {str(tmp_path/'core.py'), str(tmp_path/'use.py')}


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


def test_a_name_that_is_not_an_identifier_is_refused_before_the_server_is_asked(tmp_path):
    refs = project(tmp_path)
    c, ws, lsp = build(tmp_path, refs)
    r = c.post('/lsp/rename', json={'path': str(tmp_path/'core.py'), 'text': '', 'line': 0,
                                    'character': 4, 'newName': 'not a name', 'apply': True})
    assert r.json().get('ok') is not True
    assert lsp.asked == []
    assert (tmp_path/'core.py').read_text() == 'def area(r): return r\n'


def test_a_position_with_no_references_says_so_rather_than_reporting_success(tmp_path):
    project(tmp_path)
    c, ws, lsp = build(tmp_path, [])
    r = c.post('/lsp/rename', json={'path': str(tmp_path/'core.py'), 'text': (tmp_path/'core.py').read_text(),
                                    'line': 0, 'character': 0, 'newName': 'surface', 'apply': True})
    assert r.json().get('ok') is not True
