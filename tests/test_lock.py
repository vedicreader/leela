"The environment lock of the thin Mac app: its hash, the checks that refuse a lock, the test record, signing, and the make targets."

import importlib.util, json, os, shutil, subprocess, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('lockpy', ROOT/'tools'/'lock.py')
L = importlib.util.module_from_spec(spec); spec.loader.exec_module(L)

def _lock(d, extras=('mlx', 'llama', 'langserver'), pkgs=(), env=True, deps=('leela',), llama_in_base=False):
    "A small lock folder: the pinned project and a uv.lock with `pkgs` beside leela-lock and leela."
    d = Path(d); d.mkdir(parents=True, exist_ok=True)
    req = f'required-environments = ["{L.MARKER}"]' if env else ''
    (d/'pyproject.toml').write_text(f'[project]\nname = "leela-lock"\n[tool.uv]\n{req}\n')
    (d/'.python-version').write_text(L.PYTHON + '\n')
    whl = lambda n, v: f'{{ url = "https://files.pythonhosted.org/x/{n}-{v}-py3-none-any.whl", hash = "sha256:00", size = 10 }}'
    root_deps = ', '.join(f'{{ name = "{n}" }}' for n in deps)
    opt = '\n'.join(f'{x} = [{{ name = "{x}-pkg" }}]' for x in extras)
    rows = [f'[[package]]\nname = "leela-lock"\nversion = "0"\nsource = {{ virtual = "." }}\ndependencies = [{root_deps}]\n[package.optional-dependencies]\n{opt}\n',
            f'[[package]]\nname = "leela"\nversion = "0.1.23"\nsource = {{ url = "{L.DL}/0.1.23/leela-0.1.23-py3-none-any.whl" }}\n'
            f'dependencies = [{"{ name = " + chr(34) + L.LLAMA["name"] + chr(34) + " }" if llama_in_base else ""}]\nwheels = [{whl("leela", "0.1.23")}]\n']
    rows += [f'[[package]]\nname = "{x}-pkg"\nversion = "1.0"\nsource = {{ registry = "https://pypi.org/simple" }}\nwheels = [{whl(x, "1.0")}]\n' for x in extras]
    rows += list(pkgs)
    (d/'uv.lock').write_text('version = 1\n[options]\nexclude-newer = "2026-10-30T00:00:00Z"\n\n' + '\n'.join(rows))
    return d

def _pkg(name, source='{ registry = "https://pypi.org/simple" }', wheels=True, fn=None):
    w = f'wheels = [{{ url = "https://x/{fn or name + "-1.0-py3-none-any.whl"}", hash = "sha256:00", size = 5 }}]\n' if wheels else 'sdist = { url = "https://x/a.tar.gz" }\n'
    return f'[[package]]\nname = "{name}"\nversion = "1.0"\nsource = {source}\n{w}'

# Hash

def test_the_hash_is_stable_and_names_each_file_and_the_uv_version(tmp_path):
    d = _lock(tmp_path/'a')
    h = L.lock_hash(d, '0.13.6')
    assert h == L.lock_hash(d, '0.13.6') and len(h) == 64
    assert L.lock_hash(d, '0.13.7') != h, 'a new uv builds another env'
    (d/'.python-version').write_text('3.12.15\n')
    assert L.lock_hash(d, '0.13.6') != h

def test_the_hash_is_what_the_launcher_computes(tmp_path):
    "EnvStoreTests.swift pins the same value for the same bytes."
    (tmp_path/'pyproject.toml').write_text('p'); (tmp_path/'uv.lock').write_text('l'); (tmp_path/'.python-version').write_text('3.12.16\n')
    assert L.lock_hash(tmp_path, '0.13.6') == '2b6ad4d75869cd770d5cf35be37c47dc40fe7cfce61490729959b38333e9472a'

# Checks

def test_a_good_lock_passes(tmp_path): assert L.check(_lock(tmp_path)) == []

@pytest.mark.parametrize('pkg,why', [
    (_pkg('a', '{ editable = "../a" }'), 'editable'),
    (_pkg('b', '{ git = "https://github.com/x/b?rev=1#abc" }'), 'git'),
    (_pkg('c', '{ registry = "https://test.pypi.org/simple" }'), 'test.pypi.org'),
    (_pkg('d', '{ url = "https://example.com/d.whl" }'), 'URL'),
    (_pkg('e', '{ path = "/tmp/e.whl" }'), 'local path'),
    (_pkg('f', wheels=False), 'no wheel'),
    (_pkg('g', fn='g-1.0-cp313-cp313-manylinux_2_17_x86_64.whl'), 'no wheel'),
    (_pkg('g2', fn='g2-1.0-cp312-cp312-macosx_11_0_arm64.whl'), 'no wheel'),
    (_pkg('h', fn='h-1.0-cp311-cp311-macosx_11_0_arm64.whl'), 'no wheel'),
    (_pkg(L.LLAMA['name'], f'{{ url = "{L.LLAMA["url"]}" }}'), 'not the pinned wheel'),
])
def test_a_lock_the_app_cannot_install_is_refused(tmp_path, pkg, why):
    got = L.check(_lock(tmp_path, pkgs=[pkg]))
    assert any(why in w for w in got), got

@pytest.mark.parametrize('fn', ['a-1.0-cp313-cp313-macosx_11_0_arm64.whl', 'a-1.0-cp39-abi3-macosx_10_12_universal2.whl', 'a-1.0-py3-none-any.whl',
                                'a-1.0-cp313-cp313-macosx_10_13_x86_64.macosx_11_0_arm64.whl'])
def test_wheels_that_fit_cpython_313_on_arm64(fn): assert L.wheel_fits(fn)

def test_the_lock_python_is_the_old_apps_minor():
    "A kernel on a project's own 3.13 borrowed Leela's packages in the old app; kunda's bootstrap shares them only within one minor."
    assert L.MINOR == '3.13' and L.CP == 'cp313' and not L.wheel_fits('a-1.0-cp312-cp312-macosx_11_0_arm64.whl')

def test_the_pinned_llama_wheel_is_allowed_only_in_its_extra(tmp_path):
    llama = (f'[[package]]\nname = "{L.LLAMA["name"]}"\nversion = "{L.LLAMA["version"]}"\nsource = {{ url = "{L.LLAMA["url"]}" }}\n'
             f'wheels = [{{ url = "{L.LLAMA["url"]}", hash = "sha256:{L.LLAMA["sha256"]}" }}]\n')
    assert L.check(_lock(tmp_path/'ok', pkgs=[llama])) == []
    got = L.check(_lock(tmp_path/'base', pkgs=[llama], llama_in_base=True))
    assert any('base environment' in w for w in got)

def test_leela_from_a_local_wheel_is_only_for_a_test(tmp_path):
    d = _lock(tmp_path)
    (d/'uv.lock').write_text((d/'uv.lock').read_text().replace(f'url = "{L.DL}/0.1.23/leela-0.1.23-py3-none-any.whl" }}\ndep', 'path = "/tmp/leela.whl" }\ndep'))
    assert any('local path' in w for w in L.check(d)) and L.check(d, local=True) == []

def test_extras_and_the_required_environment_must_be_there(tmp_path):
    assert any('extras missing' in w for w in L.check(_lock(tmp_path/'a', extras=('mlx',))))
    assert any('required-environments' in w for w in L.check(_lock(tmp_path/'b', env=False)))

def test_the_pinned_project_pins_extras_and_exempts_the_owners_packages(tmp_path):
    at = datetime(2026, 11, 6, tzinfo=timezone.utc)
    t = L.pyproject('0.1.23', f'{L.DL}/0.1.23/leela-0.1.23-py3-none-any.whl', {'mlx': ['mlx-lm>=0.31'], 'llama': ['llama-cpp-python==0.3.30'], 'langserver': ['basedpyright>=1.39']}, ['ramabana'], at)
    import tomllib
    p = tomllib.loads(t)
    assert p['project']['requires-python'] == '==3.13.*' and p['project']['dependencies'] == ['leela==0.1.23']
    assert p['tool']['uv']['required-environments'] == [L.MARKER] and p['tool']['uv']['exclude-newer'] == '2026-10-30T00:00:00Z'
    assert p['tool']['uv']['exclude-newer-package'] == {'ramabana': '2026-11-06T00:00:00Z'}
    assert p['tool']['uv']['sources']['llama-cpp-python'] == {'url': L.LLAMA['url']}
    (tmp_path/'uv.lock').write_text('version = 1\n[[package]]\nname = "mlx-lm"\nversion = "0.32.2"\n[[package]]\nname = "basedpyright"\nversion = "1.40.2"\n[[package]]\nname = "llama-cpp-python"\nversion = "0.3.30"\n')
    pinned = tomllib.loads(L._pin_extras(t, tmp_path))['project']['optional-dependencies']
    assert pinned == {'mlx': ['mlx-lm==0.32.2'], 'llama': ['llama-cpp-python==0.3.30'], 'langserver': ['basedpyright==1.40.2']}

# childenv.json: the one spec Swift and Python both read

def test_childenv_has_what_the_plan_names():
    s = json.loads(L.CHILDENV.read_text())
    assert {'VIRTUAL_ENV', 'CONDA_PREFIX', 'PYTHONHOME', 'PYTHONPATH', 'PYTHONSTARTUP', 'PYTHONUSERBASE'} <= set(s['drop']) and 'UV_' in s['drop_prefixes']
    assert s['uv'] | {} == s['uv'] and {'UV_NO_CONFIG', 'UV_CACHE_DIR', 'UV_PYTHON_INSTALL_DIR', 'UV_PYTHON_PREFERENCE', 'UV_PYTHON', 'UV_PROJECT_ENVIRONMENT', 'UV_FROZEN', 'UV_NO_PROGRESS', 'UV_LINK_MODE'} == set(s['uv'])
    assert s['server'] == {'PYTHONUNBUFFERED': '1'} and 'path_first' not in s and s['api'] == L.LAUNCHER_API
    assert s['sync'][:3] == ['sync', '--frozen', '--no-install-project'] and s['inexact'] == ['--inexact']

def test_the_child_env_drops_the_parents_python_and_uv_settings():
    e = L.child_env(dict(PATH='/usr/bin', VIRTUAL_ENV='/v', UV_INDEX_URL='x', PYTHONPATH='p', LEELA_HOST_TOKEN='t', HOME='/h'),
                    cache='/c', python='/py', python_version='3.12.16', env='/e')
    assert 'VIRTUAL_ENV' not in e and 'UV_INDEX_URL' not in e and 'PYTHONPATH' not in e and 'LEELA_HOST_TOKEN' not in e
    assert e['UV_PROJECT_ENVIRONMENT'] == '/e' and e['UV_PYTHON'] == '3.12.16' and e['UV_NO_CONFIG'] == '1' and e['HOME'] == '/h'
    s = L.server_env(dict(PATH='/usr/bin:/x', VIRTUAL_ENV='/v', UV_INDEX_URL='x', OPENAI_API_KEY='k'))
    assert not [k for k in s if k.startswith('UV_')] and 'VIRTUAL_ENV' not in s and 'PYTHONNOUSERSITE' not in s and 'NO_COLOR' not in s, 'kernels and shells inherit it'
    assert s['PATH'].startswith(os.path.expanduser('~/.local/bin') + ':/opt/homebrew/bin') and s['PATH'].endswith(':/x') and s['OPENAI_API_KEY'] == 'k'
    o = L.server_env_1_0('/e', dict(PATH='/usr/bin'), cache='/c', python='/py', python_version='3.12.16')
    assert o['PATH'].startswith('/e/bin:') and o['VIRTUAL_ENV'] == '/e' and o['PYTHONNOUSERSITE'] == '1' and o['UV_PROJECT_ENVIRONMENT'] == '/e'
    assert L.sync_args('/l', ['mlx', 'llama']) == ['sync', '--frozen', '--no-install-project', '--project', '/l', '--extra', 'mlx', '--extra', 'llama']
    assert L.sync_args('/l', ['mlx'], inexact=True)[-3:] == ['--inexact', '--extra', 'mlx']

def test_the_manifest_has_the_documented_keys(tmp_path):
    d = _lock(tmp_path)
    m = L.manifest(d, 4, '0.13.6')
    assert set(m) == {'n', 'hash', 'files', 'leela', 'python', 'uv_min', 'launcher_api_min', 'platform', 'macos_min', 'download_bytes'}
    assert set(m['files']) == set(L.FILES) and m['leela'] == '0.1.23' and m['platform'] == 'darwin-arm64'
    doc = (ROOT/'docs'/'thin-app.md').read_text()
    assert all(f'`{k}`' in doc for k in m), 'docs/thin-app.md names every manifest key'

# Test records and lock-publish refusals

def _record(d, h, **kw):
    (d/'tested').mkdir(exist_ok=True)
    r = dict(hash=h, passed=True, uv=L.pinned_version(), test_code=L.test_code_hash(), time=L.iso(L.now())) | kw
    (d/'tested'/f'{h}.json').write_text(json.dumps(r))

@pytest.mark.parametrize('kw,why', [({}, ''), ({'passed': False}, 'did not pass'), ({'uv': '0.1.0'}, 'not the pinned'),
                                    ({'test_code': 'x'}, 'changed since the test'),
                                    ({'time': L.iso(L.now() - timedelta(days=8))}, 'days old')])
def test_a_test_record_must_pass_be_fresh_and_match_uv_and_the_test_code(tmp_path, kw, why):
    _record(tmp_path, 'h', **kw)
    r, msg = L.record_for('h', tmp_path)
    assert (r is not None) == (not why) and why in msg
    assert L.record_for('other', tmp_path)[1].startswith('no test record')

def test_publish_refuses_an_untested_lock_a_dirty_tree_and_a_downgrade(tmp_path, monkeypatch):
    d = _lock(tmp_path/'lock')
    monkeypatch.setattr(L, 'tree_clean', lambda: 'the git tree has changes that are not committed')
    monkeypatch.setattr(L, 'key_paths', lambda home=None: [tmp_path/'none'])
    why = L.refusals(d, {'leela': '0.2.0'}, keys_pub=tmp_path/'none.pub')
    assert any('not committed' in w for w in why) and any('no test record' in w for w in why)
    assert any('lower than the published' in w for w in why) and any('lock-key' in w for w in why)
    assert not any('lower than' in w for w in L.refusals(d, {'leela': '0.2.0'}, allow_downgrade=True))

def test_publish_stops_before_any_network_call_when_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(L, 'channel', lambda *a, **kw: pytest.fail('no network before the local refusals pass'))
    monkeypatch.setattr(L, 'tree_clean', lambda: 'dirty')
    with pytest.raises(SystemExit, match='lock-publish refuses'): L.publish(_lock(tmp_path/'lock'), keys_pub=tmp_path/'k.pub')

def test_a_failed_build_writes_no_passing_record(tmp_path, monkeypatch):
    fake = tmp_path/'uv'
    fake.write_text(f'#!/bin/sh\nif [ "$1" = "--version" ]; then echo "uv {L.pinned_version()}"; exit 0; fi\necho "no network" >&2; exit 2\n'); fake.chmod(0o755)
    monkeypatch.setenv('LEELA_UV', str(fake))
    d = _lock(tmp_path/'lock')
    rec = L.lock_test(d, fresh=True, record_dir=tmp_path/'records')
    assert not rec['passed'] and rec['results'][0]['step'] == 'uv sync' and 'no network' in rec['results'][0]['error']
    assert not (tmp_path/'records').exists()

def test_the_pinned_uv_must_be_the_pinned_version(tmp_path, monkeypatch):
    fake = tmp_path/'uv'; fake.write_text('#!/bin/sh\necho "uv 0.0.1"\n'); fake.chmod(0o755)
    monkeypatch.setenv('LEELA_UV', str(fake))
    with pytest.raises(SystemExit, match='not the pinned'): L.pinned_uv()

# Signing: real ssh-keygen, throwaway keys, a temporary HOME; never ~/.ssh, the agent or the keychain

needs_keygen = pytest.mark.skipif(not shutil.which('ssh-keygen'), reason='no ssh-keygen')

@needs_keygen
def test_lock_key_makes_both_keys_refuses_to_overwrite_and_prints_them(tmp_path, capsys):
    home = tmp_path/'home'; home.mkdir()
    pubs = L.lock_key(home=home, keys_out=tmp_path/'keys.pub', passphrase=False, agent=False)
    main, emergency = L.key_paths(home)
    assert main.is_file() and emergency.is_file() and pubs.count('ssh-ed25519') == 2 and (tmp_path/'keys.pub').read_text() == pubs
    assert oct(main.stat().st_mode & 0o777) == '0o600' and oct(main.parent.stat().st_mode & 0o777) == '0o700'
    with pytest.raises(SystemExit, match='refusing to overwrite'): L.lock_key(home=home, passphrase=False, agent=False)

@needs_keygen
def test_a_signed_lock_verifies_and_a_changed_byte_or_another_key_does_not(tmp_path, monkeypatch):
    home = tmp_path/'home'; home.mkdir()
    L.lock_key(home=home, keys_out=tmp_path/'keys.pub', passphrase=False, agent=False)
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('SSH_AUTH_SOCK', str(tmp_path/'no-agent'))
    d = _lock(tmp_path/'lock')
    (d/'manifest.json').write_text(L.dumps(L.manifest(d, 3, '0.13.6')))
    L.sign(d/'manifest.json', L.key_paths(home)[0]).rename(d/'manifest.sig')
    assert L.check_lock_dir(d, tmp_path/'keys.pub')['n'] == 3
    with pytest.raises(SystemExit, match='not newer'): L.check_lock_dir(d, tmp_path/'keys.pub', highest=3)
    (d/'uv.lock').write_text((d/'uv.lock').read_text() + '\n')
    with pytest.raises(SystemExit, match='does not match the manifest'): L.check_lock_dir(d, tmp_path/'keys.pub')
    other = tmp_path/'other'; other.mkdir()
    L.lock_key(home=other, keys_out=tmp_path/'other.pub', passphrase=False, agent=False)
    assert not L.verify_sig(d/'manifest.json', d/'manifest.sig', tmp_path/'other.pub')

# Make targets

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

# The cooldown, against a local index: an owner's package newer than 7 days is locked, a third-party one is held back

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
    import hashlib, threading, tomllib
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    uv = ROOT/'packaging'/'mac'/'build'/'uv'/'uv'
    if not uv.is_file(): pytest.skip('no pinned uv: make -C packaging/mac uv-fetch')
    at = L.now()
    files, d, hits = {}, tmp_path/'files', []; d.mkdir()
    for name in ('ownpkg', 'thirdpkg'):
        for v, age in (('1.0', 30), ('1.1', 1)):
            w = _wheel(d, name, v)
            files.setdefault(name, []).append(dict(filename=w.name, url=f'/files/{w.name}', hashes={'sha256': hashlib.sha256(w.read_bytes()).hexdigest()},
                                                   **{'upload-time': L.iso(at - timedelta(days=age))}))
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            parts = self.path.strip('/').split('/')
            if parts[0] == 'simple' and parts[1] in files:
                b, ct = json.dumps({'meta': {'api-version': '1.1'}, 'name': parts[1], 'files': files[parts[1]]}).encode(), 'application/vnd.pypi.simple.v1+json'
            elif parts[0] == 'files' and (d/parts[1]).is_file(): b, ct = (d/parts[1]).read_bytes(), 'application/octet-stream'
            else: self.send_response(404); self.end_headers(); return
            self.send_response(200); self.send_header('Content-Type', ct); self.send_header('Content-Length', str(len(b))); self.end_headers()
            if self.command == 'GET': self.wfile.write(b)
        do_HEAD = do_GET
        def log_message(self, *a): pass
    srv = ThreadingHTTPServer(('127.0.0.1', 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        u = tomllib.loads(L.pyproject('0.1.23', f'{L.DL}/x.whl', {x: [] for x in L.EXTRAS}, ['ownpkg'], at))['tool']['uv']
        (p := tmp_path/'proj').mkdir()
        (p/'pyproject.toml').write_text(f'''[project]\nname = "t"\nversion = "0"\nrequires-python = ">=3.12"\ndependencies = ["ownpkg", "thirdpkg"]\n[tool.uv]\npackage = false
exclude-newer = "{u['exclude-newer']}"\nexclude-newer-package = {{ ownpkg = "{u['exclude-newer-package']['ownpkg']}" }}\n''')
        env = L.child_env(cache=tmp_path/'cache', python=tmp_path/'py', python_version='3.12', env=tmp_path/'env') | {'UV_PYTHON_PREFERENCE': 'system', 'UV_PYTHON': sys.executable, 'NO_PROXY': '127.0.0.1,localhost', 'no_proxy': '127.0.0.1,localhost'}
        env.pop('UV_FROZEN')
        index = ['--default-index', f'http://127.0.0.1:{srv.server_address[1]}/simple']
        r = subprocess.run([uv, 'lock', '--project', p, *index, *L.cooldown_args(p)], env=env, capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, (r.stderr, hits)
        got = {x['name']: x['version'] for x in tomllib.loads((p/'uv.lock').read_text())['package']}
        assert got['ownpkg'] == '1.1' and got['thirdpkg'] == '1.0'
        assert tomllib.loads((p/'uv.lock').read_text())['options']['exclude-newer'], 'the lock records the cooldown'
        r = subprocess.run([uv, 'lock', '--project', p, '--upgrade', *index], env=env, capture_output=True, text=True, timeout=120)
        got = {x['name']: x['version'] for x in tomllib.loads((p/'uv.lock').read_text())['package']}
        assert got['thirdpkg'] == '1.1', 'UV_NO_CONFIG drops the [tool.uv] cooldown: without the flags the new release gets in'
    finally: srv.shutdown()

def test_a_pointer_names_its_channel_and_an_old_expires_field_is_ignored(tmp_path, monkeypatch):
    p = L.pointer(4, 'ab', 'channel-test')
    assert p['channel'] == 'channel-test' and p['n'] == 4 and 'expires' not in p
    monkeypatch.setattr(L, 'verify_sig', lambda *a: True)
    def serve(body): monkeypatch.setattr(L, 'fetch', lambda url, dst=None: Path(dst).write_text(json.dumps(body)) if dst else None)
    serve(p)
    with pytest.raises(SystemExit, match='pointer for channel-test'): L.channel('channel', tmp_path/'k')
    serve(p | {'expires': '2020-01-01T00:00:00Z'})
    assert L.channel('channel-test', tmp_path/'k')['n'] == 4, 'a pointer with no change for months is still good'
    serve(p)
    assert L.channel('channel-test', tmp_path/'k')['n'] == 4

def test_the_lock_tests_refuse_the_leela_the_person_runs(tmp_path):
    "A probe once reached the running app; the harness now refuses its ports, read from the real serving.json."
    (cfg := tmp_path/'.config'/'leela').mkdir(parents=True)
    (cfg/'serving.json').write_text(json.dumps({'pid': os.getpid(), 'port': 5999, 'ports': [6001]}))
    assert L.live_ports(tmp_path) == {5999, 6001}
    (cfg/'serving.json').write_text(json.dumps({'pid': 999999, 'port': 5999}))
    assert L.live_ports(tmp_path) == set(), 'a stale file names nobody'
    import unittest.mock as m
    with m.patch.object(L, 'live_ports', lambda: {5999}), pytest.raises(RuntimeError, match='the Leela you are running'): L._get('http://127.0.0.1:5999/health')
