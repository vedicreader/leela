"The git block: one repository, its safety rails, and the workspace of many."

import json
import subprocess
import time
import pytest
from fastcore.basics import first
from shalya.tools import git_tools as _git_tools
from leela.blocks.git.git import GitError, GitRepo, repo_root
from leela.workspace import Workspace
from leela.app import ide_app
from starlette.testclient import TestClient
from leela.blocks.git.repos import MEMBERS, RepoSet

def git(path, *args):
    return subprocess.run(['git', *args], cwd=path, check=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()

@pytest.fixture
def repo_git(tmp_path):
    git(tmp_path, 'init', '-b', 'main')
    git(tmp_path, 'config', 'user.email', 'tests@leela.local')
    git(tmp_path, 'config', 'user.name', 'Leela tests')
    (tmp_path/'src').mkdir()
    (tmp_path/'src'/'app.py').write_text('value = 1\n')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-m', 'initial')
    return tmp_path

def test_agent_git_tools_fetch_track_and_report_failures(repo_git, tmp_path):
    remote = tmp_path/'agent-remote.git'
    git(tmp_path, 'init', '--bare', remote.name)
    git(repo_git, 'remote', 'add', 'origin', str(remote))
    git(repo_git, 'push', '-u', 'origin', 'main')
    git(repo_git, 'branch', 'from-agent')
    git(repo_git, 'push', 'origin', 'from-agent')
    git(repo_git, 'branch', '-D', 'from-agent')
    class Host:
        roots = [str(repo_git)]
        def check(self, path, must_exist=False):
            p = __import__('pathlib').Path(path).resolve()
            if not p.is_relative_to(repo_git): raise ValueError('outside workspace')
            if must_exist and not p.exists(): raise FileNotFoundError(p)
            return p
    tools = {f.__name__: f for f in _git_tools(Host())}
    fetched = tools['git_remote']('fetch')
    assert 'origin/from-agent' in fetched
    checked_out = tools['git_checkout']('origin/from-agent')
    assert '"branch": "from-agent"' in checked_out
    assert '"upstream": "origin/from-agent"' in checked_out
    from shalya.core import failed
    assert failed(tools['git_status'](str(repo_git.parent))), 'a path outside the roots is a message'

def conflicted(repo_git, ours, theirs):
    "Leave `repo` mid-merge with src/app.py conflicted between the two texts."
    r = GitRepo.at(repo_git); path = repo_git/'src'/'app.py'
    r.create('other'); path.write_text(theirs)
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'other side')
    r.checkout('main'); path.write_text(ours)
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'main side')
    assert subprocess.run(['git', 'merge', 'other'], cwd=repo_git, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode != 0
    return r, path

MIXED_OURS = 'shared\nours only\ntail\n'
MIXED_THEIRS = 'shared\ntheirs only\ntail\n'

def served(roots):
    "One IDE over these folders, and the workspace whose journal the writes must reach."
    from starlette.testclient import TestClient
    from leela.app import ide_app
    ws = Workspace(roots=roots)
    return TestClient(ide_app(ws)), ws

def gitop(client, **d): return client.post('/git/action', json=d)

def journalled(ws, label):
    return first(op for op in ws.journal.rows() if op['label'] == label)

def test_ignoring_a_path_is_versioned_and_undoable(repo_git):
    """`ignore` wrote through Ramabana's own `write_text`, so nothing kept a copy of what it replaced and `/history/undo` could not reach it."""
    c, ws = served([repo_git])
    (repo_git/'.gitignore').write_text('build/\n')
    assert gitop(c, op='ignore', path='src/app.py').status_code == 200
    assert (repo_git/'.gitignore').read_text() == 'build/\nsrc/app.py\n'
    op = journalled(ws, 'Git ignore')
    assert op and op['paths'] == [str(repo_git/'.gitignore')] and op['reversible']
    assert ws.history.rows(str(repo_git/'.gitignore'))
    assert c.post('/history/undo', json={}).json()['ok']
    assert (repo_git/'.gitignore').read_text() == 'build/\n'

RESOLVED = 'shared\nsettled\ntail\n'

def resolving(client, **extra):
    return gitop(client, op='resolve_conflict', path='src/app.py', choice='resolved',
                 content=RESOLVED, **extra)

def test_resolving_a_conflict_refuses_when_the_file_moved_under_the_panes(repo_git):
    "The browser's text was written over whatever was on disk now, destroying it silently."
    _, path = conflicted(repo_git, MIXED_OURS, MIXED_THEIRS)
    c, ws = served([repo_git])
    c.get('/git/conflict', params={'path': 'src/app.py'})
    path.write_text('someone else got here first\n')
    r = resolving(c)
    assert r.status_code == 409 and r.json()['ok'] is False
    assert path.read_text() == 'someone else got here first\n', 'their work is still there'
    assert journalled(ws, 'Git resolve conflict') is None

def test_a_resolution_keeps_the_files_mode(repo_git):
    "`atomic_save` renames a new file into place, which would drop the executable bit."
    _, path = conflicted(repo_git, MIXED_OURS, MIXED_THEIRS)
    path.chmod(0o755)
    c, _ = served([repo_git])
    c.get('/git/conflict', params={'path': 'src/app.py'})
    assert resolving(c).status_code == 200
    assert path.stat().st_mode & 0o111, 'still executable'

def conflicted_files(repo_git, *names):
    "Leave the repository mid-merge with each of these files conflicted between two texts."
    r, paths = GitRepo.at(repo_git), [repo_git/n for n in names]
    def commit_all(text, msg):
        for p in paths: p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)
        git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', msg)
    commit_all('base\n', 'base'); r.create('other'); commit_all('theirs\n', 'other side')
    r.checkout('main'); commit_all('ours\n', 'main side')
    assert subprocess.run(['git', 'merge', 'other'], cwd=repo_git, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode != 0
    return paths

def test_a_conflict_route_refuses_what_the_sandbox_refuses(repo_git, monkeypatch):
    "Git sat above the open folder, so a conflicted file beside it was written or deleted with no sandbox check."
    outside, lib, ok = conflicted_files(repo_git, 'other.py', 'lib/x.py', 'src/ok.py')
    c, ws = served([repo_git/'src'])
    monkeypatch.setattr(ws.fs, 'stdlib_root', lambda: [(repo_git/'lib').resolve()])
    for path, why in ((outside, 'outside the open folders'), (lib, 'standard library')):
        was, rel = path.read_text(), str(path.relative_to(repo_git))
        for choice in ('resolved', 'ours', 'worktree'):
            r = gitop(c, op='resolve_conflict', path=rel, choice=choice, content='x\n', before=was)
            assert r.json().get('ok') is False and why in r.json()['error'], (rel, choice, r.json())
            assert path.read_text() == was and unmerged_now(repo_git, rel), (rel, choice)
    r = gitop(c, op='resolve_conflict', path='src/ok.py', choice='resolved', content='settled\n', before=ok.read_text())
    assert r.status_code == 200 and ok.read_text() == 'settled\n'

def test_a_batch_resolution_stops_at_a_file_outside_the_folders(repo_git):
    "`resolve_safe_conflicts` names no paths by default, so only the write itself can refuse the outside file."
    outside, ok = conflicted_files(repo_git, 'other.py', 'src/ok.py')
    same = 'a\n<<<<<<< ours\nsame\n=======\nsame\n>>>>>>> theirs\nb\n'
    for p in (outside, ok): p.write_text(same)
    c, _ = served([repo_git/'src'])
    assert c.get('/git/conflicts').json()['files']
    r = gitop(c, op='resolve_safe_conflicts')
    assert r.json().get('ok') is False and 'outside the open folders' in r.json()['error'], r.json()
    assert outside.read_text() == same and ok.read_text() == same, 'nothing was left half-done'

def test_discarding_the_whole_folder_stays_an_ordinary_write(repo_git):
    "`.` names the open folder itself, so checking its parent would refuse the folder the user opened."
    c, _ = served([repo_git])
    (repo_git/'src'/'app.py').write_text('value = 2\n')
    assert gitop(c, op='discard', paths=['.']).status_code == 200
    assert (repo_git/'src'/'app.py').read_text() == 'value = 1\n'

NOTEBOOK = {
    'cells': [
        {'cell_type': 'markdown', 'id': 'a1', 'metadata': {}, 'source': ['# title\n', '\n', 'prose\n']},
        {'cell_type': 'code', 'id': 'b2', 'metadata': {}, 'execution_count': None, 'outputs': [],
         'source': ['def add(a, b):\n', '    return a + b\n']},
    ],
    'metadata': {'kernelspec': {'display_name': 'python3', 'language': 'python', 'name': 'python3'}},
    'nbformat': 4, 'nbformat_minor': 5,
}

def write_nb(path, cells):
    doc = {**NOTEBOOK, 'cells': cells}
    path.write_text(json.dumps(doc, indent=1) + '\n')
    return path

def test_blaming_a_notebook_reports_cells_of_source_not_lines_of_json(repo_git):
    'The whole point: `git blame` on an .ipynb blames `"source": [` and escaped newlines.'
    write_nb(repo_git/'nb.ipynb', NOTEBOOK['cells'])
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'add the notebook')
    d = GitRepo.at(repo_git).blame_notebook('nb.ipynb')
    assert d['notebook'] and not d['error']
    assert [c['kind'] for c in d['cells']] == ['markdown', 'code']
    assert [c['index'] for c in d['cells']] == [1, 2]
    code = d['cells'][1]
    assert [l['text'] for l in code['lines']] == ['def add(a, b):', '    return a + b']
    assert [l['n'] for l in code['lines']] == [1, 2], 'numbered within the cell'
    assert all(l['author'] == 'Leela tests' for l in code['lines'])
    assert code['touched']['summary'] == 'add the notebook'
    assert code['id'] == 'b2' and code['mapped']

def test_an_uncommitted_notebook_line_is_marked_rather_than_attributed(repo_git):
    "Working-tree lines are marked, not attributed to whoever came last."
    write_nb(repo_git/'nb.ipynb', NOTEBOOK['cells'])
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'first')
    edited = [NOTEBOOK['cells'][0],
              {**NOTEBOOK['cells'][1], 'source': ['def add(a, b):\n', '    return a + b\n', '    # new\n']}]
    write_nb(repo_git/'nb.ipynb', edited)
    cells = GitRepo.at(repo_git).blame_notebook('nb.ipynb')['cells']
    fresh = [l['text'] for l in cells[1]['lines'] if l['uncommitted']]
    assert '    # new' in fresh, 'the line that was actually added'
    assert fresh == ['    return a + b', '    # new'], 'and the comma-touched one before it'
    assert not any(l['uncommitted'] for l in cells[0]['lines']), 'the untouched cell is clean'
    assert cells[1]['touched']['uncommitted']

def _repo(path, name):
    path.mkdir(parents=True, exist_ok=True)
    git(path, 'init', '-b', name)
    git(path, 'config', 'user.email', 'tests@leela.local')
    git(path, 'config', 'user.name', 'Leela tests')
    (path/'readme.md').write_text(f'# {name}\n')
    git(path, 'add', '.'); git(path, 'commit', '-m', 'initial')
    return path

def test_choosing_a_folder_moves_source_control_to_that_checkout(tmp_path):
    "The reported bug: open leela on one repo, add a second, switch -- git stayed behind."
    from starlette.testclient import TestClient
    from leela.app import ide_app
    a, b = _repo(tmp_path/'ramabana', 'main'), _repo(tmp_path/'rishi', 'dev')
    ws = Workspace(roots=[a, b])
    with TestClient(ide_app(ws)) as client:
        assert client.get('/git/info').json()['branch'] == 'main', 'precondition: the first folder'
        assert client.post('/workspace/activate', json={'path': str(b)}).json()['ok'] is True
        assert client.get('/git/info').json()['branch'] == 'dev', 'the chosen folder, not the first'
        assert client.get('/workspace/info').json()['active'] == str(b)
        assert client.get('/cwd').json()['cwd'] == str(b)
    assert ws.state()['active_root'] == str(b), 'and it survives a restart'

def test_a_folder_of_checkouts_follows_the_file_from_repository_to_repository(tmp_path):
    """Open a directory of clones, `orgs`, or anything holding a set of repositories, and every Git surface said the folder is not a repository, while every file open inside it was in one."""
    from leela.blocks.git.repos import discover
    a, b = _repo(tmp_path/'ramabana', 'main'), _repo(tmp_path/'rishi', 'dev')
    (tmp_path/'repos.txt').write_text('ramabana\nrishi\n')
    ws = Workspace(roots=[tmp_path])            # the container, not the checkouts
    assert [p.name for p in discover([tmp_path])] == ['ramabana', 'rishi'], 'both are found'
    with TestClient(ide_app(ws)) as client:
        assert client.get('/git/info').json()['repo'] is False, 'the container is not one itself'
        ws.open(str(a/'readme.md'))
        assert client.get('/git/info').json()['branch'] == 'main', "the open file's repository"
        ws.open(str(b/'readme.md'))
        d = client.get('/git/info').json()
        assert d['branch'] == 'dev' and d['root'] == str(b), 'and it follows to the next one'
        # An explicit choice still wins: a panel pinned to one repository stays there.
        assert client.get('/git/info', params={'repo': str(a)}).json()['branch'] == 'main'

def test_a_commit_file_names_its_repository_while_the_active_tab_is_in_another(tmp_path):
    "History listed one repository and the commit file request ran in the active tab's: unknown commit."
    a, b = _repo(tmp_path/'rupaka', 'main'), _repo(tmp_path/'vedicreader', 'main')
    (a/'a.py').write_text('x = 1\n'); git(a, 'add', '.'); git(a, 'commit', '-m', 'a only')
    sha = git(a, 'rev-parse', 'HEAD')
    ws = Workspace(roots=[a, b])
    with TestClient(ide_app(ws)) as client:
        ws.open(str(b/'readme.md'))
        assert client.get('/git/info').json()['root'] == str(b), 'precondition: the active tab is in B'
        bare = client.get('/git/commit/file', params={'ref': sha, 'path': 'a.py'})
        assert bare.status_code >= 400, 'without a repository the request runs in B, where the sha is unknown'
        r = client.get('/git/commit/file', params={'repo': str(a), 'ref': sha, 'path': 'a.py'})
        assert r.status_code == 200, r.text
        assert 'x = 1' in r.json()['patch']

def _outside(tmp_path, name):
    "A sibling of `tmp_path`, because the `repo` fixture *is* `tmp_path`."
    return tmp_path.parent/f'{tmp_path.name}-{name}'

def _bare_remote(repo_git, tmp_path, name='remote.git'):
    "A local bare repository standing in for a network remote, published from `repo`."
    remote = _outside(tmp_path, name)
    git(tmp_path.parent, 'init', '--bare', remote.name)
    git(repo_git, 'remote', 'add', 'origin', str(remote))
    git(repo_git, 'push', '-u', 'origin', 'main')
    git(remote, 'symbolic-ref', 'HEAD', 'refs/heads/main')
    return remote

def _await_job(client, jid, tries=300):
    for _ in range(tries):
        job = client.get('/git/clone/status', params={'job': jid}).json()
        if not job['active']: return job
        time.sleep(.05)
    raise AssertionError(f'job {jid} never finished')

def test_cloning_a_repository_into_a_folder_runs_as_a_job_and_can_then_be_opened(repo_git, tmp_path):
    "A clone is minutes of network, so `/git/clone` answers with a job, not a checkout."
    from starlette.testclient import TestClient
    from leela.app import ide_app
    remote = _bare_remote(repo_git, tmp_path)
    into = _outside(tmp_path, 'checkouts'); into.mkdir()
    with TestClient(ide_app(Workspace(roots=[repo_git]))) as client:
        landed = into/remote.name.removesuffix('.git')
        started = client.post('/git/clone', json={'url': str(remote), 'parent': str(into)}).json()
        assert started['root'] == str(landed), 'the folder name comes from the URL'
        job = _await_job(client, started['job']['id'])
        assert job['status'] == 'complete', job.get('error')
        assert (landed/'src'/'app.py').read_text() == 'value = 1\n'
        assert repo_root(landed) == landed and job['result']['root'] == str(landed)
        assert client.post('/fs/add-root', json={'path': str(landed)}, headers={'origin': 'http://testserver', 'sec-fetch-site': 'same-origin'}).json()['ok']
        assert client.post('/workspace/activate', json={'path': str(landed)}).json()['ok']
        assert client.get('/git/info').json()['root'] == str(landed)
        assert client.post('/git/clone', json={'url': str(remote), 'parent': str(into)}).json()['error']
        assert client.post('/git/clone',
            json={'url': str(remote), 'parent': str(_outside(tmp_path, 'imaginary'))}).json()['error']

def test_fetch_pull_and_push_are_the_same_one_route_the_panel_already_uses(repo_git, tmp_path):
    "The three top-bar icons add no route: `/git/action` has known all three all along."
    from starlette.testclient import TestClient
    from leela.app import ide_app
    remote = _bare_remote(repo_git, tmp_path, 'quick-remote.git')
    other = _outside(tmp_path, 'other')
    git(tmp_path.parent, 'clone', str(remote), other.name)
    git(other, 'config', 'user.email', 'tests@leela.local')
    git(other, 'config', 'user.name', 'Leela tests')
    (other/'src'/'app.py').write_text('value = 7\n')
    git(other, 'commit', '-am', 'upstream work')
    git(other, 'push', 'origin', 'main')
    with TestClient(ide_app(Workspace(roots=[repo_git]))) as client:
        assert client.post('/git/action', json={'op': 'fetch'}).json()['behind'] == 1
        assert client.post('/git/action', json={'op': 'pull'}).json()['behind'] == 0
        assert (repo_git/'src'/'app.py').read_text() == 'value = 7\n'
        (repo_git/'notes.txt').write_text('local work\n')
        git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'local work')
        assert client.post('/git/action', json={'op': 'push'}).json()['ahead'] == 0
        git(repo_git, 'checkout', '-b', 'fresh')
        d = client.post('/git/action', json={'op': 'push', 'publish': True}).json()
        assert d['upstream'] == 'origin/fresh' and d['ahead'] == 0

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

def test_a_fastws_repos_file_is_read_where_it_lands(workspace, tmp_path):
    "A `repos.txt` naming a checkout outside the folder still puts it in the workspace."
    outside = make_repo(tmp_path/'elsewhere'/'delta')
    (workspace/MEMBERS).write_text('# the workspace\nalpha\n'
                                  f'{outside}\n'
                                  'https://github.com/AnswerDotAI/fastws.git\n')
    names = [p.name for p in repo_set(workspace, tmp_path).paths()]
    assert names == ['alpha', 'beta', 'gamma', 'delta']

def test_a_repository_the_workspace_does_not_list_is_refused(workspace, tmp_path):
    "The security boundary for every repository-targeted route: discovery, not resolution."
    outside = make_repo(tmp_path/'stranger')
    repos = repo_set(workspace, tmp_path)
    assert repos.require(workspace/'alpha') == workspace/'alpha'
    with pytest.raises(GitError):
        repos.require(outside)
    with pytest.raises(GitError):
        repos.require('/etc')

def test_a_batch_reports_every_repository_and_one_failure_does_not_end_it(workspace, tmp_path):
    "`fetch` across a workspace where one member has no remote at all."
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
    "Nothing in a batch invents a remote or publishes a branch."
    remote = tmp_path/'origin.git'
    git(tmp_path, 'init', '--bare', remote.name)
    alpha = workspace/'alpha'
    git(alpha, 'remote', 'add', 'origin', str(remote))
    git(alpha, 'push', '-u', 'origin', 'main')
    repos = repo_set(workspace, tmp_path)
    pulled = {r['name']: r for r in repos.run('pull')}
    assert pulled['alpha']['skipped'] and pulled['beta']['skipped']
    pushed = {r['name']: r for r in repos.run('push')}
    assert pushed['alpha']['skipped'] and pushed['gamma']['skipped']
    (alpha/'seed.py').write_text('value = 4\n')
    git(alpha, 'commit', '-am', 'local work')
    assert repos.run('push', [alpha])[0]['ok']
    assert git(remote, 'log', '-1', '--format=%s', 'main') == 'local work'

def test_a_folder_without_a_repository_is_an_answer_not_an_error(tmp_path):
    """Every boot in a non-repo folder logged a console error, because "there is no repository here" came back as HTTP 400, which also made a real 400 from this route indistinguishable."""
    from starlette.testclient import TestClient
    from leela.app import ide_app
    plain = tmp_path/'notes'; plain.mkdir(); (plain/'a.md').write_text('# a\n')
    with TestClient(ide_app(Workspace(roots=[plain]))) as client:
        r = client.get('/git/info')
        assert r.status_code == 200, 'a folder with no git in it is not a client error'
        assert r.json()['repo'] is False

def test_the_pull_request_panel_gets_a_blocking_github_client(monkeypatch, tmp_path):
    """`GhApi` defaults to `sync=False`, and gheasy below 0.0.7 took that default: `pulls.list(...)` handed back a coroutine nobody awaited, `first` raised, and the panel reported `GitHub: ...` instead of the pull request."""
    from inspect import iscoroutinefunction
    from leela.blocks.git import hub
    g = pytest.importorskip('gheasy.core')
    monkeypatch.setattr(g, '_get_repo_slug', lambda path='.': ('vedicreader', 'leela'))
    monkeypatch.setattr('leela.blocks.git.seam.gh_token', lambda *a, **kw: 'tok')
    api, owner, name = hub._api(str(tmp_path))
    assert not iscoroutinefunction(type(api.pulls.list).__call__)
    assert (owner, name) == ('vedicreader', 'leela')

def test_deleting_a_branch_or_a_stash_reports_the_commit_it_was_at(tmp_path):
    """Git prints `Deleted branch x (was abc1234)` and the gateway returns None, so the sha never reached the panel."""
    from leela.blocks.git.app import _dropped
    from leela.blocks.git.git import GitRepo
    r = GitRepo.at(_repo(tmp_path/'repo', 'main'))
    r.run('branch', 'feature')
    out = _dropped(r, 'feature', False)
    assert out['deleted'] == 'feature' and len(out['was']) >= 7
    assert out['recover'] == f"git branch feature {out['was']}"
    r.run('branch', 'feature', out['was'])          # and the command it gives actually works
    assert 'feature' in r.run('branch', '--list', 'feature')

def staged_now(root):
    "Which paths the index holds differently from HEAD."
    return git(root, 'diff', '--cached', '--name-only').split()

def unmerged_now(root, path='src/app.py'):
    "Whether the index still holds this path's three conflict stages."
    return bool(git(root, 'ls-files', '-u', '--', path).strip())

def reviewable(repo_git):
    "A branch ahead of a clean, checked-out main: what `can_apply` in a review needs."
    r, path = GitRepo.at(repo_git), repo_git/'src'/'app.py'
    r.create('feature'); path.write_text('value = 2\n')
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'the feature')
    r.checkout('main')
    return r, path

def reviewing(client, path='src/app.py'):
    return client.get('/git/review/file', params={'base': 'main', 'head': 'feature', 'path': path})

MERGED = 'value = 3\n'

def applying(client, **extra):
    return gitop(client, op='write_worktree', path='src/app.py', content=MERGED, **extra)

def test_applying_a_reviewed_result_refuses_when_the_file_moved_under_the_panes(repo_git):
    "The merge pane's write went over whatever was on disk now, destroying it silently."
    _, path = reviewable(repo_git)
    c, ws = served([repo_git])
    reviewing(c)
    path.write_text('someone else got here first\n')
    r = applying(c)
    assert r.status_code == 409 and r.json()['ok'] is False
    assert path.read_text() == 'someone else got here first\n', 'their work is still there'
    assert journalled(ws, 'Git write worktree') is None

def test_a_notebook_is_never_written_from_a_diff_pane(repo_git):
    "Those panes hold decoded cell sources, so writing them back would flatten the notebook."
    write_nb(repo_git/'nb.ipynb', NOTEBOOK['cells'])
    c, _ = served([repo_git])
    r = gitop(c, op='write_worktree', path='nb.ipynb', content='x = 1\n', before='')
    assert r.status_code == 400 and r.json()['error']
    assert (repo_git/'nb.ipynb').read_text().startswith('{')

def test_undoing_a_resolution_puts_gits_index_back_too(repo_git):
    "Undo restored the text and left the file staged, so only `git reset` finished the job."
    _, path = conflicted(repo_git, MIXED_OURS, MIXED_THEIRS)
    c, _ = served([repo_git])
    c.get('/git/conflict', params={'path': 'src/app.py'})
    assert resolving(c).status_code == 200
    assert staged_now(repo_git) == ['src/app.py'] and not unmerged_now(repo_git)
    assert c.post('/history/undo', json={}).json()['ok']
    assert '<<<<<<<' in path.read_text()
    assert unmerged_now(repo_git), 'conflicted again, all three stages, as it was'

def test_undoing_a_resolution_after_the_merge_was_committed_only_unstages(repo_git):
    "Making a file conflicted again with no merge to finish leaves a state the IDE cannot end."
    _, path = conflicted(repo_git, MIXED_OURS, MIXED_THEIRS)
    c, _ = served([repo_git])
    c.get('/git/conflict', params={'path': 'src/app.py'})
    resolving(c)
    git(repo_git, 'commit', '-m', 'merged')
    assert c.post('/history/undo', json={}).json()['operation']['note']
    assert staged_now(repo_git) == [] and not unmerged_now(repo_git)
    assert '<<<<<<<' in path.read_text(), 'the text is still put back'

def test_a_git_row_that_staged_nothing_leaves_the_index_alone(repo_git):
    "Only what the operation staged may be taken back out, never what was staged before it."
    c, _ = served([repo_git])
    (repo_git/'src'/'app.py').write_text('value = 2\n')
    git(repo_git, 'add', '--', 'src/app.py')
    assert gitop(c, op='ignore', path='build').status_code == 200
    assert c.post('/history/undo', json={}).json()['ok']
    assert staged_now(repo_git) == ['src/app.py'], 'their staging is untouched'

def whole_side(client, choice, before, path='src/app.py'):
    return gitop(client, op='resolve_conflict', path=path, choice=choice, before=before)

def test_choosing_ours_is_journalled_versioned_and_undoable(repo_git):
    """`ours` was a Git checkout rather than a write through `saver`, so it staged a file and left no journal row at all."""
    _, path = conflicted(repo_git, MIXED_OURS, MIXED_THEIRS)
    markers = path.read_text()
    c, ws = served([repo_git])
    assert whole_side(c, 'ours', markers).status_code == 200
    assert path.read_text() == MIXED_OURS
    # `ours` is what HEAD already holds, so it is staged without differing from it.
    assert not unmerged_now(repo_git)
    op = journalled(ws, 'Git resolve conflict')
    assert op and op['paths'] == [str(path)] and op['reversible']
    assert ws.history.rows(str(path))
    assert c.post('/history/undo', json={}).json()['ok']
    assert path.read_text() == markers
    assert unmerged_now(repo_git), 'conflicted again, all three stages, as it was'

def binary_conflict(repo_git):
    "Leave `repo` mid-merge with a binary file conflicted, which is `choose one complete side`."
    r, path = GitRepo.at(repo_git), repo_git/'src'/'logo.bin'
    path.write_bytes(b'\x00base\x00')
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'the binary')
    r.create('other'); path.write_bytes(b'\x00theirs\x00')
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'other side')
    r.checkout('main'); path.write_bytes(b'\x00ours\x00')
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'main side')
    assert subprocess.run(['git', 'merge', 'other'], cwd=repo_git, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode != 0
    return r, path

def test_a_binary_side_leaves_a_row_and_an_undo_that_puts_the_bytes_back(repo_git):
    "Its bodies cannot be journal text, so the row carries the stages the bytes are still in."
    _, path = binary_conflict(repo_git)
    assert path.read_bytes() == b'\x00ours\x00', 'git leaves our version in the tree'
    c, ws = served([repo_git])
    c.get('/git/conflict', params={'path': 'src/logo.bin'})
    r = gitop(c, op='resolve_conflict', path='src/logo.bin', choice='theirs')
    assert r.status_code == 200 and path.read_bytes() == b'\x00theirs\x00'
    op = journalled(ws, 'Git resolve conflict')
    assert op and op['reversible'] and op['paths'] == [str(path)]
    undone = c.post('/history/undo', json={}).json()
    assert undone['ok'] and not undone['operation']['note']
    assert path.read_bytes() == b'\x00ours\x00', 'the bytes are back'
    assert unmerged_now(repo_git, 'src/logo.bin'), 'conflicted again, all three stages'

def test_a_side_that_deleted_the_file_is_never_staged_as_an_empty_one(repo_git):
    """`git show :3:` is `''` for a missing stage, so writing it would stage the empty blob and finish the merge with content nobody chose."""
    r, path = GitRepo.at(repo_git), repo_git/'src'/'app.py'
    r.create('other'); git(repo_git, 'rm', '-q', 'src/app.py')
    git(repo_git, 'commit', '-m', 'deleted on the other side')
    r.checkout('main'); path.write_text('value = 2\n')
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'edited on main')
    assert subprocess.run(['git', 'merge', 'other'], cwd=repo_git, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode != 0
    c, ws = served([repo_git])
    r2 = gitop(c, op='resolve_conflict', path='src/app.py', choice='theirs',
               before=path.read_text())
    assert r2.status_code == 200 and not path.exists()
    assert git(repo_git, 'ls-files', '-s', '--', 'src/app.py') == '', 'no blob at all, empty or not'
    assert git(repo_git, 'diff', '--cached', '--name-status') == 'D\tsrc/app.py'
    assert journalled(ws, 'Git resolve conflict')

def test_a_symlink_side_is_still_a_checkout(repo_git):
    "A text write of `git show :2:` would write the link's target through it into another file."
    r = GitRepo.at(repo_git)
    (repo_git/'src'/'one.py').write_text('one\n'); (repo_git/'src'/'two.py').write_text('two\n')
    (repo_git/'src'/'link').symlink_to('one.py')
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'a link')
    r.create('other')
    (repo_git/'src'/'link').unlink(); (repo_git/'src'/'link').symlink_to('two.py')
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'other side')
    r.checkout('main')
    (repo_git/'src'/'link').unlink(); (repo_git/'src'/'link').symlink_to('src/app.py')
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'main side')
    assert subprocess.run(['git', 'merge', 'other'], cwd=repo_git, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode != 0
    c, _ = served([repo_git])
    c.get('/git/conflict', params={'path': 'src/link'})
    assert gitop(c, op='resolve_conflict', path='src/link', choice='ours').status_code == 200
    link = repo_git/'src'/'link'
    assert link.is_symlink() and str(link.readlink()) == 'src/app.py'
    assert (repo_git/'src'/'one.py').read_text() == 'one\n', 'nothing was written through the link'

def modify_delete(repo_git, deleted_by, name='src/app.py', body=None):
    """Leave `repo` mid-merge with one side holding no file at all."""
    r, path = GitRepo.at(repo_git), repo_git/name
    path.parent.mkdir(parents=True, exist_ok=True)
    if body is not None: path.write_bytes(body)
    else: path.write_text('base\n')
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'the file')
    r.create('other')
    if deleted_by == 'theirs': git(repo_git, 'rm', '-q', '--', name)
    elif body is not None: path.write_bytes(b'\x00theirs\x00')
    else: path.write_text('theirs\n')
    git(repo_git, 'add', '-A'); git(repo_git, 'commit', '-m', 'other side')
    r.checkout('main')
    if deleted_by == 'ours': git(repo_git, 'rm', '-q', '--', name)
    elif body is not None: path.write_bytes(b'\x00ours\x00')
    else: path.write_text('ours\n')
    git(repo_git, 'add', '-A'); git(repo_git, 'commit', '-m', 'main side')
    assert subprocess.run(['git', 'merge', 'other'], cwd=repo_git, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode != 0
    return r, path

@pytest.mark.parametrize('deleted_by', ['ours', 'theirs'])
def test_a_deleted_side_undoes_back_to_a_conflict(repo_git, deleted_by):
    "Undo has to bring the file back and put the stages back, or the merge cannot be finished."
    _, path = modify_delete(repo_git, deleted_by)
    survives = path.read_text()
    c, _ = served([repo_git])
    assert whole_side(c, deleted_by, survives).status_code == 200
    assert c.post('/history/undo', json={}).json()['ok']
    assert path.read_text() == survives
    assert unmerged_now(repo_git), 'conflicted again, the stages it had, as it was'

def test_a_batch_that_fails_part_way_leaves_nothing_staged(repo_git, monkeypatch):
    """`resolve_safe_conflicts` writes and stages one file at a time, so a failure on the second file leaves the first one's conflict stages already collapsed to one settled blob."""
    _, path = conflicted(repo_git, MIXED_OURS, MIXED_THEIRS)
    same = 'top\n<<<<<<< HEAD\nsame\n=======\nsame\n>>>>>>> other\nnext\n'
    path.write_text(same)
    c, ws = served([repo_git])
    c.get('/git/conflicts')
    def boom(self): raise OSError('the disk went away')
    monkeypatch.setattr(GitRepo, 'conflict_plan', boom)
    assert gitop(c, op='resolve_safe_conflicts', paths=['src/app.py']).status_code != 200
    assert path.read_text() == same, 'the write it did make is put back'
    assert unmerged_now(repo_git), 'and so are the conflict stages it staged over'
    assert journalled(ws, 'Git resolve safe conflicts') is None

def _nb_text(cells):
    "A notebook whose cells are `(id, source)` pairs, written the way nbformat writes them."
    import json
    return json.dumps({'cells': [{'id': i, 'cell_type': 'code', 'metadata': {}, 'execution_count': 1,
                                  'outputs': [{'output_type': 'stream', 'name': 'stdout', 'text': ['old\n']}],
                                  'source': [src]} for i, src in cells],
                       'metadata': {'kernelspec': {'name': 'python3'}}, 'nbformat': 4, 'nbformat_minor': 5},
                      indent=1) + '\n'

def _conflicted_notebook(tmp_path):
    "A repository mid-merge, with one notebook conflicted on one cell and added on another."
    import subprocess
    root = tmp_path/'repo'; root.mkdir()
    run = lambda *a: subprocess.run(['git', *a], cwd=root, check=True, capture_output=True, text=True)
    run('init', '-q', '-b', 'main')
    run('config', 'user.email', 't@example.com'); run('config', 'user.name', 'T')
    nb = root/'n.ipynb'
    nb.write_text(_nb_text([('a', 'x = 1'), ('b', 'y = 1')]))
    run('add', 'n.ipynb'); run('commit', '-qm', 'base')
    run('checkout', '-qb', 'other')
    nb.write_text(_nb_text([('a', 'x = 3'), ('b', 'y = 1'), ('c', 'theirs_only = 1')]))
    run('commit', '-qam', 'theirs')
    run('checkout', '-q', 'main')
    nb.write_text(_nb_text([('a', 'x = 2'), ('b', 'y = 1')]))
    run('commit', '-qam', 'ours')
    merge = subprocess.run(['git', 'merge', 'other'], cwd=root, capture_output=True, text=True)
    assert merge.returncode != 0, 'the merge is supposed to conflict'
    return root, nb

def test_a_conflicted_notebook_is_read_as_cells_not_as_marked_up_json(tmp_path):
    """The worktree file carries conflict markers, so the text panes showed unreadable JSON."""
    root, nb = _conflicted_notebook(tmp_path)
    assert '<<<<<<<' in nb.read_text(), 'precondition: the file on disk is marked up'
    ws = Workspace(roots=[root])
    with TestClient(ide_app(ws)) as client:
        d = client.get('/git/notebook/conflict', params={'path': str(nb)}).json()
    assert d['notebook'] and d['owed'] == 2, d
    states = {r['key']: r['state'] for r in d['rows']}
    assert states == {'a': 'both', 'b': 'same', 'c': 'added'}, states
    a = first(r for r in d['rows'] if r['key'] == 'a')
    assert ''.join(a['ours']['source']) == 'x = 2' and ''.join(a['theirs']['source']) == 'x = 3'

def test_choosing_per_cell_writes_a_notebook_and_settles_the_merge(tmp_path):
    "What the buttons do: one side, the other, or both, and the file that comes out is a notebook."
    import json
    root, nb = _conflicted_notebook(tmp_path)
    ws = Workspace(roots=[root])
    with TestClient(ide_app(ws)) as client:
        r = client.post('/git/notebook/conflict/resolve',
                        json={'path': str(nb), 'choices': {'a': 'both', 'c': 'ours'}}).json()
        assert r.get('ok') is not False, r
        book = json.loads(nb.read_text())
        sources = [''.join(c['source']) for c in book['cells']]
        assert sources == ['x = 2', 'x = 3', 'y = 1'], sources
        assert book['metadata']['kernelspec']['name'] == 'python3', 'the notebook keeps its own metadata'
        decided = [c for c in book['cells'] if ''.join(c['source']).startswith('x =')]
        assert all(c['outputs'] == [] and c['execution_count'] is None for c in decided), \
            'a cell somebody decided about comes back without a run that belongs to another source'
        assert len({c['id'] for c in book['cells']}) == 3, 'both sides of one cell are two cells with two ids'
        status = client.get('/git/info').json()
        assert not [c for c in status['changes'] if c['conflicted']], 'the merge has nothing left to settle'

def test_a_git_diff_carries_its_code_coloured_line_for_line(repo_git):
    """The git diff views were green and red text; `/git/diff` now sends `ramabana.hl.diff_html` beside each patch."""
    (repo_git/'src'/'app.py').write_text('value = "a<b"\n')
    client, _ = served([repo_git])
    d = client.get('/git/diff', params={'path': 'src/app.py'}).json()
    lines = d['text'].split('\n')
    assert len(d['text_hl']) == len(lines) and len(d['content_hl']) == len(d['content'].split('\n'))
    added = lines.index('+value = "a<b"')
    assert '&lt;' in d['text_hl'][added]
    assert all(d['text_hl'][i] is None for i, l in enumerate(lines) if l.startswith(('diff ', 'index ', '@@', '---', '+++')))

def test_a_notebook_in_no_repository_has_no_changes_and_no_error(tmp_path):
    "Smoke round 4: each lesson that opened in a folder with no Git gave the page a 400 from /git/notebook."
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.blocks.nb.nb import Notebook
    from leela.workspace import Workspace
    from gheasy.repo import repo_root
    assert repo_root(tmp_path) is None
    Notebook.blank().save(p := tmp_path/'lesson.ipynb')
    ws = Workspace(roots=[tmp_path])
    try:
        with TestClient(ide_app(ws), base_url='http://127.0.0.1:5011') as c:
            r = c.get('/git/notebook', params=dict(path=str(p)))
            assert r.status_code == 200 and r.json() == dict(path=str(p), git=False, changed=False, cells={}, lines={})
            assert c.get('/git/notebook', params=dict(path='/etc/hosts')).status_code == 400, 'a path outside the open folders is still refused'
    finally: ws.shutdown_now()
