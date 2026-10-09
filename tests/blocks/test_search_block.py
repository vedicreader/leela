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
    assert out['recorded'] == 0 and 'off' in out['note']
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


