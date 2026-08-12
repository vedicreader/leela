"""Integrative web UX block: cursor theme, file selection, SCM refresh, nbdev prepare."""

from __future__ import annotations

from pathlib import Path

from fasthtml.common import first, to_xml
from starlette.testclient import TestClient

from leela.term import TerminalGate
from leela.web.app import _shell, ide_app
from leela.workspace import Workspace

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / 'leela/web/static/lee-ide.js').read_text()
CSS = (ROOT / 'leela/web/static/lee-ide.css').read_text()


def test_cursor_theme_is_default_and_keeps_light_dark_system():
    assert "const THEMES = ['system', 'dark', 'light', 'cursor']" in JS
    assert "localStorage.getItem('lee-theme') || 'cursor'" in JS
    assert ':root[data-theme="cursor"]' in CSS
    assert ':root[data-theme="light"]' in CSS
    assert ':root[data-theme="dark"]' not in CSS or '--lee-bg:' in CSS  # dark is :root default
    assert 'thin light chrome' in JS
    # Quiet chrome — not chunky card buttons as the primary look.
    assert ':root[data-theme="cursor"] .lee-btn.go' in CSS
    assert ':root[data-theme="cursor"] .lee-phead' in CSS
    assert ':root[data-theme="cursor"] .lee-node.sel' in CSS


def test_file_click_sets_the_same_selected_state_as_keyboard_navigation(tmp_path):
    """Mouse opens used to stopPropagation without painting `.sel`; keys already did."""
    from leela.web.app import _tree_node
    (tmp_path / 'alpha.py').write_text('x = 1\n')
    ws = Workspace(roots=[tmp_path])
    file_entry = first(ws.fs.ls(str(tmp_path)))
    html = to_xml(_tree_node(file_entry))
    assert 'selectTreeNode(this)' in html
    assert 'leeOpenFile(' in html
    open_fn = JS[JS.index('async function leeOpenFile'):JS.index('window.leeOpenFile')]
    assert 'selectTreeNode(treeNode)' in open_fn or 'selectTreeNode(after)' in open_fn
    assert 'function selectTreeNode(n)' in JS
    assert "n.classList.add('sel')" in JS
    assert "window.selectTreeNode = selectTreeNode" in JS


def test_source_control_refreshes_when_repo_or_branch_switches():
    assert "gitUI.repoRoot" in JS
    assert 'function gitInfoUrl()' in JS
    assert "root: gitUI.repoRoot" in JS or "'?root=' + encodeURIComponent(root)" in JS
    assert 'if (scmPanelOpen()) renderGitPanel(d)' in JS
    workspace = JS[JS.index('async function leeWorkspaceMenu'):JS.index('window.leeWorkspaceMenu')]
    assert "gitUI.repoRoot = root.path" in workspace
    assert 'renderGitPanel()' in workspace
    branch = JS[JS.index('async function leeBranchMenu'):JS.index('window.leeBranchMenu')]
    assert 'refreshScmIfOpen' in branch
    assert "async def git_info(root: str = '')" in (ROOT / 'leela/web/app.py').read_text()


def test_nbdev_prepare_uses_settings_ini_and_initialises_uv(tmp_path):
    (tmp_path / 'settings.ini').write_text(
        '[DEFAULT]\nlib_name = demo\nlib_path = demo\nnbs_path = nbs\n')
    (tmp_path / 'nbs').mkdir()
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        # Without nbdev installed this returns a structured error, but the route must exist
        # and must prefer the settings.ini root rather than silently no-op.
        r = client.post('/project/nbdev_prepare', json={})
        body = r.json()
        assert r.status_code in (200, 400)
        if body.get('ok'):
            assert body['root'] == str(tmp_path)
            assert body['nbs_path'] == 'nbs'
        else:
            assert 'nbdev' in body.get('error', '').lower() or 'uv' in body.get('error', '').lower() \
                or 'settings.ini' in body.get('error', '').lower()
    assert "leeNbdevPrepare" in JS
    assert "'nbdev prepare…'" in JS or 'nbdev prepare…' in JS
    assert '/project/nbdev_prepare' in JS


def test_shell_still_exposes_workspace_and_git_switchers(tmp_path):
    html = to_xml(_shell(Workspace(roots=[tmp_path]), TerminalGate()))
    assert 'id="workspacepill"' in html and 'leeWorkspaceMenu(this)' in html
    assert 'id="gitpill"' in html and 'leeBranchMenu(this)' in html
    assert 'data-left="git"' in html


def test_agent_focus_action_opens_the_right_panel_before_prompt_fill():
    # webshots and block flows fill #agentprompt only after focus_agent.
    assert 'focus_agent:' in JS
    assert "leeRight('agent')" in JS
    assert "$('#agentprompt')?.focus()" in JS
    assert "applyTheme('cursor')" in (ROOT / 'tools/webshots.py').read_text()
    assert "leeAct('focus_agent')" in (ROOT / 'tools/webshots.py').read_text()
