"The file tree, and the Git decoration on it."

from __future__ import annotations

import json, os
from pathlib import Path
from urllib.parse import quote

from fasthtml.common import Button, Details, Div, Section, Span, Summary

from ...core.ui import action_bar, menu_button
from ..git.git import GitError, GitRepo

__all__ = ['git_tree_state', 'tree_node', 'files_panel']

def git_tree_state(fs):
    "Absolute changed paths for file-tree decoration, across every open repository."
    out = {}
    seen = set()
    for root in fs.roots:
        try: repo = GitRepo.at(root)
        except GitError: continue
        if repo.root in seen: continue
        seen.add(repo.root)
        try:
            for c in repo.decorations(): out[str((repo.root/c['path']).resolve())] = c
        except GitError: pass
        for rel in _ignored_paths(repo):
            out.setdefault(str((repo.root/rel).resolve()), {'path': rel, 'ignored': True})
    return out

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
        if c and (not best or GIT_RANK.index(c) > GIT_RANK.index(best)): best = c
        if best == GIT_RANK[-1]: break
    return best

def _kids(fs, path, git_state, hidden, opened):
    # A remembered folder can be gone, or outside the roots, by the time this draws.
    try: return [tree_node(e, git_state, hidden, fs, opened) for e in fs.ls(path, hidden=hidden)]
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
    state = git_tree_state(fs)
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
