"Independent web workspaces behind one Leela server."

from __future__ import annotations

import re
from urllib.parse import urlsplit
from dataclasses import dataclass
from pathlib import Path

__all__ = ['WorkspaceSite', 'WorkspaceHub', 'LoopbackHostGuard', 'workspace_slug']

LOOPBACK = ('127.0.0.1', 'localhost', '::1')

def workspace_slug(value, used=()):
    "A URL-safe slug for `value`, suffixed until it is not already in `used`."
    base = re.sub(r'[^a-z0-9]+', '-', str(value).lower()).strip('-') or 'workspace'
    slug, n, used = base, 2, set(used)
    while slug in used:
        slug, n = f'{base}-{n}', n + 1
    return slug

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
        site = self.site_for(scope)
        if site is None: return await _refuse(scope, send, 'unknown workspace host')
        scope = dict(scope)
        scope['leela.workspace_id'] = site.slug
        await site.app(scope, receive, send)
