"""Browser IDE ergonomics: project runtimes, movement, terminal sizing and run gestures."""

from pathlib import Path

from leela.blocks.runtime.kernels import bootstrap_src, project_python
from leela.workspace import Workspace

ROOT = Path(__file__).resolve().parents[1]
from tests.assets import JS, CSS, EDITOR


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
    """"Apply to" defaults to All languages, and a language scope is only ever chosen explicitly.

    It used to default to `curLang()`, so opening settings with a .py file focused preselected
    Python; saving then remembered that choice, and every later edit was written to
    `languages.python`. The writes succeeded, but the editor reads global preferences with no
    language, so they looked like they reverted on the next restart.
    """
    body = JS[JS.index('async function editorSettings'):][:1200]
    block = body[:body.index('const rememberedScope')]
    code = '\n'.join(l for l in block.splitlines() if not l.strip().startswith('//'))
    assert "localStorage.getItem('lee-settings-language-scope')" in code   # an explicit choice persists
    assert "remembered!==null?remembered:''" in code                       # otherwise: all languages
    assert 'curLang' not in code                                           # never inferred from the tab


def test_inspector_support_is_appended_inside_the_project_kernel():
    src = bootstrap_src()
    assert 'sys.path.append(_p)' in src
    assert 'import dhrishti.serving as ls' in src
    assert src.index('sys.path.append(_p)') < src.index('import dhrishti.serving as ls')


def test_one_router_owns_platform_mod_and_derives_context_from_focus():
    assert "window.addEventListener('keydown'" in JS
    assert "const wantMeta = !!c.mod && MAC" in JS
    assert 'function eventContext(e)' in JS
    assert "inPath('#agentprompt, .lee-agent')" in JS
    assert "inPath('#execbox, .lee-exec')" in JS
    assert 'function cmBinds' not in JS


def test_exec_and_variables_can_switch_to_the_persistent_agent_session():
    from leela.app import _vars_panel
    from leela.workspace import Workspace
    html = str(_vars_panel(Workspace(roots=[])))
    assert '>agent</button>' in html and 'leeScope("agent")' in html
    assert "lee.execScope === 'live' ? 'agent' : 'live'" in JS
    assert "protected agent session" in JS


def test_identical_variable_polls_do_not_rebuild_the_dom():
    refresh = JS[JS.index('async function refreshVars'):JS.index('function varRow')]
    assert 'lee.varFingerprints.get(runtime) === fingerprint' in refresh
    assert 'lee.varFingerprints.set(runtime, fingerprint)' in refresh


def test_run_and_advance_reveals_the_next_cell_in_the_outer_scroller():
    focus = JS[JS.index('function focusCell'):JS.index('function markDirty')]
    assert "scrollIntoView({block: 'nearest'" in focus
    assert 'requestAnimationFrame' in focus


def test_missing_kernel_support_can_be_installed_from_the_picker():
    picker = JS[JS.index('async function pickKernel'):JS.index('/* ---------------------------------------------------------- the keymap')]
    assert "post('/runtime/support', {python: o.python})" in picker
    assert 'installing ipykernel and ipymini with uv' in picker
    assert "return pickKernel()" in picker


def test_switching_runtime_does_not_destroy_existing_terminal_tabs():
    picker = JS[JS.index('async function pickKernel'):JS.index('/* ---------------------------------------------------------- the keymap')]
    assert '.dispose()' not in picker
    assert "post('/term/close" not in picker


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


def test_codemirror_navigation_extensions_are_optional_live_preferences():
    editor = EDITOR
    assert 'function overviewPlugin' in editor and 'const stickyPlugin' in editor
    assert "'editor','overviewMode'" in JS and "'editor','stickyNavigation'" in JS


def test_the_overview_is_the_scrollbar_marked_up_rather_than_a_picture_of_the_text():
    """A compressed image of the letters answers no question you can act on.

    What a full-file view is for is where the problems and the changes are, so the stripe
    carries a tick per diagnostic and a bar per uncommitted line -- and it takes the
    scrollbar's place rather than sitting beside it, so there is never a second thing to
    scroll or two bars down one edge.
    """
    stripe = EDITOR[EDITOR.index('function overviewPlugin'):EDITOR.index('const stickyPlugin')]
    assert 'forEachDiagnostic(this.view.state' in stripe, 'ticks come from the real diagnostics'
    assert 'this.view.state.field(changesField, false)' in stripe, 'bars come from the git marks'
    assert 'cm-lee-change-(\\w+)' in stripe, 'a change bar is coloured by its kind'
    assert 's.scrollTop =' in stripe and 'pointermove' in stripe, 'it scrolls, and it drags'
    assert 'viewportLineBlocks' in stripe, 'and it says where you are'
    assert 'scrollbar-width: none' in CSS and '.cm-lee-has-overview .cm-scroller' in CSS
    assert 'cm-lee-minimap' not in CSS, 'the old canvas is gone, not merely hidden'


def test_the_overview_setting_carries_its_two_older_names_forward():
    "A stored preference must not silently reset because the feature was renamed twice."
    prefs = JS[JS.index('function readEditorPrefs'):JS.index('lee.editorPrefs = readEditorPrefs()')]
    assert "if ('minimap' in old && !old.minimapMode)" in prefs
    assert 'if (old.minimapMode && !old.overviewMode) old.overviewMode = old.minimapMode;' in prefs
    assert 'settings.overviewMode || settings.minimapMode' in EDITOR, 'and on the editor side too'


def test_codemirror_merge_view_is_used_for_external_file_conflicts():
    editor = EDITOR
    assert 'MergeView' in editor and 'export function createMerge' in editor
    assert 'function openMergeConflict' in JS and 'data-save-merge' in JS
    assert 'Resolve notebook conflict' in JS and 'data-cell-merge' in JS
    assert '/tab/disk?path=' in JS


def test_run_configuration_workbench_edits_environment_without_putting_secrets_in_browser_storage():
    assert 'function editRuns()' in JS and 'data-run-env-file' in JS and 'data-env-key' in JS
    assert 'Secret values belong in an ignored .env.local file' in JS


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


def test_appending_agent_status_does_not_reparse_and_detach_existing_actions():
    log = JS[JS.index('function agentLog'):JS.index('/* A write pauses')]
    assert "insertAdjacentHTML('beforeend', html)" in log
    assert 'log.innerHTML +=' not in log


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


def test_research_can_promote_a_source_or_digest_into_an_editable_agent_memory_note():
    research = JS[JS.index('function researchWorkspace'):JS.index('function webSearch')]
    assert 'Add to agent memory' in research and "leeNewMemoryNote({title:" in research
    assert 'data-new-thought' in research and 'New research note' in research
    assert 'Markdown scratchpad' in research and 'edit and choose model routing before saving' in research


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


def test_terminal_can_expand_and_refits_its_pty():
    assert 'function leeTermExpand()' in JS
    assert 'lee.term?.refit()' in JS
    assert '.lee-centre.term-expanded .lee-bottomdock' in CSS
    assert '.lee-centre.agent-expanded .lee-editor, .lee-centre.term-expanded .lee-editor' in CSS


def test_lower_panels_cannot_consume_the_editor():
    assert '.lee-editor-stage { position:relative; flex:1 1 auto; min-height:240px' in CSS
    assert 'max-height: min(900px, calc(100% - 240px))' in CSS
    assert 'const limit = () => Math.min(900, Math.max(110, centreHeight() - 240))' in JS
    assert "['exec-h', 80]" in JS and "['agent-h', 110]" in JS


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


def test_editor_keeps_replaced_triple_quotes_paired():
    src=EDITOR
    assert 'pairedTripleQuotes' in src and 'transactionFilter' in src
    assert (ROOT/'leela/vendor/lee-cm6.js').stat().st_size > 100_000


def test_one_static_prefix_serves_both_the_authored_and_vendored_asset_trees(tmp_path):
    """`/leestatic` spans `leela/static` and `leela/vendor` as if they were one folder.

    Splitting them must not change a single asset URL. The font is the case that matters:
    `lee-ide.css` names `/leestatic/fonts/*.woff2` from the authored tree, but the file itself
    now lives in the vendored one, so a mount that could not fall through would 404 it.
    """
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


def test_inline_model_calls_explain_their_progress():
    assert 'checking Kosha graph, then asking the completion model' in JS
    assert 'asking the inline model to rewrite the selection' in JS
    assert 'review before replacing' in JS


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


def test_rendering_markdown_does_not_hide_its_editor():
    run = JS[JS.index('async function runCell'):JS.index('async function askCell')]
    assert "renderMarkdown(out.querySelector('.lee-md'), src, true)" in run
    assert "style.display = 'none'" not in run


def test_model_discovery_does_not_block_shell_render_or_editor_mount():
    from leela.app import _agent_panel
    from leela.workspace import Workspace
    html = str(_agent_panel(Workspace(roots=[])))
    assert html.count('loading…') == 3
    boot = JS[JS.index('async function boot()'):JS.index("document.addEventListener('DOMContentLoaded'")]
    assert 'await loadAgentModels()' not in boot
    assert 'loadAgentModels().catch' in boot


def test_opening_the_ide_does_not_warm_a_local_model():
    boot = JS[JS.index('async function boot()'):JS.index("document.addEventListener('DOMContentLoaded'")]
    assert '/complete/warm' not in boot


def test_notebook_editors_mount_lazily_near_the_viewport():
    mount = JS[JS.index('function observeNotebookCells'):JS.index('const gutterFor')]
    assert 'new IntersectionObserver' in mount
    assert "rootMargin: '700px 0px'" in mount
    assert 'st.cells.forEach((c, i) => mountCell(c, i))' not in mount


def test_terminal_bundle_loads_only_when_the_terminal_opens():
    from leela.app import _asset, _shell
    from leela.blocks.term.term import TerminalGate
    from leela.workspace import Workspace
    html = str(_shell(Workspace(roots=[]), TerminalGate()))
    assert f'<script src="{_asset("lee-term.js")}">' not in html
    terminal = JS[JS.index('let termBundle'):JS.index('function leeTermExpand')]
    assert "document.createElement('script')" in terminal and 'await loadTermBundle()' in terminal


def test_file_backed_changes_have_configurable_autosave_and_keep_a_crash_recovery_draft():
    assert "lee.filePrefs.autoSave || 'afterDelay'" in JS
    assert "'onFocusChange'" in JS and "'onWindowChange'" in JS
    assert 'persistDraft(key, payload)' in JS
    assert 'base_disk_version = draftBaseFor(documentKey)' in JS
    assert 'showSaveConflict(message)' in JS


def test_file_mutations_refresh_only_the_tree_panel():
    ops = JS[JS.index('async function refreshFileTree'):JS.index('document.addEventListener(\'click\'')]
    assert 'location.reload()' not in ops
    assert "fetch('/files/panel')" in ops
    assert "old.replaceWith(fresh)" in ops
