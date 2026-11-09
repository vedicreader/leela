import json
from types import SimpleNamespace
import pytest
from fastcore.basics import first
from abhyasa.learner import PROMPTS, set_prompt
from rupaka.spec import gallery, validate
from leela.blocks.agent.ai import Interventions, WorkspaceHost, WRITE_TOOLS, _session_tools
from leela.blocks.fs.fs import Sandbox
from leela.blocks.nb.lesson import CHARTER_TAIL, demo_refusal, fence, lesson_notebook
from leela.blocks.nb.nb import Cell, Notebook
from leela.workspace import Tab, Workspace
from tests.fakemodel import WIDE, Step, install

@pytest.fixture
def demo(tmp_path):
    path = tmp_path/'ordinary.ipynb'
    nb = Notebook([Cell(source='before'), Cell(source='after')])
    nb.save(path)
    host = WorkspaceHost(SimpleNamespace(fs=Sandbox([tmp_path]), project_root=tmp_path))
    tools = {f.__name__: f for f in _session_tools(host)}
    assert 'add_demo' in tools
    return tools['add_demo'], path, nb

@pytest.mark.parametrize('spec', gallery().values(), ids=gallery().keys())
def test_add_demo_inserts_one_markdown_cell_after_id(demo, spec):
    add, path, before = demo
    assert not validate(spec)
    result = add(str(path), spec, before[0].id)
    after = Notebook.load(path)
    assert len(after) == len(before) + 1
    assert [after[i].dict() for i in (0, 2)] == [c.dict() for c in before.cells]
    assert after[1].cell_type == 'markdown' and after[1].source == fence(spec)
    assert after[1].id in result

@pytest.mark.parametrize('as_json', [False, True])
def test_add_demo_appends_on_an_unopened_ordinary_notebook(demo, as_json):
    add, path, before = demo
    spec = gallery()['softmax-temperature']
    add(str(path), json.dumps(spec) if as_json else spec)
    after = Notebook.load(path)
    assert [c.id for c in after.cells[:-1]] == [c.id for c in before.cells]
    assert len(after) == len(before) + 1 and after[-1].source == fence(spec)
    assert after[-1].cell_type == 'markdown'

@pytest.mark.parametrize('spec', [{}, [], 3, '[]', '3', dict(gallery()['softmax-temperature'], id='')])
def test_invalid_demo_preserves_validator_lines_and_file_bytes(demo, spec):
    add, path, _ = demo
    before = path.read_bytes()
    errors = validate(json.loads(spec) if isinstance(spec, str) else spec)
    assert errors
    assert add(str(path), spec) == demo_refusal(errors)
    assert path.read_bytes() == before

def test_bad_json_is_refused_with_the_parse_error(demo):
    add, path, _ = demo
    before = path.read_bytes()
    with pytest.raises(json.JSONDecodeError) as err: json.loads('{oops')
    assert str(err.value) in add(str(path), '{oops')
    assert path.read_bytes() == before

def test_unknown_anchor_refuses_without_writing(demo):
    add, path, _ = demo
    before = path.read_bytes()
    result = add(str(path), gallery()['softmax-temperature'], 'unknown-cell')
    assert 'unknown-cell' in result and 'no cell' in result
    assert path.read_bytes() == before

@pytest.mark.parametrize('name', ['missing.ipynb', 'not-a-notebook.py'])
def test_add_demo_requires_an_existing_notebook(demo, name):
    add, path, _ = demo
    other = path.parent/name
    if other.suffix == '.py': other.write_text('pass\n')
    before = other.read_bytes() if other.exists() else None
    assert 'failed' in add(str(other), gallery()['softmax-temperature'])
    assert (other.read_bytes() if other.exists() else None) == before

def test_add_demo_is_approval_gated():
    assert 'add_demo' in WRITE_TOOLS
    gate = Interventions(tools=WRITE_TOOLS, mode='ask')
    assert gate.request('add_demo', {'path': 'ordinary.ipynb', 'spec': {}}, timeout=.01).answer is False

@pytest.mark.parametrize('profile', ['small', 'full'])
def test_lesson_charter_follows_only_the_active_tab(tmp_path, profile):
    lesson = tmp_path/'lesson.ipynb'
    ordinary = tmp_path/'ordinary.ipynb'
    lesson_notebook('Softmax').save(lesson)
    Notebook.blank(ordinary).save(ordinary)
    ws = Workspace(roots=[tmp_path], agent_profile=profile)
    ws.open(lesson)
    ws.open(ordinary)
    ai = ws.ai
    assert CHARTER_TAIL not in ai.system_prompt()
    assert 'add_demo' in {f.__name__ for f in ai._plain}
    ws.activate(ws.find(lesson))
    assert CHARTER_TAIL in ai.system_prompt()
    ws.activate(ws.find(ordinary))
    assert CHARTER_TAIL not in ai.system_prompt()
    ws.close()
    assert CHARTER_TAIL in ai.system_prompt()
    ws.close()
    assert CHARTER_TAIL not in ai.system_prompt()

@pytest.mark.parametrize('start_lesson', [False, True])
def test_live_backend_rebriefs_both_ways_without_tool_rebuilds_hiding_it(tmp_path, monkeypatch, start_lesson):
    lesson = tmp_path/'lesson.ipynb'
    ordinary = tmp_path/'ordinary.ipynb'
    lesson_notebook('Softmax').save(lesson)
    Notebook.blank(ordinary).save(ordinary)
    ws = Workspace(roots=[tmp_path])
    ws.open(lesson)
    ws.open(ordinary)
    ws.activate(ws.find(lesson if start_lesson else ordinary))
    be = install(ws, [], spec=WIDE)
    ai, prompts = ws.ai, []
    refresh = be.refresh
    monkeypatch.setattr(be, 'refresh', lambda sp, tools: (prompts.append(sp), refresh(sp, tools))[-1])
    ai._follow_mode()
    assert (CHARTER_TAIL in be.sp) == start_lesson
    for target in (not start_lesson, start_lesson):
        ws.activate(ws.find(lesson if target else ordinary))
        assert (CHARTER_TAIL in ai.system_prompt()) == target
        ai._forget()
        _ = ai.tools
        count = len(prompts)
        ai._follow_mode()
        assert len(prompts) == count + 1
        assert (CHARTER_TAIL in be.sp) == target
        ai._follow_mode()
        assert len(prompts) == count + 1

def test_feed_changes_still_rebrief_without_changing_lesson_status(tmp_path):
    from leela.blocks.vault.news import Feed
    path = tmp_path/'lesson.ipynb'
    lesson_notebook('Softmax').save(path)
    ws = Workspace(roots=[tmp_path])
    ws.open(path)
    be = install(ws, [], spec=WIDE)
    ai = ws.ai
    ai._follow_mode()
    for followed in (True, False):
        ws.feeds.rows[:] = [Feed(url='https://example.test/feed.xml', title='Example')] if followed else []
        ai._forget()
        _ = ai.tools
        ai._follow_mode()
        assert CHARTER_TAIL in be.sp
        assert ('news_latest' in {f.__name__ for f in be.tools}) == followed

def test_a_saved_tutor_prompt_reaches_the_live_backend_on_the_next_turn(tmp_path, monkeypatch, abhyasa_cfg):
    path = tmp_path/'lesson.ipynb'
    lesson_notebook('Softmax').save(path)
    ws = Workspace(roots=[tmp_path])
    ws.open(path)
    be = install(ws, [Step(text='ok')], token_delay=0, spec=WIDE)
    ai, prompts = ws.ai, []
    refresh = be.refresh
    monkeypatch.setattr(be, 'refresh', lambda sp, tools: (prompts.append(sp), refresh(sp, tools))[-1])
    a, b = 'Prompt A. Ask one question at a time.', 'Prompt B. Never give the answer.'
    set_prompt('tutor', a)
    assert a + CHARTER_TAIL in ai.system_prompt()
    ai.ask('first')
    assert len(prompts) == 1 and a + CHARTER_TAIL in be.sp and ai._briefed_lesson
    ai.ask('second')
    assert len(prompts) == 1
    hist = list(be.hist)
    asked = lambda h: [m['content'].splitlines()[0] for m in h if m['role'] == 'user']
    assert asked(hist) == ['first', 'second']
    set_prompt('tutor', b)
    ai.ask('third')
    assert len(prompts) == 2 and b + CHARTER_TAIL in be.sp and a not in be.sp
    ai.ask('fourth')
    assert len(prompts) == 2
    set_prompt('tutor', '')
    ai.ask('fifth')
    assert len(prompts) == 3 and PROMPTS['tutor'].dflt + CHARTER_TAIL in be.sp and b not in be.sp
    assert be.hist[:len(hist)] == hist
    assert asked(be.hist) == ['first', 'second', 'third', 'fourth', 'fifth']

@pytest.fixture
def walks(tmp_path, monkeypatch, abhyasa_cfg, request):
    "A workspace over a learning store with the test walk; lesson A is step 0, lesson B is step 1 with a `pydantic-ai-slim` exercise."
    from abhyasa.learner import Learning
    from leela.blocks.learn import learn
    from leela.blocks.learn.toolenv import tool_dir, tool_key
    from leela.blocks.memory.memory import Memory
    from tests.learn_data import JID, walk
    from tests.test_lesson_prompt import SPEC
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path/'data'))
    key = tool_key(['pydantic-ai-slim'])
    tool_dir(key).mkdir(parents=True); (tool_dir(key)/'ready').write_text('pydantic-ai-slim\n')
    a, b, c, plain = (tmp_path/f'{n}.ipynb' for n in ('a', 'b', 'c', 'ordinary'))
    lesson_notebook('Softmax', step=dict(walk=JID, step=0)).save(a)
    lesson_notebook('Attention', exercise=SPEC | dict(env=key), step=dict(walk=JID, step=1)).save(b)
    lesson_notebook('Gone', step=dict(walk='nope-1', step=0)).save(c)
    Notebook.blank(plain).save(plain)
    ws = Workspace(roots=[tmp_path], agent_profile=getattr(request, 'param', 'auto'))
    monkeypatch.setattr(ws, 'memory', Memory(path=tmp_path/'vault.db', offline=True))
    lr = Learning(ws.memory._store('learning')); walk(lr)
    for p in (a, b, c, plain): ws.open(p)
    reads, real = [], learn.find_step
    monkeypatch.setattr(learn, 'find_step', lambda lr, q: (reads.append((q.walk, q.step)), real(lr, q))[-1])
    be = install(ws, [], spec=WIDE)
    prompts, refresh = [], be.refresh
    monkeypatch.setattr(be, 'refresh', lambda sp, tools: (prompts.append(sp), refresh(sp, tools))[-1])
    go = lambda p: ws.activate(ws.find(p))
    try: yield SimpleNamespace(ws=ws, ai=ws.ai, be=be, lr=lr, reads=reads, prompts=prompts, go=go, a=a, b=b, c=c, plain=plain, key=key, JID=JID)
    finally: ws.shutdown_now()

A_TEXT, B_TEXT = 'Softmax maps scores to weights.', 'Attention mixes values.'

def test_lesson_a_to_lesson_b_rebriefs_once_with_the_new_step_and_packages(walks):
    w = walks
    w.go(w.a); w.ai._follow_mode()
    assert A_TEXT in w.be.sp and 'Watch the sum.' in w.be.sp and 'pydantic-ai-slim' not in w.be.sp and 'TestModel' not in w.be.sp
    n = len(w.prompts)
    w.go(w.b); w.ai._follow_mode()
    assert len(w.prompts) == n + 1 and B_TEXT in w.be.sp and A_TEXT not in w.be.sp
    assert 'pydantic-ai-slim' in w.be.sp and 'TestModel' in w.be.sp and 'Attention' in w.ai._briefed_charter
    reads = len(w.reads)
    for _ in range(3): w.ai._follow_mode(); w.ai.system_prompt()
    assert len(w.prompts) == n + 1 and len(w.reads) == reads
    w.go(w.a); w.ai._follow_mode()
    assert len(w.prompts) == n + 2 and A_TEXT in w.be.sp and B_TEXT not in w.be.sp

def test_a_store_change_reloads_the_step(walks):
    w = walks
    w.go(w.a); w.ai._follow_mode()
    n, reads = len(w.prompts), len(w.reads)
    j = w.lr.journey(w.JID)
    w.lr.put_journey(dict(j, steps=[dict(j.steps[0], note='Watch the sum again.'), *j.steps[1:]]))
    w.ai._follow_mode()
    assert len(w.reads) == reads + 1 and len(w.prompts) == n + 1 and 'Watch the sum again.' in w.be.sp
    w.ai._follow_mode()
    assert len(w.reads) == reads + 1 and len(w.prompts) == n + 1

def test_tutor_and_library_prompt_edits_reach_the_next_briefing(walks):
    w = walks
    w.go(w.b); w.ai._follow_mode()
    n = len(w.prompts)
    set_prompt('leela.library', 'Library rule X.')
    w.ai._follow_mode()
    assert len(w.prompts) == n + 1 and 'Library rule X.' in w.be.sp and 'TestModel' not in w.be.sp
    set_prompt('tutor', 'Tutor rule Y.')
    w.ai._follow_mode()
    assert len(w.prompts) == n + 2 and 'Tutor rule Y.' in w.be.sp and 'Library rule X.' in w.be.sp and B_TEXT in w.be.sp

def test_a_missing_or_unreadable_walk_never_reuses_the_previous_passage(walks, monkeypatch):
    from leela.blocks.learn import learn
    from leela.blocks.nb.lesson import lesson_charter
    w = walks
    w.go(w.a); w.ai._follow_mode()
    assert A_TEXT in w.be.sp
    w.go(w.c); w.ai._follow_mode()
    assert w.ai._briefed_charter == lesson_charter() and A_TEXT not in w.be.sp
    w.go(w.b); w.ai._follow_mode()
    assert B_TEXT in w.be.sp
    def locked(lr, q): raise OSError('database is locked')
    monkeypatch.setattr(learn, 'find_step', locked)
    w.go(w.a); w.ai._follow_mode()
    assert w.ai._briefed_charter == lesson_charter(packages=()) and A_TEXT not in w.be.sp and B_TEXT not in w.be.sp

def test_the_lesson_context_reads_the_vault_that_holds_the_walk(tmp_path, monkeypatch, abhyasa_cfg):
    from abhyasa.learner import Learning
    from leela.blocks.memory.memory import Memory, learning_store
    from tests.learn_data import JID, walk
    ws = Workspace(roots=[tmp_path], agent_profile='auto')
    monkeypatch.setattr(ws, 'memory', Memory(path=tmp_path/'vault.db', offline=True)); ws.vaults.own = ws.memory
    ws.vaults.create(tmp_path/'learn'/'vault.db', name='learn', agent=True)
    walk(Learning(learning_store(ws.vaults.memory('learn'))))
    a = tmp_path/'a.ipynb'; lesson_notebook('Softmax', step=dict(walk=JID, step=0)).save(a)
    try:
        ws.open(a); ws.activate(ws.find(a))
        assert ws.vaults.active.name == 'workspace' and Learning(learning_store(ws.memory)).journey(JID) is None
        step, _ = ws.ai._lesson_ctx()
        assert step and step['walk'] == JID and A_TEXT in ws.ai._charter()
    finally: ws.shutdown_now()

@pytest.mark.parametrize('walks', ['small', 'full'], indirect=True)
def test_look_up_code_follows_the_lesson_tab(walks):
    w = walks
    names = lambda: ({f.__name__ for f in w.be.tools}, {f.__name__ for f in w.ai.registry.tools})
    for p, want in ((w.a, True), (w.plain, False), (w.b, True), (w.plain, False)):
        w.go(p); w.ai._follow_mode()
        offered, registered = names()
        assert ('look_up_code' in offered) == want and ('look_up_code' in registered) == want
        assert 'add_demo' in offered and sum(f.__name__ == 'look_up_code' for f in w.ai.registry.tools) <= 1

def test_look_up_code_reads_the_current_lessons_environment(walks, monkeypatch):
    from leela.blocks.learn import app
    w = walks
    seen, out = [], {}
    monkeypatch.setattr(app, 'find_code', lambda search, q, names, tool=None: (seen.append((q, list(names), tool)), out['rows'])[-1])
    w.go(w.b); w.ai._follow_mode()
    look = first(f for f in w.ai.registry.tools if f.__name__ == 'look_up_code')
    out['rows'] = None
    assert look('Agent') == app.NO_INDEX
    assert seen[-1] == ('Agent', ['pydantic-ai-slim'], w.key)
    out['rows'] = []
    assert look('Agent') == 'Nothing found.'
    out['rows'] = [dict(name='Agent.run_sync', package='pydantic_ai_slim', path='pydantic_ai/agent.py', line=12, doc='Run the agent.', snippet='def run_sync(self, p):\n    ...')]
    t = look('Agent')
    assert all(x in t for x in ('Agent.run_sync', 'pydantic_ai_slim', 'pydantic_ai/agent.py:12', 'Run the agent.', 'def run_sync'))
    w.go(w.a)
    look('softmax')
    assert seen[-1] == ('softmax', [], None)
    monkeypatch.setattr(app, 'find_code', lambda *a, **k: 1/0)
    assert look('Agent') == app.NO_INDEX

@pytest.mark.parametrize('tab', [None, Tab(path='', kind='notebook', scratch=True), Tab(path='missing.ipynb'), Tab(path='broken.ipynb'), Tab(path='note.py')])
def test_unreadable_or_non_notebook_tabs_have_no_lesson_charter(tmp_path, tab):
    ws = Workspace(roots=[tmp_path])
    if tab:
        tab.path = str(tmp_path/tab.path) if tab.path else ''
        if tab.path.endswith('broken.ipynb'): (tmp_path/'broken.ipynb').write_text('{broken')
        ws.tabs.append(tab)
    assert CHARTER_TAIL not in ws.ai.system_prompt()
