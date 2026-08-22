"Independent web workspaces behind one Leela server."

from __future__ import annotations

import asyncio, re
from urllib.parse import urlsplit
from dataclasses import dataclass
from pathlib import Path

__all__ = ['WorkspaceSite', 'WorkspaceHub', 'LoopbackHostGuard', 'workspace_slug',
           'workspace_slugs', 'workspace_urls']

LOOPBACK = ('127.0.0.1', 'localhost', '::1')

def workspace_slug(value, used=()):
    "A URL-safe slug for `value`, suffixed until it is not already in `used`."
    base = re.sub(r'[^a-z0-9]+', '-', str(value).lower()).strip('-') or 'workspace'
    slug, n, used = base, 2, set(used)
    while slug in used:
        slug, n = f'{base}-{n}', n + 1
    return slug

def workspace_slugs(names):
    "Slugs for `names`, disambiguated against each other and stable in order."
    used = []
    for n in names: used.append(workspace_slug(n, used))
    return used

def workspace_urls(roots, port):
    "Where each root will be served, before `serve_ide` has built the workspaces to say so."
    # Resolved, because `serve_ide` slugs resolved roots: a symlink would name another host.
    names = (Path(r).expanduser().resolve().name for r in roots)
    return [f'http://{s}.localhost:{port}/' for s in workspace_slugs(names)]

def _headers(scope): return {k.lower(): v for k, v in (scope.get('headers') or ())}

def _host(headers):
    "The Host header's name: an IPv6 literal unbracketed, the port dropped, lowercased."
    raw = headers.get(b'host', b'').decode().lower()
    return raw[1:].split(']', 1)[0] if raw.startswith('[') else raw.split(':', 1)[0]

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

class LoopbackHostGuard:
    "Reject DNS-rebinding and forwarded Host headers before they reach executable routes."
    def __init__(self, app): self.app = app
    async def __call__(self, scope, receive, send):
        headers = _headers(scope)
        host = _host(headers)
        allowed = not host or host in LOOPBACK or host.endswith('.localhost')
        origin = headers.get(b'origin', b'').decode()
        origin_host = (urlsplit(origin).hostname or '').lower() if origin else ''
        origin_ok = not origin or origin_host in LOOPBACK or origin_host.endswith('.localhost')
        browser_ok = headers.get(b'sec-fetch-site', b'').decode().lower() != 'cross-site'
        if allowed and origin_ok and browser_ok:
            await self.app(scope, receive, send)
            return
        await _refuse(scope, send, 'invalid Host header')

class WorkspaceHub:
    "ASGI host dispatcher for isolated workspace applications."
    def __init__(self, sites, port, default=None):
        self.sites = {s.slug: s for s in sites}
        self.port = int(port)
        self.default = default or next(iter(self.sites), '')
    def catalog(self):
        "Every workspace and the `*.localhost` URL that reaches it."
        return [{'id': s.slug, 'name': s.name, 'root': s.root,
                 'url': f'http://{s.slug}.localhost:{self.port}/'} for s in self.sites.values()]
    def site_for(self, scope):
        "The workspace a request's Host header names, or None."
        host = _host(_headers(scope))
        if host.endswith('.localhost'): return self.sites.get(host[:-10])
        if not host or host in LOOPBACK: return self.sites.get(self.default)
        return None
    async def __call__(self, scope, receive, send):
        # Lifespan carries no Host header, so it belongs to every workspace rather than to
        # whichever answers for bare loopback: one that never hears it never stops its kernels.
        if scope.get('type') == 'lifespan': return await self._lifespan(scope, receive, send)
        site = self.site_for(scope)
        if site is None: return await _refuse(scope, send, 'unknown workspace host')
        scope = dict(scope)
        scope['leela.workspace_id'] = site.slug
        await site.app(scope, receive, send)
    async def _lifespan(self, scope, receive, send):
        "One startup and one shutdown, fanned out to every site and answered once."
        async def spent(message): pass
        queues = [asyncio.Queue() for _ in self.sites]
        async def leg(app, q): await app(dict(scope), q.get, spent)
        legs = [asyncio.create_task(leg(s.app, q)) for s, q in zip(self.sites.values(), queues)]
        try:
            while True:
                message = await receive()
                for q in queues: q.put_nowait(message)
                if message['type'] == 'lifespan.startup':
                    await send({'type': 'lifespan.startup.complete'})
                elif message['type'] == 'lifespan.shutdown':
                    await asyncio.gather(*legs, return_exceptions=True)
                    return await send({'type': 'lifespan.shutdown.complete'})
        finally:
            for t in legs:
                if not t.done(): t.cancel()
