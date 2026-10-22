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

def test_a_tracked_folder_holding_an_ignored_one_is_not_ignored(tmp_path):
    """Every package with a `__pycache__/` was drawn ignored: an ignored entry under a folder rolled up to it."""
    repo = _repo(tmp_path)
    (tmp_path/'.gitignore').write_text('__pycache__/\n')
    (pkg := tmp_path/'vr').mkdir()
    (pkg/'core.py').write_text('x = 1\n')
    subprocess.run(['git', 'add', '-A'], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(['git', 'commit', '-qm', 'vr'], cwd=tmp_path, check=True, capture_output=True)
    (pkg/'__pycache__').mkdir()
    (pkg/'__pycache__'/'core.pyc').write_text('')
    state = git_tree_state(Workspace(roots=[tmp_path]).fs)
    assert _folder_class(pkg, state) == ''
    assert _folder_class(pkg/'__pycache__', state) == 'ignored', 'and the ignored folder itself still is'

def test_a_folder_expands_without_waiting_on_git(tmp_path, monkeypatch):
    """The Mac app waited seconds on `git status` before showing a folder's children; `/tree` now runs no git."""
    from leela.blocks.fs import ui
    _repo(tmp_path)
    (tmp_path/'pkg').mkdir(); (tmp_path/'pkg'/'new.py').write_text('x = 1\n')
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        assert client.post('/tree/git', json={'paths': [str(tmp_path/'pkg')]}).json()['states'] == {str(tmp_path/'pkg'): 'untracked'}
        ran = []
        monkeypatch.setattr(ui.GitRepo, 'at', classmethod(lambda cls, root: ran.append('at') or (_ for _ in ()).throw(AssertionError('git ran'))))
        monkeypatch.setattr(ui.GitRepo, 'decorations', lambda self: ran.append('status') or [])
        monkeypatch.setattr(ui, '_git_stamp', lambda repo: ran.append('stamp') or ())
        r = client.get('/tree', params={'path': str(tmp_path/'pkg')})
        assert r.status_code == 200 and 'new.py' in r.text
        top = client.get('/tree', params={'path': str(tmp_path)}).text
        assert 'git-untracked' in top, 'drawn with the marks the last look found'
        assert ran == []

def test_tree_git_marks_files_and_folders_by_the_paths_asked(tmp_path):
    repo = _repo(tmp_path)
    (tmp_path/'.gitignore').write_text('__pycache__/\n')
    (pkg := tmp_path/'vr').mkdir(); (pkg/'core.py').write_text('x = 1\n')
    subprocess.run(['git', 'add', '-A'], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(['git', 'commit', '-qm', 'vr'], cwd=tmp_path, check=True, capture_output=True)
    (pkg/'__pycache__').mkdir(); (pkg/'__pycache__'/'core.pyc').write_text('')
    (tmp_path/'README.md').write_text('changed\n')
    ws = Workspace(roots=[tmp_path])
    asked = [str(pkg), str(pkg/'__pycache__'), str(pkg/'core.py'), str(tmp_path/'README.md'), str(tmp_path/'nowhere')]
    with TestClient(ide_app(ws)) as client:
        got = client.post('/tree/git', json={'paths': asked}).json()['states']
    assert got == {str(pkg): '', str(pkg/'__pycache__'): 'ignored', str(pkg/'core.py'): '',
                   str(tmp_path/'README.md'): 'modified', str(tmp_path/'nowhere'): ''}

def test_show_hidden_files_lists_the_virtualenv_in_the_tree(tmp_path):
    "With hidden files shown, `.venv` stayed out of the tree: the listing pruned it as search and the watcher do."
    (tmp_path/'.venv'/'lib').mkdir(parents=True); (tmp_path/'a.py').write_text('x = 1\n')
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as client:
        shown = client.get('/tree', params={'path': str(tmp_path), 'hidden': 'true'}).text
        assert '.venv' in shown and 'a.py' in shown
        assert 'lib' in client.get('/tree', params={'path': str(tmp_path/'.venv'), 'hidden': 'true'}).text
        assert '.venv' not in client.get('/tree', params={'path': str(tmp_path)}).text, 'hidden files off still hides it'
