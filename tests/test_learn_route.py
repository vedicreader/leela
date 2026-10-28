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

NO_INDEX = 'No code index for this yet.'
ROW = dict(package='pydantic_ai', content='def run_sync(self, prompt):\n    "<b>Run</b> the agent."',
           metadata=dict(name='run_sync', path='pydantic_ai/agent.py', lineno=40, docstring='Run <i>the</i> agent.'))

class FakeKosha:
    def __init__(self, rows=(ROW,), have=('pydantic_ai',)): self.rows, self.have, self.calls = list(rows), have, []
    def env_context(self, q, **kw): self.calls.append((q, kw)); return self.rows
    def pkgs2consider(self, sys_wide=True): return dict.fromkeys(self.have).keys()

class Broken(FakeKosha):
    def pkgs2consider(self, sys_wide=True): raise RuntimeError('database disk image is malformed')

class Failing(FakeKosha):
    def env_context(self, q, **kw): raise RuntimeError('no such table: store')

def handle(ws, monkeypatch, k):
    asked = []
    monkeypatch.setattr(ws.search, '_kosha', lambda path=None: asked.append(path) or k)
    return asked

def lesson_tab(c, ws, root):
    from leela.blocks.nb.lesson import lesson_notebook
    p = root/'lesson.ipynb'
    lesson_notebook('Doubling', dict(task='Double it.', fname='double', stub='def double(x): pass',
                                     tests=[dict(say='doubles 2', test='assert double(2) == 4', shown=True)])).save(p)
    ws.open(p); c.get('/tab/state')
    return p, ws.docstore.owner(str(p))[1]

@pytest.mark.parametrize('k', [None, Broken(), Failing(), FakeKosha(have=())])
def test_lookup_with_no_index_says_one_line(rig, monkeypatch, k):
    c, ws = rig[:2]
    handle(ws, monkeypatch, k)
    r = c.get('/learn/lookup?q=x&pane=1')
    assert r.status_code == 200 and r.text == NO_INDEX and r.headers['content-type'].startswith('text/plain')
    headers_ok(r)

def test_lookup_when_making_the_handle_raises(rig, monkeypatch):
    c, ws = rig[:2]
    def boom(path=None): raise OSError('locked')
    monkeypatch.setattr(ws.search, '_kosha', boom)
    r = c.get('/learn/lookup?q=x')
    assert r.status_code == 200 and r.text == NO_INDEX
    headers_ok(r)

@pytest.mark.parametrize('pkg', ["x' OR 1=1 --", '--index-url=https://x', '../p'])
def test_lookup_refuses_a_bad_package_name_before_the_index(rig, monkeypatch, pkg):
    from urllib.parse import quote
    c, ws = rig[:2]
    asked = handle(ws, monkeypatch, FakeKosha())
    r = c.get(f'/learn/lookup?q=x&package={quote(pkg)}')
    assert r.status_code == 400 and 'not a package name' in r.text and 'Traceback' not in r.text and asked == []
    headers_ok(r)

def test_lookup_shows_rows_as_text_and_the_scratch_button_only_for_an_open_notebook(rig, monkeypatch):
    from urllib.parse import quote
    c, ws, lr, j, root = rig
    k = FakeKosha()
    handle(ws, monkeypatch, k)
    r = c.get('/learn/lookup?q=run+sync&package=pydantic-ai&pane=1')
    assert r.status_code == 200 and r.headers['content-type'].startswith('text/html')
    headers_ok(r)
    assert 'class="in-pane"' in r.text and 'lee-pane.js' in r.text and 'run_sync' in r.text and 'pydantic_ai/agent.py:40' in r.text
    assert '<b>Run' not in r.text and '&lt;b&gt;Run' in r.text and '<i>the' not in r.text
    assert k.calls[-1] == ('run sync', dict(limit=8, where="(package='pydantic_ai')"))
    assert 'Put in a scratch cell' not in r.text
    assert 'Put in a scratch cell' not in c.get(f'/learn/lookup?q=x&path={quote(str(root/"shut.ipynb"))}').text
    p, _ = lesson_tab(c, ws, root)
    t = c.get(f'/learn/lookup?q=x&path={quote(str(p))}').text
    assert 'Put in a scratch cell' in t and 'in-pane' not in t and 'data-snippet=' in t

def test_lookup_with_no_query_asks_for_one(rig, monkeypatch):
    c, ws = rig[:2]
    k = FakeKosha()
    handle(ws, monkeypatch, k)
    r = c.get('/learn/lookup')
    assert r.status_code == 200 and 'Type what to look for.' in r.text and k.calls == []
    headers_ok(r)

def test_lookup_says_when_nothing_is_found(rig, monkeypatch):
    c, ws = rig[:2]
    handle(ws, monkeypatch, FakeKosha(rows=()))
    r = c.get('/learn/lookup?q=zzz')
    assert r.status_code == 200 and 'Nothing found.' in r.text

def test_lookup_uses_the_project_for_a_tool_that_is_not_ready(rig, monkeypatch):
    c, ws = rig[:2]
    k = FakeKosha()
    asked = handle(ws, monkeypatch, k)
    assert c.get('/learn/lookup?q=x&tool=0123456789abcdef').status_code == 200 and asked == [None] and k.calls

def test_scratch_appends_and_never_changes_the_graded_cell(rig):
    c, ws, lr, j, root = rig
    p, nb = lesson_tab(c, ws, root)
    graded = next(x for x in nb.cells if 'tests' in x.extra.get('exercise', {}))
    before, extra, ids = graded.source, repr(graded.extra), [x.id for x in nb.cells]
    r = c.post('/learn/scratch', json=dict(path=str(p), snippet='from pydantic_ai import Agent'))
    assert r.status_code == 200, r.text
    got = r.json()
    assert got['ok'] and got['index'] == len(ids) and got['version'] == nb.version
    assert [x['id'] for x in got['cells']][:-1] == ids and got['cells'][-1]['source'] == 'from pydantic_ai import Agent'
    assert nb.cells[-1].extra == {'lesson': {'role': 'scratch'}} and nb.cells[-1].cell_type == 'code'
    assert graded.source == before and repr(graded.extra) == extra
    assert ws.docstore.tab_for(str(p)).dirty

@pytest.mark.parametrize('body', [dict(path='nope.ipynb', snippet='x'), dict(snippet='x'), dict(path='', snippet='x'), dict(path='P', snippet=5), dict(path='P')])
def test_scratch_refuses_a_path_that_is_not_an_open_notebook(rig, body):
    c, ws, lr, j, root = rig
    p, nb = lesson_tab(c, ws, root)
    n = len(nb.cells)
    body = {k: str(p) if v == 'P' else v for k, v in body.items()}
    r = c.post('/learn/scratch', json=body)
    assert r.status_code == 400 and r.json()['ok'] is False and len(nb.cells) == n

def test_scratch_is_post_only(rig):
    assert rig[0].get('/learn/scratch').status_code == 405 and rig[0].post('/learn/lookup?q=x').status_code == 405

def test_guard_lets_only_a_learn_navigation_cross_site():
    assert guard('/learn', NAV) == 'passed'
    assert guard('/learn', {**NAV, 'sec-fetch-mode': 'Navigate', 'sec-fetch-dest': 'Document'}) == 'passed'
    assert guard('/learn', {**NAV, 'sec-fetch-mode': 'cors'}) == 421
    assert guard('/learn', {**NAV, 'sec-fetch-dest': 'iframe'}) == 421
    assert guard('/learn', NAV, 'POST') == 421 and guard('/learn/open', NAV, 'POST') == 421
    assert guard('/learn/scratch', NAV, 'POST') == 421 and guard('/learn/lookup', NAV) == 421
    assert guard('/learn/', NAV) == 421 and guard('/tab/state', NAV) == 421
    assert guard('/learn', {**NAV, 'host': 'evil.example'}) == 421
    assert guard('/learn', {**NAV, 'origin': 'https://evil.example'}) == 421
