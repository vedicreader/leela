import subprocess

import pytest

from leela.ai import GIT_WRITE_TOOLS, WRITE_TOOLS, _git_tools
from leela.git import GitError, GitRepo, repo_root
from leela.workspace import Workspace


def git(path, *args):
    return subprocess.run(['git', *args], cwd=path, check=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, 'init', '-b', 'main')
    git(tmp_path, 'config', 'user.email', 'tests@leela.local')
    git(tmp_path, 'config', 'user.name', 'Leela tests')
    (tmp_path/'src').mkdir()
    (tmp_path/'src'/'app.py').write_text('value = 1\n')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-m', 'initial')
    return tmp_path


def test_repo_root_and_workspace_cwd_follow_git(repo):
    nested = repo/'src'/'app.py'
    assert repo_root(nested) == repo
    ws = Workspace(roots=[repo/'src']); tab = ws.open(nested)
    # Git root can be above an opened subfolder: execution follows the project, while an
    # explicit override is still confined to the IDE's opened filesystem roots.
    assert ws.cwd_for(tab) == repo
    ws.set_cwd(repo/'src', tab)
    assert ws.cwd_for(tab) == repo/'src'
    ws.set_cwd('', tab)
    assert ws.cwd_for(tab) == repo


def test_status_stage_unstage_branch_and_commit(repo):
    r = GitRepo.at(repo/'src')
    (repo/'src'/'app.py').write_text('value = 2\n')
    (repo/'notes.txt').write_text('work\n')
    info = r.info()
    assert info['branch'] == 'main' and not info['clean']
    assert {c['path'] for c in info['changes']} == {'src/app.py', 'notes.txt'}
    assert next(c for c in info['changes'] if c['path'] == 'notes.txt')['untracked']

    r.stage(['src/app.py'])
    assert next(c for c in r.info()['changes'] if c['path'] == 'src/app.py')['staged']
    r.unstage(['src/app.py'])
    assert not next(c for c in r.info()['changes'] if c['path'] == 'src/app.py')['staged']

    r.create('feature/cwd')
    assert r.info()['branch'] == 'feature/cwd'
    r.checkout('main')
    r.delete('feature/cwd')
    assert 'feature/cwd' not in {b['name'] for b in r.info()['branches']}

    r.stage(['src/app.py', 'notes.txt'])
    r.commit('save work')
    assert r.info()['clean']


def test_fetch_exposes_remote_branches_and_checkout_tracks_them(repo, tmp_path):
    remote = tmp_path/'remote.git'
    git(tmp_path, 'init', '--bare', remote.name)
    git(repo, 'remote', 'add', 'origin', str(remote))
    git(repo, 'push', '-u', 'origin', 'main')
    git(repo, 'branch', 'remote-only')
    git(repo, 'push', 'origin', 'remote-only')
    git(repo, 'branch', '-D', 'remote-only')

    r = GitRepo.at(repo)
    r.fetch()
    branch = next(b for b in r.info()['branches'] if b['name'] == 'origin/remote-only')
    assert branch['remote'] and not branch['current']

    r.checkout('origin/remote-only')
    info = r.info()
    assert info['branch'] == 'remote-only'
    assert info['upstream'] == 'origin/remote-only'
    assert not any(b['name'] == 'origin/remote-only' for b in info['branches'])


def test_stash_tags_and_repository_metadata(repo):
    r = GitRepo.at(repo)
    (repo/'src'/'app.py').write_text('stashed = True\n')
    r.stash('checkpoint')
    info = r.info()
    assert info['stashes'] and info['stashes'][0]['subject'].endswith('checkpoint')
    assert 'remotes' in info and 'tags' in info
    r.stash_apply(info['stashes'][0]['ref'])
    assert 'stashed = True' in (repo/'src'/'app.py').read_text()
    git(repo, 'reset', '--hard', 'HEAD')
    r.stash_drop(info['stashes'][0]['ref'])
    r.tag('v0.1-test')
    assert 'v0.1-test' in r.info()['tags']


def test_file_changes_locate_modified_lines_for_the_editor(repo):
    p = repo/'src'/'app.py'
    p.write_text('value = 1\n\nchanged = True\n')
    detail = GitRepo.at(repo).file_changes('src/app.py')
    assert detail['changed'] and detail['diff']
    assert any(r['from'] <= 3 <= r['to'] for r in detail['ranges'])

    (repo/'new.py').write_text('one\ntwo\n')
    detail = GitRepo.at(repo).file_changes('new.py')
    assert detail['status']['untracked']
    assert detail['ranges'] == [{'from': 1, 'to': 2, 'kind': 'added'}]


def test_notebook_diff_defaults_to_cell_source_instead_of_json(repo):
    nb = repo/'analysis.ipynb'
    nb.write_text('{"cells":[{"cell_type":"code","source":["value = 1\\n"],"outputs":[],"metadata":{},"id":"noise"}],"metadata":{},"nbformat":4,"nbformat_minor":5}')
    r = GitRepo.at(repo)
    view = r.diff_view('analysis.ipynb')
    assert view['notebook'] and '# %% code · cell 1' in view['content']
    assert 'value = 1' in view['content']
    assert '"metadata"' not in view['content'] and '"outputs"' not in view['content']


def test_notebook_review_is_utf8_even_when_the_app_has_no_utf8_locale(repo, monkeypatch):
    nb = repo/'unicode.ipynb'
    nb.write_text('{"cells":[{"cell_type":"markdown","source":["plain\\n"],"metadata":{}}],"metadata":{},"nbformat":4,"nbformat_minor":5}')
    git(repo, 'add', 'unicode.ipynb'); git(repo, 'commit', '-m', 'unicode base')
    nb.write_text('{"cells":[{"cell_type":"markdown","source":["arrow → and café\\n"],"metadata":{}}],"metadata":{},"nbformat":4,"nbformat_minor":5}')
    monkeypatch.setenv('LC_ALL', 'C'); monkeypatch.setenv('LANG', 'C')
    view = GitRepo.at(repo).diff_view('unicode.ipynb')
    assert 'arrow → and café' in view['content']


def test_agent_git_tools_fetch_track_and_report_failures(repo, tmp_path):
    remote = tmp_path/'agent-remote.git'
    git(tmp_path, 'init', '--bare', remote.name)
    git(repo, 'remote', 'add', 'origin', str(remote))
    git(repo, 'push', '-u', 'origin', 'main')
    git(repo, 'branch', 'from-agent')
    git(repo, 'push', 'origin', 'from-agent')
    git(repo, 'branch', '-D', 'from-agent')

    class Host:
        roots = [str(repo)]
        def check(self, path, must_exist=False):
            p = __import__('pathlib').Path(path).resolve()
            if not p.is_relative_to(repo): raise ValueError('outside workspace')
            if must_exist and not p.exists(): raise FileNotFoundError(p)
            return p

    tools = {f.__name__: f for f in _git_tools(Host())}
    assert set(tools) == {'git_status', 'git_fetch', 'git_checkout', 'git_pull', 'git_push'}
    assert GIT_WRITE_TOOLS <= WRITE_TOOLS and 'git_status' not in WRITE_TOOLS
    fetched = tools['git_fetch']()
    assert 'origin/from-agent' in fetched
    checked_out = tools['git_checkout']('origin/from-agent')
    assert '"branch": "from-agent"' in checked_out
    assert '"upstream": "origin/from-agent"' in checked_out
    assert tools['git_status'](str(repo.parent)).startswith('git status failed:')


def test_remote_head_is_not_a_branch_and_refs_explain_recency(repo, tmp_path):
    remote = tmp_path/'dated.git'
    git(tmp_path, 'init', '--bare', remote.name)
    git(repo, 'remote', 'add', 'origin', str(remote))
    git(repo, 'push', '-u', 'origin', 'main')
    git(remote, 'symbolic-ref', 'HEAD', 'refs/heads/main')
    git(repo, 'remote', 'set-head', 'origin', '--auto')

    rows = GitRepo.at(repo).info()['branches']
    assert 'origin' not in {row['name'] for row in rows}
    current = next(row for row in rows if row['current'])
    assert current['name'] == 'main' and current['timestamp'] > 0
    assert current['date'] and current['author'] == 'Leela tests'
    assert current['latest'] and current['default']


def test_partial_hunk_staging_and_reversal(repo):
    path = repo/'src'/'app.py'
    path.write_text('value = 2\n')
    r = GitRepo.at(repo)
    patch = r.diff('src/app.py')
    assert '-value = 1' in patch and '+value = 2' in patch

    r.apply_patch(patch)
    change = r.info()['changes'][0]
    assert change['staged'] and not change['unstaged']
    r.apply_patch(patch, reverse=True)
    change = r.info()['changes'][0]
    assert not change['staged'] and change['unstaged']


def test_history_commit_compare_and_blame(repo):
    path = repo/'src'/'app.py'
    path.write_text('value = 2\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-m', 'second value')
    r = GitRepo.at(repo)

    history = r.history()
    assert [row['subject'] for row in history[:2]] == ['second value', 'initial']
    detail = r.commit_detail(history[0]['oid'])
    assert detail['message'] == 'second value' and '+value = 2' in detail['patch']
    comparison = r.compare(history[1]['oid'], history[0]['oid'])
    assert comparison['right_only'] == 1 and '+value = 2' in comparison['patch']
    blamed = r.blame('src/app.py')
    assert blamed[0]['author'] == 'Leela tests' and blamed[0]['text'] == 'value = 2'


def test_branch_lifecycle_structured_remotes_and_worktrees(repo, tmp_path):
    remote = tmp_path/'lifecycle.git'
    git(tmp_path, 'init', '--bare', remote.name)
    r = GitRepo.at(repo)
    r.add_remote('upstream', str(remote))
    assert r.info()['remotes'][0]['name'] == 'upstream'
    assert r.info()['remotes'][0]['fetch'] == str(remote)

    r.create('topic')
    r.rename_branch('topic', 'renamed')
    r.checkout('main')
    worktree = tmp_path/'topic-worktree'
    r.add_worktree(worktree, 'renamed')
    assert any(row['branch'] == 'renamed' and row['path'] == str(worktree) for row in r.worktrees())
    r.remove_worktree(worktree)
    r.delete('renamed')
    r.remove_remote('upstream')
    assert not r.info()['remotes']


def test_conflict_versions_resolution_operation_state_and_reflog(repo):
    path = repo/'src'/'app.py'
    r = GitRepo.at(repo)
    r.create('other')
    path.write_text('other = True\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-m', 'other side')
    r.checkout('main')
    path.write_text('main = True\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-m', 'main side')

    merged = subprocess.run(['git', 'merge', 'other'], cwd=repo, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert merged.returncode != 0
    assert r.info()['operation']['active'] == 'merge'
    versions = r.conflict_versions('src/app.py')
    assert versions['ours'] == 'main = True\n'
    assert versions['theirs'] == 'other = True\n'
    r.resolve_conflict('src/app.py', 'theirs')
    assert path.read_text() == 'other = True\n'
    assert r.info()['changes'][0]['staged']
    r.operation_action('abort')
    assert not r.info()['operation']['active']
    assert r.reflog() and all(row['selector'].startswith('HEAD@{') for row in r.reflog())


def test_git_errors_are_readable(tmp_path):
    with pytest.raises(GitError, match='not inside a Git repository'):
        GitRepo.at(tmp_path)
