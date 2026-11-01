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
    from abhyasa.contract import SAFE_NAMES, check_exercise, safe_test
    assert callable(safe_test) and callable(check_exercise)
    assert isinstance(SAFE_NAMES, (list, tuple)) and 'len' in SAFE_NAMES
    assert safe_test('assert double(2) == 4', 'double')
    assert not safe_test('assert double.__globals__', 'double')

def test_six_hint_rungs():
    from abhyasa.tutor import HINTS
    assert len(HINTS) == 6

def test_pure_imports_in_isolated_python():
    src = '''import sys, json
import abhyasa.store, abhyasa.model, abhyasa.method, abhyasa.tutor, abhyasa.journey, abhyasa.prompts, abhyasa.talk, abhyasa.contract, abhyasa.stagekit, abhyasa.sources, abhyasa.demo, rupaka.spec
print(json.dumps([n for n in sys.modules if n == 'ipywidgets' or n.startswith('ipywidgets.') or n == 'abhyasa.app' or n == 'abhyasa.blocks' or n.startswith('abhyasa.blocks.')]))
'''
    p = subprocess.run([sys.executable, '-I', '-c', src], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout) == []

def test_rupaka_vendor_version():
    import rupaka
    text = (ROOT/'leela'/'vendor'/'lee-rupaka.js').read_text()
    version = re.search(r"\bversion:\s*'([^']+)'", text).group(1)
    assert version == rupaka.__version__, f'vendored rupaka {version}, installed {rupaka.__version__}: write the bundle again (leela/vendor/README)'
    deps = tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['dependencies']
    assert f'rupaka=={version}' in deps

def test_abhyasa_dependency_floor():
    t = tomllib.loads((ROOT/'pyproject.toml').read_text())
    deps = t['project']['dependencies']
    assert 'abhyasa==0.0.15' in deps and 'rupaka==0.0.9' in deps
    assert 'abhyasa' not in t['tool']['uv']['sources']

def test_room_spec_contract():
    from abhyasa.stagekit import room_spec
    s = {'state': {'x': 2}, 'blocks': [{'type': 'row', 'blocks': [{'type': 'gate', 'id': 'g', 'answer': {'is': 'two'}, 'why': 'w'}]}, {'type': 'readout', 'answer': 1}]}
    assert room_spec(s) == {'state': {'x': 2}, 'blocks': [{'type': 'row', 'blocks': [{'type': 'gate', 'id': 'g', 'why': 'w'}]}, {'type': 'readout', 'answer': 1}]}
    assert s['blocks'][0]['blocks'][0]['answer'] == {'is': 'two'}

def test_talk_contract():
    from abhyasa.talk import TALK_SCHEMA, TALK_CASES, check_talk, new_run
    assert TALK_SCHEMA == 1
    for t, want in TALK_CASES: assert check_talk(t) == want
    run = new_run(TALK_CASES[0][0], now=1.)
    assert run['at'] == dict(slide='s1', beat=1, blank=False, pane=None, ask=None) and len(run['key']) == 16

def test_stage_contract():
    from importlib.resources import files
    from abhyasa.core.stage import STAGE_V, STAGE_TYPES, STAGE_CASES
    js = (files('abhyasa.core')/'stage.js').read_text()
    assert STAGE_V == 1 and 'out' not in STAGE_TYPES and (files('abhyasa.core')/'stage.css').is_file()
    src = js + f'\nprocess.stdout.write(JSON.stringify({json.dumps([m for m, _ in STAGE_CASES])}.map(abhyasaStage.valid)));'
    got = json.loads(subprocess.run(['node', '-'], input=src, capture_output=True, text=True, check=True).stdout)
    assert got == [ok for _, ok in STAGE_CASES]

def test_learn_handoff():
    from abhyasa.contract import LEELA_ROUTE, HANDOFF_CASES, HANDOFF_BAD, handoff, read_handoff
    assert LEELA_ROUTE == '/learn' and any(kw.get('v') for kw, _ in HANDOFF_CASES)
    for kw, path in HANDOFF_CASES:
        assert handoff(**kw) == path
        q = read_handoff(path.split('?', 1)[1])
        assert (q.walk, q.step, q.topic, q.v) == (kw.get('jid', ''), kw.get('i'), kw.get('topic', ''), kw.get('v', ''))
    for bad in HANDOFF_BAD:
        with pytest.raises(ValueError): read_handoff(bad)

def test_nb_spec_cases(tmp_path, monkeypatch):
    from abhyasa.contract import NB_SPEC_CASES, validate_nb_spec
    monkeypatch.setenv('HOME', str(tmp_path))   # `path_why` reads the home folder: a linked ~/code must not change a case
    for spec, key in NB_SPEC_CASES:
        if key is None: assert validate_nb_spec(spec)['run']
        else:
            with pytest.raises(ValueError, match=f'^{key}:'): validate_nb_spec(spec)

def test_run_cases():
    from abhyasa.contract import RUN_CASES, run_ok
    assert [run_ok(a) for a, _ in RUN_CASES] == [ok for _, ok in RUN_CASES]

def test_prompts_contract(abhyasa_cfg):
    import abhyasa.tutor
    from abhyasa.prompts import PROMPTS, prompt
    assert 'tutor' in PROMPTS and prompt('tutor') == PROMPTS['tutor'].dflt

def abhyasa_imports():
    "Each `(module, name)` that Leela's source imports from abhyasa; `name` is None for `import abhyasa.x`."
    import ast
    seen = set()
    for f in (ROOT/'leela').rglob('*.py'):
        for n in ast.walk(ast.parse(f.read_text(), str(f))):
            if isinstance(n, ast.ImportFrom) and n.level == 0 and (n.module or '').split('.')[0] == 'abhyasa': seen |= {(n.module, a.name) for a in n.names}
            elif isinstance(n, ast.Import): seen |= {(a.name, None) for a in n.names if a.name.split('.')[0] == 'abhyasa'}
    return sorted(seen, key=str)

def test_every_name_leela_imports_from_abhyasa_is_there():
    "abhyasa main removed `abhyasa.check`, and Leela did not start: `from abhyasa import check` raised ImportError."
    import importlib
    got = abhyasa_imports()
    assert ('abhyasa.contract', 'handoff') in got and len(got) > 20, got
    gone = []
    for mod, name in got:
        try: m = importlib.import_module(mod)
        except ImportError as e: gone.append(f'{mod}: {e}'); continue
        if name is not None and not hasattr(m, name):
            try: importlib.import_module(f'{mod}.{name}')
            except ImportError: gone.append(f'{mod}.{name}')
    assert gone == [], gone

def test_run_isolated_contract():
    from leela.blocks.nb.check import run_isolated
    ps = inspect.signature(run_isolated).parameters
    assert list(ps)[:4] == ['kind', 'fname', 'source', 'tests'] and {'total', 'setup', 'sandbox', 'python', 'unix'} <= ps.keys()

def test_journey_contract():
    from abhyasa.journey import walk_state
    from abhyasa.store import Learning
    assert all(hasattr(Learning, n) for n in ('put_journey', 'journey', 'journeys'))
    assert walk_state(dict(steps=[dict(slug='a', status='done'), dict(slug='b')])).current == 1
