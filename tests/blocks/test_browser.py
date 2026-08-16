"The inline browser: what it refuses to open, how a page becomes a tab, and a real page."

from __future__ import annotations

import asyncio, base64, functools, http.server, json, threading
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from leela.app import ide_app
from leela.blocks.browser.browser import Browser, BrowserUnavailable, WebPage

def test_a_bare_domain_becomes_https_rather_than_a_relative_path():
    assert Browser().check('example.com/a') == 'https://example.com/a'

@pytest.mark.parametrize('url', ['http://127.0.0.1:5001/', 'http://localhost:5001/',
                                 'http://169.254.169.254/latest/meta-data/'])
def test_the_browser_will_not_be_pointed_at_the_machine_it_is_running_on(url):
    "`fossick.check_url` is the same guard research fetches through, and just as necessary."
    with pytest.raises(Exception) as e: Browser().check(url)
    assert 'internal host' in str(e.value) or 'private or reserved' in str(e.value)

def test_a_non_web_scheme_is_refused():
    with pytest.raises(Exception): Browser().check('file:///etc/passwd')

def test_a_page_you_read_opens_in_your_own_browser_rather_than_the_driven_one(monkeypatch):
    "The CDP profile is fresh, so a story read through it meets a bot wall. Yours has your session."
    from leela.workspace import Workspace
    opened = []
    monkeypatch.setattr('webbrowser.open_new_tab', lambda url: opened.append(url) or True)
    with TestClient(ide_app(Workspace(roots=[]))) as c:
        assert c.get('/browser/external?url=https://example.com/a').json()['ok']
        refused = c.get('/browser/external?url=file:///etc/passwd').json()
    assert opened == ['https://example.com/a']
    assert refused.get('ok') is False and 'not an http address' in refused['error']

def test_an_empty_url_is_refused_before_anything_is_started():
    with pytest.raises(ValueError): Browser().check('   ')

def test_listing_pages_does_not_start_a_browser_to_discover_there_are_none(monkeypatch):
    "Asking a question must not have the side effect of booting Chrome. Opening a page may."
    b = Browser(port=1)
    monkeypatch.setattr(b, 'running', lambda: False)
    monkeypatch.setattr(b, 'cdp', lambda: (_ for _ in ()).throw(AssertionError('connected!')))
    with pytest.raises(BrowserUnavailable): asyncio.run(b.pages())

def test_a_page_becomes_a_tab_with_no_path_and_no_kernel(ws):
    t = ws.open_web('TARGET1', 'Some article')
    assert (t.kind, t.ref, t.path, t.private_kernel) == ('web', 'TARGET1', '', False)
    assert t.scratch and ws.tabs[ws.active] is t

def test_opening_the_same_page_twice_focuses_the_tab_rather_than_casting_it_twice(ws):
    first = ws.open_web('TARGET1', 'Article')
    ws.open_web('OTHER', 'Other')
    assert ws.open_web('TARGET1') is first and ws.tabs[ws.active] is first
    assert sum(t.kind == 'web' for t in ws.tabs) == 2

def test_the_tab_payload_names_the_page_and_nothing_else(ws):
    "No content crosses this route: the panel opens a socket and gets frames instead."
    ws.open_web('TARGET1', 'Some article')
    with TestClient(ide_app(ws)) as client:
        d = client.get('/tab/state').json()
    assert d == {'kind': 'web', 'title': 'Some article', 'target': 'TARGET1'}

class FakeBrowser:
    "Enough of `Browser` for the routes, with no Chrome anywhere near it."
    port = 9223

    def __init__(self, up=True, installed=True):
        self.up, self.installed, self.closed, self.opened = up, installed, [], []

    def running(self): return self.up

    def available(self): return self.up or self.installed

    async def pages(self):
        if not self.up: raise BrowserUnavailable('no browser running on the CDP port 9223')
        return [WebPage(id='T1', url='https://example.com/', title='Example'),
                WebPage(id='T2', url='chrome://newtab/', title='New Tab')]

    async def open(self, url, background=True):
        self.opened.append(url)
        return WebPage(id='T9', url=url, title='Opened')

    async def state(self, tid):
        return {'id': tid, 'url': 'https://example.com/', 'title': 'Example',
                'back': True, 'forward': False}

    async def markdown(self, tid, sel=None): return '# Example\n\nbody text\n'
    async def shut(self, tid): self.closed.append(tid); return True

@pytest.fixture
def client(ws):
    ws.browser = FakeBrowser()
    with TestClient(ide_app(ws)) as c: yield c, ws

def test_a_browser_that_is_installed_but_not_running_yet_still_counts_as_available(client):
    "Chrome starts on the first page that wants one, so \"not up yet\" is not \"not here\"."
    c, ws = client
    ws.browser.up = False
    assert c.get('/browser/ready').json() == {'ok': True, 'running': False, 'port': 9223}

def test_no_chrome_at_all_is_reported_as_no_browser(client):
    c, ws = client
    ws.browser.up = ws.browser.installed = False
    assert c.get('/browser/ready').json()['ok'] is False

@pytest.mark.parametrize('binary,want', [('chrome-that-exists', True), ('', False)])
def test_availability_is_answered_without_starting_anything(tmp_path, monkeypatch, binary, want):
    "The question must stay cheap: it is asked every time a research result is clicked."
    if binary: (tmp_path/binary).write_text('')
    monkeypatch.setattr('fossick.cdp.chrome_bin', lambda: binary and str(tmp_path/binary))
    b = Browser(port=1, profile=tmp_path)
    assert b.running() is False
    assert b.available() is want

def test_a_missing_browser_is_reported_in_the_panel_rather_than_as_a_500(client):
    c, ws = client
    ws.browser.up = False
    d = c.get('/browser/tabs').json()
    assert d['ok'] is False and d['tabs'] == [] and 'no browser running' in d['error']

def test_the_pages_chrome_already_has_are_offered_for_adoption(client):
    c, _ = client
    d = c.get('/browser/tabs').json()
    assert [t['id'] for t in d['tabs']] == ['T1', 'T2']

def test_opening_a_page_answers_with_the_tab_strip_like_every_other_tab_route(client):
    c, ws = client
    r = c.get('/browser/open?url=https://example.com/a')
    assert ws.browser.opened == ['https://example.com/a']
    assert 'id="tabbar"' in r.text and 'Opened' in r.text
    assert ws.tabs[ws.active].kind == 'web'

def test_a_refused_url_leaves_no_tab_behind(client):
    c, ws = client
    async def refuse(url, background=True): raise ValueError('nope')
    ws.browser.open = refuse
    before = len(ws.tabs)
    r = c.get('/browser/open?url=http://127.0.0.1/')
    assert 'lee-err' in r.text and 'nope' in r.text
    assert len(ws.tabs) == before

def test_adopting_a_page_gives_it_the_title_chrome_reports(client):
    c, ws = client
    c.get('/browser/attach?id=T1')
    assert ws.tabs[ws.active].ref == 'T1' and ws.tabs[ws.active].title == 'Example'

def test_reading_the_live_page_returns_markdown_and_where_it_came_from(client):
    c, _ = client
    d = c.get('/browser/markdown?id=T1').json()
    assert d['markdown'].startswith('# Example') and d['url'] == 'https://example.com/'
    assert d['note'] == ''      # not asked to remember

def test_remembering_a_live_page_files_it_in_the_vault_like_a_fetched_one(client):
    c, _ = client
    d = c.get('/browser/markdown?id=T1&remember=1').json()
    assert d['ok'] and d['note']

def test_closing_the_page_closes_it_in_chrome(client):
    c, ws = client
    assert c.get('/browser/close?id=T1').json() == {'ok': True}
    assert ws.browser.closed == ['T1']

class Recorder:
    def __init__(self): self.calls = []

    def __getattr__(self, name):
        async def f(*a, **kw): self.calls.append((name, a, kw))
        return f

def drive(cmd):
    from leela.blocks.browser.app import _drive
    r, sock = Recorder(), Recorder()
    asyncio.run(_drive(r, 'T1', cmd, sock))
    return r.calls

def test_a_click_is_forwarded_with_its_button_and_modifiers():
    (name, args, kw), = drive({'t': 'mouse', 'kind': 'mousePressed', 'x': 10, 'y': 20,
                               'button': 'right', 'clicks': 2, 'modifiers': 8})
    assert name == 'mouse' and args == ('T1', 'mousePressed', 10, 20)
    assert kw == {'button': 'right', 'clicks': 2, 'modifiers': 8, 'dx': 0, 'dy': 0}

def test_a_keystroke_only_forwards_the_fields_chrome_accepts():
    "A stray field from a DOM KeyboardEvent would be a protocol error that kills the socket."
    (name, args, kw), = drive({'t': 'key', 'kind': 'keyDown', 'key': 'a', 'code': 'KeyA',
                               'windowsVirtualKeyCode': 65, 'isTrusted': True, 'junk': 1})
    assert name == 'key' and args == ('T1', 'keyDown')
    assert kw == {'key': 'a', 'code': 'KeyA', 'windowsVirtualKeyCode': 65}

def test_an_unknown_command_is_refused_rather_than_ignored():
    with pytest.raises(ValueError): drive({'t': 'summon'})

def test_hiding_the_window_stops_the_encoding_and_showing_it_starts_again():
    "A minimised app should not keep Chrome producing a JPEG per frame for nobody."
    assert [c[0] for c in drive({'t': 'pause'})] == ['stop_cast']
    assert [c[0] for c in drive({'t': 'resume', 'w': 800, 'h': 600})] == ['start_cast']

def test_the_stream_belongs_to_the_socket_rather_than_to_each_start(ws):
    """Pausing and resuming must not orphan the cast.

    Teardown stops the stream by owner. If `resume` took a fresh identity, the socket's own
    teardown would no longer match and a closed tab would leave Chrome encoding forever.
    """
    b = Browser(port=1)
    started = []

    async def fake_start(tid, w, h, quality=62, scale=1, owner=None):
        started.append(owner)
        b._casts[tid] = owner
        return w, h, owner

    b.start_cast = fake_start
    mine = object()
    asyncio.run(_drive_owned(b, {'t': 'resume', 'w': 800, 'h': 600}, mine))
    assert started == [mine] and b._casts['T1'] is mine

def test_two_attachers_to_one_page_get_the_same_session(monkeypatch):
    """Attaching twice is two CDP sessions, of which the cache keeps one.

    The caller left holding the other filters frames by a session id nothing will ever send,
    so its screencast is silent -- and the session it holds is never closed.
    """
    import fastcdp
    b, made = Browser(port=1), []

    class FakePage:
        is_open = True
        @staticmethod
        async def new(tid, cdp):
            await asyncio.sleep(0)          # the window: the other attacher runs here
            made.append(tid)
            return FakePage()

    monkeypatch.setattr(fastcdp, 'Page', FakePage, raising=False)
    monkeypatch.setattr(b, 'cdp', lambda: asyncio.sleep(0))
    first, second = asyncio.run(_both(b, 'T1'))
    assert made == ['T1'] and first is second is b._pages['T1']

async def _both(browser, tid): return await asyncio.gather(browser.page(tid), browser.page(tid))

def test_closing_a_page_forgets_the_cast_it_was_streaming(monkeypatch):
    "Chrome does not reuse target ids, so an entry left behind is one nothing will ever clear."
    b = Browser(port=1)
    b._pages['T1'], b._casts['T1'] = object(), object()
    monkeypatch.setattr(b, 'cdp', lambda: asyncio.sleep(0))
    assert asyncio.run(b.shut('T1')) is True
    assert 'T1' not in b._casts and 'T1' not in b._pages

async def _drive_owned(browser, cmd, owner):
    from leela.blocks.browser.app import _drive

    async def say(**kw): pass
    await _drive(browser, 'T1', cmd, say, owner)

# The page reports what reached it by renaming itself, so both input paths can be checked
# through `/browser/state` -- and listening on the document means the assertion does not
# depend on guessing where a button landed in the rendered frame.
PAGE = ("<!doctype html><meta charset=utf-8><title>idle</title>"
        "<style>body{font:16px sans-serif;margin:32px}</style>"
        "<h1>Inline browser fixture</h1>"
        "<p>A paragraph with enough prose in it that a reader has something to extract, "
        "which is what the markdown route is for.</p>"
        "<button id=b>Press</button>"
        "<script>addEventListener('click',()=>{document.title='clicked'});"
        "addEventListener('keydown',e=>{document.title+='+'+e.key});</script>")

@pytest.fixture
def site():
    "A page on loopback, served for the duration of one test."
    import tempfile
    d = Path(tempfile.mkdtemp())
    (d/'index.html').write_text(PAGE)
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(d))
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), h)
    srv.RequestHandlerClass.log_message = lambda *a, **k: None
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try: yield f'http://127.0.0.1:{srv.server_address[1]}/index.html'
    finally: srv.shutdown()

@pytest.mark.slow
def test_a_real_page_streams_frames_into_the_socket_and_takes_a_click(ws, site, monkeypatch,
                                                                      tmp_path):
    """The whole path, once: Chrome renders, a frame arrives, a click lands, the page reads.

    `FOSSICK_ALLOW_PRIVATE` because the fixture site is on loopback, which the URL guard is
    otherwise right to refuse -- see `test_the_browser_will_not_be_pointed_at...`. The profile
    is a throwaway rather than fossick's: Chrome allows one process per user-data-dir, so a
    suite sharing the real one would either fail to start or attach to the developer's session.
    """
    monkeypatch.setenv('FOSSICK_ALLOW_PRIVATE', '1')
    pytest.importorskip('fastcdp')
    profile = tmp_path/'chrome'
    # Start Chrome, but make no CDP connection here: a websocket belongs to the loop that
    # created it, and one opened by `asyncio.run` would be dead by the time the app used it.
    try: asyncio.run(_start_chrome(9401, profile))
    except Exception as e: pytest.skip(f'no Chrome to drive: {e}')

    ws.browser = Browser(port=9401, headless=True, profile=profile)
    with TestClient(ide_app(ws)) as client:
        assert 'id="tabbar"' in client.get(f'/browser/open?url={site}').text
        target = ws.tabs[ws.active].ref

        # Exactly two reads, both of which Chrome is guaranteed to send: `ready` on attach, and
        # the initial frame `startScreencast` always emits. A static page stops producing
        # frames once it has settled, so a third read here would simply block.
        with client.websocket_connect('/browser/ws') as sock:
            sock.send_text(json.dumps({'id': target, 'w': 800, 'h': 600}))
            ready = json.loads(sock.receive_text())
            assert ready['t'] == 'ready', ready
            assert (ready['w'], ready['h']) == (800, 600)
            assert ready['url'].startswith('http://127.0.0.1:')
            assert ready['title'] == 'idle'

            # Raw JPEG bytes, not base64 in JSON: a third fewer on the wire, and the client
            # can hand them straight to `createImageBitmap`. The screencast only emits for a
            # page Chrome believes is visible, which is why `start_cast` brings the target to
            # the front; without that this frame never arrives at all.
            frame = sock.receive()
            assert frame.get('bytes'), f'expected a binary frame, got {frame}'
            assert frame['bytes'][:2] == b'\xff\xd8', 'not a JPEG'

            for kind in ('mousePressed', 'mouseReleased'):
                sock.send_text(json.dumps({'t': 'mouse', 'kind': kind, 'x': 400, 'y': 300,
                                           'button': 'left', 'clicks': 1}))
            for kind in ('rawKeyDown', 'keyUp'):
                sock.send_text(json.dumps({'t': 'key', 'kind': kind, 'key': 'z', 'code': 'KeyZ',
                                           'windowsVirtualKeyCode': 90}))
            # Ask where the page is *after* the input. Commands are handled in order, so the
            # reply cannot arrive before the four events have been dispatched -- and closing
            # the socket instead would simply drop whatever had not been read yet.
            sock.send_text(json.dumps({'t': 'state'}))
            nav = _reply(sock, 'nav')

        # The page renamed itself for each event it received, so its title is the receipt.
        assert nav['title'] == 'clicked+z', f'input did not reach the page: {nav}'

        d = client.get(f'/browser/markdown?id={target}').json()
        assert 'Inline browser fixture' in d['markdown']
        assert 'a reader has something to extract' in d['markdown']

        assert client.get(f'/browser/close?id={target}').json() == {'ok': True}

def _reply(sock, kind, tries=40):
    "Read past any frames the page painted meanwhile, to the reply that must be coming."
    for _ in range(tries):
        m = sock.receive()
        if m.get('bytes') is not None: continue      # a frame; keep looking for the reply
        d = json.loads(m['text'])
        if d['t'] == kind: return d
    raise AssertionError(f'no {kind!r} reply arrived')

async def _start_chrome(port, profile):
    from fossick.cdp import _debug_ready, cdp_setup
    if not _debug_ready(port):
        await cdp_setup(port=port, user_data_dir=profile, headless=True, timeout=60)
