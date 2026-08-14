"""The deploy taken apart: one library call per step, each with its own output.

Steps run in a subprocess on a pty: `hetzner_deploy` shells out to ssh and rsync, whose
output goes to a file descriptor `redirect_stdout` cannot catch. Values flow between steps
through dockeasy's store (`env_set`/`env_get`), as they do inside `deploy.py`.
"""

from __future__ import annotations

import json, sys
from dataclasses import dataclass, field
from pathlib import Path

from ...core.envs import EnvStore
from ..pipelines.pipelines import Pipeline, PipelineError, Step, env_value

__all__ = ['Drive', 'DriveError', 'Part', 'PARTS', 'DRIVE_FILE', 'context', 'parts']

DRIVE_FILE = '.leela/drive.json'
DriveError = PipelineError


@dataclass
class Part:
    "One library call, as a step you can run on its own."
    id: str
    package: str
    label: str
    doc: str
    code: str
    needs: list = field(default_factory=list)
    writes: list = field(default_factory=list)
    produces: list = field(default_factory=list)


PARTS = [
    Part('image', 'dockeasy', 'Dockerfile',
         'detect_app reads the project and returns the image it would build. Written here so '
         'the compose stack and the workflow build the same thing.',
         "from dockeasy import detect_app\n"
         "df = detect_app({root!r}, pkgs={pkgs!r}, vols={vols!r})\n"
         "open({root!r} + '/Dockerfile', 'w').write(str(df) + '\\n')\n"
         "print(df)",
         produces=['Dockerfile']),
    Part('stack', 'vpseasy', 'compose stack',
         'caddy_stack wraps that image in Caddy and cloudflared, and writes docker-compose.yml '
         'and the Caddyfile beside it.',
         "from dockeasy import detect_app\n"
         "from vpseasy import caddy_stack\n"
         "df = detect_app({root!r}, pkgs={pkgs!r}, vols={vols!r})\n"
         "c = caddy_stack({host!r}, df, vols={vols!r}, root={root!r})\n"
         "print(c)",
         produces=['docker-compose.yml', 'Caddyfile', 'Dockerfile']),
    Part('tunnel', 'cfeasy', 'Cloudflare tunnel',
         'setup_tunnel reuses the tunnel of this name or creates it, points the hostname at it, '
         'and returns the token the container runs cloudflared with.',
         "from cfeasy import CF\n"
         "from dockeasy import env_get, env_set\n"
         "cf = CF(token=env_get('CLOUDFLARE_API_TOKEN'))\n"
         "tid, tok = cf.setup_tunnel({domain!r}, {subdomain!r} or None, tunnel_name={tunnel!r})\n"
         "env_set('CF_TUNNEL_TOKEN', tok)\n"
         "print('tunnel', tid, 'for', {host!r})",
         needs=['CLOUDFLARE_API_TOKEN'], writes=['CF_TUNNEL_TOKEN']),
    Part('dns', 'cfeasy', 'extra hostname',
         'A second hostname on the same tunnel and the same container. Skipped unless '
         'SECOND_HOST is set; Caddy tells the two apart by the Host header.',
         "from cfeasy import CF\n"
         "from dockeasy import env_get\n"
         "host = env_get('SECOND_HOST', default='')\n"
         "if not host: raise SystemExit('SECOND_HOST is not set — nothing to point')\n"
         "cf = CF(token=env_get('CLOUDFLARE_API_TOKEN'))\n"
         "tid = cf.tunnel_id({tunnel!r})\n"
         "print(cf.tunnel_cname(host, host, tid))",
         needs=['CLOUDFLARE_API_TOKEN']),
    Part('server', 'vpseasy', 'server and rsync',
         'hetzner_deploy provisions the VPS if it is missing, waits for cloud-init, rsyncs the '
         'directory and brings the stack up. Idempotent: run it again after a fix.',
         "from dockeasy import env_get, env_set\n"
         "from vpseasy import hetzner_deploy\n"
         "r = hetzner_deploy(env_get('SERVER_NAME', default={app!r}), {root!r},\n"
         "                   include={inc!r}, exclude={exc!r}, path='/srv/app',\n"
         "                   user=env_get('SERVER_USER', default='deploy'))\n"
         "env_set('HETZNER_IP', r.ip)\n"
         "print('deployed', r.name, 'at', r.ip)",
         needs=['HCLOUD_TOKEN'], writes=['HETZNER_IP']),
    Part('secrets', 'gheasy', 'push secrets',
         'gh_push_env sends every key the schema declares to GitHub, as a secret or a variable '
         'depending on how it is declared, so the workflow can run this same deploy.',
         "from gheasy import gh_push_env\n"
         "from dockeasy import env_get\n"
         "keys = {keys!r}\n"
         "vals = {{k: v for k in keys if (v := env_get(k, default=''))}}\n"
         "print('pushing', len(vals), 'of', len(keys), 'declared keys')\n"
         "gh_push_env(vals, path={root!r})",
         needs=['GITHUB_TOKEN']),
]


def context(root, env=None):
    "The values every snippet is rendered with, resolved once."
    root = Path(root).expanduser().resolve()
    store = env or EnvStore()
    def value(key, default=''): return env_value(store, key, default)
    app, schema = '', {}
    try:
        from gheasy.core import GheasyConfig
        cfg = GheasyConfig.load(str(root))
        app, schema = cfg.app, dict(cfg.env_schema or {})
    except Exception: pass
    if not app:
        try:
            import tomllib
            with open(root/'pyproject.toml', 'rb') as f:
                app = str(((tomllib.load(f).get('project') or {}).get('name') or '')).strip()
        except (OSError, ValueError, ImportError): pass
    app = app or root.name
    host = value('DOMAIN')
    domain, subdomain = host, ''
    if host.count('.') > 1:
        subdomain, _, domain = host.partition('.')
    return {'root': str(root), 'app': app, 'host': host or root.name, 'domain': domain,
            'subdomain': subdomain, 'tunnel': f'{subdomain or app}_{domain}' if domain else app,
            'port': value('PORT', '5001'), 'keys': sorted(schema) or ['DOMAIN'],
            'pkgs': ['curl'], 'vols': ['/app/data'],
            'inc': [f'{app}/', 'pyproject.toml', 'uv.lock', 'main.py', 'Dockerfile',
                    'docker-compose.yml', 'Caddyfile', '.env'],
            'exc': ['data/', '.git/', '.venv/', '__pycache__/']}


def _step(part, exe, ctx):
    "One part as a `Step`, its snippet rendered with this project's values."
    code = part.code.format(**ctx)
    return Step(id=part.id, label=f'{part.package} · {part.label}', doc=part.doc,
                cmd=f'python -c … {part.package}', argv=[exe, '-c', code], needs=list(part.needs),
                meta={'package': part.package, 'code': code, 'writes': list(part.writes),
                      'produces': list(part.produces), 'title': part.label})


def parts(root, env=None, python=''):
    "Every part as a runnable step, with this project's values already in the snippet."
    ctx = context(root, env)
    return [_step(p, str(python or sys.executable), ctx) for p in PARTS]


class Drive(Pipeline):
    "The deploy, driven a library at a time."

    FILE = DRIVE_FILE
    KIND = 'drive'

    def __init__(self, root, python=None, env=None):
        super().__init__(root, python=python, env=env)
        self._rendered = ''

    @staticmethod
    def defaults(root): return parts(root)

    def refresh(self):
        "Re-render the snippets against the current values."
        if self.path.exists(): return self.steps          # an edited plan is the user's
        key = json.dumps(context(self.root, self.env), sort_keys=True)
        if key != self._rendered:
            self.steps = parts(self.root, self.env, self.python or '')
            self._rendered = key
        return self.steps

    def state(self):
        self.refresh()
        ctx = context(self.root, self.env)
        return super().state() | {'context': ctx, 'packages': sorted({p.package for p in PARTS})}
