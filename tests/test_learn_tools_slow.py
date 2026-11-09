import os, shutil, subprocess
import pytest
from leela.blocks.learn.toolenv import make_tool_env

pytestmark = pytest.mark.skipif(os.getenv('LEELA_NET_TESTS') != '1' or not shutil.which('uv'), reason='needs LEELA_NET_TESTS=1 and uv')

def test_a_real_environment_imports_its_package(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path/'data'))
    r = make_tool_env(['six'])
    assert r.ok, r.error
    assert subprocess.run([r.python, '-I', '-c', 'import six'], capture_output=True, stdin=subprocess.DEVNULL, timeout=60).returncode == 0
