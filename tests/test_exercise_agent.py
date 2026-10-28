import json, time
from pathlib import Path
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
    assert result == f'Added the exercise (cells {task.id}, {code.id}). Checked: the solution passes 2 of 2; the stub fails 2 of 2 tests.'
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

def test_a_stub_that_fails_some_tests_says_how_many_of_all(exercise, spec):
    add, path, _ = exercise
    assert add(str(path), **{**spec, 'stub': 'def double(x): return 4'}, solution=SOLUTION).endswith('the solution passes 2 of 2; the stub fails 1 of 2 tests.')

def test_a_stub_status_with_no_words_says_it_does_not_pass(exercise, spec, monkeypatch):
    import leela.blocks.nb.exercise as E
    rows = lambda *s: dict(found=True, timeout=False, checks=[dict(i=i, status=x) for i, x in enumerate(s)])
    monkeypatch.setattr(E, 'check_solution', lambda spec, solution: dict(solution=rows('pass', 'pass'), stub=rows('pass', 'skipped')))
    add, path, _ = exercise
    assert add(str(path), **spec, solution=SOLUTION).endswith('the solution passes 2 of 2; the stub does not pass every test.')

@pytest.mark.parametrize('stub, says', [('def double(x):\n    raise NotImplementedError', 'the stub errors on 2 of 2 tests'),
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

@pytest.fixture
def marked(tmp_path):
    "A workspace whose agent has recorded its tools, so ramabana's `SECRET_ARGS` holds each tool's `secret_args`."
    from leela.workspace import Workspace
    ws = Workspace(roots=[tmp_path], approvals='ask')
    try: yield ws.ai, ws.ai.tools
    finally: ws.shutdown_now()

def approve(edit, ask=ASK, tool='add_exercise', tools=WRITE_TOOLS):
    "Raise `tool` with `ask` through Leela's notebook approvals and answer it with `edit` as the ask is raised."
    nb, shown = Notebook([Cell(source='set an exercise', cell_type='prompt')]), {}
    ap = notebook_approvals(lambda: (nb, 0), tools=tools, timeout=5)
    stop = ap.listen(on_ask=lambda a: shown.update(a.dict()) or ap.answer(a.id, True, args=edit(a.dict()['args'])))
    tc = {'function': {'name': tool, 'arguments': dict(ask)}}
    try: decision = ap.gate(tc)
    finally: stop()
    return tc['function']['arguments'], nb, shown, decision

def test_approval_card_hides_the_reference_solution(marked):
    args, nb, shown, decision = approve(EDITS['edited'])
    card = '\n'.join([json.dumps(shown), json.dumps(decision.dict()), *(c.source for c in nb.cells)])
    assert 'SECRET_REFERENCE_SOLUTION_7f9c' not in card and '[SECRET]' in card
    assert 'Double it.' in nb.cells[-1].source, 'the edit is still shown'

def test_a_new_tool_marked_secret_is_hidden_on_leelas_card(marked):
    "A tool's `secret_args`, recorded by ramabana, hide on Leela's card with no Leela list naming the tool."
    def peek(x: str, y: str = '') -> str:
        "Return `x`."
        return x
    peek.secret_args = ('x',)
    marked[0]._record(peek)
    args, nb, shown, decision = approve(lambda a: {**a, 'y': 'shown'}, dict(x='PEEK_SECRET_51b2', y='plain'), 'peek', {'peek'})
    card = '\n'.join([json.dumps(shown), json.dumps(decision.dict()), *(c.source for c in nb.cells)])
    assert 'PEEK_SECRET_51b2' not in card and '[SECRET]' in card and 'shown' in card
    assert args == dict(x='PEEK_SECRET_51b2', y='shown'), 'the tool still runs with the real value'

@pytest.mark.parametrize('edit', EDITS)
def test_the_tool_still_receives_the_reference_solution(marked, edit):
    args, *_ = approve(EDITS[edit])
    assert args['solution'] == SOLUTION
    assert args['task'] == ('Double it.' if edit == 'edited' else ASK['task'])

@pytest.fixture
def recorded(tmp_path, monkeypatch, abhyasa_cfg):
    "One approved and edited `add_exercise` call through the agent's gate and its recorded tool: the workspace, the args that ran, the solutions the check got and the tool's rows."
    import leela.blocks.nb.exercise as E
    from leela.workspace import Workspace
    path = tmp_path/'ordinary.ipynb'; Notebook([Cell(source='before')]).save(path)
    seen, real = [], E.check_solution
    monkeypatch.setattr(E, 'check_solution', lambda spec, solution, **kw: seen.append(solution) or real(spec, solution, **kw))
    ws = Workspace(roots=[tmp_path], approvals='ask')
    try:
        add, ap = next(t for t in ws.ai.tools if t.__name__ == 'add_exercise'), ws.ai.approvals
        stop = ap.listen(on_ask=lambda a: ap.answer(a.id, True, args={**a.dict()['args'], 'task': 'Double it.'}))
        ws.ai._prepare('set an exercise')
        tc = {'id': 'call-1', 'function': {'name': 'add_exercise', 'arguments': {**ASK, 'path': str(path)}}}
        try: assert ap.gate(tc)
        finally: stop()
        args = tc['function']['arguments']; out = add(**args)
        ws.ai._finish('done')
        yield ws, args, out, seen, [x.dict() for x in ws.ai.activity.acts if x.tool == 'add_exercise']
    finally: ws.shutdown_now()

def test_a_recorded_add_exercise_runs_with_the_solution_and_keeps_it_out_of_its_row_and_calls(recorded):
    "ramabana 0.2.87 writes `[SECRET]` for a tool's `secret_args`; the tool and Leela's approval edit still use the real solution."
    ws, args, out, seen, rows = recorded
    assert args['solution'] == SOLUTION and args['task'] == 'Double it.', 'the edit runs with the real solution'
    assert out.startswith('Added the exercise') and seen == [SOLUTION], 'the tool gets the real solution'
    run = [r for r in rows if r['kind'] == 'tool']
    assert len(run) == 1 and run[0]['action_id'] == 'call-1', 'the row of the run keeps the approved call'
    assert 'SECRET_REFERENCE_SOLUTION_7f9c' not in json.dumps(run) and 'SECRET_REFERENCE_SOLUTION_7f9c' not in json.dumps(ws.ai.calls, default=str)
    assert ('add_exercise', {**args, 'solution': '[SECRET]'}) in ws.ai.calls

def test_the_approval_row_and_the_saved_history_keep_no_solution(recorded):
    ws, *_, rows = recorded
    kept = dict(rows=json.dumps(rows), history=json.dumps(ws.ai.history, default=str), saved=Path(ws.ai.history_path).read_text())
    assert not (leaks := [k for k, t in kept.items() if 'SECRET_REFERENCE_SOLUTION_7f9c' in t]), leaks

def test_an_exercise_with_packages_still_hides_the_reference_solution(marked):
    args, nb, shown, decision = approve(EDITS['unchanged'], {**ASK, 'packages': ['six']})
    card = '\n'.join([json.dumps(shown), json.dumps(decision.dict()), *(c.source for c in nb.cells)])
    assert 'SECRET_REFERENCE_SOLUTION_7f9c' not in card and '[SECRET]' in card and 'six' in card
    assert args['solution'] == SOLUTION and args['packages'] == ['six']
