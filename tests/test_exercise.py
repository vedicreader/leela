from copy import deepcopy
import pytest
from leela.blocks.nb.check import validate_exercise
from leela.blocks.nb.exercise import exercise_cells, validate_exercise_spec
from leela.blocks.nb.lesson import lesson_notebook
from leela.blocks.nb.nb import Cell

@pytest.fixture
def spec():
    return dict(task='Double a number.', fname='double', stub='def double(x):\n    pass', uses=['math'], tests=[
        dict(say='A positive number', test='assert double(2) == 4', shown=True),
        dict(say='A negative number', test='assert double(-123) == -246', shown=False)])

def test_good_spec_is_clean_and_independent(spec):
    given = deepcopy(spec)
    given['solution'] = 'not retained'
    clean = validate_exercise_spec(given)
    assert clean == spec and 'solution' not in clean
    clean['tests'][0]['say'] = 'Changed'
    clean['uses'].append('numpy')
    assert given['tests'][0]['say'] == 'A positive number' and given['uses'] == ['math']

@pytest.mark.parametrize('test', ['import os', 'assert double.__globals__'])
def test_unsafe_test_keeps_abhyasa_reason(spec, test):
    spec['tests'][0]['test'] = test
    with pytest.raises(ValueError) as upstream:
        validate_exercise({**spec, 'tests': [t['test'] for t in spec['tests']]})
    with pytest.raises(ValueError) as local: validate_exercise_spec(spec)
    assert str(local.value) == str(upstream.value)

@pytest.mark.parametrize('say', [None, 1, [], '', 'x'*201, 'two\nlines', 'tab\tlabel', '\x00'])
def test_bad_label(spec, say):
    spec['tests'][0]['say'] = say
    with pytest.raises(ValueError, match='say'): validate_exercise_spec(spec)

@pytest.mark.parametrize('shown', [None, 0, 1, 'yes'])
def test_shown_must_be_bool(spec, shown):
    spec['tests'][0]['shown'] = shown
    with pytest.raises(ValueError, match='shown'): validate_exercise_spec(spec)

@pytest.mark.parametrize('uses', [['math', 1], 'math', None])
def test_uses_must_be_strings(spec, uses):
    spec['uses'] = uses
    with pytest.raises(ValueError, match='uses'): validate_exercise_spec(spec)

@pytest.mark.parametrize('bad', [None, [], {}, {'tests': [None]}])
def test_malformed_spec_has_plain_reason(bad):
    with pytest.raises(ValueError): validate_exercise_spec(bad)

def test_exercise_cells(spec):
    task, code = exercise_cells(spec)
    assert isinstance(task, Cell) and isinstance(code, Cell)
    assert task.cell_type == 'markdown' and code.cell_type == 'code'
    assert task.extra['exercise'] == {'role': 'task', 'for': code.id}
    assert code.source == spec['stub']
    assert code.extra['exercise'] == dict(v=1, fname='double', uses=['math'], tests=spec['tests'],
        state=dict(checks=0, rung=0, last=None, passed=False))
    assert spec['task'] in task.source and spec['tests'][0]['test'] in task.source
    assert 'A negative number' in task.source and spec['tests'][1]['test'] not in task.source
    assert '-123' not in task.source and '-246' not in task.source
    assert Cell.from_nb(code.nbcell()).extra == code.extra
    code.extra['exercise']['state']['checks'] = 1
    assert exercise_cells(spec)[1].extra['exercise']['state']['checks'] == 0
    assert len({task.id, code.id, *(c.id for c in exercise_cells(spec))}) == 4

def test_lesson_without_exercise_is_unchanged():
    nb = lesson_notebook('Numbers')
    assert len(nb.cells) == 5
    assert [c.cell_type for c in nb.cells] == ['markdown', 'markdown', 'markdown', 'code', 'markdown']
    assert nb.cells[0].source == '# Numbers\n\nA lesson notebook. Predict the output before running the code. Then write your reasoning in the card.'
    assert nb.cells[1].source == 'No demo yet. Ask the tutor to add one.'
    assert nb.cells[2].extra == {'lesson': {'role': 'prediction', 'for': nb.cells[3].id}}
    assert nb.cells[3].source == 'pass'
    assert nb.cells[4].extra == {'lesson': {'role': 'card', 'for': nb.cells[3].id}}
    assert nb.meta == {'lesson': {'v': 1, 'name': 'Numbers'}}

def test_lesson_adds_exercise_after_code(spec):
    nb, old = lesson_notebook('Numbers', exercise=spec), lesson_notebook('Numbers')
    assert len(nb.cells) == 7
    assert [c.source for c in nb.cells[:4] + nb.cells[6:]] == [c.source for c in old.cells]
    task, code = nb.cells[4:6]
    assert task.extra['exercise']['for'] == code.id and code.source == spec['stub']
    assert nb.cells[6].extra['lesson']['for'] == nb.cells[3].id

@pytest.mark.parametrize('source, found, statuses, got', [
    ('def double(x): return x*2', True, ['pass', 'pass'], None),
    ('def double(x): return 4', True, ['pass', 'fail'], '4'),
    ('x = 1', False, [], None)])
def test_check_solution_without_kernel(spec, source, found, statuses, got):
    from leela.blocks.nb.exercise import check_solution
    result = check_solution(spec, source)
    assert result['solution']['found'] is found
    assert [r['status'] for r in result['solution']['checks']] == statuses
    if got is not None: assert result['solution']['checks'][-1]['got'] == got
    assert [r['status'] for r in result['stub']['checks']] == ['fail', 'fail']

@pytest.mark.parametrize('source', ['while True: pass', 'def double(x):\n    while True: pass'])
def test_check_solution_timeout(spec, source, abhyasa_cfg):
    import time
    from leela.blocks.nb.exercise import check_solution
    started = time.monotonic()
    result = check_solution(spec, source, timeout=.1)['solution']
    assert time.monotonic() - started < 2 * (.1 + 2) + 1   # abhyasa stops each of the two runs at `total + 2` s; 1 s for a loaded machine
    assert result.get('timeout') or all(r['status'] == 'timeout' for r in result['checks'])

@pytest.mark.parametrize('source', ['raise ValueError("SECRET_SOURCE_TOKEN")', 'def double(:'])
def test_check_solution_source_errors_do_not_echo_source(spec, source):
    import json
    from leela.blocks.nb.exercise import check_solution
    result = check_solution(spec, source)
    assert result['solution'].get('error')
    assert 'SECRET_SOURCE_TOKEN' not in json.dumps(result)


def test_check_solution_delegates_to_the_closed_runner_isolated_and_silent(spec, monkeypatch, abhyasa_cfg):
    import json
    from leela.blocks.nb import check as nbcheck
    from leela.blocks.nb.exercise import check_solution
    source = 'print("SECRET_SOURCE_TOKEN")\nimport os, sys\nassert sys.flags.isolated and os.getcwd() == os.environ["HOME"]\ndef double(x): return x*2'
    calls, real = [], nbcheck.run_isolated
    monkeypatch.setattr(nbcheck, 'run_isolated', lambda *a, **kw: calls.append((a, kw)) or real(*a, **kw))
    result = check_solution(spec, source, timeout=5)
    tests = [t['test'] for t in spec['tests']]
    assert calls == [(('assert', 'double', source, tests), dict(total=5, sandbox=True)),
                     (('assert', 'double', spec['stub'], tests), dict(total=5, sandbox=True))]
    assert [r['status'] for r in result['solution']['checks']] == ['pass', 'pass']
    assert 'SECRET_SOURCE_TOKEN' not in json.dumps(result)
