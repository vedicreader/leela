"The web IDE surface: project tools, movement, tabs, cells and workspaces."

from fasthtml.common import to_xml
from leela.blocks.term.term import TerminalGate
from leela.app import _shell
from leela.workspace import Workspace
from tests.assets import CSS, JS, SERVER, read
from pathlib import Path
from leela.blocks.runtime.kernels import bootstrap_src, project_python
ROOT = Path(__file__).resolve().parents[1]
from tests.assets import JS, CSS, EDITOR
from tests.assets import JS, CSS, SERVER, AGENT
import json
import re
from starlette.testclient import TestClient
from leela.app import ide_app
from tests.assets import JS
from tests.assets import JS, CSS
import asyncio
from unittest.mock import Mock
import pytest
from leela.blocks.runtime.kernels import RuntimeBroker, KernelPool
from leela.hub import LoopbackHostGuard, WorkspaceHub, WorkspaceSite, workspace_slug

def test_the_shell_paints_status_theme_and_layout():
    block = JS[JS.index('let statusTimer'):JS.index('/* ------------------------------------------------------------------ keymap')]
    assert "tone === 'busy' ? 0" in block and "el.classList.add('show')" in block
    assert "busyWords.test(msg)" in block and 'el.onclick = () =>' in block
    assert 'position: fixed; left: 50%; bottom: 34px' in CSS
    assert '.lee-status.busy::before' in CSS and '@keyframes lee-status-breathe' in CSS
    assert '@media (prefers-reduced-motion: reduce)' in CSS
    assert "const THEME_MODES = ['system', 'dark', 'light']" in JS
    assert "localStorage.getItem('lee-theme')" in JS
    assert ':root[data-theme="leela"][data-mode="light"]' in CSS
    assert ':root[data-theme="cursor"][data-mode="light"]' in CSS
    assert ':root:not([data-mode])' in CSS
    assert '.lee-app.mobile-left .lee-left' in CSS and '.lee-app.mobile-right .lee-right' in CSS
    assert "matchMedia('(max-width: 1100px)')" in JS
    assert '.lee-left, .lee-right { display: none; }' not in CSS
    assert 'function leeTermExpand()' in JS
    assert 'lee.term?.refit()' in JS
    assert '.lee-centre.term-expanded .lee-bottomdock' in CSS
    assert '.lee-centre.agent-expanded .lee-editor, .lee-centre.term-expanded .lee-editor' in CSS
    assert '.lee-editor-stage { position:relative; flex:1 1 auto; min-height:240px' in CSS
    assert 'max-height: min(900px, calc(100% - 240px))' in CSS
    assert 'const limit = () => Math.min(900, Math.max(110, centreHeight() - 240))' in JS
    assert "['exec-h', 80]" in JS and "['agent-h', 110]" in JS
    from leela.app import _asset
    assert _asset('lee-ide.css').startswith('/leestatic/lee-ide.css?v=')
    assert _asset('lee-ide.js').startswith('/leestatic/lee-ide.js?v=')


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


def test_running_a_cell_saves_first_and_reports_where_it_ran():
    run_cell = JS[JS.index('async function runCell'):JS.index('function paintDebugInlineValues')]
    run_file = JS[JS.index('async function runFile'):JS.index('async function runSelection')]
    guard = "$('.lee-tab.active.dirty') && !await saveTab(true)"
    assert guard in run_cell and guard in run_file
    assert run_cell.index('saveTab(true)') < run_cell.index("postEvents('/nb/run/stream'")
    run = JS[JS.index('async function runCell'):JS.index('async function askCell')]
    ask = JS[JS.index('async function askCell'):JS.index('/* ---------------------------------------------------------- running files */')]
    assert 'lee.path === runPath' in run and 'lee.cells[i]?.id === cellId' in run
    assert 'lee.path !== runPath' in ask and 'lee.cells[i]?.id !== cellId' in ask
    run = JS[JS.index('async function runCell'):JS.index('async function askCell')]
    exec_run = JS[JS.index('async function runExec'):JS.index('function recall')]
    assert 'if (c.running)' in run and 'is already running' in run
    assert 'if (lee.execBusy)' in exec_run and 'finally { lee.execBusy = false; }' in exec_run
    cell = JS[JS.index('const cellState'):JS.index('/* The per-cell controls')]
    assert "!c.fresh ? 'previous'" in cell
    assert "saved output from a previous kernel" in cell
    assert 'function markPreviousRuns()' in cell
    assert '.lee-cell-state.previous' in CSS
    assert '.lee-cell-time.previous' in CSS
    output = JS[JS.index('function outputTone'):JS.index('function paintSel')]
    assert "return 'error'" in output and "? 'warning' : 'log'" in output
    assert "return 'result'" in output and "return 'output'" in output
    for selector in ('.lee-out.output', '.lee-out.warning', '.lee-out.log', '.lee-out.error'):
        assert selector in CSS


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
    "Clicking one gutter mark has to answer with that change, not with the whole file's diff."
    mount = JS[JS.index('async function mountFile'):JS.index('function notebookHeadings')]
    assert 'showChangePopup(st.path, line)' in mount and "armChangeGutter($('#filecm'))" in mount
    arm = JS[JS.index('function armChangeGutter'):JS.index('function changePopupBody')]
    assert "closest?.('.cm-lee-change')" in arm and 'getBoundingClientRect().left + 12' in arm
    assert "line.classList.add('lee-change-hot')" in arm
    assert '.cm-line.cm-lee-change.lee-change-hot' in CSS and '.lee-change-pop' in CSS
    pop = JS[JS.index('function showChangePopup'):JS.index('async function copyChangeHunk')]
    assert 'hunkAtLine(line)' in pop and 'Commit this change' in pop
    for act in ('prev', 'next', 'revert', 'diff', 'copy', 'commit'):
        assert f'data-act="{act}"' in pop
    assert 'changePopupBody(h)' in pop and "e.key === 'Escape'" in pop
    assert 'if (at < 0) return showGitFileDiff' in pop

def test_one_change_can_be_reverted_or_committed_without_touching_the_rest_of_the_file():
    "Both operations are one server-built patch and nothing else -- no patch text is assembled"
    revert = JS[JS.index('async function revertChangeHunk'):JS.index('async function commitChangeHunk')]
    assert "gitDo('apply_patch', {patch: h.patch, staged: false, reverse: true})" in revert
    assert "$('.lee-tab.active.dirty') && !await saveTab(true)" in revert
    assert 'confirmDialog(' in revert and 'refreshFileChanges(path, true)' in revert
    commit = JS[JS.index('async function commitChangeHunk'):JS.index('function gitChangeRow')]
    assert "gitDo('apply_patch', {patch: h.patch, staged: true, reverse: false})" in commit
    assert "gitDo('commit', {message: text})" in commit
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
    "A notebook has no single file editor, so a location in one has to name a cell."
    open_at = JS[JS.index('function openLocation'):JS.index('async function stopCell')]
    assert 'hit.cell_line' in open_at and 'cellId: hit.cell' in open_at
    assert 'cell_index' in open_at, 'a notebook before nbformat 4.5 has no cell ids, only order'
    assert 'is in no cell' in open_at, 'an unplaceable notebook hit says so instead of scrolling somewhere'
    landing = JS[JS.index('if (lee.pendingLocation'):JS.index('refreshKernelPill();')]
    assert '(loc.cellId || loc.cellIndex >= 0)' in landing
    assert 'loc.cellIndex < lee.cells.length) i = loc.cellIndex' in landing
    assert 'selectCell(i)' in landing and 'ensureCellMounted(i)' in landing and 'jumpToLine(loc.line)' in landing
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
    with TestClient(ide_app(Workspace(roots=[tmp_path], model='sonnet'))) as client:
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
    assert rows['package-that-does-not-exist']['line'] == 9
    assert len({r['column'] for r in data['packages'] if r['line'] == 9}) == 2
    assert data['summary']['missing'] == 1
    assert 'LeeCM.setPackageVersions' in JS and 'lee-package-summary' in JS
    assert '.cm-lee-package.missing' in CSS and '.lee-package-popover' in CSS

def test_the_notebook_surface_mounts_patches_and_folds_cells():
    assert 'function notebookHeadings' in JS and 'function notebookToc' in JS
    assert 'function setCellCollapsed' in JS and 'cell_collapse:' in JS
    assert '.lee-cell.collapsed .lee-cm' in CSS and '.lee-nb-toc' in CSS
    assert '.lee-gutter .lee-cell-fold' in CSS
    focus = JS[JS.index('function focusCell'):JS.index('function markDirty')]
    assert "scrollIntoView({block: 'nearest'" in focus
    assert 'requestAnimationFrame' in focus
    run = JS[JS.index('async function runCell'):JS.index('async function askCell')]
    assert "renderMarkdown(out.querySelector('.lee-md'), src, true)" in run
    assert "style.display = 'none'" not in run
    mount = JS[JS.index('function observeNotebookCells'):JS.index('const gutterFor')]
    assert 'new IntersectionObserver' in mount
    assert "rootMargin: '700px 0px'" in mount
    assert 'st.cells.forEach((c, i) => mountCell(c, i))' not in mount
    mount = JS[JS.index('function mountCell'):JS.index('function renderOutputs')]
    run = JS[JS.index('async function runCell'):JS.index('async function askCell')]
    assert 'lee.dirtyBuffers.has(key) ? lee.buffers.get(key) : c.source' in mount
    assert 'Object.assign(c, r.cell)' in run
    assert 'lee.cells[i] = r.cell' not in run
    mount = JS[JS.index('function mountCell'):JS.index('function renderOutputs')]
    assert 'if (c.running)' in mount
    assert "setCellState(c, 'running'" in mount
    assert "notice.hidden = false" in mount
    actions = JS[JS.index('const ACTIONS'):JS.index("for (let i = 1")]
    assert 'is now ${r.cells[at]?.cell_type' in actions
    assert "status('cell split', 'ok')" in actions
    assert "status('cell inserted below', 'ok')" in actions
    assert "status('cell deleted', 'ok')" in actions
    assert 'focusCell(at + 1)' in actions
    mount = JS[JS.index('function mountCell'):JS.index('function renderOutputs')]
    assert "c.cell_type === 'markdown' ? 'markdown' : ''" in mount
    assert '.lee-cell.prompt .lee-cm' not in CSS
    assert '.lee-cell.prompt .lee-gutter' not in CSS
    assert 'lee-cell-context' in JS
    assert "op: 'context'" in JS
    assert "['auto', 'keep', 'discard']" in JS
    patch = JS[JS.index('function patchNotebook'):JS.index('function ensureCellMounted')]
    assert 'oldEls = new Map' in patch
    assert 'host.appendChild(el)' in patch
    assert 'if (!el || changed)' in patch
    assert 'LeeCM.destroy(view)' in patch
    assert "host.innerHTML = ''" not in patch
    cell = JS[JS.index('function cellEl'):JS.index('function setCellCollapsed')]
    mounted = JS[JS.index('function mountCell'):JS.index('function renderOutputs')]
    assert 'selectCell(+d.dataset.i)' in cell
    assert "moveCellTo(from, +d.dataset.i)" in cell
    assert "findIndex(cell => cell.id === c.id)" in mounted
    focus = JS[JS.index('function focusCell'):JS.index('function autoSaveEnabled')]
    assert "scrollIntoView({block: 'nearest', inline: 'nearest'})" in focus
    assert "behavior: 'smooth'" not in focus


def test_workspace_panes_can_minimise_and_restore_independently(tmp_path):
    html = to_xml(_shell(Workspace(roots=[tmp_path]), TerminalGate()))
    assert html.count('lee-pane-min') >= 3 and html.count('lee-pane-restore') == 3
    assert 'function leePane' in JS and "'no-bottom'" in JS
    assert '.lee-app.no-bottom .lee-bottomdock' in CSS

def test_the_file_and_agent_panes_can_be_pinned_or_left_to_auto_close(tmp_path):
    "Unpinned, a pane closes when you work elsewhere; pinned is the default and the old behaviour."
    html = to_xml(_shell(Workspace(roots=[tmp_path]), TerminalGate()))
    for pane in ('left', 'right'):
        assert f'data-pane-pin="{pane}"' in html, pane
        assert f'leePinPane(&quot;{pane}&quot;)' in html or f"leePinPane(\"{pane}\")" in html, pane
    assert html.count('lee-pane-min') >= 4, 'the file pane gained its own minimise'
    block = JS[JS.index('const DOCKABLE'):JS.index('function leeTerm')]
    assert "localStorage.getItem('lee-pin-' + which) !== '0'" in block, 'pinned is the default'
    assert ".lee-modal, .lee-ctxmenu, .lee-pane-restore, .lee-split" in block
    assert "leePane(which, false, false)" in block, 'an auto-close is not persisted as a preference'
    assert 'function leePane(which, show = null, persist = true)' in JS
    assert "if (persist) localStorage.setItem('lee-pane-' + which" in JS
    assert '.lee-pane-pin.pinned' in CSS and '.unpinned-left  #left' in CSS
    assert "which === 'right' && lee.agentBusy" in block, 'a streaming agent is never auto-closed'
    assert "pane.matches(':hover')" in block, 'a pane does not close under the pointer'

def test_git_is_a_first_class_vertical_project_tab(tmp_path):
    html = to_xml(_shell(Workspace(roots=[tmp_path]), TerminalGate()))
    assert 'lee-activity' in html and 'data-left="files"' in html and 'data-left="git"' in html
    assert 'id="gitpanel"' in html and 'lee-source-control' in html
    assert 'function leeLeft' in JS and 'async function renderGitPanel' in JS
    assert '.lee-activity-btn.active' in CSS
    assert '.lee-left-content > .lee-panel { display: none; }' in CSS
    assert '.lee-left.left-git .lee-source-control' in CSS
    panel = JS[JS.index('async function renderGitPanel'):JS.index('function gitBranchMenu')]
    for feature in ('Staged changes', 'Changes', 'Branches', 'Stashes', 'Remotes & tags'):
        assert feature in panel
    for op in ('fetch', 'pull', 'push', 'stash', 'tag', 'stage all', 'unstage all'):
        assert op in panel

def test_workflows_are_a_panel_with_a_job_graph_in_it():
    "The visual half: the activity tab, the levels, and the four views."
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
    "The Add view: what the project is, what it could have, and why."
    block = JS[JS.index('function wfPickRows'):JS.index('function wfEnvRows')]
    assert 'lee-wf-detect' in block and 'recommended' in block
    assert 'data-pick-preview' in block and 'data-pick-add' in block
    assert 'already here' in block, 'a workflow that exists is not offered again'
    assert "api('/workflows/catalogue'" in JS and "op: op === 'add' ? 'add' : 'preview'" in JS
    assert "['add', 'Add']" in JS, 'the picker is one of the panel views'
    assert '.lee-wf-pick.recommended' in CSS and '.lee-wf-detect' in CSS

def test_the_builder_is_a_form_rendered_from_the_servers_vocabulary():
    'The answer to "I am not good at Actions": choose, do not type.'
    block = JS[JS.index('const bldUI ='):JS.index('// -- the release pipeline')]
    assert "api('/workflows/presets')" in block, 'the vocabulary is fetched, not hard-coded'
    assert 'bldTrigger' in block and 'bldOption' in block and 'bldJob' in block
    assert "o.type === 'flag'" in block and "o.type === 'lines'" in block
    assert "op: 'build'" in block and "op: 'write_spec'" in block
    assert 'scheduleBuild' in block, 'the YAML follows the form as it changes'
    assert 'data-needs' in block, 'jobs wire to each other by needs'
    assert 'The file has been edited' in block, 'a hand edit is not overwritten silently'
    assert '.lee-bld-job' in CSS and '.lee-bld-trigger' in CSS

def test_the_git_panel_reports_outcomes_filters_and_history():
    block = JS[JS.index('function blameRow'):JS.index('function relStepRow')]
    assert 'your checkout' in block and 'installed copy' in block
    assert 'data-blame-open' in block and 'leeOpenFile' in JS
    assert 'scrollIntoView: true' in JS, 'landing on a line you cannot see is not landing on it'
    assert '.lee-blame' in CSS
    assert "openTerm('gh-auth')" in JS
    assert "gh_auth_argv() if kind == 'gh-auth'" in SERVER
    assert "kind === 'gh-auth' ? 'gh auth'" in JS
    assert "gitUrl('/git/commit/review', {ref})" in JS
    assert "gitUrl('/git/commit/file', {ref, path})" in JS
    assert 'function gitCommitInspector' in JS and 'data-history-commit' in JS
    assert 'openGitCommitFile' in JS and "kind: 'commit'" in JS
    assert '.lee-git-commit-inspector' in CSS and '.lee-git-commit-file' in CSS
    fn = JS[JS.index('function firstLine('):JS.index('function leeLogFilter(')]
    assert "replace(/^\\w*Error:\\s*/, '')" in fn, 'the class name is not the message'
    assert "split('\\n').find(x => x.trim())" in fn, 'the first line that says anything'
    assert 'max - 1' in fn and '…' in fn, 'and it is clipped for a status line'
    done = JS[JS.index('async function gitDo('):JS.index('function gitOperationBanner')]
    assert "lee.gitSignature = ''; gitChanged();" in done, \
        'immediately, and the next poll does not treat our own mutation as news'
    block = JS[JS.index('function gitFilterBanner'):JS.index('function gitSummary')]
    assert 'f.ok !== false' in block and 'f.explain' in block
    assert 'may not stay staged' in block
    assert 'data-git-undo' in block and 'point.describe' in block
    assert 'gitFilterBanner(d) + gitUndoBanner(d)' in JS, 'both sit with the file list'
    assert '.lee-git-undo' in CSS
    block = JS[JS.index('async function gitDo'):JS.index('function gitOperationBanner')]
    assert 'd.outcome?.summary' in block
    assert "d.outcome?.note ? ' — ' + d.outcome.note : ''" in block, 'one call, so neither is dropped'


def test_the_deploy_panel_shows_the_servers_and_tunnels_it_deploys_onto():
    block = JS[JS.index('function depInfraRows'):JS.index('function renderDeployPanel')]
    assert "api('/infra')" in block and "api('/infra/records?zone=" in block and "api('/stack'" in block
    for word in ('servers', 'tunnels', 'zones'):
        assert word in block
    assert 'data-server-del' in block and 'data-tunnel-del' in block
    assert 'delete this server' in block and 'confirmDialog' in JS
    assert 'edits in your checkout are not what runs' in block, 'the shadowed package warning'
    assert '.lee-inf-row' in CSS and '.lee-pkg.shadowed' in CSS


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
    "Two separate things it needs to be useful."
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
    "A button you cannot read is not a diagnostic."
    block = JS[JS.index('const drvUI ='):JS.index('async function renderGitPanel')]
    assert "api('/drive'" in block and "post('/drive/action'" in block
    assert 'lee-drv-code' in block and '} the call</summary>' in block
    assert 'lee-drv-pkg' in block, 'each part says which package it drives'
    assert 'sets ' in block and 'writes ' in block, 'what a call leaves for the next one'
    assert "openReleaseTerm(drvUI.data.root, 'drive')" in block
    assert "data_left='drive'" in SERVER and '.lee-left.left-drive' in CSS
    assert '.lee-drv-part.state-failed' in CSS

def test_panels_refresh_themselves_and_keep_secrets_server_side():
    assert "url: kind === 'drive' ? '/drive/ws' : '/pipeline/ws'" in JS
    assert "openReleaseTerm(root = '', kind = 'release')" in JS
    assert 'def pipeline_socket(' in read('leela/core/web.py')
    assert SERVER.count("pipeline_socket(app, '") == 2, 'both blocks register through it'
    block = JS[JS.index('function wfEnvRows'):JS.index('function renderWorkflowsPanel')]
    assert "'••••••••'" in block or '••••••••' in block
    assert 'e.secret ?' in block, 'a secret and a variable are drawn differently'
    ops = JS[JS.index('async function refreshFileTree'):JS.index('document.addEventListener(\'click\'')]
    assert 'location.reload()' not in ops
    assert "fetch('/files/panel')" in ops
    assert "old.replaceWith(fresh)" in ops
    first = workspace_slug('My Project')
    second = workspace_slug('My Project', [first])
    assert first == 'my-project' and second == 'my-project-2'



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
    "The plural view, and the two rules that keep it from lying."
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
    assert 'Review ${branch} into ${d.branch}' in block, 'the branch kebab offers the review'
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
    '"See logs" has to end with the reader seeing the log.'
    show = JS[JS.index('function showLog('):JS.index('function firstLine(')]
    assert "if (lee.logFilter && lee.logFilter !== source) leeLogFilter('')" in show, \
        'a filter that would hide the new row is cleared'
    assert "leeDock('logs')" in show
    failed = JS[JS.index('async function gitDo('):JS.index('function gitOperationBanner')]
    assert failed.index("leeLog('git'") < failed.index("showLog('git')"), 'written, then shown'
    assert 'status(`git ${name} failed — ${firstLine(detail)}`' in failed, \
        "git's first line is usually the whole story, so the toast carries it"
    assert 'see logs' not in JS, 'nothing tells you to go and look any more'


def test_a_branch_change_reaches_every_surface_that_was_derived_from_it():
    "The pill and the tree badges were repainted by the poll; nothing else was."
    sig = JS[JS.index('function gitSignature('):JS.index('function noticeGitState(')]
    assert 'd.head' in sig, 'a commit moves nothing else: branch, counts and files all read the same'
    assert 'd.branch' in sig and 'd.ahead' in sig and "(d.operation || {}).active" in sig
    notice = JS[JS.index('function noticeGitState('):JS.index('function gitChanged()')]
    assert 'if (had && had !== sig) gitChanged()' in notice, 'the first poll is not a change'
    fan = JS[JS.index('function gitChanged()'):JS.index('window.leeGitChanged')]
    assert 'refreshOpenGitMarks()' in fan, 'the open file or notebook is re-marked'
    assert 'gitUI.snapshot = null; gitUI.history = []' in fan, 'History and Branches reload'
    assert 'leeReleases()' in fan and 'leeDeploys()' in fan
    pills = JS[JS.index('async function refreshProjectPills'):JS.index('async function leeCwd')]
    assert 'noticeGitState(d)' in pills
    assert 'setInterval(refreshProjectPills, 5000)' in JS


def test_the_merge_button_always_answers_instead_of_being_disabled():
    '"I clicked merge and nothing happened" was a disabled button.'
    fn = JS[JS.index('async function showMergePreview('):JS.index('async function showRebasePreview(')]
    assert 'data-merge>' in fn and "data-merge ${" not in fn, 'the button is never disabled'
    assert "if (blocked) return status(`cannot merge — ${blocked}`, 'err')" in fn, \
        'a press that cannot proceed says why'
    assert 'commit or stash ${p.dirty.length} changed file' in fn, 'and names the real blocker'
    assert 'p.dirty.map(esc).join' in fn, 'listing the tracked files, not a count of everything'
    rb = JS[JS.index('async function showRebasePreview('):JS.index('function gitBranchMenu(')]
    assert 'data-rebase>' in rb and "data-rebase ${" not in rb
    assert "if (rbBlocked) return status(`cannot rebase — ${rbBlocked}`, 'err')" in rb

def test_the_conflict_resolver_is_three_panes_over_gits_own_markers():
    "Reading the conflicts out of the markers Git wrote, not re-diffing the three versions."
    block = JS[JS.index('const CONFLICT_OPEN'):JS.index('// Blame, reachable from wherever')]
    assert 'function scanConflicts' in block and 'function conflictSide' in block
    assert 'if (block.end < 0) continue' in block, 'an unclosed marker is text, not a conflict'
    assert "for (const key of ['base', 'ours', 'theirs'])" in block
    assert 'data-pane="${key}"' in block and "pane('result', 'result', 'editable')" in block
    assert 'onChange:' in block, 'the result pane is the editable one'
    for control in ('data-take="ours"', 'data-take="theirs"', 'data-take="both"',
                    'data-nav="prev"', 'data-nav="next"', 'data-base-toggle', 'data-resolve'):
        assert control in block, control
    assert 'setTimeout(() => refresh(text, false), 0)' in block
    assert 'programmatic = true' in block
    assert "choice: 'resolved'" in block, 'the assembled text is what gets staged'
    assert 'showWholeSideConflict' in block, 'delete/modify has no lines to work through'
    assert '.lee-merge3-panes' in CSS and '.cm-line.cm-lee-change-conflict-active' in CSS



def test_choosing_a_folder_reloads_every_project_panel_not_just_git():
    "The backend answering correctly is half of it: the open panel has to ask again."
    block = JS[JS.index('function projectChanged'):JS.index('async function refreshProjectPills')]
    assert 'gitUI.snapshot = null' in block and 'relUI.data = drvUI.data = null' in block
    assert "Object.assign(wfUI, {data: null" in block and "Object.assign(depUI, {data: null" in block
    assert "left-drive')) leeDrive()" in block and "left-workflows')) leeWorkflows()" in block
    activate = JS[JS.index("await post('/workspace/activate'"):]
    assert 'projectChanged();' in activate[:600]
    assert 'renderGitPanel();' not in activate[:600], 'superseded by projectChanged'

def test_search_leads_with_all_and_walks_its_modes_from_a_rail():
    "`all` ranks every backend together, so it is the mode that answers without you first"
    modes = JS[JS.index('const SEARCH_MODES'):JS.index('async function codeSearch')]
    assert modes.index("['all'") < modes.index("['rg'") < modes.index("['context'")
    block = JS[JS.index('async function codeSearch'):JS.index('function cursorWord')]
    assert "localStorage.getItem('lee-search-mode') || 'all'" in block
    assert "if (!SEARCH_MODES.some(([id]) => id === mode)) mode = 'all'" in block, 'a stale mode falls back'
    assert "e.key === 'Tab'" in block and 'cycleMode(e.shiftKey ? -1 : 1)' in block
    assert 'const cycleMode = step =>' in block and '% SEARCH_MODES.length' in block, 'and it wraps'
    assert "counts[id] == null ? '' : counts[id]" in block
    assert 'counts[mode] = hits.length' in block
    assert '.lee-searchrail' in CSS and '.lee-searchrail-mode.active' in CSS
    assert 'lee-searchmodes' not in block, 'the old horizontal segbar is gone, not just hidden'

def test_all_streams_its_backends_into_stable_slots():
    "rg answers in tens of milliseconds and the embedding leg in seconds, so `all` fills in as"
    block = JS[JS.index('const streamAll'):JS.index('let timer, liveStream')]
    assert "new EventSource('/search/stream?q='" in block
    assert "for (const leg of d.legs || []) slots.set(leg, [])" in block, 'order fixed once, up front'
    assert 'already.sources = [...new Set([...(already.sources || []), d.leg])]' in block
    assert 'if (sel >= hits.length)' in block, 'the selection survives a list that grew at the end'
    assert 'liveStream = es' in block
    search = JS[JS.index('let timer, liveStream'):JS.index('input.addEventListener(\'input\', search)')]
    assert 'if (liveStream) { try { liveStream.close(); }' in search
    assert "if (mode === 'all')" in search and 'return streamAll(q, seq)' in search

def test_research_and_search_stream_into_the_workspace():
    from tests.assets import read
    src = read('leela/blocks/search/app.py')
    assert 'asyncio.as_completed(tasks)' in src, 'completion order is the entire point'
    assert 'off_loop(ctx.search.leg, name' in src, 'each leg on its own worker thread'
    assert 'await req.is_disconnected()' in src and 't.cancel()' in src
    assert "sse('leg'" in src and "sse('done'" in src and "sse('start'" in src
    research = JS[JS.index('function researchWorkspace'):JS.index('function webSearch')]
    assert 'Add to agent memory' in research and "leeNewMemoryNote({title:" in research
    assert 'data-new-thought' in research and 'New research note' in research
    assert 'Markdown scratchpad' in research and 'edit and choose model routing before saving' in research


def test_a_pdf_opens_in_the_browsers_own_viewer(tmp_path):
    "We are in a browser, so the viewer already exists -- the feature is handing the bytes over."
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
        (tmp_path/'x.py').write_text('x = 1\n')
        assert c.get('/file/raw', params={'path': str(tmp_path/'x.py')}).json()['error']
        assert c.get('/file/raw', params={'path': '/etc/passwd'}).json()['error']

def test_markdown_renders_beside_its_source_without_giving_up_the_editor(tmp_path):
    "Rendered, split and edit are ways of *looking* at the file, not different kinds of tab."
    mount = JS[JS.index('async function mountFile'):JS.index('async function mountSecondary')]
    assert "const isMd = (st.lang || '') === 'markdown'" in mount
    assert "localStorage.getItem('lee-md-view') || 'split'" in mount
    assert "['edit', 'split', 'rendered']" in mount
    assert "renderMarkdown($('#mdpreview'), txt)" in mount, 'the preview follows the buffer'
    assert 'id="filecm"' in mount, 'and the editor is mounted in every view'
    assert '.lee-md-stage[data-view="rendered"] .lee-cm { display: none; }' in CSS
    assert '.lee-md-stage[data-view="edit"] .lee-md-preview { display: none; }' in CSS
    assert 'requestAnimationFrame(() => LeeCM.focus(v))' in mount
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
    "The modal's close and expand sit *over* the top-right corner, absolutely positioned."
    import re
    close_r = re.search(r'\.lee-modal-close \{ right: (\d+)px', CSS)
    expand_r = re.search(r'\.lee-modal-expand \{ right: (\d+)px', CSS)
    bar = re.search(r'\.lee-searchbar \{[^}]*padding-right: (\d+)px', CSS)
    assert close_r and expand_r and bar, 'the three rules this depends on still exist'
    assert int(bar.group(1)) >= int(expand_r.group(1)) + 24

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
    "`alignMarkdownBlocks`, in Python: the pairs, or None where the browser draws nothing."
    nodes, pairs, at = _md_carriers(html), [], 0
    for b in blocks:
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
    from leela.core.text import md_blocks
    blocks = md_blocks(README)
    pairs = _md_align(_md_render(README), blocks)
    assert pairs is not None, 'a rendered diff of an ordinary README can be marked'
    assert [n for _, n in pairs] == ['h1', '#comment', 'p', 'pre', 'h2', 'ul', 'table',
                                     'blockquote', 'hr', 'figure']
    assert [b['type'] for b in blocks if not b['renders']] == ['link_ref', 'footnote_def']
    fence = next(b for b in blocks if b['type'] == 'code_block')
    assert (fence['from'], fence['to']) == (7, 9) and fence['code'] == 'uv add rishi\n'

def test_markdown_diffs_map_blocks_onto_the_elements_they_rendered():
    from leela.core.text import md_blocks
    doc = 'para one\n\n<p>a</p><p>b</p>\n\n## heading\n'
    assert _md_align(_md_render(doc), md_blocks(doc)) is None
    assert _md_align('<p>only</p>', md_blocks('para\n\npara two\n')) is None, 'a block with no element'
    assert _md_align('<p>a</p><p>b</p>', md_blocks('para\n')) is None, 'an element no block claimed'
    render = JS[JS.index('function renderMarkdown('):JS.index('async function api(')]
    assert 'onRender = null' in render
    assert render.index('onRender(el)') < render.index('enhanceCodeBlocks(el)'), 'the pre is still a pre'
    assert 'try { onRender(el); } catch' in render, 'a mapping bug cannot cost the reader the rendering'
    paint = JS[JS.index('function paintMarkdownDiff'):JS.index('async function mountMarkdownDiff')]
    assert "if (row.status === 'removed') { removed.push(row); continue; }" in paint
    assert 'host.dataset.removedAbove' in paint and 'last.dataset.removedBelow' in paint
    assert 'removed.map(r => r.source).join' in paint, 'the old text is readable without another request'
    assert '.lee-md-change[data-removed-above]::after' in CSS


def test_a_markdown_diff_pairs_blocks_and_refuses_to_pair_across_types():
    from leela.core.text import md_block_diff
    old = '# t\n\nold prose\n\n```sh\nold cmd\n```\n\ngone entirely\n'
    new = '# t\n\nnew prose\n\n```sh\nnew cmd\n```\n\n## Install\n\nfresh\n'
    d = md_block_diff(old, new)
    rows = [(r['status'], r['type']) for r in d['blocks']]
    assert rows[:3] == [('equal', 'heading'), ('modified', 'paragraph'), ('modified', 'code_block')]
    assert ('modified', 'heading') not in rows, 'a paragraph did not become a heading'
    assert ('added', 'heading') in rows
    assert (d['blocks'][-1]['status'], d['blocks'][-1]['old']) == ('modified', 'gone entirely')
    fence = next(r for r in d['blocks'] if r['type'] == 'code_block')
    assert fence['old_code'] == 'old cmd\n' and fence['code'] == 'new cmd\n'
    assert d['changed'] and (d['added'], d['removed']) == (5, 3)

def test_the_diff_records_still_line_up_with_the_document_being_read():
    "The records the rendered view actually receives, against the rendering it actually gets."
    from leela.core.text import md_block_diff
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
    from leela.core.text import md_blocks, md_change_kinds
    blocks = md_blocks('# t\n\nprose\n\n```sh\na\nb\n```\n')
    kinds = md_change_kinds(blocks, [{'from': 3, 'to': 3, 'kind': 'added'},
                                     {'from': 6, 'to': 6, 'kind': 'deleted'}])
    assert kinds == [None, 'added', 'removed']
    both = md_change_kinds(blocks, [{'from': 1, 'to': 8, 'kind': 'modified'}])
    assert both == ['modified', 'modified', 'modified']
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
    assert "renderMarkdown(doc, data.right || '', false, () => paintMarkdownDiff(doc, rows))" in block
    assert 'allow_raw: true' not in block and "'/markdown/render'" not in block
    assert '.lee-md-diff-doc' in CSS and '.lee-md-change::before' in CSS
    for kind in ('added', 'modified', 'code'):
        assert f'.lee-md-change[data-change="{kind}"]::before' in CSS


def test_a_block_that_cannot_be_matched_leaves_the_rendering_unmarked_and_says_so():
    block = JS[JS.index('function alignMarkdownBlocks'):JS.index('function markdownCodeDiffHtml')]
    assert 'if (!row.renders) continue' in block, 'a definition consumes no element'
    assert 'if (at >= tags.length) return null' in block, 'a block with no element voids the mapping'
    assert 'if (want.length && !want.includes(tag)) return null' in block, 'and so does the wrong element'
    assert 'return at === tags.length ? pairs : null' in block, 'and so does an element nobody claimed'
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
    assert "host.className = 'lee-md-code-host'; host.appendChild(node)" in paint
    assert '.lee-md-code-host' in CSS
    assert '.lee-md-code-line.del' in CSS and 'text-decoration: line-through' in CSS
    assert '.lee-md-code-line.add' in CSS


def test_the_rendered_markdown_pane_carries_the_change_marks_of_the_gutter_beside_it():
    "The file's own preview places `/git/file` line ranges by block: the other route to the"
    block = JS[JS.index('async function paintMarkdownFileChanges'):JS.index('async function leeOpenFile')]
    assert "post('/markdown/blocks', {text, ranges})" in block
    assert 'tags = markdownCarriers(el).map(markdownTagOf)' in block, 'tags read before the request goes out'
    assert 'if (!el.isConnected || el.dataset.markdown !== text) return' in block, 'a superseded render draws nothing'
    assert 'if (!pairs) return' in block
    mount = JS[JS.index('async function mountFile'):JS.index('async function mountSecondary')]
    assert 'paintMarkdownFileChanges(el, git.ranges || [])' in mount
    assert "if (isMd) renderMarkdown($('#mdpreview'), txt);" in mount, 'a keystroke re-render carries no marks'

def test_a_pdf_is_served_under_its_own_name_and_fills_the_pane(tmp_path):
    'Two things were wrong with the viewer: it was short, and every document was called "raw".'
    from starlette.testclient import TestClient
    from leela.app import ide_app
    pdf = tmp_path/'2306.14881.pdf'; pdf.write_bytes(b'%PDF-1.4\n%%EOF\n')
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as c:
        named = c.get('/file/raw/2306.14881.pdf', params={'path': str(pdf)})
        assert named.status_code == 200 and named.headers['content-type'] == 'application/pdf'
        assert 'inline; filename="2306.14881.pdf"' in named.headers['content-disposition']
        assert c.get('/file/raw', params={'path': str(pdf)}).status_code == 200, 'both spellings'
        assert c.get('/leestatic/lee-ide.css').status_code == 200
        assert c.get('/file/raw/passwd.pdf', params={'path': '/etc/passwd'}).status_code == 400
    mount = JS[JS.index('function mountPdf'):JS.index('async function mountFile')]
    assert "'/file/raw/' + encodeURIComponent(name) + '?path='" in mount
    assert 'class="lee-doc"' in mount, 'a column that fills the pane'
    assert '.lee-editor:has(> .lee-doc) { display: flex; flex-direction: column;' in CSS
    assert '.lee-doc { display: flex; flex-direction: column; flex: 1 1 auto; min-height: 0; }' in CSS
    assert '.lee-doc-body { display: grid; flex: 1 1 auto; min-height: 0;' in CSS
    assert '.lee-pdf { width: 100%; height: 100%;' in CSS

def test_source_control_notices_an_edit_and_not_only_a_new_file():
    "The reported bug: the panel only refreshed when refreshed by hand."
    block = JS[JS.index('function gitSignature'):JS.index('function noticeGitState')]
    for field in ('c.path', 'c.index', 'c.worktree', 'staged_stat', 'unstaged_stat'):
        assert field in block, field
    assert '(d.changes || []).length' not in block, 'the count alone was the bug'
    save = JS[JS.index('async function saveTab'):JS.index('async function saveAllTabs')]
    assert 'refreshProjectPills' in save
    pills = JS[JS.index('async function refreshProjectPills'):JS.index('function projectRepo')]
    assert 'noticeGitState(d)' in pills and "api('/git/info')" in pills
    assert 'setInterval(refreshProjectPills, 5000)' in JS, 'and an external change lands by poll'

def test_the_editor_pane_fills_its_stage_and_the_splitter_only_exists_when_split():
    "Measured in a browser, not reasoned about: on a 900px window the stage was 577px and the"
    assert '.lee-editor-stage:not(.split) { grid-template-columns:minmax(0,1fr); ' \
           'grid-template-rows:minmax(0,1fr); }' in CSS
    assert '.lee-editor-stage:not(.split) .lee-editor-splitter { display:none; }' in CSS
    split = JS[JS.index('function mountSecondary'):JS.index('function leeSplit')]
    assert "classList.add('split',`split-${direction}`)" in split
    assert '.lee-editor-stage.split-vertical { grid-template-columns:' in CSS
    assert '.lee-editor-stage.split-horizontal { grid-template-rows:' in CSS

def _fake_venv(root):
    py = root/'.venv'/'bin'/'python'
    py.parent.mkdir(parents=True)
    py.write_text('')
    return py

def test_project_venv_is_the_default_runtime_without_moving_leela(tmp_path):
    py = _fake_venv(tmp_path)
    assert project_python([tmp_path]) == str(py)
    ws = Workspace(roots=[tmp_path])
    assert ws.pool.default_python == str(py)

def test_adding_the_first_folder_adopts_its_venv(tmp_path):
    py = _fake_venv(tmp_path)
    ws = Workspace(roots=[])
    ws.add_root(tmp_path)
    assert ws.pool.default_python == str(py)

def test_settings_dialog_never_scopes_saves_to_the_focused_tabs_language():
    '"Apply to" defaults to All languages, and a language scope is only ever chosen explicitly.'
    body = JS[JS.index('async function editorSettings'):][:1200]
    block = body[:body.index('const rememberedScope')]
    code = '\n'.join(l for l in block.splitlines() if not l.strip().startswith('//'))
    assert "localStorage.getItem('lee-settings-language-scope')" in code
    assert "remembered!==null?remembered:''" in code
    assert 'curLang' not in code

def test_variables_and_runtimes_follow_the_active_tab():
    src = bootstrap_src()
    assert 'sys.path.append(_p)' in src
    assert 'import dhrishti.serving as ls' in src
    assert src.index('sys.path.append(_p)') < src.index('import dhrishti.serving as ls')
    from leela.app import _vars_panel
    from leela.workspace import Workspace
    html = str(_vars_panel(Workspace(roots=[])))
    assert '>agent</button>' in html and 'leeScope("agent")' in html
    assert "lee.execScope === 'live' ? 'agent' : 'live'" in JS
    assert "protected agent session" in JS
    refresh = JS[JS.index('async function refreshVars'):JS.index('function varRow')]
    assert 'lee.varFingerprints.get(runtime) === fingerprint' in refresh
    assert 'lee.varFingerprints.set(runtime, fingerprint)' in refresh
    picker = JS[JS.index('async function pickKernel'):JS.index('/* ---------------------------------------------------------- the keymap')]
    assert "post('/runtime/support', {python: o.python})" in picker
    assert 'installing ipykernel and ipymini with uv' in picker
    assert "return pickKernel()" in picker
    picker = JS[JS.index('async function pickKernel'):JS.index('/* ---------------------------------------------------------- the keymap')]
    assert '.dispose()' not in picker
    assert "post('/term/close" not in picker
    assert 'function editRuns()' in JS and 'data-run-env-file' in JS and 'data-env-key' in JS
    assert 'Secret values belong in an ignored .env.local file' in JS
    vars_code = JS[JS.index('async function leeVars'):JS.index('function varRow')]
    assert 'lee.varStates.set(lee.varRuntime' in vars_code
    assert 'lee.varStates.get(runtime)' in vars_code
    assert 'open: new Set(lee.varOpen)' in vars_code
    assert "filter: $('#varfilter')?.value" in vars_code


def test_one_keyboard_router_reaches_every_panel():
    assert "window.addEventListener('keydown'" in JS
    assert "const wantMeta = !!c.mod && MAC" in JS
    assert 'function eventContext(e)' in JS
    assert "inPath('#agentprompt, .lee-agent')" in JS
    assert "inPath('#execbox, .lee-exec')" in JS
    assert 'function cmBinds' not in JS
    from leela.core.keys import lookup
    for action, panel in (('panel_git', 'git'), ('panel_releases', 'releases'), ('panel_deploys', 'deploys')):
        key = lookup(action)
        assert key.scope == 'global' and key.keys, f'{action} is bound'
        assert re.search(rf"{action}:\s*\(\) => leeLeft\('{panel}'\)", JS), f'{action} opens the {panel} panel'
    assert 'lee.keys.filter(k => k.label)' in JS







def test_terminal_starts_inside_the_project_uv_environment():
    "One builder, used by the pty and by every release, deploy and drive step alike."
    import inspect, os
    from leela.app import ide_app
    from leela.blocks.runtime.kernels import venv_env
    env = venv_env('/proj/.venv/bin/python', {'PATH': '/usr/bin'})
    assert env['VIRTUAL_ENV'] == env['UV_PROJECT_ENVIRONMENT'] == '/proj/.venv'
    assert env['PATH'] == '/proj/.venv/bin' + os.pathsep + '/usr/bin'
    assert 'env = venv_env(py) if py else None' in inspect.getsource(ide_app)

def test_codemirror_preferences_are_live_reconfigurable_and_have_a_settings_workbench():
    editor = EDITOR
    assert 'function settingsExt' in editor and 'export function configure' in editor
    assert 'EditorState.tabSize.of' in editor and 'EditorView.lineWrapping' in editor
    assert 'async function editorSettings(' in JS and "post('/settings/save'" in JS
    settings = JS[JS.index('async function editorSettings'):JS.index('function leeTheme')]
    assert 'data-settings-target' in settings and "await loadSettings(language.value)" in settings
    for setting in ('fontFamily', 'fontSize', 'lineHeight', 'lineLength', 'guideColumns',
                    'visualGuides', 'tabSize', 'ligatures', 'useTabs', 'wordWrap',
                    'activeLine', 'bracketMatching', 'closeBrackets'):
        assert f"'editor','{setting}'" in JS or f'data-pref="{setting}"' in JS
    assert 'data-pref="fontFamily"' in JS and 'fontSelect' in JS
    assert 'function guideTheme' in editor and 'guideColumns' in editor

def test_indent_detection_copies_tabs_or_space_units_without_treating_alignment_as_policy():
    editor = EDITOR
    detection = editor[editor.index('function detectedIndentation'):editor.index('function normalizedSettings')]
    assert "if(tabs>widths.length)return {...settings,useTabs:true}" in detection
    assert 'const candidates=[2,4,8]' in detection and 'width%unit===0' in detection
    assert 'Math.min(...widths)' not in detection
    assert 'function indentColumns' in editor and '--lee-indent-cols' in editor
    assert 'background-repeat: no-repeat' in CSS

def test_editor_extensions_are_live_preferences():
    editor = EDITOR
    assert 'function overviewPlugin' in editor and 'const stickyPlugin' in editor
    assert "'editor','overviewMode'" in JS and "'editor','stickyNavigation'" in JS
    prefs = JS[JS.index('function readEditorPrefs'):JS.index('lee.editorPrefs = readEditorPrefs()')]
    assert "if ('minimap' in old && !old.minimapMode)" in prefs
    assert 'if (old.minimapMode && !old.overviewMode) old.overviewMode = old.minimapMode;' in prefs
    assert 'settings.overviewMode || settings.minimapMode' in EDITOR, 'and on the editor side too'
    src=EDITOR
    assert 'pairedTripleQuotes' in src and 'transactionFilter' in src
    assert (ROOT/'leela/vendor/lee-cm6.js').stat().st_size > 100_000


def test_the_overview_is_the_scrollbar_marked_up_rather_than_a_picture_of_the_text():
    "A compressed image of the letters answers no question you can act on."
    stripe = EDITOR[EDITOR.index('function overviewPlugin'):EDITOR.index('const stickyPlugin')]
    assert 'forEachDiagnostic(this.view.state' in stripe, 'ticks come from the real diagnostics'
    assert 'this.view.state.field(changesField, false)' in stripe, 'bars come from the git marks'
    assert 'cm-lee-change-(\\w+)' in stripe, 'a change bar is coloured by its kind'
    assert 's.scrollTop =' in stripe and 'pointermove' in stripe, 'it scrolls, and it drags'
    assert 'viewportLineBlocks' in stripe, 'and it says where you are'
    assert 'scrollbar-width: none' in CSS and '.cm-lee-has-overview .cm-scroller' in CSS
    assert 'cm-lee-minimap' not in CSS, 'the old canvas is gone, not merely hidden'


def test_drafts_and_autosave_survive_reload_and_conflict():
    editor = EDITOR
    assert 'MergeView' in editor and 'export function createMerge' in editor
    assert 'function openMergeConflict' in JS and 'data-save-merge' in JS
    assert 'Resolve notebook conflict' in JS and 'data-cell-merge' in JS
    assert '/tab/disk?path=' in JS
    assert "lee.filePrefs.autoSave || 'afterDelay'" in JS
    assert "'onFocusChange'" in JS and "'onWindowChange'" in JS
    assert 'persistDraft(key, payload)' in JS
    assert 'base_disk_version = draftBaseFor(documentKey)' in JS
    assert 'showSaveConflict(message)' in JS
    assert "const DRAFT_DB = 'leela-editor-drafts'" in JS
    assert 'indexedDB.open(DRAFT_DB, 1)' in JS
    assert 'await restoreDrafts(st)' in JS
    assert "window.addEventListener('pagehide', snapshotCurrentDraft)" in JS
    assert 'await clearDrafts(path)' in JS
    restore = JS[JS.index('async function restoreDrafts'):JS.index('window.lee = lee')]
    assert 'let recovered = false' in restore
    assert 'if (!recovered) await clearDrafts(documentKey)' in restore
    assert "row.payload.text !== st.text" in restore
    conflict = JS[JS.index('function showSaveConflict'):JS.index('async function saveAllTabs')]
    assert 'heldSaveConflicts.add(lee.path)' in conflict
    assert "automatic retries paused" in conflict
    autosave = JS[JS.index('function scheduleAutoSave'):JS.index('function markDirty')]
    assert 'lee.heldSaveConflicts.has(lee.path)' in autosave
    reload_code = JS[JS.index('async function takeDiskVersion'):JS.index('async function stopAgent')]
    assert "await post('/tab/reload', {path})" in reload_code
    assert 'lee.buffers.delete(key)' in reload_code
    assert 'await takeDiskVersion(e.path)' in reload_code
    assert 'function rememberBuffer(key, payload)' in JS
    assert "post('/tab/buffer', {...payload, base_disk_version:" in JS
    assert 'persistDraft(key, payload)' in JS
    assert "lee.dirtyBuffers.has(key) ? lee.buffers.get(key)" in JS
    assert 'bufferTimers' in JS



def test_editor_toolbar_keeps_contextual_actions_and_moves_the_rest_to_kebab():
    from fasthtml.common import to_xml
    from leela.app import _toolbar
    html = to_xml(_toolbar())
    assert 'data-action="run_cell"' in html and 'data-action="run_file"' in html
    assert 'data-action="run_all"' not in html
    assert 'leeEditorMenu(this)' in html and 'more editor actions' in html
    assert 'function updateToolbarForKind(kind)' in JS

def test_agent_teleprompter_exposes_control_modes_and_editable_tool_calls():
    from fasthtml.common import to_xml
    from leela.app import _agent_panel
    from leela.workspace import Workspace
    html = to_xml(_agent_panel(Workspace(roots=[])))
    assert 'id="agentcontrol"' in html
    assert all(f'value="{mode}"' in html for mode in ('autopilot', 'guided', 'directed'))
    assert "post('/agent/control', {control})" in JS
    assert 'data-tool' in JS and 'data-args' in JS
    assert "post('/agent/approve', {id: a.id, ok, note, session, tool, args})" in JS
    assert "post('/agent/run-policy', {policy, count:" in JS
    assert "post('/agent/tool-preview', {tool, args})" in JS
    assert "post('/agent/steer', {text})" in JS
    assert '.lee-proposal-editor' in CSS and '.lee-proposal-error' in CSS

def test_modals_are_resizable_expandable_and_keep_content_scrollable():
    overlay = JS[JS.index('function modal('):JS.index('function inputDialog')]
    assert 'lee-modal-resizable' in overlay and 'lee-modal-expand' in overlay
    assert 'ResizeObserver' in overlay and 'lee-modal-size:' in overlay
    assert "dragHandle.addEventListener('pointerdown'" in overlay
    assert "dragHandle.addEventListener('pointermove'" in overlay
    assert "m.classList.add('lee-modal-moved'" in overlay
    assert '.lee-modalbox.lee-modal-resizable { resize: both; }' in CSS
    assert '.lee-modal.lee-modal-moved .lee-modalbox' in CSS
    assert '.lee-modal.lee-modal-expanded .lee-modalbox' in CSS
    assert '.lee-modalbox > .lee-mfoot { flex: none; flex-wrap: wrap; }' in CSS

def test_agent_state_is_a_markdown_codemirror_with_preview_lint_and_tool_insertion():
    state = JS[JS.index('async function leeAgentState'):JS.index('window.leeAgentState')]
    assert "lang: 'markdown'" in state and "lintPath: '<agent-state>'" in state
    assert 'lee-agent-state-editor' in state and 'agentstatepreview' in state
    assert 'data-add-rule' in state and 'data-add-check' in state and 'data-add-tool' in state
    assert 'lee-state-tool-list' in state and 'insertStateMarkdown' in state
    assert '.lee-agent-state-editor .cm-editor { height: 100%' in CSS
    assert '.lee-state-ref-tabs' in CSS and '.lee-state-ref-pane.active' in CSS

def test_the_agent_panel_streams_steps_approvals_and_usage():
    log = JS[JS.index('function agentLog'):JS.index('/* A write pauses')]
    assert "insertAdjacentHTML('beforeend', html)" in log
    assert 'log.innerHTML +=' not in log
    assert 'checking Kosha graph, then asking the completion model' in JS
    assert 'asking the inline model to rewrite the selection' in JS
    assert 'review before replacing' in JS
    boot = JS[JS.index('async function boot()'):JS.index("document.addEventListener('DOMContentLoaded'")]
    assert '/complete/warm' not in boot
    step = JS[JS.index('function renderAgentStep'):JS.index('// A turn gets an immediate')]
    assert "document.createElement('summary')" in step
    assert 'lee-agent-step-detail' in step and 'readableDetail(a.detail)' in step
    assert "mountCodeSurface(block, code, 'python', true)" in step
    assert "document.createElement('details')" in JS
    assert '.lee-agent-step > summary' in CSS and '.lee-agent-step-detail' in CSS
    card = JS[JS.index('function showApproval'):JS.index('function readableDetail')]
    assert 'Pause again' in card and 'Trust changes for this session' in card
    assert "const session = ok && $('[data-run-policy]', card).value === 'approve_session'" in card
    assert "post('/agent/approve', {id: a.id, ok, note, session, tool, args})" in card
    assert "api('/agent/approval')" in JS
    assert 'if (r.pending) showApproval(r.pending)' in JS
    assert 'setInterval(pollApproval, 750)' in JS
    card = JS[JS.index('function showApproval'):JS.index('async function pollApproval')]
    assert "leePane('right', true)" in card
    assert "leeRight('agent')" in card
    assert "restoreAgentLive()" in card
    message = JS[JS.index('function userMessage'):JS.index('function renderTurns')]
    assert "raw.length > 900" in message and "raw.split('\\n').length > 14" in message
    assert 'Show full request' in message and 'lee-user-message-more' in message
    assert 'item.appendChild(userMessage(turn.prompt))' in JS
    assert 'log.appendChild(userMessage(q))' in JS
    assert '.lee-user-message {' in CSS and '.lee-user-message-body.preview' in CSS
    js = JS
    agent = AGENT
    assert "'usage': self.turn_use.dict()" in agent
    assert 'function usageMeta(' in js and 'usageMeta(turn.usage' in js
    assert 'usageMeta(d.usage' in js and 'Token usage and estimated cost for this turn' in js
    from leela.app import _agent_panel
    from leela.workspace import Workspace
    html=str(_agent_panel(Workspace(roots=[])))
    assert 'leeAddModel' in html and '/agent/models/add' in JS
    assert 'Hugging Face URL' in JS and 'hosted API / FastLLM' in JS
    from leela.workspace import Workspace
    ws = Workspace(roots=[])
    assert ws.inline_model == 'gpt-mini'
    assert ws.completion_model == 'gpt-4.1'
    assert ws.ai.routing.name_for('completion') == 'gpt-4.1'


def test_agent_memory_workbench_edits_notes_and_routes_each_model_surface():
    assert 'async function leeAgentMemory' in JS
    assert 'async function leeMemoryNotes' in JS and 'leeNewMemoryNote' in JS
    assert 'data-quick-target' in JS and 'Select exactly where each note is used.' in JS
    assert 'durable notes with explicit model routing' in JS
    assert 'Agent conversation' in JS and 'Prompt cells' in JS and 'Code completion' in JS
    assert "post('/agent/memory/save'" in JS and "post('/agent/memory/select'" in JS
    assert "targets: requestedTargets" in JS and 'Choose now; routing starts when you save.' in JS
    assert 'Changes apply to live model context immediately.' in JS
    assert '.lee-memory-workbench' in CSS and '.lee-memory-target' in CSS
    assert '.lee-memory-note-empty[hidden] { display: none; }' in CSS
    assert '.lee-memory-note-card' in CSS and '.lee-memory-note-routes' in CSS


def test_agent_execution_ui_has_run_policies_previews_steering_and_state_memory():
    required = ("/agent/run-policy", "/agent/tool-preview", "/agent/retry-tool", "/agent/rollback-tool",
                "/agent/steer", "/agent/state/save", "/agent/state/load")
    from inspect import getsource
    from leela.app import ide_app
    source = getsource(ide_app)
    assert all(route in source for route in required)
    assert 'function proposalFields' in JS and 'function refreshProposalPreview' in JS
    assert 'function updateAgentRunstrip' in JS and 'function leeQueueSteer' in JS
    assert 'function retryProposal' in JS and 'function rollbackProposal' in JS
    assert 'function leeAgentState' in JS and 'data-ref="conversation"' in JS
    assert '.lee-agent-runstrip' in CSS and '.lee-agent-state-grid' in CSS

def test_tool_schema_only_marks_read_only_calls_as_rerunnable(tmp_path):
    from leela.app import _tool_schemas
    from leela.workspace import Workspace
    rows = {row['name']: row for row in _tool_schemas(Workspace(roots=[tmp_path]).ai)}
    assert rows['run_shell']['changes_state'] and not rows['run_shell']['retryable']
    assert not rows['view_file']['changes_state'] and rows['view_file']['retryable']

def test_checkpoints_and_response_revision_explain_consequences_in_plain_language():
    assert 'Nothing runs until you approve' in JS
    assert 'Nothing changes until you approve' in JS
    assert 'To run it again, ask the agent so you can review a new checkpoint.' in JS
    assert 'This result is not in the conversation yet.' in JS
    assert 'Use in next message' in JS
    assert 'You are correcting the conversation.' in JS
    assert 'Tools will not run again and files will not change.' in JS
    assert 'function editableResponse' in JS and 'decodeResponseEntities' in JS
    assert 'Edit what agent remembers' in JS and 'Use edited answer' in JS
    assert '.lee-revision-layout' in CSS and '.lee-checkpoint-result' in CSS

def test_agent_control_route_changes_checkpoint_policy_without_starting_a_model(tmp_path):
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.workspace import Workspace
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        r = client.post('/agent/control', json={'control': 'directed'})
        bad = client.post('/agent/control', json={'control': 'reckless'})
    assert r.json() == {'ok': True, 'control': 'directed'}
    assert ws.approvals.control == 'directed'
    assert bad.status_code == 400

def test_agent_and_variables_share_the_right_tabs_while_exec_and_terminal_share_the_bottom():
    from fasthtml.common import to_xml
    from leela.app import _shell
    from leela.blocks.term.term import TerminalGate
    from leela.workspace import Workspace
    html = to_xml(_shell(Workspace(roots=[]), TerminalGate()))
    assert 'lee-righttabs' in html and 'data-right="agent"' in html and 'data-right="vars"' in html
    assert 'lee-docktabs' in html and 'data-dock="exec"' in html and 'data-dock="term"' in html
    assert 'function leeRight(which)' in JS and "leeDock('exec')" in JS
    assert 'agentAttachments' in JS and '/agent/commands' in JS and "'/fs/find?q='" in JS



def test_terminal_has_mouse_resize_and_multiple_live_tabs():
    splits = JS[JS.index('function initSplits'):JS.index('async function refreshKernelPill')]
    terminal = JS[JS.index('function nextTermId'):JS.index('// The IDE follows')]
    assert "const dockSplit = $('.lee-dock-split')" in splits
    assert "localStorage.setItem('lee-agent-h'" in splits
    assert 'lee.terms.set(id, record)' in terminal
    assert 'function switchTerm' in terminal and 'function cycleTerm' in terminal
    assert '.lee-termtabs' in CSS and '.lee-termtab.active' in CSS
    assert '.lee-docktabs' in CSS and '.lee-bottomdock.dock-term .lee-agent' in CSS

def test_screen_capture_route_rejects_oversized_payloads_before_decoding(tmp_path):
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.workspace import Workspace
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as client:
        response = client.post('/screen', json={'data_url': 'data:image/png;base64,' + 'A' * 12_000_001})
    assert response.status_code == 413
    assert 'larger than 9 MB' in response.json()['error']


def test_one_static_prefix_serves_both_the_authored_and_vendored_asset_trees(tmp_path):
    "`/leestatic` spans `leela/static` and `leela/vendor` as if they were one folder."
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.workspace import Workspace
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as client:
        authored = client.get('/leestatic/lee-ide.css')
        vendored = client.get('/leestatic/lee-cm6.js')
        font = client.get('/leestatic/fonts/jetbrains-mono-latin-wght-normal.woff2')
        missing = client.get('/leestatic/no-such-asset.js')
    assert authored.status_code == vendored.status_code == font.status_code == 200
    assert b'@font-face' in authored.content and b'/leestatic/fonts/' in authored.content
    assert missing.status_code == 404


def test_selection_help_uses_summary_and_completion_jobs_without_editing(tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.workspace import Workspace
    ws = Workspace(roots=[tmp_path])
    calls = []
    class FakeAI:
        note = ''
        routing = type('Routing', (), {'name_for': lambda self, job: 'fake-' + job})()
        def summarise(self, text, sp): calls.append(('summary', text, sp)); return 'short summary'
        def oneshot(self, prompt, sp, job, max_tokens): calls.append((job, prompt, sp)); return 'rewritten text'
    ws._ai = FakeAI()
    with TestClient(ide_app(ws)) as client:
        summary = client.post('/complete/selection', json={'text': 'long source', 'mode': 'summary'}).json()
        rewrite = client.post('/complete/selection', json={'text': 'rough source', 'mode': 'instruction',
                                                            'instruction': 'make clearer', 'lang': 'markdown'}).json()
    assert summary['text'] == 'short summary' and summary['model'] == 'fake-summary'
    assert rewrite['text'] == 'rewritten text' and rewrite['model'] == 'fake-completion'
    assert [c[0] for c in calls] == ['summary', 'completion']

def test_untrusted_markdown_cannot_execute_raw_html(tmp_path):
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.workspace import Workspace
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as client:
        raw = '```{=html}\n<img src=x onerror=alert(1)>\n```'
        safe = client.post('/markdown/render', json={'text': raw, 'allow_raw': False}).json()['html']
        trusted = client.post('/markdown/render', json={'text': raw, 'allow_raw': True}).json()['html']
    assert 'onerror=' not in safe and 'language-html' in safe
    assert 'onerror=' in trusted


def test_model_discovery_does_not_block_shell_render_or_editor_mount():
    from leela.app import _agent_panel
    from leela.workspace import Workspace
    html = str(_agent_panel(Workspace(roots=[])))
    assert html.count('loading…') == 3
    boot = JS[JS.index('async function boot()'):JS.index("document.addEventListener('DOMContentLoaded'")]
    assert 'await loadAgentModels()' not in boot
    assert 'loadAgentModels().catch' in boot



def test_terminal_bundle_loads_only_when_the_terminal_opens():
    from leela.app import _asset, _shell
    from leela.blocks.term.term import TerminalGate
    from leela.workspace import Workspace
    html = str(_shell(Workspace(roots=[]), TerminalGate()))
    assert f'<script src="{_asset("lee-term.js")}">' not in html
    terminal = JS[JS.index('let termBundle'):JS.index('function leeTermExpand')]
    assert "document.createElement('script')" in terminal and 'await loadTermBundle()' in terminal



def test_prompt_cells_show_a_live_notice_and_render_server_markdown():
    assert 'id="model-${c.id}"' in JS
    assert 'role="status"' in JS and 'aria-live="polite"' in JS
    assert '●' in JS and 'Model is running' in JS and ' · ${seconds}s elapsed' in JS
    ask = JS[JS.index('async function askCell'):JS.index('/* ---------------------------------------------------------- running files */')]
    assert 'notice.hidden = false' in ask
    assert 'setInterval(tick, 1000)' in ask
    assert 'finally {' in ask and 'notice.hidden = true' in ask
    assert 'clearInterval(clock)' in ask
    assert '.lee-model-running[hidden] { display: none; }' in CSS
    assert '@keyframes lee-model-pulse' in CSS
    assert '@media (prefers-reduced-motion: reduce)' in CSS
    assert 'function renderMarkdown(el, text, allowRaw = false' in JS
    assert "fetch('/markdown/render'" in JS
    assert 'window.leeMarkdown' not in JS
    assert "renderMarkdown(reply, c.reply)" in JS
    assert "renderMarkdown(reply, raw)" in JS





def test_mdhtml_rendering_is_paste_safe_and_reports_unclosed_constructs():
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.workspace import Workspace
    with TestClient(ide_app(Workspace(roots=[]))) as client:
        response = client.post('/markdown/render', json={
            'text': '<style>body{display:none}</style>\n\n<script>alert(1)</script>\n\n# visible'})
        assert response.status_code == 200
        html = response.json()['html']
        assert '&lt;style&gt;' in html and '&lt;script&gt;' in html
        assert '<style>' not in html and '<script>' not in html
        assert '<h1>visible</h1>' in html

def test_mdhtml_keeps_explicit_html_passthrough_deliberate():
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.workspace import Workspace
    with TestClient(ide_app(Workspace(roots=[]))) as client:
        response = client.post('/markdown/render', json={'text': '```{=html}\n<kbd>explicit</kbd>\n```'})
        assert response.status_code == 200
        assert '<kbd>explicit</kbd>' in response.json()['html']

def test_agent_turn_has_a_live_one_line_progress_surface_and_one_line_tools():
    turn = JS[JS.index('function renderAgentStep'):JS.index('/* Reloading the open tab')]
    assert 'Model is working' in turn and 'Preparing context' in turn
    assert 'lee-agent-elapsed' in turn and 'setInterval' in turn
    assert 'lee-agent-step-copy' in turn and 'a.summary' in turn
    assert 'lee.agentBusy' in turn and 'progress.finish' in turn
    assert 'grid-template-columns: 30px minmax(0, 1fr) auto auto' in CSS
    assert '.lee-agent-progress-copy { display: flex; align-items: baseline' in CSS
    assert '.lee-agent-step-copy { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }' in CSS
    assert '@keyframes lee-agent-wave' in CSS


def test_markdown_code_uses_readonly_codemirror_and_only_python_can_promote():
    code = JS[JS.index('async function promoteCodeToNotebook'):JS.index('function renderMarkdown')]
    assert "nbEdit({op: 'insert'" in code and "cell_type:" in code
    assert "createEditor(editor, {doc:" in code and 'readOnly: true' in code
    assert 'promote to cell' in code and 'data-copy' in code
    assert "const python = /^(language-)?(py|python)$/" in code
    assert '!CODE_LANGS[named]' in code and 'text.length > 40000' in code
    assert "python && el.classList.contains('lee-reply')" in code
    assert '.lee-code-surface' in CSS and '.lee-code-editor .cm-editor' in CSS

def test_agent_markdown_can_become_an_editable_markdown_cell_and_hides_duplicate_tool_protocol():
    assert 'edit response as markdown cell' in JS
    assert "promoteCodeToNotebook(el.dataset.markdown, 'markdown')" in JS
    assert 'function upgradePortableToolMarkdown' in JS
    assert "if (!value || !('result' in value))" in JS
    assert "document.createElement('details')" in JS
    assert 'function polishActivityGroup' in JS and 'lee-activity-list' in JS
    assert 'function portableToolKind' in JS and 'compactPath(a.path)' in JS
    assert '.lee-activity-group' in CSS and '.lee-activity-list::before' in CSS
    assert '.lee-agent-step.kind-search .lee-agent-step-state' in CSS
    assert '.lee-reply {' in CSS and 'white-space: normal' in CSS






def test_history_groups_turns_by_context_session_without_rendering_every_turn():
    from leela.app import _history_sessions
    turns = [
        {'session': 'agent-a', 'at': 10, 'prompt': 'one'},
        {'session': 'agent-a', 'at': 20, 'prompt': 'two'},
        {'session': 'agent-b', 'at': 30, 'prompt': 'three'},
    ]
    groups = _history_sessions(turns, [{'id': 'agent-a', 'code': 4}])
    assert [g['id'] for g in groups] == ['agent-b', 'agent-a']
    assert groups[0]['models'] == [] and groups[1]['models'] == []
    assert [x['prompt'] for x in groups[1]['turns']] == ['one', 'two']
    assert groups[1]['context_continues'] and groups[1]['code'] == 4
    history = JS[JS.index('async function showHistorySession'):JS.index('function renderSessionCells')]
    assert "renderTurns(log, group.turns || [], 'conversation')" in history
    assert 'groups.find' in history
    assert "(s.models || []).map" in history

def test_routing_popover_closes_on_outside_click_and_escape():
    from leela.app import _agent_panel
    from leela.workspace import Workspace
    html = str(_agent_panel(Workspace(roots=[])))
    assert 'lee-dismissable' in html
    assert "details.lee-dismissable[open]" in JS
    assert "document.addEventListener('pointerdown'" in JS
    assert "e.key !== 'Escape'" in JS and 'open.open = false' in JS

def test_agent_pane_has_model_history_and_expand_controls():
    from leela.app import _agent_panel
    from leela.workspace import Workspace
    html = str(_agent_panel(Workspace(roots=[])))
    assert 'agentmodel' in html and 'leeAgentModel' in html
    assert 'localmultimodal' in html and 'leeLocalMultimodal' in html
    assert 'leeAgentHistory' in html and 'leeAgentExpand' in html
    assert html.count('>transcript</button>') == 0
    assert '/agent/history' in JS and 'function renderSessionCells' in JS
    assert 'function showHistorySession' in JS and 'context continued across these turns' in JS
    assert 'lee-session-code' in JS and '.lee-history-index' in CSS
    assert 'agent-expanded' in CSS and 'lee-dock-split' in JS
    assert 'id="agentprompt"' in html and '<textarea' in html
    assert 'centreHeight() - 240' in JS and 'Math.min(900' in JS
    assert 'lee-history-select' in JS and '.lee-history-heading' in CSS

def test_agent_state_refresh_uses_current_project_evidence(tmp_path):
    from leela.app import _project_state_context
    from leela.workspace import Workspace
    (tmp_path/'pyproject.toml').write_text('[project]\nname = "current-code"\n')
    (tmp_path/'module.py').write_text('def current_api():\n    return 1\n')
    context = _project_state_context(Workspace(roots=[tmp_path]))
    assert 'pyproject.toml' in context and 'module.py' in context and 'current-code' in context
    assert 'Refresh from code' in JS
    assert '<current-project>' in SERVER


def test_model_picker_shows_older_models_by_default(monkeypatch):
    from starlette.testclient import TestClient
    from leela.agent import core as models
    from leela.app import _agent_panel, ide_app
    from leela.workspace import Workspace
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    monkeypatch.setattr(models, '_oai_cache', (float('inf'), ['gpt-4.1', 'gpt-5.6-luna']))
    ws = Workspace(roots=[])
    assert 'id="legacymodels"' in str(_agent_panel(ws)) and 'checked' in str(_agent_panel(ws))
    with TestClient(ide_app(ws)) as client:
        values = {row['value'] for row in client.get('/agent/models').json()['models']}
    assert 'openai/gpt-4.1' in values

def test_model_selector_endpoint_exposes_sources_not_secrets(monkeypatch):
    from starlette.testclient import TestClient
    from leela.agent import core as models
    from leela.app import ide_app
    from leela.workspace import Workspace
    monkeypatch.setenv('OPENAI_API_KEY', 'top-secret')
    monkeypatch.setattr(models, '_oai_cache', (float('inf'), ['gpt-5.4']))
    with TestClient(ide_app(Workspace(roots=[]))) as client:
        data = client.get('/agent/models').json()
    assert any(m['value'] == 'openai/gpt-5.4' for m in data['models'])
    assert data['auth']['openai']['source'] == 'OPENAI_API_KEY'
    assert 'top-secret' not in str(data)

def test_every_model_choice_is_saved_and_restored(tmp_path):
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.workspace import Workspace
    path = tmp_path/'workspace.json'
    ws = Workspace(roots=[]); ws._state_path = path
    with TestClient(ide_app(ws)) as client:
        assert client.post('/agent/model', json={'target': 'agent', 'model': 'gemma-12b'}).json()['ok']
        assert client.post('/agent/model', json={'target': 'inline', 'model': 'gemma-e2b'}).json()['ok']
        assert client.post('/agent/model', json={'target': 'completion', 'model': 'gemma-e4b'}).json()['ok']
    restored = Workspace.load(path)
    assert (restored.model, restored.inline_model, restored.completion_model) == ('gemma-12b', 'gemma-e2b', 'gemma-e4b')


def test_configured_agent_does_not_offer_setup_again():
    from leela.app import _agent_panel
    from leela.workspace import Workspace
    ws = Workspace(roots=[])
    ws.agent_state_layers['project']['text'] = '# Goal\n\nMaintain this project.'
    html = str(_agent_panel(ws))
    assert 'state active' in html
    assert 'Set up agent state' not in html

def test_agent_memory_api_selects_notes_per_surface_and_rebriefs(tmp_path):
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.workspace import Workspace
    ws = Workspace(roots=[tmp_path]); ws._state_path = tmp_path/'workspace.json'
    with TestClient(ide_app(ws)) as client:
        saved = client.post('/agent/memory/save', json={
            'title': 'Completion conventions', 'text': 'Prefer pathlib and preserve public APIs.',
            'targets': ['agent', 'inline', 'completion']}).json()
        note_id = saved['id']
        data = client.get('/agent/memory').json()
    assert data['selected'] == {'agent': [note_id], 'inline': [note_id], 'completion': [note_id]}
    assert data['notes'][0]['text'] == 'Prefer pathlib and preserve public APIs.'
    assert 'Prefer pathlib' in ws.ai.system_prompt()
    assert 'Prefer pathlib' in ws.inline_ai.system_prompt()
    assert '<user_memory>' in ws.completer._prompt('x = ', 4, 'python')

def test_local_multimodal_setting_is_persisted_from_the_ui(tmp_path):
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.workspace import Workspace
    ws = Workspace(roots=[])
    ws._state_path = tmp_path/'workspace.json'
    with TestClient(ide_app(ws)) as client:
        data = client.post('/agent/settings', json={'local_multimodal': True}).json()
    assert data['ok'] and ws.local_multimodal is True
    assert ws._state_path.read_json()['local_multimodal'] is True


def _nb(path, source):
    path.write_text(json.dumps({'nbformat': 4, 'nbformat_minor': 5, 'metadata': {}, 'cells': [{
        'cell_type': 'code', 'source': source, 'metadata': {}, 'outputs': [],
        'execution_count': None, 'id': path.stem,
    }]}))

def test_explicit_reload_invalidates_the_notebook_cache_and_reads_agent_changes(tmp_path):
    a = tmp_path/'a.ipynb'; _nb(a, 'value = "before"')
    ws = Workspace(roots=[tmp_path]); ws.open(a)
    with TestClient(ide_app(ws)) as client:
        assert client.get('/tab/state').json()['cells'][0]['source'] == 'value = "before"'
        _nb(a, 'value = "agent edit"')
        assert client.get('/tab/state').json()['cells'][0]['source'] == 'value = "before"'
        assert client.post('/tab/reload', json={'path': str(a)}).json()['ok']
        assert client.get('/tab/state').json()['cells'][0]['source'] == 'value = "agent edit"'





def test_browser_watch_detects_an_external_file_write(tmp_path):
    a = tmp_path/'a.py'; a.write_text('before = True\n')
    ws = Workspace(roots=[tmp_path]); ws.open(a)
    with TestClient(ide_app(ws)) as client:
        before = client.get('/tab/watch').json()
        a.write_text('after = True\n')
        after = client.get('/tab/watch').json()
    assert before['path'] == str(a)
    assert before['disk_version'] != after['disk_version']
    assert 'setInterval(watchOpenFile, 1000)' in JS
    watch = JS[JS.index('async function watchOpenFile'):JS.index('async function takeDiskVersion')]
    assert "classList.contains('dirty')" in watch and 'await takeDiskVersion(lee.path)' in watch

def test_same_named_files_in_different_roots_keep_absolute_identity(tmp_path):
    one,two=tmp_path/'ramabana',tmp_path/'rishi';one.mkdir();two.mkdir()
    a,b=one/'00_core.ipynb',two/'00_core.ipynb';_nb(a,'RAMABANA');_nb(b,'RISHI')
    ws=Workspace(roots=[one,two])
    with TestClient(ide_app(ws)) as client:
        client.post('/tab/open',params={'path':str(a)})
        client.post('/tab/open',params={'path':str(b)})
        assert client.get('/tab/state').json()['cells'][0]['source']=='RISHI'
        client.post('/tab/open',params={'path':str(a)})
        assert client.get('/tab/state').json()['cells'][0]['source']=='RAMABANA'
    assert len(ws.tabs)==2 and {t.path for t in ws.tabs}=={str(a.resolve()),str(b.resolve())}
    from fasthtml.common import to_xml
    from leela.app import _tab_bar
    tabs=to_xml(_tab_bar(ws));assert 'ramabana/00_core.ipynb' in tabs and 'rishi/00_core.ipynb' in tabs
    assert 'leeOpenFile' in JS and 'pendingFocusPath === st.path' in JS
    assert 'version!==openFileVersion' in JS and "mountTab(path)" in JS

def test_split_state_reads_an_inactive_file_without_changing_active_tab(tmp_path):
    a,b=tmp_path/'a.py',tmp_path/'b.py';a.write_text('A');b.write_text('B')
    ws=Workspace(roots=[tmp_path]);ws.open(a);ws.open(b);ws.activate(0)
    with TestClient(ide_app(ws)) as client:
        state=client.get('/tab/state',params={'path':str(b)}).json()
    assert state['text']=='B' and ws.tab.path==str(a.resolve())
    assert 'function leeSplit' in JS and 'mountSecondary' in JS and 'lee-editor-split' in JS

def test_tab_state_reuses_the_live_notebook_instead_of_reloading_disk(tmp_path):
    a, b = tmp_path/'a.ipynb', tmp_path/'b.py'
    _nb(a, 'value = "live buffer"')
    b.write_text('pass\n')
    ws = Workspace(roots=[tmp_path]); ws.open(a)
    with TestClient(ide_app(ws)) as client:
        assert client.get('/tab/state').json()['cells'][0]['source'] == 'value = "live buffer"'
        client.post('/tab/open', params={'path': str(b)})
        _nb(a, 'value = "changed on disk"')
        client.post('/tab/select', params={'i': 0})
        assert client.get('/tab/state').json()['cells'][0]['source'] == 'value = "live buffer"'

def test_remove_root_route_never_deletes_the_folder(tmp_path):
    root = tmp_path/'project'; root.mkdir(); kept = root/'keep.py'; kept.write_text('x = 1\n')
    ws = Workspace(roots=[root])
    with TestClient(ide_app(ws)) as client:
        assert client.post('/fs/remove-root', json={'path': str(root)}).json()['ok']
    assert root.exists() and kept.read_text() == 'x = 1\n'
    assert root not in ws.fs.roots


def test_save_refuses_to_overwrite_a_disk_change_after_the_draft_started(tmp_path):
    a = tmp_path/'a.py'; a.write_text('before = True\n')
    ws = Workspace(roots=[tmp_path]); ws.open(a)
    with TestClient(ide_app(ws)) as client:
        state = client.get('/tab/state').json()
        client.post('/tab/buffer', json={'path': str(a), 'kind': 'text', 'text': 'browser = True\n',
                                         'base_disk_version': state['disk_version']})
        a.write_text('external = True\n')
        refused = client.post('/nb/save', json={'text': 'browser = True\n',
                                                'base_disk_version': state['disk_version']})
        assert refused.status_code == 409
        assert a.read_text() == 'external = True\n'
        forced = client.post('/nb/save', json={'text': 'browser = True\n',
                                               'base_disk_version': state['disk_version'], 'force': True})
        assert forced.status_code == 200
    assert a.read_text() == 'browser = True\n'

def test_unsaved_text_file_buffer_survives_a_tab_round_trip(tmp_path):
    a, b = tmp_path/'a.py', tmp_path/'b.py'
    a.write_text('disk = True\n'); b.write_text('pass\n')
    ws = Workspace(roots=[tmp_path]); ws.open(a)
    with TestClient(ide_app(ws)) as client:
        client.get('/tab/state')
        client.post('/tab/buffer', json={'path': str(a), 'kind': 'text', 'text': 'unsaved = True\n'})
        client.post('/tab/open', params={'path': str(b)})
        client.post('/tab/select', params={'i': 0})
        assert client.get('/tab/state').json()['text'] == 'unsaved = True\n'
    assert a.read_text() == 'disk = True\n'

def test_save_all_persists_inactive_tab_buffers(tmp_path):
    a, b = tmp_path/'a.py', tmp_path/'b.py'
    a.write_text('old_a = True\n'); b.write_text('old_b = True\n')
    ws = Workspace(roots=[tmp_path]); ws.open(a); ws.open(b)
    with TestClient(ide_app(ws)) as client:
        client.get('/tab/state')
        client.post('/tab/buffer', json={'path': str(a), 'kind': 'text', 'text': 'new_a = True\n'})
        client.post('/tab/buffer', json={'path': str(b), 'kind': 'text', 'text': 'new_b = True\n'})
        response = client.post('/tabs/save-all')
        assert response.status_code == 200 and response.json()['saved'] == 2
    assert a.read_text() == 'new_a = True\n'
    assert b.read_text() == 'new_b = True\n'




def test_cell_runs_carry_document_and_cell_identity_and_reject_stale_positions(tmp_path):
    notebook = tmp_path/'ordered.ipynb'; _nb(notebook, 'class Definition: pass')
    ws = Workspace(roots=[tmp_path]); ws.open(notebook)
    with TestClient(ide_app(ws)) as client:
        state = client.get('/tab/state').json()
        response = client.post('/nb/run/stream', json={
            'path': str(notebook), 'i': 0, 'id': 'a-cell-that-moved', 'source': 'pass',
        })
    assert response.status_code == 409
    assert 'id: cellId' in JS and "path: runPath || lee.tabKey || ''" in JS

def test_a_tab_can_be_dragged_to_a_new_position_and_the_same_document_stays_active(tmp_path):
    "The strip is the user's arrangement of their own work, so the order is server state."
    a, b, c = (tmp_path/f'{n}.py' for n in 'abc')
    for p in (a, b, c): p.write_text('x = 1\n')
    ws = Workspace(roots=[tmp_path])
    for p in (a, b, c): ws.open(p)
    ws.activate(0)
    with TestClient(ide_app(ws)) as client:
        assert client.post('/tab/move?i=0&j=2').status_code == 200
    assert [t.title for t in ws.tabs] == ['b.py', 'c.py', 'a.py']
    assert ws.tab.title == 'a.py', 'the dragged tab is still the one being edited'

def test_moving_a_tab_nowhere_or_out_of_range_is_a_no_op(tmp_path):
    a, b = (tmp_path/f'{n}.py' for n in 'ab')
    for p in (a, b): p.write_text('x = 1\n')
    ws = Workspace(roots=[tmp_path])
    for p in (a, b): ws.open(p)
    before = list(ws.tabs)
    ws.move_tab(1, 1); ws.move_tab(9, 0); ws.move_tab(0, 9)
    assert [t.title for t in ws.tabs] == [t.title for t in ([before[1], before[0]])], 'only the clamped move applied'

def test_middle_click_closes_a_tab_the_way_a_browser_does():
    assert "document.addEventListener('auxclick'" in JS
    aux = JS[JS.index("document.addEventListener('auxclick'"):]
    aux = aux[:aux.index("document.addEventListener('dragstart'")]
    assert 'e.button !== 1' in aux, 'middle button only'
    assert 'closeTerm(term.dataset.term)' in aux, 'terminal tabs too'
    assert 'closeTab(+tab.dataset.i)' in aux
    assert 'e.preventDefault()' in aux, 'button 1 pastes or autoscrolls otherwise'

def test_the_tab_menu_offers_the_bulk_closes_and_they_run_right_to_left():
    from leela.blocks.keys.menus import MENUS
    actions = [i.action for i in MENUS['tab']]
    assert actions[-3:] == ['close_others', 'close_right', 'close_saved']
    body = JS[JS.index('async function closeTabs('):JS.index('function moveTab(')]
    assert '.reverse()' in body, 'tabs are addressed by index; close the highest first'
    assert "await htmxPost('/tab/close?i=' + i)" in body, 'each swap is awaited'
    assert 'dataset.gitDiff' in body, 'browser-only diff tabs are not server tabs'
    assert 'confirmDialog' in body, 'unsaved work is still asked about'


def _notebook(path):
    path.write_text(json.dumps({'nbformat': 4, 'nbformat_minor': 5, 'metadata': {}, 'cells': [
        {'cell_type': 'code', 'source': f'value_{i} = {i}', 'metadata': {}, 'outputs': [],
         'execution_count': None, 'id': f'cell-{i}'} for i in range(12)
    ]}))

def test_type_change_accepts_all_live_sources_in_one_request(tmp_path):
    p = tmp_path/'work.ipynb'; _notebook(p)
    ws = Workspace(roots=[tmp_path]); ws.open(p)
    with TestClient(ide_app(ws)) as client:
        client.get('/tab/state')
        sources = [{'i': i, 'source': f'edited_{i} = {i}'} for i in range(12)]
        d = client.post('/nb/edit', json={'op': 'type', 'i': 7, 'cycle': True,
                                          'sources': sources}).json()
    assert d['cells'][7]['cell_type'] == 'markdown'
    assert d['cells'][0]['source'] == 'edited_0 = 0'
    assert d['cells'][11]['source'] == 'edited_11 = 11'

def test_structural_edits_preserve_scroll_selection_cursor_and_visual_anchor():
    edit = JS[JS.index('async function nbEdit'):JS.index('async function toggleComment')]
    assert 'scrollTop = host?.scrollTop' in edit
    assert 'selectedId = lee.cells[lee.sel]?.id' in edit
    assert 'host.scrollTop = scrollTop' in edit
    assert 'anchored.getBoundingClientRect().top - anchor.top' in edit
    assert 'LeeCM.setCursor' in edit
    assert 'patchNotebook(host, before, r.cells, d.op)' in edit
    assert "{...d, sources: cur}" in edit


def test_cell_clipboard_survives_tabs_and_pastes_full_cells_with_new_ids(tmp_path):
    actions = JS[JS.index('const ACTIONS'):JS.index("for (let i = 1")]
    clipboard = JS[JS.index('function cellClipboardPayload'):JS.index('async function moveCellTo')]
    assert 'cell_copy: () => copyCell(lee.sel)' in actions
    assert 'more cell actions' in JS and "openMenu('cell'" in JS
    assert 'cell_cut: () => cutCell(lee.sel)' in actions
    assert 'cell_paste_above: () => pasteCell(lee.sel)' in actions
    assert 'lee.cellClipboard = {cells, cell: cells[0], from:' in clipboard
    assert "op: 'paste_many'" in clipboard and "op: 'delete_many'" in clipboard
    assert "op: 'paste_many'" in clipboard and 'LeeCM.getDoc(view)' in clipboard
    a = tmp_path/'a.ipynb'; b = tmp_path/'b.ipynb'; _notebook(a); _notebook(b)
    ws = Workspace(roots=[tmp_path]); ws.open(a)
    with TestClient(ide_app(ws)) as client:
        client.get('/tab/state')
        payload = client.post('/nb/edit', json={'op': 'paste', 'i': 1, 'cell': {
            'source': 'moved = True', 'cell_type': 'code', 'id': 'old-id',
            'outputs': [{'output_type': 'stream', 'text': 'yes\n'}], 'execution_count': 4,
        }}).json()
    pasted = payload['cells'][1]
    assert pasted['source'] == 'moved = True' and pasted['outputs'][0]['text'] == 'yes\n'
    assert pasted['id'] != 'old-id' and pasted['running'] is False


def test_exec_newline_and_file_tree_parent_are_real_actions_not_noops():
    actions = JS[JS.index('const ACTIONS'):JS.index("for (let i = 1")]
    assert "LeeCM.insert(v, '\\n')" in actions
    assert 'up_dir:       treeCollapse' in actions
    tree = JS[JS.index('function treeCollapse'):JS.index('async function refreshFileTree')]
    assert "closest('.lee-node.lee-dir')" in tree
    assert 'exec_newline: () => {}' not in actions
    assert 'up_dir:       () => {}' not in actions

def test_range_and_cell_structure_actions_are_reachable_from_the_shared_dispatch():
    actions = JS[JS.index('const ACTIONS'):JS.index("for (let i = 1")]
    assert "run_above:    () => runRange(0, lee.sel" in actions
    assert "run_below:    () => runRange(lee.sel" in actions
    for op in ('duplicate', 'merge_above', 'merge_below', 'clear_cell'):
        assert f"op: '{op}'" in actions
    range_run = JS[JS.index('async function runRange'):JS.index('async function restartRunAll')]
    assert "c.cell_type !== 'code'" in range_run
    assert 'o.output_type === \'error\'' in range_run

def test_cell_controls_form_an_attached_header_above_the_editor_not_an_overlay():
    cell = JS[JS.index('function cellEl'):JS.index('async function moveCellTo')]
    assert '<div class="lee-cell-chrome">' in cell
    assert '<div class="lee-cellmain"><div class="lee-cell-chrome">' in cell
    assert cell.index('lee-model-running') < cell.index('lee-cellbtns') < cell.index('lee-cm')
    chrome_start = CSS.index('.lee-cell-chrome {\n  position: relative')
    chrome = CSS[chrome_start:CSS.index('.lee-cell-state {', chrome_start)]
    assert 'position: relative' in chrome and 'width: 100%' in chrome
    assert 'border-bottom: 0' in chrome and 'border-radius: 5px 5px 0 0' in chrome
    assert 'position: absolute' not in chrome








def test_cell_chrome_shows_live_and_last_execution_time():
    cell = JS[JS.index('function setCellState'):JS.index('/* The per-cell controls')]
    run = JS[JS.index('async function runCell'):JS.index('/* Running a prompt cell')]
    prompt = JS[JS.index('async function askCell'):JS.index('/* ---------------------------------------------------------- running files */')]
    assert 'function formatCellTime' in cell and 'function setCellTime' in cell
    assert 'id="time-${c.id}"' in JS and 'execution_ms' in JS
    assert 'setInterval(() => setCellTime' in run and 'clearInterval(cellClock)' in run
    assert 'setCellTime(c, elapsed, true)' in prompt


def test_a_changed_notebook_cell_carries_the_same_mark_a_changed_file_line_does():
    "PyCharm-style: a thin bar at the start of the work that differs from the commit."
    assert "api('/git/notebook?path='" in JS, 'the marks come from git, not from the buffer'
    paint = JS[JS.index('function repaintNotebookGitMarks()'):]
    paint = paint[:paint.index('\n}\n') + 2]
    assert "el.classList.toggle('changed'" in paint and "el.classList.toggle('changed-added'" in paint
    assert 'lee.notebookGit' in paint, 'repainting a reordered cell must not refetch'
    assert 'LeeCM.setChangedLines(view, lines[el.dataset.id] || [])' in paint
    mount = JS[JS.index('function mountCell('):JS.index('function renderOutputs')]
    assert "changedLines: (lee.notebookGit?.lines || {})[c.id] || []" in mount, \
        'a cell mounted after the marks arrived is still marked'
    assert 'repaintNotebookGitMarks();' in JS[JS.index('function patchNotebook('):JS.index('function ensureCellMounted(')]
    assert 'paintNotebookGitMarks();' in JS[JS.index('function mountNotebook('):JS.index('function patchNotebook(')]
    assert '.lee-cell.changed .lee-cellmain' in CSS and '.lee-cell.changed-added .lee-cellmain' in CSS

def test_a_notebook_gets_its_own_overview_stripe_on_the_page_scrollbar():
    "A file's stripe belongs to CodeMirror; a notebook scrolls as a page of cells."
    stripe = JS[JS.index('function paintNotebookOverview()'):JS.index('let nbOverviewFrame')]
    assert 'lee.notebookGit?.cells' in stripe, 'uncommitted cells are the bars'
    assert "$('.lee-cell-state.error', el)" in stripe, 'failed runs are the ticks'
    assert 'host.scrollTop' in stripe and 'host.clientHeight' in stripe, 'and the viewport is the thumb'
    assert 'host.scrollHeight > host.clientHeight + 4' in stripe, \
        'a notebook that already fits keeps its scrollbar'
    assert 'box.right - stageBox.left - NB_OVERVIEW_W' in stripe, 'measured, so a split lands right'
    assert '.lee-editor.has-overview { scrollbar-width:none; }' in CSS, 'it takes the scrollbar’s place'
    assert "if (e.target?.id === 'editor') queueNotebookOverview();" in JS
    assert "addEventListener('resize', queueNotebookOverview)" in JS
    assert 'queueNotebookOverview();' in JS[JS.index('function setCellState'):JS.index('function markPreviousRuns')]


def test_workspace_hub_dispatches_by_localhost_subdomain():
    seen = []
    async def app_a(scope, receive, send): seen.append(('a', scope['leela.workspace_id']))
    async def app_b(scope, receive, send): seen.append(('b', scope['leela.workspace_id']))
    hub = WorkspaceHub([WorkspaceSite('alpha', 'Alpha', '/a', app_a),
                        WorkspaceSite('beta', 'Beta', '/b', app_b)], 5001)
    scope = {'type': 'http', 'headers': [(b'host', b'beta.localhost:5001')]}
    asyncio.run(hub(scope, Mock(), Mock()))
    assert seen == [('b', 'beta')]
    assert hub.catalog()[0]['url'] == 'http://alpha.localhost:5001/'

def test_workspace_hub_rejects_unknown_hosts_instead_of_opening_default_workspace():
    called, messages = [], []
    async def app(scope, receive, send): called.append(scope)
    async def send(message): messages.append(message)
    hub = WorkspaceHub([WorkspaceSite('alpha', 'Alpha', '/a', app)], 5001)
    scope = {'type': 'http', 'headers': [(b'host', b'attacker.example:5001')]}
    asyncio.run(hub(scope, Mock(), send))
    assert not called
    assert messages[0]['status'] == 421

def test_loopback_guard_rejects_dns_rebinding_and_cross_site_browser_requests():
    called = []
    async def app(scope, receive, send): called.append(scope)
    async def run(headers):
        messages = []
        async def send(message): messages.append(message)
        await LoopbackHostGuard(app)({'type': 'http', 'headers': headers}, Mock(), send)
        return messages
    rebound = asyncio.run(run([(b'host', b'attacker.example:5001')]))
    cross_site = asyncio.run(run([(b'host', b'localhost:5001'),
                                  (b'origin', b'https://attacker.example'),
                                  (b'sec-fetch-site', b'cross-site')]))
    assert rebound[0]['status'] == cross_site[0]['status'] == 421
    assert not called

def test_runtime_broker_refuses_a_thirteenth_heap_without_evicting_live_state(monkeypatch):
    broker = RuntimeBroker(max_kernels=1)
    pool = KernelPool(broker=broker)
    alive = Mock(alive=True, pid=42, kernel_kind='ipykernel', cwd='/project')
    pool.kernels['first'] = alive
    with pytest.raises(RuntimeError, match='kernel limit reached'):
        asyncio.run(broker.admit(pool, 'second'))
    assert pool.kernels['first'] is alive
