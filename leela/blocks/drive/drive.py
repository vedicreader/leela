"""The deploy taken apart: one library call per step, each with its own output.

`leela.deploys` runs the project's `deploy.py`, which is the right thing when the deploy
works -- it is the file CI runs, so what you see is what ships. It is the wrong thing when
the deploy *does not* work, because five library calls share one exit code and one stream of
output, and "it failed somewhere in deploy" is where the afternoon goes.

So this is the same deploy with the seams left in. dockeasy writes the Dockerfile; vpseasy
writes the compose stack; cfeasy opens the tunnel; vpseasy provisions and rsyncs; gheasy
pushes the secrets. Five steps, five exit codes, five transcripts, each runnable on its own
and re-runnable after a fix. Nothing is sequenced implicitly -- `Pipeline` will run them in
order if asked, and the panel's normal move is to run one.

Two decisions make it a diagnostic rather than a second deploy system.

**Each step is a snippet, and the snippet is on screen.** The panel shows the exact call it
is about to make, with this project's values already substituted --
`CF(token=...).setup_tunnel('sankalpa.sh', 'lego', tunnel_name='lego_sankalpa.sh')`. That is
the difference between a button and an explanation, and it is also the line you paste into a
REPL when you want to poke at it yourself.

**They run in a subprocess, on a pty, like every other pipeline.** In-process calls would be
shorter to write and would lose exactly what matters: `hetzner_deploy` shells out to ssh and
rsync, and their output goes to a file descriptor no `redirect_stdout` can catch. A pty gets
the progress, the prompts and the colour -- and a traceback that `leela.packages` can then
attribute to whichever of your packages raised.

Values flow through dockeasy's store, not through this module: a step that produces
`CF_TUNNEL_TOKEN` writes it with `env_set`, and the next step reads it with `env_get`, which
is what the same steps do inside `deploy.py`.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ...core.envs import EnvStore
from ..pipelines.pipelines import Pipeline, PipelineError, Step

__all__ = ['Drive', 'DriveError', 'Part', 'PARTS', 'DRIVE_FILE', 'context', 'parts']

DRIVE_FILE = '.leela/drive.json'
DriveError = PipelineError


@dataclass
class Part:
    """One library call, as a step you can run on its own.

    `code` is a template rendered with the project's context, so what runs and what the panel
    shows are the same string. `writes` is what the call leaves in dockeasy's store for the
    next one -- the panel draws the arrow between two steps from it rather than from an order
    someone wrote down.
    """
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
    """The values every snippet is rendered with, resolved once.

    Read from the same two places the deploy reads: gheasy's config for the app name and the
    schema, dockeasy's store for the host and the rest. Nothing is invented here -- an
    unset `DOMAIN` renders as an empty string and the step says so when it runs, rather than
    being quietly replaced by a guess.
    """
    root = Path(root).expanduser().resolve()
    store = env or EnvStore()
    def value(key, default=''):
        try: return store.get(key, secret=False) or default
        except Exception: return default
    # gheasy's config is the declared answer; `[project] name` is the one every Python
    # project already has, which is what gheasy itself bootstraps from. The directory name
    # is the last resort and is right often enough to be worth having.
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


def parts(root, env=None, python=''):
    "Every part as a runnable step, with this project's values already in the snippet."
    ctx = context(root, env)
    exe = str(python or sys.executable)
    out = []
    for part in PARTS:
        code = part.code.format(**ctx)
        out.append(Step(
            id=part.id, label=f'{part.package} · {part.label}', doc=part.doc,
            cmd=f'python -c … {part.package}', argv=[exe, '-c', code], needs=list(part.needs),
            meta={'package': part.package, 'code': code, 'writes': list(part.writes),
                  'produces': list(part.produces), 'title': part.label}))
    return out


class Drive(Pipeline):
    """The deploy, driven a library at a time.

    Deliberately the same `Pipeline` the script-driven deploy uses: same pty, same transcript,
    same halting rules, same package attribution on a failure. The only difference is what a
    step *is*, which is the thing being compared.
    """

    FILE = DRIVE_FILE
    KIND = 'drive'

    def __init__(self, root, python=None, env=None):
        super().__init__(root, python=python, env=env)
        self._rendered = ''

    @staticmethod
    def defaults(root): return parts(root)

    def refresh(self):
        """Re-render the snippets against the current values.

        The store changes while the panel is open -- setting `DOMAIN` is often the fix for
        the step that just failed -- and a snippet showing the old value would be a lie about
        what the next run does.
        """
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
