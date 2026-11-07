"Leela's environment lock is kavacha's lock tool with Leela's spec and checks: the names it gives, the hooks, the cooldown against a local index, and the make targets."

import json, os, subprocess, sys
from datetime import timedelta
from pathlib import Path
import pytest
from kavacha import lock as K
from kavacha.thin import Thin

ROOT = Path(__file__).resolve().parent.parent
L = K.Lock(Thin.load(ROOT))

def test_the_spec_gives_the_names_leela_shipped_with():
    t = L.t
    assert (t.identifier, t.sig_ns, t.marker, t.env_prefix, t.server, t.lock_project, t.cask) == ('org.vedicreader.leela', 'leela-lock', '.leela-env.json', 'LEELA_', 'leela', 'leela-lock', 'leela')
    assert t.key_names == ['leela_lock_ed25519', 'leela_lock_emergency_ed25519'] and L.dl == 'https://github.com/vedicreader/leela/releases/download'
    assert (t.python, L.minor, t.extras, t.seed_extra) == ('3.13.18', '3.13', ['mlx', 'llama', 'langserver'], 'langserver'), 'the old app\'s minor: a kernel on a 3.13 project borrows Leela\'s packages'
    assert t.wheels['llama-cpp-python']['url'].endswith('llama_cpp_python-0.3.30-py3-none-macosx_11_0_arm64.whl')

def test_the_child_environment_is_the_one_app_1_0_shipped_with():
    s = L.spec()
    assert s['drop_prefixes'] == ['UV_', 'LEELA_HOST_', 'LEELA_LOCK_', 'LEELA_ENV_', 'LEELA_APP_'] and s['uv']['UV_LINK_MODE'] == 'clone'
    assert s['server_args'] == ['--app', '--shell', 'none', '--port', '{port}', '--gateway-port', '0'] and s['tool_dirs'][:2] == ['~/.local/bin', '/opt/homebrew/bin']

def test_the_hooks_name_each_extra_and_the_old_apps_document_types():
    x = L.extra_reqs()
    assert set(x) == set(L.t.extras) and any(r.startswith('llama-cpp-python') for r in x['llama']) and x['langserver']
    p = L.hook('plist')()
    assert p['CFBundleDocumentTypes'][0]['LSItemContentTypes'] == ['public.folder'] and p['UTImportedTypeDeclarations']
    assert set(L.hooks.EXTRA_CHECK) == set(L.t.extras) and all(L.hook(n) for n in ('checks', 'smoke', 'prepare', 'prepare_steps', 'hold_open', 'copy_checks'))

def test_the_test_code_hash_covers_leelas_checks(tmp_path, monkeypatch):
    a = L.test_code_hash()
    (h := tmp_path/'hooks.py').write_text((ROOT/'tools'/'lock_hooks.py').read_text() + '\n# changed\n')
    monkeypatch.setattr(L.t, 'hooks', str(h))
    assert L.test_code_hash() != a, 'a record from other checks is refused at publish'

def _make(*args, env=None):
    e = {k: v for k, v in os.environ.items() if k not in ('V', 'N', 'WHEEL', 'DIR')} | (env or {})
    return subprocess.run(['make', '-C', str(ROOT), *args], capture_output=True, text=True, env=e, timeout=60)

@pytest.mark.parametrize('target,msg', [('lock', 'make lock V='), ('lock-promote', 'make lock-promote N='), ('ship-app', 'make ship-app V='), ('lock-wheel', 'make lock-wheel V=')])
def test_targets_that_need_a_value_refuse_without_it(target, msg):
    p = _make(target)
    assert p.returncode != 0 and msg in p.stderr

def test_ship_app_refuses_a_version_that_is_not_one():
    p = _make('ship-app', env={'V': '1.0;rm'})
    assert p.returncode != 0 and 'version such as' in p.stderr

def _wheel(d, name, v):
    import base64, hashlib, zipfile
    fn = d/f'{name}-{v}-py3-none-any.whl'
    meta = {f'{name}-{v}.dist-info/METADATA': f'Metadata-Version: 2.1\nName: {name}\nVersion: {v}\n',
            f'{name}-{v}.dist-info/WHEEL': 'Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n', f'{name}/__init__.py': ''}
    rec = ''.join(f"{k},sha256={base64.urlsafe_b64encode(hashlib.sha256(v_.encode()).digest()).rstrip(b'=').decode()},{len(v_)}\n" for k, v_ in meta.items())
    with zipfile.ZipFile(fn, 'w') as z:
        for k, v_ in meta.items(): z.writestr(k, v_)
        z.writestr(f'{name}-{v}.dist-info/RECORD', rec + f'{name}-{v}.dist-info/RECORD,,\n')
    return fn

def test_the_cooldown_holds_back_a_new_third_party_release_and_not_an_owner_one(tmp_path):
    "Against a local index: an owner's release from yesterday is locked, a third-party one is held back."
    import hashlib, threading, tomllib
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    uv = ROOT/'packaging'/'mac'/'build'/'uv'/'uv'
    if not uv.is_file(): pytest.skip('no pinned uv: make -C packaging/mac uv-fetch')
    at = K.now()
    files, d, hits = {}, tmp_path/'files', []; d.mkdir()
    for name in ('ownpkg', 'thirdpkg'):
        for v, age in (('1.0', 30), ('1.1', 1)):
            w = _wheel(d, name, v)
            files.setdefault(name, []).append(dict(filename=w.name, url=f'/files/{w.name}', hashes={'sha256': hashlib.sha256(w.read_bytes()).hexdigest()}, **{'upload-time': K.iso(at - timedelta(days=age))}))
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            parts = self.path.strip('/').split('/')
            if parts[0] == 'simple' and parts[1] in files: b, ct = json.dumps({'meta': {'api-version': '1.1'}, 'name': parts[1], 'files': files[parts[1]]}).encode(), 'application/vnd.pypi.simple.v1+json'
            elif parts[0] == 'files' and (d/parts[1]).is_file(): b, ct = (d/parts[1]).read_bytes(), 'application/octet-stream'
            else: self.send_response(404); self.end_headers(); return
            self.send_response(200); self.send_header('Content-Type', ct); self.send_header('Content-Length', str(len(b))); self.end_headers()
            if self.command == 'GET': self.wfile.write(b)
        do_HEAD = do_GET
        def log_message(self, *a): pass
    srv = ThreadingHTTPServer(('127.0.0.1', 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        u = tomllib.loads(L.pyproject('0.1.23', f'{L.dl}/x.whl', {x: [] for x in L.t.extras}, ['ownpkg'], at))['tool']['uv']
        (p := tmp_path/'proj').mkdir()
        (p/'pyproject.toml').write_text(f'''[project]\nname = "t"\nversion = "0"\nrequires-python = ">=3.12"\ndependencies = ["ownpkg", "thirdpkg"]\n[tool.uv]\npackage = false
exclude-newer = "{u['exclude-newer']}"\nexclude-newer-package = {{ ownpkg = "{u['exclude-newer-package']['ownpkg']}" }}\n''')
        env = L.child_env(cache=tmp_path/'cache', python=tmp_path/'py', python_version='3.12', env=tmp_path/'env') | {'UV_PYTHON_PREFERENCE': 'system', 'UV_PYTHON': sys.executable, 'NO_PROXY': '127.0.0.1,localhost', 'no_proxy': '127.0.0.1,localhost'}
        env.pop('UV_FROZEN')
        index = ['--default-index', f'http://127.0.0.1:{srv.server_address[1]}/simple']
        r = subprocess.run([uv, 'lock', '--project', p, *index, *K.cooldown_args(p)], env=env, capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, (r.stderr, hits)
        got = {x['name']: x['version'] for x in tomllib.loads((p/'uv.lock').read_text())['package']}
        assert got['ownpkg'] == '1.1' and got['thirdpkg'] == '1.0' and tomllib.loads((p/'uv.lock').read_text())['options']['exclude-newer']
        r = subprocess.run([uv, 'lock', '--project', p, '--upgrade', *index], env=env, capture_output=True, text=True, timeout=120)
        got = {x['name']: x['version'] for x in tomllib.loads((p/'uv.lock').read_text())['package']}
        assert got['thirdpkg'] == '1.1', 'UV_NO_CONFIG drops the [tool.uv] cooldown: without the flags the new release gets in'
    finally: srv.shutdown()
