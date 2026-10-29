"The presentation held in memory: its routes, keys, images, headers and events, and the freezers that ship `stage.js`."
import asyncio, base64, copy, hashlib, importlib.util, io, json, re, sys, threading
from html.parser import HTMLParser
from importlib.resources import files
from pathlib import Path
import pytest
from PIL import Image
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.hub import LoopbackHostGuard
from leela.workspace import Workspace

ROOT = Path(__file__).resolve().parents[1]
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
ENDED, BAD_KEY, NEWER = 'This presentation has ended.', 'This presentation link is not valid.', 'A newer presentation started.'
NOT_OBJECT, NOTHING = 'The request body is not a JSON object.', 'There is nothing to present in this notebook.'
STAGE = (files('abhyasa.core')/'stage.js').read_bytes()

def _png(colour):
    b = io.BytesIO(); Image.new('RGB', (4, 3), colour).save(b, 'PNG'); return b.getvalue()

RED, BLUE, GREEN = _png((200, 30, 30)), _png((30, 30, 200)), _png((30, 200, 30))
def _sha(b): return hashlib.sha256(b).hexdigest()
def _out(b): return {'output_type': 'display_data', 'data': {'image/png': base64.b64encode(b).decode()}}

CELLS = [dict(id='m0', cell_type='markdown', source='# Intro\nUNSAVED-EDIT ![p](pic.png)', outputs=[]),
         dict(id='m1', cell_type='markdown', source='SECRET-NOTE', outputs=[]),
         dict(id='c2', cell_type='code', source='print(1)', outputs=[{'output_type': 'stream', 'name': 'stdout', 'text': 'UNSAVED-OUT\n'}, _out(RED)]),
         dict(id='m3', cell_type='markdown', source='## Two', outputs=[])]
LINE = [dict(items=[dict(i=0, frag=-1), dict(i=2, frag=0)], notes=[1], groups=1), dict(items=[dict(i=3, frag=-1)], notes=[], groups=0)]
#: every keyed route that changes the presentation; `/present/start` is the one unkeyed mutation, because it makes the key
MUTATIONS = [('/present/at', dict(slide='s2', step=0, blank=False, size=10)), ('/present/move', dict(t='look', theme='leela:dark:relaxed')), ('/present/resume', {}),
             ('/present/out', dict(cell='c2', gen=1, seq=1, outputs=[], done=True)), ('/present/show-error', dict(cell='c2', gen=1)),
             ('/present/clear', dict(gen=1)), ('/present/end', {})]
SHUT = {'cache-control': 'no-store', 'x-content-type-options': 'nosniff'}

def body(root, **kw):
    b = dict(path=str(root/'a.ipynb'), title='a', cells=copy.deepcopy(CELLS), line=copy.deepcopy(LINE), start=dict(slide=0, step=0))
    return {**b, **kw}

def _shut(r): return {k: r.headers.get(k) for k in SHUT} == SHUT

@pytest.fixture
def rig(tmp_path):
    (root := tmp_path/'ws').mkdir(); (root/'pic.png').write_bytes(BLUE)
    ws = Workspace(roots=[root], python=sys.executable)
    app = ide_app(ws)
    try:
        with TestClient(LoopbackHostGuard(app), base_url='http://127.0.0.1') as c: yield c, root, app
    finally: ws.shutdown_now()

def start(c, root, **kw): return c.post('/present/start', json=body(root, **kw))
def held(app): return app.state.presentation

def test_a_presentation_starts_from_the_live_cells_and_writes_nothing(rig):
    c, root, app = rig
    before = sorted((p, p.stat().st_mtime_ns) for p in root.rglob('*'))
    r = start(c, root)
    assert r.status_code == 200 and _shut(r), r.text
    d = r.json()
    assert re.fullmatch('[0-9a-f]{32}', d['key']) and re.fullmatch('[0-9a-f]{16}', d['id']) and d['id'] != d['key']
    # Task 4 on purpose: the audience URL and every image URL hold the audience key `ak`, so the audience page never sees the presenter key
    assert re.fullmatch('[0-9a-f]{32}', d['ak']) and d['ak'] != d['key']
    assert d['ok'] and d['at'] == dict(slide='s1', step=0, blank=False, size=10) and d['audience'] == '/present/audience?k=' + d['ak']
    ps = json.dumps(d['presenter'])
    assert 'SECRET-NOTE' in ps and 'UNSAVED-EDIT' in ps and [s['id'] for s in d['presenter']['slides']] == ['s1', 's2']
    deck = c.get('/present/deck', params=dict(k=d['key']))
    assert deck.status_code == 200 and deck.headers['content-security-policy'] == CSP and deck.headers['referrer-policy'] == 'no-referrer' and _shut(deck)
    room = deck.json(); rs = json.dumps(room)
    assert 'SECRET-NOTE' not in rs and 'UNSAVED-EDIT' in rs and str(root) not in rs and [s['id'] for s in room['slides']] == ['s1', 's2']
    code = room['slides'][0]['blocks'][1]
    assert code['cell'] == 'c2' and 'UNSAVED-OUT' in code['out'] and f'/present/img/{_sha(RED)}?k=' + d['ak'] in code['out'] and d['key'] not in rs + ps
    assert set(held(app).cur['images']) == {_sha(RED), _sha(BLUE)}
    assert sorted((p, p.stat().st_mtime_ns) for p in root.rglob('*')) == before

def test_the_start_place_and_every_move_are_checked(rig):
    c, root, app = rig
    assert start(c, root, start=dict(slide=1, step=0)).json()['at']['slide'] == 's2'
    d = start(c, root, start=dict(slide=0, step=1)).json(); k = d['key']
    assert d['at'] == dict(slide='s1', step=1, blank=False, size=10)
    ok = c.post('/present/at', json=dict(k=k, slide='s2', step=0, blank=True, size=12))
    assert (ok.status_code, ok.json()) == (200, dict(ok=True, at=dict(slide='s2', step=0, blank=True, size=12))) and _shut(ok)
    at = dict(held(app).cur['at'])
    bad = [(dict(slide='s9'), 'There is no such slide in this presentation.'), (dict(slide='s0'), 'There is no such slide in this presentation.'),
           (dict(slide='2'), 'There is no such slide in this presentation.'), (dict(slide=2), 'There is no such slide in this presentation.'),
           (dict(slide='s1', step=2), 'The step is not on this slide.'), (dict(step=1), 'The step is not on this slide.'),
           (dict(step=-1), 'The step is not on this slide.'), (dict(step=True), 'The step is not on this slide.'),
           (dict(size=4), 'The text size must be a whole number from 5 to 25.'), (dict(size=26), 'The text size must be a whole number from 5 to 25.'),
           (dict(size=10.5), 'The text size must be a whole number from 5 to 25.'), (dict(blank='yes'), 'Blank must be true or false.')]
    for change, why in bad:
        r = c.post('/present/at', json={**dict(k=k, slide='s2', step=0, blank=False, size=10), **change})
        assert (r.status_code, r.json()) == (400, dict(ok=False, error=why)), change
        assert held(app).cur['at'] == at, change
    for gone in ('slide', 'step', 'blank', 'size'):
        r = c.post('/present/at', json={x: v for x, v in dict(k=k, slide='s2', step=0, blank=False, size=10).items() if x != gone})
        assert r.status_code == 400 and held(app).cur['at'] == at, gone
    assert c.post('/present/at', json=dict(k=k, slide='s1', step=1, blank=False, size=25)).json()['at']['step'] == 1

def _cells(n): return [dict(id=f'x{i}', cell_type='markdown', source='x', outputs=[]) for i in range(n)]
def _set(path, v):
    def f(b, root):
        o = b
        for k in path[:-1]: o = o[k]
        o[path[-1]] = v(root) if callable(v) else v
    return f

OUTSIDE, NOT_NB = 'The notebook is outside the open folders.', 'Only a notebook can be presented.'
CELLS_BAD, LINE_BAD, TWICE = 'The cells are not a list of cells.', 'The slide line is not a list of slides.', 'A cell is in the slide line more than once.'
ORDER, NOT_IN, START = 'The fragment groups of a slide are out of order.', 'The slide line names a cell that is not in the notebook.', 'The start place is not in the presentation.'
BAD_STARTS = [
    ('not_a_notebook', _set(['path'], lambda r: str(r/'a.py')), NOT_NB), ('path_not_text', _set(['path'], 7), NOT_NB),
    ('dot_dot', _set(['path'], lambda r: str(r/'sub'/'..'/'a.ipynb')), OUTSIDE), ('outside', _set(['path'], lambda r: str(r.parent/'out'/'a.ipynb')), OUTSIDE),
    ('symlink', _set(['path'], lambda r: str(r/'link'/'a.ipynb')), OUTSIDE),
    ('cells_not_list', _set(['cells'], {}), CELLS_BAD), ('cell_not_object', _set(['cells'], [1]), CELLS_BAD),
    ('id_not_text', _set(['cells', 0, 'id'], 3), 'Each cell needs its own text id.'), ('id_twice', _set(['cells', 1, 'id'], 'm0'), 'Each cell needs its own text id.'),
    ('kind', _set(['cells', 0, 'cell_type'], 'heading'), 'A cell type is not markdown, code, raw or prompt.'),
    ('source', _set(['cells', 0, 'source'], ['a']), 'A cell source is not text.'),
    ('outputs', _set(['cells', 2, 'outputs'], {}), 'The outputs of a cell are not a list of outputs.'),
    ('output_item', _set(['cells', 2, 'outputs'], [1]), 'The outputs of a cell are not a list of outputs.'),
    ('too_many_cells', _set(['cells'], _cells(2001)), 'A presentation can have at most 2,000 cells.'),
    ('long_source', _set(['cells', 0, 'source'], 'x' * 1_000_001), 'A cell has more than 1,000,000 characters of source.'),
    ('long_output', _set(['cells', 2, 'outputs'], [{'output_type': 'stream', 'name': 'stdout', 'text': 'x' * 4_000_001}]), 'A cell has more than 4,000,000 characters of output.'),
    ('line_not_list', _set(['line'], {}), LINE_BAD), ('slide_not_object', _set(['line'], [1]), LINE_BAD), ('notes_not_list', _set(['line', 0, 'notes'], 1), LINE_BAD),
    ('empty_line', _set(['line'], []), NOTHING), ('no_items', _set(['line', 1, 'items'], []), NOTHING),
    ('too_many_slides', _set(['line'], [LINE[1]] * 10_000), 'A presentation can have at most 9,999 slides.'),
    ('past_the_cells', _set(['line', 1, 'items', 0, 'i'], 9), NOT_IN), ('boolean_index', _set(['line', 1, 'items', 0, 'i'], True), NOT_IN),
    ('note_past_the_cells', _set(['line', 1, 'notes'], [9]), NOT_IN),
    ('frags_out_of_order', _set(['line', 0, 'items'], [dict(i=2, frag=0), dict(i=0, frag=-1)]), ORDER),
    ('frag_past_groups', _set(['line', 0, 'items', 1, 'frag'], 1), ORDER), ('groups_not_frags', _set(['line', 0, 'groups'], 2), ORDER),
    ('frag_boolean', _set(['line', 0, 'items', 1, 'frag'], False), ORDER),
    ('groups_50', _set(['line', 0, 'groups'], 50), 'A slide can have at most 49 fragment groups.'),
    ('item_and_note', _set(['line', 0, 'notes'], [0]), TWICE), ('two_slides', _set(['line', 1, 'items', 0, 'i'], 0), TWICE),
    ('start_missing', _set(['start'], None), START), ('start_past', _set(['start'], dict(slide=2, step=0)), START),
    ('start_step', _set(['start'], dict(slide=0, step=2)), START), ('start_boolean', _set(['start'], dict(slide=True, step=0)), START)]

@pytest.mark.parametrize('name,change,why', BAD_STARTS, ids=[x[0] for x in BAD_STARTS])
def test_a_bad_start_says_why_and_leaves_the_live_presentation(rig, name, change, why):
    c, root, app = rig
    (root.parent/'out').mkdir(); (root/'link').symlink_to(root.parent/'out')
    live = start(c, root).json(); cur = held(app).cur
    b = body(root); change(b, root)
    r = c.post('/present/start', json=b)
    assert (r.status_code, r.json()) == (400, dict(ok=False, error=why)) and _shut(r), r.text
    assert held(app).cur is cur and cur['key'] == live['key'] and set(cur['images']) == {_sha(RED), _sha(BLUE)}
    assert c.get('/present/deck', params=dict(k=live['key'])).status_code == 200

def test_an_unsaved_notebook_presents(rig):
    c, root, _ = rig
    assert not (root/'new.ipynb').exists() and start(c, root, path=str(root/'new.ipynb')).status_code == 200

BODIES = [('{bad', 'application/json'), ('[1]', 'application/json'), ('null', 'application/json'), ('', 'application/json'),
          ('{"k": "x"}', 'text/plain'), ('k=x', 'application/x-www-form-urlencoded')]

@pytest.mark.parametrize('route', ['/present/start', '/present/at', '/present/end'])
@pytest.mark.parametrize('raw,ctype', BODIES)
def test_a_body_that_is_not_a_json_object_changes_nothing(rig, route, raw, ctype):
    c, root, app = rig
    cur = held(app).cur if start(c, root).status_code == 200 else None
    r = c.post(route, content=raw, headers={'Content-Type': ctype})
    assert (r.status_code, r.json()) == (400, dict(ok=False, error=NOT_OBJECT)), r.text
    assert cur is not None and held(app).cur is cur

def test_a_body_over_the_limit_is_refused_before_it_is_parsed(rig, monkeypatch):
    import leela.blocks.nb.presentation as pm
    c, root, app = rig
    cur = start(c, root).json() and held(app).cur
    monkeypatch.setattr(pm, 'MOST_BODY', 100)
    for route in ('/present/start', '/present/at', '/present/end'):
        r = c.post(route, json=dict(body(root), k=cur['key']))
        assert (r.status_code, r.json()) == (400, dict(ok=False, error='The request is larger than 32 MB.')), route
        assert held(app).cur is cur

def test_a_build_failure_leaves_the_live_presentation(rig, monkeypatch):
    import leela.blocks.nb.presentation as pm
    c, root, app = rig
    cur = start(c, root).json() and held(app).cur
    def boom(*a, **kw): raise RuntimeError('boom')
    monkeypatch.setattr(pm, 'decks', boom)
    r = start(c, root)
    assert (r.status_code, r.json()) == (500, dict(ok=False, error='RuntimeError: boom')) and held(app).cur is cur

def _keyed(c, k, h, gets=True):
    "Each keyed route asked with key `k` (`...` sends none): `(name, response)`. A query string holds only text, so `gets=False` asks the POST routes alone."
    ks = {} if k is ... else dict(k=k)
    if gets:
        for p in ('/present/audience', '/present/deck', f'/present/img/{h}'): yield p, c.get(p, params=ks)
    for p, b in MUTATIONS: yield p, c.post(p, json={**b, **ks})

def test_every_keyed_route_refuses_cross_site_and_bad_keys(rig):
    c, root, app = rig
    old = start(c, root).json()['key']; k = start(c, root).json()['key']; cur = held(app).cur; at = dict(cur['at'])
    h = _sha(RED)
    for name, r in [(p, c.get(p, params=dict(k=k))) for p in ('/present/audience', '/present/deck', f'/present/img/{h}')]:
        assert r.status_code == 200, name
    assert c.post('/present/at', json=dict(MUTATIONS[0][1], k=k)).status_code == 200 and held(app).cur['at'] != at
    at = dict(cur['at'])
    for hdrs in ({'sec-fetch-site': 'cross-site'}, {'host': 'attacker.example'}, {'origin': 'http://evil.example'}):
        for p in ('/present/audience', '/present/deck', f'/present/img/{h}'): assert c.get(p, params=dict(k=k), headers=hdrs).status_code == 421, (p, hdrs)
        for p, b in [('/present/start', body(root))] + MUTATIONS:
            assert c.post(p, json=dict(b, k=k), headers=hdrs).status_code == 421, (p, hdrs)
        assert held(app).cur is cur and cur['key'] == k and cur['at'] == at, hdrs
    texts, others = [..., '', '0' * 32, old, k.upper(), k + 'x'], [None, 7, True, ['x'], {'k': k}]
    for bad, gets in [(x, True) for x in texts] + [(x, False) for x in others]:
        for name, r in _keyed(c, bad, h, gets):
            assert (r.status_code, r.json()) == (403, dict(ok=False, error=BAD_KEY)) and _shut(r), (name, bad)
        assert held(app).cur is cur and cur['at'] == at, bad
    for p, b in MUTATIONS:
        r = c.post(p, content=json.dumps(dict(b, k='\ud800')), headers={'Content-Type': 'application/json'})    # a lone surrogate, as JSON can hold
        assert (r.status_code, r.json()) == (403, dict(ok=False, error=BAD_KEY)) and held(app).cur is cur, p
    assert c.get(f'/present/img/{"0" * 64}', params=dict(k=old)).status_code == 403    # the key before the lookup
    r = c.post('/present/end', json=dict(k=k))
    assert (r.status_code, r.json()) == (200, dict(ok=True)) and _shut(r) and held(app).cur is None
    for bad in (..., k, old, ''):
        for name, r in _keyed(c, bad, h):
            assert (r.status_code, r.json()) == (410, dict(ok=False, error=ENDED)) and _shut(r), (name, bad)

def test_audience_and_deck_before_any_start(rig):
    c, _, _ = rig
    for p in ('/present/audience', '/present/deck'):
        r = c.get(p, params=dict(k='0' * 32))
        assert (r.status_code, r.json()) == (410, dict(ok=False, error=ENDED)), p

def test_a_stale_tab_cannot_move_or_end_the_new_presentation(rig):
    c, root, app = rig
    old = start(c, root).json()['key']
    new = start(c, root, start=dict(slide=1, step=0)).json(); cur = held(app).cur
    for p, b in MUTATIONS:
        r = c.post(p, json=dict(b, k=old))
        assert (r.status_code, r.json()) == (403, dict(ok=False, error=BAD_KEY)), p
    assert held(app).cur is cur and cur['at'] == new['at'] and c.get('/present/deck', params=dict(k=new['key'])).status_code == 200
    for p in ('/present/audience', '/present/deck'): assert c.get(p, params=dict(k=old)).status_code == 403, p

def test_images_are_the_live_presentations_by_key_not_by_hash(rig):
    c, root, _ = rig
    a = start(c, root).json()['key']; h = _sha(RED)
    r = c.get(f'/present/img/{h}', params=dict(k=a))
    assert r.status_code == 200 and r.content == RED and r.headers['content-type'] == 'image/png' and _shut(r)
    b = start(c, root).json()['key']
    assert c.get(f'/present/img/{h}', params=dict(k=a)).status_code == 403 and c.get(f'/present/img/{h}', params=dict(k=b)).content == RED
    cells = copy.deepcopy(CELLS); cells[2]['outputs'] = [_out(GREEN)]
    n = start(c, root, cells=cells).json()['key']
    assert c.get(f'/present/img/{_sha(GREEN)}', params=dict(k=n)).content == GREEN
    for x in (h, h.upper(), 'zz', h + '0'):
        r = c.get(f'/present/img/{x}', params=dict(k=n))
        assert (r.status_code, r.json()) == (404, dict(ok=False, error='No such image.')) and _shut(r), x
    r = c.get('/present/img/..%2F..%2Fpic.png', params=dict(k=n))    # a slash is no hash: the route is never reached
    assert r.status_code == 404 and r.content != BLUE

class _Page(HTMLParser):
    def __init__(self): super().__init__(); self.scripts, self.links, self.body, self.inline = [], [], None, []
    def handle_starttag(self, tag, a):
        a = dict(a); self.tag = tag
        if tag == 'script': self.scripts.append(a)
        if tag == 'link': self.links.append(a)
        if tag == 'body': self.body = a
        if any(k.startswith('on') for k in a): self.inline.append((tag, a))
    def handle_data(self, d):
        if getattr(self, 'tag', '') in ('script', 'style') and d.strip(): self.inline.append((self.tag, d))

def _asset(name):
    from leela.core.web import asset
    return asset(name)

def test_audience_page_headers(rig):
    c, root, _ = rig
    k = start(c, root).json()['key']
    r = c.get('/present/audience', params=dict(k=k))
    assert r.status_code == 200 and r.headers['content-type'].startswith('text/html')
    assert r.headers['content-security-policy'] == CSP and r.headers['referrer-policy'] == 'no-referrer' and _shut(r)
    p = _Page(); p.feed(r.text)
    assert p.inline == [] and all(set(s) <= {'src', 'defer'} for s in p.scripts) and p.body == {'data-page': 'audience'}
    assert [s['src'] for s in p.scripts] == [f'/present/stage.js?v={_sha(STAGE)[:16]}', _asset('lee-rupaka.js'), _asset('lee-slides.js')]
    # Task 4 on purpose: code on a slide needs the highlight colours of `lee-hl.css`
    assert [l['href'] for l in p.links if l.get('rel') == 'stylesheet'] == [_asset('lee-ide.css'), _asset('lee-slides.css'), _asset('lee-hl.css')]
    assert k not in r.text

def test_stage_js_is_abhyasas_own_file_without_a_key(rig):
    c, root, _ = rig
    for q in ('', f'?v={_sha(STAGE)[:16]}'):
        r = c.get('/present/stage.js' + q)
        assert r.status_code == 200 and r.content == STAGE, q
        assert r.headers['content-type'] == 'text/javascript; charset=utf-8' and r.headers['x-content-type-options'] == 'nosniff'
        assert r.headers['cache-control'] == 'public, max-age=31536000, immutable'
    assert c.post('/present/stage.js').status_code == 405
    assert c.get('/present/stage.js', headers={'sec-fetch-site': 'cross-site'}).status_code == 421
    assert c.get('/present/stage.css').status_code == 404

def test_a_bounded_queue_drops_the_oldest():
    from leela.blocks.nb.presentation import Drop
    q = Drop(3)
    for i in range(5): q.put_nowait(i)
    assert [q.get_nowait() for _ in range(q.qsize())] == [2, 3, 4]

def _scope(method, path, headers=()):
    path, _, q = path.partition('?')
    return {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': method, 'scheme': 'http', 'path': path, 'raw_path': path.encode(),
            'query_string': q.encode(), 'root_path': '', 'headers': [(b'host', b'127.0.0.1'), *headers], 'client': ('127.0.0.1', 50000), 'server': ('127.0.0.1', 80)}

async def _post(app, path, b):
    raw, msgs, sent = json.dumps(b).encode(), [], False
    async def receive():
        nonlocal sent
        if sent: await asyncio.Event().wait()
        sent = True; return {'type': 'http.request', 'body': raw, 'more_body': False}
    async def send(m): msgs.append(m)
    await app(_scope('POST', path, [(b'content-type', b'application/json'), (b'content-length', str(len(raw)).encode())]), receive, send)
    return msgs[0]['status'], json.loads(b''.join(m.get('body', b'') for m in msgs if m['type'] == 'http.response.body'))

async def _listen(app, got, stop, path='/present/events'):
    "Read the SSE stream at `path` into `got` as `(event, data)` until `stop` is set or the stream ends, then hang up."
    sent, buf = False, ['']
    async def receive():
        nonlocal sent
        if not sent: sent = True; return {'type': 'http.request', 'body': b'', 'more_body': False}
        await stop.wait(); return {'type': 'http.disconnect'}
    async def send(m):
        if m['type'] != 'http.response.body' or not m.get('body'): return
        *done, buf[0] = (buf[0] + m['body'].decode()).split('\n\n')
        for f in done:
            ev = dict(l.split(': ', 1) for l in f.split('\n') if ': ' in l and not l.startswith(':'))
            if 'event' in ev: got.append((ev['event'], json.loads(ev['data'])))
    await app(_scope('GET', path), receive, send)

async def _until(cond, t=10):
    for _ in range(int(t / .01)):
        if cond(): return
        await asyncio.sleep(.01)
    raise AssertionError('timed out')

@pytest.fixture
def bare(tmp_path):
    (root := tmp_path/'ws').mkdir()
    ws = Workspace(roots=[root], python=sys.executable)
    app = ide_app(ws)
    try: yield LoopbackHostGuard(app), app.state.presentation, root
    finally: ws.shutdown_now()

def test_a_second_start_ends_the_first(bare):
    app, pres, root = bare
    async def go():
        one, two, stop = [], [], asyncio.Event()
        t1 = asyncio.create_task(_listen(app, one, stop))
        await _until(lambda: one)
        # Task 6 on purpose: the first event also names the server's boot and the page that holds the presenter screen
        assert one[0] == ('presentation', {'id': None, 'boot': pres.boot, 'holder': None})
        a = (await _post(app, '/present/start', body(root)))[1]
        t2 = asyncio.create_task(_listen(app, two, stop))
        await _until(lambda: two)
        assert two[0] == ('presentation', {'id': a['id'], 'boot': pres.boot, 'holder': a['holder']}) and len(pres.subs) == 2
        b = (await _post(app, '/present/start', body(root)))[1]
        ended = lambda g: [d for e, d in g if e == 'presentation-ended']
        await _until(lambda: ended(one) and ended(two))
        assert ended(one) == ended(two) == [dict(id=a['id'], reason='replaced')]
        assert (await _post(app, '/present/at', dict(MUTATIONS[0][1], k=a['key'])))[0] == 403
        assert (await _post(app, '/present/end', dict(k=b['key']))) == (200, dict(ok=True))
        await _until(lambda: len(ended(one)) == 2)
        assert ended(one)[1] == ended(two)[1] == dict(id=b['id'], reason='ended') and a['key'] not in json.dumps(one + two)
        stop.set(); await asyncio.wait_for(asyncio.gather(t1, t2), 10)
        assert not pres.subs
    asyncio.run(go())

@pytest.mark.parametrize('order', ['later_first', 'earlier_first'])
def test_overlapping_starts_keep_only_the_latest(bare, monkeypatch, order):
    import leela.blocks.nb.presentation as pm
    app, pres, root = bare
    real, gates, inside = pm.decks, [threading.Event(), threading.Event()], [threading.Event(), threading.Event()]
    def gated(*a, **kw):
        n = sum(e.is_set() for e in inside); inside[n].set()
        assert gates[n].wait(10); return real(*a, **kw)
    async def go():
        live = (await _post(app, '/present/start', body(root)))[1]
        monkeypatch.setattr(pm, 'decks', gated)
        ca, cb = copy.deepcopy(CELLS), copy.deepcopy(CELLS)
        ca[2]['outputs'], cb[2]['outputs'] = [_out(GREEN)], [_out(BLUE)]
        ta = asyncio.create_task(_post(app, '/present/start', body(root, cells=ca)))
        assert await asyncio.to_thread(inside[0].wait, 10)
        tb = asyncio.create_task(_post(app, '/present/start', body(root, cells=cb)))
        assert await asyncio.to_thread(inside[1].wait, 10)
        assert pres.cur['key'] == live['key']    # nothing replaces the live presentation while the builds run
        first, then = ((1, tb), (0, ta)) if order == 'later_first' else ((0, ta), (1, tb))
        gates[first[0]].set(); r1 = await first[1]
        gates[then[0]].set(); r2 = await then[1]
        ra, rb = (r2, r1) if order == 'later_first' else (r1, r2)
        assert ra == (409, dict(ok=False, error=NEWER)) and rb[0] == 200, (ra, rb)
        assert pres.cur['key'] == rb[1]['key'] and set(pres.cur['images']) == {_sha(BLUE)}
        assert (await _post(app, '/present/end', dict(k=live['key'])))[0] == 403
    asyncio.run(go())

def test_an_end_during_a_build_discards_the_build(bare, monkeypatch):
    import leela.blocks.nb.presentation as pm
    app, pres, root = bare
    real, gate, inside = pm.decks, threading.Event(), threading.Event()
    def gated(*a, **kw): inside.set(); assert gate.wait(10); return real(*a, **kw)
    async def go():
        live = (await _post(app, '/present/start', body(root)))[1]
        monkeypatch.setattr(pm, 'decks', gated)
        t = asyncio.create_task(_post(app, '/present/start', body(root)))
        assert await asyncio.to_thread(inside.wait, 10)
        assert (await _post(app, '/present/end', dict(k=live['key']))) == (200, dict(ok=True)) and pres.cur is None
        gate.set()
        assert (await t) == (409, dict(ok=False, error=NEWER)) and pres.cur is None
    asyncio.run(go())

def _setup(rel):
    spec = importlib.util.spec_from_file_location(f'pkg_{Path(rel).parent.name}', ROOT/rel)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m

@pytest.mark.parametrize('rel', ['packaging/macos/setup.py', 'packaging/windows/setup.py'])
def test_the_desktop_builds_carry_abhyasas_stage_js(rel):
    "`/present/stage.js` reads the file through `importlib.resources`; a scanned package keeps only bytecode in the freezer's zip."
    assert 'abhyasa' in _setup(rel).PACKAGES
    assert (Path(importlib.util.find_spec('abhyasa').submodule_search_locations[0])/'core'/'stage.js').read_bytes() == STAGE

from rupaka.spec import demo, gate, is_, slider   # noqa: E402

SPEC = demo('d1', title='Weights', state={'x': 2}, blocks=[slider('x', label='x', min=0, max=4, step=1), gate('g1', 'Which one?', ['one', 'two'], is_('two'), why='because')])
DEMO_CELLS = CELLS + [dict(id='m4', cell_type='markdown', source=f'## Demo\n\n```rupaka\n{json.dumps(SPEC)}\n```', outputs=[])]
DEMO_LINE = LINE + [dict(items=[dict(i=4, frag=-1)], notes=[], groups=0)]
MOVES = [dict(t='point', x=.25, y=.5), dict(t='demo', slug='d1', state={'x': 3}, gates={'g1': 'done'}, pick={'g1': 1}),
         dict(t='answers', slide='s3', slug='d1', gates={'g1': {'is': 'two'}}), dict(t='look', theme='leela:dark:relaxed'), dict(t='point', off=True)]
def _room(k): return f'/present/room?k={k}'
def _demo_body(root): return body(root, cells=copy.deepcopy(DEMO_CELLS), line=copy.deepcopy(DEMO_LINE))
def _bare(m): return {x: v for x, v in m.items() if x != 't'}

async def _stop(stop, *ts):
    stop.set(); await asyncio.wait_for(asyncio.gather(*ts), 10)

def test_presenter_moves_reach_the_room_and_a_reload_gets_the_state(bare):
    app, pres, root = bare
    async def go():
        a = (await _post(app, '/present/start', _demo_body(root)))[1]; k = a['key']
        got, stop = [], asyncio.Event()
        t = asyncio.create_task(_listen(app, got, stop, _room(a['ak'])))
        await _until(lambda: got)
        ev, st = got[0]
        assert ev == 'state' and st['at'] == dict(slide='s1', step=0, blank=False, size=10) and st['title'] == 'a'
        assert st['demo'] == [] and st['answers'] == [] and st['look']['theme']
        assert (await _post(app, '/present/at', dict(k=k, slide='s3', step=0, blank=True, size=12)))[0] == 200
        for m in MOVES: assert (await _post(app, '/present/move', dict(m, k=k))) == (200, dict(ok=True)), m
        await _until(lambda: len(got) == 2 + len(MOVES))
        assert got[1] == ('at', dict(slide='s3', step=0, blank=True, size=12))
        assert got[2:] == [(m['t'], _bare(m)) for m in MOVES]
        again, stop2 = [], asyncio.Event()
        t2 = asyncio.create_task(_listen(app, again, stop2, _room(a['ak'])))
        await _until(lambda: again)
        ev, st = again[0]
        assert ev == 'state' and st['at'] == dict(slide='s3', step=0, blank=True, size=12) and st['look']['theme'] == 'leela:dark:relaxed'
        assert st['demo'] == [_bare(MOVES[1])] and st['answers'] == [_bare(MOVES[2])]
        assert k not in json.dumps(got + again) and a['ak'] not in json.dumps(got + again)
        await _stop(stop, t); await _stop(stop2, t2)
        assert not pres.cur['rooms']
    asyncio.run(go())

def test_a_new_slide_and_a_reopened_gate_drop_the_stored_answers(bare):
    app, pres, root = bare
    async def go():
        k = (await _post(app, '/present/start', _demo_body(root)))[1]['key']
        await _post(app, '/present/at', dict(k=k, slide='s3', step=0, blank=False, size=10))
        for m in MOVES[1:3]: await _post(app, '/present/move', dict(m, k=k))
        assert list(pres.cur['live']['answers'])
        await _post(app, '/present/move', dict(MOVES[1], gates={}, pick={}, k=k))
        assert not pres.cur['live']['answers']
        for m in MOVES[1:3]: await _post(app, '/present/move', dict(m, k=k))
        await _post(app, '/present/at', dict(k=k, slide='s3', step=0, blank=False, size=10))
        assert pres.cur['live']['answers'], 'the same slide keeps them'
        await _post(app, '/present/at', dict(k=k, slide='s1', step=0, blank=False, size=10))
        assert not pres.cur['live']['answers']
    asyncio.run(go())

def test_the_room_stream_refuses_bad_keys_with_no_state(rig):
    c, root, _ = rig
    old = start(c, root).json()['key']; d = start(c, root).json(); k = d['key']
    for q in ({}, dict(k=''), dict(k='0' * 32), dict(k=old), dict(k=k.upper())):
        r = c.get('/present/room', params=q)
        assert (r.status_code, r.json()) == (403, dict(ok=False, error=BAD_KEY)) and _shut(r) and 'event:' not in r.text, q
    assert c.get('/present/room', params=dict(k=k), headers={'sec-fetch-site': 'cross-site'}).status_code == 421
    c.post('/present/end', json=dict(k=k))
    for q in (dict(k=k), dict(k=d['ak']), {}):
        r = c.get('/present/room', params=q)
        assert (r.status_code, r.json()) == (410, dict(ok=False, error=ENDED)) and 'event:' not in r.text, q

def test_the_audience_key_reads_and_never_moves(rig):
    c, root, app = rig
    d = start(c, root).json(); ak, cur = d['ak'], held(app).cur; at = dict(cur['at'])
    for p in ('/present/audience', '/present/deck', f'/present/img/{_sha(RED)}'): assert c.get(p, params=dict(k=ak)).status_code == 200, p
    for p, b in MUTATIONS:
        r = c.post(p, json=dict(b, k=ak))
        assert (r.status_code, r.json()) == (403, dict(ok=False, error=BAD_KEY)), p
    assert held(app).cur is cur and cur['at'] == at and d['key'] not in c.get('/present/deck', params=dict(k=ak)).text

def test_the_audience_cannot_post(rig):
    c, root, _ = rig
    ak = start(c, root).json()['ak']
    for p in ('/present/room', '/present/deck', '/present/audience', f'/present/img/{_sha(RED)}'):
        assert c.post(p, params=dict(k=ak), json={}).status_code == 405, p
    js = (ROOT/'leela'/'blocks'/'nb'/'slides.js').read_text()
    assert not re.search(r'method\s*:|POST|sendBeacon|XMLHttpRequest|WebSocket', js)
    assert not re.search(r'/present/(move|at|end|start|resume|out|show-error)\b', js)

def test_laser_moves_are_coalesced(bare):
    from leela.blocks.nb.presentation import Room
    q = Room(64)
    for i in range(5): q.put_nowait(('point', dict(x=i / 10, y=0)))
    q.put_nowait(('at', {'n': 1})); q.put_nowait(('point', dict(off=True))); q.put_nowait(('point', dict(x=.9, y=.9)))
    assert [q.get_nowait() for _ in range(q.qsize())] == [('point', dict(x=.4, y=0)), ('at', {'n': 1}), ('point', dict(x=.9, y=.9))]
    q = Room(3)
    for i in range(3): q.put_nowait(('demo', {'n': i}))
    q.put_nowait(('demo', {'n': 3}))
    q.put_nowait(('demo', {'n': 4}))
    assert q.stale and [q.get_nowait() for _ in range(q.qsize())] == [('stale', None)], 'a full queue closes the stream, so the page connects again for a new state'
    q = Room(3)
    for i in range(3): q.put_nowait(('demo', {'n': i}))
    q.put_nowait(('end', {}))
    assert [q.get_nowait() for _ in range(q.qsize())] == [('end', {})], 'an end is never dropped'
    app, pres, root = bare
    async def go():
        a = (await _post(app, '/present/start', body(root)))[1]
        got, stop = [], asyncio.Event()
        t = asyncio.create_task(_listen(app, got, stop, _room(a['ak'])))
        await _until(lambda: got)
        for i in range(20): assert (await _post(app, '/present/move', dict(t='point', x=i / 20, y=.5, k=a['key'])))[0] == 200
        await _until(lambda: got[-1] == ('point', dict(x=19 / 20, y=.5)))
        assert 1 <= sum(e == 'point' for e, _ in got) <= 20
        await _stop(stop, t)
    asyncio.run(go())

def test_a_room_that_connects_again_gets_blank_and_no_laser(bare):
    "The server keeps blank in `at` and never keeps a laser point, so a fresh or reconnecting audience draws blank and no stale dot."
    app, pres, root = bare
    async def go():
        a = (await _post(app, '/present/start', body(root)))[1]; k = a['key']
        await _post(app, '/present/at', dict(k=k, slide='s1', step=0, blank=True, size=10))
        assert (await _post(app, '/present/move', dict(t='point', x=.5, y=.5, k=k)))[0] == 200
        got, stop = [], asyncio.Event()
        t = asyncio.create_task(_listen(app, got, stop, _room(a['ak'])))
        await _until(lambda: got)
        ev, st = got[0]
        # Task 7 on purpose: the state also holds the latest output of each code cell
        assert ev == 'state' and st['at']['blank'] is True and 'point' not in json.dumps(st) and set(st) == {'title', 'at', 'look', 'demo', 'answers', 'outs'}
        await _stop(stop, t)
    asyncio.run(go())

BAD_MOVES = [dict(t='go', slide='s1', beat=1), dict(t='point', x=1.5, y=0), dict(t='point', x=.1), dict(t='point', x=.1, y=.1, z=1), dict(t='point', off=False),
             dict(t='point', x=True, y=0), dict(t='point', x=float('nan'), y=0),
             dict(t='demo', slug='Bad Slug', state={}, gates={}), dict(t='demo', slug='d2', state={}, gates={}), dict(t='demo', slug='d1', state=[], gates={}),
             dict(t='demo', slug='d1', state={}, gates={'g1': 'open'}), dict(t='demo', slug='d1', state={}, gates={}, pick={'g1': 0}),
             dict(t='demo', slug='d1', state={'__proto__': 1}, gates={}), dict(t='demo', slug='d1', state={'a': {'b': {'c': {'d': {'e': {'f': {'g': {'h': 1}}}}}}}}, gates={}),
             dict(t='demo', slug='d1', state={'s': '\U0001F600' * 32760}, gates={}),
             dict(t='answers', slide='s1', slug='d1', gates={'g1': {'no': 1}}), dict(t='answers', slide='s9', slug='d1', gates={'g1': {'is': 1}}),
             dict(t='look', theme='x'), dict(t='look', theme='leela:dark:relaxed', extra=1), dict(slug='d1')]

def test_a_bad_move_sends_nothing(bare):
    app, pres, root = bare
    async def go():
        a = (await _post(app, '/present/start', _demo_body(root)))[1]
        got, stop = [], asyncio.Event()
        t = asyncio.create_task(_listen(app, got, stop, _room(a['ak'])))
        await _until(lambda: got)
        live = copy.deepcopy(pres.cur['live'])
        for m in BAD_MOVES:
            s, r = await _post(app, '/present/move', dict(m, k=a['key']))
            assert s == 400 and not r['ok'], m
        assert pres.cur['live'] == live
        assert (await _post(app, '/present/move', dict(MOVES[3], k=a['key'])))[0] == 200
        await _until(lambda: len(got) > 1)
        assert got[1:] == [('look', _bare(MOVES[3]))]
        await _stop(stop, t)
    asyncio.run(go())

def test_a_move_just_under_the_limit_is_sent(bare):
    "The limit counts UTF-16 units, as `JSON.stringify` does: an astral character is two."
    from leela.blocks.nb.show import _size
    app, pres, root = bare
    async def go():
        k = (await _post(app, '/present/start', _demo_body(root)))[1]['key']
        m = dict(t='demo', slug='d1', state={'s': ''}, gates={})
        m['state']['s'] = '\U0001F600' * ((65536 - _size({'v': 1, **m})) // 2)
        assert 65534 <= _size({'v': 1, **m}) <= 65536
        assert (await _post(app, '/present/move', dict(m, k=k)))[0] == 200
        m['state']['s'] += 'xyz'
        assert (await _post(app, '/present/move', dict(m, k=k)))[0] == 400
    asyncio.run(go())

def test_end_and_replace_send_end_without_the_key(bare):
    app, pres, root = bare
    async def go():
        a = (await _post(app, '/present/start', body(root)))[1]
        one, stop = [], asyncio.Event()
        t1 = asyncio.create_task(_listen(app, one, stop, _room(a['ak'])))
        await _until(lambda: one)
        b = (await _post(app, '/present/start', body(root)))[1]
        await asyncio.wait_for(t1, 10)
        assert one[-1] == ('end', {}) and [e for e, _ in one] == ['state', 'end']
        two = []
        t2 = asyncio.create_task(_listen(app, two, stop, _room(b['key'])))
        await _until(lambda: two)
        assert (await _post(app, '/present/end', dict(k=b['key'])))[0] == 200
        await asyncio.wait_for(t2, 10)
        assert two[-1] == ('end', {})
        s = json.dumps(one + two)
        assert all(x not in s for x in (a['key'], a['ak'], b['key'], b['ak']))
    asyncio.run(go())

def test_the_audience_count_follows_the_room_streams(bare):
    app, pres, root = bare
    async def go():
        a = (await _post(app, '/present/start', body(root)))[1]
        ev, stop = [], asyncio.Event()
        te = asyncio.create_task(_listen(app, ev, stop))
        await _until(lambda: len(ev) >= 2)
        assert ev[:2] == [('presentation', {'id': a['id'], 'boot': pres.boot, 'holder': a['holder']}), ('audience', {'id': a['id'], 'n': 0})]
        rooms, rstop = [[], []], asyncio.Event()
        ts = [asyncio.create_task(_listen(app, g, rstop, _room(a['ak']))) for g in rooms]
        await _until(lambda: ('audience', {'id': a['id'], 'n': 2}) in ev)
        await _stop(rstop, *ts)
        await _until(lambda: ev[-1] == ('audience', {'id': a['id'], 'n': 0}))
        assert a['key'] not in json.dumps(ev) and a['ak'] not in json.dumps(ev)
        await _stop(stop, te)
    asyncio.run(go())

def test_resume_returns_the_servers_state_without_a_new_key_and_writes_nothing(rig):
    "A reloaded presenter gets the stored place, blank, size, look, deck, keys and code sources; the place, the look and the room do not change."
    c, root, app = rig
    a = start(c, root).json(); k = a['key']
    assert c.post('/present/at', json=dict(k=k, slide='s1', step=1, blank=True, size=12)).status_code == 200
    assert c.post('/present/move', json=dict(k=k, t='look', theme='leela:dark:relaxed')).status_code == 200
    cur = held(app).cur; before = copy.deepcopy({x: cur[x] for x in ('at', 'room', 'presenter', 'live', 'key', 'ak', 'id')})
    r = c.post('/present/resume', json=dict(k=k))
    assert r.status_code == 200 and _shut(r), r.text
    d = r.json()
    assert (d['key'], d['ak'], d['id'], d['audience']) == (k, a['ak'], a['id'], a['audience'])
    assert d['at'] == dict(slide='s1', step=1, blank=True, size=12) and d['look']['theme'] == d['presenter']['look']['theme'] == 'leela:dark:relaxed'
    assert d['presenter']['slides'] == a['presenter']['slides'] and d['live'] == dict(outs={}, demo={}, answers={})
    assert d['src'] == a['src'] == {'c2': 'print(1)'} and d['title'] == 'a' and 0 <= d['elapsed'] < 60
    assert d['boot'] == a['boot'] == held(app).boot and d['holder'] != a['holder'] and held(app).cur['holder'] == d['holder']
    assert held(app).cur is cur and {x: cur[x] for x in before} == before, 'resume writes nothing the room sees'
    for bad in (a['ak'], '0' * 32, ''):
        assert c.post('/present/resume', json=dict(k=bad)).status_code == 403, bad
    b = start(c, root).json()
    assert c.post('/present/resume', json=dict(k=k)).status_code == 403 and c.post('/present/resume', json=dict(k=b['key'])).status_code == 200
    c.post('/present/end', json=dict(k=b['key']))
    r = c.post('/present/resume', json=dict(k=b['key']))
    assert (r.status_code, r.json()) == (410, dict(ok=False, error=ENDED)) and r.headers['x-leela-boot'] == held(app).boot

def test_the_deck_names_the_servers_boot_so_a_window_can_tell_a_restart(rig):
    c, root, app = rig
    ak = start(c, root).json()['ak']
    assert c.get('/present/deck', params=dict(k=ak)).headers['x-leela-boot'] == held(app).boot
    assert c.get('/present/deck', params=dict(k='0' * 32)).headers['x-leela-boot'] == held(app).boot
    from leela.blocks.nb.presentation import Presentation
    assert re.fullmatch('[0-9a-f]{16}', held(app).boot) and held(app).boot != Presentation().boot, 'a new server has a new boot'

def test_a_resume_tells_the_other_pages_who_holds_the_presenter_screen(bare):
    "A takeover or a reload names a new holder on `/present/events`, so an old presenter page closes; no event holds a key."
    app, pres, root = bare
    async def go():
        a = (await _post(app, '/present/start', body(root)))[1]
        ev, stop = [], asyncio.Event()
        t = asyncio.create_task(_listen(app, ev, stop))
        await _until(lambda: ev)
        s, r = await _post(app, '/present/resume', dict(k=a['key']))
        assert s == 200
        await _until(lambda: ('presenter', dict(id=a['id'], holder=r['holder'])) in ev)
        assert a['key'] not in json.dumps(ev) and a['ak'] not in json.dumps(ev)
        await _stop(stop, t)
    asyncio.run(go())

ERR = {'output_type': 'error', 'ename': 'ZeroDivisionError', 'evalue': 'division by zero',
       'traceback': ['\x1b[31mTraceback <b>x</b>\x1b[0m', 'ZeroDivisionError: division by zero']}
def _stream(t): return {'output_type': 'stream', 'name': 'stdout', 'text': t}
OUT_CELLS = CELLS + [dict(id='c4', cell_type='code', source='print(2)', outputs=[_stream('DECK-OUT\n')])]
OUT_LINE = [LINE[0], dict(items=[dict(i=3, frag=-1), dict(i=4, frag=-1)], notes=[], groups=0)]
def _out_body(root): return body(root, cells=copy.deepcopy(OUT_CELLS), line=copy.deepcopy(OUT_LINE))
def _o(k, cell, gen, seq, outputs=(), done=True): return dict(k=k, cell=cell, gen=gen, seq=seq, outputs=list(outputs), done=done)

def test_output_goes_to_any_code_cell_of_the_deck_in_order_and_a_reload_gets_it(bare):
    "Output for a code cell on another slide is kept with no audience window, sent as `out` in order, and in each new `state`."
    app, pres, root = bare
    async def go():
        a = (await _post(app, '/present/start', _out_body(root)))[1]; k = a['key']
        for cell in ('m1', 'm0', 'nope', 7):
            assert (await _post(app, '/present/out', _o(k, cell, 1, 1)))[0] == 400 and not pres.cur['live']['outs'], cell
        for bad in (dict(gen=0), dict(gen=True), dict(seq=-1), dict(seq=1.5), dict(done='yes'), dict(outputs={}), dict(outputs=['x']), dict(extra=1)):
            assert (await _post(app, '/present/out', {**_o(k, 'c2', 1, 1), **bad}))[0] == 400, bad
        s, r = await _post(app, '/present/out', _o(k, 'c4', 1, 2, [_stream('second slide 2\n')], done=False))
        assert s == 200 and r['msg'] == dict(cell='c4', gen=1, seq=2, html='<pre>second slide 2\n</pre>') and r['error'] is None, r
        assert (await _post(app, '/present/out', _o(k, 'c4', 1, 1, [_stream('older\n')])))[1] == dict(ok=True, stale=True)
        assert (await _post(app, '/present/out', _o(k, 'c4', 1, 2, [_stream('same\n')])))[1] == dict(ok=True, stale=True)
        got, stop = [], asyncio.Event()
        t = asyncio.create_task(_listen(app, got, stop, _room(a['ak'])))
        await _until(lambda: got)
        assert got[0][0] == 'state' and got[0][1]['outs'] == [dict(cell='c4', gen=1, seq=2, html='<pre>second slide 2\n</pre>')]
        assert (await _post(app, '/present/out', _o(k, 'c4', 2, 1, [_stream('rerun\n')])))[0] == 200
        assert (await _post(app, '/present/out', _o(k, 'c2', 1, 1, [_out(RED)])))[0] == 200
        await _until(lambda: len(got) == 3)
        assert got[1] == ('out', dict(cell='c4', gen=2, seq=1, html='<pre>rerun\n</pre>'))
        assert got[2][0] == 'out' and f'/present/img/{_sha(RED)}?k={a["ak"]}' in got[2][1]['html']
        again, stop2 = [], asyncio.Event()
        t2 = asyncio.create_task(_listen(app, again, stop2, _room(a['ak'])))
        await _until(lambda: again)
        outs = again[0][1]['outs']
        assert {o['cell']: (o['gen'], o['seq']) for o in outs} == {'c4': (2, 1), 'c2': (1, 1)} and 'rerun' in json.dumps(outs)
        assert k not in json.dumps(got + again)
        await _stop(stop, t); await _stop(stop2, t2)
    asyncio.run(go())

def test_a_failed_run_keeps_the_error_private_until_show_error_for_that_run(bare):
    "The room gets a failed run's other outputs; Show error needs the run that failed last, so a late click shows no older traceback."
    app, pres, root = bare
    async def go():
        a = (await _post(app, '/present/start', _out_body(root)))[1]; k = a['key']
        got, stop = [], asyncio.Event()
        t = asyncio.create_task(_listen(app, got, stop, _room(a['ak'])))
        await _until(lambda: got)
        s, r = await _post(app, '/present/out', _o(k, 'c2', 3, 1, [_stream('before the error\n'), ERR]))
        assert s == 200 and 'before the error' in r['msg']['html'] and 'ZeroDivisionError' not in json.dumps(r['msg'])
        assert r['error']['ename'] == 'ZeroDivisionError' and '\x1b' not in json.dumps(r['error'])
        assert (await _post(app, '/present/show-error', dict(k=k, cell='c4', gen=3)))[0] == 400, 'that cell has no run'
        for bad in (dict(gen='3'), dict(gen=True), dict(cell='m1'), dict(extra=1)):
            assert (await _post(app, '/present/show-error', {**dict(k=k, cell='c2', gen=3), **bad}))[0] == 400, bad
        s, r2 = await _post(app, '/present/show-error', dict(k=k, cell='c2', gen=3))
        h = r2['msg']['html']
        assert s == 200 and r2['msg']['seq'] == 2 and 'before the error' in h and 'ZeroDivisionError: division by zero' in h and '&lt;b&gt;x&lt;/b&gt;' in h and '<b>' not in h, r2
        await _until(lambda: len(got) == 3)
        assert 'ZeroDivisionError' not in json.dumps(got[1]) and got[2] == ('out', r2['msg'])
        assert (await _post(app, '/present/out', _o(k, 'c2', 4, 1, [], done=False)))[0] == 200
        assert (await _post(app, '/present/out', _o(k, 'c2', 4, 2, [dict(ERR, evalue='RUN-TWO', traceback=['ZeroDivisionError: RUN-TWO'])])))[0] == 200
        await _until(lambda: len(got) == 5)
        assert (await _post(app, '/present/show-error', dict(k=k, cell='c2', gen=3)))[1] == dict(ok=True, stale=True)
        await asyncio.sleep(.1)
        assert len(got) == 5 and 'division by zero' not in json.dumps(got[3:]), 'a late click reveals no older traceback'
        s, r3 = await _post(app, '/present/show-error', dict(k=k, cell='c2', gen=4))
        assert s == 200 and 'RUN-TWO' in r3['msg']['html'] and 'division by zero' not in r3['msg']['html']
        assert (await _post(app, '/present/out', _o(k, 'c2', 5, 1, [_stream('fixed\n')])))[1]['error'] is None
        assert (await _post(app, '/present/show-error', dict(k=k, cell='c2', gen=5)))[0] == 400, 'a run with no error'
        await _stop(stop, t)
    asyncio.run(go())

def test_a_kernel_restart_clears_every_code_cell_and_every_private_error(bare):
    "`/present/clear` empties each code cell of the deck, its first outputs too, drops each error, and makes older runs stale."
    app, pres, root = bare
    async def go():
        a = (await _post(app, '/present/start', _out_body(root)))[1]; k = a['key']
        assert (await _post(app, '/present/out', _o(k, 'c2', 2, 1, [ERR])))[0] == 200
        got, stop = [], asyncio.Event()
        t = asyncio.create_task(_listen(app, got, stop, _room(a['ak'])))
        await _until(lambda: got)
        assert (await _post(app, '/present/clear', dict(k=k, gen=2)))[1] == dict(ok=True, stale=True)
        assert (await _post(app, '/present/clear', dict(k=k, gen='3')))[0] == 400
        assert (await _post(app, '/present/clear', dict(k=k, gen=3))) == (200, dict(ok=True))
        await _until(lambda: len(got) == 3)
        assert sorted(d['cell'] for e, d in got[1:]) == ['c2', 'c4'] and all(e == 'out' and d['html'] == '' and d['gen'] == 3 for e, d in got[1:])
        assert (await _post(app, '/present/show-error', dict(k=k, cell='c2', gen=2)))[1] == dict(ok=True, stale=True)
        assert (await _post(app, '/present/show-error', dict(k=k, cell='c2', gen=3)))[0] == 400
        assert (await _post(app, '/present/out', _o(k, 'c2', 2, 9, [_stream('late\n')])))[1] == dict(ok=True, stale=True)
        assert (await _post(app, '/present/out', _o(k, 'c2', 4, 1, [_stream('after\n')])))[0] == 200
        again, stop2 = [], asyncio.Event()
        t2 = asyncio.create_task(_listen(app, again, stop2, _room(a['ak'])))
        await _until(lambda: again)
        assert {o['cell']: o['html'] for o in again[0][1]['outs']} == {'c2': '<pre>after\n</pre>', 'c4': ''}
        assert all(o.get('error') is None for o in pres.cur['live']['outs'].values() if o['cell'] == 'c4')
        await _stop(stop, t); await _stop(stop2, t2)
    asyncio.run(go())

def test_run_images_go_to_the_live_store_within_its_quota(rig, monkeypatch):
    "An image a run shows is served by hash with the audience key; at the store's limit the output falls back to its text."
    import leela.blocks.nb.presentation as pm
    from leela.blocks.nb.show import IMG_MOST
    c, root, app = rig
    a = c.post('/present/start', json=_out_body(root)).json(); k = a['key']
    r = c.post('/present/out', json=_o(k, 'c4', 1, 1, [_out(GREEN)])).json()
    assert f'/present/img/{_sha(GREEN)}?k={a["ak"]}' in r['msg']['html'] and k not in r['msg']['html']
    assert c.get(f'/present/img/{_sha(GREEN)}', params=dict(k=a['ak'])).content == GREEN
    imgs = held(app).cur['images']
    for i in range(IMG_MOST - len(imgs)): imgs[f'{i:064x}'] = ('image/png', b'x')
    pic = _png((1, 2, 3))
    fig = {'output_type': 'display_data', 'data': {'image/png': base64.b64encode(pic).decode(), 'text/plain': '<Figure FALLBACK>'}}
    h = c.post('/present/out', json=_o(k, 'c4', 2, 1, [fig])).json()['msg']['html']
    assert '&lt;Figure FALLBACK&gt;' in h and '<img' not in h and _sha(pic) not in imgs and len(imgs) == IMG_MOST
    monkeypatch.setattr(pm, 'MOST_RUN', 2000)
    r = c.post('/present/out', json=_o(k, 'c4', 3, 1, [_stream('x' * 4000)]))
    assert r.status_code == 400 and held(app).cur['live']['outs']['c4']['gen'] == 2, 'a body over the limit is refused before it is read'

def test_a_run_in_a_presentation_initialises_no_placeholder(tmp_path, monkeypatch):
    "`save: false` on `/nb/run/stream` writes neither the zero-byte notebook it runs nor another placeholder; an ordinary run still does."
    p, other = tmp_path/'new.ipynb', tmp_path/'other.ipynb'; p.touch(); other.touch()
    ws = Workspace(roots=[tmp_path]); ws.open(p)
    async def no_kernel(tab=None): raise RuntimeError('no kernel in this test')
    monkeypatch.setattr(ws, 'runtime', no_kernel)
    try:
        with TestClient(ide_app(ws)) as client:
            client.get('/tab/state', params={'path': str(p)})
            with pytest.raises(RuntimeError): client.post('/nb/run/stream', json={'path': str(p), 'i': 0, 'source': 'X = 1', 'save': False})
            assert (p.stat().st_size, other.stat().st_size) == (0, 0)
            with pytest.raises(RuntimeError): client.post('/nb/run/stream', json={'path': str(p), 'i': 0, 'source': 'X = 1'})
            assert p.stat().st_size and other.stat().st_size, 'ordinary Run keeps its behaviour'
    finally: ws.shutdown_now()
