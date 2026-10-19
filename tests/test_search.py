"Search: kosha, the scan fallback, reindexing and navigation."

import threading
from types import SimpleNamespace
from leela.blocks.fs.fs import Sandbox
from leela.blocks.search.search import Hit, Search
import time
import pytest
from leela.blocks.memory.memory import Memory
from fastcore.all import Path

def test_definition_follows_an_import_alias_and_keeps_its_binding_as_fallback(tmp_path):
    target, caller = tmp_path/'target.py', tmp_path/'caller.py'
    target.write_text('class original:\n    pass\n')
    caller.write_text('from target import original as alias\n\nvalue = alias()\n')
    hits = Search(Sandbox([tmp_path]), prefer_kosha=False).definitions('alias', caller)
    assert [(Path(h.path).name, h.line, h.symbol, h.column) for h in hits] == [
        ('target.py', 1, 'original', 6), ('caller.py', 1, 'alias', 31)]


def test_definition_alias_cycles_and_zero_limits_terminate(tmp_path):
    caller = tmp_path/'caller.py'
    caller.write_text('from package import same as same\nfrom package import other as alias\nfrom package import alias as other\n')
    s = Search(Sandbox([tmp_path]), prefer_kosha=False)
    assert [(h.line, h.symbol) for h in s.definitions('same', caller)] == [(1, 'same')]
    assert [(h.line, h.symbol) for h in s.definitions('alias', caller)] == [(3, 'other'), (2, 'alias')]
    assert s.definitions('alias', caller, limit=0) == []


def _repo(root, indexed=True):
    "A checkout on disk, with its own Kosha index when `indexed`."
    (root/'nbs').mkdir(parents=True, exist_ok=True)
    (root/'.git').mkdir(exist_ok=True)
    (root/'mod.py').write_text('def thing(): pass\n')
    if indexed: (root/'.kosha').mkdir(exist_ok=True)
    return root

def test_the_index_read_is_the_one_belonging_to_the_repo_being_worked_in(monkeypatch, tmp_path):
    """The reported failure: `orgs` open as one folder, and every indexed leg read an index at `orgs` that nothing had built, while the index in each repo below it sat unread."""
    orgs = tmp_path/'orgs'; orgs.mkdir()
    a, b = _repo(orgs/'dockeasy'), _repo(orgs/'fossick')
    s = Search(Sandbox([orgs]), prefer_kosha=False)
    assert s.kosha_root(b/'nbs'/'00_core.ipynb') == b, 'the notebook belongs to the repo holding it'
    assert s.kosha_root(a/'mod.py') == a
    s.focus = lambda: b/'nbs'
    assert s.kosha_root() == b, 'and the folder being worked in is what says which, unasked'
    s.focus = lambda: orgs
    assert s.kosha_root() == orgs, 'outside every checkout, the open folder is the answer'


def test_project_scope_is_the_checkout_not_the_folder_of_clones(tmp_path):
    """With `orgs` open as one folder the two scopes named the same thing, and the indexed legs answered from one repo while ripgrep answered from all of them."""
    import subprocess
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.workspace import Workspace
    orgs = tmp_path/'orgs'
    a, b = orgs/'repo-a', orgs/'repo-b'
    for d in (a, b):
        d.mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', str(d)], check=True)
    (a/'one.py').write_text('needle = 1\n')
    (b/'two.py').write_text('needle = 2\n')
    ws = Workspace(roots=[orgs])
    with TestClient(ide_app(ws)) as c:
        ws.open(a/'one.py')
        first = c.get('/search', params={'q': 'needle'}).json()
        assert first['searched'] == [str(a)], 'the checkout the open file is in'
        assert [Path(h['path']).name for h in first['hits']] == ['one.py']
        ws.open(b/'two.py')
        after = c.get('/search', params={'q': 'needle'}).json()
        assert after['searched'] == [str(b)] and [Path(h['path']).name for h in after['hits']] == ['two.py']
        both = c.get('/search', params={'q': 'needle', 'scope': 'workspace'}).json()
        assert sorted(Path(h['path']).name for h in both['hits']) == ['one.py', 'two.py'], 'the widening still widens'
        assert both['searched'] == [str(orgs)]

def a_notebook(path):
    "A saved notebook with a def in one cell and a class with a method in the next."
    from leela.blocks.nb.nb import Cell, Notebook
    Notebook([Cell(source='## Loading', cell_type='markdown', id='m1'),
              Cell(source='import os\n\ndef alpha(x):\n    return x', id='c1'),
              Cell(source='class Beta:\n    def gamma(self):\n        return alpha(1)', id='c2')]).save(path)
    return path

def test_a_notebooks_symbols_are_read_from_its_cells_not_from_its_json(tmp_path):
    """A notebook read as text has no symbols: the line is ` "def f(x): ",`."""
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
    assert legs['ann']['hits'] == [], 'an index holding nothing reports no hits, not a failure'


@pytest.fixture
def vault(tmp_path):
    (tmp_path/'a.md').write_text('# A\n\nalpha\n')
    (tmp_path/'b.md').write_text('# B\n\nbeta\n')
    m = Memory(path=tmp_path/'vault.db', offline=True)
    m.clip([tmp_path/'a.md', tmp_path/'b.md'])
    return m, tmp_path


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


class _FakeConn: pass
class _FakeDb:
    def __init__(self): self.conn = _FakeConn()

class _FakeStore:
    "A store is callable *and* carries methods, the shape that left the symbol leg with neither."
    def __init__(self, owner): self.owner = owner
    def __call__(self, **kw): return self.rows_where()
    def rows_where(self, *a, **kw):
        self.owner.enter()
        return iter([{'content': 'def thing(): pass', 'metadata': '{"name": "thing"}'}])

class _FakeKosha:
    "Counts how many threads are inside a call at once, which is what apsw refuses to allow."
    def __init__(self):
        self.codedb, self.envdb, self.inside, self.clashes = _FakeDb(), _FakeDb(), 0, 0
        self.code_st = self.env_st = _FakeStore(self)
    def enter(self):
        self.inside += 1
        if self.inside > 1: self.clashes += 1
        time.sleep(0.02)
        self.inside -= 1
    def status(self, **kw): return {}
    def context(self, *a, **kw):
        self.enter()
        return []

def _hammer(target, n=4):
    threads = [threading.Thread(target=target) for _ in range(n)]
    for t in threads: t.start()
    for t in threads: t.join()

def test_one_search_handle_is_never_inside_two_threads_at_once():
    """apsw binds a connection to its thread and readers share one handle, so `/search/stream`'s three concurrent legs lost one to `ThreadingViolationError`."""
    from leela.blocks.search.search import _Serial
    bare = _FakeKosha()
    _hammer(lambda: bare.context('q'))
    assert bare.clashes, 'the test cannot see the fault it is about'   # control
    guarded = _FakeKosha()
    k = _Serial(guarded)
    _hammer(lambda: k.context('q'))
    assert guarded.clashes == 0, 'one call at a time, through litesearch\'s own connection lock'
    assert k.status() == {}, 'and a plain result still comes back as itself'

def test_a_store_reached_through_the_handle_keeps_its_methods_and_the_lock():
    """A store is an object that is callable, so wrapping every callable attribute in a function left `code_st` with no `rows_where` at all, and the symbol leg answered with that AttributeError on every search anyone ran."""
    from leela.blocks.search.search import _Serial
    guarded = _FakeKosha()
    k = _Serial(guarded)
    rows = k.code_st.rows_where("json_extract(metadata, '$.name') = ?", ['thing'])
    assert [r['content'] for r in rows] == ['def thing(): pass'], 'the store answers, as a store'
    assert isinstance(rows, list), 'and its lazy rows are drained while the lock is still held'
    _hammer(lambda: k.code_st.rows_where('1', []))
    assert guarded.clashes == 0, 'one reader at a time, as on the handle itself'
    _hammer(lambda: k.code_st(select='path'))
    assert guarded.clashes == 0, 'calling the store itself is guarded too'


def test_serial_kosha_legs_on_worker_threads_load_their_indexes(tmp_path):
    "`Kosha.context` runs its legs on worker threads while `_Serial` holds `db_lock`; on litesearch 0.1.47 and 0.1.48 a leg's first `get_index` waited on that lock forever."
    import numpy as np
    from litesearch import database
    from leela.blocks.search.search import _Serial
    vs = {c: np.eye(4, dtype=np.float16)[i] for i, c in enumerate('ABC')}
    def db(name):
        database(tmp_path/name).get_store('st', hash=True, ann=True).sync([dict(content=c) for c in 'ABC'], emb_fn=lambda ts: [vs[t] for t in ts])
        return database(tmp_path/name)   # a fresh connection: no index loaded, no SQL functions yet
    class Legs:
        def __init__(self): self.codedb, self.envdb = db('code.db'), db('env.db')
        def context(self):
            out = []
            def leg(d): out.append((d.get_index('st').size, len(d.t['st'].vec_search(vs['A'].tobytes(), limit=2))))
            ts = [threading.Thread(target=leg, args=(d,), daemon=True) for d in (self.codedb, self.envdb)]
            for t in ts: t.start()
            for t in ts: t.join(30)
            assert not any(t.is_alive() for t in ts), 'a leg waited on the lock its caller holds'
            return out
    assert _Serial(Legs()).context() == [(3, 2)]*2


def test_a_literal_search_stays_literal_and_a_regex_search_does_not(tmp_path):
    "rgapi has no fixed-strings flag, so a literal pattern is escaped rather than passed through."
    (tmp_path/'a.py').write_text('needle here\n')
    (tmp_path/'b.py').write_text('nee.le there\n')
    s = Search(Sandbox([tmp_path]), prefer_kosha=False)
    literal = {Path(h.path).name for h in s._rg('nee.le', 20)}
    assert literal == {'b.py'}, 'a dot in a literal search is a dot'
    assert {Path(h.path).name for h in s._rg('nee.le', 20, regex=True)} == {'a.py', 'b.py'}


