import asyncio, html, json, os, re, subprocess, sys
from contextlib import contextmanager
from unittest.mock import Mock
import pytest
from starlette.testclient import TestClient
from abhyasa.store import Learning
from leela.app import ide_app
from leela.blocks.memory.memory import Memory
from leela.blocks.nb.lesson import lesson_notebook
from leela.blocks.nb.nb import Notebook
from leela.workspace import Workspace
from learn_data import JID, NB_JID, nb_walk, rig, walk  # noqa: F401

def headers_ok(r):
    csp = r.headers['content-security-policy']
    assert "frame-ancestors 'self'" in csp and "img-src 'self' data:" in csp and r.headers['referrer-policy'] == 'no-referrer'

def one_line(r, code, text, exact=True):
    "`r` is a styled `learn` page of the muted line `text` with the status `code` and both headers."
    assert r.status_code == code and r.headers['content-type'].startswith('text/html') and 'Traceback' not in r.text
    assert 'class="lee-learn-page' in r.text and (f'<p class="lee-learn-line">{text}</p>' in r.text if exact else 'class="lee-learn-line">' in r.text and text in r.text)
    headers_ok(r)

def test_learn_shows_the_step_and_writes_nothing(rig):
    c, ws, lr, j, root = rig
    state = lambda: (lr.journey(JID), sorted(root.rglob('*.ipynb')), len(ws.tabs), len(lr.attempts(limit=10**6)), [x.id for x in ws.jobs.all(limit=10**6)])
    before = state()
    r = c.get(f'/learn?walk={JID}&step=0')
    assert r.status_code == 200 and 'Softmax maps scores to weights.' in r.text and 'Watch the sum.' in r.text
    assert r.headers['content-type'].startswith('text/html')
    headers_ok(r)
    assert 'action="/learn/open"' in r.text and 'method="post"' in r.text
    assert '<html class="lee-learn-page">' in r.text and 'in-pane' not in r.text
    assert '<button type="submit" class="lee-btn">Open as a lesson</button>' in r.text
    assert re.search(r'<p class="lee-learn-line">\s*Idea: <strong>', r.text)
    assert r.text.index('localStorage.getItem') < r.text.index('lee-ide.css') and 'MutationObserver' in r.text
    r = c.get(f'/learn?walk={JID}&step=1')
    assert '<script>x()' not in r.text and '&lt;script&gt;' in r.text
    assert 'Softmax maps scores to weights.' in c.get(f'/learn?walk={JID}').text
    assert state() == before

def test_a_learn_page_renders_the_saved_theme_before_the_stylesheet(rig):
    c, ws, lr, j, root = rig
    (root/'.leela').mkdir(exist_ok=True)
    (root/'.leela/settings.json').write_text('{"appearance": {"theme": "nord:dark:tight"}}')
    for u in (f'/learn?walk={JID}&step=0', '/learn?walk=gone-0000', '/learn/lookup'):
        t = c.get(u).text
        assert 'saved = "nord:dark:tight"' in t and t.index('saved = ') < t.index('lee-ide.css'), u

def test_learn_is_get_only(rig):
    assert rig[0].post(f'/learn?walk={JID}').status_code == 405

def test_learn_shows_the_current_step_and_a_done_walk(rig):
    c, ws, lr, j, root = rig
    lr.put_journey({**j, 'id': 'half-0001', 'steps': [{**j.steps[0], 'done': dict(outcome='solid')}, j.steps[1]]})
    r = c.get('/learn?walk=half-0001')
    assert r.status_code == 200 and 'Attention mixes values.' in r.text and 'Softmax maps' not in r.text
    lr.put_journey({**j, 'id': 'done-0001', 'steps': [{**s, 'status': 'known'} for s in j.steps]})
    one_line(c.get('/learn?walk=done-0001'), 200, 'This walk is done.')
    r = c.get('/learn?walk=done-0001&pane=1')
    one_line(r, 200, 'This walk is done.')
    assert '<html class="lee-learn-page in-pane">' in r.text

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
    assert 'onerror' not in r.text and 'src="x"' not in r.text and '<img src=x' not in r.text, 'markdown keeps no handler and no request'

@pytest.mark.parametrize('q, code, text', [
    ('walk=../x', 400, 'walk is not a walk id'), ('walk=a-1&step=-1', 400, 'step must be a whole number from 0'), ('', 400, 'nothing to open'),
    (f'walk={JID}&step=9', 400, 'no step 9'), ('walk=gone-0000', 200, 'This walk is not in your learning store.'),
    ('walk=gone-0000&topic=Softmax', 200, 'This walk is not in your learning store.')])
def test_learn_refuses_bad_queries(rig, q, code, text):
    one_line(rig[0].get('/learn?' + q), code, text, exact=code == 200)

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
        one_line(c.get(f'/learn?walk={JID}'), 503, 'The learning store is locked or cannot be read.')
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

NO_INDEX = 'No code index yet.'
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
    one_line(r, 200, NO_INDEX)
    assert '<html class="lee-learn-page in-pane">' in r.text and '<title>Look up code</title>' in r.text
    assert 'action="/learn/lookup"' in r.text and 'value="x"' in r.text, 'the form stays, so another search needs no reload'
    assert ' autofocus' not in r.text, 'a page in the pane never takes focus from the editor'

def test_lookup_when_making_the_handle_raises(rig, monkeypatch):
    c, ws = rig[:2]
    def boom(path=None): raise OSError('locked')
    monkeypatch.setattr(ws.search, '_kosha', boom)
    one_line(c.get('/learn/lookup?q=x'), 200, NO_INDEX)

@pytest.mark.parametrize('pkg', ["x' OR 1=1 --", '--index-url=https://x', '../p'])
def test_lookup_refuses_a_bad_package_name_before_the_index(rig, monkeypatch, pkg):
    from urllib.parse import quote
    c, ws = rig[:2]
    asked = handle(ws, monkeypatch, FakeKosha())
    r = c.get(f'/learn/lookup?q=x&package={quote(pkg)}')
    one_line(r, 400, 'not a package name', exact=False)
    assert asked == [] and '<p class="lee-learn-line"><' not in r.text

def test_a_refusal_page_escapes_what_it_repeats(rig):
    r = rig[0].get('/learn/lookup?q=x&package=%3Cimg%20src%3Dx%20onerror%3Dy()%3E&pane=1')
    one_line(r, 400, 'not a package name', exact=False)
    assert '<img src=x' not in r.text and '&lt;img src=x' in r.text and 'class="lee-learn-page in-pane"' in r.text

def test_lookup_shows_rows_as_text_and_the_scratch_button_only_for_an_open_notebook(rig, monkeypatch):
    from urllib.parse import quote
    c, ws, lr, j, root = rig
    k = FakeKosha()
    handle(ws, monkeypatch, k)
    r = c.get('/learn/lookup?q=run+sync&package=pydantic-ai&pane=1')
    assert r.status_code == 200 and r.headers['content-type'].startswith('text/html')
    headers_ok(r)
    assert 'class="lee-learn-page in-pane"' in r.text and 'lee-pane.js' in r.text and 'run_sync' in r.text and 'pydantic_ai/agent.py:40' in r.text
    assert 'class="lee-input"' in r.text and '<button type="submit" class="lee-btn">Look up</button>' in r.text
    assert '<b>Run' not in r.text and '&lt;b&gt;Run' in r.text and '<i>the' not in r.text
    assert k.calls[-1] == ('run sync', dict(limit=8, where="(package='pydantic_ai')"))
    assert 'Put in a scratch cell' not in r.text
    assert 'Put in a scratch cell' not in c.get(f'/learn/lookup?q=x&path={quote(str(root/"shut.ipynb"))}').text
    p, _ = lesson_tab(c, ws, root)
    t = c.get(f'/learn/lookup?q=x&path={quote(str(p))}').text
    assert 'Put in a scratch cell' in t and 'in-pane' not in t and 'data-snippet=' in t
    assert re.search(r'<button type="button"[^>]*class="lee-btn"[^>]*>Put in a scratch cell</button>', t)

def test_lookup_shows_a_package_path_and_finds_a_notebook_through_a_linked_folder(rig, monkeypatch, tmp_path_factory):
    "A row showed the whole virtual environment path, and a notebook asked for as /tmp while its tab was /private/tmp had no scratch button."
    from urllib.parse import quote
    c, ws, lr, j, root = rig
    row = {**ROW, 'metadata': {**ROW['metadata'], 'path': '/Users/someone/proj/.venv/lib/python3.13/site-packages/pydantic_ai/agent.py'}}
    handle(ws, monkeypatch, FakeKosha(rows=(row,)))
    p, _ = lesson_tab(c, ws, root)
    (alias := tmp_path_factory.mktemp('alias')/'root').symlink_to(root, target_is_directory=True)
    t = c.get(f'/learn/lookup?q=x&path={quote(str(alias/p.name))}').text
    assert 'pydantic_ai/agent.py:40' in t and '/Users/someone' not in t and 'site-packages' not in t
    assert 'Put in a scratch cell' in t and f'data-path="{p}"' in t, 'the button posts the path of the open tab'
    assert 'Put in a scratch cell' not in c.get(f'/learn/lookup?q=x&path={quote(str(alias/"shut.ipynb"))}').text
    assert c.get('/learn/lookup?q=x&path=a%00b').status_code == 200

def test_lookup_with_no_query_asks_for_one(rig, monkeypatch):
    c, ws = rig[:2]
    k = FakeKosha()
    handle(ws, monkeypatch, k)
    r = c.get('/learn/lookup')
    assert r.status_code == 200 and 'Type what to look for.' in r.text and k.calls == []
    assert 'placeholder="What to look for"' in r.text and ' autofocus' in r.text
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

def test_scratch_writes_the_notebook_as_an_agent_edit_does_and_tells_the_open_tab(rig, monkeypatch):
    c, ws, lr, j, root = rig
    p, nb = lesson_tab(c, ws, root)
    told = []
    monkeypatch.setattr(ws.fs_watch, 'changed', told.append, raising=False)
    graded = next(x for x in nb.cells if 'tests' in x.extra.get('exercise', {}))
    before, extra, ids = graded.source, repr(graded.extra), [x.id for x in nb.cells]
    r = c.post('/learn/scratch', json=dict(path=str(p), snippet='from pydantic_ai import Agent'))
    assert r.status_code == 200, r.text
    got, disk = r.json(), Notebook.load(p)
    assert got['ok'] and got['index'] == len(ids) and isinstance(got['version'], int)
    assert [x['id'] for x in got['cells']][:-1] == ids and got['cells'][-1]['source'] == 'from pydantic_ai import Agent'
    assert disk.cells[-1].source == 'from pydantic_ai import Agent' and disk.cells[-1].extra == {'lesson': {'role': 'scratch'}} and disk.cells[-1].cell_type == 'code'
    kept = next(x for x in disk.cells if x.id == graded.id)
    assert kept.source == before and repr(kept.extra) == extra
    assert told == [[str(p)]], 'the open tab hears of the write as it does of an agent edit'

@pytest.mark.parametrize('route', ['/learn/scratch', '/lesson/predict'])
@pytest.mark.parametrize('body', [b'', b'[1]', b'null'])
@pytest.mark.parametrize('ctype', ['application/json', 'text/plain'])
def test_a_body_that_is_not_a_json_object_is_400(rig, route, body, ctype):
    c = TestClient(rig[0].app, base_url='http://127.0.0.1:5011', raise_server_exceptions=False)
    r = c.post(route, content=body, headers={'content-type': ctype})
    assert r.status_code == 400 and r.json() == dict(ok=False, error='The request body is not a JSON object.'), r.text

PANE_ONLY = 'The side pane shows only Learn pages.'

@pytest.mark.parametrize('path', ['/', '/tab/state', '/lesson/due'])
def test_a_pane_request_outside_learn_gets_the_one_line_refusal(rig, path):
    one_line(rig[0].get(path + '?pane=1'), 403, PANE_ONLY)
    assert rig[0].get(path).status_code != 403

def test_a_pane_request_inside_learn_still_passes(rig):
    c = rig[0]
    assert c.get(f'/learn?walk={JID}&pane=1').status_code == 200 and c.get('/learn/lookup?pane=1').status_code == 200

def test_learn_pages_load_images_from_leela_only(rig):
    for u in (f'/learn?walk={JID}&step=0', '/learn?walk=gone-0000', '/learn/lookup?pane=1'):
        assert "img-src 'self' data:" in rig[0].get(u).headers['content-security-policy'], u

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

def test_guard_lets_a_post_from_the_pane_frame_in():
    h = {'sec-fetch-site': 'same-origin', 'sec-fetch-mode': 'navigate', 'sec-fetch-dest': 'iframe', 'origin': 'http://127.0.0.1:5011'}
    assert guard('/learn/open', h, 'POST') == 'passed' and guard('/learn/open', {**h, 'sec-fetch-dest': 'document'}, 'POST') == 'passed'
    assert guard('/learn/open', {**h, 'origin': 'https://evil.example'}, 'POST') == 421

def opened(c, **form): return c.post('/learn/open', data=form)

def state(ws, lr, root):
    "Everything an open must not change when it refuses."
    return (lr.journey(JID), sorted(str(p) for p in root.rglob('*.ipynb')), [t.path for t in ws.tabs], len(lr.attempts(limit=10**6)),
            [x.id for x in ws.jobs.all(limit=10**6)], list(ws.fs.roots))

@pytest.fixture
def announced(rig, monkeypatch):
    seen = []
    monkeypatch.setattr(rig[1].fs_watch, 'announce', seen.append)
    return seen

def test_open_makes_one_lesson_and_reopens_it(rig, announced, monkeypatch):
    c, ws, lr, j, root = rig
    for k in ('put_journey', 'walk_step', 'journey_step'):
        if hasattr(Learning, k): monkeypatch.setattr(Learning, k, lambda *a, **kw: pytest.fail('Leela wrote the journey'))
    before, roots = lr.journey(JID), list(ws.fs.roots)
    r = opened(c, walk=JID, step='0', topic='')
    one_line(r, 200, 'Opened in Leela.')
    assert '<html class="lee-learn-page"' in r.text and 'in-pane' not in r.text
    assert f'data-rh-url="/learn?walk={JID}&amp;step=0"' in r.text      # the pane keeps the step, not this POST route
    p = root/'lessons'/f'{JID}-0.ipynb'
    nb = Notebook.load(p)
    assert nb.meta['lesson']['walk'] == dict(walk=JID, step=0, section='2 Background') and nb.meta['lesson']['name'] == 'Softmax'
    assert '> Softmax maps scores to weights.' in nb[0].source and 'Watch the sum.' in nb[0].source
    assert ws.tab.path == str(p) and announced == [str(p)]
    t, n = p.stat().st_mtime_ns, len(ws.tabs)
    one_line(opened(c, walk=JID, step='0'), 200, 'Opened in Leela.')
    assert p.stat().st_mtime_ns == t and list((root/'lessons').glob('*.ipynb')) == [p] and len(ws.tabs) == n and announced == [str(p)] * 2
    one_line(opened(c, walk=JID, step='', topic='Attention'), 200, 'Opened in Leela.')   # no step: the current one; a walk wins over a topic
    assert p.stat().st_mtime_ns == t and list((root/'lessons').glob('*.ipynb')) == [p]
    assert opened(c, walk=JID, step='1').status_code == 200 and Notebook.load(root/'lessons'/f'{JID}-1.ipynb').meta['lesson']['walk'] == dict(walk=JID, step=1, section='')
    assert lr.journey(JID) == before and list(ws.fs.roots) == roots and len(lr.attempts(limit=10**6)) == 0

@pytest.mark.parametrize('topic, name, file', [('Softmax', 'Softmax', 'softmax'), ('Agents & tools + more', 'Agents & tools + more', 'agents-and-tools-plus-more'),
                                               ('सॉफ्टमैक्स', 'सॉफ्टमैक्स', 'saphtamaiksa')])
def test_open_makes_a_topic_lesson_and_reopens_it(rig, topic, name, file):
    c, ws, lr, j, root = rig
    assert html.escape(topic) in c.get('/learn', params=dict(topic=topic)).text
    one_line(opened(c, walk='', step='', topic=topic), 200, 'Opened in Leela.')
    p = root/'lessons'/f'{file}.ipynb'
    nb = Notebook.load(p)
    assert nb.meta['lesson'] == {'v': 1, 'name': name, 'topic': file} and nb[0].source.startswith(f'# {name}\n')
    t = p.stat().st_mtime_ns
    assert opened(c, topic=topic).status_code == 200 and p.stat().st_mtime_ns == t and ws.tab.path == str(p)
    assert list((root/'lessons').iterdir()) == [p]

def _plain(p): Notebook.blank().save(p)
def _lesson(**kw): return lambda p: (lesson_notebook('Softmax', step=dict(walk=JID, step=0, section='', text='', note='') | kw) if kw else lesson_notebook('Softmax')).save(p)
def _topic(slug):
    def make(p):
        nb = lesson_notebook('Softmax'); nb.meta['lesson']['topic'] = slug; nb.save(p)
    return make
TAKEN = dict(invalid=lambda p: p.write_text('{not json'), empty=lambda p: p.write_bytes(b''), plain=_plain, other_lesson=_lesson(),
             other_walk=_lesson(walk='other-0000'), other_step=_lesson(step=1), topic_lesson=_topic('softmax'),
             folder=lambda p: p.mkdir(), link=lambda p: ((p.parent/'real.ipynb').write_text('{}'), p.symlink_to(p.parent/'real.ipynb')),
             dangling=lambda p: p.symlink_to(p.parent/'gone.ipynb'))

@pytest.mark.parametrize('kind', TAKEN)
def test_open_refuses_a_file_that_is_not_this_lesson_and_changes_no_bytes(rig, announced, kind):
    c, ws, lr, j, root = rig
    (folder := root/'lessons').mkdir()
    p = folder/f'{JID}-0.ipynb'
    TAKEN[kind](p)
    snap = lambda: sorted((str(x), x.is_symlink(), x.is_dir(), x.read_bytes() if x.is_file() else None) for x in folder.iterdir())
    before, was = snap(), state(ws, lr, root)
    r = opened(c, walk=JID, step='0')
    one_line(r, 409, f'{p.name} is in the lessons folder and is not the lesson for this step. Move it or rename it, then open the lesson again.')
    assert snap() == before and state(ws, lr, root) == was and announced == []

@pytest.mark.parametrize('kind', ['other_walk', 'plain'])
def test_open_refuses_a_topic_file_that_is_not_this_topic(rig, kind):
    c, ws, lr, j, root = rig
    (folder := root/'lessons').mkdir()
    p = folder/'softmax.ipynb'
    (_topic('soft-max') if kind == 'plain' else _lesson(walk='other-0000'))(p)
    b = p.read_bytes()
    one_line(opened(c, topic='Softmax'), 409, 'softmax.ipynb is in the lessons folder and is not the lesson for this idea. Move it or rename it, then open the lesson again.')
    assert p.read_bytes() == b and ws.tab is None

@pytest.mark.parametrize('where', ['outside', 'inside', 'dangling'])
def test_open_refuses_a_symbolic_link_lessons_folder(rig, tmp_path_factory, where):
    c, ws, lr, j, root = rig
    target = {'outside': tmp_path_factory.mktemp('outside'), 'inside': root/'elsewhere', 'dangling': root/'gone'}[where]
    if where == 'inside': target.mkdir()
    (root/'lessons').symlink_to(target, target_is_directory=True)
    was = state(ws, lr, root)
    one_line(opened(c, walk=JID, step='0'), 400, 'The lessons folder is a symbolic link. Leela does not write a lesson through a link.')
    assert state(ws, lr, root) == was and not (where != 'dangling' and list(target.iterdir())) and not (root/'gone').exists()

def test_open_checks_the_walk_again_when_it_posts(rig, announced):
    c, ws, lr, j, root = rig
    assert c.get(f'/learn?walk={JID}&step=1').status_code == 200
    lr.put_journey({**j, 'steps': j.steps[:1]})
    was = state(ws, lr, root)
    one_line(opened(c, walk=JID, step='1'), 400, 'step: this walk has no step 1')
    assert state(ws, lr, root) == was
    assert c.get(f'/learn?walk={JID}&step=0').status_code == 200
    lr.drop_journey(JID)
    was = state(ws, lr, root)
    one_line(opened(c, walk=JID, step='0', topic='Softmax'), 200, 'This walk is not in your learning store.')
    assert state(ws, lr, root) == was and announced == [] and not (root/'lessons').exists()

@pytest.mark.parametrize('form, code, text', [
    (dict(walk='../x'), 400, 'walk is not a walk id'), (dict(walk=JID, step='-1'), 400, 'step must be a whole number from 0'),
    (dict(walk='', step='', topic=''), 400, 'nothing to open'), (dict(), 400, 'nothing to open'), (dict(walk=JID, step='9'), 400, 'no step 9'),
    (dict(walk='gone-0000', step='0'), 200, 'This walk is not in your learning store.'), (dict(walk='done-0001'), 200, 'This walk is done.'),
    (dict(walk=JID, step='0', pane='1', topic='x' * 1000), 400, 'topic is more than')])
def test_open_refuses_as_the_link_does(rig, form, code, text):
    c, ws, lr, j, root = rig
    lr.put_journey({**j, 'id': 'done-0001', 'steps': [{**s, 'status': 'known'} for s in j.steps]})
    was = state(ws, lr, root)
    one_line(opened(c, **form), code, text, exact=code == 200)
    assert state(ws, lr, root) == was

def test_open_reads_the_journey_under_the_lock(rig, monkeypatch):
    from leela.blocks.memory.memory import _open_lock
    c, ws, lr, j, root = rig
    journey = Learning.journey
    def locked(self, jid):
        assert _open_lock(ws.memory.path).locked()
        return journey(self, jid)
    monkeypatch.setattr(Learning, 'journey', locked)
    assert opened(c, walk=JID, step='0').status_code == 200

def test_open_says_when_the_store_cannot_be_read(rig, monkeypatch):
    def locked(*a): raise PermissionError('locked')
    monkeypatch.setattr(Memory, '_store', locked)
    one_line(opened(rig[0], walk=JID, step='0'), 503, 'The learning store is locked or cannot be read.')
    assert not (rig[4]/'lessons').exists()

def test_open_from_the_pane_answers_in_the_pane(rig):
    c = rig[0]
    assert '<input type="hidden" value="1" name="pane">' in c.get(f'/learn?walk={JID}&step=0&pane=1').text
    assert 'name="pane"' not in c.get(f'/learn?walk={JID}&step=0').text and 'name="pane"' not in c.get('/learn?topic=Softmax').text
    assert '<input type="hidden" value="1" name="pane">' in c.get('/learn?topic=Softmax&pane=1').text
    r = opened(c, walk=JID, step='0', pane='1')
    one_line(r, 200, 'Opened in Leela.')
    assert '<html class="lee-learn-page in-pane" data-rh-url="/learn?walk=' in r.text and 'lee-pane.js' in r.text
    r = opened(c, walk='gone-0000', pane='1')
    one_line(r, 200, 'This walk is not in your learning store.')
    assert 'in-pane' in r.text
    assert 'in-pane' not in opened(c, walk=JID, step='0').text

@pytest.mark.parametrize('where', ['project', 'no_folder'])
@pytest.mark.parametrize('boom, code', [(OSError('disk full'), 500), (PermissionError('denied'), 500), ('unsafe', 403)])
def test_open_says_when_it_cannot_write_and_opens_nothing(rig, monkeypatch, announced, boom, code, where, tmp_path):
    from leela.blocks.fs.fs import Unsafe
    c, ws, lr, j, root = rig
    e = Unsafe('outside the open folders') if boom == 'unsafe' else boom
    def save(self, path=None, sandbox=None): raise e
    monkeypatch.setattr(Notebook, 'save', save)
    if where == 'no_folder':
        (tmp_path/'nf').mkdir()
        with bare(tmp_path/'nf', monkeypatch) as (c, ws, fixed, seen):
            r = opened(c, walk=JID, step='0')
            one_line(r, code, 'Leela could not write the lesson.', exact=False)
            assert list(ws.fs.roots) == [] and ws.tab is None and seen == [] and str(fixed) not in ws._closed_roots, 'a failed save leaves no new folder open'
        return
    was = state(ws, lr, root)
    r = opened(c, walk=JID, step='0')
    one_line(r, code, 'Leela could not write the lesson.', exact=False)
    assert 'Opened in Leela.' not in r.text and state(ws, lr, root) == was and announced == []

@pytest.mark.parametrize('boom, text', [
    (PermissionError(13, 'Permission denied', '/Users/someone/Learning/Leela lessons/x.ipynb'), 'Leela could not write the lesson. Permission denied: x.ipynb'),
    (OSError('/Users/someone/disk full'), 'Leela could not write the lesson.'),
    (RuntimeError('/Users/someone/secret'), 'Leela could not open the lesson.')])
def test_open_failure_shows_no_folder_path_or_type_name(rig, monkeypatch, boom, text):
    def save(self, path=None, sandbox=None): raise boom
    monkeypatch.setattr(Notebook, 'save', save)
    r = opened(rig[0], walk=JID, step='0')
    one_line(r, 500, text)
    assert '/Users/someone' not in r.text and type(boom).__name__ not in r.text

def test_open_does_not_read_a_large_file_to_check_it(rig, monkeypatch):
    import leela.blocks.learn.learn as L
    c, ws, lr, j, root = rig
    (folder := root/'lessons').mkdir()
    _lesson(walk=JID, step=0)(p := folder/f'{JID}-0.ipynb')
    monkeypatch.setattr(L, 'MAX_EDIT_BYTES', 10)
    monkeypatch.setattr(Notebook, 'load', lambda *a, **kw: pytest.fail('Leela read a file over the size limit on the event loop'))
    one_line(opened(c, walk=JID, step='0'), 409, f'{p.name} is in the lessons folder and is too large for Leela to check. Move it or rename it, then open the lesson again.')

def test_no_test_uses_the_owners_lessons_folder():
    import leela.blocks.learn.learn as L
    from pathlib import Path
    assert Path.home() not in L.LESSONS.parents

@contextmanager
def bare(tmp_path, monkeypatch, *roots, loose=None):
    "A client on a workspace with the given roots and no folder of its own; `LESSONS` is a folder in `tmp_path`."
    import leela.blocks.learn.learn as L
    monkeypatch.setattr(L, 'LESSONS', fixed := tmp_path/'home'/'Learning'/'Leela lessons')   # the owner's real folder is never used
    ws = Workspace(roots=[], approvals='auto', python=sys.executable)
    if loose: loose.mkdir(parents=True, exist_ok=True); ws.add_root(loose, loose=True)
    for r in roots: r.mkdir(parents=True, exist_ok=True); ws.add_root(r)
    monkeypatch.setattr(ws, 'memory', Memory(path=tmp_path/'other.db', offline=True))
    lr = Learning(ws.memory._store('learning')); walk(lr)
    seen = []
    monkeypatch.setattr(ws.fs_watch, 'announce', seen.append)
    try:
        with TestClient(ide_app(ws), base_url='http://127.0.0.1:5011') as c: yield c, ws, fixed.resolve(), seen
    finally: ws.shutdown_now()

def test_open_with_no_folder_uses_the_fixed_folder_twice(tmp_path, monkeypatch):
    with bare(tmp_path, monkeypatch) as (c, ws, fixed, seen):
        assert ws.project_root is None
        one_line(opened(c, walk=JID, step='0'), 200, 'Opened in Leela.')
        p = fixed/f'{JID}-0.ipynb'
        assert p.is_file() and list(ws.fs.roots) == [fixed] and ws.tab.path == str(p) and seen == [str(p)]
        t = p.stat().st_mtime_ns
        one_line(opened(c, walk=JID, step='0'), 200, 'Opened in Leela.')
        assert p.stat().st_mtime_ns == t and not (fixed/'lessons').exists() and list(ws.fs.roots) == [fixed] and len(ws.tabs) == 1
        assert opened(c, topic='Softmax').status_code == 200 and (fixed/'softmax.ipynb').is_file()
        assert sorted(x.name for x in fixed.iterdir()) == [f'{JID}-0.ipynb', 'softmax.ipynb']

@pytest.mark.parametrize('case', ['loose', 'loose_and_fixed', 'loose_and_parent', 'fixed_alone'])
def test_open_with_the_fixed_folder_already_open_or_covered(tmp_path, monkeypatch, case):
    fixed, loose = tmp_path/'home'/'Learning'/'Leela lessons', tmp_path/'loose'
    roots = dict(loose=(), loose_and_fixed=(fixed,), loose_and_parent=(tmp_path/'home',), fixed_alone=(fixed,))[case]
    with bare(tmp_path, monkeypatch, *roots, loose=None if case == 'fixed_alone' else loose) as (c, ws, fixed, seen):
        before = list(ws.fs.roots)
        for _ in range(2): one_line(opened(c, walk=JID, step='0'), 200, 'Opened in Leela.')
        p = fixed/f'{JID}-0.ipynb'
        assert p.is_file() and ws.tab.path == str(p) and not (fixed/'lessons').exists() and len(ws.tabs) == 1
        assert list(ws.fs.roots) == (before + [fixed] if case == 'loose' else before) and len(set(ws.fs.roots)) == len(ws.fs.roots)
        if case != 'fixed_alone': assert ws.fs.roots[0] == loose.resolve() and ws.fs.loose == loose.resolve()

def test_open_with_no_folder_leaves_no_folder_open_when_the_file_is_taken(tmp_path, monkeypatch):
    import leela.blocks.learn.learn as L
    with bare(tmp_path, monkeypatch) as (c, ws, fixed, seen):
        L.LESSONS.mkdir(parents=True); _plain(L.LESSONS/f'{JID}-0.ipynb')
        one_line(opened(c, walk=JID, step='0'), 409, f'{JID}-0.ipynb is in the lessons folder and is not the lesson for this step. Move it or rename it, then open the lesson again.')
        assert list(ws.fs.roots) == [] and ws.tab is None and seen == [] and str(fixed) not in ws._closed_roots

@pytest.mark.parametrize('block', ['file', 'parent_file', 'read_only', 'link', 'parent_link'])
def test_open_with_no_folder_says_when_the_fixed_folder_cannot_be_made(tmp_path, monkeypatch, block):
    import leela.blocks.learn.learn as L
    with bare(tmp_path, monkeypatch) as (c, ws, fixed, seen):
        fixed = L.LESSONS
        fixed.parent.parent.mkdir(parents=True)
        if block == 'file': fixed.parent.mkdir(); fixed.write_text('keep')
        elif block == 'parent_file': fixed.parent.write_text('keep')
        elif block == 'link': fixed.parent.mkdir(); (tmp_path/'away').mkdir(); fixed.symlink_to(tmp_path/'away', target_is_directory=True)
        elif block == 'parent_link': (tmp_path/'away').mkdir(); fixed.parent.symlink_to(tmp_path/'away', target_is_directory=True)
        else: fixed.parent.parent.chmod(0o555)
        try:
            r = opened(c, walk=JID, step='0')
            if block in ('link', 'parent_link'): one_line(r, 400, 'The lessons folder is a symbolic link. Leela does not write a lesson through a link.')
            else: one_line(r, 500, 'Leela could not write the lesson.', exact=False)
            assert list(ws.fs.roots) == [] and ws.tab is None and seen == []
            if block == 'file': assert fixed.read_text() == 'keep'
            if block == 'parent_file': assert fixed.parent.read_text() == 'keep'
            if block in ('link', 'parent_link'): assert list((tmp_path/'away').iterdir()) == []
        finally: fixed.parent.parent.chmod(0o755)

@pytest.mark.parametrize('pane', ['', '1'])
def test_an_opened_lesson_keeps_the_step_title_and_a_way_back(rig, pane):
    c = rig[0]
    r = opened(c, walk=JID, step='0', pane=pane)
    one_line(r, 200, 'Opened in Leela.')
    back = f'/learn?walk={JID}&amp;step=0' + ('&amp;pane=1' if pane else '')
    assert '<title>Attention</title>' in r.text and f'<a href="{back}" class="lee-learn-back">Back to the step</a>' in r.text, r.text
    r = opened(c, walk='', step='', topic='Softmax')
    assert '<title>Softmax</title>' in r.text and 'href="/learn?topic=Softmax" class="lee-learn-back"' in r.text, r.text
    assert '<title>Learn</title>' in opened(c, walk='nope').text, 'a refusal keeps the plain title'

def test_lookup_keeps_the_tool_for_the_next_search(rig, monkeypatch):
    c, ws = rig[:2]
    handle(ws, monkeypatch, None)
    r = c.get('/learn/lookup?q=x&tool=abc123&pane=1')
    assert re.search(r'<input type="hidden" (name="tool" value="abc123"|value="abc123" name="tool")>', r.text), 'a second search left the tool environment'
    assert 'name="tool"' not in c.get('/learn/lookup?q=x').text

MATH = dict(text='Weights $w_i$ sum to 1.\n\n$$\\sum w = 1$$\n\n```python\nprint(1 < 2)\n```', note='See [the paper](https://example.org), [here](javascript:x()) and ![a](/learn/x).')

def test_a_step_renders_its_markdown_and_maths_and_keeps_nothing_live(rig):
    c, ws, lr, j, root = rig
    lr.put_journey({**j, 'id': 'math-0001', 'steps': [{**j.steps[0], 'read': dict(section='', text=MATH['text']), 'note': MATH['note']}, j.steps[1]]})
    r = c.get('/learn?walk=math-0001&step=0')
    assert '<span class="math inline">w_i</span>' in r.text and '<span class="math display">\\sum w = 1</span>' in r.text
    assert re.search(r'<pre><code class="language-python">.*print.*&lt;.*2', r.text) and '$w_i$' not in r.text
    assert 'href="https://example.org"' in r.text and 'javascript:' not in r.text and 'src="/learn/x"' not in r.text, 'stored text makes no request'
    assert 'katex/katex.min.js' in r.text and 'katex/katex.min.css' in r.text and 'lee-pane.js' in r.text
    r = c.get('/learn?walk=math-0001&step=1')
    assert '<script>x()' not in r.text and '&lt;script&gt;' in r.text

@pytest.mark.parametrize('pane', ['', '1'])
def test_a_step_says_where_it_is_in_the_walk_and_links_its_neighbours(rig, pane):
    c = rig[0]
    tail = '&amp;pane=1' if pane else ''
    first, last = c.get(f'/learn?walk={JID}&step=0&pane={pane}').text, c.get(f'/learn?walk={JID}&step=1&pane={pane}').text
    assert 'Idea 1 of 2' in first and f'href="/learn?walk={JID}&amp;step=1{tail}"' in first and 'Previous idea' not in first and 'Next idea' in first
    assert 'Idea 2 of 2' in last and f'href="/learn?walk={JID}&amp;step=0{tail}"' in last and 'Next idea' not in last and 'Previous idea' in last
    assert ' of 2' not in c.get('/learn?topic=Softmax').text and 'Step ' not in first, 'a topic is not in a walk'

def test_a_step_names_its_sources_in_words(rig, tmp_path_factory, monkeypatch):
    c, ws, lr = rig[:3]
    monkeypatch.setenv('HOME', str(tmp_path_factory.mktemp('home')))
    nb_walk(lr)
    t = c.get(f'/learn?walk={NB_JID}&step=0').text
    assert re.search(r'<strong>your source</strong>\s*· Comic notes · section 2', t) and 'A caption names who acts.' in t
    assert re.search(r'<strong>from the web</strong>\s*· example\.org · \d+ \w+ 2026 · <a href="https://example\.org/c"[^>]*>Captions</a>', t)
    assert '<strong>your source</strong>' in c.get(f'/learn?walk={JID}&step=0').text and 'href="/v/' not in t

def _abhyasa_at(monkeypatch, d, **addr):
    "Point the address file at `d`, with `addr` in it; no `addr` leaves no file."
    monkeypatch.delenv('ABHYASA_ADDRESS_FILE', raising=False); monkeypatch.setenv('XDG_CONFIG_HOME', str(d))
    if addr: (d/'abhyasa').mkdir(exist_ok=True); (d/'abhyasa'/'serving.json').write_text(json.dumps(addr))

def test_a_link_from_another_vault_says_so_and_reads_nothing(rig, monkeypatch, tmp_path_factory):
    from abhyasa.contract import vault_key
    c, ws, lr = rig[:3]
    mine, there = vault_key(ws.memory.path), tmp_path_factory.mktemp('cfg')
    other = next(k for k in ('0a1b2c3d', '0a1b2c3e') if k != mine)
    _abhyasa_at(monkeypatch, there, url='http://127.0.0.1:5099', pid=os.getpid(), vault='/x/abhyasa.db')
    monkeypatch.setattr('leela.blocks.learn.app.read_step', lambda *a: pytest.fail('a link from another vault read the store'))
    line = f'abhyasa uses the vault at /x/abhyasa.db. Leela uses {ws.memory.path}. Start both with the same vault.'
    one_line(c.get(f'/learn?walk={JID}&step=0&v={other}'), 200, line)
    one_line(c.post('/learn/open', data=dict(walk=JID, step='0', v=other)), 200, line)
    p = subprocess.Popen([sys.executable, '-c', '']); p.wait()   # a pid that has ended: abhyasa was killed and left its file
    _abhyasa_at(monkeypatch, there, url='http://127.0.0.1:5099', pid=p.pid, vault='/x/abhyasa.db')
    one_line(c.get(f'/learn?walk={JID}&v={other}'), 200, f'abhyasa uses another vault. Leela uses {ws.memory.path}. Start both with the same vault.')
    for bad in (dict(pid=0, vault='/x'), dict(pid=True, vault='/x'), dict(pid='1', vault='/x'), dict(pid=10**100, vault='/x'), dict(vault='/x')):
        _abhyasa_at(monkeypatch, there, url='http://127.0.0.1:5099', **bad)
        assert 'abhyasa uses another vault.' in c.get(f'/learn?walk={JID}&v={other}').text

def test_a_link_from_the_same_vault_opens_and_keeps_its_key(rig, monkeypatch, tmp_path_factory):
    from abhyasa.contract import vault_key
    c, ws = rig[:2]
    _abhyasa_at(monkeypatch, tmp_path_factory.mktemp('cfg'))
    v = vault_key(ws.memory.path)
    t = c.get(f'/learn?walk={JID}&step=0&v={v}').text
    assert 'Softmax maps scores to weights.' in t and len(re.findall(rf'<input type="hidden" value="{v}" name="v">', t)) == 1 and f'href="/learn?walk={JID}&amp;step=1&amp;v={v}"' in t
    one_line(c.get(f'/learn?walk=gone-0000&v={v}'), 200, f'This walk is not in the vault at {ws.memory.path}. abhyasa and Leela must use the same vault.')
    one_line(c.post('/learn/open', data=dict(walk='gone-0000', v=v)), 200, f'This walk is not in the vault at {ws.memory.path}. abhyasa and Leela must use the same vault.')
    one_line(c.get('/learn?walk=gone-0000'), 200, 'This walk is not in your learning store.')
    one_line(c.get(f'/learn?walk={JID}&v=0A1B2C3D'), 400, 'v is not a vault key: give 8 characters from 0-9 and a-f')
