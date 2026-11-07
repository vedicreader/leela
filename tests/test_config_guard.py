"A test run never writes the person's real `~/.config/leela`. See `REAL_WRITES` in `conftest.py`."

import os, subprocess, sys

from fastcore.xtras import Path, atomic_save

import conftest
from conftest import REAL_CONFIG_HOME, REAL_WRITES

def test_a_write_under_the_guarded_folder_is_caught(tmp_path):
    (cfg := tmp_path/'cfg').mkdir()
    was, n = list(conftest.GUARDED), len(REAL_WRITES)
    conftest.GUARDED[:] = [str(cfg)]
    try:
        (cfg/'workspace.json').write_text('{}'); (cfg/'d').mkdir()
        with atomic_save(cfg/'desktop.json', mode='w') as f: f.write('{}')
        (cfg/'workspace.json').read_text()
    finally: conftest.GUARDED[:] = was
    got = REAL_WRITES[n:]; del REAL_WRITES[n:]
    assert ('open', str(cfg/'workspace.json')) in got and ('os.mkdir', str(cfg/'d')) in got
    assert any(e == 'os.rename' and p == str(cfg/'desktop.json') for e, p in got), 'an atomic save is a write'
    assert sum(e == 'open' and p == str(cfg/'workspace.json') for e, p in got) == 1, 'a read is not'

def test_leela_and_any_server_it_spawns_point_away_from_the_real_config():
    import leela
    assert Path(os.environ['XDG_CONFIG_HOME']).resolve() != REAL_CONFIG_HOME.parent.resolve()
    assert not Path(leela.leela_cfg).resolve().is_relative_to(REAL_CONFIG_HOME.resolve())
    out = subprocess.run([sys.executable, '-c', 'import leela; print(leela.leela_cfg)'], capture_output=True, text=True,
                         stdin=subprocess.DEVNULL, timeout=60).stdout.strip()
    assert out and not Path(out).resolve().is_relative_to(REAL_CONFIG_HOME.resolve()), out

def test_isolate_moves_every_store_and_the_guard_covers_the_real_ones(tmp_path, monkeypatch):
    from tools.isolate import REAL_STORES, isolate, isolated_env
    import ramabana.core as rc
    for k in isolated_env(tmp_path): monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(rc, 'PROBE_DIR', rc.PROBE_DIR)
    assert isolate(tmp_path) == tmp_path
    for k in 'XDG_CONFIG_HOME XDG_DATA_HOME XDG_CACHE_HOME VISHALAKSHI_VAULT LEELA_SEARCH_VAULT ABHYASA_CONFIG RAMABANA_CONFIG'.split():
        assert Path(os.environ[k]).is_relative_to(tmp_path), k
    assert os.environ['LEELA_MEMORY_OFFLINE'] == '1'
    assert rc.probe_path('x').is_relative_to(tmp_path)
    home = Path.home()
    for p in ('.config/leela', '.local/share/leela', '.cache/leela', '.vishalakshi', '.config/ramabana', '.config/abhyasa'):
        assert home/p in REAL_STORES and str(home/p) in conftest.GUARDED, p

def test_the_suite_writes_no_ramabana_probe_to_the_real_folder():
    import ramabana.core as rc
    assert not rc.probe_path('x').is_relative_to(Path.home()/'.config'/'ramabana')

def test_the_keyring_is_a_fake_per_test(fake_keyring):
    import keyring
    keyring.set_password('leela-test', 'k', 'v')
    assert fake_keyring.get_password('leela-test', 'k') == 'v' and keyring.get_keyring() is fake_keyring
