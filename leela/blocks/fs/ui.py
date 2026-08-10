"""The file tree, and the Git decoration on it.

Directories fetch their children on first open (`hx_trigger='click once'`) rather than the
whole tree being rendered up front — a monorepo would otherwise cost tens of thousands of
nodes to draw a panel showing twelve.

Git state is computed once per render for *every* open root, not per node. `changes()` is a
subprocess per repository, so doing it inside `tree_node` would fork once per file.
"""

from __future__ import annotations

import json
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
            for c in repo.changes():
                out[str((repo.root/c['path']).resolve())] = c
        except GitError: pass
    return out


def tree_node(e, git_state=None):
    "One file-tree row; directories lazily fetch their children on first open."
    if e.is_dir:
        return Details(
            Summary(Span('▸', cls='lee-caret'), Span(e.name, cls='lee-fname'),
                    hx_get=f'/tree?path={quote(e.path)}', hx_target='next .lee-kids', hx_trigger='click once'),
            Div(cls='lee-kids'),
            cls='lee-node lee-dir' + (' lee-root' if e.is_root else ''), data_path=e.path,
            role='treeitem', aria_expanded='false', aria_selected='false')
    change = (git_state or {}).get(str(Path(e.path).resolve()))
    state = ('conflict' if change and change['conflicted'] else 'untracked' if change and change['untracked']
             else 'staged' if change and change['staged'] and not change['unstaged'] else 'modified' if change else '')
    return Div(Span(e.name, cls='lee-fname'), Span(state[:1].upper(), cls='lee-tree-git') if state else '',
               cls='lee-node lee-file' + (f' git-{state}' if state else ''), data_path=e.path, data_lang=e.lang or '',
               role='treeitem',aria_selected='false',
               onclick=f'event.preventDefault();event.stopPropagation();leeOpenFile({json.dumps(e.path)})')


def files_panel(fs):
    state = git_tree_state(fs)
    body = [tree_node(e, state) for e in fs.ls(None)] or [Div('no folder open', cls='lee-dim')]
    return Section(
        Div(Span('files', cls='lee-ptitle'), Span(cls='lee-spacer'), action_bar('web_files'),
            action_bar('files'), menu_button('files'),
            Button('−', cls='lee-pane-min', title='minimise files', aria_label='minimise files',
                   onclick='leePane("left", false)'), cls='lee-phead'),
        Div(*body, id='filetree', cls='lee-tree', tabindex='0', role='tree', aria_label='project files'),
        cls='lee-panel lee-files')
