"Warm starts from dhrona's rounds: which seed a fresh conversation, why the rest were skipped, and the turn that records it."

import json, pytest
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


def library(tmp_path, monkeypatch):
    "A rounds library of this test's own, in place of `~/.config/dhrona/rounds`, for both dhrona modules that name it."
    lib = tmp_path/'lib'; lib.mkdir()
    import dhrona.rounds, dhrona.core
    monkeypatch.setattr(dhrona.rounds, 'ROUNDS_DIR', lib); monkeypatch.setattr(dhrona.core, 'ROUNDS_DIR', lib)
    return lib


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


