"The file tree, and the Git decoration on it."

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
            for c in repo.changes(): out[str((repo.root/c['path']).resolve())] = c
        except GitError: pass
    return out

def _git_class(change):
    "One file's Git decoration, worst news first: a conflict outranks an unstaged edit."
    if not change: return ''
    if change['conflicted']: return 'conflict'
    if change['untracked']: return 'untracked'
    if change['staged'] and not change['unstaged']: return 'staged'
    return 'modified'

def tree_node(e, git_state=None):
    "One file-tree row; directories lazily fetch their children on first open."
    if e.is_dir:
        summary = Summary(Span('▸', cls='lee-caret'), Span(e.name, cls='lee-fname'),
            hx_get=f'/tree?path={quote(e.path)}', hx_target='next .lee-kids', hx_trigger='click once')
        return Details(summary, Div(cls='lee-kids'), data_path=e.path, role='treeitem',
            cls='lee-node lee-dir' + (' lee-root' if e.is_root else ''), aria_expanded='false', aria_selected='false')
    state = _git_class((git_state or {}).get(str(Path(e.path).resolve())))
    return Div(Span(e.name, cls='lee-fname'), Span(state[:1].upper(), cls='lee-tree-git') if state else '',
        cls='lee-node lee-file' + (f' git-{state}' if state else ''), data_path=e.path, role='treeitem',
        data_lang=e.lang or '', aria_selected='false',
        onclick=f'event.preventDefault();event.stopPropagation();leeOpenFile({json.dumps(e.path)})')

def files_panel(fs):
    state = git_tree_state(fs)
    # With nothing open this pane is the only way to start a session, so it offers, not reports.
    body = [tree_node(e, state) for e in fs.ls(None)] or [
        Div(Div('no folder open', cls='lee-dim'),
            Button('Open a folder…', cls='lee-btn go', onclick='leeAct("add_root")'),
            cls='lee-tree-empty')]
    minimise = Button('−', cls='lee-pane-min', title='minimise files', aria_label='minimise files',
        onclick='leePane("left", false)')
    head = Div(Span('files', cls='lee-ptitle'), Span(cls='lee-spacer'), action_bar('web_files'),
        action_bar('files'), menu_button('files'), minimise, cls='lee-phead')
    tree = Div(*body, id='filetree', cls='lee-tree', tabindex='0', role='tree', aria_label='project files')
    return Section(head, tree, cls='lee-panel lee-files')
