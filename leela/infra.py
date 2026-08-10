"""The servers, tunnels and DNS a deploy actually landed on -- read from the source of truth.

A deploy panel that only shows the deploy is half a tool. The other half is the question you
ask *after* it: is the server up, is the tunnel the one this app uses, does the record point
where I think it does. Those live in Hetzner and Cloudflare, and vpseasy and cfeasy already
know how to ask -- `Hetzner().servers()`, `CF().tunnels()`, `CF().dns_records(zone)`. This
module is those calls with three things added and nothing else:

**Tokens come from dockeasy's store.** `Hetzner` reads `HCLOUD_TOKEN` from the environment
and `CF` takes one as an argument; both are resolved here through `leela.envs`, so a token
set once in the panel works for the deploy, for the CLI, and for these views.

**Nothing here is bulk.** Every listing is a read; the only mutations are deleting one
tunnel and deleting one server, each named explicitly by the caller. A "delete all the
things that look unused" button is exactly the button nobody should have.

**A missing package or token is an answer.** `status` says which of the four pieces is
absent, so the panel shows a sentence to act on instead of an empty list that could mean
either "nothing there" or "nothing asked".
"""

from __future__ import annotations

import os
from contextlib import contextmanager

from .envs import EnvStore

__all__ = ['Infra', 'InfraError']


class InfraError(RuntimeError):
    pass


@contextmanager
def _with_env(values):
    """Put resolved tokens into the environment for the duration of one call.

    vpseasy reads `HCLOUD_TOKEN` from `os.environ` at construction. Rather than reaching
    into it or asking people to export things before starting Leela, the value from
    dockeasy's store is placed there for exactly as long as the call takes and removed
    afterwards -- a token that outlives the call it was for is a token in a process dump.
    """
    old = {k: os.environ.get(k) for k in values}
    os.environ.update({k: v for k, v in values.items() if v})
    try: yield
    finally:
        for k, v in old.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v


class Infra:
    "Hetzner and Cloudflare, through vpseasy and cfeasy, with this project's tokens."

    HCLOUD, CF_TOKEN = 'HCLOUD_TOKEN', 'CLOUDFLARE_API_TOKEN'

    def __init__(self, env=None):
        self.env = env or EnvStore()

    # -- what is available -----------------------------------------------------
    def token(self, key):
        try: return self.env.get(key) or os.environ.get(key, '')
        except Exception: return os.environ.get(key, '')

    def status(self):
        from importlib.util import find_spec
        def installed(name):
            try: return find_spec(name) is not None
            except (ImportError, ValueError): return False
        return {'vpseasy': installed('vpseasy'), 'cfeasy': installed('cfeasy'),
                'hcloud_token': bool(self.token(self.HCLOUD)),
                'cf_token': bool(self.token(self.CF_TOKEN)),
                'keys': [self.HCLOUD, self.CF_TOKEN]}

    def _hetzner(self):
        try:
            from vpseasy.core import Hetzner
        except ImportError as e:
            raise InfraError('servers need vpseasy: pip install "leela[github]"') from e
        if not self.token(self.HCLOUD):
            raise InfraError('HCLOUD_TOKEN is not set — add it in Workflows → Environment')
        with _with_env({self.HCLOUD: self.token(self.HCLOUD)}):
            return Hetzner()

    def _cf(self):
        try:
            from cfeasy.core import CF
        except ImportError as e:
            raise InfraError('tunnels and DNS need cfeasy: pip install "leela[github]"') from e
        token = self.token(self.CF_TOKEN)
        if not token:
            raise InfraError('CLOUDFLARE_API_TOKEN is not set — add it in Workflows → Environment')
        return CF(token=token)

    # -- servers ---------------------------------------------------------------
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

    def keys(self):
        return list(self._hetzner().keys())

    # -- tunnels and DNS -------------------------------------------------------
    def tunnels(self):
        "Cloudflare tunnels, trimmed to what a panel can show without a horizontal scrollbar."
        rows = []
        for t in self._cf().tunnels():
            rows.append({'id': t.get('id') or '', 'name': t.get('name') or '',
                         'status': t.get('status') or '', 'created_at': str(t.get('created_at') or ''),
                         'deleted_at': str(t.get('deleted_at') or ''),
                         'connections': len(t.get('connections') or [])})
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
        """DNS records for one zone, by name or id.

        A tunnel's hostname is a proxied CNAME to `<id>.cfargotunnel.com`, so `tunnel` marks
        the records that belong to a tunnel -- which is the one thing you are looking for
        when a deploy answers on the wrong host.
        """
        cf = self._cf()
        zone = str(zone or '').strip()
        if not zone: raise InfraError('choose a zone')
        zid = zone if len(zone) == 32 and '.' not in zone else cf.zone_id(zone)
        rows = []
        for r in cf.dns_records(zid):
            content = str(r.get('content') or '')
            rows.append({'id': r.get('id') or '', 'type': r.get('type') or '',
                         'name': r.get('name') or '', 'content': content,
                         'proxied': bool(r.get('proxied')), 'ttl': r.get('ttl'),
                         'tunnel': content.endswith('.cfargotunnel.com')})
        return sorted(rows, key=lambda r: (r['name'], r['type']))

    def verify(self):
        "cfeasy's own token check, so a permissions problem is named before a deploy hits it."
        return self._cf().verify()

    def overview(self):
        """Everything at once, with each half's failure kept to that half.

        The panel opens on this. Cloudflare being unreachable must not hide the servers, so
        the two are reported as `{rows, error}` rather than as one call that either works or
        does not.
        """
        out = {'status': self.status()}
        for key, fn in (('servers', self.servers), ('tunnels', self.tunnels), ('zones', self.zones)):
            try: out[key] = {'rows': fn(), 'error': ''}
            except Exception as e:
                out[key] = {'rows': [], 'error': str(e) if isinstance(e, InfraError) else f'{type(e).__name__}: {e}'}
        return out
