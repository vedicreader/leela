import contextvars, threading
from pathlib import Path
from urllib.parse import quote
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Match, Mount, Route
from ... import errstr, leela_cfg
from ...core.web import fail, off_loop
from ...hub import LOOPBACK
from ..memory.vaults import LEARN
from .speech import make_transcribe, speech_values
from .tools import contract_missing, missing_line, learn_ask, learn_settings, learn_store, learn_vision, learn_vision_why, run_gather

__all__ = ['BASE', 'HOSTS', 'Hosted', 'Prefixed', 'STATE', 'Shared', 'abhyasa_app', 'host_ask', 'learn_key', 'mount_abhyasa', 'shared', 'using']

HOSTS = (*LOOPBACK, '.localhost')   # `LoopbackHostGuard`'s rule: loopback, and any `<slug>.localhost`
LEFT_OUT = ('build', 'guide')
BASE = '/learn/abh'
STATE = 'learn-abhyasa'   # Abhyasa's own files, kept in Leela's config folder
METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']
_ws = contextvars.ContextVar('learn_ws', default=None)


class using:
    "Inside `with using(ws)`, Abhyasa's model calls go through the assistant of `ws`, and so do the background jobs it submits."
    def __init__(self, ws): self.ws = ws
    def __enter__(self): self.tok = _ws.set(self.ws)
    def __exit__(self, *a): _ws.reset(self.tok)


def host_ask(ai):
    "Abhyasa's default ask, hosted: each routed task goes to `learn_ask(ai, task)`, so `ai.oneshot` and the privacy guard see every call. Its `gather` and `vision` hooks do research and pictures as a job and a call of `ai`."
    class HostAsk:
        hosted, model = True, 'leela'
        def via(self, task, name='', max_tokens=None):
            ask = learn_ask(ai, task)
            ask.stream, ask.model = (lambda prompt, sp='': iter([ask(prompt, sp)])), name or self.model
            return ask
        def __call__(self, prompt, sp=''): return self.via('ask')(prompt, sp)
        def gather(self, lr, jid, stop): return run_gather(ai, lr, jid, stop)
        def vision(self, prompt, img, sp=''): return learn_vision(ai)(prompt, img, sp)
        def vision_why(self): return learn_vision_why(ai)
    return HostAsk()


class _Live:
    "The assistant of the workspace that the current request or job belongs to, looked up on each use."
    def __getattr__(self, name):
        if (ws := _ws.get()) is None: raise RuntimeError('no workspace: Abhyasa asked the model outside a Leela request')
        return getattr(ws.ai, name)


def learn_key(ws, make=False):
    "The path of the Learn vault of `ws`, which says what the one hosted app serves; None when none is attached (made first when `make`)."
    ref = ws.vaults.learn() if make else ws.vaults.get(LEARN)
    return str(Path(ref.path).resolve()) if ref else None


def abhyasa_app(ws, ai=None, hosts=None):
    "Abhyasa's app over the Learn store of `ws`, with the blocks that run their own agents left out and no speech warm-up."
    from abhyasa.app import mk_app
    from abhyasa.blocks import NAMES
    _, lr = learn_store(ws)
    return mk_app(lr, host_ask(ai or _Live()), transcribe=make_transcribe(ws.jobs, lambda: ws.project_root), names=[n for n in NAMES if n not in LEFT_OUT], warm_speech=False, hosts=hosts or HOSTS, config=leela_cfg/STATE)


class Shared:
    "The one Abhyasa app of the process, keyed by its Learn vault, and the hosts that use it."
    def __init__(self): self.app = self.key = None; self.users, self.lock = set(), threading.RLock()
    def get(self, user, key, build):
        "The app for `key`: kept when it serves that vault, else the old one is stopped and `build()` makes the new one."
        with self.lock:
            if self.app is None or self.key != key: self.drop(); self.app, self.key = build(), key
            self.users.add(user)
            return self.app
    def drop(self):
        from abhyasa.app import stop_app
        with self.lock:
            app, self.app, self.key = self.app, None, None
            if app is not None: stop_app(app)
    def release(self, user):
        "`user` is done; the app stops with its last user."
        with self.lock:
            self.users.discard(user)
            if not self.users: self.drop()


shared = Shared()


def _known(app, scope):
    "Whether Abhyasa's own route table answers `scope`; its catch-all for files in the working folder does not count."
    return any(r.matches(scope)[0] != Match.NONE for r in app.router.routes if not getattr(r, 'path', '').startswith('/{fname'))


class Hosted:
    "Leela's last route: Abhyasa's app, built only by `open` and shared by every workspace of the process."
    def __init__(self, ws, ai=None, siblings=(), reg=None): self.ws, self.ai, self.siblings, self.shared = ws, ai, siblings, reg or shared
    @property
    def app(self): return self.shared.app
    def partial(self, scope):
        "The Leela route that matches the path but not the method."
        return next((r for r in self.siblings if r.matches(scope)[0] == Match.PARTIAL), None)
    def get(self):
        "The app over this workspace's Learn vault, built when the process has none for it."
        def build():
            with using(self.ws): return abhyasa_app(self.ws, self.ai)
        return self.shared.get(self, learn_key(self.ws, True), build)
    def live(self):
        "The app when it serves this workspace's Learn vault, else None."
        s = self.shared
        return s.app if s.app is not None and s.key == learn_key(self.ws) else None
    def stop(self): self.shared.release(self)
    async def _refuse(self, scope, receive, send, text, status):
        if scope['type'] == 'websocket': return await send(dict(type='websocket.close', code=1008))
        await PlainTextResponse(text, status)(scope, receive, send)
    def _host(self, scope):
        from abhyasa.app import LocalOnly
        return LocalOnly(None, HOSTS).refuse(scope) if scope['type'] == 'http' else ''
    async def _serve(self, app, scope, receive, send, path=None):
        sc = dict(scope)   # a copy: Abhyasa's session middleware must not replace the one Leela's holds
        if path is not None: sc.update(path=path, raw_path=quote(path).encode())
        from abhyasa.learner import use_settings
        cur = learn_settings(self.ws)
        with using(self.ws), use_settings({**cur, **speech_values(cur=cur)}): await app(sc, receive, send)
    async def open(self, req):
        "POST `/learn/abh/open`: build the app if needed."
        if why := self._host(req.scope): return PlainTextResponse(why, 403)
        if missing := contract_missing(): return fail(f'Learn is not available: {missing_line(missing)}', 503)
        try: await off_loop(self.get)
        except Exception as e: return fail(f'Learn is not available: {errstr(e)}', 503)
        return JSONResponse(dict(ok=True, base=BASE))
    async def under(self, scope, receive, send):
        "Any method on `/learn/abh/{path}`: Abhyasa's `/{path}`, when the app is built for this workspace's vault."
        if why := self._host(scope): return await self._refuse(scope, receive, send, why, 403)
        if (app := self.live()) is None: return await JSONResponse(dict(ok=False, error='learn_not_open'), 409)(scope, receive, send)
        path = '/' + scope['path_params'].get('path', '')
        if not _known(app, {**scope, 'path': path}): return await self._refuse(scope, receive, send, 'Not found', 404)
        await self._serve(app, scope, receive, send, path)
    async def __call__(self, scope, receive, send):
        if scope['type'] not in ('http', 'websocket'): return
        if scope['type'] == 'http' and (r := self.partial(scope)): return await r.handle(scope, receive, send)   # Starlette takes a later full match over an earlier partial one: that route's 405 stands
        if why := self._host(scope): return await self._refuse(scope, receive, send, why, 403)
        if (app := self.live()) is None or not _known(app, scope): return await self._refuse(scope, receive, send, 'Not found', 404)
        await self._serve(app, scope, receive, send)


class Prefixed:
    "`Hosted.under` as the endpoint of a Starlette route."
    def __init__(self, h): self.h = h
    async def __call__(self, scope, receive, send): await self.h.under(scope, receive, send)


def mount_abhyasa(app, ws, ai=None):
    "Append the entry routes and Abhyasa's app to `app` as its last routes, and release the app when `app` shuts down."
    h = Hosted(ws, ai, app.router.routes)
    app.router.routes += [Route(f'{BASE}/open', h.open, methods=['POST']), Route(f'{BASE}/{{path:path}}', Prefixed(h), methods=METHODS), Mount('/', app=h)]
    async def stop(): await off_loop(h.stop)
    app.on_event('shutdown')(stop)
    return h
