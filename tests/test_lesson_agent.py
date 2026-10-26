import json
from types import SimpleNamespace
import pytest
from rupaka.spec import gallery, validate
from leela.blocks.agent.ai import Interventions, WorkspaceHost, WRITE_TOOLS, _session_tools
from leela.blocks.fs.fs import Sandbox
from leela.blocks.nb.lesson import LESSON_CHARTER, demo_refusal, fence, lesson_notebook
from leela.blocks.nb.nb import Cell, Notebook
from leela.workspace import Tab, Workspace
from tests.fakemodel import WIDE, install

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
    assert LESSON_CHARTER not in ai.system_prompt()
    assert 'add_demo' in {f.__name__ for f in ai._plain}
    ws.activate(ws.find(lesson))
    assert LESSON_CHARTER in ai.system_prompt()
    ws.activate(ws.find(ordinary))
    assert LESSON_CHARTER not in ai.system_prompt()
    ws.close()
    assert LESSON_CHARTER in ai.system_prompt()
    ws.close()
    assert LESSON_CHARTER not in ai.system_prompt()

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
    assert (LESSON_CHARTER in be.sp) == start_lesson
    for target in (not start_lesson, start_lesson):
        ws.activate(ws.find(lesson if target else ordinary))
        assert (LESSON_CHARTER in ai.system_prompt()) == target
        ai._forget()
        _ = ai.tools
        count = len(prompts)
        ai._follow_mode()
        assert len(prompts) == count + 1
        assert (LESSON_CHARTER in be.sp) == target
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
        assert LESSON_CHARTER in be.sp
        assert ('news_latest' in {f.__name__ for f in be.tools}) == followed

@pytest.mark.parametrize('tab', [None, Tab(path='', kind='notebook', scratch=True), Tab(path='missing.ipynb'), Tab(path='broken.ipynb'), Tab(path='note.py')])
def test_unreadable_or_non_notebook_tabs_have_no_lesson_charter(tmp_path, tab):
    ws = Workspace(roots=[tmp_path])
    if tab:
        tab.path = str(tmp_path/tab.path) if tab.path else ''
        if tab.path.endswith('broken.ipynb'): (tmp_path/'broken.ipynb').write_text('{broken')
        ws.tabs.append(tab)
    assert LESSON_CHARTER not in ws.ai.system_prompt()
