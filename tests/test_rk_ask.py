import json, re, shutil, subprocess
from pathlib import Path
import pytest

ROOT = Path(__file__).parents[1]/'leela'
LESSON = ROOT/'blocks'/'nb'/'lesson.js'
HARNESS = r'''
const vm = require('vm'), fs = require('fs');
const [file, cfg] = [process.argv[1], JSON.parse(process.argv[2])];
const log = [], prompt = {value: cfg.typed || ''};
const cell = {dataset: {id: 'c2'}, matches: s => s === '.lee-cell[data-id]'}, host = {classList: {contains: c => c === 'lee-rupaka'}};
const ctx = {console, Map, Set, JSON, Math, Object, String, Promise,
  lee: {cells: [{id: 'c1', cell_type: 'code'}, {id: 'c2', cell_type: cfg.lesson ? 'markdown' : 'code', extra: cfg.lesson ? {lesson: {}} : {}}], path: '/w/demo.ipynb', agentBusy: !!cfg.busy},
  $: s => s === '#agentprompt' ? prompt : null, status: (t, k) => log.push(['status', t, k]), leeAct: a => log.push(['act', a]),
  sendAgent: () => log.push(['send', prompt.value]), inputDialog: () => { throw new Error('no dialog for an ask'); }, isExercise: () => false};
ctx.globalThis = ctx; ctx.window = ctx; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(file, 'utf8'), ctx);
ctx.lessonGuide = (id, picked, said) => log.push(['guide', id, said]);
let prevented = false;
const e = {detail: {demo: 'halves', text: cfg.text, step: 2, state: {t: 1.5}}, composedPath: () => [{}, host, cell], preventDefault: () => { prevented = true; }};
ctx.lessonAsk(e);
console.log(JSON.stringify({prevented, log}));
'''

def ask(**cfg):
    node = shutil.which('node')
    if not node: pytest.skip('node is not installed')
    r = subprocess.run([node, '-e', HARNESS, str(LESSON), json.dumps(cfg)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)

def test_an_ask_from_a_notebook_demo_goes_to_the_agent_with_the_cell():
    "rupaka 0.0.14's `rk-ask` had no listener in Leela, so every demo said 'No tutor is on this page'."
    r = ask(text='Why does it fall?')
    assert r['prevented'] and ['act', 'focus_agent'] in r['log']
    assert ['send', 'About cell 2 of demo.ipynb, the demo "halves", step 2, values t = 1.5: Why does it fall?'] in r['log']

def test_an_ask_in_a_lesson_goes_to_the_screen_guide_with_no_dialog():
    r = ask(text='', lesson=True)
    assert r['prevented'] and r['log'] == [['guide', 'c2', 'I don\'t get this demo. (the demo "halves", step 2, values t = 1.5)']]

@pytest.mark.parametrize('cfg,said', [(dict(busy=True), 'The agent is working. Ask again when it finishes.'),
                                      (dict(typed='half done'), 'Send or clear your message to the agent first.')])
def test_an_ask_that_cannot_go_is_not_taken(cfg, said):
    "Not taken, so rupaka does not say the ask was sent."
    r = ask(text='x', **cfg)
    assert not r['prevented'] and ['status', said, 'err'] in r['log'] and not any(x[0] == 'send' for x in r['log'])

def test_present_mode_and_the_audience_window_mount_with_no_ask_control():
    "A room has no tutor: the presenter copy, the audience copy and a revived demo all mount with `askable: false`."
    present, slides, core = [(ROOT/p).read_text() for p in ('blocks/nb/present.js', 'blocks/nb/slides.js', 'static/js/core.js')]
    assert 'rupakaDraw(spec, null, null, null, {askable: false})' in present
    assert 'window.Rupaka.mount(inner, spec, {askable: false})' in slides
    assert 'Rupaka.mount(e.inner, e.spec, e.opts)' in core and 'window.Rupaka.mount(inner, spec, opts)' in core
    built = (ROOT/'static'/'lee-core.js').read_text()
    assert "addEventListener('rk-ask', lessonAsk)" in built and '{askable: false}' in built
