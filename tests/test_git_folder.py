"""Staging a folder of a language you are meeting for the first time."""
import subprocess

from starlette.testclient import TestClient

from leela.app import ide_app
from leela.blocks.fs.ui import _folder_class, git_tree_state
from leela.blocks.git.git import GitRepo
from leela.blocks.git.ignores import prepare
from leela.workspace import Workspace

def _repo(tmp_path):
    for argv in (['init', '-q'], ['config', 'user.email', 'a@b'], ['config', 'user.name', 'c']):
        subprocess.run(['git', *argv], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path/'README.md').write_text('hi\n')
    subprocess.run(['git', 'add', '-A'], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(['git', 'commit', '-qm', 'init'], cwd=tmp_path, check=True, capture_output=True)
    return GitRepo.at(tmp_path)

def _crate(root, name='mycrate'):
    "A maturin crate, minus the ignore file, plus the build output that trips people up."
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

# what it writes ----------------------------------------------------------------------------------

def test_a_repository_that_already_ignores_them_is_left_alone(tmp_path):
    "The check is `git check-ignore`, so a rule written in some other shape still counts."
    repo = _repo(tmp_path)
    (tmp_path/'.gitignore').write_text('**/target/\n**/dist/\n')
    assert prepare(repo, _crate(tmp_path))['added'] == []

# the route ---------------------------------------------------------------------------------------

def test_staging_a_folder_writes_its_ignores_first(tmp_path):
    """The fault this exists for: `git add mycrate` on a fresh crate stages 'target/' too, and a person meeting Rust has no way to know that is wrong."""
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

# what the tree shows ------------------------------------------------------------------------------

def test_a_folder_takes_the_strongest_state_under_it(tmp_path):
    "A new folder is entirely untracked, and every row inside it is out of sight until it opens."
    _repo(tmp_path)
    d = _crate(tmp_path)
    state = git_tree_state(Workspace(roots=[tmp_path]).fs)
    assert _folder_class(d, state) == 'untracked'
