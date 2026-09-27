"Warm starts from dhrona's rounds: which seed a fresh conversation, why the rest were skipped, and the turn that records it."

import json, sys, pytest
from pathlib import Path
from leela.workspace import Workspace
from tests.fakemodel import WIDE, Step, install as _install
dhrona = pytest.importorskip('dhrona')

def install(ws, steps, token_delay=0.02):
    "The scripted backend on a full window: ramabana seeds only when `budget.inline` admits it, and the 8k default does not."
    return _install(ws, steps, token_delay=token_delay, spec=WIDE)


def a_round(name, tool='ls', args=None, rank=50, model=None):
    "An accepted round whose one call is `tool(**args)`."
    return {'meta': {'name': name, 'status': 'accepted', 'reviewer': 't', 'tools': [tool], 'rank': rank, 'model': model},
            'history': [
        {'role': 'user', 'content': [{'type': 'text', 'text': f'show me the tree ({name})'}]},
        {'role': 'assistant', 'content': [{'type': 'text', 'text': 'Listing first.'},
                                          {'type': 'tool_use', 'id': f'c_{name}', 'name': tool, 'arguments': args or {}}]},
        {'role': 'tool', 'content': [{'type': 'tool_result', 'id': f'c_{name}', 'name': tool, 'text': 'a.py'}]},
        {'role': 'assistant', 'content': [{'type': 'text', 'text': 'Done.'}]}]}


def use_library(monkeypatch, d):
    "Point dhrona's library at `d`: ramabana's warm start reads `fit_rounds` from `dhrona.core` at call time, and Leela's `with_messages` reads the same rounds back."
    import dhrona.core as dc
    monkeypatch.setattr(dc, 'load_rounds', lambda dirs=None, _f=dc.load_rounds: _f(dirs or [d]))


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


def test_the_assistant_hands_warm_to_ramabana(tmp_path):
    from leela.blocks.agent.ai import Assistant
    ws = Workspace(roots=[tmp_path])
    assert Assistant(ws, engines=False).warm is False and Assistant(ws, engines=False, warm=True).warm is True


def test_with_messages_paints_each_used_round_and_forgives_a_missing_one(rounds):
    from leela.blocks.agent.warm import with_messages
    rep = with_messages({'used': [{'name': 'fits', 'rank': 50, 'model': None}, {'name': 'gone', 'rank': 50, 'model': None}],
                         'skipped': [{'name': 'alien', 'reason': 'tool teleport is not offered here'}]})
    fits, gone = rep['used']
    assert [m['role'] for m in fits['messages']] == ['user', 'assistant', 'tool', 'assistant']
    assert fits['messages'][1]['tool_calls'][0]['name'] == 'ls' and fits['messages'][2]['tool_call_id'] == 'c_fits'
    assert gone['messages'] == [] and rep['skipped'][0]['name'] == 'alien'
    json.dumps(rep)   # what the feed and `/agent/thread/turns` carry


def test_a_warm_thread_is_seeded_once_and_the_turn_records_it(rounds, tmp_path):
    ws = Workspace(roots=[tmp_path]); t = ws.threads.new(warm=True)
    be = install(ws, [Step(text='hello')], token_delay=0)
    assert t.ai.budget.inline, 'the scripted window must admit seeds or this test proves nothing'
    t.ai.ask('first'); t.ai.ask('second')
    assert be.hist_[0]['role'] == 'user' and seeded_names(be) == ['ls']
    assert [m['role'] for m in be.hist_][:4] == ['user', 'assistant', 'tool', 'assistant']
    assert be.hist_[4]['content'].startswith('first')
    assert t.ai.history[-2]['plan']['warm'] == ['fits'] and 'warm' not in t.ai.history[-1]['plan']
    assert t.ai.warm_report['used'][0]['name'] == 'fits' and t.ai.warm_report['used'][0]['messages'][1]['tool_calls'][0]['name'] == 'ls'
    assert {s['name'] for s in t.ai.warm_report['skipped']} == {'alien', 'badsig'}


def test_default_off_and_resume_get_no_seeds(rounds, tmp_path, monkeypatch):
    ws = Workspace(roots=[tmp_path]); t = ws.threads.new()
    be = install(ws, [Step(text='hi')], token_delay=0); t.ai.ask('plain')
    assert not seeded_names(be) and t.ai.warm_report == {'used': [], 'skipped': []} and not t.ai._warmed
    sid = t.id
    # `Threads.resume` builds its own `Assistant`, and ramabana validates the logged model name on
    # resume, which the scripted one fails. So: a thread the fake is installed on, already routed
    # at it, resumes the session itself -- the same `resume_hist` path `Threads.resume` takes.
    ws2 = Workspace(roots=[tmp_path]); r = ws2.threads.new(warm=True)
    be2 = install(ws2, [Step(text='again')], token_delay=0)
    monkeypatch.setattr(r.ai, 'set_model', lambda name, job='turn': None)
    r.ai.refresh_history(); r.ai.resume_session(sid); r.ai.ask('more')
    assert not seeded_names(be2) and be2.hist_[0]['content'] == 'plain' and r.ai.warm_report == {'used': [], 'skipped': []}
    assert 'warm' not in r.ai.history[-1]['plan']


def test_missing_dhrona_is_a_note_not_a_failure(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, 'dhrona', None); monkeypatch.setitem(sys.modules, 'dhrona.core', None)
    ws = Workspace(roots=[tmp_path]); t = ws.threads.new(warm=True)
    said = []; monkeypatch.setattr(t.ai.host, 'note', said.append)
    be = install(ws, [Step(text='ok')], token_delay=0); t.ai.ask('x')
    assert be.hist_[0]['content'].startswith('x') and any('no warm start' in s for s in said)


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
        install(ws, [Step(text='cold')], token_delay=0); ws.ai.ask('first')
        turns = c.get('/agent/thread/turns', params={'thread': cold['active']}).json()
        assert turns['warm'] is None, 'a cold thread never paints an empty warm block'


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
    assert warm['used'][0]['name'] == 'fits' and warm['thread'] == t.id and warm['used'][0]['messages']


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
    install(ws, [Step(tool=('ls', {})), Step(text='two files')], token_delay=0); t.ai.ask('what is here?')
    from leela.blocks.agent.warm import capture_round, accept_round
    from dhrona.core import fit_rounds
    nb = capture_round(t.ai.history_path, t.id, tmp_path/'.dhrona'/'tree.ipynb', 'tree')
    assert Path(nb).exists()
    installed = accept_round(nb, 'Karthik')
    assert Path(installed).parent == lib and json.loads(Path(installed).read_text())['meta']['status'] == 'accepted'
    used, _ = fit_rounds(ws.ai._plain, dirs=[lib])
    assert [r['meta']['name'] for r in used] == ['tree']
    fresh = ws.threads.new(warm=True); be = install(ws, [Step(text='ok')], token_delay=0)
    use_library(monkeypatch, lib)
    fresh.ai.ask('again')
    assert seeded_names(be) == ['ls'] and fresh.ai.history[-1]['plan']['warm'] == ['tree']


def test_a_review_notebook_saved_by_leela_still_accepts(tmp_path, monkeypatch):
    "Editing the dialog in Leela is the review: its save must keep aidialog's cell and notebook metadata."
    library(tmp_path, monkeypatch)
    ws = Workspace(roots=[tmp_path]); t = ws.threads.new()
    install(ws, [Step(tool=('ls', {})), Step(text='two files')], token_delay=0); t.ai.ask('what is here?')
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


def test_accept_takes_only_a_review_notebook_under_the_roots_dhrona_folder(ws, tmp_path, monkeypatch):
    "A `source` outside `<root>/.dhrona/` is refused before dhrona touches it: accept saves the notebook and writes beside it."
    lib = library(tmp_path, monkeypatch)
    from starlette.testclient import TestClient
    from leela.app import ide_app
    elsewhere = tmp_path/'elsewhere'; elsewhere.mkdir()
    with TestClient(ide_app(ws)) as c:
        t = ws.threads.new(); install(ws, [Step(text='hello')], token_delay=0); ws.ai.ask('first')
        d = c.post('/agent/thread/capture', json={'thread': t.id, 'name': 'ok'}).json()
        stray = elsewhere/'stray.ipynb'; stray.write_bytes(Path(d['path']).read_bytes())
        for source in (str(stray), str(tmp_path/'.dhrona'/'..'/'elsewhere'/'stray.ipynb'), '/etc/passwd', ''):
            r = c.post('/agent/round/accept', json={'source': source, 'reviewer': 'Karthik'})
            assert r.status_code == 400 and '.dhrona' in r.json()['error'], source
        assert sorted(p.name for p in elsewhere.iterdir()) == ['stray.ipynb'] and not list(lib.iterdir())
        r = c.post('/agent/round/accept', json={'source': d['path'], 'reviewer': 'Karthik'}).json()
        assert r['ok'] and Path(r['installed']) == lib/'ok.json'


def test_the_installed_round_is_named_after_the_notebook_not_what_its_metadata_says(tmp_path, monkeypatch):
    lib = library(tmp_path, monkeypatch)
    ws = Workspace(roots=[tmp_path]); t = ws.threads.new()
    install(ws, [Step(tool=('ls', {})), Step(text='two files')], token_delay=0); t.ai.ask('what is here?')
    from leela.blocks.agent.warm import capture_round, accept_round, round_name
    src = Path(capture_round(t.ai.history_path, t.id, tmp_path/'.dhrona'/'..evil..ipynb', '../x'))
    nb = json.loads(src.read_text()); nb['metadata']['dhrona']['name'] = '../x'; src.write_text(json.dumps(nb))
    installed = Path(accept_round(src, 'Karthik'))
    assert installed.parent == lib and installed.name == 'evil.json'
    assert json.loads(installed.read_text())['meta']['name'] == 'evil'
    assert round_name('../../x') == 'x' and round_name('..') == 'round' and round_name('Hello World.v2') == 'Hello-World.v2'


def test_capture_without_an_open_folder_is_a_sentence_not_a_crash(ws, monkeypatch):
    from starlette.testclient import TestClient
    from leela.app import ide_app
    with TestClient(ide_app(ws)) as c:
        t = ws.threads.new(); install(ws, [Step(text='hello')], token_delay=0); ws.ai.ask('first')
        monkeypatch.setattr(ws.fs, 'roots', type(ws.fs.roots)())
        r = c.post('/agent/thread/capture', json={'thread': t.id})
        assert r.status_code == 400 and 'open a folder' in r.json()['error']
