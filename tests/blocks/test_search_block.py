"Search block: Kosha/litesearch façade over a workspace folder."

import pytest



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
    """A name the project only imports is defined in site-packages, which the project walk skips on purpose."""
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


def test_a_star_import_names_the_package_a_name_comes_from(ws, tmp_path, no_index):
    "`L` resolved to python-fasthtml's when the file had `from fastcore.utils import *`: the shorter path won."
    _venv(tmp_path, {'fastcore/basics.py': 'class L:\n    pass\n', 'fasthtml/core.py': 'class L:\n    pass\n'})
    (tmp_path/'mine.py').write_text('from fastcore.utils import *\nL()\n')
    s = ws.search
    assert s.star_packages(str(tmp_path/'mine.py')) == ['fastcore']
    assert s.env_definitions('L', path=str(tmp_path/'mine.py'))[0].package == 'fastcore'
    assert s.env_definitions('L')[0].package == 'fasthtml', 'with no import to go on, the old order stands'

def test_an_indexed_top_level_definition_beats_a_method_of_the_same_name(ws, tmp_path, monkeypatch):
    "Kosha indexes methods by name too, so fasthtml's `PathFT.L(self, x, y)` came before fastcore's `class L`."
    import json
    from types import SimpleNamespace
    from leela.blocks.search.search import Search
    site = _venv(tmp_path, {'fastcore/foundation.py': 'class L:\n    pass\n',
                            'fasthtml/svg.py': 'class PathFT:\n    def L(self, x, y): pass\n'})
    row = lambda pkg, rel, mn, ln: dict(content='L', package=pkg,
        metadata=json.dumps(dict(path=str(site/rel), mod_name=mn, lineno=ln)))
    rows = [row('python-fasthtml', 'fasthtml/svg.py', 'fasthtml.svg.PathFT.L', 2),
            row('fastcore', 'fastcore/foundation.py', 'fastcore.foundation.L', 1)]
    k = SimpleNamespace(env_st=SimpleNamespace(rows_where=lambda *a, **kw: rows))
    monkeypatch.setattr(Search, '_kosha', lambda self, path=None: k)
    hits = ws.search.env_definitions('L')
    assert [(h.package, h.line, h.score) for h in hits] == [('fastcore', 1, 0.0), ('python-fasthtml', 2, 4.0)]

def test_a_notebook_import_picks_the_installed_package_over_a_source_checkout(ws, tmp_path, monkeypatch):
    "In karma's `session1.ipynb`, `Index` jumped to usearch: the cells' list-of-lines sources were read as one `str(list)`, and litesearch's row named a source checkout, so it had no module and ranked as a method."
    import json
    from types import SimpleNamespace
    from leela.blocks.search.search import Search
    site = _venv(tmp_path, {'litesearch/api.py': '"doc"\nimport os\nclass Index:\n    pass\n',
                            'usearch/index.py': 'class Index:\n    pass\n'})
    src = tmp_path/'elsewhere'/'litesearch'/'litesearch'/'api.py'; src.parent.mkdir(parents=True); src.write_text('\n'*18 + 'class Index: pass\n')
    nb = tmp_path/'session1.ipynb'
    nb.write_text(json.dumps({'nbformat': 4, 'nbformat_minor': 5, 'metadata': {}, 'cells': [
        {'cell_type': 'code', 'id': 'a', 'metadata': {}, 'outputs': [], 'execution_count': None, 'source': ['%time 1\n']},
        {'cell_type': 'code', 'id': 'b', 'metadata': {}, 'outputs': [], 'execution_count': None,
         'source': ['import os\n', 'from litesearch import Index\n']}]}))
    row = lambda pkg, p, mn, ln: dict(content='class Index', package=pkg, metadata=json.dumps(dict(path=str(p), mod_name=mn, lineno=ln)))
    rows = [row('usearch', site/'usearch'/'index.py', 'usearch.index.Index', 1), row('litesearch', src, 'litesearch.api.Index', 19)]
    k = SimpleNamespace(env_st=SimpleNamespace(rows_where=lambda *a, **kw: rows))
    monkeypatch.setattr(Search, '_kosha', lambda self, path=None: k)
    s = ws.search
    assert s.absolute_source('Index', str(nb)) == 'litesearch', 'a %magic cell costs only its own imports'
    kind, out = s.declaration_or_usages('Index', str(nb), 2)
    assert (out[0].path, out[0].line, out[0].module, out[0].score) == (str(site/'litesearch'/'api.py'), 3, 'litesearch.api', 0.0)

def test_an_index_miss_scans_only_the_packages_the_file_names(ws, tmp_path, monkeypatch):
    "A name nothing defines cost 2.7 s here: ripgrep over all of site-packages after the index had answered."
    from types import SimpleNamespace
    from leela.blocks.search.search import Search
    site = _venv(tmp_path, {'fastcore/basics.py': 'def unindexed(): pass\n', 'rich/x.py': 'def unindexed(): pass\n'})
    k = SimpleNamespace(env_st=SimpleNamespace(rows_where=lambda *a, **kw: []))
    monkeypatch.setattr(Search, '_kosha', lambda self, path=None: k)
    scanned, real = [], Search._rg
    monkeypatch.setattr(Search, '_rg', lambda self, *a, roots=None, **kw: scanned.append(roots) or real(self, *a, roots=roots, **kw))
    (tmp_path/'none.py').write_text('x = 1\n'); (tmp_path/'use.py').write_text('from fastcore.basics import unindexed\n')
    assert ws.search.env_definitions('unindexed', path=str(tmp_path/'none.py')) == [] and scanned == []
    hits = ws.search.env_definitions('unindexed', path=str(tmp_path/'use.py'))
    assert [(h.package, h.module) for h in hits] == [('fastcore', 'fastcore.basics')]
    assert [str(r) for r in scanned[0]] == [str(site/'fastcore')]

def test_an_imported_name_beats_a_project_definition_of_the_same_name(ws, tmp_path, no_index):
    "The file imports `store_attr` from fastcore, so the project's own `store_attr` is not the one clicked."
    _venv(tmp_path, {'fastcore/basics.py': 'def store_attr(names=None):\n    pass\n'})
    (tmp_path/'helpers.py').write_text('def store_attr():\n    pass\n')
    (tmp_path/'use.py').write_text('from fastcore.basics import (\n    store_attr)\nstore_attr()\n')
    kind, out = ws.search.declaration_or_usages('store_attr', str(tmp_path/'use.py'), 3)
    assert kind == 'definition' and out[0].package == 'fastcore' and out[0].path.endswith('fastcore/basics.py')
    (tmp_path/'other.py').write_text('store_attr()\n')
    kind, out = ws.search.declaration_or_usages('store_attr', str(tmp_path/'other.py'), 1)
    assert out[0].path.endswith('helpers.py'), 'a file that imports nothing still gets the project one'

def test_a_submodule_imported_by_name_is_the_module(ws, tmp_path, no_index):
    "`from fastcore import test` binds a module, whatever `def test` another package has."
    site = _venv(tmp_path, {'fastcore/__init__.py': '', 'fastcore/test.py': 'def test_eq(a, b): pass\n',
                            'rich/style.py': 'def test():\n    pass\n'})
    (tmp_path/'use.py').write_text('from fastcore import test\n')
    kind, out = ws.search.declaration_or_usages('test', str(tmp_path/'use.py'), 1)
    assert kind == 'definition' and out[0].path == str(site/'fastcore'/'test.py')

def test_a_submodule_the_package_rebinds_to_its_function_is_the_function(ws, tmp_path, no_index):
    "`from fossick import search`: `__init__` does `from .search import *`, so Python binds `fossick.search.search`, not the module."
    site = _venv(tmp_path, {'pkg/__init__.py': 'from .search import *\n', 'pkg/search.py': '"doc"\n\n\ndef search(q): pass\n',
                            'pkg/cli.py': 'def search(): pass\n'})
    (tmp_path/'use.py').write_text('from pkg import search\nsearch("x")\n')
    s = ws.search
    assert s.reexported_from('pkg', 'search', str(tmp_path/'use.py')) == 'pkg.search'
    assert s.reexported_from('pkg', 'cli', str(tmp_path/'use.py')) == ''
    kind, out = s.declaration_or_usages('search', str(tmp_path/'use.py'), 2)
    assert kind == 'definition' and (out[0].path, out[0].line) == (str(site/'pkg'/'search.py'), 4)
    assert out[1:] == [] or out[1].path.endswith('cli.py')

def test_the_index_is_ranked_before_it_is_cut(ws, tmp_path, monkeypatch):
    "Twelve rows of other packages came back first, so the package the file imported never reached the ranking."
    import json
    from types import SimpleNamespace
    from leela.blocks.search.search import Search
    site = _venv(tmp_path, {'right/mod.py': 'def X(): pass\n', 'other/mod.py': 'def X(): pass\n'})
    row = lambda pkg: dict(content='def X', package=pkg, metadata=json.dumps(dict(path=str(site/pkg/'mod.py'), mod_name=f'{pkg}.mod.X', lineno=1)))
    rows = [row('other') for _ in range(30)] + [row('right')]
    k = SimpleNamespace(env_st=SimpleNamespace(rows_where=lambda *a, limit=None, **kw: rows[:limit]))
    monkeypatch.setattr(Search, '_kosha', lambda self, path=None: k)
    (tmp_path/'use.py').write_text('from right.mod import X\n')
    assert ws.search.env_symbols('X', path=str(tmp_path/'use.py'))[0].package == 'right'


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


def test_an_indexed_package_path_is_remapped_to_this_project_copy(ws, tmp_path, no_index):
    """One Kosha index serves every checkout, so a row can name another project's virtualenv."""
    site = _venv(tmp_path, {'fastcore/aio.py': 'def run_sync(): pass\n'})
    s, elsewhere = ws.search, '/somewhere/else/.venv/lib/python3.12/site-packages/fastcore/aio.py'
    assert s._here(elsewhere) == str(site/'fastcore'/'aio.py')
    assert s._here('/somewhere/else/site-packages/nothing/here.py') == '', 'and one nobody has is no path'
    assert s._here(str(tmp_path/'readme.md')) == str(tmp_path/'readme.md'), 'a project file is already here'
    assert s._here('') == ''


def _client(ws):
    from starlette.testclient import TestClient
    from leela.app import ide_app
    return TestClient(ide_app(ws))

def _prefer(values):
    "Write a `search` settings section the way the settings dialog does."
    from leela.blocks.settings.settings import Settings
    Settings(None).save('user', 'search', values)


def test_nothing_is_recorded_when_the_setting_says_not_to(ws):
    from leela.blocks.search.signals import Signals
    _prefer({'telemetry': 'off'})
    with _client(ws) as client:
        out = client.post('/search/events', json={'events': [{'kind': 'query', 'q': 'merge'}],
                                                  'session': {'q': 'merge'}}).json()
    assert out['recorded'] == 0
    assert list(Signals().read()) == []

def test_the_matched_text_is_kept_only_when_the_setting_says_so(ws):
    "A query is a person's search history and a snippet is their code. Off unless asked for."
    from leela.blocks.search.signals import Signals
    _prefer({'telemetry': 'local'})
    with _client(ws) as client:
        client.post('/search/events', json={'events': [
            {'kind': 'open', 'query_id': '1', 'text': 'def secret_key():'}]})
        assert 'text' not in list(Signals().read())[0]
        _prefer({'snippets': True})
        client.post('/search/events', json={'events': [
            {'kind': 'open', 'query_id': '2', 'text': 'def secret_key():'}]})
    assert [r.get('text') for r in Signals().read()] == [None, 'def secret_key():']


