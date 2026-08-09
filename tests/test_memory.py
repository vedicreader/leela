"""Fetched pages become durable, navigable litesearch document trees."""

from types import SimpleNamespace
import json
import numpy as np

from leela.memory import Memory
from leela.research import Doc, Research
from leela.fs import Sandbox


class FakeKosha:
    def emb_doc(self, texts, **kw):
        return np.asarray([[len(t) % 17, t.count('memory'), t.count('agent'), 1] for t in texts], dtype=np.float16)
    def emb_query(self, text):
        return np.asarray([len(text) % 17, text.count('memory'), text.count('agent'), 1], dtype=np.float16)


def test_remembered_page_has_a_tree_and_searchable_sections(tmp_path):
    mem = Memory(kosha=lambda: FakeKosha(), path=tmp_path/'memory.db')
    doc = Doc(title='Agent memory notes', url='https://example.com/memory', kind='page', text='''
# Memory systems

Simple structured memory can outperform elaborate retrieval.

## Evaluation

Measure recall accuracy and latency for every agent memory design.
''')
    saved = mem.remember(doc)
    assert saved['nodes'] >= 3 and saved['chunks'] >= 2
    assert mem.status()['documents'] == 1
    toc = mem.toc(saved['doc_id'])
    assert toc[0]['title'] == 'Agent memory notes'
    children = toc[0]['tree'].get('children', [])
    assert any(row['title'] == 'Memory systems' for row in children)
    hits = mem.search('recall accuracy agent memory')
    assert hits and hits[0]['node_id']
    section = mem.read(hits[0]['node_id'])
    assert 'recall accuracy' in section['text']
    # Same URL and title is a no-op until its content changes, then it is refreshed in place.
    assert mem.remember(doc)['skipped']
    doc.text += '\n\n## Update\n\nNew durable memory material.'
    refreshed = mem.remember(doc)
    assert refreshed['nodes'] >= 4 and mem.status()['documents'] == 1


def test_research_automatically_remembers_sources_and_query_brief(monkeypatch, tmp_path):
    mem = Memory(kosha=lambda: FakeKosha(), path=tmp_path/'memory.db')
    research = Research(Sandbox([tmp_path]), memory=mem)
    hits = [{'title': 'One', 'href': 'https://one.example'}, {'title': 'Two', 'href': 'https://two.example'}]
    pages = [object(), object()]
    fake = SimpleNamespace(
        search=lambda *a, **k: hits,
        fetch_all=lambda *a, **k: pages,
        to_md=lambda page, **kw: '# Findings\n\nAgent memory evidence ' * 100,
    )
    monkeypatch.setattr(research, '_fossick', lambda: fake)
    docs, digest = research.dig('agent memory evidence', n=2)
    assert len(docs) == 2 and digest
    remembered = mem.documents()
    assert {row['kind'] for row in remembered} == {'page', 'research'}
    assert any(row['title'] == 'Research: agent memory evidence' for row in remembered)


def test_research_can_read_without_adding_to_memory(monkeypatch, tmp_path):
    mem = Memory(kosha=lambda: FakeKosha(), path=tmp_path/'memory.db')
    research = Research(Sandbox([tmp_path]), memory=mem)
    fake = SimpleNamespace(fetch=lambda *a, **k: object(),
                           to_md=lambda *a, **k: '# Private result\n\nDo not retain this page. ' * 60)
    monkeypatch.setattr(research, '_fossick', lambda: fake)
    doc = research.read('https://sensitive.example/result', remember=False)
    assert doc and not doc.memory_id
    assert mem.status()['documents'] == 0


def test_memory_can_forget_a_document_and_all_its_sections(tmp_path):
    mem = Memory(kosha=lambda: FakeKosha(), path=tmp_path/'memory.db')
    saved = mem.remember(Doc('Temporary', 'https://temporary.example', '# Note\n\nForget this research.'))
    assert mem.forget(saved['doc_id'])
    assert mem.status()['documents'] == 0 and mem.status()['chunks'] == 0


def test_memory_can_purge_selected_or_everything(tmp_path):
    mem = Memory(kosha=lambda: FakeKosha(), path=tmp_path/'memory.db')
    one = mem.remember(Doc('Bad result', 'https://bad.example', '# Bad\n\nIrrelevant result.'))
    mem.remember(Doc('Useful result', 'https://good.example', '# Good\n\nUseful result.'))
    assert mem.purge([one['doc_id']]) == 1
    assert [d['title'] for d in mem.documents()] == ['Useful result']
    assert mem.purge() == 1 and mem.status()['documents'] == 0


def test_edited_conversation_state_round_trips_through_memory(tmp_path):
    mem = Memory(kosha=lambda: FakeKosha(), path=tmp_path/'memory.db')
    state = '# Goal\n\nKeep the agent focused.\n\n# Next steps\n\nInspect before editing.'
    saved = mem.remember_agent_state('Focused implementation', state, {'session': 'agent_test'})
    states = mem.agent_states()
    assert saved and states[0]['kind'] == 'agent-state'
    assert states[0]['title'] == 'Focused implementation'
    loaded = mem.agent_state_text(saved['doc_id'])
    assert 'Keep the agent focused' in loaded and 'Inspect before editing' in loaded


def test_agent_memory_notes_can_be_created_edited_and_deleted(tmp_path):
    mem = Memory(kosha=lambda: FakeKosha(), path=tmp_path/'memory.db')
    authored = '# Decision\n\n- Keep the public API stable.\n\n```python\nvalue = 1\n```\n'
    first = mem.remember_agent_note('Architecture', authored)
    note_id = first['doc_id']
    assert mem.agent_notes()[0]['title'] == 'Architecture'
    assert mem.exact_text(note_id) == authored.strip()
    edited = mem.remember_agent_note('Architecture rules', '# Decision\n\nKeep compatibility.', note_id)
    assert edited['doc_id'] != note_id
    assert [note['title'] for note in mem.agent_notes()] == ['Architecture rules']
    assert mem.forget(edited['doc_id'])
    assert mem.agent_notes() == []


def test_workspace_persists_the_active_agent_state(tmp_path):
    from leela.workspace import Workspace
    state_file = tmp_path/'workspace.json'
    ws = Workspace(roots=[tmp_path]); ws.agent_state = '# Goal\n\nStart from reviewed context.'; ws.save(state_file)
    restored = Workspace.load(state_file)
    assert restored.agent_state == ws.agent_state


def test_workspace_persists_per_surface_memory_routing(tmp_path):
    from leela.workspace import Workspace
    path = tmp_path/'workspace.json'; ws = Workspace(roots=[tmp_path])
    ws.agent_memory_selection = {'agent': ['one'], 'inline': ['one', 'two'], 'completion': ['two']}
    ws.save(path); restored = Workspace.load(path)
    assert restored.agent_memory_selection == ws.agent_memory_selection


def test_workspace_load_restores_a_remembered_agent_state_for_the_project(tmp_path, monkeypatch):
    from leela.memory import Memory
    from leela.workspace import Workspace
    root = tmp_path/'project'; root.mkdir()
    monkeypatch.setattr(Memory, 'agent_states', lambda self: [{
        'id': 'remembered', 'meta': {'agent': {'roots': [str(root)]}}}])
    monkeypatch.setattr(Memory, 'agent_state_text', lambda self, doc_id: '# Goal\n\nFollow this project.')
    state = tmp_path/'workspace.json'
    state.write_text(json.dumps({'roots': [str(root)]}))
    restored = Workspace.load(state)
    assert restored.agent_state_layers['task']['source'] == 'memory'
    assert 'Follow this project' in restored.agent_state


def test_clusters_report_why_a_small_memory_cannot_form_topics(tmp_path):
    mem = Memory(kosha=lambda: FakeKosha(), path=tmp_path/'memory.db')
    mem.remember(Doc('One note', 'https://one.example', '# Note\n\nA small memory entry.'))
    result = mem.clusters()
    assert 'note' in result and 'clusters' in result
