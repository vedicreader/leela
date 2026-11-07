"Independent web workspaces behind one Leela server."

from __future__ import annotations

import asyncio, hashlib, json, re, threading, time, weakref
from urllib.parse import parse_qs, urlsplit
from dataclasses import dataclass
from pathlib import Path

__all__ = ['WorkspaceSite', 'WorkspaceHub', 'LoopbackHostGuard', 'learn_navigation', 'OPEN_PATH', 'workspace_slug',
           'workspace_slugs', 'assign_slugs', 'cfg_mark', 'slug_map', 'save_slug_map', 'workspace_urls',
           'NoWindow', 'set_confirmer', 'grant', 'declined', 'admit_folder', 'window_name', 'reset_gate']

LOOPBACK = ('127.0.0.1', 'localhost', '::1')
SAFE_METHODS = ('GET', 'HEAD', 'OPTIONS')
GRANT_SECS, DECLINE_SECS, YES_SECS = 60, 600, 10
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

class NoWindow(Exception): "The confirmer has no window to ask in."

#: The folder gate's state: who asks, the one-time grants and the recent Nos, each `resolved path -> monotonic deadline`.
_gate = dict(confirm=None, grants={}, declined={}, lock=threading.Lock())
_hubs = weakref.WeakSet()
NO_WINDOW = 'No Leela window is open to ask in.'
BROWSER_NO = 'Leela adds a folder only when you ask for it in a Leela page.'

def reset_gate():
    "No confirmer, no grants, no Nos."
    _gate.update(confirm=None, grants={}, declined={})

def set_confirmer(f):
    "`f(question) -> bool` asks the person in a native dialog; it raises `NoWindow` when it cannot."
    _gate['confirm'] = f

def _key(p): return str(Path(p).expanduser().resolve())

def grant(root, secs=GRANT_SECS):
    "Let the next add of `root` within `secs` seconds pass with no question: a folder the person picked or opened from the Dock or Finder."
    _gate['grants'][_key(root)] = time.monotonic() + secs

def declined(root) -> bool:
    "Whether the person said No to `root` in the last `DECLINE_SECS` seconds."
    return _gate['declined'].get(_key(root), 0) > time.monotonic()

def window_name(ws) -> str:
    "The window a workspace is, as the question names it."
    from .core.projects import loose_root
    r = ws.project_root
    return f'the Leela window for {Path(r).name}' if r is not None and r != loose_root() else 'this Leela window'

def _hval(headers, k):
    v = headers.get(k) if hasattr(headers, 'get') else None
    if v is None and isinstance(headers, dict): v = headers.get(k.encode())
    return (v.decode('latin-1') if isinstance(v, bytes) else v or '')

def _same_origin(headers) -> bool:
    "A browser's own request from a Leela page: `Sec-Fetch-Site: same-origin` and an `Origin` that is the `Host`."
    o, host = _hval(headers, 'origin'), _hval(headers, 'host').lower()
    return _hval(headers, 'sec-fetch-site').lower() == 'same-origin' and bool(o) and (o == 'null' or urlsplit(o).netloc.lower() == host)

def _is_open(r, covers=None):
    from .core.projects import loose_root
    loose = str(loose_root())
    if r == loose or (covers is not None and covers(Path(r))): return True
    return any(s.root == r or (s.covers and s.root and s.root != loose and s.covers(Path(r))) for h in list(_hubs) for s in list(h.sites.values()))

def _refusal(root, error, no=False): return 403, {'ok': False, 'declined': no, 'offer': root, 'error': error}

def _question(todo, into, files):
    q = f"Add the folder {todo[0]} to {into}?" if len(todo) == 1 else f"Add the folders {' and '.join(todo)} to {into}?"
    return q + (f"\n\nLeela then opens {', '.join(Path(f).name for f in files)}." if files else '')

def admit_folder(root, into, files=(), trusted=False, covers=None, headers=None):
    "None when the folder `root` (or each of a list) may be added to the window `into`, else `(status, body)`. Asks the person at most once."
    roots = [_key(r) for r in ([root] if isinstance(root, (str, Path)) else root)]
    need = lambda: [r for r in roots if not _is_open(r, covers)]
    if not (todo := need()) or trusted: return None
    now, g = time.monotonic(), _gate['grants']
    if all(g.get(r, 0) > now for r in todo):
        for r in todo: g.pop(r, None)
        return None
    if any(map(declined, todo)): return _refusal(todo[0], f'You said No to adding {todo[0]}. Leela does not ask again for 10 minutes.', True)
    if _gate['confirm'] is None: return None if _same_origin(headers or {}) else _refusal(todo[0], BROWSER_NO)
    with _gate['lock']:
        if not (todo := need()): return None
        now = time.monotonic()
        if all(g.get(r, 0) > now for r in todo): return None
        if any(map(declined, todo)): return _refusal(todo[0], f'You said No to adding {todo[0]}.', True)
        try: yes = bool(_gate['confirm'](_question(todo, into, files)))
        except NoWindow: return _refusal(todo[0], NO_WINDOW)
        except Exception: yes = False
        now = time.monotonic()
        # a Yes covers the requests that were waiting on this dialog for the same folders
        for r in todo: (g if yes else _gate['declined'])[r] = now + (YES_SECS if yes else DECLINE_SECS)
        return None if yes else _refusal(todo[0], f'You said No to adding {todo[0]}.', True)

def _unopenable(file, root):
    "Why `file` cannot be opened as a tab in the workspace at `root` (a folder, or a list of them), or None."
    from .blocks.fs.fs import loose_refusal
    from .core.projects import loose_root
    from .workspace import openable
    try: f = Path(file).expanduser().resolve()
    except (OSError, ValueError): return f'not a file: {file}'
    if not f.is_file(): return f'not a file: {file}'
    if root == loose_root():
        if why := loose_refusal(f): return why
    elif root is not None and not any(f.is_relative_to(r) for r in (root if isinstance(root, list) else [root])): return f'{f} is outside {root if not isinstance(root, list) else root[0]}'
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

async def _refuse(scope, send, why, status=421):
    "Turn a request away over whichever protocol it arrived on."
    if scope.get('type') == 'websocket':
        return await send({'type': 'websocket.close', 'code': 1008, 'reason': why})
    await send({'type': 'http.response.start', 'status': status,
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
    #: `covers(path)`: whether a folder this workspace has open holds `path`. Absent, `root` alone is asked.
    covers: object = None
    #: `add_root(path)` adds a folder to this workspace: the second folder one question may add.
    add_root: object = None

def learn_navigation(scope, headers) -> bool:
    "True for a browser's top-level `GET /learn` navigation, the one cross-site request that the guard lets in."
    h = lambda k: headers.get(k, b'').decode().lower()
    return (scope.get('method') == 'GET' and scope.get('path') == '/learn'
            and h(b'sec-fetch-mode') == 'navigate' and h(b'sec-fetch-dest') == 'document')

class LoopbackHostGuard:
    "Reject DNS-rebinding and forwarded Host headers before they reach executable routes."
    def __init__(self, app): self.app = app
    async def __call__(self, scope, receive, send):
        headers = _headers(scope)
        host = _host(headers)
        allowed = not host or host in LOOPBACK or host.endswith('.localhost')
        origin = headers.get(b'origin', b'').decode()
        origin_host = _name(urlsplit(origin).hostname) if origin else ''
        site = headers.get(b'sec-fetch-site', b'').decode().lower()
        # a page with `Referrer-Policy: no-referrer` posts to itself with `Origin: null`
        origin_ok = not origin or origin_host in LOOPBACK or origin_host.endswith('.localhost') or (origin == 'null' and site == 'same-origin')
        # `same-site` is a page on another local port: 127.0.0.1:3000 and 127.0.0.1:5001 are one site
        browser_ok = site in ('', 'same-origin', 'none') or learn_navigation(scope, headers)
        if not (allowed and origin_ok and browser_ok): return await _refuse(scope, send, 'invalid Host header')
        # as abhyasa's `LocalOnly`: a change, or a socket, from a page on another port is another site's
        changes = scope.get('type') == 'websocket' or scope.get('method', 'GET') not in SAFE_METHODS
        if changes and origin and origin != 'null' and urlsplit(origin).netloc.lower() != headers.get(b'host', b'').decode().lower():
            return await _refuse(scope, send, 'Leela does not take changes from another page.', 403)
        await self.app(scope, receive, send)

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
        _hubs.add(self)
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
    def site_covering(self, f):
        "The deepest folder site that already holds file `f`. The loose and welcome sites hold nothing."
        from .core.projects import loose_root
        f, loose = Path(f).expanduser().resolve(), str(loose_root())
        hits = [s for s in self.sites.values() if s.root and s.root != loose and (s.covers(f) if s.covers else f.is_relative_to(s.root))]
        return max(hits, key=lambda s: len(s.root), default=None)
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
        # A file alone never adds a folder: one no open folder holds goes to the loose window, with the folder as `offer`. `folder=1` asks to add it.
        from .core.projects import loose_root, workspace_for
        q = parse_qs(scope.get('query_string', b'').decode())
        raw, file, folder = (q.get('path') or [''])[0], (q.get('file') or [''])[0], (q.get('folder') or [''])[0] == '1'
        if scope.get('method', 'GET') != 'POST' and raw.strip():
            return await _json(send, {'ok': False, 'error': 'Open a folder with a POST request.', 'config': cfg_mark()}, 405)
        try: root = Path(raw).expanduser().resolve() if raw.strip() else None
        except (OSError, ValueError): root = None
        # A file alone, as Open… sends it, goes where a Finder open sends it.
        if root is not None and root.is_file() and not file: file, root = str(root), workspace_for(root) or loose_root()
        if root is None or not root.is_dir():
            return await _json(send, {'ok': False, 'error': f'not a folder: {raw}', 'config': cfg_mark()}, 400)
        try: also = [a for a in (Path(x).expanduser().resolve() for x in q.get('also') or [] if x.strip()) if a.is_dir()]
        except (OSError, ValueError): also = []
        loose, site, offer = loose_root(), None, ''
        if file and not folder and root != loose and (site := self.site_covering(file)) is None: offer, root, also = str(root), loose, []
        # Refused before anything is built, so a bad file leaves no workspace, recent entry or window behind.
        if file and (why := _unopenable(file, None if site else [root, *also] if also else root)):
            return await _json(send, {'ok': False, 'error': why, 'offer': offer, 'config': cfg_mark()}, 400)
        if site is None:
            into = f'the Leela window for {root.name}' if self.site_at(root) else 'a new Leela window'
            # off the loop: the question waits on a person, and the window it asks in needs the loop to load
            if no := await asyncio.to_thread(admit_folder, [root, *also], into, [file] if file else (), headers=_headers(scope)):
                return await _json(send, {**no[1], 'config': cfg_mark()}, no[0])
        # Building one starts a kernel pool, which would stall every open window on the loop.
        try:
            if site is None: site = await asyncio.to_thread(self.open_folder, root)
            for a in also:
                if site.add_root is None: raise RuntimeError('this workspace cannot add a folder')
                await asyncio.to_thread(site.add_root, a)
            if file:
                if site.open_file is None: raise RuntimeError('this workspace cannot open a file')
                f = Path(file).expanduser().resolve()
                await asyncio.to_thread(site.open_file, f)
                if site.root != str(loose) and (ls := self.site_at(loose)) and ls.release:
                    for r in ([root, *also] if folder else [f]): await asyncio.to_thread(ls.release, r)
        except Exception as e: return await _json(send, {'ok': False, 'error': str(e), 'config': cfg_mark()}, 400)
        await _json(send, {'ok': True, 'id': site.slug, 'name': site.name, 'root': site.root, 'offer': offer,
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
