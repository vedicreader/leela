#!/usr/bin/env python3
"The environment lock of the thin Mac app: make, check, test, diff, publish, promote, verify, and its signing keys. See docs/thin-app.md."
import argparse, hashlib, json, os, re, shutil, socket, subprocess, sys, tempfile, threading, time, tomllib, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT/'packaging'
LOCK = PKG/'lock'
CHILDENV = PKG/'childenv.json'
FILES = ('pyproject.toml', 'uv.lock', '.python-version')
REPO = 'vedicreader/leela'
DL = f'https://github.com/{REPO}/releases/download'
NS = 'leela-lock'
PYTHON = '3.13.18'   # the old app's minor: a kernel on a project's 3.13 borrows Leela's packages only when the minors match
MINOR, CP = PYTHON.rsplit('.', 1)[0], 'cp' + ''.join(PYTHON.split('.')[:2])
PLATFORM, MACOS_MIN, LAUNCHER_API = 'darwin-arm64', '14.0', 1
COOLDOWN, RECORD_DAYS = 7, 7
MARKER = "sys_platform == 'darwin' and platform_machine == 'arm64'"
PYPI = 'https://pypi.org/simple'
LLAMA = dict(name='llama-cpp-python', version='0.3.30', sha256='4f5b385f31dbda502d7118aff0c07c9e98961fa0402c025b89ff3250db843eb3',
             url=f'https://github.com/abetlen/llama-cpp-python/releases/download/v0.3.30-metal/llama_cpp_python-0.3.30-py3-none-macosx_11_0_arm64.whl')
#: Packages with no wheel that may still be locked; none, since llama-cpp-python comes from its pinned wheel.
SOURCE_ONLY = set()
EXTRAS = ('mlx', 'llama', 'langserver')
KEYS = ('leela_lock_ed25519', 'leela_lock_emergency_ed25519')

def sh(*cmd, check=True, **kw):
    "Run `cmd`; its stdout, stripped."
    p = subprocess.run([str(c) for c in cmd], text=True, capture_output=True, **kw)
    if check and p.returncode: raise SystemExit(f"{Path(str(cmd[0])).name} {' '.join(map(str, cmd[1:3]))} failed: {(p.stderr or p.stdout).strip()[-2000:]}")
    return p.stdout.strip()

def sha256(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def now(): return datetime.now(timezone.utc)
def iso(t): return t.strftime('%Y-%m-%dT%H:%M:%SZ')
def pinned_version(): return (PKG/'uv.version').read_text().strip()

def uv_version(uv): return sh(uv, '--version').split()[1]

def pinned_uv():
    "The uv the app ships, refused when it is not the pinned version."
    uv = Path(os.environ.get('LEELA_UV') or PKG/'mac'/'build'/'uv'/'uv')
    if not uv.is_file(): raise SystemExit(f'no uv at {uv}; run make -C packaging/mac uv-fetch')
    if (v := uv_version(uv)) != pinned_version(): raise SystemExit(f'{uv} is uv {v}, not the pinned {pinned_version()}')
    return uv

def lock_hash(d, uv):
    "sha256 over the names and contents of the lock files, then the uv version. The launcher computes the same."
    h = hashlib.sha256()
    for f in FILES: h.update(f.encode()); h.update((Path(d)/f).read_bytes())
    h.update(b'uv'); h.update(uv.encode())
    return h.hexdigest()

def spec(): return json.loads(CHILDENV.read_text())

def _kept(s, base):
    base = dict(os.environ if base is None else base)
    return {k: v for k, v in base.items() if k not in s['drop'] and not k.startswith(tuple(s['drop_prefixes']))}

def child_env(base=None, **vals):
    "The environment uv gets from the app, from childenv.json: dropped keys, uv settings, `vals` filled in."
    s = spec()
    return s['set'] | _kept(s, base) | {k: v.format(**vals) for k, v in s['uv'].items()}

def server_env(base=None):
    "The server's environment, as the launcher's `serverEnv`: the person's, minus the dropped keys, with the tool folders on PATH and the server keys."
    s = spec()
    e = _kept(s, base)
    path = [os.path.expanduser(d) for d in s['tool_dirs']] + e.get('PATH', '').split(os.pathsep)
    return e | s['server'] | dict(PATH=os.pathsep.join(dict.fromkeys(filter(None, path))))

def server_env_1_0(env, base=None, **vals):
    "The server's environment from app 1.0.0, which gave it uv's build settings, VIRTUAL_ENV and the env's bin first; a newer lock still runs under it."
    e = server_env(base)
    return e | child_env(base, env=env, **vals) | dict(PYTHONNOUSERSITE='1', VIRTUAL_ENV=str(env), PATH=os.pathsep.join([f'{env}/bin', e['PATH']]))

def sync_args(lock, extras=(), inexact=False):
    "The build command; `inexact` adds an extra to an env without removing what it has."
    s = spec()
    return [a.format(lock=lock) for a in s['sync']] + (s['inexact'] if inexact else []) + [a.format(name=x) for x in extras for a in s['extra']]

def owners():
    "The packages the owner publishes, from the metadata installed here; they skip the cooldown."
    import importlib.metadata as md
    by = lambda d: ((d.metadata.get('Author-email') or '') + (d.metadata.get('Author') or '')).lower()
    return sorted({d.metadata['Name'].lower() for d in md.distributions() if 'karthik' in by(d)} - {'leela'})

def extra_reqs():
    "Each extra's requirements, as Leela's setup panel names them."
    sys.path.insert(0, str(ROOT))
    from leela.blocks.agent.models import TOOLS, runtime_requirements
    return {'mlx': runtime_requirements('mlx'), 'llama': runtime_requirements('llama'), 'langserver': list(TOOLS['langserver'][1])}

def constraints(): return tomllib.loads((ROOT/'pyproject.toml').read_text()).get('tool', {}).get('uv', {}).get('constraint-dependencies', [])

def pyproject(v, leela, extras, owned=(), at=None, pins=()):
    "The pinned project's pyproject.toml. `leela` is a wheel URL, or a local wheel path for a lock that cannot be published."
    at = at or now()
    q = lambda xs: '[' + ', '.join(json.dumps(x) for x in xs) + ']'
    src = f'{{ url = {json.dumps(leela)} }}' if '://' in leela else f'{{ path = {json.dumps(str(leela))} }}'
    pkgs = ', '.join(f'{json.dumps(o)} = {json.dumps(iso(at))}' for o in owned)
    return f'''[project]
name = "leela-lock"
version = "0"
requires-python = "=={MINOR}.*"
dependencies = ["leela=={v}"]

[project.optional-dependencies]
{chr(10).join(f'{k} = {q(extras[k])}' for k in EXTRAS)}

[tool.uv]
package = false
environments = ["{MARKER}"]
required-environments = ["{MARKER}"]
exclude-newer = "{iso(at - timedelta(days=COOLDOWN))}"
exclude-newer-package = {{ {pkgs} }}
constraint-dependencies = {q([*constraints(), *pins])}

[tool.uv.sources]
leela = {src}
llama-cpp-python = {{ url = "{LLAMA['url']}" }}
'''

def release_wheel(v, wait=600, every=20):
    "The URL and sha256 of the Leela wheel on GitHub release `v`, waited for up to `wait` seconds."
    name, end = f'leela-{v}-py3-none-any.whl', time.monotonic() + wait
    while True:
        try:
            r = json.loads(urllib.request.urlopen(f'https://api.github.com/repos/{REPO}/releases/tags/{v}', timeout=10).read())
            if a := next((a for a in r.get('assets', []) if a['name'] == name and a.get('digest')), None):
                return a['browser_download_url'], a['digest'].removeprefix('sha256:')
        except Exception: pass
        if time.monotonic() > end: raise SystemExit(f'no {name} on release {v}; run make lock-wheel V={v} first')
        print(f'waiting for {name} on release {v}'); time.sleep(every)

def packages(d): return tomllib.loads((Path(d)/'uv.lock').read_text()).get('package', [])

def _closure(pkgs, roots):
    by, seen, todo = {p['name']: p for p in pkgs}, set(), list(roots)
    while todo:
        if (n := todo.pop()) in seen or n not in by: continue
        seen.add(n)
        p = by[n]
        todo += [x['name'] for x in p.get('dependencies', [])]
        for x in p.get('dependencies', []): todo += [y['name'] for e in x.get('extra', []) for y in p.get('optional-dependencies', {}).get(e, [])]
    return seen

def _wname(w): return w.get('filename') or (w.get('url') or w.get('path') or '').rsplit('/', 1)[-1]

def wheel_fits(fn):
    "Whether a wheel filename installs on the pinned CPython, macOS arm64."
    if fn.count('-') < 4: return False
    py, abi, plat = fn[:-4].split('-')[-3:]
    abis = set(abi.split('.'))
    pyok = lambda p: p in (CP, 'py3', 'py' + CP[2:]) or ('abi3' in abis and re.fullmatch(r'cp3\d+', p) and int(p[3:]) <= int(CP[3:]))
    return (any(map(pyok, py.split('.'))) and bool(abis & {CP, 'abi3', 'none'})
            and any(p == 'any' or (p.startswith('macosx') and p.endswith(('arm64', 'universal2'))) for p in plat.split('.')))

def check(d, local=False):
    "Refuse a lock the app cannot install: another index, editable or git sources, no fitting wheel, llama outside its extra, no required environment."
    pkgs, why = packages(d), []
    proj = tomllib.loads((Path(d)/'pyproject.toml').read_text())
    if proj.get('tool', {}).get('uv', {}).get('required-environments') != [MARKER]: why.append(f'required-environments is not [{MARKER}]')
    if not tomllib.loads((Path(d)/'uv.lock').read_text()).get('options', {}).get('exclude-newer'): why.append('the lock records no exclude-newer cooldown')
    root = next((p for p in pkgs if p['name'] == 'leela-lock'), None)
    if root is None: return why + ['the lock has no leela-lock project']
    if missing := [x for x in EXTRAS if x not in root.get('optional-dependencies', {})]: why.append(f'extras missing: {missing}')
    for p in pkgs:
        n, src = p['name'], p.get('source', {})
        if n == 'leela-lock': continue
        if (k := next(iter(src), None)) in ('editable', 'directory', 'git', 'virtual'): why.append(f'{n} comes from a {k} source')
        elif k == 'path' and not (n == 'leela' and local): why.append(f'{n} comes from a local path')
        elif k == 'url' and n == LLAMA['name']:
            if src['url'] != LLAMA['url'] or not any(w.get('hash') == f"sha256:{LLAMA['sha256']}" for w in p.get('wheels', [])):
                why.append(f"{n} is not the pinned wheel {LLAMA['url']}")
        elif k == 'url' and n == 'leela':
            if not src['url'].startswith(f'{DL}/'): why.append(f"leela comes from {src['url']}, not a release of {REPO}")
        elif k == 'url': why.append(f'{n} comes from a URL')
        elif k == 'registry' and src['registry'].rstrip('/') != PYPI: why.append(f"{n} comes from {src['registry']}")
        wheels = [w for w in p.get('wheels', []) if wheel_fits(_wname(w))]
        if not wheels and n not in SOURCE_ONLY: why.append(f'{n} {p.get("version")} has no wheel for CPython {MINOR} on macOS arm64')
    base = _closure(pkgs, [x['name'] for x in root.get('dependencies', [])])
    if LLAMA['name'] in base: why.append(f"{LLAMA['name']} is in the base environment; it belongs in the llama extra only")
    return why

def _pin_extras(text, d):
    "The extras with every requirement pinned `==` to the version the lock chose."
    ver = {p['name']: p['version'] for p in packages(d)}
    def pin(r):
        name = re.split(r'[\[<>=!~; ]', r, maxsplit=1)[0]
        extra = re.match(r'[^\[]*(\[[^\]]*\])', r)
        mark = r.split(';', 1)[1] if ';' in r else ''
        key = name.lower().replace('_', '-')
        return f"{name}{extra.group(1) if extra else ''}=={ver[key]}" + (f'; {mark.strip()}' if mark else '') if key in ver else r
    out = []
    for line in text.splitlines():
        if (m := re.match(r'^(mlx|llama|langserver) = (\[.*\])$', line)): line = f'{m[1]} = ' + json.dumps([pin(r) for r in json.loads(m[2])])
        out.append(line)
    return '\n'.join(out) + '\n'

def cooldown_args(d):
    "The pinned project's cooldown as uv flags, which UV_NO_CONFIG does not drop."
    u = tomllib.loads((Path(d)/'pyproject.toml').read_text())['tool']['uv']
    return ['--exclude-newer', u['exclude-newer'], *[a for k, v in u.get('exclude-newer-package', {}).items() for a in ('--exclude-newer-package', f'{k}={v}')]]

def make(v, out=LOCK, wheel=None, owned=None, pins=()):
    "Write the pinned project for Leela `v`, lock it with the pinned uv, pin the extras, check it, and print its hash."
    uv, out = pinned_uv(), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    leela = str(Path(wheel).resolve()) if wheel else None
    if leela is None:
        leela, digest = release_wheel(v)
    (out/'.python-version').write_text(PYTHON + '\n')
    text = pyproject(v, leela, extra_reqs(), owners() if owned is None else owned, pins=pins)
    (out/'pyproject.toml').write_text(text)
    cache = Path(os.environ.get('UV_CACHE_DIR') or Path.home()/'Library'/'Caches'/'Leela'/'uv')
    env = child_env(cache=cache, python=cache.parent/'python-lock', python_version=PYTHON, env=cache.parent/'lock-venv')
    env.pop('UV_FROZEN', None)
    # UV_NO_CONFIG keeps a person's uv.toml out, and with it the settings in [tool.uv]: the cooldown goes on the command line
    run = lambda: subprocess.run([uv, 'lock', '--project', out, *cooldown_args(out)], env=env, check=True)
    run()
    (out/'pyproject.toml').write_text(_pin_extras(text, out))
    run()
    if not wheel and not any(w.get('hash') == f'sha256:{digest}' for p in packages(out) if p['name'] == 'leela' for w in p.get('wheels', [])):
        raise SystemExit(f'the locked leela wheel does not match the sha256 GitHub gives: {digest}')
    if why := check(out, local=bool(wheel)): raise SystemExit('the lock is refused:\n  ' + '\n  '.join(why))
    h = lock_hash(out, uv_version(uv))
    print(f'lock hash {h}' + ('  (local wheel: test only, cannot be published)' if wheel else ''))
    return h

def download_bytes(d):
    "What a first install downloads: one fitting wheel per package of the base env, no extras."
    pkgs, tot = packages(d), 0
    root = next((p for p in pkgs if p['name'] == 'leela-lock'), {})
    base = _closure(pkgs, [x['name'] for x in root.get('dependencies', [])])
    for p in pkgs:
        if p['name'] not in base: continue
        ws = [w for w in p.get('wheels', []) if wheel_fits(_wname(w))]
        tot += max((w.get('size') or 0 for w in ws), default=0)
    return tot

def leela_version(d): return next((p['version'] for p in packages(d) if p['name'] == 'leela'), None)

def manifest(d, n, uv):
    "The manifest the app checks before it installs lock `n`."
    return dict(n=n, hash=lock_hash(d, uv), files={f: sha256(Path(d)/f) for f in FILES}, leela=leela_version(d), python=PYTHON,
                uv_min=uv, launcher_api_min=LAUNCHER_API, platform=PLATFORM, macos_min=MACOS_MIN, download_bytes=download_bytes(d))

def dumps(o): return json.dumps(o, indent=1, sort_keys=True) + '\n'

# Smoke test: what the app's build does, then the server on a temp folder
_SMOKE_KERNEL = '''
import sys
from jupyter_client.manager import start_new_kernel
km, kc = start_new_kernel(kernel_name='python3')
try:
    mid, got = kc.execute('1+1'), None
    while got is None:
        m = kc.get_iopub_msg(timeout=60)
        if m['parent_header'].get('msg_id') == mid and m['msg_type'] == 'execute_result': got = m['content']['data']['text/plain']
    print(got)
finally: kc.stop_channels(); km.shutdown_kernel(now=True)
'''
_EXTRA_CHECK = {'mlx': ['-c', 'import mlx_lm'], 'llama': ['-c', 'import llama_cpp'],
                'langserver': ['-c', 'import os, sys, sysconfig; sys.exit(0 if os.access(os.path.join(sysconfig.get_path("scripts"), "basedpyright-langserver"), os.X_OK) else 1)']}

def test_code_hash(): return hashlib.sha256(Path(__file__).read_bytes() + CHILDENV.read_bytes()).hexdigest()

def _free_port():
    with socket.socket() as s: s.bind(('127.0.0.1', 0)); return s.getsockname()[1]

class FakeHost:
    "The launcher's control server, enough for a smoke test: every question gets Yes."
    def __init__(self, token):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        host = self
        self.calls = []
        class H(BaseHTTPRequestHandler):
            def _do(self):
                n = int(self.headers.get('Content-Length') or 0)
                host.calls.append((self.command, self.path, self.rfile.read(n) if n else b''))
                ok = self.headers.get('Authorization') == f'Bearer {token}'
                body = json.dumps({'answer': True} if self.path == '/confirm' else {'ok': True}).encode() if ok else b'{"ok":false}'
                self.send_response(200 if ok else 401); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
            do_GET = do_POST = _do
            def log_message(self, *a): pass
        self.srv = ThreadingHTTPServer(('127.0.0.1', 0), H)
        self.url = f'http://127.0.0.1:{self.srv.server_address[1]}'
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
    def close(self): self.srv.shutdown()

def live_ports(home=None):
    "The ports of the Leela the person runs, from their real serving.json: no test or script may call them."
    f = Path(home or Path.home())/'.config'/'leela'/'serving.json'
    try: d = json.loads(f.read_text()); os.kill(int(d['pid']), 0)
    except (OSError, ValueError, KeyError, TypeError): return set()
    return {int(d['port']), *map(int, d.get('ports') or ())}

def _get(url, data=None, headers=None, timeout=5, raw=False):
    if urllib.parse.urlsplit(url).port in live_ports(): raise RuntimeError(f'{url} is the Leela you are running; tests use their own server')
    req = urllib.request.Request(url, data=data, headers=headers or {}, method='POST' if data is not None else 'GET')
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with op.open(req, timeout=timeout) as r: return r.read() if raw else json.loads(r.read())

_PROJECT_CELL = """import json, os, sys, leela_lock_marker
print(json.dumps(dict(prefix=sys.prefix, uv=sorted(k for k in os.environ if k.startswith('UV_')), nousersite=os.environ.get('PYTHONNOUSERSITE'),
                      venv=os.environ.get('VIRTUAL_ENV'), path=os.environ.get('PATH', '').split(os.pathsep))))"""

def _project(tmp, py):
    "A project with its own .venv: a marker package the app env lacks, ipykernel from the app env by a .pth (offline), and one notebook."
    d = tmp/'proj'; sh(py, '-m', 'venv', '--without-pip', d/'.venv')
    site = next((d/'.venv'/'lib').glob('python3*/site-packages'))
    (site/'leela_lock_marker.py').write_text('OK = 1\n')
    (site/'zz_app_env.pth').write_text(sh(py, '-I', '-c', 'import sysconfig; print(sysconfig.get_path("purelib"))') + '\n')
    cell = dict(cell_type='code', id='c0', metadata={}, execution_count=None, outputs=[], source=_PROJECT_CELL)
    (d/'probe.ipynb').write_text(json.dumps(dict(cells=[cell], metadata={}, nbformat=4, nbformat_minor=5)))
    return d

_AGENT_SHELL = '''
import json, subprocess, sys
from pathlib import Path
from leela.core import host
host._host.update(url='http://127.0.0.1:9', token='t')
from leela.blocks.agent.ai import WorkspaceHost
from types import SimpleNamespace
e = WorkspaceHost._env(SimpleNamespace(ws=None), Path(sys.argv[1]))
r = lambda c: subprocess.run(c, shell=True, cwd=sys.argv[1], env=e, capture_output=True, text=True)
ran = lambda n: (lambda p: f'usage: {n}' in (p.stdout + p.stderr).lower())(r(f'{n} --help'))   # kosha's --help exits 1
print(json.dumps(dict(ramabana=ran('ramabana'), kosha=ran('kosha'), python=r('command -v python').stdout.strip(),
                      at=r('command -v kosha').stdout.strip(), dir=str(host.tools_dir()), linked=sorted(p.name for p in host.tools_dir().iterdir()))))
'''

def agent_shell(py, proj, env):
    "The links the server made: an agent's shell in `proj` runs `ramabana` and `kosha` from the app's env, and its `python` is the project's."
    got = json.loads(sh(py, '-I', '-c', _AGENT_SHELL, proj, env=env, timeout=120).splitlines()[-1])
    bad = [f'{n} --help printed no usage' for n in ('ramabana', 'kosha') if not got[n]]
    bad += [f'kosha is {got["at"]}, not the linked one'] if os.path.dirname(got['at']) != got['dir'] else []
    bad += [f'python is {got["python"]}'] if os.path.realpath(os.path.dirname(got['python'])) != os.path.realpath(proj/'.venv'/'bin') else []
    bad += [f'{n} is linked' for n in got['linked'] if n.startswith(('python', 'pip', 'uv'))]
    if bad: raise RuntimeError('; '.join(bad))

_PNG = bytes.fromhex('89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de0000000c4944415478da63f8ffff3f0005fe02fea7d6a4a10000000049454e44ae426082')

def windows_by_port(base, port, tmp):
    "A folder window and a dropped image's loose window, each on a loopback port of its own: the Mac app could not reach a `*.localhost` name."
    (d := tmp/'drop').mkdir(exist_ok=True); (png := d/'shot.png').write_bytes(_PNG)
    (f := tmp/'folder').mkdir(exist_ok=True); (f/'a.py').write_text('x = 1\n')
    for q, want in ((dict(path=str(f)), None), (dict(path=str(d), file=str(png)), 'image')):
        r = _get(f'{base}/hub/open?{urllib.parse.urlencode(q)}', data=b'', timeout=120)
        u = urllib.parse.urlsplit(r.get('url', ''))
        if not r.get('ok') or u.hostname != '127.0.0.1' or u.port in (None, port): raise RuntimeError(f'not a port of its own: {r}')
        if b'<html' not in _get(r['url'], raw=True, timeout=60).lower(): raise RuntimeError(f'no page at {r["url"]}')
        if want and (t := _get(r['url'] + 'tab/state', timeout=30)).get('kind') != want: raise RuntimeError(f'the loose window shows {t}')

def project_cell(base, port, proj, env_dir):
    "Through the server's routes, a cell of a notebook in `proj` runs on the project's .venv, and no app build setting reaches it."
    d = _get(f'{base}/hub/open?path={urllib.parse.quote(str(proj))}', data=b'', timeout=120)
    if not d.get('ok'): raise RuntimeError(d)
    site, h = d['url'].rstrip('/'), {'Content-Type': 'application/json'}
    nb = str(proj/'probe.ipynb')
    _get(f'{site}/tab/open?path={urllib.parse.quote(nb)}', headers=h, timeout=60, raw=True)
    r = _get(f'{site}/nb/run', data=json.dumps(dict(path=nb, i=0, id='c0')).encode(), headers=h, timeout=180)
    outs = r.get('cell', {}).get('outputs', [])
    text = ''.join(o.get('text', '') for o in outs if o.get('output_type') == 'stream')
    if not r.get('ok') or not text.strip(): raise RuntimeError(f'the cell failed: {json.dumps(outs)[-800:]}')
    got, app = json.loads(text.strip().splitlines()[-1]), os.path.realpath(env_dir)
    bad = [f'sys.prefix is {got["prefix"]}'] if os.path.realpath(got['prefix']) != os.path.realpath(proj/'.venv') else []
    bad += [f'UV keys {got["uv"]}, not only the stored UV_INDEX_URL'] if got['uv'] != ['UV_INDEX_URL'] else []
    bad += ['PYTHONNOUSERSITE is set'] if got['nousersite'] else []
    bad += [f'VIRTUAL_ENV is the app env'] if got['venv'] and os.path.realpath(got['venv']) == app else []
    bad += ['the app env bin is on PATH'] if any(p and os.path.realpath(p) == os.path.join(app, 'bin') for p in got['path']) else []
    if bad: raise RuntimeError('; '.join(bad))

def smoke(env_dir, results, extras=(), wait=180):
    "Check an installed env: pip check, imports, the server in host mode on a temp folder, one kernel cell, each extra."
    py, uv = env_dir/'bin'/'python', pinned_uv()
    def step(name, f):
        t = time.monotonic()
        try: f(); results.append(dict(step=name, ok=True, secs=round(time.monotonic()-t, 1)))
        except Exception as e: results.append(dict(step=name, ok=False, secs=round(time.monotonic()-t, 1), error=str(e)[-1500:])); return False
        return True
    ok = step('pip check', lambda: sh(uv, 'pip', 'check', '--python', py))
    ok &= step('imports', lambda: sh(py, '-I', '-c', 'import leela, leela.app, leela.core.host, ramabana, shalya, kunda, rishi, ipykernel'))
    tmp = Path(tempfile.mkdtemp(prefix='leela-smoke-')).resolve()
    (tmp/'cfg').mkdir(); (tmp/'data').mkdir(); (work := tmp/'work').mkdir()
    ok &= step('project .venv', lambda: _project(tmp, py))
    (tmp/'cfg'/'leela').mkdir(parents=True); (tmp/'cfg'/'leela'/'env.json').write_text(json.dumps({'UV_INDEX_URL': 'https://example.invalid/simple'}))   # the person's own, set in Leela
    proj = tmp/'proj'
    def serve(name, env, checks):
        "The server in host mode under `env`, as the launcher starts it, then `checks(base, port)`."
        port, token, host = _free_port(), os.urandom(16).hex(), None
        try:
            host = FakeHost(token)
            env = env | dict(XDG_CONFIG_HOME=str(tmp/'cfg'), XDG_DATA_HOME=str(tmp/'data'), LEELA_SHELL_ENV='0',
                             LEELA_HOST_URL=host.url, LEELA_APP_VERSION='0.0.0-test', LEELA_LOCK_N='0')
            args = [a.format(port=port) for a in spec()['server_args']]
            with open(tmp/f'server-{name}.log', 'wb') as log:
                srv = subprocess.Popen([env_dir/'bin'/'leela', *args], env=env, cwd=tmp, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.PIPE)
            srv.stdin.write(f'{token}\n'.encode()); srv.stdin.close()   # as the launcher does: never in argv, env, a file or a log
            base = f'http://127.0.0.1:{port}'
            def health():
                end = time.monotonic() + wait
                while time.monotonic() < end:
                    if srv.poll() is not None: raise RuntimeError(f'the server stopped with {srv.returncode}: ' + (tmp/f'server-{name}.log').read_text()[-1500:])
                    try:
                        if _get(f'{base}/health', timeout=2).get('status') == 'ok': return
                    except Exception: time.sleep(.5)
                raise TimeoutError(f'no /health in {wait} s: ' + (tmp/f'server-{name}.log').read_text()[-1500:])
            good = step(f'server /health{name}', health) and checks(base, port)
            def quit():   # an open window holds an endless /fs/events stream; the launcher kills a server still up after 15 s
                ports = {port, *(urllib.parse.urlsplit(r['url']).port for r in _get(f'{base}/app/sites').get('sites', []))}
                socks = [socket.create_connection(('127.0.0.1', p)) for p in ports if p]
                for s, p in zip(socks, ports): s.sendall(f'GET /fs/events HTTP/1.1\r\nHost: 127.0.0.1:{p}\r\n\r\n'.encode())
                time.sleep(1); t = time.monotonic(); srv.terminate()
                try: srv.wait(15)
                except subprocess.TimeoutExpired: srv.kill(); raise RuntimeError(f'SIGTERM did not stop the server in 15 s while page streams were open on {sorted(ports)}')
                finally:
                    for s in socks: s.close()
                if (secs := time.monotonic() - t) > 5: raise RuntimeError(f'the server took {secs:.1f} s to stop')
            done = step(f'quit with a page open{name}', quit)
            if srv.poll() is None: srv.kill()
            return done and good
        finally:
            if host: host.close()
    def hub_open(base):
        d = _get(f'{base}/hub/open?path={urllib.parse.quote(str(work))}', data=b'', timeout=120)
        if not d.get('ok'): raise RuntimeError(d)
    ok &= serve('', server_env(), lambda base, port: step('/hub/open', lambda: hub_open(base)) & step('project kernel cell', lambda: project_cell(base, port, proj, env_dir))
                & step('windows by port', lambda: windows_by_port(base, port, tmp)))
    ok &= step('agent shell tools', lambda: agent_shell(py, proj, server_env() | dict(XDG_CONFIG_HOME=str(tmp/'cfg'), XDG_DATA_HOME=str(tmp/'data'))))
    old = server_env_1_0(env_dir, cache='', python='', python_version=PYTHON)
    ok &= serve(' (app 1.0.0 env)', old, lambda base, port: step('project kernel cell (app 1.0.0 env)', lambda: project_cell(base, port, proj, env_dir)))
    kenv = server_env() | dict(XDG_CONFIG_HOME=str(tmp/'cfg'), XDG_DATA_HOME=str(tmp/'data'), JUPYTER_DATA_DIR=str(tmp/'jd'))
    def cell():
        if (got := sh(py, '-I', '-c', _SMOKE_KERNEL, env=kenv, cwd=tmp, timeout=180).splitlines()[-1:]) != ['2']: raise RuntimeError(f'the cell gave {got}')
    ok &= step('kernel cell 1+1', cell)
    def find():   # rgapi 0.2.3 swapped fd's first two arguments, and an empty file list looked like a pass
        (work/'probe.py').write_text('x = 1\n')
        got = sh(py, '-I', '-c', f'from pathlib import Path; from leela.blocks.fs.fs import _walked; print(len(_walked([Path({str(work)!r})], False, 100, None)))', env=kenv, cwd=tmp, timeout=120)
        if got.splitlines()[-1:] != ['1']: raise RuntimeError(f'the file walk found {got.strip()[-200:]!r} files, not 1')
    ok &= step('file walk', find)
    for x in extras: ok &= step(f'extra {x}', lambda x=x: sh(py, *_EXTRA_CHECK[x], env=kenv))
    shutil.rmtree(tmp, ignore_errors=True)
    return ok

def seed(a, b):
    "`b` as an APFS clone of env `a` with `a`'s path rewritten in bin/ and pyvenv.cfg, and no bytecode: what the launcher's `EnvStore.seed` does."
    sh('cp', '-c', '-R', a, b)
    for c in list(Path(b).rglob('__pycache__')): shutil.rmtree(c, ignore_errors=True)
    old, new = str(a).encode(), str(b).encode()
    for f in [Path(b)/'pyvenv.cfg', *(Path(b)/'bin').iterdir()]:
        if f.is_symlink() or not f.is_file() or f.stat().st_size > 2_000_000: continue
        if old in (d := f.read_bytes()): f.write_bytes(d.replace(old, new))

def _digest(env):
    return hashlib.sha256(b''.join((env/f).read_bytes() for f in ('pyvenv.cfg', 'bin/leela'))
                          + '\n'.join(sorted(p.name for p in (env/'bin').iterdir())).encode()).hexdigest()

def _health(env_dir, tmp, wait=120):
    "Whether the server from `env_dir` answers /health in host mode, started as the launcher starts it."
    port, token, host = _free_port(), os.urandom(16).hex(), None
    (d := tmp/'health'/env_dir.name).mkdir(parents=True, exist_ok=True); (d/'cfg').mkdir(exist_ok=True); (d/'data').mkdir(exist_ok=True)
    try:
        host = FakeHost(token)
        env = server_env() | dict(XDG_CONFIG_HOME=str(d/'cfg'), XDG_DATA_HOME=str(d/'data'), LEELA_SHELL_ENV='0', LEELA_HOST_URL=host.url, LEELA_APP_VERSION='0.0.0-test', LEELA_LOCK_N='0')
        srv = subprocess.Popen([env_dir/'bin'/'leela', *[a.format(port=port) for a in spec()['server_args']]], env=env, cwd=d,
                               stdout=open(d/'server.log', 'wb'), stderr=subprocess.STDOUT, stdin=subprocess.PIPE)
        srv.stdin.write(f'{token}\n'.encode()); srv.stdin.close()
        end = time.monotonic() + wait
        try:
            while time.monotonic() < end and srv.poll() is None:
                try:
                    if _get(f'http://127.0.0.1:{port}/health', timeout=2).get('status') == 'ok': return True
                except Exception: time.sleep(.5)
            return False
        finally:
            srv.terminate()
            try: srv.wait(15)
            except subprocess.TimeoutExpired: srv.kill()
    finally:
        if host: host.close()

def incremental(env_a, lock, cache, tmp, uv, results):
    "The next env from a copy of this one: `uv sync` changes one thing (an extra), and the copy works and names only itself."
    t, b = time.monotonic(), tmp/'next'   # a name the old path is not the start of, or the check below finds `env` inside `env-b`
    try:
        before = _digest(env_a)
        seed(env_a, b)
        env = child_env(cache=cache, python=tmp/'python', python_version=PYTHON, env=b)
        p = subprocess.run([str(uv), *sync_args(lock, ['langserver'])], env=env, capture_output=True, text=True, timeout=600)
        if p.returncode: raise RuntimeError(f'uv sync on the copy: {(p.stderr or p.stdout)[-800:]}')
        n = int(m.group(1)) if (m := re.search(r'Installed (\d+) packages?', p.stderr + p.stdout)) else 0
        bad = [] if 0 < n < 20 else [f'the copy installed {n} packages, not only the extra']
        bad += [str(f) for f in b.rglob('*') if f.is_file() and not f.is_symlink() and f.stat().st_size < 2_000_000 and str(env_a).encode() in f.read_bytes()]
        bad += [] if (b/'bin'/'leela').read_text().startswith(f'#!{b}/bin/python') else ['bin/leela does not run the copy\'s python']
        bad += [] if _digest(env_a) == before else ['the env in use changed']
        py = b/'bin'/'python'
        sh(py, '-I', '-c', 'import leela, leela.app, ramabana, kunda, ipykernel')
        kenv = server_env() | dict(XDG_CONFIG_HOME=str(tmp/'cfg'), XDG_DATA_HOME=str(tmp/'data'), JUPYTER_DATA_DIR=str(tmp/'jd-b'))
        if sh(py, '-I', '-c', _SMOKE_KERNEL, env=kenv, cwd=tmp, timeout=180).splitlines()[-1:] != ['2']: bad.append('the kernel cell failed on the copy')
        if not _health(b, tmp): bad.append('the server from the copy did not answer /health')
        if bad: raise RuntimeError('; '.join(bad[:8]))
        results.append(dict(step=f'env from a copy ({n} installed)', ok=True, secs=round(time.monotonic()-t, 1)))
        return True
    except Exception as e:
        results.append(dict(step='env from a copy', ok=False, secs=round(time.monotonic()-t, 1), error=str(e)[-1500:]))
        return False

def lock_test(d=LOCK, fresh=False, extras=False, record_dir=None, keep=False):
    "Build the env as the app does, in a temp folder, smoke it, and write the test record for this lock hash."
    uv, d = pinned_uv(), Path(d)
    uvv, h = uv_version(uv), lock_hash(d, uv_version(uv))
    tmp = Path(tempfile.mkdtemp(prefix='leela-lock-test-')).resolve()
    lock = tmp/'lock'; lock.mkdir()
    for f in FILES: shutil.copy(d/f, lock/f)
    cache = tmp/'cache' if fresh else Path(os.environ.get('LEELA_LOCK_CACHE') or Path.home()/'Library'/'Caches'/'Leela'/'uv')
    env_dir, results, t0 = tmp/'env', [], time.monotonic()
    env = child_env(cache=cache, python=tmp/'python', python_version=PYTHON, env=env_dir)
    xs = EXTRAS if extras else ()
    print(f'building {h[:16]} in {tmp} (cache {cache})')
    with open(tmp/'sync.log', 'wb') as log: rc = subprocess.run([uv, *sync_args(lock, xs)], env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    results.append(dict(step='uv sync', ok=rc == 0, secs=round(time.monotonic()-t0, 1), **({} if rc == 0 else {'error': (tmp/'sync.log').read_text()[-1500:]})))
    ok = rc == 0 and smoke(env_dir, results, xs)
    if ok and not xs: ok &= incremental(env_dir, lock, cache, tmp, uv, results)
    size = sum(f.stat().st_size for f in env_dir.rglob('*') if f.is_file() and not f.is_symlink()) if env_dir.exists() else 0
    rec = dict(hash=h, passed=ok, uv=uvv, python=PYTHON, macos=platform_mac(), launcher_api=LAUNCHER_API, test_code=test_code_hash(),
               time=iso(now()), fresh=fresh, extras=list(xs), env_bytes=size, leela=leela_version(d), results=results)
    for r in results: print(f"  {'ok  ' if r['ok'] else 'FAIL'} {r['step']} ({r['secs']} s)" + (f"\n       {r['error'][-600:]}" if not r['ok'] else ''))
    out = Path(record_dir or d/'tested')
    if ok:
        out.mkdir(parents=True, exist_ok=True)
        (out/f'{h}.json').write_text(dumps(rec))
        print(f'passed; record {out}/{h}.json; env {size/2**20:.0f} MB')
    else: print('failed; no record written')
    if not keep: shutil.rmtree(tmp, ignore_errors=True)
    return rec

def platform_mac():
    import platform
    return platform.mac_ver()[0]

# Signing: SSH Ed25519 keys in ~/.ssh, SSHSIG with namespace leela-lock
def key_paths(home=None): return [Path(home or Path.home())/'.ssh'/k for k in KEYS]

def sign(path, key):
    "Sign `path` with `key` (the agent signs when it holds it); the signature goes beside it as `<path>.sig`, then to `sig`."
    Path(f'{path}.sig').unlink(missing_ok=True)
    pub = Path(f'{key}.pub')
    use = pub if pub.is_file() and pub.read_text().split()[1] in sh('ssh-add', '-L', check=False) else key
    sh('ssh-keygen', '-Y', 'sign', '-n', NS, '-f', use, path)
    return Path(f'{path}.sig')

def allowed(keys_pub):
    "An allowed_signers file for `ssh-keygen -Y verify`, from the public keys the app embeds."
    lines = [f'{NS} namespaces="{NS}" ' + ' '.join(l.split()[:2]) for l in Path(keys_pub).read_text().splitlines() if l.strip().startswith('ssh-ed25519')]
    if not lines: raise SystemExit(f'no ssh-ed25519 key in {keys_pub}')
    f = Path(tempfile.mkdtemp())/'allowed_signers'
    f.write_text('\n'.join(lines) + '\n')
    return f

def verify_sig(data, sig, keys_pub):
    "Whether `sig` is a leela-lock signature over the file `data` by one of the keys in `keys_pub`."
    with open(data, 'rb') as f:
        p = subprocess.run(['ssh-keygen', '-Y', 'verify', '-f', allowed(keys_pub), '-I', NS, '-n', NS, '-s', sig], stdin=f, capture_output=True)
    return p.returncode == 0

def check_lock_dir(d, keys_pub, highest=-1):
    "Check a downloaded or bundled lock as the app does: signature, file hashes, lock hash, platform. The manifest, or SystemExit."
    d = Path(d)
    if not verify_sig(d/'manifest.json', d/'manifest.sig', keys_pub): raise SystemExit(f'{d}/manifest.sig is not a good leela-lock signature')
    m = json.loads((d/'manifest.json').read_text())
    for f in FILES:
        if m['files'].get(f) != sha256(d/f): raise SystemExit(f'{f} does not match the manifest')
    if lock_hash(d, m['uv_min']) != m['hash']: raise SystemExit('the lock hash does not match the manifest')
    if m['platform'] != PLATFORM: raise SystemExit(f"the lock is for {m['platform']}")
    if m['n'] <= highest: raise SystemExit(f"lock {m['n']} is not newer than {highest}")
    return m

def lock_key(home=None, keys_out=None, passphrase=True, agent=True):
    "Make the main and emergency signing keys in ~/.ssh, add them to the agent with the passphrase in the keychain, print the public keys."
    paths = key_paths(home)
    if have := [p for p in paths if p.exists() or Path(f'{p}.pub').exists()]: raise SystemExit(f'refusing to overwrite {", ".join(map(str, have))}')
    paths[0].parent.mkdir(mode=0o700, exist_ok=True)
    for p, who in zip(paths, ('main', 'emergency')):
        cmd = ['ssh-keygen', '-t', 'ed25519', '-a', '100', '-f', str(p), '-C', f'leela-lock-{who}'] + ([] if passphrase else ['-N', ''])
        if subprocess.run(cmd).returncode: raise SystemExit(f'ssh-keygen did not make {p}')
        if agent and subprocess.run(['ssh-add', '--apple-use-keychain', str(p)]).returncode: raise SystemExit(f'ssh-add did not take {p}')
    pubs = ''.join(Path(f'{p}.pub').read_text() for p in paths)
    print(f'public keys to embed (packaging/lock/keys.pub):\n{pubs}')
    if keys_out and not Path(keys_out).exists(): Path(keys_out).write_text(pubs); print(f'wrote {keys_out}; commit it')
    return pubs

def gh(*a, check=True): return sh('gh', *a, '-R', REPO, check=check, env={k: v for k, v in os.environ.items() if k != 'GITHUB_TOKEN'})

def fetch(url, dst=None):
    "The bytes at `url`, also written to `dst`."
    with urllib.request.urlopen(url, timeout=30) as r: b = r.read()
    if dst: Path(dst).write_bytes(b)
    return b

def pointer(n, manifest_sha, name, at=None):
    "A channel pointer. It names its channel, so a test pointer served as stable is refused."
    return dict(n=n, manifest_sha256=manifest_sha, published=iso(at or now()), channel=name)

def channel(name='channel', keys_pub=LOCK/'keys.pub', base=f'{DL}/lock-channel'):
    "The channel pointer `name` (channel or channel-test), checked; {} when none is published."
    tmp = Path(tempfile.mkdtemp())
    try: fetch(f'{base}/{name}.json', tmp/'c.json'); fetch(f'{base}/{name}.sig', tmp/'c.sig')
    except urllib.error.HTTPError as e:
        if e.code == 404: return {}
        raise
    if not verify_sig(tmp/'c.json', tmp/'c.sig', keys_pub): raise SystemExit(f'{name}.json has a bad signature')
    c = json.loads((tmp/'c.json').read_text())
    if c.get('channel') != name: raise SystemExit(f"{name}.json is a pointer for {c.get('channel')}")
    return c

def fetch_lock(n, into, base=DL):
    into = Path(into); into.mkdir(parents=True, exist_ok=True)
    for f in ('manifest.json', 'manifest.sig', *FILES): fetch(f'{base}/lock-{n}/{asset_name(f)}', into/f)
    return into

def asset_name(f): return 'python-version' if f == '.python-version' else f

def record_for(h, d=LOCK, days=RECORD_DAYS, at=None):
    "The passing test record for hash `h`, or why it cannot be used."
    p = Path(d)/'tested'/f'{h}.json'
    if not p.is_file(): return None, f'no test record for {h[:16]}; run make lock-test'
    r = json.loads(p.read_text())
    if not r.get('passed'): return None, 'the test record did not pass'
    age = (at or now()) - datetime.strptime(r['time'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    if age > timedelta(days=days): return None, f'the test record is {age.days} days old; run make lock-test again'
    if r.get('uv') != pinned_version(): return None, f"the record used uv {r.get('uv')}, not the pinned {pinned_version()}"
    if r.get('test_code') != test_code_hash(): return None, 'tools/lock.py or childenv.json changed since the test; run make lock-test again'
    return r, ''

def tree_clean(root=ROOT):
    "Why the git tree cannot publish, or ''."
    if sh('git', '-C', root, 'status', '--porcelain'): return 'the git tree has changes that are not committed'
    head, up = sh('git', '-C', root, 'rev-parse', 'HEAD'), sh('git', '-C', root, 'rev-parse', '@{u}', check=False)
    return '' if head == up else 'HEAD is not pushed to its upstream branch'

def refusals(d=LOCK, published=None, allow_downgrade=False, at=None, keys_pub=LOCK/'keys.pub'):
    "Every reason `lock-publish` refuses this lock."
    why, uv = [], pinned_version()
    if not Path(keys_pub).is_file(): why.append(f'no {keys_pub}; run make lock-key and commit the public keys')
    if not key_paths()[0].is_file(): why.append(f'no signing key {key_paths()[0]}; run make lock-key')
    if bad := check(d): why += bad
    if (t := tree_clean()): why.append(t)
    h = lock_hash(d, uv)
    if not record_for(h, d, at=at)[0]: why.append(record_for(h, d, at=at)[1])
    if published and published.get('leela') and not allow_downgrade:
        from packaging.version import Version
        if Version(leela_version(d)) < Version(published['leela']): why.append(f"leela {leela_version(d)} is lower than the published {published['leela']}; ALLOW_DOWNGRADE=1 to roll back")
    return why

def publish(d=LOCK, keys_pub=LOCK/'keys.pub', allow_downgrade=False):
    "Sign and publish this lock as lock-<n>, check what GitHub serves, then point the test channel at it."
    if why := refusals(d, None, allow_downgrade, keys_pub=keys_pub): raise SystemExit('lock-publish refuses:\n  ' + '\n  '.join(why))
    cur = channel('channel-test', keys_pub) or channel('channel', keys_pub)
    last = check_lock_dir(fetch_lock(cur['n'], Path(tempfile.mkdtemp())/'last'), keys_pub) if cur else None
    if why := refusals(d, last, allow_downgrade, keys_pub=keys_pub): raise SystemExit('lock-publish refuses:\n  ' + '\n  '.join(why))
    n, key = (cur.get('n') or 0) + 1, key_paths()[0]
    out = Path(tempfile.mkdtemp(prefix=f'leela-lock-{n}-'))
    for f in FILES: shutil.copy(Path(d)/f, out/asset_name(f))
    (out/'manifest.json').write_text(dumps(manifest(d, n, pinned_version())))
    sign(out/'manifest.json', key).rename(out/'manifest.sig')
    rec = Path(d)/'tested'/f"{lock_hash(d, pinned_version())}.json"
    shutil.copy(rec, out/'tested.json')
    gh('release', 'create', f'lock-{n}', '--latest=false', '--prerelease', '--title', f'Lock {n}', '--notes', f'Environment lock {n}: leela {leela_version(d)}.',
       *sorted(map(str, out.iterdir())))
    got = check_lock_dir(fetch_lock(n, out/'check'), keys_pub)
    c = out/'channel-test.json'
    c.write_text(dumps(pointer(n, sha256(out/'manifest.json'), 'channel-test')))
    sign(c, key).rename(out/'channel-test.sig')
    gh('release', 'view', 'lock-channel', check=False) or gh('release', 'create', 'lock-channel', '--latest=false', '--prerelease', '--title', 'Lock channel', '--notes', 'Pointers to the current environment locks.')
    gh('release', 'upload', 'lock-channel', c, out/'channel-test.sig', '--clobber')
    if channel('channel-test', keys_pub).get('n') != n: raise SystemExit('the test channel does not point at the new lock')
    print(f"lock {n} (leela {got['leela']}) is on the test channel; LEELA_LOCK_CHANNEL=test points an app at it; then make lock-promote N={n}")

def promote(n, keys_pub=LOCK/'keys.pub'):
    "Point the stable channel at lock `n`, which must be the one on the test channel."
    t = channel('channel-test', keys_pub)
    if t.get('n') != n: raise SystemExit(f"the test channel points at lock {t.get('n')}, not {n}")
    out = Path(tempfile.mkdtemp())
    check_lock_dir(fetch_lock(n, out/'lock'), keys_pub)
    (c := out/'channel.json').write_text(dumps(pointer(n, t['manifest_sha256'], 'channel')))
    sign(c, key_paths()[0]).rename(out/'channel.sig')
    gh('release', 'upload', 'lock-channel', c, out/'channel.sig', '--clobber')
    verify(keys_pub=keys_pub)

def verify(name='channel', keys_pub=LOCK/'keys.pub'):
    "Check a published channel as the app does."
    c = channel(name, keys_pub)
    if not c: raise SystemExit(f'no {name}.json is published')
    d = fetch_lock(c['n'], Path(tempfile.mkdtemp())/'lock')
    if sha256(d/'manifest.json') != c['manifest_sha256']: raise SystemExit('the manifest does not match the channel pointer')
    m = check_lock_dir(d, keys_pub)
    print(f"{name}: lock {m['n']}, leela {m['leela']}, hash {m['hash'][:16]}, {m['download_bytes']/2**20:.0f} MB to download: good")
    return m

def diff(d=LOCK, keys_pub=LOCK/'keys.pub', old=None):
    "Packages added, removed and changed against the published lock; owner versions with no git tag are flagged."
    if old is None:
        c = channel('channel', keys_pub)
        old = packages(fetch_lock(c['n'], Path(tempfile.mkdtemp())/'lock')) if c else []
    a, b = {p['name']: p['version'] for p in old}, {p['name']: p['version'] for p in packages(d)}
    rows = [f'+ {n} {b[n]}' for n in sorted(b.keys() - a.keys())] + [f'- {n} {a[n]}' for n in sorted(a.keys() - b.keys())]
    rows += [f'~ {n} {a[n]} -> {b[n]}' for n in sorted(a.keys() & b.keys()) if a[n] != b[n]]
    own = set(owners())
    for n in sorted(own & b.keys()):
        if (n not in a or a[n] != b[n]) and not _tagged(n, b[n]): rows.append(f'! {n} {b[n]} has no git tag on vedicreader/{n}')
    print('\n'.join(rows) or 'no change')
    return rows

def _tagged(name, v):
    for t in (v, f'v{v}'):
        try: urllib.request.urlopen(f'https://api.github.com/repos/vedicreader/{name}/git/ref/tags/{t}', timeout=10); return True
        except Exception: pass
    return False

def fetch_channel(out, name='channel', keys_pub=LOCK/'keys.pub'):
    "The published lock a channel points at, checked, into `out`: the bootstrap lock of a release build."
    c = channel(name, keys_pub)
    if not c: raise SystemExit(f'no {name}.json is published; publish and promote a lock first')
    d = fetch_lock(c['n'], out)
    if sha256(d/'manifest.json') != c['manifest_sha256']: raise SystemExit('the manifest does not match the channel pointer')
    shutil.copy(keys_pub, Path(out)/'keys.pub')
    m = check_lock_dir(d, keys_pub)
    print(f"bootstrap lock {m['n']} (leela {m['leela']}) in {out}")

def wheel(v, upload=False):
    "Build the Leela wheel from tag `v` in a clean checkout, and with `upload` attach it to release `v`; `make lock` pins it by GitHub's sha256."
    tmp = Path(tempfile.mkdtemp(prefix='leela-wheel-'))
    sh('git', '-C', ROOT, 'worktree', 'add', '--detach', tmp/'src', v)
    try:
        sh('uv', 'build', '--wheel', '--out-dir', tmp/'dist', tmp/'src')
        w = tmp/'dist'/f'leela-{v}-py3-none-any.whl'
        if not w.is_file(): raise SystemExit(f'the build made no {w.name}')
        if upload: gh('release', 'upload', v, w)
        print(f'{w}' + (f' is on release {v}' if upload else ''))
        return w
    finally: sh('git', '-C', ROOT, 'worktree', 'remove', '--force', tmp/'src', check=False)

def dev_lock(out, src=LOCK, n=0):
    "A lock signed with a throwaway key, for a local app build: the pinned project in `src`, manifest `n`, keys.pub with the throwaway key."
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    for f in FILES: shutil.copy(Path(src)/f, out/f)
    k = Path(tempfile.mkdtemp())/'dev'
    sh('ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C', 'leela-lock-dev', '-f', k)
    (out/'manifest.json').write_text(dumps(manifest(out, n, pinned_version())))
    sh('ssh-keygen', '-Y', 'sign', '-n', NS, '-f', k, out/'manifest.json')
    Path(f"{out/'manifest.json'}.sig").rename(out/'manifest.sig')
    shutil.copy(f'{k}.pub', out/'keys.pub')
    shutil.rmtree(k.parent)
    print(f'dev lock in {out} (throwaway key; not for release)')

def fixtures(out):
    "SSHSIG fixtures for the Swift tests, made by ssh-keygen with throwaway keys under a temporary HOME."
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp())
    env = dict(PATH='/usr/bin:/bin', HOME=str(tmp))
    for k in ('main', 'emergency', 'stranger'): sh('ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C', f'fixture-{k}', '-f', tmp/k, env=env)
    msg = out/'message.json'
    msg.write_text(dumps(dict(n=7, hash='ab'*32, platform=PLATFORM)))
    for k, ns, name in (('main', NS, 'main'), ('emergency', NS, 'emergency'), ('stranger', NS, 'stranger'), ('main', 'other-ns', 'wrongns')):
        sh('ssh-keygen', '-Y', 'sign', '-n', ns, '-f', tmp/k, msg, env=env)
        Path(f'{msg}.sig').rename(out/f'{name}.sig')
    (out/'keys.pub').write_text(''.join((tmp/f'{k}.pub').read_text() for k in ('main', 'emergency')))
    shutil.copy(tmp/'main', out/'main.key')   # throwaway, so the Swift tests can sign manifests the same way through tools/lock.py
    shutil.rmtree(tmp)
    print(f'fixtures in {out}')

def verify_app(app, zip_=None, max_kb=None, max_zip_kb=None):
    "Check a built Leela.app without opening it."
    import plistlib
    app, why = Path(app), []
    c = app/'Contents'
    p = plistlib.loads((c/'Info.plist').read_bytes())
    want = dict(CFBundleIdentifier='org.vedicreader.leela', CFBundleExecutable='Leela', CFBundlePackageType='APPL')
    why += [f'{k} is {p.get(k)!r}, not {v!r}' for k, v in want.items() if p.get(k) != v]
    if not p.get('NSAppTransportSecurity', {}).get('NSAllowsLocalNetworking'): why.append('no NSAllowsLocalNetworking')
    if not p.get('CFBundleDocumentTypes'): why.append('no document types')
    if not os.access(c/'MacOS'/'Leela', os.X_OK): why.append('no launcher')
    uv = c/'Helpers'/'uv'
    if not os.access(uv, os.X_OK): why.append('no Helpers/uv')
    elif (v := uv_version(uv)) != pinned_version(): why.append(f'Helpers/uv is {v}, not {pinned_version()}')
    try: m = check_lock_dir(c/'Resources'/'Lock', c/'Resources'/'lock-keys.pub')
    except (SystemExit, OSError, ValueError) as e: why.append(f'bootstrap lock: {e}'); m = {}
    if not (c/'Resources'/'childenv.json').is_file(): why.append('no childenv.json')
    dev = (LOCK/'keys.pub').is_file() and (c/'Resources'/'lock-keys.pub').read_text() != (LOCK/'keys.pub').read_text()
    kb = sum(f.stat().st_size for f in app.rglob('*') if f.is_file() and not f.is_symlink()) // 1024
    if max_kb and kb > max_kb: why.append(f'{kb/1024:.1f} MB on disk is over {max_kb/1024:.0f} MB')
    if zip_ and max_zip_kb and (z := Path(zip_).stat().st_size // 1024) > max_zip_kb: why.append(f'{z/1024:.1f} MB zipped is over {max_zip_kb/1024:.0f} MB')
    if why: raise SystemExit('the app is refused:\n  ' + '\n  '.join(why))
    print(f"bundle ok: {p.get('CFBundleShortVersionString')}, uv {pinned_version()}, lock {m.get('n')} (leela {m.get('leela')})"
          + ('' if (LOCK/'keys.pub').is_file() and not dev else ', signed with a throwaway key: not for release'))

def main(argv=None):
    a = argparse.ArgumentParser(prog='lock.py', description=__doc__)
    s = a.add_subparsers(dest='cmd', required=True)
    p = s.add_parser('make'); p.add_argument('version'); p.add_argument('--dir', default=LOCK); p.add_argument('--wheel'); p.add_argument('--pin', action='append', default=[], help='an extra constraint, such as ramabana==0.2.109')
    p = s.add_parser('hash'); p.add_argument('--dir', default=LOCK)
    p = s.add_parser('check'); p.add_argument('--dir', default=LOCK)
    p = s.add_parser('test'); p.add_argument('--dir', default=LOCK); p.add_argument('--fresh', action='store_true'); p.add_argument('--extras', action='store_true')
    p.add_argument('--records'); p.add_argument('--keep', action='store_true')
    p = s.add_parser('diff'); p.add_argument('--dir', default=LOCK); p.add_argument('--against', help='a local lock folder in place of the published one')
    p = s.add_parser('publish'); p.add_argument('--allow-downgrade', action='store_true')
    p = s.add_parser('promote'); p.add_argument('n', type=int)
    p = s.add_parser('verify'); p.add_argument('--channel', default='stable', choices=['stable', 'test'])
    p = s.add_parser('key'); p.add_argument('--keys-out', default=LOCK/'keys.pub')
    p = s.add_parser('dev-lock'); p.add_argument('out'); p.add_argument('--from', dest='src', default=LOCK); p.add_argument('--n', type=int, default=0)
    p = s.add_parser('fetch'); p.add_argument('out'); p.add_argument('--channel', default='stable', choices=['stable', 'test'])
    p = s.add_parser('wheel'); p.add_argument('version'); p.add_argument('--upload', action='store_true')
    p = s.add_parser('fixtures'); p.add_argument('out')
    p = s.add_parser('verify-app'); p.add_argument('app'); p.add_argument('--zip'); p.add_argument('--max-kb', type=int); p.add_argument('--max-zip-kb', type=int)
    o = a.parse_args(argv)
    match o.cmd:
        case 'make': make(o.version, o.dir, o.wheel, pins=o.pin)
        case 'hash': print(lock_hash(o.dir, pinned_version()))
        case 'check':
            if why := check(o.dir): raise SystemExit('\n'.join(why))
            print('lock ok')
        case 'test':
            if not lock_test(o.dir, o.fresh, o.extras, o.records, o.keep)['passed']: raise SystemExit(1)
        case 'diff': diff(o.dir, old=packages(o.against) if o.against else None)
        case 'publish': publish(allow_downgrade=o.allow_downgrade)
        case 'promote': promote(o.n)
        case 'verify': verify('channel-test' if o.channel == 'test' else 'channel')
        case 'key': lock_key(keys_out=o.keys_out)
        case 'dev-lock': dev_lock(o.out, o.src, o.n)
        case 'fetch': fetch_channel(o.out, 'channel-test' if o.channel == 'test' else 'channel')
        case 'wheel': wheel(o.version, o.upload)
        case 'fixtures': fixtures(o.out)
        case 'verify-app': verify_app(o.app, o.zip, o.max_kb, o.max_zip_kb)

if __name__ == '__main__': main()
