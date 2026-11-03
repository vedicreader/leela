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
    be = install(ws, [Step(tool=('ls', {}), pause=3.0), Step(text='done')], token_delay=0)
    run = Run('run_mid', 'background', 'what is x', 'fake', log=t.ai.runs_dir/'run_mid.log')
    t.ai.background.start(lambda r: _until(lambda: be.sent) and 'x is 42', run)   # it finishes once the prompt is out, not after a fixed wait
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


def _asked(ap):
    "The tools that raised a card on `ap`."
    seen = []; ap.listen(lambda a: seen.append(a.tool))
    return seen

def _raise(ap, *a, **kw):
    "Raise a request off this thread; returns a getter for its answer."
    import threading
    got = {}
    threading.Thread(target=lambda: got.setdefault('a', ap.request(*a, **kw)), daemon=True).start()
    return lambda: got.get('a')

def test_autopilot_raises_no_card_and_gives_back_the_mode():
    ap = Interventions(tools=WRITE_TOOLS, mode='ask', control='guided', timeout=.3); seen = _asked(ap)
    ap.set_control('autopilot')
    assert ap.mode == 'auto' and ap.chosen == 'autopilot'
    assert ap.request('edit_file', {'path': 'a.py', 'commands': '[]'}).answer and ap.request('run_shell', {'command': 'make'}).answer
    assert seen == [], 'autopilot shows no card'
    ap.set_control('edits'); assert ap.mode == 'edits' and ap.control == 'autopilot' and ap.chosen == 'edits'
    ap.set_control('guided'); assert ap.mode == 'ask' and ap.chosen == 'guided'
    ap.set_control('directed'); assert ap.mode == 'ask'

def test_autopilot_still_asks_for_the_repeat_guard_a_person_a_policy_and_a_pause():
    ap = Interventions(tools=WRITE_TOOLS, mode='ask', control='guided', timeout=.2,
                       policy=lambda n, a: 'ask' if a.get('command') == 'rm x' else None)
    seen = _asked(ap); ap.set_control('autopilot')
    for _ in range(3): ap.request('run_shell', {'command': 'make'})
    assert seen == ['run_shell'], 'the third same call asks'
    ap.request('run_shell', {'command': 'rm x'}); assert len(seen) == 2, 'a host policy that asks still asks'
    ap.request('peer ask', {'question': 'ok?'}, force=True); assert seen[-1] == 'peer ask'
    ap.set_pause_next(); ap.request('read_file', {'path': 'a.py'}); assert seen[-1] == 'read_file', 'pause after current stops a read'
    ap.set_pause_next(); ap.request('edit_file', {'path': 'a.py', 'commands': '[]'}); assert seen[-1] == 'edit_file', 'and a write'
    assert ap.request('edit_file', {'path': 'b.py', 'commands': '[]'}).answer and seen[-1] == 'edit_file' and len(seen) == 5
    ap.stop(); assert not ap.request('edit_file', {'path': 'c.py', 'commands': '[]'}).answer and len(seen) == 5

def test_switching_to_autopilot_leaves_a_waiting_repeat_guard_card():
    ap = Interventions(tools=WRITE_TOOLS, mode='ask', control='guided', timeout=5); ap.listen()
    ap.mode = 'auto'
    for _ in range(2): ap.request('run_shell', {'command': 'make'})
    got = _raise(ap, 'run_shell', {'command': 'make'})
    a = _until(lambda: ap.pending)
    ap.set_mode('ask'); ap.set_control('autopilot')
    assert ap.pending is a and a.pending, 'the person still answers the repeat guard'
    ap.answer(a.id, False, 'no'); assert not _until(got).answer

def test_session_trust_survives_leaving_autopilot_or_edits():
    ap = Interventions(tools=WRITE_TOOLS, mode='ask', control='guided', timeout=5); ap.listen()
    got = _raise(ap, 'run_shell', {'command': 'make'})
    ap.answer(_until(lambda: ap.pending).id, True, session=True); assert _until(got).answer and ap.mode == 'auto'
    ap.set_control('edits'); ap.set_control('guided')
    assert ap.mode == 'auto', 'trust given before edits comes back, not the launch mode'
    ap.set_mode('ask'); ap.set_control('edits')
    got = _raise(ap, 'run_shell', {'command': 'pytest'})
    ap.answer(_until(lambda: ap.pending).id, True, session=True); assert _until(got).answer
    ap.set_control('guided'); assert ap.mode == 'auto', 'trust given under edits stays'

def test_approvals_switched_off_stay_off_under_autopilot_and_edits():
    ap = Interventions(tools=WRITE_TOOLS, mode='off', control='guided', timeout=.3); seen = _asked(ap)
    for c in ('autopilot', 'edits'):
        ap.set_control(c); assert ap.mode == 'off'
        assert not ap.request('edit_file', {'path': 'a.py', 'commands': '[]'}).answer and seen == []
    ap.set_control('guided'); assert ap.mode == 'off'

def test_the_control_route_gives_back_session_trust_and_threads_report_their_control(tmp_path, monkeypatch):
    monkeypatch.setattr('leela.blocks.settings.settings.agent_cfg', lambda settings=None: tmp_path)
    ws = Workspace(roots=[tmp_path], approvals='ask')
    with TestClient(ide_app(ws)) as c:
        t = ws.threads.active
        got = _raise(t.approvals, 'run_shell', {'command': 'make'}, timeout=5)
        a = _until(lambda: t.approvals.pending)
        assert c.post('/agent/approve', json={'id': a.id, 'ok': True, 'session': True, 'thread': t.id}).json()['ok'] and _until(got).answer
        d = c.post('/agent/control', json={'control': 'autopilot', 'thread': t.id}).json()
        assert d['control'] == 'autopilot' and d['mode'] == 'auto'
        assert c.post('/agent/control', json={'control': 'edits', 'thread': t.id}).json()['mode'] == 'edits'
        d = c.post('/agent/control', json={'control': 'guided', 'thread': t.id}).json()
        assert d['control'] == 'guided' and d['mode'] == 'auto'
        c.post('/agent/control', json={'control': 'autopilot', 'thread': t.id})
        new = c.post('/agent/thread/new', json={}).json()
        assert new['control'] == 'guided' and ws.threads.require(new['active']).approvals.mode == 'ask'
        assert c.post('/agent/thread/switch', json={'thread': t.id}).json()['control'] == 'autopilot'

def test_always_allow_answers_a_prompt_cell_card(tmp_path, monkeypatch):
    monkeypatch.setattr('leela.blocks.settings.settings.agent_cfg', lambda settings=None: tmp_path)
    ws = Workspace(roots=[tmp_path], approvals='ask')
    with TestClient(ide_app(ws)) as c:
        t, nb = ws.threads.active, ws._notebook_approvals
        assert nb.rules_path == tmp_path/'approvals.json'
        got = _raise(nb, 'run_shell', {'command': 'pytest -q'}, timeout=5)
        a = _until(lambda: nb.pending)
        d = c.post('/agent/approval/always', json={'id': a.id, 'thread': t.id}).json()
        assert d['ok'], d
        assert d['rules'] == [['run_shell', 'pytest -q', 'allow']] and _until(got).answer
        assert json.loads((tmp_path/'approvals.json').read_text()) == [['run_shell', 'pytest -q', 'allow']]
        assert t.approvals.rules == nb.rules and t.approvals.rules is not nb.rules
        assert nb.request('run_shell', {'command': 'pytest -q'}).answer and t.approvals.request('run_shell', {'command': 'pytest -q'}).answer
