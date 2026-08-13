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
