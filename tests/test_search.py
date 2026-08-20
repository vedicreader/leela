"Search: kosha, the scan fallback, reindexing and navigation."

import asyncio, sys, threading
from pathlib import Path
from types import SimpleNamespace
from leela.blocks.fs.fs import Sandbox
from leela.blocks.search.search import Hit, Search
import time
import pytest
from leela.blocks.memory.memory import Memory, _added_epoch, source_kind
import sys
from fastcore.all import Path
ROOT = Path(__file__).resolve().parents[1]

def test_default_search_uses_ripgrep_and_reports_real_lines(tmp_path):
    p = tmp_path / 'sample.py'
    p.write_text('first = 1\nNeedleValue = 2\nlast = 3\n')
    s = Search(Sandbox([tmp_path]), prefer_kosha=False)
    hits = s.search('needlevalue')
    assert s.backend in ('rg', 'scan')
    assert [(h.path, h.line, h.text) for h in hits] == [(str(p), 2, 'NeedleValue = 2')]

def test_definition_and_usage_fallbacks_report_exact_locations(tmp_path):
    p = tmp_path/'sample.py'
    p.write_text('def calculate_total(x):\n    return x\n\nresult = calculate_total(3)\n')
    s = Search(Sandbox([tmp_path]), prefer_kosha=False)
    defs = s.definitions('calculate_total', p)
    uses = s.usages('calculate_total')
    assert [(h.path, h.line) for h in defs] == [(str(p), 1)]
    assert [(h.path, h.line) for h in uses] == [(str(p), 1), (str(p), 4)]

def test_definition_follows_an_import_alias_and_keeps_its_binding_as_fallback(tmp_path):
    target, caller = tmp_path/'target.py', tmp_path/'caller.py'
    target.write_text('class original:\n    pass\n')
    caller.write_text('from target import original as alias\n\nvalue = alias()\n')
    hits = Search(Sandbox([tmp_path]), prefer_kosha=False).definitions('alias', caller)
    assert [(Path(h.path).name, h.line, h.symbol, h.column) for h in hits] == [
        ('target.py', 1, 'original', 6), ('caller.py', 1, 'alias', 31)]

def test_definition_keeps_an_unresolved_import_alias_binding(tmp_path):
    caller = tmp_path/'caller.py'
    caller.write_text('import unavailable_package as alias\n')
    hits = Search(Sandbox([tmp_path]), prefer_kosha=False).definitions('alias', caller)
    assert [(Path(h.path).name, h.line, h.symbol) for h in hits] == [('caller.py', 1, 'alias')]

def test_definition_alias_cycles_and_zero_limits_terminate(tmp_path):
    caller = tmp_path/'caller.py'
    caller.write_text('from package import same as same\nfrom package import other as alias\nfrom package import alias as other\n')
    s = Search(Sandbox([tmp_path]), prefer_kosha=False)
    assert [(h.line, h.symbol) for h in s.definitions('same', caller)] == [(1, 'same')]
    assert [(h.line, h.symbol) for h in s.definitions('alias', caller)] == [(3, 'other'), (2, 'alias')]
    assert s.definitions('alias', caller, limit=0) == []

def test_definition_alias_column_counts_unicode_characters_not_utf8_bytes(tmp_path):
    caller = tmp_path/'caller.py'
    source = 'π = 1; from target import original as alias\n'
    caller.write_text(source)
    hit = Search(Sandbox([tmp_path]), prefer_kosha=False).definitions('alias', caller)[-1]
    assert hit.column == source.index('alias')

def test_kosha_is_bound_to_the_workspace_not_the_packaged_apps_cwd(monkeypatch, tmp_path):
    seen = []
    class FakeKosha:
        def __init__(self, **kwargs): seen.append(kwargs)
        def status(self, **kwargs): seen.append(kwargs); return {}
    monkeypatch.setitem(sys.modules, 'kosha', SimpleNamespace(Kosha=FakeKosha))
    s = Search(Sandbox([tmp_path]))
    assert s._kosha() is not None
    assert seen[0]['dir'] == tmp_path.resolve()
    assert seen[0]['install_skill'] is False
    assert seen[0]['busy_timeout'] == 30000
    assert 'xdg_dir' not in seen[0]
    assert seen[1] == {'pyproject': False}

def test_kosha_sync_has_fastcore_thread_and_awaitable_surfaces(monkeypatch, tmp_path):
    s = Search(Sandbox([tmp_path]), prefer_kosha=False)
    main, seen = threading.get_ident(), []
    monkeypatch.setattr(s, '_sync', lambda *a: seen.append(threading.get_ident()) or {'ok': True})
    worker = s.sync()
    worker.join(timeout=2)
    assert worker.result == {'ok': True} and seen[-1] != main
    assert asyncio.run(s.async_sync()) == {'ok': True}
    assert seen[-1] != main

def test_kosha_sync_indexes_notebook_cells_through_the_normal_repo_pipeline(monkeypatch, tmp_path):
    import json
    notebook = tmp_path/'routing.ipynb'
    notebook.write_text(json.dumps({'nbformat': 4, 'nbformat_minor': 5, 'metadata': {}, 'cells': [
        {'id': 'route-test', 'cell_type': 'code', 'metadata': {}, 'execution_count': None,
         'outputs': [], 'source': ['assert Routing().spec("turn")\n']},
    ]}))
    seen = []
    class Graph:
        db = None
        def sync(self, **kw): seen.append(('graph', kw))
    class Writer:
        root = tmp_path; graph = Graph(); codedb = envdb = None
        def update_repo(self, **kw): seen.append(('repo', kw))
        def status(self, **kw): return {'files': 1}
    s = Search(Sandbox([tmp_path]))
    monkeypatch.setattr(s, '_make_kosha', lambda: Writer())
    result = s._sync(notebooks=True, graph=True)
    repo = next(data for kind, data in seen if kind == 'repo')
    assert '.ipynb' in repo['exts']
    assert result['ok'] and result['notebook_cells'] == 1


def test_kosha_sync_is_serial(monkeypatch, tmp_path):
    seen = {}
    class Writer:
        root = tmp_path
        def sync(self, **kwargs): seen.update(kwargs)
        def status(self, **kwargs): return {}
    s = Search(Sandbox([tmp_path]))
    monkeypatch.setattr(s, '_make_kosha', lambda: Writer())
    assert s._sync(notebooks=False, graph=False)['ok']
    assert 'in_parallel' not in seen

def test_search_keeps_reading_while_the_separate_writer_syncs(monkeypatch,tmp_path):
    import time
    started,release=threading.Event(),threading.Event()
    current=tmp_path/'core.py'; current.write_text('def live(): pass\n')
    class Reader:
        def context(self,*a,**kw): return [{'content':'def live(): pass','metadata':{'path':str(current),'lineno':1}}]
    class DB:
        def close(self): pass
    class Writer:
        root=tmp_path; codedb=DB()
        def sync(self,**kw): started.set(); release.wait(2)
        def status(self,**kw): return {}
    s=Search(Sandbox([tmp_path])); s._k=Reader(); s._k_tried=True
    monkeypatch.setattr(s,'_make_kosha',lambda:Writer())
    worker=s.sync(notebooks=False,graph=False)
    assert started.wait(1)
    t=time.perf_counter(); hits=s.agent_search('live'); dt=time.perf_counter()-t
    release.set(); worker.join(2)
    assert hits and dt<.2

def test_agent_search_uses_kosha_semantics_and_drops_stale_paths(monkeypatch, tmp_path):
    current = tmp_path/'core.py'; current.write_text('def code_clusters(): pass\n')
    stale = tmp_path/'moved.py'
    seen = []
    class FakeKosha:
        def context(self, q, **kwargs):
            seen.append((q, kwargs))
            return [
                {'content': 'def old(): pass', 'metadata': {'path': str(stale), 'lineno': 1}},
                {'content': 'def code_clusters(): pass',
                 'metadata': {'path': str(current), 'lineno': 1, 'mod_name': 'core.code_clusters'}},
            ]
    s = Search(Sandbox([tmp_path])); s._k = FakeKosha(); s._k_tried = True
    hits = s.agent_search('change the clustering method')
    assert [h.path for h in hits] == [str(current)]
    assert seen == [('change the clustering method', {'graph': True, 'env': True, 'limit': 20})]
    assert s.backend == 'kosha' and 'existing paths only' in s.note

def test_agent_search_falls_back_to_current_files_when_kosha_has_no_live_hit(monkeypatch, tmp_path):
    p = tmp_path/'core.py'; p.write_text('code_clusters = 1\n')
    s = Search(Sandbox([tmp_path])); s._k = SimpleNamespace(context=lambda *a, **k: []); s._k_tried = True
    hits = s.agent_search('code_clusters')
    assert [(h.path, h.line) for h in hits] == [(str(p), 1)]
    assert s.backend in ('rg', 'scan')

def test_context_mode_combines_repo_and_environment_rows(monkeypatch, tmp_path):
    local = tmp_path/'local.py'; local.write_text('def local_symbol(): pass\n')
    class FakeKosha:
        root = tmp_path
        def context(self, *a, **kw):
            assert kw['graph'] and kw['env']
            return [
                {'content': 'def local_symbol(): pass', 'metadata': {'path': str(local), 'lineno': 1,
                 'mod_name': 'project.local_symbol'}, 'callers': ['project.caller']},
                {'content': 'def package_symbol(): pass', 'metadata': {'path': '/venv/pkg/api.py', 'lineno': 8,
                 'mod_name': 'pkg.api.package_symbol', 'package': 'pkg'}},
            ]
    s = Search(Sandbox([tmp_path])); s._k = FakeKosha(); s._k_tried = True
    hits = s.search('symbol implementation', mode='context')
    assert [h.kind for h in hits] == ['context', 'env-context']
    assert hits[0].callers == ['project.caller'] and hits[1].package == 'pkg'
    assert '1 repo + 1 environment' in s.note

def test_repo_and_environment_modes_target_their_kosha_stores(monkeypatch, tmp_path):
    local = tmp_path/'local.py'; local.write_text('pass\n')
    called = []
    class FakeKosha:
        root = tmp_path
        def repo_context(self, q, **kw):
            called.append('repo'); return [{'content': 'repo body', 'path': str(local), 'metadata': {'path': str(local)}}]
        def env_context(self, q, **kw):
            called.append('env'); return [{'content': 'env body', 'package': 'fastcore',
                                            'metadata': {'path': '/site/fastcore/xtras.py', 'package': 'fastcore'}}]
    s = Search(Sandbox([tmp_path])); s._k = FakeKosha(); s._k_tried = True
    assert s.search('body', mode='repo')[0].kind == 'repo-context'
    assert s.search('body', mode='env')[0].kind == 'env-context'
    assert called == ['repo', 'env']

def test_package_public_api_is_exposed_through_kosha(tmp_path):
    class FakeKosha:
        def public_api(self, package):
            assert package == 'fastcore'
            return [{'mod_name': 'fastcore.basics.store_attr', 'docstring': 'Store arguments as attributes'}]
    s = Search(Sandbox([tmp_path])); s._k = FakeKosha(); s._k_tried = True
    assert s.package_api('fastcore')[0]['mod_name'] == 'fastcore.basics.store_attr'

def test_all_mode_merges_every_backend_and_ranks_exact_symbols_first(monkeypatch, tmp_path):
    path = str(tmp_path/'engine.py')
    s = Search(Sandbox([tmp_path]))
    monkeypatch.setattr(s, '_rg', lambda *a, **k: [Hit(path, 20, 'engine = RuntimeEngine()', kind='rg')])
    monkeypatch.setattr(s, '_symbols', lambda *a, **k: [Hit(path, 5, 'class RuntimeEngine: pass',
                                                             kind='symbol', symbol='RuntimeEngine')])
    monkeypatch.setattr(s, '_fts', lambda *a, **k: [Hit(path, 20, 'engine = RuntimeEngine()', kind='fts')])
    monkeypatch.setattr(s, '_ann', lambda *a, **k: [Hit(path, 40, 'runtime machinery', kind='ann')])
    hits = s.search('RuntimeEngine', mode='all')
    assert [(h.line, h.kind) for h in hits] == [(5, 'symbol'), (20, 'rg'), (40, 'ann')]
    assert hits[1].sources == ['rg', 'fts']
    assert s.backend == 'all' and all(name in s.note for name in ('rg', 'symbols', 'fts', 'ann'))

def test_all_mode_finds_file_names_without_matching_their_contents(tmp_path):
    wanted = tmp_path/'billing_report.py'
    wanted.write_text('total = 1\n')
    (tmp_path/'billing_notes.md').write_text('nothing relevant\n')
    hits = Search(Sandbox([tmp_path]), prefer_kosha=False).search('billing', mode='all')
    files = [h for h in hits if h.kind == 'file']
    assert [(Path(h.path).name, h.line, h.sources) for h in files] == [
        ('billing_notes.md', 1, ['files']), ('billing_report.py', 1, ['files'])]
    py = Search(Sandbox([tmp_path]), prefer_kosha=False).search('billing', mode='all', exts=['py'])
    assert [Path(h.path).name for h in py if h.kind == 'file'] == ['billing_report.py']

def test_search_modes_are_explicit_not_inferred_from_the_query(monkeypatch, tmp_path):
    s = Search(Sandbox([tmp_path]))
    called = []
    monkeypatch.setattr(s, '_rg', lambda q, limit, regex=False, exts=(), roots=None:
                        called.append('rg') or [])
    monkeypatch.setattr(s, '_fts', lambda q, limit: called.append('fts') or [Hit('/x', 1, 'x')])
    monkeypatch.setattr(s, '_ann', lambda q, limit: called.append('ann') or [Hit('/x', 1, 'x')])
    s.search('a long semantic-looking question')
    s.search('literal name', mode='fts')
    s.search('conceptual equivalent', mode='ann')
    monkeypatch.setattr(s, '_symbols', lambda q, limit: called.append('symbols') or [Hit('/x', 1, 'x')])
    s.search('SomeClass', mode='symbols')
    assert called == ['rg', 'fts', 'ann', 'symbols']

def test_an_extension_filter_narrows_every_backend_the_same_way(tmp_path):
    '"Only .py" has to mean the same thing whichever backend answers.'
    (tmp_path/'a.py').write_text('needle = 1\n')
    (tmp_path/'b.js').write_text('const needle = 1\n')
    (tmp_path/'c.md').write_text('needle\n')
    s = Search(Sandbox([tmp_path]), prefer_kosha=False)
    assert {Path(h.path).name for h in s.search('needle')} == {'a.py', 'b.js', 'c.md'}
    assert {Path(h.path).name for h in s.search('needle', exts='py')} == {'a.py'}
    assert {Path(h.path).name for h in s.search('needle', exts='.PY')} == {'a.py'}
    assert {Path(h.path).name for h in s.search('needle', exts='py,js')} == {'a.py', 'b.js'}
    assert {Path(h.path).name for h in s.search('needle', exts=['*.md'])} == {'c.md'}
    assert Search.clean_exts('py, .ts ,,*') == {'.py', '.ts'}, 'junk is dropped, not guessed at'
    hits = s._keep([Hit(str(tmp_path/'a.py'), 1, 'x'), Hit(str(tmp_path/'b.js'), 1, 'x')], exts='py')
    assert [Path(h.path).name for h in hits] == ['a.py']

def test_a_search_can_be_confined_to_one_checkout(tmp_path):
    "Two folders open, one question: matches from the repository you are not in are noise."
    a, b = tmp_path/'repo-a', tmp_path/'repo-b'
    for d in (a, b): d.mkdir()
    (a/'one.py').write_text('needle = 1\n')
    (b/'two.py').write_text('needle = 2\n')
    s = Search(Sandbox([a, b]), prefer_kosha=False)
    assert len(s.search('needle')) == 2, 'both, by default, at this level'
    assert [Path(h.path).name for h in s.search('needle', roots=[a])] == ['one.py']
    assert [Path(h.path).name for h in s.search('needle', roots=[b])] == ['two.py']
    hits = s._keep([Hit(str(a/'one.py'), 1, 'x'), Hit(str(b/'two.py'), 1, 'x')], roots=[a])
    assert [Path(h.path).name for h in hits] == ['one.py']

def test_the_search_route_follows_the_chosen_folder_and_never_takes_a_root(tmp_path):
    "`scope` is a word, not a path."
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.workspace import Workspace
    a, b = tmp_path/'repo-a', tmp_path/'repo-b'
    for d in (a, b): d.mkdir()
    (a/'one.py').write_text('needle = 1\n')
    (b/'two.py').write_text('needle = 2\n')
    ws = Workspace(roots=[a, b])
    with TestClient(ide_app(ws)) as c:
        first = c.get('/search', params={'q': 'needle'}).json()
        assert first['searched'] == [str(a)] and first['scope'] == 'project'
        assert [Path(h['path']).name for h in first['hits']] == ['one.py']
        ws.activate_root(b)
        after = c.get('/search', params={'q': 'needle'}).json()
        assert after['searched'] == [str(b)], 'the search follows the chosen folder'
        assert [Path(h['path']).name for h in after['hits']] == ['two.py']
        both = c.get('/search', params={'q': 'needle', 'scope': 'workspace'}).json()
        assert sorted(Path(h['path']).name for h in both['hits']) == ['one.py', 'two.py']
        assert c.get('/search', params={'q': 'x', 'scope': str(tmp_path)}).json()['error']
        filtered = c.get('/search', params={'q': 'needle', 'exts': 'md', 'scope': 'workspace'}).json()
        assert filtered['hits'] == [] and filtered['exts'] == 'md'

def a_notebook(path):
    "A saved notebook with a def in one cell and a class with a method in the next."
    from leela.blocks.nb.nb import Cell, Notebook
    Notebook([Cell(source='## Loading', cell_type='markdown', id='m1'),
              Cell(source='import os\n\ndef alpha(x):\n    return x', id='c1'),
              Cell(source='class Beta:\n    def gamma(self):\n        return alpha(1)', id='c2')]).save(path)
    return path

def test_a_notebooks_symbols_are_read_from_its_cells_not_from_its_json(tmp_path):
    'A notebook read as text has no symbols: the line is ` "def f(x):\n",`.'
    p = a_notebook(tmp_path/'demo.ipynb')
    s = Search(Sandbox([tmp_path]), prefer_kosha=False)
    syms = s.symbols(p)
    assert [(h.symbol, h.cell, h.cell_index, h.cell_line) for h in syms] == [
        ('alpha', 'c1', 1, 3), ('Beta', 'c2', 2, 1), ('gamma', 'c2', 2, 2)]
    assert [h.score for h in syms] == [0.0, 0.0, 4.0], 'indent depth still nests a method'
    assert [h.column for h in syms] == [4, 6, 8]
    lines = p.read_text().splitlines()
    for h in syms: assert h.symbol in lines[h.line - 1], 'the file line is the JSON line holding it'

def test_going_to_a_definition_in_a_notebook_lands_in_the_cell(tmp_path):
    p = a_notebook(tmp_path/'demo.ipynb')
    s = Search(Sandbox([tmp_path]), prefer_kosha=False)
    defs = s.definitions('gamma', p)
    assert [(h.symbol, h.cell, h.cell_line) for h in defs] == [('gamma', 'c2', 2)]
    uses = s.usages('alpha')
    assert [(h.cell, h.cell_index, h.cell_line) for h in uses] == [('c1', 1, 3), ('c2', 2, 3)]
    assert all(h.line > 1 for h in uses), 'the JSON line is still reported alongside'

def test_a_literal_search_in_a_notebook_says_which_cell_it_matched(tmp_path):
    p = a_notebook(tmp_path/'demo.ipynb')
    (tmp_path/'plain.py').write_text('alpha = 1\n')
    s = Search(Sandbox([tmp_path]), prefer_kosha=False)
    hits = {Path(h.path).name: h for h in s.search('alpha')}
    assert hits['demo.ipynb'].cell_index >= 0 and hits['demo.ipynb'].cell_line > 0
    assert (hits['plain.py'].cell, hits['plain.py'].cell_index, hits['plain.py'].cell_line) == ('', -1, 0), \
        'an ordinary file has no cell to name'

def test_an_indexed_notebook_hit_is_placed_by_its_text_when_it_has_no_line(monkeypatch, tmp_path):
    "Kosha chunks a notebook by cell and records no line number, so every notebook row it"
    p = a_notebook(tmp_path/'demo.ipynb')
    rows = [{'content': 'class Beta:\n    def gamma(self):\n        return alpha(1)',
             'metadata': {'path': str(p)}},
            {'content': 'nothing in this notebook', 'metadata': {'path': str(p)}}]
    s = Search(Sandbox([tmp_path]))
    s._k = SimpleNamespace(context=lambda *a, **k: rows,
                           status=lambda **k: {'files': 1, 'new_files': 0, 'stale_files': 0})
    s._k_tried = True
    placed, unplaced = s.agent_search('the Beta class')
    assert (placed.cell, placed.cell_index, placed.cell_line) == ('c2', 2, 1)
    assert placed.line > 1, 'placing it also recovers the JSON line it never had'
    assert (unplaced.cell, unplaced.cell_index, unplaced.cell_line) == ('', -1, 0)

def test_a_notebook_that_cannot_be_parsed_reports_no_symbols_at_all(tmp_path):
    p = tmp_path/'broken.ipynb'
    p.write_text('{"cells": [ this is not JSON')
    s = Search(Sandbox([tmp_path]), prefer_kosha=False)
    assert list(s.symbols(p)) == [], 'no symbol beats a symbol at a guessed line'
    assert [h.cell_line for h in s.usages('cells')] == [0], 'and the hit stays honestly unplaced'

def test_the_outline_route_gives_a_notebook_the_cell_coordinates_it_needs(tmp_path):
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.workspace import Workspace
    p = a_notebook(tmp_path/'demo.ipynb')
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as c:
        rows = c.get('/outline', params={'path': str(p)}).json()['symbols']
    assert [(r['symbol'], r['cell'], r['cell_index'], r['cell_line']) for r in rows] == [
        ('alpha', 'c1', 1, 3), ('Beta', 'c2', 2, 1), ('gamma', 'c2', 2, 2)]

def test_narrowing_the_scope_never_hides_an_installed_package(tmp_path):
    "The reported regression: `merge dict` stopped returning `fastcore.basics.merge`."
    (tmp_path/'x.py').write_text('x = 1\n')
    s = Search(Sandbox([tmp_path]), prefer_kosha=False)
    package = Hit(path='/site-packages/fastcore/basics.py', line=655, text='def merge(*ds):',
                  kind='env-context', symbol='fastcore.basics.merge', package='fastcore')
    mine = Hit(path=str(tmp_path/'x.py'), line=1, text='x = 1', kind='context')
    elsewhere = Hit(path='/somewhere/else/other.py', line=1, text='x = 1', kind='context')
    kept = s._keep([package, mine, elsewhere], roots=[tmp_path])
    assert [h.symbol or h.path for h in kept] == ['fastcore.basics.merge', str(tmp_path/'x.py')]
    assert elsewhere not in kept, 'a repo hit outside the scope is still excluded'
    bare = Hit(path='/site-packages/pkg/api.py', line=1, text='def f(): pass', kind='env-context')
    assert s._keep([bare], roots=[tmp_path]) == [bare]
    assert s._keep([package], exts='ts', roots=[tmp_path]) == []

def test_context_mode_keeps_both_halves_under_a_project_scope(tmp_path):
    "The mode that returns repo *and* environment rows is where the regression actually bit."
    local = tmp_path/'local.py'; local.write_text('def local_symbol(): pass\n')
    class FakeKosha:
        root = tmp_path
        def context(self, *a, **kw):
            return [
                {'content': 'def local_symbol(): pass',
                 'metadata': {'path': str(local), 'lineno': 1, 'mod_name': 'project.local_symbol'}},
                {'content': 'def merge(*ds): ...',
                 'metadata': {'path': '/site/fastcore/basics.py', 'lineno': 655,
                              'mod_name': 'fastcore.basics.merge', 'package': 'fastcore'}},
            ]
    s = Search(Sandbox([tmp_path])); s._k = FakeKosha(); s._k_tried = True
    hits = s.search('merge dict', mode='context', roots=[tmp_path])
    assert [h.kind for h in hits] == ['context', 'env-context']
    assert any(h.symbol == 'fastcore.basics.merge' for h in hits)

def test_a_leg_is_scored_exactly_as_the_batch_answer_scores_it(tmp_path):
    "A streamed hit that ranked differently from the same hit in `all` would make the list"
    p = tmp_path/'core.py'; p.write_text('def merge_dicts(a, b):\n    return a | b\n')
    s = Search(Sandbox([tmp_path]), prefer_kosha=False)
    hits, note = s.leg('rg', 'merge_dicts', 20)
    assert note == '' and [h.line for h in hits] == [1]
    assert hits[0].sources == ['rg']
    from dataclasses import replace
    pristine = replace(hits[0], score=0.0, sources=[])
    assert hits[0].score == s.relevance('rg', pristine, 'merge_dicts') == 120.0
    assert s.relevance('rg', hits[0], 'merge_dicts') == 130.0, 'documented: not idempotent'
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)

def test_an_unavailable_leg_says_so_instead_of_taking_the_others_down(tmp_path):
    "One absent index must not cost the other three their answers."
    s = Search(Sandbox([tmp_path]), prefer_kosha=False)
    hits, note = s.leg('ann', 'anything', 10)
    assert hits == [] and 'unavailable' in note
    def boom(*a, **kw): raise RuntimeError('index is corrupt')
    s._fts = boom
    hits, note = s.leg('fts', 'anything', 10)
    assert hits == [] and 'fts failed' in note and 'corrupt' in note
    assert s.leg('nonsense', 'x', 10)[1].startswith('unknown search leg')

def test_the_streaming_search_reports_each_backend_as_it_finishes(tmp_path):
    "The legs never depended on each other; they were merely written as one loop, so the"
    import json as _json
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.workspace import Workspace
    (tmp_path/'core.py').write_text('def merge_dicts(a, b):\n    return a | b\n')
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as c:
        with c.stream('GET', '/search/stream', params={'q': 'merge_dicts'}) as r:
            assert r.status_code == 200
            events, name = [], ''
            for line in r.iter_lines():
                if line.startswith('event: '): name = line[7:].strip()
                elif line.startswith('data: '): events.append((name, _json.loads(line[6:])))
    kinds = [n for n, _ in events]
    assert kinds[0] == 'start' and kinds[-1] == 'done'
    start = events[0][1]
    assert start['legs'] == list(Search.ALL_LEGS) and start['searched'] == [str(tmp_path)]
    legs = {d['leg']: d for n, d in events if n == 'leg'}
    assert set(legs) == set(Search.ALL_LEGS), 'every leg reports, even the ones with no index'
    assert any(h['line'] == 1 for h in legs['rg']['hits']), 'and rg found the definition'
    assert legs['ann']['hits'] == [] and 'unavailable' in legs['ann']['note']

def test_the_stream_says_so_when_there_is_nothing_to_search_for(tmp_path):
    import json as _json
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.workspace import Workspace
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as c:
        with c.stream('GET', '/search/stream', params={'q': '  '}) as r:
            body = r.read().decode()
    assert 'event: start' in body and 'event: done' in body and 'event: leg' not in body
    assert 'nothing to search for' in body

def test_similar_and_peers_prefer_kosha_primitives_when_present(monkeypatch, tmp_path):
    "Search is an adapter: kosha owns similarity; leela only formats hits."
    path = str(tmp_path/'core.py')
    class FakeKosha:
        def similar(self, p, line=1, limit=15, graph=False):
            assert (p, line, limit, graph) == (path, 3, 5, True)
            return [SimpleNamespace(path=path, lineno=10, mod_name='core.peer',
                                    sig='def peer():', content='def peer():', kind='ann', dist=0.1)]
        def peers(self, p, line=1, limit=25, graph=False, **kw):
            return SimpleNamespace(hits=[SimpleNamespace(path=path, lineno=12, mod_name='core.family',
                                                         sig='def family():', content='def family():',
                                                         kind='usearch', dist=None)],
                                   method='usearch', note='cluster of 4 (usearch)')
        def code_clusters(self, limit=None, min_size=2, **kw):
            return SimpleNamespace(clusters=[SimpleNamespace(centroid=1, size=4, label='family',
                                                             members=[SimpleNamespace(path=path, lineno=12,
                                                                                      mod_name='core.family',
                                                                                      content='def family():')])],
                                   method='usearch', note='1 clusters over 4 vectors (usearch)')
    s = Search(Sandbox([tmp_path])); s._k = FakeKosha(); s._k_tried = True
    sim = s.similar(path, 3, limit=5)
    assert [(h.path, h.line, h.symbol) for h in sim] == [(path, 10, 'core.peer')]
    peer = s.peers(path, 3)
    assert s.backend == 'usearch' and 'cluster of 4' in s.note
    assert peer[0].symbol == 'core.family'
    cs = s.clusters()
    assert cs[0].label == 'family' and cs[0].members[0].path == path

def test_similar_uses_litesearch_ann_neighbors_without_kosha_helpers(monkeypatch, tmp_path):
    path = str(tmp_path/'a.py')
    class Store:
        def ann_neighbors(self, key, limit=15, columns=None, **kw):
            assert key == 7 and limit == 3
            return [{'rowid': 8, 'path': path, 'content': 'def neighbour():\n    pass',
                     'metadata': {'lineno': 4, 'mod_name': 'a.neighbour'}, '_dist': 0.2}]
        def peers(self, key, limit=25, columns=None, **kw):
            return SimpleNamespace(hits=[{'rowid': 9, 'path': path, 'content': 'def cousin():\n    pass',
                                          'metadata': {'lineno': 8, 'mod_name': 'a.cousin'}}],
                                   method='knn', note='index holds 3 vectors; showing nearest neighbours')
        def clusters(self, **kw):
            return SimpleNamespace(clusters=[SimpleNamespace(centroid=1, size=2, label='cousin',
                                                             members=[{'path': path, 'content': 'def cousin():',
                                                                       'metadata': {'lineno': 8, 'mod_name': 'a.cousin'}}])],
                                   method='knn', note='1 clusters over 3 vectors (knn)')
    class FakeKosha:
        code_st = Store()
    s = Search(Sandbox([tmp_path])); s._k = FakeKosha(); s._k_tried = True
    monkeypatch.setattr(s, '_anchor', lambda p, line: (7, s._k.code_st))
    assert s.similar(path, 1, limit=3)[0].symbol == 'a.neighbour'
    assert s.peers(path, 1)[0].symbol == 'a.cousin' and s.backend == 'knn'
    assert s.clusters()[0].label == 'cousin'

@pytest.fixture
def vault(tmp_path):
    (tmp_path/'a.md').write_text('# A\n\nalpha\n')
    (tmp_path/'b.md').write_text('# B\n\nbeta\n')
    m = Memory(path=tmp_path/'vault.db', offline=True)
    m.clip([tmp_path/'a.md', tmp_path/'b.md'])
    return m, tmp_path

def test_a_result_says_what_it_is_and_when_it_arrived():
    from datetime import datetime, timezone
    naive = '2026-08-14 09:43:14'
    assert _added_epoch(naive) == datetime(2026, 8, 14, 9, 43, 14, tzinfo=timezone.utc).timestamp()
    assert _added_epoch(1786664594.0) == 1786664594.0
    assert _added_epoch('not a date') == float('inf')
    assert source_kind('/a/b.md') == 'file'
    assert source_kind('https://example.com/p') == 'url'
    for s in ('memory:ab12', 'pointer:ff01', '', None): assert source_kind(s) == 'synthetic'


def test_an_untouched_vault_is_not_reindexed(vault):
    m, _ = vault
    r = m.reindex_changed()
    assert r['checked'] == 2 and r['reindexed'] == 0

def test_a_changed_file_is_reindexed_once_and_then_settles(vault):
    "Re-clipping advances `added_at`, so a change costs one sweep rather than every sweep."
    m, d = vault
    time.sleep(1.1)
    (d/'a.md').write_text('# A\n\nalpha rewritten\n')
    r = m.reindex_changed()
    assert r['reindexed'] == 1 and [p.split('/')[-1] for p in r['paths']] == ['a.md']
    time.sleep(1.1)
    assert m.reindex_changed()['reindexed'] == 0, 'it must converge, not re-read forever'
    assert len(m.all_documents()) == 2, 're-clipping updates the document, it does not add one'

def test_a_missing_file_is_reported_and_never_forgotten(vault):
    "A vault is a record. An unplugged drive is not a reason to drop what was on it."
    m, d = vault
    (d/'b.md').unlink()
    r = m.reindex_changed()
    assert [p.split('/')[-1] for p in r['missing']] == ['b.md']
    assert len(m.all_documents()) == 2, 'the row survives its file'

def test_documents_that_were_never_files_are_not_walked(vault):
    m, d = vault
    m.clip([d/'a.md'])
    before = m.reindex_changed()['checked']
    assert before == 2, 'only filed documents are candidates'

sys.path.insert(0, str(ROOT/'tools'))
import build_ide_js as builder  # noqa: E402
