import json, sys
import pytest
from starlette.testclient import TestClient
from abhyasa.store import Learning
from leela.app import ide_app
from leela.blocks.agent.ai import WRITE_TOOLS, _session_tools
from leela.blocks.memory.memory import Memory
from leela.blocks.nb.lesson import LESSON_CHARTER, lesson_notebook
from leela.blocks.nb.nb import src_hash
from leela.workspace import Workspace

SPEC = dict(task='Double a number.', fname='double', stub='def double(x):\n    pass', tests=[
    dict(say='A positive number', test='assert double(2) == 4', shown=True),
    dict(say='A negative number', test='assert double(-123) == -246', shown=False)])
GOOD = 'def double(x):\n    return x * 2'
GOOD2 = 'def double(x):\n    return 2 * x'
WRONG = 'def double(x):\n    return 999777'
SCALED = 'def double(x):\n    return x * 1000 + 7'

@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path/'xdg-data'))
    mem = Memory(path=tmp_path/'vault.db', offline=True)
    p = tmp_path/'lesson.ipynb'
    nb = lesson_notebook('Doubling', SPEC)
    nb.save(p)
    code = next(c for c in nb.cells if 'tests' in c.extra.get('exercise', {}))
    ws = Workspace(roots=[tmp_path], approvals='auto', python=sys.executable)
    monkeypatch.setattr(ws, 'memory', mem)
    monkeypatch.setattr(ws, 'vaults', None)
    ws.open(p)
    try:
        with TestClient(ide_app(ws)) as client:
            client.get('/tab/state')
            tab, live, lock = ws.docstore.owner(str(p))
            cell = next(c for c in live.cells if c.id == code.id)
            i = list(live.cells).index(cell)
            tools = {f.__name__: f for f in _session_tools(ws.inline_ai.host)}
            def check(source=None):
                if source is not None: cell.source = source
                return json.loads(tools['check_exercise'](str(p), cell.id))
            yield dict(client=client, p=p, live=live, cell=cell, i=i, tools=tools, check=check, mem=mem,
                       grade=lambda score, note='Clear and short.': tools['grade_exercise'](str(p), cell.id, score, note),
                       state=lambda: cell.extra['exercise']['state'],
                       attempts=lambda: Learning(mem._store('learning')).attempts('doubling', limit=100))
    finally: ws.shutdown_now()

def test_check_stores_public_state_and_the_page_never_sees_a_hidden_test(rig):
    r = rig
    got = r['client'].post('/exercise/check', json=dict(path=str(r['p']), i=r['i'], id=r['cell'].id, source=GOOD)).json()
    assert got['passed'] == 2
    s = r['state']()
    assert s['checks'] == 1 and s['passed'] is True
    assert s['last'] == dict(hash=src_hash(GOOD), state='done', passed=2, total=2)
    r['client'].post('/exercise/check', json=dict(path=str(r['p']), i=r['i'], id=r['cell'].id, source=SCALED, seq=100))
    s = r['state']()
    assert s['checks'] == 2 and s['passed'] is False and s['last']['passed'] == 0 and s['last']['hash'] == src_hash(SCALED)
    assert r['tools']['grade_exercise'](str(r['p']), r['cell'].id, 5, 'Hard coded.').startswith('Graded 5 of 10')
    page = json.dumps(r['cell'].dict())
    for hidden in ('assert double(-123)', '-246', '-122993'): assert hidden not in page
    assert 'A negative number' in page

def test_grade_is_stored_with_its_source_hash_shown_on_the_page_and_validated(rig):
    r = rig
    assert 'grade_exercise' not in WRITE_TOOLS   # a grade is a note under the learner's own checks, so it does not ask
    assert 'check_exercise first' in r['grade'](8)
    assert 'grade' not in r['state']()
    r['check'](GOOD)
    for bad in (-1, 11, True, '7', 7.5, None): assert 'whole number from 0 to 10' in r['grade'](bad), bad
    for bad in ('', '   ', 'two\nlines', 'x' * 201, 7, 'It wrote assert double(-123) == -246 itself.', 'It wrote assert  double( -123 )==-246.'):
        assert r['grade'](8, bad).startswith('`note` must'), bad
    assert 'grade' not in r['state']()
    assert r['grade'](8).startswith('Graded 8 of 10')
    want = dict(score=8, note='Clear and short.', hash=src_hash(GOOD))
    assert r['state']()['grade'] == want
    assert r['cell'].dict()['extra']['exercise']['state']['grade'] == want
    r['cell'].source = GOOD2
    assert 'check_exercise first' in r['grade'](9)
    assert r['state']()['grade'] == want

def test_a_full_pass_with_a_grade_files_one_code_attempt_per_source_version(rig):
    r = rig
    r['check'](WRONG)
    assert 'Not filed' in r['grade'](3, 'Returns a constant.')
    assert len(r['attempts']()) == 0
    r['check'](GOOD)
    msg = r['grade'](8)
    assert 'learning shelf' in msg and 'review' in msg
    [a] = r['attempts']()
    assert (a.kind, a.depth, a.correct, a.grade, a.feedback, a.answer) == ('code', 4, True, 8, 'Clear and short.', GOOD)
    assert a.card_key == f'{r["cell"].id}:{src_hash(GOOD)}' and 'Double a number.' in a.question
    for hidden in ('-246', 'assert double(-123)'): assert hidden not in json.dumps(dict(a))
    lr = Learning(r['mem']._store('learning'))
    c = lr.concept('doubling')
    assert c.seen == 1 and c.floor == 4 and c.due > c.last
    r['grade'](8)
    assert len(r['attempts']()) == 1 and lr.concept('doubling').seen == 1
    assert 'Graded 9 of 10' in r['grade'](9, 'Better after thought.')
    [a] = r['attempts']()
    assert a.grade == 9 and a.feedback == 'Better after thought.' and lr.concept('doubling').seen == 1
    r['check'](GOOD2)
    r['grade'](7, 'Same idea, other order.')
    assert sorted(a.card_key.split(':')[1] for a in r['attempts']()) == sorted([src_hash(GOOD), src_hash(GOOD2)])
    assert lr.concept('doubling').seen == 2

def test_grade_refuses_a_plain_cell_and_a_notebook_that_is_not_open(rig, tmp_path):
    r = rig
    assert 'not an exercise' in r['tools']['grade_exercise'](str(r['p']), r['live'][0].id, 8, 'Fine.')
    assert 'no cell' in r['tools']['grade_exercise'](str(r['p']), 'nosuchid', 8, 'Fine.')
    other = tmp_path/'other.ipynb'
    lesson_notebook('Other', SPEC).save(other)
    assert 'not open in a tab' in r['tools']['grade_exercise'](str(other), r['cell'].id, 8, 'Fine.')

def test_a_copied_exercise_cell_starts_with_no_check_and_no_grade(rig):
    r = rig
    r['check'](GOOD)
    r['grade'](8)
    copy = r['live'].duplicate(r['i'])
    assert copy.id != r['cell'].id
    s = copy.extra['exercise']['state']
    assert s['checks'] == 0 and s['last'] is None and s['passed'] is False and 'grade' not in s
    assert r['state']()['grade']['score'] == 8

def test_the_charter_carries_the_grading_rules():
    lines = LESSON_CHARTER.splitlines()
    assert 'call add_exercise with a reference solution' in LESSON_CHARTER
    assert ("To grade, call check_exercise, then grade_exercise. Give one hint rung at a time; name a package only after confirming it is installed; name the module at rung 3 and the function at rung 4; never write the call.") in lines
    assert "After each learner message add at most one line 'Prompt note: ...' when it would help." in lines
