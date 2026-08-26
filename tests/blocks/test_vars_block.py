"""The variables pane's own routes, where `→live` can take a name the user already has.

`/vars/promote` passed the accessor straight to dhrishti, whose `_promote` rebinds the owner
namespace without looking. The agent's `promote_var` refused the same collision, so the button
and the `p` key could do what the tool would not.
"""

from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from leela.app import ide_app
from leela.workspace import Workspace


def rows(*names):
    return {'groups': [{'label': 'live', 'nodes': [{'name': n, 'type': 'int', 'value': '1'} for n in names]}]}


class Inspector:
    "A dhrishti inspector with a named owner namespace and agent layer."
    alive, base, pid, boot_error, token, kernel_kind = True, 'http://127.0.0.1:9', 1, None, None, 'ipykernel'
    def __init__(self, owner=(), layer=(), owner_rows=True):
        self.owner, self.layer, self.owner_rows, self.calls = list(owner), list(layer), owner_rows, []
    async def api(self, path, params=None, timeout=15):
        self.calls.append((path, dict(params or {})))
        if path == '/api/rows': return rows(*self.owner) if self.owner_rows else None
        if path == '/agent/api/info': return {'agent_names': sorted(self.layer)}
        if path == '/agent/api/exec': return {'ok': True, 'stdout': '', 'error': None}
        if path == '/api/promote':
            a = json.loads(params['accessor'])
            if len(a) != 1: return {'ok': False, 'error': 'can only promote a whole (top-level) variable'}
            if a[0] not in self.layer: return {'ok': False, 'error': f'no agent variable {a[0]!r}'}
            self.owner.append(a[0])
            return {'ok': True, 'error': None}
        return None


@pytest.fixture
def promote(tmp_path, monkeypatch):
    "A client whose `/vars/promote` reaches one `Inspector`, returned alongside it."
    def build(**kw):
        k = Inspector(**kw)
        async def runtime(self, tab=None): return k
        monkeypatch.setattr(Workspace, 'runtime', runtime)
        client = TestClient(ide_app(Workspace(roots=[tmp_path])))
        def ask(name, **params):
            acc = name if isinstance(name, str) else json.dumps(name)
            return client.get('/vars/promote', params={'accessor': acc, **params})
        return k, ask
    return build


def paths(k): return [p for p, _ in k.calls]


def test_promoting_over_a_name_the_user_has_is_refused(promote):
    "The 409 `/refactor/apply` and the git routes answer with, carrying the sentence to show."
    k, ask = promote(owner=['df'], layer=['df'])
    r = ask(['df'])
    assert r.status_code == 409
    assert r.json() == {'ok': False, 'error': 'df already exists in the live namespace. Promoting '
                        'replaces it, and the value that is there now cannot be brought back.'}
    assert '/api/promote' not in paths(k), 'refused before the kernel is asked'
    assert k.owner == ['df']


def test_a_replace_the_person_asked_for_goes_through(promote):
    "A person deciding about their own namespace is not the agent overwriting their work."
    k, ask = promote(owner=['df'], layer=['df'])
    r = ask(['df'], replace=1)
    assert r.status_code == 200 and r.json()['ok'] is True
    assert ('/api/promote', {'accessor': '["df"]'}) in k.calls


def test_a_promoted_name_stops_being_shadowed(promote):
    "The tool drops its layer copy after promoting, and the pane must leave the same state."
    k, ask = promote(owner=['df'], layer=['total'])
    assert ask(['total']).json()['ok'] is True
    assert ('/agent/api/exec', {'code': 'del total', 'scope': 'overlay'}) in k.calls


def test_a_name_the_agent_never_bound_keeps_dhrishtis_own_answer(promote):
    "Only a shadowed name can replace anything, so an owner-only name must not raise a dialog."
    k, ask = promote(owner=['df'], layer=[])
    r = ask(['df'])
    assert r.status_code == 200 and r.json() == {'ok': False, 'error': "no agent variable 'df'"}
    assert '/api/rows' not in paths(k), 'the owner namespace was read for a name nothing can promote'


def test_a_nested_accessor_is_left_to_the_inspector(promote):
    "Nothing below the top level can be promoted at all, so no name of the user's is at stake."
    k, ask = promote(owner=['df'], layer=['df'])
    r = ask(['df', 'index'])
    assert r.status_code == 200
    assert r.json()['error'] == 'can only promote a whole (top-level) variable'


def test_an_unreadable_live_namespace_refuses_rather_than_overwrites(promote):
    "One timed-out probe must not be read as an empty namespace."
    k, ask = promote(owner=['df'], layer=['df'], owner_rows=False)
    r = ask(['df'])
    assert r.status_code == 409 and 'could not be read' in r.json()['error']
    assert '/api/promote' not in paths(k)
    assert ask(['df'], replace=1).json()['ok'] is True


def test_no_kernel_inspector_still_answers_the_shape_the_pane_reads(promote):
    "An inspector that answers nothing is not a probe that failed, and it keeps its own sentence."
    k, ask = promote(owner=[], layer=[])
    async def silent(path, params=None, timeout=15): return None
    k.api = silent
    r = ask(['df'])
    assert r.status_code == 200 and r.json() == {'ok': False, 'error': 'no kernel inspector'}
