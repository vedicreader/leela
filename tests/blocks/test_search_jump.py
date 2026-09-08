"""Where a jump hit says it is."""

from __future__ import annotations
import re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
import build_ide_js as builder                                              # noqa: E402

from leela.blocks.search.search import Hit, Search                          # noqa: E402
from leela.blocks.fs.fs import Sandbox                                      # noqa: E402

def test_a_hit_carries_the_module_it_is_in():
    assert 'module' in Hit(path='x', line=1, text='').dict()

def test_a_site_packages_path_becomes_a_dotted_module(tmp_path):
    sp = tmp_path/'lib'/'python3.12'/'site-packages'
    (sp/'chonkie'/'types').mkdir(parents=True)
    s = Search(Sandbox([tmp_path]))
    roots = [sp]
    assert s.env_module(sp/'fastcore'/'basics.py', roots) == 'fastcore.basics'
    assert s.env_module(sp/'chonkie'/'types'/'document.py', roots) == 'chonkie.types.document'
    assert s.env_module(sp/'exhash'/'__init__.py', roots) == 'exhash', '`__init__` is its folder'
    assert s.env_module(tmp_path/'mine'/'app.py', roots) == '', 'a project file has no module here'
