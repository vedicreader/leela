"The run result Leela files from a lesson, the tries on a code attempt, and the concept on every attempt."
import json
from fastcore.basics import first
from abhyasa.contract import run_ok
from abhyasa.learner import Learning
from leela.blocks.memory.memory import Memory
from learn_data import rig  # noqa: F401
from leela.blocks.nb.lesson import exercise_filing, lesson_notebook, lock, record_card, record_exercise, record_run, run_filing, step_lesson

PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 64
STEP = dict(walk='comic-ab12', step=0, section='2 Captions', slug='caption-line')
NB = dict(task='Write `caption(ep)`.', fname='caption', stub='def caption(ep):\n    ...',
          tests=[dict(test="assert caption({'desc': 'a'}) == 'a'", say='one episode', shown=True)], data=[],
          run=dict(say='Run it.', makes='captions.jsonl', minutes=2, predict='How many?'))

def lesson_rig(tmp_path):
    nb = step_lesson('Caption', STEP, NB, file='comic-ab12-0.ipynb')
    folder = tmp_path/'comic-ab12-0.result'; folder.mkdir()
    return Memory(path=tmp_path/'vault.db', offline=True), nb, tmp_path/'comic-ab12-0.ipynb', folder

def result(folder, names=('0.png', '1.png'), metrics=None):
    for n in names: (folder/n).write_bytes(PNG)
    (folder/'result.json').write_text(json.dumps(dict(metrics=metrics or dict(loss=0.083, steps=500), images=list(names), device='cpu')))

def test_a_result_files_one_run_attempt_and_its_images_once(tmp_path):
    mem, nb, path, folder = lesson_rig(tmp_path)
    result(folder)
    f = run_filing(nb, path, folder)
    assert record_run(mem, f).startswith('Sent to your walk:')
    lr = Learning(mem._store('learning'))
    a, = lr.attempts(limit=10)
    assert run_ok(a) and a.kind == 'run' and a.metrics == dict(loss=0.083, steps=500) and a.makes == 'captions.jsonl' and a.device == 'cpu'
    root = lr.vault.assets()
    assert sorted(a.images) == ['leela/comic-ab12/0/0.png', 'leela/comic-ab12/0/1.png'] and all((root/p).read_bytes() == PNG for p in a.images)
    assert record_run(mem, run_filing(nb, path, folder)) is None
    assert len(lr.attempts(limit=10)) == 1 and len(list((root/'leela').rglob('*.png'))) == 2

def test_a_big_png_a_non_png_a_link_and_an_outside_path_are_skipped(tmp_path):
    mem, nb, path, folder = lesson_rig(tmp_path)
    result(folder, names=('0.png',))
    (folder/'1.png').write_bytes(PNG + b'0' * 2_000_000)
    (folder/'2.png').write_bytes(b'not a png')
    (tmp_path/'out.png').write_bytes(PNG); (folder/'3.png').symlink_to(tmp_path/'out.png')
    d = json.loads((folder/'result.json').read_text())
    (folder/'result.json').write_text(json.dumps({**d, 'images': ['0.png', '1.png', '2.png', '3.png', '../out.png']}))
    f = run_filing(nb, path, folder)
    assert run_ok(f) and f['images'] == ['leela/comic-ab12/0/0.png']
    record_run(mem, f)
    a, = Learning(mem._store('learning')).attempts(limit=10)
    assert run_ok(a) and a.images == ['leela/comic-ab12/0/0.png']

def test_a_bad_result_files_nothing(tmp_path):
    mem, nb, path, folder = lesson_rig(tmp_path)
    result(folder, metrics={f'm{i}': i for i in range(13)})
    assert run_filing(nb, path, folder) is None
    (folder/'result.json').write_text('not json')
    assert run_filing(nb, path, folder) is None
    assert run_filing(lesson_notebook('Plain'), path, folder) is None

def test_every_attempt_carries_the_step_concept(tmp_path):
    mem, nb, path, folder = lesson_rig(tmp_path)
    lr = Learning(mem._store('learning'))
    result(folder); record_run(mem, run_filing(nb, path, folder))
    code = first(c for c in nb.cells if c.extra.get('exercise', {}).get('tests'))
    code.extra['exercise']['state'].update(checks=1, passed=True, grade=dict(score=9, note='Clear.', hash=''))
    record_exercise(mem, exercise_filing(nb, code, path))
    card = lesson_notebook('Caption', step=STEP); run = card[3]
    run.source, run.execution_count = 'print(1)', 1
    run.outputs = [{'output_type': 'stream', 'name': 'stdout', 'text': '1\n'}]
    lock(run, '1'); record_card(mem, card, run, str(path))
    got = {a.kind: a.concept for a in lr.attempts(limit=10)}
    assert got == dict(run='caption-line', code='caption-line', predict='caption-line')
    assert 'concept' not in lesson_notebook('Caption', step={k: v for k, v in STEP.items() if k != 'slug'}).meta['lesson']['walk']

def test_a_code_attempt_counts_the_checks_up_to_and_with_the_pass(tmp_path):
    for checks in (1, 3):
        (tmp_path/str(checks)).mkdir()
        mem, nb, path, _ = lesson_rig(tmp_path/str(checks))
        code = first(c for c in nb.cells if c.extra.get('exercise', {}).get('tests'))
        code.extra['exercise']['state'].update(checks=checks, passed=True, grade=dict(score=9, note='Clear.', hash=''))
        f = exercise_filing(nb, code, path)
        assert f['tries'] == checks
        record_exercise(mem, f)
        a = first(a for a in Learning(mem._store('learning')).attempts(limit=10) if a.kind == 'code')
        assert a.tries == checks

def test_a_result_saved_beside_a_lesson_is_filed_by_the_file_watcher(rig):
    import time
    c, ws, lr, j, root = rig
    step_lesson('Caption', STEP, NB, file='comic-ab12-0.ipynb').save(root/'comic-ab12-0.ipynb')
    folder = root/'comic-ab12-0.result'; folder.mkdir()
    for _ in range(100):
        result(folder)   # saved again until the watcher is up; the same content files once
        if lr.attempts(limit=5): break
        time.sleep(.1)
    a, = lr.attempts(limit=5)
    assert run_ok(a) and a.kind == 'run'

def _ide(tmp_path, monkeypatch, sweep):
    "A lesson with its result already on disk, then the IDE over its folder: the watcher starts after the write. `sweep` is the seconds between two looks."
    import sys
    from contextlib import contextmanager
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.blocks.learn import app as learn_app
    from leela.workspace import Workspace
    monkeypatch.setattr(learn_app, 'SWEEP', sweep)
    nb = step_lesson('Caption', STEP, NB, file='comic-ab12-0.ipynb'); nb.save(p := tmp_path/'comic-ab12-0.ipynb')
    folder = tmp_path/'comic-ab12-0.result'; folder.mkdir(); result(folder)
    ws = Workspace(roots=[tmp_path], approvals='auto', python=sys.executable)
    monkeypatch.setattr(ws, 'memory', Memory(path=tmp_path/'vault.db', offline=True))
    @contextmanager
    def up():
        try:
            with TestClient(ide_app(ws), base_url='http://127.0.0.1:5011') as c: yield c, ws, p, nb, Learning(ws.memory._store('learning'))
        finally: ws.shutdown_now()
    return up()

def _until(f, secs=10):
    import time
    end = time.monotonic() + secs
    while not (got := f()) and time.monotonic() < end: time.sleep(.05)
    return got

def test_a_result_written_before_the_watcher_starts_is_filed_once_when_its_lesson_is_open(tmp_path, monkeypatch):
    "Smoke round 4: the first result.json of a lesson was not filed; the same file written again was."
    import time
    with _ide(tmp_path, monkeypatch, .1) as (c, ws, p, nb, lr):
        assert lr.attempts(limit=5) == [], 'no lesson is open yet'
        ws.open(p)
        a, = _until(lambda: lr.attempts(limit=5))
        assert run_ok(a) and a.kind == 'run'
        time.sleep(.5)
        assert len(lr.attempts(limit=5)) == 1, 'the next looks file nothing more'

def test_a_lesson_files_its_result_when_its_kernel_goes_idle(tmp_path, monkeypatch):
    import time
    with _ide(tmp_path, monkeypatch, 1000.) as (c, ws, p, nb, lr):
        ws.open(p)
        i = next(k for k, x in enumerate(nb.cells) if x.cell_type == 'markdown' and x.extra.get('lesson', {}).get('role') == 'prediction')
        assert c.post('/nb/run', json=dict(path=str(p), i=i, id=nb[i].id)).status_code == 200
        a, = _until(lambda: lr.attempts(limit=5))
        assert run_ok(a)
        assert c.post('/nb/run', json=dict(path=str(p), i=i, id=nb[i].id)).status_code == 200
        time.sleep(.5)
        assert len(lr.attempts(limit=5)) == 1, 'the same result files once'
