"Settings > Learn refuses what Abhyasa's own `fit` would clamp or replace, for every row, with a sentence that names the bound."
import itertools
import pytest
from leela.blocks.learn.app import learn_rows
from leela.blocks.settings import settings as S
from leela.blocks.settings.app import saved_say
from leela.blocks.settings.settings import Settings, register_section
from copy import deepcopy

abh = pytest.importorskip('abhyasa.learner')
ROWS = learn_rows()
NUM = [r for r in ROWS if r['kind'] in ('int', 'float') and r['lo'] is not None]
CAPS = {r['hi_key'] for r in NUM if r['hi_key']}   # lowering a cap under the row it limits is refused: see the limit test
_n = itertools.count()

@pytest.fixture
def s(monkeypatch, tmp_path):
    for n in ('DEFAULT_SETTINGS', '_ENUMS', '_RANGES', 'USER_ONLY', 'SECTIONS'): monkeypatch.setattr(S, n, deepcopy(getattr(S, n)))
    register_section('learn', ROWS, 'abhyasa')
    return lambda: Settings(None, user_path=tmp_path/f'u{next(_n)}.json')

def _leela_takes(s, key, v):
    try: s().save('user', 'learn', {key: v}); return True
    except ValueError: return False

def _abh_takes(name, v, **given):
    with abh.use_settings({k.replace('__', '.'): x for k, x in given.items()}):
        r = abh.SETTINGS[name]
        f = abh.fit(r, v)
        return type(f) is type(v) and f == v

def test_learn_has_rows_to_test(): assert len(NUM) > 30 and {'walks.steps', 'links.pages', 'walks.hands'} <= {r['key'] for r in NUM}

@pytest.mark.parametrize('r', NUM, ids=lambda r: r['key'])
def test_numbers_match_abhyasa(s, r):
    name, lo = r['key'], r['lo']
    with abh.use_settings({}): hi = abh.top(abh.SETTINGS[name]) if name in abh.SETTINGS else r['hi']
    step = 1 if r['kind'] == 'int' else 0.01 * (hi - lo)
    for v in (lo - step, lo, hi, hi + step)[2 * (name in CAPS):]:
        v = int(v) if r['kind'] == 'int' else v
        want = _abh_takes(name, v) if name in abh.SETTINGS else lo <= v <= hi
        assert _leela_takes(s, name, v) == want, (name, v)

@pytest.mark.parametrize('r', [r for r in NUM if r['hi_key']], ids=lambda r: r['key'])
def test_a_limit_that_is_another_setting_is_enforced(s, r):
    cap = r['hi_key']
    for lim in (5, 12):
        for v in (lim - 1, lim, lim + 1):
            want = _abh_takes(r['key'], v, **{cap.replace('.', '__'): lim})
            try: s().save('user', 'learn', {cap: lim, r['key']: v}); got = True
            except ValueError: got = False
            assert got == want, (r['key'], lim, v)

@pytest.mark.parametrize('r', [r for r in ROWS if r['kind'] in ('bool', 'choice', 'str') and r['key'] in abh.SETTINGS], ids=lambda r: r['key'])
def test_other_kinds_match_abhyasa(s, r):
    odd = {'bool': [True, False, 'yes', 1, 0], 'choice': [*r['choices'], 'zzz', 3], 'str': ['text', 5, True]}[r['kind']]
    for v in odd: assert _leela_takes(s, r['key'], v) == _abh_takes(r['key'], v), (r['key'], v)

def test_numbers_that_are_not_numbers_are_refused(s):
    for v in (True, 'x', float('nan'), float('inf'), None, [3]): assert not _leela_takes(s, 'walks.steps', v), v
    assert _leela_takes(s, 'walks.steps', ' 5 ')

def test_the_refusal_names_the_bound(s):
    for key, v, say in (('walks.steps', 99, 'Ideas in a walk must be from 3 to 7.'), ('walks.steps', 2, 'Ideas in a walk must be from 3 to 7.'),
                        ('walks.hands', 1.5, 'Hands-on share must be from 0% to 100%.'), ('walks.passage', 5000, 'Passage length must be from 200 to 2000 characters.'),
                        ('walks.steps', 'x', 'Ideas in a walk must be a number.'), ('guide.point', 'x', None)):
        with pytest.raises(ValueError) as e: s().save('user', 'learn', {key: v})
        assert say is None or str(e.value) == say, str(e.value)
    with pytest.raises(ValueError, match=r'^Pages? .* must be from 1 to 5, the limit set by .*\.$'): s().save('user', 'learn', {'links.cap': 5, 'links.pages': 6})
    with pytest.raises(ValueError) as e: s().save('user', 'learn', {'links.cap': 5, 'links.pages': 6})
    assert 'learn.' not in str(e.value)

def test_the_route_refuses_99_and_a_save_says_no_path(s, tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    from fasthtml.common import FastHTML
    from types import SimpleNamespace as NS
    from leela.blocks.settings.app import connect
    monkeypatch.setattr(S, 'user_settings_file', lambda: tmp_path/'route.json')
    app = FastHTML(); connect(app, NS(session=NS(project_root=None)))
    c = TestClient(app)
    bad = c.post('/settings/save', json=dict(scope='user', section='learn', values={'walks.steps': 99})).json()
    assert not bad.get('ok') and 'Ideas in a walk must be from 3 to 7.' in str(bad) and not (tmp_path/'route.json').exists()
    ok = c.post('/settings/save', json=dict(scope='user', section='learn', values={'walks.steps': 5})).json()
    assert ok['ok'] and ok['message'] == saved_say('user') and str(tmp_path) not in ok['message'] and '/' not in ok['message']
    assert saved_say('workspace', 'python') == 'Saved. This applies to this project, in python files.'
