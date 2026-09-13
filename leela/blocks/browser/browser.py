"Web pages as tabs, drawn by the CDP Chrome fossick keeps. See `docs/desktop.md`."

from __future__ import annotations
import asyncio, json, os, shutil
from dataclasses import dataclass
from fastcore.all import L, Path, atomic_save, ifnone, store_attr

from ... import Dictable, errstr, leela_cfg

__all__ = ['WebPage', 'Browser', 'BrowserUnavailable', 'DEFAULT_SIZE', 'MAX_SIZE', 'MAX_SCALE',
           'SCALE_FLAG']

#: Viewport sizes are CSS pixels, because that is the unit a click arrives in.
DEFAULT_SIZE = (1280, 800)
MAX_SIZE = (2560, 1600)
#: A frame costs `scale**2` pixels to encode, and no desktop display needs more than this.
MAX_SCALE = 2
#: How many image pixels a screencast frame carries per CSS pixel. A per-page `deviceScaleFactor`
#: does not change it, and the browser's own factor is fixed at launch.
SCALE_FLAG = f'--force-device-scale-factor={MAX_SCALE}'

#: Ports whose Chrome this process started, and the connected `Browser`s on each. One Chrome serves
#: every window on a port, so closing it belongs to the last window out rather than the first.
_OURS, _LIVE = set(), {}

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
    "The persistent CDP Chrome as pages Leela can draw and drive, addressed by CDP target id."

    def __init__(self, port=9223, headless=True, profile=None):
        port, profile = int(port), profile or os.environ.get('LEELA_CDP_PROFILE') or None
        store_attr()
        self.note = ''
        self.scale, self.warning, self.guid = None, '', ''
        self._cdp = self._loop = None
        self._pages, self._casts = {}, {}   # target -> its `Page`; target -> its cast's owner
        self._mine = set()                  # targets Leela opened, as against ones it adopted
        self._lock, self._attaching = asyncio.Lock(), asyncio.Lock()

    async def cdp(self):
        "The live CDP connection, starting Chrome if nothing is listening yet."
        async with self._lock:
            loop = asyncio.get_running_loop()
            if self._cdp is not None and self._cdp.is_open and self._loop is loop: return self._cdp
            self._cdp, self._pages, self._casts, self._loop = None, {}, {}, loop
            self.scale, self.warning = None, ''
            try: from fossick.cdp import cdp_connect
            except ImportError as e:
                raise BrowserUnavailable(f'the inline browser needs fossick ({errstr(e)})') from e
            # Asked before connecting: afterwards a Chrome Leela started looks like one it adopted.
            started = not self.running()
            try: self._cdp = await cdp_connect(port=self.port, headless=self.headless,
                                               user_data_dir=self.profile,
                                               extra_flags=[SCALE_FLAG])
            except Exception as e:
                raise BrowserUnavailable(f'no Chrome on the CDP port {self.port}: {errstr(e)}') from e
            if started: _OURS.add(self.port)
            _LIVE.setdefault(self.port, set()).add(self)
            await self._own()
            return self._cdp

    def _guid_of(self, cdp):
        "The browser's own DevTools id. Chrome mints a new one at every launch."
        u = getattr(cdp, 'wsconn', '') or ''
        return u.rsplit('/devtools/browser/', 1)[1] if '/devtools/browser/' in u else ''

    def _owned_path(self): return leela_cfg/'browser'/f'pages-{self.port}.json'

    def _stored(self):
        "The `(browser, targets, launched)` on disk for this port. Unreadable reads as nothing owned."
        try: d = self._owned_path().read_json()
        except Exception: return '', set(), False
        if not isinstance(d, dict): return '', set(), False
        return (d.get('browser') or '', {t for t in (d.get('targets') or []) if isinstance(t, str)},
                bool(d.get('launched')))

    def _remember(self, drop=()):
        "Write the owned set back, keeping what another Leela on this port owns."
        if not self.guid: return
        guid, stored, _ = self._stored()
        keep = sorted(((stored if guid == self.guid else set()) | self._mine) - set(drop))
        try:
            with atomic_save(self._owned_path(), mode='w', encoding='utf-8') as f:
                f.write(json.dumps({'browser': self.guid, 'targets': keep,
                                    'launched': self.port in _OURS}))
        except Exception: pass

    async def _own(self):
        "Take back what a previous Leela opened, once this is the same Chrome and still open."
        guid = self._guid_of(self._cdp)
        if guid != self.guid: self._mine, self.guid = set(), guid
        if not guid: return
        stored_guid, stored, launched = self._stored()
        if stored_guid != guid: return
        # The same Chrome a Leela that died had started: still this Leela's to close, not adopted.
        if launched: _OURS.add(self.port)
        if not stored: return
        try: live = {t.get('targetId') or t.get('id') for t in await self._cdp.pages}
        except Exception: return
        self._mine |= stored & live

    async def _measure(self, p):
        "Read how many image pixels a frame carries per CSS pixel, and note a Chrome that is short."
        try: m = await asyncio.wait_for(p.page.getLayoutMetrics(), 5)
        except Exception: return
        raster = (m.get('layoutViewport') or {}).get('clientWidth')
        css = (m.get('cssLayoutViewport') or {}).get('clientWidth')
        if not raster or not css: return
        self.scale = round(raster/css, 2)
        if self.scale >= MAX_SCALE: return
        self.warning = (f'the Chrome on port {self.port} draws pages at {self.scale:g}x, because it '
                        f'was started without {SCALE_FLAG}. Chrome takes that flag at launch only. '
                        f'Quit that Chrome and open the page again for {MAX_SCALE}x text.')

    def running(self):
        "Whether a debug Chrome is already answering on the port, asked without starting one."
        try:
            from fossick.cdp import _debug_ready   # the one seam still behind an underscore
            return bool(_debug_ready(self.port))
        except Exception: return False

    def available(self):
        "Whether a page *could* be opened: a Chrome exists, running or not. It starts on demand."
        if self.running(): return True
        try:
            from fossick.cdp import chrome_bin
            binary = chrome_bin()
        except Exception: return False
        return bool(binary and (shutil.which(binary) or Path(binary).exists()))

    async def alive(self):
        "Whether a page could be opened right now. Starts Chrome if it has to."
        try: await self.cdp()
        except BrowserUnavailable as e:
            self.note = errstr(e)
            return False
        return True

    async def close(self):
        "Drop Leela's connection. Chrome and its profile outlive it, on purpose."
        _LIVE.get(self.port, set()).discard(self)
        cdp, self._cdp, self._pages, self._casts, self._loop = self._cdp, None, {}, {}, None
        if cdp is None: return
        try: await cdp.close()
        except Exception: pass

    async def quit(self):
        "Close the Chrome Leela started, and drop the connection either way."
        cdp = self._cdp
        _LIVE.get(self.port, set()).discard(self)
        if cdp is not None and self.port in _OURS and not _LIVE.get(self.port):
            _OURS.discard(self.port)
            # Bounded: a Chrome that will not answer must not hold up the rest of the teardown.
            # It answers before it exits, and a socket that drops under the call means the same.
            try: await asyncio.wait_for(cdp.browser.close(), 5)
            except Exception: pass
            try: self._owned_path().unlink()
            except OSError: pass
        await self.close()

    async def page(self, tid):
        "The `Page` for target `tid`, attaching to one Leela did not open itself."
        if (p := self._pages.get(tid)) is not None and p.is_open: return p
        cdp = await self.cdp()
        # Attaching twice is two sessions, of which the cache keeps one; the other hears nothing.
        async with self._attaching:
            if (p := self._pages.get(tid)) is not None and p.is_open: return p
            from fastcdp import Page
            self._pages[tid] = p = await Page.new(tid, cdp)
        # Measured outside the lock: a page held by a dialog must not block every other attach.
        if self.scale is None: await self._measure(p)
        return p

    def _as_page(self, t):
        "One CDP target row as a `WebPage`."
        tid = t.get('targetId') or t.get('id') or ''
        return WebPage(id=tid, url=t.get('url', ''), title=t.get('title', ''), attached=tid in self._pages)

    async def pages(self):
        "Every page target in the CDP Chrome, Leela's own tabs included."
        if not self.running(): raise BrowserUnavailable(f'no browser running on the CDP port {self.port}')
        cdp = await self.cdp()
        return L(await cdp.pages).map(self._as_page)

    async def open(self, url, background=True):
        "Open `url` as a new target and return it. `background` keeps focus in Leela."
        url = self.check(url)
        cdp = await self.cdp()
        tid = await cdp.target.createTarget(url=url, background=background)
        await asyncio.sleep(.05)   # createTarget answers before the load
        self._mine.add(tid)
        self._remember()
        p = await self.page(tid)
        return WebPage(id=tid, url=url, title=await self.title(p) or url, attached=True)

    async def shut(self, tid, mine_only=False):
        "Close one page in Chrome and forget its session. `mine_only` spares one Leela adopted."
        cdp = await self.cdp()
        if mine_only and tid not in self._mine: return False
        self._pages.pop(tid, None); self._casts.pop(tid, None)
        try: await cdp.target.closeTarget(targetId=tid)
        except Exception: return False
        self._mine.discard(tid)
        self._remember(drop=[tid])
        return True

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
        except Exception: h = {}
        i, entries = h.get('currentIndex', 0), h.get('entries', [])
        cur = entries[i] if 0 <= i < len(entries) else {}
        return {'id': tid, 'url': cur.get('url', ''), 'title': await self.title(p),
                'back': i > 0, 'forward': i < len(entries) - 1}

    async def title(self, p):
        try: return await p.eval('document.title') or ''
        except Exception: return ''

    async def markdown(self, tid, sel=None):
        "The live page as Markdown, through the same `fossick.to_md` research uses."
        from fossick.core import to_md
        p = await self.page(tid)
        md = to_md(await p.eval('document.documentElement.outerHTML') or '', sel=sel)
        if md.strip(): return md
        return (await p.eval('document.body ? document.body.innerText : ""') or '').strip()

    async def resize(self, tid, width, height, scale=1):
        "Pin the viewport to the panel showing it, so panel (x, y) is page (x, y). Sizes are CSS pixels; `scale` is the panel's device pixel ratio."
        w = max(240, min(int(width or 0) or DEFAULT_SIZE[0], MAX_SIZE[0]))
        h = max(180, min(int(height or 0) or DEFAULT_SIZE[1], MAX_SIZE[1]))
        s = max(1.0, min(float(scale or 1), MAX_SCALE))
        p = await self.page(tid)
        await p.emulation.setDeviceMetricsOverride(width=w, height=h, mobile=False,
                                                   deviceScaleFactor=s)
        return w, h

    async def start_cast(self, tid, width, height, quality=80, scale=1, owner=None):
        "Stream frames for `tid`. `(width, height, owner)`; `owner` is the socket that owns it."
        w, h = await self.resize(tid, width, height, scale)
        p = await self.page(tid)
        try:
            await p.emulation.setFocusEmulationEnabled(enabled=True)
            await p.page.bringToFront()
        except Exception: pass
        # A ceiling rather than a size: a frame Chrome rasterised at `SCALE_FLAG` must not be
        # scaled back down to the CSS box, which is what pinning these to `w, h` did.
        await p.page.startScreencast(format='jpeg', quality=int(quality),
                                     maxWidth=round(w*MAX_SCALE), maxHeight=round(h*MAX_SCALE),
                                     everyNthFrame=1)
        owner = self._casts[tid] = ifnone(owner, object())
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

    async def mouse(self, tid, kind, x, y, button='left', clicks=1, modifiers=0, dx=0, dy=0):
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
