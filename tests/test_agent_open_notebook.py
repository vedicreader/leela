"The agent's notebook tools act on the open tab's notebook, unsaved edits included, not on the file."

import sys
import pytest
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.blocks.nb.nb import Cell, Notebook
from leela.workspace import Workspace

@pytest.fixture
def rig(tmp_path):
    p = tmp_path/'a.ipynb'
    Notebook([Cell(source="print('disk')", id='c1'), Cell(source='# notes', cell_type='markdown', id='m1')]).save(p)
    ws = Workspace(roots=[tmp_path], approvals='auto', python=sys.executable)
    ws.open(p)
    try:
        with TestClient(ide_app(ws)) as client:
            client.get('/tab/state')
            tab, live, _ = ws.docstore.owner(str(p))
            live.cells[0].source = "print('unsaved')"   # the person's edit, mirrored to the server, not saved
            yield dict(p=p, tab=tab, live=live, tools={t.__name__: t for t in ws.ai.tools}, client=client)
    finally: ws.shutdown_now()

def disk(p): return [c.source for c in Notebook.load(p).cells]

def test_the_agent_reads_the_unsaved_source(rig):
    t, p = rig['tools'], str(rig['p'])
    assert "print('unsaved')" in t['notebook_cells'](path=p)
    assert "print('unsaved')" in t['view_cell'](path=p, cell_id='c1')

def test_an_agent_edit_lands_in_the_tab_and_not_on_disk(rig):
    t, p, live = rig['tools'], str(rig['p']), rig['live']
    out = t['edit_cell'](path=p, cell_id='c1', edits=[{'oldText': 'unsaved', 'newText': 'agent'}])
    assert 'replaced 1' in out, out
    assert live.cells[0].source == "print('agent')" and rig['tab'].dirty
    assert disk(rig['p']) == ["print('disk')", '# notes'], 'the file is untouched until the person saves'
    assert 'added cell' in t['add_cell'](path=p, source='x = 1')
    assert [c.source for c in live.cells][-1] == 'x = 1' and len(disk(rig['p'])) == 2

def test_an_older_page_write_does_not_undo_the_agent_edit(rig):
    t, p, live = rig['tools'], str(rig['p']), rig['live']
    t['edit_cell'](path=p, cell_id='c1', edits=[{'oldText': 'unsaved', 'newText': 'agent'}])
    r = rig['client'].post('/nb/edit', json={'path': p, 'op': 'source', 'id': 'c1', 'source': "print('stale')", 'seq': 1})
    assert live.cells[0].source == "print('agent')", r.text

def test_run_cell_runs_the_unsaved_source_and_keeps_the_output_in_the_tab(rig):
    out = rig['tools']['run_cell'](path=str(rig['p']), cell_id='c1')
    assert 'unsaved' in out and 'disk' not in out, out
    assert any('unsaved' in str(o) for o in rig['live'].cells[0].outputs) and rig['tab'].dirty
