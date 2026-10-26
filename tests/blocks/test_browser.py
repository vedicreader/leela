"The inline browser: what it refuses to open, how a page becomes a tab, and a real page."

from __future__ import annotations

import asyncio, functools, http.server, json, threading, time
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from leela.app import ide_app
from leela.blocks.browser.browser import Browser, BrowserUnavailable, SCALE_FLAG


@pytest.mark.parametrize('url', ['http://127.0.0.1:5001/', 'http://localhost:5001/',
                                 'http://169.254.169.254/latest/meta-data/'])
def test_the_browser_will_not_be_pointed_at_the_machine_it_is_running_on(url):
    "`fossick.check_url` is the same guard research fetches through, and just as necessary."
    with pytest.raises(Exception): Browser().check(url)


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
        assert client.get(f'/browser/open?url={site}').status_code == 200
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
            assert client.get(f'/browser/open?url={site}').status_code == 200
            target = ws.tabs[ws.active].ref
            with client.websocket_connect('/browser/ws') as sock:
                sock.send_text(json.dumps({'id': target, 'w': 800, 'h': 600, 'scale': 2}))
                ready = _reply(sock, 'ready')
            assert ready['scale'] == 1, ready
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
    from fossick.cdp import cdp_setup, debug_ready
    if not debug_ready(port):
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


def test_a_headless_start_never_takes_the_visible_cdp_chromes_port_or_profile(monkeypatch, tmp_path):
    "Nothing on 9223: the headless Chrome starts on its own port and profile, not the visible CDP Chrome's. A Chrome already up on 9223 is adopted there."
    from leela.blocks.browser import browser as B
    monkeypatch.setattr('leela.blocks.browser.browser.leela_cfg', Path(tmp_path))
    monkeypatch.delenv('LEELA_CDP_PROFILE', raising=False)
    asked = []
    async def connect(**kw): asked.append(kw); return FakeCdp()
    monkeypatch.setattr('fossick.cdp.cdp_connect', connect)
    for up in (False, True):
        b = B.Browser(port=9223); b.port, b.profile = 9223, None   # past conftest's private port, to test the real rule
        monkeypatch.setattr(b, 'running', lambda up=up: up)
        asyncio.run(b.cdp())
    started, adopted = asked
    assert (started['port'], str(started['user_data_dir'])) == (B.HEADLESS_PORT, str(B.HEADLESS_PROFILE)), started
    assert (adopted['port'], adopted['user_data_dir']) == (9223, None), adopted

def test_the_last_window_out_closes_the_shared_chrome_not_the_first(monkeypatch, tmp_path):
    "Windows share one Chrome per port. Closing one must not take the pages of the others with it."
    monkeypatch.setattr('leela.blocks.browser.browser.leela_cfg', Path(tmp_path))
    first, cdp = _connected(monkeypatch, 9903, running=False)
    second, _ = _connected(monkeypatch, 9903, running=True, cdp=cdp)   # the same Chrome
    asyncio.run(first.quit())
    assert cdp.closed_browser == 0, 'the owner quit while another window was still using it'
    asyncio.run(second.quit())
    assert cdp.closed_browser == 1, 'the last one out did not close what the first one started'


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
        with pytest.raises(Exception): b.check(url)
    import os, leela.core.projects as P
    monkeypatch.setattr(P, 'serving', lambda: {'host': '127.0.0.1', 'port': 5999, 'pid': os.getpid() + 1})
    with pytest.raises(Exception): b.check(f'{OWN}/')          # a record another process wrote allows nothing


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


def test_clicking_typing_and_script_are_refused_on_leelas_own_page(agent_tab):
    "The agent could otherwise press its own Approve button, or `fetch()` the API that answers it."
    h = agent_tab.host
    h.browse(f'{OWN}/')
    for call in (lambda: h.page_click('', 10, 10), lambda: h.page_type('', 'x'), lambda: h.page_eval('', 'fetch("/agent/approve")')):
        with pytest.raises(PermissionError): call()
    tab = agent_tab.ws.browser._pages['AGENT1']
    assert not [c for c in tab.calls if c[0] in ('dispatchMouseEvent', 'insertText')]


def _no_loopback(u):
    if '127.0.0.1' in u: raise ValueError(f'{u} is a private or reserved address')
    return u

def test_a_redirect_to_a_local_address_is_refused_and_the_tab_left_blank(agent_tab, monkeypatch):
    "`check` sees only the first URL; Chrome's own debugging port is one redirect away."
    import fossick.core
    monkeypatch.setattr(fossick.core, 'check_url', _no_loopback)
    agent_tab.chrome.redirects['https://example.org/r'] = 'http://127.0.0.1:9223/json'
    with pytest.raises(PermissionError): agent_tab.host.browse('https://example.org/r')
    assert agent_tab.chrome.urls['AGENT1'] == 'about:blank'


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
