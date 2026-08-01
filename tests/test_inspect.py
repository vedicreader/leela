"""Tests for `leela.inspect` — the engine that turns a namespace into the node tree.

These exist because of how the rest of the suite is built. Every other test here runs
against a *fake* kernel (see `conftest.py`), which is the right call for testing what the
frontends draw — but it means the real inspection engine, all thousand-odd lines of it,
would otherwise have no coverage in this repository at all. That was tolerable while the
engine lived in dhrishti and was tested there under nbdev. It is not tolerable now that
leela owns it.

Nothing here needs a kernel: the engine reads whatever namespace it is handed, so a plain
dict driven through `NsClient` exercises the same code paths the in-kernel server uses.
"""

import numpy as np
import pandas as pd
import pytest

from leela.inspect import (AgentSession, Bridge, NsClient, PROFILES, SORTS, expand,
                           grid_page, profile_view, value_str, var_info)


@pytest.fixture
def ns():
    "A namespace with one of each thing the engine special-cases."
    return {'n': 42, 's': 'hello', 'xs': [1, 2, 3], 'd': {'a': 1, 'b': 2},
            'arr': np.arange(6).reshape(2, 3),
            'df': pd.DataFrame({'revenue': [120, 340, 90], 'units': [12, 34, 9]}),
            '_hidden': 'underscored'}


@pytest.fixture
def bridge(ns): return Bridge(NsClient(ns))


# -- what a variable looks like ------------------------------------------------
def test_var_info_reports_type_and_value():
    v = var_info('n', 42, ('n',), ())
    assert v.name == 'n' and v.type == 'int' and v.value == '42'


def test_a_frame_carries_its_shape():
    df = pd.DataFrame({'a': [1, 2], 'b': [3, 4]})
    v = var_info('df', df, ('df',), ())
    assert v.type == 'DataFrame' and v.shape == '(2, 2)' and v.is_container


def test_value_str_survives_an_object_that_raises_in_repr():
    "A broken __repr__ is the user's bug, not a reason for the whole panel to go blank."
    class Boom:
        def __repr__(self): raise RuntimeError('nope')
    assert isinstance(value_str(Boom()), str)


# -- the grouped view ----------------------------------------------------------
@pytest.mark.parametrize('profile', list(PROFILES))
def test_every_profile_produces_groups(bridge, profile):
    "Ungrouped nodes come back under a `None` label; grouped ones under a string."
    groups = bridge.view(profile)
    assert groups and all(lbl is None or isinstance(lbl, str) for lbl, _ in groups)


@pytest.mark.parametrize('sort', list(SORTS))
def test_every_sort_order_is_accepted(bridge, sort):
    assert bridge.view('full', sort) is not None


def test_the_view_finds_the_plain_variables(bridge):
    names = {v.name for _, vs in bridge.view('full') for v in vs}
    assert {'n', 's', 'xs', 'd', 'arr', 'df'} <= names


def test_sorting_by_name_is_alphabetical(ns):
    got = [v.name for _, vs in profile_view(ns, profile='full', sort='name') for v in vs]
    plain = [n for n in got if not n.startswith('_')]
    assert plain == sorted(plain)


def test_underscored_names_sort_to_the_bottom(ns):
    "Private names are still shown, but they never push the interesting ones down the panel."
    got = [v.name for _, vs in profile_view(ns, profile='full', sort='name') for v in vs]
    assert got[-1] == '_hidden'


def test_recency_order_follows_the_version_map(ns):
    "sort='recent' is driven by an injected name->version map; the newest version comes first."
    order = {'n': 3, 's': 1, 'xs': 2}
    got = [v.name for _, vs in profile_view(ns, profile='full', sort='recent', order=order)
           for v in vs if v.name in order]
    assert got[0] == 'n'


# -- expanding a container -----------------------------------------------------
def test_expanding_a_dict_yields_its_keys(ns):
    "Keys are shown as their repr, so a string key is visibly a string."
    assert {c.name for c in expand(ns, ('d',))} >= {"'a'", "'b'"}


def test_expanding_a_list_yields_its_items(ns):
    assert len(expand(ns, ('xs',))) >= 3


def test_expanding_a_frame_reaches_its_columns(ns):
    assert {'revenue', 'units'} <= {c.name for c in expand(ns, ('df',))}


def test_expanding_something_that_is_not_there_does_not_raise(ns):
    "The IDE can ask about a name a cell has since deleted; that must not take the panel down."
    assert expand(ns, ('nope',)) == [] or expand(ns, ('nope',)) is not None


# -- the grid ------------------------------------------------------------------
def test_a_frame_pages_as_a_grid(ns):
    g = grid_page(ns, ('df',))
    assert g['headers'] == ['revenue', 'units'] and g['nrows'] == 3


def test_an_array_pages_as_a_grid(ns):
    assert grid_page(ns, ('arr',))['nrows'] == 2


def test_a_scalar_is_not_gridable(ns):
    assert grid_page(ns, ('n',)) is None


# -- writing back --------------------------------------------------------------
def test_setting_a_value_writes_into_the_namespace(ns, bridge):
    assert bridge.set_value(('n',), '99') is None
    assert ns['n'] == 99


def test_a_bad_expression_comes_back_as_an_error(bridge):
    assert bridge.set_value(('n',), 'this is not python') is not None


# -- the agent overlay ---------------------------------------------------------
# This is the security-relevant half: an agent gets to read everything and create its own
# names, and must never be able to rebind or delete one of the owner's.
# `owner` is a *callable* returning the namespace, so the session always reads it live
# rather than holding a stale copy.
def test_the_agent_can_create_its_own_names():
    s = AgentSession(owner=lambda: {'x': 1}, log=False)
    r = s.run('y = 5')
    assert r.ok and s.layer.get('y') == 5


def test_the_agent_reads_the_owner_namespace():
    s = AgentSession(owner=lambda: {'x': 7}, log=False)
    r = s.run('print(x)')
    assert r.ok and '7' in r.stdout


def test_an_agent_write_shadows_instead_of_rebinding():
    """The agent's assignment succeeds, but lands in its own layer.

    This is the whole security property, and the shape of it matters: the write is not
    refused (which would make the agent useless), it is *redirected*. The agent sees its
    own value from then on; the owner's binding is untouched.
    """
    owner = {'x': 1}
    s = AgentSession(owner=lambda: owner, log=False)
    r = s.run('x = 999')
    assert r.ok
    assert owner['x'] == 1, "the owner's binding must survive whatever the agent does"
    assert s.layer['x'] == 999, 'the agent should see its own value'


def test_the_agent_cannot_delete_an_owner_name():
    owner = {'x': 1}
    s = AgentSession(owner=lambda: owner, log=False)
    s.run('del x')
    assert 'x' in owner


def test_the_isolated_scope_discards_what_it_wrote():
    s = AgentSession(owner=lambda: {'x': 1}, log=False)
    s.run('z = 5', scope='isolated')
    assert 'z' not in s.layer
