"Every name Leela's Learn block imports from Abhyasa exists in the installed Abhyasa, and the host API is a usable number."
import ast, importlib
from pathlib import Path

import pytest

import leela.blocks.learn as learn_pkg
from leela.blocks.learn.tools import HOST_API_NEEDED

LEARN = Path(learn_pkg.__file__).parent

def imports():
    "(file, module, name) for each `from abhyasa... import name` in Learn's sources."
    out = []
    for f in sorted(LEARN.glob('*.py')):
        for n in ast.walk(ast.parse(f.read_text())):
            if isinstance(n, ast.ImportFrom) and n.module and n.module.split('.')[0] == 'abhyasa': out += [(f.name, n.module, a.name) for a in n.names]
    return out

def test_host_api_is_an_int_that_meets_what_leela_needs():
    from abhyasa.core.hostapi import HOST_API
    assert type(HOST_API) is int and HOST_API >= 1 and HOST_API >= HOST_API_NEEDED

def test_the_scan_finds_the_imports():
    assert len(imports()) > 20 and ('host.py', 'abhyasa.app', 'mk_app') in imports()

@pytest.mark.parametrize('f,mod,name', imports())
def test_the_name_exists_in_abhyasa(f, mod, name):
    m = importlib.import_module(mod)
    assert hasattr(m, name) or importlib.util.find_spec(f'{mod}.{name}'), f'{f}: {mod}.{name}'

def test_the_host_calls_beyond_imports_exist():
    "Names the host reaches by attribute: the engine entry points and the hooks `mk_app` takes."
    import inspect
    from abhyasa import agent_tools as at, learner
    from abhyasa.app import mk_app
    assert {'warm_speech', 'config', 'names', 'hosts', 'transcribe'} <= set(inspect.signature(mk_app).parameters)
    assert {'research', 'gather', 'settings', 'guard'} <= set(inspect.signature(at.create_walk).parameters)
    for n in ('create_walk', 'TOOLS', 'page_of'): assert hasattr(at, n)
    for n in ('use_settings', 'use_config'): assert hasattr(learner, n)


FIRST_HOST_API_RELEASE = (0, 0, 22)   # the first Abhyasa release with HOST_API

def test_the_abhyasa_pin_is_at_or_above_the_first_release_with_host_api():
    import re
    pin = re.search(r'"abhyasa>=([\d.]+)"', (LEARN.parents[2]/'pyproject.toml').read_text())
    assert pin and tuple(map(int, pin[1].split('.'))) >= FIRST_HOST_API_RELEASE
