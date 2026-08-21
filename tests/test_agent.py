"The agent: tools, briefing, context window, routing and budgets."

import threading
import time
import pytest
from leela.agent import agent as activity, agent as hitl, agent as fastllm_hitl
from leela.agent import core as models, runtime as compact, tools as skills
from leela.agent.runtime import Backend, Usage
from leela.agent.agent import Agent, prompt_directives, tool_plan
from leela.agent.tools import Registry, load
from leela.agent.tools import NullHost
from leela.agent.tools import WRITE_TOOLS, tools_for
from fastcore.all import first
from leela.agent.agent import RULES, project_context, system_prompt, work_rules
from leela.agent.testing import MemHost
from leela.agent.tools import (ERR, clip, clip_lines, err, failed, file_tools,
                               code_tools, shell_tools)
import sys
from fastcore.all import Path
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.workspace import Workspace
ROOT = Path(__file__).resolve().parents[1]
import os
from leela.agent.runtime import Compactor, RESERVE, threshold
from leela.agent.core import DFLT_LOCAL_CTX, env, local_ctx, resolve
from leela.agent.runtime import captured, interesting
from leela.agent.runtime import capture as native_capture
from leela.workspace import STEP_RANGE, TOOL_RANGE, budget_value, ws_path
import json
from leela.blocks.agent.models import delete_model,load_models,save_model
from leela.blocks.fs.fs import Sandbox
from leela.blocks.search.search import Search
from leela.agent.agent import Completer

class MemHost_agent(NullHost):
    "A host whose folders live in a dict, so file tools can be driven without touching disk."
    def __init__(self, files=None, root='/proj'):
        super().__init__([root])
        self.files, self.root = dict(files or {}), root
        self.ran = []
    def check(self, path, must_exist=False):
        from pathlib import Path
        p = Path(path)
        return p if p.is_absolute() else Path(self.root)/p
    def walk(self): return list(self.files)
    def read(self, path): return self.files.get(str(path))
    def text_at(self, path): return self.files.get(str(path), '')
    def write(self, path, text):
        self.files[str(path)] = text
        return str(path)
    def search(self, query, limit=20):
        from leela.agent.tools import Hit
        return [Hit(p, 1, '', t.splitlines()[0]) for p, t in self.files.items() if query in t][:limit]
    @property
    def search_note(self): return 'memory'
    def run_python(self, code):
        self.ran.append(code)
        return 'ok'

class FakeBackend(Backend):
    "A backend over a scripted list of replies, so a turn can be driven with no model at all."
    kind = 'fake'
    def __init__(self, spec, replies=(), **kw):
        super().__init__(spec, **kw)
        self.replies, self.sent, self.hist_ = list(replies), [], []
        self.spawned = []
    def _start(self): return self
    def _close(self): pass
    def _send(self, msg, **kw):
        self.sent.append(msg)
        self.hist_.append({'role': 'user', 'content': str(msg)})
        out = self.replies.pop(0) if self.replies else '(done)'
        self.hist_.append({'role': 'assistant', 'content': out})
        return out
    def _stream(self, msg, **kw):
        for w in self._send(msg, **kw).split(' '): yield w + ' '
    def _oneshot(self, prompt, sp, max_tokens): return f'ONESHOT:{prompt[:40]}'
    def _usage(self): return Usage(model=self.spec.model_id, input=10, output=5, total=15, turns=1)
    @property
    def hist(self): return self.hist_
    def _replace_hist(self, summary, keep):
        self.hist_ = [{'role': 'user', 'content': summary}] + list(keep)
    def _refresh(self): self.refreshed = getattr(self, 'refreshed', 0) + 1
    def spawn(self, sp='', tools=(), **kw):
        s = FakeBackend(self.spec, replies=['sub answer'], sp=sp, tools=tools, shared=True)
        self.spawned.append(s)
        return s

@pytest.fixture
def spec(): return models.ModelSpec('fake', 'fake', 'fake/model', ctx=1000)

def fake_agent(host=None, replies=(), **kw):
    "An `Agent` whose every job routes to one `FakeBackend`."
    a = Agent(host or MemHost_agent({'/proj/a.py': 'def a(): pass\n'}), extensions=False, **kw)
    be = FakeBackend(models.ModelSpec('fake', 'fake', 'fake/model', ctx=1000), replies=replies)
    a._be = lambda job='turn': be
    a._be_or_none = lambda job='turn': be
    return a, be

def test_agent_package_does_not_import_leela():
    "The harness lives inside leela now, but it must still not reach back into the IDE."
    import pathlib, re
    import leela.agent as pkg
    bad = []
    for p in pathlib.Path(pkg.__file__).parent.glob('*.py'):
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if re.match(r'\s*(from|import)\s+leela\b', line): bad.append(f'{p.name}:{i}: {line.strip()}')
            if re.match(r'\s*from\s+\.\.', line): bad.append(f'{p.name}:{i}: {line.strip()}')
    assert not bad, 'leela.agent must not import from leela:\n' + '\n'.join(bad)

def test_a_host_offers_only_the_tools_it_supports():
    from leela.agent.tools import read_only
    from leela.blocks.agent.ai import WorkspaceHost
    names = {t.__name__ for t in tools_for(NullHost(['/x']))}
    assert 'search_code' in names and 'view_file' in names
    assert 'run_python' not in names and 'notebook_cells' not in names
    names = {t.__name__ for t in tools_for(MemHost_agent())}
    assert 'run_python' not in names
    from ramabana.git import GIT_WRITE_TOOLS
    assert {'edit_file', 'replace_text', 'create_file', 'edit_cell', 'add_cell', 'run_python',
            'run_shell', 'memory_forget', 'create_skill',
            'cancel_watch', 'cart_add', 'cart_remove'} | GIT_WRITE_TOOLS == set(WRITE_TOOLS)
    a, _ = fake_agent()
    names = {t.__name__ for t in read_only(a.tools)}
    assert not (names & WRITE_TOOLS)
    assert 'search_code' in names
    h = WorkspaceHost(Workspace(roots=[]))
    with pytest.raises(NotImplementedError): h.run_python('1')
    assert 'run_python' not in {t.__name__ for t in tools_for(h)}
    assert 'run_shell' not in named(tools_for(NullHost(['/x'])))
    h = MemHost()
    assert 'run_shell' in named(tools_for(h))
    assert h.cmds == []


def test_cheap_jobs_stay_local_when_the_turn_goes_to_the_cloud(monkeypatch):
    "The whole argument for routing: pointing the turn at a frontier model must not move completions."
    monkeypatch.delenv('LEELA_MODEL', raising=False)
    r = models.Routing(turn='gemma-e2b')
    r.set('gemma-12b')
    assert r.spec('turn').name == 'gemma-12b'
    for job, name in models.DEFAULT_POLICY.items():
        if job == 'turn': continue
        assert r.spec(job).name == (name or models.DFLT_LOCAL), job
        assert r.spec(job).local, job

def test_env_overrides_a_single_job(monkeypatch):
    monkeypatch.setenv('LEELA_MODEL_SUMMARY', 'gemma-12b')
    r = models.Routing(turn='gemma-e2b')
    assert r.spec('summary').name == 'gemma-12b'
    assert r.spec('classify').name == models.DFLT_LOCAL, 'the other cheap jobs stay put'

def test_a_model_spec_resolves_or_says_why_not():
    from leela.agent.runtime import FastllmBackend, MAX_STEPS, RishiBackend
    with pytest.raises(KeyError): models.resolve('sonnnet')
    s = models.resolve('somevendor/some-model')
    assert (s.backend, s.model_id) == ('remote', 'somevendor/some-model')
    assert s.ctx > 0
    local = models.ModelSpec('local', 'rishi', 'local/model', ctx=1000)
    cloud = models.ModelSpec('cloud', 'fastllm', 'cloud/model', ctx=1000)
    assert RishiBackend(local).max_steps == MAX_STEPS
    assert FastllmBackend(cloud).max_steps == MAX_STEPS
    with pytest.raises(KeyError): Registry().on('after_lunch', lambda: None)
    a, _ = fake_agent()
    assert {'model', 'cost', 'compact', 'skills', 'tools', 'reload'} <= set(a.commands())
    assert a.command('nonsense') is None
    assert 'tok' in a.command('cost') or a.command('cost') is not None
    a, _ = fake_agent()
    out = a.command('model')
    for job in models.JOBS: assert job in out


def test_backend_refresh_updates_sp_and_tools_in_place(spec):
    "A running backend keeps its engine and conversation; only the briefing and tools change."
    be = FakeBackend(spec, sp='old', tools=[])
    be.start()
    hist_before = be.hist
    be.refresh('new briefing', [lambda: None])
    assert be.sp == 'new briefing' and len(be.tools) == 1
    assert be.refreshed == 1
    assert be.chat is be
    assert be.hist is hist_before

def test_backend_refresh_before_start_only_records(spec):
    "Refreshing a backend that never started just stores the values for its eventual start."
    be = FakeBackend(spec, sp='old')
    be.refresh('new', [])
    assert be.sp == 'new' and not hasattr(be, 'refreshed')


def test_agent_refresh_rebriefs_a_running_turn_backend():
    "Opening a folder reaches the live conversation: the briefing names it, without a reload."
    host = MemHost_agent({'/proj/a.py': 'def a(): pass\n'})
    a = Agent(host, extensions=False, subagents=False)
    spec = a.routing.spec('turn')
    be = FakeBackend(spec, sp=a.system_prompt(), tools=a.tools)
    be.start()
    a._backends[(spec.backend, spec.model_id)] = be
    assert '/proj' in be.sp and '/newproj' not in be.sp
    host._roots.append('/newproj')
    a.refresh()
    assert be.chat is be and be.refreshed == 1
    assert '/newproj' in be.sp
    assert a._skills is not None and a._tools is not None

def test_a_turn_records_its_activity_usage_and_changes():
    from leela.core.web import sse as _sse
    a = Agent(MemHost_agent(), extensions=False, subagents=False)
    _ = a.tools
    a.refresh()
    assert a._tools is None
    a, be = fake_agent(replies=['done'])
    assert a.ask('hello') == 'done'
    assert a.use.total == 15
    assert be.sent and 'hello' in str(be.sent[0])
    before = Usage(model='m', input=10, output=4, total=14, cost=.01, turns=1)
    after = Usage(model='m', input=18, output=7, total=25, cost=.016, turns=2)
    delta = after - before
    assert (delta.input, delta.output, delta.total, round(delta.cost, 3), delta.turns) == (8, 3, 11, .006, 1)
    u = Usage(model='a', input=1, output=2, total=3, cost=0.5) + Usage(model='b', input=1, output=1, total=2, cost=0.25)
    assert (u.total, u.cost, u.model) == (5, 0.75, 'b')
    assert '$0.75' in repr(u)
    a, be = fake_agent(replies=['all done'])
    out = ''.join(a.stream('go'))
    assert out.strip() == 'all done'
    assert a.use.total == 15
    f = _sse('chunk', {'text': 'line one\nline two'})
    assert f.count('\n\n') == 1 and f.startswith('event: chunk\ndata: ')
    a = agent_on(MemHost(commands={'pytest': (0, '5 passed')}))
    named(a.tools)['run_shell']('pytest')
    assert a.activity.rows()[-1]['ok'] is True
    h = MemHost({'/proj/m.py': SRC})
    a = agent_on(h)
    named(a.tools)['replace_text']('/proj/m.py', '[{"oldText": "a + b", "newText": "a * b"}]')
    before, after = a.changes()['/proj/m.py']
    assert 'a + b' in before and 'a * b' in after
    h = MemHost({'/proj/m.py': SRC})
    a = agent_on(h)
    named(a.tools)['replace_text']('/proj/m.py', '[{"oldText": "nope", "newText": "x"}]')
    assert a.changes() == {}


def test_the_briefing_says_what_is_true_of_this_project():
    from leela.blocks.agent.ai import STATE_TEMPLATE
    for heading in ('Agent charter', 'Hard boundaries', 'Routing rules', 'Tool practices',
                    'Verification', 'Progress', 'Critical context', 'State maintenance'):
        assert heading in STATE_TEMPLATE
    assert 'Update this state after' in STATE_TEMPLATE
    everything = work_rules()
    assert 'run_shell' in everything and 'grep' in everything
    narrow = work_rules({'search_code', 'view_file'})
    assert 'run_shell' not in narrow and 'delegate_parallel' not in narrow
    assert 'search_code' in narrow
    narrow = work_rules({'view_file'})
    assert 'unless a tool\n  result in this conversation says so' in narrow
    assert 'ERROR:' in narrow
    assert 'inside the folders above' in narrow
    real = {t.__name__ for t in tools_for(MemHost())} | {'notebook_cells', 'delegate_parallel',
                                                         'memory_search', 'web_search', 'run_python',
                                                         'read_skill'}   # only present with `get_skills`
    assert {tool for tool, _ in RULES if tool} <= real
    h = MemHost({'/proj/AGENTS.md': '# House rules\n\nUse uv, never pip.\n'})
    ctx = project_context(h)
    assert 'Use uv, never pip' in ctx and '/proj/AGENTS.md' in ctx
    assert 'Use uv, never pip' in system_prompt(h, tools=tools_for(h))
    h = MemHost({'/proj/AGENTS.md': 'rule\n' + 'filler\n' * 5000})
    ctx = project_context(h, mx=200)
    assert 'rule' in ctx and 'truncated' in ctx and len(ctx) < 900
    assert project_context(MemHost()) == ''
    assert '<project_context>' not in system_prompt(MemHost(), tools=tools_for(MemHost()))
    sp = system_prompt(MemHost(), tools=tools_for(MemHost()))
    assert '/proj' in sp
    h = MemHost({'/proj/AGENTS.md': 'Use uv, never pip.\n'})
    a = agent_on(h)
    sp = a.system_prompt()
    assert 'run_shell' in sp and 'Use uv, never pip' in sp
    assert 'scale_numeric' not in sp


def test_directed_checkpoint_can_rewrite_the_live_tool_call():
    from leela.blocks.agent.ai import Interventions
    ap = Interventions(tools={'edit_file'}, mode='ask', control='directed', timeout=2)
    stop = ap.listen()
    tc = {'function': {'name': 'search_code', 'arguments': {'query': 'old'}}}
    def rewrite():
        for _ in range(200):
            if ap.pending is not None:
                return ap.answer(ap.pending.id, True, 'look here instead',
                                 tool='view_file', args={'path': 'README.md'})
            time.sleep(.005)
    threading.Thread(target=rewrite, daemon=True).start()
    try: decision = ap.gate(tc)
    finally: stop()
    assert decision and decision.edited
    assert tc['function'] == {'name': 'view_file', 'arguments': {'path': 'README.md'}}
    assert decision.reply() == 'Approved by the user. Note from the user: look here instead'

def test_queued_steering_interrupts_a_pending_checkpoint():
    from leela.blocks.agent.ai import Interventions
    ap = Interventions(tools={'edit_file'}, mode='ask', control='directed', timeout=2)
    stop = ap.listen(); tc = {'id': 'call_edit', 'function': {'name': 'edit_file', 'arguments': {'path': 'a.py'}}}
    def steer():
        for _ in range(200):
            if ap.pending is not None: return ap.queue_steer('inspect the failing test first')
            time.sleep(.005)
    threading.Thread(target=steer, daemon=True).start()
    try: assert ap.gate(tc)
    finally: stop()
    assert tc['function']['name'] == 'user_steering'
    assert 'inspect the failing test first' in tc['function']['arguments']['instruction']
    assert ap.state()['queued_steer'] == ''

def test_rejection_ignores_rewritten_or_malformed_call_fields():
    from leela.blocks.agent.ai import Interventions
    ap = Interventions(tools={'edit_file'}, mode='ask', control='directed')
    from leela.blocks.agent.ai import Intervention
    pending = Intervention(tool='edit_file', args={'path': 'original.py', 'commands': '[]'},
                           summary='edit_file → original.py')
    ap.current = pending
    resolved = ap.answer(pending.id, False, 'use the notebook instead',
                         tool='create_file', args={})
    assert not resolved
    assert resolved.tool == 'edit_file'
    assert resolved.args == {'path': 'original.py', 'commands': '[]'}
    assert resolved.note == 'use the notebook instead'

def test_a_steer_no_tool_call_consumed_rides_the_next_turn(tmp_path):
    "Queued while the model was writing its answer, it waited for a tool call that never came."
    ws = Workspace(roots=[tmp_path], approvals='auto')
    ws.approvals.queue_steer('use the notebook, not the script')
    out = ws.ai._steered('carry on')
    assert out == 'carry on\n\nUser steering: use the notebook, not the script'
    assert ws.approvals.state()['queued_steer'] == '', 'and it is not delivered twice'
    assert ws.ai._steered('carry on') == 'carry on'

def test_a_steer_survives_a_turn_it_cannot_ride(tmp_path):
    "A multimodal prompt keeps the steer queued rather than dropping it."
    ws = Workspace(roots=[tmp_path], approvals='auto')
    ws.approvals.queue_steer('check the fixture first')
    parts = [{'type': 'text', 'text': 'look'}]
    assert ws.ai._steered(parts) is parts
    assert ws.approvals.state()['queued_steer'] == 'check the fixture first'

def test_a_steer_lands_on_a_tool_call_that_carries_no_id():
    "A local model's tool call often has no `id`, and the steer used to be dropped for those."
    from leela.blocks.agent.ai import Interventions
    ap = Interventions(tools={'edit_file'}, mode='ask', control='directed', timeout=2)
    stop = ap.listen(); tc = {'function': {'name': 'edit_file', 'arguments': {'path': 'a.py'}}}
    def steer():
        for _ in range(200):
            if ap.pending is not None: return ap.queue_steer('read the test first')
            time.sleep(.005)
    threading.Thread(target=steer, daemon=True).start()
    try: assert ap.gate(tc)
    finally: stop()
    assert tc['function']['name'] == 'user_steering'
    assert 'read the test first' in tc['function']['arguments']['instruction']

@pytest.mark.parametrize('note', ['', 'edit the notebook source instead'])
def test_refusal_becomes_a_do_not_retry_tool_result_with_optional_direction(note):
    from leela.blocks.agent.ai import Interventions
    ap = Interventions(tools={'edit_file'}, mode='ask', control='directed', timeout=2)
    stop = ap.listen(); tc = {'id': 'call_edit', 'function': {'name': 'edit_file', 'arguments': {'path': 'a.py'}}}
    def refuse():
        for _ in range(200):
            if ap.pending is not None: return ap.answer(ap.pending.id, False, note)
            time.sleep(.005)
    threading.Thread(target=refuse, daemon=True).start()
    try: decision = ap.gate(tc)
    finally: stop()
    assert decision is True
    assert tc['function']['name'] == 'user_steering'
    instruction = tc['function']['arguments']['instruction']
    assert 'user rejected' in instruction.lower() and 'Do not retry' in instruction
    assert (note in instruction) if note else ('User direction:' not in instruction)

def test_control_levels_checkpoint_only_the_expected_tools():
    from leela.blocks.agent.ai import Interventions
    auto = Interventions(tools={'edit_file'}, mode='ask', control='autopilot')
    assert auto.request('search_code', {'query': 'x'})
    assert not auto.history[-1].edited
    guided = Interventions(tools={'edit_file'}, mode='ask', control='guided')
    assert not guided.request('read_url', {'url': 'https://example.com'})
    assert 'nothing is listening' in guided.history[-1].note

def test_run_until_write_bypasses_reads_then_stops_at_the_write():
    from leela.blocks.agent.ai import Interventions
    ap = Interventions(tools={'edit_file'}, mode='ask', control='directed')
    ap.set_run_policy('until_write')
    assert ap.request('search_code', {'query': 'x'})
    assert ap.run_policy == {'kind': 'until_write'}
    denied = ap.request('edit_file', {'path': 'a.py', 'commands': '[]'})
    assert not denied and ap.run_policy is None
    assert 'nothing is listening' in denied.note

def test_count_and_until_failure_policies_have_explicit_stop_conditions():
    from leela.blocks.agent.ai import Interventions
    ap = Interventions(control='directed')
    ap.set_run_policy('count', 2)
    assert ap.request('search_code', {'query': 'one'})
    assert ap.request('view_file', {'path': 'a.py'})
    assert ap.run_policy is None
    ap.set_run_policy('until_failure')
    assert ap.request('search_code', {'query': 'two'})
    ap.observe_result(False)
    assert ap.run_policy is None and ap.pause_next

def test_approved_notebook_call_passes_only_activity_identity_metadata(tmp_path):
    from leela.blocks.nb.nb import Cell, Notebook
    p = tmp_path/'sample.ipynb'; Notebook([Cell(source='x = 1')]).save(p)
    ws = Workspace(roots=[tmp_path], approvals='auto'); a = ws.ai
    a.approvals.control = 'autopilot'
    tool = next(t for t in a.tools if t.__name__ == 'notebook_cells')
    tc = {'id': 'call_notebook', 'function': {'name': 'notebook_cells', 'arguments': {'path': str(p)}}}
    assert a.approvals.gate(tc)
    out = tool(path=str(p))
    assert 'x = 1' in out
    row = a.activity.rows()[-1]
    assert row['action_id'] == 'call_notebook' and row['tool'] == 'notebook_cells'

def test_queued_steering_runs_the_current_tool_and_reaches_the_next_decision(tmp_path):
    ws = Workspace(roots=[tmp_path], approvals='auto')
    ws.approvals.queue_steer('inspect the failing test before editing')
    tool = next(t for t in ws.ai.tools if t.__name__ == 'list_files')
    out = tool('')
    assert 'inspect the failing test before editing' in out
    assert ws.approvals.state()['queued_steer'] == ''

def test_workspace_repo_writes_are_opt_in_and_persisted(tmp_path):
    first, second = tmp_path/'one', tmp_path/'two'
    first.mkdir(); second.mkdir()
    ws = Workspace(roots=[first, second])
    tool = next(t for t in ws.ai.tools if t.__name__ == 'create_file')
    assert 'another workspace repository' in tool(path=str(second/'blocked.py'), text='x = 1\n')
    ws.allow_workspace_repo_writes = True
    assert 'wrote' in tool(path=str(second/'allowed.py'), text='x = 1\n')
    ws.save()
    assert Workspace.load(ws_path()).allow_workspace_repo_writes

def test_subagent_writes_are_opt_in_persisted_and_reach_the_assistant(tmp_path):
    "The checkbox is the front of it; the setting has to survive a restart and reach the `Agent`."
    from ramabana.tools import WRITE_TOOLS, read_only
    ws = Workspace(roots=[tmp_path])
    assert ws.subagent_writes is False and ws.ai.subagent_writes is False
    assert not ({t.__name__ for t in read_only(ws.ai.tools)} & WRITE_TOOLS)

    ws.ai.set_subagent_writes(True)
    assert 'create_file' in {t.__name__ for t in read_only(ws.ai.tools, writes=True)}
    # A writing sub-agent gets the turn model's recorded list, so its edits reach `calls`,
    # `Activity` and the before-images -- but never leela's Git writes, which are refused to
    # delegation whatever the toggle says. This used to be the identical list, git_push included.
    from leela.blocks.agent.ai import GIT_WRITE_TOOLS
    sub = {t.__name__ for t in ws.ai._sub_plain()}
    assert 'create_file' in sub, 'writing means the write tools, recorded'
    assert not (sub & GIT_WRITE_TOOLS), 'and pushing is still not delegable'
    assert sub == {t.__name__ for t in ws.ai.tools} - GIT_WRITE_TOOLS, 'nothing else was taken'

    ws.subagent_writes = True; ws.save()
    back = Workspace.load(ws_path(), port=0)
    assert back.subagent_writes and back.ai.subagent_writes


def test_new_agent_setup_keeps_file_and_notebook_access_inside_workspace(tmp_path):
    from leela.blocks.nb.nb import Cell, Notebook
    file = tmp_path/'a.py'; file.write_text('x = 1\n')
    notebook = tmp_path/'a.ipynb'; Notebook([Cell(source='y = 2')]).save(notebook)
    ws = Workspace(roots=[tmp_path], approvals='auto'); tools = {t.__name__: t for t in ws.ai.tools}
    assert 'x = 1' in tools['view_file'](path=str(file))
    cells = tools['notebook_cells'](path=str(notebook)); cell_id = cells.split()[0]
    assert 'y = 2' in tools['view_cell'](path=str(notebook), cell_id=cell_id)
    assert 'wrote' in tools['create_file'](path=str(tmp_path/'created.py'), text='safe = True\n')
    outside = tmp_path.parent/'outside-agent-access.py'
    assert 'outside the open folders' in tools['create_file'](path=str(outside), text='unsafe = True\n')
    assert not outside.exists()

def test_approval_gates_writes_and_carries_its_answer_back():
    from leela.blocks.agent.ai import Interventions
    act = activity.Activity(); act.mark('turn-1')
    row = act.start('search_code', {'query': 'needle'}, action_id='call_exact', branch_id='branch_a')
    assert row.dict()['action_id'] == 'call_exact'
    assert row.dict()['turn_id'] == 'turn-1' and row.dict()['branch_id'] == 'branch_a'
    ap = Interventions(control='guided')
    ap.queue_steer('inspect the existing component first')
    assert ap.state()['queued_steer'] == 'inspect the existing component first'
    assert ap.consume_steer() == 'inspect the existing component first'
    assert ap.consume_steer() == ''
    ap = hitl.Approvals(tools={'edit_file'})
    assert ap.gate({'function': {'name': 'search_code', 'arguments': {'query': 'x'}}})
    ap = hitl.Approvals(tools={'edit_file'}, timeout=30)
    t0 = time.time()
    d = ap.gate({'function': {'name': 'edit_file', 'arguments': {'path': 'a.py'}}})
    assert not d and time.time() - t0 < 1
    assert 'nothing is listening' in d.reply()
    ap = hitl.Approvals(tools={'edit_file'}, mode='ask')
    a = hitl.Ask(tool='edit_file'); ap.current = a
    ap.answer(a.id, False, 'not this file', session=True)
    assert ap.mode == 'ask' and not a
    ap = hitl.Approvals(tools={'edit_file'}, mode='auto')
    d = ap.request('edit_file', {'path': 'a.py'})
    assert d and d.reply() is None
    d2 = hitl.Ask(tool='edit_file').resolve(True, 'keep the docstring')
    assert 'keep the docstring' in d2.reply()
    p = hitl.preview_for('edit_file', {'path': 'a.py', 'commands': '[["12|ab|","s","old","new"]]'})
    assert '12|ab|' in p and 'old' in p and 'new' in p
    p2 = hitl.preview_for('create_file', {'path': 'b.py', 'text': 'x = 1'})
    assert 'new file' in p2 and 'x = 1' in p2
    ap = hitl.Approvals(tools={'edit_file'}, timeout=30)
    stop = ap.listen()
    threading.Thread(target=lambda: (time.sleep(0.05), ap.cancel_all()), daemon=True).start()
    d = ap.gate({'function': {'name': 'edit_file', 'arguments': {}}})
    stop()
    assert not d and 'cancelled' in d.reply()
    assert fastllm_hitl.apply() and fastllm_hitl.applied()
    assert 'rishi.remote' in fastllm_hitl.note()
    assert 'run_shell' in WRITE_TOOLS


def test_file_checkpoint_rolls_back_only_its_unchanged_output():
    from leela.blocks.agent.ai import Interventions
    host = MemHost_agent({'/proj/a.py': 'before'})
    ap = Interventions(tools={'create_file'}, mode='auto', control='autopilot', host=host)
    decision = ap.request('create_file', {'path': '/proj/a.py', 'text': 'after'})
    host.write('/proj/a.py', 'after'); ap.observe_result(True)
    assert decision.dict()['rollback']
    assert ap.rollback(decision.id) == '/proj/a.py'
    assert host.text_at('/proj/a.py') == 'before'
    host.write('/proj/a.py', 'someone else changed it')
    with pytest.raises(ValueError, match='changed after'): ap.rollback(decision.id)


def test_external_request_can_force_a_browser_decision_for_an_unknown_tool():
    ap = hitl.Approvals(tools={'edit_file'}, timeout=5)
    stop = ap.listen()
    def answer():
        for _ in range(200):
            if ap.pending is not None: return ap.answer(ap.pending.id, True)
            time.sleep(0.01)
    threading.Thread(target=answer, daemon=True).start()
    try: d = ap.request('custom_tool', {'value': 1}, force=True)
    finally: stop()
    assert d and d.tool == 'custom_tool'


def test_a_refusal_carries_the_reason_back_to_the_model():
    "The point of the whole module: 'that file is generated' redirects, 'denied' just gets retried."
    ap = hitl.Approvals(tools={'edit_file'}, timeout=5)
    stop = ap.listen()
    out = {}
    def answer():
        for _ in range(200):
            if (a := ap.pending) is not None:
                ap.answer(a.id, False, 'that file is generated, edit the notebook instead')
                return
            time.sleep(0.01)
    threading.Thread(target=answer, daemon=True).start()
    out['d'] = ap.gate({'function': {'name': 'edit_file', 'arguments': {'path': 'gen.py'}}})
    stop()
    assert not out['d']
    assert 'that file is generated' in out['d'].reply()

def test_approve_session_answers_now_and_auto_approves_later_writes():
    ap = hitl.Approvals(tools={'edit_file'}, timeout=5)
    stop = ap.listen()
    def answer():
        for _ in range(200):
            if (a := ap.pending) is not None: return ap.answer(a.id, True, session=True)
            time.sleep(0.01)
    threading.Thread(target=answer, daemon=True).start()
    first = ap.request('edit_file', {'path': 'one.py'})
    stop()
    second = ap.request('edit_file', {'path': 'two.py'})
    assert first and second and ap.mode == 'auto'
    assert 'rest of this session' in first.reply()
    assert second.reply() is None


def test_every_watcher_and_the_recorder_both_hear_it():
    "A second frontend opening must not unhook the notebook recorder, or the first frontend."
    seen = []
    ap = hitl.Approvals(tools={'edit_file'}, mode='auto', on_ask=lambda a: seen.append('recorder'))
    ap.listen(on_ask=lambda a: seen.append('one'))
    ap.listen(on_ask=lambda a: seen.append('two'))
    ap.mode = 'ask'
    def answer():
        for _ in range(200):
            if (a := ap.pending) is not None: return ap.answer(a.id, True)
            time.sleep(0.01)
    threading.Thread(target=answer, daemon=True).start()
    ap.gate({'function': {'name': 'edit_file', 'arguments': {}}})
    assert sorted(seen) == ['one', 'recorder', 'two']


def test_a_workspace_answers_the_whole_host_protocol(tmp_path, monkeypatch):
    "Every capability answered rather than probed or absent. `api` is never probed at all."
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'v.db'))
    from leela.blocks.agent.ai import WorkspaceHost
    (tmp_path/'a.py').write_text('def hello():\n    return 1\n')
    h = WorkspaceHost(Workspace(roots=[tmp_path]))
    assert h.capabilities['api'] and h.capabilities['memory'] and h.capabilities['watch']
    names = set(named(tools_for(h)))
    assert {'api_load', 'api_ops', 'api_call', 'ask_memory', 'poll_watches', 'grep'} <= names
    hits = h.grep('def hello', regex=False)
    assert [(Path(x.path).name, x.line) for x in hits] == [('a.py', 1)], 'ripgrep, not a read per file'
    assert h.grep('DEF HELLO', regex=False) == [], 'a cased ask is not answered case-folded'
    assert h.poll()['ran'] == 0, 'nothing is due, which is an answer rather than a refusal'

def test_reads_may_leave_the_open_folders_only_when_that_is_turned_on(tmp_path, monkeypatch):
    "Confining writes protects what nobody opened; confining reads costs the sibling checkout."
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'v.db'))
    from leela.blocks.agent.ai import WorkspaceHost
    from leela.blocks.fs.fs import Unsafe
    root, outside = tmp_path/'open', tmp_path/'elsewhere'
    root.mkdir(); outside.mkdir()
    (outside/'lib.py').write_text('x = 1\n'); (outside/'.env').write_text('KEY=1\n')
    ws = Workspace(roots=[root])
    h = WorkspaceHost(ws)
    with pytest.raises(Unsafe): h.check(str(outside/'lib.py'), reading=True)
    ws.agent_read_outside = True
    assert h.check(str(outside/'lib.py'), reading=True) == (outside/'lib.py').resolve()
    with pytest.raises(Unsafe): h.check(str(outside/'.env'), reading=True)   # credentials, never
    with pytest.raises(Unsafe): h.check(str(outside/'lib.py'))               # a write is not a read

def test_every_harness_job_can_be_pointed_at_a_model(tmp_path, monkeypatch):
    "`subagent`, `summary`, `classify` and `oneshot` were reachable only through the environment."
    from leela.agent.core import JOBS
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    assert {'subagent', 'summary', 'classify', 'oneshot'} <= set(JOBS)
    ws = Workspace(roots=[tmp_path])
    ws.job_models = {'subagent': 'gemma-e2b'}
    saved = ws.save(tmp_path/'ws.json')
    assert Workspace.load(saved).job_models == {'subagent': 'gemma-e2b'}, 'and it survives a restart'


def test_saved_job_models_are_reapplied_before_each_agent_turn(tmp_path):
    ws = Workspace(roots=[tmp_path])
    ai = ws.ai
    ws.job_models = {'subagent': 'gemma-e2b', 'summary': 'gemma-e4b'}
    ai.ask_with = lambda *args, **kwargs: 'done'
    assert ws.ask('question') == 'done'
    assert ai.routing.name_for('subagent') == 'gemma-e2b'
    assert ai.routing.name_for('summary') == 'gemma-e4b'


def test_a_new_conversation_keeps_every_saved_job_model(tmp_path):
    ws = Workspace(roots=[tmp_path])
    ws.completion_model = 'gemma-e2b'
    ws.job_models = {'oneshot': 'gemma-e2b', 'classify': 'gemma-e4b',
                     'summary': 'gemma-e2b', 'subagent': 'gemma-e4b'}
    old = ws.ai
    with TestClient(ide_app(ws)) as client:
        assert client.post('/agent/new').json()['ok']
    assert ws.ai is not old
    assert ws.ai.routing.name_for('completion') == 'gemma-e2b'
    assert {job: ws.ai.routing.name_for(job) for job in ws.job_models} == ws.job_models

def test_an_agent_harness_is_not_a_pip_extra(monkeypatch):
    "Cursor and Claude Code are runtimes now; the picker told you to `pip install rishi[cursor]`."
    from leela.blocks.agent.models import runtimes
    rows = {r['value']: r for r in runtimes()}
    assert {'cursor', 'claude'} <= set(rows)
    assert rows['cursor']['label'] == 'Cursor agent' and rows['claude']['label'] == 'Claude Code'
    assert 'CLI or SDK' in rows['cursor']['why'] and 'pip install' not in rows['cursor']['why']
    assert 'pip install rishi[mlx]' in rows['mlx']['why']

def test_older_specialized_openai_models_are_opt_in(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'present')
    monkeypatch.setattr(models, '_oai_cache', (float('inf'), ['gpt-4.1', 'gpt-4.1-mini', 'gpt-5']))
    normal = {r['label'] for r in models.available_models() if r['provider'] == 'openai'}
    older = {r['label'] for r in models.available_models(include_legacy=True) if r['provider'] == 'openai'}
    assert 'gpt-5' in normal and 'gpt-4.1' not in normal
    assert {'gpt-4.1', 'gpt-4.1-mini'} <= older

def test_anthropic_key_exposes_fastllms_full_claude_catalog(monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'connected')
    rows = models.available_models()
    anthropic = {r['value'] for r in rows if r['provider'] == 'anthropic'}
    assert 'anthropic/claude-sonnet-4-6' in anthropic
    assert 'anthropic/claude-opus-4-8' in anthropic
    assert all(r['source'] == 'ANTHROPIC_API_KEY' for r in rows if r['provider'] == 'anthropic')

def test_available_models_follow_environment_and_codex_login(monkeypatch, tmp_path):
    auth = tmp_path/'auth.json'
    auth.write_text('{"tokens":{"access_token":"present"}}')
    monkeypatch.setenv('CODEX_AUTH_PATH', str(auth))
    monkeypatch.setenv('OPENAI_API_KEY', 'present')
    monkeypatch.setenv('GEMINI_API_KEY', 'present')
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.setattr(models, '_oai_cache', (float('inf'), []))
    rows = models.available_models()
    providers = {r['provider'] for r in rows}
    assert {'openai', 'codex', 'gemini'} <= providers
    assert any('on device' in r['source'] for r in rows)
    assert 'anthropic' not in providers
    assert any(r['value'].startswith('codex/') for r in rows)
    assert all('present' not in str(r) for r in rows)

def test_skills_are_discovered_and_selected_by_the_prompt():
    from leela.agent.tools import Skill, find
    def research(query: str): return query
    skill = skills.Skill('nbdev', 'md', 'Notebook development', '/skills/nbdev', 'full instructions')
    tools, loaded = prompt_directives(
        'add test cells /research nbdev projects then use /nbdev, not /Users/me', [research], [skill])
    assert tools == [('research', 'nbdev projects then use')]
    assert loaded == [skill]
    assert tool_plan('what default model does leela use?')[0] == 'repo'
    assert tool_plan('where is approval implemented in this repo?')[0] == 'repo'
    assert tool_plan('change the code_clusters method to accept a store')[0] == 'repo'
    assert tool_plan('what do the current pandas release notes say?')[0] == 'web'
    assert tool_plan('what is 2 + 2?')[0] == 'direct'
    found = {s.name: s for s in skills.discover()}
    assert 'exhash' in found, 'exhash ships the editing reference leela used to paste by hand'
    assert found['exhash'].source == 'pyskill'
    assert found['exhash'].text().strip()
    for n in ('coding_patterns', 'theory', 'write_prose', 'write_docs'):   # what AGENTS.md points at
        assert found[n].source == 'pyskill' and found[n].where == f'ramabana.{n}'
        assert 'more chars]' not in found[n].text(), n
    ss = [Skill('editskill', 'pyskill'), Skill('editor', 'pyskill')]
    assert find(ss, 'edit') is None
    assert find(ss, 'editskill').name == 'editskill'
    meta, body = skills.frontmatter('---\nname: x\ndescription: "y z"\n---\nbody\n')
    assert meta == {'name': 'x', 'description': 'y z'} and body.strip() == 'body'


def test_explicit_research_uses_only_the_request_not_composed_notebook_context():
    class ResearchHost(MemHost_agent):
        def __init__(self): super().__init__(); self.queries = []
        def research(self, query): self.queries.append(query); return 'grounded research'
    host = ResearchHost()
    a, be = fake_agent(host=host, replies=['done'], model='sonnet')
    composed = a.compose('add tests /research nbdev test cells', context='<cell>implementation details</cell>',
                         context_path='/proj/nbs/core.ipynb')
    assert a.ask(composed) == 'done'
    assert host.queries == ['nbdev test cells']
    assert '<preflight-tool name="research">' in str(be.sent[-1])
    assert a.history[-1]['plan']['tools'] == ['research']

def test_create_skill_writes_standard_project_skill_without_overwriting():
    host = MemHost_agent()
    create = next(t for t in tools_for(host, lambda: []) if t.__name__ == 'create_skill')
    result = create('notebook-tests', 'How this project tests notebooks', 'Add one red cell, then make it green.')
    path = '/proj/.agents/skills/notebook-tests/SKILL.md'
    assert result.startswith('created ') and path in host.files
    assert 'name: "notebook-tests"' in host.files[path]
    assert 'description: "How this project tests notebooks"' in host.files[path]


def test_the_composer_carries_files_selections_and_notices():
    host = MemHost_agent({'/proj/nbs/core.ipynb': 'code_clusters method'})
    search = next(t for t in tools_for(host) if t.__name__ == 'search_code')
    out = search('code_clusters')
    assert '/proj/nbs/core.ipynb:1' in out
    assert 'use this exact path with notebook_cells, then view_cell/edit_cell' in out
    assert 'clean namespace' in compact.reorient(kernel_alive=False)
    assert compact.prompt_notices('where is this handled?') == [compact.Q_NOTICE]
    assert compact.APPROVAL_NOTICE in compact.prompt_notices('go')
    assert compact.APPROVAL_NOTICE in compact.prompt_notices('ok.')
    assert compact.BTW_NOTICE in compact.prompt_notices('BTW can you also check the tests')
    assert compact.ACTION_NOTICE in compact.prompt_notices('add a test for this')
    assert compact.ACTION_NOTICE in compact.prompt_notices('scale the numeric columns as df_norm')
    assert '<system-reminder>' in compact.notices_block('what does this do?')
    assert compact.ACTION_NOTICE in compact.notices_block('add a test')
    c = Completer(Agent_comple())
    prompt = c._prompt('frame.', 6, 'python', 'def clean(frame):\n    return frame.dropna()')
    assert '<related_code>' in prompt and 'def clean(frame)' in prompt
    assert '<runtime_variables>' in prompt and 'threshold: float = 0.73' in prompt
    assert '<before>\nframe.' in prompt


def test_agent_keeps_inspectable_conversation_history():
    host = MemHost_agent({'/proj/models.py': "DFLT_LOCAL = 'gemma-e2b'\n"})
    a, be = fake_agent(host=host, replies=['the answer'])
    assert a.ask('what default model does leela use?') == 'the answer'
    assert '<preflight-tool name="search_code">' in str(be.sent[-1])
    turn = a.history[-1]
    assert turn['prompt'] == 'what default model does leela use?'
    assert turn['reply'] == 'the answer' and turn['plan']['route'] == 'repo'
    assert turn['model']

def test_the_context_window_keeps_recent_turns_and_the_notebook():
    assert compact.threshold(200_000, 16_384) == 200_000 - 16_384
    assert compact.threshold(0) is None
    assert compact.should_compact(190_000, 200_000)
    assert not compact.should_compact(100_000, 200_000)
    prompt = '<notebook>\n<cell id="a" type="code" compact="discard">all details</cell>\n</notebook>'
    assert compact.compact_notebook_context(prompt, lambda text: True) == prompt
    a, _ = fake_agent()
    msg = a.compose('q', context='CTX', context_path='/work/dialog.ipynb')
    assert '<notebook path="/work/dialog.ipynb">' in msg
    assert '<user-request>\nq\n</user-request>' in msg
    a = Agent(MemHost_agent(), model='gemma-e4b', extensions=False, local_multimodal=False)
    msg = a.compose('describe it', image=b'not-an-image')
    assert isinstance(msg, str)
    assert 'omitted' in msg and 'describe it' in msg
    assert threshold(4096) == 4096 - 1024
    assert threshold(200_000) == 200_000 - RESERVE
    assert threshold(0) is None
    c = Compactor()
    assert c.budget(4096) == 2048
    assert c.budget(200_000) == c.keep_recent


def test_an_existing_summary_is_updated_not_re_summarised():
    "Summarising a summary loses a little every time; tau's second prompt exists to stop that."
    msgs = [{'role': 'user', 'content': compact.SUMMARY_PREFIX + 'old summary'},
            {'role': 'assistant', 'content': 'later work'}]
    prev, rest = compact.split_previous(msgs)
    assert prev == 'old summary' and len(rest) == 1
    p = compact.summarise_prompt(msgs)
    assert '<previous-summary>' in p and 'PRESERVE' in p

def test_the_kept_tail_starts_at_a_user_turn():
    "A tail starting at an orphaned tool result is a dangling call some providers reject outright."
    c = compact.Compactor(keep_recent=50)
    msgs = [{'role': 'user', 'content': 'a' * 400}, {'role': 'assistant', 'content': 'b'},
            {'role': 'tool', 'content': 'c'}, {'role': 'user', 'content': 'd'},
            {'role': 'assistant', 'content': 'e'}]
    kept = c._keep(msgs)
    assert kept and kept[0]['role'] == 'user'

def test_pending_notebook_compaction_honours_cell_policy():
    prompt = ('<notebook path="/x.ipynb">\n'
              '<cell id="a" type="markdown" compact="keep"><source>KEEP ME</source></cell>\n'
              '<cell id="b" type="code" compact="discard"><source>DROP FIRST</source></cell>\n'
              '<cell id="c" type="code" compact="auto"><source>AUTO LATER</source></cell>\n'
              '</notebook>\n\nquestion')
    out = compact.compact_notebook_context(prompt, lambda text: len(text) < 245)
    assert 'KEEP ME' in out and 'DROP FIRST' not in out
    assert '<context-compacted' in out and 'discard="1"' in out


def test_compaction_replaces_history_and_reorients(spec):
    be = FakeBackend(spec)
    be.start()
    be.hist_ = [{'role': 'user', 'content': 'x' * 4000}, {'role': 'assistant', 'content': 'y' * 4000},
                {'role': 'user', 'content': 'recent'}]
    c = compact.Compactor(keep_recent=40)
    out = c.compact(be, lambda p, sp: 'GOAL: ship it')
    assert out == 'GOAL: ship it'
    head = be.hist[0]['content']
    assert head.startswith(compact.SUMMARY_PREFIX) and 'GOAL: ship it' in head
    assert 'kernel process was not touched' in head
    assert 'do not re-import' in head


def test_skill_md_directories_win_over_packages(tmp_path):
    d = tmp_path/'skills'/'exhash'
    d.mkdir(parents=True)
    (d/'SKILL.md').write_text('---\nname: exhash\ndescription: ours\n---\n\nlocal body\n')
    found = {s.name: s for s in skills.discover(cfg=tmp_path)}
    assert found['exhash'].source == 'md' and found['exhash'].description == 'ours'
    assert 'local body' in found['exhash'].text()

def test_a_bare_md_at_the_root_is_not_a_skill(tmp_path):
    d = tmp_path/'skills'
    d.mkdir(parents=True)
    (d/'loose.md').write_text('not a skill')
    assert not [s for s in skills.discover(cfg=tmp_path) if s.name == 'loose']

def test_the_index_carries_names_not_bodies():
    "Progressive disclosure: a dozen full skill texts would crowd out the code being worked on."
    ss = skills.discover()
    idx = skills.skill_index(ss)
    assert 'read_skill' in idx
    for s in ss: assert s.name in idx
    assert len(idx) < 4000
    rows = [l for l in idx.splitlines() if l.startswith('- `')]
    assert rows and all(len(l) <= 60 + skills.SKILL_DESC_MAX for l in rows), max(rows, key=len)


def test_activity_markdown_folds_results_and_reads_like_prose():
    s = activity.summarise
    assert s('search_code', {'query': 'AgentSession'}) == 'Search AgentSession'
    assert s('view_file', {'path': 'leela/ai.py', 'start': 240, 'end': 290}) == 'View leela/ai.py:240-290'
    assert s('read_url', {'url': 'https://github.com/AnswerDotAI/ipymini'}).startswith('Web fetch: https://')
    assert s('edit_file', {'path': 'a.py'}) == 'Edit a.py'
    act = activity.Activity()
    act.mark()
    act.finish(act.start('search_code', {'query': 'q'}), 'a hit')
    md = act.md(mark=0)
    assert '<details>' in md and 'Search q' in md and 'a hit' in md
    act = activity.Activity()
    a = act.start('view_file', {'path': 'a.md'})
    act.finish(a, 'text\n```\nfenced\n```\n')
    assert '\n```\n' not in a.md().split('```\n', 1)[1].rsplit('```', 1)[0]
    a, be = fake_agent(replies=['because x'])
    a.ask('why does this break?')
    assert a.history[-1]['plan']['route'] == 'direct'
    assert 'Answer directly' in str(be.sent[0])


def test_activity_fires_at_the_start_of_a_call_not_only_at_the_end():
    "Showing ⏳ while a fetch happens is the difference between looking alive and looking stuck."
    seen = []
    act = activity.Activity(on_change=lambda a: seen.append((a.summary, a.done)))
    a = act.start('read_url', {'url': 'https://x'})
    act.finish(a, 'the page')
    assert [d for _, d in seen] == [False, True]
    assert a.detail == 'the page' and a.done


def test_results_are_clipped_and_failures_spelled_one_way():
    import inspect
    a, _ = fake_agent()
    t = next(t for t in a.tools if t.__name__ == 'view_file')
    assert t.__doc__ and 'lineno|hash|content' in t.__doc__
    assert list(inspect.signature(t).parameters) == ['path', 'start', 'end']
    assert failed(err('could not read x'))
    assert failed(err('write failed', ValueError('nope')))
    assert not failed('exit 0\nall tests passed')
    assert err('a', ValueError('b')) == f'{ERR}a: ValueError: b'
    out = clip_lines([f'line {i}' for i in range(1, 500)], start=1, n=120,
                     more='call view_file(path, start={next}) to continue')
    assert 'more line(s) not shown' in out
    assert 'start=' in out and 'start={next}' not in out
    assert clip_lines([], empty='(nothing)') == '(nothing)'
    out = clip_lines(['x' * 50, 'y' * 50, 'z' * 50], n=60)
    assert 'y' not in out.split('…')[0].split('\n')[-1]
    assert clip('short') == 'short'
    assert 'truncated' in clip('x' * 100, n=50)


def test_changes_report_the_file_not_the_claim():
    "A tool that reported success and changed nothing must not appear in the diff."
    host = MemHost_agent({'/proj/a.py': 'x = 1\n'})
    a, _ = fake_agent(host)
    create = next(t for t in a.tools if t.__name__ == 'create_file')
    a.before.clear()
    create(path='/proj/a.py', text='x = 1\n')
    assert a.changes() == {}
    create(path='/proj/a.py', text='x = 2\n')
    assert a.changes() == {'/proj/a.py': ('x = 1\n', 'x = 2\n')}


def test_a_subagent_tool_budget_is_a_hard_stop():
    from leela.agent.tools import read_only
    calls = []
    def look(query: str) -> str:
        "Look something up."
        calls.append(query)
        return query
    guarded = read_only([look], max_calls=2)[0]
    assert guarded('one') == 'one' and guarded('two') == 'two'
    assert 'budget exhausted' in guarded('three')
    assert calls == ['one', 'two']

def test_delegation_runs_on_a_thrown_away_conversation(spec):
    from leela.agent.tools import delegate
    be = FakeBackend(spec)
    be.start()
    out = delegate(be, 'where do we do X?', tools=[])
    assert out == 'sub answer'
    assert len(be.spawned) == 1 and be.hist == []

def test_an_extension_registers_a_tool_a_skill_and_a_command(tmp_path):
    d = tmp_path/'extensions'
    d.mkdir(parents=True)
    (d/'mine.py').write_text(
        'def setup(ext):\n'
        '    @ext.tool\n'
        '    def count_todos(path: str) -> str:\n'
        '        "Count TODOs."\n'
        '        return "3"\n'
        '    ext.skill("house-style", "we write it like this", "How we write code here")\n'
        '    ext.command("hi", lambda agent, arg: f"hello {arg}", "say hi")\n')
    reg = load(Registry(), cfg=tmp_path)
    assert [t.__name__ for t in reg.tools] == ['count_todos']
    assert reg.skills[0].name == 'house-style'
    assert reg.commands['hi'][0](None, 'you') == 'hello you'
    assert 'mine.py: 1 tool(s), 1 skill(s), 1 command(s)' in reg.notes

def test_a_broken_extension_is_reported_not_raised(tmp_path):
    "An IDE that will not open because of a stray file in a config directory is a worse IDE."
    d = tmp_path/'extensions'
    d.mkdir(parents=True)
    (d/'bad.py').write_text('raise RuntimeError("boom")\n')
    reg = load(Registry(), cfg=tmp_path)
    assert reg.tools == [] and any('boom' in n for n in reg.notes)

def test_project_extensions_are_off_unless_asked_for(tmp_path):
    "A file in a repo you cloned five minutes ago runs arbitrary Python with the agent's tools."
    d = tmp_path/'.leela'/'extensions'
    d.mkdir(parents=True)
    (d/'x.py').write_text('def setup(ext):\n    ext.command("boom", lambda a, b: "", "")\n')
    assert load(Registry(), roots=[tmp_path]).commands == {}
    assert 'boom' in load(Registry(), roots=[tmp_path], project=True).commands


def test_an_approval_exchange_is_written_into_the_notebook():
    "The request, the refusal and the reason land as cells beside the prompt that caused"
    from leela.blocks.nb.nb import Cell, Notebook
    ws = Workspace(roots=[])
    nb = Notebook([Cell(source='fix it', cell_type='prompt')])
    ws._approval_target = (nb, 0)
    stop = ws.approvals.listen()
    def answer():
        for _ in range(300):
            if (a := ws.approvals.pending) is not None:
                return ws.answer_approval(a.id, False, 'that file is generated')
            time.sleep(0.01)
    threading.Thread(target=answer, daemon=True).start()
    tc = {'function': {'name': 'edit_file', 'arguments': {'path': 'gen.py'}}}
    d = ws.approvals.gate(tc)
    stop()
    # a refusal is handed back as steering, the same for a call with an id and one without
    assert d is True and tc['function']['name'] == 'user_steering'
    assert 'that file is generated' in tc['function']['arguments']['instruction']
    states = [(c.cell_type, (c.approval or {}).get('state')) for c in nb.cells]
    assert states == [('prompt', None), ('markdown', 'pending'), ('markdown', 'refused')]
    assert 'that file is generated' in nb[2].source

def test_workspace_path_refusal_names_the_folders_that_are_open(tmp_path):
    """The gate is the open roots, and it used to name the open tabs instead.

    A refusal listing five files that happened to be open read as a path or quoting bug in one of
    them, so the fix people reached for was to re-quote a path that was never the problem.
    """
    from leela.blocks.agent.ai import WorkspaceHost
    p = tmp_path/'dialog.ipynb'
    p.write_text('{}')
    ws = Workspace(roots=[tmp_path])
    ws.open(p)
    with pytest.raises(Exception) as e: WorkspaceHost(ws).check('/Users/719/dialog.ipynb', reading=True)
    msg = str(e.value)
    assert 'open folders' in msg and str(tmp_path) in msg
    assert 'open files' not in msg, 'the tabs are not what the refusal is about'
    assert 'reading outside the open folders' in msg, 'and the setting that would have allowed it'


def test_workspace_agent_reaches_the_live_kernel_inspector():
    from leela.blocks.agent.ai import WorkspaceHost
    class K:
        base = 'http://kernel'
        def __init__(self): self.calls = []
        def api_sync(self, path, params=None, timeout=30):
            self.calls.append((path, params))
            if path == '/api/rows':
                return {'groups': [{'nodes': [{'name': 'df', 'type': 'DataFrame', 'value': '[5×2]'}]}]}
            return {'ok': True, 'stdout': '', 'error': '', 'result': {'value': 'done'}}
    ws, k = Workspace(roots=[]), K()
    ws.kernel_peek = lambda tab=None: k
    h = WorkspaceHost(ws)
    assert 'df: DataFrame' in h.list_vars()
    assert h.run_python('df_norm = df.copy()') == 'done'
    assert h.inspect_python('df_norm.shape', scope='overlay') == 'done'
    assert [p for p, _ in k.calls] == ['/api/rows', '/api/exec', '/agent/api/exec']
    names = {t.__name__ for t in tools_for(h)}
    assert {'run_python', 'inspect_python', 'list_vars'} <= names


def test_a_stream_yields_before_it_finishes(spec):
    "The whole point. A stream that only yields at the end is a blocking call with extra steps."
    from tests.fakemodel import ScriptedBackend, Step
    be = ScriptedBackend(steps=[Step(text='one two three')], token_delay=0)
    be.start()
    got = list(be.stream('hi'))
    assert len(got) == 3 and ''.join(got).split() == ['one', 'two', 'three']


def test_agent_prompt_bar_accepts_the_open_notebook_context(tmp_path):
    seen = {}
    class A:
        class Model: local = True
        model = Model()
        def stream_with(self, prompt, **kwargs):
            seen.update(prompt=prompt, **kwargs)
            return iter(['ok'])
    ws = Workspace(roots=[tmp_path]); ws._ai = A()
    assert list(ws.ask_stream('question', context='<cell>answer = 42</cell>',
                              context_path='/work/demo.ipynb')) == ['ok']
    assert seen['context'] == '<cell>answer = 42</cell>'
    assert seen['context_path'] == '/work/demo.ipynb'

def test_streaming_and_blocking_compose_the_same_message():
    "A streamed turn that quietly saw a different message would be a very hard bug to find."
    a, be = fake_agent(replies=['x', 'y'])
    a.ask_with('q', context='CTX', screen='SCR')
    blocking = str(be.sent[-1])
    list(a.stream_with('q', context='CTX', screen='SCR'))
    assert str(be.sent[-1]) == blocking
    assert '<notebook>' in blocking and '<screen>' in blocking


def test_local_multimodal_is_forwarded_to_rishi(monkeypatch):
    import leela.agent.agent as chat
    made = []
    monkeypatch.setattr(chat, 'make_backend', lambda spec, **kw: made.append((spec, kw)) or object())
    a = Agent(MemHost_agent(), model='gemma-e4b', extensions=False, local_multimodal=False)
    a._tools = []
    a._be('turn')
    assert made[0][0].backend == 'litert'
    assert made[0][1]['multimodal'] is False


def test_prompt_cells_and_agent_chat_have_separate_assistants_and_histories():
    ws = Workspace(roots=[], model='gemma-12b', inline_model='gemma-e2b')
    assert ws.ai is not ws.inline_ai
    assert ws.ai.model.name == 'gemma-12b'
    assert ws.inline_ai.model.name == 'gemma-e2b'
    assert ws.ai.history_path.name == 'agent-history.jsonl'
    assert ws.inline_ai.history_path.name == 'inline-history.jsonl'

def test_a_prompt_cell_fills_in_as_the_answer_arrives():
    "`ask_cell_stream` appends to `cell.reply` on the way past, so repainting the cell"
    from leela.blocks.nb.nb import Cell, Notebook
    from tests.fakemodel import Step, install
    ws = Workspace(roots=[])
    install(ws, [Step(text='the answer is four')], token_delay=0)
    nb = Notebook([Cell(source='what is 2+2', cell_type='prompt')])
    seen = []
    for _ in ws.ask_cell_stream(nb, 0): seen.append(nb[0].reply)
    assert len(seen) > 1
    assert seen[0].strip() == 'the'
    assert seen[-1].strip() == 'the answer is four'
    assert nb[0].reply.startswith('the answer is four')
    assert nb.dirty

def test_a_streamed_cell_still_gets_its_activity_trail():
    from leela.blocks.nb.nb import Cell, Notebook
    from tests.fakemodel import Step, install
    ws = Workspace(roots=[])
    ws.add_root('.')
    install(ws, [Step(tool=('search_code', {'query': 'Approvals'})),
                 Step(text='found it')], token_delay=0)
    nb = Notebook([Cell(source='where is approval handled?', cell_type='prompt')])
    list(ws.ask_cell_stream(nb, 0))
    assert '<details>' in nb[0].reply and 'Search Approvals' in nb[0].reply
    assert nb[0].calls and nb[0].calls[0]['tool'] == 'search_code'


def test_workspace_at_attachments_are_grounded_and_sandboxed(tmp_path):
    p = tmp_path/'notes.txt'; p.write_text('the attached fact')
    ws = Workspace(roots=[tmp_path])
    context, images = ws._attachment_context([str(p)])
    assert str(p) in context and 'the attached fact' in context and images == []
    with pytest.raises(Exception): ws._attachment_context(['/etc/passwd'])

def test_the_sse_endpoint_streams_the_real_app():
    "Drive the actual route, not a mock of it."
    pytest.importorskip('starlette.testclient')
    from tests.fakemodel import Step, install
    ws = Workspace(roots=[])
    ws.add_root('.')
    install(ws, [Step(tool=('search_code', {'query': 'Approvals'})),
                 Step(text='found it in hitl.py')], token_delay=0)
    with TestClient(ide_app(ws)) as c:
        with c.stream('GET', '/agent/stream', params={'prompt': 'where?'}) as r:
            assert r.status_code == 200
            assert r.headers['content-type'].startswith('text/event-stream')
            body = ''.join(r.iter_text())
    assert 'event: chunk' in body
    assert body.count('event: activity') >= 1
    assert '"done": true' in body
    assert 'event: done' in body
    assert 'Search Approvals' in body
    assert 'found' in body
    done = body.rsplit('event: done\ndata: ', 1)[1]
    import json as _j
    d = _j.loads(done.strip())
    assert d['ok'] and 'edits' in d and d['activity']

def test_agent_stream_rejects_a_second_turn_while_busy(tmp_path):
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        with ws.ai.lock:
            response = client.get('/agent/stream', params={'prompt': 'where?'})
    assert response.status_code == 409
    assert 'already working' in response.text

def test_external_rishi_request_uses_the_web_approval_queue():
    ws = Workspace(roots=[])
    result = {}
    with TestClient(ide_app(ws)) as client:
        def request():
            result['response'] = client.post('/agent/approval/request', json={
                'tool_call': {'function': {'name': 'custom_tool', 'arguments': {'value': 1}}}})
        t = threading.Thread(target=request, daemon=True); t.start()
        for _ in range(200):
            pending = client.get('/agent/approval').json()['pending']
            if pending: break
            time.sleep(0.01)
        assert pending['tool'] == 'custom_tool'
        assert client.post('/agent/approve', json={'id': pending['id'], 'ok': True}).status_code == 200
        t.join(2)
    response = result['response']
    assert response.status_code == 200 and response.json()['answer']['answer'] is True

def test_workspace_repo_writes_setting_route_persists_and_reports_approval(tmp_path):
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        response = client.post('/agent/workspace-repo-writes', json={'enabled': True})
    assert response.status_code == 200 and response.json()['enabled']
    assert 'approval rules still apply' in response.json()['note']

def test_prompt_cell_endpoint_streams_into_the_notebook():
    from pathlib import Path
    from tests.fakemodel import Step, install
    p = Path(__file__).parent/'fixtures'/'dialog.ipynb'
    ws = Workspace(roots=[p.parent], approvals='auto')
    ws.open(p)
    install(ws, [Step(text='created df_norm successfully')], token_delay=0)
    with TestClient(ide_app(ws)) as client:
        assert client.get('/tab/state').status_code == 200
        with client.stream('POST', '/nb/ask/stream', json={'i': 2, 'source': 'scale it'}) as r:
            body = ''.join(r.iter_text())
    assert r.status_code == 200
    assert 'event: chunk' in body and 'event: done' in body
    assert 'created df_norm successfully' in body

def test_a_subagent_can_ask_for_the_overlay_scope():
    "A sub-agent gets the scope choice too, because the sandbox is a limit on the Python"
    import inspect as _i
    from leela.agent.tools import read_only
    class H(NullHost):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.calls = []
        def inspect_python(self, code, scope='isolated'):
            self.calls.append((code, scope))
            return 'ok'
        def list_vars(self): return 'df: DataFrame'
        def terminal_text(self, lines=200): return ''
        def run_python(self, code): return 'ok'
    h = H(['/x'])
    tools = tools_for(h)
    sub = {t.__name__: t for t in read_only(tools)}
    assert 'inspect_python' in sub
    assert 'scope' in _i.signature(sub['inspect_python']).parameters
    sub['inspect_python'](code='list(df.columns)', scope='overlay')
    assert h.calls == [('list(df.columns)', 'overlay')]

def test_a_narrow_host_says_why_rather_than_failing_silently():
    from leela.agent.tools import NullHost as _N
    class H(_N):
        scopes = ('isolated',)
        def inspect_python(self, code, scope='isolated'):
            if scope not in self.scopes: return f'scope {scope!r} is not available here'
            return 'sandboxed ok'
    assert 'not available' in H(['/x']).inspect_python('x', 'overlay')

def test_one_unresolvable_model_does_not_blank_the_whole_picker(monkeypatch):
    "A model that will not resolve costs its own row, not the model list."
    from tokenize import TokenError
    from fastcore.basics import first
    broken, real = 'codex/gpt-5.6-terra', models.resolve
    def resolve(name, *a, **kw):
        if name == broken: raise TokenError('unterminated string literal (detected at line 19)', (19, 62))
        return real(name, *a, **kw)
    ws = Workspace(roots=[], model=broken)
    with TestClient(ide_app(ws)) as c:
        ws.ai
        monkeypatch.setattr(models, 'resolve', resolve)
        ws.ai.routing._cache.clear()
        r = c.get('/agent/models')
    assert r.status_code == 200
    d = r.json()
    assert len(d['models']) > 1 and d['selected']['agent'] == broken
    row = first(m for m in d['models'] if m['value'] == broken)
    assert row['unavailable'] and 'TokenError' in row['source']
    assert all('TokenError' not in (m.get('source') or '') for m in d['models'] if m['value'] != broken)

def named(tools):
    return {t.__name__: t for t in tools}


def test_run_shell_reports_what_it_ran_and_how_it_ended():
    h = MemHost(commands={'pytest -q': (1, '2 failed, 3 passed')})
    run = named(shell_tools(h))['run_shell']
    out = run('pytest -q')
    assert failed(out) and 'exit 1' in out and 'FAILED' in out and '2 failed' in out
    h = MemHost(commands={'pytest -q': (0, '5 passed')})
    out = named(shell_tools(h))['run_shell']('pytest -q')
    assert not failed(out) and out.startswith('exit 0') and '5 passed' in out
    out = named(shell_tools(MemHost()))['run_shell']('ruff check .')
    assert 'exit 0' in out and '(no output)' in out
    h = MemHost()
    assert failed(named(shell_tools(h))['run_shell']('   '))
    assert h.cmds == []
    h = MemHost()
    named(shell_tools(h))['run_shell']('git status --short', cwd='/proj/sub', timeout=30)
    assert h.cmds == [('git status --short', '/proj/sub', 30)]


SRC = 'def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n'

def editor(files=None):
    h = MemHost(files if files is not None else {'/proj/m.py': SRC})
    return h, named(file_tools(h))['replace_text']

def test_edit_file_applies_every_edit_or_refuses_with_a_reason():
    h, edit = editor()
    out = edit('/proj/m.py', '[{"oldText": "a + b", "newText": "a + b + 1"},'
                             ' {"oldText": "a - b", "newText": "a - b - 1"}]')
    assert not failed(out) and 'replaced 2 block(s)' in out
    assert h.files['/proj/m.py'] == SRC.replace('a + b', 'a + b + 1').replace('a - b', 'a - b - 1')
    _, edit = editor()
    out = edit('/proj/m.py', '[{"oldText": "a + b", "newText": "a * b"}]')
    assert '-    return a + b' in out and '+    return a * b' in out
    h, edit = editor()
    out = edit('/proj/m.py', '[{"oldText": "return a", "newText": "return 0"}]')
    assert failed(out) and 'matches 2 places' in out and 'more surrounding' in out
    assert h.files['/proj/m.py'] == SRC
    h, edit = editor()
    out = edit('/proj/m.py', '[{"oldText": "def add(a, b, c):", "newText": "x"}]')
    assert failed(out) and 'not found' in out and 'Re-read' in out
    assert h.files['/proj/m.py'] == SRC
    h, edit = editor()
    out = edit('/proj/m.py', '[{"oldText": "a + b", "newText": "ok"},'
                             ' {"oldText": "not in the file", "newText": "x"}]')
    assert failed(out) and 'edit 2' in out
    assert h.files['/proj/m.py'] == SRC
    h, edit = editor()
    out = edit('/proj/m.py', '[{"oldText": "def add(a, b):\\n    return a + b", "newText": "x"},'
                             ' {"oldText": "return a + b", "newText": "y"}]')
    assert failed(out) and 'overlap' in out
    assert h.files['/proj/m.py'] == SRC
    _, edit = editor()
    out = edit('/proj/m.py', '[{"oldText": "", "newText": "x"}]')
    assert failed(out) and 'create_file' in out
    _, edit = editor()
    out = edit('/proj/m.py', '[{"oldText": "a + b", "newText": "a + b"}]')
    assert failed(out) and 'changed nothing' in out
    _, edit = editor()
    out = edit('/proj/nope.py', '[{"oldText": "a", "newText": "b"}]')
    assert failed(out) and 'create_file' in out
    _, edit = editor()
    assert failed(edit('/proj/m.py', 'not json'))
    assert failed(edit('/proj/m.py', '[]'))
    assert 'oldText' in edit('/proj/m.py', '[{"old": "a"}]')


def test_the_shapes_a_model_actually_sends_are_all_accepted():
    "A JSON string, a list of dicts, and a list of pairs are each unambiguous. Refusing"
    for edits in ['[{"oldText": "a + b", "newText": "z"}]',
                  [{'oldText': 'a + b', 'newText': 'z'}],
                  [['a + b', 'z']],
                  {'oldText': 'a + b', 'newText': 'z'}]:
        h, edit = editor()
        assert not failed(edit('/proj/m.py', edits)), edits
        assert 'return z' in h.files['/proj/m.py']


FILES = {'/proj/a.py': 'import json\nvalue = compute(1)\n',
         '/proj/tests/test_a.py': 'from a import compute\n\ndef test_compute():\n    assert compute(1)\n',
         '/proj/notes.md': 'compute is described here\n'}

def test_grep_reports_its_matches_and_what_it_searched():
    out = named(code_tools(MemHost(FILES)))['grep']('compute')
    assert '/proj/a.py:2' in out and '/proj/tests/test_a.py:1' in out and '/proj/notes.md:1' in out
    assert 'match(es) in 3 file(s) searched' in out
    out = named(code_tools(MemHost(FILES)))['grep']('compute', path_filter='tests/')
    assert '/proj/tests/test_a.py' in out and '/proj/a.py:' not in out
    g = named(code_tools(MemHost(FILES)))['grep']
    assert '/proj/a.py' in g(r'compute\(\d\)')
    assert 'no matches' in g('compute(1)', regex=True)
    assert '/proj/a.py' in g('compute(1)', regex=False)
    g = named(code_tools(MemHost({'/proj/a.py': 'Value = 1\n'})))['grep']
    assert 'no matches' in g('value')
    assert '/proj/a.py' in g('value', ignore_case=True)
    out = named(code_tools(MemHost(FILES)))['grep']('nowhere')
    assert 'no matches' in out and '3 file(s)' in out
    g = named(code_tools(MemHost(FILES)))['grep']
    assert failed(g(''))
    assert failed(g('(unclosed'))


def test_ls_lists_the_open_folders_when_asked_for_nothing(tmp_path):
    class H(NullHost):
        def check(self, path, must_exist=False):
            from pathlib import Path
            return Path(path)
    (tmp_path/'pkg').mkdir()
    (tmp_path/'x.py').write_text('x = 1\n')
    out = named(code_tools(H([str(tmp_path)])))['ls']('')
    assert 'pkg/' in out and 'x.py' in out


def agent_on(host):
    "An `Agent` over `host` with no model behind it: these tests are about the tool layer."
    from leela.agent.testing import fake_agent
    return fake_agent(host, replies=['done'], subagents=False, compact=False)[0]

def test_a_failed_tool_call_is_recorded_as_failed():
    "The old test was a list of prefixes ('edit failed', 'could not') that each new tool"
    h = MemHost({'/proj/m.py': SRC}, commands={'pytest': (1, 'boom')})
    a = agent_on(h)
    tools = named(a.tools)
    tools['run_shell']('pytest')
    tools['replace_text']('/proj/m.py', '[{"oldText": "nope", "newText": "x"}]')
    rows = a.activity.rows()
    assert [r['ok'] for r in rows[-2:]] == [False, False]


def test_a_capability_lost_mid_session_is_a_failure_not_the_end_of_the_turn():
    "A kernel dies, a folder closes. Raising here ends the turn; a failure the model can"
    class Gone(MemHost):
        def run_cmd(self, command, cwd=None, timeout=120):
            if not str(command or '').strip(): return 0, ''
            raise NotImplementedError('the shell went away')
    a = agent_on(Gone())
    out = named(a.tools)['run_shell']('pytest')
    assert failed(out) and 'not available' in out
    assert a.activity.rows()[-1]['ok'] is False


@pytest.fixture
def project(tmp_path):
    from leela.blocks.agent.ai import WorkspaceHost
    (tmp_path/'src').mkdir()
    (tmp_path/'src'/'app.py').write_text('value = 1\n')
    return WorkspaceHost(Workspace(roots=[tmp_path]))

def test_a_real_command_returns_its_output_and_exit_code(project):
    assert project.run_cmd('echo hello') == (0, 'hello\n')
    code, out = project.run_cmd('exit 3')
    assert code == 3 and out == ''

def test_stdout_and_stderr_come_back_in_the_order_they_happened(project):
    "A failing test *is* its traceback. Splitting the streams loses which line came first."
    code, out = project.run_cmd('echo out; echo err 1>&2; echo after')
    assert out.splitlines() == ['out', 'err', 'after']

def test_a_command_runs_in_the_project_by_default(project):
    code, out = project.run_cmd('ls')
    assert code == 0 and 'src' in out

def test_a_command_can_be_run_in_a_subdirectory(project):
    code, out = project.run_cmd('ls', cwd=str(project.roots[0] + '/src'))
    assert code == 0 and 'app.py' in out

def test_a_command_cannot_be_started_outside_the_open_folders(project):
    from leela.blocks.fs.fs import Unsafe
    with pytest.raises(Unsafe):
        project.run_cmd('ls', cwd='/etc')

def test_a_hung_command_is_killed_and_says_so(project):
    code, out = project.run_cmd('sleep 30', timeout=1)
    assert code == 124 and 'killed after 1s' in out

def test_a_timeout_takes_the_children_with_it(project):
    "`pytest -n 4` behind a pipe leaves children that outlive the shell, and a leaked"
    import os, time
    marker = project.roots[0] + '/child.pid'
    project.run_cmd(f'(sleep 30 & echo $! > {marker}); sleep 30', timeout=2)
    pid = int(open(marker).read().strip())
    time.sleep(0.2)
    with pytest.raises(OSError):
        os.kill(pid, 0)

def test_the_probe_command_never_spawns_anything(project):
    assert project.run_cmd('') == (0, '')
    assert project.run_cmd('   ') == (0, '')

def test_leelas_own_agent_is_offered_the_shell(project):
    from leela.blocks.agent.ai import ide_tools
    assert 'run_shell' in named(ide_tools(project))

def test_the_browser_previews_an_exact_text_edit_as_a_diff_without_writing_it(project):
    "The checkpoint form shows what the call would do. It must not do it."
    from leela.blocks.agent.turns import tool_preview as _tool_preview
    path = project.roots[0] + '/src/app.py'
    args = {'path': path, 'edits': '[{"oldText": "value = 1", "newText": "value = 2"}]'}
    preview = _tool_preview(project.ws.ai, 'replace_text', args)
    assert preview['kind'] == 'diff'
    assert open(path).read() == 'value = 1\n'

def test_the_browser_previews_a_command_as_a_command(project):
    from leela.blocks.agent.turns import tool_preview as _tool_preview
    p = _tool_preview(project.ws.ai, 'run_shell', {'command': 'pytest -q'})
    assert p['text'] == 'pytest -q' and p['language'] == 'bash'

def test_a_sub_agent_does_not_get_a_shell(project):
    "A research sub-agent reports; it does not act, and a command is an action."
    from leela.agent.tools import read_only
    from leela.blocks.agent.ai import ide_tools
    assert 'run_shell' not in named(read_only(ide_tools(project)))
    assert 'replace_text' not in named(read_only(ide_tools(project)))
    assert 'grep' in named(read_only(ide_tools(project)))

def _index_legs(ws, monkeypatch, path):
    "Stand in for the three Kosha-backed legs and record which of them the blend ran."
    from fastcore.all import L
    from leela.blocks.search.search import Hit
    ran = []
    rows = {'symbols': [Hit(path=path, line=1, text='def compute_total(x):', kind='symbol',
                            symbol='compute_total')],
            'fts': [Hit(path=path, line=1, text='def compute_total(x):', kind='fts', score=0.5)],
            'ann': [Hit(path=path, line=2, text='return x', kind='ann', symbol='compute_total',
                        score=0.9)]}
    for name, hits in rows.items():
        def leg(q, limit, name=name, hits=hits): return ran.append(name) or L(hits)
        monkeypatch.setattr(ws.search, f'_{name}', leg)
    return ran

def test_search_all_reports_the_engines_that_agreed_on_each_hit(project, monkeypatch):
    "One location four engines found is the point: the row has to say so, or it is just another list."
    path = project.roots[0] + '/src/app.py'
    open(path, 'w').write('def compute_total(x):\n    return x\n')
    _index_legs(project.ws, monkeypatch, path)
    panel = project.ws.ai
    panel.tools
    out = named(panel.registry.tools)['search_all']('compute_total')
    lines = out.splitlines()
    assert lines[0].startswith('[all:')
    agreed = first(lines, lambda r: r.startswith(f'{path}:1'))
    alone = first(lines, lambda r: r.startswith(f'{path}:2'))
    assert agreed.endswith('[symbols+rg+fts]') and 'def compute_total(x):' in agreed
    assert alone.endswith('[ann]')
    assert len([r for r in lines if r.startswith(path)]) == 2

def test_the_inline_agent_never_waits_on_the_embedding_leg(project, monkeypatch):
    "A prompt cell is answered while someone waits mid-line; `ann` embeds the query first."
    path = project.roots[0] + '/src/app.py'
    open(path, 'w').write('def compute_total(x):\n    return x\n')
    ran = _index_legs(project.ws, monkeypatch, path)
    inline = project.ws.inline_ai
    inline.tools
    out = named(inline.registry.tools)['search_all']('compute_total')
    assert set(ran) == {'symbols', 'fts'} and 'ann' not in ran
    assert '[ann]' not in out and f'{path}:1' in out

def test_both_surfaces_offer_the_blend_and_a_sub_agent_keeps_it(project):
    "Reading is never the dangerous part, so delegation should not lose the better search."
    from leela.agent.tools import read_only
    from leela.blocks.agent.ai import ide_tools
    panel = project.ws.ai
    panel.tools
    assert 'search_all' in named(panel.registry.tools)
    assert 'search_all' in named(read_only(ide_tools(project)))
    assert 'search_code' in named(ide_tools(project))

sys.path.insert(0, str(ROOT/'tools'))

@pytest.fixture
def ws(tmp_path):
    (tmp_path/'pkg').mkdir()
    (tmp_path/'pkg'/'a.py').write_text('print(1)\n')
    (tmp_path/'pkg'/'b.md').write_text('# B\n')
    (tmp_path/'top.py').write_text('x = 1\ny = 2\n')
    return Workspace(roots=[tmp_path])

def test_a_folder_is_a_manifest_not_its_contents(ws, tmp_path):
    "A folder is attached to say *look in here*, and the agent has file tools of its own."
    out = ws.folder_manifest(tmp_path/'pkg')
    assert '<attached-folder' in out and 'files="2"' in out
    assert 'a.py' in out and 'b.md' in out
    assert 'python' in out and 'markdown' in out, 'the language is what makes it worth reading'
    assert 'print(1)' not in out, 'the contents are the agent\'s to fetch'

def test_a_folder_manifest_skips_what_walk_skips(ws, tmp_path):
    "Otherwise the first thing a manifest shows is somebody's virtualenv."
    (tmp_path/'pkg'/'node_modules').mkdir()
    (tmp_path/'pkg'/'node_modules'/'junk.js').write_text('module.exports = 1\n')
    assert 'junk.js' not in ws.folder_manifest(tmp_path/'pkg')

def test_attaching_a_folder_no_longer_raises(ws, tmp_path):
    "It used to be refused outright: `attachment is not a file`."
    text, _ = ws._attachment_context([str(tmp_path/'pkg')])
    assert '<attached-folder' in text

def test_a_selection_is_sent_as_chosen_not_re_read_from_disk(ws, tmp_path):
    "The buffer may be unsaved, and what was highlighted is what was meant."
    sel = {'kind': 'selection', 'path': str(tmp_path/'top.py'), 'from': 2, 'to': 2,
           'text': 'y = 2  # edited, never saved'}
    text, _ = ws._attachment_context([sel])
    assert 'lines="2-2"' in text and 'never saved' in text
    assert '<attached-selection' in text, 'marked as a range, not mistaken for a whole file'

def test_two_selections_in_one_file_are_two_contexts(ws, tmp_path):
    p = str(tmp_path/'top.py')
    a = {'kind': 'selection', 'path': p, 'from': 1, 'to': 1, 'text': 'x = 1'}
    b = {'kind': 'selection', 'path': p, 'from': 2, 'to': 2, 'text': 'y = 2'}
    text, _ = ws._attachment_context([a, b])
    assert text.count('<attached-selection') == 2
    assert ws._attachment_context([a, dict(a)])[0].count('<attached-selection') == 1

def test_folders_are_offered_to_the_agent_and_not_to_quick_open(ws, tmp_path):
    with TestClient(ide_app(ws)) as c:
        agent = c.get('/fs/find', params={'q': 'pkg', 'dirs': 1}).json()['hits']
        assert any(h['kind'] == 'folder' and h['name'] == 'pkg/' for h in agent)
        quick = c.get('/fs/find', params={'q': 'pkg'}).json()['hits']
        assert all(h['kind'] == 'file' for h in quick), 'opening a folder is not quick-open\'s job'


def test_an_interpreters_libraries_are_not_the_project(tmp_path):
    "98% of a walk of this repo was site-packages, so `@keys` ranked `libxslt/keys.h` over"
    for d in ('.venv', '.app-venv', 'my-venv', 'venv-3.12'):
        lib = tmp_path/d/'lib'/'python3.12'/'site-packages'/'lxml'
        lib.mkdir(parents=True)
        (lib/'keys.h').write_text('/* not your code */\n')
    (tmp_path/'keys.py').write_text('KEYS = 1\n')
    (tmp_path/'conventions').mkdir(); (tmp_path/'conventions'/'keys.py').write_text('X = 1\n')
    ws = Workspace(roots=[tmp_path])
    walked = [str(p) for p in ws.fs.walk(tmp_path)]
    assert not [p for p in walked if 'site-packages' in p], walked[:3]
    assert len(walked) == 2, walked
    assert any(p.endswith('conventions/keys.py') for p in walked), 'not an over-eager skip'

def test_a_site_packages_under_an_oddly_named_venv_is_still_skipped(tmp_path):
    "The inner skip is the backstop for a venv folder named something nobody predicted."
    lib = tmp_path/'weird'/'lib'/'site-packages'/'pkg'
    lib.mkdir(parents=True)
    (lib/'mod.py').write_text('x = 1\n')
    (tmp_path/'mine.py').write_text('y = 2\n')
    ws = Workspace(roots=[tmp_path])
    assert [p.name for p in ws.fs.walk(tmp_path)] == ['mine.py']

def test_a_file_leela_just_wrote_can_be_found_before_the_walk_cache_expires(tmp_path):
    "The walk is cached to keep quick-open cheap. Our own writes skip the window."
    ws = Workspace(roots=[tmp_path])
    assert [p.name for p in ws.fs.walk(tmp_path)] == []
    ws.fs.write(tmp_path/'fresh.py', 'x = 1\n')
    assert [p.name for p in ws.fs.walk(tmp_path)] == ['fresh.py'], 'stale for 2s was the bug'
    ws.fs.delete(tmp_path/'fresh.py')
    assert [p.name for p in ws.fs.walk(tmp_path)] == []


def test_the_local_window_errs_small_and_can_be_overridden(monkeypatch):
    "Under-stating a window costs one early compaction; over-stating it costs the turn."
    monkeypatch.delenv('LEELA_LOCAL_CTX', raising=False)
    assert local_ctx('gemma-e2b') == 16384
    assert resolve('gemma-e2b').ctx == 16384
    assert local_ctx('something-else') == DFLT_LOCAL_CTX
    monkeypatch.setenv('LEELA_LOCAL_CTX', '8192')
    assert local_ctx('gemma-e2b') == 8192
    monkeypatch.setenv('LEELA_LOCAL_CTX', 'gemma-e4b:16384,gemma-12b:32000')
    assert local_ctx('gemma-e4b') == 16384
    assert local_ctx('gemma-e2b') == 16384, 'a per-model override must not move the others'

def test_leela_environment_names_override_legacy_ramabana_names(monkeypatch):
    monkeypatch.setenv('LEELA_MODEL', 'current')
    monkeypatch.setenv('RAMABANA_MODEL', 'legacy')
    assert env('MODEL') == 'current'
    monkeypatch.delenv('LEELA_MODEL')
    assert env('MODEL') == 'legacy'

GEMMA = ('E0000 00:00:1234.567 llm_engine.cc:412] input token IDs exceed the maximum '
         'number of tokens 4096, got 5092\n')

def _native_write(text):
    "Write straight to fd 2, the way a C++ engine does -- around Python's sys.stderr, not through it."
    os.write(2, text.encode())

def test_native_output_is_captured_without_being_lost():
    with captured() as cap:
        _native_write(GEMMA)
    assert 'exceed the maximum number of tokens 4096' in cap.text
    assert cap.problems, 'a line saying "exceed" is a problem, not chatter'
    with captured() as cap:
        _native_write('INFO: Created TensorFlow Lite XNNPACK delegate for CPU.\n')
    assert cap.text and not cap.problems
    assert interesting(GEMMA * 5) == [GEMMA.strip()]
    assert len(interesting('\n'.join(f'error {i}' for i in range(20)))) == 4
    def boom():
        _native_write(GEMMA)
        raise RuntimeError('generate failed')
    with pytest.raises(RuntimeError) as e: native_capture(boom)
    assert 'exceed the maximum number of tokens' in getattr(e.value, 'native_output', '')


def test_the_descriptor_survives_an_exception_inside_the_block():
    "A broken stderr would be a far worse bug than the one this fixes."
    before = os.dup(2)
    try:
        with pytest.raises(ValueError):
            with captured():
                _native_write('something\n')
                raise ValueError('boom')
        _native_write('')
        assert sys.stderr is not None
    finally: os.close(before)


def test_capture_can_be_switched_off(monkeypatch):
    "Anything that moves a file descriptor needs a way out."
    monkeypatch.setenv('LEELA_NO_NATIVE_CAPTURE', '1')
    with captured() as cap: _native_write('x\n')
    assert cap.text == ''

class MutteringBackend(Backend):
    "A backend that fails the way litert does: it prints, returns nothing, and raises nothing."
    kind = 'muttering'
    def __init__(self, spec, mode='empty', **kw):
        super().__init__(spec, **kw)
        self.mode = mode
    def _start(self): return self
    def _close(self): pass
    def _usage(self): return Usage(model=self.spec.model_id)
    def _mutter(self):
        "What `RishiBackend._native` does for real: keep what the engine said, and report it."
        self.last_native = GEMMA.strip()
        self.problem(f'{self.spec.name}: {GEMMA.strip()}')
    def _send(self, msg, **kw):
        self._mutter()
        return ''
    def _stream(self, msg, **kw):
        self._mutter()
        return iter(())
    def _oneshot(self, prompt, sp, max_tokens):
        self._mutter()
        raise RuntimeError('input too long')

@pytest.fixture
def muttering():
    from leela.agent.core import ModelSpec
    return MutteringBackend(ModelSpec('gemma-e2b', 'muttering', 'gemma/e2b', ctx=4096))

def test_a_silent_failure_is_reported_rather_than_shown_as_an_empty_answer(muttering):
    "The bug as the user met it: a turn that produced nothing and said nothing about it."
    out = ''.join(muttering.stream('hello'))
    assert 'exceed the maximum number of tokens 4096' in out
    assert muttering.problems

def test_a_cheap_job_that_fails_still_says_so(muttering):
    "`oneshot` returns '' by contract -- completion, classification and compaction all"
    assert muttering.oneshot('summarise this') == ''
    assert any('input too long' in p for p in muttering.problems)

def test_problems_reach_the_agents_status(ws):
    "Which is what the frontends read, and what puts it on a status bar."
    from leela.agent.core import ModelSpec
    ai = ws.ai
    b = MutteringBackend(ModelSpec('gemma-e2b', 'muttering', 'gemma/e2b', ctx=4096))
    ai._backends[('muttering', 'gemma/e2b')] = b
    b.oneshot('anything')
    assert ai.problems and ai.problems[-1] in ai.status()['problems']
    ai.clear_problems()
    assert not ai.problems

@pytest.mark.parametrize('given,want', [
    ('auto', 'auto'), ('AUTO', 'auto'), (' 80 ', 80), (80, 80),
    (TOOL_RANGE[0], TOOL_RANGE[0]), (TOOL_RANGE[1], TOOL_RANGE[1]),
    (TOOL_RANGE[0] - 1, 'auto'), (TOOL_RANGE[1] + 1, 'auto'),
    (None, 'auto'), (True, 'auto'), ('', 'auto'), ('lots', 'auto'),
])
def test_a_budget_is_auto_or_a_number_in_range(given, want):
    assert budget_value(given, *TOOL_RANGE) == want

def test_the_setting_reaches_the_agent_that_is_built_from_it(tmp_path):
    ws = Workspace(roots=[tmp_path])
    assert (ws.tool_budget, ws.step_budget) == ('auto', 'auto'), 'auto is the default'
    ws.tool_budget, ws.step_budget = 240, 60
    assert (ws.ai.tool_budget, ws.ai.step_budget) == (240, 60)

def test_changing_it_does_not_restart_the_conversation(tmp_path):
    ws = Workspace(roots=[tmp_path])
    agent = ws.ai
    with TestClient(ide_app(ws)) as c:
        d = c.post('/agent/budget', json={'tools': 240, 'steps': 60}).json()
        assert d['tools'] == 240 and d['steps'] == 60
        status = c.get('/agent/status').json()
        assert {'tool_calls', 'tool_limit', 'step_limit'} <= status.keys()
        assert (agent.tool_budget, agent.step_budget) == (240, 60), 'the live agent was updated in place'
        assert ws.ai is agent, 'and it is the same conversation'
        assert c.post('/agent/budget', json={'tools': 'auto'}).json()['tools'] == 'auto'
        assert agent.tool_budget == 'auto' and agent.step_budget == 60, 'one field at a time'

def test_a_value_it_will_not_take_is_refused_rather_than_reset(tmp_path):
    "`budget_value` answers `auto` for anything it rejects, so a typo would look like a reset."
    ws = Workspace(roots=[tmp_path])
    ws.tool_budget = 160
    with TestClient(ide_app(ws)) as c:
        r = c.post('/agent/budget', json={'tools': 4000})
        assert r.status_code != 200 or not r.json().get('ok')
        assert f'{TOOL_RANGE[0]} to {TOOL_RANGE[1]}' in r.text
        assert ws.tool_budget == 160, 'the refused value did not land'

def test_the_budget_survives_a_reload(tmp_path, monkeypatch):
    ws = Workspace(roots=[tmp_path])
    ws.tool_budget, ws.step_budget = 160, 40
    ws.save()
    assert Workspace.load(ws_path()).tool_budget == 160
    assert Workspace.load(ws_path()).step_budget == 40

def test_a_saved_budget_outside_the_range_falls_back_to_auto(tmp_path):
    "A workspace.json edited by hand, or written by a version with different bounds."
    ws = Workspace(roots=[tmp_path])
    ws.tool_budget = 160
    ws.save()
    d = json.loads(ws_path().read_text()); d['tool_budget'] = 9999
    ws_path().write_text(json.dumps(d))
    assert Workspace.load(ws_path()).tool_budget == 'auto'

def test_the_slash_command_and_the_setting_do_not_disagree(tmp_path):
    "`/tool-budget` is ramabana's and sets the attribute on one agent."
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as c:
        out = c.post('/agent/command', json={'line': '/tool-budget 240'}).json()
        assert '240' in out['text']
        assert ws.tool_budget == 240, 'the workspace followed the command'
        assert Workspace.load(ws_path()).tool_budget == 240, 'and it was saved'
        c.post('/agent/command', json={'line': '/tool-budget auto'})
        assert ws.tool_budget == 'auto'

def test_the_panel_can_ask_what_is_actually_in_force(tmp_path):
    ws = Workspace(roots=[tmp_path]); ws.tool_budget = 160
    with TestClient(ide_app(ws)) as c:
        d = c.get('/agent/budget/state').json()
        assert d['tools'] == 160 and d['tool_range'] == list(TOOL_RANGE)
        assert d['step_range'] == list(STEP_RANGE)

def test_huggingface_urls_are_saved_and_registered(tmp_path):
    p=tmp_path/'models.json'
    row=save_model({'name':'ornith-test','model_id':'https://huggingface.co/litert-community/Ornith-1.0-9B',
                    'runtime':'litert','ctx':128_000},p)
    assert row['model_id']=='litert-community/Ornith-1.0-9B'
    assert resolve('ornith-test').runtime=='litert'
    assert load_models(p)[0]['name']=='ornith-test'
    assert json.loads(p.read_text())[0]['ctx']==128_000

def test_hosted_model_ids_persist_without_secrets(tmp_path):
    p=tmp_path/'models.json'
    save_model({'name':'new-api-model','model_id':'openai/new-api-model','runtime':'remote','ctx':200_000,
                'base_url':'https://api.example.test/v1','api_key_env':'EXAMPLE_API_KEY'},p)
    spec=resolve('new-api-model')
    assert spec.model_id=='openai/new-api-model' and spec.config['base_url'].endswith('/v1')
    assert 'EXAMPLE_API_KEY' in p.read_text() and 'secret-value' not in p.read_text()
    delete_model('new-api-model',p)
    assert load_models(p)==[]

class Host_comple:
    def list_vars(self): return 'frame: DataFrame = DataFrame [18×4]\nthreshold: float = 0.73'

class Agent_comple:
    host = Host_comple()


def test_kosha_adds_dynamic_patch_methods_to_runtime_completion(tmp_path):
    class Store:
        def rows_where(self,*a,**kw):
            return [{'content':'def read_json(self:Path, encoding=None): pass',
                     'metadata':{'name':'read_json','mod_name':'fastcore.xtras.read_json',
                                 'docstring':'Read JSON from this path'}}]
    class Kosha:
        code_st=env_st=Store()
        def public_api(self,*a,**kw): return []
    s=Search(Sandbox([tmp_path])); s._k=Kosha(); s._k_tried=True
    code='from fastcore.all import Path\np: Path\np.re'
    out=s.merge_completions(code,len(code),{'from':len(code)-2,'matches':['read_text']})
    assert out['matches']==['read_text','read_json']
    assert out['graph'][0]['symbol']=='fastcore.xtras.read_json'

def test_audio_reaches_a_model_that_can_hear_it_and_is_carried_by_path_otherwise(tmp_path, monkeypatch):
    import ramabana.cli as rcli
    sound = tmp_path/'note.wav'
    sound.write_bytes(b'RIFF....WAVE')
    ws = Workspace(roots=[tmp_path])
    monkeypatch.setattr(rcli, 'accepts', lambda spec, kind: True)
    text, media = ws._attachment_context([str(sound)], object())
    assert media == [b'RIFF....WAVE'] and 'audio above is attached' in text
    monkeypatch.setattr(rcli, 'accepts', lambda spec, kind: False)
    text, media = ws._attachment_context([str(sound)], object())
    assert media == [] and 'attached by path only' in text and str(sound) in text

def test_audio_is_sent_when_the_model_capabilities_are_unknown(tmp_path, monkeypatch):
    "Withholding on an unknown is how not-knowing silently becomes a smaller agent."
    import ramabana.core as rcore
    sound = tmp_path/'note.mp3'
    sound.write_bytes(b'ID3')
    monkeypatch.setattr(rcore, '_caps', lambda model_id, runtime: None)
    ws = Workspace(roots=[tmp_path])
    _, media = ws._attachment_context([str(sound)], resolve('gpt-4.1'))
    assert media == [b'ID3']

def test_the_picker_says_what_a_model_takes_and_marks_the_ones_that_can_draw(monkeypatch):
    import ramabana.core as rcore
    from types import SimpleNamespace
    from leela.blocks.agent.models import mark_models
    caps = {'draws': SimpleNamespace(fmt=lambda: 'in: text image · out: text image', gen_image=True, gen_video=False),
            'talks': SimpleNamespace(fmt=lambda: 'modalities unknown', gen_image=False, gen_video=False)}
    monkeypatch.setattr(rcore, 'resolve', lambda name: name)
    monkeypatch.setattr(rcore, 'spec_caps', lambda spec: caps.get(spec))
    rows = mark_models([{'value': 'draws'}, {'value': 'talks'}, {'value': 'unresolvable'}])
    assert rows[0]['gen_image'] and rows[0]['modalities'] == 'in: text image · out: text image'
    assert not rows[1]['gen_image'] and rows[1]['modalities'] == 'modalities unknown'
    assert rows[2] == {'value': 'unresolvable'}, 'no one model may blank the picker'

def test_a_model_that_draws_is_marked_in_the_picker_itself():
    from tests.assets import JS
    assert "m.gen_image ? ' · draws' : ''" in JS

def test_a_video_job_persists_its_handle_and_is_drawn_once_when_it_finishes(tmp_path, monkeypatch):
    from leela.blocks.agent import video as V
    from leela.blocks.nb.nb import media_output
    monkeypatch.setenv('GEMINI_API_KEY', 'test-key')
    monkeypatch.setattr(V, '_start', lambda prompt, model, **kw: 'operations/abc')
    jobs = V.VideoJobs(tmp_path/'jobs.json')
    tools = {f.__name__: f for f in V.video_tools(None, session=str(tmp_path), jobs=jobs)}
    assert 'started' in tools['generate_video']('a cat, in the rain', seconds=30)
    row = jobs.all()[-1]
    assert (row['state'], row['op'], row['seconds']) == ('running', 'operations/abc', 8)
    assert V.VideoJobs(tmp_path/'jobs.json').get(row['id'][:4])['op'] == 'operations/abc', 'a handle outlives the process'
    monkeypatch.setattr(V, '_poll', lambda op: (False, '', ''))
    assert 'still generating' in tools['video_status'](row['id'])
    monkeypatch.setattr(V, '_poll', lambda op: (True, 'https://example/v.mp4', ''))
    monkeypatch.setattr(V, '_fetch', lambda uri: b'MP4BYTES')
    out = tools['video_status'](row['id'])
    saved = Path(jobs.get(row['id'])['path'])
    assert saved.read_bytes() == b'MP4BYTES' and str(saved) in out
    assert jobs.unshown() == [{'mime': 'video/mp4', 'data': b'MP4BYTES'}]
    assert jobs.unshown() == [], 'an artifact is drawn once, not on every later turn'
    assert media_output({'mime': 'video/mp4', 'data': b'MP4BYTES'})['data']['text/html'].startswith('<video controls')

def test_a_failed_video_job_keeps_its_id_and_says_why(tmp_path, monkeypatch):
    from leela.blocks.agent import video as V
    monkeypatch.setenv('GEMINI_API_KEY', 'test-key')
    monkeypatch.setattr(V, '_start', lambda prompt, model, **kw: 'operations/abc')
    monkeypatch.setattr(V, '_poll', lambda op: (True, '', 'the prompt was rejected'))
    jobs = V.VideoJobs(tmp_path/'jobs.json')
    tools = {f.__name__: f for f in V.video_tools(None, session=str(tmp_path), jobs=jobs)}
    tools['generate_video']('something forbidden')
    id = jobs.all()[-1]['id']
    out = tools['video_status'](id)
    assert id in out and 'failed' in out and 'the prompt was rejected' in out
    assert jobs.get(id)['state'] == 'failed' and jobs.unshown() == []
    assert 'no such video job' in tools['video_status']('nope')

def test_video_generation_is_offered_only_where_there_is_a_credential(tmp_path, monkeypatch):
    from leela.blocks.agent import video as V
    assert not V.video_available(), 'the suite runs with no provider credentials'
    tools = {f.__name__: f for f in V.video_tools(None, session=str(tmp_path), jobs=V.VideoJobs(tmp_path/'j.json'))}
    assert 'GEMINI_API_KEY' in tools['generate_video']('a cat')
    monkeypatch.setenv('GEMINI_API_KEY', 'test-key')
    assert V.video_available() and V.video_caps()['out'] == ('video',)

def test_veo_is_described_here_because_litellms_table_has_no_entry_for_it():
    from leela.blocks.agent.video import DFLT_VIDEO, video_caps
    assert video_caps(DFLT_VIDEO)['provider'] == 'gemini'
    assert video_caps('no-such-model') is None


def test_the_turn_pictures_become_data_urls_a_browser_can_draw():
    "A tool result is a path, and a browser cannot draw a filename."
    import base64
    from leela.blocks.agent.turns import turn_media
    class A: turn_media = [{'mime': 'image/png', 'data': b'\x89PNG\r\n\x1a\nx'},
                           {'mime': 'video/mp4', 'data': b'ftyp'}, {'mime': 'image/png', 'data': b''}]
    rows = turn_media(A())
    assert [r['mime'] for r in rows] == ['image/png', 'video/mp4']   # the empty one is dropped
    assert rows[0]['url'].startswith('data:image/png;base64,')
    assert base64.b64decode(rows[0]['url'].split(',', 1)[1]) == b'\x89PNG\r\n\x1a\nx'
    class B: turn_media = []
    assert turn_media(B()) == []
    class C: pass
    assert turn_media(C()) == []

def test_a_steer_rides_the_next_tool_result(tmp_path):
    """The path the UI actually promises -- 'applies after current call' -- and the only one of
    the three with no test. It is what a steer queued mid-call takes."""
    (tmp_path/'a.py').write_text('x = 1\n')
    ws = Workspace(roots=[tmp_path], approvals='auto')
    view = next(t for t in ws.ai.tools if t.__name__ == 'view_file')
    ws.approvals.queue_steer('read the test first')
    out = str(view(str(tmp_path/'a.py')))
    assert out.endswith('User steering for the next decision: read the test first')
    assert ws.approvals.state()['queued_steer'] == '', 'and it is not delivered twice'
    assert 'steering' not in str(view(str(tmp_path/'a.py'))).lower()


def test_delegation_never_gets_the_git_write_tools(monkeypatch):
    """Leela's Git writes are kept off the delegation surface. Filtering `_plain` only covered the
    branch that returns it: a sub-agent sized to a different model is built from `registry.tools`,
    and a writing one is handed the recorded wrappers. Neither passes through `_plain`, so both
    arrived holding `git_push`."""
    from leela.blocks.agent.ai import GIT_WRITE_TOOLS, Assistant

    def git_push(): pass
    def git_checkout(): pass
    def git_pull(): pass
    def git_status(): pass
    def view_file(): pass

    a = Assistant.__new__(Assistant)          # the method reads nothing off the instance
    branches = ([git_push, git_status, view_file],      # `_plain`, the branch that was covered
                [git_checkout, git_pull, view_file],    # `_subtools`, built from the registry
                [git_push, git_checkout, git_status],   # the recorded wrappers a writer is given
                [])
    for branch in branches:
        monkeypatch.setattr(Agent, '_sub_plain', lambda self, b=branch: list(b))
        names = {f.__name__ for f in a._sub_plain()}
        assert not (names & GIT_WRITE_TOOLS), f'git writes reached delegation via {branch}'
        assert names == {f.__name__ for f in branch} - GIT_WRITE_TOOLS, 'and nothing else was taken'

    # Reading git is not writing git, and must survive.
    monkeypatch.setattr(Agent, '_sub_plain', lambda self: [git_status, view_file])
    assert {f.__name__ for f in a._sub_plain()} == {'git_status', 'view_file'}


def test_stopping_a_cloud_turn_returns_its_terminal_run_state(tmp_path):
    ws = Workspace(roots=[tmp_path])
    a = ws.ai
    assert a.cancel()['state'] == 'idle'
    backend = type('Backend', (), {'cancel': lambda self: False})()
    run = a._new_run('cloud request'); run.start(backend)
    result = a.cancel(run.id, grace=0)
    assert result['state'] == 'detached'
    assert ws.approvals.state()['stopping'] is True
    assert a.status()['runs'] == []

def test_a_cancelled_turn_refuses_the_calls_still_to_come(tmp_path):
    "Approval cancellation remains part of Stop after provider cancellation moves to Ramabana."
    ws = Workspace(roots=[tmp_path], approvals='auto')
    ws.approvals.stop()
    tc = {'id': 'c1', 'function': {'name': 'list_files', 'arguments': {'path': ''}}}
    assert ws.approvals.gate(tc) is True
    assert tc['function']['name'] == 'user_steering'
    assert 'stopped this turn' in tc['function']['arguments']['instruction']

def test_the_next_turn_clears_the_stop(tmp_path):
    ws = Workspace(roots=[tmp_path], approvals='auto')
    ws.approvals.stop()
    ws.ai._prepare('carry on')
    assert ws.approvals.state()['stopping'] is False

def test_stop_and_send_next_returns_the_exact_terminal_run(tmp_path):
    ws = Workspace(roots=[tmp_path])
    ws.ai.cancel_grace = 0
    backend = type('Backend', (), {'cancel': lambda self: False})()
    run = ws.ai._new_run('cloud request'); run.start(backend)
    with TestClient(ide_app(ws)) as c:
        d = c.post('/agent/steer', json={'text': 'read the test first', 'force': True}).json()
    assert d['ok'] and d['forced'] and d['run']['id'] == run.id
    assert d['run']['state'] == 'detached'
    assert d['text'] == 'read the test first'
    assert d['queued_steer'] == ''


def test_agent_run_routes_return_structured_states(tmp_path):
    ws = Workspace(roots=[tmp_path])
    ws.ai.cancel_grace = 0
    backend = type('Backend', (), {'cancel': lambda self: False, 'close': lambda self: None})()
    root = ws.ai._new_run('root'); root.start(backend)
    child = root.child('investigate', 'copilot'); child.start(backend)
    with TestClient(ide_app(ws)) as c:
        status = c.get('/agent/status').json()
        assert status['runs'][0]['children'][0]['id'] == child.id
        cancelled = c.post(f'/agent/runs/{child.id}/cancel', json={}).json()
        assert cancelled['ok'] and cancelled['id'] == child.id and cancelled['state'] == 'detached'
        assert ws.approvals.state()['stopping'] is False, 'a child Stop must not stop its parent or siblings'
        stopped = c.post('/agent/stop', json={'run_id': root.id}).json()
        assert stopped['ok'] and stopped['id'] == root.id and stopped['state'] == 'detached'
        terminated = c.post(f'/agent/runs/{root.id}/terminate', json={}).json()
        assert terminated['ok'] and terminated['state'] == 'terminated'

@pytest.mark.asyncio
async def test_workspace_shutdown_cancels_agent_runs_before_close(tmp_path):
    ws = Workspace(roots=[tmp_path])
    a, order = ws.ai, []
    a.cancel_grace = 0
    backend = type('Backend', (), {
        'cancel': lambda self: order.append('cancel') or False,
        'close': lambda self: order.append('close')})()
    run = a._new_run('shutdown'); run.start(backend)
    a._backends[('fake', 'shutdown')] = backend
    await ws.shutdown()
    assert order[:2] == ['cancel', 'close']
    assert run.state == 'detached'
