"The git block: one repository, its safety rails, and the workspace of many."

import json
import subprocess
import time
import pytest
from fastcore.basics import first
from leela.blocks.agent.ai import GIT_WRITE_TOOLS, WRITE_TOOLS
from ramabana.git import git_tools as _git_tools
from leela.blocks.git.git import GitError, GitRepo, repo_root
from leela.workspace import Workspace
import threading
from ramabana.git import GitGateway, classify, gateway
from leela.blocks.git.repos import MEMBERS, RepoSet, clone_url, discover

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

def test_repo_root_and_workspace_cwd_follow_git(repo_git):
    nested = repo_git/'src'/'app.py'
    assert repo_root(nested) == repo_git
    ws = Workspace(roots=[repo_git/'src']); tab = ws.open(nested)
    assert ws.cwd_for(tab) == repo_git
    ws.set_cwd(repo_git/'src', tab)
    assert ws.cwd_for(tab) == repo_git/'src'
    ws.set_cwd('', tab)
    assert ws.cwd_for(tab) == repo_git

def test_status_stage_unstage_branch_and_commit(repo_git):
    r = GitRepo.at(repo_git/'src')
    (repo_git/'src'/'app.py').write_text('value = 2\n')
    (repo_git/'notes.txt').write_text('work\n')
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

def test_tree_decoration_asks_git_once_per_burst_not_once_per_folder(repo_git, monkeypatch):
    "A file-tree refresh reads `changes()` once per open folder; three git runs each is the lag."
    from ramabana import git as safety
    runs, real = [], safety.GitGateway._exec
    monkeypatch.setattr(safety.GitGateway, '_exec',
        lambda self, cwd, args, **kw: (runs.append(args[0]), real(self, cwd, args, **kw))[1])
    r = GitRepo.at(repo_git)
    (repo_git/'src'/'app.py').write_text('value = 2\n')
    r.decorations(); runs.clear()
    for _ in range(8): r.decorations()
    assert not runs, f'every open folder pays for its own status: {runs}'
    seeded = r.info()['changes']; runs.clear()
    assert r.decorations() == seeded and not runs, '`info` seeds the same answer'
    r.stage(['src/app.py'])
    assert first(c for c in r.decorations() if c['path'] == 'src/app.py')['staged'], 'a write invalidates it'
    runs.clear(); r.changes()
    assert runs, 'the gutter still asks git directly -- it reads this straight after a save'

def test_ignore_adds_one_repository_relative_rule(repo_git):
    r = GitRepo.at(repo_git)
    rule = r.ignore('cache', directory=True)
    assert rule['rule'] == 'cache/' and (repo_git/'.gitignore').read_text() == 'cache/\n'
    r.ignore('cache', directory=True)
    assert (repo_git/'.gitignore').read_text() == 'cache/\n'
    with pytest.raises(GitError): r.ignore('../outside')

def test_fetch_exposes_remote_branches_and_checkout_tracks_them(repo_git, tmp_path):
    remote = tmp_path/'remote.git'
    git(tmp_path, 'init', '--bare', remote.name)
    git(repo_git, 'remote', 'add', 'origin', str(remote))
    git(repo_git, 'push', '-u', 'origin', 'main')
    git(repo_git, 'branch', 'remote-only')
    git(repo_git, 'push', 'origin', 'remote-only')
    git(repo_git, 'branch', '-D', 'remote-only')
    r = GitRepo.at(repo_git)
    r.fetch()
    branch = next(b for b in r.info()['branches'] if b['name'] == 'origin/remote-only')
    assert branch['remote'] and not branch['current']
    r.checkout('origin/remote-only')
    info = r.info()
    assert info['branch'] == 'remote-only'
    assert info['upstream'] == 'origin/remote-only'
    assert not any(b['name'] == 'origin/remote-only' for b in info['branches'])

def test_stash_tags_and_repository_metadata(repo_git):
    r = GitRepo.at(repo_git)
    (repo_git/'src'/'app.py').write_text('stashed = True\n')
    r.stash('checkpoint')
    info = r.info()
    assert info['stashes'] and info['stashes'][0]['subject'].endswith('checkpoint')
    assert 'remotes' in info and 'tags' in info
    r.stash_apply(info['stashes'][0]['ref'])
    assert 'stashed = True' in (repo_git/'src'/'app.py').read_text()
    git(repo_git, 'reset', '--hard', 'HEAD')
    r.stash_drop(info['stashes'][0]['ref'])
    r.tag('v0.1-test')
    assert 'v0.1-test' in r.info()['tags']

def test_file_changes_locate_modified_lines_for_the_editor(repo_git):
    p = repo_git/'src'/'app.py'
    p.write_text('value = 1\n\nchanged = True\n')
    detail = GitRepo.at(repo_git).file_changes('src/app.py')
    assert detail['changed'] and detail['diff']
    assert any(r['from'] <= 3 <= r['to'] for r in detail['ranges'])
    (repo_git/'new.py').write_text('one\ntwo\n')
    detail = GitRepo.at(repo_git).file_changes('new.py')
    assert detail['status']['untracked']
    assert detail['ranges'] == [{'from': 1, 'to': 2, 'kind': 'added'}]
    assert detail['hunks'] == [], 'an untracked file has no committed version to patch against'

def test_each_gutter_change_carries_its_own_appliable_patch(repo_git):
    "One click on a gutter mark has to be able to revert or stage exactly that change."
    (repo_git/'src'/'app.py').write_text('value = 1\nadded = True\n')
    (repo_git/'src'/'other.py').write_text('kept = 1\n')
    git(repo_git, 'add', 'src/other.py'), git(repo_git, 'commit', '-m', 'other')
    r = GitRepo.at(repo_git)
    hunks = r.file_changes('src/app.py')['hunks']
    assert len(hunks) == 1
    h = hunks[0]
    assert h['kind'] == 'added' and h['from'] == 2 and h['to'] == 2
    assert h['old'] == '' and h['new'] == 'added = True\n'
    assert h['patch'].startswith('diff --git') and '+added = True' in h['patch']
    r.apply_patch(h['patch'], staged=False, reverse=True)
    assert (repo_git/'src'/'app.py').read_text() == 'value = 1\n'
    (repo_git/'src'/'app.py').write_text('value = 2\ntail = 3\n')
    h = r.file_changes('src/app.py')['hunks'][0]
    assert h['kind'] == 'modified' and h['old'] == 'value = 1\n' and 'tail = 3' in h['new']
    (repo_git/'src'/'app.py').write_text('')
    h = r.file_changes('src/app.py')['hunks'][0]
    assert h['kind'] == 'deleted' and h['old'] == 'value = 1\n' and h['from'] == 1
    (repo_git/'src'/'app.py').write_text('value = 1\nonly = "this"\n')
    h = r.file_changes('src/app.py')['hunks'][0]
    r.apply_patch(h['patch'], staged=True)
    r.commit('just this change')
    assert 'only = "this"' in r.run('show', 'HEAD:src/app.py')

def test_untracked_text_can_be_reviewed_before_staging(repo_git):
    path = repo_git/'new-untracked.py'
    path.write_text('answer = 42\n')
    view = GitRepo.at(repo_git).diff_view('new-untracked.py')
    assert '+answer = 42' in view['content']
    assert '--- /dev/null' in view['content']
    assert not GitRepo.at(repo_git).info()['changes'][0]['staged']

def test_notebook_diff_defaults_to_cell_source_instead_of_json(repo_git):
    nb = repo_git/'analysis.ipynb'
    nb.write_text('{"cells":[{"cell_type":"code","source":["value = 1\\n"],"outputs":[],"metadata":{},"id":"noise"}],"metadata":{},"nbformat":4,"nbformat_minor":5}')
    r = GitRepo.at(repo_git)
    view = r.diff_view('analysis.ipynb')
    assert view['notebook'] and '# %% code · cell 1' in view['content']
    assert 'value = 1' in view['content']
    assert '"metadata"' not in view['content'] and '"outputs"' not in view['content']

def test_notebook_review_is_utf8_even_when_the_app_has_no_utf8_locale(repo_git, monkeypatch):
    nb = repo_git/'unicode.ipynb'
    nb.write_text('{"cells":[{"cell_type":"markdown","source":["plain\\n"],"metadata":{}}],"metadata":{},"nbformat":4,"nbformat_minor":5}')
    git(repo_git, 'add', 'unicode.ipynb'); git(repo_git, 'commit', '-m', 'unicode base')
    nb.write_text('{"cells":[{"cell_type":"markdown","source":["arrow → and café\\n"],"metadata":{}}],"metadata":{},"nbformat":4,"nbformat_minor":5}')
    monkeypatch.setenv('LC_ALL', 'C'); monkeypatch.setenv('LANG', 'C')
    view = GitRepo.at(repo_git).diff_view('unicode.ipynb')
    assert 'arrow → and café' in view['content']

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
    from leela.blocks.agent.ai import GIT_READ_TOOLS
    assert GIT_WRITE_TOOLS <= WRITE_TOOLS and not (set(GIT_READ_TOOLS) & WRITE_TOOLS), \
        'rehearsing a merge is not approving one'
    assert {'git_divergence', 'git_rebase_preview'} <= set(tools)
    fetched = tools['git_remote']('fetch')
    assert 'origin/from-agent' in fetched
    checked_out = tools['git_checkout']('origin/from-agent')
    assert '"branch": "from-agent"' in checked_out
    assert '"upstream": "origin/from-agent"' in checked_out
    from ramabana.tools import failed
    assert failed(tools['git_status'](str(repo_git.parent))), 'a path outside the roots is a message'
    from leela.blocks.agent.ai import GIT_TOOLS
    assert set(tools) == set(GIT_TOOLS)

def test_agent_checkout_reports_what_the_switch_said(repo_git, tmp_path):
    "`git_checkout` carries `GitRepo.checkout`'s message in the result the harness answers with."
    git(repo_git, 'branch', 'other')
    (repo_git/'app.py').write_text('print("uncommitted")\n')
    class Host:
        roots = [str(repo_git)]
        def check(self, path, must_exist=False):
            from pathlib import Path
            return Path(path or repo_git).resolve()
    checkout = {f.__name__: f for f in _git_tools(Host())}['git_checkout']
    out = checkout('other')
    from ramabana.tools import failed
    assert not failed(out), out
    assert '"branch": "other"' in out and '"result"' in out, out[:200]

def test_remote_head_is_not_a_branch_and_refs_explain_recency(repo_git, tmp_path):
    remote = tmp_path/'dated.git'
    git(tmp_path, 'init', '--bare', remote.name)
    git(repo_git, 'remote', 'add', 'origin', str(remote))
    git(repo_git, 'push', '-u', 'origin', 'main')
    git(remote, 'symbolic-ref', 'HEAD', 'refs/heads/main')
    git(repo_git, 'remote', 'set-head', 'origin', '--auto')
    rows = GitRepo.at(repo_git).info()['branches']
    assert 'origin' not in {row['name'] for row in rows}
    current = next(row for row in rows if row['current'])
    assert current['name'] == 'main' and current['timestamp'] > 0
    assert current['date'] and current['author'] == 'Leela tests'
    assert current['latest'] and current['default']

def test_reviewed_split_result_can_replace_a_worktree_file_without_staging(repo_git):
    r = GitRepo.at(repo_git)
    r.write_worktree('src/app.py', 'value = 9\n')
    assert (repo_git/'src'/'app.py').read_text() == 'value = 9\n'
    change = r.info()['changes'][0]
    assert change['unstaged'] and not change['staged']
    with pytest.raises(GitError, match='outside the repository'):
        r.write_worktree('../outside.py', 'unsafe\n')

def test_partial_hunk_staging_and_reversal(repo_git):
    path = repo_git/'src'/'app.py'
    path.write_text('value = 2\n')
    r = GitRepo.at(repo_git)
    patch = r.diff('src/app.py')
    assert '-value = 1' in patch and '+value = 2' in patch
    r.apply_patch(patch)
    change = r.info()['changes'][0]
    assert change['staged'] and not change['unstaged']
    r.apply_patch(patch, reverse=True)
    change = r.info()['changes'][0]
    assert not change['staged'] and change['unstaged']

def test_history_commit_compare_and_blame(repo_git):
    path = repo_git/'src'/'app.py'
    path.write_text('value = 2\n')
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'second value')
    r = GitRepo.at(repo_git)
    history = r.history()
    assert [row['subject'] for row in history[:2]] == ['second value', 'initial']
    detail = r.commit_detail(history[0]['oid'])
    assert detail['message'] == 'second value' and '+value = 2' in detail['patch']
    comparison = r.compare(history[1]['oid'], history[0]['oid'])
    assert comparison['right_only'] == 1 and '+value = 2' in comparison['patch']
    blamed = r.blame('src/app.py')
    assert blamed[0]['author'] == 'Leela tests' and blamed[0]['text'] == 'value = 2'

def test_compare_uses_complete_ref_snapshots_when_target_branch_is_behind(repo_git):
    r = GitRepo.at(repo_git)
    r.create('behind')
    r.checkout('main')
    (repo_git/'main-only.txt').write_text('visible in a direct snapshot comparison\n')
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'advance main')
    comparison = r.compare('main', 'behind')
    assert comparison['left_only'] == 1 and comparison['right_only'] == 0
    assert comparison['changed_files'] == 1
    assert 'main-only.txt' in comparison['patch']
    assert '-visible in a direct snapshot comparison' in comparison['patch']
    assert comparison['merge_base']

def test_structured_review_separates_proposed_changes_from_snapshot_drift(repo_git):
    r = GitRepo.at(repo_git)
    r.create('feature')
    (repo_git/'feature.txt').write_text('feature\n')
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'feature commit')
    r.checkout('main')
    (repo_git/'main.txt').write_text('main\n')
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'main commit')
    proposed = r.review('main', 'feature', 'review')
    assert [f['path'] for f in proposed['files']] == ['feature.txt']
    assert proposed['head_only'] == 1 and proposed['base_only'] == 1
    assert proposed['summary']['additions'] == 1 and not proposed['can_apply']
    detail = r.review_file('main', 'feature', 'feature.txt', 'review')
    assert '+feature' in detail['patch']
    assert detail['left'] == '' and detail['right'] == 'feature\n'
    snapshots = r.review('main', 'feature', 'snapshot')
    assert {f['path'] for f in snapshots['files']} == {'feature.txt', 'main.txt'}

def test_directional_review_explains_snapshot_differences_when_head_is_ancestor(repo_git):
    r = GitRepo.at(repo_git)
    r.create('ahead')
    (repo_git/'ahead.txt').write_text('only on ahead\n')
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'ahead work')
    result = r.review('ahead', 'main', 'review')
    assert result['files'] == [] and result['head_only'] == 0 and result['base_only'] == 1
    assert result['snapshot_alternative'] == {'files': 1, 'additions': 0, 'deletions': 1}
    snapshot = r.review('ahead', 'main', 'snapshot')
    assert [f['path'] for f in snapshot['files']] == ['ahead.txt']

def test_merge_preview_reports_relation_conflicts_and_stats(repo_git):
    r = GitRepo.at(repo_git)
    r.create('incoming')
    (repo_git/'src'/'app.py').write_text('incoming = True\n')
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'incoming side')
    r.checkout('main')
    (repo_git/'src'/'app.py').write_text('main = True\n')
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'main side')
    preview = r.merge_preview('incoming')
    assert preview['relation'] == 'diverged' and preview['clean']
    assert preview['conflict_likely'] and 'src/app.py' in preview['conflicts']
    assert preview['review']['head_only'] == 1

def test_rebase_preview_lists_commits_without_moving_history(repo_git):
    r = GitRepo.at(repo_git)
    r.create('feature')
    (repo_git/'feature.py').write_text('feature = True\n')
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'feature work')
    before = git(repo_git, 'rev-parse', 'HEAD')
    preview = r.rebase_preview('main')
    assert preview['current'] == 'feature' and preview['clean']
    assert [c['subject'] for c in preview['commits']] == ['feature work']
    assert preview['already_based']
    assert git(repo_git, 'rev-parse', 'HEAD') == before

def test_compare_accepts_remote_tracking_refs(repo_git, tmp_path):
    remote = tmp_path.parent/f'{tmp_path.name}-compare-remote.git'
    git(tmp_path.parent, 'init', '--bare', remote.name)
    git(repo_git, 'remote', 'add', 'origin', str(remote))
    git(repo_git, 'push', '-u', 'origin', 'main')
    git(repo_git, 'checkout', '-b', 'remote-work')
    (repo_git/'remote.txt').write_text('remote branch content\n')
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'remote work')
    git(repo_git, 'push', 'origin', 'remote-work')
    git(repo_git, 'checkout', 'main')
    git(repo_git, 'branch', '-D', 'remote-work')
    comparison = GitRepo.at(repo_git).compare('main', 'origin/remote-work')
    assert comparison['right_only'] == 1 and comparison['changed_files'] == 1
    assert '+remote branch content' in comparison['patch']

def test_commit_review_is_file_first_and_loads_each_diff_lazily(repo_git):
    path = repo_git/'src'/'app.py'
    path.write_text('value = 2\n')
    (repo_git/'added.py').write_text('added = True\n')
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'two reviewed files')
    r = GitRepo.at(repo_git)
    review = r.commit_review('HEAD')
    assert review['message'] == 'two reviewed files'
    assert review['summary'] == {'files': 2, 'additions': 2, 'deletions': 1, 'binary': 0}
    assert {f['path'] for f in review['files']} == {'src/app.py', 'added.py'}
    detail = r.commit_file('HEAD', 'src/app.py')
    assert detail['left'] == 'value = 1\n' and detail['right'] == 'value = 2\n'
    assert '-value = 1' in detail['patch'] and '+value = 2' in detail['patch']

def test_branch_lifecycle_structured_remotes_and_worktrees(repo_git, tmp_path):
    remote = tmp_path/'lifecycle.git'
    git(tmp_path, 'init', '--bare', remote.name)
    r = GitRepo.at(repo_git)
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

def test_conflict_versions_resolution_operation_state_and_reflog(repo_git):
    path = repo_git/'src'/'app.py'
    r = GitRepo.at(repo_git)
    r.create('other')
    path.write_text('other = True\n')
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'other side')
    r.checkout('main')
    path.write_text('main = True\n')
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'main side')
    merged = subprocess.run(['git', 'merge', 'other'], cwd=repo_git, text=True,
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

def test_conflict_blocks_span_the_whole_marker_and_survive_an_empty_side():
    "Each payload must be exactly what its span should become, newline included."
    from ramabana.git import _conflict_blocks
    text = 'a\n<<<<<<< HEAD\nx\n=======\n>>>>>>> o\nb\n'
    block, = _conflict_blocks(text)
    assert (block['ours'], block['theirs']) == ('x\n', '')
    assert text[:block['start']] + block['ours'] + text[block['end']:] == 'a\nx\nb\n'
    assert text[:block['start']] + block['theirs'] + text[block['end']:] == 'a\nb\n'
    assert _conflict_blocks('a\n<<<<<<< HEAD\nx\n') == []

def test_conflict_plan_counts_safe_and_manual_blocks(repo_git):
    r, _ = conflicted(repo_git, 'one\ntwo\n', 'ONE\ntwo\n')
    plan = r.conflict_plan()
    assert plan['operation']['active'] == 'merge'
    assert plan['summary'] == {'files': 1, 'blocks': 1, 'safe': 0, 'manual': 1}
    row = plan['files'][0]
    assert row['path'] == 'src/app.py' and row['kind'] == 'text' and row['reason']

def test_resolving_a_safe_conflict_keeps_the_line_break_it_replaced(repo_git):
    "The whole marker span is swapped for one side, so that side must keep its newline."
    r, path = conflicted(repo_git, MIXED_OURS, MIXED_THEIRS)
    path.write_text('top\n<<<<<<< HEAD\nsame\n=======\nsame\n>>>>>>> other\nnext\n')
    out = r.resolve_safe_conflicts(['src/app.py'])
    assert path.read_text() == 'top\nsame\nnext\n'
    assert out['resolved'] == [{'path': 'src/app.py', 'safe': 1, 'remaining': 0}]

def test_a_partly_resolved_file_is_written_but_not_staged(repo_git):
    "Staging is what marks a conflict settled, so it must wait for the last contested block."
    r, path = conflicted(repo_git, MIXED_OURS, MIXED_THEIRS)
    path.write_text('<<<<<<< HEAD\nsame\n=======\nsame\n>>>>>>> other\n' + path.read_text())
    out = r.resolve_safe_conflicts(['src/app.py'])
    assert out['resolved'] == [{'path': 'src/app.py', 'safe': 1, 'remaining': 1}]
    assert path.read_text().startswith('same\n') and '<<<<<<<' in path.read_text()
    assert first(c for c in r.info()['changes'] if c['path'] == 'src/app.py')['conflicted']

def test_conflicts_route_answers_json_for_a_clean_repo_and_a_stopped_merge(repo_git):
    from starlette.testclient import TestClient
    from leela.app import ide_app
    c = TestClient(ide_app(Workspace(roots=[repo_git])))
    d = c.get('/git/conflicts').json()
    assert d['files'] == [] and d['summary']['files'] == 0 and not d['operation']['active']
    conflicted(repo_git, 'one\ntwo\n', 'ONE\ntwo\n')
    d = c.get('/git/conflicts').json()
    assert [f['path'] for f in d['files']] == ['src/app.py'] and d['operation']['active'] == 'merge'

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

def test_a_notebook_cell_edited_later_shows_the_newer_commit(repo_git):
    "The reason to blame a notebook at all: which cell is the recent one."
    import os
    write_nb(repo_git/'nb.ipynb', NOTEBOOK['cells'])
    git(repo_git, 'add', '.')
    old_env = os.environ.get('GIT_AUTHOR_DATE'), os.environ.get('GIT_COMMITTER_DATE')
    os.environ['GIT_AUTHOR_DATE'] = os.environ['GIT_COMMITTER_DATE'] = '2024-01-01T09:00:00'
    git(repo_git, 'commit', '-m', 'first')
    changed = [NOTEBOOK['cells'][0],
               {**NOTEBOOK['cells'][1], 'source': ['def add(a, b):\n', '    return a + b + 0\n']}]
    write_nb(repo_git/'nb.ipynb', changed)
    git(repo_git, 'add', '.')
    os.environ['GIT_AUTHOR_DATE'] = os.environ['GIT_COMMITTER_DATE'] = '2024-02-02T09:00:00'
    git(repo_git, 'commit', '-m', 'second')
    for key, value in zip(('GIT_AUTHOR_DATE', 'GIT_COMMITTER_DATE'), old_env):
        if value is None: os.environ.pop(key, None)
        else: os.environ[key] = value
    cells = GitRepo.at(repo_git).blame_notebook('nb.ipynb')['cells']
    assert cells[0]['touched']['summary'] == 'first', 'the markdown cell was not touched'
    assert cells[1]['touched']['summary'] == 'second'
    assert {l['summary'] for l in cells[1]['lines']} == {'first', 'second'}
    assert len(cells[1]['commits']) == 2

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

def test_a_notebook_that_cannot_be_mapped_says_so_instead_of_guessing(repo_git):
    "A wrong line here attributes someone else's code to you, so it reports nothing instead."
    (repo_git/'min.ipynb').write_text(json.dumps(NOTEBOOK))
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'minified')
    d = GitRepo.at(repo_git).blame_notebook('min.ipynb')
    assert d['notebook'] and len(d['cells']) == 2
    assert sum(1 for c in d['cells'] if c['lines']) <= 1

def test_a_file_that_is_not_a_notebook_falls_back_to_lines(repo_git):
    d = GitRepo.at(repo_git).blame_notebook('src/app.py')
    assert not d['notebook'] and d['error'] and d['lines'], 'the raw blame is still returned'

def _ipynb(cells):
    return json.dumps({'nbformat': 4, 'nbformat_minor': 5, 'metadata': {}, 'cells': [
        {'cell_type': 'code', 'source': src, 'metadata': {}, 'outputs': [],
         'execution_count': None, 'id': cid} for cid, src in cells]}) + '\n'

def test_a_notebooks_marks_are_per_cell_because_its_line_numbers_mean_nothing(repo_git):
    "An .ipynb is JSON: editing one cell moves every line below it."
    nb = repo_git/'work.ipynb'
    nb.write_text(_ipynb([('a', 'first = 1'), ('b', 'second = 2'), ('c', 'third = 3')]))
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'notebook')
    r = GitRepo(repo_git)
    assert r.notebook_changes('work.ipynb') == {'path': 'work.ipynb', 'changed': False,
                                                'cells': {}, 'lines': {}}
    nb.write_text(_ipynb([('a', 'first = 1'), ('b', 'second = 22'), ('c', 'third = 3'),
                          ('d', 'fourth = 4')]))
    out = r.notebook_changes('work.ipynb')
    assert out['changed'] is True
    assert out['cells'] == {'b': 'modified', 'd': 'added'}, 'the untouched cells stay unmarked'

def test_an_untracked_notebook_is_added_cell_by_cell(repo_git):
    (repo_git/'fresh.ipynb').write_text(_ipynb([('a', 'x = 1'), ('b', 'y = 2')]))
    assert GitRepo(repo_git).notebook_changes('fresh.ipynb')['cells'] == {'a': 'added', 'b': 'added'}

def test_notebook_changes_declines_anything_that_is_not_a_notebook(repo_git):
    (repo_git/'src'/'app.py').write_text('value = 2\n')
    out = GitRepo(repo_git).notebook_changes('src/app.py')
    assert out['changed'] is False and out['cells'] == {}, 'a .py file is answered by file_changes'

def test_a_modified_cell_says_which_of_its_own_lines_moved(repo_git):
    "Line numbers inside one cell's editor, which is the only place they are ever drawn."
    nb = repo_git/'work.ipynb'
    nb.write_text(_ipynb([('a', 'one\ntwo\nthree'), ('b', 'kept')]))
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'notebook')
    nb.write_text(_ipynb([('a', 'one\nTWO\nthree\nfour'), ('b', 'kept')]))
    out = GitRepo(repo_git).notebook_changes('work.ipynb')
    assert out['cells'] == {'a': 'modified'}
    assert out['lines']['a'] == [{'from': 2, 'to': 2, 'kind': 'modified'},
                                 {'from': 4, 'to': 4, 'kind': 'added'}]
    assert 'b' not in out['lines'], 'an untouched cell has nothing to draw'

def test_a_deleted_line_is_reported_where_the_text_closed_over_it(repo_git):
    "It has no line of its own in the new source, which is what git's `+n,0` hunk also means."
    nb = repo_git/'work.ipynb'
    nb.write_text(_ipynb([('a', 'one\ntwo\nthree')]))
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'notebook')
    nb.write_text(_ipynb([('a', 'one\nthree')]))
    ranges = GitRepo(repo_git).notebook_changes('work.ipynb')['lines']['a']
    assert ranges == [{'from': 2, 'to': 2, 'kind': 'deleted'}]

def test_every_line_of_a_new_cell_is_added(repo_git):
    nb = repo_git/'work.ipynb'
    nb.write_text(_ipynb([('a', 'kept')]))
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'notebook')
    nb.write_text(_ipynb([('a', 'kept'), ('b', 'x = 1\ny = 2')]))
    out = GitRepo(repo_git).notebook_changes('work.ipynb')
    assert out['cells']['b'] == 'added'
    assert out['lines']['b'] == [{'from': 1, 'to': 2, 'kind': 'added'}]

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
    ws.activate_root(b)
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

def test_info_reports_the_head_a_watcher_needs_to_see_a_commit(repo_git):
    "Commit everything and the branch, the counts and the file list all read the same after."
    r = GitRepo.at(repo_git)
    before = r.info()
    (repo_git/'src'/'app.py').write_text('value = 2\n')
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'second')
    time.sleep(0.5)
    after = GitRepo.at(repo_git).info()
    assert before['branch'] == after['branch'] and before['clean'] == after['clean']
    assert len(before['changes']) == len(after['changes']) == 0
    assert before['head'] and after['head'] and before['head'] != after['head'], \
        'without this a commit is invisible to anything watching the snapshot'

def test_an_untracked_file_does_not_block_a_merge(repo_git):
    "The reported bug: click merge, nothing happens."
    git(repo_git, 'checkout', '-b', 'feature')
    (repo_git/'src'/'lib.py').write_text('added = True\n')
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'feature work')
    git(repo_git, 'checkout', 'main')
    (repo_git/'uv.lock').write_text('never committed\n')
    p = GitRepo.at(repo_git).merge_preview('feature')
    assert p['clean'] is True, 'an untracked file is not uncommitted work'
    assert p['untracked'] == 1 and p['dirty'] == []
    assert p['relation'] == 'fast-forward'

def test_uncommitted_work_on_a_tracked_file_still_blocks_and_names_the_files(repo_git):
    git(repo_git, 'checkout', '-b', 'feature')
    (repo_git/'src'/'lib.py').write_text('added = True\n')
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'feature work')
    git(repo_git, 'checkout', 'main')
    (repo_git/'src'/'app.py').write_text('value = 99\n')
    for p in (GitRepo.at(repo_git).merge_preview('feature'), GitRepo.at(repo_git).rebase_preview('feature')):
        assert p['clean'] is False
        assert p['dirty'] == ['src/app.py'], 'and the dialog can say which'

def test_choosing_a_folder_moves_releases_deploys_and_drive_too(tmp_path):
    "The reported bug, one layer down: source control followed the choice, releases did not."
    from starlette.testclient import TestClient
    from leela.app import ide_app
    a, b = _repo(tmp_path/'ramabana', 'main'), _repo(tmp_path/'rishi', 'dev')
    ws = Workspace(roots=[a, b])
    ws.open(a/'readme.md')
    with TestClient(ide_app(ws)) as client:
        for url in ('/releases', '/deploys', '/drive'):
            assert client.get(url).json()['root'] == str(a), f'precondition for {url}'
        assert client.post('/workspace/activate', json={'path': str(b)}).json()['ok'] is True
        assert client.get('/git/info').json()['branch'] == 'dev', 'source control already did this'
        for url in ('/releases', '/deploys', '/drive'):
            assert client.get(url).json()['root'] == str(b), f'{url} stayed on the first repo'

def test_a_project_panel_still_follows_the_tab_when_no_folder_was_chosen(tmp_path):
    "Opening a file is the other way of saying which project you mean, so it must still count."
    from starlette.testclient import TestClient
    from leela.app import ide_app
    a, b = _repo(tmp_path/'ramabana', 'main'), _repo(tmp_path/'rishi', 'dev')
    ws = Workspace(roots=[a, b])
    ws.open(b/'readme.md')
    with TestClient(ide_app(ws)) as client:
        assert client.get('/releases').json()['root'] == str(b)
        assert client.get('/git/info').json()['branch'] == 'dev', 'and the two agree'

def test_a_named_repository_still_wins_over_the_chosen_one(tmp_path):
    "The panels can be pointed at any listed checkout explicitly; that must outrank the choice."
    from starlette.testclient import TestClient
    from leela.app import ide_app
    a, b = _repo(tmp_path/'ramabana', 'main'), _repo(tmp_path/'rishi', 'dev')
    ws = Workspace(roots=[a, b]); ws.activate_root(b)
    with TestClient(ide_app(ws)) as client:
        assert client.get('/releases', params={'repo': str(a)}).json()['root'] == str(a)
        assert client.get('/releases').json()['root'] == str(b), 'and it did not become sticky'

def test_choosing_a_folder_moves_the_agent_and_the_kernel_fallback_too(tmp_path):
    "Two more project surfaces that were answering about the first folder."
    a, b = _repo(tmp_path/'ramabana', 'main'), _repo(tmp_path/'rishi', 'dev')
    ws = Workspace(roots=[a, b])
    assert ws.kernel_key() == str(a), 'precondition: the first folder'
    rebriefed = []
    ws._rebrief_agents = lambda: rebriefed.append(True)
    ws.activate_root(b)
    assert ws.kernel_key() == str(b), 'the exec box and variables follow the chosen project'
    assert rebriefed, 'and a live assistant is told the project changed'
    from leela.blocks.agent.ai import WorkspaceHost
    assert WorkspaceHost(ws).project == str(b), 'as does where its commands run'

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

def test_clone_target_refuses_anything_but_a_free_folder_in_a_real_directory(tmp_path):
    from leela.blocks.git.git import clone_target
    assert clone_target('https://example.com/x/leela.git', tmp_path) == tmp_path/'leela'
    with pytest.raises(GitError, match='not a repository URL'):
        clone_target('--upload-pack=whatever', tmp_path)
    with pytest.raises(GitError, match='not a directory'):
        clone_target('https://example.com/x/leela.git', tmp_path/'imaginary')
    (tmp_path/'leela').mkdir()
    with pytest.raises(GitError, match='already exists'):
        clone_target('https://example.com/x/leela.git', tmp_path)

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
        assert client.post('/fs/add-root', json={'path': str(landed)}).json()['ok']
        assert client.post('/workspace/activate', json={'path': str(landed)}).json()['ok']
        assert client.get('/git/info').json()['root'] == str(landed)
        assert 'already exists' in client.post('/git/clone',
            json={'url': str(remote), 'parent': str(into)}).json()['error']
        assert 'not a directory' in client.post('/git/clone',
            json={'url': str(remote), 'parent': str(_outside(tmp_path, 'imaginary'))}).json()['error']

def test_switching_branches_from_the_top_bar_says_what_became_of_dirty_work(repo_git):
    "The popup's rows post `checkout`, and `checkout` may have to set the tree aside."
    from starlette.testclient import TestClient
    from leela.app import ide_app
    path = repo_git/'src'/'app.py'
    path.write_text('top\n' + 'body\n' * 20 + 'bottom\n')
    git(repo_git, 'commit', '-am', 'room to edit either end')
    git(repo_git, 'checkout', '-b', 'feature/one')
    path.write_text(path.read_text().replace('top\n', 'TOP\n', 1))
    git(repo_git, 'commit', '-am', 'the other branch owns the first line')
    git(repo_git, 'checkout', 'main')
    path.write_text(path.read_text().replace('bottom\n', 'MINE\n', 1))
    with TestClient(ide_app(Workspace(roots=[repo_git]))) as client:
        d = client.post('/git/action', json={'op': 'checkout', 'branch': 'feature/one'}).json()
    assert d['branch'] == 'feature/one'
    assert 'carried' in d['outcome']['message'], 'the sentence the browser has to show'
    assert not d['outcome']['note'], 'nothing had to be left behind'
    assert path.read_text().startswith('TOP\n') and 'MINE\n' in path.read_text()
    git(repo_git, 'checkout', '-f', 'main')
    path.write_text(path.read_text().replace('top\n', 'mine\n', 1))
    with TestClient(ide_app(Workspace(roots=[repo_git]))) as client:
        d = client.post('/git/action', json={'op': 'checkout', 'branch': 'feature/one'}).json()
    assert 'error' in d and 'still on main' in d['error']
    assert path.read_text().startswith('mine\n'), 'the work is exactly where it was'
    assert GitRepo.at(repo_git).info()['branch'] == 'main'

def test_a_remote_only_branch_is_checked_out_by_its_leaf_name(repo_git, tmp_path):
    "What the popup sends for an `origin/…` row: the name without the remote, so Git tracks it."
    _bare_remote(repo_git, tmp_path, 'leaf-remote.git')
    git(repo_git, 'branch', 'cursor/work')
    git(repo_git, 'push', 'origin', 'cursor/work')
    git(repo_git, 'branch', '-D', 'cursor/work')
    r = GitRepo.at(repo_git)
    r.fetch()
    assert 'origin/cursor/work' in {b['name'] for b in r.info()['branches']}
    r.checkout('cursor/work')
    info = r.info()
    assert info['branch'] == 'cursor/work' and info['upstream'] == 'origin/cursor/work'

def test_every_branch_row_carries_its_own_ahead_and_behind(repo_git, tmp_path):
    "The popup shows `↙2 ↗1` per branch, so the counts cannot come from the current one alone."
    _bare_remote(repo_git, tmp_path, 'drift-remote.git')
    (repo_git/'src'/'app.py').write_text('value = 2\n')
    git(repo_git, 'commit', '-am', 'ahead by one')
    git(repo_git, 'checkout', '-b', 'side')
    (repo_git/'notes.txt').write_text('side\n')
    git(repo_git, 'add', '.'); git(repo_git, 'commit', '-m', 'side work')
    rows = {b['name']: b for b in GitRepo.at(repo_git).info()['branches']}
    assert rows['main']['upstream'] == 'origin/main'
    assert (rows['main']['ahead'], rows['main']['behind']) == (1, 0)
    assert (rows['side']['ahead'], rows['side']['behind']) == (0, 0), 'no upstream, no drift'
    assert not rows['side']['gone'] and not rows['main']['gone']

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

@pytest.fixture
def repo_git_sa(tmp_path):
    git(tmp_path, 'init', '-b', 'main')
    git(tmp_path, 'config', 'user.email', 'tests@leela.local')
    git(tmp_path, 'config', 'user.name', 'Leela tests')
    (tmp_path/'app.py').write_text('value = 1\n')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-m', 'initial')
    return tmp_path

@pytest.mark.parametrize('args,kind', [
    (('status', '--porcelain=v1'), 'read'),
    (('diff', '--cached'), 'read'),
    (('rev-parse', 'HEAD'), 'read'),
    (('for-each-ref', '--format=%(refname)'), 'read'),
    (('merge-tree', '--write-tree', 'a', 'b'), 'read'),
    (('branch', '--show-current'), 'read'),
    (('branch',), 'read'),
    (('tag', '-l'), 'read'),
    (('remote',), 'read'),
    (('remote', 'get-url', 'origin'), 'read'),
    (('stash', 'list'), 'read'),
    (('worktree', 'list'), 'read'),
    (('config', '--get', 'filter.x.clean'), 'read'),
    (('symbolic-ref', '--quiet', '--short', 'refs/remotes/origin/HEAD'), 'read'),
    (('branch', '-d', 'gone'), 'write'),
    (('tag', 'v1'), 'write'),
    (('stash',), 'write'),
    (('stash', 'pop'), 'write'),
    (('remote', 'add', 'origin', 'url'), 'write'),
    (('worktree', 'add', 'path'), 'write'),
    (('symbolic-ref', 'HEAD', 'refs/heads/main'), 'write'),
    (('merge', '--no-edit', 'feature'), 'write'),
    (('commit', '-m', 'x'), 'write'),
    (('reset', '--hard', 'HEAD'), 'write'),
    (('pull', '--ff-only'), 'write'),
    (('add', '--', 'app.py'), 'write'),
    (('checkout', '--ours', '--', 'app.py'), 'write'),
    (('fetch', '--all', '--prune'), 'net'),
    (('push', '--set-upstream', 'origin', 'main'), 'net'),
    (('clone', '--', 'url', 'name'), 'net'),
    (('-c', 'core.hooksPath=/dev/null', 'status'), 'read'),
    (('--git-dir', '/tmp/x', 'commit', '-m', 'x'), 'write'),
    (('bisect', 'start'), 'write'),
    ((), 'write'),
])
def test_commands_are_sorted_by_what_they_do_to_the_repository(args, kind):
    assert classify(args) == kind

def test_reads_do_not_take_the_index_lock_and_writes_are_not_given_the_flag(repo_git_sa, monkeypatch):
    seen = []
    real = subprocess.run
    def spy(argv, *a, **kw):
        seen.append(list(argv))
        return real(argv, *a, **kw)
    monkeypatch.setattr('ramabana.git.subprocess.run', spy)
    g = GitGateway()
    g.run(repo_git_sa, 'status', '--porcelain=v1')
    g.run(repo_git_sa, 'add', '--', 'app.py')
    reads = [c for c in seen if 'status' in c]
    writes = [c for c in seen if 'add' in c]
    assert reads and all('--no-optional-locks' in c for c in reads)
    assert writes and not any('--no-optional-locks' in c for c in writes)

def test_a_write_excludes_every_other_command_in_the_same_repository(repo_git_sa):
    "A merge and a status poll in the same checkout must not overlap."
    g = GitGateway()
    live, peak, lock = 0, 0, threading.Lock()
    write_saw = []
    def fake_exec(cwd, args, check, input, timeout, kind):
        nonlocal live, peak
        with lock:
            live += 1
            peak = max(peak, live)
            here = live
        if kind == 'write':
            write_saw.append(here)
        time.sleep(.05)
        with lock:
            live -= 1
        return subprocess.CompletedProcess(args, 0, '', '')
    g._exec = fake_exec
    threads = [threading.Thread(target=g.run, args=(repo_git_sa, 'status')) for _ in range(4)]
    threads.append(threading.Thread(target=g.run, args=(repo_git_sa, 'commit', '-m', 'x')))
    threads += [threading.Thread(target=g.run, args=(repo_git_sa, 'status')) for _ in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert write_saw == [1], 'a write ran while something else was in the repository'
    assert peak > 1, 'reads should still share, or the panel crawls'

def test_a_slow_fetch_does_not_stop_the_panel_from_reading(repo_git_sa):
    g = GitGateway()
    overlapped = threading.Event()
    started = threading.Event()
    def fake_exec(cwd, args, check, input, timeout, kind):
        if kind == 'net':
            started.set()
            time.sleep(.3)
        else:
            if started.wait(1) and not overlapped.is_set():
                overlapped.set()
        return subprocess.CompletedProcess(args, 0, '', '')
    g._exec = fake_exec
    net = threading.Thread(target=g.run, args=(repo_git_sa, 'fetch', '--all'))
    net.start()
    started.wait(1)
    g.run(repo_git_sa, 'status')
    net.join()
    assert overlapped.is_set(), 'a status read waited for the fetch to finish'

def test_a_transaction_holds_the_lock_and_can_still_ask_questions(repo_git_sa):
    "Reentrancy: the safepoint and the mutation are both Git calls inside the write lock."
    g = GitGateway()
    with g.transaction(repo_git_sa, 'merge') as point:
        assert point is not None and point.head
        assert g.out(repo_git_sa, 'branch', '--show-current').strip() == 'main'
        g.run(repo_git_sa, 'commit', '--allow-empty', '-m', 'inside')
    assert g.out(repo_git_sa, 'log', '-1', '--format=%s').strip() == 'inside'

def test_a_foreign_lock_is_retried_and_then_explained(repo_git_sa, monkeypatch):
    "Another Git in the same checkout is a wait, then a sentence -- not a stack trace."
    (repo_git_sa/'.git'/'index.lock').write_text('')
    g = GitGateway()
    monkeypatch.setattr('ramabana.git.LOCK_BACKOFF', .001)
    attempts = []
    real = subprocess.run
    def spy(argv, *a, **kw):
        attempts.append(argv)
        return real(argv, *a, **kw)
    monkeypatch.setattr('ramabana.git.subprocess.run', spy)
    (repo_git_sa/'app.py').write_text('value = 2\n')
    with pytest.raises(GitError) as e:
        g.run(repo_git_sa, 'add', '--', 'app.py')
    assert len(attempts) > 1, 'a foreign lock should be waited on, not failed at once'
    assert 'Another Git process' in str(e.value) and 'Nothing was changed' in str(e.value)

def test_a_refusal_reports_both_streams(repo_git_sa):
    "Git diagnoses on stderr and lists on stdout; a refusal is worth nothing without the list."
    git(repo_git_sa, 'checkout', '-b', 'other')
    (repo_git_sa/'app.py').write_text('value = 2\n')
    git(repo_git_sa, 'commit', '-am', 'theirs')
    git(repo_git_sa, 'checkout', 'main')
    (repo_git_sa/'app.py').write_text('value = 3\n')
    git(repo_git_sa, 'commit', '-am', 'ours')
    with pytest.raises(GitError) as e:
        GitGateway().run(repo_git_sa, 'merge', 'other')
    assert 'Automatic merge failed' in str(e.value), 'the diagnosis, from stderr'
    assert 'CONFLICT' in str(e.value) and 'app.py' in str(e.value), 'the files, from stdout'

def test_a_safepoint_keeps_uncommitted_work_and_undo_puts_it_back(repo_git_sa):
    r = GitRepo.at(repo_git_sa)
    (repo_git_sa/'app.py').write_text('value = 99\n')
    (repo_git_sa/'extra.txt').write_text('untracked\n')
    before = git(repo_git_sa, 'rev-parse', 'HEAD')
    g = gateway()
    with g.transaction(repo_git_sa, 'merge') as point:
        assert point.stash and point.dirty >= 1
        g.run(repo_git_sa, 'commit', '-am', 'not what I wanted')
        g.run(repo_git_sa, 'commit', '--allow-empty', '-m', 'nor this')
    assert git(repo_git_sa, 'rev-parse', 'HEAD') != before
    outcome = g.undo(repo_git_sa)
    assert git(repo_git_sa, 'rev-parse', 'HEAD') == before
    assert (repo_git_sa/'app.py').read_text() == 'value = 99\n', 'the uncommitted edit came back'
    assert (repo_git_sa/'extra.txt').exists(), 'untracked files were never at risk'
    assert outcome['branch'] == 'main' and outcome['op'] == 'merge'

def test_undo_aborts_an_operation_it_finds_in_progress(repo_git_sa):
    "A reset during a rebase leaves the rebase running, so undo aborts first."
    g = gateway()
    git(repo_git_sa, 'checkout', '-b', 'feature')
    (repo_git_sa/'app.py').write_text('feature\n')
    git(repo_git_sa, 'commit', '-am', 'feature edit')
    git(repo_git_sa, 'checkout', 'main')
    (repo_git_sa/'app.py').write_text('main\n')
    git(repo_git_sa, 'commit', '-am', 'main edit')
    before = git(repo_git_sa, 'rev-parse', 'HEAD')
    with g.transaction(repo_git_sa, 'merge'):
        g.run(repo_git_sa, 'merge', '--no-edit', 'feature', check=False)
    assert g.active_operation(repo_git_sa) == 'merge', 'the fixture needs a real conflict'
    g.undo(repo_git_sa)
    assert not g.active_operation(repo_git_sa)
    assert git(repo_git_sa, 'rev-parse', 'HEAD') == before

def test_a_safepoint_survives_aggressive_garbage_collection(repo_git_sa):
    "The snapshot commit is pinned, or `gc` collects the undo button."
    g = gateway()
    (repo_git_sa/'app.py').write_text('value = 7\n')
    with g.transaction(repo_git_sa, 'reset') as point:
        g.run(repo_git_sa, 'reset', '--hard', 'HEAD')
    assert point.stash
    git(repo_git_sa, 'gc', '--prune=now', '--aggressive')
    g.undo(repo_git_sa)
    assert (repo_git_sa/'app.py').read_text() == 'value = 7\n'

def test_undo_says_so_when_there_is_nothing_to_undo(repo_git_sa):
    with pytest.raises(GitError, match='nothing to undo'):
        GitGateway().undo(repo_git_sa)

def test_a_filter_that_cannot_run_is_named_instead_of_dirtying_notebooks_for_ever(repo_git_sa):
    "The nbdev shape: a clean filter configured, and its command not installed here."
    (repo_git_sa/'.gitattributes').write_text('*.ipynb filter=nbdev_clean\n')
    git(repo_git_sa, 'config', 'filter.nbdev_clean.clean', 'nbdev_clean_stdin --nowhere')
    r = GitRepo.at(repo_git_sa)
    health = r.filter_health()
    assert health['ok'] is False
    assert [f['name'] for f in health['filters']] == ['nbdev_clean']
    assert health['filters'][0]['resolved'] == ''
    assert 'nbdev_clean' in health['explain'] and 'keep reappearing as modified' in health['explain']
    assert r.info()['filters']['ok'] is False, 'and the panel is told without asking separately'

def test_a_filter_that_resolves_is_reported_as_working(repo_git_sa):
    (repo_git_sa/'.gitattributes').write_text('*.ipynb filter=plain\n')
    git(repo_git_sa, 'config', 'filter.plain.clean', 'cat')
    health = GitRepo.at(repo_git_sa).filter_health()
    assert health['ok'] is True and health['explain'] == ''
    assert health['filters'][0]['resolved'].endswith('cat')

def test_a_filter_named_but_configured_nowhere_says_that_instead(repo_git_sa):
    "A different problem with the same symptom, so it gets its own sentence."
    (repo_git_sa/'.gitattributes').write_text('*.ipynb filter=ghost\n')
    health = GitRepo.at(repo_git_sa).filter_health()
    assert health['ok'] is False
    assert health['filters'][0]['configured'] is False
    assert 'configured nowhere' in health['explain']

def test_a_repository_with_no_filters_is_quiet_about_them(repo_git_sa):
    health = GitRepo.at(repo_git_sa).filter_health()
    assert health == {'filters': [], 'ok': True, 'explain': ''}

@pytest.fixture
def diverged(repo_git_sa):
    "`main` and `feature` with one commit each, touching different files."
    git(repo_git_sa, 'checkout', '-b', 'feature')
    (repo_git_sa/'lib.py').write_text('shared = True\n')
    git(repo_git_sa, 'add', '.'); git(repo_git_sa, 'commit', '-m', 'feature work')
    git(repo_git_sa, 'checkout', 'main')
    (repo_git_sa/'other.py').write_text('other = True\n')
    git(repo_git_sa, 'add', '.'); git(repo_git_sa, 'commit', '-m', 'main work')
    return repo_git_sa

def test_a_dirty_tree_no_longer_refuses_a_merge_and_the_work_comes_back(diverged):
    "The complaint: leela refuses where PyCharm shelves, does it, and restores."
    r = GitRepo.at(diverged)
    (diverged/'app.py').write_text('value = 42\n')
    out = r.merge('feature')
    assert (diverged/'lib.py').exists(), 'the merge happened'
    assert (diverged/'app.py').read_text() == 'value = 42\n', 'the uncommitted edit came back'
    assert out['kept_work'] is True
    assert not out['conflicted']
    assert git(diverged, 'stash', 'list') == ''

def test_a_squash_merge_says_that_it_staged_rather_than_committed(diverged):
    "`merge --squash` leaves the index full on purpose; not saying so reads as a bug in leela."
    out = GitRepo.at(diverged).merge('feature', 'squash')
    assert out['staged'] == ['lib.py']
    assert not out['moved']
    assert out['summary'] == 'merge staged 1 file without committing -- commit to finish'

def test_a_merge_reports_its_conflicts_and_can_be_undone_whole(repo_git_sa):
    r = GitRepo.at(repo_git_sa)
    r.create('other')
    (repo_git_sa/'app.py').write_text('other = True\n')
    r.stage(['app.py']); r.commit('other side')
    r.checkout('main')
    (repo_git_sa/'app.py').write_text('main = True\n')
    r.stage(['app.py']); r.commit('main side')
    before = git(repo_git_sa, 'rev-parse', 'HEAD')
    out = r.merge('other')
    assert out['conflicted'] == ['app.py']
    assert out['operation']['active'] == 'merge'
    assert out['summary'] == 'merge stopped at 1 conflicted file -- resolve them to continue'
    assert out['undo'], 'a merge that stopped is exactly when undo has to be there'
    back = r.undo(out['undo'])
    assert git(repo_git_sa, 'rev-parse', 'HEAD') == before
    assert not r.info()['operation']['active'], 'the half-finished merge was called off too'
    assert (repo_git_sa/'app.py').read_text() == 'main = True\n'
    assert back['op'] == 'merge'

def test_a_switch_that_cannot_carry_the_work_changes_nothing_at_all(repo_git_sa):
    "Git refuses when the switch would lose an edit. Half of a shelve is worse than neither."
    r = GitRepo.at(repo_git_sa)
    git(repo_git_sa, 'checkout', '-b', 'feature')
    (repo_git_sa/'app.py').write_text('feature = True\n')
    git(repo_git_sa, 'commit', '-am', 'feature edit')
    git(repo_git_sa, 'checkout', 'main')
    (repo_git_sa/'app.py').write_text('uncommitted work\n')
    with pytest.raises(GitError) as e:
        r.checkout('feature')
    assert 'Nothing was changed' in str(e.value) and 'still on main' in str(e.value)
    assert git(repo_git_sa, 'rev-parse', '--abbrev-ref', 'HEAD') == 'main'
    assert (repo_git_sa/'app.py').read_text() == 'uncommitted work\n', 'the work is where it was'
    assert '<<<<<<<' not in (repo_git_sa/'app.py').read_text(), 'and it is not half-merged'

def test_a_switch_carries_uncommitted_work_when_it_can(repo_git_sa):
    "The ordinary case: Git itself moves compatible edits, and nothing is set aside."
    r = GitRepo.at(repo_git_sa)
    git(repo_git_sa, 'checkout', '-b', 'feature')
    (repo_git_sa/'lib.py').write_text('only_on_feature = True\n')
    git(repo_git_sa, 'add', '.'); git(repo_git_sa, 'commit', '-m', 'feature file')
    git(repo_git_sa, 'checkout', 'main')
    (repo_git_sa/'app.py').write_text('uncommitted work\n')
    out = r.checkout('feature')
    assert out['branch'] == 'feature'
    assert (repo_git_sa/'app.py').read_text() == 'uncommitted work\n'
    assert not out['kept_work'], 'Git carried it; Leela did not have to'

def test_every_mutation_reports_where_the_repository_now_is(repo_git_sa):
    r = GitRepo.at(repo_git_sa)
    (repo_git_sa/'app.py').write_text('value = 2\n')
    r.stage(['app.py'])
    out = r.commit('a change')
    assert set(out) >= {'op', 'head', 'head_before', 'moved', 'branch', 'staged', 'conflicted',
                        'operation', 'summary', 'undo', 'undoes'}
    assert out['moved'] and out['head'] != out['head_before']
    assert out['branch'] == 'main' and not out['staged']
    assert out['summary'] == f'commit moved this branch to {out["head"]}'
    assert 'commit on main' in out['undoes']

def test_the_journal_lists_the_ways_back_newest_first(repo_git_sa):
    r = GitRepo.at(repo_git_sa)
    (repo_git_sa/'app.py').write_text('one\n')
    r.stage(['app.py']); r.commit('first')
    (repo_git_sa/'app.py').write_text('two\n')
    r.stage(['app.py']); r.commit('second')
    points = r.safepoints()
    assert [p['op'] for p in points][:2] == ['commit', 'commit']
    assert points[0]['created_at'] >= points[1]['created_at']
    assert all(p['token'] for p in points)

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
    assert names == ['alpha', 'beta', 'gamma']

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
    assert names == ['alpha', 'beta', 'gamma', 'delta']

def test_membership_is_added_and_removed_without_touching_the_checkout(workspace, tmp_path):
    outside = make_repo(tmp_path/'outside'/'epsilon')
    repos = repo_set(workspace, tmp_path)
    repos.add(outside/'seed.py')
    assert [p.name for p in repos.paths()][-1] == 'epsilon'
    repos.remove(outside)
    assert 'epsilon' not in [p.name for p in repos.paths()]
    assert outside.exists()
    repos.remove(workspace/'beta')
    assert [p.name for p in repos.paths()] == ['alpha', 'gamma']
    repos.add(workspace/'beta')
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
    assert over['expected_branch'] == 'main'
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
    assert rows['beta']['unreleased'] is None

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
    other = make_repo(tmp_path/'other')
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

def test_a_diverged_branch_is_offered_every_way_back_with_its_conflicts_rehearsed(repo_git, tmp_path):
    "`pull` is --ff-only. Divergence needs a plan, each way out rehearsed before it runs."
    remote = tmp_path/'remote.git'
    git(tmp_path, 'init', '--bare', remote.name)
    git(repo_git, 'remote', 'add', 'origin', str(remote))
    git(repo_git, 'push', '-u', 'origin', 'main')
    git(repo_git, 'switch', '-c', 'upstream-work')
    (repo_git/'src'/'app.py').write_text('value = 1\nupstream = 1\n')
    git(repo_git, 'commit', '-am', 'upstream moved')
    git(repo_git, 'push', 'origin', 'upstream-work:main')
    git(repo_git, 'switch', 'main')
    git(repo_git, 'branch', '-D', 'upstream-work')
    r = GitRepo.at(repo_git)
    r.fetch()
    (repo_git/'src'/'app.py').write_text('first = 1\nvalue = 1\n')
    git(repo_git, 'commit', '-am', 'ours one')
    (repo_git/'src'/'app.py').write_text('first = 1\nclash = 1\n')
    git(repo_git, 'commit', '-am', 'ours two')
    plan = r.divergence()
    assert (plan['relation'], plan['ahead'], plan['behind']) == ('diverged', 2, 1)
    ops = {o['op']: o for o in plan['options']}
    assert not ops['fast-forward']['available'], 'our own commits are in the way'
    assert ops['merge']['available'] and ops['rebase']['available'] and ops['reset']['destructive']
    stops = ops['rebase']['stops_at']
    assert stops and stops['subject'] in ('ours one', 'ours two')
    assert ops['rebase']['replayed'] < 2, 'a replay that stops has not replayed everything'
    assert 'src/app.py' in ops['rebase']['conflicts']
    assert plan['recommended'] == 'merge', 'resolving once beats resolving per replayed commit'
    out = r.sync('merge')
    assert out['conflicted'] == ['src/app.py'] and r.divergence()['relation'] == 'diverged'
    git(repo_git, 'merge', '--abort')
    assert r.sync('reset')['head'] == r._ask('rev-parse', '--short', 'origin/main')

def test_a_clean_divergence_prefers_rebase_and_a_branch_only_behind_fast_forwards(repo_git, tmp_path):
    remote = tmp_path/'remote.git'
    git(tmp_path, 'init', '--bare', remote.name)
    git(repo_git, 'remote', 'add', 'origin', str(remote))
    git(repo_git, 'push', '-u', 'origin', 'main')
    git(repo_git, 'switch', '-c', 'upstream-work')
    (repo_git/'theirs.py').write_text('theirs = 1\n')
    git(repo_git, 'add', 'theirs.py'); git(repo_git, 'commit', '-m', 'theirs')
    git(repo_git, 'push', 'origin', 'upstream-work:main')
    git(repo_git, 'switch', 'main')
    git(repo_git, 'branch', '-D', 'upstream-work')
    r = GitRepo.at(repo_git)
    r.fetch()
    assert r.divergence()['recommended'] == 'fast-forward', 'behind only: nothing to reconcile'
    (repo_git/'ours.py').write_text('ours = 1\n')
    git(repo_git, 'add', 'ours.py'); git(repo_git, 'commit', '-m', 'ours')
    plan = r.divergence()
    assert plan['recommended'] == 'rebase' and not plan['options'][2]['stops_at']
    r.sync('rebase')
    assert r.divergence()['relation'] == 'ahead'

def test_the_agent_can_rehearse_a_divergence_without_being_able_to_run_it(repo_git, tmp_path):
    "Read-only git tools answer with JSON. The mutations stay behind the approvals gate."
    from leela.blocks.agent.ai import GIT_READ_TOOLS
    remote = tmp_path/'agent-diverge.git'
    git(tmp_path, 'init', '--bare', remote.name)
    git(repo_git, 'remote', 'add', 'origin', str(remote))
    git(repo_git, 'push', '-u', 'origin', 'main')
    git(repo_git, 'switch', '-c', 'theirs')
    (repo_git/'src'/'app.py').write_text('value = 1\ntheirs = 1\n')
    git(repo_git, 'commit', '-am', 'theirs')
    git(repo_git, 'push', 'origin', 'theirs:main')
    git(repo_git, 'switch', 'main')
    git(repo_git, 'branch', '-D', 'theirs')
    (repo_git/'src'/'app.py').write_text('value = 2\n')
    git(repo_git, 'commit', '-am', 'ours')
    class Host:
        roots = [str(repo_git)]
        def check(self, path, must_exist=False):
            p = __import__('pathlib').Path(path).resolve()
            if not p.is_relative_to(repo_git): raise ValueError('outside workspace')
            return p
    tools = {f.__name__: f for f in _git_tools(Host())}
    GitRepo.at(repo_git).fetch()
    plan = json.loads(tools['git_divergence']())
    assert plan['relation'] == 'diverged' and plan['ahead'] == 1 and plan['behind'] == 1
    assert {o['op'] for o in plan['options']} == {'fast-forward', 'merge', 'rebase', 'reset'}
    assert plan['ours'] and isinstance(plan['ours'][0], str), 'commits arrive short, not whole'
    preview = json.loads(tools['git_rebase_preview']('origin/main'))
    assert 'review' not in preview and preview['conflict_likely'] is True
    assert preview['stops_at']['subject'] == 'ours'
    assert set(GIT_READ_TOOLS) & set(tools) == set(GIT_READ_TOOLS)


def test_a_folder_without_a_repository_is_an_answer_not_an_error(tmp_path):
    """Every boot in a non-repo folder logged a console error, because "there is no repository
    here" came back as HTTP 400 -- which also made a real 400 from this route indistinguishable.
    """
    from starlette.testclient import TestClient
    from leela.app import ide_app
    plain = tmp_path/'notes'; plain.mkdir(); (plain/'a.md').write_text('# a\n')
    with TestClient(ide_app(Workspace(roots=[plain]))) as client:
        r = client.get('/git/info')
        assert r.status_code == 200, 'a folder with no git in it is not a client error'
        assert r.json()['repo'] is False and 'not inside a Git repository' in r.json()['note']

def test_a_folder_with_a_repository_says_so_beside_the_branch(tmp_path):
    "The flag has to be positive too, or every real checkout reads as repo-less."
    from starlette.testclient import TestClient
    from leela.app import ide_app
    with TestClient(ide_app(Workspace(roots=[_repo(tmp_path/'r', 'main')]))) as client:
        d = client.get('/git/info').json()
        assert d['repo'] is True and d['branch'] == 'main'

def test_a_real_git_failure_is_still_a_400(tmp_path):
    "Only absence is an answer; a broken call stays an error the client can report."
    from starlette.testclient import TestClient
    from leela.app import ide_app
    with TestClient(ide_app(Workspace(roots=[_repo(tmp_path/'r', 'main')]))) as client:
        assert client.get('/git/info', params={'repo': '/nowhere/at/all'}).status_code == 400


def test_the_sync_dialog_survives_the_options_that_carry_no_conflicts(tmp_path):
    """`divergence` puts `conflicts` on `merge` and `rebase` only, and no option carries a
    `label`. Reading either unguarded killed the dialog on the first option, every time.
    """
    import sys
    from pathlib import Path as _P
    sys.path.insert(0, str(_P(__file__).resolve().parents[1]/'tools'))
    from ramabana.git import GitRepo
    a = _repo(tmp_path/'up', 'main')
    git(a, 'clone', str(a), str(tmp_path/'down'))
    down = tmp_path/'down'
    (down/'mine.txt').write_text('mine\n'); git(down, 'add', '.'); git(down, 'commit', '-m', 'mine')
    (a/'theirs.txt').write_text('theirs\n'); git(a, 'add', '.'); git(a, 'commit', '-m', 'theirs')
    git(down, 'fetch', 'origin')
    plan = GitRepo.at(down).divergence()
    assert plan['relation'] == 'diverged'
    bare = [o['op'] for o in plan['options'] if 'conflicts' not in o]
    assert bare, 'precondition: some options carry no conflicts list'
    assert not [o for o in plan['options'] if 'label' in o], 'precondition: none carry a label'


def test_the_pull_request_panel_calls_github_the_way_ghapi_binds_it(monkeypatch, tmp_path):
    """`GhApi(owner=, repo=)` fills `/repos/{owner}/{repo}/...` itself, so passing them again
    positionally bound them to *query* parameters: `pulls.list` filtered on a base branch named
    after the owner and `compare_commits` dropped its fourth argument.
    """
    import sys, types
    from leela.blocks.git import hub
    seen = {}
    class Group:
        def __init__(self, name): self.name = name
        def __getattr__(self, op):
            def go(*a, **kw):
                seen[f'{self.name}.{op}'] = (a, kw)
                if op == 'list': return [{'number': 7, 'title': 'T', 'html_url': 'u', 'draft': False,
                                          'base': {'ref': 'main'}, 'head': {'sha': 'deadbeef'}}]
                if op == 'compare_commits': return {'behind_by': 2, 'ahead_by': 1}
                return {'check_runs': [{'name': 'ci', 'conclusion': 'success', 'status': 'completed'}]}
            return go
    api = types.SimpleNamespace(pulls=Group('pulls'), repos=Group('repos'), checks=Group('checks'))
    fake = types.ModuleType('gheasy.core')
    fake._gh_api = lambda token=None, path='.': ('vedicreader', 'leela', api)
    fake._get_repo_slug = lambda path='.': ('vedicreader', 'leela')
    fake._resolve_gh_token = lambda: 'tok'
    monkeypatch.setitem(sys.modules, 'gheasy.core', fake)
    monkeypatch.setattr(hub, 'hub_available', lambda: True)

    out = hub.pr_context.__wrapped__(str(tmp_path), 'my-branch')
    assert out['pr'], out.get('note')
    assert out['pr']['number'] == 7 and out['pr']['behind_base'] == 2

    assert seen['pulls.list'][0] == (), 'owner and repo are already bound to the client'
    assert seen['pulls.list'][1]['head'] == 'vedicreader:my-branch'
    assert seen['repos.compare_commits'][0] == ('main...my-branch',), 'one basehead, not four args'
    assert seen['checks.list_for_ref'][0] == ('deadbeef',)


def test_the_branch_search_box_does_not_grow_into_the_list():
    """`.lee-input` grows, which is what a search bar in a row wants. A modal box is a column, so
    the branch modal's search box grew *taller* and took every pixel the list could not use once
    its max-height was reached -- worst in a repo with few branches, where it filled the modal."""
    from tests.assets import CSS
    assert '.lee-input { flex: 1 1 auto; }' in CSS, 'the rule this guards against is still there'
    assert '.lee-modalbox > .lee-input { flex: none; }' in CSS
    assert '.lee-branchlist { max-height: min(58vh, 520px); }' in CSS, 'the cap that made it visible'

def test_the_pull_request_panel_gets_a_blocking_github_client(monkeypatch, tmp_path):
    """`GhApi` defaults to `sync=False`, and gheasy below 0.0.7 took that default: `pulls.list(...)`
    handed back a coroutine nobody awaited, `first` raised, and the panel reported `GitHub: ...`
    instead of the pull request. `gheasy>=0.0.7` is what holds the operations blocking."""
    from inspect import iscoroutinefunction
    from leela.blocks.git import hub
    g = pytest.importorskip('gheasy.core')
    monkeypatch.setattr(g, '_get_repo_slug', lambda path='.': ('vedicreader', 'leela'))
    monkeypatch.setattr(g, '_resolve_gh_token', lambda *a, **kw: 'tok')
    api, owner, name = hub._api(str(tmp_path))
    assert not iscoroutinefunction(type(api.pulls.list).__call__)
    assert (owner, name) == ('vedicreader', 'leela')
