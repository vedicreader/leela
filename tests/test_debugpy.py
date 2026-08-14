import shutil
from pathlib import Path

import pytest

from leela.blocks.debug.debug import DebugSession, debugpy_available


def test_direct_debugpy_stops_exposes_locals_and_continues(tmp_path):
    python = shutil.which('python')
    if not python or not debugpy_available(python): pytest.skip('debugpy is not installed in the test interpreter')
    source = tmp_path/'direct_debug.py'
    source.write_text('value = 41\nanswer = value + 1\nprint(answer)\n')
    session = DebugSession(python, tmp_path).start_adapter()
    try:
        session.launch({'request':'launch', 'program':str(source), 'justMyCode':True},
                       {str(source): [2]})
        event = session.wait_event('stopped', 15)
        state = session.state(event['body']['threadId'])
        assert state['frames'][0]['line'] == 2
        assert any(v['name'] == 'value' and v['value'] == '41' for v in state['variables'])
        assert session.evaluate('value + 1')['result'] == '42'
        session.control('continue')
        assert session.wait_event({'exited', 'terminated'}, 15)['event'] in ('exited', 'terminated')
    finally:
        session.disconnect()


def test_debugpy_breakpoints_accept_conditions_hit_counts_and_log_messages(tmp_path, monkeypatch):
    session = DebugSession(shutil.which('python') or 'python', tmp_path)
    captured = {}
    def request(command, arguments=None, timeout=10):
        captured.update(command=command, arguments=arguments)
        return {'breakpoints': [{'verified': True, 'line': 7}]}
    monkeypatch.setattr(session, 'request', request)
    rows = session.set_breakpoints(tmp_path/'app.py', [{'line':7, 'condition':'ready',
        'hitCondition':'> 3', 'logMessage':'value={value}'}])
    assert rows[0]['verified']
    bp = captured['arguments']['breakpoints'][0]
    assert bp == {'line':7, 'condition':'ready', 'hitCondition':'> 3', 'logMessage':'value={value}'}
