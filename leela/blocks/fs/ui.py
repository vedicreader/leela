"The file tree, and the Git decoration on it."

from __future__ import annotations

import json, os, threading, time
from pathlib import Path
from urllib.parse import quote

from fasthtml.common import Button, Details, Div, Section, Span, Summary

from ...core.ui import action_bar, menu_button
from ..git.git import GitError, GitRepo
from ..git.seam import invalidate

__all__ = ['git_tree_state', 'tree_git', 'tree_node', 'files_panel', 'stale_tree', 'git_ignored']

#: How long one repository's decoration is reused when nothing under it was seen to change. Every
#: `/tree` ran `git status` and `git ls-files` in every open repository, forked from a process of a
#: gigabyte or more, and a folder being written to without pause asked for one a second.
TREE_TTL = 5
#: The ignored list changes with a `.gitignore`, which `stale_tree` sees, so it lasts longer.
IGNORED_TTL = 30
_TREE, _TREE_LOCK = {}, threading.Lock()
#: One real look at a time: two tabs asking at once otherwise ran git twice, and the second finds the first's answer.
_LOOK = threading.Lock()

def _git_stamp(repo):
    "What a stage, commit, checkout or reset changes inside `.git`, which the watcher skips."
    with _TREE_LOCK: gd = _TREE.get(('gitdir', str(repo.root)))
    if gd is None:
        try: gd = Path(repo.run('rev-parse', '--absolute-git-dir').strip())
        except Exception: gd = Path(repo.root)/'.git'
        with _TREE_LOCK: _TREE[('gitdir', str(repo.root))] = gd
    def mt(p):
        try: return p.stat().st_mtime_ns
        except OSError: return 0
    return tuple(mt(gd/n) for n in ('index', 'HEAD', 'logs/HEAD'))

def _memo(key, ttl, stamp, make, peek=False):
    "`make()`, reused while younger than `ttl` and `stamp` is unchanged. `peek` returns what is held, however old, or None, and never calls `make`."
    with _TREE_LOCK: hit = _TREE.get(key)
    if peek: return hit[2] if hit else None
    if hit and time.monotonic() - hit[0] < ttl and hit[1] == stamp: return hit[2]
    value = make()
    with _TREE_LOCK: _TREE[key] = (time.monotonic(), stamp, value)
    return value

def _repo_state(repo, cached=False):
    "One repository's changed and ignored paths, absolute. `cached` runs no git: it is what the last look found."
    def changes():
        try: return {str((repo.root/c['path']).resolve()): c for c in repo.decorations()}
        except GitError: return {}
    key = ('changes', str(repo.root))
    out = dict((_memo(key, 0, None, None, peek=True) if cached else _memo(key, TREE_TTL, _git_stamp(repo), changes)) or {})
    for rel in _repo_ignored(repo, cached) or (): out.setdefault(str((repo.root/rel).resolve()), {'path': rel, 'ignored': True})
    return out

def _repo_ignored(repo, cached=False):
    return _memo(('ignored', str(repo.root)), IGNORED_TTL, None, lambda: _ignored_paths(repo), peek=cached)

#: How long the repository each root sits in is trusted. Finding it is a `git rev-parse` per root.
REPOS_TTL = 60

def _repos(fs, cached=False):
    "Each open repository once. `cached` runs no git, and is empty until a real look has found them."
    def find():
        seen = {}
        for root in fs.roots:
            try: repo = GitRepo.at(root)
            except GitError: continue
            seen.setdefault(str(repo.root), repo)
        return list(seen.values())
    return _memo(('repos', tuple(str(r) for r in fs.roots)), REPOS_TTL, None, find, peek=cached) or []

def git_tree_state(fs, cached=False):
    "Absolute changed paths for file-tree decoration, across every open repository. `cached` never runs git."
    if cached: return {k: v for repo in _repos(fs, True) for k, v in _repo_state(repo, True).items()}
    with _LOOK:
        out = {}
        for repo in _repos(fs): out.update(_repo_state(repo))
        return out

#: Rows one `/tree/git` answers; a client with more asks in batches.
TREE_GIT_MAX = 5000

def tree_git(fs, paths):
    "`{path: state}` for tree rows, keyed as the client sent them: a folder takes the strongest state under it."
    state = git_tree_state(fs)
    def one(p):
        try: return _folder_class(p, state) if os.path.isdir(p) else _git_class(state.get(str(Path(p).resolve())))
        except Exception: return ''
    return {p: one(p) for p in list(paths)[:TREE_GIT_MAX]}

def _under(p, root): return p == root or p.startswith(root.rstrip('/') + '/')

def git_ignored(fs, path):
    "Whether git ignores `path` or a folder above it, from the cached ignored lists."
    p = os.path.realpath(path)
    for repo in _repos(fs):
        if not _under(p, str(repo.root)): continue
        return any(_under(p, str(repo.root/rel.rstrip('/'))) for rel in _repo_ignored(repo))
    return False

def stale_tree(paths):
    "Forget the decoration of each repository a changed path is in, and its ignored list on a `.gitignore`."
    paths = [os.path.realpath(p) for p in paths]
    with _TREE_LOCK:
        for key in [k for k in _TREE if k[0] in ('changes', 'ignored')]:
            hit = [p for p in paths if _under(p, key[1])]
            if not hit: continue
            if key[0] == 'changes': invalidate(key[1])        # gheasy's own short cache, or the old answer comes back
            if key[0] == 'changes' or any(Path(p).name == '.gitignore' for p in hit): del _TREE[key]

def _ignored_paths(repo):
    "What git is deliberately not tracking here. A failure is no decoration, never no tree."
    try: out = repo.run('ls-files', '--others', '--ignored', '--exclude-standard', '--directory')
    except Exception: return ()
    return [l.strip() for l in str(out or '').splitlines() if l.strip()]

#: Worst news first, so a folder can take the strongest state under it and mean something by it.
GIT_RANK = ('ignored', 'staged', 'modified', 'untracked', 'conflict')

def _git_class(change):
    "One file's Git decoration, worst news first: a conflict outranks an unstaged edit."
    if not change: return ''
    if change.get('ignored'): return 'ignored'
    if change['conflicted']: return 'conflict'
    if change['untracked']: return 'untracked'
    if change['staged'] and not change['unstaged']: return 'staged'
    return 'modified'

def _folder_class(path, git_state):
    "The strongest state anywhere under this folder."
    try: prefix = str(Path(path).resolve())
    except Exception: return ''
    best = ''
    for key, change in git_state.items():
        if not (key == prefix or key.startswith(prefix + os.sep)): continue
        c = _git_class(change)
        # An ignored `__pycache__/` inside says nothing about a tracked folder holding it.
        if c == 'ignored' and key != prefix: continue
        if c and (not best or GIT_RANK.index(c) > GIT_RANK.index(best)): best = c
        if best == GIT_RANK[-1]: break
    return best

def _kids(fs, path, git_state, hidden, opened):
    # A remembered folder can be gone, or outside the roots, by the time this draws.
    try: return [tree_node(e, git_state, hidden, fs, opened) for e in fs.ls(path, hidden=hidden, skip=not hidden)]
    except Exception: return []

def tree_node(e, git_state=None, hidden=False, fs=None, opened=frozenset()):
    "One file-tree row. A folder in `opened` is drawn expanded rather than fetched on click."
    if e.is_dir:
        rows = _kids(fs, e.path, git_state, hidden, opened) if fs is not None and e.path in opened else []
        # Drawn children and the lazy fetch together would give the folder two copies of itself.
        lazy = {} if rows else dict(hx_get=f'/tree?path={quote(e.path)}' + ('&hidden=1' if hidden else ''),
            hx_target='next .lee-kids', hx_trigger='click once')
        state = _folder_class(e.path, git_state or {})
        summary = Summary(Span('▸', cls='lee-caret'), Span(e.name, cls='lee-fname'),
            Span(state[:1].upper(), cls='lee-tree-git') if state else '', **lazy)
        return Details(summary, Div(*rows, cls='lee-kids'), data_path=e.path, role='treeitem',
            cls='lee-node lee-dir' + (' lee-root' if e.is_root else '')
                + (f' git-{state}' if state else ''), open=bool(rows),
            aria_expanded='true' if rows else 'false', aria_selected='false')
    state = _git_class((git_state or {}).get(str(Path(e.path).resolve())))
    return Div(Span(e.name, cls='lee-fname'), Span(state[:1].upper(), cls='lee-tree-git') if state else '',
        cls='lee-node lee-file' + (f' git-{state}' if state else ''), data_path=e.path, role='treeitem',
        data_lang=e.lang or '', aria_selected='false',
        onclick=f'leeTreeClick(event,{json.dumps(e.path)})')

def files_panel(fs, hidden=False, opened=()):
    state = git_tree_state(fs, cached=True)   # the client paints the marks from `/tree/git`
    opened = frozenset(str(p) for p in opened)
    # With nothing open this pane is the only way to start a session, so it offers, not reports.
    body = [tree_node(e, state, hidden, fs, opened) for e in fs.ls(None)] or [
        Div(Div('no folder open', cls='lee-dim'),
            Button('Open a folder…', cls='lee-btn go', onclick='leeAct("add_root")'),
            cls='lee-tree-empty')]
    minimise = Button('−', cls='lee-pane-min', title='minimise files', aria_label='minimise files',
        onclick='leePane("left", false)')
    head = Div(Span('files', cls='lee-ptitle'), Span(cls='lee-spacer'), action_bar('web_files'),
        action_bar('files'), menu_button('files'), minimise, cls='lee-phead')
    tree = Div(*body, id='filetree', cls='lee-tree', tabindex='0', role='tree', aria_label='project files')
    return Section(head, tree, cls='lee-panel lee-files')
