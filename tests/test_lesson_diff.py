import json, shutil, subprocess
from pathlib import Path
import pytest
from leela.blocks.nb.lesson import same_lines

CASES = [
    ('equal', 'one\ntwo', 'one\ntwo', [('one', 'one', 'match'), ('two', 'two', 'match')]),
    ('spaces', '  one\t two  ', 'one two', [('one two', 'one two', 'match')]),
    ('blank-lines', '\n one\n\n two \n', 'one\n \n two', [('one', 'one', 'match'), ('two', 'two', 'match')]),
    ('shorter', 'one', 'one\ntwo', [('one', 'one', 'match'), (None, 'two', 'missing')]),
    ('longer', 'one\ntwo', 'one', [('one', 'one', 'match'), ('two', None, 'extra')]),
    ('middle', 'a\nx\nc', 'a\nb\nc', [('a', 'a', 'match'), ('x', 'b', 'mismatch'), ('c', 'c', 'match')]),
    ('empty-guess', '', 'one', [(None, 'one', 'missing')]),
    ('unicode', '  नमस्ते\t 世界 🙂 ', 'नमस्ते 世界 🙂', [('नमस्ते 世界 🙂', 'नमस्ते 世界 🙂', 'match')]),
    ('both-empty', '', '', []),
    ('empty-actual', 'one', '', [('one', None, 'extra')]),
    ('crlf', 'one\r\ntwo\rthree', 'one\ntwo\nthree', [('one', 'one', 'match'), ('two', 'two', 'match'), ('three', 'three', 'match')]),
    ('python-breaks', 'a\vb\fc\x1cd\x1de\x1ef\x85g\u2028h\u2029i', 'a\nb\nc\nd\ne\nf\ng\nh\ni', [(c, c, 'match') for c in 'abcdefghi']),
    ('python-spaces', ' a\x1fb\u00a0c\u1680d\u2007e\u202ff\u205fg\u3000h ', 'a b c d e f g h', [('a b c d e f g h', 'a b c d e f g h', 'match')]),
    ('bom-not-space', '\ufeffone', 'one', [('\ufeffone', 'one', 'mismatch')]),
    ('zero-width-not-space', 'one\u200btwo', 'one two', [('one\u200btwo', 'one two', 'mismatch')]),
    ('only-spaces', '\t \x1f\u00a0\u1680\u2007\u202f\u205f\u3000', '', []),
]
LESSON = Path(__file__).parents[1]/'leela'/'blocks'/'nb'/'lesson.js'
HARNESS = r'''
const vm = require('vm'), fs = require('fs');
const ctx = {console, Map, Set, JSON, Math}; ctx.window = ctx; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
console.log(JSON.stringify(JSON.parse(process.argv[2]).map(([guess, actual]) => ctx.learnDiff(guess, actual))));
'''

@pytest.mark.parametrize('name,guess,actual,rows', CASES, ids=[c[0] for c in CASES])
def test_python_same_lines_shared_cases(name, guess, actual, rows):
    assert same_lines(guess, actual) == [dict(guess=g, actual=a, kind=k) for g, a, k in rows]

def test_javascript_learn_diff_matches_python_shared_cases():
    node = shutil.which('node')
    if not node: pytest.skip('node is not installed')
    inputs = [(guess, actual) for _, guess, actual, _ in CASES]
    r = subprocess.run([node, '-e', HARNESS, str(LESSON), json.dumps(inputs)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout.strip().splitlines()[-1])
    assert got == [same_lines(guess, actual) for guess, actual in inputs]
