import json, shutil, subprocess
from pathlib import Path
import pytest

ROOT = Path(__file__).parents[1]
HARNESS = r'''
const vm = require('vm'), fs = require('fs');
const ctx = {console}; ctx.window = ctx; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8').match(/const stripAnsi = .*;/)[0], ctx);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), ctx);
console.log(JSON.stringify(JSON.parse(process.argv[3]).map(c => ctx.lessonRevealText(c))));
'''
CASES = [
    ('all-match', 'one\ntwo', [{'output_type': 'stream', 'text': 'one\ntwo\n'}], None, 'Right. You saw that before running it.'),
    ('mismatch', 'one\nx\nthree', [{'output_type': 'stream', 'text': 'one\ntwo\nthree'}], None, 'one\nthree\nYou wrote x. It printed two.'),
    ('missing', 'one', [{'output_type': 'stream', 'text': 'one\ntwo'}], None, 'one\nIt printed two, which you did not expect.'),
    ('extra', 'one\ntwo', [{'output_type': 'execute_result', 'data': {'text/plain': ['one']}}], None, 'one\nYou expected two, which did not appear.'),
    ('raised', 'one', [{'output_type': 'error', 'ename': 'NameError', 'evalue': "name 'x' is not defined", 'traceback': ['Traceback', "\u001b[31mNameError: name 'x' is not defined\u001b[0m"]}], None, "You wrote one. It printed It raised NameError: name 'x' is not defined."),
    ('joined', 'one\ntwo\nthree', [{'output_type': 'stream', 'text': ['one\n', 'two\n']}, {'output_type': 'display_data', 'data': {'text/plain': 'three'}}], 90, 'Right. You saw that before running it.'),
    ('html', '<img onerror=bad>', [{'output_type': 'stream', 'text': '<script>bad</script>'}], 10, 'You wrote <img onerror=bad>. It printed <script>bad</script>.'),
]

@pytest.mark.parametrize('name,guess,outputs,confidence,expected', CASES, ids=[c[0] for c in CASES])
def test_reveal_text(name, guess, outputs, confidence, expected):
    node = shutil.which('node')
    if not node: pytest.skip('node is not installed')
    cell = dict(extra={'lesson': dict(prediction=guess, confidence=confidence)}, outputs=outputs)
    r = subprocess.run([node, '-e', HARNESS, str(ROOT/'leela/blocks/nb/cells.js'), str(ROOT/'leela/blocks/nb/lesson.js'), json.dumps([cell])], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout.strip().splitlines()[-1]) == [expected]

@pytest.mark.parametrize('confidence', [None, 10, 30, 50, 59, 60, 70, 90])
@pytest.mark.parametrize('wrong', [False, True])
def test_sure_line_only_for_confident_miss(confidence, wrong):
    node = shutil.which('node')
    if not node: pytest.skip('node is not installed')
    cell = dict(extra={'lesson': dict(prediction='one', confidence=confidence)}, outputs=[dict(output_type='stream', text='two' if wrong else 'one')])
    r = subprocess.run([node, '-e', HARNESS, str(ROOT/'leela/blocks/nb/cells.js'), str(ROOT/'leela/blocks/nb/lesson.js'), json.dumps([cell])], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    text = json.loads(r.stdout.strip().splitlines()[-1])[0]
    assert ('You were sure, and it went another way. That is the part worth a look.' in text) == (wrong and confidence is not None and confidence >= 60)

DRAW_HARNESS = r'''
const vm = require('vm'), fs = require('fs');
const ctx = {console, CSS: {escape: s => s}}; ctx.window = ctx; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8').match(/const stripAnsi = .*;/)[0], ctx);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), ctx);
const result = [];
for (const change of [{}, {cell_type: 'markdown'}, {extra: {}}, {execution_count: 2}, {stale: true}, {running: true}, {outputs: []}, {badgeStale: true}]) {
  const c = {id: 'code', cell_type: 'code', execution_count: 1,
    extra: {lesson: {prediction: '<img onerror=bad>', for_count: 1}}, outputs: [{output_type: 'stream', text: '<script>bad</script>'}], ...change};
  let el = null, removed = false, hooks = 0;
  ctx.$ = selector => selector.startsWith('.lee-cell') ? {} : selector === '.lee-reveal' ? {remove: () => { removed = true; }}
    : selector.startsWith('#state-') ? {classList: {contains: () => !!change.badgeStale}} : {after: e => { el = e; }};
  ctx.document = {createElement: () => new Proxy({}, {set(obj, prop, value) {
    if (prop === 'innerHTML') throw Error('user text must not use innerHTML'); obj[prop] = value; return true;
  }})};
  ctx.lessonRevealActions = () => { hooks++; }; ctx.lee = {path: ''}; ctx.lessonFiling = () => {};
  ctx.renderLessonReveal(c);
  result.push({removed, hooks, text: el?.textContent || '', className: el?.className || ''});
}
console.log(JSON.stringify(result));
'''

def test_reveal_gates_replace_old_reveal_and_use_text_content():
    node = shutil.which('node')
    if not node: pytest.skip('node is not installed')
    r = subprocess.run([node, '-e', DRAW_HARNESS, str(ROOT/'leela/blocks/nb/cells.js'), str(ROOT/'leela/blocks/nb/lesson.js')], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    rows = json.loads(r.stdout.strip().splitlines()[-1])
    assert rows[0] == dict(removed=True, hooks=1, text='You wrote <img onerror=bad>. It printed <script>bad</script>.', className='lee-reveal')
    assert rows[1:] == [dict(removed=True, hooks=0, text='', className='')]*7
