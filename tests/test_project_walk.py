"""What a walk of a project actually contains.

An interpreter's libraries are not the project, and a walk that returns them buries the code in
somebody else's and spends its cap before reaching it.
"""

import sys

import pytest
from fastcore.all import Path
from starlette.testclient import TestClient

from leela.app import ide_app
from leela.workspace import Workspace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'tools'))
import build_ide_js as builder  # noqa: E402



def test_an_interpreters_libraries_are_not_the_project(tmp_path):
    """98% of a walk of this repo was site-packages, so `@keys` ranked `libxslt/keys.h` over
    `leela/core/keys.py` and the 20k cap was spent before the project was reached.

    A virtualenv is not always called `.venv` -- this repo has `packaging/.app-venv` -- so the
    skip matches the shape rather than the one name.
    """
    for d in ('.venv', '.app-venv', 'my-venv', 'venv-3.12'):
        lib = tmp_path/d/'lib'/'python3.12'/'site-packages'/'lxml'
        lib.mkdir(parents=True)
        (lib/'keys.h').write_text('/* not your code */\n')
    (tmp_path/'keys.py').write_text('KEYS = 1\n')
    # A folder that merely *contains* the word is still the project's.
    (tmp_path/'conventions').mkdir(); (tmp_path/'conventions'/'keys.py').write_text('X = 1\n')

    ws = Workspace(roots=[tmp_path])
    walked = [str(p) for p in ws.fs.walk(tmp_path)]
    assert not [p for p in walked if 'site-packages' in p], walked[:3]
    assert len(walked) == 2, walked
    assert any(p.endswith('conventions/keys.py') for p in walked), 'not an over-eager skip'


def test_a_site_packages_under_an_oddly_named_venv_is_still_skipped(tmp_path):
    "The inner skip is the backstop for a venv folder named something nobody predicted."
    lib = tmp_path/'weird'/'lib'/'site-packages'/'pkg'
    lib.mkdir(parents=True)
    (lib/'mod.py').write_text('x = 1\n')
    (tmp_path/'mine.py').write_text('y = 2\n')
    ws = Workspace(roots=[tmp_path])
    assert [p.name for p in ws.fs.walk(tmp_path)] == ['mine.py']
