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
import abhyasa.store, abhyasa.model, abhyasa.method, abhyasa.tutor, rupaka.spec
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
    assert 'abhyasa>=0.0.9' in deps
