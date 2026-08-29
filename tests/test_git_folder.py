"""Staging a folder of a language you are meeting for the first time.

`git add` honours `.gitignore`, so the whole difficulty is that a folder you have just created
does not have one. These cover the rules being written from what the folder is, git being asked
rather than guessed at about what it already covers, and the tree saying which files are in which
state without being expanded.
"""
import subprocess
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from leela.app import ide_app
from leela.blocks.fs.ui import _folder_class, _git_class, git_tree_state
from leela.blocks.git.git import GitRepo
from leela.blocks.git.ignores import KINDS, kinds_in, missing_rules, prepare
from leela.workspace import Workspace

def _repo(tmp_path):
    for argv in (['init', '-q'], ['config', 'user.email', 'a@b'], ['config', 'user.name', 'c']):
        subprocess.run(['git', *argv], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path/'README.md').write_text('hi\n')
    subprocess.run(['git', 'add', '-A'], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(['git', 'commit', '-qm', 'init'], cwd=tmp_path, check=True, capture_output=True)
    return GitRepo.at(tmp_path)

def _crate(root, name='mycrate'):
    "What `nbship` writes, minus the ignore file, plus the build output that trips people up."
    d = root/name
    (d/'src').mkdir(parents=True)
    (d/'Cargo.toml').write_text('[package]\nname = "mycrate"\n')
    (d/'pyproject.toml').write_text('[build-system]\nrequires = ["maturin"]\n')
    (d/'src'/'lib.rs').write_text('pub fn f() {}\n')
    (d/'target'/'debug').mkdir(parents=True)
    (d/'target'/'debug'/'build').write_text('a big binary\n')
    (d/'dist').mkdir()
    (d/'dist'/'x.whl').write_text('a wheel\n')
    return d

# what the folder is -----------------------------------------------------------------------------

def test_a_folder_says_which_kinds_of_project_it_is(tmp_path):
    assert kinds_in(_crate(tmp_path)) == ['rust', 'maturin']

def test_a_pyproject_alone_is_a_python_project(tmp_path):
    (tmp_path/'pyproject.toml').write_text('[project]\nname="x"\n')
    assert kinds_in(tmp_path) == ['python']

def test_a_pyproject_beside_a_cargo_toml_is_a_wheel_built_from_rust(tmp_path):
    "Both name a `dist/`, and saying so twice would write the same rules twice."
    kinds = kinds_in(_crate(tmp_path))
    assert 'maturin' in kinds and 'python' not in kinds

def test_a_folder_that_is_no_kind_of_project_needs_nothing(tmp_path):
    (tmp_path/'notes.txt').write_text('x')
    assert kinds_in(tmp_path) == []

def test_every_kind_can_be_recognised_and_has_something_to_say():
    for kind, spec in KINDS.items():
        assert spec['markers'] and spec['probes'] and spec['lines'], kind

# what it writes ----------------------------------------------------------------------------------

def test_the_rules_a_new_crate_needs_are_written_from_what_it_is(tmp_path):
    repo = _repo(tmp_path)
    out = prepare(repo, _crate(tmp_path))
    assert out['kinds'] == ['rust', 'maturin']
    assert '/target/' in out['added'] and '/dist/' in out['added']
    assert '/target/' in (tmp_path/'mycrate'/'.gitignore').read_text(), 'in the crate, not the repo'

def test_a_repository_that_already_ignores_them_is_left_alone(tmp_path):
    "The check is `git check-ignore`, so a rule written in some other shape still counts."
    repo = _repo(tmp_path)
    (tmp_path/'.gitignore').write_text('**/target/\n**/dist/\n')
    assert prepare(repo, _crate(tmp_path))['added'] == []

def test_running_it_twice_writes_nothing_the_second_time(tmp_path):
    repo = _repo(tmp_path)
    d = _crate(tmp_path)
    prepare(repo, d)
    before = (d/'.gitignore').read_text()
    assert prepare(repo, d)['added'] == []
    assert (d/'.gitignore').read_text() == before

def test_a_dry_run_reports_without_writing(tmp_path):
    repo = _repo(tmp_path)
    d = _crate(tmp_path)
    out = prepare(repo, d, write=False)
    assert out['added'] and not (d/'.gitignore').exists()

def test_existing_rules_are_added_to_rather_than_replaced(tmp_path):
    repo = _repo(tmp_path)
    d = _crate(tmp_path)
    (d/'.gitignore').write_text('secrets.env\n')
    prepare(repo, d)
    text = (d/'.gitignore').read_text()
    assert 'secrets.env' in text and '/target/' in text

# the route ---------------------------------------------------------------------------------------

def test_staging_a_folder_writes_its_ignores_first(tmp_path):
    """The fault this exists for: `git add mycrate` on a fresh crate stages 'target/' too, and a
    person meeting Rust has no way to know that is wrong."""
    repo = _repo(tmp_path)
    d = _crate(tmp_path)
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        r = client.post('/git/tree/prepare', json={'path': str(d)})
    assert r.status_code == 200, r.text
    prepared = r.json()['prepared']
    assert prepared['kinds'] == ['rust', 'maturin']
    assert prepared['staged'] == ['mycrate']
    staged = subprocess.run(['git', 'diff', '--cached', '--name-only'], cwd=tmp_path,
                            capture_output=True, text=True).stdout.split()
    assert 'mycrate/Cargo.toml' in staged and 'mycrate/src/lib.rs' in staged
    assert not any(p.startswith('mycrate/target') for p in staged), 'the build output stayed out'
    assert not any(p.endswith('.whl') for p in staged), 'and so did the wheel'

def test_a_file_is_refused_with_a_reason(tmp_path):
    _repo(tmp_path)
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        r = client.post('/git/tree/prepare', json={'path': str(tmp_path/'README.md')})
    assert 'not a folder' in r.text

# what the tree shows ------------------------------------------------------------------------------

def test_an_ignored_file_is_its_own_state(tmp_path):
    "Knowing a file is deliberately not committed is the same question as knowing one is missing."
    repo = _repo(tmp_path)
    d = _crate(tmp_path)
    prepare(repo, d)
    state = git_tree_state(Workspace(roots=[tmp_path]).fs)
    ignored = [k for k, v in state.items() if _git_class(v) == 'ignored']
    assert any('target' in k for k in ignored)

def test_a_folder_takes_the_strongest_state_under_it(tmp_path):
    "A new folder is entirely untracked, and every row inside it is out of sight until it opens."
    _repo(tmp_path)
    d = _crate(tmp_path)
    state = git_tree_state(Workspace(roots=[tmp_path]).fs)
    assert _folder_class(d, state) == 'untracked'

def test_a_clean_folder_gets_no_colour(tmp_path):
    _repo(tmp_path)
    assert _folder_class(tmp_path/'nothing-here', git_tree_state(Workspace(roots=[tmp_path]).fs)) == ''

def test_a_conflict_outranks_everything_else():
    from leela.blocks.fs.ui import GIT_RANK
    assert GIT_RANK[-1] == 'conflict'
    assert GIT_RANK.index('untracked') > GIT_RANK.index('ignored')

# the release flow a crate gets ---------------------------------------------------------------------

from leela.blocks.pipelines.pipelines import (CRATE_STEPS, MATURIN_STEPS, default_steps,  # noqa: E402
                                              maturin_project, release_flow, rust_project)

def _crate_files(d, pyproject=None):
    d.mkdir(parents=True, exist_ok=True)
    (d/'Cargo.toml').write_text('[package]\nname = "x"\nversion = "0.1.0"\n')
    if pyproject is not None: (d/'pyproject.toml').write_text(pyproject)
    return d

MATURIN_PY = ('[build-system]\nrequires = ["maturin>=1.0,<2.0"]\nbuild-backend = "maturin"\n'
              '[project]\nname = "x"\ndynamic = ["version"]\n')

def test_a_crate_with_python_bindings_releases_through_maturin(tmp_path):
    d = _crate_files(tmp_path/'a', MATURIN_PY)
    assert maturin_project(d) and release_flow(d) == 'maturin'
    assert [s.id for s in default_steps(d)] == ['test', 'wheel', 'ci', 'changelog', 'release']

def test_a_crate_without_them_releases_to_crates_io(tmp_path):
    d = _crate_files(tmp_path/'b')
    assert rust_project(d) and not maturin_project(d)
    assert release_flow(d) == 'crate'
    assert [s.id for s in default_steps(d)] == ['test', 'clippy', 'package', 'publish']

def test_a_maturin_crate_is_not_mistaken_for_a_plain_python_package(tmp_path):
    """It has a `pyproject.toml`, so the fastship flow used to claim it -- and `ship-pypi` would
    upload one platform's wheel where the workflow builds every platform's."""
    d = _crate_files(tmp_path/'c', MATURIN_PY)
    assert release_flow(d) != 'fastship'
    assert not any(s.cmd.startswith('ship-pypi') for s in default_steps(d))

def test_nothing_is_published_from_the_maturin_flow_itself():
    "The tag is the trigger; the runners build and upload, because only they have every platform."
    assert not any('upload' in s.cmd or 'twine' in s.cmd for s in MATURIN_STEPS)
    assert MATURIN_STEPS[-1].cmd == 'ship-release'

def test_each_publishing_step_names_the_credential_it_needs():
    for steps in (MATURIN_STEPS, CRATE_STEPS):
        for s in steps:
            if 'publish' in s.id or 'release' in s.id or s.id == 'changelog':
                assert s.needs, f'{s.id} publishes but names no secret'

def test_a_pyproject_that_is_not_maturin_is_not_a_maturin_crate(tmp_path):
    d = _crate_files(tmp_path/'d', '[build-system]\nbuild-backend = "hatchling.build"\n')
    assert not maturin_project(d) and release_flow(d) == 'crate'
