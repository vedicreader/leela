"""The agent block's routes, now that they are its own rather than `ide_app`'s.

Route presence used to be asserted by grepping `getsource(ide_app)`, which said nothing about
whether the route was reachable and broke the moment the routes moved. Ask the app instead.
"""

from __future__ import annotations
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.workspace import Workspace

EXECUTION = ('/agent/run-policy', '/agent/tool-preview', '/agent/retry-tool', '/agent/rollback-tool',
             '/agent/steer', '/agent/state/save', '/agent/state/load')

def paths(app): return {getattr(r, 'path', '') for r in app.routes}

def test_the_execution_surface_is_reachable(tmp_path):
    "Run policies, previews, steering and state memory, each as a live route."
    got = paths(ide_app(Workspace(roots=[tmp_path])))
    missing = [p for p in EXECUTION if p not in got]
    assert missing == [], missing

def test_every_agent_route_comes_from_the_block(tmp_path):
    "A route left behind in `ide_app` is a route the block cannot own."
    from leela.app import ide_app as _f
    import inspect
    assert "rt('/agent" not in inspect.getsource(_f), 'an /agent route is still in ide_app'
    served = [p for p in paths(ide_app(Workspace(roots=[tmp_path]))) if p.startswith('/agent')]
    assert len(served) > 60, len(served)

def test_the_block_declares_what_it_touches():
    from leela.blocks import agent as block
    from leela.core import CAPABILITIES
    assert set(block.CAPS) <= set(CAPABILITIES)
    assert {'ai', 'memory', 'docs'} <= set(block.CAPS)

def test_tool_groups_cover_the_families_the_picker_shows():
    from leela.blocks.agent.turns import TOOL_GROUPS, tool_group
    assert tool_group('search_code') == 'Repository' and tool_group('run_python') == 'Runtime'
    assert tool_group('web_search') == 'Web' and tool_group('edit_cell') == 'Notebook'
    assert tool_group('something_else') == 'Other'
    assert set(TOOL_GROUPS) == {'Repository', 'Runtime', 'Web'}

def test_history_groups_untagged_turns_by_the_gap_between_them():
    "Old history has no session id, so a 30 minute gap is what separates one context from the next."
    from leela.blocks.agent.turns import history_sessions
    turns = [{'at': 0}, {'at': 60}, {'at': 60 + 1801}, {'at': 5000, 'session': 's1'}]
    got = history_sessions(turns)
    assert [len(g['turns']) for g in got] == [1, 1, 2]
    assert got[0]['id'] == 's1'

#: routes that resolve a thread before doing anything else. `/agent/turn` validates its input
#: first, so an empty prompt is a 400 there rather than a refusal about the conversation.
THREAD_ROUTES = ('/agent/approve', '/agent/command', '/agent/history', '/agent/steer')

def test_an_unknown_conversation_is_refused_with_a_code_and_a_sentence(tmp_path):
    """Thread-aware routes answer `code` and `message`, never `error`. A client reading only
    `error` showed a person the word "Conflict" instead of the sentence it was sent.
    """
    app = ide_app(Workspace(roots=[tmp_path]))
    served = paths(app)
    with TestClient(app) as client:
        for path in THREAD_ROUTES:
            assert path in served, path
            r = client.post(path, json={'thread': 'no-such-thread', 'text': 'x'})
            body = r.json()
            assert r.status_code == 409, (path, r.status_code, body)
            assert body.get('code') == 'thread_not_found', (path, body)
            assert body.get('message') and 'error' not in body, (path, body)
