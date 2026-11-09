import inspect, json, time
from types import SimpleNamespace

import pytest
from abhyasa import agent_tools as engine
from abhyasa.learner import temp_learning
from leela.blocks.agent.threads import TurnError
from leela.blocks.learn.tools import learn_tools, register_learn_jobs
from tests.fakemodel import WIDE, install


@pytest.fixture
def learn_thread(ws, monkeypatch):
    install(ws, [], spec=WIDE)
    thread = ws.threads.active
    monkeypatch.setattr(thread.ai, 'refresh', lambda: thread.ai._forget(files=False))
    monkeypatch.setattr(thread.ai, 'learn_context', lambda: 'Learn mode.' if thread.ai.learn_mode else '')
    return thread


def test_toggle_keeps_assistant_history_and_contract_tools(learn_thread):
    t = learn_thread; ai, history = t.ai, t.ai.history
    names = {name for name, _ in engine.TOOLS}
    assert not names.intersection(f.__name__ for f in ai.tools)
    t.set_learn_mode(True)
    assert t.ai is ai and ai.history is history
    assert names <= {f.__name__ for f in ai.tools}
    for f in ai._learn_toolset:
        assert list(inspect.signature(f).parameters) == list(dict(engine.TOOLS)[f.__name__])
    stale = ai._learn_toolset[0]
    t.set_learn_mode(False)
    assert t.ai is ai and ai.history is history
    assert not names.intersection(f.__name__ for f in ai.tools)
    r = stale(goal='fractions')
    assert r['status'] == 'error' and r['error'] == 'mode_off'


@pytest.mark.parametrize('held', ['busy', 'queued', 'approval'])
def test_toggle_refuses_accepted_work(learn_thread, monkeypatch, held):
    t = learn_thread
    if held == 'busy': monkeypatch.setattr(type(t.ai), 'busy', property(lambda self: True))
    if held == 'queued': t.runner._pending['queued'] = {}
    if held == 'approval': monkeypatch.setattr(type(t.approvals), 'pending', property(lambda self: object()))
    try:
        with pytest.raises(TurnError, match='Learn mode'): t.set_learn_mode(True)
        assert not t.ai.learn_mode
    finally: t.runner._pending.clear()


def test_refresh_failure_rolls_back(learn_thread, monkeypatch):
    t = learn_thread; before = list(t.ai.tools)
    def broken(): raise RuntimeError('refresh failed')
    monkeypatch.setattr(t.ai, 'refresh', broken)
    with pytest.raises(RuntimeError, match='refresh failed'): t.set_learn_mode(True)
    assert not t.ai.learn_mode
    assert t.ai.tools == before
    assert not t.ai.saved_learn_mode(t.id)


def test_mode_restores_for_resumed_conversation(learn_thread, monkeypatch):
    t = learn_thread
    t.set_learn_mode(True)
    t.ai.learn_mode = False
    monkeypatch.setattr(t.ai.__class__.__mro__[1], 'resume_session', lambda self, *a, **kw: None)
    t.ai.resume_session(t.id)
    assert t.ai.learn_mode and t.ai.saved_learn_mode(t.id)
    t.set_learn_mode(False)


@pytest.mark.parametrize('active,on,status', [(True, True, 'ok'), (False, True, 'ok'), (True, False, 'ok'), (True, True, 'error'), (True, True, 'stopped')])
def test_create_walk_starts_cancellable_job_with_tab(ws, monkeypatch, active, on, status):
    lr = temp_learning()
    ref = ws.vaults.active
    monkeypatch.setattr(ws.vaults, 'memory', lambda name: SimpleNamespace(_store=lambda shelf: lr.v))
    calls, seen = [], []
    monkeypatch.setattr(ws.fs_watch, 'announce_tab', lambda *a: seen.append(a), raising=False)
    thread = ws.threads.active
    ai = SimpleNamespace(ws=ws, learn_mode=True, session_id=thread.id if active else 'other-thread')
    def ask(prompt, sp='', *args, **kwargs):
        calls.append((prompt, kwargs))
        return 'a plan'
    ai.oneshot = ask
    def create(lr, ask, goal, **kw):
        settings, guard, stopping, progress = (kw[k] for k in ('settings', 'guard', 'stopping', 'progress'))
        assert isinstance(settings, dict) and callable(guard)
        assert not stopping(); progress('planning', .5)
        assert ask(goal) == 'a plan'
        ai.learn_mode = on
        if status != 'ok': return engine.failed('stopped' if status == 'stopped' else 'model_refused', 'No answer.')
        return engine.result('ok', walk='walk-test', data={'title': goal})
    ai.spec_or_none = lambda job='turn': None
    monkeypatch.setattr(engine, 'create_walk', create)
    register_learn_jobs(ws)
    tools = {f.__name__: f for f in learn_tools(ai)}
    r = tools['create_walk'](goal='fractions')
    job = ws.jobs.get(r['operation_id'])
    assert job.kind == 'learn_walk' and job.cancellable
    assert job.params['vault'] == ref.name
    end = time.monotonic() + 5
    while job.active and time.monotonic() < end:
        time.sleep(.01); job = ws.jobs.get(job.id)
    assert job.status == ('cancelled' if status == 'stopped' else 'complete'), job.error
    assert job.result['operation_id'] == job.id
    assert job.result['vault'] == ref.name
    if status == 'ok': assert job.result['data']['tab'] == dict(kind='learn_walk', vault=ref.name, walk='walk-test')
    opened = active and on and status == 'ok'
    assert bool([t for t in ws.tabs if t.kind == 'learn_walk']) == opened
    assert seen == ([('learn_walk', json.dumps([ref.name, 'walk-test']))] if opened else [])
    assert calls and calls[0][1]['strict'] and calls[0][1]['wait']
    assert callable(calls[0][1]['prepare'])


@pytest.mark.parametrize('fails', ['open', 'save'])
def test_a_walk_that_cannot_be_opened_stays_a_completed_job(ws, monkeypatch, caplog, fails):
    lr = temp_learning()
    ref = ws.vaults.active
    monkeypatch.setattr(ws.vaults, 'memory', lambda name: SimpleNamespace(_store=lambda shelf: lr.v))
    ai = SimpleNamespace(ws=ws, learn_mode=True, session_id=ws.threads.active.id, oneshot=lambda *a, **k: 'a plan', spec_or_none=lambda job='turn': None)
    monkeypatch.setattr(engine, 'create_walk', lambda lr, ask, goal, **kw: engine.result('ok', walk='walk-test', data={'title': goal}))
    def boom(*a, **k): raise OSError('disk full')
    monkeypatch.setattr(ws, 'open_learn_walk' if fails == 'open' else 'save', boom)
    register_learn_jobs(ws)
    r = {f.__name__: f for f in learn_tools(ai)}['create_walk'](goal='fractions')
    job = ws.jobs.get(r['operation_id'])
    end = time.monotonic() + 5
    while job.active and time.monotonic() < end:
        time.sleep(.01); job = ws.jobs.get(job.id)
    assert job.status == 'complete', job.error
    assert job.result['status'] == 'ok' and job.result['walk'] == 'walk-test'
    assert job.result['data']['tab'] == dict(kind='learn_walk', vault=ref.name, walk='walk-test')
    assert any('disk full' in m for m in caplog.messages)


def test_the_tools_call_the_engine_with_the_contract_arguments(ws, monkeypatch):
    lr = temp_learning()
    monkeypatch.setattr(ws.vaults, 'memory', lambda name: SimpleNamespace(_store=lambda shelf: lr.v))
    ai = SimpleNamespace(ws=ws, learn_mode=True, session_id='s', oneshot=lambda *a, **k: 'x', spec_or_none=lambda job='turn': None)
    got = {}
    for name in ('walk_state', 'record_attempt', 'note_confusion'):
        monkeypatch.setattr(engine, name, lambda lr, _n=name, **kw: got.setdefault(_n, kw) and engine.result('ok'))
    tools = {f.__name__: f for f in learn_tools(ai)}
    tools['walk_state'](jid='w'); tools['record_attempt'](jid='w', i=0, answer='a', attempt_id='k'); tools['note_confusion'](jid='w', i=0, note='n')
    assert set(got['walk_state']) == {'jid', 'settings'}
    assert set(got['record_attempt']) == {'jid', 'i', 'answer', 'attempt_id', 'ask', 'settings'} and callable(got['record_attempt']['ask'])
    assert set(got['note_confusion']) == {'jid', 'i', 'note'}
