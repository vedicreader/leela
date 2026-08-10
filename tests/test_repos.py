"""A workspace of repositories, and the operations that cross all of them.

The single-repository behaviour is `tests/test_git.py`'s subject. What is under test here is
everything that only exists in the plural: who is in the list, who is refused, and whether a
batch survives one member of it failing.
"""

import subprocess

import pytest

from leela.git import GitError, GitRepo
from leela.repos import MEMBERS, RepoSet, clone_url, discover


def git(path, *args):
    return subprocess.run(['git', *args], cwd=path, check=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()


def make_repo(path, name='seed.py'):
    path.mkdir(parents=True, exist_ok=True)
    git(path, 'init', '-b', 'main')
    git(path, 'config', 'user.email', 'tests@leela.local')
    git(path, 'config', 'user.name', 'Leela tests')
    (path/name).write_text('value = 1\n')
    git(path, 'add', '.')
    git(path, 'commit', '-m', 'initial')
    return path


@pytest.fixture
def workspace(tmp_path):
    "A folder of checkouts -- the layout fastws manages -- plus a folder that is not one."
    root = tmp_path/'work'
    for name in ('alpha', 'beta', 'gamma'):
        make_repo(root/name)
    (root/'notes').mkdir()
    return root


def repo_set(root, tmp_path):
    "A RepoSet whose membership file is the test's own, never the user's config directory."
    return RepoSet([root], store=tmp_path/'members.json')


def test_a_folder_of_checkouts_is_the_workspace(workspace, tmp_path):
    names = [p.name for p in repo_set(workspace, tmp_path).paths()]
    assert names == ['alpha', 'beta', 'gamma']          # sorted, and the plain folder is not one


def test_a_folder_that_is_itself_a_checkout_counts_too(tmp_path):
    root = make_repo(tmp_path/'solo')
    make_repo(root/'vendored')
    assert [p.name for p in discover([root])] == ['solo', 'vendored']


def test_a_fastws_repos_file_is_read_where_it_lands(workspace, tmp_path):
    "A `repos.txt` naming a checkout outside the folder still puts it in the workspace."
    outside = make_repo(tmp_path/'elsewhere'/'delta')
    (workspace/MEMBERS).write_text('# the workspace\nalpha\n'
                                  f'{outside}\n'
                                  'https://github.com/AnswerDotAI/fastws.git\n')
    names = [p.name for p in repo_set(workspace, tmp_path).paths()]
    assert names == ['alpha', 'beta', 'gamma', 'delta']  # the un-cloned URL contributes nothing


def test_membership_is_added_and_removed_without_touching_the_checkout(workspace, tmp_path):
    outside = make_repo(tmp_path/'outside'/'epsilon')
    repos = repo_set(workspace, tmp_path)

    repos.add(outside/'seed.py')                        # a path inside the repo is enough
    assert [p.name for p in repos.paths()][-1] == 'epsilon'

    repos.remove(outside)
    assert 'epsilon' not in [p.name for p in repos.paths()]
    assert outside.exists()                             # removing is forgetting, not deleting

    repos.remove(workspace/'beta')                      # a discovered repository is hidden
    assert [p.name for p in repos.paths()] == ['alpha', 'gamma']
    repos.add(workspace/'beta')                         # and adding it back un-hides it
    assert [p.name for p in repos.paths()] == ['alpha', 'beta', 'gamma']


def test_a_repository_the_workspace_does_not_list_is_refused(workspace, tmp_path):
    "The security boundary for every repository-targeted route: discovery, not resolution."
    outside = make_repo(tmp_path/'stranger')
    repos = repo_set(workspace, tmp_path)
    assert repos.require(workspace/'alpha') == workspace/'alpha'
    with pytest.raises(GitError, match='not a repository in this workspace'):
        repos.require(outside)
    with pytest.raises(GitError, match='not a repository in this workspace'):
        repos.require('/etc')


def test_the_overview_names_the_odd_one_out(workspace, tmp_path):
    (workspace/'alpha'/'seed.py').write_text('value = 2\n')
    git(workspace/'gamma', 'switch', '-c', 'feature/other')
    over = repo_set(workspace, tmp_path).overview()

    assert over['expected_branch'] == 'main'            # nobody said so; most of them are on it
    assert over['summary'] == {'repos': 3, 'dirty': 1, 'ahead': 0, 'behind': 0,
                               'off_branch': 1, 'unreleased': 0, 'errors': 0}
    rows = {r['name']: r for r in over['repos']}
    assert rows['alpha']['changed'] == 1 and not rows['alpha']['clean']
    assert rows['gamma']['off_branch'] and rows['gamma']['branch'] == 'feature/other'
    assert not rows['beta']['off_branch']

    named = repo_set(workspace, tmp_path).overview('feature/other')
    assert {r['name'] for r in named['repos'] if r['off_branch']} == {'alpha', 'beta'}


def test_unreleased_commits_are_counted_from_the_last_tag(workspace, tmp_path):
    alpha = workspace/'alpha'
    GitRepo(alpha).tag('v0.1')
    (alpha/'seed.py').write_text('value = 3\n')
    git(alpha, 'commit', '-am', 'after the release')
    rows = {r['name']: r for r in repo_set(workspace, tmp_path).overview()['repos']}
    assert rows['alpha']['tag'] == 'v0.1' and rows['alpha']['unreleased'] == 1
    assert rows['beta']['unreleased'] is None           # never released is not zero unreleased


def test_a_batch_reports_every_repository_and_one_failure_does_not_end_it(workspace, tmp_path):
    """`fetch` across a workspace where one member has no remote at all.

    The point of the fan-out is that the other two still answer -- a batch that stopped at
    the first error would make a workspace only as usable as its worst repository.
    """
    remote = tmp_path/'origin.git'
    git(tmp_path, 'init', '--bare', remote.name)
    git(workspace/'alpha', 'remote', 'add', 'origin', str(remote))
    git(workspace/'alpha', 'push', '-u', 'origin', 'main')
    git(workspace/'beta', 'remote', 'add', 'origin', str(tmp_path/'missing.git'))

    results = {r['name']: r for r in repo_set(workspace, tmp_path).run('fetch')}
    assert set(results) == {'alpha', 'beta', 'gamma'}
    assert results['alpha']['ok'] and results['gamma']['ok']
    assert not results['beta']['ok'] and results['beta']['error']


def test_bulk_pull_and_push_skip_rather_than_guess(workspace, tmp_path):
    """Nothing in a batch invents a remote or publishes a branch.

    `skipped` is a third outcome on purpose: in a list of twenty repositories "nothing to
    do" and "it failed" look identical and mean opposite things.
    """
    remote = tmp_path/'origin.git'
    git(tmp_path, 'init', '--bare', remote.name)
    alpha = workspace/'alpha'
    git(alpha, 'remote', 'add', 'origin', str(remote))
    git(alpha, 'push', '-u', 'origin', 'main')
    repos = repo_set(workspace, tmp_path)

    pulled = {r['name']: r for r in repos.run('pull')}
    assert pulled['alpha']['skipped'] == 'already current'
    assert pulled['beta']['skipped'] == 'no upstream'

    pushed = {r['name']: r for r in repos.run('push')}
    assert pushed['alpha']['skipped'] == 'nothing to push'
    assert pushed['gamma']['skipped'] == 'unpublished branch'

    (alpha/'seed.py').write_text('value = 4\n')
    git(alpha, 'commit', '-am', 'local work')
    assert repos.run('push', [alpha])[0]['ok']
    assert git(remote, 'log', '-1', '--format=%s', 'main') == 'local work'


def test_pull_fast_forwards_a_repository_that_is_behind(workspace, tmp_path):
    remote = tmp_path/'origin.git'
    git(tmp_path, 'init', '--bare', remote.name)
    alpha = workspace/'alpha'
    git(alpha, 'remote', 'add', 'origin', str(remote))
    git(alpha, 'push', '-u', 'origin', 'main')

    other = make_repo(tmp_path/'other')                 # someone else pushes
    git(other, 'remote', 'add', 'origin', str(remote))
    git(other, 'fetch', 'origin')
    git(other, 'reset', '--hard', 'origin/main')
    (other/'seed.py').write_text('value = 5\n')
    git(other, 'commit', '-am', 'upstream work')
    git(other, 'push', 'origin', 'main')

    result = {r['name']: r for r in repo_set(workspace, tmp_path).run('pull')}['alpha']
    assert result['ok'] and not result['skipped']
    assert (alpha/'seed.py').read_text() == 'value = 5\n'


def test_cloning_stays_inside_the_open_folders(workspace, tmp_path):
    source = make_repo(tmp_path/'source')
    repos = repo_set(workspace, tmp_path)

    assert repos.clone([str(source)])[0]['ok']
    assert [p.name for p in repos.paths()] == ['alpha', 'beta', 'gamma', 'source']

    again = repos.clone([str(source)])[0]
    assert not again['ok'] and 'already exists' in again['error']

    with pytest.raises(GitError, match='outside the open folders'):
        repos.clone([str(source)], into=tmp_path)


def test_owner_name_is_the_shorthand_both_lists_use():
    assert clone_url('AnswerDotAI/fastws') == 'https://github.com/AnswerDotAI/fastws.git'
    assert clone_url('https://example.com/x/y.git') == 'https://example.com/x/y.git'
    assert clone_url('git@example.com:x/y.git') == 'git@example.com:x/y.git'


def test_an_unknown_operation_is_refused_before_anything_runs(workspace, tmp_path):
    with pytest.raises(GitError, match='unknown workspace operation'):
        repo_set(workspace, tmp_path).run('rm -rf')
