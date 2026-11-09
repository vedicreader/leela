import threading
from starlette.responses import PlainTextResponse
from starlette.routing import Match, Mount
from ... import errstr
from ...core.web import off_loop
from .tools import learn_ask, learn_store

__all__ = ['HOSTS', 'Hosted', 'abhyasa_app', 'host_ask', 'mount_abhyasa', 'no_speech']

HOSTS = ('127.0.0.1', 'localhost', '::1')
LEFT_OUT = ('build', 'guide')


def host_ask(ai):
    "Abhyasa's default ask, hosted: each routed task goes to `learn_ask(ai, task)`, so `ai.oneshot` and the privacy guard see every call."
    class HostAsk:
        hosted, model = True, 'leela'
        def via(self, task, name='', max_tokens=None):
            ask = learn_ask(ai, task)
            ask.stream, ask.model = (lambda prompt, sp='': iter([ask(prompt, sp)])), name or self.model
            return ask
        def __call__(self, prompt, sp=''): return self.via('ask')(prompt, sp)
    return HostAsk()


def no_speech(audio, hint=''): raise RuntimeError('Speech comes in S6: Leela has no transcribe function yet.')


class _Live:
    "The workspace's active assistant, looked up on each use, because the thread may change."
    def __init__(self, ws): self._ws = ws
    def __getattr__(self, name): return getattr(self._ws.ai, name)


def abhyasa_app(ws, ai=None, hosts=None):
    "Abhyasa's app over the Learn store of `ws`, with the blocks that run their own agents left out and no speech warm-up."
    from abhyasa.app import mk_app
    from abhyasa.blocks import NAMES
    _, lr = learn_store(ws)
    return mk_app(lr, host_ask(ai or _Live(ws)), transcribe=no_speech, names=[n for n in NAMES if n not in LEFT_OUT], warm_speech=False, hosts=hosts or HOSTS)


class Hosted:
    "Leela's last route: Abhyasa's app, built on the first request that no Leela route answered."
    def __init__(self, build, siblings=()): self.build, self.siblings, self.app, self.lock = build, siblings, None, threading.Lock()
    def partial(self, scope):
        "The Leela route that matches the path but not the method."
        return next((r for r in self.siblings if r.matches(scope)[0] == Match.PARTIAL), None)
    def get(self):
        with self.lock:
            if self.app is None: self.app = self.build()
            return self.app
    def stop(self):
        from abhyasa.app import stop_app
        if self.app is not None: stop_app(self.app)
    async def _refuse(self, scope, receive, send, text, status):
        if scope['type'] == 'websocket': return await send(dict(type='websocket.close', code=1008))
        await PlainTextResponse(text, status)(scope, receive, send)
    async def __call__(self, scope, receive, send):
        if scope['type'] not in ('http', 'websocket'): return
        from abhyasa.app import LocalOnly
        if scope['type'] == 'http' and (r := self.partial(scope)): return await r.handle(scope, receive, send)   # Starlette takes a later full match over an earlier partial one: that route's 405 stands
        if scope['type'] == 'http' and (why := LocalOnly(None, HOSTS).refuse(scope)): return await self._refuse(scope, receive, send, why, 403)
        try: app = self.app or await off_loop(self.get)
        except Exception as e: return await self._refuse(scope, receive, send, f'Learn is not available: {errstr(e)}', 503)
        await app(dict(scope), receive, send)   # a copy: Abhyasa's session middleware must not replace the one Leela's holds


def mount_abhyasa(app, ws, ai=None):
    "Append Abhyasa's app to `app` as its last route, and stop it when `app` shuts down."
    h = Hosted(lambda: abhyasa_app(ws, ai))
    h.siblings = app.router.routes
    app.router.routes.append(Mount('/', app=h))
    async def stop(): await off_loop(h.stop)
    app.on_event('shutdown')(stop)
    return h