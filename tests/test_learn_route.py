import asyncio
from unittest.mock import Mock
import pytest
from abhyasa.store import Learning
from leela.blocks.memory.memory import Memory
from learn_data import JID, rig, walk  # noqa: F401

def headers_ok(r):
    assert "frame-ancestors 'self'" in r.headers['content-security-policy'] and r.headers['referrer-policy'] == 'no-referrer'

def test_learn_shows_the_step_and_writes_nothing(rig):
    c, ws, lr, j, root = rig
    state = lambda: (lr.journey(JID), sorted(root.rglob('*.ipynb')), len(ws.tabs), len(lr.attempts(limit=10**6)), [x.id for x in ws.jobs.all(limit=10**6)])
    before = state()
    r = c.get(f'/learn?walk={JID}&step=0')
    assert r.status_code == 200 and 'Softmax maps scores to weights.' in r.text and 'Watch the sum.' in r.text
    assert r.headers['content-type'].startswith('text/html')
    headers_ok(r)
    assert 'action="/learn/open"' in r.text and 'method="post"' in r.text
    r = c.get(f'/learn?walk={JID}&step=1')
    assert '<script>x()' not in r.text and '&lt;script&gt;' in r.text
    assert 'Softmax maps scores to weights.' in c.get(f'/learn?walk={JID}').text
    assert state() == before

def test_learn_is_get_only(rig):
    assert rig[0].post(f'/learn?walk={JID}').status_code == 405

def test_learn_shows_the_current_step_and_a_done_walk(rig):
    c, ws, lr, j, root = rig
    lr.put_journey({**j, 'id': 'half-0001', 'steps': [{**j.steps[0], 'done': dict(outcome='solid')}, j.steps[1]]})
    r = c.get('/learn?walk=half-0001')
    assert r.status_code == 200 and 'Attention mixes values.' in r.text and 'Softmax maps' not in r.text
    lr.put_journey({**j, 'id': 'done-0001', 'steps': [{**s, 'status': 'known'} for s in j.steps]})
    r = c.get('/learn?walk=done-0001')
    assert r.status_code == 200 and r.text == 'This walk is done.' and r.headers['content-type'].startswith('text/plain')
    headers_ok(r)

def test_learn_shows_a_step_with_no_passage_or_note(rig):
    c, ws, lr, j, root = rig
    lr.put_journey({**j, 'id': 'bare-0001', 'steps': [dict(slug='softmax', status='todo', read=None)]})
    r = c.get('/learn?walk=bare-0001&step=0')
    assert r.status_code == 200 and 'Softmax' in r.text and 'Traceback' not in r.text

def test_learn_escapes_the_title_and_the_note(rig):
    c, ws, lr, j, root = rig
    lr.put_journey({**j, 'id': 'html-0001', 'title': '<b>Bold</b> walk', 'steps': [{**j.steps[0], 'note': '<img src=x onerror=y()>'}]})
    r = c.get('/learn?walk=html-0001&step=0')
    assert '<b>Bold' not in r.text and '&lt;b&gt;Bold' in r.text
    assert '<img src=x' not in r.text and '&lt;img src=x' in r.text

@pytest.mark.parametrize('q, code, text', [
    ('walk=../x', 400, 'walk is not a walk id'), ('walk=a-1&step=-1', 400, 'step must be a whole number from 0'), ('', 400, 'nothing to open'),
    (f'walk={JID}&step=9', 400, 'no step 9'), ('walk=gone-0000', 200, 'This walk is not in your learning store.'),
    ('walk=gone-0000&topic=Softmax', 200, 'This walk is not in your learning store.')])
def test_learn_refuses_bad_queries(rig, q, code, text):
    r = rig[0].get('/learn?' + q)
    assert r.status_code == code and text in r.text and 'Traceback' not in r.text
    assert r.headers['content-type'].startswith('text/plain')
    headers_ok(r)

def test_a_bad_query_never_opens_the_store(rig, monkeypatch):
    opened = []
    monkeypatch.setattr(Memory, '_store', lambda self, name: opened.append(name))
    assert rig[0].get('/learn?walk=../x').status_code == 400 and opened == []

def test_learn_reads_the_journey_under_the_lock(rig, monkeypatch):
    from leela.blocks.memory.memory import _open_lock
    c, ws, lr, j, root = rig
    opened, original, journey = [], Memory._store, Learning.journey
    def store(self, name):
        opened.append(name)
        return original(self, name)
    def locked(self, jid):
        assert _open_lock(ws.memory.path).locked()
        return journey(self, jid)
    monkeypatch.setattr(Memory, '_store', store); monkeypatch.setattr(Learning, 'journey', locked)
    assert c.get(f'/learn?walk={JID}').status_code == 200 and opened == ['learning']

def test_learn_says_when_the_store_cannot_be_read(rig, monkeypatch):
    c = rig[0]
    with monkeypatch.context() as m:
        def locked(*a): raise PermissionError('locked')
        m.setattr(Memory, '_store', locked)
        r = c.get(f'/learn?walk={JID}')
        assert r.status_code == 503 and r.text == 'The learning store is locked or cannot be read.'
        assert r.headers['content-type'].startswith('text/plain')
        headers_ok(r)
    assert c.get(f'/learn?walk={JID}').status_code == 200

def test_learn_opens_a_topic(rig):
    c = rig[0]
    r = c.get('/learn?topic=Softmax')
    assert r.status_code == 200 and 'Softmax' in r.text and 'action="/learn/open"' in r.text
    headers_ok(r)
    assert 'Agents and tools' in c.get('/learn?topic=Agents+and+tools').text

def guard(path, h, method='GET'):
    from leela.hub import LoopbackHostGuard
    seen, sent = [], []
    async def app(scope, receive, send): seen.append(scope['path'])
    async def send(m): sent.append(m)
    h = {'host': '127.0.0.1:5011', **h}
    asyncio.run(LoopbackHostGuard(app)({'type': 'http', 'method': method, 'path': path,
        'headers': [(k.encode(), v.encode()) for k, v in h.items()]}, Mock(), send))
    return 'passed' if seen else sent[0]['status']

NAV = {'sec-fetch-site': 'cross-site', 'sec-fetch-mode': 'navigate', 'sec-fetch-dest': 'document'}

def test_guard_lets_only_a_learn_navigation_cross_site():
    assert guard('/learn', NAV) == 'passed'
    assert guard('/learn', {**NAV, 'sec-fetch-mode': 'Navigate', 'sec-fetch-dest': 'Document'}) == 'passed'
    assert guard('/learn', {**NAV, 'sec-fetch-mode': 'cors'}) == 421
    assert guard('/learn', {**NAV, 'sec-fetch-dest': 'iframe'}) == 421
    assert guard('/learn', NAV, 'POST') == 421 and guard('/learn/open', NAV, 'POST') == 421
    assert guard('/learn/', NAV) == 421 and guard('/tab/state', NAV) == 421
    assert guard('/learn', {**NAV, 'host': 'evil.example'}) == 421
    assert guard('/learn', {**NAV, 'origin': 'https://evil.example'}) == 421
