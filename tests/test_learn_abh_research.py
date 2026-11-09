import json, threading, time
from types import SimpleNamespace

import pytest

from abhyasa import path
from abhyasa.models import Router, Withheld
from ramabana.core import ModelSpec
from tests.fakemodel import install
from tests.test_learn_abh_models import TASKS, _start, served  # noqa: F401

SENTENCE = 'Equal parts make a fraction, and adding fractions works when both fractions share one denominator.'
PAGE = f'# Fractions\n\n{SENTENCE}\n\nA fraction names equal parts of a whole.'
URL = 'https://example.org/fractions'


@pytest.fixture
def web(served, monkeypatch):
    "A fake web under the workspace's research tools, and a scripted model that quotes `SENTENCE`."
    s, ws = served, served['ws']
    s['searched'], s['read'], s['pages'], s['said'] = [], [], {URL: PAGE}, []
    def search(q, n=10):
        s['searched'].append(q)
        return [SimpleNamespace(title='Fractions explained', url=URL)]
    def read(url, sel=None, remember=True):
        assert remember is False
        s['read'].append(url)
        return SimpleNamespace(title='Fractions explained', url=url, text=s['pages'][url]) if url in s['pages'] else None
    monkeypatch.setattr(ws.research, 'search', search)
    monkeypatch.setattr(ws.research, 'read', read)
    def oneshot(prompt, sp, max_tokens, deadline=None):
        s['calls'].append((prompt, sp))
        if 'You find one passage' in sp: return json.dumps(dict(passage=SENTENCE))
        if 'You help a learner find a web page' in sp: return json.dumps(dict(queries=['fraction parts']))
        return 'A short note.'
    s['be']._oneshot = oneshot
    seen = s['seen'] = []
    update = ws.jobs.update
    def upd(jid, _owner=None, **kv):
        if kv.get('current'): seen.append(kv['current'])
        return update(jid, _owner, **kv) if _owner is not None else update(jid, **kv)
    monkeypatch.setattr(ws.jobs, 'update', upd)
    s['s'] = Router(__import__('leela.blocks.learn.host', fromlist=['x']).host_ask(ws.ai))
    s['ask'] = s['s']
    s['calls'].clear(); s['jobs'].clear()
    return s


def _gather(s, stop=None, jid=None):
    return path.gather(s['lr'], jid or s['jid'], stop or threading.Event(), s['ask'])


def test_gather_runs_as_a_leela_job_on_the_research_task_and_files_a_real_quote(web):
    s = web
    out = _gather(s)
    assert out.passages == 2 and out.read == 2 and not out.stopped
    assert set(s['jobs']) == {'research'} <= TASKS and not s['forbidden']
    steps = s['lr'].journey(s['jid']).steps
    assert [x['read']['text'] for x in steps] == [SENTENCE] * 2 and all(x['read']['url'] == URL and x['read']['src'] == 'web' for x in steps)
    job, = s['ws'].jobs.all(kind='learn_gather')
    assert job.status == 'complete' and job.result['data']['passages'] == 2 and job.result['status'] == 'ok'
    assert any(c.startswith('Looking for a source for') for c in s['seen']) and any(c.startswith('Searching the web:') for c in s['seen']) and 'Reading example.org' in s['seen']
    assert 'got a source' in job.result['data']['said'] and 'got a source' in s['lr'].journey(s['jid']).gather_why


def test_the_finished_card_says_what_happened_in_words(web):
    from leela.blocks.vault.ui import job_card
    from fasthtml.common import to_xml
    s = web
    _gather(s)
    job, = s['ws'].jobs.all(kind='learn_gather')
    assert 'Searched the web and read 2 pages: 2 of 2 ideas got a source' in str(to_xml(job_card(job)))


def test_an_idea_that_no_page_served_gets_model_worded_searches_and_a_line(web):
    s = web
    s['pages'].clear()
    out = _gather(s)
    assert out.passages == 0
    steps = s['lr'].journey(s['jid']).steps
    assert all(x['research_why'] and not x['read'] for x in steps)
    assert 'fraction parts' in s['searched'] and 'did not' in out.why
    assert set(s['jobs']) == {'research'}


@pytest.mark.parametrize('vault_pii', ['redact', 'refuse'])
def test_a_page_with_personal_data_never_reaches_the_model(web, vault_pii):
    s = web
    s['ws'].vault_pii = vault_pii
    mail = 'jane.doe@example.com'
    s['pages'][URL] = f'{PAGE}\n\nWrite to {mail} for help.'
    out = _gather(s)
    texts = ' '.join(p for p, _ in s['calls'])
    assert mail not in texts
    if vault_pii == 'refuse':
        assert out.passages == 0 and not [c for c in s['calls'] if 'You find one passage' in c[1]]
        assert all('did not read a page' in x['research_why'] for x in s['lr'].journey(s['jid']).steps)


def test_a_model_worded_search_with_personal_data_is_not_searched(web):
    s = web
    s['pages'].clear()
    def oneshot(prompt, sp, max_tokens, deadline=None):
        s['calls'].append((prompt, sp))
        return json.dumps(dict(queries=['softmax jane.doe@example.com'])) if 'You help a learner find a web page' in sp else '{}'
    s['be']._oneshot = oneshot
    _gather(s)
    assert not [q for q in s['searched'] if 'jane.doe' in q]


def test_stop_mid_search_files_no_source_and_cancels_the_job(web):
    s, ws = web, web['ws']
    stop, entered = threading.Event(), threading.Event()
    def read(url, sel=None, remember=True):
        s['read'].append(url)
        stop.set(); entered.set()
        job = ws.jobs.all(kind='learn_gather')[0]
        for _ in range(60):
            if ws.jobs.stopping(job.id): break
            time.sleep(.05)
        return SimpleNamespace(title='Fractions explained', url=url, text=PAGE)
    ws.research.read = read
    out = _gather(s, stop)
    assert entered.is_set() and out.stopped == 'you' and out.passages == 0
    j = s['lr'].journey(s['jid'])
    assert [bool(x['read']) for x in j.steps] == [False, False] and [x.get('research') for x in j.steps] == [None, None]
    assert not [c for c in s['calls'] if 'You find one passage' in c[1]]
    job, = ws.jobs.all(kind='learn_gather')
    assert job.status == 'cancelled' and job.result['cancelled'] and s['read'] == [URL]


def test_a_walk_job_can_research_after_it_makes_the_walk(web, monkeypatch):
    from leela.blocks.learn import tools
    from tools.s2_native_pilot import PLAN
    s, ws = web, web['ws']
    monkeypatch.setattr(tools, 'learn_store', lambda ws, vault=None, write=False: ('test', s['lr']))
    def oneshot(prompt, sp, max_tokens, deadline=None):
        s['calls'].append((prompt, sp))
        if 'You plan a learning path' in sp: return PLAN
        if 'You find one passage' in sp: return json.dumps(dict(passage=SENTENCE))
        return 'A short note.'
    s['be']._oneshot = oneshot
    made = tools.start_learn_job(ws.ai, 'fractions again', research=True)
    assert made['status'] == 'ok'
    job = ws.jobs.get(made['operation_id'])
    for _ in range(200):
        if not ws.jobs.get(job.id).active: break
        time.sleep(.05)
    job = ws.jobs.get(job.id)
    assert job.status == 'complete', job.error
    assert 'got a source' in job.result['data']['research']
    assert set(s['jobs']) <= {'plan', 'research', 'extract'} and not s['forbidden']


def _vision(s, pii, spec=None):
    ws = s['ws']; ws.vault_pii = pii
    if spec: s['be'].spec = spec; ws.ai.routing._cache[spec.name] = spec
    return Router(__import__('leela.blocks.learn.host', fromlist=['x']).host_ask(ws.ai))


PNG = bytes.fromhex('89504e470d0a1a0a0000000d49484452')


@pytest.mark.parametrize('pii', ['redact', 'refuse'])
def test_a_picture_never_goes_to_a_model_off_this_mac_under_redact_or_refuse(web, pii):
    from abhyasa.show import vision_ask, vision_why
    s = web
    ask = _vision(s, pii)
    why = vision_why(ask)
    assert f'privacy setting is "{pii}"' in why and 'cannot have personal data hidden' in why
    assert vision_ask(ask) is None
    with pytest.raises(Withheld):
        ask.dflt.vision('What is in the picture?', PNG)
    assert not s['calls']


def test_a_picture_goes_through_oneshot_when_privacy_is_off_and_the_route_keeps_images(web, monkeypatch):
    from abhyasa import show
    s = web
    monkeypatch.setattr(show, 'keeps_images', lambda spec: True)
    seen = []
    s['be']._oneshot = lambda prompt, sp, max_tokens, deadline=None: seen.append(prompt) or '{"labels": []}'
    ask = _vision(s, 'off')
    assert show.vision_why(ask) == ''
    call = show.vision_ask(ask)
    assert call is not None and call('Read the labels.', PNG, 'sp') == '{"labels": []}'
    assert s['jobs'] == ['vision'] and 'vision' in TASKS and isinstance(seen[0], list) and PNG in seen[0]


def test_a_route_that_drops_the_picture_says_so_in_words(web, monkeypatch):
    from abhyasa import show
    s = web
    monkeypatch.setattr(show, 'keeps_images', lambda spec: False)
    ask = _vision(s, 'off')
    assert 'does not get pictures on this route' in show.vision_why(ask) and show.vision_ask(ask) is None


def _create(s, monkeypatch, **kw):
    from leela.blocks.learn import tools
    from tools.s2_native_pilot import PLAN
    ws = s['ws']
    monkeypatch.setattr(tools, 'learn_store', lambda ws, vault=None, write=False: ('test', s['lr']))
    ws.ai.mode = 'learn'
    def oneshot(prompt, sp, max_tokens, deadline=None):
        s['calls'].append((prompt, sp))
        if 'You plan a learning path' in sp: return PLAN
        if 'You find one passage' in sp: return json.dumps(dict(passage=SENTENCE))
        return json.dumps(dict(queries=[])) if 'You help a learner find a web page' in sp else 'A short note.'
    s['be']._oneshot = oneshot
    made = {f.__name__: f for f in tools.learn_tools(ws.ai)}['create_walk'](goal='new fractions walk', **kw)
    assert made['status'] == 'ok', made
    for _ in range(300):
        if not ws.jobs.get(made['operation_id']).active: break
        time.sleep(.05)
    return ws.jobs.get(made['operation_id'])


def test_an_agent_made_walk_runs_the_gather_job_and_shows_its_real_quote(web, monkeypatch):
    s = web
    job = _create(s, monkeypatch)
    assert job.status == 'complete', job.error
    gather, = s['ws'].jobs.all(kind='learn_gather')
    assert gather.status == 'complete' and gather.target != s['jid'] and gather.result['data']['passages'] == 2
    assert 'got a source' in job.result['data']['research']
    walk = next(j for j in s['lr'].journeys() if j.title == 'Fractions' and j.id != s['jid'] and j.steps[0].get('read'))
    assert [x['read']['text'] for x in s['lr'].journey(walk.id).steps] == [SENTENCE] * 2 and set(s['read']) == {URL}
    assert set(s['jobs']) <= {'plan', 'research', 'extract'} and not s['forbidden']


def test_an_agent_made_walk_with_no_page_says_the_gap_in_plain_words(web, monkeypatch):
    s = web
    s['pages'].clear()
    job = _create(s, monkeypatch)
    assert job.status == 'complete', job.error
    assert '0 of 2 ideas got a source' in job.result['data']['research']
    walk = next(j for j in s['lr'].journeys() if j.id != s['jid'] and j.get('gather_why'))
    assert all(x.get('research_why') and not x.get('read') for x in walk.steps) and walk.gather_why.startswith('Searched the web')


def test_an_agent_made_walk_can_skip_research(web, monkeypatch):
    s = web
    job = _create(s, monkeypatch, research='no')
    assert job.status == 'complete' and 'research' not in job.result['data'] and not s['searched']
