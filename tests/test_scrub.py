"A number scrubbed in a code cell re-runs the cell only when the cell is safe to run over and over."
import ast, copy, json, os, shutil, subprocess
from pathlib import Path
import pytest
from leela.blocks.nb.scrub import scrub_ok, scrub_why

ROOT = Path(__file__).parents[1]
CORPUS = json.loads((ROOT/'tests'/'scrub_corpus.json').read_text())
IDS = [c['name'] for c in CORPUS]

@pytest.mark.parametrize('case', CORPUS, ids=IDS)
def test_the_corpus_verdict_holds(case):
    "Every snippet the independent review judged unsafe is refused and every one judged safe is accepted; `judgement` marks a call the review left open."
    why = scrub_why(case['src'])
    assert bool(why) == (case['want'] == 'refuse'), (case['name'], case['want'], why)
    assert '\n' not in why

def test_the_corpus_is_big_and_names_its_judgement_calls():
    assert len(CORPUS) >= 190 and sum(c['want'] == 'refuse' for c in CORPUS) > 100 and sum(c['want'] == 'accept' for c in CORPUS) > 25
    assert 0 < sum(c['judgement'] for c in CORPUS) < 70

def test_what_is_accepted_runs_without_touching_a_file_or_a_name_another_cell_made(tmp_path, monkeypatch):
    "Run every accepted snippet in an empty folder against a made-up notebook: no file appears or changes, and no outside value changes."
    np = pytest.importorskip('numpy'); pd = pytest.importorskip('pandas'); plt = pytest.importorskip('matplotlib.pyplot')
    import matplotlib; matplotlib.use('agg')
    monkeypatch.chdir(tmp_path); (tmp_path/'victim.txt').write_text('precious')
    outside = lambda: dict(data=[1, 2, 3], xs=[1, 2, 3], arr=np.ones(3), df=pd.DataFrame({'a': [1, 5]}), d={'a': 1}, rng=np.random.default_rng(1))
    for c in CORPUS:
        if c['want'] != 'accept' or c['name'] in ('busy time loop', 'recursion'): continue
        ns = outside(); before = {k: copy.deepcopy(v) for k, v in ns.items()}
        try: exec(compile(c['src'], c['name'], 'exec'), ns)
        except Exception: pass
        plt.close('all')
        made = {n.id for n in ast.walk(ast.parse(c['src'])) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
        for k, v in before.items():
            if k in made: continue
            same = (v.equals(ns[k]) if hasattr(v, 'equals') else (v == ns[k]).all() if hasattr(v, 'all') else (v.bit_generator.state == ns[k].bit_generator.state if hasattr(v, 'bit_generator') else v == ns[k]))
            assert same, (c['name'], k)
        assert sorted(os.listdir(tmp_path)) == ['victim.txt'] and (tmp_path/'victim.txt').read_text() == 'precious', c['name']

@pytest.mark.parametrize('bad', [None, 5, b'x = 1', [], '(' * 6000 + ')' * 6000, 'x = ' + '-' * 8000 + '1', '\x00', 'x = 1\n' * 20000, 'f"{"', '1 +'])
def test_the_check_never_raises(bad):
    assert isinstance(scrub_why(bad), str)

def test_a_dragged_number_that_makes_a_safe_cell_unsafe_is_refused_on_the_new_text():
    assert scrub_ok('import time\ntime.sleep(0.5)') and not scrub_ok('import time\ntime.sleep(5)')
    assert scrub_ok('import numpy as np\nnp.ones((100, 100))') and not scrub_ok('import numpy as np\nnp.ones((50000, 50000))')
    assert scrub_ok('x = [0] * 100') and not scrub_ok('x = [0] * 1000000000')
    assert scrub_ok('for i in range(100): pass') and not scrub_ok('for i in range(10**9): pass')

def test_a_reason_names_the_cell_s_problem_in_one_line():
    assert 'safe list' in scrub_why('import os') and 'open' in scrub_why("open('a', 'w')") and 'another cell' in scrub_why('x = x + 1')

JS = r'''
const fs = require('fs'), vm = require('vm'); const ctx = {console, setTimeout, clearTimeout, setInterval, clearInterval}; ctx.window = ctx; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
const [name, args] = JSON.parse(process.argv[2]);
Promise.resolve(vm.runInContext(`(${name})`, ctx)(...args)).then(r => console.log(JSON.stringify(r)));
'''

def js(name, *args):
    node = shutil.which('node')
    if not node: pytest.skip('node is not installed')
    r = subprocess.run([node, '-e', JS, str(ROOT/'leela/blocks/nb/scrub.js'), json.dumps([name, list(args)])], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])

FIND = [('x = 3', 4, ['3', 4, 5]), ('x = 3', 5, ['3', 4, 5]), ('x = 3', 1, None), ('y = -2.5 * 2', 5, ['-2.5', 4, 8]), ('a - 3', 4, ['3', 4, 5]),
        ('f(-3)', 3, ['-3', 2, 4]), ('s = "abc 12"', 9, None), ('# 7', 2, None), ('x1 = 5', 1, None), ('x = 1e5', 5, None), ('x = 1_000', 5, None),
        ('x = 0x1f', 5, None), ('x = .5', 5, ['.5', 4, 6]), ('x = 2j', 4, None), ('"""a\n3"""\ny = 4', 14, ['4', 14, 15])]

@pytest.mark.parametrize('text,at,want', FIND)
def test_a_number_is_found_where_python_reads_one(text, at, want):
    got = js('(t, p) => { const r = leeScrubFind(t, p); return r && [r.text, r.from, r.to]; }', text, at)
    assert got == want

STEP = [('3', 1, 0, '4'), ('3', -5, 0, '-2'), ('0.5', 1, 0, '0.51'), ('0.5', 10, 0, '0.60'), ('100', 7, 0, '107'), ('2000', 1, 0, '2010'), ('2000', 1, 1, '2001'),
        ('1.25', 1, 0, '1.251'), ('1234.5', 1, 0, '1235.5'), ('-3', 5, 0, '2'), ('3', -5, 0, '-2'), ('0', 1, 0, '1'), ('1.0', 3, 0, '1.03')]

@pytest.mark.parametrize('text,n,fine,want', STEP)
def test_a_drag_moves_a_number_by_a_step_its_size_and_decimals_choose(text, n, fine, want):
    got = js('(t, n, f) => leeScrubStep(t, n, f)', text, n, fine)
    assert got == want

def test_a_number_without_a_sign_never_flips_to_a_negative_that_would_double_the_minus():
    assert js('(t, n, s) => leeScrubStep(t, n, 0, s)', '3', -9, False) == '0'

NUMS = [('x -3', ['3']), ('x - 3', ['3']), ('f(-3)', ['-3(s)']), ('a[-1]', ['-1(s)']), ('1-2', ['1', '2']), ('2**-3', ['2', '-3(s)']), ('return -3', ['-3(s)']),
        ('print(x) -3', ['3']), ('x = 1.5e-3', []), ('x = 1E5', []), ('x=1_000', []), ('x=2j', []), ('x=- 3', ['3']), ('t = (a\n     - 3)', ['3']), ('x = (a\n -3)', ['3']),
        ('x = (\n -3)', ['-3(s)']), ('é3 = 5', ['5']), ('x = 3 if -1 else 4', ['3', '-1(s)', '4']), ('x=00', []), ('x=007', []), ('x = 0.', ['0.']), ('x = .5', ['.5']),
        ('x=a--3', ['-3(s)']), ('else -3', ['-3(s)']), ('in -3', ['-3(s)']), ('x = 1e+5', []), ('x=1.real', []), ('x[1:-1]', ['1', '-1(s)']), ('x = a -\n 3', ['3']),
        ('٣ + 4', ['4']), ('x = 12345678901234567890', ['12345678901234567890'])]

@pytest.mark.parametrize('text,want', NUMS)
def test_the_scan_reads_numbers_as_python_does(text, want):
    "Spaced and line-start minus, a keyword before a minus, exponents, `_`, `j`, leading zeros and non-ASCII names, from the review."
    assert js('(t) => leeScrubScan(t).map(r => r.text + (r.signed ? "(s)" : ""))', text) == want

BIG = [('12345678901234567890', 1, 0, '12445678901234567890'), ('1.23456789012', 1, 0, '1.23556789012'), ('0.1', -3, 0, '0.07'), ('0.0', -1, 0, '-0.01'),
       ('0.001', 1, 0, '0.0011'), ('-0.0', 1, 0, '0.01'), ('5.', 1, 0, '5.1'), ('.5', 1, 0, '0.51'), ('99.9', 1, 0, '99.91'), ('0.30', 1, 0, '0.301')]

@pytest.mark.parametrize('text,n,fine,want', BIG)
def test_a_step_is_exact_for_big_integers_and_long_decimals(text, n, fine, want): assert js('(t, n, f) => leeScrubStep(t, n, f)', text, n, fine) == want

def test_a_drag_stops_at_a_million_or_a_hundred_times_the_start():
    assert js('() => [leeScrubWindow("3"), leeScrubWindow("0.5"), leeScrubWindow("50000"), leeScrubWindow("-200")]') == [300, 100, 1000000, 20000]

def test_the_gate_runs_at_most_every_150ms_keeps_only_the_newest_value_and_ends_on_the_last():
    got = js('''async () => {
      const log = [], t0 = Date.now(); let busy = 0, over = 0;
      const g = leeScrubGate(async v => { over = Math.max(over, ++busy); log.push([v, Date.now() - t0]); await new Promise(r => setTimeout(r, 40)); busy--; }, 150);
      for (let v = 1; v <= 30; v++) { g.push(v); await new Promise(r => setTimeout(r, 20)); }
      await g.end();
      return {vals: log.map(x => x[0]), gaps: log.slice(1).map((x, i) => x[1] - log[i][1]), over};
    }''')
    assert got['over'] == 1 and got['vals'][-1] == 30 and len(got['vals']) <= 6, got
    assert all(g >= 140 for g in got['gaps']), got

def test_the_gate_stops_when_a_run_says_it_is_too_slow():
    got = js('''async () => {
      const seen = []; const g = leeScrubGate(async v => { seen.push(v); return 'stop'; }, 10);
      g.push(1); await new Promise(r => setTimeout(r, 50)); g.push(2); await new Promise(r => setTimeout(r, 50)); await g.end();
      return seen;
    }''')
    assert got == [1]
