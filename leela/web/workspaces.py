"""Independent web workspaces behind one Leela server.

Workspace identity is carried by the ``*.localhost`` host name.  That keeps every existing
absolute IDE route valid while giving each project a separate FastHTML application,
``Workspace`` object, document store, agent, terminals, and kernel pool.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit
from dataclasses import dataclass
from pathlib import Path

__all__ = ['WorkspaceSite', 'WorkspaceHub', 'LoopbackHostGuard', 'workspace_slug']


def workspace_slug(value, used=()):
    base = re.sub(r'[^a-z0-9]+', '-', str(value).lower()).strip('-') or 'workspace'
    slug, n, used = base, 2, set(used)
    while slug in used:
        slug, n = f'{base}-{n}', n + 1
    return slug


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
        headers = {k.lower(): v for k, v in (scope.get('headers') or ())}
        raw = headers.get(b'host', b'').decode().lower()
        host = raw[1:].split(']', 1)[0] if raw.startswith('[') else raw.split(':', 1)[0]
        allowed = host in ('127.0.0.1', 'localhost', '::1', '') or host.endswith('.localhost')
        origin = headers.get(b'origin', b'').decode()
        origin_host = (urlsplit(origin).hostname or '').lower() if origin else ''
        origin_ok = not origin or origin_host in ('127.0.0.1', 'localhost', '::1') or origin_host.endswith('.localhost')
        fetch_site = headers.get(b'sec-fetch-site', b'').decode().lower()
        browser_ok = fetch_site != 'cross-site'
        if allowed and origin_ok and browser_ok:
            await self.app(scope, receive, send)
            return
        if scope.get('type') == 'websocket':
            await send({'type': 'websocket.close', 'code': 1008, 'reason': 'invalid Host header'})
            return
        await send({'type': 'http.response.start', 'status': 421,
                    'headers': [(b'content-type', b'text/plain; charset=utf-8')]})
        await send({'type': 'http.response.body', 'body': b'invalid Host header'})


class WorkspaceHub:
    "ASGI host dispatcher for isolated workspace applications."

    def __init__(self, sites, port, default=None):
        self.sites = {s.slug: s for s in sites}
        self.port = int(port)
        self.default = default or next(iter(self.sites), '')

    def catalog(self):
        return [{'id': s.slug, 'name': s.name, 'root': s.root,
                 'url': f'http://{s.slug}.localhost:{self.port}/'} for s in self.sites.values()]

    def site_for(self, scope):
        raw = dict(scope.get('headers') or ()).get(b'host', b'').decode().lower()
        host = raw[1:].split(']', 1)[0] if raw.startswith('[') else raw.split(':', 1)[0]
        if host.endswith('.localhost'):
            return self.sites.get(host[:-10])
        # The bare loopback host is used by the startup health probe and is the only
        # intentional route to the default workspace. Unknown Host headers must not
        # silently cross the workspace boundary.
        if host in ('127.0.0.1', 'localhost', '::1', ''):
            return self.sites.get(self.default)
        return None

    async def __call__(self, scope, receive, send):
        site = self.site_for(scope)
        if site is None:
            if scope.get('type') == 'websocket':
                await send({'type': 'websocket.close', 'code': 1008, 'reason': 'unknown workspace host'})
                return
            await send({'type': 'http.response.start', 'status': 421,
                        'headers': [(b'content-type', b'text/plain; charset=utf-8')]})
            await send({'type': 'http.response.body', 'body': b'unknown workspace host'})
            return
        scope = dict(scope)
        scope['leela.workspace_id'] = site.slug
        await site.app(scope, receive, send)
