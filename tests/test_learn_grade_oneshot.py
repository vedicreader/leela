from starlette.testclient import TestClient

from leela.app import ide_app
from tools.s2_native_pilot import PLAN
from tests.fakemodel import install
from ramabana.core import ModelSpec


def test_walk_answer_uses_guarded_grade_oneshot_once(ws, monkeypatch):
    from abhyasa.agent_tools import create_walk
    from ramabana.agent import Agent
    be = install(ws, [], spec=ModelSpec('grade-hosted', 'remote', 'scripted/model', ctx=8000))
    ai = ws.ai
    from abhyasa.learner import temp_learning
    from types import SimpleNamespace
    from leela.blocks.learn import walk
    lr = temp_learning()
    vault = 'test'
    memory = SimpleNamespace(path=lr.v.path, _store=lambda shelf: lr.v)
    monkeypatch.setattr(walk, 'walk_memory', lambda ctx, vault: memory)
    made = create_walk(lr, lambda p, sp='': PLAN, 'fractions', settings={})
    assert made['status'] == 'ok'
    jid = made['walk']
    slug = lr.journey(jid).steps[0]['slug']
    lr.update(slug, core='A fraction names equal parts of a whole.')
    step = lr.journey(jid).steps[0]
    lr.walk_slug(jid, slug, note_none=True, check={**step['check'], 'q': 'What does a fraction name?'})
    calls = []
    def grade(prompt, sp, max_tokens, deadline=None):
        assert deadline is not None and deadline > 0
        calls.append((prompt, sp))
        return r'{"correct": true, "grade": 10, "feedback": "Correct.", "first_error": "", "misconception": ""}'
    be.supports_deadline = True
    be._oneshot = grade
    assert type(ai).oneshot is Agent.oneshot
    routed = []
    ai._be = ai._be_or_none = lambda job='turn': routed.append(job) or be
    client = TestClient(ide_app(ws))
    try:
        url = f'/learn/walk/{jid}/0/answer?vault={vault}'
        body = dict(answer='Equal parts of a whole.', attempt_id='grade-once')
        from ramabana.runtime import OneshotEmpty
        original = ai.oneshot
        def empty(*args, **kwargs): raise OneshotEmpty('grade', 'no route answered')
        ai.oneshot = empty
        refused = client.post(url, json=body).json()
        assert refused['error'] == 'model_refused', refused
        assert not lr.attempts(slug, limit=None)
        ai.oneshot = original
        first = client.post(url, json=body).json()
        repeat = client.post(url, json=body).json()
        assert first['status'] == 'ok' and repeat == first, str(first)
        assert len(calls) == 1 and len(lr.attempts(slug, limit=None)) == 1
        assert 'grade' in routed and 'plan' not in routed
        ws.vault_pii = 'refuse'
        other = create_walk(lr, lambda p, sp='': PLAN, 'fractions again', settings={})
        step = lr.journey(other['walk']).steps[0]
        lr.walk_slug(other['walk'], step['slug'], note_none=True, check={**step['check'], 'q': 'What does a fraction name?'})
        denied = client.post(f"/learn/walk/{other['walk']}/0/answer?vault={vault}",
                             json=dict(answer='jane.doe@example.com', attempt_id='private')).json()
        assert denied['error'] == 'privacy_refused'
        assert len(calls) == 1
        other_slug = lr.journey(other['walk']).steps[0]['slug']
        assert not [a for a in lr.attempts(other_slug, limit=None) if a.get('attempt_id') == 'private']
    finally: client.close()
