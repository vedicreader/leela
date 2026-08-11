"""Browser-level contracts for editable agent execution and explicit starting state."""

# drives a real browser through playwright, so it is out of the default run. `pytest -m slow` or `-m ""` includes it.
import pytest

pytestmark = pytest.mark.slow

import socket, threading, time
from contextlib import contextmanager

import pytest

from leela.app import ide_app
from leela.workspace import Workspace


def _port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


@contextmanager
def _server(ws):
    import uvicorn
    port = _port()
    server = uvicorn.Server(uvicorn.Config(ide_app(ws), host='127.0.0.1', port=port, log_level='error'))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started: break
        time.sleep(.02)
    try: yield f'http://127.0.0.1:{port}'
    finally:
        server.should_exit = True
        thread.join(timeout=3)


@pytest.mark.skipif(__import__('importlib').util.find_spec('playwright') is None, reason='playwright is not installed')
def test_browser_can_change_control_open_layered_state_and_find_agent_commands(tmp_path):
    from playwright.sync_api import sync_playwright

    ws = Workspace(roots=[tmp_path])
    with _server(ws) as url, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        page.goto(url, wait_until='networkidle')

        # A persisted workspace conflict/recovery notice may legitimately open on boot;
        # this test is about the agent surface, so close only that pre-existing shell modal.
        if page.locator('.lee-modal').count(): page.keyboard.press('Escape')
        page.select_option('#agentcontrol', 'directed')
        page.wait_for_timeout(80)
        assert ws.approvals.control == 'directed'

        page.click('#agentstate')
        page.wait_for_selector('#agentstatelayer')
        assert page.locator('[data-bootstrap]').is_visible()
        assert 'Start with a worked template' in page.locator('.lee-agent-state-onboard').inner_text()
        assert page.locator('#agentstatelayer option').all_text_contents() == [
            'organization', 'project', 'task', 'preferences', 'branch', 'ephemeral']
        box = page.locator('.lee-agent-state-modal .lee-modalbox')
        initial = box.bounding_box()
        assert initial['width'] >= 1000 and initial['height'] >= 700
        assert page.locator('.lee-agent-state-editor .cm-editor').is_visible()
        assert page.locator('.lee-state-ref-tabs').is_visible()
        heading = page.locator('.lee-agent-state-modal .lee-mhead').bounding_box()
        page.mouse.move(heading['x'] + 180, heading['y'] + 12)
        page.mouse.down(); page.mouse.move(heading['x'] + 240, heading['y'] + 52, steps=4); page.mouse.up()
        moved = box.bounding_box()
        assert moved['x'] > initial['x'] and moved['y'] > initial['y']
        page.click('.lee-agent-state-modal .lee-modal-expand')
        expanded = box.bounding_box()
        assert expanded['width'] > initial['width'] and expanded['height'] > initial['height']
        page.select_option('#agentstatelayer', 'project')
        page.locator('.lee-agent-state-editor .cm-content').fill('# Goal\n\nKeep project architecture stable.')
        page.click('[data-add-tool]')
        assert page.locator('.lee-state-tool-list button').count() > 5
        page.click('[data-ref="preview"]')
        assert page.locator('#agentstatepreview').is_visible()
        page.click('[data-activate]')
        page.wait_for_timeout(100)
        assert ws.agent_state_layers['project']['text'].endswith('architecture stable.')

        page.evaluate("leeAct('palette')")
        page.fill('#cp', 'Agent: pause')
        assert 'Agent: pause after current call' in page.locator('#cplist').inner_text()
        palette = page.locator('.lee-modal').last.locator('.lee-modalbox')
        before_drag = palette.bounding_box(); grip = palette.locator('.lee-modal-grip').bounding_box()
        page.mouse.move(grip['x'] + 10, grip['y'] + 3); page.mouse.down()
        page.mouse.move(grip['x'] + 55, grip['y'] + 38, steps=3); page.mouse.up()
        after_drag = palette.bounding_box()
        assert after_drag['x'] > before_drag['x'] and after_drag['y'] > before_drag['y']
        browser.close()


@pytest.mark.skipif(__import__('importlib').util.find_spec('playwright') is None, reason='playwright is not installed')
def test_response_fork_and_turn_undo_execute_against_a_successful_turn(tmp_path):
    from playwright.sync_api import sync_playwright
    from tests.fakemodel import Step, install

    path = tmp_path/'changed.py'; path.write_text('before\n')
    ws = Workspace(roots=[tmp_path], approvals='auto')
    install(ws, [Step(tool=('create_file', {'path': str(path), 'text': 'after\n'})),
                 Step(text='Created and verified the file.')], token_delay=0)
    with _server(ws) as url, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(url, wait_until='networkidle')
        if page.locator('.lee-modal').count(): page.keyboard.press('Escape')
        page.fill('#agentprompt', 'create the requested file')
        page.evaluate("leeAct('agent_send')")
        page.wait_for_function('!window.lee.agentBusy')

        undo = page.locator('.lee-response-revision [data-undo]')
        revise = page.locator('.lee-response-revision [data-revise]')
        assert not errors, errors
        assert undo.is_enabled() and revise.is_enabled()
        assert undo.evaluate('(el) => typeof el.onclick') == 'function', undo.evaluate('(el) => el.outerHTML')
        with page.expect_response(lambda r: '/agent/turn-transaction' in r.url) as transaction_response:
            undo.click()
        assert transaction_response.value.ok, transaction_response.value.text()
        with page.expect_response(lambda r: '/agent/rollback-turn' in r.url) as response:
            page.get_by_role('button', name='restore files').click()
        assert response.value.ok, response.value.text()
        page.wait_for_timeout(100)
        assert path.read_text() == 'before\n', page.locator('#status').inner_text()

        revise.click(); page.wait_for_selector('[data-revision]')
        page.fill('[data-revision]', 'User-authored corrected response.')
        page.click('[data-apply]'); page.wait_for_timeout(100)
        assert page.locator('.lee-agent-reply').last.get_attribute('data-user-revised') == '1'
        assert ws.ai.current_branch_id.startswith('branch_')
        browser.close()


def test_agent_state_markdown_lint_reports_missing_charter_sections(tmp_path):
    from starlette.testclient import TestClient

    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        diagnostics = client.post('/lint', json={'lang': 'markdown', 'path': '<agent-state>',
                                                  'code': '# Goal\n\nShip it.'}).json()['diagnostics']
    messages = [d['message'] for d in diagnostics]
    assert any('Hard boundaries' in m for m in messages)
    assert any('Tool practices' in m for m in messages)
    assert all(d['severity'] in {'info', 'warning', 'error'} for d in diagnostics)


def test_action_protocol_routes_and_response_revision_are_present():
    from inspect import getsource

    source = getsource(ide_app)
    for route in ('/agent/branches', '/agent/fork', '/agent/revise', '/agent/rollback-turn',
                  '/agent/state/template', '/agent/state/bootstrap', '/agent/state/suggest',
                  '/agent/state/diagnostics', '/agent/state/update', '/agent/compaction'):
        assert route in source
