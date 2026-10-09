"""`leela.core.inspectors` must keep agreeing with dhrishti, which owns both of these things."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

import pytest

from leela.core import inspectors

@pytest.fixture(scope='module')
def dhrishti():
    return pytest.importorskip('dhrishti.serving')


def test_a_live_entry_is_read_the_way_dhrishti_writes_it(dhrishti, monkeypatch, tmp_path):
    "Written by dhrishti's own `register`, read by Leela's copy: the format is the contract."
    monkeypatch.setenv('DHRISHTI_REG_DIR', str(tmp_path/'reg'))
    entry = dhrishti.register('probe', 8123)
    try:
        rows = inspectors.active()
        assert [r['base'] for r in rows] == [entry['base']]
        assert rows == dhrishti.active()
    finally: dhrishti.unregister(8123)

def test_a_dead_entry_is_pruned_rather_than_offered(monkeypatch, tmp_path):
    "A crashed kernel leaves its file behind; the reader is what notices."
    reg = tmp_path/'reg'; reg.mkdir(parents=True)
    monkeypatch.setenv('DHRISHTI_REG_DIR', str(reg))
    dead = subprocess.Popen([sys.executable, '-c', 'pass'])
    dead.wait()
    (reg/'9999.json').write_text(json.dumps({'name': 'gone', 'pid': dead.pid,
                                             'base': 'http://127.0.0.1:9999'}))
    assert inspectors.active() == []
    assert not (reg/'9999.json').exists(), 'the stale entry should have been swept'


HEAVY = ('pandas', 'IPython', 'numpy')

PROBE = textwrap.dedent('''
    import sys
    import leela.app, leela.workspace, leela.blocks.runtime.kernels
    print(','.join(sorted(m for m in %r if m in sys.modules)))
''')

def test_the_server_does_not_drag_the_kernels_scientific_stack_into_itself(tmp_path):
    """The regression this whole module exists to prevent."""
    env = {**os.environ, 'XDG_CONFIG_HOME': str(tmp_path), 'PYTHONPATH': os.getcwd()}
    out = subprocess.run([sys.executable, '-c', PROBE % (HEAVY,)],
                         capture_output=True, text=True, timeout=300, env=env)
    assert out.returncode == 0, out.stderr[-2000:]
    loaded = set(filter(None, out.stdout.strip().split(',')))
    # IPython arrives through `fasthtml.pico`, which `fast_app` imports unconditionally even
    # for `pico=False`; that one is upstream's to fix and is not what this test is guarding.
    assert loaded <= {'IPython'}, f'the server imported {sorted(loaded)}'

