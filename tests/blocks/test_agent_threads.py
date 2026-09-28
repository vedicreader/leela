import asyncio, re, threading, time
from pathlib import Path

import pytest
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.blocks.runtime.kernels import KernelPool
from leela.blocks.agent.threads import Feed, Thread, Threads, TurnError, TurnRunner
from leela.workspace import Workspace
from tests.conftest import history_file


@pytest.fixture(autouse=True)
def _kernels_stay_in_process(monkeypatch):
    "These workspaces are built bare, and a turn warms a kernel: give them the fixture's fake ones rather than a real ipykernel per test."
    from tests.blocks.conftest import _FakeKernel
    async def _get(self, key, **kw): return self.kernels.setdefault(key, _FakeKernel())
    monkeypatch.setattr(KernelPool, 'get', _get)
    monkeypatch.setattr(KernelPool, 'peek', lambda self, key: self.kernels.get(key))


def test_threads_are_lazy_isolated_and_keep_workspace_compatibility(tmp_path):
    ws = Workspace(roots=[tmp_path])
    assert ws._threads is None and ws._ai is None
    first = ws.threads.active
    second = ws.threads.new()
    assert first.id != second.id and first.ai is not second.ai
    assert first.feed is not second.feed and first.approvals is not second.approvals
    assert ws.ai is second.ai and ws.approvals is second.approvals and ws.turn_runner is second.runner
    ws.threads.switch(first.id)
    assert ws.ai is first.ai and ws.pending_approval is first.approvals.pending


def test_six_thread_lru_protects_working_and_waiting_threads(tmp_path):
    ws = Workspace(roots=[tmp_path]); threads = ws.threads
    rows = [threads.active, *[threads.new() for _ in range(5)]]
    live = rows[0].ai._new_run('working')
    rows[1].approvals.current = type('Pending', (), {'pending': True})()
    victim = rows[2].id
    seventh = threads.new()
    assert len(threads.rows()) == 6 and threads.get(victim) is None and threads.active is seventh
    assert threads.get(rows[0].id) is rows[0] and threads.get(rows[1].id) is rows[1]
    live.finish()
    from unittest.mock import patch
    with patch.object(Thread, 'state', new_callable=lambda: property(lambda self: 'working')):
        try: threads.new()
        except TurnError as e: assert e.code == 'no_evictable_thread'
        else: assert False


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


def test_feed_wait_wakes_for_events_and_close():
    feed, seen = Feed('thread-1'), []
    waiter = threading.Thread(target=lambda: seen.extend(feed.wait(0, 2)))
    waiter.start(); feed.emit('state', {'state': 'working'}); waiter.join()
    assert seen[0]['event'] == 'state'
    seen.clear(); waiter = threading.Thread(target=lambda: seen.extend(feed.wait(feed.seq, 2)))
    waiter.start(); time.sleep(.01); feed.close(); waiter.join()
    assert seen == [] and feed.closed


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


def test_runner_captures_acceptance_values_and_outlives_subscribers():
    ws, feed = _Workspace(), Feed()
    runner = TurnRunner(ws, feed)
    attachments = ['a.png']
    accepted = runner.start('question', attachments)
    attachments.append('later.png')
    end = time.time() + 2
    while not any(row['event'] == 'done' for row in feed.since(0)) and time.time() < end: time.sleep(.01)
    assert ws.seen == ('a.png',)
    assert accepted == {'ok': True, 'thread': 'thread-1', 'run': 'run-1', 'seq': 1}
    assert [row['event'] for row in feed.since(0)][0] == 'user'
    events = [row['event'] for row in feed.since(0)]
    assert events[0] == 'user' and events[-3:] == ['done', 'title', 'state']
    assert [row['event'] for row in ws.timeline] == ['chunk']


def test_the_watcher_leaves_the_previous_turns_calls_out_of_this_one():
    """`on_registered` fires before `_prepare` marks the turn, so the mark the watcher's first poll reads is the turn before this one's."""
    from ramabana.agent import Activity
    class Late(_Workspace):
        def __init__(self):
            super().__init__()
            self.ai.activity = Activity()
            self.ai.activity.start('view', {'path': 'old.py'}, action_id='old-1', turn_id='turn-1')
        def ask_stream(self, prompt, attachments=(), on_registered=None, **kwargs):
            on_registered(self.ai._run)
            self.ai.current_turn_id = 'turn-2'; self.ai.activity.mark('turn-2')
            self.ai.activity.start('grep', {'q': 'new'}, action_id='new-1', turn_id='turn-2')
            time.sleep(.25)
            yield 'answer'
            self.ai._run.terminal = True
    ws, feed = Late(), Feed()
    TurnRunner(ws, feed).start('make it succinct, no tool calls')
    end = time.time() + 3
    while not any(row['event'] == 'done' for row in feed.since(0)) and time.time() < end: time.sleep(.01)
    seen = [row['data'].get('id') for row in feed.since(0) if row['event'] == 'activity']
    assert seen == ['new-1'], seen
    assert [row['data'].get('id') for row in ws.timeline if row['event'] == 'activity'] == ['new-1']


def test_a_turn_that_died_before_it_was_prepared_keeps_the_previous_turns_timeline():
    """`save_timeline` files under `ai.current_turn_id`, which only becomes this turn's inside `_prepare`."""
    class Early(_Workspace):
        def __init__(self): super().__init__(); self.saved = []
        def save_timeline(self, thread_id, turn_id, parts):
            self.saved.append((turn_id, [row['event'] for row in parts])); return list(parts)
        def ask_stream(self, prompt, attachments=(), on_registered=None, **kwargs):
            on_registered(self.ai._run); self.ai._run.terminal = True
            raise RuntimeError('the model would not start')
            yield
    ws, feed = Early(), Feed()
    TurnRunner(ws, feed).start('and the tests')
    end = time.time() + 3
    while not any(row['event'] == 'done' for row in feed.since(0)) and time.time() < end: time.sleep(.01)
    assert ws.saved == [], ws.saved
    assert [row['event'] for row in feed.since(0)][-3:] == ['error', 'done', 'state']


def test_accepted_worker_failure_emits_error_then_done():
    class Broken(_Workspace):
        def ask_stream(self, *args, on_registered=None, **kwargs):
            on_registered(self.ai._run); yield 'started'
            raise RuntimeError('provider broke')
    ws, feed = Broken(), Feed()
    accepted = TurnRunner(ws, feed).start('question')
    end = time.time() + 2
    while not any(row['event'] == 'done' for row in feed.since(accepted['seq'])) and time.time() < end: time.sleep(.01)
    rows = feed.since(accepted['seq']); events = [row['event'] for row in rows]
    error, done = events.index('error'), events.index('done')
    assert error < done < len(events) - 1 and events[-1] == 'state'
    assert rows[error]['data']['message'] == 'RuntimeError: provider broke', 'the class of the failure is part of it'
    assert {'note', 'media', 'usage', 'model', 'turn_id', 'branch_id', 'capabilities',
        'problems', 'activity', 'edits'} <= rows[done]['data'].keys()


def test_registration_accepts_before_the_first_chunk():
    release, registered, result = threading.Event(), threading.Event(), {}
    class Delayed(_Workspace):
        def ask_stream(self, prompt, attachments=(), on_registered=None, **kwargs):
            def stream():
                on_registered(self.ai._run); registered.set(); release.wait(); yield 'late'
            return stream()
    ws, feed = Delayed(), Feed(); runner = TurnRunner(ws, feed)
    worker = threading.Thread(target=lambda: result.setdefault('accepted', runner.start('question')))
    worker.start(); assert registered.wait(.2); worker.join(.2)
    assert not worker.is_alive() and result['accepted']['run'] == 'run-1'
    events = [row['event'] for row in feed.since(0)]
    assert events[0] == 'user' and 'chunk' not in events
    release.set()


def test_start_timeout_cancels_a_run_that_registers_late():
    release = threading.Event()
    class Delayed(_Workspace):
        def ask_stream(self, *args, on_registered=None, **kwargs):
            release.wait(); on_registered(self.ai._run); yield 'late'
    ws, feed = Delayed(), Feed()
    runner = TurnRunner(ws, feed); runner.start_timeout = .02
    try: runner.start('question')
    except TurnError as e: assert e.code == 'turn_conflict'
    else: assert False
    release.set()
    end = time.time() + 2
    while not ws.ai._run.terminal and time.time() < end: time.sleep(.01)
    assert ws.ai._run.terminal and feed.since(0) == []


def test_a_second_turn_is_rejected_while_the_first_is_pending_registration():
    release, result = threading.Event(), {}
    class Delayed(_Workspace):
        def ask_stream(self, *args, on_registered=None, **kwargs):
            release.wait(); on_registered(self.ai._run); yield 'late'
    ws = Delayed(); runner = TurnRunner(ws)
    worker = threading.Thread(target=lambda: result.setdefault('accepted', runner.start('first')))
    worker.start()
    # Generous, because what is being tested is the refusal, not how fast a thread is scheduled: a
    # one second bound failed twice in a loaded suite and passed every time on its own.
    end = time.time() + 5
    while not runner._pending and time.time() < end: time.sleep(.005)
    assert runner._pending, 'precondition: the first turn is registered'
    try: runner.start('second')
    except TurnError as e: assert e.code == 'thread_busy'
    else: assert False
    release.set(); worker.join(1)
    assert not worker.is_alive() and result['accepted']['run'] == 'run-1'


def _pending_entry(worker):
    "The record `start` publishes, with `worker` as the thread that has yet to speak."
    return {'id': 'x', 'event': threading.Event(), 'gate': threading.Event(),
            'accepted': False, 'run': '', 'error': None, 'at': time.time(), 'worker': worker}


def test_a_pending_turn_is_not_reaped_before_its_worker_starts():
    """`start` publishes the pending turn and only then starts the worker."""
    ws = _Workspace(); runner = TurnRunner(ws)
    runner._pending['x'] = _pending_entry(threading.Thread(target=lambda: None))
    assert runner._reap(ws.ai) == [], 'an unstarted worker is not a finished one'
    assert 'x' in runner._pending, 'and the turn it is setting up still holds the thread'


def test_a_pending_turn_whose_worker_finished_is_reaped():
    "The other half: once the worker has run and gone, nothing is running and the turn clears."
    ws = _Workspace(); runner = TurnRunner(ws)
    worker = threading.Thread(target=lambda: None); worker.start(); worker.join()
    runner._pending['x'] = _pending_entry(worker)
    assert runner._reap(ws.ai) == ['x'] and not runner._pending


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
    except TurnError as e: assert e.code == 'turn_conflict' and 'send it again' in e.message
    else: assert False
    assert runner._pending == {}, 'the refused turn does not keep the slot'
    assert not ws.ai.busy, 'nor the run it registered before it hung'
    assert runner.start('second')['run'] == 'run-1'
    assert [row['event'] for row in feed.since(0)][0] == 'user'
    hold.set()


def test_stop_clears_a_pending_turn_whose_starter_has_gone():
    "The control a person reaches for when the pane is stuck is the one that unwedges it."
    ws = _Workspace(); runner = TurnRunner(ws)
    leaked = {'id': 'leaked', 'event': threading.Event(), 'gate': threading.Event(),
              'accepted': False, 'run': '', 'error': None, 'at': time.time() - 41}
    leaked['gate'].set(); runner._pending['leaked'] = leaked
    try: runner.start('question')
    except TurnError as e: assert e.code == 'thread_busy' and re.search(r'started 4\ds ago', e.message) and 'stop' in e.message
    else: assert False
    assert runner.stop()['cleared'] == 1
    assert runner._pending == {} and runner.start('second')['run'] == 'run-1'


def test_a_stream_that_ends_before_reporting_a_run_says_why_at_once():
    """Ramabana's `stream` returns before `on_registered` when the backend will not load, so the turn used to expire on the full start window with the reason sitting unread in `note`."""
    class Unavailable(_Workspace):
        def ask_stream(self, *args, on_registered=None, **kwargs):
            self.ai.note = 'gpt-5.6-sol unavailable (RuntimeError: simulated provider outage)'
            yield self.ai.note
    ws, feed = Unavailable(), Feed(); runner = TurnRunner(ws, feed); runner.start_timeout = 5
    started = time.time()
    try: runner.start('question')
    except TurnError as e: assert e.code == 'turn_conflict' and 'simulated provider outage' in e.message
    else: assert False
    assert time.time() - started < 1, 'the reason was there to be reported, not waited out'
    assert runner._pending == {} and feed.since(0) == []


def test_a_worker_is_not_parked_forever_when_the_starter_raises():
    "An exit from `start` that misses the gate must cost that turn, not the conversation."
    class Exploding(Feed):
        def emit(self, event, data=None):
            if event == 'user': raise RuntimeError('the pane went away')
            return super().emit(event, data)
    ws, feed = _Workspace(), Exploding(); runner = TurnRunner(ws, feed); runner.start_timeout = .05
    try: runner.start('question')
    except RuntimeError: pass
    else: assert False
    end = time.time() + 2
    while runner._pending and time.time() < end: time.sleep(.01)
    assert runner._pending == {} and ws.ai._run.terminal


def test_the_stop_route_clears_a_wedged_pane(tmp_path):
    "Every route a person can reach the wedge from: send is refused, and stop is what frees it."
    ws = _threaded_workspace(tmp_path); thread = ws.threads.active
    leaked = {'id': 'leaked', 'event': threading.Event(), 'gate': threading.Event(),
              'accepted': False, 'run': '', 'error': None, 'at': time.time() - 41}
    leaked['gate'].set(); thread.runner._pending['leaked'] = leaked
    with TestClient(ide_app(ws)) as client:
        refused = client.post('/agent/turn', json={'prompt': 'question', 'thread': thread.id})
        assert refused.status_code == 409 and refused.json()['code'] == 'thread_busy'
        assert 'stop' in refused.json()['message']
        stopped = client.post('/agent/stop', json={'thread': thread.id})
        assert stopped.json()['ok'] and stopped.json()['cleared'] == 1
    assert thread.runner._pending == {}


def test_stop_cancels_a_live_turn_without_dropping_it():
    "Stopping a turn that is running is still a cancel the worker unwinds from, not an eviction."
    release, result = threading.Event(), {}
    class Live(_Workspace):
        def ask_stream(self, *args, on_registered=None, **kwargs):
            on_registered(self.ai._run); yield 'chunk'; release.wait(5)
    ws = Live(); runner = TurnRunner(ws)
    accepted = runner.start('question')
    end = time.time() + 2
    while not any(r['event'] == 'chunk' for r in runner.feed.since(0)) and time.time() < end: time.sleep(.01)
    assert runner.stop(accepted['run'])['cleared'] == 0
    assert list(runner._pending) and ws.ai._run.terminal, 'the run was cancelled, the turn left to unwind'
    release.set()
    while runner._pending and time.time() < end: time.sleep(.01)
    assert runner._pending == {}


def test_stop_leaves_a_live_sub_agent_of_a_finished_root_alone(tmp_path):
    "`busy` with nothing pending is a delegation still running; stop must not lie about clearing it."
    ws = _threaded_workspace(tmp_path); thread = ws.threads.active
    root = thread.ai._new_run('delegated'); child = root.child('sub')
    root.finish()
    assert thread.ai.busy and thread.runner._pending == {}
    thread.runner.stop('nothing')
    assert not child.terminal, 'the sub-agent has its own controls, and stop is not one of them'
    child.finish()


def test_close_wakes_a_turn_waiting_for_registration():
    release, result = threading.Event(), {}
    class Delayed(_Workspace):
        def ask_stream(self, *args, on_registered=None, **kwargs):
            release.wait(); on_registered(self.ai._run); yield 'late'
    ws = Delayed(); runner = TurnRunner(ws)
    worker = threading.Thread(target=lambda: result.setdefault('error', _start_error(runner)))
    worker.start(); time.sleep(.01); runner.close(); worker.join(1); release.set()
    assert not worker.is_alive() and result['error'].code == 'thread_closed'


def _start_error(runner):
    try: runner.start('question')
    except TurnError as e: return e


def test_closed_feed_rejects_registration_and_cancels_the_run():
    ws, feed = _Workspace(), Feed(); feed.close()
    try: TurnRunner(ws, feed).start('question')
    except TurnError as e: assert e.code == 'thread_closed' and e.run == 'run-1'
    else: assert False
    end = time.time() + 2
    while not ws.ai._run.terminal and time.time() < end: time.sleep(.01)
    assert ws.ai._run.terminal and feed.since(0) == []


def test_completion_metadata_failure_still_emits_one_done():
    class Broken(_Workspace):
        def ask_stream(self, prompt, attachments=(), on_registered=None, **kwargs):
            def stream():
                on_registered(self.ai._run); yield 'answer'
                self.ai._run.terminal = True
            return stream()
    ws, feed = Broken(), Feed()
    ws.ai.turn_use = type('BrokenUsage', (), {'dict': lambda self: 1/0})()
    accepted = TurnRunner(ws, feed).start('question')
    end = time.time() + 2
    while not feed.finished(feed.seq) and time.time() < end: time.sleep(.01)
    done = [row for row in feed.since(accepted['seq']) if row['event'] == 'done']
    assert len(done) == 1 and done[0]['data']['problems']


def test_thread_routes_create_switch_title_close_and_isolate(tmp_path):
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        first = client.get('/agent/threads').json(); first_id = first['active']
        second = client.post('/agent/thread/new', json={}).json(); second_id = second['active']
        assert first_id != second_id
        assert client.get('/agent/threads').json()['threads'] == [], \
            'two conversations nobody has spoken in are not two of a person\'s conversations'
        titled = client.post('/agent/thread/title', json={'thread': first_id, 'title': 'First work'}).json()
        assert titled['thread']['title'] == 'First work' and ws.threads.active_id == second_id
        listed = client.get('/agent/threads').json()['threads']
        assert [row['id'] for row in listed] == [first_id], 'naming one is saying something in it'
        switched = client.post('/agent/thread/switch', json={'thread': first_id}).json()
        assert switched['active'] == first_id and ws.ai.session_id == first_id
        closed = client.post('/agent/thread/close', json={'thread': second_id}).json()
        assert closed['closed'] == second_id and ws.threads.get(second_id) is None
        assert ws._ai is ws.ai and ws._turn_runner is ws.turn_runner
        stale = client.post('/agent/thread/switch', json={'thread': second_id})
        assert stale.status_code == 409 and stale.json()['code'] == 'thread_not_found' and ws.threads.active_id == first_id


def test_a_steer_is_kept_with_the_turn_it_interrupted(tmp_path):
    """`Feed.for_run` already named `steer` among the events a turn is rebuilt from, but the route emitted it with no run on it, so the filter never matched and the steer was dropped from the saved timeline."""
    feed = Feed('thread-1')
    feed.emit('chunk', {'text': 'thinking', 'run': 'run-1'})
    feed.emit('steer', {'text': 'use the other file', 'queued_steer': 'use the other file', 'run': 'run-1'})
    feed.emit('steer', {'text': 'somebody else', 'run': 'run-2'})
    feed.emit('state', {'run': 'run-1'})
    kept = feed.for_run('run-1')
    assert [r['event'] for r in kept] == ['chunk', 'steer'], 'state is live-only; the other run is not ours'
    assert kept[1]['data']['text'] == 'use the other file'

def test_the_steer_route_stamps_the_run_the_steer_belongs_to(tmp_path):
    "Queued, forced or cancelled: each is part of a turn, and the timeline is filtered by run."
    from starlette.testclient import TestClient
    from leela.app import ide_app
    ws = _threaded_workspace(tmp_path)
    thread = ws.threads.active
    run = thread.ai._new_run('working')
    with TestClient(ide_app(ws)) as client:
        client.post('/agent/steer', json={'text': 'try the other branch'})
        client.post('/agent/steer', json={'cancel': True})
        stamped = [dict(r['data']) for r in thread.feed.rows if r['event'] == 'steer']
    assert stamped and all(d.get('run') == run.id for d in stamped), stamped
    assert [d['text'] for d in stamped] == ['try the other branch', '']
    run.finish()

def test_an_untouched_conversation_holds_no_card_until_something_is_said_in_it(tmp_path):
    """Empty `new conversation` rows piled up in the switcher."""
    ws = _threaded_workspace(tmp_path)
    fresh = ws.threads.active
    assert ws.threads.dicts() == [], 'nothing has been said in it'
    assert ws.threads.attention()['threads'] == 1, 'but it is live, and the eviction board counts it'
    fresh.opener = 'rename the widget'
    assert [d['id'] for d in ws.threads.dicts()] == [fresh.id], 'the first prompt is a conversation'

def test_a_conversation_is_shown_once_it_is_named_unread_or_working(tmp_path):
    "Each of these is something having happened in it, and any one of them earns the card."
    ws = _threaded_workspace(tmp_path)
    thread = ws.threads.active
    assert ws.threads.dicts() == []
    thread.title = 'A name a person chose'
    assert len(ws.threads.dicts()) == 1
    thread.title = ''; thread.unread = 2
    assert len(ws.threads.dicts()) == 1, 'a turn finished in it while nobody was watching'
    thread.unread = 0
    run = thread.ai._new_run('working')
    assert len(ws.threads.dicts()) == 1, 'and one that is working is never hidden'
    run.finish()

def test_a_resumed_conversation_is_named_by_its_log_so_it_keeps_its_card(tmp_path):
    "Resuming builds a thread with no opener of its own; the log it was resumed from is its name."
    import json
    ws = Workspace(roots=[tmp_path]); ws.add_root(str(tmp_path))
    thread = ws.threads.active
    log = history_file(ws)
    log.write_text(json.dumps({'session': thread.id, 'at': 1, 'model': 'gpt-4.1',
                               'turn_id': f'{thread.id}:turn_000001',
                               'prompt': 'plot the release cadence', 'reply': 'done'}) + '\n')
    ws.ai.refresh_history()
    assert [d['title'] for d in ws.threads.dicts()] == ['plot the release cadence']

def test_resuming_an_already_live_session_activates_its_existing_thread(tmp_path):
    ws = Workspace(roots=[tmp_path]); first = ws.threads.active; ws.threads.new()
    assert ws.threads.resume(first.id) is first and ws.threads.active_id == first.id


def test_turn_routes_validate_accept_and_replay(tmp_path):
    (tmp_path/'a').write_text('attached')
    ws = Workspace(roots=[tmp_path])
    feed = Feed('thread-1')
    class Runner:
        def __init__(self): self.feed = feed; self.call = None
        def held(self): return ''
        def start(self, prompt, attachments, reasoning, context, context_path, grounding):
            self.call = (prompt, tuple(attachments), reasoning)
            feed.emit('user', {'text': prompt, 'run': 'run-1'})
            feed.emit('chunk', {'text': 'answer', 'run': 'run-1'})
            feed.emit('done', {'ok': True, 'run': 'run-1'})
            feed.emit('title', {'title': 'Question'}); feed.emit('state', {'runs': []}); feed.settle()
            return {'ok': True, 'thread': 'thread-1', 'run': 'run-1', 'seq': 1}
        def close(self): feed.close()
    ws._turn_runner = Runner()
    with TestClient(ide_app(ws)) as client:
        bad = client.post('/agent/turn', json={'prompt': '', 'attachments': []})
        assert bad.status_code == 400
        missing = client.post('/agent/turn', json={'prompt': 'question', 'attachments': ['missing.txt']})
        assert missing.status_code == 400 and ws._turn_runner.call is None
        for body in ([], {'prompt': 1}, {'prompt': 'question', 'reasoning': 1},
                     {'prompt': 'question', 'attachments': [1]}):
            assert client.post('/agent/turn', json=body).status_code == 400
        accepted = client.post('/agent/turn', json={'prompt': 'question', 'attachments': ['a'], 'reasoning': 'low'})
        assert accepted.json()['run'] == 'run-1' and ws._turn_runner.call == ('question', ('a',), 'low')
        replay = client.get('/agent/stream?since=0').text
        assert all(f'event: {event}' in replay for event in ('user', 'chunk', 'done', 'title', 'state'))
        assert replay.index('event: done') < replay.index('event: title') < replay.index('event: state')
        assert '"seq": 2' in replay
        assert client.get('/agent/stream?since=nope').status_code == 400
        latest = feed.seq
        assert client.get(f'/agent/stream?since={latest}').text == ''


def test_busy_runner_rejects_before_user_event():
    ws, feed = _Workspace(), Feed()
    ws.ai.busy = True
    try: TurnRunner(ws, feed).start('question')
    except TurnError as e: assert e.code == 'thread_busy'
    else: assert False
    assert feed.since(0) == []

def test_a_terminal_foreground_run_is_not_adopted_as_this_turn():
    """`Agent.run()` answers with the foreground root, which stays the last turn's until this one registers."""
    stale, live = _Run(), _Run()
    stale.id, stale.terminal, live.id = 'run-old', True, 'run-new'
    ws, feed = _Workspace(), Feed()
    ws.ai._run = stale
    def ask_stream(prompt, attachments=(), on_registered=None, **kwargs):
        ws.ai._run = live; on_registered(live)
        yield 'answer'
        live.terminal = True
    ws.ask_stream = ask_stream
    accepted = TurnRunner(ws, feed).start('question')
    assert accepted['run'] == 'run-new'
    assert {row['data'].get('run') for row in feed.since(0)} == {'run-new'}


def test_no_chunk_reaches_the_feed_before_the_turn_is_accepted():
    "A chunk ahead of `user` is a reply to a question the transcript has not shown yet."
    ws, feed = _Workspace(), Feed()
    ws.ai._run = _Run(); ws.ai._run.id = 'run-1'
    holder = {'run': None}
    def ask_stream(prompt, attachments=(), on_registered=None, **kwargs):
        holder['run'], ws.ai._run = ws.ai._run, None
        ws.ai._run = holder['run']; on_registered(ws.ai._run)
        yield 'answer'
        ws.ai._run.terminal = True
    ws.ask_stream = ask_stream
    accepted = TurnRunner(ws, feed).start('question')
    end = time.time() + 2
    while not any(r['event'] == 'done' for r in feed.since(0)) and time.time() < end: time.sleep(.01)
    events = [row['event'] for row in feed.since(0)]
    assert events[0] == 'user' and 'chunk' in events
    assert [row['data']['text'] for row in feed.since(0) if row['event'] == 'chunk'] == ['answer']
    assert accepted['seq'] == 1


def test_a_run_that_finished_is_announced_only_by_done():
    "`run` and `done` both ending the turn made one turn report itself twice."
    ws, feed = _Workspace(), Feed()
    TurnRunner(ws, feed).start('question')
    end = time.time() + 2
    while not any(r['event'] == 'done' for r in feed.since(0)) and time.time() < end: time.sleep(.01)
    assert [r['event'] for r in feed.since(0)].count('run') == 0

    ws2, feed2 = _Workspace(), Feed()
    ws2.ai._run.dict = lambda: {'id': 'run-1', 'state': 'cancelled', 'children': []}
    ws2.ai._run.state = 'cancelled'
    TurnRunner(ws2, feed2).start('question')
    end = time.time() + 2
    while not any(r['event'] == 'done' for r in feed2.since(0)) and time.time() < end: time.sleep(.01)
    assert [r['event'] for r in feed2.since(0)].count('run') == 1


def test_closing_a_workspace_that_never_built_an_assistant_builds_none():
    "`close()` reaching through `ws.ai` would start a model in order to shut one down."
    class Cold:
        _ai = None
        def __getattr__(self, name):
            if name == 'ai': raise AssertionError('the assistant was built during shutdown')
            raise AttributeError(name)
    feed = Feed('thread-1'); feed.emit('user', {'text': 'q'})
    TurnRunner(Cold(), feed).close()
    assert feed.closed


def test_an_approval_event_carries_the_tool_schemas_the_dialog_edits():
    "The dialog's tool picker is built from `schemas`; without them a call cannot be retargeted."
    from leela.blocks.agent.threads import tool_schemas
    from leela.workspace import Workspace
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        rows = tool_schemas(Workspace(roots=[d]).ai)
    assert rows and {'name', 'fields', 'group', 'changes_state'} <= rows[0].keys()
    runner = (Path(__file__).resolve().parents[2]/'leela/blocks/agent/threads.py').read_text()
    watch = runner[runner.index('def _watch('):runner.index('def _done(')]
    assert "'schemas': tool_schemas(ai)" in watch


def test_the_feed_wakes_an_awaiting_loop_without_a_worker_thread():
    "A subscriber blocking a shared pool thread for its whole wait is the starvation to avoid."
    feed = Feed('thread-1')
    async def read():
        rows = feed.anext(0, 2)
        threading.Timer(.02, lambda: feed.emit('chunk', {'text': 'hi'})).start()
        return await rows
    rows = asyncio.run(read())
    assert [row['event'] for row in rows] == ['chunk']
    assert asyncio.run(feed.anext(feed.seq, .05)) == []

def test_a_producer_that_never_settles_does_not_hold_a_finite_subscriber():
    """`settle()` ends a finite replay, and it is written by one caller."""
    from leela.workspace import Workspace
    import tempfile
    feed = Feed('thread-1')
    class Runner:
        def __init__(self): self.feed = feed
        def held(self): return ''
        def start(self, prompt, *args):
            user = feed.emit('user', {'text': prompt, 'run': 'run-1'})
            feed.emit('chunk', {'text': 'answer', 'run': 'run-1'})
            feed.emit('done', {'ok': True, 'run': 'run-1'})      # and never settles
            return {'ok': True, 'thread': 'thread-1', 'run': 'run-1', 'seq': user['seq']}
        def close(self): feed.close()
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(roots=[d]); ws._turn_runner = Runner()
        with TestClient(ide_app(ws)) as client:
            accepted = client.post('/agent/turn', json={'prompt': 'question'}).json()
            body = client.get('/agent/stream', params={'since': accepted['seq']}).text
    assert 'event: done' in body and not feed.finished(accepted['seq'])

def _scripted_workspace(tmp, steps, delay=0):
    "A real Workspace on a scripted model, so the runner is exercised against a real Assistant."
    from leela.workspace import Workspace
    from tests.fakemodel import Step, install
    ws = Workspace(roots=[tmp]); ws.add_root('.')
    install(ws, steps, token_delay=delay)
    return ws


def test_ordered_timeline_parts_survive_a_workspace_restart(tmp_path):
    first = Workspace(roots=[tmp_path]); first._timeline_path = tmp_path/'timeline.json'
    parts = [{'seq': 1, 'event': 'chunk', 'data': {'text': 'before'}},
             {'seq': 2, 'event': 'activity', 'data': {'id': 'call-1'}},
             {'seq': 3, 'event': 'chunk', 'data': {'text': 'after'}}]
    first.save_timeline('thread-1', 'turn-1', parts)
    second = Workspace(roots=[tmp_path]); second._timeline_path = tmp_path/'timeline.json'
    assert second.timeline_parts('thread-1', 'turn-1') == parts
    assert second.with_timelines([{'session': 'thread-1', 'turn_id': 'turn-1'}, {'session': 'thread-2', 'turn_id': 'turn-1'}]) == [
        {'session': 'thread-1', 'turn_id': 'turn-1', 'timeline': parts},
        {'session': 'thread-2', 'turn_id': 'turn-1'}]


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


def test_the_timeline_is_parsed_again_only_when_the_file_has_moved(tmp_path, monkeypatch):
    """Every reader parsed the whole document, which reaches several megabytes."""
    from fastcore.all import Path as FPath
    ws = Workspace(roots=[tmp_path]); ws._timeline_path = tmp_path/'timeline.json'
    ws.save_timeline('thread-1', 'turn-1', [{'seq': 1, 'event': 'chunk', 'data': {'text': 'held'}}])
    reads, real = [], FPath.read_json
    monkeypatch.setattr(FPath, 'read_json', lambda self, *a, **kw: (reads.append(self), real(self, *a, **kw))[1])
    ws.timeline_parts('thread-1', 'turn-1')
    ws.with_timelines([{'session': 'thread-1', 'turn_id': 'turn-1'}])
    assert reads == [], 'a reader parsed the file the writer already had in hand'
    ws._timeline_path.write_json({'thread-1:turn-1': [{'seq': 9, 'event': 'chunk', 'data': {'text': 'elsewhere'}}]})
    assert ws.timeline_parts('thread-1', 'turn-1')[0]['data']['text'] == 'elsewhere', \
        'a file that moved under it was not read again'
    assert len(reads) == 1


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


def test_stop_ends_a_server_owned_turn(tmp_path):
    "Nothing cancels on disconnect any more, so the explicit routes are the only way a turn ends."
    from tests.fakemodel import Step
    ws = _scripted_workspace(tmp_path, [Step(text='thinking' * 40)], delay=.05)
    with TestClient(ide_app(ws)) as client:
        accepted = client.post('/agent/turn', json={'prompt': 'where?'}).json()
        assert client.post('/agent/stop', json={}).status_code == 200
        feed = ws.turn_runner.feed
        end = time.time() + 20
        while not feed.settled_seq and time.time() < end: time.sleep(.05)
        assert feed.settled_seq and feed.finished(feed.seq)
        assert ws.ai.runs(active=True) == []


def test_a_per_run_cancel_ends_a_server_owned_turn(tmp_path):
    from tests.fakemodel import Step
    ws = _scripted_workspace(tmp_path, [Step(text='thinking' * 40)], delay=.05)
    with TestClient(ide_app(ws)) as client:
        accepted = client.post('/agent/turn', json={'prompt': 'where?'}).json()
        cancelled = client.post(f"/agent/runs/{accepted['run']}/cancel", json={}).json()
        assert cancelled['ok'] and cancelled.get('state') in ('cancelled', 'detached', 'terminated', 'cancelling')
        feed = ws.turn_runner.feed
        end = time.time() + 20
        while not feed.settled_seq and time.time() < end: time.sleep(.05)
        assert feed.settled_seq and feed.finished(feed.seq)
        assert ws.ai.runs(active=True) == []


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

def test_closing_the_pool_does_not_wait_for_a_kernel_that_never_comes_up():
    "A kernel still starting when the workspace shuts down is cancelled, not awaited, so leaving the app cannot hang on it."
    async def go():
        pool = KernelPool()
        stuck = pool._starting['tab:1'] = asyncio.ensure_future(asyncio.Event().wait())
        await asyncio.wait_for(pool.close_all(), 5)
        return stuck.cancelled()
    assert asyncio.run(go())


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


def test_a_run_stopped_in_one_thread_leaves_the_other_running(tmp_path):
    "Each thread owns its own run registry, so a run id is only meaningful inside its own thread."
    ws = _threaded_workspace(tmp_path)
    first, second = ws.threads.new(), ws.threads.new()
    a, b = first.ai._new_run('first'), second.ai._new_run('second')
    first.ai.cancel(a.id)
    assert a.terminal and not b.terminal
    assert second.ai.run(a.id) is None, 'and the other registry never heard of it'
    b.finish()


def test_an_approval_is_answered_only_in_the_thread_that_asked(tmp_path):
    "An id that collides across threads must not let one conversation answer another's checkpoint."
    ws = _threaded_workspace(tmp_path)
    first, second = ws.threads.new(), ws.threads.new()
    assert first.approvals is not second.approvals
    ws.threads.switch(first.id)
    assert ws.approvals is first.approvals and ws.pending_approval is None
    ws.threads.switch(second.id)
    assert ws.approvals is second.approvals


def test_a_switch_does_not_retarget_a_thread_already_resolved(tmp_path):
    """A request resolves its thread once, at the start."""
    ws = _threaded_workspace(tmp_path)
    first, second = ws.threads.new(), ws.threads.new()
    ws.threads.switch(first.id)
    held = ws.threads.require(first.id)          # what a route resolves before it awaits
    ws.threads.switch(second.id)
    assert ws.threads.active_id == second.id
    assert held is first and held.ai is first.ai, 'the resolved thread is still the one asked for'

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


def test_a_waiting_conversation_is_named_for_the_attention_surfaces(tmp_path):
    "The bar and the badge need to know which conversation wants a person, not just that one does."
    ws = _threaded_workspace(tmp_path)
    first, second = ws.threads.new(), ws.threads.new()
    assert ws.threads.waiting() == []
    with TestClient(ide_app(ws)) as client:
        assert client.get('/agent/approval').json()['waiting'] == []


def test_a_finished_turn_is_unread_only_for_a_conversation_nobody_was_watching(tmp_path):
    ws = _threaded_workspace(tmp_path)
    watched, background = ws.threads.new(), ws.threads.new()
    ws.threads.switch(watched.id)
    watched.finished_turn(); background.finished_turn(); background.finished_turn()
    assert watched.unread == 0 and background.unread == 2
    ws.threads.switch(background.id)
    assert background.unread == 0, 'looking at it is what makes it read'


def test_muting_survives_in_the_session_sidecar_and_does_not_hide_waiting(tmp_path):
    "A mute is about notifications. It must not make a conversation that wants a person look idle."
    ws = _threaded_workspace(tmp_path)
    thread = ws.threads.new()
    assert thread.dict()['muted'] is False
    ws.threads.mute(thread.id, True)
    assert thread.dict()['muted'] is True and thread.state == 'idle'
    assert ws.ai.session_meta(thread.id)['muted'] is True, 'and it is remembered where titles are'
    ws.threads.mute(thread.id, False)
    assert thread.dict()['muted'] is False


def test_the_attention_aggregate_names_what_wants_a_person(tmp_path):
    ws = _threaded_workspace(tmp_path)
    first, second = ws.threads.new(), ws.threads.new()
    # `TurnRunner` sets this the moment a turn starts; without it neither is a conversation yet
    first.opener, second.opener = 'the first thing', 'the second thing'
    ws.threads.switch(first.id)
    run = second.ai._new_run('working')
    a = ws.threads.attention()
    assert a['working'] == 1 and a['waiting'] == [] and a['threads'] == 2 and a['active'] == first.id
    run.finish()
    with TestClient(ide_app(ws)) as client:
        d = client.get('/agent/threads').json()
    assert d['attention']['threads'] == 2 and d['attention']['active'] == first.id
    assert {row['id'] for row in d['threads']} == {first.id, second.id}
    assert all({'unread', 'muted', 'state', 'title'} <= row.keys() for row in d['threads'])


def test_the_mute_route_refuses_a_conversation_that_is_gone(tmp_path):
    ws = _threaded_workspace(tmp_path)
    ws.threads.new()
    with TestClient(ide_app(ws)) as client:
        stale = client.post('/agent/thread/mute', json={'thread': 'thread_gone', 'muted': True})
    assert stale.status_code == 409 and stale.json()['code'] == 'thread_not_found'


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


def test_shaping_previews_before_it_writes_and_refuses_a_stale_revision(tmp_path):
    "Preview changes nothing. Apply commits one branch, and only at the revision it was shown."
    for ws, client in _answered_thread(tmp_path):
        turn = client.get('/agent/branches').json()['turns'][-1]['turn_id']
        parts = client.get(f'/agent/branch/parts?turn_id={turn}').json()['parts']
        drop = {parts[0]['part_id']: 'discard'}
        before = {b['branch_id'] for b in client.get('/agent/branches').json()['branches']}

        pv = client.post('/agent/history/preview', json={'turn_id': turn, 'manifest': drop}).json()
        assert pv['omitted'] == 1 and pv['kept'] == 1 and pv['tokens'] > 0
        assert pv['next_revision'] == pv['revision'] + 1 and pv['groups']
        assert {b['branch_id'] for b in client.get('/agent/branches').json()['branches']} == before, \
            'a preview is a question, not a change'

        applied = client.post('/agent/history/apply',
                              json={'turn_id': turn, 'revision': pv['revision'], 'manifest': drop}).json()
        assert applied['shaped'] is True and applied['omitted'] == 1 and applied['base_branch_id'] == 'main'
        assert applied['manifest'] == drop, 'and the manifest is what was persisted'

        stale = client.post('/agent/history/apply',
                            json={'turn_id': turn, 'revision': 99, 'manifest': drop})
        assert stale.status_code == 409 and stale.json()['code'] == 'history_changed'
        assert client.post('/agent/history/apply', json={'turn_id': turn, 'manifest': drop}).status_code == 400


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


def test_one_conversation_that_cannot_close_does_not_strand_the_others(tmp_path):
    """Shutting down is the one path that has to finish."""
    ws = _threaded_workspace(tmp_path)
    first, second, third = ws.threads.new(), ws.threads.new(), ws.threads.new()
    closed = []
    for thread in (first, second, third):
        thread.ai.close = lambda t=thread: closed.append(t.id)
    def boom(): raise RuntimeError('this root went away')
    second.ai.close = boom
    problems = ws.threads.shutdown()
    assert closed == [first.id, third.id], 'the ones that could close, did'
    assert any(second.id in p and 'this root went away' in p for p in problems), 'the one that could not is named'
    assert ws.threads._rows == {} and ws.threads.active_id == ''


def test_a_mute_that_could_not_be_written_says_so(tmp_path):
    """A mute is a promise about the next restart, so what is reported is what was written rather than what was asked for, and the reason it was not written travels with it."""
    ws = _threaded_workspace(tmp_path)
    thread = ws.threads.new()
    def refuse(*a, **k): raise OSError('read-only config')
    thread.ai.set_muted = refuse
    row = thread.mute(True).dict()
    assert row['muted'] is False, 'it did not stick, so it does not claim to be muted'
    assert 'read-only config' in row['problem']
    assert thread.muted is True, 'though the intent is held for this process'
    # the success path is pinned by test_muting_survives_in_the_session_sidecar_and_does_not_hide_waiting


def test_an_unknown_turn_cannot_become_the_one_that_is_undone(tmp_path):
    """The earliest turn was picked by position, and a turn nobody recognised scored -1, ahead of every real one, so a bad id in the list quietly became the turn that was undone."""
    for ws, client in _answered_thread(tmp_path):
        turn = client.get('/agent/branches').json()['turns'][-1]['turn_id']
        bad = client.post('/agent/undo-turn', json={'turn_ids': ['no-such-turn', turn]})
        assert bad.status_code == 409 and bad.json()['code'] == 'branch_point_invalid'
        assert 'no-such-turn' in bad.json()['message']
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


def test_a_finite_replay_of_an_idle_thread_does_not_block_on_the_keepalive(tmp_path):
    "A non-follow stream of a settled, idle thread returns at once, not after the keepalive poll."
    import time
    ws = _threaded_workspace(tmp_path)
    t = ws.threads.new()
    t.feed.emit('user', {'text': 'hi'})
    with TestClient(ide_app(ws)) as client:
        t0 = time.monotonic()
        body = client.get(f'/agent/stream?since=0&thread={t.id}').text
        dt = time.monotonic() - t0
    assert 'hi' in body
    assert dt < 5, f'idle finite replay took {dt:.1f}s; the keepalive wait is not being skipped'


def test_a_finite_subscriber_is_not_held_by_a_conversation_with_no_turn_running(tmp_path):
    "There is nothing left to settle, so waiting for a settlement would wait forever."
    ws = _threaded_workspace(tmp_path)
    thread = ws.threads.new()
    thread.feed.emit('chunk', {'text': 'partial'})
    with TestClient(ide_app(ws)) as client:
        body = client.get(f'/agent/stream?since=0&thread={thread.id}').text
    assert 'partial' in body and not thread.feed.settled_seq

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
        assert 'not prose' in refused.json()['message']

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
        assert 'nothing was changed' in r.json()['message']
        assert client.get('/agent/branches').json()['active'] == before


def test_a_turn_goes_to_the_conversation_the_browser_names(tmp_path):
    "The prompt used to follow whichever thread was activated last, so a second tab stole it."
    ws = Workspace(roots=[tmp_path])
    class Runner:
        def __init__(self, thread): self.thread, self.call, self.feed = thread, None, Feed(thread)
        def held(self): return ''
        def start(self, prompt, attachments, reasoning, context, context_path, grounding):
            self.call = prompt; return {'ok': True, 'thread': self.thread, 'run': 'run-1', 'seq': 1}
        def close(self): self.feed.close()
    first, second = ws.threads.active, ws.threads.new()
    first.runner, second.runner = Runner(first.id), Runner(second.id)
    with TestClient(ide_app(ws)) as client:
        sent = client.post('/agent/turn', json={'prompt': 'to the first', 'thread': first.id})
        assert sent.json()['thread'] == first.id
        assert first.runner.call == 'to the first' and second.runner.call is None
        assert ws.threads.active_id == second.id, 'naming a conversation is not switching to it'
        client.post('/agent/turn', json={'prompt': 'to whichever is on screen'})
        assert second.runner.call == 'to whichever is on screen'
        gone = client.post('/agent/turn', json={'prompt': 'nowhere', 'thread': 'thread_missing'})
        assert gone.status_code == 409 and gone.json()['code'] == 'thread_not_found'


def test_thread_turns_serve_one_conversation_and_where_its_feed_settled(tmp_path):
    "A pane that has never shown a conversation has no DOM to restore it from."
    ws = Workspace(roots=[tmp_path])
    first, second = ws.threads.active, ws.threads.new()
    first.ai.refresh_history = lambda: None
    first.ai.history = [{'session': first.id, 'prompt': 'mine', 'reply': 'hi', 'model': 'fake'},
                        {'session': second.id, 'prompt': 'not mine', 'reply': 'no', 'model': 'fake'}]
    first.feed.emit('user', {'text': 'mine'}); first.feed.emit('done', {'ok': True}); first.feed.settle()
    first.feed.emit('chunk', {'text': 'a turn that is still running'})
    with TestClient(ide_app(ws)) as client:
        d = client.get(f'/agent/thread/turns?thread={first.id}').json()
        assert [t['prompt'] for t in d['turns']] == ['mine'] and d['thread'] == first.id
        assert d['seq'] == 2, 'the running turn replays from settlement, so it is drawn once'
        assert ws.threads.active_id == second.id, 'reading a conversation does not switch to it'
        assert client.get('/agent/thread/turns').json()['thread'] == second.id
        assert client.get('/agent/thread/turns?thread=thread_missing').status_code == 409


def test_pane_routes_act_on_the_named_conversation_not_the_active_one(tmp_path):
    "Each of these read the active binding, so a switch anywhere moved what they acted on."
    ws = Workspace(roots=[tmp_path])
    first, second = ws.threads.active, ws.threads.new()
    calls = []
    first.ai.rollback_turn = lambda turn_id: {'turn_id': turn_id, 'files': {}, 'irreversible': []}
    first.ai.turn_transactions = {'turn-1': {'turn_id': 'turn-1', 'files': {}}}
    first.ai.command = lambda line: 'the first conversation answered'
    first.approvals.rollback = lambda id: 'edited.py'
    first.approvals.answer = lambda id, ok, note, session=False, tool=None, args=None: \
        calls.append(('answer', id)) or type('A', (), {'dict': lambda self: {'id': id, 'ok': ok}})()
    for ai in (second.ai,):
        ai.rollback_turn = ai.command = lambda *a, **k: (_ for _ in ()).throw(AssertionError('wrong thread'))
    with TestClient(ide_app(ws)) as client:
        rolled = client.post('/agent/rollback-turn', json={'turn_id': 'turn-1', 'thread': first.id})
        assert rolled.json() == {'ok': True, 'thread': first.id, 'turn_id': 'turn-1',
                                'paths': [], 'git': '', 'irreversible': []}
        tx = client.get(f'/agent/turn-transaction?turn_id=turn-1&thread={first.id}')
        assert tx.json()['transaction']['turn_id'] == 'turn-1'
        assert client.get('/agent/turn-transaction?turn_id=turn-1').status_code == 404, \
            'the active conversation has no such turn, and is no longer asked about one'
        tool = client.post('/agent/rollback-tool', json={'id': 'call-1', 'thread': first.id})
        assert tool.json() == {'ok': True, 'thread': first.id, 'path': 'edited.py'}
        said = client.post('/agent/command', json={'line': '/cost', 'thread': first.id})
        assert said.json()['text'] == 'the first conversation answered'
        answered = client.post('/agent/approve', json={'id': 'call-1', 'ok': True, 'thread': first.id})
        assert answered.json()['thread'] == first.id and calls == [('answer', 'call-1')]
        assert ws.threads.active_id == second.id, 'none of them switched the conversation'
        for path, body in (('/agent/rollback-turn', {'turn_id': 'turn-1'}), ('/agent/rollback-tool', {'id': 'x'}),
                           ('/agent/command', {'line': '/cost'}), ('/agent/approve', {'id': 'x'}),
                           ('/agent/tool-preview', {'tool': 'read_file', 'args': {}}),
                           ('/agent/retry-tool', {'tool': 'read_file', 'args': {}})):
            stale = client.post(path, json={**body, 'thread': 'thread_missing'})
            assert stale.status_code == 409 and stale.json()['code'] == 'thread_not_found', path


def test_agent_state_and_history_reach_every_live_conversation(tmp_path):
    "State is the workspace's. Re-briefing only the thread on screen left the others stale."
    ws = Workspace(roots=[tmp_path])
    first, second = ws.threads.active, ws.threads.new()
    seen = []
    first.ai.refresh = lambda: seen.append(first.id)
    second.ai.refresh = lambda: seen.append(second.id)
    with TestClient(ide_app(ws)) as client:
        done = client.post('/agent/state/activate', json={'text': 'Goal: ship it', 'layer': 'task'})
        assert done.json()['ok'] and set(seen) == {first.id, second.id}
        named = client.get(f'/agent/history?thread={first.id}').json()
        assert named['current'] == first.id and named['thread'] == first.id
        assert client.get('/agent/history').json()['current'] == second.id
        assert client.get('/agent/history?thread=thread_missing').status_code == 409


def test_a_thread_card_carries_the_name_the_history_picker_shows(tmp_path):
    """`Thread.dict` read the session sidecar alone, so a conversation the summariser had not named yet read as `conversation <id>` on its card while the picker showed the derived name."""
    import json
    ws = Workspace(roots=[tmp_path]); ws.add_root(str(tmp_path))
    thread = ws.threads.active
    log = history_file(ws)
    log.write_text(json.dumps({'session': thread.id, 'at': 1, 'model': 'gpt-4.1',
                               'turn_id': f'{thread.id}:turn_000001',
                               'prompt': 'ascii art for the ramabana CLI', 'reply': 'r'}) + '\n')
    ws.ai.refresh_history()
    assert not ws.ai.session_meta(thread.id)['title'], 'nothing has been summarised'
    named = {row['id']: row for row in ws.ai.sessions()}
    assert thread.dict()['title'] == named[thread.id]['title'] == 'ascii art for the ramabana CLI'
    with TestClient(ide_app(ws)) as client:
        rows = {row['id']: row for row in client.get('/agent/threads').json()['threads']}
        assert rows[thread.id]['title'] == named[thread.id]['title'], 'the card and the picker agree'
        # inside: leaving the client ends the lifespan, and this conversation stops being live
        ws.threads.title(thread.id, 'A name a person chose')
    assert thread.dict()['title'] == 'A name a person chose', 'a chosen name outranks the derived one'


def test_a_card_is_named_by_the_first_thing_said_in_it(tmp_path):
    "The summariser, the sidecar and the log all arrive late or not at all. The prompt is there now."
    ws = Workspace(roots=[tmp_path])
    thread = ws.threads.active
    assert thread.dict()['title'] == '', 'nothing has been said in it yet'
    feed = thread.feed
    class Runner:
        def __init__(self): self.feed = feed
        def held(self): return ''
        def close(self): feed.close()
    thread.runner = Runner()
    runner = TurnRunner(ws, feed, thread=thread)
    thread.opener = ''
    runner.thread = thread
    thread.opener = 'why does the regression cell have a duplicate heading line'
    assert thread.dict()['title'] == 'why does the regression cell have a duplicate heading line'
    thread.opener = '  padded\n\nand wrapped  ' + 'x' * 200
    assert thread.dict()['title'] == 'padded and wrapped ' + 'x' * 41, 'one line, and short enough to read'
    ws.threads.title(thread.id, 'A name I chose')
    assert thread.dict()['title'] == 'A name I chose', 'a chosen name still wins'


def test_the_turn_that_starts_a_conversation_names_it(tmp_path):
    ws = Workspace(roots=[tmp_path])
    thread = ws.threads.active
    feed = Feed(thread.id)
    started = {}
    def ask_stream(prompt, attachments=(), on_registered=None, **kw):
        run = thread.ai._new_run('working'); started['run'] = run
        on_registered(run)
        yield 'answer'
        run.finish()
    ws.ask_stream = ask_stream
    runner = TurnRunner(ws, feed, ai=thread.ai, approvals=thread.approvals, thread=thread)
    accepted = runner.start('name this conversation for me')
    assert accepted['ok'] and thread.opener == 'name this conversation for me'
    assert thread.dict()['title'] == 'name this conversation for me'
    runner.close()


def _log(ws, rows):
    "Write the conversation log the way the agent writes it, and forget what was parsed before."
    import json
    p = history_file(ws)
    p.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    ws._history_stamps.clear()
    return p


def test_the_history_list_carries_no_turns_and_is_computed_once_per_log(tmp_path):
    """All the turns of every conversation was 60MB of JSON and forty seconds once Leela and the CLI shared one log."""
    ws = Workspace(roots=[tmp_path])
    rows = [{'session': 'agent_a', 'turn_id': 'agent_a:1', 'at': 10, 'model': 'm', 'prompt': 'p1', 'reply': 'r1'},
            {'session': 'agent_a', 'turn_id': 'agent_a:2', 'at': 20, 'model': 'm', 'prompt': 'p2', 'reply': 'r2'},
            {'session': 'agent_b', 'turn_id': 'agent_b:1', 'at': 30, 'model': 'm', 'prompt': 'p3', 'reply': 'r3'}]
    _log(ws, rows)
    try:
        with TestClient(ide_app(ws)) as client:
            listed = client.get('/agent/history?everything=1').json()['sessions']
            found = {s['id']: s for s in listed}
            assert found['agent_a']['count'] == 2 and found['agent_b']['count'] == 1
            assert all(s['turns'] == [] for s in listed), 'no turn bodies in the list'
            one = client.get('/agent/history/session?id=agent_a').json()
            assert [t['turn_id'] for t in one['turns']] == ['agent_a:1', 'agent_a:2'] and one['count'] == 2
            assert client.get('/agent/history/session?id=nope').status_code == 404
            calls = []
            ws.ai.refresh_history = lambda: calls.append(1)
            client.get('/agent/history?everything=1'); client.get('/agent/history?everything=1')
            assert calls == [], 'an unchanged log is not parsed again'
            _log(ws, rows + [{'session': 'agent_b', 'turn_id': 'agent_b:2', 'at': 40, 'model': 'm',
                              'prompt': 'p4', 'reply': 'r4'}])
            client.get('/agent/history')
            assert calls == [1], 'and a changed one is'
    finally: ws.threads.shutdown()


def test_a_reread_of_the_log_waits_for_the_log_to_change(tmp_path):
    "Parsing it is linear in its size, and every history read was paying for it again."
    ws = Workspace(roots=[tmp_path])
    try:
        calls = []
        ws.ai.refresh_history = lambda: calls.append(1)
        _log(ws, [{'session': 'agent_a', 'turn_id': 'agent_a:1', 'at': 1, 'model': 'm'}])
        assert ws.fresh_history() is True and len(calls) == 1
        assert ws.fresh_history() is False and len(calls) == 1, 'the stamp is unchanged'
        assert ws.history_stamp().startswith(str(ws.ai.history_path))
        _log(ws, [{'session': 'agent_a', 'turn_id': 'agent_a:1', 'at': 1, 'model': 'm'},
                  {'session': 'agent_a', 'turn_id': 'agent_a:2', 'at': 2, 'model': 'm'}])
        assert ws.fresh_history() is True and len(calls) == 2
    finally: ws.threads.shutdown()

def test_a_turn_the_core_has_finished_with_stops_holding_the_conversation():
    """The reported wedge: `turn_000007` came back `Unavailable`, so the core had no active run and the pane painted ready, while the worker stayed in the provider's stream and the gate stayed shut for twenty minutes."""
    release = threading.Event()
    class Stuck(_Workspace):
        def ask_stream(self, *args, on_registered=None, **kwargs):
            on_registered(self.ai._run); yield 'chunk'; release.wait(5)
    ws = Stuck(); runner = TurnRunner(ws); runner.stale_after = .2
    accepted = runner.start('question')
    end = time.time() + 2
    while not any(r['event'] == 'chunk' for r in runner.feed.since(0)) and time.time() < end: time.sleep(.01)
    assert runner.held() and list(runner._pending), 'while it is fresh it is a turn, not a leak'
    time.sleep(.25)
    assert runner.held() == '', 'the core is running nothing, so nothing is holding the conversation'
    assert runner.start('second')['run'] == 'run-1', 'and the next prompt goes through'
    release.set()

def test_a_worker_that_has_exited_never_holds_the_gate():
    "An entry its worker can no longer pop is a leak, whatever the core says."
    ws = _Workspace(); runner = TurnRunner(ws)
    dead = threading.Thread(target=lambda: None); dead.start(); dead.join()
    leaked = {'id': 'leaked', 'event': threading.Event(), 'gate': threading.Event(), 'worker': dead,
              'accepted': True, 'run': 'run-1', 'error': None, 'at': time.time()}
    leaked['gate'].set(); runner._pending['leaked'] = leaked
    assert runner.held() == '' and runner._pending == {}

def test_stop_clears_a_turn_that_cancel_cannot_reach():
    """`cancel` reaches a turn between steps, so a worker parked in a provider's stream does not feel it."""
    release = threading.Event()
    class Stuck(_Workspace):
        def ask_stream(self, *args, on_registered=None, **kwargs):
            on_registered(self.ai._run); yield 'chunk'; release.wait(5)
    ws = Stuck(); runner = TurnRunner(ws)
    runner.start('question')
    end = time.time() + 2
    while not any(r['event'] == 'chunk' for r in runner.feed.since(0)) and time.time() < end: time.sleep(.01)
    assert runner.stop()['cleared'] == 1
    assert runner._pending == {} and runner.held() == ''
    assert runner.start('second')['run'] == 'run-1'
    release.set()

def test_the_pane_is_never_ready_while_a_prompt_would_be_refused(tmp_path):
    "One source of truth: what `/agent/status` and the conversation card say is what `start` does."
    ws = _threaded_workspace(tmp_path); thread = ws.threads.active
    leaked = {'id': 'leaked', 'event': threading.Event(), 'gate': threading.Event(),
              'accepted': False, 'run': '', 'error': None, 'at': time.time() - 41}
    leaked['gate'].set(); thread.runner._pending['leaked'] = leaked
    assert thread.state == 'working', 'the card cannot say idle while the gate is shut'
    with TestClient(ide_app(ws)) as client:
        d = client.get('/agent/status', params={'thread': thread.id}).json()
        assert d['busy'] is True and 'still holding this conversation' in d['held']
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

def test_every_branch_route_has_a_way_in_from_the_pane():
    """The four branch routes shipped with tests and no caller: forking and switching were reachable with curl and from nowhere in the app."""
    root = Path(__file__).resolve().parents[2]
    js = (root/'leela'/'static'/'lee-agent.js').read_text() + (root/'leela'/'static'/'lee-ide.js').read_text()
    for route in ('/agent/branches', '/agent/branch/parts', '/agent/branch/switch', '/agent/fork',
                  '/agent/conversation/parts', '/agent/history/preview', '/agent/history/apply'):
        assert route in js, f'{route} is served but never called'
    cards = (root/'leela'/'blocks'/'agent'/'live.js').read_text()
    assert 'data-thread-branches' in cards, 'a conversation card is where its branches are reached'
    assert "leeAgentBranches(id)" in cards, 'and the button has to be wired to the dialog'
    bar = (root/'leela'/'blocks'/'agent'/'approvals.js').read_text()
    assert "'Branch from here'" in bar and "hasAttribute('data-fork')" in bar, \
        'forking from one turn belongs beside undo and revise, on that turn'
    palette = (root/'leela'/'blocks'/'keys'/'palette.js').read_text()
    assert 'leeAgentBranches()' in palette and 'leeAgentShape()' in palette
    assert 'data-shape' in cards, 'shaping is a branch, so it is reached from the branches dialog too'


def test_a_conversation_card_names_the_branch_the_next_turn_continues_from(tmp_path):
    "Switching moves the model's context and not the transcript, so the card is what says where it is."
    for ws, client in _answered_thread(tmp_path):
        turn = client.get('/agent/branches').json()['turns'][-1]['turn_id']
        forked = client.post('/agent/fork', json={'turn_id': turn}).json()['branch_id']
        row = next(r for r in client.get('/agent/threads').json()['threads'] if r['id'] == ws.threads.active_id)
        assert row['branch'] == forked != 'main'
        client.post('/agent/branch/switch', json={'branch_id': 'main'})
        rows = client.get('/agent/threads').json()['threads']
        assert next(r for r in rows if r['id'] == ws.threads.active_id)['branch'] == 'main'


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


def test_boot_still_opens_something_when_no_conversation_carries_the_mark(tmp_path):
    """The mark is recent, so a person's own older conversations read as the CLI's."""
    ws = Workspace(roots=[tmp_path])
    _log(ws, [{'session': 'agent_old', 'turn_id': 'agent_old:1', 'at': 30, 'model': ws.ai.model.name,
               'prompt': 'before the mark existed', 'reply': 'r'}])
    try:
        with TestClient(ide_app(ws)) as client:
            d = client.post('/agent/resume', json={'session': 'latest'})
            assert d.status_code == 200 and d.json()['session'] == 'agent_old'
    finally: ws.threads.shutdown()


def test_the_boot_resume_asks_under_the_same_filter_as_the_history_list():
    "The preference is the client's, so the client is what has to send it."
    js = (Path(__file__).resolve().parents[2]/'leela'/'blocks'/'agent'/'live.js').read_text()
    boot = js.split('async function resumeLatestAgent()')[1].split('\n}')[0]
    assert 'everything: !leelaOnly()' in boot and 'agentPrefsReady()' in boot


def test_a_thread_takes_its_own_opt_ins_and_the_default_thread_takes_none(tmp_path):
    "A per-chat opt-in reaches that thread's catalog alone; `exhash` also earns its inlined skill there and nowhere else."
    ws = Workspace(roots=[tmp_path], model='gpt-4.1')       # a full window, so `budget.inline` admits the skill
    t, plain = ws.threads.new(optin=('exhash',)), ws.threads.new()
    names = lambda a: {f.__name__ for f in a.tools}
    assert 'edit_file' in names(t.ai) and 'edit_file' not in names(plain.ai)
    assert t.ai.optin == ('exhash',) and plain.ai.optin == () and t.dict()['optin'] == ['exhash'] and plain.dict()['optin'] == []
    has_skill = any(sk.name == 'exhash' for sk in t.ai.skills)
    assert ('\n## exhash\n' in t.ai.system_prompt()) is has_skill and '\n## exhash\n' not in plain.ai.system_prompt()
    ws.agent_optin = ('research',)
    assert 'research' in names(ws.threads.new().ai) and 'research' not in names(ws.threads.new(optin=()).ai), \
        'the workspace default seeds a thread that names none; an explicit empty list means none'


def test_the_new_thread_route_takes_opt_ins_and_the_optin_route_saves_the_default(ws):
    with TestClient(ide_app(ws)) as c:
        d = c.post('/agent/thread/new', json={'optin': ['research']}).json()
        assert d['ok'] and d['optin'] == ['research'] and d['thread']['optin'] == ['research']
        bad = c.post('/agent/thread/new', json={'optin': ['teleport']})
        assert bad.status_code == 400 and 'teleport' in bad.json()['error']
        r = c.post('/agent/optin', json={'optin': ['exhash']}).json()
        assert r['ok'] and r['optin'] == ['exhash'] and ws.agent_optin == ('exhash',)
        assert c.post('/agent/optin', json={'optin': ['teleport']}).status_code == 400 and ws.agent_optin == ('exhash',)
        d2 = c.post('/agent/thread/new', json={}).json()
        assert d2['optin'] == ['exhash'], 'a thread naming no opt-ins takes the workspace default'
        # `/agent/threads` lists only conversations something was said in; the rows themselves carry the opt-ins
        assert ws.threads.require(d['active']).dict()['optin'] == ['research'] and ws.threads.require(d2['active']).dict()['optin'] == ['exhash']


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


def test_a_threads_profile_survives_eviction_and_resume(tmp_path, monkeypatch):
    "Asked for in full on a local model, a conversation comes back in full; the row is the choice, kept only where it differs from the workspace default."
    from tests.fakemodel import Step, install
    from leela.blocks.agent.ai import Assistant
    ws = Workspace(roots=[tmp_path]); ws._state_path = tmp_path/'workspace.json'
    t = ws.threads.new(profile='full'); sid = t.id
    assert t.ai.spec_or_none().local and t.ai.profile == 'full' and 'inspect_python' in {f.__name__ for f in t.ai.tools}
    install(ws, [Step(text='ok')], token_delay=0); t.ai.ask('first')
    ws.threads.close(sid); assert sid not in ws.threads._rows
    monkeypatch.setattr(Assistant, 'set_model', lambda self, name, job='turn': None)   # the scripted model is not in the catalog
    r = ws.threads.resume(sid)
    assert r.ai.profile == 'full' and 'inspect_python' in {f.__name__ for f in r.ai.tools} and r.dict()['profile'] == 'full'
    assert ws.thread_profiles.get(sid) == 'full', 'kept on the workspace'
    again = Workspace.load(ws._state_path)
    assert again.thread_profiles.get(sid) == 'full' and again.threads.resume(sid).ai.profile == 'full', 'and in its saved file'
    assert ws.threads.new(profile='auto').id not in ws.thread_profiles, 'the workspace default needs no row'
    assert ws.threads.new().dict()['profile'] == 'small', 'a thread naming no profile takes the workspace default'
    ws.thread_profiles['agent_gone-long-ago'] = 'full'; ws.threads.new(profile='full')
    assert 'agent_gone-long-ago' not in ws.thread_profiles and sid in ws.thread_profiles, 'pruned like an opt-in row; a logged conversation stays'
    ws.restore_settings({'thread_profiles': {sid: 'huge'}}); assert ws.thread_profiles == {}, 'a saved profile this ramabana lacks is dropped'


def test_opt_in_rows_are_kept_only_for_conversations_that_differ_from_the_default_and_still_exist(tmp_path):
    ws = Workspace(roots=[tmp_path]); ws._state_path = tmp_path/'workspace.json'
    ws.agent_optin = ('research',)
    same = ws.threads.new(optin=('research',)); own = ws.threads.new(optin=('exhash',)); none = ws.threads.new(optin=())
    assert same.id not in ws.thread_optins, 'the workspace default needs no row'
    assert ws.thread_optins[own.id] == ['exhash'] and ws.thread_optins[none.id] == [], 'an explicit none differs from the default and is kept'
    ws.thread_optins['agent_gone-long-ago'] = ['exhash']
    ws.threads.new(optin=('exhash',))
    assert 'agent_gone-long-ago' not in ws.thread_optins and own.id in ws.thread_optins, 'a row for a conversation neither live nor in the log is pruned; live ones stay'
    assert 'agent_gone-long-ago' not in Workspace.load(ws._state_path).thread_optins
