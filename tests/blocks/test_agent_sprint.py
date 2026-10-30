"""Approval rules and the edits mode, the replace_text preview, run transcripts, messages to a sub-agent, background results, and background commands on the host."""

from __future__ import annotations
import json, time
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.agent.runtime import Run
from leela.blocks.agent.ai import Interventions, WRITE_TOOLS, WorkspaceHost
from leela.workspace import Workspace


def _until(fn, secs=5):
    "The first non-empty answer `fn` gives; a pending `Ask` is falsy, so emptiness is tested by hand."
    end = time.time() + secs
    while time.time() < end:
        if (v := fn()) not in (None, False, '', [], ()): return v
        time.sleep(.02)
    return fn()


def test_saved_rules_and_the_edits_mode_decide_without_asking(tmp_path):
    rules = tmp_path/'approvals.json'
    rules.write_text(json.dumps([['run_shell', 'pytest -q', 'allow'], ['run_shell', 'rm *', 'deny']]))
    ap = Interventions(tools=WRITE_TOOLS, mode='ask', control='guided', timeout=1, rules_path=rules)
    assert ap.request('run_shell', {'command': 'pytest -q'}).answer, 'an allow rule runs it without a listener'
    a = ap.request('run_shell', {'command': 'rm -rf build'})
    assert not a.answer
    assert not ap.request('run_shell', {'command': 'make'}).answer, 'no rule: it is asked'
    ap.always('run_shell', 'make')
    assert json.loads(rules.read_text())[-1] == ['run_shell', 'make', 'allow'] and ap.request('run_shell', {'command': 'make'}).answer
    edits = Interventions(tools=WRITE_TOOLS, mode='edits', control='guided', timeout=1)
    assert edits.request('edit_file', {'path': 'a.py', 'commands': '[]'}).answer
    assert not edits.request('run_shell', {'command': 'make'}).answer
    directed = Interventions(tools=WRITE_TOOLS, mode='edits', control='directed', timeout=1)
    assert not directed.request('edit_file', {'path': 'a.py', 'commands': '[]'}).answer, 'directed still asks'


def test_always_allow_and_the_rules_list_reach_the_thread(tmp_path, monkeypatch):
    monkeypatch.setattr('leela.blocks.settings.settings.agent_cfg', lambda settings=None: tmp_path)
    ws = Workspace(roots=[tmp_path], approvals='ask')
    with TestClient(ide_app(ws)) as c:
        t = ws.threads.active
        assert t.approvals.rules_path == tmp_path/'approvals.json'
        import threading
        got = {}
        def ask(): got['a'] = t.approvals.request('run_shell', {'command': 'pytest -q'}, timeout=5)
        threading.Thread(target=ask, daemon=True).start()
        a = _until(lambda: t.approvals.pending)
        d = c.post('/agent/approval/always', json={'id': a.id, 'tool': 'run_shell', 'args': {'command': 'pytest -q'}, 'thread': t.id}).json()
        assert d['ok'] and d['rules'] == [['run_shell', 'pytest -q', 'allow']]
        assert _until(lambda: got.get('a')).answer
        assert t.approvals.request('run_shell', {'command': 'pytest -q'}).answer, 'the rule holds without asking'
        assert c.get('/agent/approval/rules', params={'thread': t.id}).json()['rules'] == [['run_shell', 'pytest -q', 'allow']]
        assert c.post('/agent/approval/rules/delete', json={'rule': ['run_shell', 'pytest -q', 'allow'], 'thread': t.id}).json()['rules'] == []
        assert not c.post('/agent/approval/rules/delete', json={'rule': ['run_shell', 'gone', 'allow'], 'thread': t.id}).json()['ok']
        assert json.loads((tmp_path/'approvals.json').read_text()) == []
        d = c.post('/agent/control', json={'control': 'edits', 'thread': t.id}).json()
        assert d['control'] == 'edits' and d['mode'] == 'edits' and t.approvals.control == 'autopilot'
        d = c.post('/agent/control', json={'control': 'guided', 'thread': t.id}).json()
        assert d['control'] == 'guided' and t.approvals.mode == ws.approvals_mode


def test_a_replace_text_preview_shows_the_change(tmp_path):
    from leela.blocks.agent.turns import tool_preview
    (tmp_path/'a.py').write_text('x = 1\n')
    ws = Workspace(roots=[tmp_path])
    edits = [{'oldText': 'x = 1', 'newText': 'x = 2'}]
    d = tool_preview(ws.ai, 'replace_text', {'path': str(tmp_path/'a.py'), 'edits': edits})
    assert d['kind'] == 'diff' and any('x = 2' in json.dumps(r) for r in d['rows']) and any('x = 1' in json.dumps(r) for r in d['rows'])


def test_transcripts_messages_and_background_results_reach_the_routes(tmp_path):
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as c:
        t = ws.threads.active
        log = t.ai.monitors.log; log.parent.mkdir(parents=True, exist_ok=True); log.write_text('{"status": "ok"}\n')
        d = c.get('/agent/runs/monitors/log', params={'thread': t.id}).json()
        assert d['text'].startswith('{"status"') and d['since'] == len(d['text'])
        assert c.get('/agent/runs/monitors/log', params={'thread': t.id, 'since': d['since']}).json()['text'] == ''
        run = Run('run_bg', 'background', 'what is x', 'fake', log=t.ai.runs_dir/'run_bg.log')
        t.ai.background.start(lambda r: _until(lambda: r.inbox) and f'heard {list(r.drain_inbox())}', run)
        d = c.post(f'/agent/runs/{run.id}/steer', json={'text': 'also y', 'thread': t.id}).json()
        assert d['ok']
        assert _until(lambda: t.ai.background.result(run.id).startswith('heard'))
        assert "['also y']" in t.ai.background.result(run.id)
        ev = _until(lambda: [r for r in t.feed.since(0) if r['event'] == 'background'])
        assert ev and ev[0]['data']['id'] == 'run_bg' and 'also y' in ev[0]['data']['answer']
        assert c.get(f'/agent/runs/{run.id}/log', params={'thread': t.id}).json()['done']
        assert c.post(f'/agent/runs/{run.id}/steer', json={'text': 'late', 'thread': t.id}).status_code == 409
        seen = []
        t.ai.on_watch = lambda target, log: seen.append((target, str(log)))
        assert t.ai.watch('monitors') == 'watching monitors' and seen[0][0] == 'monitors'
        assert c.get('/agent/environment', params={'thread': t.id}).status_code == 200


def test_a_background_answer_reaches_the_model_in_the_next_tool_result(tmp_path):
    "A delegation that finishes mid-turn rides on the next tool result, so the model needs no `delegate_result` poll."
    from tests.fakemodel import Step, install
    ws = Workspace(roots=[tmp_path]); t = ws.threads.active
    be = install(ws, [Step(tool=('ls', {}), pause=1.0), Step(text='done')], token_delay=0)
    run = Run('run_mid', 'background', 'what is x', 'fake', log=t.ai.runs_dir/'run_mid.log')
    t.ai.background.start(lambda r: time.sleep(.3) or 'x is 42', run)
    t.ai.ask('go')
    tool_out = next(m['content'] for m in be.hist_ if m['role'] == 'tool')
    assert '<background-results>' in tool_out and 'run_mid' in tool_out and 'x is 42' in tool_out, tool_out
    assert 'x is 42' not in str(be.sent[0]), 'it finished after the prompt went out'


def test_the_host_runs_commands_in_the_background(tmp_path):
    ws = Workspace(roots=[tmp_path])
    host = WorkspaceHost(ws)
    rid = host.run_cmd_bg('echo hi; exit 3')
    state, text = _until(lambda: (r := host.cmd_output(rid)) and r[0] != 'running' and r)
    assert state == 'exit 3' and 'hi' in text
    slow = host.run_cmd_bg('sleep 30')
    assert host.cmd_output(slow)[0] == 'running'
    p, log = host._bg[slow]
    host.close()
    assert host._bg == {} and p.poll() is not None and not log.exists()
