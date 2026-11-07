"Keys saved on the vault API page go to the keychain, else a 0600 file, and never to a child process."

import os, subprocess, warnings
import pytest
from keyring.backends.fail import Keyring as Fail
from leela.blocks.vault.spec import Creds
from leela.core.envs import EnvStore, apply_stored_env, strip_keys

@pytest.fixture
def kc(fake_keyring): return fake_keyring   # conftest's in-memory keyring

def _creds(tmp_path): return Creds(path=tmp_path/'apicreds.json', store=EnvStore(service='leela-apis-test', path=str(tmp_path/'fake.env')))

def test_a_key_goes_to_the_keychain_and_nowhere_else(tmp_path, kc):
    c = _creds(tmp_path)
    c.set('stripe', {'Authorization': 'Bearer sk_live_x'})
    assert kc.d[('leela-apis-test', 'LEELA_API_STRIPE')] == 'Authorization: Bearer sk_live_x'
    assert 'LEELA_API_STRIPE' not in os.environ and not (tmp_path/'fake.env').exists()
    assert 'sk_live_x' not in subprocess.run(['/usr/bin/env'], capture_output=True, text=True).stdout
    assert c.get('stripe') == {'Authorization': 'Bearer sk_live_x'} and c.note == ''

def test_with_no_keychain_it_goes_to_a_0600_file_and_the_page_says_so(tmp_path, monkeypatch):
    import keyring.core
    monkeypatch.setattr(keyring.core, '_keyring_backend', Fail())
    c = _creds(tmp_path)
    with warnings.catch_warnings(): warnings.simplefilter('ignore'); c.set('stripe', {'Authorization': 'Bearer sk_live_x'})
    f = tmp_path/'fake.env'
    assert oct(f.stat().st_mode & 0o777) == '0o600' and 'sk_live_x' in f.read_text()
    assert 'no keychain' in c.note and str(f) in c.note
    assert 'LEELA_API_STRIPE' not in os.environ

def test_an_old_copy_in_the_env_file_moves_to_the_keychain(tmp_path, kc):
    c = _creds(tmp_path)
    c.file.write_text('{"stripe": {"headers": ["Authorization"], "refs": [], "reach": "cloud"}}')
    (tmp_path/'fake.env').write_text("LEELA_API_STRIPE='Authorization: Bearer old'\nOTHER=1\n")
    assert c.migrate() == ['LEELA_API_STRIPE']
    assert 'LEELA_API_STRIPE' not in (tmp_path/'fake.env').read_text() and 'OTHER' in (tmp_path/'fake.env').read_text()
    assert c.get('stripe') == {'Authorization': 'Bearer old'}

def test_no_child_gets_a_leela_api_name(monkeypatch):
    monkeypatch.setenv('LEELA_API_OLD', 'secret'); monkeypatch.setenv('KEEP_ME', '1')
    apply_stored_env()
    assert 'LEELA_API_OLD' not in os.environ and os.environ['KEEP_ME'] == '1'
    assert strip_keys({'LEELA_API_X': '1', 'PATH': '/bin'}) == {'PATH': '/bin'}

def test_the_terminal_gets_no_leela_api_name(monkeypatch, tmp_path):
    import leela.blocks.term.term as term
    seen = {}
    class Fake:
        pid = 1
        def __init__(self, argv, env=None, **kw): seen.update(env)
    monkeypatch.setattr(term, 'PtySession', Fake)
    term.Pty(argv=['/bin/sh'], cwd=str(tmp_path), env={'LEELA_API_X': 'secret', 'PATH': '/bin'}).start()
    assert 'LEELA_API_X' not in seen and seen['PATH'] == '/bin'
