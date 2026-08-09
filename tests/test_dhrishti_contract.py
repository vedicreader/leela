"""The dhrishti API leela actually depends on.

The inspection engine used to be vendored here as `leela.inspect`, and was tested in full by
`tests/test_inspect.py`. It lives in dhrishti again now, where it is tested under nbdev, so
duplicating that suite here would be pure maintenance cost.

What is *not* covered upstream is the seam: leela pins `dhrishti>=0.1.1`, so a future release
could move something leela reaches for and nothing in this repository would notice until the
variable panel went blank at runtime. These tests are that alarm. They assert only the surface
leela consumes -- the names it imports, the shapes it renders, and the two behaviours it relies
on for correctness rather than for display.

Nothing here needs a kernel: the engine reads whatever namespace it is handed, so a plain dict
driven through `NsClient` exercises the same code paths the in-kernel server uses.
"""

import numpy as np
import pandas as pd
import pytest

from dhrishti.core import PROFILES, SORTS, expand, grid_page, value_str, var_info
from dhrishti.runtime import Bridge, NsClient, set_logging
from dhrishti.agent import AgentSession
import dhrishti.serving as ds


# -- the names leela imports ---------------------------------------------------
def test_leela_can_import_everything_it_wires_up():
    """Every dhrishti name leela reaches for, in one place.

    `kernels.py` and `workspace.py` take reg_dir/active; `devserver.py` takes serve/watch/active;
    the kernel bootstrap string calls serve_in_kernel and set_kernel_backend by name, where a
    rename would fail silently inside a kernel rather than at import time here.
    """
    for name in ('reg_dir', 'active', 'serve', 'serve_in_kernel', 'watch', 'set_kernel_backend'):
        assert callable(getattr(ds, name)), name


def test_the_kernel_bootstrap_keywords_still_exist():
    "The bootstrap passes these by keyword; dropping one would be a TypeError inside a kernel."
    from inspect import signature
    params = signature(ds.serve_in_kernel).parameters
    assert {'name', 'port', 'agent', 'token', 'session_dir', 'agent_session_dir'} <= set(params)


def test_the_profiles_and_sorts_the_frontend_offers():
    "web/app.py renders these as the panel's profile and sort pickers."
    assert list(PROFILES) == ['minimal', 'standard', 'full']
    assert {'name', 'recent', 'type', 'size'} <= set(SORTS)


# -- the row shape the panel renders -------------------------------------------
def test_a_row_carries_the_fields_the_panel_draws():
    v = var_info('n', 42, ('n',), 'n')
    assert (v.name, v.type, v.value) == ('n', 'int', '42')
    df = var_info('df', pd.DataFrame({'a': [1, 2], 'b': [3, 4]}), ('df',), 'df')
    assert df.shape == '(2, 2)' and df.is_container


def test_value_str_survives_an_object_that_raises_in_repr():
    "A broken __repr__ is the user's bug, not a reason for the whole panel to go blank."
    class Boom:
        def __repr__(self): raise RuntimeError('nope')
    assert isinstance(value_str(Boom()), str)


def test_expanding_reaches_keys_columns_and_cells():
    ns = {'d': {'a': 1}, 'df': pd.DataFrame({'revenue': [1, 2, 3]}), 'arr': np.arange(6).reshape(2, 3)}
    assert "'a'" in {c.name for c in expand(ns, ('d',))}
    assert 'revenue' in {c.name for c in expand(ns, ('df',))}
    assert grid_page(ns, ('df',))['nrows'] == 3
    assert grid_page(ns, ('arr',))['nrows'] == 2
    assert grid_page(ns, ('d',)) is None


def test_expanding_something_that_is_not_there_does_not_raise():
    "The IDE can ask about a name a cell has since deleted; that must not take the panel down."
    assert expand({'x': 1}, ('nope',)) is not None


def test_the_result_lens_keeps_an_expandable_accessor():
    "leela's result panel expands from `_`; the accessor has to survive the round trip."
    bridge = Bridge(NsClient({'_': [{'path': '/tmp/one.py'}]}))
    result = bridge.result()
    assert result.accessor == ('_',) and result.is_container
    first = bridge.expand(result.accessor)[0]
    assert first.path == '_[0]' and first.is_container
    assert bridge.expand(first.accessor)[0].path == "_[0]['path']"


def test_setting_a_value_writes_into_the_namespace():
    ns = {'n': 1}
    assert Bridge(NsClient(ns)).set_value(('n',), '99') is None
    assert ns['n'] == 99
    assert Bridge(NsClient(ns)).set_value(('n',), 'this is not python') is not None


# -- the overlay: the security-relevant half -----------------------------------
def test_an_agent_write_shadows_instead_of_rebinding():
    """The agent's assignment succeeds, but lands in its own layer.

    This is the property leela's agent surface is built on, and the shape of it matters: the
    write is not refused (which would make the agent useless), it is *redirected*.
    """
    owner = {'x': 1}
    s = AgentSession(owner=lambda: owner, log=False)
    assert s.run('x = 999').ok
    assert owner['x'] == 1, "the owner's binding must survive whatever the agent does"
    assert s.layer['x'] == 999, 'the agent should see its own value'


def test_the_agent_cannot_delete_or_mutate_an_owner_name():
    owner = {'x': 1, 'xs': [1, 2]}
    s = AgentSession(owner=lambda: owner, log=False)
    s.run('del x')
    assert 'x' in owner
    assert s.run('xs.append(3)').error.startswith('blocked:')
    assert owner['xs'] == [1, 2]


def test_the_isolated_scope_discards_what_it_wrote():
    s = AgentSession(owner=lambda: {'x': 1}, log=False)
    s.run('z = 5', scope='isolated')
    assert 'z' not in s.layer


# -- the knob that keeps transcripts under leela's names -----------------------
def test_leela_can_redirect_both_transcript_streams(tmp_path):
    """What the kernel bootstrap and `leela-dev` pass as session_dir/agent_session_dir.

    Read back through the accessors, not the module globals: `from dhrishti.runtime import *`
    binds those by value, so a stale copy would look like a working knob.
    """
    from dhrishti.runtime import hist_dir, agent_dir
    try:
        set_logging(dir=tmp_path/'leela_sessions', agent_dir=tmp_path/'leela_agent_sessions')
        assert hist_dir() == tmp_path/'leela_sessions'
        assert agent_dir() == tmp_path/'leela_agent_sessions'
        s = AgentSession(owner=lambda: {}, log=True)
        s.run('answer = 42')
        assert s.log_path.parent.name == 'leela_agent_sessions'
        assert s.log_path.exists()
    finally:
        set_logging(dir='leela_sessions', agent_dir='leela_agent_sessions')
