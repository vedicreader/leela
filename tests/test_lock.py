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
    (d/'uv.lock').write_text('version = 1\n' + '\n'.join(rows))
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
    (_pkg('g', fn='g-1.0-cp312-cp312-manylinux_2_17_x86_64.whl'), 'no wheel'),
    (_pkg('h', fn='h-1.0-cp311-cp311-macosx_11_0_arm64.whl'), 'no wheel'),
    (_pkg(L.LLAMA['name'], f'{{ url = "{L.LLAMA["url"]}" }}'), 'not the pinned wheel'),
])
def test_a_lock_the_app_cannot_install_is_refused(tmp_path, pkg, why):
    got = L.check(_lock(tmp_path, pkgs=[pkg]))
    assert any(why in w for w in got), got

@pytest.mark.parametrize('fn', ['a-1.0-cp312-cp312-macosx_11_0_arm64.whl', 'a-1.0-cp39-abi3-macosx_10_12_universal2.whl', 'a-1.0-py3-none-any.whl',
                                'a-1.0-cp312-cp312-macosx_10_13_x86_64.macosx_11_0_arm64.whl'])
def test_wheels_that_fit_cpython_312_on_arm64(fn): assert L.wheel_fits(fn)

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
    assert p['project']['requires-python'] == '==3.12.*' and p['project']['dependencies'] == ['leela==0.1.23']
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
    assert s['server']['PYTHONNOUSERSITE'] == '1' and s['path_first'] == ['{env}/bin'] and s['api'] == L.LAUNCHER_API
    assert s['sync'][:3] == ['sync', '--frozen', '--no-install-project'] and s['inexact'] == ['--inexact']

def test_the_child_env_drops_the_parents_python_and_uv_settings():
    e = L.child_env(dict(PATH='/usr/bin', VIRTUAL_ENV='/v', UV_INDEX_URL='x', PYTHONPATH='p', LEELA_HOST_TOKEN='t', HOME='/h'),
                    cache='/c', python='/py', python_version='3.12.16', env='/e')
    assert 'VIRTUAL_ENV' not in e and 'UV_INDEX_URL' not in e and 'PYTHONPATH' not in e and 'LEELA_HOST_TOKEN' not in e
    assert e['UV_PROJECT_ENVIRONMENT'] == '/e' and e['UV_PYTHON'] == '3.12.16' and e['UV_NO_CONFIG'] == '1' and e['HOME'] == '/h'
    s = L.server_env(dict(PATH='/usr/bin'), cache='/c', python='/py', python_version='3.12.16', env='/e')
    assert s['PATH'].startswith('/e/bin:') and s['VIRTUAL_ENV'] == '/e' and s['PYTHONNOUSERSITE'] == '1'
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
