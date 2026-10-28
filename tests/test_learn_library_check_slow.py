import os, pwd, shutil, time
from pathlib import Path
import pytest
from leela.blocks.learn.tools import LIBRARY_TOTAL, library_check, make_tool_env, tool_indexed

pytestmark = [pytest.mark.slow, pytest.mark.skipif(not (os.getenv('LEELA_NET_TESTS') == '1' and shutil.which('uv')), reason='needs uv and LEELA_NET_TESTS=1')]
SPEC = dict(fname='f', tests=['assert f() == 1'])

@pytest.fixture(scope='module')
def home(tmp_path_factory): return str(tmp_path_factory.mktemp('data'))

@pytest.fixture(scope='module')
def made(home):
    mp = pytest.MonkeyPatch(); mp.setenv('XDG_DATA_HOME', home)
    try: r = make_tool_env(['six'])
    finally: mp.undo()
    assert r.ok, r.error
    return r.key

@pytest.fixture
def key(made, home, monkeypatch, abhyasa_cfg):
    monkeypatch.setenv('XDG_DATA_HOME', home)
    return made

def statuses(r): return [c['status'] for c in r.get('checks', [])]

def test_the_asyncio_socket_pair_passes(key):
    assert statuses(library_check(SPEC, 'import six, asyncio\ndef f():\n    return asyncio.run(asyncio.sleep(0, result=1))', key)) == ['pass']

def test_a_write_inside_the_work_folder_is_allowed(key):
    real = Path(pwd.getpwuid(os.getuid()).pw_dir)/'leela-x'   # the account's home, whatever HOME says
    assert not real.exists()
    src = 'import os\nopen("x.txt", "w").write("x")\nopen(os.path.expanduser("~/leela-x"), "w").write("x")\ndef f(): return 1'
    assert statuses(library_check(SPEC, src, key)) == ['pass']
    assert not real.exists(), 'the check wrote into the real home'

def test_the_made_environment_has_a_kosha_index_that_find_code_reads(key):
    from leela.blocks.learn.app import find_code
    assert tool_indexed(key)
    rows = find_code(None, 'with_metaclass', ['six'], tool=key)
    assert any(r['name'] == 'with_metaclass' and r['package'] == 'six' for r in rows or []), rows

@pytest.mark.parametrize('bad', ['import socket\ns = socket.socket(socket.AF_UNIX)\ns.connect("/tmp/x")\ndef f(): return 1',
                                 'import socket\nsocket.create_connection(("1.1.1.1", 53))\ndef f(): return 1',
                                 'import subprocess\nsubprocess.run(["true"])\ndef f(): return 1',
                                 'open(OUTSIDE, "w").write("x")\ndef f(): return 1',
                                 'print(\'{"v": 1, "found": true, "timeout": false, "checks": [{"i": 0, "status": "pass"}]}\')\nimport sys; sys.exit(0)'])
def test_a_hostile_source_does_not_pass(key, bad, tmp_path):
    out = tmp_path/'outside'
    r = library_check(SPEC, bad.replace('OUTSIDE', repr(str(out))), key)
    assert r.get('error') or r.get('timeout') or statuses(r) != ['pass'], bad
    assert not out.exists()

def test_a_slow_test_times_out_on_its_own(key):
    started = time.monotonic()
    r = library_check(SPEC, 'def f():\n    while True: pass', key)
    assert statuses(r) == ['timeout'] and time.monotonic() - started < 2 + 5

def test_an_endless_source_stops_near_the_total(key):
    started = time.monotonic()
    assert library_check(SPEC, 'while True: pass', key) == {'timeout': True}
    assert time.monotonic() - started < LIBRARY_TOTAL + 2 + 5   # the runner stops the process at total + 2 s
