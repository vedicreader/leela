"""The block contract: capability narrowing, laziness, and port conformance."""

import pytest

from leela.core import (APP, CAPABILITIES, Ctx, DebugState, DocStore, MemoryPort, RunState,
                        RuntimePort, SearchPort, connect_all)
from leela.workspace import Workspace


@pytest.fixture(scope='module')
def ws(): return Workspace(roots=[])


@pytest.fixture
def services(ws):
    "What `ide_app` owns and hands to every block: the state that used to be closure variables."
    return dict(docs=DocStore(ws), debug=DebugState(), running=RunState(),
                gate=object(), catalog=[])


# -- capabilities ------------------------------------------------------------

def test_an_unrestricted_ctx_reaches_every_capability(ws, services):
    ctx = Ctx(ws, name='all', **services)
    for c in CAPABILITIES: getattr(ctx, c)
    assert ctx.caps == sorted(CAPABILITIES)


def test_an_application_capability_that_was_never_supplied_does_not_exist(ws):
    "A Ctx built without a doc store has no doc store -- it does not hand back None."
    ctx = Ctx(ws, name='bare')
    with pytest.raises(AttributeError, match='does not provide'): ctx.docs
    assert ctx.fs is ws.fs, 'session capabilities are unaffected'


def test_the_two_ways_to_be_missing_a_capability_report_differently(ws, services):
    """"You did not declare it" and "the app has none" need different fixes, so they read
    differently. Both arrive via `__getattr__`, which only runs once lookup has failed."""
    undeclared = Ctx(ws, name='git', caps=('fs',), **services)
    with pytest.raises(AttributeError, match='without declaring it'): undeclared.memory
    absent = Ctx(ws, name='git', caps=('docs',))
    with pytest.raises(AttributeError, match='does not provide'): absent.docs
    # and a genuine typo is still a plain attribute error
    with pytest.raises(AttributeError, match='no attribute'): undeclared.nonsense


def test_supplying_an_unknown_application_capability_is_rejected(ws):
    with pytest.raises(TypeError, match='unknown application capabilities'):
        Ctx(ws, nonsense=1)


def test_eager_capabilities_are_the_same_objects_as_the_workspaces(ws):
    "Narrowing is about access, not indirection: `ctx.fs` must *be* `ws.fs`."
    ctx = Ctx(ws)
    assert ctx.fs is ws.fs and ctx.pool is ws.pool and ctx.memory is ws.memory


def test_a_narrowed_ctx_refuses_undeclared_eager_capabilities(ws):
    ctx = Ctx(ws, name='git', caps=('fs', 'journal'))
    assert ctx.fs is ws.fs and ctx.journal is ws.journal
    with pytest.raises(AttributeError): ctx.memory
    with pytest.raises(AttributeError): ctx.pool


def test_a_narrowed_ctx_refuses_undeclared_lazy_capabilities_by_name(ws):
    "The error has to name the block and the capability, or it is unactionable at runtime."
    ctx = Ctx(ws, name='git', caps=('fs',))
    with pytest.raises(AttributeError, match="'git'.*'ai'"): ctx.ai


def test_narrow_rejects_a_capability_that_does_not_exist(ws):
    with pytest.raises(ValueError, match='unknown capabilities'):
        Ctx(ws).narrow('fs', 'telepathy')


def test_session_state_stays_shared_rather_than_injected(ws):
    "Tabs are workspace state, not a capability -- blocks read them through `session`."
    ctx = Ctx(ws, caps=('fs',))
    assert ctx.session is ws
    assert 'tabs' not in CAPABILITIES


# -- laziness ----------------------------------------------------------------

def test_building_a_ctx_does_not_construct_the_assistant(ws):
    """The reason `ai` is not an eager slot.

    `Workspace.ai` builds an `Assistant` and resolves a model. Binding it at connect time
    would pay that cost for every workspace at startup, including one whose user never
    opens the agent pane.
    """
    fresh = Workspace(roots=[])
    Ctx(fresh, name='agent')
    assert fresh._ai is None, 'constructing a Ctx eagerly built the Assistant'
    assert fresh._completer is None


def test_lazy_capabilities_read_through_to_current_session_state(ws):
    "`tab` must not be captured at construction; it changes as tabs open and close."
    ctx = Ctx(ws)
    assert ctx.tab is ws.tab
    ws.new_scratch()
    assert ctx.tab is ws.tab and ctx.tab is not None


# -- wiring ------------------------------------------------------------------

class _FakeApp:
    def __init__(self): self.registered = []
    def route(self, path, **kw):
        def deco(fn): self.registered.append((self._who, path)); return fn
        return deco


def _mkblock(name, caps, paths, seen):
    import types
    m = types.ModuleType(f'leela.blocks.{name}.app')
    m.CAPS = caps
    def connect(app, ctx, _n=name, _p=paths):
        seen.append((_n, ctx.name, tuple(ctx.caps)))
        app._who = _n
        for path in _p: app.route(path)(lambda: None)
    m.connect = connect
    return m


def test_connect_all_wires_blocks_in_order_with_narrowed_ctxs(ws):
    seen, app = [], _FakeApp()
    blocks = [_mkblock('git', ('fs', 'journal'), ['/git/info'], seen),
              _mkblock('memory', ('memory',), ['/memory/info', '/memory/search'], seen)]
    receipts = connect_all(app, ws, blocks)

    assert [b.name for b in receipts] == ['git', 'memory']
    assert [b.order for b in receipts] == [0, 1]
    # each block saw only its own capabilities, named after its folder
    assert seen == [('git', 'git', ('fs', 'journal')), ('memory', 'memory', ('memory',))]
    assert app.registered == [('git', '/git/info'), ('memory', '/memory/info'),
                              ('memory', '/memory/search')]


def test_a_block_declaring_an_unknown_capability_fails_at_connect(ws):
    seen = []
    bad = _mkblock('nonsense', ('fs', 'nope'), [], seen)
    with pytest.raises(ValueError, match='unknown capabilities'):
        connect_all(_FakeApp(), ws, [bad])


def test_a_block_without_caps_is_unrestricted_so_migration_can_be_incremental(ws):
    "Un-migrated blocks must keep working, or the extraction has to land in one commit."
    import types
    seen = []
    m = types.ModuleType('leela.blocks.legacy.app')
    def connect(app, ctx): seen.append(ctx.caps); ctx.memory; ctx.ai
    m.connect = connect
    connect_all(_FakeApp(), ws, [m])
    assert seen == [sorted(CAPABILITIES)]


# -- session services --------------------------------------------------------

def test_narrowing_covers_application_capabilities_too(ws, services):
    ctx = Ctx(ws, name='nb', caps=('docs', 'fs'), **services)
    assert ctx.docs is services['docs'] and ctx.fs is ws.fs
    with pytest.raises(AttributeError): ctx.debug
    with pytest.raises(AttributeError): ctx.gate


def test_narrow_carries_the_application_services_through(ws, services):
    "`narrow` must not silently drop the doc store the parent was built with."
    child = Ctx(ws, name='p', **services).narrow('docs', 'running')
    assert child.docs is services['docs'] and child.running is services['running']


def test_docstore_resolves_a_request_to_the_tab_that_submitted_it(ws):
    "`owner` survives a tab switch mid-run, which is the whole reason it takes a ref."
    from leela.nb import Notebook
    store = DocStore(ws)
    tab = ws.new_scratch()
    key = store.key(tab)
    store.docs[key] = Notebook()
    found, nb, lock = store.owner(key)
    assert found is tab and nb is store.docs[key] and lock is not None
    # the same kernel hands back the same lock, so submission order is preserved
    assert store.owner(key)[2] is lock


def test_docstore_refuses_a_ref_that_is_not_a_notebook(tmp_path):
    "A run request naming a `.py` tab gets nothing, rather than a half-built answer."
    p = tmp_path/'x.py'; p.write_text('x = 1\n')
    local = Workspace(roots=[tmp_path])
    local.open(str(p))
    assert DocStore(local).owner(str(p)) == (None, None, None)


def test_docstore_forget_drops_every_kind_of_per_tab_state(ws):
    store = DocStore(ws)
    store.docs['k'], store.buffers['k'], store.bases['k'] = 1, 'text', 'disk'
    store.forget('k')
    assert 'k' not in store.docs and 'k' not in store.buffers and 'k' not in store.bases
    store.forget('never-opened')      # must not raise


def test_runstate_keeps_stop_aimed_at_the_cell_that_started_the_work():
    r = RunState()
    r.start('nb-a', 'c1', 'runtime-a', 'task-a')
    r.start('nb-b', 'c1', 'runtime-b', 'task-b')
    # same cell id in two notebooks must not collide
    assert r.get('nb-a', 'c1') == ('runtime-a', 'task-a')
    assert r.get('nb-b', 'c1') == ('runtime-b', 'task-b')
    assert r.running_in('nb-a') == ['c1']
    r.finish('nb-a', 'c1')
    assert r.get('nb-a', 'c1') == (None, None) and r.running_in('nb-a') == []


def test_debugstate_clears_the_notebook_and_script_sessions_separately():
    d = DebugState()
    assert not d.paused and d.cell_sources == {}
    d.kernel, d.origin_path, d.cell_id = object(), 'a.py', 'c1'
    d.direct_session, d.direct_name = object(), 'script'
    assert d.paused
    d.clear()
    assert not d.paused and d.direct_session is not None, 'clearing one must not clear the other'
    d.clear_direct()
    assert d.direct_session is None and d.direct_name == ''


# -- ports -------------------------------------------------------------------

def test_the_current_implementations_conform_to_their_ports(ws):
    "The Protocols are extracted from these classes; drift between them is a bug in the port."
    assert isinstance(ws.memory, MemoryPort)
    assert isinstance(ws.search, SearchPort)


def test_the_agent_backend_conforms_to_the_runtime_port():
    """The contract ramabana has to meet, asserted against the implementation that defines it.

    Checked against the class rather than an instance: building a real `Backend` resolves a
    `ModelSpec` and opens a chat session. The one non-method member, `spec`, is set in
    `__init__`, so it is verified through the signature instead.
    """
    import inspect

    from leela.agent.runtime import Backend
    missing = sorted(m for m in RuntimePort.__protocol_attrs__
                     if m != 'spec' and not hasattr(Backend, m))
    assert not missing, f'Backend no longer satisfies RuntimePort: {missing}'
    assert 'spec' in inspect.signature(Backend.__init__).parameters
    # the three the port declares as attributes really are properties, not methods
    for p in ('ready', 'busy', 'hist'): assert isinstance(getattr(Backend, p), property)
