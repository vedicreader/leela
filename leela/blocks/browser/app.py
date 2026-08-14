"""The inline browser's surface: open a page, list what Chrome has, stream one into a tab.

The JSON routes are the cheap half -- opening, closing and listing pages, and lifting one out
as Markdown for research or the vault. The interesting half is `/browser/ws`, which pairs one
Leela tab with one CDP target: frames out, input in, for as long as the tab is on screen.
"""

from __future__ import annotations

import asyncio
import json

from fasthtml.common import Div
from starlette.routing import WebSocketRoute

from ... import errstr
from ...core.web import fail
from ..tabs.ui import tab_bar
from .browser import BrowserUnavailable

__all__ = ['CAPS', 'connect']

CAPS = ('browser', 'memory')

# How long the socket waits on Chrome before deciding the page is wedged rather than busy.
FRAME_TIMEOUT = 30


def connect(app, ctx):
    rt = app.route
    browser = ctx.browser

    @rt('/browser/ready')
    def browser_ready():
        "Is there a browser to render into? Cheap, and never starts one to find out."
        return {'ok': browser.running(), 'port': browser.port}

    @rt('/browser/tabs')
    async def browser_tabs():
        "Every page the CDP Chrome holds -- Leela's own workspace windows included."
        try: return {'ok': True, 'tabs': [p.dict() for p in await browser.pages()]}
        except BrowserUnavailable as e: return {'ok': False, 'error': errstr(e), 'tabs': []}

    # These two answer with the tab strip rather than JSON, because that is what opening a tab
    # means everywhere else in Leela: `/tab/open` and friends swap `#tabbar` and nothing more.
    @rt('/browser/open')
    async def browser_open(url: str = '', title: str = ''):
        "Open `url` in Chrome and give Leela a tab pointed at it."
        try:
            page = await browser.open(url)
            ctx.session.open_web(page.id, title or page.title or page.url)
            ctx.session.save()
        except Exception as e: return Div(errstr(e), cls='lee-err')
        return tab_bar(ctx.session)

    @rt('/browser/attach')
    async def browser_attach(id: str = '', title: str = ''):
        "Adopt a page Chrome already has -- one fossick opened, or one a link spawned."
        try:
            state = await browser.state(id)
            ctx.session.open_web(id, title or state.get('title') or state.get('url') or 'page')
            ctx.session.save()
        except Exception as e: return Div(errstr(e), cls='lee-err')
        return tab_bar(ctx.session)

    @rt('/browser/close')
    async def browser_close(id: str = ''):
        "Close the page in Chrome. The Leela tab is closed by the tab strip, as usual."
        try: return {'ok': await browser.shut(id)}
        except Exception as e: return fail(e)

    @rt('/browser/state')
    async def browser_state(id: str = ''):
        try: return {'ok': True, **await browser.state(id)}
        except BrowserUnavailable as e: return fail(e, 503)
        except Exception as e: return fail(e)

    @rt('/browser/markdown')
    async def browser_markdown(id: str = '', remember: bool = False):
        """The live page as Markdown -- what research would have fetched, after the JS ran.

        This is the reason the browser is inside Leela rather than beside it: a page behind a
        login or a client-rendered app is readable here and is not readable to a plain fetch.
        """
        try:
            md = await browser.markdown(id)
            state = await browser.state(id)
        except BrowserUnavailable as e: return fail(e, 503)
        except Exception as e: return fail(e)
        note = ''
        if remember:
            try: note = _remember(ctx, state, md)
            except Exception as e: note = errstr(e)
        return {'ok': True, 'markdown': md, 'note': note, **state}

    _socket(app, ctx, browser)


def _remember(ctx, state, md):
    "Put a live page into the same vault a fetched one goes to, as the same kind of document."
    from ..research.research import Doc
    doc = Doc(title=state.get('title') or state.get('url', ''), url=state.get('url', ''),
              text=md, kind='page')
    saved = ctx.memory.remember(doc)
    return f"remembered as {saved.get('doc_id')}" if saved else 'not remembered'


def _socket(app, ctx, browser):
    """Pair one Leela tab with one CDP target for as long as the tab is showing.

    A raw Starlette route rather than FastHTML's `ws`, for the same reason the terminal
    sockets are: the handler needs the socket object itself, not injected parameters.
    """

    async def handler(sock):
        await sock.accept()
        tid = casting = None
        try:
            hello = json.loads((await sock.receive()).get('text') or '{}')
            tid = hello.get('id') or ''
            if not tid: raise ValueError('no page id')
            w, h = await browser.start_cast(tid, hello.get('w'), hello.get('h'),
                                            scale=hello.get('scale') or 1)
            casting = tid
            await sock.send_text(json.dumps({'t': 'ready', 'w': w, 'h': h,
                                             **await browser.state(tid)}))
        except Exception as e:
            await sock.send_text(json.dumps({'t': 'error', 'error': errstr(e)}))
            await sock.close()
            return

        cdp = await browser.cdp()
        page = await browser.page(tid)

        async def to_client():
            "Screencast frames for this page only, acked so Chrome keeps sending them."
            async with cdp.on('Page.screencastFrame') as q:
                while True:
                    m = await q.get()
                    if m.get('sessionId') != page.sid: continue
                    p = m.get('params') or {}
                    await sock.send_text(json.dumps({'t': 'frame', 'data': p.get('data', ''),
                                                     'meta': p.get('metadata') or {}}))
                    # The frame's own `sessionId` is Chrome's ack token and has nothing to do
                    # with the CDP session above; not acking stops the stream after one frame.
                    try: await browser.ack(tid, p.get('sessionId'))
                    except Exception: return

        async def navigation():
            "Tell the address bar where the page went, whoever navigated it."
            async with cdp.on('Page.frameNavigated') as q:
                while True:
                    m = await q.get()
                    if m.get('sessionId') != page.sid: continue
                    if (m.get('params') or {}).get('frame', {}).get('parentId'): continue
                    await sock.send_text(json.dumps({'t': 'nav', **await browser.state(tid)}))

        async def from_client():
            while True:
                m = await sock.receive()
                if m['type'] == 'websocket.disconnect': return
                if (text := m.get('text')) is None: continue
                try: await _drive(browser, tid, json.loads(text), sock)
                except Exception as e:
                    await sock.send_text(json.dumps({'t': 'error', 'error': errstr(e)}))

        tasks = [asyncio.create_task(c()) for c in (to_client, navigation, from_client)]
        try: await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in tasks:
                if not t.done(): t.cancel()
            if casting: await browser.stop_cast(casting)
            try: await sock.close()
            except Exception: pass

    app.router.routes.append(WebSocketRoute('/browser/ws', handler))
    return handler


async def _drive(browser, tid, c, sock):
    "One client command against the attached page."
    t = c.get('t')
    if t == 'mouse':
        await browser.mouse(tid, c['kind'], c.get('x', 0), c.get('y', 0),
                            button=c.get('button', 'left'), clicks=c.get('clicks', 1),
                            modifiers=c.get('modifiers', 0), dx=c.get('dx', 0), dy=c.get('dy', 0))
    elif t == 'key':
        await browser.key(tid, c['kind'], **{k: v for k, v in c.items()
                                             if k in _KEY_FIELDS and v not in (None, '')})
    elif t == 'text': await browser.insert(tid, c.get('text', ''))
    elif t == 'resize': await browser.start_cast(tid, c.get('w'), c.get('h'), scale=c.get('scale') or 1)
    elif t == 'goto':
        await browser.goto(tid, c.get('url', ''))
        await sock.send_text(json.dumps({'t': 'nav', **await browser.state(tid)}))
    elif t in ('back', 'forward'):
        await browser.history(tid, -1 if t == 'back' else 1)
    elif t == 'reload': await browser.reload(tid)
    elif t == 'state': await sock.send_text(json.dumps({'t': 'nav', **await browser.state(tid)}))
    else: raise ValueError(f'unknown browser command: {t!r}')


# What `Input.dispatchKeyEvent` will accept from the client. Anything else a keydown handler
# might carry is dropped rather than forwarded, so a malformed event is a missing keystroke
# instead of a CDP protocol error that closes the socket.
_KEY_FIELDS = ('text', 'key', 'code', 'windowsVirtualKeyCode', 'nativeVirtualKeyCode',
               'modifiers', 'location', 'autoRepeat', 'isKeypad', 'unmodifiedText')
