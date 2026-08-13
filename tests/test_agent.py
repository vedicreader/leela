"""Tests for the agent harness.

Nothing here loads a model. That is the same bargain `tests/conftest.py` strikes with
kernels and for the same reason: what these tests are about is the harness -- routing,
approval, compaction arithmetic, skill discovery, the activity stream, and the tool
wrappers -- and a real engine would put gigabytes and minutes in front of all of it while
testing none of it.

The two places a model genuinely matters are covered without one. `FakeBackend`
implements the `Backend` protocol over a scripted list of replies, which is enough to
drive a turn end to end; and the fastllm approval patch is exercised against the real
`fastllm.chat._alite_call_func`, because that patch's whole job is to fit a package we do
not control.
"""

import asyncio
import threading
import time

import pytest

# The harness is five modules now; these names are the concerns the tests were written
# against, aliased so each test still says which concern it is about.
from leela.agent import agent as activity, agent as hitl, agent as fastllm_hitl
from leela.agent import core as models, runtime as compact, tools as skills
from leela.agent.runtime import Backend, Usage
from leela.agent.agent import Agent, prompt_directives, tool_plan
from leela.agent.tools import Registry, load
from leela.agent.tools import Host, NullHost
from leela.agent.tools import WRITE_TOOLS, tools_for


# ---------------------------------------------------------------------------
# a host, and a backend, with nothing behind either
# ---------------------------------------------------------------------------
class MemHost(NullHost):
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
    a = Agent(host or MemHost({'/proj/a.py': 'def a(): pass\n'}), extensions=False, **kw)
    be = FakeBackend(models.ModelSpec('fake', 'fake', 'fake/model', ctx=1000), replies=replies)
    a._be = lambda job='turn': be
    a._be_or_none = lambda job='turn': be
    return a, be


# ---------------------------------------------------------------------------
# the seam
# ---------------------------------------------------------------------------
def test_agent_package_does_not_import_leela():
    """The harness lives inside leela now, but it must still not reach back into the IDE.

    Not layering pedantry: `testing.MemHost` is a complete host in a dict, and the whole
    loop is tested against it. The moment a tool imports `leela.workspace`, that stops
    being true and the harness can only be tested by starting an IDE."""
    import pathlib, re
    import leela.agent as pkg
    bad = []
    for p in pathlib.Path(pkg.__file__).parent.glob('*.py'):
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if re.match(r'\s*(from|import)\s+leela\b', line): bad.append(f'{p.name}:{i}: {line.strip()}')
            if re.match(r'\s*from\s+\.\.', line): bad.append(f'{p.name}:{i}: {line.strip()}')
    assert not bad, 'leela.agent must not import from leela:\n' + '\n'.join(bad)


def test_null_host_offers_only_what_it_supports():
    "A capability the host does not have must not become a tool the model keeps failing to call."
    names = {t.__name__ for t in tools_for(NullHost(['/x']))}
    assert 'search_code' in names and 'view_file' in names
    assert 'run_python' not in names and 'notebook_cells' not in names


def test_mem_host_gets_the_session_tools_it_supports():
    names = {t.__name__ for t in tools_for(MemHost())}
    assert 'run_python' not in names   # list_vars/terminal_text are still absent, so the group drops


# ---------------------------------------------------------------------------
# routing
# ---------------------------------------------------------------------------
def test_cheap_jobs_stay_local_when_the_turn_goes_to_the_cloud(monkeypatch):
    "The whole argument for routing: pointing the turn at a frontier model must not move completions."
    monkeypatch.delenv('LEELA_MODEL', raising=False)
    r = models.Routing(turn='gemma-e2b')
    r.set('gemma-12b')                       # stand-in for a cloud model, no network needed
    assert r.spec('turn').name == 'gemma-12b'
    # Asserted against the policy rather than against model names: which small model is
    # cheapest here depends on the machine, and the claim being tested is that the turn
    # moving does not move anything else. `None` in the policy is not "unset" but "whatever
    # `oneshot` says", so that is what the job has to still be on.
    for job, name in models.DEFAULT_POLICY.items():
        if job == 'turn': continue
        assert r.spec(job).name == (name or models.DEFAULT_POLICY['oneshot']), job
        assert r.spec(job).local, job


def test_env_overrides_a_single_job(monkeypatch):
    monkeypatch.setenv('LEELA_MODEL_SUMMARY', 'gemma-12b')
    r = models.Routing(turn='gemma-e2b')
    assert r.spec('summary').name == 'gemma-12b'
    assert r.spec('classify').name == models.DEFAULT_POLICY['oneshot'], 'the other cheap jobs stay put'


def test_unknown_bare_name_is_an_error_not_a_guess():
    "Silently running a typo on a frontier model is the kind of surprise that shows up on a bill."
    with pytest.raises(KeyError): models.resolve('sonnnet')


def test_a_vendor_slash_model_spec_is_taken_at_face_value():
    s = models.resolve('somevendor/some-model')
    assert (s.backend, s.model_id) == ('remote', 'somevendor/some-model')
    assert s.ctx > 0


# ---------------------------------------------------------------------------
# re-briefing when the open folders change
# ---------------------------------------------------------------------------
def test_backend_refresh_updates_sp_and_tools_in_place(spec):
    "A running backend keeps its engine and conversation; only the briefing and tools change."
    be = FakeBackend(spec, sp='old', tools=[])
    be.start()
    hist_before = be.hist
    be.refresh('new briefing', [lambda: None])
    assert be.sp == 'new briefing' and len(be.tools) == 1
    assert be.refreshed == 1            # re-briefed in place
    assert be.chat is be               # engine/conversation not torn down
    assert be.hist is hist_before      # conversation history preserved


def test_backend_refresh_before_start_only_records(spec):
    "Refreshing a backend that never started just stores the values for its eventual start."
    be = FakeBackend(spec, sp='old')
    be.refresh('new', [])
    assert be.sp == 'new' and not hasattr(be, 'refreshed')


def test_local_and_cloud_backends_share_an_explicit_tool_loop_budget():
    from leela.agent.runtime import FastllmBackend, MAX_STEPS, RishiBackend
    local = models.ModelSpec('local', 'rishi', 'local/model', ctx=1000)
    cloud = models.ModelSpec('cloud', 'fastllm', 'cloud/model', ctx=1000)
    assert RishiBackend(local).max_steps == MAX_STEPS
    assert FastllmBackend(cloud).max_steps == MAX_STEPS


def test_agent_refresh_rebriefs_a_running_turn_backend():
    "Opening a folder reaches the live conversation: the briefing names it, without a reload."
    host = MemHost({'/proj/a.py': 'def a(): pass\n'})
    a = Agent(host, extensions=False, subagents=False)
    spec = a.routing.spec('turn')
    be = FakeBackend(spec, sp=a.system_prompt(), tools=a.tools)
    be.start()
    a._backends[(spec.backend, spec.model_id)] = be
    assert '/proj' in be.sp and '/newproj' not in be.sp
    host._roots.append('/newproj')                     # a folder opened mid-chat
    a.refresh()
    assert be.chat is be and be.refreshed == 1         # same engine, re-briefed in place
    assert '/newproj' in be.sp                         # the briefing now names it
    assert a._skills is not None and a._tools is not None   # caches rebuilt, not left empty


def test_agent_refresh_is_a_noop_when_nothing_is_running():
    "No turn backend built yet means nothing to re-brief, but the caches still reset for next time."
    a = Agent(MemHost(), extensions=False, subagents=False)
    _ = a.tools
    a.refresh()
    assert a._tools is None             # will rebuild lazily with the new roots


# ---------------------------------------------------------------------------
# approval and editable execution checkpoints
# ---------------------------------------------------------------------------
def test_agent_state_template_teaches_rules_routing_tools_and_maintenance():
    from leela.blocks.agent.ai import STATE_TEMPLATE
    for heading in ('Agent charter', 'Hard boundaries', 'Routing rules', 'Tool practices',
                    'Verification', 'Progress', 'Critical context', 'State maintenance'):
        assert heading in STATE_TEMPLATE
    assert 'Never claim a tool ran' in STATE_TEMPLATE
    assert 'Update this state after' in STATE_TEMPLATE


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


def test_rejection_ignores_rewritten_or_malformed_call_fields():
    from leela.blocks.agent.ai import Interventions
    ap = Interventions(tools={'edit_file'}, mode='ask', control='directed')
    # Put a request in flight directly to exercise the answer boundary without involving
    # a worker thread: rejection must preserve the proposal rather than accept form edits.
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
    from leela.blocks.agent.ai import Interventions
    from leela.blocks.nb.nb import Cell, Notebook
    from leela.workspace import Workspace
    p = tmp_path/'sample.ipynb'; Notebook([Cell(source='x = 1')]).save(p)
    ws = Workspace(roots=[tmp_path], approvals='auto'); a = ws.ai
    a.approvals.control = 'autopilot'
    tool = next(t for t in a.tools if t.__name__ == 'notebook_cells')
    # Simulate the backend approval hook: it records tool/args for matching, while the
    # Activity constructor must receive those positionally only once.
    tc = {'id': 'call_notebook', 'function': {'name': 'notebook_cells', 'arguments': {'path': str(p)}}}
    assert a.approvals.gate(tc)
    out = tool(path=str(p))
    assert 'x = 1' in out
    row = a.activity.rows()[-1]
    assert row['action_id'] == 'call_notebook' and row['tool'] == 'notebook_cells'


def test_new_agent_setup_keeps_file_and_notebook_access_inside_workspace(tmp_path):
    from leela.blocks.nb.nb import Cell, Notebook
    from leela.workspace import Workspace
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


def test_activity_uses_the_backend_tool_call_id_across_approval_and_execution():
    # Interventions are tested independently; this assertion locks the common event shape
    # that lets the browser replace proposal with result without matching by tool name.
    act = activity.Activity(); act.mark('turn-1')
    row = act.start('search_code', {'query': 'needle'}, action_id='call_exact', branch_id='branch_a')
    assert row.dict()['action_id'] == 'call_exact'
    assert row.dict()['turn_id'] == 'turn-1' and row.dict()['branch_id'] == 'branch_a'


def test_file_checkpoint_rolls_back_only_its_unchanged_output():
    from leela.blocks.agent.ai import Interventions
    host = MemHost({'/proj/a.py': 'before'})
    ap = Interventions(tools={'create_file'}, mode='auto', control='autopilot', host=host)
    decision = ap.request('create_file', {'path': '/proj/a.py', 'text': 'after'})
    host.write('/proj/a.py', 'after'); ap.observe_result(True)
    assert decision.dict()['rollback']
    assert ap.rollback(decision.id) == '/proj/a.py'
    assert host.text_at('/proj/a.py') == 'before'
    host.write('/proj/a.py', 'someone else changed it')
    with pytest.raises(ValueError, match='changed after'): ap.rollback(decision.id)


def test_queued_steering_is_consumed_exactly_once():
    from leela.blocks.agent.ai import Interventions
    ap = Interventions(control='guided')
    ap.queue_steer('inspect the existing component first')
    assert ap.state()['queued_steer'] == 'inspect the existing component first'
    assert ap.consume_steer() == 'inspect the existing component first'
    assert ap.consume_steer() == ''


def test_ungated_tools_run_without_asking():
    ap = hitl.Approvals(tools={'edit_file'})
    assert ap.gate({'function': {'name': 'search_code', 'arguments': {'query': 'x'}}})


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


def test_nothing_listening_refuses_immediately_rather_than_hanging():
    "A blocked worker thread is a hung IDE. Refusing fast is a bad answer that is at least an answer."
    ap = hitl.Approvals(tools={'edit_file'}, timeout=30)
    t0 = time.time()
    d = ap.gate({'function': {'name': 'edit_file', 'arguments': {'path': 'a.py'}}})
    assert not d and time.time() - t0 < 1
    assert 'nothing is listening' in d.reply()


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


def test_a_refusal_never_changes_the_policy_even_if_session_is_requested():
    ap = hitl.Approvals(tools={'edit_file'}, mode='ask')
    a = hitl.Ask(tool='edit_file'); ap.current = a
    ap.answer(a.id, False, 'not this file', session=True)
    assert ap.mode == 'ask' and not a


def test_an_approval_note_rides_back_with_the_result():
    ap = hitl.Approvals(tools={'edit_file'}, mode='auto')
    d = ap.request('edit_file', {'path': 'a.py'})
    assert d and d.reply() is None          # nothing to say when it was simply approved
    d2 = hitl.Ask(tool='edit_file').resolve(True, 'keep the docstring')
    assert 'keep the docstring' in d2.reply()


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


def test_preview_shows_what_would_change():
    p = hitl.preview_for('edit_file', {'path': 'a.py', 'commands': '[["12|ab|","s","old","new"]]'})
    assert '12|ab|' in p and 'old' in p and 'new' in p
    p2 = hitl.preview_for('create_file', {'path': 'b.py', 'text': 'x = 1'})
    assert 'new file' in p2 and 'x = 1' in p2


def test_cancelling_a_turn_releases_a_waiting_approval():
    ap = hitl.Approvals(tools={'edit_file'}, timeout=30)
    stop = ap.listen()
    threading.Thread(target=lambda: (time.sleep(0.05), ap.cancel_all()), daemon=True).start()
    d = ap.gate({'function': {'name': 'edit_file', 'arguments': {}}})
    stop()
    assert not d and 'cancelled' in d.reply()


# Hosted models now use Rishi's shared tool loop; no FastLLM monkey patch lives here.
def test_fastllm_compatibility_shim_reports_rishi_approval():
    assert fastllm_hitl.apply() and fastllm_hitl.applied()
    assert 'rishi.remote' in fastllm_hitl.note()


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
    # On-device models are grouped by the runtime that runs them, and which runtimes are
    # installed is a property of the machine; that any of them is offered is not.
    assert any('on device' in r['source'] for r in rows)
    assert 'anthropic' not in providers
    assert any(r['value'].startswith('codex/') for r in rows)
    # Only provenance is exposed; no credential value is returned to the browser.
    assert all('present' not in str(r) for r in rows)


def test_prompt_directives_select_tools_and_load_named_skills_without_matching_paths():
    def research(query: str): return query
    skill = skills.Skill('nbdev', 'md', 'Notebook development', '/skills/nbdev', 'full instructions')
    tools, loaded = prompt_directives(
        'add test cells /research nbdev projects then use /nbdev, not /Users/me', [research], [skill])
    assert tools == [('research', 'nbdev projects then use')]
    assert loaded == [skill]


def test_explicit_research_uses_only_the_request_not_composed_notebook_context():
    class ResearchHost(MemHost):
        def __init__(self): super().__init__(); self.queries = []
        def research(self, query): self.queries.append(query); return 'grounded research'
    host = ResearchHost()
    # A named model, because `research` is one of the tools a small window gives up: left on
    # the default local model this asserts nothing about directives and everything about ctx.
    a, be = fake_agent(host=host, replies=['done'], model='sonnet')
    composed = a.compose('add tests /research nbdev test cells', context='<cell>implementation details</cell>',
                         context_path='/proj/nbs/core.ipynb')
    assert a.ask(composed) == 'done'
    assert host.queries == ['nbdev test cells']
    assert '<preflight-tool name="research">' in str(be.sent[-1])
    assert a.history[-1]['plan']['tools'] == ['research']


def test_create_skill_writes_standard_project_skill_without_overwriting():
    host = MemHost()
    create = next(t for t in tools_for(host, lambda: []) if t.__name__ == 'create_skill')
    result = create('notebook-tests', 'How this project tests notebooks', 'Add one red cell, then make it green.')
    path = '/proj/.agents/skills/notebook-tests/SKILL.md'
    assert result.startswith('created ') and path in host.files
    assert 'name: "notebook-tests"' in host.files[path]
    assert 'description: "How this project tests notebooks"' in host.files[path]


def test_tool_planner_routes_repo_and_current_web_questions():
    assert tool_plan('what default model does leela use?')[0] == 'repo'
    assert tool_plan('where is approval implemented in this repo?')[0] == 'repo'
    assert tool_plan('change the code_clusters method to accept a store')[0] == 'repo'
    assert tool_plan('what do the current pandas release notes say?')[0] == 'web'
    assert tool_plan('what is 2 + 2?')[0] == 'direct'


def test_search_results_tell_the_agent_to_address_notebooks_by_cell_id():
    host = MemHost({'/proj/nbs/core.ipynb': 'code_clusters method'})
    search = next(t for t in tools_for(host) if t.__name__ == 'search_code')
    out = search('code_clusters')
    assert '/proj/nbs/core.ipynb:1' in out
    assert 'use this exact path with notebook_cells, then view_cell/edit_cell' in out


def test_agent_keeps_inspectable_conversation_history():
    host = MemHost({'/proj/models.py': "DFLT_LOCAL = 'gemma-e2b'\n"})
    a, be = fake_agent(host=host, replies=['the answer'])
    assert a.ask('what default model does leela use?') == 'the answer'
    assert '<preflight-tool name="search_code">' in str(be.sent[-1])
    turn = a.history[-1]
    assert turn['prompt'] == 'what default model does leela use?'
    assert turn['reply'] == 'the answer' and turn['plan']['route'] == 'repo'
    assert turn['model']


# ---------------------------------------------------------------------------
# compaction
# ---------------------------------------------------------------------------
def test_threshold_leaves_room_for_one_more_reply():
    assert compact.threshold(200_000, 16_384) == 200_000 - 16_384
    assert compact.threshold(0) is None
    assert compact.should_compact(190_000, 200_000)
    assert not compact.should_compact(100_000, 200_000)


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


def test_pending_notebook_context_is_untouched_when_it_fits():
    prompt = '<notebook>\n<cell id="a" type="code" compact="discard">all details</cell>\n</notebook>'
    assert compact.compact_notebook_context(prompt, lambda text: True) == prompt


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
    # the reorientation note is the aai-coding idea, and its value is in being specific
    assert 'kernel process was not touched' in head
    assert 'do not re-import' in head


def test_a_dead_kernel_is_not_promised():
    assert 'clean namespace' in compact.reorient(kernel_alive=False)


def test_prompt_notices_fire_where_they_should():
    assert compact.prompt_notices('where is this handled?') == [compact.Q_NOTICE]
    assert compact.APPROVAL_NOTICE in compact.prompt_notices('go')
    assert compact.APPROVAL_NOTICE in compact.prompt_notices('ok.')
    assert compact.BTW_NOTICE in compact.prompt_notices('BTW can you also check the tests')
    assert compact.ACTION_NOTICE in compact.prompt_notices('add a test for this')
    assert compact.ACTION_NOTICE in compact.prompt_notices('scale the numeric columns as df_norm')


def test_notices_ride_along_with_the_prompt():
    assert '<system-reminder>' in compact.notices_block('what does this do?')
    assert compact.ACTION_NOTICE in compact.notices_block('add a test')


# ---------------------------------------------------------------------------
# skills
# ---------------------------------------------------------------------------
def test_pyskills_are_discovered_from_installed_packages():
    """The test of whether this feature is real rather than architectural: installing a
    package that publishes the entry point should hand the agent its skill, no code here."""
    found = {s.name: s for s in skills.discover()}
    assert 'exhash' in found, 'exhash ships the editing reference leela used to paste by hand'
    assert found['exhash'].source == 'pyskill'
    assert found['exhash'].text().strip()


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
    # No single description may dominate, or the budget stops surviving new skills: some are
    # written as long trigger-word lists, so the index clips each one and `read_skill` has the rest.
    rows = [l for l in idx.splitlines() if l.startswith('- `')]
    assert rows and all(len(l) <= 60 + skills.SKILL_DESC_MAX for l in rows), max(rows, key=len)


def test_find_refuses_to_guess_between_two_matches():
    from leela.agent.tools import Skill, find
    ss = [Skill('editskill', 'pyskill'), Skill('editor', 'pyskill')]
    assert find(ss, 'edit') is None
    assert find(ss, 'editskill').name == 'editskill'


def test_frontmatter_parses_without_a_yaml_dependency():
    meta, body = skills.frontmatter('---\nname: x\ndescription: "y z"\n---\nbody\n')
    assert meta == {'name': 'x', 'description': 'y z'} and body.strip() == 'body'


# ---------------------------------------------------------------------------
# activity
# ---------------------------------------------------------------------------
def test_summaries_read_like_what_a_person_would_say():
    s = activity.summarise
    assert s('search_code', {'query': 'AgentSession'}) == 'Search AgentSession'
    assert s('view_file', {'path': 'leela/ai.py', 'start': 240, 'end': 290}) == 'View leela/ai.py:240-290'
    assert s('read_url', {'url': 'https://github.com/AnswerDotAI/ipymini'}).startswith('Web fetch: https://')
    assert s('edit_file', {'path': 'a.py'}) == 'Edit a.py'


def test_activity_fires_at_the_start_of_a_call_not_only_at_the_end():
    "Showing ⏳ while a fetch happens is the difference between looking alive and looking stuck."
    seen = []
    act = activity.Activity(on_change=lambda a: seen.append((a.summary, a.done)))
    a = act.start('read_url', {'url': 'https://x'})
    act.finish(a, 'the page')
    assert [d for _, d in seen] == [False, True]
    assert a.detail == 'the page' and a.done


def test_activity_markdown_folds_the_result():
    act = activity.Activity()
    act.mark()
    act.finish(act.start('search_code', {'query': 'q'}), 'a hit')
    md = act.md(mark=0)
    assert '<details>' in md and 'Search q' in md and 'a hit' in md


def test_a_fence_in_a_result_cannot_escape_the_fold():
    act = activity.Activity()
    a = act.start('view_file', {'path': 'a.md'})
    act.finish(a, 'text\n```\nfenced\n```\n')
    assert '\n```\n' not in a.md().split('```\n', 1)[1].rsplit('```', 1)[0]


# ---------------------------------------------------------------------------
# tools, recorded
# ---------------------------------------------------------------------------
def test_wrapping_a_tool_keeps_the_schema_the_model_reads():
    """Both backends build their tool schema from the signature and docstring, so the
    recorder must be transparent to `inspect` -- or every tool arrives as `(*args, **kw)`."""
    import inspect
    a, _ = fake_agent()
    t = next(t for t in a.tools if t.__name__ == 'view_file')
    assert t.__doc__ and 'lineno|hash|content' in t.__doc__
    assert list(inspect.signature(t).parameters) == ['path', 'start', 'end']


def test_changes_report_the_file_not_the_claim():
    "A tool that reported success and changed nothing must not appear in the diff."
    host = MemHost({'/proj/a.py': 'x = 1\n'})
    a, _ = fake_agent(host)
    create = next(t for t in a.tools if t.__name__ == 'create_file')
    a.before.clear()
    create(path='/proj/a.py', text='x = 1\n')          # writes the same bytes back
    assert a.changes() == {}
    create(path='/proj/a.py', text='x = 2\n')
    assert a.changes() == {'/proj/a.py': ('x = 1\n', 'x = 2\n')}


def test_a_turn_records_its_activity_and_usage():
    a, be = fake_agent(replies=['done'])
    assert a.ask('hello') == 'done'
    assert a.use.total == 15
    assert be.sent and 'hello' in str(be.sent[0])


def test_a_question_gets_the_answer_first_notice():
    "A question is routed to an answer, not to the work it implies."
    a, be = fake_agent(replies=['because x'])
    a.ask('why does this break?')
    assert a.history[-1]['plan']['route'] == 'direct'
    assert 'Answer directly' in str(be.sent[0])


def test_write_tools_are_the_ones_approval_draws_its_line_around():
    # The core is shared with ramabana, so the set also covers the tools leela does not
    # offer: deleting a standing reminder and spending money in a trolley are both things
    # a person should get to see before they happen.
    assert {'edit_file', 'replace_text', 'create_file', 'edit_cell', 'add_cell', 'run_python',
            'run_shell', 'memory_forget', 'create_skill',
            'cancel_watch', 'cart_add', 'cart_remove'} == set(WRITE_TOOLS)


# ---------------------------------------------------------------------------
# sub-agents
# ---------------------------------------------------------------------------
def test_a_subagent_never_gets_a_write_tool():
    "A delegated question is a question. An agent nobody is watching should not be editing files."
    from leela.agent.tools import read_only
    a, _ = fake_agent()
    names = {t.__name__ for t in read_only(a.tools)}
    assert not (names & WRITE_TOOLS)
    assert 'search_code' in names


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
    assert len(be.spawned) == 1 and be.hist == []      # nothing leaked into the parent


# ---------------------------------------------------------------------------
# extensions
# ---------------------------------------------------------------------------
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


def test_an_unknown_hook_name_is_an_error():
    with pytest.raises(KeyError): Registry().on('after_lunch', lambda: None)


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def test_commands_exist_once_for_both_frontends():
    a, _ = fake_agent()
    assert {'model', 'cost', 'compact', 'skills', 'tools', 'reload'} <= set(a.commands())
    assert a.command('nonsense') is None
    assert 'tok' in a.command('cost') or a.command('cost') is not None


def test_the_model_command_reports_the_whole_policy():
    a, _ = fake_agent()
    out = a.command('model')
    for job in models.JOBS: assert job in out


def test_usage_subtraction_produces_a_non_negative_turn_delta():
    before = Usage(model='m', input=10, output=4, total=14, cost=.01, turns=1)
    after = Usage(model='m', input=18, output=7, total=25, cost=.016, turns=2)
    delta = after - before
    assert (delta.input, delta.output, delta.total, round(delta.cost, 3), delta.turns) == (8, 3, 11, .006, 1)


def test_usage_adds_up_across_models():
    u = Usage(model='a', input=1, output=2, total=3, cost=0.5) + Usage(model='b', input=1, output=1, total=2, cost=0.25)
    assert (u.total, u.cost, u.model) == (5, 0.75, 'b')
    assert '$0.75' in repr(u)


# ---------------------------------------------------------------------------
# the binding: approval as a conversation in the notebook
# ---------------------------------------------------------------------------
def test_an_approval_exchange_is_written_into_the_notebook():
    """The request, the refusal and the reason land as cells beside the prompt that caused
    them, so reading the notebook top to bottom reads as what actually happened."""
    from leela.blocks.nb.nb import Cell, Notebook
    from leela.workspace import Workspace
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
    d = ws.approvals.gate({'function': {'name': 'edit_file', 'arguments': {'path': 'gen.py'}}})
    stop()

    assert not d and 'that file is generated' in d.reply()
    states = [(c.cell_type, (c.approval or {}).get('state')) for c in nb.cells]
    assert states == [('prompt', None), ('markdown', 'pending'), ('markdown', 'refused')]
    assert 'that file is generated' in nb[2].source


def test_workspace_path_refusal_names_the_files_that_are_open(tmp_path):
    from leela.blocks.agent.ai import WorkspaceHost
    from leela.workspace import Workspace
    p = tmp_path/'dialog.ipynb'
    p.write_text('{}')
    ws = Workspace(roots=[tmp_path])
    ws.open(p)
    with pytest.raises(Exception) as e: WorkspaceHost(ws).check('/Users/719/dialog.ipynb')
    assert str(p) in str(e.value) and 'open files' in str(e.value)


def test_workspace_agent_reaches_the_live_kernel_inspector():
    from leela.blocks.agent.ai import WorkspaceHost
    from leela.workspace import Workspace

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


def test_a_workspace_host_hides_what_the_workspace_cannot_do():
    "No kernel session bound yet means no run_python offered, not a run_python that always fails."
    from leela.blocks.agent.ai import WorkspaceHost
    from leela.workspace import Workspace
    h = WorkspaceHost(Workspace(roots=[]))
    with pytest.raises(NotImplementedError): h.run_python('1')
    assert 'run_python' not in {t.__name__ for t in tools_for(h)}


# ---------------------------------------------------------------------------
# streaming
# ---------------------------------------------------------------------------
def test_a_stream_yields_before_it_finishes(spec):
    "The whole point. A stream that only yields at the end is a blocking call with extra steps."
    from tests.fakemodel import ScriptedBackend, Step
    be = ScriptedBackend(steps=[Step(text='one two three')], token_delay=0)
    be.start()
    got = list(be.stream('hi'))
    assert len(got) == 3 and ''.join(got).split() == ['one', 'two', 'three']


def test_notebook_context_names_the_open_file_and_separates_the_user_request():
    a, _ = fake_agent()
    msg = a.compose('q', context='CTX', context_path='/work/dialog.ipynb')
    assert '<notebook path="/work/dialog.ipynb">' in msg
    assert '<user-request>\nq\n</user-request>' in msg


def test_agent_prompt_bar_accepts_the_open_notebook_context(tmp_path):
    from leela.workspace import Workspace
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


def test_text_only_local_agent_does_not_send_image_bytes():
    a = Agent(MemHost(), model='gemma-e4b', extensions=False, local_multimodal=False)
    msg = a.compose('describe it', image=b'not-an-image')
    assert isinstance(msg, str)
    assert 'omitted' in msg and 'describe it' in msg


def test_local_multimodal_is_forwarded_to_rishi(monkeypatch):
    import leela.agent.agent as chat
    made = []
    monkeypatch.setattr(chat, 'make_backend', lambda spec, **kw: made.append((spec, kw)) or object())
    a = Agent(MemHost(), model='gemma-e4b', extensions=False, local_multimodal=False)
    a._tools = []
    a._be('turn')
    assert made[0][0].backend == 'litert'
    assert made[0][1]['multimodal'] is False


def test_a_streamed_turn_still_records_usage_and_activity():
    a, be = fake_agent(replies=['all done'])
    out = ''.join(a.stream('go'))
    assert out.strip() == 'all done'
    assert a.use.total == 15


def test_prompt_cells_and_agent_chat_have_separate_assistants_and_histories():
    from leela.workspace import Workspace
    ws = Workspace(roots=[], model='gemma-12b', inline_model='gemma-e2b')
    assert ws.ai is not ws.inline_ai
    assert ws.ai.model.name == 'gemma-12b'
    assert ws.inline_ai.model.name == 'gemma-e2b'
    assert ws.ai.history_path.name == 'agent-history.jsonl'
    assert ws.inline_ai.history_path.name == 'inline-history.jsonl'


def test_a_prompt_cell_fills_in_as_the_answer_arrives():
    """`ask_cell_stream` appends to `cell.reply` on the way past, so repainting the cell
    *is* the live view -- the advantage of having put the answer in the document."""
    from leela.blocks.nb.nb import Cell, Notebook
    from leela.workspace import Workspace
    from tests.fakemodel import Step, install
    ws = Workspace(roots=[])
    install(ws, [Step(text='the answer is four')], token_delay=0)
    nb = Notebook([Cell(source='what is 2+2', cell_type='prompt')])
    seen = []
    for _ in ws.ask_cell_stream(nb, 0): seen.append(nb[0].reply)
    assert len(seen) > 1
    assert seen[0].strip() == 'the'          # the cell held a partial answer while it ran
    assert seen[-1].strip() == 'the answer is four'
    assert nb[0].reply.startswith('the answer is four')
    assert nb.dirty


def test_a_streamed_cell_still_gets_its_activity_trail():
    from leela.blocks.nb.nb import Cell, Notebook
    from leela.workspace import Workspace
    from tests.fakemodel import Step, install
    ws = Workspace(roots=[])
    ws.add_root('.')
    install(ws, [Step(tool=('search_code', {'query': 'Approvals'})),
                 Step(text='found it')], token_delay=0)
    nb = Notebook([Cell(source='where is approval handled?', cell_type='prompt')])
    list(ws.ask_cell_stream(nb, 0))
    assert '<details>' in nb[0].reply and 'Search Approvals' in nb[0].reply
    assert nb[0].calls and nb[0].calls[0]['tool'] == 'search_code'


def test_the_sse_frame_survives_a_newline_in_the_payload():
    "A raw newline would end the frame early; JSON is why chunks can contain markdown."
    from leela.app import _sse
    f = _sse('chunk', {'text': 'line one\nline two'})
    assert f.count('\n\n') == 1 and f.startswith('event: chunk\ndata: ')


def test_workspace_at_attachments_are_grounded_and_sandboxed(tmp_path):
    from leela.workspace import Workspace
    p = tmp_path/'notes.txt'; p.write_text('the attached fact')
    ws = Workspace(roots=[tmp_path])
    context, images = ws._attachment_context([str(p)])
    assert str(p) in context and 'the attached fact' in context and images == []
    with pytest.raises(Exception): ws._attachment_context(['/etc/passwd'])


def test_the_sse_endpoint_streams_the_real_app():
    """Drive the actual route, not a mock of it.

    Streaming has a lot of places to go wrong that a unit test cannot see — the generator
    running off the event loop, the frame format, the ordering of activity against chunks —
    so this exercises the mounted app end to end and asserts on the wire bytes.
    """
    pytest.importorskip('starlette.testclient')
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.workspace import Workspace
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
    assert '"done": true' in body                 # finished state is streamed, not left as pending
    assert 'event: done' in body
    assert 'Search Approvals' in body            # the activity row, rendered by the harness
    assert 'found' in body
    # The final frame is what carries the diffs and the usage the client shows afterwards.
    done = body.rsplit('event: done\ndata: ', 1)[1]
    import json as _j
    d = _j.loads(done.strip())
    assert d['ok'] and 'edits' in d and d['activity']


def test_external_rishi_request_uses_the_web_approval_queue():
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.workspace import Workspace

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


def test_prompt_cell_endpoint_streams_into_the_notebook():
    from pathlib import Path
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.workspace import Workspace
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
    """A sub-agent gets the scope choice too, because the sandbox is a limit on the Python
    available and not on what it is allowed to see — the overlay scope is protected by the
    AST policy rather than by an allowlist, so it is no more dangerous to delegate."""
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
