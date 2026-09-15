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
    """`fastcore.test` is a module, and nothing declares a module."""
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
    """One Kosha index serves every checkout, so a row can name another project's virtualenv."""
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
    """Kosha carries the package and the line."""
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

def _client(ws):
    from starlette.testclient import TestClient
    from leela.app import ide_app
    return TestClient(ide_app(ws))

def _prefer(values):
    "Write a `search` settings section the way the settings dialog does."
    from leela.blocks.settings.settings import Settings
    Settings(None).save('user', 'search', values)

def test_the_settings_defaults_and_the_scorers_defaults_are_one_set_of_numbers():
    "Two files hold these; a drift between them would tune a ranker nobody is running."
    from leela.blocks.search.search import SETTING_WEIGHTS, Weights
    from leela.blocks.settings.settings import DEFAULT_SETTINGS
    held = DEFAULT_SETTINGS['search']
    assert Weights.load(held) == Weights()
    # Everything else the section holds: what is recorded, and what the dialog was last set to.
    assert set(SETTING_WEIGHTS) == set(held) - {'telemetry', 'snippets', 'lastMode', 'lastScope', 'lastExts'}

def test_a_search_answers_with_the_weights_it_ranked_with(ws):
    "The panel re-ranks locally, so it has to be told what the server just paid."
    _prefer({'legRg': 12.0})
    with _client(ws) as client:
        d = client.get('/search?q=block&mode=rg').json()
    assert d['weights']['legRg'] == 12.0
    assert d['weights']['symbolExact'] == 120.0, 'the rest stay at their defaults'

def test_search_events_are_recorded_and_reduced_to_the_fields_this_version_stores(ws):
    from leela.blocks.search.signals import Signals
    _prefer({'telemetry': 'local'})
    with _client(ws) as client:
        out = client.post('/search/events', json={'events': [
            {'kind': 'query', 'q': 'merge', 'mode': 'all', 'query_id': '1', 'secret': 'no'},
            {'kind': 'open', 'query_id': '1', 'rank': 2, 'sources': ['rg']},
            {'kind': 'invented'}]}).json()
    assert out['ok'] and out['recorded'] == 2, 'a kind nobody declared is dropped, not stored'
    rows = list(Signals().read())
    assert [r['kind'] for r in rows] == ['query', 'open']
    assert 'secret' not in rows[0] and rows[0]['q'] == 'merge' and rows[0]['at'] > 0

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

def test_the_summary_is_the_numbers_a_ranker_is_tuned_from(tmp_path):
    "Where the opened hit sat, which leg found it, and how often nothing was opened at all."
    from leela.blocks.search.signals import Signals
    s = Signals(tmp_path/'events')
    s.record([{'kind': 'query', 'query_id': '1', 'q': 'a', 'mode': 'all'},
              {'kind': 'leg', 'query_id': '1', 'leg': 'rg', 'ms': 20, 'n': 4},
              {'kind': 'impression', 'query_id': '1', 'n': 4},
              {'kind': 'open', 'query_id': '1', 'rank': 1, 'sources': ['rg', 'ann'], 'mode': 'all'},
              {'kind': 'query', 'query_id': '2', 'q': 'b', 'mode': 'all'},
              {'kind': 'impression', 'query_id': '2', 'n': 2},
              {'kind': 'abandon', 'query_id': '2', 'n': 2}])
    d = s.summary()
    assert d['searches'] == 2 and d['opens'] == 1 and d['mrr'] == 0.5
    assert d['success_at'] == {'1': 0.0, '3': 1.0, '10': 1.0}
    assert d['abandon_rate'] == 0.5 and d['open_rate'] == 0.5
    assert d['legs'] == {'ann': {'won': 1}, 'rg': {'found': 4, 'won': 1}}, 'which leg earned the click'
    assert d['leg_ms'] == {'rg': 20} and d['modes']['all'] == {'searches': 2, 'opens': 1}

def test_the_log_is_pruned_to_the_days_it_keeps_and_purged_on_request(ws, tmp_path):
    from leela.blocks.search.signals import Signals
    s = Signals(tmp_path/'events', keep_days=2)
    for day in ('2026-01-01', '2026-01-02', '2026-01-03'):
        s.dir.mkdir(parents=True, exist_ok=True)
        (s.dir/f'{day}.jsonl').write_text('{"kind": "query", "q": "old"}\n')
    s.record([{'kind': 'query', 'q': 'new'}])
    assert len(s.files()) == 2, 'a day is a file, so keeping days is keeping files'
    _prefer({'telemetry': 'local'})
    with _client(ws) as client:
        client.post('/search/events', json={'events': [{'kind': 'query', 'q': 'x'}]})
        assert client.post('/search/signals/purge', json={}).json()['removed'] == 1
        assert client.get('/search/signals').json()['summary']['events'] == 0

def test_a_search_session_is_one_vault_document_not_one_per_keystroke(tmp_path):
    "The vault answers questions about a search; the event log is what is fitted from."
    from leela.blocks.search.signals import Signals
    text = Signals(tmp_path)._document({
        'q': 'merge dicts', 'mode': 'all', 'scope': 'project',
        'shown': [{'rank': 0, 'path': 'a.py', 'line': 3, 'symbol': 'merge', 'sources': ['rg'],
                   'previewed': True, 'opened': True},
                  {'rank': 1, 'path': 'b.py', 'line': 9, 'sources': ['ann'], 'previewed': True},
                  {'rank': 2, 'path': 'c.py', 'line': 1, 'sources': ['fts']}]})
    assert '## Query\n\nmerge dicts' in text and 'mode all · scope project' in text
    opened, rest = text.split('## Opened')[1].split('## Previewed')
    previewed = rest.split('## Shown')[0]
    assert 'a.py:3' in opened and 'b.py' not in opened
    assert 'b.py:9' in previewed and 'a.py' not in previewed, 'opened is not also previewed-only'
    assert 'c.py:1' in text.split('## Shown')[1]

def test_the_vault_write_never_takes_a_search_down_with_it(ws, tmp_path, monkeypatch):
    "A vault that will not open must cost the event log nothing."
    from leela.blocks.search import signals as mod
    from leela.blocks.search.signals import Signals
    def boom(*a, **kw): raise RuntimeError('no encoder here')
    monkeypatch.setattr(mod.Signals, '_document', boom)
    s = Signals(tmp_path/'events')
    assert s.remember({'q': 'merge'}) is None and 'could not write' in s.note
    _prefer({'telemetry': 'vault'})
    with _client(ws) as client:
        out = client.post('/search/events', json={'events': [{'kind': 'query', 'q': 'merge'}],
                                                  'session': {'q': 'merge'}}).json()
    assert out['recorded'] == 1 and out['remembering'] is True
