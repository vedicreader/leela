"The type gate: only exact plain types cross to the scrub worker, and they come out equal."
import datetime as dt, json
import pytest
from leela.blocks.nb import scrubwire as w
np = pytest.importorskip('numpy'); pd = pytest.importorskip('pandas')

def back(x): return w.decode(json.loads(json.dumps(w.encode(x))))

@pytest.mark.parametrize('x', [None, True, 3, 2.5, 'a', b'xy', 1 + 2j, (1, [2, {3: 'x'}]), {1, 2}, frozenset('ab'), {'a': 1, 2: (3,)}, float('inf'),
                               dt.datetime(2020, 1, 2, 3, 4, 5), dt.date(2020, 1, 2), dt.time(1, 2), dt.timedelta(days=1, seconds=2, microseconds=3), 10**30, [[]]])
def test_plain_values_round_trip(x): assert back(x) == x and type(back(x)) is type(x)

def test_arrays_and_frames_round_trip():
    a = np.arange(6.).reshape(2, 3); assert np.array_equal(back(a), a) and back(a).dtype == a.dtype and back(a).flags.writeable
    for arr in (np.array(['ab', 'c']), np.array([1, 2], dtype='int8'), np.array(['2020-01-01'], dtype='datetime64[ns]'), np.array([True, False]), np.float64(2.5)): assert np.array_equal(back(arr), arr)
    df = pd.DataFrame({'a': [1, 2], 'b': [0.5, 1.5], 't': pd.to_datetime(['2020-01-01', '2020-01-02']), 's': ['x', 'y']}, index=[10, 20])
    assert back(df).equals(df) and back(df.a).equals(df.a) and back(df.set_index('s')).equals(df.set_index('s'))
    assert back(pd.DataFrame({'a': [1]})).index.equals(pd.RangeIndex(1))

class Spy:
    def __len__(s): raise AssertionError('the gate called a hook')
    def __repr__(s): raise AssertionError('the gate called a hook')
    def __getattr__(s, k): raise AssertionError('the gate called a hook')

def loop():
    x = []; x.append(x); return x

@pytest.mark.parametrize('x,why', [(Spy(), 'Spy'), (lambda: 1, 'function'), (iter([1]), 'list_iterator'), (np.array([object()]), 'array'), (np.array([(1, 2)], dtype='i,i'), 'array'),
                                   (pd.DataFrame({'a': [object()]}), 'column'), (pd.DataFrame({'a': pd.Categorical(['x'])}), 'column'), (pd.Series([1], index=pd.MultiIndex.from_tuples([(1, 2)])), 'index'),
                                   (dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc), 'zone'), (loop(), 'itself'), (list(range(10**5 + 1)), 'elements'), (np.zeros(10**5 + 1), 'elements'),
                                   ([[Spy()]], 'Spy'), ({'k': print}, 'builtin_function_or_method'), (type('Sub', (list,), {})(), 'Sub'), (type('I', (int,), {})(1), 'I'), (object(), 'object')], ids=lambda v: 'x' if not isinstance(v, str) else v)
def test_anything_else_is_refused_without_calling_it(x, why):
    with pytest.raises(w.Bad) as e: w.encode(x)
    assert why in str(e.value)

def test_a_snapshot_names_the_first_name_it_cannot_copy_and_skips_missing_ones():
    got = json.loads(w.snapshot_json({'a': 1, 'b': Spy(), 'c': 2}, ['a', 'zz', 'b', 'c']))
    assert got['bad'] == 'b' and 'Spy' in got['why']
    got = json.loads(w.snapshot_json({'a': 1}, ['a', 'zz']))
    assert got == {'ok': {'a': 1}, 'missing': ['zz']}

def test_the_cap_counts_bytes_not_only_elements():
    "One 5 MB string is one element but too many bytes; so is a small array of long strings; two names share one budget."
    for x, why in (('x' * (5 * 2**20), 'MB'), (b'x' * (5 * 2**20), 'MB'), (np.array(['x' * 1000] * 2000), 'MB'), (pd.Series(['x' * 100_000] * 50, dtype='string'), 'MB'), (['x' * 100_000] * 50, 'MB')):
        with pytest.raises(w.Bad) as e: w.encode(x)
        assert why in str(e.value)
    assert w.encode('x' * 1000) == 'x' * 1000 and back(np.array(['ab', 'c'])).tolist() == ['ab', 'c']
    half = 'x' * (3 * 2**20)
    assert 'ok' in json.loads(w.snapshot_json({'a': half}, ['a']))
    got = json.loads(w.snapshot_json({'a': half, 'b': half}, ['a', 'b']))
    assert got['bad'] == 'b' and 'MB' in got['why']

def test_a_numpy_scalar_is_judged_by_its_exact_type_not_by_the_module_it_claims():
    class Fake(np.float64): __module__ = 'numpy'
    with pytest.raises(w.Bad): w.encode(Fake(1.0))
    assert back(np.float64(2.5)) == 2.5 and type(back(np.int8(3))) is np.int8
