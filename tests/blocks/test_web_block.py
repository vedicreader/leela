"The web block end to end: the routes and the HTML they answer with."

from __future__ import annotations
from pathlib import Path
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.workspace import Workspace


def test_git_info_answers_for_the_repository_it_is_asked_about(tmp_path):
    "Which repository a panel asks about travels as `repo`, so the route must answer for it."
    import subprocess
    (tmp_path/'a.py').write_text('x = 1\n')
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as client:
        bare, named = (client.get('/git/info'), client.get('/git/info', params={'repo': str(tmp_path)}))
        assert bare.status_code == named.status_code == 200
        assert named.json()['root'] == str(tmp_path)


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
