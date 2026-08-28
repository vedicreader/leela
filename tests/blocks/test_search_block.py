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
    monkeypatch.setattr(Search, '_kosha', lambda self, path=None: None)

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

def test_the_jump_route_carries_the_dotted_chain(ws, tmp_path, no_index):
    "The chain is what says `fastcore.test` is a module, so the route has to pass it through."
    from starlette.testclient import TestClient
    from leela.app import ide_app
    site = _venv(tmp_path, {'fastcore/test.py': 'def test_eq(a, b): pass\n',
                            'rich/style.py': 'def test():\n    pass\n'})
    use = tmp_path/'use.py'; use.write_text('from fastcore.test import test_eq\n')
    with TestClient(ide_app(ws)) as client:
        d = client.get(f'/code/jump?name=test&path={use}&line=1&dotted=fastcore.test').json()
        assert d['kind'] == 'definition' and d['hits'][0]['path'] == str(site/'fastcore'/'test.py')
        assert d['hits'][0]['module'] == 'fastcore.test'
        bare = client.get(f'/code/jump?name=test&path={use}&line=1').json()
        assert bare['hits'][0]['path'].endswith('rich/style.py'), 'no chain, no module'

def test_a_package_api_row_says_which_file_the_name_is_in(ws, tmp_path, monkeypatch):
    "The listing is a way into the package's files, so every row it can place carries one."
    from leela.blocks.search.search import Search
    site = _venv(tmp_path, {'fastcore/aio.py': 'def run_sync(): pass\n'})
    rows = [{'mod_name': 'fastcore.aio.run_sync', 'docstring': 'run it',
             'path': '/elsewhere/.venv/lib/python3.12/site-packages/fastcore/aio.py', 'lineno': 42},
            {'mod_name': 'fastcore.gone', 'docstring': '', 'path': '/nowhere/at/all.py', 'lineno': 3},
            {'mod_name': 'fastcore.blank', 'docstring': '', 'path': None, 'lineno': None}]
    class K:
        def public_api(self, pkg, meta_cols='', limit=200):
            assert 'path' in meta_cols and 'lineno' in meta_cols, meta_cols
            return rows
    monkeypatch.setattr(Search, '_kosha', lambda self: K())
    got = ws.search.package_api('fastcore')
    assert got[0]['path'] == str(site/'fastcore'/'aio.py') and got[0]['line'] == 42
    assert got[1]['path'] == '' and got[2]['path'] == '' and got[2]['line'] == 0
    assert ws.search.package_api('') == []

def test_a_dotted_module_name_opens_the_module_it_names(ws, tmp_path, no_index):
    """`fastcore.test` is a module, and nothing declares a module. The name alone found whichever
    package happened to have a `def test`, which is never the file that was clicked."""
    site = _venv(tmp_path, {'fastcore/__init__.py': '__version__ = "1"\n',
                            'fastcore/test.py': 'def test_eq(a, b):\n    pass\n',
                            'rich/style.py': 'def test():\n    pass\n'})
    (tmp_path/'use.py').write_text('from fastcore.test import test_eq\ntest_eq(1, 1)\n')
    s, here = ws.search, str(tmp_path/'use.py')
    assert str(s.module_file('fastcore.test', here)) == str(site/'fastcore'/'test.py')
    assert str(s.module_file('fastcore', here)) == str(site/'fastcore'/'__init__.py'), 'a package is its `__init__`'
    assert s.module_file('fastcore.nope', here) is None
    kind, hits = s.declaration_or_usages('test', here, 1, dotted='fastcore.test')
    assert kind == 'definition' and hits[0].path == str(site/'fastcore'/'test.py')
    assert hits[0].line == 1 and hits[0].module == 'fastcore.test' and hits[0].package == 'fastcore'
    assert 'is a module' in s.note
    kind, hits = s.declaration_or_usages('test', here, 1)
    assert hits[0].path.endswith('rich/style.py'), 'without the chain there is nothing saying it is a module'
    assert str(s.module_file('.'.join(['fastcore', 'test']), here)).endswith('test.py')
    assert s.module_file('fastcore..test', here) is None and s.module_file('', here) is None

def test_a_name_the_file_imports_as_a_module_is_that_module(ws, tmp_path, no_index):
    "`from fastcore import test` makes `test` a module here, whatever `def test` a package has."
    site = _venv(tmp_path, {'fastcore/__init__.py': '', 'fastcore/test.py': 'def test_eq(a, b): pass\n',
                            'rich/style.py': 'def test():\n    pass\n'})
    mine = tmp_path/'mine.py'
    mine.write_text('from fastcore import test\nimport fastcore.test as t2\nfrom fastcore.test import test_eq\n')
    s = ws.search
    assert s.imported_module('test', str(mine)) == 'fastcore.test'
    assert s.imported_module('t2', str(mine)) == 'fastcore.test', 'an alias names the module it was given'
    assert s.imported_module('test_eq', str(mine)) == 'fastcore.test.test_eq', 'which is no file, so it is no module'
    assert s.module_file('fastcore.test.test_eq', str(mine)) is None
    assert s.imported_module('nothing', str(mine)) == ''
    kind, hits = s.declaration_or_usages('test', str(mine), 1)
    assert kind == 'definition' and hits[0].path == str(site/'fastcore'/'test.py')
    kind, hits = s.declaration_or_usages('test_eq', str(mine), 1)
    assert hits[0].path == str(site/'fastcore'/'test.py') and hits[0].line == 1, 'a symbol is still a symbol'

def test_a_sibling_module_answers_a_relative_import(ws, tmp_path, no_index):
    "`from .workspace import W` puts the module beside the file, which is where it is looked for first."
    pkg = tmp_path/'leela'; pkg.mkdir(); (pkg/'__init__.py').write_text('')
    (pkg/'workspace.py').write_text('class W: pass\n')
    app = pkg/'app.py'; app.write_text('from .workspace import W\n')
    s = ws.search
    assert s.imported_module('workspace', str(app)) == '', 'a relative import binds the name, not the module'
    assert str(s.module_file('workspace', str(app))) == str(pkg/'workspace.py')
    assert str(s.module_file('leela.workspace', str(tmp_path/'x.py'))) == str(pkg/'workspace.py')

def test_an_indexed_package_path_is_remapped_to_this_project_copy(ws, tmp_path, no_index):
    """One Kosha index serves every checkout, so a row can name another project's virtualenv. Same
    package, possibly a different version, and the sandbox cannot open it at all."""
    site = _venv(tmp_path, {'fastcore/aio.py': 'def run_sync(): pass\n'})
    s, elsewhere = ws.search, '/somewhere/else/.venv/lib/python3.12/site-packages/fastcore/aio.py'
    assert s._here(elsewhere) == str(site/'fastcore'/'aio.py')
    assert s._here('/somewhere/else/site-packages/nothing/here.py') == '', 'and one nobody has is no path'
    assert s._here(str(tmp_path/'readme.md')) == str(tmp_path/'readme.md'), 'a project file is already here'
    assert s._here('') == ''

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
