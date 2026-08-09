"""The block contract: capability narrowing, laziness, and port conformance."""

import pytest

from leela.core import CAPABILITIES, Ctx, MemoryPort, RuntimePort, SearchPort, connect_all
from leela.workspace import Workspace


@pytest.fixture(scope='module')
def ws(): return Workspace(roots=[])


# -- capabilities ------------------------------------------------------------

def test_an_unrestricted_ctx_reaches_every_capability(ws):
    ctx = Ctx(ws, name='all')
    for c in CAPABILITIES: getattr(ctx, c)
    assert ctx.caps == sorted(CAPABILITIES)


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
