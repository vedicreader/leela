"The web block end to end: the routes and the HTML they answer with."

from __future__ import annotations
from pathlib import Path
from fasthtml.common import first, to_xml
from starlette.testclient import TestClient
from leela.app import _editor_pane, _shell, ide_app
from leela.blocks.term.term import TerminalGate
from leela.workspace import Workspace

ROOT = Path(__file__).resolve().parents[2]

def _bundles():
    "Every served bundle as one string. The client was one file and is now three of them."
    from leela.core.web import IDE_BUNDLES
    return '\n'.join((ROOT/'leela'/'static'/n).read_text() for n in IDE_BUNDLES)

JS = _bundles()

class _NoTab: tab = None

def test_a_file_row_opens_through_the_one_versioned_opener(tmp_path):
    """Mouse opens used to stopPropagation without painting `.sel`; keys already did."""
    from leela.blocks.fs.ui import tree_node
    (tmp_path/'alpha.py').write_text('x = 1\n')
    ws = Workspace(roots=[tmp_path])
    html = to_xml(tree_node(first(ws.fs.ls(str(tmp_path)))))
    assert 'leeTreeClick(event,' in html and 'leeOpenFile(' not in html
    src = (ROOT/'leela'/'blocks'/'fs'/'files.js').read_text()
    handler = src[src.index('function leeTreeClick'):src.index('window.leeTreeClick')]
    assert 'leeOpenFile(path)' in handler, 'a plain click still opens through the one opener'

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

def test_fastship_is_the_non_nbdev_half_of_the_same_front_end(tmp_path):
    "Every route the panel reaches answers in one shape, and both live on the files menu."
    (tmp_path/'pyproject.toml').write_text('[project]\nname = "demo"\nversion = "0.1.0"\n')
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        d = client.get('/project/fastship').json()
        assert d['ok'] and d['flow'] == 'fastship' and d['nbdev'] is False
        assert [o['op'] for o in d['ops']] == ['changelog', 'bump', 'pages']
        # fastship is not in this project's venv, so every command says so rather than raising.
        for op in ('changelog', 'bump', 'pages'):
            r = client.post('/project/fastship/action', json={'op': op})
            assert 'error' in r.json(), op
        assert 'error' in client.post('/project/fastship/action', json={'op': 'nonsense'}).json()
        for bad in ('', 'a/b', 'a\\b', '..', '.hidden'):
            assert 'error' in client.post('/project/fastship/action',
                json={'op': 'new', 'name': bad}).json(), bad
        # A refused scaffold must leave nothing behind, or retrying meets its own leftovers.
        before = sorted(p.name for p in Path(tmp_path).parent.iterdir())
        client.post('/project/fastship/action', json={'op': 'new', 'name': 'a/b'})
        assert sorted(p.name for p in Path(tmp_path).parent.iterdir()) == before
        nb = client.get('/project/fastship').json()
        assert nb['root'] == str(tmp_path)
    assert 'leeFastship' in JS and '/project/fastship' in JS
    assert "'fastship…'" in JS
    from leela.blocks.keys.menus import web_menus
    files = [r.get('action') for r in web_menus()['files']]
    assert 'nbdev_prepare' in files and 'fastship' in files, 'both on the files panel'
    assert 'fastship:' in JS and 'nbdev_prepare:' in JS, 'and both dispatch through leeAct'

def test_an_nbdev_project_says_so_rather_than_offering_fastship_commands(tmp_path):
    (tmp_path/'pyproject.toml').write_text('[project]\nname = "demo"\nversion = "0"\n\n[tool.nbdev]\n')
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as client:
        d = client.get('/project/fastship').json()
        assert d['flow'] == 'nbdev' and d['nbdev'] is True
    assert 'This is an nbdev project' in JS, 'the modal says which front end owns it'

def test_shell_still_exposes_workspace_and_git_switchers(tmp_path):
    html = to_xml(_shell(Workspace(roots=[tmp_path]), TerminalGate()))
    assert 'id="workspacepill"' in html and 'leeWorkspaceMenu(this)' in html
    assert 'id="gitpill"' in html and 'leeBranchMenu(this)' in html
    assert 'data-left="git"' in html


def test_file_click_sets_the_same_selected_state_as_keyboard_navigation(tmp_path):
    "Mouse opens used to stopPropagation without painting `.sel`; keys already did."
    src = (ROOT/'leela'/'blocks'/'fs'/'files.js').read_text()
    handler = src[src.index('function leeTreeClick'):src.index('window.leeTreeClick')]
    assert 'selectTreeNode(n)' in handler, 'a plain click paints the caret, as the arrows do'
    assert "setScope('files')" in handler
    # A modifier selects instead, and never opens: that is the whole of multi-select by mouse.
    assert 'metaKey' in handler and 'shiftKey' in handler
    opens = handler.index('leeOpenFile(path)')
    assert handler.index('if (e.shiftKey)') < opens, 'the modifier readings return before opening'


def test_the_agent_can_be_pointed_at_ramabanas_own_config_dir(tmp_path, monkeypatch):
    """Ramabana writes the log and its sidecars from the same code Leela drives, so one folder can serve both surfaces."""
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
