"""The prompt-cell progress notice is local to the question, not only in the footer."""

from tests.assets import JS, CSS, SERVER, AGENT


def test_prompt_cells_have_a_local_live_status_slot():
    assert 'id="model-${c.id}"' in JS
    assert 'role="status"' in JS and 'aria-live="polite"' in JS
    assert '●' in JS and 'Model is running' in JS and ' · ${seconds}s elapsed' in JS


def test_prompt_notice_is_shown_timed_and_always_cleared():
    ask = JS[JS.index('async function askCell'):JS.index('/* ---------------------------------------------------------- running files */')]
    assert 'notice.hidden = false' in ask
    assert 'setInterval(tick, 1000)' in ask
    assert 'finally {' in ask and 'notice.hidden = true' in ask
    assert 'clearInterval(clock)' in ask


def test_prompt_notice_motion_respects_accessibility_preferences():
    assert '.lee-model-running[hidden] { display: none; }' in CSS
    assert '@keyframes lee-model-pulse' in CSS
    assert '@media (prefers-reduced-motion: reduce)' in CSS


def test_prompt_replies_use_the_server_mdhtml_renderer():
    assert 'function renderMarkdown(el, text, allowRaw = false)' in JS
    assert "fetch('/markdown/render'" in JS
    assert 'window.leeMarkdown' not in JS
    assert "renderMarkdown(reply, c.reply)" in JS
    assert "renderMarkdown(reply, raw)" in JS


def test_mdhtml_rendering_is_paste_safe_and_reports_unclosed_constructs():
    from starlette.testclient import TestClient
    from leela.web.app import ide_app
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
    from leela.web.app import ide_app
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


def test_agent_tool_rows_expand_to_structured_details():
    step = JS[JS.index('function renderAgentStep'):JS.index('// A turn gets an immediate')]
    assert "document.createElement('summary')" in step
    assert 'lee-agent-step-detail' in step and 'readableDetail(a.detail)' in step
    assert "mountCodeSurface(block, code, 'python', true)" in step
    assert "document.createElement('details')" in JS
    assert '.lee-agent-step > summary' in CSS and '.lee-agent-step-detail' in CSS


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
    # agentlog uses pre-wrap for plain logs; replies must reset it or Markdown's source
    # whitespace becomes a visible hundred-pixel gap between otherwise compact tool cards.
    assert '.lee-reply {' in CSS and 'white-space: normal' in CSS


def test_approval_card_can_trust_later_writes_for_the_current_session():
    card = JS[JS.index('function showApproval'):JS.index('function readableDetail')]
    assert 'Pause again' in card and 'Trust changes for this session' in card
    assert "const session = ok && $('[data-run-policy]', card).value === 'approve_session'" in card
    assert "post('/agent/approve', {id: a.id, ok, note, session, tool, args})" in card


def test_browser_polls_for_approvals_from_rishi_outside_agent_streams():
    assert "api('/agent/approval')" in JS
    assert 'if (r.pending) showApproval(r.pending)' in JS
    assert 'setInterval(pollApproval, 750)' in JS


def test_an_approval_reveals_the_live_agent_tab_automatically():
    card = JS[JS.index('function showApproval'):JS.index('async function pollApproval')]
    assert "leePane('right', true)" in card
    assert "leeRight('agent')" in card
    assert "restoreAgentLive()" in card


def test_long_user_messages_are_composed_cards_not_unbounded_traceback_text():
    message = JS[JS.index('function userMessage'):JS.index('function renderTurns')]
    assert "raw.length > 900" in message and "raw.split('\\n').length > 14" in message
    assert 'Show full request' in message and 'lee-user-message-more' in message
    assert 'item.appendChild(userMessage(turn.prompt))' in JS
    assert 'log.appendChild(userMessage(q))' in JS
    assert '.lee-user-message {' in CSS and '.lee-user-message-body.preview' in CSS


def test_agent_turn_usage_is_persisted_and_rendered_in_live_and_history_views():
    js = JS
    agent = AGENT
    assert "'usage': self.turn_use.dict()" in agent
    assert 'function usageMeta(' in js and 'usageMeta(turn.usage' in js
    assert 'usageMeta(d.usage' in js and 'Token usage and estimated cost for this turn' in js


def test_history_groups_turns_by_context_session_without_rendering_every_turn():
    from leela.web.app import _history_sessions
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
    from leela.web.app import _agent_panel
    from leela.workspace import Workspace
    html = str(_agent_panel(Workspace(roots=[])))
    assert 'lee-dismissable' in html
    assert "details.lee-dismissable[open]" in JS
    assert "document.addEventListener('pointerdown'" in JS
    assert "e.key !== 'Escape'" in JS and 'open.open = false' in JS


def test_agent_pane_has_model_history_and_expand_controls():
    from leela.web.app import _agent_panel
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
    from leela.web.app import _project_state_context
    from leela.workspace import Workspace
    (tmp_path/'pyproject.toml').write_text('[project]\nname = "current-code"\n')
    (tmp_path/'module.py').write_text('def current_api():\n    return 1\n')
    context = _project_state_context(Workspace(roots=[tmp_path]))
    assert 'pyproject.toml' in context and 'module.py' in context and 'current-code' in context
    assert 'Refresh from code' in JS
    assert '<current-project>' in SERVER


def test_custom_model_controls_are_in_the_dropdown_ui():
    from leela.web.app import _agent_panel
    from leela.workspace import Workspace
    html=str(_agent_panel(Workspace(roots=[])))
    assert 'leeAddModel' in html and '/agent/models/add' in JS
    assert 'Hugging Face URL' in JS and 'hosted API / FastLLM' in JS


def test_model_picker_shows_older_models_by_default(monkeypatch):
    from starlette.testclient import TestClient
    from leela.agent import core as models
    from leela.web.app import _agent_panel, ide_app
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
    from leela.web.app import ide_app
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
    from leela.web.app import ide_app
    from leela.workspace import Workspace
    path = tmp_path/'workspace.json'
    ws = Workspace(roots=[]); ws._state_path = path
    with TestClient(ide_app(ws)) as client:
        assert client.post('/agent/model', json={'target': 'agent', 'model': 'gemma-12b'}).json()['ok']
        assert client.post('/agent/model', json={'target': 'inline', 'model': 'gemma-e2b'}).json()['ok']
        assert client.post('/agent/model', json={'target': 'completion', 'model': 'gemma-e4b'}).json()['ok']
    restored = Workspace.load(path)
    assert (restored.model, restored.inline_model, restored.completion_model) == ('gemma-12b', 'gemma-e2b', 'gemma-e4b')


def test_new_workspaces_use_requested_prompt_and_completion_defaults():
    from leela.workspace import Workspace
    ws = Workspace(roots=[])
    assert ws.inline_model == 'gpt-mini'
    assert ws.completion_model == 'gpt-4.1'
    assert ws.ai.routing.name_for('completion') == 'gpt-4.1'


def test_configured_agent_does_not_offer_setup_again():
    from leela.web.app import _agent_panel
    from leela.workspace import Workspace
    ws = Workspace(roots=[])
    ws.agent_state_layers['project']['text'] = '# Goal\n\nMaintain this project.'
    html = str(_agent_panel(ws))
    assert 'state active' in html
    assert 'Set up agent state' not in html


def test_agent_memory_api_selects_notes_per_surface_and_rebriefs(tmp_path):
    from starlette.testclient import TestClient
    from leela.web.app import ide_app
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
    from leela.web.app import ide_app
    from leela.workspace import Workspace
    ws = Workspace(roots=[])
    ws._state_path = tmp_path/'workspace.json'
    with TestClient(ide_app(ws)) as client:
        data = client.post('/agent/settings', json={'local_multimodal': True}).json()
    assert data['ok'] and ws.local_multimodal is True
    assert ws._state_path.read_json()['local_multimodal'] is True


def test_static_assets_are_cache_busted_as_one_revision():
    from leela.web.app import _asset
    assert _asset('lee-ide.css').startswith('/leestatic/lee-ide.css?v=')
    assert _asset('lee-ide.js').startswith('/leestatic/lee-ide.js?v=')
