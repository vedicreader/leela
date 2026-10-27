import builtins, json, shutil, subprocess, time
from concurrent.futures import ThreadPoolExecutor
import pytest
from abhyasa.store import Learning, slugify
from leela.blocks.memory.memory import Memory
from leela.blocks.nb.lesson import lesson_actual, lesson_feedback, lock
from leela.blocks.nb.nb import Notebook
from test_lesson_run import lesson_client
from test_lesson_reveal import CASES, ROOT

@pytest.fixture
def saved_lesson(lesson_client, tmp_path, monkeypatch):
    client, ws, path, _ = lesson_client
    monkeypatch.setenv('HOME', str(tmp_path/'home'))
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'vault.db'))
    monkeypatch.setattr(ws.memory, 'path', tmp_path/'vault.db')
    opened, original = [], Memory._store
    def guarded(self, name):
        assert self.path.resolve().is_relative_to(tmp_path.resolve()), self.path
        opened.append(name)
        return original(self, name)
    monkeypatch.setattr(Memory, '_store', guarded)
    nb = ws.docstore.doc_for(ws.tab)
    code = nb[3]
    code.execution_count = 1
    code.outputs = [dict(output_type='stream', name='stdout', text=['42', '\n'])]
    lock(code, '42', 70)
    nb[4].source = '### Question\n\nWhat prints?\n\n### Thinking\n\nI traced the call.'
    assert client.post('/nb/save', json={'path': str(path)}).json()['ok']
    return client, ws, path, nb, opened

@pytest.mark.parametrize('guess,correct,confidence', [('42', True, 70), ('wrong', False, 30), ('42', True, None)])
def test_save_records_once_and_schedules_review(saved_lesson, guess, correct, confidence):
    client, ws, path, nb, opened = saved_lesson
    lock(nb[3], guess, confidence)
    assert client.post('/nb/save', json={'path': str(path)}).json()['ok']
    body = dict(path=str(path), cell_id=nb[3].id)
    r = client.post('/lesson/save', json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data['ok'] and data['message'].startswith('Saved to your learning shelf. '), data
    assert 'Next review in ' in data['message']
    lr = Learning(ws.memory._store('learning'))
    attempts = lr.attempts(slugify(nb.meta['lesson']['name']), limit=10000)
    assert len(attempts) == 1
    a = attempts[0]
    key = f'{nb[3].id}:1'
    assert (a.card_key, a.correct, a.confidence, a.actual) == (key, correct, confidence, '42\n')
    assert (a.answer, a.question, a.thinking, a.kind, a.depth, a.notebook) == (guess, 'What prints?', 'I traced the call.', 'predict', 1, str(path))
    assert a.feedback == ('Right. You saw that before running it.' if correct else 'You wrote wrong. It printed 42.')
    c = lr.concept('output')
    assert c.seen == 1 and c.due > time.time()
    assert 'kind' not in c
    back = Notebook.load(path)[3].extra['lesson']
    assert back['saved'] == key
    again = client.post('/lesson/save', json=body)
    assert again.status_code == 200 and again.json()['message'] == data['message'], again.text
    assert len(lr.attempts('output', limit=10000)) == 1 and lr.concept('output').seen == 1
    assert opened and set(opened) == {'learning'}

@pytest.mark.parametrize('missing', ['guess', 'stale'])
def test_save_requires_a_run_with_a_guess(saved_lesson, missing):
    client, ws, path, nb, opened = saved_lesson
    if missing == 'guess': nb[3].extra.pop('lesson')
    else: nb[3].execution_count += 1
    r = client.post('/lesson/save', json=dict(path=str(path), cell_id=nb[3].id))
    assert r.status_code == 400, r.text
    assert r.json()['error'] == 'Run the cell after writing your guess, then save.'
    assert not opened

@pytest.mark.parametrize('unsaved', ['dirty', 'untitled', 'disk'])
def test_save_refuses_unsaved_notebook(saved_lesson, unsaved):
    client, ws, path, nb, opened = saved_lesson
    if unsaved == 'dirty':
        client.post('/nb/edit', json=dict(path=str(path), op='source', i=4, source='### Thinking\nchanged'))
    elif unsaved == 'untitled': path.unlink()
    else:
        disk = json.loads(path.read_text()); disk['cells'][4]['source'] = 'changed on disk'; path.write_text(json.dumps(disk))
    r = client.post('/lesson/save', json=dict(path=str(path), cell_id=nb[3].id))
    assert r.status_code == 400, r.text
    assert r.json()['error'] == 'Save the notebook first.'
    assert not opened

@pytest.mark.parametrize('failure', ['missing', 'locked'])
def test_save_reports_store_failure_and_allows_retry(saved_lesson, monkeypatch, failure):
    client, ws, path, nb, opened = saved_lesson
    body = dict(path=str(path), cell_id=nb[3].id)
    with monkeypatch.context() as patch:
        if failure == 'missing':
            original = builtins.__import__
            def unavailable(name, *args, **kwargs):
                if name == 'abhyasa.store': raise ModuleNotFoundError("No module named 'abhyasa'", name='abhyasa')
                return original(name, *args, **kwargs)
            patch.setattr(builtins, '__import__', unavailable)
        else:
            def locked(*args): raise PermissionError('locked')
            patch.setattr(Memory, '_store', locked)
        r = client.post('/lesson/save', json=body)
        assert r.status_code == 400, r.text
        assert ('abhyasa' if failure == 'missing' else 'locked or unreadable') in r.json()['error']
    assert client.post('/lesson/save', json=body).json()['ok']

@pytest.mark.parametrize('failure', ['record', 'update'])
def test_save_rolls_back_a_failed_attempt(saved_lesson, monkeypatch, failure):
    client, ws, path, nb, opened = saved_lesson
    body = dict(path=str(path), cell_id=nb[3].id)
    with monkeypatch.context() as patch:
        def failed(*args, **kwargs): raise OSError('write refused')
        patch.setattr(Learning, failure, failed)
        r = client.post('/lesson/save', json=body)
        assert r.status_code == 400, r.text
    r = client.post('/lesson/save', json=body)
    assert r.status_code == 200, r.text
    lr = Learning(ws.memory._store('learning'))
    assert len(lr.attempts('output', limit=10000)) == 1 and lr.concept('output').seen == 1

def test_simultaneous_saves_record_with_keywords_once(saved_lesson, monkeypatch):
    client, ws, path, nb, opened = saved_lesson
    original, calls = Learning.record, []
    def keywords(self, *args, **kwargs):
        assert not args and 'id' not in kwargs and 'at' not in kwargs
        calls.append(kwargs)
        return original(self, **kwargs)
    monkeypatch.setattr(Learning, 'record', keywords)
    body = dict(path=str(path), cell_id=nb[3].id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post('/lesson/save', json=body), range(2)))
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    assert len(calls) == 1 and results[0].json()['message'] == results[1].json()['message']

@pytest.mark.parametrize('name,guess,outputs,confidence,expected', CASES, ids=[c[0] for c in CASES])
def test_saved_feedback_matches_the_reveal(name, guess, outputs, confidence, expected):
    from leela.blocks.nb.nb import Cell
    cell = Cell(outputs=outputs, extra={'lesson': dict(prediction=guess, confidence=confidence)})
    assert lesson_feedback(cell) == expected
    node = shutil.which('node')
    if not node: pytest.skip('node is not installed')
    harness = '''const vm = require('vm'), fs = require('fs'), ctx = {}; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8').match(/const stripAnsi = .*;/)[0], ctx);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), ctx);
console.log(JSON.stringify(ctx.lessonActual(JSON.parse(process.argv[3]))));'''
    r = subprocess.run([node, '-e', harness, str(ROOT/'leela/blocks/nb/cells.js'), str(ROOT/'leela/blocks/nb/lesson.js'), json.dumps(cell.dict())], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert lesson_actual(cell) == json.loads(r.stdout)

def test_save_recovers_an_attempt_when_notebook_save_fails(saved_lesson, monkeypatch):
    client, ws, path, nb, opened = saved_lesson
    body = dict(path=str(path), cell_id=nb[3].id)
    with monkeypatch.context() as patch:
        def failed(*args, **kwargs): raise OSError('save refused')
        patch.setattr(Notebook, 'save', failed)
        r = client.post('/lesson/save', json=body)
        assert r.status_code == 400, r.text
    assert Notebook.load(path)[3].extra['lesson'].get('saved') is None
    r = client.post('/lesson/save', json=body)
    assert r.status_code == 200, r.text
    lr = Learning(ws.memory._store('learning'))
    assert len(lr.attempts('output', limit=10000)) == 1 and lr.concept('output').seen == 1
    assert Notebook.load(path)[3].extra['lesson']['saved'] == f'{nb[3].id}:1'

def test_retry_recreates_a_missing_concept_without_another_attempt(saved_lesson, monkeypatch):
    client, ws, path, nb, opened = saved_lesson
    body = dict(path=str(path), cell_id=nb[3].id)
    with monkeypatch.context() as patch:
        def failed(*args, **kwargs): raise OSError('save refused')
        patch.setattr(Notebook, 'save', failed)
        assert client.post('/lesson/save', json=body).status_code == 400
    lr = Learning(ws.memory._store('learning'))
    lr.drop('output')
    r = client.post('/lesson/save', json=body)
    assert r.status_code == 200, r.text
    assert len(lr.attempts('output', limit=10000)) == 1
    assert lr.concept('output').seen == 1 and lr.concept('output').due > time.time()
