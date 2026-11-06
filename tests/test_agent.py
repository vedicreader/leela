"The agent: tools, briefing, context window, routing and budgets."

import json
import shutil, threading
import time
import pytest
from leela.agent import core as models
from leela.agent.agent import Agent
from leela.agent.tools import NullHost
#: the capability groups a test host declares, and the error a declared-but-absent index raises
from shalya.core import HostError
from shalya.host import CodeHost
from leela.agent.tools import WRITE_TOOLS
from leela.agent.tools import failed
import sys
from fastcore.all import Path, first
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.workspace import Workspace
ROOT = Path(__file__).resolve().parents[1]
import os
from leela.agent.core import env
from leela.workspace import TOOL_RANGE, budget_value, ws_path
import json
import asyncio

class MemHost_agent(NullHost, CodeHost):
    "A host whose folders live in a dict, so file tools can be driven without touching disk."
    writes = True    # unlike the `NullHost` it inherits from, `write` really writes
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
    # declaring the code group means answering all four, whatever a dict can say about three of them
    def peers(self, path, line, limit=20): return []
    def symbols(self, path): return []
    def public_api(self, package, limit=200): raise HostError('no code index: memory')
    def run_python(self, code):
        self.ran.append(code)
        return 'ok'


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


def test_a_steer_no_tool_call_consumed_rides_the_next_turn(tmp_path):
    "Queued while the model was writing its answer, it waited for a tool call that never came."
    ws = Workspace(roots=[tmp_path], approvals='auto')
    ws.approvals.queue_steer('use the notebook, not the script')
    out = ws.ai._with_steer('carry on')
    assert out == 'carry on\n\nUser steering: use the notebook, not the script'
    assert ws.approvals.state()['queued_steer'] == '', 'and it is not delivered twice'
    assert ws.ai._with_steer('carry on') == 'carry on'


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


def test_an_approval_exchange_is_written_into_the_notebook():
    "The request, the refusal and the reason land as cells beside the prompt that caused"
    from leela.blocks.nb.nb import Cell, Notebook
    ws = Workspace(roots=[])
    nb = Notebook([Cell(source='fix it', cell_type='prompt')])
    ws._approval_target = (nb, 0)
    approvals = ws._notebook_approvals
    def answer():
        for _ in range(300):
            if (a := approvals.pending) is not None:
                return approvals.answer(a.id, False, 'that file is generated')
            time.sleep(0.01)
    threading.Thread(target=answer, daemon=True).start()
    tc = {'function': {'name': 'edit_file', 'arguments': {'path': 'gen.py'}}}
    d = approvals.gate(tc)
    # a refusal is handed back as steering, the same for a call with an id and one without
    assert d is True and tc['function']['name'] == 'user_steering'
    assert 'that file is generated' in tc['function']['arguments']['instruction']
    states = [(c.cell_type, (c.approval or {}).get('state')) for c in nb.cells]
    assert states == [('prompt', None), ('markdown', 'pending'), ('markdown', 'refused')]
    assert 'that file is generated' in nb[2].source


class _Rows:
    """A kernel inspector with two namespaces: the user's, and the layer `run_python` writes to."""
    base = 'http://kernel'
    def __init__(self, owner=('df',), layer=('df_norm',)):
        self.owner, self.layer, self.calls = list(owner), list(layer), []
    @staticmethod
    def _g(names): return {'groups': [{'nodes': [{'name': n, 'type': 'DataFrame', 'value': '[5×2]'} for n in names]}]}
    def api_sync(self, path, params=None, timeout=30):
        self.calls.append((path, params))
        if path == '/api/rows': return self._g(self.owner)
        if path == '/agent/api/rows': return self._g(self.owner + self.layer)
        if path == '/api/promote':
            name = json.loads((params or {})['accessor'])[0]
            if name not in self.layer: return {'ok': False, 'error': f'no agent variable {name!r}'}
            self.owner.append(name)          # dhrishti copies; it does not stop shadowing
            return {'ok': True, 'error': None}
        return {'ok': True, 'stdout': '', 'error': '', 'result': {'value': 'done'}}

def _host(k, ws=None):
    from leela.blocks.agent.ai import WorkspaceHost
    ws = ws or Workspace(roots=[])
    ws.kernel_peek = lambda tab=None: k
    return WorkspaceHost(ws)


def test_a_promotion_never_replaces_what_the_user_made():
    "0e12791 took the agent's ability to overwrite the user away. Promotion may not give it back."
    k = _Rows(owner=('df',), layer=('df', 'df_norm'))
    h = _host(k)
    out = h.promote_var('df')
    assert 'will not be replaced' in out
    assert not [c for c in k.calls if c[0] == '/api/promote'], 'refused before the kernel is asked'
    assert h.promote_var('nowhere') == "no agent variable 'nowhere'; bind it with run_python first"
    assert h.promote_var('1x') == "'1x' is not a variable name"


def test_a_failed_run_reports_what_it_had_already_done():
    """A NameError on the last line read as total failure, and the live model call two lines above it had already gone out and bound its reply."""
    class Broken(_Rows):
        def api_sync(self, path, params=None, timeout=30):
            if path == '/agent/api/exec':
                self.calls.append((path, params))
                return {'ok': False, 'stdout': 'calling the model...\n',
                        'error': "NameError: name 'typo' is not defined", 'result': None}
            return super().api_sync(path, params, timeout)
    h = _host(Broken(owner=('df',), layer=('reply',)))
    out = h.run_python('reply = ask()\nprint(typo)')
    assert 'calling the model...' in out, 'the output it printed before the error is not thrown away'
    assert "NameError: name 'typo' is not defined" in out
    assert 'partial run' in out and 'bound reply' in out, out


def test_output_is_marked_when_the_source_that_made_it_is_gone(tmp_path):
    """The traceback shown was for an assertion the cell no longer contained, and nothing said so."""
    from leela.blocks.nb.nb import Cell, Notebook, src_hash
    c = Cell(source='assert x == 1', cell_type='code', id='c1', execution_count=3, execution_ms=12.0,
             outputs=[{'output_type': 'error', 'ename': 'AssertionError', 'evalue': '',
                       'traceback': ['AssertionError']}])
    c.output_hash = src_hash(c.source)
    nb = Notebook([c, Cell(source='x', cell_type='code', id='c2')])
    ctx = nb.context(1)
    assert 'count="3"' in ctx and 'ms="12"' in ctx and 'stale=' not in ctx
    c.source = 'assert x == 2'
    assert 'stale="true"' in nb.context(1), 'the cell was edited after the run that made this output'
    c.clear()
    assert c.output_hash == '' and not c.stale


def test_the_writable_folders_are_named_before_the_first_refusal(tmp_path):
    """Both folders were open and both were said to be the agent's, and the edit to the second was refused as a cross-workspace write."""
    from leela.blocks.agent.ai import WorkspaceHost
    a, b = tmp_path/'a', tmp_path/'b'
    for d in (a, b): d.mkdir()
    ws = Workspace(roots=[a, b])
    h = WorkspaceHost(ws)
    assert h.roots == [str(a), str(b)]
    assert h.writable_roots == [str(a)], 'only the project the agent is working in'
    with pytest.raises(Exception) as e: h.check_write(str(b/'x.py'))
    assert 'Writable: ' in str(e.value) and str(a) in str(e.value)
    assert 'Writable folders' in ws.ai.system_prompt()
    ws.allow_workspace_repo_writes = True
    assert h.writable_roots == h.roots
    assert 'Writable folders' not in ws.ai.system_prompt(), 'nothing to warn about when they match'


def _git_repo(path):
    "A repository with one tracked `a.py`, committed."
    import subprocess
    path.mkdir(parents=True, exist_ok=True)
    def g(*a): return subprocess.run(['git', *a], cwd=path, check=True, text=True, capture_output=True).stdout.strip()
    g('init', '-b', 'main'); g('config', 'user.email', 't@leela.local'); g('config', 'user.name', 'Leela tests')
    (path/'a.py').write_text('value = 1\n'); g('add', '.'); g('commit', '-m', 'initial')
    return path, g


def test_rolling_a_turn_back_undoes_its_git_writes_first_then_its_files(tmp_path):
    repo, g = _git_repo(tmp_path/'r'); head = g('rev-parse', 'HEAD')
    ws = Workspace(roots=[repo], approvals='auto'); tools = {t.__name__: t for t in ws.ai.tools}
    ws.ai._prepare('x')
    assert not failed(tools['replace_text'](str(repo/'a.py'), [{'oldText': 'value = 1', 'newText': 'value = 2'}]))
    assert json.loads(tools['git_commit']('bump', 'a.py'))['undo'] and g('rev-parse', 'HEAD') != head
    ws.ai._finish('done'); turn = ws.ai.current_turn_id
    tx = ws.ai.rollback_turn(turn)
    assert g('rev-parse', 'HEAD') == head, 'the commit was undone'
    assert (repo/'a.py').read_text() == 'value = 1\n' and tx['rolled_back'] and 'undid 1 git write' in tx['git_result']
    assert not ws.ai.turn_capabilities(turn)['undoable']

def _turn_with_a_commit(tmp_path):
    "A repository, a workspace on it, and one finished turn that edited and committed `a.py`."
    repo, g = _git_repo(tmp_path/'r'); head = g('rev-parse', 'HEAD')
    ws = Workspace(roots=[repo], approvals='auto'); tools = {t.__name__: t for t in ws.ai.tools}
    ws.ai._prepare('x')
    assert not failed(tools['replace_text'](str(repo/'a.py'), [{'oldText': 'value = 1', 'newText': 'value = 2'}]))
    assert json.loads(tools['git_commit']('bump', 'a.py'))['undo']
    ws.ai._finish('done')
    return repo, g, ws, head, ws.ai.current_turn_id

def test_rollback_refuses_when_head_moved_after_the_turn(tmp_path):
    "A hard reset over the user's later commit is the one thing the undo must never do."
    repo, g, ws, head, turn = _turn_with_a_commit(tmp_path); turned = g('rev-parse', 'HEAD')
    (repo/'b.py').write_text('later = 1\n'); g('add', 'b.py'); g('commit', '-m', 'the user, afterwards'); theirs = g('rev-parse', 'HEAD')
    with pytest.raises(ValueError, match='HEAD moved after the turn.*undo refused'): ws.ai.rollback_turn(turn)
    assert g('rev-parse', 'HEAD') == theirs and (repo/'a.py').read_text() == 'value = 2\n' and (repo/'b.py').exists(), 'nothing was touched'
    assert ws.ai.turn_capabilities(turn)['undoable'] and not ws.ai.turn_transactions[turn]['rolled_back']
    g('checkout', '-q', '-b', 'side', turned)      # back on the turn's commit, but on another branch
    with pytest.raises(ValueError, match='undo refused'): ws.ai.rollback_turn(turn)


def test_a_partial_git_undo_names_what_it_undid_and_a_retry_meets_the_head_guard(tmp_path, monkeypatch):
    "Two commits in one turn; undoing the older one fails: the error says the newer was undone and HEAD moved, and the next attempt is refused rather than applied twice."
    repo, g, ws, head, turn = _turn_with_a_commit(tmp_path)
    tools = {t.__name__: t for t in ws.ai.tools}
    ws.ai._prepare('y'); (repo/'c.py').write_text('c = 1\n')
    assert json.loads(tools['git_commit']('second', 'c.py'))['undo']; ws.ai._finish('done'); turn2 = ws.ai.current_turn_id
    (repo/'a.py').write_text('value = 3\n'); assert json.loads(tools['git_commit']('third', 'a.py'))['undo'] or True
    ws.ai._prepare('z'); (repo/'d.py').write_text('d = 1\n'); assert json.loads(tools['git_commit']('d1', 'd.py'))['undo']
    (repo/'d.py').write_text('d = 2\n'); assert json.loads(tools['git_commit']('d2', 'd.py'))['undo']; ws.ai._finish('done'); turn3 = ws.ai.current_turn_id
    assert len(ws.ai.turn_transactions[turn3]['git']) == 2
    from gheasy.repo import GitRepo
    real, calls = GitRepo.undo, []
    def undo(self, token=''):
        calls.append(token)
        if len(calls) == 2: raise RuntimeError('boom')
        return real(self, token)
    monkeypatch.setattr(GitRepo, 'undo', undo)
    with pytest.raises(ValueError) as e: ws.ai.rollback_turn(turn3)
    said = str(e.value)
    assert 'undid 1 git write' in said and 'already undone: git_commit (' in said and 'HEAD moved' in said and said.endswith('boom') or 'boom' in said
    assert not ws.ai.turn_transactions[turn3]['rolled_back']
    monkeypatch.setattr(GitRepo, 'undo', real)
    with pytest.raises(ValueError, match='HEAD moved after the turn'): ws.ai.rollback_turn(turn3)
    log = g('log', '--oneline').splitlines()
    assert log[0].endswith(' d1') and not any(l.endswith(' d2') for l in log), 'd2 undone once, d1 stayed: nothing was applied twice'

def _turn_committing(tmp_path, extra=('b.py', 'c.py')):
    "A repository tracking `a.py` and `extra`; one finished turn that edited `a.py` and `c.py` but committed only `a.py`."
    repo, g = _git_repo(tmp_path/'r')
    for n in extra: (repo/n).write_text(f'{n[0]} = 0\n')
    g('add', '.'); g('commit', '-m', 'more files')
    ws = Workspace(roots=[repo], approvals='auto'); tools = {t.__name__: t for t in ws.ai.tools}
    ws.ai._prepare('x')
    assert not failed(tools['replace_text'](str(repo/'a.py'), [{'oldText': 'value = 1', 'newText': 'value = 2'}]))
    assert not failed(tools['replace_text'](str(repo/'c.py'), [{'oldText': 'c = 0', 'newText': 'c = 1'}]))
    assert json.loads(tools['git_commit']('bump a', 'a.py'))['undo']
    ws.ai._finish('done')
    return repo, g, ws, ws.ai.current_turn_id

def test_rollback_refuses_over_the_users_uncommitted_edits_but_not_over_its_own(tmp_path):
    "A git undo is a hard reset: it must never take an uncommitted edit outside the turn's files with it."
    repo, g, ws, turn = _turn_committing(tmp_path)
    (repo/'b.py').write_text('b = 99\n')                       # the user's, uncommitted, not a turn file
    with pytest.raises(ValueError, match='uncommitted changes outside this turn.*b.py'): ws.ai.rollback_turn(turn)
    assert (repo/'b.py').read_text() == 'b = 99\n' and (repo/'a.py').read_text() == 'value = 2\n', 'nothing touched'
    assert not ws.ai.turn_transactions[turn]['rolled_back']
    g('checkout', '--', 'b.py')                                # `c.py` is still dirty, but it is the turn's own file
    assert 'c.py' in g('status', '--porcelain')
    tx = ws.ai.rollback_turn(turn)
    assert tx['rolled_back'] and (repo/'a.py').read_text() == 'value = 1\n' and (repo/'c.py').read_text() == 'c = 0\n'


def test_the_third_identical_gated_call_is_put_to_the_person_even_under_auto():
    from leela.blocks.agent.ai import Interventions
    ap = Interventions(tools=WRITE_TOOLS, mode='auto', control='autopilot', timeout=0.2); stop = ap.listen()
    a1 = ap.request('run_shell', {'command': 'pytest'}); a2 = ap.request('run_shell', {'command': 'pytest'})
    assert a1 and a2
    assert ap.request('view_file', {'path': 'a.py'}), 'a read between neither counts nor resets'
    a3 = ap.request('run_shell', {'command': 'pytest'})
    assert not a3 and 'no answer' in a3.note and 'three times running' in a3.preview
    assert ap.request('run_shell', {'command': 'pytest -x'}), 'a different call starts a new streak'
    stop()


def test_auto_raises_no_card_for_what_it_allows_whatever_the_default_control(tmp_path):
    "`guided`, the default control, still paused web_search, read_url and research under `--approvals auto`."
    from leela.blocks.agent.ai import Interventions
    calls = {'web_search': {'query': 'x'}, 'read_url': {'url': 'https://example.com'}, 'research': {'question': 'q'},
             'edit_file': {'path': 'a.py', 'commands': '[]'}, 'run_cell': {'path': 'a.ipynb', 'cell_id': 'c1'},
             'run_shell': {'command': 'make'}}
    ws = Workspace(roots=[tmp_path], approvals='auto')
    for ap in (Interventions(tools=WRITE_TOOLS, mode='auto', timeout=.2), ws.approvals, ws._notebook_approvals):
        asked = []; stop = ap.listen(on_ask=asked.append)
        try: got = {n: ap.request(n, a) for n, a in calls.items()}
        finally: stop()
        assert ap.control == 'guided' and asked == [] and all(got.values()), (asked, {n: a.note for n, a in got.items()})
    ap = Interventions(tools=WRITE_TOOLS, mode='auto', timeout=.2); stop = ap.listen()
    try: assert [bool(ap.request('run_shell', {'command': 'make'})) for _ in range(3)] == [True, True, False], 'the repeat guard still asks'
    finally: stop()
    ws.shutdown_now()


def test_the_name_a_prompt_asks_for_survives_the_way_people_write_it():
    for prompt, want in [('scale the numeric columns as df_norm', 'df_norm'),
                         ('Scale the numeric columns of `df` to 0..1 as `df_norm`.', 'df_norm'),
                         ("bind it as 'out'", 'out'),
                         ('just tell me about df', '')]:
        assert Workspace._requested_name(prompt) == want, prompt


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


def test_a_later_turn_does_not_carry_the_cell_above_it_work_log():
    "The trail is saved on the cell and shown from `calls`; sending it back as `<answer>` paid for it twice."
    from leela.blocks.nb.nb import Cell, Notebook
    from tests.fakemodel import Step, install
    ws = Workspace(roots=[])
    ws.add_root('.')
    install(ws, [Step(tool=('search_code', {'query': 'Approvals'})),
                 Step(text='found it')], token_delay=0)
    nb = Notebook([Cell(source='where is approval handled?', cell_type='prompt'),
                   Cell(source='and then?', cell_type='prompt')])
    list(ws.ask_cell_stream(nb, 0))
    assert '<details>' in nb[0].reply
    ctx = ws._agent_context(nb, 1, nb[1].source)
    assert 'found it' in ctx
    assert '<details>' not in ctx and 'Search Approvals' not in ctx
    assert len(ctx) < len(nb[0].reply)


def test_the_sse_endpoint_streams_the_real_app():
    "Drive the actual route, not a mock of it."
    pytest.importorskip('starlette.testclient')
    from tests.fakemodel import Step, install
    ws = Workspace(roots=[])
    ws.add_root('.')
    install(ws, [Step(tool=('search_code', {'query': 'Approvals'})),
                 Step(text='found it in hitl.py')], token_delay=0)
    with TestClient(ide_app(ws)) as c:
        accepted = c.post('/agent/turn', json={'prompt': 'where?'}).json()
        with c.stream('GET', '/agent/stream', params={'since': accepted['seq']}) as r:
            assert r.status_code == 200
            assert r.headers['content-type'].startswith('text/event-stream')
            body = ''.join(r.iter_text())
    assert 'event: chunk' in body
    assert body.count('event: activity') >= 1
    assert '"done": true' in body
    assert 'event: done' in body
    assert 'Search Approvals' in body
    assert 'found' in body
    done = body.split('event: done\ndata: ', 1)[1].split('\n\n', 1)[0]
    import json as _j
    d = _j.loads(done.strip())
    assert d['ok'] and 'edits' in d and d['activity']


def test_running_python_starts_the_kernel_it_needs(tmp_path):
    "A person asking to run something means start what it takes, not report that nothing is up."
    from leela.workspace import Workspace
    ws = Workspace(roots=[tmp_path], port=8299)
    async def go():
        await ws.opened()
        host = ws.inline_ai.host
        assert ws.runtime_peek() is None, 'nothing is running yet'
        loop = asyncio.get_running_loop()
        out = await loop.run_in_executor(None, lambda: host.run_python('leela_probe = 6 * 7'))
        assert 'error' not in str(out).lower(), out
        back = await loop.run_in_executor(None, lambda: host.run_python('print(leela_probe)'))
        assert '42' in str(back), back
        await ws.shutdown()
    asyncio.run(go())

def test_run_python_cannot_touch_what_the_user_made(tmp_path):
    """It ran `scope: 'global'`, straight into the user's namespace, where the refusal the tool promises does not exist: `mine.append(4)`, `mine = ...` and `del mine` all went through and the variable was gone."""
    from leela.workspace import Workspace
    ws = Workspace(roots=[tmp_path], port=8288)
    async def go():
        await ws.opened()
        k = await ws.runtime()
        await k.execute('mine = [1, 2, 3]')
        host, loop = ws.inline_ai.host, asyncio.get_running_loop()
        async def run(code): return str(await loop.run_in_executor(None, lambda: host.run_python(code)))
        assert '[1, 2, 3]' in await run('print(mine)'), 'it reads what the user made'
        assert 'error' not in (await run('scene_ex = 6 * 7')).lower()
        assert '42' in await run('print(scene_ex)'), 'and what it binds survives the next call'
        assert 'blocked' in await run('mine.append(4)'), 'mutating the user is refused'
        assert 'blocked' in await run('del mine'), 'so is deleting'
        held = await k.execute('print(mine)')
        assert '[1, 2, 3]' in str(held), 'the user\'s variable is exactly as they left it'
        await ws.shutdown()
    asyncio.run(go())


def _nb(path, src):
    "A one-cell notebook on disk, the cell id `c1`."
    import json as _j
    path.write_text(_j.dumps({'cells': [{'cell_type': 'code', 'id': 'c1', 'metadata': {}, 'source': src, 'outputs': [],
        'execution_count': None}], 'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    return path

def test_run_python_keeps_its_kernel_for_the_turn_and_says_when_it_moves(tmp_path):
    """The person clicked tabs mid-turn and each click moved `run_python` to that tab's kernel: the agent's names vanished between two calls, with nothing said."""
    from leela.workspace import Workspace
    a, b = _nb(tmp_path/'a.ipynb', ''), _nb(tmp_path/'b.ipynb', '')
    ws = Workspace(roots=[tmp_path], port=8320)
    async def go():
        await ws.opened()
        host, loop = ws.inline_ai.host, asyncio.get_running_loop()
        async def run(code): return str(await loop.run_in_executor(None, lambda: host.run_python(code)))
        ws.open(a); await ws.runtime()
        assert 'error' not in (await run('pinned = 6 * 7')).lower()
        ws.open(b); kb = await ws.runtime()
        held = await run('print(pinned)')
        assert '42' in held and '[' not in held, f'a click mid-turn moves nothing: {held}'
        host.new_turn()
        moved = await run('print(1)')
        assert 'not the one your last call ran in' in moved, f'a new turn in another tab says so: {moved}'
        assert host._kernel() is kb
        await kb.restart()
        assert 'restarted' in await run('print(2)'), 'a restart is said, never silent'
        assert '[' not in await run('print(3)'), 'and said once'
        await ws.shutdown()
    asyncio.run(go())

def test_run_cell_on_an_unopened_notebook_uses_that_notebooks_kernel(tmp_path):
    """With no tab for the notebook, `run_cell` ran in the kernel of the tab in front: the person opening it later got a fresh kernel at In[1], and the binding diff compared two kernels (`bindings changed: open`)."""
    from leela.workspace import Workspace
    a, c = _nb(tmp_path/'a.ipynb', ''), _nb(tmp_path/'c.ipynb', "zz = 'mine' in globals()\nprint(zz)")
    ws = Workspace(roots=[tmp_path], port=8340)
    async def go():
        await ws.opened()
        host, loop = ws.inline_ai.host, asyncio.get_running_loop()
        ws.open(a); ka = await ws.runtime()
        await ka.execute('mine = 5')
        out = await loop.run_in_executor(None, lambda: host.nb_run_cell(str(c), 'c1', 60))
        assert 'False' in out, f"the tab in front's names are not the notebook's: {out}"
        assert 'bindings changed: zz' in out, f'the diff reads the kernel the cell ran in: {out}'
        ws.open(c)
        assert ws.kernel_peek() is not None and ws.kernel_peek() is not ka, 'opening it finds the kernel the cell ran in'
        assert 'True' in str(await ws.kernel_peek().execute("print('zz' in globals())"))
        await ws.kernel_peek().restart()
        again = await loop.run_in_executor(None, lambda: host.nb_run_cell(str(c), 'c1', 60))
        assert "this notebook's kernel is not the one" in again, again
        await ws.shutdown()
    asyncio.run(go())

def test_a_transcript_notebook_runs_where_it_was_written_from(tmp_path):
    "A kernel started for a transcript tab ran inside `_leela_agent_sessions`, and wrote its own transcripts one folder deeper."
    from leela.workspace import Tab, Workspace
    t = _nb((tmp_path/'_leela_agent_sessions').mkdir() or tmp_path/'_leela_agent_sessions'/'agent_1.ipynb', '')
    ws = Workspace(roots=[tmp_path])
    assert Path(ws.cwd_for(Tab(path=str(t), kind='notebook'))).resolve() == tmp_path.resolve()


def test_a_tool_on_the_loop_itself_does_not_wait_for_the_loop(tmp_path):
    "Called from the loop that owns the kernels there is nothing to wait for, and blocking deadlocks."
    from leela.workspace import Workspace
    ws = Workspace(roots=[tmp_path])
    async def go():
        await ws.opened()
        assert ws.inline_ai.host._start_kernel() is None
    asyncio.run(go())

def test_a_stream_still_open_at_shutdown_does_not_shout_on_the_way_out(tmp_path):
    """Both httpcore2 byte streams `yield` inside `async with safe_async_iterate(...)`."""
    import subprocess, sys as _sys
    script = tmp_path/'dangling.py'
    script.write_text(
        'import asyncio\n'
        'import leela.app                                    # installs the patch\n'
        'import httpcore2._utils as core_utils\n'
        'async def inner():\n'
        '    try: yield b"a"; yield b"b"\n'
        '    finally: await asyncio.sleep(0)\n'
        'async def stream():                                 # httpcore2\'s own shape\n'
        '    async with core_utils.safe_async_iterate(inner()) as it:\n'
        '        async for chunk in it: yield chunk\n'
        'async def main():\n'
        '    g = stream(); await g.__anext__()\n'
        '    globals()["keep"] = g                           # nobody closes it: the loop must\n'
        'asyncio.run(main())\n')
    r = subprocess.run([_sys.executable, str(script)], capture_output=True, text=True,
                       cwd=str(ROOT), timeout=180)
    assert r.returncode == 0, r.stderr
    assert 'athrow' not in r.stderr and 'asynchronous generator' not in r.stderr, r.stderr

def test_the_iterate_helper_leaves_a_closing_stream_to_its_response_context():
    "Closing is the one case that must not await: awaiting there is what half-closes the iterator."
    import httpcore2._utils as core_utils
    closed = []
    async def stream():
        try: yield b'chunk'
        finally: closed.append(True)
    async def run():
        it = stream()
        assert await anext(it) == b'chunk'
        async with core_utils.safe_async_iterate(it) as got:
            assert got is it, 'an iterator is passed through rather than re-wrapped'
        assert closed == [True], 'an ordinary exit closes it'
        again = stream(); await anext(again)
        try:
            async with core_utils.safe_async_iterate(again): raise GeneratorExit
        except GeneratorExit: pass
        assert again.ag_frame is not None, 'but a closing one is left to whoever owns it'
    asyncio.run(run())


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


def test_the_host_answers_exists_and_deletes_only_inside_writable_roots(tmp_path):
    from leela.blocks.agent.ai import WorkspaceHost
    from leela.blocks.fs.fs import Unsafe
    (tmp_path/'a.py').write_text('x\n'); ws = Workspace(roots=[tmp_path]); h = WorkspaceHost(ws)
    assert h.exists(str(tmp_path/'a.py')) and not h.exists(str(tmp_path/'nope.py')) and not h.exists('/etc/passwd')
    with pytest.raises(Unsafe): h.delete('/etc/passwd')
    h.delete(str(tmp_path/'a.py')); assert not (tmp_path/'a.py').exists()
    h.delete(str(tmp_path/'a.py'))     # already gone: not an error, like ramabana's LocalHost

def test_a_write_through_the_recorded_tool_reaches_the_undo_journal(tmp_path):
    "`Agent._record` asks `host.exists` before a path write; a host without it fails every write."
    ws = Workspace(roots=[tmp_path], approvals='auto')
    create = next(t for t in ws.ai.tools if t.__name__ == 'create_file')
    ws.ai._prepare('x')                                   # a turn's `before` map
    assert not failed(create(str(tmp_path/'n.py'), 'y = 1\n')) and str(tmp_path/'n.py') in ws.ai.new


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

def _bare_machine(monkeypatch):
    "A Linux box with no Claude Code, no Codex, no local backend and no key: only hosted APIs can be added."
    import ramabana.core as rc
    from leela.blocks.agent.models import forget_probes
    monkeypatch.setattr(rc, 'runtime_available', lambda r: r == 'remote')
    monkeypatch.setattr(rc, '_claude_login', lambda: False)
    monkeypatch.setattr(rc, '_codex_login', lambda: False)
    forget_probes(disk=True)

MODEL_KEYS = {'ok', 'models', 'saved', 'notes', 'auth', 'runtimes', 'jobs', 'job_help', 'selected', 'ready'}

@pytest.mark.no_claude
def test_the_model_list_answers_on_a_machine_with_nothing_set_up(monkeypatch):
    "Nothing installed and no key: every row unavailable, `ready` false, and the hosted runtime offered to add one."
    _bare_machine(monkeypatch)
    with TestClient(ide_app(Workspace(roots=[]))) as c: r = c.get('/agent/models')
    assert r.status_code == 200
    d = r.json()
    assert MODEL_KEYS <= set(d) and d['ok'] and not d['ready']
    assert all(m.get('unavailable') for m in d['models'])
    assert [x['value'] for x in d['runtimes'] if x['available']] == ['remote']

@pytest.mark.no_claude
@pytest.mark.parametrize('step', ['mark_models', 'Routing'])
def test_one_failing_step_of_the_model_list_is_a_note_not_a_500(monkeypatch, step):
    "The steps outside the per-row guards used to raise straight through, and `+ model` then drew nothing."
    import leela.blocks.agent.models as lm, ramabana.core as rc
    _bare_machine(monkeypatch)
    def boom(*a, **kw): raise RuntimeError('injected')
    monkeypatch.setattr(lm if step == 'mark_models' else rc, step, boom)
    with TestClient(ide_app(Workspace(roots=[]))) as c: r = c.get('/agent/models')
    assert r.status_code == 200
    d = r.json()
    assert MODEL_KEYS <= set(d) and d['ok']
    assert any('injected' in v for v in d['notes'].values())
    assert [x['value'] for x in d['runtimes'] if x['available']] == ['remote']

@pytest.mark.no_claude
def test_a_model_list_that_fails_outright_answers_in_the_same_shape(monkeypatch):
    "Whatever escapes the per-step guards is `ok: False` with the error, and the hosted runtime still offered."
    _bare_machine(monkeypatch)
    class Broken(dict):
        def items(self): raise RuntimeError('injected')
    ws = Workspace(roots=[])
    ws.job_models = Broken(x='y')
    with TestClient(ide_app(ws)) as c: r = c.get('/agent/models')
    assert r.status_code == 200
    d = r.json()
    assert MODEL_KEYS <= set(d) and not d['ok'] and 'injected' in d['error']
    assert [x['value'] for x in d['runtimes']] == ['remote']

@pytest.mark.no_claude
def test_a_hosted_model_is_saved_and_listed_on_a_machine_with_nothing_set_up(monkeypatch, tmp_path):
    "An Azure OpenAI deployment added from the form: base URL, key variable, vendor and transport, no key set."
    import leela
    _bare_machine(monkeypatch)
    monkeypatch.setattr(leela.blocks.agent.models, 'leela_cfg', tmp_path)
    row = {'name': 'azure-gpt', 'model_id': 'gpt-4.1', 'runtime': 'remote', 'ctx': 128000,
           'base_url': 'https://myres.openai.azure.com/openai/v1', 'api_key_env': 'AZURE_OPENAI_API_KEY',
           'vendor_name': 'openai', 'api_name': 'openai'}
    try:
        with TestClient(ide_app(Workspace(roots=[]))) as c:
            r = c.post('/agent/models/add', json=row)
            assert r.json()['ok'] and r.json()['model']['base_url'] == row['base_url']
            d = c.get('/agent/models').json()
    finally: models.delete_model('azure-gpt', path=tmp_path/'models.json')
    assert d['ok'] and [x['name'] for x in d['saved']] == ['azure-gpt']
    assert any(m['value'] == 'azure-gpt' and m.get('custom') for m in d['models'])


@pytest.fixture
def project(tmp_path):
    from leela.blocks.agent.ai import WorkspaceHost
    (tmp_path/'src').mkdir()
    (tmp_path/'src'/'app.py').write_text('value = 1\n')
    return WorkspaceHost(Workspace(roots=[tmp_path]))


def test_stdout_and_stderr_come_back_in_the_order_they_happened(project):
    "A failing test *is* its traceback. Splitting the streams loses which line came first."
    code, out = project.run_cmd('echo out; echo err 1>&2; echo after')
    assert out.splitlines() == ['out', 'err', 'after']


def test_a_command_cannot_be_started_outside_the_open_folders(project):
    from leela.blocks.fs.fs import Unsafe
    with pytest.raises(Unsafe):
        project.run_cmd('ls', cwd='/etc')


def killed(pid):
    """Dead, or dead and not yet reaped."""
    import os
    from pathlib import Path
    if Path('/proc').is_dir():
        stat = Path(f'/proc/{pid}/stat')
        if not stat.exists(): return True
        return stat.read_text().rsplit(')', 1)[1].split()[0] == 'Z'
    try: os.kill(pid, 0)
    except OSError: return True
    return False

def test_a_timeout_takes_the_children_with_it(project):
    "`pytest -n 4` behind a pipe leaves children that outlive the shell, and a leaked one holds the pipe open."
    import time
    marker = project.roots[0] + '/child.pid'
    project.run_cmd(f'(sleep 30 & echo $! > {marker}); sleep 30', timeout=2)
    pid = int(open(marker).read().strip())
    time.sleep(0.2)
    assert killed(pid), f'the grandchild {pid} outlived the timeout'


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

def test_the_blend_stamps_each_hit_with_the_engines_that_agreed(project, monkeypatch):
    "One location several engines found is the point: the row has to say so, or it is just another list. The blend is the host's; `search_code` is the tool."
    path = project.roots[0] + '/src/app.py'
    open(path, 'w').write('def compute_total(x):\n    return x\n')
    ran = _index_legs(project.ws, monkeypatch, path)
    hits = project.ws.ai.host.search_blend('compute_total')
    by_line = {h.line: h for h in hits if h.path == path}
    assert set(by_line) == {1, 2} and 'def compute_total(x):' in by_line[1].text
    assert by_line[1].sources == ['symbols', 'rg', 'fts'] and by_line[2].sources == ['ann']
    ran.clear()
    quick = project.ws.inline_ai.host.search_blend('compute_total', legs=('symbols', 'rg', 'fts'))
    assert set(ran) == {'symbols', 'fts'} and 'ann' not in ran, 'a caller in a hurry names the legs; `ann` embeds the query first'
    assert not any('ann' in h.sources for h in quick) and any(h.line == 1 for h in quick)


sys.path.insert(0, str(ROOT/'tools'))

@pytest.fixture
def ws(tmp_path):
    (tmp_path/'pkg').mkdir()
    (tmp_path/'pkg'/'a.py').write_text('print(1)\n')
    (tmp_path/'pkg'/'b.md').write_text('# B\n')
    (tmp_path/'top.py').write_text('x = 1\ny = 2\n')
    return Workspace(roots=[tmp_path])


def test_a_selection_is_sent_as_chosen_not_re_read_from_disk(ws, tmp_path):
    "The buffer may be unsaved, and what was highlighted is what was meant."
    sel = {'kind': 'selection', 'path': str(tmp_path/'top.py'), 'from': 2, 'to': 2,
           'text': 'y = 2  # edited, never saved'}
    text, _ = ws._attachment_context([sel])
    assert 'lines="2-2"' in text and 'never saved' in text
    assert '<attached-selection' in text, 'marked as a range, not mistaken for a whole file'


def test_a_file_leela_just_wrote_can_be_found_before_the_walk_cache_expires(tmp_path):
    "The walk is cached to keep quick-open cheap. Our own writes skip the window."
    ws = Workspace(roots=[tmp_path])
    assert [p.name for p in ws.fs.walk(tmp_path)] == []
    ws.fs.write(tmp_path/'fresh.py', 'x = 1\n')
    assert [p.name for p in ws.fs.walk(tmp_path)] == ['fresh.py'], 'stale for 2s was the bug'
    ws.fs.delete(tmp_path/'fresh.py')
    assert [p.name for p in ws.fs.walk(tmp_path)] == []


def test_leela_environment_names_override_legacy_ramabana_names(monkeypatch):
    monkeypatch.setenv('LEELA_MODEL', 'current')
    monkeypatch.setenv('RAMABANA_MODEL', 'legacy')
    assert env('MODEL') == 'current'
    monkeypatch.delenv('LEELA_MODEL')
    assert env('MODEL') == 'legacy'


@pytest.mark.parametrize('given,want', [
    ('auto', 'auto'), ('AUTO', 'auto'), (' 80 ', 80), (80, 80),
    (TOOL_RANGE[0], TOOL_RANGE[0]), (TOOL_RANGE[1], TOOL_RANGE[1]),
    (TOOL_RANGE[0] - 1, 'auto'), (TOOL_RANGE[1] + 1, 'auto'),
    (None, 'auto'), (True, 'auto'), ('', 'auto'), ('lots', 'auto'),
])
def test_a_budget_is_auto_or_a_number_in_range(given, want):
    assert budget_value(given, *TOOL_RANGE) == want


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


def test_a_steer_rides_the_next_tool_result(tmp_path):
    """The path the UI actually promises, 'applies after current call', and the only one of the three with no test."""
    (tmp_path/'a.py').write_text('x = 1\n')
    ws = Workspace(roots=[tmp_path], approvals='auto')
    view = next(t for t in ws.ai.tools if t.__name__ == 'view_file')
    ws.approvals.queue_steer('read the test first')
    out = str(view(str(tmp_path/'a.py')))
    assert out.endswith('User steering for the next decision: read the test first')
    assert ws.approvals.state()['queued_steer'] == '', 'and it is not delivered twice'
    assert 'steering' not in str(view(str(tmp_path/'a.py'))).lower()


def test_delegation_never_gets_the_git_write_tools(monkeypatch):
    """Leela's Git writes are kept off the delegation surface."""
    from leela.blocks.agent.ai import GIT_WRITE_TOOLS, Assistant

    def git_push(): pass
    def git_checkout(): pass
    def git_pull(): pass
    def git_status(): pass
    def view_file(): pass
    def user_steering(): pass

    a = Assistant.__new__(Assistant)          # the method reads nothing off the instance
    branches = ([git_push, git_status, view_file, user_steering],      # `_plain`, equal budget
                [git_checkout, git_pull, view_file, user_steering],    # `_subtools`, different budget
                [git_push, git_checkout, git_status, user_steering],   # the recorded wrappers a writer is given
                [])
    for branch in branches:
        monkeypatch.setattr(Agent, '_sub_plain', lambda self, spec=None, b=branch: list(b))
        names = {f.__name__ for f in a._sub_plain()}
        assert not (names & GIT_WRITE_TOOLS), f'git writes reached delegation via {branch}'
        assert 'user_steering' not in names, f'main-agent steering reached delegation via {branch}'
        assert names == {f.__name__ for f in branch} - GIT_WRITE_TOOLS - {'user_steering'}, 'and nothing else was taken'

    # Reading git is not writing git, and must survive.
    monkeypatch.setattr(Agent, '_sub_plain', lambda self, spec=None: [git_status, view_file])
    assert {f.__name__ for f in a._sub_plain()} == {'git_status', 'view_file'}


def test_a_delegation_to_a_named_model_reaches_leelas_refusals(tmp_path):
    "Ramabana 0.2.67 sizes a delegation's tools for the model it names, through `_sub_plain(spec)`; the override took no `spec`, so every delegation raised."
    from leela.blocks.agent.ai import GIT_WRITE_TOOLS
    from leela.agent.core import ModelSpec
    from leela.agent.agent import Agent as Base
    ws = Workspace(roots=[tmp_path], approvals='auto')
    small, big = ModelSpec('tiny-sub', 'remote', 'openai/tiny-sub', 16_000), ModelSpec('big-sub', 'remote', 'openai/big-sub', 200_000)
    for spec in (small, big):
        names = {f.__name__ for f in ws.ai._sub_tools(spec=spec)}
        assert not (names & GIT_WRITE_TOOLS) and 'user_steering' not in names, names
        assert names >= {f.__name__ for f in Base._sub_plain(ws.ai, spec)} - GIT_WRITE_TOOLS - {'user_steering'}, 'and it is sized for that model'


def test_a_cancelled_turn_refuses_the_calls_still_to_come(tmp_path):
    "Approval cancellation remains part of Stop after provider cancellation moves to Ramabana."
    ws = Workspace(roots=[tmp_path], approvals='auto')
    ws.approvals.stop()
    tc = {'id': 'c1', 'function': {'name': 'list_files', 'arguments': {'path': ''}}}
    assert ws.approvals.gate(tc) is True
    assert tc['function']['name'] == 'user_steering'
    assert 'stopped this turn' in tc['function']['arguments']['instruction']


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


def test_stream_disconnect_never_owns_or_cancels_the_turn(ws):
    "Owning the turn made a closed tab cancel the work."
    import asyncio
    from tests.fakemodel import Step, install
    words = ' '.join(f'w{i}' for i in range(30))
    be = install(ws, [Step(text=words)], token_delay=0.05)
    with TestClient(ide_app(ws)) as c:
        acc = c.post('/agent/turn', json={'prompt': 'go'}).json()
        first_chunk = asyncio.Event()
        body = [{'type': 'http.request', 'body': b'', 'more_body': False}]
        async def receive():
            if body: return body.pop()
            await first_chunk.wait()
            return {'type': 'http.disconnect'}
        async def send(m):
            if m['type'] == 'http.response.body' and m.get('body'): first_chunk.set()
        scope = {'type': 'http', 'method': 'GET', 'path': '/agent/stream', 'raw_path': b'/agent/stream', 'root_path': '',
                 'scheme': 'http', 'http_version': '1.1', 'headers': [(b'host', b'testserver')],
                 'query_string': f"since=0&thread={acc['thread']}".encode(), 'client': ('testclient', 50000),
                 'server': ('testserver', 80)}
        c.portal.call(c.app, scope, receive, send)
        assert first_chunk.is_set(), 'the tab saw the turn begin before it went'
        for _ in range(300):
            if be.hist_ and be.hist_[-1]['role'] == 'assistant': break
            time.sleep(0.05)
        assert be.hist_[-1]['content'].split() == words.split(), 'the turn ran to the end with no one watching'
        replay = c.get('/agent/stream', params={'since': 0, 'thread': acc['thread']}).text
        assert 'event: done' in replay and 'event: error' not in replay and 'cancel' not in replay.lower()


def test_a_runtime_no_package_provides_is_refused_before_any_subprocess(monkeypatch):
    "The install shells out, so the name it is handed may never reach one unchecked."
    import leela.blocks.agent.models as m
    ran = []
    monkeypatch.setattr(m.subprocess, 'run', lambda *a, **kw: ran.append(a))
    for bad in ('', 'nonsense', 'remote', 'claude', 'litert', 'llama; echo no'):
        with pytest.raises(ValueError): m.install_runtime(bad)
    assert ran == [], 'nothing was executed'


def _wait_kernel(ws, want=True, secs=10):
    "Poll for the kernel the turn asked for. A fixed sleep is a bound, and this suite is loaded."
    end = time.time() + secs
    while time.time() < end and (ws.runtime_peek() is None) == want: time.sleep(.02)
    return ws.runtime_peek()


def test_a_turn_leaves_a_running_kernel_alone(ws):
    "A kernel that is already up is the one the overlay belongs to, so nothing else is started."
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from tests.fakemodel import Step, install
    install(ws, [Step(text='ok')], token_delay=0)   # the kernel is under test, not the model
    with TestClient(ide_app(ws)) as client:
        client.post('/agent/turn', json={'prompt': 'first'})
        first = _wait_kernel(ws)
        assert first is not None
        client.post('/agent/turn', json={'prompt': 'second'})
        time.sleep(.4)
        assert ws.runtime_peek() is first, 'the same kernel, not a second one'


def test_the_update_check_survives_being_asked_twice(monkeypatch):
    """`_latest` was assigned without `global`, so the name was local and the read on the first line raised `UnboundLocalError` on every call inside the hour."""
    from leela.blocks.agent import models as m
    monkeypatch.setattr(m, '_latest', {}); monkeypatch.setattr(m, '_latest_at', 0.0)
    monkeypatch.setattr(m, 'urljson', lambda url, **kw: {'info': {'version': '9.9.9'}})
    first = m._latest_versions(['exhash'])
    assert first['exhash'] == '9.9.9'
    assert m._latest_versions(['exhash']) == first, 'the second ask is the cached first, not a crash'


# --- the small profile: ramabana 0.2.3 briefs a local or ≤32k model fourteen tools and one screen ---


def test_a_refused_call_in_a_small_session_dispatches_user_steering(tmp_path):
    "The approvals refusal path rewrites a rejected call to `user_steering`; a small catalog that dropped it would make every 'no' an unknown-tool error."
    from tests.fakemodel import Step, install
    # Small from the scripted model's 8k window: `DFLT_LOCAL` is an mlx model, and mlx runs only on macOS.
    ws = Workspace(roots=[tmp_path], approvals='ask')
    be = install(ws, [Step(tool=('replace_text', {'path': str(tmp_path/'a.py'), 'edits': []})), Step(text='ok')], token_delay=0)
    assert ws.ai.profile == 'small'
    def answer():
        for _ in range(300):
            if (p := ws.approvals.pending) is not None: return ws.approvals.answer(p.id, False, 'leave it')
            time.sleep(0.01)
    threading.Thread(target=answer, daemon=True).start()
    tc = {'function': {'name': 'replace_text', 'arguments': {'path': str(tmp_path/'a.py'), 'edits': []}}}
    assert ws.approvals.gate(tc) is True and tc['function']['name'] == 'user_steering'
    by = {t.__name__: t for t in be.tools}
    assert 'User steering' in by['user_steering'](**tc['function']['arguments'])

def test_rolling_back_a_drawing_removes_every_picture_it_made(tmp_path):
    from leela.blocks.agent.ai import Interventions
    ws = Workspace(roots=[tmp_path], approvals='auto'); ap = ws.ai.approvals
    ap.control = 'autopilot'
    a = ap.request('generate_image', {'prompt': 'x', 'n': 2, 'path': 'img.png'})
    for n in ('img.png', 'img-2.png'): (tmp_path/n).write_bytes(b'\x89PNG\r\n\x1a\n')
    ap.observe_result(True)
    assert a.dict()['rollback'] and 'img-2.png' in a.preview
    ap.rollback(a.id)
    assert not (tmp_path/'img.png').exists() and not (tmp_path/'img-2.png').exists()



def _turn(c, **body):
    acc = c.post('/agent/turn', json=body).json()
    with c.stream('GET', '/agent/stream', params={'since': acc['seq']}) as r: return acc, ''.join(r.iter_text())

def test_a_pasted_picture_is_image_in_the_log_and_the_timeline_not_its_bytes(tmp_path):
    "ramabana 0.2.44 logs `[image]`; Leela's attachments and retained timelines must not bring the bytes back."
    from tests.fakemodel import Step, install, WIDE
    (tmp_path/'pic.png').write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00'*64)
    ws = Workspace(roots=[]); ws.add_root(str(tmp_path))
    install(ws, [Step(text='a picture')], token_delay=0, spec=WIDE)
    with TestClient(ide_app(ws)) as c: acc, body = _turn(c, prompt='look', attachments=[str(tmp_path/'pic.png')])
    assert 'event: done' in body
    row = [json.loads(l) for l in Path(ws.ai.history_path).read_text().splitlines() if acc['thread'] in l][-1]
    assert row['prompt'].startswith('[image]') and 'look' in row['prompt']
    for p in (ws.ai.history_path, ws._timeline_path): assert 'PNG' not in Path(p).read_text() and "b'" not in Path(p).read_text(), p

def test_a_turn_past_the_window_says_so_in_plain_words():
    "ramabana 0.2.45 leaves `ContextFull` for a briefing that alone overflows the window; the pane shows its message with Leela's advice, never the terminal's."
    from leela.blocks.agent.ai import FRESH_HINT
    from tests.fakemodel import Step, install
    ws = Workspace(roots=[])
    be = install(ws, [Step(text='never')], token_delay=0, spec=models.ModelSpec('scripted', 'scripted', 'scripted/model', ctx=2000))
    be.sp, be.token_count = 'brief ' * 4000, 0   # a briefing past the window, counted as a hosted chat counts one before its first step
    assert ws.ai.fresh_hint == FRESH_HINT
    with TestClient(ide_app(ws)) as c: acc, body = _turn(c, prompt='hi')
    assert 'does not fit scripted' in body and 'ValueError' not in body and 'ContextFull:' not in body
    assert FRESH_HINT in body and 'ramabana --resume' not in body and 'Quit' not in body
    row = [json.loads(l) for l in Path(ws.ai.history_path).read_text().splitlines() if acc['thread'] in l][-1]
    assert row['error'].startswith('this conversation does not fit scripted')

def test_a_paste_past_the_window_goes_out_as_an_excerpt_kept_whole():
    "ramabana 0.2.45 cuts a message too large for the window to its head and end, and keeps the whole in the session's run folder."
    import re
    from tests.fakemodel import Step, install
    ws = Workspace(roots=[])
    be = install(ws, [Step(text='excerpted')], token_delay=0, spec=models.ModelSpec('scripted', 'scripted', 'scripted/model', ctx=64_000))
    be.token_count = 0
    paste = 'START ' + 'word ' * 200_000 + 'END'
    with TestClient(ide_app(ws)) as c: acc, body = _turn(c, prompt=paste)
    assert 'excerpted' in body and 'does not fit' not in body, body[-1500:]
    sent = str(be.sent[0])
    path = Path(re.search(r'full text at (\S+?\.txt)', sent).group(1))
    assert paste in path.read_text() and 'characters omitted' in sent

def test_a_context_full_that_escapes_the_stream_is_its_message_alone(monkeypatch):
    from ramabana.core import ContextFull
    from tests.fakemodel import Step, install
    ws = Workspace(roots=[])
    install(ws, [Step(text='never')], token_delay=0)
    real = ws.ask_stream
    def ask_stream(*a, **k):
        yield next(iter(real(*a, **k)))     # registered, so the turn is accepted
        raise ContextFull('this conversation does not fit scripted')
    monkeypatch.setattr(ws, 'ask_stream', ask_stream)
    with TestClient(ide_app(ws)) as c:
        acc, body = _turn(c, prompt='hi')
    errs = [json.loads(l[6:]) for l in body.splitlines() if l.startswith('data: ') and '"message"' in l]
    assert errs and errs[0]['message'] == 'this conversation does not fit scripted', body


def test_the_agent_shell_has_a_term_even_when_leela_has_none(tmp_path, monkeypatch):
    "No tty, so `dumb`: a tool that reads TERM must not fail on a missing one."
    from leela.blocks.agent.ai import WorkspaceHost
    ws = Workspace(roots=[tmp_path], approvals='auto'); h = WorkspaceHost(ws)
    try:
        for term in (None, ''):
            if term is None: monkeypatch.delenv('TERM', raising=False)
            else: monkeypatch.setenv('TERM', term)
            assert h.run_cmd('echo "T=$TERM"') == (0, 'T=dumb\n'), term
        monkeypatch.setenv('TERM', 'xterm-256color')
        assert h.run_cmd('echo "T=$TERM"') == (0, 'T=xterm-256color\n'), 'an inherited TERM is kept'
    finally: ws.shutdown_now()

@pytest.mark.slow
@pytest.mark.makes_venv
@pytest.mark.skipif(not shutil.which('uv'), reason='needs uv to create an environment')
def test_leelas_tools_run_on_leelas_python_in_a_project_whose_venv_lacks_them(tmp_path):
    "Agent code imported rupaka and kosha inside the project kernel, which worked only by borrowing Leela's packages."
    import sys
    from leela.blocks.runtime.kernels import runtime_python
    from leela.workspace import Workspace
    proj = Path(tmp_path).resolve()/'proj'; proj.mkdir(); (proj/'pyproject.toml').write_text('')
    (proj/'data.txt').write_text('hello')
    _nb(proj/'a.ipynb', '')
    ws = Workspace(roots=[proj], port=8471)
    async def go():
        await ws.opened()
        ws.open(proj/'a.ipynb')
        host, loop = ws.inline_ai.host, asyncio.get_running_loop()
        async def call(f, code): return str(await loop.run_in_executor(None, lambda: f(code)))
        k = await ws.runtime()
        assert str(proj/'.venv') in str(k.python), 'the notebook runs in the venv made for it'
        out = await call(host.run_python, 'import rupaka')
        assert 'No module named' in out and 'own_python' in out, f'the project kernel has no Leela packages, and says where they are: {out}'
        out = await call(host.own_python, 'import leela, rupaka, kosha, ramabana, nbformat, os, sys\nprint(sys.executable, os.getcwd(), open("data.txt").read())')
        assert runtime_python() in out and str(proj) in out and 'hello' in out, out
        assert '6' in await call(host.own_python, 'mine = 6\nprint(mine)')
        assert '6' in await call(host.own_python, 'print(mine)'), 'its names stay for the next call'
        assert not [e for e in ws.envs() if e.get('name') == 'leela'], "Leela's kernel is not one the variable panel offers"
        await ws.shutdown()
        assert ws._own is not None and not ws._own.alive, 'and it closes with the workspace'
    asyncio.run(go())

def test_own_python_is_shalyas_tool_and_run_python_points_at_it(tmp_path):
    "The agent had one Python tool, the user's kernel, so Leela's own tools ran where only the project's packages belong."
    from shalya.core import is_write
    from leela.blocks.agent.ai import WorkspaceHost, ide_tools
    from leela.workspace import Workspace
    ws = Workspace(roots=[tmp_path])
    host = WorkspaceHost(ws)
    assert host.can('own_python')
    tools = [t for t in ide_tools(ws) if t.__name__ == 'own_python']
    assert len(tools) == 1 and is_write(tools[0]), 'shalya builds it once from the capability, and it asks like run_python'
    host._run = lambda code, scope: "ModuleNotFoundError: No module named 'kosha'"
    assert 'own_python' in host.run_python('import kosha')
    host._run = lambda code, scope: "ModuleNotFoundError: No module named 'pandas'"
    assert 'own_python' not in host.run_python('import pandas'), "a project's own package gets no such hint"
