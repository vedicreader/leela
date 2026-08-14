"vpseasy's and cfeasy's own listings, with tokens resolved from dockeasy's store."

from __future__ import annotations

import os
from contextlib import contextmanager

from ...core.envs import EnvStore
from .packages import installed

__all__ = ['Infra', 'InfraError']


class InfraError(RuntimeError):
    pass


@contextmanager
def _with_env(values):
    "Tokens in `os.environ` for one call only: `Hetzner` reads `HCLOUD_TOKEN` at construction."
    old = {k: os.environ.get(k) for k in values}
    os.environ.update({k: v for k, v in values.items() if v})
    try: yield
    finally:
        for k, v in old.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v


def _record(r):
    "One DNS record as a panel shows it; `tunnel` marks a CNAME to `<id>.cfargotunnel.com`."
    content = str(r.get('content') or '')
    return {'id': r.get('id') or '', 'type': r.get('type') or '', 'name': r.get('name') or '',
            'content': content, 'proxied': bool(r.get('proxied')), 'ttl': r.get('ttl'),
            'tunnel': content.endswith('.cfargotunnel.com')}


class Infra:
    "Hetzner and Cloudflare, through vpseasy and cfeasy, with this project's tokens."

    HCLOUD, CF_TOKEN = 'HCLOUD_TOKEN', 'CLOUDFLARE_API_TOKEN'

    def __init__(self, env=None):
        self.env = env or EnvStore()

    def token(self, key):
        try: return self.env.get(key) or os.environ.get(key, '')
        except Exception: return os.environ.get(key, '')

    def status(self):
        return {'vpseasy': installed('vpseasy'), 'cfeasy': installed('cfeasy'),
                'hcloud_token': bool(self.token(self.HCLOUD)),
                'cf_token': bool(self.token(self.CF_TOKEN)),
                'keys': [self.HCLOUD, self.CF_TOKEN]}

    def _hetzner(self):
        try: from vpseasy.core import Hetzner
        except ImportError as e: raise InfraError('servers need vpseasy: pip install "leela[github]"') from e
        if not self.token(self.HCLOUD):
            raise InfraError('HCLOUD_TOKEN is not set — add it in Workflows → Environment')
        with _with_env({self.HCLOUD: self.token(self.HCLOUD)}): return Hetzner()

    def _cf(self):
        try: from cfeasy.core import CF
        except ImportError as e: raise InfraError('tunnels and DNS need cfeasy: pip install "leela[github]"') from e
        token = self.token(self.CF_TOKEN)
        if not token: raise InfraError('CLOUDFLARE_API_TOKEN is not set — add it in Workflows → Environment')
        return CF(token=token)

    def servers(self):
        "Every Hetzner server on this token, as vpseasy reports them."
        return list(self._hetzner().servers())

    def delete_server(self, name):
        "Delete one server, named. Irreversible, and the caller is expected to have asked."
        name = str(name or '').strip()
        if not name: raise InfraError('name the server to delete')
        known = {s['name'] for s in self.servers()}
        if name not in known: raise InfraError(f'no server called {name}')
        self._hetzner().delete(name)
        return {'deleted': name}

    def keys(self): return list(self._hetzner().keys())

    def tunnels(self):
        "Live Cloudflare tunnels, trimmed to what a panel can show."
        rows = [{'id': t.get('id') or '', 'name': t.get('name') or '',
                 'status': t.get('status') or '', 'created_at': str(t.get('created_at') or ''),
                 'deleted_at': str(t.get('deleted_at') or ''),
                 'connections': len(t.get('connections') or [])} for t in self._cf().tunnels()]
        return [r for r in rows if not r['deleted_at']]

    def delete_tunnel(self, tunnel_id):
        tunnel_id = str(tunnel_id or '').strip()
        if not tunnel_id: raise InfraError('name the tunnel to delete')
        self._cf().delete_tunnel(tunnel_id)
        return {'deleted': tunnel_id}

    def zones(self):
        return [{'id': z.get('id') or '', 'name': z.get('name') or '', 'status': z.get('status') or ''}
                for z in self._cf().zones()]

    def records(self, zone):
        "DNS records for one zone, named or by id."
        cf = self._cf()
        zone = str(zone or '').strip()
        if not zone: raise InfraError('choose a zone')
        zid = zone if len(zone) == 32 and '.' not in zone else cf.zone_id(zone)
        return sorted((_record(r) for r in cf.dns_records(zid)), key=lambda r: (r['name'], r['type']))

    def verify(self):
        "cfeasy's own token check, so a permissions problem is named before a deploy hits it."
        return self._cf().verify()

    def overview(self):
        "Everything at once as `{rows, error}` each, so Cloudflare being down cannot hide the servers."
        out = {'status': self.status()}
        for key, fn in (('servers', self.servers), ('tunnels', self.tunnels), ('zones', self.zones)):
            try: out[key] = {'rows': fn(), 'error': ''}
            except Exception as e:
                out[key] = {'rows': [], 'error': str(e) if isinstance(e, InfraError) else f'{type(e).__name__}: {e}'}
        return out
