from fasthtml.common import to_xml

from leela.blocks.term.term import TerminalGate
from leela.app import _shell
from leela.workspace import Workspace

from tests.assets import CSS, JS, SERVER, read


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
    assert "const THEMES = ['system', 'dark', 'light', 'cursor']" in JS
    assert "localStorage.getItem('lee-theme')" in JS
    assert ':root[data-theme="light"]' in CSS
    assert ':root[data-theme="cursor"]' in CSS
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
    from leela.app import _tab_bar
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


def test_a_change_mark_thickens_under_the_pointer_and_opens_the_committed_version(tmp_path):
    """Clicking one gutter mark has to answer with that change, not with the whole file's diff.

    The thickening is the affordance for the click, so the two share one hit target: the page adds
    the class, the editor bundle answers the click, and both use 12px.
    """
    mount = JS[JS.index('async function mountFile'):JS.index('function notebookHeadings')]
    assert 'showChangePopup(st.path, line)' in mount and "armChangeGutter($('#filecm'))" in mount
    arm = JS[JS.index('function armChangeGutter'):JS.index('function changePopupBody')]
    assert "closest?.('.cm-lee-change')" in arm and 'getBoundingClientRect().left + 12' in arm
    assert "line.classList.add('lee-change-hot')" in arm
    assert '.cm-line.cm-lee-change.lee-change-hot' in CSS and '.lee-change-pop' in CSS

    pop = JS[JS.index('function showChangePopup'):JS.index('async function copyChangeHunk')]
    # The hunk, not the file: every button acts on the one hunk the click resolved to.
    assert 'hunkAtLine(line)' in pop and 'Commit this change' in pop
    for act in ('prev', 'next', 'revert', 'diff', 'copy', 'commit'):
        assert f'data-act="{act}"' in pop
    assert 'changePopupBody(h)' in pop and "e.key === 'Escape'" in pop
    # An untracked file has no committed version of any hunk, so it falls back to the file diff.
    assert 'if (at < 0) return showGitFileDiff' in pop


def test_one_change_can_be_reverted_or_committed_without_touching_the_rest_of_the_file():
    """Both operations are one server-built patch and nothing else -- no patch text is assembled
    here, and neither touches the file without first settling what is unsaved in the editor."""
    revert = JS[JS.index('async function revertChangeHunk'):JS.index('async function commitChangeHunk')]
    assert "gitDo('apply_patch', {patch: h.patch, staged: false, reverse: true})" in revert
    assert "$('.lee-tab.active.dirty') && !await saveTab(true)" in revert
    assert 'confirmDialog(' in revert and 'refreshFileChanges(path, true)' in revert

    commit = JS[JS.index('async function commitChangeHunk'):JS.index('function gitChangeRow')]
    assert "gitDo('apply_patch', {patch: h.patch, staged: true, reverse: false})" in commit
    assert "gitDo('commit', {message: text})" in commit
    # Git commits the index, so anything already staged would ride along. That is said out loud
    # rather than silently widening a one-hunk commit or silently unstaging someone's work.
    assert "filter(c => c.staged && c.path !== path)" in commit
    assert 'commit anyway' in commit

    refresh = JS[JS.index('async function refreshFileChanges'):JS.index('async function revertChangeHunk')]
    assert 'LeeCM.setDoc(v, st.text)' in refresh and 'LeeCM.setChangedLines(v, git.ranges' in refresh

    diff = JS[JS.index('function tokenDiffHtml'):JS.index('function closeChangePopup')]
    assert '<mark>' in diff, 'the words the new version dropped are marked inside the old line'
    assert '.lee-change-old mark' in CSS


def test_left_activity_bar_has_a_pycharm_style_file_structure(tmp_path):
    html = to_xml(_shell(Workspace(roots=[tmp_path]), TerminalGate()))
    assert 'data-left="symbols"' in html and 'id="symbols"' in html
    assert 'async function leeSymbols()' in JS and "api('/outline?path='" in JS
    assert '.lee-symbol-row' in CSS and '.lee-left.left-symbols' in CSS


def test_a_hit_in_a_notebook_opens_the_cell_that_holds_it():
    """A notebook has no single file editor, so a location in one has to name a cell.

    Its `line` is a line of the .ipynb JSON, which is true and unopenable: the column of
    per-cell editors each start again at line 1. So the server places a notebook hit in a cell
    and the three places that navigate -- go-to-definition, the search box and the structure
    panel -- all carry that through `openLocation` to the consumer in `mountTab`.
    """
    open_at = JS[JS.index('function openLocation'):JS.index('async function stopCell')]
    assert 'hit.cell_line' in open_at and 'cellId: hit.cell' in open_at
    assert 'cell_index' in open_at, 'a notebook before nbformat 4.5 has no cell ids, only order'
    assert 'is in no cell' in open_at, 'an unplaceable notebook hit says so instead of scrolling somewhere'

    landing = JS[JS.index('if (lee.pendingLocation'):JS.index('refreshKernelPill();')]
    assert '(loc.cellId || loc.cellIndex >= 0)' in landing
    assert 'loc.cellIndex < lee.cells.length) i = loc.cellIndex' in landing
    assert 'selectCell(i)' in landing and 'ensureCellMounted(i)' in landing and 'jumpToLine(loc.line)' in landing
    # The debug decorations belong to the debugger. A search result is somewhere to go, not
    # the line a paused kernel is executing.
    assert 'if (loc.debug) {' in landing

    outline = JS[JS.index('async function leeSymbols()'):JS.index('window.leeSymbols')]
    assert "lee.kind !== 'notebook'" in outline, 'a notebook has structure worth outlining'
    assert 'data-cell-index=' in outline and 'data-cell-line=' in outline
    assert 'cell_line: +row.dataset.cellLine' in outline


def test_agent_model_and_reasoning_live_below_the_growing_prompt(tmp_path):
    html = to_xml(_shell(Workspace(roots=[tmp_path]), TerminalGate()))
    assert html.index('id="agentprompt"') < html.index('id="agentmodel"')
    assert 'id="agentreasoning"' in html and 'lee-composer-footer' in html
    composer = JS[JS.index('function initAgentComposer'):JS.index('async function sendAgentCommand')]
    assert "input.style.height = 'auto'" in composer and "localStorage.getItem('lee-agent-reasoning')" in composer
    assert "&reasoning=" in JS


def test_agent_panel_sends_the_open_notebook_cells_as_context():
    from inspect import getsource
    from leela.app import ide_app
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
    from leela.app import ide_app
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
    from leela.app import ide_app
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
    for view in ('Jobs', 'Add', 'Build', 'Runs', 'Environment'):
        assert view in block
    for op in ('run workflow', 'edit in builder', 'from gheasy config', 'Dockerfile'):
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


def test_the_builder_is_a_form_rendered_from_the_servers_vocabulary():
    """The answer to "I am not good at Actions": choose, do not type.

    The form is generated from `/workflows/presets`, so the set of decisions a workflow has
    is defined once in Python. Hard-coding any of it here in JS would be the bug.
    """
    block = JS[JS.index('const bldUI ='):JS.index('// -- the release pipeline')]
    assert "api('/workflows/presets')" in block, 'the vocabulary is fetched, not hard-coded'
    assert 'bldTrigger' in block and 'bldOption' in block and 'bldJob' in block
    assert "o.type === 'flag'" in block and "o.type === 'lines'" in block
    assert "op: 'build'" in block and "op: 'write_spec'" in block
    assert 'scheduleBuild' in block, 'the YAML follows the form as it changes'
    assert 'data-needs' in block, 'jobs wire to each other by needs'
    assert 'The file has been edited' in block, 'a hand edit is not overwritten silently'
    assert '.lee-bld-job' in CSS and '.lee-bld-trigger' in CSS


def test_a_failure_names_the_package_and_opens_your_copy_of_it():
    block = JS[JS.index('function blameRow'):JS.index('function relStepRow')]
    assert 'your checkout' in block and 'installed copy' in block
    assert 'data-blame-open' in block and 'leeOpenFile' in JS
    assert 'scrollIntoView: true' in JS, 'landing on a line you cannot see is not landing on it'
    assert '.lee-blame' in CSS


def test_the_deploy_panel_shows_the_servers_and_tunnels_it_deploys_onto():
    block = JS[JS.index('function depInfraRows'):JS.index('function renderDeployPanel')]
    assert "api('/infra')" in block and "api('/infra/records?zone=" in block and "api('/stack'" in block
    for word in ('servers', 'tunnels', 'zones'):
        assert word in block
    assert 'data-server-del' in block and 'data-tunnel-del' in block
    assert 'delete this server' in block and 'confirmDialog' in JS
    assert 'edits in your checkout are not what runs' in block, 'the shadowed package warning'
    assert '.lee-inf-row' in CSS and '.lee-pkg.shadowed' in CSS


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


def test_blame_is_reachable_from_anywhere_and_groups_a_notebook_into_cells():
    """Two separate things it needs to be useful.

    Reach: it was only ever on a changed-file row, so a clean file -- almost every file --
    had no way in at all. It is an action now, which means a chord, the palette, and the
    four context menus that name it.

    Shape: a notebook blamed as text is a list of `"source": [`, so the cell view shows the
    decoded source with per-line attribution inside a per-cell summary.
    """
    block = JS[JS.index('function blameRelative'):JS.index('async function showGitBlame')]
    assert 'function blameSelectionRange' in block, 'a text file blames what you selected'
    assert 'function blameCells' in block and 'lee-blame-bar' in block
    assert 'blameHue' in block, 'a cell made of three commits reads as three bands'
    assert 'git_blame:' in JS and 'function leeBlame' in JS, 'it is a dispatchable action'
    assert "Key('git_blame'" in read('leela/core/keys.py'), 'so it has a chord and a palette entry'
    assert read('leela/blocks/keys/menus.py').count("S('git_blame')") >= 4, 'file, editor, cell and tab'
    assert 'blame the whole file' in JS, 'the range answer is one button from the whole one'
    assert '.lee-blame-cell' in CSS and '.lee-blame-legend' in CSS


def test_the_drive_panel_shows_the_call_it_is_about_to_make():
    """A button you cannot read is not a diagnostic.

    The panel is the alternative to the deploy script, so it has to explain itself: the
    package, what the call does, and the snippet with this project's values already in it.
    """
    block = JS[JS.index('const drvUI ='):JS.index('async function renderGitPanel')]
    assert "api('/drive'" in block and "post('/drive/action'" in block
    assert 'lee-drv-code' in block and '} the call</summary>' in block
    assert 'lee-drv-pkg' in block, 'each part says which package it drives'
    assert 'sets ' in block and 'writes ' in block, 'what a call leaves for the next one'
    assert "openReleaseTerm(drvUI.data.root, 'drive')" in block
    assert "data_left='drive'" in SERVER and '.lee-left.left-drive' in CSS
    assert '.lee-drv-part.state-failed' in CSS


def test_both_pipelines_share_one_terminal_socket():
    "A release and a deploy differ in what they run and in nothing else, including this."
    assert "url: kind === 'drive' ? '/drive/ws' : '/pipeline/ws'" in JS
    assert "openReleaseTerm(root = '', kind = 'release')" in JS
    # one implementation of the socket, three kinds over it
    assert 'def pipeline_socket(' in read('leela/core/web.py')
    assert SERVER.count("pipeline_socket(app, '") == 2, 'both blocks register through it'


def test_the_environment_view_hides_secret_values_in_the_browser_too():
    "The server never sends one; the client must not invent a place to show one either."
    block = JS[JS.index('function wfEnvRows'):JS.index('function renderWorkflowsPanel')]
    assert "'••••••••'" in block or '••••••••' in block
    assert 'e.secret ?' in block, 'a secret and a variable are drawn differently'


def test_the_release_pipeline_runs_steps_and_shows_them_in_a_terminal():
    block = JS[JS.index('const REL_MARK'):JS.index('async function renderGitPanel')]
    assert "api('/releases'" in block and "post('/releases/action'" in block
    assert 'function openReleaseTerm' in JS and "'/pipeline/ws'" in JS
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


def test_a_failed_git_action_opens_the_log_it_just_wrote():
    """"See logs" has to end with the reader seeing the log.

    The detail line exists because the toast cannot hold it, so sending someone to find it --
    past a dock showing something else and a filter set an hour ago for something unrelated --
    loses the one thing worth keeping. Verified in chromium: from the dock on `term` with the
    `runs` filter set, a refused checkout lands on the log row that names the files.
    """
    show = JS[JS.index('function showLog('):JS.index('function firstLine(')]
    assert "if (lee.logFilter && lee.logFilter !== source) leeLogFilter('')" in show, \
        'a filter that would hide the new row is cleared'
    assert "leeDock('logs')" in show
    failed = JS[JS.index('async function gitDo('):JS.index('function gitOperationBanner')]
    assert failed.index("leeLog('git'") < failed.index("showLog('git')"), 'written, then shown'
    assert 'status(`git ${name} failed — ${firstLine(detail)}`' in failed, \
        "git's first line is usually the whole story, so the toast carries it"
    assert 'see logs' not in JS, 'nothing tells you to go and look any more'


def test_the_toast_reports_gits_first_line_without_the_exception_class():
    "`GitError: error: The following untracked...` reads as noise before it reads as a reason."
    fn = JS[JS.index('function firstLine('):JS.index('function leeLogFilter(')]
    assert "replace(/^\\w*Error:\\s*/, '')" in fn, 'the class name is not the message'
    assert "split('\\n').find(x => x.trim())" in fn, 'the first line that says anything'
    assert 'max - 1' in fn and '…' in fn, 'and it is clipped for a status line'


def test_a_branch_change_reaches_every_surface_that_was_derived_from_it():
    """The pill and the tree badges were repainted by the poll; nothing else was.

    So a checkout -- from the panel, from lazygit in the terminal, or from the agent -- left
    the editor's change marks describing the branch you came from, History and Branches
    showing what they showed before, and the release panel counting against the old tag.
    """
    sig = JS[JS.index('function gitSignature('):JS.index('function noticeGitState(')]
    assert 'd.head' in sig, 'a commit moves nothing else: branch, counts and files all read the same'
    assert 'd.branch' in sig and 'd.ahead' in sig and "(d.operation || {}).active" in sig
    notice = JS[JS.index('function noticeGitState('):JS.index('function gitChanged()')]
    assert 'if (had && had !== sig) gitChanged()' in notice, 'the first poll is not a change'
    fan = JS[JS.index('function gitChanged()'):JS.index('window.leeGitChanged')]
    assert 'refreshOpenGitMarks()' in fan, 'the open file or notebook is re-marked'
    assert 'gitUI.snapshot = null; gitUI.history = []' in fan, 'History and Branches reload'
    assert 'leeReleases()' in fan and 'leeDeploys()' in fan
    # The poll that already asks git every five seconds is what notices; nothing new is added.
    pills = JS[JS.index('async function refreshProjectPills'):JS.index('async function leeCwd')]
    assert 'noticeGitState(d)' in pills
    assert 'setInterval(refreshProjectPills, 5000)' in JS


def test_our_own_git_action_updates_at_once_without_the_poll_repeating_it():
    done = JS[JS.index('async function gitDo('):JS.index('function gitOperationBanner')]
    assert "lee.gitSignature = ''; gitChanged();" in done, \
        'immediately, and the next poll does not treat our own mutation as news'


def test_the_merge_button_always_answers_instead_of_being_disabled():
    """"I clicked merge and nothing happened" was a disabled button.

    It was disabled whenever `clean` was false, and `clean` counted untracked files -- so a
    repository holding a stray `uv.lock` could never merge, and the control that would have
    explained that was the one being switched off.
    """
    fn = JS[JS.index('async function showMergePreview('):JS.index('async function showRebasePreview(')]
    assert 'data-merge>' in fn and "data-merge ${" not in fn, 'the button is never disabled'
    assert "if (blocked) return status(`cannot merge — ${blocked}`, 'err')" in fn, \
        'a press that cannot proceed says why'
    assert 'commit or stash ${p.dirty.length} changed file' in fn, 'and names the real blocker'
    assert 'p.dirty.map(esc).join' in fn, 'listing the tracked files, not a count of everything'
    rb = JS[JS.index('async function showRebasePreview('):JS.index('async function branchActions(')]
    assert 'data-rebase>' in rb and "data-rebase ${" not in rb
    assert "if (rbBlocked) return status(`cannot rebase — ${rbBlocked}`, 'err')" in rb


def test_the_conflict_resolver_is_three_panes_over_gits_own_markers():
    """Reading the conflicts out of the markers Git wrote, not re-diffing the three versions.

    The markers are Git's own account of what it could not decide, so `scanConflicts` is the
    load-bearing part: an unterminated marker must stay text, and the sides must be
    reconstructable from the blocks it finds.
    """
    block = JS[JS.index('const CONFLICT_OPEN'):JS.index('// Blame, reachable from wherever')]
    assert 'function scanConflicts' in block and 'function conflictSide' in block
    assert 'if (block.end < 0) continue' in block, 'an unclosed marker is text, not a conflict'
    assert "for (const key of ['base', 'ours', 'theirs'])" in block
    assert 'data-pane="${key}"' in block and "pane('result', 'result', 'editable')" in block
    assert 'onChange:' in block, 'the result pane is the editable one'
    for control in ('data-take="ours"', 'data-take="theirs"', 'data-take="both"',
                    'data-nav="prev"', 'data-nav="next"', 'data-base-toggle', 'data-resolve'):
        assert control in block, control
    # Dispatching inside CodeMirror's own update is not allowed, and a button's setDoc must not
    # come back round as a user edit.
    assert 'setTimeout(() => refresh(text, false), 0)' in block
    assert 'programmatic = true' in block
    assert "choice: 'resolved'" in block, 'the assembled text is what gets staged'
    assert 'showWholeSideConflict' in block, 'delete/modify has no lines to work through'
    assert '.lee-merge3-panes' in CSS and '.cm-line.cm-lee-change-conflict-active' in CSS


def test_the_panel_explains_a_dirtying_filter_and_offers_the_way_back():
    block = JS[JS.index('function gitFilterBanner'):JS.index('function gitSummary')]
    assert 'f.ok !== false' in block and 'f.explain' in block
    assert 'may not stay staged' in block
    assert 'data-git-undo' in block and 'point.describe' in block
    assert 'gitFilterBanner(d) + gitUndoBanner(d)' in JS, 'both sit with the file list'
    assert '.lee-git-undo' in CSS


def test_a_mutation_reports_what_it_left_behind_rather_than_how_long_it_took():
    block = JS[JS.index('async function gitDo'):JS.index('function gitOperationBanner')]
    assert 'd.outcome?.summary' in block
    assert "d.outcome?.note ? ' — ' + d.outcome.note : ''" in block, 'one call, so neither is dropped'


def test_choosing_a_folder_reloads_every_project_panel_not_just_git():
    """The backend answering correctly is half of it: the open panel has to ask again.

    `gitChanged` reloads what depends on the branch. Choosing another folder changes which
    project the panels are *about*, so drive and workflows are in this one too, and every
    cached answer is dropped whether or not its panel is showing.
    """
    block = JS[JS.index('function projectChanged'):JS.index('async function refreshProjectPills')]
    assert 'gitUI.snapshot = null' in block and 'relUI.data = drvUI.data = null' in block
    assert "Object.assign(wfUI, {data: null" in block and "Object.assign(depUI, {data: null" in block
    assert "left-drive')) leeDrive()" in block and "left-workflows')) leeWorkflows()" in block
    # And the folder switch calls it instead of refreshing the Git panel alone.
    activate = JS[JS.index("await post('/workspace/activate'"):]
    assert 'projectChanged();' in activate[:600]
    assert 'renderGitPanel();' not in activate[:600], 'superseded by projectChanged'


def test_search_leads_with_all_and_walks_its_modes_from_a_rail():
    """`all` ranks every backend together, so it is the mode that answers without you first
    having to know which store the thing you half-remember is in -- hence the default, and
    hence first in the order Tab walks."""
    modes = JS[JS.index('const SEARCH_MODES'):JS.index('async function codeSearch')]
    assert modes.index("['all'") < modes.index("['rg'") < modes.index("['context'")
    block = JS[JS.index('async function codeSearch'):JS.index('function cursorWord')]
    assert "localStorage.getItem('lee-search-mode') || 'all'" in block
    assert "if (!SEARCH_MODES.some(([id]) => id === mode)) mode = 'all'" in block, 'a stale mode falls back'
    # Tab cycles the modes instead of the focus; the dialog traps Tab anyway.
    assert "e.key === 'Tab'" in block and 'cycleMode(e.shiftKey ? -1 : 1)' in block
    assert 'const cycleMode = step =>' in block and '% SEARCH_MODES.length' in block, 'and it wraps'
    # A count that has not been measured must not read as nought.
    assert "counts[id] == null ? '' : counts[id]" in block
    assert 'counts[mode] = hits.length' in block
    assert '.lee-searchrail' in CSS and '.lee-searchrail-mode.active' in CSS
    assert 'lee-searchmodes' not in block, 'the old horizontal segbar is gone, not just hidden'


def test_all_streams_its_backends_into_stable_slots():
    """rg answers in tens of milliseconds and the embedding leg in seconds, so `all` fills in as
    each reports rather than waiting for the slowest. The slots are stable on purpose: a list
    that re-ranked on every arrival would reshuffle under the cursor while it was being read."""
    block = JS[JS.index('const streamAll'):JS.index('let timer, liveStream')]
    assert "new EventSource('/search/stream?q='" in block
    assert "for (const leg of d.legs || []) slots.set(leg, [])" in block, 'order fixed once, up front'
    # A hit a later leg finds again joins the row that already exists rather than appearing twice.
    assert 'already.sources = [...new Set([...(already.sources || []), d.leg])]' in block
    assert 'if (sel >= hits.length)' in block, 'the selection survives a list that grew at the end'
    # A stale stream is closed rather than left running for a question nobody is asking.
    assert 'liveStream = es' in block
    search = JS[JS.index('let timer, liveStream'):JS.index('input.addEventListener(\'input\', search)')]
    assert 'if (liveStream) { try { liveStream.close(); }' in search
    assert "if (mode === 'all')" in search and 'return streamAll(q, seq)' in search


def test_the_search_stream_route_fans_its_legs_out_concurrently():
    from tests.assets import read
    src = read('leela/blocks/search/app.py')
    assert 'asyncio.as_completed(tasks)' in src, 'completion order is the entire point'
    assert 'off_loop(ctx.search.leg, name' in src, 'each leg on its own worker thread'
    assert 'await req.is_disconnected()' in src and 't.cancel()' in src
    assert "sse('leg'" in src and "sse('done'" in src and "sse('start'" in src


def test_a_pdf_opens_in_the_browsers_own_viewer(tmp_path):
    """We are in a browser, so the viewer already exists -- the feature is handing the bytes over.

    A PDF was refused outright by the texty check, so it could not be opened at all. It is its own
    tab kind rather than a text tab with binary in it, so nothing downstream tries to edit, diff or
    lint it.
    """
    from starlette.testclient import TestClient
    from leela.app import ide_app
    pdf = tmp_path/'paper.pdf'
    pdf.write_bytes(b'%PDF-1.4\ntrailer\n%%EOF\n')
    ws = Workspace(roots=[tmp_path])
    tab = ws.open(pdf)
    assert tab.kind == 'pdf' and tab.private_kernel is False

    with TestClient(ide_app(ws)) as c:
        st = c.get('/tab/state', params={'path': str(pdf)}).json()
        assert st['kind'] == 'pdf' and 'text' not in st, 'the bytes are fetched by the viewer, not inlined'

        r = c.get('/file/raw', params={'path': str(pdf)})
        assert r.status_code == 200 and r.content.startswith(b'%PDF')
        assert r.headers['content-type'] == 'application/pdf'
        assert 'inline' in r.headers['content-disposition'], 'inline, or the browser downloads it'
        assert r.headers['x-content-type-options'] == 'nosniff'

        down = c.get('/file/raw', params={'path': str(pdf), 'download': 'true'})
        assert 'attachment' in down.headers['content-disposition']

        # An allowlist, because this route returns bytes a browser is about to render.
        (tmp_path/'x.py').write_text('x = 1\n')
        assert c.get('/file/raw', params={'path': str(tmp_path/'x.py')}).json()['error']
        assert c.get('/file/raw', params={'path': '/etc/passwd'}).json()['error']


def test_markdown_renders_beside_its_source_without_giving_up_the_editor(tmp_path):
    """Rendered, split and edit are ways of *looking* at the file, not different kinds of tab.

    The editor is hidden by CSS and never unmounted, which is what keeps saving, autosave, blame
    and the change gutter working while the rendering is on screen.
    """
    mount = JS[JS.index('async function mountFile'):JS.index('async function mountSecondary')]
    assert "const isMd = (st.lang || '') === 'markdown'" in mount
    assert "localStorage.getItem('lee-md-view') || 'split'" in mount
    assert "['edit', 'split', 'rendered']" in mount
    assert "renderMarkdown($('#mdpreview'), txt)" in mount, 'the preview follows the buffer'
    assert 'id="filecm"' in mount, 'and the editor is mounted in every view'
    # Hidden, not unmounted -- the distinction the whole approach rests on.
    assert '.lee-md-stage[data-view="rendered"] .lee-cm { display: none; }' in CSS
    assert '.lee-md-stage[data-view="edit"] .lee-md-preview { display: none; }' in CSS
    # CodeMirror measures wrongly while display:none, so it re-measures on the way back.
    assert 'requestAnimationFrame(() => LeeCM.focus(v))' in mount

    # The PDF viewer shares `.lee-doc-*` with this, which is the only reason it is asserted here;
    # its own behaviour, including the named URL, belongs to
    # `test_a_pdf_is_served_under_its_own_name_and_fills_the_pane`.
    pdf = JS[JS.index('function mountPdf'):JS.index('async function mountFile')]
    assert "'?path='" in pdf and 'lee-pdf' in pdf
    assert 'download' in pdf and 'open externally' in pdf
    assert '.lee-pdf' in CSS and '.lee-doc-body' in CSS
    save = JS[JS.index('async function saveTab'):JS.index('async function saveAllTabs')]
    assert "lee.kind === 'pdf'" in save, 'a PDF tab has no editor to read a document out of'


def test_a_markdown_file_gets_the_same_change_hunks_as_code(tmp_path):
    "The gutter popup is language-agnostic; this pins that markdown really does feed it."
    import subprocess
    def git(*a): subprocess.run(['git', *a], cwd=tmp_path, check=True, capture_output=True)
    git('init', '-q', '-b', 'main', '.')
    git('config', 'user.email', 'tests@leela.local'); git('config', 'user.name', 'Leela tests')
    (tmp_path/'readme.md').write_text('# Title\n\nfirst para\n')
    git('add', '.'); git('commit', '-qm', 'init')
    (tmp_path/'readme.md').write_text('# Title\n\nfirst para edited\n')

    from leela.blocks.git.git import GitRepo
    fc = GitRepo.at(tmp_path).file_changes('readme.md')
    assert fc['ranges'] == [{'from': 3, 'to': 3, 'kind': 'modified'}]
    hunk = fc['hunks'][0]
    assert hunk['old'] == 'first para\n' and 'first para edited' in hunk['new']
    assert hunk['patch'].startswith('diff --git'), 'so revert and commit-this-change work on prose too'


def test_a_bar_with_a_control_at_its_right_edge_clears_the_modal_corner_buttons():
    """The modal's close and expand sit *over* the top-right corner, absolutely positioned.

    `sync` used to be pushed left by the mode buttons between it and the input; the moment those
    became a rail it slid under the ×. Reserved on the bar rather than by nudging `sync`, so the
    next control added to the end of that row does not rediscover the collision.
    """
    import re
    close_r = re.search(r'\.lee-modal-close \{ right: (\d+)px', CSS)
    expand_r = re.search(r'\.lee-modal-expand \{ right: (\d+)px', CSS)
    bar = re.search(r'\.lee-searchbar \{[^}]*padding-right: (\d+)px', CSS)
    assert close_r and expand_r and bar, 'the three rules this depends on still exist'
    # 24px wide each, so the far edge of `expand` is its right offset plus its width.
    assert int(bar.group(1)) >= int(expand_r.group(1)) + 24


# ---------------------------------------------------------------- markdown, read as a diff
# The rendered reading of a Markdown diff turns on one question: which element did each
# source block become? These tests hold both halves of the answer -- the records the server
# hands over, and the browser's refusal to draw anything when they do not line up.

def _md_render(text):
    "One document through the real renderer, exactly as the browser asks for it."
    from starlette.testclient import TestClient
    from leela.app import ide_app
    with TestClient(ide_app(Workspace(roots=[]))) as client:
        r = client.post('/markdown/render', json={'text': text, 'allow_raw': False})
    assert r.status_code == 200, r.text
    return r.json()['html']


def _md_carriers(html):
    "The top-level nodes the browser counts as block carriers, mirroring `markdownCarriers`."
    import fast5ever
    out = []
    for n in fast5ever.parse_fragment(html).children:
        if isinstance(n, fast5ever.Text): continue
        if isinstance(n, fast5ever.Element) and n.name == 'section' \
           and 'footnotes' in (n.attrs.get('class') or ''): continue
        out.append(n.name)
    return out


def _md_align(html, blocks):
    """`alignMarkdownBlocks`, in Python: the pairs, or None where the browser draws nothing.

    Kept in the same shape as the browser's copy on purpose -- it is the rule under test, and
    node is not available here to run the original.
    """
    nodes, pairs, at = _md_carriers(html), [], 0
    for b in blocks:
        # A removed block is answered before `renders`, exactly as the browser does it: it has
        # source lines and a type, but no element in the document being read.
        if b.get('status') == 'removed': pairs.append((b, None)); continue
        if not b['renders']: continue
        if at >= len(nodes): return None
        node = nodes[at]; at += 1
        if b['tags'] and node not in b['tags']: return None
        pairs.append((b, node))
    return pairs if at == len(nodes) else None


README = '''# rishi

<!-- a note to the reader -->

Prose with `code`, a [link][home] and a footnote[^1].

```bash
uv add rishi
```

## Install

- one
- two

| a | b |
|---|---|
| 1 | 2 |

> a quotation

---

![a picture](p.png)

[home]: https://example.com
[^1]: the note
'''


def test_every_markdown_block_maps_to_the_element_it_rendered_as():
    from leela.core.markdown import md_blocks
    blocks = md_blocks(README)
    pairs = _md_align(_md_render(README), blocks)
    assert pairs is not None, 'a rendered diff of an ordinary README can be marked'
    assert [n for _, n in pairs] == ['h1', '#comment', 'p', 'pre', 'h2', 'ul', 'table',
                                     'blockquote', 'hr', 'figure']
    # The two definitions hold source lines but render nothing, so they consume no element.
    assert [b['type'] for b in blocks if not b['renders']] == ['link_ref', 'footnote_def']
    fence = next(b for b in blocks if b['type'] == 'code_block')
    assert (fence['from'], fence['to']) == (7, 9) and fence['code'] == 'uv add rishi\n'


def test_a_block_that_cannot_be_placed_costs_the_bars_rather_than_moving_them():
    "One raw HTML block that renders as two elements shifts every block after it."
    from leela.core.markdown import md_blocks
    doc = 'para one\n\n<p>a</p><p>b</p>\n\n## heading\n'
    assert _md_align(_md_render(doc), md_blocks(doc)) is None
    assert _md_align('<p>only</p>', md_blocks('para\n\npara two\n')) is None, 'a block with no element'
    assert _md_align('<p>a</p><p>b</p>', md_blocks('para\n')) is None, 'an element no block claimed'


def test_a_markdown_diff_pairs_blocks_and_refuses_to_pair_across_types():
    from leela.core.markdown import md_block_diff
    old = '# t\n\nold prose\n\n```sh\nold cmd\n```\n\ngone entirely\n'
    new = '# t\n\nnew prose\n\n```sh\nnew cmd\n```\n\n## Install\n\nfresh\n'
    d = md_block_diff(old, new)
    rows = [(r['status'], r['type']) for r in d['blocks']]
    assert rows[:3] == [('equal', 'heading'), ('modified', 'paragraph'), ('modified', 'code_block')]
    # The new heading is not the old closing paragraph at the same offset. Blocks pair by
    # construct, so the heading is new and the paragraph is matched with the paragraph.
    assert ('modified', 'heading') not in rows, 'a paragraph did not become a heading'
    assert ('added', 'heading') in rows
    assert (d['blocks'][-1]['status'], d['blocks'][-1]['old']) == ('modified', 'gone entirely')
    fence = next(r for r in d['blocks'] if r['type'] == 'code_block')
    assert fence['old_code'] == 'old cmd\n' and fence['code'] == 'new cmd\n'
    assert d['changed'] and (d['added'], d['removed']) == (5, 3)


def test_the_diff_records_still_line_up_with_the_document_being_read():
    """The records the rendered view actually receives, against the rendering it actually gets.

    A removed block is interleaved among them and has no element, so this is where an off-by-one
    would show up: the paragraph after a deletion must still pair with its own paragraph.
    """
    from leela.core.markdown import md_block_diff
    old = README.replace('## Install', 'A paragraph that this change deletes.\n\n## Setup')
    d = md_block_diff(old, README)
    pairs = _md_align(_md_render(README), d['blocks'])
    assert pairs is not None
    assert [n for _, n in pairs if n] == ['h1', '#comment', 'p', 'pre', 'h2', 'ul', 'table',
                                          'blockquote', 'hr', 'figure']
    heading = next(b for b, n in pairs if n == 'h2')
    assert heading['status'] == 'modified' and heading['old'] == '## Setup'
    gone = [b for b in d['blocks'] if b['status'] == 'removed']
    assert [b['source'] for b in gone] == ['A paragraph that this change deletes.']


def test_a_line_range_from_git_lands_on_the_block_that_holds_it():
    from leela.core.markdown import md_blocks, md_change_kinds
    blocks = md_blocks('# t\n\nprose\n\n```sh\na\nb\n```\n')
    # Git reports a pure deletion at the line that closed over it, which is inside the fence.
    kinds = md_change_kinds(blocks, [{'from': 3, 'to': 3, 'kind': 'added'},
                                     {'from': 6, 'to': 6, 'kind': 'deleted'}])
    assert kinds == [None, 'added', 'removed']
    both = md_change_kinds(blocks, [{'from': 1, 'to': 8, 'kind': 'modified'}])
    assert both == ['modified', 'modified', 'modified']
    # And the browser gets both answers from one request, over the route it actually calls.
    from starlette.testclient import TestClient
    from leela.app import ide_app
    with TestClient(ide_app(Workspace(roots=[]))) as client:
        got = client.post('/markdown/blocks', json={'text': '# t\n\nprose\n',
                                                    'ranges': [{'from': 3, 'to': 3, 'kind': 'added'}]}).json()
        diff = client.post('/markdown/diff', json={'left': '# t\n', 'right': '# t\n\nnew\n'}).json()
    assert got['kinds'] == [None, 'added'] and got['blocks'][1]['tags'] == ['p']
    assert [b['status'] for b in diff['blocks']] == ['equal', 'added']


def test_a_markdown_diff_reads_as_a_rendering_beside_unified_and_split():
    tab = JS[JS.index('async function activateGitDiffTab'):JS.index('function gitDiffNotebookHtml')]
    assert 'data-diff-view="unified"' in tab and 'data-diff-view="split"' in tab, 'a third reading, not a replacement'
    assert 'isMarkdownPath(data.path) ?' in tab and 'data-diff-view="rendered">rendered' in tab
    assert "data.view === 'rendered' && isMarkdownPath(data.path)) await mountMarkdownDiff(body, data)" in tab
    block = JS[JS.index('const MARKDOWN_PATH'):JS.index('async function leeOpenFile')]
    assert "post('/markdown/diff', {left: data.left || '', right: data.right || ''})" in block
    # One renderer, and repository Markdown stays untrusted in it.
    assert "renderMarkdown(doc, data.right || '', false, () => paintMarkdownDiff(doc, rows))" in block
    assert 'allow_raw: true' not in block and "'/markdown/render'" not in block
    assert '.lee-md-diff-doc' in CSS and '.lee-md-change::before' in CSS
    for kind in ('added', 'modified', 'code'):
        assert f'.lee-md-change[data-change="{kind}"]::before' in CSS


def test_the_annotation_sees_the_fragment_before_the_code_upgrade_replaces_it():
    render = JS[JS.index('function renderMarkdown('):JS.index('async function api(')]
    assert 'onRender = null' in render
    assert render.index('onRender(el)') < render.index('enhanceCodeBlocks(el)'), 'the pre is still a pre'
    assert 'try { onRender(el); } catch' in render, 'a mapping bug cannot cost the reader the rendering'


def test_a_block_that_cannot_be_matched_leaves_the_rendering_unmarked_and_says_so():
    block = JS[JS.index('function alignMarkdownBlocks'):JS.index('function markdownCodeDiffHtml')]
    assert 'if (!row.renders) continue' in block, 'a definition consumes no element'
    assert 'if (at >= tags.length) return null' in block, 'a block with no element voids the mapping'
    assert 'if (want.length && !want.includes(tag)) return null' in block, 'and so does the wrong element'
    assert 'return at === tags.length ? pairs : null' in block, 'and so does an element nobody claimed'
    # Positions rather than nodes, because the code-block upgrade swaps each `<pre>` afterwards.
    assert 'pairs.push({row, at: at - 1})' in block
    paint = JS[JS.index('function paintMarkdownDiff'):JS.index('async function mountMarkdownDiff')]
    assert 'if (!pairs) { if (note) note.hidden = false; return false; }' in paint
    assert 'data-md-diff-note' in JS and '.lee-md-diff-note' in CSS
    carriers = JS[JS.index('function markdownCarriers'):JS.index('/* Which element each block became')]
    assert "n.nodeType === 8" in carriers, 'a comment is a carrier, so it cannot shift the sequence'
    assert "classList.contains('footnotes')" in carriers


def test_a_changed_code_fence_shows_its_line_diff_inside_the_rendering():
    block = JS[JS.index('function markdownCodeDiffHtml'):JS.index('// Pink for text that changed')]
    assert 'dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1' in block, 'lines are matched, not zipped'
    assert 'tokenDiffHtml(r.old, twin.now)' in block and 'tokenDiffHtml(r.now, prior.old)' in block
    assert 'a.length > 600 || b.length > 600' in block, 'a huge fence falls back rather than allocating'
    paint = JS[JS.index('function paintMarkdownDiff'):JS.index('async function mountMarkdownDiff')]
    assert "row.type === 'code_block'" in paint and "node.tagName === 'PRE'" in paint
    assert 'node.replaceWith(host)' in paint
    # The code upgrade replaces every `pre > code` just after this runs, so a fence that is
    # wholly new keeps its rendering inside a wrapper the upgrade cannot take away.
    assert "host.className = 'lee-md-code-host'; host.appendChild(node)" in paint
    assert '.lee-md-code-host' in CSS
    assert '.lee-md-code-line.del' in CSS and 'text-decoration: line-through' in CSS
    assert '.lee-md-code-line.add' in CSS


def test_text_that_was_removed_is_reported_on_the_block_that_closed_over_it():
    paint = JS[JS.index('function paintMarkdownDiff'):JS.index('async function mountMarkdownDiff')]
    assert "if (row.status === 'removed') { removed.push(row); continue; }" in paint
    assert 'host.dataset.removedAbove' in paint and 'last.dataset.removedBelow' in paint
    assert 'removed.map(r => r.source).join' in paint, 'the old text is readable without another request'
    assert '.lee-md-change[data-removed-above]::after' in CSS


def test_the_rendered_markdown_pane_carries_the_change_marks_of_the_gutter_beside_it():
    """The file's own preview places `/git/file` line ranges by block: the other route to the
    same question, and the one that has to survive a request landing after the render."""
    block = JS[JS.index('async function paintMarkdownFileChanges'):JS.index('async function leeOpenFile')]
    assert "post('/markdown/blocks', {text, ranges})" in block
    assert 'tags = markdownCarriers(el).map(markdownTagOf)' in block, 'tags read before the request goes out'
    assert 'if (!el.isConnected || el.dataset.markdown !== text) return' in block, 'a superseded render draws nothing'
    assert 'if (!pairs) return' in block
    mount = JS[JS.index('async function mountFile'):JS.index('async function mountSecondary')]
    assert 'paintMarkdownFileChanges(el, git.ranges || [])' in mount
    assert "if (isMd) renderMarkdown($('#mdpreview'), txt);" in mount, 'a keystroke re-render carries no marks'


def test_a_pdf_is_served_under_its_own_name_and_fills_the_pane(tmp_path):
    """Two things were wrong with the viewer: it was short, and every document was called "raw".

    The browser's PDF viewer titles itself from the last path segment, so the filename has to be
    in the path. That collides with FastHTML's static-asset catch-all, `/{fname:path}.{ext:static}`,
    which is registered ahead of every block and matches anything ending in a known extension --
    so the request 404ed from the static handler and never reached this route. A name without a dot
    worked, which is what made it look like the dot was at fault rather than the ordering.
    """
    from starlette.testclient import TestClient
    from leela.app import ide_app
    pdf = tmp_path/'2306.14881.pdf'; pdf.write_bytes(b'%PDF-1.4\n%%EOF\n')
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as c:
        named = c.get('/file/raw/2306.14881.pdf', params={'path': str(pdf)})
        assert named.status_code == 200 and named.headers['content-type'] == 'application/pdf'
        assert 'inline; filename="2306.14881.pdf"' in named.headers['content-disposition']
        assert c.get('/file/raw', params={'path': str(pdf)}).status_code == 200, 'both spellings'
        # Reordering must not have cost the real static route its own paths.
        assert c.get('/leestatic/lee-ide.css').status_code == 200
        # The name in the URL is decoration; it must never be a second way to ask for a file.
        assert c.get('/file/raw/passwd.pdf', params={'path': '/etc/passwd'}).status_code == 400

    mount = JS[JS.index('function mountPdf'):JS.index('async function mountFile')]
    assert "'/file/raw/' + encodeURIComponent(name) + '?path='" in mount
    assert 'class="lee-doc"' in mount, 'a column that fills the pane'
    # The height chain, every link of it, because one indefinite parent anywhere along it puts the
    # tab's own background back under the viewer. Flex rather than percentages: `.lee-editor` is a
    # *stretched* grid item, and stretched is not definite, so `height: 100%` collapsed to content.
    assert '.lee-editor:has(> .lee-doc) { display: flex; flex-direction: column;' in CSS
    assert '.lee-doc { display: flex; flex-direction: column; flex: 1 1 auto; min-height: 0; }' in CSS
    assert '.lee-doc-body { display: grid; flex: 1 1 auto; min-height: 0;' in CSS
    assert '.lee-pdf { width: 100%; height: 100%;' in CSS


def test_source_control_notices_an_edit_and_not_only_a_new_file():
    """The reported bug: the panel only refreshed when refreshed by hand.

    The poll was running the whole time. Its change signature carried the *count* of changed files,
    and the count is identical before and after almost every edit anyone actually makes -- typing in
    a file that was already modified moves no count, so nothing was ever considered to have
    changed. The per-file status codes and line counts are what differ, and `/git/info` was already
    returning them on every poll.
    """
    block = JS[JS.index('function gitSignature'):JS.index('function noticeGitState')]
    for field in ('c.path', 'c.index', 'c.worktree', 'staged_stat', 'unstaged_stat'):
        assert field in block, field
    assert '(d.changes || []).length' not in block, 'the count alone was the bug'

    # Saving already repaints the pills, so with the signature fixed a save refreshes at once
    # rather than waiting for the next poll.
    save = JS[JS.index('async function saveTab'):JS.index('async function saveAllTabs')]
    assert 'refreshProjectPills' in save
    pills = JS[JS.index('async function refreshProjectPills'):JS.index('function projectRepo')]
    assert 'noticeGitState(d)' in pills and "api('/git/info')" in pills
    assert 'setInterval(refreshProjectPills, 5000)' in JS, 'and an external change lands by poll'


def test_the_editor_pane_fills_its_stage_and_the_splitter_only_exists_when_split():
    """Measured in a browser, not reasoned about: on a 900px window the stage was 577px and the
    pane inside it 425px, with 151px of `.lee-editor-splitter` under it as bare background.

    The stage is a one-column grid whose rows were implicit and auto-sized, so a stretched grid
    item was not a filled one -- and the splitter is a child of that grid in every mode, so outside
    a split it claimed a row of its own. Invisible behind a CodeMirror that had scrolled to fill;
    plain behind a document viewer.
    """
    assert '.lee-editor-stage:not(.split) { grid-template-columns:minmax(0,1fr); ' \
           'grid-template-rows:minmax(0,1fr); }' in CSS
    assert '.lee-editor-stage:not(.split) .lee-editor-splitter { display:none; }' in CSS
    # `:not(.split)` is the right guard only because both classes go on together.
    split = JS[JS.index('function mountSecondary'):JS.index('function leeSplit')]
    assert "classList.add('split',`split-${direction}`)" in split
    # And the split modes still declare their own tracks, so scoping the rows above to non-split
    # cannot take a split layout with it.
    assert '.lee-editor-stage.split-vertical { grid-template-columns:' in CSS
    assert '.lee-editor-stage.split-horizontal { grid-template-rows:' in CSS
