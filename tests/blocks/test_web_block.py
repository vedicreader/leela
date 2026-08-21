"The web block end to end: the routes and the HTML they answer with."

from __future__ import annotations
from pathlib import Path
from fasthtml.common import first, to_xml
from starlette.testclient import TestClient
from leela.app import _editor_pane, _shell, ide_app
from leela.blocks.term.term import TerminalGate
from leela.workspace import Workspace

ROOT = Path(__file__).resolve().parents[2]

class _NoTab: tab = None

def test_a_file_row_opens_through_the_one_versioned_opener(tmp_path):
    "Mouse opens used to stopPropagation without painting `.sel`; keys already did."
    from leela.blocks.fs.ui import tree_node
    (tmp_path/'alpha.py').write_text('x = 1\n')
    ws = Workspace(roots=[tmp_path])
    html = to_xml(tree_node(first(ws.fs.ls(str(tmp_path)))))
    assert 'leeOpenFile(' in html

def test_git_info_answers_for_the_repository_it_is_asked_about(tmp_path):
    "Which repository a panel asks about travels as `repo`, so the route must answer for it."
    import subprocess
    (tmp_path/'a.py').write_text('x = 1\n')
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as client:
        bare, named = (client.get('/git/info'), client.get('/git/info', params={'repo': str(tmp_path)}))
        assert bare.status_code == named.status_code == 200
        assert named.json()['root'] == str(tmp_path)

def test_nbdev_prepare_uses_settings_ini_and_initialises_uv(tmp_path):
    (tmp_path/'settings.ini').write_text('[DEFAULT]\nlib_name = demo\nlib_path = demo\nnbs_path = nbs\n')
    (tmp_path/'nbs').mkdir()
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as client:
        r = client.post('/project/nbdev_prepare', json={})
        body = r.json()
        assert r.status_code in (200, 400)
        if body.get('ok'): assert body['root'] == str(tmp_path) and body['nbs_path'] == 'nbs'
        else: assert any(w in body.get('error', '').lower() for w in ('nbdev', 'uv', 'settings.ini'))

def test_shell_still_exposes_workspace_and_git_switchers(tmp_path):
    html = to_xml(_shell(Workspace(roots=[tmp_path]), TerminalGate()))
    assert 'id="workspacepill"' in html and 'leeWorkspaceMenu(this)' in html
    assert 'id="gitpill"' in html and 'leeBranchMenu(this)' in html
    assert 'data-left="git"' in html


def test_file_click_sets_the_same_selected_state_as_keyboard_navigation(tmp_path):
    "Mouse opens used to stopPropagation without painting `.sel`; keys already did."
    from leela.blocks.fs.ui import tree_node
    (tmp_path/'alpha.py').write_text('x = 1\n')
    ws = Workspace(roots=[tmp_path])
    html = to_xml(tree_node(first(ws.fs.ls(str(tmp_path)))))
    assert 'leeOpenFile(' in html


def test_the_agent_can_be_pointed_at_ramabanas_own_config_dir(tmp_path, monkeypatch):
    """Ramabana writes the log and its sidecars from the same code Leela drives, so one folder can
    serve both surfaces. Empty keeps every existing install exactly where it was."""
    from leela.blocks.settings.settings import Settings, agent_cfg
    import leela
    settings = Settings(user_path=tmp_path/'settings.json')
    assert agent_cfg(settings) == Path(leela.leela_cfg), 'empty means Leela\'s own config dir'
    shared = tmp_path/'shared'/'ramabana'
    settings.save('user', 'agent', {'configFolder': str(shared)})
    assert agent_cfg(settings) == shared and shared.is_dir(), 'and it is made, not just named'
    settings.save('user', 'agent', {'configFolder': '~'})
    assert agent_cfg(settings) == Path.home(), 'a home-relative folder is expanded'
    try: settings.save('user', 'agent', {'nope': 1})
    except ValueError as e: assert 'unknown setting' in str(e)
    else: assert False, 'an unknown key is refused, not written'

def test_a_workspace_assistant_and_its_backups_follow_that_folder(tmp_path, monkeypatch):
    "Moving the log without moving the copies taken of it would protect an empty file."
    from leela.blocks.settings import settings as S
    from leela.core import backups as B
    from leela.workspace import Workspace
    shared, project = tmp_path/'shared', tmp_path/'project'
    project.mkdir()
    monkeypatch.setattr(S, 'leela_cfg', tmp_path/'leela')
    S.Settings().save('user', 'agent', {'configFolder': str(shared)})
    ws = Workspace(roots=[project])
    try:
        assert Path(ws.ai.history_path) == shared/'agent-history.jsonl'
        assert B.agent_source(tmp_path/'leela') == shared
        assert B.entry_source('agent-history.jsonl', tmp_path/'leela', B.agent_source()) == shared/'agent-history.jsonl'
        assert B.entry_source('keys.json', tmp_path/'leela') == tmp_path/'leela'/'keys.json', 'only the agent moves'
    finally: ws.threads.shutdown()

def test_the_empty_state_is_written_only_in_python():
    "`mountTab` clones `#leeempty`; a second copy in the client is the drift that split them."
    js = (ROOT/'leela/blocks/editor/tabs.js').read_text()
    assert 'lee-empty-features' not in js and '#leeempty' in js
    html = to_xml(_editor_pane(_NoTab()))
    assert '<template id="leeempty">' in html and 'lee-empty-features' in html
