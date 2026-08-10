from pathlib import Path

from fasthtml.common import to_xml

from leela.term import TerminalGate
from leela.web.app import _shell
from leela.workspace import Workspace

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT/'leela/web/static/lee-ide.js').read_text()
CSS = (ROOT/'leela/web/static/lee-ide.css').read_text()


def test_status_is_a_prominent_timed_banner_with_a_busy_state():
    block = JS[JS.index('let statusTimer'):JS.index('/* ------------------------------------------------------------------ keymap')]
    assert "tone === 'busy' ? 0" in block and "el.classList.add('show')" in block
    assert "busyWords.test(msg)" in block and 'el.onclick = () =>' in block
    assert 'position: fixed; left: 50%; bottom: 34px' in CSS
    assert '.lee-status.busy::before' in CSS and '@keyframes lee-status-breathe' in CSS
    assert '@media (prefers-reduced-motion: reduce)' in CSS


def test_modals_take_focus_trap_tab_and_restore_the_previous_control():
    block = JS[JS.index('function modal('):JS.index('function inputDialog')]
    assert 'previousFocus = document.activeElement' in block
    assert 'aria-modal="true"' in block and 'role="dialog"' in block
    assert "e.key === 'Tab'" in block and "e.key === 'Escape'" in block
    assert "$$('.lee-modal').at(-1) !== m" in block
    assert 'previousFocus.focus({preventScroll: true})' in block
    assert 'MutationObserver' in block and "row.setAttribute('role', 'option')" in block


def test_header_leads_with_workspace_branch_and_named_menus_without_starting_a_kernel(tmp_path):
    html = to_xml(_shell(Workspace(roots=[tmp_path]), TerminalGate()))
    assert 'id="workspacepill"' in html and 'leeWorkspaceMenu(this)' in html
    assert 'id="gitpill"' in html and 'leeBranchMenu(this)' in html
    assert '>File</button>' in html and '>Tools</button>' in html and '>Debug</button>' in html
    assert 'id="themepill"' not in html and 'id="cwdpill"' not in html


def test_web_theme_is_applied_before_styles_and_has_all_modes():
    assert "const THEMES = ['system', 'dark', 'light']" in JS
    assert "localStorage.getItem('lee-theme')" in JS
    assert ':root[data-theme="light"]' in CSS
    assert ':root:not([data-theme="dark"])' in CSS


def test_file_backed_code_is_saved_before_execution_for_disk_reading_tools():
    run_cell = JS[JS.index('async function runCell'):JS.index('function paintDebugInlineValues')]
    run_file = JS[JS.index('async function runFile'):JS.index('async function runSelection')]
    guard = "$('.lee-tab.active.dirty') && !await saveTab(true)"
    assert guard in run_cell and guard in run_file
    assert run_cell.index('saveTab(true)') < run_cell.index("postEvents('/nb/run/stream'")


def test_autosave_is_configurable_debounced_and_invalidates_stale_requests():
    block = JS[JS.index('function autoSaveEnabled'):JS.index('function jumpToLine')]
    assert "lee.filePrefs.autoSave || 'afterDelay'" in block
    assert 'Crash recovery' in JS
    assert 'setTimeout(async () =>' in block and 'lee.filePrefs.autoSaveDelay' in block
    assert 'version !== lee.editVersion' in block
    save = JS[JS.index('async function saveTab'):JS.index('async function saveAllTabs')]
    assert 'expectedVersion !== lee.editVersion' in save


def test_every_tab_reports_pending_saving_saved_and_failed_autosave(tmp_path):
    from leela.web.app import _tab_bar
    p = tmp_path/'notes.py'; p.write_text('answer = 42\n')
    ws = Workspace(roots=[tmp_path]); tab = ws.open(p)
    saved = to_xml(_tab_bar(ws))
    assert 'lee-save-state saved' in saved and 'saved on disk' in saved
    tab.dirty = True
    pending = to_xml(_tab_bar(ws))
    assert 'lee-save-state pending' in pending and 'changes waiting for autosave' in pending

    autosave = JS[JS.index('function setTabSaveState'):JS.index('function jumpToLine')]
    save = JS[JS.index('async function saveTab'):JS.index('async function saveAllTabs')]
    assert "pending: lee.path ? 'Changes queued for autosave'" in autosave
    assert "setTabSaveState($('.lee-tab.active'), 'saving')" in autosave
    assert "setTabSaveState(saveTabEl, 'saved')" in save
    assert "setTabSaveState(saveTabEl, 'error'" in save
    for state in ('pending', 'saving', 'error'):
        assert f'.lee-save-state.{state}' in CSS


def test_modified_files_and_lines_are_visible_before_opening_source_control(tmp_path):
    html = to_xml(_shell(Workspace(roots=[tmp_path]), TerminalGate()))
    assert 'id="gitpill"' in html
    assert '.lee-file.git-modified .lee-fname' in CSS
    assert '.cm-line.cm-lee-change' in CSS
    mount = JS[JS.index('async function mountFile'):JS.index('function notebookHeadings')]
    assert "api('/git/file?path='" in mount
    assert 'changedLines: git.ranges' in mount and 'onChangeClick' in mount


def test_left_activity_bar_has_a_pycharm_style_file_structure(tmp_path):
    html = to_xml(_shell(Workspace(roots=[tmp_path]), TerminalGate()))
    assert 'data-left="symbols"' in html and 'id="symbols"' in html
    assert 'async function leeSymbols()' in JS and "api('/outline?path='" in JS
    assert '.lee-symbol-row' in CSS and '.lee-left.left-symbols' in CSS


def test_agent_model_and_reasoning_live_below_the_growing_prompt(tmp_path):
    html = to_xml(_shell(Workspace(roots=[tmp_path]), TerminalGate()))
    assert html.index('id="agentprompt"') < html.index('id="agentmodel"')
    assert 'id="agentreasoning"' in html and 'lee-composer-footer' in html
    composer = JS[JS.index('function initAgentComposer'):JS.index('async function sendAgentCommand')]
    assert "input.style.height = 'auto'" in composer and "localStorage.getItem('lee-agent-reasoning')" in composer
    assert "&reasoning=" in JS


def test_agent_panel_sends_the_open_notebook_cells_as_context():
    from inspect import getsource
    from leela.web.app import ide_app
    source = getsource(ide_app)
    stream = source[source.index("@rt('/agent/stream')"):source.index("@rt('/agent/approval')")]
    assert 'context = nb.context(len(nb))' in stream
    assert 'context_path = nb.path' in stream
    assert 'ws.ask_stream(q, attachments=attachments' in stream


def test_agent_vocabulary_exposes_commands_tools_and_project_skills(tmp_path):
    skill = tmp_path/'.agents/skills/notebook-tests/SKILL.md'
    skill.parent.mkdir(parents=True)
    skill.write_text('---\nname: notebook-tests\ndescription: How this project tests notebooks.\n---\n\nDo it carefully.\n')
    from starlette.testclient import TestClient
    from leela.web.app import ide_app
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as client:
        vocabulary = client.get('/agent/commands').json()
    assert {'commands', 'tools', 'skills'} <= vocabulary.keys()
    assert any(x['name'] == 'research' for x in vocabulary['tools'])
    assert any(x['name'] == 'notebook-tests' for x in vocabulary['skills'])


def test_agent_composer_can_mention_tools_and_skills_inline():
    composer = JS[JS.index('function chooseAgentSuggest'):JS.index('async function leeAgentControl')]
    assert "item.kind === 'tool' || item.kind === 'skill'" in composer
    assert "vocab.tools || []" in composer and "vocab.skills || []" in composer
    assert "detail: `${x.kind} · ${x.help || ''}`" in composer
    send = JS[JS.index('async function sendAgent()'):JS.index("es.addEventListener('activity'")]
    assert "agentVocabulary?.commands" in send
    assert "if (q.startsWith('/'))" in send


def test_responsive_layout_uses_mobile_drawers_instead_of_dropping_tools():
    assert '.lee-app.mobile-left .lee-left' in CSS and '.lee-app.mobile-right .lee-right' in CSS
    assert "matchMedia('(max-width: 1100px)')" in JS
    assert '.lee-left, .lee-right { display: none; }' not in CSS


def test_notebook_cells_offer_ipykernel_debugging():
    assert 'leeDebugCell' in JS and "'/nb/debug/stream'" in JS
    debug = JS[JS.index('async function debugCell'):JS.index('async function askCell')]
    assert 'id: c.id' in debug and "path: lee.path || lee.tabKey || ''" in debug
    assert "leeDebugControl('next')" in JS and "leeDebugControl('stepIn')" in JS
    assert 'onBreakpoint:' in JS and 'LeeCM.setBreakpoints' in JS
    assert '/nb/debug/variables?reference=' in JS and 'evaluates in the paused debug frame' in JS
    assert "scope: lee.execScope, frame_id: lee.debugState?.frame_id" in JS
    assert 'async function revealDebugFrame' in JS and 'LeeCM.setDebugLine' in JS
    assert 'paintDebugInlineValues' in JS and 'lee.debugState?.variables' in JS
    assert 'leeOpenFile(frame.open_path)' in JS and '/nb/debug/source?frame_id=' in JS
    assert '.lee-debugger' in CSS and '.cm-lee-breakpoint' in CSS and '.cm-lee-debug-line' in CSS


def test_pyproject_dependencies_get_runtime_version_pills(tmp_path):
    from starlette.testclient import TestClient
    from leela.web.app import ide_app
    from leela.workspace import Workspace
    p = tmp_path/'pyproject.toml'
    p.write_text('[project]\nname="demo"\nversion="0.1"\nkeywords=["package-that-does-not-exist"]\n'
                 'dependencies=[\n  "pytest>=1", # a deliberately long comment after the declaration\n]\n'
                 '[project.optional-dependencies]\ndev=["package-that-does-not-exist>=9", "pytest>=1"]\n')
    ws = Workspace(roots=[tmp_path]); ws.open(p)
    with TestClient(ide_app(ws)) as client:
        data = client.get('/editor/packages', params={'path': str(p)}).json()
    rows = {r['name']: r for r in data['packages']}
    assert rows['pytest']['installed'] and rows['pytest']['compatible'] is True
    assert rows['package-that-does-not-exist']['installed'] is None
    # The missing package belongs on its declaration, not the same text in `keywords`;
    # both optional requirements on one line retain their own insertion columns.
    assert rows['package-that-does-not-exist']['line'] == 9
    assert len({r['column'] for r in data['packages'] if r['line'] == 9}) == 2
    assert data['summary']['missing'] == 1
    assert 'LeeCM.setPackageVersions' in JS and 'lee-package-summary' in JS
    assert '.cm-lee-package.missing' in CSS and '.lee-package-popover' in CSS


def test_notebooks_have_collapsible_cells_and_a_heading_outline():
    assert 'function notebookHeadings' in JS and 'function notebookToc' in JS
    assert 'function setCellCollapsed' in JS and 'cell_collapse:' in JS
    assert '.lee-cell.collapsed .lee-cm' in CSS and '.lee-nb-toc' in CSS
    assert '.lee-gutter .lee-cell-fold' in CSS


def test_workspace_panes_can_minimise_and_restore_independently(tmp_path):
    html = to_xml(_shell(Workspace(roots=[tmp_path]), TerminalGate()))
    assert html.count('lee-pane-min') >= 3 and html.count('lee-pane-restore') == 3
    assert 'function leePane' in JS and "'no-bottom'" in JS
    assert '.lee-app.no-bottom .lee-bottomdock' in CSS


def test_git_is_a_first_class_vertical_project_tab(tmp_path):
    html = to_xml(_shell(Workspace(roots=[tmp_path]), TerminalGate()))
    assert 'lee-activity' in html and 'data-left="files"' in html and 'data-left="git"' in html
    assert 'id="gitpanel"' in html and 'lee-source-control' in html
    assert 'function leeLeft' in JS and 'async function renderGitPanel' in JS
    assert '.lee-activity-btn.active' in CSS and '.lee-left.left-git .lee-files' in CSS
    panel = JS[JS.index('async function renderGitPanel'):JS.index('async function branchActions')]
    for feature in ('Staged changes', 'Changes', 'Branches', 'Stashes', 'Remotes & tags'):
        assert feature in panel
    for op in ('fetch', 'pull', 'push', 'stash', 'tag', 'stage all', 'unstage all'):
        assert op in panel


def test_git_compare_has_explicit_direction_and_works_from_branch_rows():
    block = JS[JS.index('function gitBranchesView'):JS.index('async function showGitReflog')]
    assert 'From (base)' in block and 'To (target)' in block
    assert 'gitcompareswap' in block and "gitUI.reviewMode = 'snapshot'" in block
    assert "gitUI.reviewHead = branch" in block and "gitUI.tab = 'review'" in block
    assert 'review selected into current' in block
    assert "gitUI.reviewMode = 'snapshot'" in block
    assert '.lee-git-compare-fields' in CSS and '.lee-git-compare-summary' in CSS
    assert 'function gitReviewView' in block and 'function showMergePreview' in block
    assert 'snapshot differences' in block and 'swap direction' in block
    assert '/git/review/file?' in block and '/git/merge-preview?' in block
    assert '.lee-git-full-review' in CSS and '.lee-git-merge-preview' in CSS


def test_git_diffs_open_as_editor_tabs_with_unified_and_split_layouts():
    assert 'function openGitDiffTab' in JS and "lee.kind = 'git-diff'" in JS
    assert 'unified</button>' in JS and 'side by side</button>' in JS
    assert 'gitDiffNotebookHtml' in JS and 'LeeCM.createMerge' in JS
    assert "revertControls: data.allowWrite ? 'a-to-b' : false" in JS
    assert 'apply result to working tree' in JS and "gitDo('write_worktree'" in JS
    assert "row.querySelector('.lee-git-file').onclick" in JS and "kind: 'changes-'" in JS
    assert "loadGitReviewFile(b.dataset.reviewPath, true)" in JS
    assert '.lee-diff-document' in CSS and '.lee-diff-cell.collapsed' in CSS
    assert '.cm-merge-a .cm-changedLine' in CSS and '.cm-merge-b .cm-changedLine' in CSS
    assert '.cm-merge-revert button:hover' in CSS
    assert '.lee-git-diff-tab' in CSS


def test_git_history_inspects_commits_and_opens_each_file_without_a_full_patch_modal():
    assert "api('/git/commit/review?ref='" in JS
    assert "api('/git/commit/file?ref='" in JS
    assert 'function gitCommitInspector' in JS and 'data-history-commit' in JS
    assert 'openGitCommitFile' in JS and "kind: 'commit'" in JS
    assert '.lee-git-commit-inspector' in CSS and '.lee-git-commit-file' in CSS


def test_git_ui_confirms_destructive_operations_and_supports_branch_management():
    block = JS[JS.index('async function refreshProjectPills'):JS.index('/* ------------------------------------------------------------------ research')]
    for action in ('stage', 'unstage', 'discard', 'checkout', 'create', 'delete', 'commit', 'fetch', 'pull', 'push'):
        assert action in block
    assert "confirmDialog('discard changes'" in block
    assert "confirmDialog('delete branch'" in block
    assert 'staged changes' in block and 'working tree' in block
    assert 'showGitFileDiff' in block and 'gitPatchHtml' in block
    assert 'gitcontent' in block and 'gitraw' in block
    assert 'lee-git-diff-expanded' in block and '.lee-modal.lee-git-diff-expanded' in CSS
