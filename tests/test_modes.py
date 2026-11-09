"The modes foundation: the registry, the agent's mode string, the workspace mode and its layouts, and the cell the agent is anchored on."
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.routing import Mount
from starlette.testclient import TestClient

from leela.app import ide_app
from leela.blocks.agent.threads import TurnError
from leela.blocks.agent.turns import save_mode, saved_modes
from leela.blocks.learn import host
from leela.blocks.modes import modes as M
from leela.blocks.modes.modes import Mode, cell_anchor, get_mode, modes, register_mode
from leela.core.session import DocStore
from leela.workspace import Workspace
from tests.fakemodel import WIDE, install


@pytest.fixture
def thread(ws, monkeypatch):
    install(ws, [], spec=WIDE)
    t = ws.threads.active
    monkeypatch.setattr(t.ai, 'refresh', lambda: t.ai._forget(files=False))
    monkeypatch.setattr(t.ai, 'mode_context', lambda: f'In {t.ai.mode}.' if t.ai.mode != 'code' else '')
    return t


@pytest.fixture
def cl(ws):
    install(ws, [], spec=WIDE)
    app = ide_app(ws)
    with TestClient(app) as c: yield c
    for h in app.router.routes:
        if isinstance(h, Mount) and isinstance(h.app, host.Hosted): h.app.stop()


@pytest.fixture
def home(tmp_path):
    return Workspace(roots=[tmp_path])


@pytest.fixture
def hcl(home):
    install(home, [], spec=WIDE)
    app = ide_app(home)
    with TestClient(app) as c: yield c
    for h in app.router.routes:
        if isinstance(h, Mount) and isinstance(h.app, host.Hosted): h.app.stop()


def test_code_is_the_base_mode_and_learn_registers_itself():
    ids = [m.id for m in modes()]
    assert ids[0] == 'code' and 'learn' in ids
    c, l = get_mode('code'), get_mode('learn')
    assert c.toolset(None) == [] and c.context(None) == '' and c.contract_check() == []
    assert l.tab_kinds == ('learn',) and l.settings_section == 'learn' and l.bar == 'learn'
    assert l.palette == ('Learn: Home', 'Learn: Graph', 'Learn: Progress', 'Ask about this page')
    assert l.layout['files'] is False and l.layout['exec'] is False and l.layout['exec_handle'] is False and l.layout['agent'] is True


def test_a_duplicate_id_is_refused_and_the_same_mode_twice_is_not(monkeypatch):
    monkeypatch.setattr(M, '_REG', dict(M._REG))
    m = register_mode(Mode('create', 'Create'))
    assert register_mode(m) is m and get_mode('create') is m
    with pytest.raises(ValueError, match='already registered'): register_mode(Mode('create', 'Other'))
    with pytest.raises(KeyError): get_mode('nope')
    with pytest.raises(KeyError): get_mode(['code'])


def test_the_old_learn_file_reads_as_learn_and_is_left_alone(tmp_path):
    (tmp_path/'agent-learn.json').write_text(json.dumps({'a': True, 'b': False}))
    assert saved_modes(tmp_path) == {'a': 'learn'}
    save_mode(tmp_path, 'a', 'code'); save_mode(tmp_path, 'c', 'learn')
    assert saved_modes(tmp_path) == {'a': 'code', 'c': 'learn'}
    assert json.loads((tmp_path/'agent-learn.json').read_text()) == {'a': True, 'b': False}
    assert json.loads((tmp_path/'agent-modes.json').read_text()) == {'a': 'code', 'c': 'learn'}


def test_a_conversation_keeps_its_mode_across_a_resume_and_reads_the_old_file(thread, monkeypatch):
    ai = thread.ai
    (Path(ai.cfg)/'agent-learn.json').write_text(json.dumps({'old-thread': True}))
    assert ai.saved_mode('old-thread') == 'learn' and ai.saved_mode('other') == 'code'
    thread.set_mode('learn'); ai.mode = 'code'
    monkeypatch.setattr(ai.__class__.__mro__[1], 'resume_session', lambda self, *a, **kw: None)
    ai.resume_session(thread.id)
    assert ai.mode == 'learn'


def test_set_mode_keeps_history_swaps_tools_and_the_alias_matches(thread):
    ai, history = thread.ai, thread.ai.history
    names = {f.__name__ for f in ai._mode_toolsets['learn']}
    assert names and not names & {f.__name__ for f in ai.tools}
    r = thread.set_mode('learn')
    assert r == dict(ok=True, mode='learn', on=True, thread=thread.id) and ai.mode == 'learn'
    assert names <= {f.__name__ for f in ai.tools} and ai.history is history
    stale = ai._mode_toolsets['learn'][0]
    thread.set_mode('code')
    assert not names & {f.__name__ for f in ai.tools}
    out = stale(goal='fractions')
    assert out['error'] == 'mode_off' and out['data']['mode'] == 'code' and out['data']['needs'] == 'learn'


def test_set_mode_refuses_unknown_busy_and_a_failed_contract_and_rolls_back(thread, monkeypatch):
    with pytest.raises(TurnError) as e: thread.set_mode('nope')
    assert e.value.code == 'invalid_mode'
    thread.runner._pending['q'] = {}
    try:
        with pytest.raises(TurnError) as e: thread.set_mode('learn')
        assert e.value.code == 'thread_busy' and thread.ai.mode == 'code'
    finally: thread.runner._pending.clear()
    monkeypatch.setattr(get_mode('learn'), 'contract_check', lambda: ['abhyasa.agent_tools.TOOLS'])
    with pytest.raises(TurnError) as e: thread.set_mode('learn')
    assert e.value.code == 'contract_missing' and thread.ai.mode == 'code'
    monkeypatch.undo()
    before = list(thread.ai.tools)
    def broken(): raise RuntimeError('refresh failed')
    monkeypatch.setattr(thread.ai, 'refresh', broken)
    with pytest.raises(RuntimeError, match='refresh failed'): thread.set_mode('learn')
    assert thread.ai.mode == 'code' and thread.ai.tools == before and thread.ai.saved_mode(thread.id) == 'code'


def test_the_alias_and_the_mode_endpoint_answer_alike_and_threads_carries_both_maps(cl):
    a = cl.post('/agent/learn-mode', json={'on': True}).json()
    assert a['ok'] and a['on'] is True and a['mode'] == 'learn'
    t = cl.get('/agent/threads').json()
    tid = t['active']
    assert t['modes'][tid] == 'learn' and t['learn_modes'][tid] is True and t['mode'] == 'code'
    b = cl.post('/agent/mode', json={'mode': 'code'}).json()
    assert b['ok'] and b['mode'] == 'code' and b['on'] is False
    assert cl.post('/agent/mode', json={'mode': 3}).status_code == 400
    assert cl.post('/agent/mode', json={'mode': 'nope'}).status_code == 409
    assert cl.post('/agent/learn-mode', json={'on': 'yes'}).status_code == 400


def test_a_busy_agent_blocks_the_workspace_switch_and_changes_nothing(ws, cl):
    ws.threads.active.runner._pending['q'] = {}
    try:
        r = cl.post('/workspace/mode', json={'mode': 'learn'})
        assert r.status_code == 409 and r.json()['code'] == 'thread_busy' and r.json()['ok'] is False
    finally: ws.threads.active.runner._pending.clear()
    assert ws.mode == 'code' and not [t for t in ws.tabs if t.kind == 'learn']


def test_the_workspace_mode_route_switches_both_and_lists_the_registry(ws, cl):
    d = cl.get('/workspace/mode').json()
    assert d['mode'] == 'code' and [m['id'] for m in d['modes']][:2] == ['code', 'learn']
    assert set(d['modes'][1]) == {'id', 'title', 'layout', 'palette', 'bar', 'tab_kinds'}
    r = cl.post('/workspace/mode', json={'mode': 'learn'}).json()
    assert r['ok'] and r['mode'] == 'learn' and r['focus'] == dict(kind='learn', path='/') and r['layout']['files'] is False
    assert ws.mode == 'learn' and ws.threads.active.ai.mode == 'learn'
    assert cl.post('/workspace/mode', json={'mode': 'nope'}).status_code == 400
    assert cl.post('/workspace/mode', json=[1]).status_code == 400
    assert cl.post('/workspace/mode', json={'mode': 'code'}).json()['mode'] == 'code' and ws.threads.active.ai.mode == 'code'


def test_a_state_change_takes_a_post_only(cl):
    assert cl.get('/workspace/layout').status_code == 405 and cl.put('/workspace/mode', json={}).status_code == 405


def test_each_mode_remembers_its_layout_and_the_state_round_trips(tmp_path, ws):
    ws._state_path, ws._owns_session = tmp_path/'ws.json', True
    got = ws.remember_layout('learn', {'files': True, 'bogus': 1, 'main': 'learn'})
    assert got['files'] is True and 'bogus' not in got and got['exec'] is False
    assert ws.mode_layout('code')['files'] is True
    with pytest.raises(KeyError): ws.remember_layout('nope', {})
    with pytest.raises(ValueError): ws.remember_layout('code', [])
    ws.set_mode('learn')
    back = Workspace.load(tmp_path/'ws.json')
    assert back.mode == 'learn' and back.mode_layout('learn')['files'] is True
    d = json.loads((tmp_path/'ws.json').read_text()); d['mode'] = 'gone'
    (tmp_path/'ws.json').write_text(json.dumps(d))
    assert Workspace.load(tmp_path/'ws.json').mode == 'code'


def test_the_layout_route_stores_and_merges(ws, cl):
    r = cl.post('/workspace/layout', json={'mode': 'learn', 'layout': {'agent': False}}).json()
    assert r['ok'] and r['layout']['agent'] is False and r['layout']['main'] == 'learn'
    assert cl.get('/workspace/mode').json()['layouts']['learn']['agent'] is False
    assert cl.post('/workspace/layout', json={'mode': 'nope', 'layout': {}}).status_code == 400
    assert cl.post('/workspace/layout', json={'mode': 'code', 'layout': 3}).status_code == 400


def test_focus_learn_has_one_tab_at_its_last_path_and_code_returns_to_the_last_editor_tab(home):
    ws = home
    (ws.fs.roots[0]/'a.py').write_text('x = 1\n'); (ws.fs.roots[0]/'b.py').write_text('y = 2\n')
    a, b = ws.open(str(ws.fs.roots[0]/'a.py')), ws.open(str(ws.fs.roots[0]/'b.py'))
    ws.activate(ws.tabs.index(a))
    n = len(ws.tabs)
    l1 = ws.set_mode('learn')
    assert l1['focus'] == dict(kind='learn', path='/') and len(ws.tabs) == n + 1 and ws.tab.kind == 'learn'
    ws.tab.page = '/w/walk-1/2'
    assert ws.set_mode('code')['focus'] == dict(kind='text', path=a.path) and ws.tab is a
    ws.activate(ws.tabs.index(b))
    assert ws.set_mode('learn')['focus'] == dict(kind='learn', path='/w/walk-1/2') and len(ws.tabs) == n + 1
    assert ws.set_mode('code')['focus']['path'] == b.path
    assert [t.kind for t in ws.tabs].count('learn') == 1


def test_code_with_only_the_learn_tab_has_no_active_tab_and_a_restore_keeps_it_so(home, tmp_path):
    ws = home
    ws.set_mode('learn')
    assert [t.kind for t in ws.tabs] == ['learn'] and ws.tab.kind == 'learn'
    assert ws.set_mode('code')['focus'] == dict(kind='', path='') and ws.tab is None and ws.mode == 'code'
    assert ws.cycle(1).kind == 'learn' and ws.close() is not None and ws.tab is None
    ws.set_mode('learn'); ws.mode = 'code'; ws.active = 0
    ws._settle_mode()
    assert ws.tab is None
    ws.set_mode('learn'); (ws.fs.roots[0]/'a.py').write_text('x = 1\n'); a = ws.open(str(ws.fs.roots[0]/'a.py'))
    ws.mode = 'code'; ws.activate(ws.tabs.index(ws.tabs.filter(lambda t: t.kind == 'learn')[0])); ws._settle_mode()
    assert ws.tab is a


def _nb(tmp_path):
    nb = {'cells': [
        {'cell_type': 'code', 'id': 'c1', 'metadata': {}, 'execution_count': 1, 'source': 'print("hi")', 'outputs': [{'output_type': 'stream', 'name': 'stdout', 'text': 'hi\n' * 3000}]},
        {'cell_type': 'code', 'id': 'c2', 'metadata': {}, 'execution_count': 2, 'source': 'y = 1/0',
         'outputs': [{'output_type': 'error', 'ename': 'ZeroDivisionError', 'evalue': 'division by zero', 'traceback': ['\x1b[31m---\x1b[0m', 'ZeroDivisionError: division by zero']}]},
        {'cell_type': 'markdown', 'id': 'c3', 'metadata': {}, 'source': 'notes'}],
        'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}
    p = tmp_path/'cells.ipynb'; p.write_text(json.dumps(nb))
    return p


def test_cell_anchor_carries_the_failing_cell_and_clips_output(home):
    ws = home
    p = _nb(ws.fs.roots[0])
    assert cell_anchor(ws) == ''
    ws.open(str(p))
    ws.docstore = DocStore(ws)
    a = cell_anchor(ws)
    assert '<active-cell id="c2" index="1"' in a and 'y = 1/0' in a and 'ZeroDivisionError: division by zero' in a and '\x1b' not in a and '<output>' not in a
    ws.note_cell('c1')
    b = cell_anchor(ws)
    assert 'id="c1"' in b and '<error>' not in b and '<output>' in b and len(b) < 2500
    assert cell_anchor(ws, 'c2').count('<active-cell') == 1 and 'id="c2"' in cell_anchor(ws, 'c2')
    ws.note_cell('missing')
    assert 'id="c2"' in cell_anchor(ws)
    ws.docstore.docs.clear()


def test_the_turn_context_has_the_anchor_in_code_mode_only(home, hcl):
    ws, cl = home, hcl
    p = _nb(ws.fs.roots[0])
    ws.open(str(p))
    seen = []
    runner = ws.threads.active.runner
    runner.start = lambda q, att, reasoning, context, path, grounding: seen.append(context) or {'ok': True}
    cl.post('/agent/turn', json={'prompt': 'why?', 'cell': 'c2'})
    assert '<active-cell id="c2"' in seen[-1] and '<cell id="c1"' in seen[-1]
    cl.post('/agent/mode', json={'mode': 'learn'})
    cl.post('/agent/turn', json={'prompt': 'why?', 'cell': 'c2'})
    assert '<active-cell' not in seen[-1]
