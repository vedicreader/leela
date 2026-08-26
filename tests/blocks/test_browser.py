"The inline browser: what it refuses to open, how a page becomes a tab, and a real page."

from __future__ import annotations

import asyncio, functools, http.server, json, threading, time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from leela.app import ide_app
from leela.blocks.browser.browser import (Browser, BrowserUnavailable, MAX_SCALE,
                                          SCALE_FLAG, WebPage)

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
        self.mine = set()

    def running(self): return self.up

    def available(self): return self.up or self.installed

    async def pages(self):
        if not self.up: raise BrowserUnavailable('no browser running on the CDP port 9223')
        return [WebPage(id='T1', url='https://example.com/', title='Example'),
                WebPage(id='T2', url='chrome://newtab/', title='New Tab')]

    async def open(self, url, background=True):
        self.opened.append(url)
        self.mine.add('T9')
        return WebPage(id='T9', url=url, title='Opened')

    async def state(self, tid):
        return {'id': tid, 'url': 'https://example.com/', 'title': 'Example',
                'back': True, 'forward': False}

    async def markdown(self, tid, sel=None): return '# Example\n\nbody text\n'
    async def shut(self, tid, mine_only=False):
        if mine_only and tid not in self.mine: return False
        self.closed.append(tid)
        return True

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

def test_closing_the_leela_tab_closes_the_page_it_opened(client):
    """`/browser/close` had no caller, so a page opened here outlived its tab for the session.

    The report: open a site, close the tab, and it is still on the list `browse_tabs` offers.
    """
    c, ws = client
    c.get('/browser/open?url=https://example.com/a')
    assert ws.tabs[ws.active].kind == 'web'
    c.post(f'/tab/close?i={ws.active}')
    assert ws.browser.closed == ['T9']
    assert not any(t.kind == 'web' for t in ws.tabs)

def test_closing_the_tab_for_an_adopted_page_leaves_the_page_alone(client):
    "A page from the user's own Chrome was only borrowed; the tab going away does not close it."
    c, ws = client
    c.get('/browser/attach?id=T1')
    c.post(f'/tab/close?i={ws.active}')
    assert ws.browser.closed == []

def test_a_tab_closes_even_when_chrome_will_not(client):
    "The strip must never be held by the browser: the tab is gone either way."
    c, ws = client
    async def wedged(tid, mine_only=False): raise RuntimeError('chrome is not answering')
    c.get('/browser/open?url=https://example.com/a')
    ws.browser.shut = wedged
    n = len(ws.tabs)
    assert 'id="tabbar"' in c.post(f'/tab/close?i={ws.active}').text
    assert len(ws.tabs) == n - 1

def test_no_chrome_is_started_merely_to_close_a_tab(client):
    "Closing a stale web tab after Chrome has quit must not boot one to close nothing."
    c, ws = client
    c.get('/browser/open?url=https://example.com/a')
    ws.browser.up = False
    async def boom(tid, mine_only=False): raise AssertionError('connected!')
    ws.browser.shut = boom
    c.post(f'/tab/close?i={ws.active}')
    assert not any(t.kind == 'web' for t in ws.tabs)

def test_a_page_leela_adopted_is_never_shut_by_the_owning_check(monkeypatch):
    b = Browser(port=1)
    monkeypatch.setattr(b, 'cdp', lambda: asyncio.sleep(0))
    assert asyncio.run(b.shut('ADOPTED', mine_only=True)) is False
    b._mine.add('OURS'); b._pages['OURS'] = object()
    assert asyncio.run(b.shut('OURS', mine_only=True)) is True
    assert 'OURS' not in b._mine

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

    async def fake_start(tid, w, h, quality=80, scale=1, owner=None):
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

class FakePage:
    "A `Page` that records the CDP calls `resize` and `start_cast` make."
    is_open = True
    def __init__(self): self.calls = []
    def __getattr__(self, domain):
        class D:
            def __getattr__(_, name):
                async def f(**kw): self.calls.append((name, kw))
                return f
        return D()

def _cast(scale, **kw):
    "Start a cast against a fake page and return what Chrome was told."
    b, p = Browser(port=1), FakePage()
    b._pages['T1'] = p
    out = asyncio.run(b.start_cast('T1', 900, 700, scale=scale, **kw))
    return out, dict(p.calls)

def test_the_frame_ceiling_leaves_room_for_a_browser_that_rasterises_above_one_to_one():
    """A frame captured at 1x and drawn into a 2x display is the blur this fixes.

    `maxWidth` was pinned to the viewport in CSS pixels, so a Chrome rasterising at 2x had its
    frame scaled straight back down to 1x before it reached the socket. It is a ceiling now.
    """
    (w, h, _), calls = _cast(2)
    assert (w, h) == (900, 700), 'the viewport stays in CSS pixels'
    assert calls['startScreencast']['maxWidth'] == 900*MAX_SCALE
    assert calls['startScreencast']['maxHeight'] == 700*MAX_SCALE

def test_the_page_is_told_the_device_pixel_ratio_of_the_panel_showing_it():
    "A page reads `devicePixelRatio` to pick between a 1x and a 2x asset."
    _, calls = _cast(2)
    assert calls['setDeviceMetricsOverride'] == {'width': 900, 'height': 700, 'mobile': False,
                                                 'deviceScaleFactor': 2.0}
    _, calls = _cast(4)
    assert calls['setDeviceMetricsOverride']['deviceScaleFactor'] == float(MAX_SCALE), 'clamped'

def test_the_frames_are_encoded_at_the_quality_text_needs():
    "Quality 62 leaves visible JPEG artefacts on body text, which is most of what a page is."
    _, calls = _cast(1)
    assert calls['startScreencast']['quality'] == 80

def test_chrome_is_started_at_the_scale_a_screencast_frame_is_rasterised_at(monkeypatch):
    """The only lever on how many pixels a frame carries is the browser's own scale factor.

    Measured against Chrome, a 200px div is 200 image pixels in the frame at every per-page
    `deviceScaleFactor`, and 400 with this flag. The flag only takes at launch, so a Chrome
    already running when Leela connects goes on sending 1x frames.
    """
    assert SCALE_FLAG == '--force-device-scale-factor=2'
    b, seen = Browser(port=1), {}
    async def fake_connect(**kw):
        seen.update(kw)
        raise RuntimeError('far enough')
    monkeypatch.setattr('fossick.cdp.cdp_connect', fake_connect)
    with pytest.raises(BrowserUnavailable): asyncio.run(b.cdp())
    assert seen['extra_flags'] == [SCALE_FLAG]

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
        "<script>addEventListener('click',e=>{document.title='at '+e.clientX+','+e.clientY});"
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
    # A free port, not a fixed one: `SCALE_FLAG` is taken at launch, so a Chrome already up on a
    # well-known port would be reused and would still be sending 1x frames.
    port = _free_port()
    try: asyncio.run(_start_chrome(port, profile))
    except Exception as e: pytest.skip(f'no Chrome to drive: {e}')

    ws.browser = Browser(port=port, headless=True, profile=profile)
    with TestClient(ide_app(ws)) as client:
        assert 'id="tabbar"' in client.get(f'/browser/open?url={site}').text
        target = ws.tabs[ws.active].ref

        # Exactly two reads, both of which Chrome is guaranteed to send: `ready` on attach, and
        # the initial frame `startScreencast` always emits. A static page stops producing
        # frames once it has settled, so a third read here would simply block.
        with client.websocket_connect('/browser/ws') as sock:
            sock.send_text(json.dumps({'id': target, 'w': 800, 'h': 600, 'scale': 2}))
            ready = json.loads(sock.receive_text())
            assert ready['t'] == 'ready', ready
            assert (ready['w'], ready['h']) == (800, 600), 'the viewport is CSS pixels'
            assert ready['url'].startswith('http://127.0.0.1:')
            assert ready['title'] == 'idle'

            # Raw JPEG bytes, not base64 in JSON: a third fewer on the wire, and the client
            # can hand them straight to `createImageBitmap`. The screencast only emits for a
            # page Chrome believes is visible, which is why `start_cast` brings the target to
            # the front; without that this frame never arrives at all.
            frame = sock.receive()
            assert frame.get('bytes'), f'expected a binary frame, got {frame}'
            assert frame['bytes'][:2] == b'\xff\xd8', 'not a JPEG'
            sizes = [_jpeg_size(frame['bytes'])]

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
            nav = _reply(sock, 'nav', sizes)
            # Chrome emits nothing for a page that has settled, and a metrics override resizes
            # the window it composites into asynchronously, so an early frame is the window as it
            # was. A restarted cast always emits one, and the window converges within a few.
            for _ in range(10):
                if sizes[-1] == (1600, 1200): break
                time.sleep(.2)
                sock.send_text(json.dumps({'t': 'resize', 'w': 800, 'h': 600, 'scale': 2}))
                sizes.append(_frame(sock))

        # The page renamed itself for each event it received, so its title is the receipt.
        assert nav['title'] == 'at 400,300+z', f'input did not land where it was aimed: {nav}'
        # The whole contract in two lines: twice the pixels on the wire, and the coordinates
        # still the CSS ones the panel measured.
        assert (1600, 1200) in sizes, f'an 800x600 viewport must cast at 2x: {sizes}'

        d = client.get(f'/browser/markdown?id={target}').json()
        assert 'Inline browser fixture' in d['markdown']
        assert 'a reader has something to extract' in d['markdown']

        assert client.get(f'/browser/close?id={target}').json() == {'ok': True}

def _reply(sock, kind, sizes=None, tries=40):
    "Read past any frames the page painted meanwhile, to the reply that must be coming."
    for _ in range(tries):
        m = sock.receive()
        if m.get('bytes') is not None:               # a frame; keep looking for the reply
            if sizes is not None: sizes.append(_jpeg_size(m['bytes']))
            continue
        d = json.loads(m['text'])
        if d['t'] == kind: return d
    raise AssertionError(f'no {kind!r} reply arrived')

def _frame(sock, tries=40):
    "The size of the next frame, reading past whatever the socket is saying meanwhile."
    for _ in range(tries):
        m = sock.receive()
        if m.get('bytes'): return _jpeg_size(m['bytes'])
    raise AssertionError('no frame arrived')

def _jpeg_size(b):
    "A JPEG's `(width, height)` off its first frame header, so the test needs no image library."
    i = 2
    while i + 9 < len(b):
        if b[i] != 0xFF: i += 1; continue
        marker, n = b[i+1], int.from_bytes(b[i+2:i+4], 'big')
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            return int.from_bytes(b[i+7:i+9], 'big'), int.from_bytes(b[i+5:i+7], 'big')
        i += 2 + n
    raise AssertionError('no JPEG frame header')

def _free_port():
    import socket
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

async def _start_chrome(port, profile):
    from fossick.cdp import _debug_ready, cdp_setup
    if not _debug_ready(port):
        await cdp_setup(port=port, user_data_dir=profile, headless=True, timeout=60,
                        extra_flags=[SCALE_FLAG])
