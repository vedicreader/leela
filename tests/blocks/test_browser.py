"The inline browser: what it refuses to open, how a page becomes a tab, and a real page."

from __future__ import annotations

import asyncio, contextlib, functools, http.server, json, threading, time
from pathlib import Path
from types import SimpleNamespace

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

class FakeConn:
    "A CDP connection that never says anything, for the socket routes."
    @contextlib.asynccontextmanager
    async def on(self, method): yield asyncio.Queue()

class FakeBrowser:
    "Enough of `Browser` for the routes, with no Chrome anywhere near it."
    port = 9223
    scale, guid = 1.0, 'G1'
    warning = 'the Chrome on port 9223 draws pages at 1x'

    def __init__(self, up=True, installed=True):
        self.up, self.installed, self.closed, self.opened = up, installed, [], []
        self.mine, self.quits = set(), 0

    def running(self): return self.up

    async def quit(self): self.quits += 1

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

    async def start_cast(self, tid, w, h, quality=80, scale=1, owner=None):
        return w or 800, h or 600, owner

    async def stop_cast(self, tid, owner=None): return True
    async def cdp(self): return FakeConn()
    async def page(self, tid): return SimpleNamespace(sid='S1')
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
    assert c.get('/browser/ready').json() == {'ok': True, 'running': False, 'port': 9223,
                                              'scale': 1.0}

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
    """`/browser/close` had no caller, so a page opened here outlived its tab for the session."""
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

class FakeCDP:
    "A CDP connection with an identity and a target list, for the ownership bookkeeping."
    is_open = True

    def __init__(self, guid='G1', targets=()):
        self.wsconn = f'ws://127.0.0.1:9/devtools/browser/{guid}'
        self.live, self.made, self.wedged = list(targets), 0, False

    @property
    async def pages(self): return [{'targetId': t, 'type': 'page'} for t in self.live]

    @property
    def target(self):
        cdp = self
        class T:
            @staticmethod
            async def createTarget(url, background=True):
                cdp.made += 1
                cdp.live.append(tid := f'NEW{cdp.made}')
                return tid
            @staticmethod
            async def closeTarget(targetId):
                if cdp.wedged: raise RuntimeError('chrome is not answering')
                if targetId in cdp.live: cdp.live.remove(targetId)
        return T

class StubPage:
    "A page that answers the two calls `open` and `_measure` make."
    is_open = True

    def __init__(self, raster=2, css=1): self.raster, self.css = raster, css
    async def eval(self, expr): return 'a page'

    @property
    def page(self):
        m = {'layoutViewport': {'clientWidth': self.raster},
             'cssLayoutViewport': {'clientWidth': self.css}}
        class D:
            @staticmethod
            async def getLayoutMetrics(): return m
            @staticmethod
            async def navigate(url): return {'loaderId': 'L'}
        return D

def wired(cdp, port=4321):
    "A `Browser` connected to `cdp`, taking back what it owns exactly as a real connect does."
    b = Browser(port=port)
    async def connect():
        if b._cdp is None or b._cdp is not cdp:
            b._cdp = cdp
            await b._own()
        return b._cdp
    async def page(tid): return StubPage()
    b.cdp, b.page = connect, page
    return b

def test_a_page_a_previous_leela_opened_is_still_closeable_after_a_restart():
    """`_mine` lived on the process, so a page opened before a restart could never be closed."""
    cdp = FakeCDP()
    tid = asyncio.run(wired(cdp).open('https://example.com/a')).id
    later = wired(cdp)                                    # a new process, an empty `_mine`
    assert asyncio.run(later.shut(tid, mine_only=True)) is True
    assert tid not in cdp.live

def test_a_page_from_a_different_chrome_launch_is_never_taken_back():
    "Ownership is keyed to the browser that answered, so a record cannot outlive its Chrome."
    cdp = FakeCDP('G1')
    tid = asyncio.run(wired(cdp).open('https://example.com/a')).id
    other = FakeCDP('G2', targets=[tid])                  # the same id, a different launch
    assert asyncio.run(wired(other).shut(tid, mine_only=True)) is False
    assert tid in other.live

def test_a_recorded_page_the_user_has_already_closed_is_not_taken_back():
    cdp = FakeCDP()
    tid = asyncio.run(wired(cdp).open('https://example.com/a')).id
    cdp.live.remove(tid)
    later = wired(cdp)
    asyncio.run(later.cdp())
    assert later._mine == set()

def test_a_chrome_that_replaces_another_on_the_port_owns_none_of_its_pages():
    "Reconnecting is not always to the same browser, and the ids do not carry over."
    b = wired(FakeCDP('G1'))
    asyncio.run(b.open('https://example.com/a'))
    assert b._mine
    b._cdp = FakeCDP('G2')
    asyncio.run(b._own())
    assert b._mine == set() and b.guid == 'G2'

def test_a_record_that_cannot_be_read_owns_nothing():
    "Erring towards not closing: an unreadable record spares every page rather than guessing."
    cdp = FakeCDP(targets=['THEIRS'])
    b = wired(cdp)
    p = b._owned_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{not json')
    assert asyncio.run(b.shut('THEIRS', mine_only=True)) is False
    assert 'THEIRS' in cdp.live

def test_a_close_chrome_refuses_leaves_the_page_owned():
    "A close that fails must not be the thing that makes a page unclosable."
    cdp = FakeCDP()
    b = wired(cdp)
    tid = asyncio.run(b.open('https://example.com/a')).id
    cdp.wedged = True
    assert asyncio.run(b.shut(tid, mine_only=True)) is False
    assert tid in b._mine
    cdp.wedged = False
    assert asyncio.run(wired(cdp).shut(tid, mine_only=True)) is True

def test_two_workspaces_on_one_chrome_do_not_forget_each_others_pages():
    "One record per port, and the hub serves several workspaces out of one process."
    cdp = FakeCDP()
    a = asyncio.run(wired(cdp).open('https://example.com/a')).id
    b = asyncio.run(wired(cdp).open('https://example.com/b')).id
    third = wired(cdp)
    asyncio.run(third.cdp())
    assert {a, b} <= third._mine

def test_adopting_a_page_records_no_ownership_of_it():
    cdp = FakeCDP(targets=['THEIRS'])
    b = wired(cdp)
    asyncio.run(b.cdp())
    assert b._mine == set() and not b._owned_path().exists()

def test_a_chrome_that_cannot_rasterise_at_the_wanted_scale_is_measured_and_said():
    """`SCALE_FLAG` takes at launch, so a Chrome that predates it goes on sending 1x frames."""
    b = Browser(port=1)
    asyncio.run(b._measure(StubPage(756, 756)))
    assert b.scale == 1
    assert 'port 1' in b.warning and SCALE_FLAG in b.warning and f'{MAX_SCALE}x' in b.warning

def test_a_chrome_that_rasterises_at_the_wanted_scale_says_nothing():
    b = Browser(port=1)
    asyncio.run(b._measure(StubPage(1000, 500)))
    assert b.scale == MAX_SCALE and b.warning == ''

def test_a_page_with_no_layout_yet_is_left_unmeasured():
    "An unmeasured browser is asked again at the next attach; a wrong 1 would never be revisited."
    b = Browser(port=1)
    asyncio.run(b._measure(StubPage(0, 0)))
    assert b.scale is None and b.warning == ''

def test_the_ready_frame_carries_the_note_and_the_browser_it_is_about(client):
    "The panel is where the user is looking, and the browser id is what it dedupes the note by."
    c, ws = client
    with c.websocket_connect('/browser/ws') as sock:
        sock.send_text(json.dumps({'id': 'T1', 'w': 800, 'h': 600, 'scale': 2}))
        m = json.loads(sock.receive_text())
    assert m['t'] == 'ready' and m['scale'] == 1.0 and m['browser'] == 'G1'
    assert 'draws pages at 1x' in m['note']

def test_a_page_leela_adopted_is_never_shut_by_the_owning_check():
    cdp = FakeCDP(targets=['ADOPTED'])
    b = wired(cdp)
    assert asyncio.run(b.shut('ADOPTED', mine_only=True)) is False
    assert 'ADOPTED' in cdp.live
    tid = asyncio.run(b.open('https://example.com/a')).id
    assert asyncio.run(b.shut(tid, mine_only=True)) is True
    assert 'OURS' not in b._mine and tid not in cdp.live

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
    """Pausing and resuming must not orphan the cast."""
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
    """Attaching twice is two CDP sessions, of which the cache keeps one."""
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
    """A frame captured at 1x and drawn into a 2x display is the blur this fixes."""
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
    """The only lever on how many pixels a frame carries is the browser's own scale factor."""
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
                                                                      tmp_path, request):
    """The whole path, once: Chrome renders, a frame arrives, a click lands, the page reads."""
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
    # Leela adopts this Chrome rather than starting it, so its own teardown rightly leaves it
    # running. Nothing else will: without this the suite leaks a headless Chrome per run.
    request.addfinalizer(lambda: asyncio.run(_quit(ws.browser)))
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

@pytest.mark.slow
def test_a_real_chrome_started_without_the_flag_is_measured_at_one_to_one(ws, site, monkeypatch,
                                                                          tmp_path):
    """The user's report, reproduced: Leela reuses a Chrome that predates the flag and it stays 1x."""
    monkeypatch.setenv('FOSSICK_ALLOW_PRIVATE', '1')
    pytest.importorskip('fastcdp')
    port = _free_port()
    try: asyncio.run(_start_chrome(port, tmp_path/'chrome', flags=[]))
    except Exception as e: pytest.skip(f'no Chrome to drive: {e}')
    b = ws.browser = Browser(port=port, headless=True, profile=tmp_path/'chrome')
    try:
        with TestClient(ide_app(ws)) as client:
            assert 'id="tabbar"' in client.get(f'/browser/open?url={site}').text
            target = ws.tabs[ws.active].ref
            with client.websocket_connect('/browser/ws') as sock:
                sock.send_text(json.dumps({'id': target, 'w': 800, 'h': 600, 'scale': 2}))
                ready = _reply(sock, 'ready')
            assert ready['scale'] == 1, ready
            assert SCALE_FLAG in ready['note']
            assert _jpeg_size(_last_frame(client, target)) == (800, 600), 'a 1x Chrome sends 1x'
    finally: asyncio.run(_quit(b))

async def _quit(b):
    cdp = await b.cdp()
    try: await cdp('Browser.close')
    except Exception: pass

def _last_frame(client, target):
    "One frame from a second socket, which `startScreencast` always emits."
    with client.websocket_connect('/browser/ws') as sock:
        sock.send_text(json.dumps({'id': target, 'w': 800, 'h': 600, 'scale': 2}))
        _reply(sock, 'ready')
        for _ in range(40):
            m = sock.receive()
            if m.get('bytes'): return m['bytes']
    raise AssertionError('no frame arrived')

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

@pytest.mark.slow
def test_a_real_chrome_opens_a_slow_leela_and_names_what_refused_a_dead_one(tmp_path, monkeypatch):
    "The live root answers after 1.5s; the open must hand back the committed page, and a closed port Chrome's own error."
    import os, leela.core.projects as P
    class Slow(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            time.sleep(1.5); body = b'<!doctype html><title>Leela</title><h1>root</h1>'
            self.send_response(200); self.send_header('Content-Type', 'text/html'); self.send_header('Content-Length', str(len(body)))
            self.end_headers(); self.wfile.write(body)
        def log_message(self, *a): pass
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Slow)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    own = srv.server_address[1]
    monkeypatch.setattr(P, 'serving', lambda: {'host': '127.0.0.1', 'port': own, 'pid': os.getpid()})
    port = _free_port()
    try: asyncio.run(_start_chrome(port, tmp_path/'chrome'))
    except Exception as e: pytest.skip(f'no Chrome to drive: {e}')
    async def go():
        b = Browser(port=port, headless=True, profile=tmp_path/'chrome')
        try:
            page = await b.open(f'http://127.0.0.1:{own}/')
            await b.settle(page.id)
            st = await b.state(page.id)
            assert (st['url'], st['title']) == (f'http://127.0.0.1:{own}/?observer=1', 'Leela') and await b.allowed(st['url'])
            monkeypatch.setenv('FOSSICK_ALLOW_PRIVATE', '1')
            with pytest.raises(ConnectionError, match='ERR_CONNECTION_REFUSED'): await b.goto(page.id, f'http://127.0.0.1:{_free_port()}/')
        finally: await _quit(b)
    try: asyncio.run(go())
    finally: srv.shutdown()

async def _start_chrome(port, profile, flags=(SCALE_FLAG,)):
    from fossick.cdp import _debug_ready, cdp_setup
    if not _debug_ready(port):
        await cdp_setup(port=port, user_data_dir=profile, headless=True, timeout=60,
                        extra_flags=list(flags))

class FakeCdp:
    "A connected CDP that records the browser-level close, and the pages call `_own` makes."
    def __init__(self, guid='G1'):
        self.wsconn, self.is_open, self.closed_browser = f'ws://x/devtools/browser/{guid}', True, 0
        self.browser = SimpleNamespace(close=self._close)
    async def _close(self): self.closed_browser += 1
    @property
    async def pages(self): return []
    async def close(self): self.is_open = False

def _connected(monkeypatch, port, running, guid='G1', cdp=None):
    "A `Browser` taken through `cdp()` with Chrome either already up or started by us."
    from leela.blocks.browser import browser as B
    b, cdp = B.Browser(port=port), cdp or FakeCdp(guid)
    monkeypatch.setattr(b, 'running', lambda: running)
    monkeypatch.setattr(B, 'cdp_connect', lambda **kw: _ret(cdp), raising=False)
    monkeypatch.setattr('fossick.cdp.cdp_connect', lambda **kw: _ret(cdp))
    asyncio.run(b.cdp())
    return b, cdp

async def _ret(x): return x

@pytest.fixture(autouse=True)
def _no_leaked_ownership():
    "Ownership is process-wide, so a test that claims a port must not hand it to the next one."
    from leela.blocks.browser import browser as B
    B._OURS.clear(); B._LIVE.clear()
    yield
    B._OURS.clear(); B._LIVE.clear()

def test_quitting_closes_the_chrome_leela_started(monkeypatch, tmp_path):
    "The whole point: what Leela launched dies with it, rather than outliving it on the port."
    monkeypatch.setattr('leela.blocks.browser.browser.leela_cfg', Path(tmp_path))
    b, cdp = _connected(monkeypatch, 9901, running=False)
    asyncio.run(b.quit())
    assert cdp.closed_browser == 1 and not cdp.is_open

def test_quitting_leaves_a_chrome_leela_merely_adopted_running(monkeypatch, tmp_path):
    "Somebody else's browser, with their tabs in it. Leela drops the connection and nothing more."
    monkeypatch.setattr('leela.blocks.browser.browser.leela_cfg', Path(tmp_path))
    b, cdp = _connected(monkeypatch, 9902, running=True)
    asyncio.run(b.quit())
    assert cdp.closed_browser == 0 and not cdp.is_open

def test_the_last_window_out_closes_the_shared_chrome_not_the_first(monkeypatch, tmp_path):
    "Windows share one Chrome per port. Closing one must not take the pages of the others with it."
    monkeypatch.setattr('leela.blocks.browser.browser.leela_cfg', Path(tmp_path))
    first, cdp = _connected(monkeypatch, 9903, running=False)
    second, _ = _connected(monkeypatch, 9903, running=True, cdp=cdp)   # the same Chrome
    asyncio.run(first.quit())
    assert cdp.closed_browser == 0, 'the owner quit while another window was still using it'
    asyncio.run(second.quit())
    assert cdp.closed_browser == 1, 'the last one out did not close what the first one started'

def test_a_chrome_left_behind_by_a_crashed_leela_is_owned_again_not_adopted(monkeypatch, tmp_path):
    "Otherwise every crash leaks a headless Chrome that only the user, with lsof, can find."
    monkeypatch.setattr('leela.blocks.browser.browser.leela_cfg', Path(tmp_path))
    b, _ = _connected(monkeypatch, 9904, running=False)
    b._mine.add('T1'); b._remember()
    assert json.loads(b._owned_path().read_text())['launched'] is True
    from leela.blocks.browser import browser as B
    B._OURS.clear(); B._LIVE.clear()          # the crash
    again, cdp = _connected(monkeypatch, 9904, running=True)
    asyncio.run(again.quit())
    assert cdp.closed_browser == 1

def test_the_workspace_teardown_quits_the_browser(ws):
    "The browser hangs off the same `shutdown` as the kernels, or nothing ever calls `quit`."
    quit_calls = []
    async def fake_quit(): quit_calls.append(True)
    ws.browser.quit = fake_quit
    asyncio.run(ws.shutdown())
    assert quit_calls == [True]

@pytest.mark.slow
def test_the_chrome_leela_starts_really_does_die_when_leela_quits(tmp_path, monkeypatch):
    """The fakes prove the decision; only a real Chrome proves the process goes away."""
    pytest.importorskip('fastcdp')
    monkeypatch.setattr('leela.blocks.browser.browser.leela_cfg', Path(tmp_path))
    port = _free_port()
    b = Browser(port=port, headless=True, profile=tmp_path/'chrome')
    async def go():
        try: await b.cdp()
        except BrowserUnavailable as e: pytest.skip(f'no Chrome to drive: {e}')
        assert b.running(), 'Chrome never came up, so there is nothing to prove'
        await b.quit()
    asyncio.run(go())
    for _ in range(100):
        if not b.running(): return
        time.sleep(.1)
    pytest.fail(f'Chrome is still answering on the CDP port {port} ten seconds after quit')

# -- the agent's own tab -----------------------------------------------------------------------

OWN = 'http://127.0.0.1:5999'

@pytest.fixture
def own(monkeypatch):
    "This process serves Leela at `OWN`, as `serving.json` would say."
    import os, leela.core.projects as P
    monkeypatch.setattr(P, 'serving', lambda: {'host': '127.0.0.1', 'port': 5999, 'pid': os.getpid()})

def test_only_leelas_own_origin_is_allowed_among_local_addresses(own, monkeypatch):
    "Scheme, host and port all match, or fossick's loopback refusal stands, and names the one address that would pass."
    b = Browser()
    assert b.check(f'{OWN}/') == f'{OWN}/?observer=1'
    # any other path collapses to the root: FastHTML routes answer GET, so a path could act on load
    for path in ('/w/x?a=1&observer=0', '/fs/add_root?path=/', '/tabs/save-all'): assert b.check(OWN + path) == f'{OWN}/?observer=1', path
    for url in ('http://127.0.0.1:5998/', 'https://127.0.0.1:5999/', 'http://localhost:5999/',
                'http://10.0.0.1:5999/', '127.0.0.1:5999', 'http://169.254.169.254/'):
        with pytest.raises(Exception) as e: b.check(url)
        assert f'Leela itself, {OWN}/' in str(e.value), url
    import os, leela.core.projects as P
    monkeypatch.setattr(P, 'serving', lambda: {'host': '127.0.0.1', 'port': 5999, 'pid': os.getpid() + 1})
    with pytest.raises(Exception): b.check(f'{OWN}/')          # a record another process wrote allows nothing

@pytest.mark.parametrize('url', ['file:///etc/passwd', 'chrome://settings', 'javascript:alert(1)', 'data:text/html,x'])
def test_no_scheme_but_the_web_opens_even_beside_leelas_own_origin(own, url):
    with pytest.raises(Exception): Browser().check(url)

class Chrome:
    "A CDP connection whose targets keep a URL, and the pages over them. `errors` is Chrome's `errorText` by URL."
    is_open, wsconn = True, ''
    def __init__(self): self.urls, self.loops, self.redirects, self.errors, self.shot = {'PERSON': 'https://example.com/'}, [], {}, {}, lambda kw: _jpeg(64, 40)
    @property
    async def pages(self): return [{'targetId': t, 'type': 'page', 'url': u} for t, u in self.urls.items()]
    @property
    def target(self):
        cdp = self
        class T:
            @staticmethod
            async def createTarget(url, background=True):
                # Chrome answers before the load: until it commits, the target is its empty first document.
                cdp.urls[tid := f'AGENT{len(cdp.urls)}'] = 'about:blank' if url == 'about:blank' else ''
                return tid
            @staticmethod
            async def closeTarget(targetId): cdp.urls.pop(targetId, None)
        return T

class Tab:
    "A `fastcdp.Page` over one `Chrome` target, recording the loop each call ran on."
    is_open = True
    def __init__(self, cdp, tid): self.cdp, self.tid, self.calls = cdp, tid, []
    async def eval(self, expr):
        self.cdp.loops.append(asyncio.get_running_loop())
        return 'complete' if 'readyState' in expr else ('Leela' if 'title' in expr else {'n': 1})
    @staticmethod
    async def new(tid, cdp): return Tab(cdp, tid)
    def __getattr__(self, domain):
        tab = self
        class D:
            def __getattr__(_, name):
                async def f(**kw):
                    tab.cdp.loops.append(asyncio.get_running_loop()); tab.calls.append((name, kw))
                    if name == 'captureScreenshot': return base64.b64encode(tab.cdp.shot(kw)).decode()
                    if name == 'getNavigationHistory': return {'currentIndex': 0, 'entries': [{'id': 1, 'url': tab.cdp.urls[tab.tid]}]}
                    if name == 'navigate':
                        if err := tab.cdp.errors.get(kw['url']): return {'errorText': err}
                        tab.cdp.urls[tab.tid] = tab.cdp.redirects.get(kw['url'], kw['url'])
                        return {'loaderId': 'L'}
                    if name == 'getLayoutMetrics': return {'cssVisualViewport': {'pageX': 0, 'pageY': 0, 'clientWidth': 1280, 'clientHeight': 800}}
                return f
        return D()

@pytest.fixture
def agent_tab(ws, monkeypatch, own):
    "A `WorkspaceHost` whose browser runs on a live workspace loop, with the person's page cast on it."
    import fastcdp, fossick.cdp
    from leela.blocks.agent.ai import WorkspaceHost
    chrome = Chrome()
    async def connect(**kw): return chrome
    monkeypatch.setattr(fossick.cdp, 'cdp_connect', connect)
    monkeypatch.setattr(fastcdp, 'Page', Tab, raising=False)
    monkeypatch.setattr(ws.browser, 'running', lambda: True)
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True); t.start()
    ws._loop, cast = loop, object()
    asyncio.run_coroutine_threadsafe(ws.browser.cdp(), loop).result(5)
    ws.browser._casts['PERSON'] = cast
    yield SimpleNamespace(host=WorkspaceHost(ws), chrome=chrome, loop=loop, cast=cast, ws=ws)
    loop.call_soon_threadsafe(loop.stop); t.join(5)

import base64

def _jpeg(w, h):
    "A real JPEG of `w` x `h`, so its header carries the size the scaling reads."
    from io import BytesIO
    from PIL import Image
    buf = BytesIO(); Image.new('RGB', (w, h), 'white').save(buf, 'JPEG', quality=80)
    return buf.getvalue()

def test_every_browser_call_runs_on_the_workspace_loop_and_the_persons_cast_survives(agent_tab):
    "`Browser.cdp` drops every page and cast when asked from another loop, which is the person's inline page going dark."
    h, b = agent_tab.host, agent_tab.ws.browser
    said = h.browse(f'{OWN}/')
    assert said.startswith('AGENT1') and 'observer=1' in said, said
    h.screenshot(); h.page_text(); h.page_reload()
    assert set(agent_tab.chrome.loops) == {agent_tab.loop}
    assert b._casts.get('PERSON') is agent_tab.cast and b._loop is agent_tab.loop

def test_a_screenshot_lands_inside_the_project_and_git_ignores_it(agent_tab):
    import subprocess
    h, root = agent_tab.host, Path(agent_tab.ws.cwd_for()).resolve()
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    h.browse(f'{OWN}/')
    p = Path(h.screenshot())
    assert p.resolve().is_relative_to(root) and p.read_bytes().startswith(b'\xff\xd8\xff') and p.suffix == '.jpg'
    assert h.check(str(p), must_exist=True)                      # where `delegate_search(images=)` can read it
    assert subprocess.run(['git', '-C', str(root), 'check-ignore', '-q', str(p)]).returncode == 0
    assert '.leela-attachments' not in subprocess.run(['git', '-C', str(root), 'status', '--porcelain', '-uall'], capture_output=True, text=True).stdout

def test_a_screenshot_goes_to_the_project_when_the_kernel_cwd_is_outside_the_open_folders(agent_tab, tmp_path_factory, monkeypatch):
    "`delegate_search(images=)` refuses a path outside the open folders, so the shot must not land there."
    h, elsewhere = agent_tab.host, tmp_path_factory.mktemp('elsewhere')
    monkeypatch.setattr(agent_tab.ws, 'cwd_for', lambda *a, **kw: elsewhere)
    h.browse(f'{OWN}/')
    p = Path(h.screenshot())
    assert p.parent == Path(h.project).resolve()/'.leela-attachments' and not list(elsewhere.iterdir())

def test_a_screenshot_is_a_jpeg_retaken_smaller_when_too_big_and_says_so(agent_tab):
    "A vision API refuses a picture over its byte or side limit, so an oversized shot is retaken at a scale its name states."
    h, sent = agent_tab.host, []
    def shot(kw):
        sent.append(kw)
        return _jpeg(8000, 100) if 'clip' not in kw else _jpeg(7000, 87)
    agent_tab.chrome.shot = shot
    h.browse(f'{OWN}/')
    p = Path(h.screenshot())
    assert [k['format'] for k in sent] == ['jpeg', 'jpeg'] and sent[0]['quality'] == 80
    assert 0 < sent[1]['clip']['scale'] < 7500 / 8000 + .001 and sent[1]['clip']['width'] == 1280
    assert '-scaled-' in p.name and p.name.endswith('pct.jpg')
    sent.clear(); agent_tab.chrome.shot = lambda kw: sent.append(kw) or _jpeg(64, 40)
    assert '-scaled-' not in Path(h.screenshot()).name and len(sent) == 1   # a small shot is taken once

def test_a_screenshot_is_no_write_the_gate_snapshots_or_rewinds():
    from leela.agent.tools import path_write
    from leela.blocks.agent.ai import WRITE_TOOLS
    assert not path_write('screenshot', {'page': ''}) and 'screenshot' not in WRITE_TOOLS
    assert {'page_click', 'page_type', 'page_eval'} <= WRITE_TOOLS

def test_clicking_typing_and_script_are_refused_on_leelas_own_page(agent_tab):
    "The agent could otherwise press its own Approve button, or `fetch()` the API that answers it."
    h = agent_tab.host
    h.browse(f'{OWN}/')
    for call in (lambda: h.page_click('', 10, 10), lambda: h.page_type('', 'x'), lambda: h.page_eval('', 'fetch("/agent/approve")')):
        with pytest.raises(PermissionError, match="Leela's own page"): call()
    tab = agent_tab.ws.browser._pages['AGENT1']
    assert not [c for c in tab.calls if c[0] in ('dispatchMouseEvent', 'insertText')]

def test_off_leela_the_agent_clicks_types_and_evaluates(agent_tab, monkeypatch):
    import fossick.core
    monkeypatch.setattr(fossick.core, 'check_url', lambda u: u)   # no DNS in a unit test
    h = agent_tab.host
    h.browse('https://example.org/')
    assert h.page_click('', 3, 4) == 'clicked 3,4' and h.page_type('', 'hi') == 'typed 2 characters'
    assert h.page_eval('', '({n: 1})') == '{"n": 1}'
    calls = [c[0] for c in agent_tab.ws.browser._pages['AGENT1'].calls]
    assert calls.count('dispatchMouseEvent') == 2 and 'insertText' in calls

def _no_loopback(u):
    if '127.0.0.1' in u: raise ValueError(f'{u} is a private or reserved address')
    return u

def test_a_redirect_to_a_local_address_is_refused_and_the_tab_left_blank(agent_tab, monkeypatch):
    "`check` sees only the first URL; Chrome's own debugging port is one redirect away."
    import fossick.core
    monkeypatch.setattr(fossick.core, 'check_url', _no_loopback)
    agent_tab.chrome.redirects['https://example.org/r'] = 'http://127.0.0.1:9223/json'
    with pytest.raises(PermissionError, match='where browse would not go'): agent_tab.host.browse('https://example.org/r')
    assert agent_tab.chrome.urls['AGENT1'] == 'about:blank'

def test_a_page_script_sent_somewhere_local_is_no_longer_read(agent_tab, monkeypatch):
    import fossick.core
    monkeypatch.setattr(fossick.core, 'check_url', _no_loopback)
    h = agent_tab.host
    h.browse('https://example.org/')
    agent_tab.chrome.urls['AGENT1'] = 'http://127.0.0.1:8000/admin'   # what `location = ...` in page_eval would do
    for call in (h.page_text, h.screenshot, h.page_reload):
        with pytest.raises(PermissionError, match='where browse would not go'): call()

def test_acting_fails_closed_when_leela_cannot_say_its_own_origin(agent_tab, monkeypatch):
    "Another Leela overwrote `serving.json`: the page is still Leela, and loopback is still refused."
    import os, fossick.core, leela.core.projects as P
    h = agent_tab.host
    h.browse(f'{OWN}/')
    monkeypatch.setattr(P, 'serving', lambda: {'host': '127.0.0.1', 'port': 6001, 'pid': os.getpid() + 1})
    monkeypatch.setattr(fossick.core, 'check_url', _no_loopback)
    with pytest.raises(PermissionError): h.page_click('', 1, 1)
    with pytest.raises(PermissionError): h.page_eval('', '1')

def test_browse_waits_for_a_slow_leela_to_commit_rather_than_reading_the_blank_first_document(agent_tab):
    "The live root takes over a second; `createTarget(url)` answers at once, and its empty first document reads as complete."
    h = agent_tab.host
    said = h.browse(f'{OWN}/')
    assert said.endswith(f'{OWN}/?observer=1'), said
    assert agent_tab.chrome.urls['AGENT1'] == f'{OWN}/?observer=1'
    assert h.screenshot().endswith('.jpg')

@pytest.mark.parametrize('again', [False, True])
def test_a_page_chrome_will_not_load_says_what_chrome_said_and_leaves_no_tab(agent_tab, monkeypatch, again):
    import fossick.core
    monkeypatch.setattr(fossick.core, 'check_url', lambda u: u)
    h, chrome = agent_tab.host, agent_tab.chrome
    if again: h.browse('https://example.org/')
    chrome.errors['https://down.example/'] = 'net::ERR_CONNECTION_REFUSED'
    with pytest.raises(ConnectionError, match='Chrome could not load https://down.example/: net::ERR_CONNECTION_REFUSED'): h.browse('https://down.example/')
    assert set(chrome.urls) == ({'PERSON', 'AGENT1'} if again else {'PERSON'})
    assert h._pages == (['AGENT1'] if again else [])

def test_a_navigation_another_replaced_is_no_error(agent_tab, monkeypatch):
    import fossick.core
    monkeypatch.setattr(fossick.core, 'check_url', lambda u: u)
    agent_tab.chrome.errors['https://example.org/'] = 'net::ERR_ABORTED'
    with pytest.raises(ConnectionError, match='left the tab blank'): agent_tab.host.browse('https://example.org/')

def test_the_agent_cannot_address_a_page_it_did_not_open(agent_tab):
    h = agent_tab.host
    with pytest.raises(ValueError, match='browse'): h.screenshot()
    h.browse(f'{OWN}/')
    with pytest.raises(ValueError, match='not a page the agent opened'): h.screenshot('PERSON')

def test_the_host_declares_the_browser_group_and_its_tools():
    from shalya.tools import group_of
    from leela.agent.tools import tools_for
    from leela.blocks.agent.ai import WorkspaceHost
    from leela.workspace import Workspace
    h = WorkspaceHost(Workspace(roots=[]))
    assert 'browser' in h.provides
    assert not {n for n in (t.__name__ for t in tools_for(h)) if group_of(n) == 'browser'}, 'an opt-in: nothing unasked'
    assert {n for n in (t.__name__ for t in tools_for(h, optin=('browser',))) if group_of(n) == 'browser'} == \
        {'browse', 'screenshot', 'page_text', 'page_reload', 'page_click', 'page_type', 'page_eval'}
    with pytest.raises(RuntimeError, match='workspace loop'): h._on_loop(asyncio.sleep(0))

def test_an_observer_boot_resumes_nothing_saves_nothing_and_draws_no_approvals():
    "The agent's screenshot of Leela must not switch the person's conversation, save their tabs or show its own Approve."
    import re
    pkg = Path(__file__).resolve().parents[2]/'leela'
    src = lambda p: (pkg/p).read_text()
    assert re.search(r"observer: new URLSearchParams\(location\.search\)\.get\('observer'\) === '1'", src('static/js/core.js'))
    def body(text, name):
        m = re.search(rf'^(?:async\s+)?function {name}\([^)]*\)\s*\{{\n(.*?)\n\}}', text, re.M | re.S)
        assert m, name
        return m.group(1)
    for path, name in (('blocks/agent/live.js', 'rehydrateAgentLive'), ('blocks/agent/live.js', 'resumeLatestAgent'),
                       ('blocks/agent/steer.js', 'approvalLoop'), ('blocks/agent/approvals.js', 'showApproval')):
        assert 'lee.observer' in body(src(path), name).splitlines()[0], name
    for path, name in (('blocks/editor/split.js', 'checkProjectRuntime'), ('static/js/core.js', 'restoreDrafts'),
                       ('static/js/core.js', 'prefSet')):
        assert 'lee.observer' in body(src(path), name).splitlines()[0], name
    save = [l for l in body(src('blocks/editor/tabs.js'), 'mountTab').splitlines() if '/tabs/save-all' in l]
    assert save and all('!lee.observer' in l for l in save)
    for p in ('lee-core.js', 'lee-agent.js', 'lee-ide.js'): assert 'lee.observer' in (pkg/'static'/p).read_text(), p


def test_the_browser_is_one_toggle_in_the_agent_head(tmp_path):
    """The browser group is an opt-in, so it needs the same control `research` and `exhash` have, and a new conversation started with it gets the tools."""
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.workspace import Workspace
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as c:
        assert 'id="agentoptin-browser"' in c.get('/').text
        tid = c.post('/agent/thread/new', json={'optin': ['browser']}).json()['active']
        assert 'screenshot' in {t.__name__ for t in ws.threads.require(tid).ai.tools}

def test_a_screenshot_reaches_the_turn_model_and_draws_inline(agent_tab):
    "The agent's own recorded `screenshot` returns its picture: the urai loop sends it to the model, and `turn_media` draws it."
    from urai import Chat, ChatOpts, Resp, ToolCall, ToolLoopMixin, is_media
    from leela.blocks.agent.turns import turn_media
    class Script(ToolLoopMixin, Chat):
        "A fake turn model whose replies are scripted."
        _runtime = 'leela-script'
        def __init__(self, model=None, *, script=(), tools=()):
            self.script = list(script)
            self._setup(None, ChatOpts.create(None, tools=tools)); self._set_tools(self.tools)
        def _model_step(self, **kw): return Resp({'role': 'assistant', **self.script.pop(0)})
    ai = agent_tab.ws.ai
    ai.optin, ai._tools = ('browser',), None
    tools = {t.__name__: t for t in ai.tools}
    agent_tab.host.browse(f'{OWN}/')
    c = Script(script=[{'content': '', 'tool_calls': [dict(ToolCall('screenshot', {}))]}, {'content': 'I can see Leela'}], tools=[tools['screenshot']])
    c('look at the page')
    assert [m['role'] for m in c.hist] == ['user', 'assistant', 'tool', 'user', 'assistant']
    assert '.jpg' in c.hist[2]['content'] and [p['type'] for p in c.hist[3]['content']] == ['text', 'image_url']
    assert c.hist[3]['content'][1]['image_url']['url'].startswith('data:image/jpeg;base64,')
    shown = turn_media(ai)
    assert len(shown) == 1 and shown[0]['url'].startswith('data:image/jpeg;base64,')
