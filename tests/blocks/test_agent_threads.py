import asyncio, threading, time
from pathlib import Path

import pytest
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.blocks.runtime.kernels import KernelPool
from leela.blocks.agent.threads import Feed, TurnError, TurnRunner
from leela.workspace import Workspace
from tests.conftest import history_file


@pytest.fixture(autouse=True)
def _kernels_stay_in_process(monkeypatch):
    "These workspaces are built bare, and a turn warms a kernel: give them the fixture's fake ones rather than a real ipykernel per test."
    from tests.blocks.conftest import _FakeKernel
    async def _get(self, key, **kw): return self.kernels.setdefault(key, _FakeKernel())
    monkeypatch.setattr(KernelPool, 'get', _get)
    monkeypatch.setattr(KernelPool, 'peek', lambda self, key: self.kernels.get(key))


def test_feed_sequences_replays_and_resyncs():
    feed = Feed('thread-1', maxlen=2)
    assert feed.emit('user', {'text': 'one'})['seq'] == 1
    feed.emit('chunk', {'text': 'two'}); feed.emit('done', {'ok': True})
    assert [row['seq'] for row in feed.since(1)] == [2, 3]
    assert feed.since(0) == [{'seq': 3, 'event': 'resync', 'data': {
        'thread': 'thread-1', 'oldest': 2, 'latest': 3}}]
    feed.emit('activity', {'done': True}); feed.settle()
    assert feed.finished(4), 'a late watcher event does not erase the settlement cursor'
    feed.emit('user', {'text': 'next'})
    assert not feed.finished(5), 'a new turn resets the terminal cursor'


class _Run:
    id, terminal, state = 'run-1', False, 'completed'
    def dict(self): return {'id': self.id, 'state': 'completed', 'children': []}
    def cancel(self, grace=None): self.terminal = True; return self.terminal


class _AI:
    session_id, busy, ready, note, current_turn_id, current_branch_id = 'thread-1', False, True, '', 'turn-1', 'main'
    problems = []
    compactor = type('Compactor', (), {'count': 0, 'strategy': 'summary', 'note': '', 'last': ''})()
    activity = type('Activity', (), {'_mark': 0, 'rows': lambda self, mark=0: []})()
    turn_use = use = type('Usage', (), {'dict': lambda self: {}})()
    model = type('Model', (), {'name': 'fake'})()
    turn_media = []
    def __init__(self): self._run = _Run()
    def run(self, run_id=''): return self._run
    def runs(self, active=False): return []
    def cancel(self, run_id=''): self._run.terminal = True; return self._run.dict()
    def changes(self): return {}
    def turn_capabilities(self, turn_id): return {}
    def summarize_session(self): return {'title': 'A useful title', 'title_turns': 1, 'muted': False}


class _Approvals:
    pending = None
    def state(self): return {'queued_steer': ''}


class _Workspace:
    def __init__(self):
        self.ai = self._ai = _AI()
        self.approvals, self.pending_approval, self.seen, self.timeline = _Approvals(), None, None, []
    def save_timeline(self, thread_id, turn_id, parts): self.timeline = list(parts); return self.timeline
    def ask_stream(self, prompt, attachments=(), on_registered=None, **kwargs):
        self.seen = tuple(attachments); on_registered(self.ai._run)
        self.ai.current_turn_id = 'turn-2'      # `_prepare` mints this turn's id
        yield 'answer'
        self.ai._run.terminal = True


class _Latched(_AI):
    "An assistant that registers its run before the engine reports it, as Ramabana's `stream` does."
    registered = False
    @property
    def busy(self): return self.registered and not self._run.terminal
    def runs(self, active=False): return [] if self._run.terminal else [self._run.dict()]


def test_a_start_that_never_reports_leaves_the_pane_usable(tmp_path):
    """The reported wedge: one slow start held `_pending` and the registered run for good, so every later send was refused as busy until Leela was restarted."""
    hold = threading.Event()
    class Hung(_Workspace):
        def __init__(self): super().__init__(); self.ai = self._ai = _Latched(); self.calls = 0
        def ask_stream(self, prompt, attachments=(), on_registered=None, **kwargs):
            self.calls += 1
            if self.calls > 1: on_registered(self.ai._run); yield 'answer'; return
            self.ai.registered = True; hold.wait(5)
    ws, feed = Hung(), Feed(); runner = TurnRunner(ws, feed); runner.start_timeout = .05
    try: runner.start('question')
    except TurnError as e: assert e.code == 'turn_conflict'
    else: assert False
    assert runner._pending == {}, 'the refused turn does not keep the slot'
    assert not ws.ai.busy, 'nor the run it registered before it hung'
    assert runner.start('second')['run'] == 'run-1'
    assert [row['event'] for row in feed.since(0)][0] == 'user'
    hold.set()


def _scripted_workspace(tmp, steps, delay=0):
    "A real Workspace on a scripted model, so the runner is exercised against a real Assistant."
    from leela.workspace import Workspace
    from tests.fakemodel import Step, install
    ws = Workspace(roots=[tmp]); ws.add_root('.')
    install(ws, steps, token_delay=delay)
    return ws


def test_a_retained_turn_holds_only_what_a_replay_rebuilds_from_it(tmp_path):
    """`reduceAgentTimeline` joins consecutive chunks into one block of prose and keeps one part per `action_id` holding the newest payload, at the position where that call first appeared."""
    ws = Workspace(roots=[tmp_path]); ws._timeline_path = tmp_path/'timeline.json'
    parts = [{'seq': 1, 'event': 'chunk', 'data': {'text': 'one '}},
             {'seq': 2, 'event': 'chunk', 'data': {'text': 'two '}},
             {'seq': 3, 'event': 'chunk', 'data': {'text': 'three'}},
             {'seq': 4, 'event': 'activity', 'data': {'action_id': 'call-1', 'done': False}},
             {'seq': 5, 'event': 'activity', 'data': {'action_id': 'call-1', 'done': True, 'ok': True}},
             {'seq': 6, 'event': 'activity', 'data': {'summary': 'no id of its own'}},
             {'seq': 7, 'event': 'chunk', 'data': {'text': 'after'}}]
    held = ws.save_timeline('thread-1', 'turn-1', parts)
    assert [r['event'] for r in held] == ['chunk', 'activity', 'activity', 'chunk']
    assert held[0]['data']['text'] == 'one two three', 'the prose was not joined'
    assert held[1]['data'] == {'action_id': 'call-1', 'done': True, 'ok': True}, 'the call kept a stale payload'
    assert held[2]['data'] == {'summary': 'no id of its own'}, 'a row with no id can only ever be new'
    assert held[3]['data']['text'] == 'after', 'prose after a call is a block of its own'
    again = Workspace(roots=[tmp_path]); again._timeline_path = tmp_path/'timeline.json'
    assert again.timeline_parts('thread-1', 'turn-1') == held, 'a restart reads back something else'


def test_a_turn_finishes_after_its_only_subscriber_has_gone(tmp_path):
    """Closing the EventSource used to be how a turn ended."""
    from tests.fakemodel import Step
    ws = _scripted_workspace(tmp_path, [Step(tool=('search_code', {'query': 'Approvals'})),
                                        Step(text='found it')], delay=.01)
    with TestClient(ide_app(ws)) as client:
        accepted = client.post('/agent/turn', json={'prompt': 'where?'}).json()
        with client.stream('GET', '/agent/stream', params={'since': accepted['seq']}) as r:
            next(r.iter_text())                      # one frame, then leave mid-turn
        feed = ws.turn_runner.feed
        end = time.time() + 20
        while not feed.settled_seq and time.time() < end: time.sleep(.05)
        assert feed.settled_seq, 'the turn ran on without anyone listening'
        rows = feed.since(accepted['seq'])
        assert [row['event'] for row in rows].count('done') == 1
        assert any(row['event'] == 'chunk' for row in rows)
        assert ws.ai.runs(active=True) == []
        replay = client.get('/agent/stream', params={'since': accepted['seq']}).text
        assert 'event: done' in replay, 'and the whole turn is still replayable afterwards'


def test_shutdown_cancels_the_run_and_wakes_a_waiting_subscriber(tmp_path):
    "A subscriber parked on the feed must not outlive the process that was filling it."
    from tests.fakemodel import Step
    ws = _scripted_workspace(tmp_path, [Step(text='thinking' * 40)], delay=.05)
    client = TestClient(ide_app(ws))
    with client:
        accepted = client.post('/agent/turn', json={'prompt': 'where?'}).json()
        seen = {}
        async def read():
            seen['rows'] = await ws.turn_runner.feed.anext(accepted['seq'] + 200, 20)
        waiter = threading.Thread(target=lambda: asyncio.run(read()))
        waiter.start(); time.sleep(.05)
        ws.turn_runner.close()
        waiter.join(5)
        # read inside: leaving the client ends the lifespan, and the next `turn_runner` is a
        # fresh thread's, whose feed was never the one this waiter was parked on
        assert seen['rows'] == [] and ws.turn_runner.feed.closed
        assert ws.ai.runs(active=True) == []
    assert not waiter.is_alive(), 'the waiter was woken rather than left on its timeout'


def _threaded_workspace(tmp):
    from leela.workspace import Workspace
    ws = Workspace(roots=[tmp]); ws.add_root('.')
    return ws


def test_eviction_takes_the_least_recently_used_idle_thread(tmp_path):
    """Six slots, and the one that goes is the one nobody has looked at longest, not the oldest, which is why recency is touched on every access rather than only on creation."""
    ws = _threaded_workspace(tmp_path)
    threads = ws.threads
    ids = [threads.new().id for _ in range(6)]
    assert len(threads.rows()) == 6
    for wanted in (ids[0], ids[2], ids[1]): threads.switch(wanted)   # ids[3] is now the stalest idle
    stalest = min((r for r in threads.rows() if r.id != threads.active_id), key=lambda r: r.touched)
    threads.new()
    assert stalest.id not in {r.id for r in threads.rows()}
    assert len(threads.rows()) == 6


def test_a_working_thread_is_never_evicted_and_a_full_board_says_so(tmp_path):
    ws = _threaded_workspace(tmp_path)
    threads = ws.threads
    rows = [threads.new() for _ in range(6)]
    runs = [row.ai._new_run('holding') for row in rows]
    assert {row.state for row in rows} == {'working'}
    try: threads.new()
    except TurnError as e: assert e.code == 'no_evictable_thread'
    else: assert False, 'a working conversation cannot be thrown away to make room'
    for run in runs: run.finish()
    threads.new()
    assert len(threads.rows()) == 6


def test_every_conversation_route_names_the_thread_it_acted_on(tmp_path):
    """A run id is unique only inside its own registry, and an approval belongs to whoever asked."""
    ws = _threaded_workspace(tmp_path)
    first, second = ws.threads.new(), ws.threads.new()
    ws.threads.switch(first.id)
    with TestClient(ide_app(ws)) as client:
        for url in ('/agent/status', '/agent/runs', '/agent/approval'):
            assert client.get(url).json()['thread'] == first.id, url
            assert client.get(f'{url}?thread={second.id}').json()['thread'] == second.id, url
            stale = client.get(f'{url}?thread=thread_gone')
            assert stale.status_code == 409 and stale.json()['code'] == 'thread_not_found', url
        assert client.post('/agent/stop', json={}).json()['thread'] == first.id
        assert client.post('/agent/stop', json={'thread': second.id}).json()['thread'] == second.id

        run = second.ai._new_run('held')
        missing = client.post(f'/agent/runs/{run.id}/cancel', json={})
        assert missing.status_code == 404 and missing.json()['code'] == 'run_not_found'
        assert not run.terminal, 'and the run in the other conversation was left alone'
        ok = client.post(f'/agent/runs/{run.id}/cancel?thread={second.id}').json()
        assert ok['ok'] and ok['thread'] == second.id and run.terminal


def _answered_thread(tmp, text='answered'):
    "A real workspace with one finished turn, so its checkpoints and parts exist."
    import time
    from leela.workspace import Workspace
    from tests.fakemodel import Step, install
    ws = Workspace(roots=[tmp]); ws.add_root('.')
    install(ws, [Step(text=text)], token_delay=0)
    client = TestClient(ide_app(ws))
    with client:
        client.post('/agent/turn', json={'prompt': 'q1'})
        feed, end = ws.turn_runner.feed, time.time() + 20
        while not feed.settled_seq and time.time() < end: time.sleep(.05)
        assert feed.settled_seq, 'the turn has to finish before it can be branched'
        yield ws, client


def test_branching_shaping_and_undo_all_name_their_thread_and_their_branch(tmp_path):
    """One conversation, three ways to move its context: fork a point, shape what it keeps, and undo a turn out of it."""
    for ws, client in _answered_thread(tmp_path):
        listing = client.get('/agent/branches').json()
        assert listing['thread'] == ws.threads.active_id and listing['active'] == 'main'
        turn = listing['turns'][-1]['turn_id']
        parts = client.get(f'/agent/branch/parts?turn_id={turn}').json()['parts']
        assert [p['kind'] for p in parts] == ['user', 'assistant']
        assert all(p['part_id'].startswith(turn) for p in parts), 'a part id names its turn'

        forked = client.post('/agent/fork', json={'turn_id': turn, 'part_id': parts[0]['part_id']}).json()
        assert forked['ok'] and forked['active'] == forked['branch_id'] != 'main'
        assert forked['parent_part_id'] == parts[0]['part_id'] and forked['parent_branch_id'] == 'main'

        undone = client.post('/agent/undo-turn', json={'turn_id': turn}).json()
        assert undone['stage'] == 'before' and undone['undone'] == [turn]
        assert undone['files_restored'] is None, 'undo is about the conversation, never about disk'

        back = client.post('/agent/branch/switch', json={'branch_id': 'main'}).json()
        assert back['active'] == 'main', 'and switching rebuilds rather than copying'
        assert len(ws.ai.history) >= 1, 'the undone turn is still in canonical history'


def test_a_branch_point_inside_a_tool_exchange_is_refused_or_taken_whole(tmp_path):
    "A call without its result is not a conversation any provider will accept."
    for ws, client in _answered_thread(tmp_path):
        turn = client.get('/agent/branches').json()['turns'][-1]['turn_id']
        ws.ai.checkpoints[turn]['after'][:] = [
            {'role': 'user', 'content': 'q'},
            {'role': 'assistant', 'tool_calls': [{'id': 'c1'}]},
            {'role': 'tool', 'tool_call_id': 'c1', 'content': 'r'},
            {'role': 'assistant', 'content': 'done'}]
        parts = client.get(f'/agent/branch/parts?turn_id={turn}').json()['parts']
        assert parts[1]['group'] == parts[2]['group'], 'the call and its result are one group'
        bad = client.post('/agent/fork', json={'turn_id': turn, 'part_id': f'{turn}:99'})
        assert bad.status_code == 409 and bad.json()['code'] == 'branch_point_invalid'
        assert client.get('/agent/branches').json()['active'] == 'main', 'and nothing was created'


def test_reshaping_is_refused_while_the_conversation_is_still_working(tmp_path):
    "Changing the context under a live run would move the question the model is answering."
    for ws, client in _answered_thread(tmp_path):
        turn = client.get('/agent/branches').json()['turns'][-1]['turn_id']
        run = ws.ai._new_run('holding')
        try:
            for url, body in (('/agent/fork', {'turn_id': turn}),
                              ('/agent/undo-turn', {'turn_id': turn}),
                              ('/agent/branch/switch', {'branch_id': 'main'}),
                              ('/agent/history/apply', {'turn_id': turn, 'revision': 0, 'manifest': {}})):
                r = client.post(url, json=body)
                assert r.status_code == 409 and r.json()['code'] == 'thread_busy', url
        finally: run.finish()
        assert client.post('/agent/undo-turn', json={'turn_id': turn}).json()['ok'], 'and allowed once idle'


    # the success path is pinned by test_muting_survives_in_the_session_sidecar_and_does_not_hide_waiting


def test_an_unknown_turn_cannot_become_the_one_that_is_undone(tmp_path):
    """The earliest turn was picked by position, and a turn nobody recognised scored -1, ahead of every real one, so a bad id in the list quietly became the turn that was undone."""
    for ws, client in _answered_thread(tmp_path):
        turn = client.get('/agent/branches').json()['turns'][-1]['turn_id']
        bad = client.post('/agent/undo-turn', json={'turn_ids': ['no-such-turn', turn]})
        assert bad.status_code == 409 and bad.json()['code'] == 'branch_point_invalid'
        assert client.get('/agent/branches').json()['active'] == 'main', 'and nothing was branched'
        assert client.post('/agent/undo-turn', json={'turn_ids': [turn]}).json()['ok']


def test_a_conversation_that_is_not_on_screen_can_still_be_reached(tmp_path):
    """Every conversation owns its own feed, approvals and run policy."""
    ws = _threaded_workspace(tmp_path)
    first, second = ws.threads.new(), ws.threads.new()
    ws.threads.switch(first.id)
    second.feed.emit('user', {'text': 'in the background'})
    with TestClient(ide_app(ws)) as client:
        body = client.get(f'/agent/stream?since=0&thread={second.id}').text
        assert 'in the background' in body, 'the background feed is subscribable by name'
        assert 'in the background' not in client.get('/agent/stream?since=0').text, 'and is not the active one'
        for url, payload in (('/agent/control', {'control': 'directed'}),
                             ('/agent/run-policy', {'policy': 'once'}),
                             ('/agent/steer', {'text': 'go left'})):
            named = client.post(url, json={**payload, 'thread': second.id}).json()
            assert named['thread'] == second.id, url
            stale = client.post(url, json={**payload, 'thread': 'thread_gone'})
            assert stale.status_code == 409 and stale.json()['code'] == 'thread_not_found', url
        assert not first.approvals.state().get('queued_steer'), 'the active one was left alone'
        assert second.approvals.state().get('queued_steer') == 'go left'


def test_a_resumed_conversation_can_be_reshaped_and_its_prose_rewritten(tmp_path):
    """The conversation a person wants to edit is usually one they just resumed, and a resumed assistant has no snapshots, so the parts are rebuilt from the turn log."""
    import json
    from leela.workspace import Workspace
    ws = Workspace(roots=[tmp_path]); ws.add_root('.')
    log = history_file(ws)
    turns = [{'session': 'conv-x', 'at': 1, 'model': ws.ai.model.name, 'turn_id': 'conv-x:turn_000001',
              'prompt': 'q1', 'reply': 'r1',
              'activity': [{'tool': 'view_file', 'line': 'view_file a.py', 'detail': 'contents',
                            'action_id': 'act1', 'ok': True}]},
             {'session': 'conv-x', 'at': 2, 'model': ws.ai.model.name, 'turn_id': 'conv-x:turn_000002',
              'prompt': 'q2', 'reply': 'r2'}]
    log.write_text('\n'.join(json.dumps(t) for t in turns) + '\n')
    with TestClient(ide_app(ws)) as client:
        resumed = client.post('/agent/resume', json={'session': 'conv-x'}).json()
        assert resumed['ok'] and not ws.threads.active.ai.checkpoints, 'no snapshots to compile from'

        listing = client.get('/agent/conversation/parts').json()
        parts = listing['parts']
        assert [p['kind'] for p in parts] == ['user', 'call', 'result', 'assistant', 'user', 'assistant']
        assert [p['editable'] for p in parts] == [True, False, False, True, True, True]
        assert parts[1]['group'] == parts[2]['group'], 'a call and its result move together'

        drop, reword = {parts[1]['part_id']: 'discard'}, {parts[0]['part_id']: 'my better question'}
        pv = client.post('/agent/history/preview',
                         json={'manifest': drop, 'rewrites': reword, 'revision': listing['revision']}).json()
        assert pv['omitted'] == 2 and parts[2]['part_id'] in [*pv['adjusted'], *drop], \
            'dropping the call takes its result with it'
        assert pv['rewritten'] == [parts[0]['part_id']] and pv['tokens'] > 0

        refused = client.post('/agent/history/preview',
                              json={'rewrites': {parts[1]['part_id']: 'faked'}, 'revision': listing['revision']})
        assert refused.status_code == 409 and refused.json()['code'] == 'branch_point_invalid'

        applied = client.post('/agent/history/apply',
                              json={'manifest': drop, 'rewrites': reword, 'revision': listing['revision']}).json()
        assert applied['shaped'] is True and applied['rewrites'] == reword and applied['stage'] == 'reshaped'
        stale = client.post('/agent/history/apply', json={'manifest': drop, 'revision': 99})
        assert stale.status_code == 409 and stale.json()['code'] == 'history_changed'
        assert len(ws.threads.active.ai.history) >= 2, 'and the recorded turns are untouched'

def _logged_conversation(ws, sid='conv-n'):
    import json
    a = ws.ai
    log = history_file(ws)
    turns = [{'session': sid, 'at': 1, 'model': a.model.name, 'turn_id': f'{sid}:turn_000001',
              'prompt': 'q1', 'reply': 'r1',
              'activity': [{'tool': 'view_file', 'line': 'view_file a.py', 'detail': 'contents',
                            'action_id': 'act1', 'ok': True}]},
             {'session': sid, 'at': 2, 'model': a.model.name, 'turn_id': f'{sid}:turn_000002',
              'prompt': 'q2', 'reply': 'r2'}]
    log.write_text('\n'.join(json.dumps(x) for x in turns) + '\n')
    return sid


def test_a_conversation_opens_as_a_notebook_and_its_edits_come_back_as_one_branch(tmp_path):
    """Editing a conversation in the editor a person already knows, rather than in a dialog of its own."""
    import json
    from leela.workspace import Workspace
    ws = Workspace(roots=[tmp_path]); ws.add_root(str(tmp_path))
    sid = _logged_conversation(ws)
    with TestClient(ide_app(ws)) as client:
        client.post('/agent/resume', json={'session': sid})
        made = client.post('/agent/conversation/notebook', json={'session': sid}).json()
        assert made['parts'] == 6 and made['path'].endswith('.ipynb')

        raw = json.loads(Path(made['path']).read_text())
        tagged = [c for c in raw['cells'] if c.get('metadata', {}).get('leela', {}).get('part_id')]
        assert len(tagged) == 6, 'a cell per part, each carrying the part it stands for'
        assert raw['cells'][0]['metadata'].get('leela', {}).get('part_id') is None, 'plus a heading'

        # delete the call and its result; reword the first question
        keep = [c for c in raw['cells']
                if c.get('metadata', {}).get('leela', {}).get('part_kind') not in ('call', 'result')]
        for cell in keep:
            leela = cell.get('metadata', {}).get('leela', {})
            if leela.get('part_kind') == 'user' and 'q1' in ''.join(cell['source']):
                cell['source'] = [cell['source'][0], 'my much better q1']
        raw['cells'] = keep
        Path(made['path']).write_text(json.dumps(raw))

        out = client.post('/agent/conversation/reshape',
                          json={'session': sid, 'path': made['path'], 'revision': made['revision']}).json()
        assert out['discarded'] == [f'{sid}:turn_000001:1', f'{sid}:turn_000001:2'], 'the pair went together'
        assert out['rewritten'] == [f'{sid}:turn_000001:0'] and out['shaped'] is True
        assert len(ws.threads.active.ai.history) >= 2, 'and the recorded turns are untouched'


def test_a_notebook_we_cannot_read_does_not_erase_the_conversation(tmp_path):
    """Every part missing from the notebook is a part discarded, so a notebook whose parts we failed to find would drop the entire conversation."""
    from leela.blocks.nb.nb import Notebook
    from leela.workspace import Workspace
    ws = Workspace(roots=[tmp_path]); ws.add_root(str(tmp_path))
    sid = _logged_conversation(ws, 'conv-blank')
    empty = tmp_path/'nothing.ipynb'; Notebook.blank().save(str(empty))
    with TestClient(ide_app(ws)) as client:
        client.post('/agent/resume', json={'session': sid})
        before = client.get('/agent/branches').json()['active']
        r = client.post('/agent/conversation/reshape', json={'session': sid, 'path': str(empty)})
        assert r.status_code == 409 and r.json()['code'] == 'branch_point_invalid'
        assert client.get('/agent/branches').json()['active'] == before


def test_history_lists_every_conversation_not_just_the_log_tail(tmp_path, monkeypatch):
    """The list was grouped from the turns in the log's last 8 MB, and pasted pictures made that about thirty turns."""
    import json, ramabana.agent as ra
    from leela.blocks.agent.turns import mark_surface
    ws = Workspace(roots=[tmp_path])
    log, pad = history_file(ws), 'x' * 400
    rows = [{'session': 'agent_old', 'at': 1, 'model': 'gpt-4.1', 'turn_id': 'agent_old:turn_000001', 'prompt': 'the old one', 'reply': 'r'}]
    rows += [{'session': 'agent_new', 'at': 10 + i, 'model': 'gpt-4.1', 'turn_id': f'agent_new:turn_{i:06d}',
              'prompt': f'{i} {pad}', 'reply': 'r'} for i in range(20)]
    rows += [{'session': 'agent_fake', 'at': 5, 'model': 'scripted', 'turn_id': 'agent_fake:turn_000001', 'prompt': 'a test', 'reply': 'r'}]
    log.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    for sid in ('agent_old', 'agent_new', 'agent_fake'): mark_surface(ws.ai.cfg, sid)
    monkeypatch.setattr(ra, 'HISTORY_TAIL', 2000)
    with TestClient(ide_app(ws)) as client:
        listed = [s['id'] for s in client.get('/agent/history').json()['sessions']]
        old = client.get('/agent/history/session?id=agent_old').json()
    assert listed[:2] == ['agent_new', 'agent_old'], 'a conversation older than the tail is missing'
    assert 'agent_fake' not in listed, 'a scripted conversation is listed, and opens empty'
    assert [t['prompt'] for t in old['turns']] == ['the old one'] and old['count'] == 1


def test_a_resumed_conversation_runs_on_the_model_picked_here(tmp_path):
    """Resuming adopted the model the conversation last ran: a reload put the pane on Opus while the picker named another."""
    ws = Workspace(roots=[tmp_path], model='gpt-4.1')
    picked = ws.threads.active.ai.model.name
    _log(ws, [{'session': 'agent_old', 'at': 1, 'model': 'claude-opus-5-5', 'turn_id': 'agent_old:turn_000001',
               'prompt': 'from the command line', 'reply': 'r'}])
    with TestClient(ide_app(ws)) as client:
        r = client.post('/agent/resume', json={'session': 'agent_old'}).json()
        assert r['ok'] and r['session'] == 'agent_old'
        assert ws.ai.model.name == picked, 'the turn runs on the pick, and the picker reads this'
        assert ws.ai.session_id == 'agent_old', 'on the conversation it resumed'
        # a model switch after the replay used to carry an empty conversation: right model, no context
        said = [m.get('content') for m in ws.ai._be('turn').snapshot_hist()]
        assert said == ['from the command line', 'r'], 'the resumed conversation is in the model context'
        client.post('/agent/command', json={'line': '/resume agent_old', 'thread': ws.ai.session_id})
        assert ws.ai.model.name == picked, 'the slash command resumes the same way'
        assert [m.get('content') for m in ws.ai._be('turn').snapshot_hist()] == said


def _log(ws, rows):
    "Write the conversation log the way the agent writes it, and forget what was parsed before."
    import json
    p = history_file(ws)
    p.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    ws._history_stamps.clear()
    return p


def test_the_pane_is_never_ready_while_a_prompt_would_be_refused(tmp_path):
    "One source of truth: what `/agent/status` and the conversation card say is what `start` does."
    ws = _threaded_workspace(tmp_path); thread = ws.threads.active
    leaked = {'id': 'leaked', 'event': threading.Event(), 'gate': threading.Event(),
              'accepted': False, 'run': '', 'error': None, 'at': time.time() - 41}
    leaked['gate'].set(); thread.runner._pending['leaked'] = leaked
    assert thread.state == 'working', 'the card cannot say idle while the gate is shut'
    with TestClient(ide_app(ws)) as client:
        d = client.get('/agent/status', params={'thread': thread.id}).json()
        assert d['busy'] is True and d['held']
        assert client.post('/agent/turn', json={'prompt': 'x', 'thread': thread.id}).status_code == 409
        client.post('/agent/stop', json={'thread': thread.id})
        clear = client.get('/agent/status', params={'thread': thread.id}).json()
        assert clear['held'] == '' and clear['busy'] is False


def test_a_stop_settles_the_feed_but_a_rejected_turn_says_nothing(tmp_path):
    """`_clear` drops the gate on a turn already running, which then read exactly like a turn nobody ever accepted: the worker returned without settling, and anything waiting on `finished` waited for ever."""
    from tests.fakemodel import Step
    ws = _scripted_workspace(tmp_path, [Step(text='thinking' * 40)], delay=.05)
    runner = ws.turn_runner
    with TestClient(ide_app(ws)) as client:
        client.post('/agent/turn', json={'prompt': 'where?'})
        assert client.post('/agent/stop', json={}).status_code == 200
        feed = runner.feed
        end = time.time() + 20
        while not feed.settled_seq and time.time() < end: time.sleep(.05)
        assert feed.settled_seq, 'a stopped turn left the feed unsettled'
        assert feed.finished(feed.seq)

    # the same flag, the other way round: `_clear` marks what it took off an accepted turn
    ready = {'id': 'x', 'accepted': True, 'gate': threading.Event()}
    runner._pending['x'] = ready
    runner._clear()
    assert ready['cleared'] is True and ready['accepted'] is False
    never = {'id': 'y', 'accepted': False, 'gate': threading.Event()}
    runner._pending['y'] = never
    runner._clear()
    assert never['cleared'] is False, 'a turn nobody accepted has nothing to settle'


def test_shaping_from_the_pane_previews_before_it_writes_and_survives_a_moved_branch(tmp_path):
    """What the dialog does, in the order it does it: read the parts, price a manifest, apply at the revision it was shown."""
    for ws, client in _answered_thread(tmp_path):
        parts = client.get('/agent/conversation/parts').json()['parts']
        assert parts and any(p['editable'] for p in parts), 'prose is what a person can rewrite'
        drop = {parts[-1]['part_id']: 'discard'}
        pv = client.post('/agent/history/preview', json={'manifest': drop}).json()
        assert pv['omitted'] == 1 and pv['tokens'] > 0 and pv['branch_id'] == 'main'

        stale = client.post('/agent/history/apply', json={'manifest': drop, 'revision': pv['revision'] + 5})
        assert stale.status_code == 409 and stale.json()['code'] == 'history_changed'
        assert client.get('/agent/branches').json()['active'] == 'main', 'and nothing was written'

        out = client.post('/agent/history/apply',
                          json={'branch_id': pv['branch_id'], 'revision': pv['revision'], 'manifest': drop}).json()
        assert out['ok'] and out['omitted'] == 1 and out['stage'] == 'reshaped'
        row = next(r for r in client.get('/agent/threads').json()['threads'] if r['id'] == ws.threads.active_id)
        assert row['branch'] == out['branch_id'], 'and the card says which branch the next turn uses'


def test_boot_picks_up_this_apps_newest_conversation_and_not_the_clis(tmp_path):
    """One log holds Leela's conversations and the ramabana CLI's, and most of it is the CLI's."""
    from leela.blocks.agent.turns import mark_surface, surfaces
    ws = Workspace(roots=[tmp_path]); model = ws.ai.model.name
    _log(ws, [{'session': 'agent_mine', 'turn_id': 'agent_mine:1', 'at': 10, 'model': model,
               'prompt': 'mine', 'reply': 'r1'},
              {'session': 'agent_cli', 'turn_id': 'agent_cli:1', 'at': 30, 'model': model,
               'prompt': 'theirs', 'reply': 'r2'}])
    mark_surface(ws.ai.cfg, 'agent_mine')
    try:
        with TestClient(ide_app(ws)) as client:
            d = client.post('/agent/resume', json={'session': 'latest'}).json()
            assert d['session'] == 'agent_mine', "the newest of this app's own, not of the log"
            assert 'agent_cli' not in surfaces(ws.ai.cfg), "and nothing adopted the CLI's"
            both = client.post('/agent/resume', json={'session': 'latest', 'everything': True}).json()
            assert both['session'] == 'agent_cli', "the filter off means the log's newest again"
    finally: ws.threads.shutdown()


def test_a_threads_opt_ins_survive_eviction_and_resume(tmp_path, monkeypatch):
    from tests.fakemodel import Step, install
    from leela.blocks.agent.ai import Assistant
    ws = Workspace(roots=[tmp_path]); ws._state_path = tmp_path/'workspace.json'
    t = ws.threads.new(optin=('exhash',)); sid = t.id
    install(ws, [Step(text='ok')], token_delay=0); t.ai.ask('first')
    ws.threads.close(sid); assert sid not in ws.threads._rows
    monkeypatch.setattr(Assistant, 'set_model', lambda self, name, job='turn': None)   # the scripted model is not in the catalog
    r = ws.threads.resume(sid)
    assert 'edit_file' in {f.__name__ for f in r.ai.tools} and r.dict()['optin'] == ['exhash']
    assert ws.thread_optins.get(sid) == ['exhash'], 'kept on the workspace'
    again = Workspace.load(ws._state_path)
    assert again.thread_optins.get(sid) == ['exhash'], 'and in its saved file, so a restart resumes the same catalog'
    assert 'edit_file' in {f.__name__ for f in again.threads.resume(sid).ai.tools}


def test_subagent_settings_outlive_the_conversation_that_set_them(tmp_path):
    """`/subagents nest 1` changed one live assistant; a new conversation and a reload went back to ramabana's defaults."""
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        for line in ('/subagents nest 1', '/subagents steps 20', '/subagents timeout 120'):
            assert client.post('/agent/command', json={'line': line}).json()['ok'], line
        assert (ws.subagent_depth, ws.subagent_steps, ws.subagent_timeout) == (1, 20, 120)
        ai = ws.threads.require(client.post('/agent/thread/new', json={}).json()['active']).ai
        assert (ai.subagent_depth, ai.subagent_steps, ai.subagent_timeout) == (1, 20, 120), 'a new conversation starts on them'
    back = Workspace(roots=[tmp_path]); back.restore_settings(ws.state())
    assert (back.subagent_depth, back.subagent_steps, back.subagent_timeout) == (1, 20, 120), 'and a reload keeps them'
    back.restore_settings({**ws.state(), 'subagent_depth': 'junk'})
    assert back.subagent_depth is None, 'a value that is not a number falls back to the default rather than failing the load'


