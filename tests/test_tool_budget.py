"""How much work one turn may do, as a setting rather than a constant.

ramabana sizes a turn from the prompt when the budget is `auto` -- 24 tool calls for a question,
240 for "implement and verify" -- and takes a number to pin it. What leela owns is making that
choice persist, reach every live agent, and mean the same thing whether it was set in the
settings panel or typed as `/tool-budget` mid-conversation.
"""

import pytest
from starlette.testclient import TestClient

from leela.app import ide_app
from leela.workspace import STEP_RANGE, TOOL_RANGE, Workspace, budget_value, ws_path


@pytest.mark.parametrize('given,want', [
    ('auto', 'auto'), ('AUTO', 'auto'), (' 80 ', 80), (80, 80),
    (TOOL_RANGE[0], TOOL_RANGE[0]), (TOOL_RANGE[1], TOOL_RANGE[1]),
    # Out of range is `auto`, never a silent clamp: a request for 4000 that quietly became 400
    # would be a different answer wearing the same face.
    (TOOL_RANGE[0] - 1, 'auto'), (TOOL_RANGE[1] + 1, 'auto'),
    (None, 'auto'), (True, 'auto'), ('', 'auto'), ('lots', 'auto'),
])
def test_a_budget_is_auto_or_a_number_in_range(given, want):
    assert budget_value(given, *TOOL_RANGE) == want


def test_the_setting_reaches_the_agent_that_is_built_from_it(tmp_path):
    ws = Workspace(roots=[tmp_path])
    assert (ws.tool_budget, ws.step_budget) == ('auto', 'auto'), 'auto is the default'
    ws.tool_budget, ws.step_budget = 240, 60
    assert (ws.ai.tool_budget, ws.ai.step_budget) == (240, 60)


def test_changing_it_does_not_restart_the_conversation(tmp_path):
    ws = Workspace(roots=[tmp_path])
    agent = ws.ai                       # built while the budget was still auto
    with TestClient(ide_app(ws)) as c:
        d = c.post('/agent/budget', json={'tools': 240, 'steps': 60}).json()
        assert d['tools'] == 240 and d['steps'] == 60
        assert (agent.tool_budget, agent.step_budget) == (240, 60), 'the live agent was updated in place'
        assert ws.ai is agent, 'and it is the same conversation'

        assert c.post('/agent/budget', json={'tools': 'auto'}).json()['tools'] == 'auto'
        assert agent.tool_budget == 'auto' and agent.step_budget == 60, 'one field at a time'


def test_a_value_it_will_not_take_is_refused_rather_than_reset(tmp_path):
    "`budget_value` answers `auto` for anything it rejects, so a typo would look like a reset."
    ws = Workspace(roots=[tmp_path])
    ws.tool_budget = 160
    with TestClient(ide_app(ws)) as c:
        r = c.post('/agent/budget', json={'tools': 4000})
        assert r.status_code != 200 or not r.json().get('ok')
        assert f'{TOOL_RANGE[0]} to {TOOL_RANGE[1]}' in r.text
        assert ws.tool_budget == 160, 'the refused value did not land'


def test_the_budget_survives_a_reload(tmp_path, monkeypatch):
    ws = Workspace(roots=[tmp_path])
    ws.tool_budget, ws.step_budget = 160, 40
    ws.save()
    assert Workspace.load(ws_path()).tool_budget == 160
    assert Workspace.load(ws_path()).step_budget == 40


def test_a_saved_budget_outside_the_range_falls_back_to_auto(tmp_path):
    "A workspace.json edited by hand, or written by a version with different bounds."
    ws = Workspace(roots=[tmp_path])
    ws.tool_budget = 160
    ws.save()
    import json
    d = json.loads(ws_path().read_text()); d['tool_budget'] = 9999
    ws_path().write_text(json.dumps(d))
    assert Workspace.load(ws_path()).tool_budget == 'auto'


def test_the_slash_command_and_the_setting_do_not_disagree(tmp_path):
    """`/tool-budget` is ramabana's and sets the attribute on one agent.

    Left there, the panel would show the old number and the next prompt cell would be built with
    it -- one way of saying a thing with two answers to what it is.
    """
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as c:
        out = c.post('/agent/command', json={'line': '/tool-budget 240'}).json()
        assert '240' in out['text']
        assert ws.tool_budget == 240, 'the workspace followed the command'
        assert Workspace.load(ws_path()).tool_budget == 240, 'and it was saved'

        c.post('/agent/command', json={'line': '/tool-budget auto'})
        assert ws.tool_budget == 'auto'


def test_the_panel_can_ask_what_is_actually_in_force(tmp_path):
    ws = Workspace(roots=[tmp_path]); ws.tool_budget = 160
    with TestClient(ide_app(ws)) as c:
        d = c.get('/agent/budget/state').json()
        assert d['tools'] == 160 and d['tool_range'] == list(TOOL_RANGE)
        assert d['step_range'] == list(STEP_RANGE)
