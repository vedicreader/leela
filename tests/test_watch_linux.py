"On Linux the watcher lists its folders itself, so inotify has no watch inside node_modules, .venv or .git/objects."
import os, threading
from leela.blocks.fs import watch as W

def _tree(root):
    for d in ('src/pkg', 'node_modules/a/b', '.venv/lib/site', '.git/objects/ab', '.git/refs/heads/feat', '.git/refs/remotes/origin', 'target/debug', 'docs/.hidden'):
        (root/d).mkdir(parents=True, exist_ok=True)
    (root/'.git'/'HEAD').write_text('ref: refs/heads/main\n'); (root/'.gitignore').write_text('target/\n')
    wt = root/'src'/'wt'; wt.mkdir(); (wt/'.git').write_text('gitdir: /elsewhere\n')   # a worktree's .git is a file
    return root

def test_the_linux_list_leaves_out_ignored_folders(tmp_path):
    root = _tree(tmp_path/'r')
    got = {os.path.relpath(p, root) for p in W.linux_targets([str(root)])}
    assert {'.', 'src', 'src/pkg', 'src/wt', 'docs', 'docs/.hidden', '.git', '.git/refs', '.git/refs/heads', '.git/refs/heads/feat', '.git/refs/remotes/origin'} <= got
    assert not {p for p in got if p.startswith(('node_modules', '.venv', '.git/objects', 'target'))}, got

def test_the_watcher_on_linux_watches_each_folder_and_adds_a_new_one(tmp_path, monkeypatch):
    "A fake `watchfiles.watch`: the first call reports a new folder, the second ends the watch."
    import watchfiles
    from watchfiles import Change
    root = _tree(tmp_path/'r')
    calls, pushed = [], []
    def fake(*paths, recursive=True, **kw):
        calls.append((set(paths), recursive))
        if len(calls) == 1:
            (root/'src'/'new'/'deep').mkdir(parents=True); (root/'src'/'new'/'deep'/'m.py').write_text('x')
            yield {(Change.added, str(root/'src'/'new'))}
    monkeypatch.setattr(watchfiles, 'watch', fake); monkeypatch.setattr(W, '_linux', lambda: True)
    class FS: roots, admitted = [root], []
    w = W.Watcher(FS())
    monkeypatch.setattr(w, '_push', lambda paths, resync=False: pushed.append(paths))
    w._run((str(root),), threading.Event(), threading.Event())
    (first, rec1), (second, rec2) = calls
    assert rec1 is False and rec2 is False, 'one watch per folder, never recursive'
    assert str(root/'node_modules') not in first and str(root/'.git'/'objects') not in first and str(root/'src') in first
    assert str(root/'src'/'new'/'deep') in second, 'a new folder is watched from the next round'
    assert str(root/'src'/'new'/'deep'/'m.py') in pushed[0], 'and what was made in it before then is pushed'

def test_the_watcher_off_linux_keeps_one_recursive_watch(tmp_path, monkeypatch):
    import watchfiles
    calls = []
    def fake(*paths, recursive=True, **kw):
        calls.append((paths, recursive)); return iter(())
    monkeypatch.setattr(watchfiles, 'watch', fake); monkeypatch.setattr(W, '_linux', lambda: False)
    class FS: roots, admitted = [tmp_path], []
    W.Watcher(FS())._run((str(tmp_path),), threading.Event(), threading.Event())
    assert calls == [((str(tmp_path),), True)]

def test_the_watcher_falls_back_to_whole_roots_when_inotify_runs_out(tmp_path, monkeypatch):
    import watchfiles
    calls = []
    def fake(*paths, recursive=True, **kw):
        calls.append(recursive)
        if not recursive: raise OSError(28, 'OS file watch limit reached')
        return iter(())
    monkeypatch.setattr(watchfiles, 'watch', fake); monkeypatch.setattr(W, '_linux', lambda: True)
    class FS: roots, admitted = [tmp_path], []
    W.Watcher(FS())._run((str(tmp_path),), threading.Event(), threading.Event())
    assert calls[-1] is True and calls.count(False) == 3


def _rig(tmp_path, monkeypatch):
    import watchfiles
    root = _tree(tmp_path/'r')
    calls, pushed, quiet = [], [], threading.Event()
    class FS: roots, admitted = [root], []
    w = W.Watcher(FS())
    monkeypatch.setattr(w, '_push', lambda paths, resync=False: pushed.append(paths))
    monkeypatch.setattr(W, '_linux', lambda: True)
    return watchfiles, root, calls, pushed, quiet, w

def test_the_re_list_returns_a_folder_made_after_the_list_and_what_is_in_it(tmp_path):
    root = _tree(tmp_path/'r')
    targets = W.linux_targets([str(root)])
    (root/'src'/'late'/'deep').mkdir(parents=True); (root/'src'/'late'/'deep'/'m.py').write_text('x')
    (root/'node_modules'/'a'/'junk.js').write_text('y')
    keep = lambda _c, p: 'node_modules' not in p
    new, files = W._unwatched(targets, [str(root)], keep)
    assert str(root/'src'/'late'/'deep') in new and str(root/'src'/'late'/'deep'/'m.py') in files
    assert not [f for f in files if 'node_modules' in f]
    assert W._unwatched(W.linux_targets([str(root)]), [str(root)], keep) == ([], [])

def test_a_folder_made_after_the_list_and_before_the_watch_is_found_on_the_first_idle_tick(tmp_path, monkeypatch):
    "The window is the one between the folder list and the watch starting; a folder made after the watch is live comes as an event. The re-list runs once per restart."
    watchfiles, root, calls, pushed, quiet, w = _rig(tmp_path, monkeypatch)
    def fake(*paths, recursive=True, **kw):
        calls.append((set(paths), quiet.is_set()))
        if len(calls) == 1:
            (root/'src'/'late'/'deep').mkdir(parents=True); (root/'src'/'late'/'deep'/'m.py').write_text('x')   # after the list, before the watch
            yield set()                                   # the first idle tick: no event ever named the folder
    monkeypatch.setattr(watchfiles, 'watch', fake)
    w._run((str(root),), threading.Event(), quiet)
    assert len(calls) == 2, 'the watch was rebuilt once, and the thread went on'
    assert str(root/'src'/'late'/'deep') in calls[1][0], 'the folder is watched from the rebuild'
    assert calls[1][1] is False, '`quiet` was not set before the re-list: a settled watch covers every folder that existed'
    assert pushed and str(root/'src'/'late'/'deep'/'m.py') in pushed[0], 'and what was in it is pushed'

def test_a_tree_with_no_new_folder_is_not_rebuilt_and_is_quiet(tmp_path, monkeypatch):
    watchfiles, root, calls, pushed, quiet, w = _rig(tmp_path, monkeypatch)
    def fake(*paths, recursive=True, **kw):
        calls.append(paths); yield set(); yield set()
    monkeypatch.setattr(watchfiles, 'watch', fake)
    w._run((str(root),), threading.Event(), quiet)
    assert len(calls) == 1 and quiet.is_set() and pushed == []

def test_the_re_list_restarts_at_most_twice_in_a_row(tmp_path, monkeypatch):
    "A list that always has one more folder than the watch must not loop for ever."
    watchfiles, root, calls, pushed, quiet, w = _rig(tmp_path, monkeypatch)
    real, n = W.linux_targets, []
    def stub(live):
        n.append(1)
        return real(live) + ([str(tmp_path/f'x{len(n)}')] if len(n) > 1 else [])
    monkeypatch.setattr(W, 'linux_targets', stub)
    def fake(*paths, recursive=True, **kw):
        calls.append(paths); yield set()
    monkeypatch.setattr(watchfiles, 'watch', fake)
    w._run((str(root),), threading.Event(), quiet)
    assert len(calls) == 3 and quiet.is_set()

def test_a_re_list_that_fails_is_skipped_and_the_watch_goes_on(tmp_path, monkeypatch):
    watchfiles, root, calls, pushed, quiet, w = _rig(tmp_path, monkeypatch)
    real, n = W.linux_targets, []
    def stub(live):
        n.append(1)
        if len(n) > 1: raise OSError(5, 'gone')
        return real(live)
    monkeypatch.setattr(W, 'linux_targets', stub)
    def fake(*paths, recursive=True, **kw):
        calls.append(paths); yield set()
    monkeypatch.setattr(watchfiles, 'watch', fake)
    w._run((str(root),), threading.Event(), quiet)
    assert len(calls) == 1 and quiet.is_set(), 'no retry was spent on it'
