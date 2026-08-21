"Search block: Kosha/litesearch façade over a workspace folder."

import pytest

from leela.core.block import Ctx

def test_search_finds_workspace_file(ws):
    hits = list(ws.search.search('block fixture', limit=5) or [])
    assert hits or ws.search.note
    assert isinstance(ws.search.note, str)

def test_search_ctx_cap(ws):
    ctx = Ctx(ws, 'search', caps=('search',))
    assert ctx.search is ws.search
    with pytest.raises(AttributeError, match='without declaring it'): _ = ctx.research

def test_one_key_goes_to_the_declaration_or_to_the_usages(ws, tmp_path, monkeypatch):
    "From a usage it means the declaration; standing on the declaration it means who uses it."
    from fastcore.all import L
    from leela.blocks.search.search import Hit, Search
    mod, use = tmp_path/'mod.py', tmp_path/'use.py'
    mod.write_text('def helper():\n    return 1\n'); use.write_text('from mod import helper\nhelper()\n')
    definition = Hit(path=str(mod), line=1, text='def helper():', symbol='helper')
    usage = Hit(path=str(use), line=2, text='helper()')
    monkeypatch.setattr(Search, 'definitions', lambda self, name, path=None, limit=30: L(definition))
    monkeypatch.setattr(Search, 'usages', lambda self, name, limit=200: L(usage))
    assert ws.search.declaration_or_usages('helper', str(use), 2) == ('definition', L(definition))
    assert ws.search.declaration_or_usages('helper', str(mod), 1) == ('usages', L(usage))
    assert ws.search.declaration_or_usages('helper', str(mod), 2)[0] == 'definition', 'not the def line'
    monkeypatch.setattr(Search, 'definitions', lambda self, name, path=None, limit=30: L())
    assert ws.search.declaration_or_usages('helper', str(use), 2) == ('usages', L(usage)), \
        'nothing declares it, so the usages are the only answer worth giving'

def test_a_notebook_cursor_is_a_cell_and_a_line_in_it(ws, tmp_path):
    "The file line of a notebook hit is a line of JSON, so it can never match the cursor."
    from fastcore.all import L
    from leela.blocks.search.search import Hit
    nb = str(tmp_path/'nb.ipynb')
    hit = Hit(path=nb, line=412, text='def helper():', symbol='helper', cell='c2', cell_index=2, cell_line=3)
    assert ws.search.at_definition(L(hit), nb, 3, cell_index=2)
    assert not ws.search.at_definition(L(hit), nb, 3, cell_index=1)
    assert not ws.search.at_definition(L(hit), nb, 412, cell_index=2), 'the JSON line is not a cursor'
    assert not ws.search.at_definition(L(hit), nb, 0, cell_index=2)

def test_the_jump_route_says_which_direction_it_went(ws, tmp_path, monkeypatch):
    from fastcore.all import L
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.blocks.search.search import Hit, Search
    mod = tmp_path/'mod.py'; mod.write_text('def helper():\n    return 1\n')
    definition = Hit(path=str(mod), line=1, text='def helper():', symbol='helper')
    monkeypatch.setattr(Search, 'definitions', lambda self, name, path=None, limit=30: L(definition))
    monkeypatch.setattr(Search, 'usages', lambda self, name, limit=200: L(Hit(path=str(mod), line=9, text='helper()')))
    with TestClient(ide_app(ws)) as client:
        away = client.get(f'/code/jump?name=helper&path={mod}&line=9').json()
        assert away['kind'] == 'definition' and [h['line'] for h in away['hits']] == [1]
        assert 'backend' in away and 'note' in away
        home = client.get(f'/code/jump?name=helper&path={mod}&line=1').json()
        assert home['kind'] == 'usages' and [h['line'] for h in home['hits']] == [9]

@pytest.fixture
def no_index(monkeypatch):
    "No Kosha index, so the site-packages scan is what answers. The index has its own tests."
    from leela.blocks.search.search import Search
    monkeypatch.setattr(Search, '_kosha', lambda self: None)

def _venv(root, files):
    "A project with a virtualenv whose site-packages holds `files`, keyed by relative path."
    (root/'.venv'/'bin').mkdir(parents=True, exist_ok=True)
    (root/'.venv'/'bin'/'python').write_text('')
    site = root/'.venv'/'lib'/'python3.13'/'site-packages'
    for rel, text in files.items():
        p = site/rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)
    return site

def test_a_symbol_a_package_defines_is_found_in_the_venv(ws, tmp_path, no_index):
    """A name the project only imports is defined in site-packages, which the project walk skips
    on purpose. Without it the only answer was the import lines that mention it."""
    site = _venv(tmp_path, {
        'fastcore/basics.py': 'def store_attr(names=None):\n    pass\n',
        'fastcore/other.py': 'class STORE_ATTR: pass\n',
        'jedi/third_party/typeshed/x.pyi': 'def store_attr(a) -> None: ...\n'})
    (tmp_path/'use.py').write_text('from fastcore.basics import store_attr\nstore_attr()\n')
    s = ws.search
    assert [str(r) for r in s.env_roots()] == [str(site)]
    hits = s.env_definitions('store_attr', path=str(tmp_path/'use.py'))
    assert hits[0].package == 'fastcore' and hits[0].path.endswith('fastcore/basics.py')
    assert hits[0].line == 1 and hits[0].kind == 'env-definition' and hits[0].symbol == 'store_attr'
    assert all('STORE_ATTR' not in h.text for h in hits), 'a definition is an identifier, so case matters'
    assert not any('third_party' in h.path for h in hits[:1]), 'a vendored stub is not the answer'
    kind, out = s.declaration_or_usages('store_attr', str(tmp_path/'use.py'), 2)
    assert kind == 'definition' and out[0].package == 'fastcore'
    assert 'not in this project' in s.note, 'and it says where it came from'

def test_the_package_the_file_imports_from_is_the_one_offered_first(ws, tmp_path, no_index):
    "Twelve packages define `patch`. The one this file imported is the one that was clicked."
    _venv(tmp_path, {'bottle.py': 'patch = 1\n', 'fastcore/basics.py': 'def patch(f=None):\n    pass\n',
                     'requests/api.py': 'def patch(url):\n    pass\n'})
    (tmp_path/'mine.py').write_text('from fastcore.basics import patch\n')
    s = ws.search
    assert s.import_package('patch', str(tmp_path/'mine.py')) == 'fastcore'
    assert s.env_definitions('patch', path=str(tmp_path/'mine.py'))[0].package == 'fastcore'
    assert {h.package for h in s.env_definitions('patch')} == {'bottle', 'fastcore', 'requests'}, \
        'with nothing to go on they are all still offered'
    assert s.import_package('patch', str(tmp_path/'missing.py')) == '', 'and a file that is not there is not an error'

def test_a_method_is_not_offered_as_the_definition_of_a_bare_name(ws, tmp_path, no_index):
    "`def render(self)` in twelve packages is a method called render, not the name that was clicked."
    site = _venv(tmp_path, {'one/a.py': 'class C:\n    def render(self): pass\n',
                            'two/b.py': 'def render():\n    pass\n'})
    s = ws.search
    assert [h.package for h in s.env_definitions('render')] == ['two']
    (site/'two'/'b.py').unlink()
    indented = s.env_definitions('render')
    assert [h.package for h in indented] == ['one'], 'an indented one answers when nothing else does'

def test_a_project_without_a_venv_has_no_environment_to_search(ws, tmp_path, no_index):
    assert ws.search.env_roots() == []
    assert ws.search.env_definitions('anything') == []

def test_the_index_answers_before_the_scan_when_it_knows_the_name(ws, tmp_path, monkeypatch):
    """Kosha carries the package and the line. A path prefix only guesses at the package, and a
    namespace package, a vendored copy or an editable install each break the guess."""
    import json
    from leela.blocks.search.search import Search
    site = _venv(tmp_path, {'fastcore/basics.py': 'def store_attr(x):\n    pass\n'})
    real = site/'fastcore'/'basics.py'
    class Store:
        def rows_where(self, where, args, select='', limit=0):
            assert 'json_extract' in where and args == ['store_attr'], where
            return [{'content': 'def store_attr(x):\nbody', 'package': 'fastcore-editable',
                     'metadata': json.dumps({'name': 'store_attr', 'path': str(real), 'lineno': 1})},
                    {'content': 'gone', 'package': 'ghost',
                     'metadata': json.dumps({'name': 'store_attr', 'path': str(site/'ghost.py'), 'lineno': 9})}]
    monkeypatch.setattr(Search, '_kosha', lambda self: type('K', (), {'env_st': Store()})())
    hits = ws.search.env_symbols('store_attr')
    assert [(h.package, h.line, h.kind) for h in hits] == [('fastcore-editable', 1, 'env-definition')], \
        'a row whose file is gone is a stale index, not a result'
    assert hits[0].text == 'def store_attr(x):' and ws.search.backend == 'kosha'
    assert ws.search.env_definitions('store_attr')[0].package == 'fastcore-editable', 'the index wins'

def test_a_missing_or_broken_index_still_finds_the_definition(ws, tmp_path, monkeypatch):
    "The scan needs nothing to be fresh, which is the point of keeping it."
    from leela.blocks.search.search import Search
    _venv(tmp_path, {'fastcore/basics.py': 'def store_attr(x):\n    pass\n'})
    class Broken:
        def rows_where(self, *a, **k): raise RuntimeError('index is locked')
    monkeypatch.setattr(Search, '_kosha', lambda self: type('K', (), {'env_st': Broken()})())
    assert ws.search.env_symbols('store_attr') == []
    assert 'index is locked' in ws.search.note and 'scanning site-packages' in ws.search.note
    found = ws.search.env_definitions('store_attr')
    assert [h.package for h in found] == ['fastcore'] and ws.search.backend == 'rg'
