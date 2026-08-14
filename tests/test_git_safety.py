"""The guarantees under Leela's Git: one command at a time, and a way back."""

import subprocess
import threading
import time

import pytest

from leela.blocks.git.git import GitError, GitRepo
from leela.blocks.git.safety import GitGateway, classify, gateway


def git(path, *args):
    return subprocess.run(['git', *args], cwd=path, check=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()


@pytest.fixture
def repo(tmp_path):
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
    # The same subcommands, asked to change something.
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
    # Network: slow, and touches neither the index nor the working tree.
    (('fetch', '--all', '--prune'), 'net'),
    (('push', '--set-upstream', 'origin', 'main'), 'net'),
    (('clone', '--', 'url', 'name'), 'net'),
    # Global options come before the subcommand and must not confuse the reading.
    (('-c', 'core.hooksPath=/dev/null', 'status'), 'read'),
    (('--git-dir', '/tmp/x', 'commit', '-m', 'x'), 'write'),
    # An unrecognised subcommand is a write, because guessing the other way corrupts.
    (('bisect', 'start'), 'write'),
    ((), 'write'),
])
def test_commands_are_sorted_by_what_they_do_to_the_repository(args, kind):
    assert classify(args) == kind


def test_reads_do_not_take_the_index_lock_and_writes_are_not_given_the_flag(repo, monkeypatch):
    seen = []
    real = subprocess.run

    def spy(argv, *a, **kw):
        seen.append(list(argv))
        return real(argv, *a, **kw)

    monkeypatch.setattr('leela.blocks.git.safety.subprocess.run', spy)
    g = GitGateway()
    g.run(repo, 'status', '--porcelain=v1')
    g.run(repo, 'add', '--', 'app.py')
    reads = [c for c in seen if 'status' in c]
    writes = [c for c in seen if 'add' in c]
    assert reads and all('--no-optional-locks' in c for c in reads)
    assert writes and not any('--no-optional-locks' in c for c in writes)


def test_a_write_excludes_every_other_command_in_the_same_repository(repo):
    """A merge and a status poll in the same checkout must not overlap.

    This is the invariant the whole module exists for, so it is asserted on observed overlap
    rather than on the lock's internals: instrument the one place a subprocess would be, count
    how many commands are inside it at once, and require that a write is ever alone.
    """
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
    threads = [threading.Thread(target=g.run, args=(repo, 'status')) for _ in range(4)]
    threads.append(threading.Thread(target=g.run, args=(repo, 'commit', '-m', 'x')))
    threads += [threading.Thread(target=g.run, args=(repo, 'status')) for _ in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert write_saw == [1], 'a write ran while something else was in the repository'
    assert peak > 1, 'reads should still share, or the panel crawls'


def test_a_slow_fetch_does_not_stop_the_panel_from_reading(repo):
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
    net = threading.Thread(target=g.run, args=(repo, 'fetch', '--all'))
    net.start()
    started.wait(1)
    g.run(repo, 'status')
    net.join()
    assert overlapped.is_set(), 'a status read waited for the fetch to finish'


def test_a_transaction_holds_the_lock_and_can_still_ask_questions(repo):
    "Reentrancy: the safepoint and the mutation are both Git calls inside the write lock."
    g = GitGateway()
    with g.transaction(repo, 'merge') as point:
        assert point is not None and point.head
        assert g.out(repo, 'branch', '--show-current').strip() == 'main'
        g.run(repo, 'commit', '--allow-empty', '-m', 'inside')
    assert g.out(repo, 'log', '-1', '--format=%s').strip() == 'inside'


def test_a_foreign_lock_is_retried_and_then_explained(repo, monkeypatch):
    """Another Git in the same checkout is a wait, then a sentence -- not a stack trace.

    Retrying is only sound because Git takes `index.lock` before it does any work, so the
    command that could not take it did nothing.
    """
    (repo/'.git'/'index.lock').write_text('')
    g = GitGateway()
    monkeypatch.setattr('leela.blocks.git.safety.LOCK_BACKOFF', .001)
    attempts = []
    real = subprocess.run

    def spy(argv, *a, **kw):
        attempts.append(argv)
        return real(argv, *a, **kw)

    monkeypatch.setattr('leela.blocks.git.safety.subprocess.run', spy)
    (repo/'app.py').write_text('value = 2\n')
    with pytest.raises(GitError) as e:
        g.run(repo, 'add', '--', 'app.py')
    assert len(attempts) > 1, 'a foreign lock should be waited on, not failed at once'
    assert 'Another Git process' in str(e.value) and 'Nothing was changed' in str(e.value)


def test_a_safepoint_keeps_uncommitted_work_and_undo_puts_it_back(repo):
    r = GitRepo.at(repo)
    (repo/'app.py').write_text('value = 99\n')
    (repo/'extra.txt').write_text('untracked\n')
    before = git(repo, 'rev-parse', 'HEAD')
    g = gateway()
    with g.transaction(repo, 'merge') as point:
        assert point.stash and point.dirty >= 1
        # Something destructive, of the shape a bad merge has.
        g.run(repo, 'commit', '-am', 'not what I wanted')
        g.run(repo, 'commit', '--allow-empty', '-m', 'nor this')
    assert git(repo, 'rev-parse', 'HEAD') != before
    outcome = g.undo(repo)
    assert git(repo, 'rev-parse', 'HEAD') == before
    assert (repo/'app.py').read_text() == 'value = 99\n', 'the uncommitted edit came back'
    assert (repo/'extra.txt').exists(), 'untracked files were never at risk'
    assert outcome['branch'] == 'main' and outcome['op'] == 'merge'


def test_undo_aborts_an_operation_it_finds_in_progress(repo):
    "A reset during a rebase leaves the rebase running, so undo aborts first."
    g = gateway()
    git(repo, 'checkout', '-b', 'feature')
    (repo/'app.py').write_text('feature\n')
    git(repo, 'commit', '-am', 'feature edit')
    git(repo, 'checkout', 'main')
    (repo/'app.py').write_text('main\n')
    git(repo, 'commit', '-am', 'main edit')
    before = git(repo, 'rev-parse', 'HEAD')
    with g.transaction(repo, 'merge'):
        g.run(repo, 'merge', '--no-edit', 'feature', check=False)
    assert g.active_operation(repo) == 'merge', 'the fixture needs a real conflict'
    g.undo(repo)
    assert not g.active_operation(repo)
    assert git(repo, 'rev-parse', 'HEAD') == before


def test_a_safepoint_survives_aggressive_garbage_collection(repo):
    "The snapshot commit is pinned, or `gc` collects the undo button."
    g = gateway()
    (repo/'app.py').write_text('value = 7\n')
    with g.transaction(repo, 'reset') as point:
        g.run(repo, 'reset', '--hard', 'HEAD')
    assert point.stash
    git(repo, 'gc', '--prune=now', '--aggressive')
    g.undo(repo)
    assert (repo/'app.py').read_text() == 'value = 7\n'


def test_undo_says_so_when_there_is_nothing_to_undo(repo):
    with pytest.raises(GitError, match='nothing to undo'):
        GitGateway().undo(repo)


def test_a_filter_that_cannot_run_is_named_instead_of_dirtying_notebooks_for_ever(repo):
    """The nbdev shape: a clean filter configured, and its command not installed here.

    Git does not consider a failing filter an error, so the only symptom is a notebook that
    comes back as modified however often it is staged. This is the sentence that replaces the
    mystery, and it has to name the command.
    """
    (repo/'.gitattributes').write_text('*.ipynb filter=nbdev_clean\n')
    git(repo, 'config', 'filter.nbdev_clean.clean', 'nbdev_clean_stdin --nowhere')
    r = GitRepo.at(repo)
    health = r.filter_health()
    assert health['ok'] is False
    assert [f['name'] for f in health['filters']] == ['nbdev_clean']
    assert health['filters'][0]['resolved'] == ''
    assert 'nbdev_clean' in health['explain'] and 'keep reappearing as modified' in health['explain']
    assert r.info()['filters']['ok'] is False, 'and the panel is told without asking separately'


def test_a_filter_that_resolves_is_reported_as_working(repo):
    (repo/'.gitattributes').write_text('*.ipynb filter=plain\n')
    git(repo, 'config', 'filter.plain.clean', 'cat')
    health = GitRepo.at(repo).filter_health()
    assert health['ok'] is True and health['explain'] == ''
    assert health['filters'][0]['resolved'].endswith('cat')


def test_a_filter_named_but_configured_nowhere_says_that_instead(repo):
    "A different problem with the same symptom, so it gets its own sentence."
    (repo/'.gitattributes').write_text('*.ipynb filter=ghost\n')
    health = GitRepo.at(repo).filter_health()
    assert health['ok'] is False
    assert health['filters'][0]['configured'] is False
    assert 'configured nowhere' in health['explain']


def test_a_repository_with_no_filters_is_quiet_about_them(repo):
    health = GitRepo.at(repo).filter_health()
    assert health == {'filters': [], 'ok': True, 'explain': ''}


@pytest.fixture
def diverged(repo):
    "`main` and `feature` with one commit each, touching different files."
    git(repo, 'checkout', '-b', 'feature')
    (repo/'lib.py').write_text('shared = True\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-m', 'feature work')
    git(repo, 'checkout', 'main')
    (repo/'other.py').write_text('other = True\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-m', 'main work')
    return repo


def test_a_dirty_tree_no_longer_refuses_a_merge_and_the_work_comes_back(diverged):
    """The complaint: leela refuses where PyCharm shelves, does it, and restores.

    `git merge` has no `--autostash`, so this is Leela's, and the assertion that matters is
    the last one -- the edit is still there afterwards, unstaged, as it was.
    """
    r = GitRepo.at(diverged)
    (diverged/'app.py').write_text('value = 42\n')
    out = r.merge('feature')
    assert (diverged/'lib.py').exists(), 'the merge happened'
    assert (diverged/'app.py').read_text() == 'value = 42\n', 'the uncommitted edit came back'
    assert out['kept_work'] is True
    assert not out['conflicted']
    # And the stash list is untouched: this was a borrow, not an entry to wonder about later.
    assert git(diverged, 'stash', 'list') == ''


def test_a_squash_merge_says_that_it_staged_rather_than_committed(diverged):
    "`merge --squash` leaves the index full on purpose; not saying so reads as a bug in leela."
    out = GitRepo.at(diverged).merge('feature', 'squash')
    assert out['staged'] == ['lib.py']
    assert not out['moved']
    assert out['summary'] == 'merge staged 1 file without committing -- commit to finish'


def test_a_merge_reports_its_conflicts_and_can_be_undone_whole(repo):
    r = GitRepo.at(repo)
    r.create('other')
    (repo/'app.py').write_text('other = True\n')
    r.stage(['app.py']); r.commit('other side')
    r.checkout('main')
    (repo/'app.py').write_text('main = True\n')
    r.stage(['app.py']); r.commit('main side')
    before = git(repo, 'rev-parse', 'HEAD')

    out = r.merge('other')
    assert out['conflicted'] == ['app.py']
    assert out['operation']['active'] == 'merge'
    assert out['summary'] == 'merge stopped at 1 conflicted file -- resolve them to continue'
    assert out['undo'], 'a merge that stopped is exactly when undo has to be there'

    back = r.undo(out['undo'])
    assert git(repo, 'rev-parse', 'HEAD') == before
    assert not r.info()['operation']['active'], 'the half-finished merge was called off too'
    assert (repo/'app.py').read_text() == 'main = True\n'
    assert back['op'] == 'merge'


def test_a_switch_that_cannot_carry_the_work_changes_nothing_at_all(repo):
    """Git refuses when the switch would lose an edit. Half of a shelve is worse than neither.

    The edit is to the one file that differs between the branches, so it genuinely cannot be
    carried across -- and the point of the test is that the attempt leaves no trace: same
    branch, same file, no conflict markers, and a sentence saying why.
    """
    r = GitRepo.at(repo)
    git(repo, 'checkout', '-b', 'feature')
    (repo/'app.py').write_text('feature = True\n')
    git(repo, 'commit', '-am', 'feature edit')
    git(repo, 'checkout', 'main')
    (repo/'app.py').write_text('uncommitted work\n')

    with pytest.raises(GitError) as e:
        r.checkout('feature')
    assert 'Nothing was changed' in str(e.value) and 'still on main' in str(e.value)
    assert git(repo, 'rev-parse', '--abbrev-ref', 'HEAD') == 'main'
    assert (repo/'app.py').read_text() == 'uncommitted work\n', 'the work is where it was'
    assert '<<<<<<<' not in (repo/'app.py').read_text(), 'and it is not half-merged'


def test_a_switch_carries_uncommitted_work_when_it_can(repo):
    "The ordinary case: Git itself moves compatible edits, and nothing is set aside."
    r = GitRepo.at(repo)
    git(repo, 'checkout', '-b', 'feature')
    (repo/'lib.py').write_text('only_on_feature = True\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-m', 'feature file')
    git(repo, 'checkout', 'main')
    (repo/'app.py').write_text('uncommitted work\n')

    out = r.checkout('feature')
    assert out['branch'] == 'feature'
    assert (repo/'app.py').read_text() == 'uncommitted work\n'
    assert not out['kept_work'], 'Git carried it; Leela did not have to'


def test_every_mutation_reports_where_the_repository_now_is(repo):
    r = GitRepo.at(repo)
    (repo/'app.py').write_text('value = 2\n')
    r.stage(['app.py'])
    out = r.commit('a change')
    assert set(out) >= {'op', 'head', 'head_before', 'moved', 'branch', 'staged', 'conflicted',
                        'operation', 'summary', 'undo', 'undoes'}
    assert out['moved'] and out['head'] != out['head_before']
    assert out['branch'] == 'main' and not out['staged']
    assert out['summary'] == f'commit moved this branch to {out["head"]}'
    assert 'commit on main' in out['undoes']


def test_the_journal_lists_the_ways_back_newest_first(repo):
    r = GitRepo.at(repo)
    (repo/'app.py').write_text('one\n')
    r.stage(['app.py']); r.commit('first')
    (repo/'app.py').write_text('two\n')
    r.stage(['app.py']); r.commit('second')
    points = r.safepoints()
    assert [p['op'] for p in points][:2] == ['commit', 'commit']
    assert points[0]['created_at'] >= points[1]['created_at']
    assert all(p['token'] for p in points)
