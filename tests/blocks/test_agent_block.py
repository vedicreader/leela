"""The agent block's routes, now that they are its own rather than `ide_app`'s.

Route presence used to be asserted by grepping `getsource(ide_app)`, which said nothing about
whether the route was reachable and broke the moment the routes moved. Ask the app instead.
"""

from __future__ import annotations
import time
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
    """Every workspace saves into the one shared store, so the list has always held other projects'
    charters. Nothing said so, and `Working state` with a date is not something anyone can reuse on
    purpose. The layer is recorded on the way in, and the origin is reported on the way out."""
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

def test_tool_groups_cover_the_families_the_picker_shows():
    from leela.blocks.agent.turns import TOOL_GROUPS, tool_group
    assert tool_group('search_code') == 'Repository' and tool_group('run_python') == 'Runtime'
    assert tool_group('web_search') == 'Web' and tool_group('edit_cell') == 'Notebook'
    assert tool_group('something_else') == 'Other'
    assert set(TOOL_GROUPS) == {'Repository', 'Runtime', 'Web'}

def test_the_tool_tables_have_one_home():
    """`app.py` carried its own `TOOL_GROUPS`, `_tool_group` and `_tool_preview`. Nothing called
    them, and they drifted: `promote_var` was added to the ones in `turns.py` alone, so the two
    tables disagreed about a tool that exists.
    """
    import ast
    owner = 'leela/blocks/agent/turns.py'
    for name in ('TOOL_GROUPS', 'tool_group', 'tool_preview'):
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


def test_an_unlinked_delegation_is_not_reported_as_having_done_nothing(tmp_path):
    "No stamped call anywhere means we cannot account for the sub-agent, which is not the same thing."
    ws = Workspace(roots=[tmp_path])
    ai = ws.threads.active.ai
    ai.activity.finish(ai.activity.start('delegate_search', {'question': 'anything?'}), 'nothing')
    with TestClient(ide_app(ws)) as client:
        d = client.get('/agent/subagents').json()
        assert d['delegations'] and d['delegations'][0]['calls'] == []
        assert d['records_sub_calls'] is False

def test_a_delegation_is_inspectable_and_says_when_nothing_was_recorded(tmp_path):
    """A delegated sub-agent's conversation is thrown away when it answers, so its recorded calls
    are the only account of it. Where the agent core still hands a read-only sub-agent unwrapped
    tools there are none, and the pane must be told that rather than draw an empty list.

    `records_sub_calls` was `hasattr(ai, '_record_sub')`, a name no ramabana release has, so the
    answer was always no and the pane said nothing was being recorded even where it plainly was.
    It is evidence now: a call stamped with the delegation it was made inside.
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

def test_a_tool_installed_into_a_frozen_app_is_actually_found(tmp_path, monkeypatch):
    """The Tools row installs into `extras_site`, because the bundle is signed and read-only, and
    `find_server` looked only on PATH. So in a packaged app the language server installed, worked,
    and was found by nothing: the row went on offering to install it forever."""
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
    """`api()` reaches for `ws.runtime()`, which starts one, and that is over a second. Listing what
    has been said must not boot Python to decorate the answer with kernel run counts."""
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        assert client.get('/agent/history').status_code == 200
        assert not ws.pool.kernels, 'opening history started a kernel'
    src = (ROOT/'leela/blocks/agent/app.py').read_text()
    route = src[src.index("@rt('/agent/history')"):src.index("@rt('/agent/history/session')")]
    assert 'api_peek(' in route and 'await api(' not in route, 'the peek is what it may use'

def test_history_is_leelas_own_until_the_rest_is_asked_for(tmp_path, monkeypatch):
    """One log holds Leela's conversations and the CLI's, and most of it is the CLI's. Grouping and
    shipping all of them so the browser could filter them out was the wrong end to do it at."""
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
    """Asking what is installed and who is signed in reaches for every backend and every account:
    together they were most of a seven-second first paint of the model picker."""
    from leela.blocks.agent import models
    calls = []
    def slow():
        calls.append(1)
        return f'answer {len(calls)}'
    models._PROBED.pop('t', None)
    assert models.probed('t', slow) == 'answer 1', 'the first caller has nothing to serve but the truth'
    assert models.probed('t', slow) == 'answer 1' and len(calls) == 1, 'and the next waits for nothing'
    models._PROBED['t']['at'] = 0            # stale
    assert models.probed('t', slow) == 'answer 1', 'a stale answer is still served at once'
    for _ in range(100):
        if len(calls) > 1: break
        time.sleep(.02)
    assert len(calls) == 2, 'while it is refreshed behind'
    assert models.probed('t', slow) == 'answer 2'
    models._PROBED.pop('t', None)

def test_a_probe_already_gathering_when_the_cache_is_dropped_does_not_come_back(tmp_path, monkeypatch):
    """`forget_probes` means the machine changed under us: the refresh button, or the next test.

    A probe already gathering wrote its answer in afterwards, so the next caller was served the
    state that had just been thrown away, and it landed in whichever config dir was current by
    then. In the suite that is one test's catalog answering another's request."""
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
    """`selected` resolved every one of ninety-odd rows to find the one a chosen model matched, and
    it ran three times a request. The catalog is probed with that index already built."""
    src = (ROOT/'leela/blocks/agent/app.py').read_text()
    route = src[src.index("def agent_models("):src.index("@rt('/agent/models/add')")]
    picked = route[route.index('def selected('):route.index('# The routed jobs')]
    assert 'by_id.get(' in picked and 'for r in rows' not in picked, 'no scan per selection'
    assert "probed(f'catalog:{legacy}'" in route, 'and the catalog itself is probed'
    assert 'if refresh: forget_probes(disk=True)' in route, 'with a way to ask for a fresh one'
    from leela.blocks.agent.models import catalog
    rows, index = catalog(legacy=False)
    assert rows and len(index) <= len(rows), 'one entry per row that resolves'
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in index.items())

def test_a_probe_survives_the_process_that_made_it(tmp_path, monkeypatch):
    """A desktop app is a fresh process every launch, so an in-memory cache is empty exactly when
    the picker is first drawn. What a previous run learned is served at once and re-probed behind."""
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
    """`model_marks` reaches `spec_caps`, which scans the Hugging Face cache for a local model.
    Running that over ninety rows on every request was three and a half seconds of a route that is
    fetched on load. The catalog carries the marks; `mark_models` leaves a marked row alone."""
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
