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


def test_history_says_which_app_started_each_conversation(tmp_path):
    """Leela and the ramabana CLI append to one log. The filter that hides the CLI's conversations
    needs to tell them apart, and only Leela marks the sessions it started, so anything unmarked
    is the CLI's.
    """
    from leela.blocks.agent.turns import history_sessions, mark_surface, surfaces
    assert surfaces(tmp_path) == {} and surfaces(None) == {}
    assert mark_surface(tmp_path, '') == {} and mark_surface(None, 's1') == {}
    mark_surface(tmp_path, 'mine', 'agent')
    mark_surface(tmp_path, 'mine', 'agent')            # marking twice writes one row
    assert surfaces(tmp_path) == {'mine': 'agent'}

    turns = [{'session': 'mine', 'at': 1}, {'session': 'theirs', 'at': 2}]
    got = {g['id']: g['app'] for g in history_sessions(turns, (), surfaces(tmp_path))}
    assert got == {'mine': 'leela', 'theirs': 'ramabana'}
    # a kernel-run row with no turns is grouped too, and answers the same question
    only = history_sessions([], [{'id': 'theirs', 'code': 2}], surfaces(tmp_path))
    assert only[0]['app'] == 'ramabana'
    # unmarked history from before this existed reads as the CLI's rather than crashing
    assert all(g['app'] == 'ramabana' for g in history_sessions(turns))


def test_every_routed_job_says_where_its_model_is_spent():
    """The settings pane renders three model controls server-side and the rest from
    `/agent/models`. One copy of the text, because two drifted apart the first time.
    """
    from leela.agent.core import JOBS
    from leela.blocks.agent.models import JOB_HELP
    from leela.app import help_mark
    assert set(JOBS) <= set(JOB_HELP), f'no help for {set(JOBS) - set(JOB_HELP)}'
    assert 'falls back to oneshot' in JOB_HELP['classify']
    # nothing calls the oneshot job directly: it is only what the unset cheap jobs fall back to
    assert 'Nothing calls it directly' in JOB_HELP['oneshot']
    assert 'follows the turn model' in JOB_HELP['summary']
    assert JOB_HELP['turn'] in str(help_mark('turn')) and 'lee-hint' in str(help_mark('turn'))
    assert str(help_mark('nosuchjob'))                 # an unknown job renders, saying nothing


def test_a_delegation_is_inspectable_and_says_when_nothing_was_recorded(tmp_path):
    """A delegated sub-agent's conversation is thrown away when it answers, so its recorded calls
    are the only account of it. Where the agent core still hands a read-only sub-agent unwrapped
    tools there are none, and the pane must be told that rather than draw an empty list.
    """
    ws = Workspace(roots=[tmp_path])
    app = ide_app(ws)
    ai = ws.threads.active.ai
    parent = ai.activity.start('delegate_search', {'question': 'which files import fastllm?'})
    kid = ai.activity.start('search_code', {'query': 'fastllm'}, parent_action_id=parent.id)
    ai.activity.finish(kid, 'backend.py:12'); ai.activity.finish(parent, 'one file does')
    with TestClient(app) as client:
        d = client.get('/agent/subagents').json()
        assert d['ok'] and len(d['delegations']) == 1
        one = d['delegations'][0]
        assert one['id'] == parent.id and [c['tool'] for c in one['calls']] == ['search_code']
        assert d['records_sub_calls'] is hasattr(ai, '_record_sub')
        assert client.get(f'/agent/subagents?action_id={parent.id}').json()['delegations'][0]['id'] == parent.id
        assert client.get('/agent/subagents?action_id=nope').json()['delegations'] == []

        # bounded and newest first: recording every sub-agent call makes the stream far larger than
        # it was, and this is polled while a delegation runs
        for i in range(6): ai.activity.finish(ai.activity.start('delegate_search', {'question': f'q{i}'}), 'ok')
        got = client.get('/agent/subagents?limit=2').json()['delegations']
        assert [x['args']['question'] for x in got] == ['q5', 'q4'], got
        assert client.get('/agent/subagents?limit=0').json()['delegations'], 'a bad limit is not no answer'
        # a live root keeps its finished children; those are not running now
        assert client.get('/agent/subagents').json()['runs'] == []


def test_steering_one_sub_agent_answers_the_same_shape_however_it_refuses(tmp_path):
    """Missing run, nothing said, and an agent core that cannot carry a steer are all structured,
    the way `cancel` and `terminate` already answer. Which run is asked about is settled before
    what was said to it, so a stale button in the pane names the run it could not reach.
    """
    ws = Workspace(roots=[tmp_path])
    app = ide_app(ws)
    assert '/agent/runs/{run_id}/steer' in paths(app)
    run = ws.threads.active.ai._new_run('what imports fastllm?')
    with TestClient(app) as client:
        r = client.post('/agent/runs/run_nope/steer', json={'text': 'look in tests too'})
        assert r.status_code == 404 and r.json()['code'] == 'run_not_found', r.json()
        assert 'error' not in r.json() and r.json()['message']

        assert client.post(f'/agent/runs/{run.id}/steer', json={'text': '   '}).status_code == 400

        r = client.post(f'/agent/runs/{run.id}/steer', json={'text': 'look in tests too'})
        if not hasattr(run, 'steer'):    # an agent core with no way to carry it says so, once
            assert r.status_code == 501 and r.json()['code'] == 'steer_unsupported', r.json()
            assert 'error' not in r.json() and r.json()['message']
            return
        assert r.status_code == 200 and r.json()['ok'] and r.json()['steer_pending'], r.json()
        run.finish()
        r = client.post(f'/agent/runs/{run.id}/steer', json={'text': 'too late'})
        assert r.status_code == 409 and r.json()['code'] == 'run_over', r.json()


def test_a_painted_turn_carries_what_can_still_be_done_to_it(tmp_path):
    """Undo, restore and revise reached the browser only on the live `done` payload, so they
    vanished on every repaint that rebuilt from the turn log. `known` separates a turn that
    changed nothing from one this process no longer holds a boundary for.
    """
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        d = client.get('/agent/thread/turns').json()
        assert d['ok'] and all('capabilities' in t for t in d['turns'])
    caps = ws.threads.active.ai.turn_capabilities('nothing-like-this')
    assert caps == {'revisable': False, 'undoable': False, 'branchable': False, 'known': False,
                    'files': [], 'irreversible': []}
