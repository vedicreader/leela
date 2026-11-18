import json
import pytest
from abhyasa.learner import Learning
from leela.blocks.nb import lesson as teaching
from leela.blocks.nb.nb import src_hash
from test_lesson_predict import serve, rig, lesson, post, shelf, picks


def rows(r): return list(shelf(r).attempts('halves', limit=10000))


def test_prediction_freezes_identity_inputs_and_assistance(rig):
    response = post(rig, picked=4, why='Two equal parts.', evidence_id='attempt-1', inputs={}, assistance=['hint'])
    assert response.status_code == 200, response.text
    records = rows(rig)
    prediction = next(a for a in records if a.kind == 'demo')
    assert prediction.evidence_id == 'attempt-1'
    assert prediction.source_hash == src_hash(rig.nb[1].source)
    assert prediction.inputs == {} and prediction.assistance == ['hint']
    assert prediction.thinking == '' and prediction.depth <= 2
    explanation = next(a for a in records if a.kind == 'explanation')
    assert explanation.of == prediction.id and explanation.thinking == 'Two equal parts.'
    assert explanation.grade_status == 'pending'
    assert shelf(rig).concept('halves').seen == 1


def test_vault_commit_before_response_retry_is_once(rig, monkeypatch):
    from leela.blocks.nb import app
    original = app.record_prediction
    def interrupted(*args):
        original(*args)
        raise OSError('interrupted after vault commit')
    with monkeypatch.context() as patch:
        patch.setattr(app, 'record_prediction', interrupted)
        assert post(rig, picked=4, why='Two parts.', evidence_id='retry-1', inputs={}).status_code == 400
    assert post(rig, picked=4, why='Two parts.', evidence_id='retry-1', inputs={}).status_code == 200
    assert len([a for a in rows(rig) if a.kind == 'demo']) == 1
    assert len([a for a in rows(rig) if a.kind == 'explanation']) == 1
    assert picks(rig).json()['picks'] == {'halves:g1': '4'}


def test_read_only_cannot_file(rig, monkeypatch):
    monkeypatch.setattr(rig.ws.fs, 'read_only', lambda path: True)
    response = post(rig, picked=4, evidence_id='readonly', inputs={})
    assert response.status_code == 403
    assert rows(rig) == []


def test_explanation_grades_outside_storage_lock_and_retries(rig, monkeypatch):
    import threading
    from leela.blocks.memory.memory import _open_lock
    post(rig, picked=4, why='Two equal parts.', evidence_id='grade-1', inputs={})
    explanation = next(a for a in rows(rig) if a.kind == 'explanation')
    seen = shelf(rig).concept('halves').seen
    acquired = []
    def grade(*args):
        def probe():
            with _open_lock(rig.ws.memory.path): acquired.append(True)
        thread = threading.Thread(target=probe); thread.start(); thread.join(2)
        assert acquired
        return None
    monkeypatch.setattr('abhyasa.show.grade_why', grade)
    teaching.grade_explanation(rig.ws.memory, explanation.id, object())
    assert next(a for a in rows(rig) if a.id == explanation.id).grade_status == 'pending'
    monkeypatch.setattr('abhyasa.show.grade_why', lambda *args: dict(correct=True, grade=9, feedback='The reason holds.'))
    teaching.grade_explanation(rig.ws.memory, explanation.id, object())
    assert next(a for a in rows(rig) if a.id == explanation.id).grade_status == 'graded'
    assert shelf(rig).concept('halves').seen == seen


def transfer_body(r): return dict(path=str(r.p), cell_id=r.nb[1].id, demo='throw-angle', src=src_hash(r.nb[1].source))


def test_transfer_requires_kept_run_and_files_separate_unaided_item(serve):
    from rupaka.spec import gallery
    from leela.blocks.nb.lesson import fence
    r = serve(lesson(fence(gallery()['throw-angle'])))
    body = transfer_body(r)
    assert r.c.post('/lesson/transfer', json=body).status_code == 400
    assert post(r, demo='throw-angle', gate='g', picked=60, evidence_id='first', inputs={'a': 30, 't': .5}).status_code == 200
    edit = dict(op='rupaka_trial', path=str(r.p), id=r.nb[1].id, i=1, demo='throw-angle', src=body['src'], rev=0, inputs={'a': 30, 't': .5})
    assert r.c.post('/nb/edit', json=edit).status_code == 200
    response = r.c.post('/lesson/transfer', json=body)
    assert response.status_code == 200, response.text
    question = response.json()
    assert question['spec']['id'] != 'throw-angle' and 'plot' not in json.dumps(question['spec'])
    submit = dict(body, transfer_id=question['transfer_id'], picked=70)
    saved = r.c.post('/lesson/transfer', json=submit)
    assert saved.status_code == 200, saved.text
    assert r.c.post('/lesson/transfer', json=submit).status_code == 200
    records = rows(r)
    prediction = next(a for a in records if a.kind == 'demo')
    transfer = next(a for a in records if a.kind == 'transfer')
    assert transfer.id != prediction.id and not transfer.aided and transfer.correct
    assert transfer.source_hash == body['src'] and transfer.inputs == {'a': 30, 't': .5}
    assert len([a for a in records if a.kind == 'transfer']) == 1
    assert shelf(r).concept('halves').floor == 5


@pytest.mark.parametrize('help_kind', ['hint', 'tutor', 'demo', 'reveal'])
def test_help_since_transfer_appeared_prevents_deeper_credit(serve, help_kind):
    from rupaka.spec import gallery
    from leela.blocks.nb.lesson import fence
    r = serve(lesson(fence(gallery()['throw-angle'])))
    body = transfer_body(r)
    post(r, demo='throw-angle', gate='g', picked=60, inputs={'a': 30, 't': .5})
    r.c.post('/nb/edit', json=dict(op='rupaka_trial', path=str(r.p), id=r.nb[1].id, i=1, demo='throw-angle', src=body['src'], rev=0, inputs={'a': 30, 't': .5}))
    question = r.c.post('/lesson/transfer', json=body).json()
    response = r.c.post('/lesson/assist', json=dict(body, kind=help_kind))
    assert response.status_code == 200, response.text
    assert r.c.post('/lesson/transfer', json=dict(body, transfer_id=question['transfer_id'], picked=70, assistance=[])).status_code == 200
    transfer = next(a for a in rows(r) if a.kind == 'transfer')
    assert transfer.aided and shelf(r).concept('halves').floor <= 2


def test_transfer_identity_survives_workspace_restart(serve):
    from rupaka.spec import gallery
    from leela.blocks.nb.lesson import fence
    from leela.blocks.nb.nb import Notebook
    r = serve(lesson(fence(gallery()['throw-angle'])))
    body = transfer_body(r)
    post(r, demo='throw-angle', gate='g', picked=60, inputs={'a': 30, 't': .5})
    r.c.post('/nb/edit', json=dict(op='rupaka_trial', path=str(r.p), id=r.nb[1].id, i=1, demo='throw-angle', src=body['src'], rev=0, inputs={'a': 30, 't': .5}))
    question = r.c.post('/lesson/transfer', json=body).json()
    saved = Notebook.load(r.p)[1].extra['rupaka']['throw-angle']['transfer']
    assert saved['id'] == question['transfer_id']


def test_tutor_request_marks_pending_transfer_before_grading(serve, monkeypatch):
    from rupaka.spec import gallery
    from leela.blocks.nb.lesson import fence
    from leela.blocks.nb import app
    r = serve(lesson(fence(gallery()['throw-angle'])))
    body = transfer_body(r)
    post(r, demo='throw-angle', gate='g', picked=60, inputs={'a': 30, 't': .5})
    r.c.post('/nb/edit', json=dict(op='rupaka_trial', path=str(r.p), id=r.nb[1].id, i=1, demo='throw-angle', src=body['src'], rev=0, inputs={'a': 30, 't': .5}))
    question = r.c.post('/lesson/transfer', json=body).json()
    monkeypatch.setattr(app, 'guide_board', lambda *a, **kw: {})
    response = r.c.post('/nb/guide', json=dict(path=str(r.p), cell_id=r.nb[1].id, said='Give me a hint.'))
    assert response.status_code == 200, response.text
    response = r.c.post('/lesson/transfer', json=dict(body, transfer_id=question['transfer_id'], picked=70))
    assert response.status_code == 200, response.text
    assert next(a for a in rows(r) if a.kind == 'transfer').aided


@pytest.fixture
def transfer_rig(serve):
    from rupaka.spec import gallery
    from leela.blocks.nb.lesson import fence
    r = serve(lesson(fence(gallery()['throw-angle'])))
    body = transfer_body(r)
    post(r, demo='throw-angle', gate='g', picked=60, inputs={'a': 30, 't': .5})
    r.c.post('/nb/edit', json=dict(op='rupaka_trial', path=str(r.p), id=r.nb[1].id, i=1, demo='throw-angle', src=body['src'], rev=0, inputs={'a': 30, 't': .5}))
    question = r.c.post('/lesson/transfer', json=body).json()
    return r, body, question


def test_reopening_demo_after_transfer_appeared_marks_reveal(transfer_rig):
    r, body, question = transfer_rig
    assert picks(r).status_code == 200
    response = r.c.post('/lesson/transfer', json=dict(body, transfer_id=question['transfer_id'], picked=70))
    assert response.status_code == 200, response.text
    assert next(a for a in rows(r) if a.kind == 'transfer').aided


def test_general_tutor_context_marks_assistance(transfer_rig):
    r, body, question = transfer_rig
    r.ws._grounding([], '', context_path=str(r.p))
    response = r.c.post('/lesson/transfer', json=dict(body, transfer_id=question['transfer_id'], picked=70))
    assert response.status_code == 200, response.text
    assert next(a for a in rows(r) if a.kind == 'transfer').aided


def test_prediction_identity_cannot_file_another_question(rig):
    assert post(rig, picked=4, evidence_id='same-id').status_code == 200
    rig.nb[1].source += '\nChanged question version.'
    response = post(rig, picked=4, evidence_id='same-id')
    assert response.status_code == 409, response.text
    assert len(rows(rig)) == 1


def test_presentation_start_marks_reveal(transfer_rig):
    r, body, question = transfer_rig
    response = r.c.post('/present/start', json=dict(path=str(r.p), cells=[r.nb[1].dict()], line=[dict(items=[dict(i=0, frag=-1)], notes=[], groups=0)], start=dict(slide=0, step=0)))
    assert response.status_code == 200, response.text
    assert r.nb[1].extra['rupaka']['throw-angle']['transfer']['assistance'] == ['reveal']


def test_add_demo_marks_active_transfer_as_aided(transfer_rig):
    from leela.blocks.agent.ai import _session_tools
    r, body, question = transfer_rig
    tools = {f.__name__: f for f in _session_tools(r.ws.inline_ai.host)}
    result = tools['add_demo'](str(r.p), dict(rupaka=1, id='help', state={}, blocks=[dict(type='gate', id='h', prompt='Which angles pair?', options=[60, 70], answer={'is': 60})]))
    assert any(c.id == result for c in r.nb.cells), result
    assert r.nb[1].extra['rupaka']['throw-angle']['transfer']['assistance'] == ['demo']


def test_reload_returns_pending_explanation_without_regrading(rig):
    assert post(rig, picked=4, why='Two equal parts.', evidence_id='explain-reload', inputs={}).status_code == 200
    response = picks(rig).json()
    assert response['explanations']['halves:g1']['status'] == 'pending'
    assert response['explanations']['halves:g1']['id'] == next(a for a in rows(rig) if a.kind == 'explanation').id


def test_transfer_crash_after_vault_commit_retries_once(transfer_rig, monkeypatch):
    from leela.blocks.nb import app
    r, body, question = transfer_rig
    original = app.record_transfer
    def interrupted(*args):
        original(*args)
        raise OSError('interrupted after vault commit')
    submit = dict(body, transfer_id=question['transfer_id'], picked=70)
    with monkeypatch.context() as patch:
        patch.setattr(app, 'record_transfer', interrupted)
        assert r.c.post('/lesson/transfer', json=submit).status_code == 400
    response = r.c.post('/lesson/transfer', json=submit)
    assert response.status_code == 200, response.text
    assert len([a for a in rows(r) if a.kind == 'transfer']) == 1


def test_completed_transfer_replay_cannot_claim_another_answer(transfer_rig):
    r, body, question = transfer_rig
    submit = dict(body, transfer_id=question['transfer_id'], picked=70)
    assert r.c.post('/lesson/transfer', json=submit).status_code == 200
    response = r.c.post('/lesson/transfer', json=dict(submit, picked=80))
    assert response.status_code == 409, response.text


def test_new_server_process_cannot_claim_old_transfer_unaided(transfer_rig):
    from starlette.testclient import TestClient
    from leela.app import ide_app
    r, body, question = transfer_rig
    with TestClient(ide_app(r.ws)) as client:
        client.get('/tab/state')
        response = client.post('/lesson/transfer', json=dict(body, transfer_id=question['transfer_id'], picked=70))
        assert response.status_code == 200, response.text
        assert response.json()['aided']


def test_readonly_owner_cannot_be_bypassed_by_omitting_path(rig, monkeypatch):
    monkeypatch.setattr(rig.ws.fs, 'read_only', lambda path: True)
    response = rig.c.post('/lesson/predict', json=dict(cell_id=rig.nb[1].id, demo='halves', gate='g1', src=src_hash(rig.nb[1].source), picked=4, evidence_id='readonly-owner'))
    assert response.status_code == 403, response.text
    assert rows(rig) == []


def test_general_tutor_before_prediction_is_filed_as_assisted(rig):
    rig.ws._grounding([], '', context_path=str(rig.p))
    assert post(rig, picked=4, evidence_id='tutor-before', inputs={}).status_code == 200
    assert 'tutor' in rows(rig)[0].assistance


def test_file_preview_during_transfer_marks_reveal(transfer_rig):
    r, body, question = transfer_rig
    preview = r.p.parent/'help.md'; preview.write_text('Complementary angles have equal ranges.')
    r.ws.open(preview)
    assert 'reveal' in r.nb[1].extra['rupaka']['throw-angle']['transfer']['assistance']


def test_initial_restore_is_not_help(rig):
    assert picks(rig).status_code == 200
    assert post(rig, picked=4, evidence_id='unassisted-first', inputs={}).status_code == 200
    assert rows(rig)[0].assistance == []


def test_legacy_client_reason_still_files_separate_evidence(rig):
    assert post(rig, picked=4, why='Two equal parts.').status_code == 200
    assert len([a for a in rows(rig) if a.kind == 'explanation']) == 1
    assert next(a for a in rows(rig) if a.kind == 'demo').thinking == ''


def test_concurrent_experiment_metadata_is_a_conflict(tmp_path):
    from leela.blocks.nb.nb import Cell, Notebook
    path = tmp_path/'shared.ipynb'
    Notebook([Cell(cell_type='markdown', source='Question', extra={'rupaka': {'demo': {'v': 1, 'rev': 0, 'inputs': {}}}})]).save(path)
    mine, theirs = Notebook.load(path), Notebook.load(path)
    mine[0].extra['rupaka']['demo']['transfer'] = dict(id='mine', assistance=['tutor'])
    theirs[0].extra['rupaka']['demo']['transfer'] = dict(id='theirs', assistance=[])
    assert mine.take_disk(theirs) == [theirs[0]]
    assert mine[0].extra['rupaka']['demo']['transfer']['assistance'] == ['tutor']


def test_landed_prediction_retry_cannot_reveal_a_changed_pick(rig):
    assert post(rig, picked=2, evidence_id='landed-before-timeout', inputs={}).status_code == 200
    response = post(rig, picked=4, evidence_id='landed-before-timeout', inputs={})
    assert response.status_code == 409, response.text
    assert next(a for a in rows(rig) if a.kind == 'demo').answer == '2'
