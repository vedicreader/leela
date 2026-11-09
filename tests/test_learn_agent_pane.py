"The agent pane builds and changes a walk, and explains the step that the Learn tab shows, through the one Leela session."
import json, time
from types import SimpleNamespace

import pytest
from abhyasa import agent_tools as engine
from abhyasa.learner import temp_learning
from leela.blocks.learn.tools import learn_tools, learn_view, register_learn_jobs
from shalya.core import is_write
from tools.s2_native_pilot import PLAN

QUOTE = 'Ranking orders items by score.'


@pytest.fixture
def pane(ws, monkeypatch):
    "A Learn-mode assistant over an isolated store and a scripted `oneshot` that logs the task of each call."
    lr = temp_learning()
    ref = ws.vaults.learn()
    monkeypatch.setattr(ws.vaults, 'memory', lambda name: SimpleNamespace(_store=lambda shelf: lr.v))
    made = engine.create_walk(lr, lambda p, sp='': PLAN, 'fractions', settings={})
    jid = made['walk']
    calls, reply = [], dict(text='1. A fraction names equal parts.')
    def oneshot(prompt, sp='', task='plan', *a, **kw):
        calls.append((task, prompt, kw))
        r = reply['text']
        return r(prompt) if callable(r) else r
    ai = SimpleNamespace(ws=ws, learn_mode=True, session_id=ws.threads.active.id, oneshot=oneshot, spec_or_none=lambda job='turn': None)
    register_learn_jobs(ws)
    tools = {f.__name__: f for f in learn_tools(ai)}
    return SimpleNamespace(ws=ws, lr=lr, jid=jid, calls=calls, reply=reply, ai=ai, tools=tools, vault=ref.name)


def _wait(ws, r, limit=5):
    job = ws.jobs.get(r['operation_id'])
    end = time.monotonic() + limit
    while job.active and time.monotonic() < end:
        time.sleep(.01); job = ws.jobs.get(job.id)
    return job


def _show(pane, path):
    "Open the Learn tab on `path`, as the page does when it saves its place."
    pane.ws.open_learn(pane.vault, '/')
    pane.ws.note_learn_page(path)
    return pane.ws.tab


def _skip(*idea): return lambda p: json.dumps(dict(changes=[dict(op='skip', idea=i, why='you asked') for i in idea]))


def test_the_builder_tools_are_offered_and_the_writers_need_approval(pane):
    names = {n for n, _ in engine.TOOLS}
    assert {'change_walk', 'keep_idea', 'drop_idea', 'move_idea', 'add_source', 'list_versions', 'restore_version', 'explain_here'} <= names <= set(pane.tools)
    reads = {n for n, t in pane.tools.items() if not is_write(t)}
    assert reads == set(engine.READS) == {'walk_state', 'list_versions'}


def test_change_walk_is_one_cancellable_job_through_the_lesson_free_plan_task(pane):
    slug = pane.lr.journey(pane.jid).steps[1]['slug']
    pane.reply['text'] = _skip(slug)
    r = pane.tools['change_walk'](jid=pane.jid, instruction='skip the second idea')
    job = _wait(pane.ws, r)
    assert job.kind == 'learn_change' and job.cancellable and job.status == 'complete', job.error
    assert (job.result['status'], job.result['operation_id'], job.result['vault']) == ('ok', job.id, pane.vault) and job.result['data']['changed']
    assert pane.lr.journey(pane.jid).steps[1]['status'] == 'skip' and len(pane.lr.edits('walk', pane.jid)) == 1
    assert {c[0] for c in pane.calls} == {'plan'} and pane.calls[0][2]['strict'] and pane.calls[0][2]['wait'] and callable(pane.calls[0][2]['prepare'])


def test_change_walk_not_found_privacy_stale_and_stop(pane):
    assert pane.tools['change_walk'](jid='nope', instruction='x')['error'] == 'not_found' and not pane.calls
    slug = pane.lr.journey(pane.jid).steps[1]['slug']
    before = pane.lr.journey(pane.jid)
    from abhyasa.models import Withheld
    def refuse(p): raise Withheld('the privacy setting blocks it')
    pane.reply['text'] = refuse
    job = _wait(pane.ws, pane.tools['change_walk'](jid=pane.jid, instruction='mail jane.doe@example.com'))
    assert job.result['error'] == 'privacy_refused' and pane.lr.journey(pane.jid) == before
    def edits_meanwhile(p): engine.keep_idea(pane.lr, pane.jid, '1'); return _skip(slug)(p)
    pane.reply['text'] = edits_meanwhile
    job = _wait(pane.ws, pane.tools['change_walk'](jid=pane.jid, instruction='skip it'))
    assert job.result['error'] == 'stale_state' and pane.lr.journey(pane.jid).steps[1]['status'] != 'skip'
    def stop_inside(p):
        pane.ws.jobs.cancel(pane.ws.jobs.all(kind='learn_change', limit=1)[0].id); return _skip(slug)(p)
    pane.reply['text'] = stop_inside
    n = len(pane.lr.edits('walk', pane.jid))
    job = _wait(pane.ws, pane.tools['change_walk'](jid=pane.jid, instruction='skip it again'))
    assert job.status == 'cancelled' and job.result['status'] == 'stopped' and job.result['cancelled']
    assert pane.lr.journey(pane.jid).steps[1]['status'] != 'skip' and len(pane.lr.edits('walk', pane.jid)) == n, 'a stop leaves the walk as it was'


def test_hand_tools_versions_and_sources_work_through_the_pane(pane):
    t, j = pane.tools, pane.jid
    k = t['keep_idea'](jid=j, idea='1')
    assert (k['status'], k['vault'], k['data']['changed']) == ('ok', pane.vault, True)
    m = t['move_idea'](jid=j, idea='2', to=1)
    assert m['data']['ideas'][0] == pane.lr.journey(j).steps[0]['slug'] and m['data']['changed']
    v = t['list_versions'](jid=j)
    assert [x['version'] for x in v['data']['versions']] == [1, 2]
    assert t['restore_version'](jid=j, version=1)['data']['changed'] and len(t['list_versions'](jid=j)['data']['versions']) == 3
    n = len(pane.lr.journey(j).steps)
    assert t['drop_idea'](jid=j, idea='1')['status'] == 'ok' and len(pane.lr.journey(j).steps) == n - 1
    assert [t['drop_idea'](jid=j, idea='zzz')['error'], t['keep_idea'](jid='nope', idea='1')['error'], t['restore_version'](jid=j, version=99)['error'],
            t['list_versions'](jid='nope')['error'], t['add_source'](jid=j, source='doc:nope')['error']] == ['not_found'] * 4 + ['source_missing']
    from leela.blocks.learn.tools import learn_store
    d = learn_store(pane.ws)[1].vault.add([(0, 'Fractions\n\nA fraction names equal parts of a whole. The bottom number says how many equal parts the whole has.' * 2)], 'Fraction notes', source='https://example.org/f', kind='web')['doc_id']
    a = t['add_source'](jid=j, source=f'doc:{d}')
    assert a['status'] == 'ok', a['data']
    assert a['data']['documents'] == 1 and pane.lr.journey(j)['chips'] == [f'doc:{d}']
    assert not pane.calls, 'no tool here asks a model'


def test_learn_mode_off_refuses_the_new_tools_too(pane):
    pane.ai.learn_mode = False
    for name, args in (('keep_idea', dict(jid=pane.jid, idea='1')), ('explain_here', dict(note='x')), ('list_versions', dict(jid=pane.jid))):
        assert pane.tools[name](**args)['error'] == 'mode_off'


def test_the_context_knows_the_page_on_screen(pane):
    ws, lr, j = pane.ws, pane.lr, pane.jid
    assert learn_view(ws) == (None, None, '')
    _show(pane, f'/w/{j}/1')
    assert learn_view(ws) == (pane.vault, None, f'/w/{j}/1')
    from leela.blocks.agent.ai import Assistant
    text = Assistant.learn_context(SimpleNamespace(learn_mode=True, ws=ws))
    step = lr.journey(j).steps[1]['slug']
    assert 'Step 2 of' in text and (lr.concept(step)['name']) in text and 'explain_here' in text and engine.RULE in text and len(text) <= 1200
    _show(pane, '/graph')
    assert 'the graph page' in Assistant.learn_context(SimpleNamespace(learn_mode=True, ws=ws))
    ws.open_walk(pane.vault, j)
    assert f'({j})' in Assistant.learn_context(SimpleNamespace(learn_mode=True, ws=ws)), 'a walk tab with no saved page still gives its walk'
    ws.tabs.clear()
    assert 'On screen' not in Assistant.learn_context(SimpleNamespace(learn_mode=True, ws=ws))


def test_explain_here_gives_the_agent_the_step_data_and_makes_no_model_call(pane):
    lr, j = pane.lr, pane.jid
    step = lr.journey(j).steps[1]
    lr.walk_slug(j, step['slug'], read=dict(src='vault:notes', ref='n1', title='Notes', url='https://example.org/n', text=QUOTE))
    assert pane.tools['explain_here'](note='I do not get it')['error'] == 'not_found', 'no Learn tab shows a step'
    _show(pane, f'/w/{j}/1?pane=1')
    r = pane.tools['explain_here'](note='why does it split\nin equal parts')
    d = r['data']
    assert (r['status'], r['walk'], r['step'], r['vault']) == ('ok', j, 1, pane.vault) and d['concept'] == step['slug'] and d['quote'] == dict(text=QUOTE, url='https://example.org/n', title='Notes')
    assert d['level'] and 'numbered steps' in d['rules'] and 'answered anything wrong' in d['rules'] and d['confusion'] == 'why does it split in equal parts' and d['recorded']
    assert not pane.calls and is_write(pane.tools['explain_here']), 'the agent writes the explanation, the tool asks no model'
    _show(pane, '/w/nope/0')
    assert pane.tools['explain_here'](note='q')['error'] == 'not_found'
    _show(pane, f'/w/{j}/0')
    assert pane.tools['explain_here'](note=' ')['error'] == 'model_refused'


def test_explain_here_inside_a_real_turn_returns_with_the_quote_and_level(pane, monkeypatch):
    "A nested model call inside a turn waits for the lock that the turn holds; this tool makes none."
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from tests.fakemodel import Step, WIDE, install
    ws, lr, j = pane.ws, pane.lr, pane.jid
    lr.walk_slug(j, lr.journey(j).steps[1]['slug'], read=dict(src='vault:notes', ref='n1', title='Notes', url='https://example.org/n', text=QUOTE))
    _show(pane, f'/w/{j}/1')
    be = install(ws, [Step(text='Explaining.', tool=('explain_here', dict(note='I do not get this')))], token_delay=0, spec=WIDE)
    thread = ws.threads.active
    monkeypatch.setattr(thread.ai, 'refresh', lambda: thread.ai._forget(files=False))
    thread.set_learn_mode(True)
    seen, real = [], be._tool
    def tool(name):
        f = real(name)
        return f and (lambda **kw: (seen.append(f(**kw)), seen[-1])[1])
    be._tool = tool
    with TestClient(ide_app(ws)) as client:
        client.post('/agent/turn', json={'prompt': 'I do not get this'})
        end = time.time() + 20
        while (not seen or thread.ai.busy) and time.time() < end: time.sleep(.05)
    assert seen and not thread.ai.busy, 'the turn did not finish: the tool hung'
    assert seen and seen[0]['status'] == 'ok', seen
    assert seen[0]['data']['quote']['text'] == QUOTE and seen[0]['data']['level'] and seen[0]['data']['recorded']
