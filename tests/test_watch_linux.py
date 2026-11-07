"On Linux the watcher lists its folders itself, so inotify has no watch inside node_modules, .venv or .git/objects."
import os, threading
from pathlib import Path
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
