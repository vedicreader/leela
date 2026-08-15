"The inline browser's surface. `/browser/ws` pairs a Leela tab with one CDP target."

from __future__ import annotations
import asyncio, base64, json

from fasthtml.common import Div
from starlette.routing import WebSocketRoute

from ... import errstr
from ...core.web import fail
from ..tabs.ui import tab_bar
from .browser import BrowserUnavailable

__all__ = ['CAPS', 'connect']

CAPS = ('browser', 'memory')

def connect(app, ctx):
    rt = app.route
    browser = ctx.browser

    @rt('/browser/ready')
    def browser_ready():
        "Could a page be opened here? `ok` is a Chrome to drive, `running` is one already up."
        return {'ok': browser.available(), 'running': browser.running(), 'port': browser.port}

    @rt('/browser/tabs')
    async def browser_tabs():
        "Every page the CDP Chrome holds -- Leela's own workspace windows included."
        try: return {'ok': True, 'tabs': [p.dict() for p in await browser.pages()]}
        except BrowserUnavailable as e: return {'ok': False, 'error': errstr(e), 'tabs': []}

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
        "The live page as Markdown -- what research would have fetched, after the JS ran."
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
    saved = ctx.memory.remember(Doc(title=state.get('title') or state.get('url', ''),
                                    url=state.get('url', ''), text=md, kind='page'))
    return f"remembered as {saved.get('doc_id')}" if saved else 'not remembered'

def _socket(app, ctx, browser):
    "Pair one Leela tab with one CDP target for as long as the tab is showing."
    async def handler(sock):
        await sock.accept()
        writing = asyncio.Lock()   # a Starlette websocket is not safe for concurrent sends

        async def say(**m):
            async with writing: await sock.send_text(json.dumps(m))

        tid, cast, mine = None, False, object()
        try:
            hello = json.loads((await sock.receive()).get('text') or '{}')
            if not (tid := hello.get('id') or ''): raise ValueError('no page id')
            w, h, _ = await browser.start_cast(tid, hello.get('w'), hello.get('h'),
                                               scale=hello.get('scale') or 1, owner=mine)
            cast = True
            await say(t='ready', w=w, h=h, **await browser.state(tid))
            # Guarded: Chrome dying here left a cast nobody stops and a socket nobody closes.
            cdp, page = await browser.cdp(), await browser.page(tid)
        except Exception as e:
            await say(t='error', error=errstr(e))
            if cast: _detach(browser.stop_cast(tid, mine))
            await sock.close()
            return

        async def to_client():
            "Screencast frames for this page only, acked so Chrome keeps sending them."
            async with cdp.on('Page.screencastFrame') as q:
                while True:
                    m = await q.get()
                    if m.get('sessionId') != page.sid: continue
                    p = m.get('params') or {}
                    try: jpeg = base64.b64decode(p.get('data') or '')
                    except (ValueError, TypeError): jpeg = b''
                    if jpeg:
                        async with writing: await sock.send_bytes(jpeg)
                    try: await _whole(browser.ack(tid, p.get('sessionId')))
                    except asyncio.CancelledError: raise
                    except Exception: return

        async def navigation():
            "Tell the address bar where the page went, whoever navigated it."
            async with cdp.on('Page.frameNavigated') as q:
                while True:
                    m = await q.get()
                    if m.get('sessionId') != page.sid: continue
                    if (m.get('params') or {}).get('frame', {}).get('parentId'): continue
                    await say(t='nav', **await _whole(browser.state(tid)))

        async def from_client():
            while True:
                try: m = await sock.receive()
                except Exception: return           # the client went away mid-read
                if m['type'] == 'websocket.disconnect': return
                if (text := m.get('text')) is None: continue
                try: await _whole(_drive(browser, tid, json.loads(text), say, mine))
                except asyncio.CancelledError: raise
                except Exception as e:
                    try: await say(t='error', error=errstr(e))
                    except Exception: return

        tasks = [asyncio.create_task(c()) for c in (to_client, navigation, from_client)]
        try: await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in tasks:
                if not t.done(): t.cancel()
            if cast: _detach(browser.stop_cast(tid, mine))
            try: await sock.close()
            except Exception: pass

    app.router.routes.append(WebSocketRoute('/browser/ws', handler))
    return handler

async def _whole(coro):
    "Await `coro`, but let it finish even if this task is cancelled. CDP calls only."
    return await asyncio.shield(coro)

# Held so the loop does not collect a teardown task before it has run.
_LOOSE = set()

def _detach(coro):
    "Run `coro` on the loop, outside the lifetime of whatever asked for it."
    t = asyncio.ensure_future(coro)
    _LOOSE.add(t)
    t.add_done_callback(_LOOSE.discard)
    return t

async def _drive(browser, tid, c, say, owner=None):
    "One client command against the attached page. `say(**msg)` is the serialised writer."
    t = c.get('t')
    if t == 'mouse':
        await browser.mouse(tid, c['kind'], c.get('x', 0), c.get('y', 0),
                            button=c.get('button', 'left'), clicks=c.get('clicks', 1),
                            modifiers=c.get('modifiers', 0), dx=c.get('dx', 0), dy=c.get('dy', 0))
    elif t == 'key':
        await browser.key(tid, c['kind'], **{k: v for k, v in c.items()
                                             if k in _KEY_FIELDS and v not in (None, '')})
    elif t == 'text': await browser.insert(tid, c.get('text', ''))
    elif t in ('resize', 'resume'):
        await browser.start_cast(tid, c.get('w'), c.get('h'), scale=c.get('scale') or 1, owner=owner)
    elif t == 'pause': await browser.stop_cast(tid, owner)
    elif t == 'goto':
        await browser.goto(tid, c.get('url', ''))
        await say(t='nav', **await browser.state(tid))
    elif t in ('back', 'forward'): await browser.history(tid, -1 if t == 'back' else 1)
    elif t == 'reload': await browser.reload(tid)
    elif t == 'state': await say(t='nav', **await browser.state(tid))
    else: raise ValueError(f'unknown browser command: {t!r}')

# What `Input.dispatchKeyEvent` accepts; anything else a keydown carries is dropped.
_KEY_FIELDS = ('text', 'key', 'code', 'windowsVirtualKeyCode', 'nativeVirtualKeyCode',
               'modifiers', 'location', 'autoRepeat', 'isKeypad', 'unmodifiedText')
