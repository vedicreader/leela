"Independent web workspaces behind one Leela server."

from __future__ import annotations

import asyncio, hashlib, json, re, threading
from urllib.parse import parse_qs, urlsplit
from dataclasses import dataclass
from pathlib import Path

__all__ = ['WorkspaceSite', 'WorkspaceHub', 'LoopbackHostGuard', 'OPEN_PATH', 'workspace_slug',
           'workspace_slugs', 'assign_slugs', 'cfg_mark', 'slug_map', 'save_slug_map', 'workspace_urls']

LOOPBACK = ('127.0.0.1', 'localhost', '::1')
#: Where a running Leela is asked for another workspace. On the hub, which the new site joins, not on any one workspace.
OPEN_PATH = '/hub/open'

def workspace_slug(value, used=()):
    "A URL-safe slug for `value`, suffixed until it is not already in `used`."
    base = re.sub(r'[^a-z0-9]+', '-', str(value).lower()).strip('-') or 'workspace'
    slug, n, used = base, 2, set(used)
    while slug in used:
        slug, n = f'{base}-{n}', n + 1
    return slug

def _pathmark(root):
    return hashlib.blake2b(str(root).encode(), digest_size=3).hexdigest()

def cfg_mark(cfg=None):
    "Which config dir a Leela serves from, as `/hub/open` reports it: a second launch attaches only to its own."
    from . import leela_cfg
    return _pathmark(Path(cfg or leela_cfg).expanduser().resolve())

def slug_store():
    from . import leela_cfg
    return leela_cfg/'workspaces'/'index.json'

def slug_map(store=None):
    "Which slug each folder has been given. A missing or corrupt file reads as none, never an error."
    try: d = json.loads(Path(store or slug_store()).read_text())
    except (OSError, ValueError): return {}
    return {str(k): str(v) for k, v in d.items()} if isinstance(d, dict) else {}

def save_slug_map(m, store=None):
    from fastcore.xtras import atomic_save
    store = Path(store or slug_store())
    try:
        store.parent.mkdir(parents=True, exist_ok=True)
        with atomic_save(store, mode='w') as f: json.dump(m, f, indent=1)
    except OSError: pass

def workspace_slugs(roots, taken=None, used=()):
    "Slugs for `roots`, named after the folder and remembered per folder in `taken`."
    # The slug names the state file, so a counter would hand a folder another project's tabs.
    taken = {} if taken is None else taken
    used, out = set(used) | set(taken.values()), []
    for r in roots:
        r = str(r)
        if (s := taken.get(r)) is None:
            s = workspace_slug(Path(r).name)
            if s in used: s = workspace_slug(f'{s}-{_pathmark(r)}', used)
            taken[r] = s
        used.add(s); out.append(s)
    return out

def assign_slugs(roots, store=None):
    "`workspace_slugs`, remembering the assignments it makes so the next launch repeats them."
    taken = slug_map(store)
    before = dict(taken)
    out = workspace_slugs(roots, taken)
    if taken != before: save_slug_map(taken, store)
    return out

def workspace_urls(roots, port, store=None):
    "Where each root will be served, before `serve_ide` has built the workspaces to say so."
    # Resolved, because `serve_ide` slugs resolved roots: a symlink would name another host.
    roots = [Path(r).expanduser().resolve() for r in roots]
    return [f'http://{s}.localhost:{port}/' for s in assign_slugs(roots, store)]

def _unopenable(file, root):
    "Why `file` cannot be opened as a tab in the workspace at `root`, or None."
    from .blocks.fs.fs import loose_refusal
    from .core.projects import loose_root
    from .workspace import openable
    try: f = Path(file).expanduser().resolve()
    except (OSError, ValueError): return f'not a file: {file}'
    if not f.is_file(): return f'not a file: {file}'
    if root == loose_root():
        if why := loose_refusal(f): return why
    elif not f.is_relative_to(root): return f'{f} is outside {root}'
    if not openable(f): return f'{f.name} is not a text file'
    return None

async def _json(send, body, status=200):
    raw = json.dumps(body).encode()
    await send({'type': 'http.response.start', 'status': status,
                'headers': [(b'content-type', b'application/json; charset=utf-8')]})
    await send({'type': 'http.response.body', 'body': raw})

def _headers(scope): return {k.lower(): v for k, v in (scope.get('headers') or ())}

def _name(raw):
    "A host name from a header or a URL: an IPv6 literal unbracketed, the port and root dot gone."
    raw = str(raw or '').lower()
    name = raw[1:].split(']', 1)[0] if raw.startswith('[') else raw.split(':', 1)[0]
    return name.rstrip('.')

def _host(headers): return _name(headers.get(b'host', b'').decode())

async def _refuse(scope, send, why):
    "Turn a request away over whichever protocol it arrived on."
    if scope.get('type') == 'websocket':
        return await send({'type': 'websocket.close', 'code': 1008, 'reason': why})
    await send({'type': 'http.response.start', 'status': 421,
                'headers': [(b'content-type', b'text/plain; charset=utf-8')]})
    await send({'type': 'http.response.body', 'body': why.encode()})

@dataclass
class WorkspaceSite:
    slug: str
    name: str
    root: str
    app: object
    #: `open_file(path)` shows a file as this workspace's active tab. Absent, the hub cannot open files in it.
    open_file: object = None
    #: `release(path)` closes that tab. Only the loose-files workspace gives one up when a folder takes the file.
    release: object = None

class LoopbackHostGuard:
    "Reject DNS-rebinding and forwarded Host headers before they reach executable routes."
    def __init__(self, app): self.app = app
    async def __call__(self, scope, receive, send):
        headers = _headers(scope)
        host = _host(headers)
        allowed = not host or host in LOOPBACK or host.endswith('.localhost')
        origin = headers.get(b'origin', b'').decode()
        origin_host = _name(urlsplit(origin).hostname) if origin else ''
        origin_ok = not origin or origin_host in LOOPBACK or origin_host.endswith('.localhost')
        browser_ok = headers.get(b'sec-fetch-site', b'').decode().lower() != 'cross-site'
        if allowed and origin_ok and browser_ok:
            await self.app(scope, receive, send)
            return
        await _refuse(scope, send, 'invalid Host header')

class WorkspaceHub:
    "ASGI host dispatcher for isolated workspace applications."
    def __init__(self, sites, port, default=None, build=None):
        self.sites = {s.slug: s for s in sites}
        self.port = int(port)
        self.default = default or next(iter(self.sites), '')
        #: `build(root, slug)` -> `WorkspaceSite`. Without one the hub serves what it launched with.
        self.build = build
        self._loop = self._scope = None
        self._queues, self._legs = {}, []
        # Two files for one checkout arrive together on a cold launch: one site, not two.
        self._opening = threading.Lock()
    def url_for(self, slug): return f'http://{slug}.localhost:{self.port}/'
    def catalog(self):
        "Every workspace and the `*.localhost` URL that reaches it."
        return [{'id': s.slug, 'name': s.name, 'root': s.root, 'url': self.url_for(s.slug)}
                for s in self.sites.values()]
    def site_for(self, scope):
        "The workspace a request's Host header names, or None."
        host = _host(_headers(scope))
        if host.endswith('.localhost'): return self.sites.get(host[:-10])
        if not host or host in LOOPBACK: return self.sites.get(self.default)
        return None
    def site_at(self, root):
        "The workspace already serving `root`, or None. A folder opened twice is one window."
        root = str(root)
        return next((s for s in self.sites.values() if s.root and s.root == root), None)
    def add_site(self, site):
        "Register a workspace built after launch, and give it the lifespan the others got."
        self.sites[site.slug] = site
        # Reached from a request, which uvicorn runs in a threadpool: no loop to create a task on.
        if self._loop is not None: self._loop.call_soon_threadsafe(self._start_leg, site)
        return self.url_for(site.slug)
    def open_folder(self, root):
        "The site serving `root`, building and registering one when nothing does yet."
        with self._opening:
            if (s := self.site_at(root)) is not None: return self._noted(root, s)
            if self.build is None: raise RuntimeError('this workspace cannot open another folder')
            s = self.build(root, assign_slugs([root])[0])
            if s is None: raise RuntimeError(f'no workspace could be built for {root}')
            self.add_site(s)
            return self._noted(root, s)
    def _noted(self, root, site):
        "Remember the folder here, where both callers pass, rather than in the desktop one."
        from .core.projects import loose_root, note_folder
        if Path(root) == loose_root(): return site
        try: note_folder(str(root))
        except Exception: pass
        return site
    def _start_leg(self, site):
        self._queues[site.slug] = q = asyncio.Queue()
        q.put_nowait({'type': 'lifespan.startup'})
        self._legs.append(asyncio.create_task(self._leg(site.app, q)))
    async def _leg(self, app, q):
        async def spent(message): pass
        await app(dict(self._scope), q.get, spent)
    async def __call__(self, scope, receive, send):
        # Lifespan carries no Host header, so it belongs to every workspace rather than to
        # whichever answers for bare loopback: one that never hears it never stops its kernels.
        if scope.get('type') == 'lifespan': return await self._lifespan(scope, receive, send)
        if scope.get('path') == OPEN_PATH: return await self._open(scope, send)
        site = self.site_for(scope)
        if site is None: return await _refuse(scope, send, 'unknown workspace host')
        scope = dict(scope)
        scope['leela.workspace_id'] = site.slug
        await site.app(scope, receive, send)
    async def _open(self, scope, send):
        "Serve a folder as its own workspace, and with `file`, open that file in it. The desktop shell then points a window at the row."
        from .core.projects import loose_root
        q = parse_qs(scope.get('query_string', b'').decode())
        raw, file = (q.get('path') or [''])[0], (q.get('file') or [''])[0]
        try: root = Path(raw).expanduser().resolve() if raw.strip() else None
        except (OSError, ValueError): root = None
        if root is None or not root.is_dir():
            return await _json(send, {'ok': False, 'error': f'not a folder: {raw}', 'config': cfg_mark()}, 400)
        # Refused before anything is built, so a bad file leaves no workspace, recent entry or window behind.
        if file and (why := _unopenable(file, root)):
            return await _json(send, {'ok': False, 'error': why, 'config': cfg_mark()}, 400)
        # Building one starts a kernel pool, which would stall every open window on the loop.
        try:
            site = await asyncio.to_thread(self.open_folder, root)
            if file:
                if site.open_file is None: raise RuntimeError('this workspace cannot open a file')
                f = Path(file).expanduser().resolve()
                await asyncio.to_thread(site.open_file, f)
                if root != loose_root() and (ls := self.site_at(loose_root())) and ls.release: await asyncio.to_thread(ls.release, f)
        except Exception as e: return await _json(send, {'ok': False, 'error': str(e), 'config': cfg_mark()}, 400)
        await _json(send, {'ok': True, 'id': site.slug, 'name': site.name, 'root': site.root,
                           'url': self.url_for(site.slug), 'config': cfg_mark()})
    async def _lifespan(self, scope, receive, send):
        "One startup and one shutdown, fanned out to every site and answered once."
        self._loop, self._scope = asyncio.get_running_loop(), dict(scope)
        for s in self.sites.values(): self._queues[s.slug] = asyncio.Queue()
        self._legs = [asyncio.create_task(self._leg(s.app, self._queues[s.slug]))
                      for s in self.sites.values()]
        try:
            while True:
                message = await receive()
                # Listed, not iterated: a folder opened while this is in flight adds a queue.
                for q in list(self._queues.values()): q.put_nowait(message)
                if message['type'] == 'lifespan.startup':
                    await send({'type': 'lifespan.startup.complete'})
                elif message['type'] == 'lifespan.shutdown':
                    await asyncio.gather(*self._legs, return_exceptions=True)
                    return await send({'type': 'lifespan.shutdown.complete'})
        finally:
            self._loop = None
            for t in self._legs:
                if not t.done(): t.cancel()
