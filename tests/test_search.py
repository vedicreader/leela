"""Code search is predictable: rg by default, indexed modes only by explicit request."""

import asyncio, sys, threading
from types import SimpleNamespace

from leela.fs import Sandbox
from leela.search import Hit, Search


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
    assert 'xdg_dir' not in seen[0]  # the shared Kosha env.db spans indexed environments
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


def test_search_modes_are_explicit_not_inferred_from_the_query(monkeypatch, tmp_path):
    s = Search(Sandbox([tmp_path]))
    called = []
    monkeypatch.setattr(s, '_rg', lambda q, limit, regex=False: called.append('rg') or [])
    monkeypatch.setattr(s, '_fts', lambda q, limit: called.append('fts') or [Hit('/x', 1, 'x')])
    monkeypatch.setattr(s, '_ann', lambda q, limit: called.append('ann') or [Hit('/x', 1, 'x')])
    s.search('a long semantic-looking question')
    s.search('literal name', mode='fts')
    s.search('conceptual equivalent', mode='ann')
    monkeypatch.setattr(s, '_symbols', lambda q, limit: called.append('symbols') or [Hit('/x', 1, 'x')])
    s.search('SomeClass', mode='symbols')
    assert called == ['rg', 'fts', 'ann', 'symbols']
