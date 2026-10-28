"Walk lessons: the passage in the first cell, the walk in the meta, and the walk meta on each check filed from one."
from fastcore.basics import first
from abhyasa.store import Learning
from leela.blocks.memory.memory import Memory
from leela.blocks.nb.lesson import exercise_filing, lesson_notebook, lock, prediction_filing, record_card, walk_meta

STEP = dict(walk='attention-ab12', step=0, section='2 Background', text='Softmax maps scores to weights.\nThe sum is 1.', note='Watch the sum.')
WALK = {'walk': 'attention-ab12', 'step': 0, 'section': '2 Background', 'from': 'attention-ab12/0', 'app': 'leela'}

def test_walk_meta():
    assert walk_meta(lesson_notebook('Softmax', step=STEP)) == WALK
    assert walk_meta(lesson_notebook('Softmax', step={**STEP, 'section': ''})).keys() == {'walk', 'step', 'from', 'app'}
    assert walk_meta(lesson_notebook('Softmax')) == {}

def test_a_walk_lesson_keeps_the_cell_layout_and_quotes_the_passage():
    nb, plain = lesson_notebook('Softmax', step=STEP), lesson_notebook('Softmax')
    assert [c.cell_type for c in nb.cells] == [c.cell_type for c in plain.cells] and [c.source for c in nb.cells][1:] == [c.source for c in plain.cells][1:]
    assert nb[0].source.startswith(plain[0].source) and '> Softmax maps scores to weights.\n> The sum is 1.' in nb[0].source and 'Watch the sum.' in nb[0].source
    assert nb.meta['lesson'] == {'v': 1, 'name': 'Softmax', 'walk': dict(walk='attention-ab12', step=0, section='2 Background')}
    assert plain.meta['lesson'] == {'v': 1, 'name': 'Softmax'}

def test_a_card_from_a_walk_lesson_carries_the_walk_meta(tmp_path):
    mem, nb = Memory(path=tmp_path/'vault.db', offline=True), lesson_notebook('Softmax', step=STEP)
    code = nb[3]; code.source, code.execution_count = 'print(1)', 1
    code.outputs = [{'output_type': 'stream', 'name': 'stdout', 'text': '1\n'}]
    lock(code, '1')
    record_card(mem, nb, code, str(tmp_path/'softmax.ipynb'))
    a = first(Learning(mem._store('learning')).attempts('softmax', limit=5))
    assert (a.kind, a.walk, a.step, a['from'], a.app, a.section) == ('predict', 'attention-ab12', 0, 'attention-ab12/0', 'leela', '2 Background')

def test_a_card_from_a_plain_lesson_has_no_walk_meta(tmp_path):
    mem, nb = Memory(path=tmp_path/'vault.db', offline=True), lesson_notebook('Softmax')
    code = nb[3]; code.source, code.execution_count = 'print(1)', 1
    code.outputs = [{'output_type': 'stream', 'name': 'stdout', 'text': '1\n'}]
    lock(code, '1')
    record_card(mem, nb, code, str(tmp_path/'softmax.ipynb'))
    a = first(Learning(mem._store('learning')).attempts('softmax', limit=5))
    assert not {'walk', 'step', 'from', 'app', 'section'} & set(a)

def test_the_filings_copy_the_walk_meta_when_made():
    from test_lesson_predict import DEMO
    from leela.blocks.nb.lesson import fence
    spec = dict(task='Double it.', fname='double', stub='def double(x): pass', tests=[dict(say='doubles 2', test='assert double(2) == 4', shown=True)])
    nb = lesson_notebook('Softmax', spec, step=STEP)
    code = next(c for c in nb.cells if 'tests' in c.extra.get('exercise', {}))
    code.extra['exercise']['state'] = dict(grade=dict(score=8, note='Clear.', hash=''))
    f = exercise_filing(nb, code, 'x.ipynb')
    nb.meta['lesson']['walk'] = dict(walk='other-0000', step=3, section='')
    assert f['walk'] == WALK
    nb[1].source = fence(DEMO)
    assert prediction_filing(nb, nb[1], 'x.ipynb', 'halves', 'g1', 4)['walk'] == {'walk': 'other-0000', 'step': 3, 'from': 'other-0000/3', 'app': 'leela'}
    plain = lesson_notebook('Plain'); plain[1].source = fence(DEMO)
    assert prediction_filing(plain, plain[1], 'x.ipynb', 'halves', 'g1', 4)['walk'] == {}
