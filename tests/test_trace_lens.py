"The inline trace's text for each line and step, from the model the pane gets: no browser, no editor."
import json, shutil, subprocess
from pathlib import Path
import pytest
from dhrishti.trace import trace_model

ROOT = Path(__file__).parents[1]
JS = r'''
const fs = require('fs'), vm = require('vm'); const ctx = {console, setTimeout, clearTimeout}; ctx.window = ctx; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
const [name, args] = JSON.parse(process.argv[2]);
console.log(JSON.stringify(vm.runInContext(`(${name})`, ctx)(...args)));
'''

def lens(name, *args):
    node = shutil.which('node')
    if not node: pytest.skip('node is not installed')
    r = subprocess.run([node, '-e', JS, str(ROOT/'leela/blocks/nb/tracelens.js'), json.dumps([name, list(args)])], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)

def ev(step, line, **vals): return dict(step=step, line=line, event='line', depth=1, locals_changed=vals)

def loop(n, skip=0):
    "A two-line loop: line 2 sets `i`, line 3 sets `t`, `n` passes."
    out, step, t = [ev(0, 1, t='0')], 1, 0
    for i in range(n):
        t += i; out += [ev(step, 2, i=str(i)), ev(step + 1, 3, t=str(t))]; step += 2
    if skip: out.insert(5, dict(step=step, line=2, event='skip', depth=1, count=skip, locals_changed={}))
    return out

def test_each_line_shows_what_its_current_pass_made():
    m = trace_model(loop(3))
    assert lens('leeLensTexts', m, 6) == {'1': 't=0', '2': 'i=2', '3': 't=3'}
    assert lens('leeLensTexts', m, 2) == {'1': 't=0', '2': 'i=0', '3': 't=0'}

def test_a_line_that_has_not_run_yet_has_no_current_column():
    m = trace_model(loop(3))
    assert '3' not in lens('leeLensTexts', m, 1)
    p = lens('leeLensLine', m, 1, 3)
    assert p['cur'] == -1 and not any(c['cur'] for c in p['cols']) and all(c['future'] for c in p['cols'])

def test_a_long_loop_keeps_eight_columns_round_the_current_pass_and_counts_the_rest():
    m = trace_model(loop(30))
    p = lens('leeLensLine', m, 40, 2)
    cols = [c['i'] for c in p['cols']]
    assert len(cols) == 8 and p['before'] == cols[0] and p['after'] == 30 - cols[-1] - 1 and any(c['cur'] for c in p['cols'])
    assert lens('leeLensLine', m, 40, 2, 20)['cols'][0]['i'] == 20 and lens('leeLensLine', m, 40, 2, 99)['cols'][-1]['i'] == 29

def test_a_narrow_editor_gets_fewer_columns_but_always_the_current_one():
    m = trace_model(loop(30))
    p = lens('leeLensLine', m, 40, 2, None, 90)
    assert 1 <= len(p['cols']) < 8 and any(c['cur'] for c in p['cols'])
    assert any(c['cur'] for c in lens('leeLensLine', m, 40, 2, None, 1)['cols'])

def test_skipped_passes_are_counted_and_kept_out_of_the_columns():
    m = trace_model(loop(10, skip=4900))
    p = lens('leeLensLine', m, 5, 2)
    assert p['skipped'] == 4900 and all('skip' not in c for c in p['cols'])

def test_a_changed_value_carries_the_old_one_from_the_last_run():
    a, b = loop(3), loop(3)
    b[1]['locals_changed'] = dict(i='9')
    m = trace_model(b, prev=a)
    c = lens('leeLensLine', m, 99, 2)['cols'][0]
    assert c['parts'][0]['was'] == '0' and lens('leeLensText', c) == 'i=0→9'

def test_unchanged_values_are_marked_so_the_strip_can_dim_them():
    ev_ = [ev(0, 1, a='1'), ev(1, 1, a='1', b='2'), ev(2, 1, a='1', b='3')]
    cols = lens('leeLensLine', trace_model(ev_), 2, 1)['cols']
    assert [[q['chg'] for q in c['parts']] for c in cols] == [[True], [False, True], [False, True]]
