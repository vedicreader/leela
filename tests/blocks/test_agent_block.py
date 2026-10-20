"""The agent block's routes, now that they are its own rather than `ide_app`'s."""

from __future__ import annotations
from fastcore.basics import first
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.workspace import Workspace
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]


def paths(app): return {getattr(r, 'path', '') for r in app.routes}


def test_every_tool_the_agent_can_be_given_has_a_family_the_picker_shows():
    """`TOOL_GROUPS` was a hand-copy of shalya's `GROUPS` naming twenty tools, and shalya ships about fifty."""
    from shalya.tools import tool_groups
    from leela.blocks.agent.turns import GROUP_LABELS, LEELA_TOOLS, tool_group
    assert tool_group('search_code') == 'Repository' and tool_group('run_python') == 'Runtime'
    assert tool_group('web_search') == 'Web' and tool_group('edit_cell') == 'Notebook'
    assert tool_group('git_status') == 'Git' and tool_group('remember') == 'Memory'
    assert tool_group('memory_search') == 'Memory' and tool_group('read_skill') == 'Skills'
    assert tool_group('api_call') == 'API' and tool_group('generate_image') == 'Media'
    assert tool_group('run_cell') == 'Runtime' and tool_group('news_feeds') == 'Web'
    assert tool_group('screenshot') == 'Browser' and tool_group('page_eval') == 'Browser'
    assert tool_group('something_else') == 'Other'
    ungrouped = sorted(n for n in tool_groups() if tool_group(n) == 'Other')
    assert ungrouped == [], f'shalya groups these and Leela does not label them: {ungrouped}'
    assert set(tool_groups().values()) <= set(GROUP_LABELS), 'a shalya group with no label here'
    assert not (set(LEELA_TOOLS) & set(tool_groups())), 'shalya already names these'


def test_history_says_which_app_started_each_conversation(tmp_path):
    """Leela and the ramabana CLI append to one log."""
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
    # the index lists the whole log; a fallback row has no `first_at`, and a run with no turns comes last
    from leela.blocks.agent.turns import indexed_sessions
    rows = [{'id': 'theirs', 'turns': 3, 'at': 9, 'first_at': 5, 'model': 'm'}, {'id': 'mine', 'turns': 1, 'at': 4}]
    got = indexed_sessions(rows, [{'id': 'mine', 'code': 2}, {'id': 'runs', 'code': 1}], surfaces(tmp_path))
    assert [(g['id'], g['app'], g['code'], g['count']) for g in got] == \
        [('theirs', 'ramabana', 0, 3), ('mine', 'leela', 2, 1), ('runs', 'ramabana', 1, 0)]
    assert got[0]['started'] == 5 and got[1]['started'] == 4 and all(g['turns'] == [] for g in got)


def test_a_nested_delegation_is_drawn_under_the_one_that_asked(tmp_path):
    """A sub-agent's own delegation came back twice: as a top-level card, and as a bare call with nothing under it."""
    ws = Workspace(roots=[tmp_path])
    ai = ws.threads.active.ai
    outer = ai.activity.start('delegate_search', {'question': 'outer?'})
    inner = ai.activity.start('delegate_search', {'question': 'inner?'}, parent_action_id=outer.id)
    leaf = ai.activity.start('grep', {'pattern': 'x'}, parent_action_id=inner.id)
    for a in (leaf, inner, outer): ai.activity.finish(a, 'ok')
    with TestClient(ide_app(ws)) as client:
        d = client.get('/agent/subagents').json()
        assert [x['id'] for x in d['delegations']] == [outer.id], 'the nested one is not a card of its own'
        nested = d['delegations'][0]['calls'][0]
        assert nested['id'] == inner.id and [c['tool'] for c in nested['calls']] == ['grep']
        asked = client.get(f'/agent/subagents?action_id={inner.id}').json()['delegations']
        assert [x['id'] for x in asked] == [inner.id], 'and it can still be opened by itself'


def test_a_delegation_is_inspectable_and_says_when_nothing_was_recorded(tmp_path):
    """A delegated sub-agent's conversation is thrown away when it answers, so its recorded calls are the only account of it."""
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
        assert d['records_sub_calls'] is True, 'a linked call is the evidence that linkage works'
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
    """Missing run, nothing said, and an agent core that cannot carry a steer are all structured, the way `cancel` and `terminate` already answer."""
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
        assert r.status_code == 200 and r.json()['ok'] and r.json()['note'] == f'told {run.id}', r.json()
        assert list(run.inbox) == ['look in tests too'], 'the agent core carries the message'
        run.finish()
        r = client.post(f'/agent/runs/{run.id}/steer', json={'text': 'too late'})
        assert r.status_code == 409 and r.json()['code'] == 'run_over', r.json()


def test_a_tool_installed_into_a_frozen_app_is_actually_found(tmp_path, monkeypatch):
    """The Tools row installs into `extras_site`, because the bundle is signed and read-only, and `find_server` looked only on PATH."""
    import leela
    from leela.blocks.lsp import lsp
    import subprocess
    site = tmp_path/'extras'
    bin_dir = site/'bin'
    bin_dir.mkdir(parents=True)
    monkeypatch.setattr(leela, 'extras_bin', lambda: bin_dir)
    monkeypatch.setattr(lsp.shutil, 'which', lambda name: None)
    assert lsp.find_server() == (None, None), 'nothing on PATH and nothing installed'
    (site/'fakels.py').write_text('import sys\ndef main(): print(sys.argv[1:])\n')
    server = bin_dir/'basedpyright-langserver'
    # What `pip install --target` writes, from an interpreter since deleted: a rebuilt app, say.
    server.write_text("#!/gone/Leela.app/Contents/MacOS/python\nimport sys\nfrom fakels import main\nif __name__ == '__main__': sys.exit(main())\n")
    assert lsp.find_server() == (None, None), 'a file that cannot be run is not a server'
    server.chmod(0o755)
    name, argv = lsp.find_server()
    assert name == 'basedpyright-langserver'
    out = subprocess.run(argv, capture_output=True, text=True, cwd=tmp_path, timeout=30)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "['--stdio']", 'it runs despite its shebang, driven the way that server wants'


def test_listing_conversations_does_not_start_a_kernel(tmp_path):
    """`api()` reaches for `ws.runtime()`, which starts one, and that is over a second."""
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        assert client.get('/agent/history').status_code == 200
        assert not ws.pool.kernels, 'opening history started a kernel'
    src = (ROOT/'leela/blocks/agent/app.py').read_text()
    route = src[src.index("@rt('/agent/history')"):src.index("@rt('/agent/history/session')")]
    assert 'api_peek(' in route and 'await api(' not in route, 'the peek is what it may use'


def _completion_prefs(values):
    "Write a `completions` settings section the way the settings dialog does."
    from leela.blocks.settings.settings import Settings
    Settings(None).save('user', 'completions', values)


def test_the_selection_route_answers_with_the_ask_id_the_browser_sent(tmp_path, monkeypatch):
    """The browser logs the ask before this request and the verdict long after it, so an id minted here reached the reply and the outcome and never the ask."""
    from leela.workspace import Workspace
    ws = Workspace(roots=[tmp_path])
    monkeypatch.setattr(type(ws.ai), 'summarise', lambda self, text, sp='': 'a shorter version')
    with TestClient(ide_app(ws)) as client:
        d = client.post('/complete/selection', json={'text': 'some selected prose', 'mode': 'summary',
                                                     'ask_id': 'browser-minted'}).json()
        assert d['ok'] and d['ask_id'] == 'browser-minted'
        # a client that does not send one is still answered, so an old page keeps working
        older = client.post('/complete/selection', json={'text': 'some selected prose', 'mode': 'summary'}).json()
        assert older['ok'] and older['ask_id'] and older['ask_id'] != 'browser-minted'


def test_a_suggestion_accepted_after_it_went_stale_is_the_one_that_counts(tmp_path):
    """`stale` is the selection moving out from under a replace."""
    from leela.blocks.agent.completions import judgements, summary
    rows = [{'kind': 'ask', 'ask_id': 'a', 'instruction': 'tidy this'},
            {'kind': 'reply', 'ask_id': 'a', 'model': 'fast'},
            {'kind': 'stale', 'ask_id': 'a'},
            {'kind': 'replace', 'ask_id': 'a'}]
    s = summary(rows)
    assert (s['replaced'], s['discarded'], s['accept_rate']) == (1, 0, 1.0)
    assert first(s['models'])['stale'] == 0, 'the stale was counted as well as the accept'
    assert [r['kind'] for r in judgements(rows)] == ['replace'], 'the row reports the attempt, not the outcome'


def test_completion_events_are_recorded_and_reduced_to_the_fields_this_version_stores(tmp_path):
    from leela.blocks.agent.completions import completions
    _completion_prefs({'telemetry': 'on', 'snippets': False})
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as client:
        out = client.post('/ai/events', json={'events': [
            {'kind': 'ask', 'ask_id': '1', 'instruction': 'add a docstring', 'model': 'm1',
             'text': 'def f(): pass', 'secret': 'no'},
            {'kind': 'replace', 'ask_id': '1'},
            {'kind': 'invented', 'ask_id': '1'}]}).json()
        assert out['ok'] and out['recorded'] == 2, 'a kind nobody declared is dropped, not stored'
        rows = list(completions().read())
        assert [r['kind'] for r in rows] == ['ask', 'replace']
        assert 'secret' not in rows[0] and 'text' not in rows[0], 'the code is kept only when asked for'
        assert rows[0]['instruction'] == 'add a docstring' and rows[0]['at'] > 0
        d = client.get('/ai/completions').json()
        assert d['ok'] and d['telemetry'] == 'on' and d['snippets'] is False
        assert d['summary']['asks'] == 1 and d['summary']['accept_rate'] == 1.0
        assert d['summary']['recent'][0]['instruction'] == 'add a docstring'
        assert client.post('/ai/completions/purge', json={}).json()['removed'] == 1
        assert client.get('/ai/completions').json()['summary']['asks'] == 0


def _pane_js():
    from tests.assets import read
    return read('leela/blocks/agent/live.js') + read('leela/blocks/agent/steer.js')


def test_the_migration_asks_which_layer_a_value_came_from(tmp_path):
    """settings.json answers with a default for every key, so a saved `false` and a default `false` read the same and `prefAdopt` would skip the migration."""
    from leela.blocks.settings.settings import Settings
    path = tmp_path/'settings.json'
    s = Settings(root=tmp_path, user_path=path)
    assert s.describe()['origins']['agent']['notify'] == 'default'
    s.save('user', 'agent', {'notify': False})
    assert Settings(root=tmp_path, user_path=path).describe()['origins']['agent']['notify'] == 'user'
    assert "origins?.agent?.[key]" in _pane_js(), 'the pane decides from origins, not from the value'




SUB_KEYS = {'ok', 'model', 'effort', 'tools', 'note', 'unavailable', 'error'}

def test_subagent_settings_reach_every_conversation_and_the_next_one(tmp_path):
    """The sub-agent effort and tool channel are the workspace's, as `subagent_writes` is: a POST reaches every live conversation, a new one inherits them, and a restart keeps them."""
    ws = Workspace(roots=[tmp_path])
    a, b = ws.threads.active.ai, ws.threads.new().ai
    with TestClient(ide_app(ws)) as client:
        d = client.get('/agent/subagent-settings').json()
        assert set(d) == SUB_KEYS and d['ok'] and d['tools'] == 'auto' and d['effort'] == ''
        r = client.post('/agent/subagent-settings', json={'effort': 'xhigh', 'tools': 'native'})
        d = r.json()
        assert r.status_code == 200 and set(d) == SUB_KEYS and d['ok'], d
        assert (d['effort'], d['tools']) == ('xhigh', 'native') and 'sub-agent effort xhigh' in d['note']
        assert [(x.sub_effort, x.sub_channel) for x in (a, b)] == [('xhigh', 'native')] * 2
        assert (ws.subagent_effort, ws.subagent_tools) == ('xhigh', 'native')
        assert (ws.threads.new().ai.sub_effort, ws.threads.active.ai.sub_channel) == ('xhigh', 'native'), 'a new conversation starts on them'
        assert client.get('/agent/subagent-settings').json()['effort'] == 'xhigh'
        again = Workspace(roots=[tmp_path]); again.restore_settings(ws.state())
        assert (again.subagent_effort, again.subagent_tools) == ('xhigh', 'native'), 'a restart forgot them'
        d = client.post('/agent/subagent-settings', json={'effort': 'default', 'tools': 'text'}).json()
        assert d['ok'] and d['effort'] == '' and d['tools'] == 'text' and b.sub_channel == 'tags' and ws.subagent_effort == ''
        # the command answers with the same dict, and is kept the same way
        out = client.post('/agent/command', json={'line': '/subagents effort max'}).json()
        assert out['ok'] and set(out['settings']) == SUB_KEYS and out['settings']['effort'] == 'max'
        assert out['text'] == out['settings']['note'] and b.sub_effort == 'max' and ws.subagent_effort == 'max'
    bad = Workspace(roots=[tmp_path]); bad.restore_settings({'subagent_effort': 'ludicrous', 'tool_channel': 'smoke'})
    assert (bad.subagent_effort, bad.tool_channel) == ('', ''), 'a value this ramabana cannot read is dropped'


def test_a_sub_agent_model_that_is_not_set_up_answers_the_same_on_every_route(tmp_path):
    """Settings, `/subagents model` and the routed-jobs row all refuse an unknown model with one shape: HTTP 200, `ok: false`, the setup message, nothing applied."""
    ws = Workspace(roots=[tmp_path])
    ai = ws.threads.active.ai
    before = ai.routing.name_for('subagent')
    with TestClient(ide_app(ws)) as client:
        rs = [client.post('/agent/subagent-settings', json={'model': 'no-such-model-xyz'}),
              client.post('/agent/command', json={'line': '/subagents model no-such-model-xyz'}),
              client.post('/agent/model', json={'target': 'subagent', 'model': 'no-such-model-xyz'})]
        assert [r.status_code for r in rs] == [200] * 3
        setting, command, routed = (r.json() for r in rs)
        assert set(setting) == SUB_KEYS and not setting['ok'] and setting['error']
        assert command['settings'] == setting and command['ok'] is False and command['text'] == setting['error']
        assert routed == {**setting, 'target': 'subagent'}, 'the routed-jobs row answers the same dict'
        assert ai.routing.name_for('subagent') == before and 'subagent' not in ws.job_models, 'a refused model was applied'
        assert client.post('/agent/subagent-settings', json={'effort': 'ludicrous'}).json()['ok'] is False
        assert client.post('/agent/subagent-settings', content=b'not json').status_code == 400


def test_the_turn_tool_mode_route_sets_every_conversation_and_is_kept(tmp_path):
    """`/agent/tool-mode` and `/model tools` set the turn's channel for every idle conversation; a refusal is `ok: false` with the mode unchanged."""
    ws = Workspace(roots=[tmp_path])
    a, b = ws.threads.active.ai, ws.threads.new().ai
    with TestClient(ide_app(ws)) as client:
        d = client.get('/agent/tool-mode').json()
        assert d['ok'] and d['tools'] == 'auto' and set(d) == {'ok', 'tools', 'now', 'note', 'error'}
        d = client.post('/agent/tool-mode', json={'tools': 'text'}).json()
        assert d['ok'] and d['tools'] == 'text' and d['note'].startswith('turn tools text'), d
        assert (a.turn_channel, b.turn_channel, ws.tool_channel) == ('tags', 'tags', 'tags')
        assert ws.threads.new().ai.turn_channel == 'tags', 'a new conversation starts on it'
        r = client.post('/agent/tool-mode', json={'tools': 'sideways'})
        assert r.status_code == 200 and r.json()['ok'] is False and r.json()['error'] and r.json()['tools'] == 'text'
        client.post('/agent/command', json={'line': '/model tools native'})
        assert (a.turn_channel, b.turn_channel, ws.tool_channel) == ('native',) * 3
        assert client.post('/agent/tool-mode', json={'tools': 'auto'}).json()['tools'] == 'auto' and ws.tool_channel == ''


def test_a_turn_accepts_every_effort_level(tmp_path, monkeypatch):
    """The reasoning select offers xhigh and max, so the turn route takes them; anything else is refused before a turn starts."""
    from leela.blocks.agent.threads import TurnRunner
    seen = []
    monkeypatch.setattr(TurnRunner, 'start', lambda self, q, att, reasoning, *a: seen.append(reasoning) or {'ok': True})
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        for level in ('xhigh', 'max', 'auto'): assert client.post('/agent/turn', json={'prompt': 'hi', 'reasoning': level}).json()['ok']
        r = client.post('/agent/turn', json={'prompt': 'hi', 'reasoning': 'ludicrous'})
        assert r.status_code == 400 and 'xhigh' in r.json()['error'] and 'max' in r.json()['error']
    assert seen == ['xhigh', 'max', None]
    from tests.assets import read
    html = read('leela/app.py')
    assert "Option(f'{e} reasoning', value=e) for e in EFFORTS" in html


def test_the_palette_and_settings_reach_the_sub_agent_and_tool_controls():
    """Each new control has a palette row that opens it, and `/agent/commands` describes the commands that set them."""
    from tests.assets import read
    pal, js = read('leela/blocks/keys/palette.js'), read('leela/blocks/agent/budgets.js')
    for name, sel in (('sub-agent model', '#jobmodels [data-job="subagent"]'), ('sub-agent effort', '#subeffort'),
                      ('tool calls native or text', '#toolmode'), ('sub-agent tool calls native or text', '#subtools')):
        assert f"name: 'Agent: {name}', scope: 'agent', run: () => leeOpenSetting('{sel}')" in pal
    assert "post('/agent/subagent-settings'" in js and "post('/agent/tool-mode'" in js
    ws = Workspace(roots=[ROOT/'tests'/'fixtures'])
    with TestClient(ide_app(ws)) as client:
        html = client.get('/').text
        for id_ in ('subeffort', 'subtools', 'toolmode', 'jobmodels'): assert f'id="{id_}"' in html
        assert 'value="xhigh"' in html and 'value="max"' in html
        helps = {c['name']: c['help'] for c in client.get('/agent/commands').json()['commands']}
        assert 'effort' in helps['subagents'] and 'native' in helps['subagents'] and 'effort' in helps['models']
