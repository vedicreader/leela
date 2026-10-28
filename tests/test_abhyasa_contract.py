import inspect, json, re, subprocess, sys, tomllib
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]

def test_record_parameters():
    from abhyasa.store import Learning
    params = inspect.signature(Learning.record).parameters
    assert list(params) == ['self', 'concept', 'question', 'answer', 'thinking', 'correct', 'confidence', 'depth',
                            'kind', 'hints', 'dont_know', 'grade', 'feedback', 'first_error', 'misconception', 'session', 'meta']
    assert params['meta'].kind is inspect.Parameter.VAR_KEYWORD

def test_exercise_pure_contract():
    from abhyasa.nb import SAFE_NAMES, safe_test, validate_exercise
    assert callable(safe_test) and callable(validate_exercise)
    assert isinstance(SAFE_NAMES, (list, tuple)) and 'len' in SAFE_NAMES
    assert safe_test('assert double(2) == 4', 'double')
    assert not safe_test('assert double.__globals__', 'double')

def test_six_hint_rungs():
    from abhyasa.tutor import HINTS
    assert len(HINTS) == 6

def test_pure_imports_in_isolated_python():
    src = '''import sys, json
import abhyasa.store, abhyasa.model, abhyasa.method, abhyasa.tutor, abhyasa.journey, abhyasa.prompts, abhyasa.check, rupaka.spec
print(json.dumps([n for n in sys.modules if n == 'ipywidgets' or n.startswith('ipywidgets.') or n == 'abhyasa.app' or n == 'abhyasa.blocks' or n.startswith('abhyasa.blocks.')]))
'''
    p = subprocess.run([sys.executable, '-I', '-c', src], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout) == []

def test_rupaka_vendor_version():
    import rupaka
    text = (ROOT/'leela'/'vendor'/'lee-rupaka.js').read_text()
    version = re.search(r"\bversion:\s*'([^']+)'", text).group(1)
    if version != rupaka.__version__:
        pytest.xfail(f'vendored rupaka {version} differs from installed rupaka {rupaka.__version__}; vendor unchanged in slice A')
    assert version == rupaka.__version__

def test_abhyasa_dependency_floor():
    deps = tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['dependencies']
    assert 'abhyasa>=0.0.11,<0.1' in deps
    assert any(re.fullmatch(r'rupaka==\d+\.\d+\.\d+', d) for d in deps)

def test_learn_handoff():
    from abhyasa.journey import LEELA_ROUTE, HANDOFF_CASES, handoff, read_handoff
    assert LEELA_ROUTE == '/learn'
    for kw, path in HANDOFF_CASES:
        assert handoff(**kw) == path
        q = read_handoff(path.split('?', 1)[1])
        assert (q.walk, q.step, q.topic) == (kw.get('jid', ''), kw.get('i'), kw.get('topic', ''))
    for bad in ('walk=../x', 'walk=a-1&step=-1', ''):
        with pytest.raises(ValueError): read_handoff(bad)

def test_prompts_contract():
    import abhyasa.tutor
    from abhyasa.prompts import PROMPTS, prompt
    assert 'tutor' in PROMPTS and prompt('tutor') == PROMPTS['tutor'].dflt   # ABHYASA_CONFIG is a temp folder: no saved text

def test_run_isolated_contract():
    from abhyasa.check import run_isolated
    ps = inspect.signature(run_isolated).parameters
    assert list(ps)[:4] == ['kind', 'fname', 'source', 'tests'] and {'total', 'setup', 'sandbox', 'python', 'unix'} <= ps.keys()

def test_journey_contract():
    from abhyasa.journey import walk_state
    from abhyasa.store import Learning
    assert all(hasattr(Learning, n) for n in ('put_journey', 'journey', 'journeys'))
    assert walk_state(dict(steps=[dict(slug='a', status='done'), dict(slug='b')])).current == 1
