"Calm mode: the agent pane shows only text, and each stretch of activity between two text chunks is one closed group."
import asyncio, json, shutil, subprocess
from pathlib import Path
import pytest

MEDIA = Path(__file__).parents[1]/'leela'/'blocks'/'agent'/'media.js'
SHOTS = Path(__file__).parents[1]/'target'/'calm'

HARNESS = r'''
const vm = require('vm'), fs = require('fs');
const ctx = {console, Map, Set, JSON, Math}; ctx.window = ctx; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
console.log(JSON.stringify(JSON.parse(process.argv[2]).map(parts => ctx.calmSummary(parts))));
'''

def call(kind='view', done=True, ok=True, path=None): return dict(kind=kind, done=done, ok=ok, args={'path': path} if path else {})

def summaries(cases):
    node = shutil.which('node')
    if not node: pytest.skip('node is not installed')
    r = subprocess.run([node, '-e', HARNESS, str(MEDIA), json.dumps(cases)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])

def test_calm_summary_counts_calls_files_and_subagents():
    cases = [
        [call(), call(), call(), call('run'), call('edit', path='a.py'), call('edit', path='b.py'), call('delegate')],
        [call()],
        [call('edit', path='a.py')],
        [call('edit', path='a.py'), call('edit', path='a.py')],
        [call(), call('run', ok=False), call('edit', ok=False, path='a.py')],
        [call(), call(done=False)],
        [call('delegate'), call('delegate')],
        [call('run', done=False, ok=False), call('run', ok=False)],
        [],
    ]
    assert summaries(cases) == [
        '7 tool calls · 2 files changed · 1 sub-agent', '1 tool call', '1 tool call · 1 file changed',
        '2 tool calls · 1 file changed', '3 tool calls · 2 failed', 'working · 2 tool calls', '2 tool calls · 2 sub-agents',
        'working · 2 tool calls · 1 failed', ''], summaries(cases)

def test_calm_is_off_by_default():
    from leela.blocks.settings.settings import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS['agent']['calm'] is False


slow = pytest.mark.slow
LIVE = r"""calm => {
  lee.prefs = {agent: {calm}}; window.post = async () => ({ok: true});
  leePane('right', true); leeRight('agent');
  const log = $('#agentlog'); log.innerHTML = '';
  const card = agentTurnCard({prompt: 'tidy the module'}); turnBody(card).appendChild(userMessage('tidy the module')); log.appendChild(card);
  const root = document.createElement('div'); root.className = 'lee-agent-timeline'; turnBody(card).appendChild(root);
  const t = agentTimeline(root, agentCalm()); lee.agentTimeline = t;
  t.chunk('I will read the module first.');
  for (const [id, tool, kind] of [['a', 'read', 'view'], ['b', 'grep', 'search'], ['c', 'edit_file', 'edit']]) {
    const a = {action_id: id, tool, kind, summary: `${tool} m.py`, args: {path: 'm.py'}};
    t.activity({...a, done: false}); t.activity({...a, done: true, ok: true, secs: 0.2, detail: 'ok'});
  }
  t.seal(); showApproval({id: 'ap1', tool: 'run_python', args: {code: 'print(1)'}, schemas: []}, root);
  t.chunk('provider error: rate limited'); t.seal(); t.end();
  const g = [...root.querySelectorAll(':scope > .lee-activity-group')];
  return {groups: g.length, open: g.map(x => x.open), inside: g.map(x => x.querySelectorAll('.lee-agent-step').length),
    summary: g[0]?.querySelector('.lee-activity-count')?.textContent || '',
    bare: root.querySelectorAll(':scope > details.lee-agent-step').length,
    approval: !!root.querySelector(':scope > .lee-approval'), error: [...root.querySelectorAll(':scope > .lee-timeline-prose')].map(p => p._text)};
}"""

HISTORY = r"""calm => {
  lee.prefs = {agent: {calm}};
  const log = $('#agentlog'); log.innerHTML = '';
  const act = (id, done) => ({event: 'activity', data: {action_id: id, tool: 'read', kind: 'view', summary: 'read m.py', args: {path: 'm.py'}, done, ok: done}});
  const timeline = [{event: 'chunk', data: {text: 'Reading.'}}, act('a', false), act('a', true), act('b', true), act('c', true), {event: 'chunk', data: {text: 'Done.'}}];
  renderTurns(log, [{prompt: 'p', model: 'm', timeline, reply: 'Reading.Done.'}], 'conversation', false);
  const g = [...log.querySelectorAll('.lee-activity-group')];
  return {groups: g.length, open: g.map(x => x.open), inside: g.map(x => x.querySelectorAll('.lee-agent-step').length),
    bare: log.querySelectorAll('.lee-agent-timeline > details.lee-agent-step').length};
}"""

@slow
@pytest.mark.parametrize('calm', [True, False])
def test_calm_groups_a_stretch_of_activity_and_leaves_the_rest_visible(tmp_path, calm):
    pytest.importorskip('playwright.async_api')
    from test_completion_caret_slow import _real_page
    async def go(pg):
        hist = await pg.evaluate(HISTORY, calm)
        live = await pg.evaluate(LIVE, calm)
        SHOTS.mkdir(parents=True, exist_ok=True)
        await pg.evaluate("() => { $('#agentlog').scrollTop = 0; }")
        await pg.locator('.lee-agent').first.screenshot(path=str(SHOTS/f"agent-calm-{'on' if calm else 'off'}.png"))
        return hist, live
    hist, live = asyncio.run(_real_page(go, tmp_path))
    if calm:
        assert hist == dict(groups=1, open=[False], inside=[3], bare=0), hist
        assert live['groups'] == 1 and live['open'] == [False] and live['inside'] == [3] and live['bare'] == 0, live
        assert live['summary'] == '3 tool calls · 1 file changed', live
    else:
        assert hist['groups'] == 0 and hist['bare'] == 3, hist
        assert live['groups'] == 0 and live['bare'] == 3, live
    assert live['approval'] and live['error'][-1] == 'provider error: rate limited', live

@slow
def test_calm_command_toggles_without_sending_a_turn_and_waits_out_a_running_turn(tmp_path):
    pytest.importorskip('playwright.async_api')
    from test_completion_caret_slow import _real_page
    async def go(pg):
        return await pg.evaluate(r"""async () => {
          window.post = async (u, b) => { (window._posts ||= []).push(u); return {ok: true}; };
          lee.prefs = {agent: {}}; leePane('right', true); leeRight('agent');
          const log = $('#agentlog'), prompt = $('#agentprompt'), out = {};
          const say = async q => { prompt.value = q; await sendAgent(); };
          await say('/calm on'); out.on = [agentCalm(), prompt.value];
          await say('/calm off'); out.off = [agentCalm()];
          log.insertAdjacentHTML('beforeend', '<div id="mark">kept</div>'); lee.agentBusy = true;
          await say('/calm'); out.busy = [agentCalm(), !!$('#mark'), prompt.value];
          lee.agentBusy = false; out.posts = (window._posts || []).filter(u => u === '/agent/turn' || u === '/agent/steer');
          return out;
        }""")
    got = asyncio.run(_real_page(go, tmp_path))
    assert got['on'] == [True, ''] and got['off'] == [False], got
    assert got['busy'] == [True, True, ''] and got['posts'] == [], got