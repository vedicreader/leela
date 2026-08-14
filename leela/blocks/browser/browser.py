"""Web pages as tabs inside Leela, drawn by the CDP Chrome fossick already keeps.

Leela has had a persistent debug Chrome for a while: `--app` opens each workspace in one, and
`fossick` reuses its profile so a logged-in session survives between runs. This module treats
that same browser as a *renderer*. A page is opened as a CDP target, its frames are streamed
into a Leela tab over a websocket, and mouse and keyboard events go back the other way -- so
reading a page found in research is a tab beside the notebook rather than an application
switch, and the cookies it uses are the ones fossick already has.

Nothing here parses or executes web content in Leela's process. Chrome renders, Leela draws
JPEG frames on a canvas, and the only structured thing that crosses back is the Markdown that
`fossick.to_md` already produces for research.

Every navigation goes through `fossick.core.check_url`, which is not decoration: the browser
runs on the same loopback interface as Leela's own unauthenticated server, so `127.0.0.1` and
friends are refused unless `FOSSICK_ALLOW_PRIVATE` says otherwise.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from ... import Dictable, errstr

__all__ = ['WebPage', 'Browser', 'BrowserUnavailable', 'DEFAULT_SIZE', 'MAX_SIZE']

# The frame size Chrome is asked for when a panel has not measured itself yet, and the ceiling
# on what it will honour. The cap is about bandwidth, not politeness: a screencast is re-encoded
# JPEG per frame, and a maximised 5K panel asking for native pixels saturates the socket.
DEFAULT_SIZE = (1280, 800)
MAX_SIZE = (2560, 1600)


class BrowserUnavailable(RuntimeError):
    "No CDP Chrome to render into, and Leela could not start one."


@dataclass
class WebPage(Dictable):
    "One page in the CDP Chrome, as the tab strip and the panel need it."
    id: str = ''
    url: str = ''
    title: str = ''
    attached: bool = False


class Browser:
    """The persistent CDP Chrome, as a small set of pages Leela can draw and drive.

    One connection per workspace, opened on first use and re-opened if Chrome goes away.
    Pages are addressed by CDP target id, which is also what `fossick.cdp.cdp_app` reports,
    so a window fossick opened and a tab Leela opened are the same kind of thing.
    """

    def __init__(self, port=9223, headless=True, profile=None):
        self.port, self.headless = int(port), headless
        # Which Chrome profile to render in. `None` means fossick's own, which is the point of
        # the feature -- its logins are the reason a page reads here and not through a fetch.
        # `$LEELA_CDP_PROFILE` overrides it, and the tests use a throwaway one, because a
        # second port cannot be opened against a profile Chrome is already holding.
        self.profile = profile or os.environ.get('LEELA_CDP_PROFILE') or None
        self.note = ''
        self._cdp = None
        self._loop = None
        self._pages: dict[str, object] = {}
        self._casts: dict[str, object] = {}   # target -> the token of its current screencast
        self._lock = asyncio.Lock()

    # -- connection ---------------------------------------------------------
    async def cdp(self):
        "The live CDP connection, starting Chrome if nothing is listening yet."
        async with self._lock:
            loop = asyncio.get_running_loop()
            # A websocket belongs to the loop that created it. Reusing one across loops does
            # not raise -- it reports itself open and then never completes a read, which is a
            # hang rather than an error. A `Workspace` outlives any one loop, so this is
            # checked rather than assumed.
            if self._cdp is not None and self._cdp.is_open and self._loop is loop:
                return self._cdp
            # A dropped connection invalidates every session id we were holding.
            self._cdp, self._pages, self._loop = None, {}, loop
            try:
                from fossick.cdp import cdp_connect
            except ImportError as e:
                raise BrowserUnavailable(f'the inline browser needs fossick ({errstr(e)})') from e
            try:
                self._cdp = await cdp_connect(port=self.port, headless=self.headless,
                                              user_data_dir=self.profile)
            except Exception as e:
                raise BrowserUnavailable(
                    f'no Chrome on the CDP port {self.port}: {errstr(e)}') from e
            return self._cdp

    def running(self):
        """Whether a debug Chrome is already answering on the port -- without starting one.

        The distinction matters to callers that are only asking a question. Listing pages must
        not boot a browser as a side effect; opening a page may, because that is the request.
        """
        try:
            from fossick.cdp import _debug_ready
            return bool(_debug_ready(self.port))
        except Exception: return False

    async def alive(self):
        "Whether a page could be opened right now. Starts Chrome if it has to."
        try:
            await self.cdp()
            return True
        except BrowserUnavailable as e:
            self.note = errstr(e)
            return False

    async def close(self):
        "Drop Leela's connection. Chrome and its profile outlive it, on purpose."
        cdp, self._cdp, self._pages, self._loop = self._cdp, None, {}, None
        if cdp is not None:
            try: await cdp.close()
            except Exception: pass

    # -- pages --------------------------------------------------------------
    async def page(self, tid):
        "The `Page` for target `tid`, attaching to one Leela did not open itself."
        if (p := self._pages.get(tid)) is not None and p.is_open: return p
        cdp = await self.cdp()
        from fastcdp import Page
        sid = await cdp.attach(tid)
        p = Page(cdp, tid, sid)
        await cdp.page.enable(sid=sid)
        self._pages[tid] = p
        return p

    async def pages(self):
        "Every page target in the CDP Chrome, Leela's own tabs included."
        if not self.running():
            raise BrowserUnavailable(f'no browser running on the CDP port {self.port}')
        cdp = await self.cdp()
        out = []
        for t in await cdp.pages:
            tid = t.get('targetId') or t.get('id') or ''
            out.append(WebPage(id=tid, url=t.get('url', ''), title=t.get('title', ''),
                               attached=tid in self._pages))
        return out

    async def open(self, url, background=True):
        "Open `url` as a new target and return it. `background` keeps focus in Leela."
        url = self.check(url)
        cdp = await self.cdp()
        tid = await cdp.target.createTarget(url=url, background=background)
        # `createTarget` answers as soon as the target exists; a caller that immediately asks
        # for the title would otherwise get 'about:blank'.
        await asyncio.sleep(.05)
        p = await self.page(tid)
        return WebPage(id=tid, url=url, title=await self.title(p) or url, attached=True)

    async def shut(self, tid):
        "Close one page in Chrome and forget its session."
        p = self._pages.pop(tid, None)
        cdp = await self.cdp()
        try: await cdp.target.closeTarget(targetId=tid)
        except Exception: pass
        return p is not None

    # -- driving one page ---------------------------------------------------
    def check(self, url):
        "Normalise and refuse a URL the browser must not be pointed at."
        url = (url or '').strip()
        if not url: raise ValueError('no URL')
        if '://' not in url: url = f'https://{url}'
        from fossick.core import check_url
        return check_url(url)

    async def goto(self, tid, url):
        "Navigate an open page. Returns once Chrome has accepted the navigation, not the load."
        p = await self.page(tid)
        url = self.check(url)
        await p.page.navigate(url=url)
        return url

    async def history(self, tid, delta):
        "Step `delta` entries through a page's own history; a no-op at either end."
        p = await self.page(tid)
        h = await p.page.getNavigationHistory()
        i, entries = h['currentIndex'] + delta, h['entries']
        if not 0 <= i < len(entries): return False
        await p.page.navigateToHistoryEntry(entryId=entries[i]['id'])
        return True

    async def reload(self, tid):
        p = await self.page(tid)
        await p.page.reload()

    async def state(self, tid):
        "Where a page is and where it can go: the address bar and the two arrows."
        p = await self.page(tid)
        try: h = await p.page.getNavigationHistory()
        except Exception: h = {'currentIndex': 0, 'entries': []}
        i, entries = h.get('currentIndex', 0), h.get('entries', [])
        cur = entries[i] if 0 <= i < len(entries) else {}
        return {'id': tid, 'url': cur.get('url', ''), 'title': await self.title(p),
                'back': i > 0, 'forward': i < len(entries) - 1}

    async def title(self, p):
        try: return await p.eval('document.title') or ''
        except Exception: return ''

    async def markdown(self, tid, sel=None):
        """The live page as Markdown, through the same `fossick.to_md` research uses.

        With a fallback research does not need. `to_md` runs readability first, which is right
        for an article and returns nothing at all for an application -- and an application
        behind a login is most of the reason to read a page in here rather than fetch it. When
        readability declines, the rendered text is a worse answer than Markdown but a much
        better one than the empty string.
        """
        p = await self.page(tid)
        from fossick.core import to_md
        html = await p.eval('document.documentElement.outerHTML') or ''
        md = to_md(html, sel=sel) if sel else to_md(html)
        if md.strip(): return md
        text = await p.eval('document.body ? document.body.innerText : ""') or ''
        return text.strip()

    # -- the picture --------------------------------------------------------
    async def resize(self, tid, width, height, scale=1):
        """Pin the page's viewport to the panel showing it.

        With the metrics overridden, a click at panel (x, y) is a click at page (x, y): the
        alternative is mapping every event through the frame metadata, which drifts the moment
        the page scrolls.
        """
        w = max(240, min(int(width or 0) or DEFAULT_SIZE[0], MAX_SIZE[0]))
        h = max(180, min(int(height or 0) or DEFAULT_SIZE[1], MAX_SIZE[1]))
        p = await self.page(tid)
        await p.emulation.setDeviceMetricsOverride(
            width=w, height=h, deviceScaleFactor=float(scale or 1), mobile=False)
        return w, h

    async def start_cast(self, tid, width, height, quality=62, scale=1, owner=None):
        """Begin streaming frames for `tid`. Returns `(width, height, owner)`.

        Chrome only composites a page it believes is visible, and a target opened in the
        background is not: without these two calls `startScreencast` succeeds and then never
        emits a frame. `bringToFront` makes it visible; focus emulation keeps it *rendering*
        once the next inline tab takes the front, which is what lets two Leela tabs hold live
        pages at the same time.

        `owner` says who the stream belongs to -- the socket, for its whole life, across the
        stops and starts of pausing for a hidden window. Handing it back to `stop_cast` is what
        stops a slow teardown from switching off a stream that a reopened tab has just started.
        """
        w, h = await self.resize(tid, width, height, scale)
        p = await self.page(tid)
        try:
            await p.emulation.setFocusEmulationEnabled(enabled=True)
            await p.page.bringToFront()
        except Exception: pass
        await p.page.startScreencast(format='jpeg', quality=int(quality),
                                     maxWidth=w, maxHeight=h, everyNthFrame=1)
        owner = self._casts[tid] = owner if owner is not None else object()
        return w, h, owner

    async def stop_cast(self, tid, owner=None):
        "Stop streaming and hand the page's viewport back to Chrome. `owner=None` stops any."
        if owner is not None and self._casts.get(tid) is not owner: return False
        self._casts.pop(tid, None)
        try:
            p = await self.page(tid)
            await p.page.stopScreencast()
            await p.emulation.clearDeviceMetricsOverride()
        except Exception: return False
        return True

    async def ack(self, tid, ack_id):
        "Tell Chrome the frame arrived. Without this the stream stops after one frame."
        p = await self.page(tid)
        await p.page.screencastFrameAck(sessionId=int(ack_id))

    # -- input --------------------------------------------------------------
    async def mouse(self, tid, kind, x, y, button='left', clicks=1, modifiers=0,
                    dx=0, dy=0):
        p = await self.page(tid)
        kw = dict(type=kind, x=float(x), y=float(y), modifiers=int(modifiers))
        if kind == 'mouseWheel': kw |= dict(deltaX=float(dx), deltaY=float(dy))
        else: kw |= dict(button=button, clickCount=int(clicks))
        await p.input.dispatchMouseEvent(**kw)

    async def key(self, tid, kind, **kw):
        p = await self.page(tid)
        await p.input.dispatchKeyEvent(type=kind, **kw)

    async def insert(self, tid, text):
        "Type a string as text, which is what a paste or an IME commit is."
        p = await self.page(tid)
        await p.input.insertText(text=text)
