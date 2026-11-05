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
