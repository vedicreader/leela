from fasthtml.common import to_xml

from leela.term import TerminalGate
from leela.web.app import _shell
from leela.workspace import Workspace

from tests.assets import CSS, JS, SERVER


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
    assert '.lee-activity-btn.active' in CSS
    # Each view names the panels it shows; everything else in the column is hidden by the
    # one rule above it. The guarantee is the same -- Git does not show the file tree.
    assert '.lee-left-content > .lee-panel { display: none; }' in CSS
    assert '.lee-left.left-git .lee-source-control' in CSS
    panel = JS[JS.index('async function renderGitPanel'):JS.index('async function branchActions')]
    for feature in ('Staged changes', 'Changes', 'Branches', 'Stashes', 'Remotes & tags'):
        assert feature in panel
    for op in ('fetch', 'pull', 'push', 'stash', 'tag', 'stage all', 'unstage all'):
        assert op in panel


def test_workflows_are_a_panel_with_a_job_graph_in_it():
    """The visual half: the activity tab, the levels, and the four views.

    Playwright covers the behaviour where chromium exists; this is the part that has to
    hold everywhere, because a panel wired to a route name that no longer exists fails
    silently in the browser and loudly nowhere.
    """
    block = JS[JS.index('const wfUI ='):JS.index('const REL_MARK')]
    assert "data_left='workflows'" in SERVER and "data_left='releases'" in SERVER
    assert "api('/workflows'" in block and "post('/workflows/action'" in block
    assert "api('/workflows/runs'" in block and "api('/workflows/env'" in block
    assert 'function wfGraph' in block and 'lee-wf-level' in block and 'lee-wf-edge' in block
    for view in ('Jobs', 'Runs', 'Generated', 'Environment'):
        assert view in block
    for op in ('run workflow', 'generate from gheasy', 'Dockerfile'):
        assert op in block
    assert '.lee-wf-job' in CSS and '.lee-wf-graph' in CSS and '.lee-left.left-workflows' in CSS


def test_the_picker_offers_a_list_and_says_why_each_one_is_recommended():
    """The Add view: what the project is, what it could have, and why.

    A picker that only listed workflows would be a menu; the reason beside each one is what
    makes it a recommendation, and it comes from detection rather than from a preference.
    """
    block = JS[JS.index('function wfPickRows'):JS.index('function wfEnvRows')]
    assert 'lee-wf-detect' in block and 'recommended' in block
    assert 'data-pick-preview' in block and 'data-pick-add' in block
    assert 'already here' in block, 'a workflow that exists is not offered again'
    assert "api('/workflows/catalogue'" in JS and "op: op === 'add' ? 'add' : 'preview'" in JS
    assert "['add', 'Add']" in JS, 'the picker is one of the panel views'
    assert '.lee-wf-pick.recommended' in CSS and '.lee-wf-detect' in CSS


def test_authenticating_opens_the_real_gh_login():
    "It is a conversation with a browser and a one-time code; a form cannot hold it."
    assert "openTerm('gh-auth')" in JS
    assert "gh_auth_argv() if kind == 'gh-auth'" in SERVER
    assert "kind === 'gh-auth' ? 'gh auth'" in JS


def test_the_deploy_panel_shows_where_it_goes_before_it_goes_there():
    block = JS[JS.index('const depUI ='):JS.index('async function renderGitPanel')]
    assert "api('/deploys'" in block and "post('/deploys/action'" in block
    for f in ('deploy.py', 'Dockerfile', 'docker-compose.yml', 'Caddyfile'):
        assert f in block, 'the target card says which pieces exist'
    assert ' not set</strong>' in block and 'Workflows → Environment' in block
    assert "op: 'scaffold'" in block and 'write deploy.py' in block
    assert "openReleaseTerm(d.root, 'deploy')" in block
    assert '.lee-dep-files i.has' in CSS and '.lee-left.left-deploys' in CSS


def test_both_pipelines_share_one_terminal_socket():
    "A release and a deploy differ in what they run and in nothing else, including this."
    assert "url: '/pipeline/ws'" in JS and "openReleaseTerm(root = '', kind = 'release')" in JS
    assert 'WebSocketRoute(\'/pipeline/ws\'' in SERVER


def test_the_environment_view_hides_secret_values_in_the_browser_too():
    "The server never sends one; the client must not invent a place to show one either."
    block = JS[JS.index('function wfEnvRows'):JS.index('function renderWorkflowsPanel')]
    assert "'••••••••'" in block or '••••••••' in block
    assert 'e.secret ?' in block, 'a secret and a variable are drawn differently'


def test_the_release_pipeline_runs_steps_and_shows_them_in_a_terminal():
    block = JS[JS.index('const REL_MARK'):JS.index('async function renderGitPanel')]
    assert "api('/releases'" in block and "post('/releases/action'" in block
    assert 'function openReleaseTerm' in JS and "url: '/pipeline/ws'" in JS
    assert "termLabel('release'" in JS or "'release pipeline'" in JS
    for op in ('retry', 'skip', 'stop', 'reset', 'edit steps'):
        assert op in block
    assert 'relPoll' in block, 'steps finish on their own, so the panel keeps asking'
    assert 'missing' in block and 'Run anyway?' in block, 'it warns before a run it expects to fail'
    assert '.lee-rel-step.state-failed' in CSS and '.lee-left.left-releases' in CSS


def test_source_control_can_look_at_every_repository_in_the_workspace():
    """The plural view, and the two rules that keep it from lying.

    Every panel request carries the repository it is about, and the branch pill and tree
    badges refuse to be repainted from a repository the active tab is not in.
    """
    block = JS[JS.index('function gitScope'):JS.index('async function loadGitReview')]
    assert "function gitUrl" in JS and "q.set('repo', gitUI.repo)" in JS
    assert "post('/git/action', {op, repo: gitUI.repo" in JS
    assert 'if (gitUI.repo) return;' in JS, 'a pinned panel must not repaint the pill or tree'
    assert "['repos','All repos']" in JS
    assert "api('/git/repos'" in block and "post('/git/repos/action'" in block
    for op in ('fetch all', 'pull all', 'push all', 'clone…', 'add repository…'):
        assert op in block
    assert 'data-repo-open' in block and 'data-repo-remove' in block and 'data-repos-op' in block
    assert 'off branch' in block and 'unreleased' in block and 'expected_branch' in block
    assert 'function gitPinRepo' in JS and 'gitUI.selectedChanges.clear()' in JS
    assert '.lee-git-repo-row' in CSS and '.lee-git-repos-summary' in CSS and '.lee-git-scope' in CSS


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
    assert "gitUrl('/git/review/file'" in block and "gitUrl('/git/merge-preview'" in block
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
    assert "gitUrl('/git/commit/review', {ref})" in JS
    assert "gitUrl('/git/commit/file', {ref, path})" in JS
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
