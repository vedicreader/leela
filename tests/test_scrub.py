"A number scrubbed in a code cell re-runs the cell only when the cell is safe to run over and over."
import json, shutil, subprocess
from pathlib import Path
import pytest
from leela.blocks.nb.scrub import scrub_ok, scrub_why

ROOT = Path(__file__).parents[1]

OK = ['x = 3\nprint(x*2)', 'import math\nprint(math.sin(0.5))', 'import numpy as np\na = np.linspace(0, 1, 5)\nprint(a.sum())',
      'import matplotlib.pyplot as plt\nplt.plot([1, 2, 3])\nplt.show()', 'import pandas as pd\ndf = pd.DataFrame({"a": [1, 2]})\ndf', 'import random\nrandom.seed(1)\nrandom.random()',
      'from collections import Counter\nCounter("aab")', 'import itertools, functools\nlist(itertools.islice(range(10), 3))',
      'import time\ntime.sleep(0.5)', 'import time\ntime.sleep(1)', 'xs = []\nxs.append(1)\nprint(xs)', 'total = 0\ntotal += 5\ntotal',
      'def f(n):\n    return n * 2\nf(4)', 'print(sum(i*i for i in range(10)))', 'with open("a.txt") as f:\n    pass', 'open("a.txt", "rb")',
      'd = {}\nd["a"] = 1\nd', 'import statistics\nstatistics.mean([1, 2, 3])']
BAD = [('open("a.txt", "w").write("x")', 'write'), ('open("a.txt", mode="a")', 'open'), ('open("a.txt", "r+")', 'open'), ('open("a", m)', 'open'),
       ('import requests', 'requests'), ('import urllib.request', 'urllib'), ('from urllib import request', 'urllib'), ('import subprocess', 'subprocess'),
       ('import os\nos.system("ls")', 'os'), ('import shutil', 'shutil'), ('import socket', 'socket'), ('input("x")', 'input'),
       ('import time\ntime.sleep(2)', 'sleeps'), ('import time\ntime.sleep(n)', 'sleeps'), ('exec("x=1")', 'exec'), ('eval("1+1")', 'eval'),
       ('__import__("os")', '__import__'), ('import sys', 'sys'), ('import pickle', 'pickle'), ('from . import x', 'relative'),
       ('global g\ng = 1', 'global'), ('data.append(1)', 'data'), ('count += 1', 'count'), ('cfg["a"] = 1', 'cfg'),
       ('import matplotlib.pyplot as plt\nplt.savefig("a.png")', 'savefig'), ('import pandas as pd\npd.DataFrame().to_csv("a.csv")', 'to_csv'),
       ('import numpy as np\nnp.save("a", [1])', 'save'), ('from pathlib import Path\nPath("a").write_text("x")', 'pathlib'),
       ('x.__class__.__subclasses__()', '__subclasses__'), ('%timeit 1', 'valid Python'), ('!ls', 'valid Python'), ('x = (', 'valid Python'),
       ('import importlib', 'importlib'), ('breakpoint()', 'breakpoint'), ('setattr(o, "a", 1)', 'setattr'), ('globals()["a"] = 1', 'globals')]

@pytest.mark.parametrize('src', OK)
def test_a_pure_cell_may_scrub(src): assert scrub_ok(src), scrub_why(src)

@pytest.mark.parametrize('src,word', BAD)
def test_an_unsafe_cell_is_refused_with_a_reason(src, word):
    why = scrub_why(src)
    assert why and word in why and not scrub_ok(src), why

def test_a_reason_is_one_line(): assert all('\n' not in scrub_why(s) for s, _ in BAD)

def test_a_name_made_in_the_cell_may_change_and_one_made_outside_may_not():
    assert scrub_ok('a = [1]\na.append(2)') and not scrub_ok('a.append(2)')
    assert scrub_ok('a = 0\na += 1') and not scrub_ok('a += 1')
    assert scrub_ok('for i in range(3):\n    pass\ni += 1')

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
