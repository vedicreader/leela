"""The agent block's routes, now that they are its own rather than `ide_app`'s."""

from __future__ import annotations
import re, time
from fastcore.basics import first
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.workspace import Workspace
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]

EXECUTION = ('/agent/run-policy', '/agent/tool-preview', '/agent/retry-tool', '/agent/rollback-tool',
             '/agent/steer', '/agent/state/save', '/agent/state/load')

def paths(app): return {getattr(r, 'path', '') for r in app.routes}

def test_the_execution_surface_is_reachable(tmp_path):
    "Run policies, previews, steering and state memory, each as a live route."
    got = paths(ide_app(Workspace(roots=[tmp_path])))
    missing = [p for p in EXECUTION if p not in got]
    assert missing == [], missing

def test_saved_states_say_which_project_and_layer_they_came_from(tmp_path, monkeypatch):
    """Every workspace saves into the one shared store, so the list has always held other projects' charters."""
    from leela.blocks.memory.memory import Memory
    here, elsewhere = tmp_path/'here', tmp_path/'elsewhere'
    for d in (here, elsewhere): d.mkdir()
    remembered = []
    monkeypatch.setattr(Memory, 'remember_agent_state',
                        lambda self, title, text, meta=None: remembered.append((title, text, meta or {})) or
                        {'doc_id': f'doc-{len(remembered)}'})
    monkeypatch.setattr(Memory, 'agent_states', lambda self, limit=40: [
        {'id': 'ours', 'title': 'Working state', 'added_at': 2,
         'meta': {'agent': {'layer': 'project', 'roots': [str(here)], 'revision': 3}}},
        {'id': 'theirs', 'title': 'Another charter', 'added_at': 1,
         'meta': {'agent': {'layer': 'organization', 'roots': [str(elsewhere)]}}}])
    ws = Workspace(roots=[here])
    with TestClient(ide_app(ws)) as c:
        c.post('/agent/state/save', json={'title': 'Working state', 'text': '# Goal\n\nShip it.',
                                          'layer': 'project', 'activate': False})
        assert remembered[0][2]['layer'] == 'project', 'the layer is saved with the state'
        d = c.get('/agent/states').json()
        rows = {s['id']: s for s in d['states']}
        assert set(rows) == {'ours', 'theirs'}, "another project's state is offered for reuse"
        assert rows['ours']['mine'] is True and rows['ours']['where'] == 'here'
        assert rows['ours']['layer'] == 'project' and rows['ours']['revision'] == 3
        assert rows['theirs']['mine'] is False and rows['theirs']['where'] == 'elsewhere'
        assert rows['theirs']['layer'] == 'organization'
        assert d['layers_seen'] == ['organization', 'project']
        narrowed = c.get('/agent/states', params={'scope': 'project'}).json()
        assert [s['id'] for s in narrowed['states']] == ['ours'], 'and the narrowing still narrows'

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
    assert tool_group('something_else') == 'Other'
    ungrouped = sorted(n for n in tool_groups() if tool_group(n) == 'Other')
    assert ungrouped == [], f'shalya groups these and Leela does not label them: {ungrouped}'
    assert set(tool_groups().values()) <= set(GROUP_LABELS), 'a shalya group with no label here'
    assert not (set(LEELA_TOOLS) & set(tool_groups())), 'shalya already names these'

def test_the_tools_leela_adds_are_the_ones_it_labels_itself():
    "A name in `LEELA_TOOLS` that Leela no longer builds is a stale label hiding the next gap."
    from leela.blocks.agent.ai import _news_tools, _session_tools
    from leela.blocks.agent.turns import LEELA_TOOLS
    from leela.blocks.agent.video import video_tools
    built = {t.__name__ for f in (_session_tools, _news_tools, video_tools) for t in f(None)}
    assert set(LEELA_TOOLS) == built, (f'only in the table: {set(LEELA_TOOLS) - built}; '
                                      f'only built: {built - set(LEELA_TOOLS)}')

def test_the_undo_button_and_the_json_field_follow_the_new_dialect():
    js = (ROOT/'leela/blocks/agent/approvals.js').read_text()
    assert "['edit_file', 'create_file', 'replace_text', 'edit_cell']" in js and "field.kind === 'json'" in js and 'JSON.parse' in js
    core = (ROOT/'leela/static/js/core.js').read_text()
    assert 'JSON.stringify(value)' in core and 'list_files' not in core

def test_the_pane_offers_the_opt_ins_beside_the_warm_toggle_and_the_settings_hold_the_default():
    live = (ROOT/'leela/blocks/agent/live.js').read_text(); app = (ROOT/'leela/app.py').read_text()
    assert "optin: agentOptins()" in live and 'lee-thread-warm' in live and "'·' + " in live, 'a thread row wears its opt-ins like ·warm'
    assert "id='agentoptin-research'" in app and "id='agentoptin-exhash'" in app, 'per-chat toggles beside warm'
    assert "id='agent-optin-research'" in app and "id='agent-optin-exhash'" in app, 'workspace defaults in settings'
    assert "/agent/optin" in (ROOT/'leela/blocks/agent/budgets.js').read_text()
    assert 'overrides this default' in app.split("id='agent-optin-research'")[1][:600], "the settings tooltip says a browser's own toggle overrides the default"

def test_the_restore_dialog_names_the_git_writes_and_the_loop_note_survives_a_preview_refresh():
    js = (ROOT/'leela/blocks/agent/approvals.js').read_text()
    assert 'g.tool' in js and 'g.summary' in js and 'g.undoes' in js, 'each git write the rollback would undo is named'
    assert 'uncommitted' in js[js.index('function gitWritesList'):], 'the dialog says the undo is refused over uncommitted edits outside the turn'
    assert 'card._loopNote =' in js and 'card._loopNote ?' in js[js.index('async function refreshProposalPreview'):], 'kept on the card, re-painted on refresh'

def test_the_tool_tables_have_one_home():
    """`app.py` carried its own `TOOL_GROUPS`, `_tool_group` and `_tool_preview`."""
    import ast
    owner = 'leela/blocks/agent/turns.py'
    for name in ('GROUP_LABELS', 'LEELA_TOOLS', 'tool_group', 'tool_preview'):
        homes = []
        for p in sorted((ROOT/'leela').rglob('*.py')):
            if 'vendor' in p.parts: continue
            for node in ast.walk(ast.parse(p.read_text())):
                bound = ([t.id for t in getattr(node, 'targets', []) if isinstance(t, ast.Name)]
                         if isinstance(node, ast.Assign) else
                         [node.name] if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else [])
                if any(b.lstrip('_') == name for b in bound): homes.append(p.relative_to(ROOT).as_posix())
        assert homes == [owner], f'{name} is defined in {homes}'

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
    """Thread-aware routes answer `code` and `message`, never `error`."""
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


def test_every_routed_job_says_where_its_model_is_spent():
    """The settings pane renders three model controls server-side and the rest from `/agent/models`."""
    from leela.agent.core import JOBS
    from leela.blocks.agent.models import JOB_HELP
    from leela.app import help_mark
    assert set(JOBS) <= set(JOB_HELP), f'no help for {set(JOBS) - set(JOB_HELP)}'
    assert 'falls back to oneshot' in JOB_HELP['classify']
    # nothing calls the oneshot job directly: it is only what the unset cheap jobs fall back to
    assert 'Nothing calls it directly' in JOB_HELP['oneshot']
    assert 'gpt-4.1' in JOB_HELP['summary'] and 'claude-sonnet-5' in JOB_HELP['subagent'], 'ramabana 0.2.5 defaults'
    assert all('stays on the turn model' in JOB_HELP[j] for j in ('oneshot', 'summary', 'subagent')), 'and a local turn keeps them'
    assert JOB_HELP['turn'] in str(help_mark('turn')) and 'lee-hint' in str(help_mark('turn'))
    assert str(help_mark('nosuchjob'))                 # an unknown job renders, saying nothing


def test_an_unlinked_delegation_is_not_reported_as_having_done_nothing(tmp_path):
    "No stamped call anywhere means we cannot account for the sub-agent, which is not the same thing."
    ws = Workspace(roots=[tmp_path])
    ai = ws.threads.active.ai
    ai.activity.finish(ai.activity.start('delegate_search', {'question': 'anything?'}), 'nothing')
    with TestClient(ide_app(ws)) as client:
        d = client.get('/agent/subagents').json()
        assert d['delegations'] and d['delegations'][0]['calls'] == []
        assert d['records_sub_calls'] is False

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


def test_a_painted_turn_carries_what_can_still_be_done_to_it(tmp_path):
    """Undo, restore and revise reached the browser only on the live `done` payload, so they vanished on every repaint that rebuilt from the turn log."""
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        d = client.get('/agent/thread/turns').json()
        assert d['ok'] and all('capabilities' in t for t in d['turns'])
    caps = ws.threads.active.ai.turn_capabilities('nothing-like-this')
    assert caps == {'revisable': False, 'undoable': False, 'branchable': False, 'known': False,
                    'files': [], 'git': [], 'irreversible': []}

def test_a_tool_installed_into_a_frozen_app_is_actually_found(tmp_path, monkeypatch):
    """The Tools row installs into `extras_site`, because the bundle is signed and read-only, and `find_server` looked only on PATH."""
    import leela
    from leela.blocks.lsp import lsp
    bin_dir = tmp_path/'extras'/'bin'
    bin_dir.mkdir(parents=True)
    monkeypatch.setattr(leela, 'extras_bin', lambda: bin_dir)
    monkeypatch.setattr(lsp.shutil, 'which', lambda name: None)
    assert lsp.find_server() == (None, None), 'nothing on PATH and nothing installed'
    server = bin_dir/'basedpyright-langserver'
    server.write_text('#!/bin/sh\nexec cat\n')
    assert lsp.find_server() == (None, None), 'a file that cannot be run is not a server'
    server.chmod(0o755)
    name, argv = lsp.find_server()
    assert name == 'basedpyright-langserver'
    assert argv == [str(server), '--stdio'], 'and it is driven the way that server wants'

def test_the_tools_row_reports_what_it_would_install_and_what_is_here(monkeypatch):
    "The row is what a person clicks to get a language server, so it has to answer for one."
    from leela.blocks.agent import models
    monkeypatch.setattr('leela.blocks.lsp.lsp.find_server', lambda: ('basedpyright-langserver', []))
    row = first(r for r in models.tool_rows() if r['value'] == 'langserver')
    assert row['available'] is True and row['found'] == 'basedpyright-langserver'
    assert row['mb'] and row['blurb'] and row['label']
    assert any('basedpyright' in r for r in row['requirements']), 'named, so the install is pinned'
    monkeypatch.setattr('leela.blocks.lsp.lsp.find_server', lambda: (None, None))
    assert first(r for r in models.tool_rows() if r['value'] == 'langserver')['available'] is False


def test_listing_conversations_does_not_start_a_kernel(tmp_path):
    """`api()` reaches for `ws.runtime()`, which starts one, and that is over a second."""
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        assert client.get('/agent/history').status_code == 200
        assert not ws.pool.kernels, 'opening history started a kernel'
    src = (ROOT/'leela/blocks/agent/app.py').read_text()
    route = src[src.index("@rt('/agent/history')"):src.index("@rt('/agent/history/session')")]
    assert 'api_peek(' in route and 'await api(' not in route, 'the peek is what it may use'

def test_history_is_leelas_own_until_the_rest_is_asked_for(tmp_path, monkeypatch):
    """One log holds Leela's conversations and the CLI's, and most of it is the CLI's."""
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        mine, both = (client.get('/agent/history').json(),
                      client.get('/agent/history?everything=1').json())
    assert mine['only_leela'] is True and both['only_leela'] is False
    assert all(s.get('app') == 'leela' for s in mine['sessions']), 'the default is this Leela\'s own'
    assert len(both['sessions']) >= len(mine['sessions'])
    assert mine['hidden'] == len(both['sessions']) - len(mine['sessions'])
    assert both['hidden'] == 0, 'nothing is hidden when everything was asked for'
    for s in mine['sessions'] + both['sessions']:
        assert s['turns'] == [] and 'count' in s, 'the heading and how many turns, never the turns'
    route = (ROOT/'leela/blocks/agent/app.py').read_text()
    route = route[route.index("@rt('/agent/history')"):route.index("@rt('/agent/history/session')")]
    assert "if not everything: groups = [g for g in groups if g.get('app') == 'leela']" in route

def test_a_probe_serves_its_last_answer_and_refreshes_behind_it():
    """Asking what is installed and who is signed in reaches for every backend and every account: together they were most of a seven-second first paint of the model picker."""
    from leela.blocks.agent import models
    calls = []
    def slow():
        calls.append(1)
        return f'answer {len(calls)}'
    models.forget_probes(disk=True)
    assert models.probed('t', slow) == 'answer 1', 'the first caller has nothing to serve but the truth'
    assert models.probed('t', slow) == 'answer 1' and len(calls) == 1, 'and the next waits for nothing'
    assert models.probed('t', slow, ttl=0) == 'answer 1', 'a stale answer is still served at once'
    for _ in range(100):
        if len(calls) > 1: break
        time.sleep(.02)
    assert len(calls) == 2, 'while it is refreshed behind'
    assert models.probed('t', slow) == 'answer 2'
    models.forget_probes(disk=True)

def test_a_probe_already_gathering_when_the_cache_is_dropped_does_not_come_back(tmp_path, monkeypatch):
    """`forget_probes` means the machine changed under us: the refresh button, or the next test."""
    import threading
    import leela.blocks.agent.models as models
    monkeypatch.setattr(models, 'leela_cfg', tmp_path)
    models.forget_probes()
    gathering, finish = threading.Event(), threading.Event()
    def slow():
        gathering.set(); finish.wait(5); return 'stale'
    t = threading.Thread(target=lambda: models.probed('inflight', slow), daemon=True)
    t.start()
    assert gathering.wait(5), 'the probe is under way'
    models.forget_probes()
    finish.set(); t.join(5)
    assert models.probed('inflight', lambda: 'fresh') == 'fresh', 'no answer from before the drop'
    assert models.probe_path('inflight').read_text().count('stale') == 0, 'nor kept for the next run'
    models.forget_probes(disk=True)

def test_which_row_a_chosen_model_is_is_a_lookup_not_a_scan():
    """`selected` resolved every one of ninety-odd rows to find the one a chosen model matched, and it ran three times a request."""
    src = (ROOT/'leela/blocks/agent/app.py').read_text()
    route = src[src.index("def agent_models("):src.index("@rt('/agent/models/add')")]
    picked = route[route.index('def selected('):route.index('# The routed jobs')]
    assert 'by_id.get(' in picked and 'for r in rows' not in picked, 'no scan per selection'
    assert "probed(f'catalog2:{legacy}'" in route, 'and the catalog itself is probed'
    assert 'if refresh: forget_probes(disk=True)' in route, 'with a way to ask for a fresh one'
    from leela.blocks.agent.models import catalog
    rows, index = catalog(legacy=False)
    assert rows and len(index) <= len(rows), 'one entry per row that resolves'
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in index.items())

def test_a_probe_survives_the_process_that_made_it(tmp_path, monkeypatch):
    """A desktop app is a fresh process every launch, so an in-memory cache is empty exactly when the picker is first drawn."""
    import leela.blocks.agent.models as models
    monkeypatch.setattr(models, 'leela_cfg', tmp_path)
    models.forget_probes()
    calls = []
    def probe():
        calls.append(1)
        return {'rows': ['a', 'b'], 'n': len(calls)}
    assert models.probed('disk-test', probe)['n'] == 1
    assert models.probe_path('disk-test').is_file(), 'kept for the next process'
    models.forget_probes()                       # as a new process starts: memory empty, disk warm
    assert models.probed('disk-test', probe) == {'rows': ['a', 'b'], 'n': 1}, 'served from disk'
    # What a previous run learned is a starting point, not news, so a refresh runs behind it. The
    # caller waited for none of it: the answer above is the one that was already on disk.
    for _ in range(100):
        if len(calls) > 1: break
        time.sleep(.02)
    assert len(calls) == 2, 'and it is re-probed behind whoever asked'
    models.forget_probes(disk=True)
    assert not models.probe_path('disk-test').is_file(), 'the refresh button drops it'

def test_the_picker_marks_a_model_once_not_once_per_request():
    """`model_marks` reaches `spec_caps`, which scans the Hugging Face cache for a local model."""
    from leela.blocks.agent import models
    rows = [{'value': 'x', 'modalities': 'text'}, {'value': 'y', 'gen_image': False}]
    seen = []
    original = models.model_marks
    try:
        models.model_marks = lambda name: seen.append(name) or {}
        models.mark_models(rows)
        assert seen == [], 'a row that already carries marks is not marked again'
        models.mark_models([{'value': 'z'}])
        assert seen == ['z'], 'and one that does not, is'
    finally: models.model_marks = original

def _completion_prefs(values):
    "Write a `completions` settings section the way the settings dialog does."
    from leela.blocks.settings.settings import Settings
    Settings(None).save('user', 'completions', values)

def test_only_a_decided_completion_counts_towards_the_accept_rate(tmp_path):
    """A rate is accepts over decisions."""
    from leela.blocks.agent.completions import summary
    rows = [{'kind': 'ask', 'ask_id': 'a', 'instruction': 'add a docstring', 'model': 'm1'},
            {'kind': 'reply', 'ask_id': 'a', 'model': 'm1', 'ms': 900},
            {'kind': 'replace', 'ask_id': 'a'},
            {'kind': 'ask', 'ask_id': 'b', 'instruction': 'rename it', 'model': 'm1'},
            {'kind': 'reply', 'ask_id': 'b', 'model': 'm1'},
            {'kind': 'discard', 'ask_id': 'b'},
            {'kind': 'ask', 'ask_id': 'c', 'instruction': 'stale one', 'model': 'm1'},
            {'kind': 'reply', 'ask_id': 'c', 'model': 'm1'},
            {'kind': 'stale', 'ask_id': 'c'},
            {'kind': 'ask', 'ask_id': 'd', 'instruction': 'still open', 'model': 'm1'},
            {'kind': 'ask', 'ask_id': 'e', 'instruction': 'walked away', 'model': 'm1'},
            {'kind': 'abandon', 'ask_id': 'e'}]
    d = summary(rows)
    assert d['asks'] == 5 and d['answered'] == 3
    assert d['replaced'] == 1 and d['discarded'] == 1
    assert d['accept_rate'] == 0.5, 'one accept and one reject, whatever else was asked'
    assert [r['ask_id'] for r in d['recent']] == ['c', 'b', 'a'], 'newest first, decisions only'
    assert d['recent'][-1]['instruction'] == 'add a docstring' and d['recent'][-1]['ms'] == 900
    assert summary([{'kind': 'ask', 'ask_id': 'z'}])['accept_rate'] is None, 'no decision, no rate'

def test_the_accept_rate_is_reported_per_model(tmp_path):
    "The point of the log: which model's suggestions get taken."
    from leela.blocks.agent.completions import summary
    rows = [{'kind': 'ask', 'ask_id': 'a', 'model': 'fast'}, {'kind': 'reply', 'ask_id': 'a', 'model': 'fast'},
            {'kind': 'replace', 'ask_id': 'a'},
            {'kind': 'ask', 'ask_id': 'b', 'model': 'fast'}, {'kind': 'reply', 'ask_id': 'b', 'model': 'fast'},
            {'kind': 'discard', 'ask_id': 'b'},
            {'kind': 'ask', 'ask_id': 'c', 'model': 'slow'}, {'kind': 'reply', 'ask_id': 'c', 'model': 'slow'},
            {'kind': 'replace', 'ask_id': 'c'},
            {'kind': 'stale', 'ask_id': 'unknown-ask'}]
    models = {m['model']: m for m in summary(rows)['models']}
    assert models['fast']['replaced'] == 1 and models['fast']['discarded'] == 1
    assert models['fast']['accept_rate'] == 0.5
    assert models['slow']['accept_rate'] == 1.0 and models['slow']['discarded'] == 0
    assert models['unknown']['stale'] == 1 and models['unknown']['accept_rate'] is None, \
        'an outcome whose ask is off the end of the log still has to go somewhere'

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


def test_a_completion_row_carries_the_question_the_suggestion_and_the_verdict(tmp_path, monkeypatch):
    """The three things a completion log is for, none of which could be read."""
    from leela.blocks.agent.completions import judgements
    rows = [{'kind': 'ask', 'ask_id': 'a', 'instruction': 'tidy this', 'lang': 'python', 'text': 'x=1'},
            {'kind': 'reply', 'ask_id': 'a', 'model': 'fast', 'ms': 90, 'reply': 'x = 1'},
            {'kind': 'replace', 'ask_id': 'a'},
            {'kind': 'ask', 'ask_id': 'b', 'instruction': 'still thinking'},
            {'kind': 'ask', 'ask_id': 'c', 'instruction': 'this one failed'},
            {'kind': 'error', 'ask_id': 'c'},
            {'kind': 'reply', 'ask_id': '', 'model': 'old'},
            {'kind': 'discard', 'ask_id': ''}]
    out = {r['ask_id']: r for r in judgements(rows)}
    assert out['a']['instruction'] == 'tidy this' and out['a']['kind'] == 'replace'
    assert out['a']['text'] == 'x=1' and out['a']['reply'] == 'x = 1', 'the question and the answer'
    assert out['a']['model'] == 'fast' and out['a']['code'] == 'kept'
    assert out['b']['kind'] == 'ask', 'an ask with no verdict is still an ask'
    assert out['c']['kind'] == 'error', 'a model that failed is the signal a rate would hide'
    unlinked = [r for r in judgements(rows) if r['orphan']]
    assert len(unlinked) == 2, 'two idless rows were joined into one ask'

    withheld = {r['ask_id']: r for r in judgements(rows, snippets=False)}
    assert withheld['a']['text'] is None and withheld['a']['reply'] is None
    assert withheld['a']['code'] == 'withheld', 'recorded but not served reads the same as never recorded'
    assert withheld['b']['code'] == 'not kept', 'and never recorded still reads as never recorded'


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


def test_an_ask_that_never_carried_an_id_still_shows_what_was_asked(tmp_path):
    """Every event recorded before the browser began minting ids is this shape, so it is what the log shows on its first open."""
    from leela.blocks.agent.completions import judgements
    rows = [{'kind': 'ask', 'instruction': 'this is so convoluted', 'lang': 'python', 'at': 1},
            {'ask_id': 'ec14fa9705e9', 'kind': 'reply', 'model': 'gpt-mini', 'ms': 5474, 'at': 2},
            {'ask_id': 'ec14fa9705e9', 'kind': 'stale', 'at': 3}]
    out = judgements(rows)
    assert all(r['orphan'] for r in out), 'nothing here can be joined'
    asked = first(r for r in out if r['kind'] == 'ask')
    assert asked and asked['instruction'] == 'this is so convoluted', 'the question was dropped'
    assert asked['lang'] == 'python'


def test_the_code_is_not_written_because_a_project_said_so(tmp_path, monkeypatch):
    """The reader's gate is the user scope, and so is the writer's."""
    from leela.blocks.agent.completions import completions
    from leela.blocks.settings.settings import Settings
    monkeypatch.setattr(Settings, 'raw', lambda self, scope: {'completions': {'snippets': False}}
                        if scope == 'user' else {'completions': {'snippets': True}})
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as client:
        client.post('/ai/events', json={'events': [
            {'kind': 'ask', 'ask_id': 'a', 'instruction': 'tidy', 'text': 'secret = 1'},
            {'kind': 'reply', 'ask_id': 'a', 'model': 'fast', 'reply': 'secret = 1  # tidy'}]})
    on_disk = '\n'.join(p.read_text() for p in completions().files())
    assert 'tidy' in on_disk, 'the instruction is the label on the judgement and is kept'
    assert 'secret = 1' not in on_disk, 'a project setting wrote the code the user said not to keep'


def test_the_completion_route_reads_the_snippet_gate_from_the_user_scope_alone(tmp_path, monkeypatch):
    """One store holds every project's events, and `effective` lets a workspace override the user."""
    from leela.blocks.agent.completions import completions
    from leela.blocks.settings.settings import Settings
    completions().record([{'kind': 'ask', 'ask_id': 'a', 'instruction': 'tidy', 'text': 'x=1'},
                          {'kind': 'reply', 'ask_id': 'a', 'model': 'fast', 'reply': 'x = 1'},
                          {'kind': 'replace', 'ask_id': 'a'}], True)
    monkeypatch.setattr(Settings, 'raw', lambda self, scope: {'completions': {'snippets': False}}
                        if scope == 'user' else {'completions': {'snippets': True}})
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as client:
        r = client.get('/ai/completions')
        d = r.json()
        assert d['snippets'] is False, 'a workspace override unlocked another project\'s code'
        assert r.headers.get('cache-control') == 'no-store', 'source code in a cacheable GET'
        row = first(e for e in d['events'] if e['ask_id'] == 'a')
        assert row['instruction'] == 'tidy' and row['text'] is None and row['reply'] is None
        assert row['code'] == 'withheld'


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

def test_nothing_about_a_completion_is_recorded_when_the_setting_says_not_to(tmp_path):
    from leela.blocks.agent.completions import completions
    _completion_prefs({'telemetry': 'off'})
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as client:
        out = client.post('/ai/events', json={'events': [{'kind': 'ask', 'ask_id': '1'}]}).json()
    assert out['recorded'] == 0 and 'off' in out['note']
    assert list(completions().read()) == []

def test_the_suggested_code_is_kept_only_when_the_setting_says_so(tmp_path):
    "The selection and the reply are the person's own code. Off unless asked for."
    from leela.blocks.agent.completions import completions
    _completion_prefs({'telemetry': 'on', 'snippets': True})
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as client:
        client.post('/ai/events', json={'events': [
            {'kind': 'reply', 'ask_id': '1', 'reply': 'def secret_key(): ...'}]})
    assert [r.get('reply') for r in completions().read()] == ['def secret_key(): ...']

def _pane_js():
    from tests.assets import read
    return read('leela/blocks/agent/live.js') + read('leela/blocks/agent/steer.js')

def test_the_panes_three_preferences_round_trip_through_settings(tmp_path):
    """`localStorage` is per origin and the app takes whatever port it is given, so a preference kept only there read as its default at the next launch: notifications a person switched on came back off without anyone asking."""
    from leela.blocks.settings.settings import Settings, DEFAULT_SETTINGS
    for key in ('notify', 'reasoning', 'historyLeelaOnly'): assert key in DEFAULT_SETTINGS['agent'], key
    path = tmp_path/'settings.json'
    Settings(root=tmp_path, user_path=path).save(
        'user', 'agent', {'notify': True, 'reasoning': 'high', 'historyLeelaOnly': False})
    got = Settings(root=tmp_path, user_path=path).effective()['agent']
    assert (got['notify'], got['reasoning'], got['historyLeelaOnly']) == (True, 'high', False)

def test_the_per_origin_keys_are_read_only_by_the_one_migration():
    "Each old key is named once, in the table the migration reads, and nowhere else."
    src = _pane_js()
    for legacy in ('lee-agent-notify', 'lee-agent-reasoning', 'leeHistoryLeelaOnly'):
        assert src.count(legacy) == 1, legacy
    assert "prefGet('agent', 'notify', false)" in src and "prefSet('agent', 'notify', true)" in src
    assert "prefGet('agent', 'historyLeelaOnly', true)" in src
    assert "prefSet('agent', 'historyLeelaOnly', e.target.checked)" in src
    assert "prefSet('agent', 'reasoning', reasoning.value)" in src

def test_the_migration_asks_which_layer_a_value_came_from(tmp_path):
    """settings.json answers with a default for every key, so a saved `false` and a default `false` read the same and `prefAdopt` would skip the migration."""
    from leela.blocks.settings.settings import Settings
    path = tmp_path/'settings.json'
    s = Settings(root=tmp_path, user_path=path)
    assert s.describe()['origins']['agent']['notify'] == 'default'
    s.save('user', 'agent', {'notify': False})
    assert Settings(root=tmp_path, user_path=path).describe()['origins']['agent']['notify'] == 'user'
    assert "origins?.agent?.[key]" in _pane_js(), 'the pane decides from origins, not from the value'

def test_the_probe_memo_and_the_alias_file_are_ramabanas_and_leela_only_names_the_place():
    """`probed` was a TTL memo with atomic disk persistence and a background refresh here, while Ramabana hand-rolled two worse versions of the same idea as bare module tuples."""
    import inspect
    from leela.agent import core
    from leela.blocks.agent import models
    for gone in ('_PROBED', '_probe_lock', '_probe_gen', '_read_probe', '_write_probe', '_keep',
                 '_rows', '_without', '_write', 'API_KEYS', 'HARNESS', 'unavailable_detail'):
        assert not hasattr(models, gone), f'{gone} belongs to Ramabana now'
    for name in ('probed', 'probe_path', 'forget_probes', 'load_models', 'save_model',
                 'delete_model', 'runtime_detail', 'PROBE_TTL', 'API_KEYS'):
        assert hasattr(core, name), f'ramabana.core is missing {name}'
    for name in ('probed', 'probe_path', 'forget_probes', 'load_models', 'save_model', 'delete_model'):
        src = inspect.getsource(getattr(models, name))
        assert 'agent.core import' in src, f'{name} should bind Ramabana\'s, not reimplement it'
        assert len(src.splitlines()) <= 5, f'{name} is a binding, not an implementation'

def test_the_probe_directory_and_the_alias_file_are_under_leelas_own_config():
    import leela.blocks.agent.models as models
    from leela.blocks.agent.models import MODELS_FILE, model_path, probe_dir, probe_path
    assert probe_path('k').parent == probe_dir() == models.leela_cfg/'probes'
    assert model_path() == models.leela_cfg/MODELS_FILE
    assert model_path('/elsewhere/models.json') == Path('/elsewhere/models.json')

def test_pinned_notes_reach_a_completion_prompt_and_not_only_the_briefing(tmp_path, monkeypatch):
    """`Completer._prompt` reached `self.a.ws.agent_memory_context(...)`."""
    from leela.agent.agent import Completer
    from leela.agent.core import env
    from leela.blocks.agent.ai import BRIEFING_NOTES, Assistant
    from ramabana.agent import Agent
    assert Assistant.memory_context is not Agent.memory_context, 'Leela fills the seam in'
    assert Agent.memory_context(None, 'completion') == '', 'and an embedder without one answers ""'
    asked = []
    class Stub:
        ws = None
        host = None
        def memory_context(self, surface, max_chars=6000):
            asked.append((surface, max_chars))
            return 'remember: the encoder is shared'
    prompt = Completer(Stub())._prompt('x = 1', 5, 'python')
    assert asked == [('completion', 6000)], 'the completer names its own surface and its own budget'
    assert '<user_memory>\nremember: the encoder is shared\n</user_memory>' in prompt

def test_the_briefing_and_the_completer_ask_the_same_hook_with_different_budgets(tmp_path):
    "One route to the notes, two budgets: a briefing can afford 24k of them and a keystroke cannot."
    import inspect
    from leela.blocks.agent.ai import BRIEFING_NOTES, Assistant
    src = inspect.getsource(Assistant.system_prompt)
    assert 'self.memory_context(' in src and 'self.ws.agent_memory_context' not in src
    assert inspect.signature(Assistant.memory_context).parameters['max_chars'].default == BRIEFING_NOTES

def test_the_folder_monitor_is_not_advertised_until_it_is_wired():
    """`JOB_HELP` told the user the subagent model was used for folder-monitor reviews."""
    from leela.blocks.agent.models import JOB_HELP
    assert 'folder-monitor' not in JOB_HELP['subagent']
    seam = ROOT/'leela/agent/__init__.py'      # aliases `ramabana.monitor` by name; wires nothing
    users = [p.relative_to(ROOT).as_posix() for p in (ROOT/'leela').rglob('*.py')
             if p != seam and re.search(r'monitor(?!ing)', p.read_text(encoding='utf-8'))]   # `sys.monitoring` is the tracer, not a folder monitor
    assert users == ['leela/blocks/agent/app.py', 'leela/blocks/vault/jobs.py'], f'monitors reach the UI only through /agent/runs/monitors/log: {users}'
