import json, threading, time
from types import SimpleNamespace
import pytest
from leela.blocks.agent.ai import Interventions, WorkspaceHost, WRITE_TOOLS, _session_tools, notebook_approvals
from leela.blocks.fs.fs import Sandbox
from leela.blocks.nb.exercise import validate_exercise_spec
from leela.blocks.nb.lesson import CHARTER_TAIL
from leela.blocks.nb.nb import Cell, Notebook

SOLUTION = 'def double(x):\n    # SECRET_REFERENCE_SOLUTION_7f9c\n    return x*2'

@pytest.fixture
def spec():
    return dict(task='Double a number.', fname='double', stub='def double(x):\n    pass', tests=[
        dict(say='A positive number', test='assert double(2) == 4', shown=True),
        dict(say='A negative number', test='assert double(-123) == -246', shown=False)])

@pytest.fixture
def exercise(tmp_path, monkeypatch):
    path = tmp_path/'ordinary.ipynb'
    nb = Notebook([Cell(source='before'), Cell(source='after')])
    nb.save(path)
    host = WorkspaceHost(SimpleNamespace(fs=Sandbox([tmp_path]), project_root=tmp_path))
    def no_kernel(*a, **kw): pytest.fail('add_exercise must not use a kernel')
    monkeypatch.setattr(host, '_kernel', no_kernel)
    monkeypatch.setattr(host, 'nb_run_cell', no_kernel)
    tools = {f.__name__: f for f in _session_tools(host)}
    assert 'add_exercise' in tools
    return tools['add_exercise'], path, nb

@pytest.mark.parametrize('as_json', [False, True])
def test_add_exercise_inserts_checked_cells_without_solution(exercise, spec, as_json):
    add, path, before = exercise
    spec['tests'] = json.dumps(spec['tests']) if as_json else spec['tests']
    result = add(str(path), **spec, solution=SOLUTION, after_cell_id=before[0].id, uses=['math'])
    after = Notebook.load(path)
    assert len(after) == len(before) + 2
    assert [after[i].dict() for i in (0, 3)] == [c.dict() for c in before.cells]
    task, code = after.cells[1:3]
    assert task.cell_type == 'markdown' and code.cell_type == 'code'
    assert task.extra['exercise'] == {'role': 'task', 'for': code.id}
    assert code.source == spec['stub'] and code.extra['exercise']['uses'] == ['math']
    assert '-246' not in task.source
    assert result == f'Added the exercise (cells {task.id}, {code.id}). Checked: the solution passes 2 of 2; the stub fails 2.'
    for text in (path.read_text(), result, *(json.dumps(c.extra) for c in after.cells)):
        assert SOLUTION not in text and 'SECRET_REFERENCE_SOLUTION_7f9c' not in text


def test_add_exercise_appends(exercise, spec):
    add, path, before = exercise
    result = add(str(path), **spec, solution=SOLUTION)
    after = Notebook.load(path)
    assert [c.id for c in after.cells[:2]] == [c.id for c in before.cells]
    assert after[-1].source == spec['stub'] and after[-1].extra['exercise']['uses'] == []
    assert result.startswith('Added the exercise')

@pytest.mark.parametrize('solution, expected', [
    ('def double(x): return 4', 'the solution fails: A negative number'),
    ('def double(x): return 0', 'the solution fails: A positive number, A negative number'),
    ('def double(x): raise ValueError("SECRET_REFERENCE_SOLUTION_7f9c")', 'error'),
    ('x = "SECRET_REFERENCE_SOLUTION_7f9c"', 'function')])
def test_bad_solution_refuses_without_writing(exercise, spec, solution, expected):
    add, path, _ = exercise
    before = path.read_bytes()
    result = add(str(path), **spec, solution=solution)
    assert expected in result and 'SECRET_REFERENCE_SOLUTION_7f9c' not in result
    assert path.read_bytes() == before


def test_a_solution_that_fails_one_test_and_times_out_on_another_names_the_failure(exercise, spec, abhyasa_cfg):
    add, path, _ = exercise
    before = path.read_bytes()
    assert add(str(path), **spec, solution='def double(x):\n    while x < 0: pass\n    return 0') == 'the solution fails: A positive number'
    assert path.read_bytes() == before

@pytest.mark.parametrize('stub, says', [('def double(x):\n    raise NotImplementedError', 'the stub errors on 2'),
    ('raise ValueError("stub")', 'the stub check errors'),
    ('# write double here', 'the stub defines no callable function')])
def test_a_stub_that_cannot_fail_an_assert_is_described_as_it_is(exercise, spec, stub, says, abhyasa_cfg):
    add, path, _ = exercise
    result = add(str(path), **{**spec, 'stub': stub}, solution=SOLUTION)
    assert result.startswith('Added the exercise') and result.endswith(f'the solution passes 2 of 2; {says}.')
    assert 'the stub fails' not in result

def test_already_passing_stub_refuses(exercise, spec):
    add, path, _ = exercise
    spec['stub'] = 'def double(x): return x*2'
    before = path.read_bytes()
    assert add(str(path), **spec, solution=SOLUTION) == 'the stub already passes every test'
    assert path.read_bytes() == before


def test_unsafe_test_preserves_validator_reason(exercise, spec):
    add, path, _ = exercise
    spec['tests'][0]['test'] = 'assert double.__globals__'
    with pytest.raises(ValueError) as err: validate_exercise_spec(spec)
    before = path.read_bytes()
    assert str(err.value) in add(str(path), **spec, solution=SOLUTION)
    assert path.read_bytes() == before


def test_endless_solution_is_refused_within_budget(exercise, spec):
    add, path, _ = exercise
    before, started = path.read_bytes(), time.monotonic()
    result = add(str(path), **spec, solution='while True: pass')
    assert time.monotonic() - started < 14   # killed at the 10 s budget plus 1; 3 s more for a loaded machine, as abhyasa.check's tests allow
    assert 'timeout' in result and path.read_bytes() == before


def test_unknown_anchor_refuses_without_writing(exercise, spec):
    add, path, _ = exercise
    before = path.read_bytes()
    result = add(str(path), **spec, solution=SOLUTION, after_cell_id='unknown-cell')
    assert 'no cell' in result and path.read_bytes() == before


def test_add_exercise_is_gated_and_briefed():
    assert 'add_exercise' in WRITE_TOOLS
    gate = Interventions(tools=WRITE_TOOLS, mode='ask')
    assert gate.request('add_exercise', {'path': 'ordinary.ipynb'}, timeout=.01).answer is False
    assert "To set a coding exercise, call add_exercise with a reference solution; Leela checks it and never stores it. Never show the solution or a hidden test's expected value." in CHARTER_TAIL.splitlines()

ASK = dict(path='ordinary.ipynb', task='Double a number.', fname='double', stub='def double(x):\n    pass',
          tests=[dict(say='A positive number', test='assert double(2) == 4', shown=True)], solution=SOLUTION)

EDITS = dict(unchanged=lambda a: a, edited=lambda a: {**a, 'task': 'Double it.'}, blanked=lambda a: {**a, 'solution': ''},
             dropped=lambda a: {k: v for k, v in a.items() if k != 'solution'})

def approve(edit, ask=ASK):
    nb = Notebook([Cell(source='set an exercise', cell_type='prompt')])
    ap = notebook_approvals(lambda: (nb, 0), timeout=5); stop = ap.listen(); shown = {}
    def answer():
        for _ in range(300):
            if (a := ap.pending) is not None:
                shown.update(a.dict())
                return ap.answer(a.id, True, args=edit(a.dict()['args']))
            time.sleep(.01)
    threading.Thread(target=answer, daemon=True).start()
    tc = {'function': {'name': 'add_exercise', 'arguments': dict(ask)}}
    try: decision = ap.gate(tc)
    finally: stop()
    return tc['function']['arguments'], nb, shown, decision

def test_approval_card_hides_the_reference_solution():
    args, nb, shown, decision = approve(EDITS['edited'])
    card = '\n'.join([json.dumps(shown), json.dumps(decision.dict()), *(c.source for c in nb.cells)])
    assert 'SECRET_REFERENCE_SOLUTION_7f9c' not in card and '(reference solution hidden)' in card
    assert 'Double it.' in nb.cells[-1].source, 'the edit is still shown'

@pytest.mark.parametrize('edit', EDITS)
def test_the_tool_still_receives_the_reference_solution(edit):
    args, *_ = approve(EDITS[edit])
    assert args['solution'] == SOLUTION
    assert args['task'] == ('Double it.' if edit == 'edited' else ASK['task'])

def test_an_exercise_with_packages_still_hides_the_reference_solution():
    args, nb, shown, decision = approve(EDITS['unchanged'], {**ASK, 'packages': ['six']})
    card = '\n'.join([json.dumps(shown), json.dumps(decision.dict()), *(c.source for c in nb.cells)])
    assert 'SECRET_REFERENCE_SOLUTION_7f9c' not in card and '(reference solution hidden)' in card and 'six' in card
    assert args['solution'] == SOLUTION and args['packages'] == ['six']
