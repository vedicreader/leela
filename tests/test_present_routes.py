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
MUTATIONS = [('/present/at', dict(slide='s2', step=0, blank=False, size=10)), ('/present/end', {})]
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
    assert d['ok'] and d['at'] == dict(slide='s1', step=0, blank=False, size=10) and d['audience'] == '/present/audience?k=' + d['key']
    ps = json.dumps(d['presenter'])
    assert 'SECRET-NOTE' in ps and 'UNSAVED-EDIT' in ps and [s['id'] for s in d['presenter']['slides']] == ['s1', 's2']
    deck = c.get('/present/deck', params=dict(k=d['key']))
    assert deck.status_code == 200 and deck.headers['content-security-policy'] == CSP and deck.headers['referrer-policy'] == 'no-referrer' and _shut(deck)
    room = deck.json(); rs = json.dumps(room)
    assert 'SECRET-NOTE' not in rs and 'UNSAVED-EDIT' in rs and str(root) not in rs and [s['id'] for s in room['slides']] == ['s1', 's2']
    code = room['slides'][0]['blocks'][1]
    assert code['cell'] == 'c2' and 'UNSAVED-OUT' in code['out'] and f'/present/img/{_sha(RED)}?k=' + d['key'] in code['out']
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
    assert [l['href'] for l in p.links if l.get('rel') == 'stylesheet'] == [_asset('lee-ide.css'), _asset('lee-slides.css')]
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
    return {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': method, 'scheme': 'http', 'path': path, 'raw_path': path.encode(),
            'query_string': b'', 'root_path': '', 'headers': [(b'host', b'127.0.0.1'), *headers], 'client': ('127.0.0.1', 50000), 'server': ('127.0.0.1', 80)}

async def _post(app, path, b):
    raw, msgs, sent = json.dumps(b).encode(), [], False
    async def receive():
        nonlocal sent
        if sent: await asyncio.Event().wait()
        sent = True; return {'type': 'http.request', 'body': raw, 'more_body': False}
    async def send(m): msgs.append(m)
    await app(_scope('POST', path, [(b'content-type', b'application/json'), (b'content-length', str(len(raw)).encode())]), receive, send)
    return msgs[0]['status'], json.loads(b''.join(m.get('body', b'') for m in msgs if m['type'] == 'http.response.body'))

async def _listen(app, got, stop):
    "Read `/present/events` into `got` as `(event, data)` until `stop` is set, then hang up."
    sent, buf = False, ['']
    async def receive():
        nonlocal sent
        if not sent: sent = True; return {'type': 'http.request', 'body': b'', 'more_body': False}
        await stop.wait(); return {'type': 'http.disconnect'}
    async def send(m):
        if m['type'] != 'http.response.body' or not m.get('body'): return
        *done, buf[0] = (buf[0] + m['body'].decode()).split('\n\n')
        for f in done:
            ev = dict(l.split(': ', 1) for l in f.split('\n') if ': ' in l)
            got.append((ev['event'], json.loads(ev['data'])))
    await app(_scope('GET', '/present/events'), receive, send)

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
        assert one[0] == ('presentation', {'id': None})
        a = (await _post(app, '/present/start', body(root)))[1]
        t2 = asyncio.create_task(_listen(app, two, stop))
        await _until(lambda: two)
        assert two[0] == ('presentation', {'id': a['id']}) and len(pres.subs) == 2
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
