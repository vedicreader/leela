"Warm starts from dhrona's rounds: which seed a fresh conversation, why the rest were skipped, and the turn that records it."

import json, sys, pytest
from pathlib import Path
from leela.workspace import Workspace
from tests.fakemodel import Step, install
dhrona = pytest.importorskip('dhrona')


def a_round(name, tool='list_files', args=None, rank=50, model=None):
    "An accepted round whose one call is `tool(**args)`."
    return {'meta': {'name': name, 'status': 'accepted', 'reviewer': 't', 'tools': [tool], 'rank': rank, 'model': model},
            'history': [
        {'role': 'user', 'content': [{'type': 'text', 'text': f'show me the tree ({name})'}]},
        {'role': 'assistant', 'content': [{'type': 'text', 'text': 'Listing first.'},
                                          {'type': 'tool_use', 'id': f'c_{name}', 'name': tool, 'arguments': args or {}}]},
        {'role': 'tool', 'content': [{'type': 'tool_result', 'id': f'c_{name}', 'name': tool, 'text': 'a.py'}]},
        {'role': 'assistant', 'content': [{'type': 'text', 'text': 'Done.'}]}]}


def use_library(monkeypatch, d):
    "Point Leela's `fit_rounds` at the library `d` rather than the config dir and the packaged seeds."
    from leela.blocks.agent import warm
    monkeypatch.setattr(warm, 'fit_rounds', lambda tools, model=None, limit=warm.WARM_ROUNDS, dirs=None, _f=warm.fit_rounds:
                        _f(tools, model, limit, dirs=[d]))


@pytest.fixture
def rounds(tmp_path, monkeypatch):
    "A rounds library of three: one that binds, one naming a tool Leela lacks, one with a bad signature."
    d = tmp_path/'rounds'; d.mkdir()
    for r in (a_round('fits'), a_round('alien', tool='teleport'), a_round('badsig', args={'nope': 1})):
        (d/f"{r['meta']['name']}.json").write_text(json.dumps(r))
    use_library(monkeypatch, d)
    return d


def seeded_names(be):
    "The tools the seeds called, from the backend's history (urai's `ToolCall` is OpenAI-shaped)."
    return [tc['function']['name'] for m in be.hist_ if m.get('tool_calls') for tc in m['tool_calls']]


def test_fit_rounds_explains_every_skip(rounds, ws):
    from leela.blocks.agent.warm import fit_rounds, warm_report
    used, skipped = fit_rounds(ws.ai._plain, dirs=[rounds])
    assert [r['meta']['name'] for r in used] == ['fits']
    reasons = {r['meta']['name']: why for r, why in skipped}
    assert reasons['alien'] == 'tool teleport is not offered here' and 'does not match' in reasons['badsig']
    rep = warm_report(used, skipped)
    assert rep['used'][0]['messages'][0]['role'] == 'user' and len(rep['skipped']) == 2
    assert rep['used'][0]['messages'][1]['tool_calls'][0]['name'] == 'list_files'
    assert rep['used'][0]['messages'][2]['tool_call_id'] == 'c_fits'
    json.dumps(rep)   # what the feed and `/agent/thread/turns` carry


def test_fit_rounds_agrees_with_dhrona_warm_start(rounds, ws):
    from leela.blocks.agent.warm import fit_rounds, warm_messages
    used, _ = fit_rounds(ws.ai._plain, dirs=[rounds])
    assert warm_messages(used) == dhrona.core.warm_start(ws.ai._plain, limit=3, dirs=[rounds])


def test_a_warm_thread_is_seeded_once_and_the_turn_records_it(rounds, tmp_path):
    ws = Workspace(roots=[tmp_path]); t = ws.threads.new(warm=True)
    be = install(ws, [Step(text='hello')], token_delay=0)
    t.ai.ask('first'); t.ai.ask('second')
    assert be.hist_[0]['role'] == 'user' and seeded_names(be) == ['list_files']
    assert [m['role'] for m in be.hist_][:4] == ['user', 'assistant', 'tool', 'assistant']
    assert be.hist_[4]['content'].startswith('first')
    assert t.ai.history[-2]['plan']['warm'] == ['fits'] and 'warm' not in t.ai.history[-1]['plan']
    assert t.ai.warm_report['used'][0]['name'] == 'fits' and {s['name'] for s in t.ai.warm_report['skipped']} == {'alien', 'badsig'}


def test_default_off_and_resume_get_no_seeds(rounds, tmp_path, monkeypatch):
    ws = Workspace(roots=[tmp_path]); t = ws.threads.new()
    be = install(ws, [Step(text='hi')], token_delay=0); t.ai.ask('plain')
    assert not seeded_names(be) and t.ai.warm_report is None
    sid = t.id
    # `Threads.resume` builds its own `Assistant`, and ramabana validates the logged model name on
    # resume, which the scripted one fails. So: a thread the fake is installed on, already routed
    # at it, resumes the session itself -- the same `resume_hist` path `Threads.resume` takes.
    ws2 = Workspace(roots=[tmp_path]); r = ws2.threads.new(warm=True)
    be2 = install(ws2, [Step(text='again')], token_delay=0)
    monkeypatch.setattr(r.ai, 'set_model', lambda name, job='turn': None)
    r.ai.refresh_history(); r.ai.resume_session(sid); r.ai.ask('more')
    assert not seeded_names(be2) and be2.hist_[0]['content'] == 'plain' and r.ai.warm_report is None
    assert 'warm' not in r.ai.history[-1]['plan']


def test_missing_dhrona_is_a_note_not_a_failure(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, 'dhrona', None)
    ws = Workspace(roots=[tmp_path]); t = ws.threads.new(warm=True)
    be = install(ws, [Step(text='ok')], token_delay=0); t.ai.ask('x')
    assert be.hist_[0]['content'].startswith('x') and t.ai.warm_report['problem'].startswith('warm starts need')
    assert 'no warm start' in t.ai.note


def test_no_round_fits_says_so(rounds, tmp_path):
    (rounds/'fits.json').unlink()
    ws = Workspace(roots=[tmp_path]); t = ws.threads.new(warm=True)
    install(ws, [Step(text='ok')], token_delay=0); t.ai.ask('x')
    assert t.ai.warm_report['used'] == [] and len(t.ai.warm_report['skipped']) == 2


def test_thread_new_takes_warm_and_turns_reports_the_block(rounds, ws):
    from starlette.testclient import TestClient
    from leela.app import ide_app
    with TestClient(ide_app(ws)) as c:
        d = c.post('/agent/thread/new', json={'warm': True}).json()
        assert d['ok'] and d['warm'] is True and d['thread']['warm'] is True
        install(ws, [Step(text='hello')], token_delay=0); ws.ai.ask('first')
        turns = c.get('/agent/thread/turns', params={'thread': d['active']}).json()
        assert turns['warm']['used'][0]['name'] == 'fits' and turns['warm_on'] is True
        assert [m['role'] for m in turns['warm']['used'][0]['messages']] == ['user', 'assistant', 'tool', 'assistant']
        cold = c.post('/agent/thread/new', json={}).json()
        assert cold['warm'] is False and cold['thread']['warm'] is False
        bare = c.post('/agent/thread/new').json()      # the old client sends no body at all
        assert bare['ok'] and bare['warm'] is False
        turns = c.get('/agent/thread/turns', params={'thread': cold['active']}).json()
        assert turns['warm'] is None and turns['warm_on'] is False


def test_the_warm_feed_event_precedes_the_first_chunk(rounds, tmp_path):
    ws = Workspace(roots=[tmp_path]); t = ws.threads.new(warm=True)
    install(ws, [Step(text='hello')], token_delay=0)
    t.runner.start('first')
    for _ in range(50):
        events = [row['event'] for row in t.feed.since(0)]
        if 'done' in events: break
        t.feed.wait(t.feed.seq, timeout=5)
    assert 'warm' in events and events.index('warm') < events.index('done')
    warm = next(row['data'] for row in t.feed.since(0) if row['event'] == 'warm')
    assert warm['used'][0]['name'] == 'fits' and warm['thread'] == t.id


def library(tmp_path, monkeypatch):
    "A rounds library of this test's own, in place of `~/.config/dhrona/rounds`, for both dhrona modules that name it."
    lib = tmp_path/'lib'; lib.mkdir()
    import dhrona.rounds, dhrona.core
    monkeypatch.setattr(dhrona.rounds, 'ROUNDS_DIR', lib); monkeypatch.setattr(dhrona.core, 'ROUNDS_DIR', lib)
    return lib


def test_assess_scores_this_thread_and_tags_turns(tmp_path):
    ws = Workspace(roots=[tmp_path]); t = ws.threads.new()
    install(ws, [Step(tool=('run_shell', {'command': 'git status'})), Step(text='clean')], token_delay=0)
    t.ai.ask('is the tree clean?')
    from leela.blocks.agent.warm import assess_session
    a = assess_session(t.ai.history_path, t.id)
    assert a['turns'] == 1 and a['calls'] == 1
    assert any(f['kind'] == 'bypass' and f['turn'] == 0 and f['tool'] == 'run_shell' for f in a['findings'])
    assert a['findings'][0]['turn_id'] == t.ai.history[-1]['turn_id']
    assert a['score'] == 100 - 20*len(a['findings'])
    json.dumps(a)


def test_capture_then_accept_installs_a_round_the_next_warm_thread_replays(tmp_path, monkeypatch):
    lib = library(tmp_path, monkeypatch)
    ws = Workspace(roots=[tmp_path]); t = ws.threads.new()
    install(ws, [Step(tool=('list_files', {})), Step(text='two files')], token_delay=0); t.ai.ask('what is here?')
    from leela.blocks.agent.warm import capture_round, accept_round, fit_rounds
    nb = capture_round(t.ai.history_path, t.id, tmp_path/'.dhrona'/'tree.ipynb', 'tree')
    assert Path(nb).exists()
    installed = accept_round(nb, 'Karthik')
    assert Path(installed).parent == lib and json.loads(Path(installed).read_text())['meta']['status'] == 'accepted'
    used, _ = fit_rounds(ws.ai._plain, dirs=[lib])
    assert [r['meta']['name'] for r in used] == ['tree']
    fresh = ws.threads.new(warm=True); be = install(ws, [Step(text='ok')], token_delay=0)
    use_library(monkeypatch, lib)
    fresh.ai.ask('again')
    assert seeded_names(be) == ['list_files'] and fresh.ai.history[-1]['plan']['warm'] == ['tree']


def test_a_review_notebook_saved_by_leela_still_accepts(tmp_path, monkeypatch):
    "Editing the dialog in Leela is the review: its save must keep aidialog's cell and notebook metadata."
    library(tmp_path, monkeypatch)
    ws = Workspace(roots=[tmp_path]); t = ws.threads.new()
    install(ws, [Step(tool=('list_files', {})), Step(text='two files')], token_delay=0); t.ai.ask('what is here?')
    from leela.blocks.agent.warm import capture_round, accept_round
    from leela.blocks.nb.nb import Notebook
    src = capture_round(t.ai.history_path, t.id, tmp_path/'.dhrona'/'edited.ipynb')
    nb = Notebook.load(src); nb.save(src)
    from dhrona.rounds import read_dialog
    dlg = read_dialog(src)
    assert dlg.meta['dhrona']['status'] == 'review' and [m for m in dlg if m.msg_type == 'prompt' and not m.skipped]
    installed = accept_round(src, 'Karthik')
    history = json.loads(Path(installed).read_text())['history']
    assert history[0]['role'] == 'user' and 'two files' in json.dumps(history)


def test_capture_and_accept_routes(ws, tmp_path, monkeypatch):
    library(tmp_path, monkeypatch)
    from starlette.testclient import TestClient
    from leela.app import ide_app
    with TestClient(ide_app(ws)) as c:
        t = ws.threads.new()
        install(ws, [Step(text='hello')], token_delay=0); ws.ai.ask('first')
        d = c.post('/agent/thread/capture', json={'thread': t.id, 'name': 'Hello World'}).json()
        assert d['ok'] and d['name'] == 'hello-world' and d['path'].endswith('/.dhrona/hello-world.ipynb')
        assert Path(d['path']).is_relative_to(tmp_path)
        assert 'lee-err' not in c.post('/tab/open', data={'path': d['path']}).text   # the review is reachable as a tab
        r = c.post('/agent/round/accept', json={'source': d['path'], 'reviewer': ''})
        assert r.status_code == 400 and 'reviewer' in r.json()['error']
        r = c.post('/agent/round/accept', json={'source': d['path'], 'reviewer': 'Karthik'}).json()
        assert r['ok'] and Path(r['installed']).exists()
        a = c.post('/agent/thread/assess', json={'thread': t.id}).json()
        assert a['ok'] and a['score'] == 100 and a['turns'] == 1
        empty = ws.threads.new()
        assert c.post('/agent/thread/capture', json={'thread': empty.id}).status_code == 400
