import os, sys, time

import pytest
from starlette.testclient import TestClient

from leela.app import ide_app
from leela.blocks.term.term import TerminalGate
from leela.workspace import Workspace


@pytest.fixture
def shell(tmp_path):
    gate = TerminalGate()
    with TestClient(ide_app(Workspace(roots=[tmp_path]), gate)) as client: yield client, gate.token, tmp_path


def _finished(client, d):
    for _ in range(200):
        log = client.get(f"/agent/runs/{d['run']}/log?thread={d['thread']}").json()
        if log['done']: return log
        time.sleep(.05)
    raise AssertionError('the command did not finish')


def test_a_snippet_run_from_a_reply_reports_through_the_run_log_and_stops(shell):
    "The run button's route starts the command in the project; its output, exit state and stop use the background-command routes."
    client, token, root = shell
    d = client.post('/agent/shell-run', json={'command': 'echo hi > made.txt; cat made.txt; exit 3', 'token': token}).json()
    assert d['ok'] and d['run'].startswith('cmd_')
    log = _finished(client, d)
    assert log['state'] == 'exit 3' and 'hi' in log['text'] and (root/'made.txt').exists()
    d = client.post('/agent/shell-run', json={'command': 'sleep 30', 'token': token}).json()
    assert client.post(f"/agent/shell/{d['run']}/stop?thread={d['thread']}").json()['state'] == 'stopped'


def test_a_snippet_never_reads_leelas_own_stdin(shell):
    "Leela's stdin can be a terminal or a pipe; a snippet that reads input gets end of file instead."
    client, token, _ = shell
    probe = f'"{sys.executable}" -c "import os; print(os.path.samestat(os.fstat(0), os.stat(os.devnull)))"'
    r, w = os.pipe(); held = os.dup(0); os.dup2(r, 0)
    try: log = _finished(client, client.post('/agent/shell-run', json={'command': probe, 'token': token}).json())
    finally: os.dup2(held, 0); [os.close(f) for f in (held, r, w)]
    assert log['text'].strip() == 'True', log['text']


def test_a_snippet_run_needs_the_terminal_token_and_a_command(shell):
    "Running any command is a terminal's power, so the route asks for the terminal's token."
    client, token, _ = shell
    for body, code in (({'command': 'echo hi'}, 403), ({'command': 'echo hi', 'token': 'wrong'}, 403),
                       ({'command': 'echo hi', 'token': 'tök'}, 403), ({'command': ' ', 'token': token}, 400)):
        assert client.post('/agent/shell-run', json=body).status_code == code, body
    assert client.get('/agent/shell-run?command=echo').status_code == 405
