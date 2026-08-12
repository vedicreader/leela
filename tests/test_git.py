import subprocess
import time

import pytest

from leela.blocks.agent.ai import GIT_WRITE_TOOLS, WRITE_TOOLS, _git_tools
from leela.blocks.git.git import GitError, GitRepo, repo_root
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


def test_untracked_text_can_be_reviewed_before_staging(repo):
    path = repo/'new-untracked.py'
    path.write_text('answer = 42\n')
    view = GitRepo.at(repo).diff_view('new-untracked.py')
    assert '+answer = 42' in view['content']
    assert '--- /dev/null' in view['content']
    assert not GitRepo.at(repo).info()['changes'][0]['staged']


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


def test_reviewed_split_result_can_replace_a_worktree_file_without_staging(repo):
    r = GitRepo.at(repo)
    r.write_worktree('src/app.py', 'value = 9\n')
    assert (repo/'src'/'app.py').read_text() == 'value = 9\n'
    change = r.info()['changes'][0]
    assert change['unstaged'] and not change['staged']
    with pytest.raises(GitError, match='outside the repository'):
        r.write_worktree('../outside.py', 'unsafe\n')


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


def test_compare_uses_complete_ref_snapshots_when_target_branch_is_behind(repo):
    r = GitRepo.at(repo)
    r.create('behind')
    r.checkout('main')
    (repo/'main-only.txt').write_text('visible in a direct snapshot comparison\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-m', 'advance main')

    # A three-dot `main...behind` patch is empty because it only considers changes made
    # on the right after the merge base. The IDE must still show the actual file delta.
    comparison = r.compare('main', 'behind')
    assert comparison['left_only'] == 1 and comparison['right_only'] == 0
    assert comparison['changed_files'] == 1
    assert 'main-only.txt' in comparison['patch']
    assert '-visible in a direct snapshot comparison' in comparison['patch']
    assert comparison['merge_base']


def test_structured_review_separates_proposed_changes_from_snapshot_drift(repo):
    r = GitRepo.at(repo)
    r.create('feature')
    (repo/'feature.txt').write_text('feature\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-m', 'feature commit')
    r.checkout('main')
    (repo/'main.txt').write_text('main\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-m', 'main commit')

    proposed = r.review('main', 'feature', 'review')
    assert [f['path'] for f in proposed['files']] == ['feature.txt']
    assert proposed['head_only'] == 1 and proposed['base_only'] == 1
    assert proposed['summary']['additions'] == 1 and not proposed['can_apply']
    detail = r.review_file('main', 'feature', 'feature.txt', 'review')
    assert '+feature' in detail['patch']
    assert detail['left'] == '' and detail['right'] == 'feature\n'

    snapshots = r.review('main', 'feature', 'snapshot')
    assert {f['path'] for f in snapshots['files']} == {'feature.txt', 'main.txt'}


def test_directional_review_explains_snapshot_differences_when_head_is_ancestor(repo):
    r = GitRepo.at(repo)
    r.create('ahead')
    (repo/'ahead.txt').write_text('only on ahead\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-m', 'ahead work')

    result = r.review('ahead', 'main', 'review')
    assert result['files'] == [] and result['head_only'] == 0 and result['base_only'] == 1
    assert result['snapshot_alternative'] == {'files': 1, 'additions': 0, 'deletions': 1}
    snapshot = r.review('ahead', 'main', 'snapshot')
    assert [f['path'] for f in snapshot['files']] == ['ahead.txt']


def test_merge_preview_reports_relation_conflicts_and_stats(repo):
    r = GitRepo.at(repo)
    r.create('incoming')
    (repo/'src'/'app.py').write_text('incoming = True\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-m', 'incoming side')
    r.checkout('main')
    (repo/'src'/'app.py').write_text('main = True\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-m', 'main side')

    preview = r.merge_preview('incoming')
    assert preview['relation'] == 'diverged' and preview['clean']
    assert preview['conflict_likely'] and 'src/app.py' in preview['conflicts']
    assert preview['review']['head_only'] == 1


def test_rebase_preview_lists_commits_without_moving_history(repo):
    r = GitRepo.at(repo)
    r.create('feature')
    (repo/'feature.py').write_text('feature = True\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-m', 'feature work')
    before = git(repo, 'rev-parse', 'HEAD')

    preview = r.rebase_preview('main')
    assert preview['current'] == 'feature' and preview['clean']
    assert [c['subject'] for c in preview['commits']] == ['feature work']
    assert preview['already_based']
    assert git(repo, 'rev-parse', 'HEAD') == before


def test_compare_accepts_remote_tracking_refs(repo, tmp_path):
    remote = tmp_path.parent/f'{tmp_path.name}-compare-remote.git'
    git(tmp_path.parent, 'init', '--bare', remote.name)
    git(repo, 'remote', 'add', 'origin', str(remote))
    git(repo, 'push', '-u', 'origin', 'main')
    git(repo, 'checkout', '-b', 'remote-work')
    (repo/'remote.txt').write_text('remote branch content\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-m', 'remote work')
    git(repo, 'push', 'origin', 'remote-work')
    git(repo, 'checkout', 'main')
    git(repo, 'branch', '-D', 'remote-work')

    comparison = GitRepo.at(repo).compare('main', 'origin/remote-work')
    assert comparison['right_only'] == 1 and comparison['changed_files'] == 1
    assert '+remote branch content' in comparison['patch']


def test_commit_review_is_file_first_and_loads_each_diff_lazily(repo):
    path = repo/'src'/'app.py'
    path.write_text('value = 2\n')
    (repo/'added.py').write_text('added = True\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-m', 'two reviewed files')
    r = GitRepo.at(repo)

    review = r.commit_review('HEAD')
    assert review['message'] == 'two reviewed files'
    assert review['summary'] == {'files': 2, 'additions': 2, 'deletions': 1, 'binary': 0}
    assert {f['path'] for f in review['files']} == {'src/app.py', 'added.py'}
    detail = r.commit_file('HEAD', 'src/app.py')
    assert detail['left'] == 'value = 1\n' and detail['right'] == 'value = 2\n'
    assert '-value = 1' in detail['patch'] and '+value = 2' in detail['patch']


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
    import json
    doc = {**NOTEBOOK, 'cells': cells}
    path.write_text(json.dumps(doc, indent=1) + '\n')
    return path


def test_blaming_a_notebook_reports_cells_of_source_not_lines_of_json(repo):
    """The whole point: `git blame` on an .ipynb blames `"source": [` and escaped newlines.

    Each cell's source lines are matched back to the file lines that hold them, so the text
    is the code you wrote and the attribution beside it is the one Git gave that line.
    """
    write_nb(repo/'nb.ipynb', NOTEBOOK['cells'])
    git(repo, 'add', '.'); git(repo, 'commit', '-m', 'add the notebook')

    d = GitRepo.at(repo).blame_notebook('nb.ipynb')
    assert d['notebook'] and not d['error']
    assert [c['kind'] for c in d['cells']] == ['markdown', 'code']
    assert [c['index'] for c in d['cells']] == [1, 2]
    code = d['cells'][1]
    assert [l['text'] for l in code['lines']] == ['def add(a, b):', '    return a + b']
    assert [l['n'] for l in code['lines']] == [1, 2], 'numbered within the cell'
    assert all(l['author'] == 'Leela tests' for l in code['lines'])
    assert code['touched']['summary'] == 'add the notebook'
    assert code['id'] == 'b2' and code['mapped']


def test_a_notebook_cell_edited_later_shows_the_newer_commit(repo):
    "The reason to blame a notebook at all: which cell is the recent one."
    import os
    # Distinct commit dates on purpose: author time has one-second resolution, and two
    # commits made in the same second cannot be ordered from blame output at all.
    write_nb(repo/'nb.ipynb', NOTEBOOK['cells'])
    git(repo, 'add', '.')
    old_env = os.environ.get('GIT_AUTHOR_DATE'), os.environ.get('GIT_COMMITTER_DATE')
    os.environ['GIT_AUTHOR_DATE'] = os.environ['GIT_COMMITTER_DATE'] = '2024-01-01T09:00:00'
    git(repo, 'commit', '-m', 'first')
    changed = [NOTEBOOK['cells'][0],
               {**NOTEBOOK['cells'][1], 'source': ['def add(a, b):\n', '    return a + b + 0\n']}]
    write_nb(repo/'nb.ipynb', changed)
    git(repo, 'add', '.')
    os.environ['GIT_AUTHOR_DATE'] = os.environ['GIT_COMMITTER_DATE'] = '2024-02-02T09:00:00'
    git(repo, 'commit', '-m', 'second')
    for key, value in zip(('GIT_AUTHOR_DATE', 'GIT_COMMITTER_DATE'), old_env):
        if value is None: os.environ.pop(key, None)
        else: os.environ[key] = value

    cells = GitRepo.at(repo).blame_notebook('nb.ipynb')['cells']
    assert cells[0]['touched']['summary'] == 'first', 'the markdown cell was not touched'
    assert cells[1]['touched']['summary'] == 'second'
    # the unchanged line in the changed cell still belongs to the first commit
    assert {l['summary'] for l in cells[1]['lines']} == {'first', 'second'}
    assert len(cells[1]['commits']) == 2


def test_an_uncommitted_notebook_line_is_marked_rather_than_attributed(repo):
    """Working-tree lines are marked, not attributed to whoever came last.

    This also pins the one limitation inherited from blaming JSON: appending to a cell
    rewrites the line *before* it, because that entry gains a trailing comma. So the
    previous last line is reported as uncommitted too. Documented in `blame_notebook`,
    asserted here so it cannot change silently.
    """
    write_nb(repo/'nb.ipynb', NOTEBOOK['cells'])
    git(repo, 'add', '.'); git(repo, 'commit', '-m', 'first')
    edited = [NOTEBOOK['cells'][0],
              {**NOTEBOOK['cells'][1], 'source': ['def add(a, b):\n', '    return a + b\n', '    # new\n']}]
    write_nb(repo/'nb.ipynb', edited)

    cells = GitRepo.at(repo).blame_notebook('nb.ipynb')['cells']
    fresh = [l['text'] for l in cells[1]['lines'] if l['uncommitted']]
    assert '    # new' in fresh, 'the line that was actually added'
    assert fresh == ['    return a + b', '    # new'], 'and the comma-touched one before it'
    assert not any(l['uncommitted'] for l in cells[0]['lines']), 'the untouched cell is clean'
    assert cells[1]['touched']['uncommitted']


def test_a_notebook_that_cannot_be_mapped_says_so_instead_of_guessing(repo):
    "A wrong line here attributes someone else's code to you, so it reports nothing instead."
    import json
    (repo/'min.ipynb').write_text(json.dumps(NOTEBOOK))       # one line, no indentation
    git(repo, 'add', '.'); git(repo, 'commit', '-m', 'minified')

    d = GitRepo.at(repo).blame_notebook('min.ipynb')
    assert d['notebook'] and len(d['cells']) == 2
    # everything landed on the single physical line, so at most one cell can be mapped
    assert sum(1 for c in d['cells'] if c['lines']) <= 1


def test_a_file_that_is_not_a_notebook_falls_back_to_lines(repo):
    d = GitRepo.at(repo).blame_notebook('src/app.py')
    assert not d['notebook'] and d['error'] and d['lines'], 'the raw blame is still returned'


# ---------------------------------------------------------- notebook change marks

def _ipynb(cells):
    import json
    return json.dumps({'nbformat': 4, 'nbformat_minor': 5, 'metadata': {}, 'cells': [
        {'cell_type': 'code', 'source': src, 'metadata': {}, 'outputs': [],
         'execution_count': None, 'id': cid} for cid, src in cells]}) + '\n'


def test_a_notebooks_marks_are_per_cell_because_its_line_numbers_mean_nothing(repo):
    """An .ipynb is JSON: editing one cell moves every line below it.

    `file_changes` would answer "the whole document changed", which is true of the file and
    useless about the work. Cells carry nbformat ids that survive edits above them.
    """
    nb = repo/'work.ipynb'
    nb.write_text(_ipynb([('a', 'first = 1'), ('b', 'second = 2'), ('c', 'third = 3')]))
    git(repo, 'add', '.'); git(repo, 'commit', '-m', 'notebook')
    r = GitRepo(repo)
    assert r.notebook_changes('work.ipynb') == {'path': 'work.ipynb', 'changed': False,
                                                'cells': {}, 'lines': {}}

    nb.write_text(_ipynb([('a', 'first = 1'), ('b', 'second = 22'), ('c', 'third = 3'),
                          ('d', 'fourth = 4')]))
    out = r.notebook_changes('work.ipynb')
    assert out['changed'] is True
    assert out['cells'] == {'b': 'modified', 'd': 'added'}, 'the untouched cells stay unmarked'


def test_an_untracked_notebook_is_added_cell_by_cell(repo):
    (repo/'fresh.ipynb').write_text(_ipynb([('a', 'x = 1'), ('b', 'y = 2')]))
    assert GitRepo(repo).notebook_changes('fresh.ipynb')['cells'] == {'a': 'added', 'b': 'added'}


def test_notebook_changes_declines_anything_that_is_not_a_notebook(repo):
    (repo/'src'/'app.py').write_text('value = 2\n')
    out = GitRepo(repo).notebook_changes('src/app.py')
    assert out['changed'] is False and out['cells'] == {}, 'a .py file is answered by file_changes'


def test_a_modified_cell_says_which_of_its_own_lines_moved(repo):
    "Line numbers inside one cell's editor, which is the only place they are ever drawn."
    nb = repo/'work.ipynb'
    nb.write_text(_ipynb([('a', 'one\ntwo\nthree'), ('b', 'kept')]))
    git(repo, 'add', '.'); git(repo, 'commit', '-m', 'notebook')
    nb.write_text(_ipynb([('a', 'one\nTWO\nthree\nfour'), ('b', 'kept')]))
    out = GitRepo(repo).notebook_changes('work.ipynb')
    assert out['cells'] == {'a': 'modified'}
    assert out['lines']['a'] == [{'from': 2, 'to': 2, 'kind': 'modified'},
                                 {'from': 4, 'to': 4, 'kind': 'added'}]
    assert 'b' not in out['lines'], 'an untouched cell has nothing to draw'


def test_a_deleted_line_is_reported_where_the_text_closed_over_it(repo):
    "It has no line of its own in the new source, which is what git's `+n,0` hunk also means."
    nb = repo/'work.ipynb'
    nb.write_text(_ipynb([('a', 'one\ntwo\nthree')]))
    git(repo, 'add', '.'); git(repo, 'commit', '-m', 'notebook')
    nb.write_text(_ipynb([('a', 'one\nthree')]))
    ranges = GitRepo(repo).notebook_changes('work.ipynb')['lines']['a']
    assert ranges == [{'from': 2, 'to': 2, 'kind': 'deleted'}]


def test_every_line_of_a_new_cell_is_added(repo):
    nb = repo/'work.ipynb'
    nb.write_text(_ipynb([('a', 'kept')]))
    git(repo, 'add', '.'); git(repo, 'commit', '-m', 'notebook')
    nb.write_text(_ipynb([('a', 'kept'), ('b', 'x = 1\ny = 2')]))
    out = GitRepo(repo).notebook_changes('work.ipynb')
    assert out['cells']['b'] == 'added'
    assert out['lines']['b'] == [{'from': 1, 'to': 2, 'kind': 'added'}]


# ------------------------------------------------- which project the panels are about

def _repo(path, name):
    path.mkdir(parents=True, exist_ok=True)
    git(path, 'init', '-b', name)
    git(path, 'config', 'user.email', 'tests@leela.local')
    git(path, 'config', 'user.name', 'Leela tests')
    (path/'readme.md').write_text(f'# {name}\n')
    git(path, 'add', '.'); git(path, 'commit', '-m', 'initial')
    return path


def test_choosing_a_folder_moves_source_control_to_that_checkout(tmp_path):
    """The reported bug: open leela on one repo, add a second, switch -- git stayed behind.

    `roots[0]` was standing in for "which project is this about", so every project-scoped
    surface described the folder that happened to be opened first.
    """
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


def test_opening_a_file_in_another_checkout_says_which_project_too(tmp_path):
    from starlette.testclient import TestClient
    from leela.app import ide_app
    a, b = _repo(tmp_path/'ramabana', 'main'), _repo(tmp_path/'rishi', 'dev')
    ws = Workspace(roots=[a, b])
    ws.activate_root(b)
    ws.open(a/'readme.md')
    with TestClient(ide_app(ws)) as client:
        assert client.get('/git/info').json()['branch'] == 'main', 'the file you opened re-chooses'


def test_a_files_change_marks_come_from_its_own_repository_not_the_chosen_one(tmp_path):
    "Which project the panels are about is a choice; where a file's diff comes from is not."
    from starlette.testclient import TestClient
    from leela.app import ide_app
    a, b = _repo(tmp_path/'ramabana', 'main'), _repo(tmp_path/'rishi', 'dev')
    (a/'readme.md').write_text('# ramabana\nchanged\n')
    ws = Workspace(roots=[a, b])
    ws.activate_root(b)                      # panels point at rishi
    with TestClient(ide_app(ws)) as client:
        d = client.get('/git/file', params={'path': str(a/'readme.md')}).json()
    assert d.get('changed') is True and d['ranges'], 'the marks still come from ramabana'


def test_activating_a_folder_the_workspace_does_not_list_is_refused(tmp_path):
    from starlette.testclient import TestClient
    from leela.app import ide_app
    a = _repo(tmp_path/'ramabana', 'main')
    outside = tmp_path/'elsewhere'; outside.mkdir()
    ws = Workspace(roots=[a])
    with TestClient(ide_app(ws)) as client:
        assert 'error' in client.post('/workspace/activate', json={'path': str(outside)}).json()
    assert ws.project_root == a


def test_info_reports_the_head_a_watcher_needs_to_see_a_commit(repo):
    "Commit everything and the branch, the counts and the file list all read the same after."
    r = GitRepo.at(repo)
    before = r.info()
    (repo/'src'/'app.py').write_text('value = 2\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-m', 'second')
    # Committed by hand, the way lazygit or the agent would: nothing invalidated the shared
    # snapshot, so this waits out its half-second TTL rather than reaching past it.
    time.sleep(0.5)
    after = GitRepo.at(repo).info()
    assert before['branch'] == after['branch'] and before['clean'] == after['clean']
    assert len(before['changes']) == len(after['changes']) == 0
    assert before['head'] and after['head'] and before['head'] != after['head'], \
        'without this a commit is invisible to anything watching the snapshot'
