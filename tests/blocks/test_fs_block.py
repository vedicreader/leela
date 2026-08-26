"""The file tree's operations: what they do to disk, to the journal and to what is open.

These four routes were the only mutating surface in the codebase with no tests, which is a fair
part of why a folder delete left no record and a rename of a PNG could destroy it.
"""

from __future__ import annotations
import json
from pathlib import Path
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.workspace import Workspace

PNG = bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489')

def ws_client(tmp_path, cfg):
    "A workspace whose journal, history and trash are under `cfg` rather than the real config dir."
    import leela.workspace as w
    w.leela_cfg = cfg
    ws = Workspace(roots=[tmp_path])
    return ws, TestClient(ide_app(ws))

def test_deleting_a_folder_is_recorded_and_comes_back_whole(tmp_path, monkeypatch):
    """It used to record nothing at all: `before` was only read for a file, and the journal row was
    conditional on it, so a recursive tree removal left no row, no version and no undo."""
    monkeypatch.setattr('leela.workspace.leela_cfg', tmp_path/'cfg')
    (tmp_path/'pkg').mkdir()
    (tmp_path/'pkg'/'a.py').write_text('x = 1\n')
    (tmp_path/'pkg'/'deep').mkdir()
    (tmp_path/'pkg'/'deep'/'b.py').write_text('y = 2\n')
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        assert client.post('/fs/delete', json={'path': str(tmp_path/'pkg')}).status_code == 200
        assert not (tmp_path/'pkg').exists()
        op = ws.journal.rows()[0]
        assert op['kind'] == 'delete' and op['reversible'], 'a folder delete has to be reversible'
        ws.journal.undo(op['id'])
    assert (tmp_path/'pkg'/'a.py').read_text() == 'x = 1\n'
    assert (tmp_path/'pkg'/'deep'/'b.py').read_text() == 'y = 2\n', 'the whole tree, not just the top'

def test_deleting_and_undoing_a_binary_returns_the_same_bytes(tmp_path, monkeypatch):
    "It was journalled as `errors='replace'` text, so undo rewrote a PNG as replacement characters."
    monkeypatch.setattr('leela.workspace.leela_cfg', tmp_path/'cfg')
    p = tmp_path/'logo.png'; p.write_bytes(PNG)
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        assert client.post('/fs/delete', json={'path': str(p)}).status_code == 200
        assert not p.exists()
        ws.journal.undo()
    assert p.read_bytes() == PNG, 'byte for byte, or the file was not recovered'

def test_renaming_a_binary_and_undoing_it_keeps_one_intact_copy(tmp_path, monkeypatch):
    """Rename recorded two text rows, so undoing a renamed image wrote mojibake to the old path and
    unlinked the good file at the new one, leaving no intact copy anywhere."""
    monkeypatch.setattr('leela.workspace.leela_cfg', tmp_path/'cfg')
    p = tmp_path/'logo.png'; p.write_bytes(PNG)
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        r = client.post('/fs/rename', json={'path': str(p), 'name': 'mark.png'})
        assert r.status_code == 200, r.text
        assert (tmp_path/'mark.png').read_bytes() == PNG and not p.exists()
        ws.journal.undo()
    assert p.read_bytes() == PNG and not (tmp_path/'mark.png').exists()

def test_a_rename_moves_the_open_tab_with_the_file(tmp_path, monkeypatch):
    """The tab kept the old path, so its next save saw a `missing` disk version, and the conflict
    dialog offered to force it through, recreating the file under the name it was renamed away from.
    """
    monkeypatch.setattr('leela.workspace.leela_cfg', tmp_path/'cfg')
    p = tmp_path/'mod.py'; p.write_text('VALUE = 1\n')
    ws = Workspace(roots=[tmp_path]); ws.open(p)
    with TestClient(ide_app(ws)) as client:
        client.get('/tab/state', params={'path': str(p)})
        r = client.post('/fs/rename', json={'path': str(p), 'name': 'renamed.py'})
        assert r.json()['retargeted'] == [str(tmp_path/'renamed.py')]
        assert [t.path for t in ws.tabs] == [str(tmp_path/'renamed.py')]
        assert ws.tabs[0].title == 'renamed.py'
        state = client.get('/tab/state', params={'path': str(tmp_path/'renamed.py')}).json()
        assert state['disk_version'] != 'missing', 'the tab is on a file that is really there'

def test_a_reused_path_does_not_serve_the_deleted_file_from_cache(tmp_path, monkeypatch):
    "`/tab/state` prefers a cached buffer to the disk, so the deleted text came back and could be saved."
    monkeypatch.setattr('leela.workspace.leela_cfg', tmp_path/'cfg')
    p = tmp_path/'notes.md'; p.write_text('the old file\n')
    ws = Workspace(roots=[tmp_path]); ws.open(p)
    with TestClient(ide_app(ws)) as client:
        assert 'the old file' in client.get('/tab/state', params={'path': str(p)}).json()['text']
        client.post('/fs/delete', json={'path': str(p)})
        p.write_text('a different file with the same name\n')
        ws.open(p)
        assert client.get('/tab/state', params={'path': str(p)}).json()['text'].strip() == \
            'a different file with the same name'

def test_deleting_a_folder_closes_the_tabs_inside_it(tmp_path, monkeypatch):
    """The close matched one exact path, so tabs on files inside a deleted directory stayed open and
    dirty, and the tab strip is index-addressed, so the indices to the right went stale."""
    monkeypatch.setattr('leela.workspace.leela_cfg', tmp_path/'cfg')
    (tmp_path/'pkg').mkdir()
    inside, outside = tmp_path/'pkg'/'a.py', tmp_path/'keep.py'
    inside.write_text('x = 1\n'); outside.write_text('y = 2\n')
    ws = Workspace(roots=[tmp_path]); ws.open(inside); ws.open(outside)
    with TestClient(ide_app(ws)) as client:
        r = client.post('/fs/delete', json={'path': str(tmp_path/'pkg')})
        assert r.json()['closed'] == [str(inside)]
    assert [t.path for t in ws.tabs] == [str(outside)], 'only the tab inside it closes'

def test_a_recovered_delete_can_be_thrown_away_again(tmp_path, monkeypatch):
    "Redo has to reverse a trashed row as well, or the second half of undo/redo is missing."
    monkeypatch.setattr('leela.workspace.leela_cfg', tmp_path/'cfg')
    (tmp_path/'pkg').mkdir(); (tmp_path/'pkg'/'a.py').write_text('x = 1\n')
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        client.post('/fs/delete', json={'path': str(tmp_path/'pkg')})
        ws.journal.undo()
        assert (tmp_path/'pkg'/'a.py').is_file()
        ws.journal.redo()
        assert not (tmp_path/'pkg').exists()
        ws.journal.undo()
        assert (tmp_path/'pkg'/'a.py').read_text() == 'x = 1\n'

def test_an_undo_refuses_when_the_path_was_taken_back(tmp_path, monkeypatch):
    "Restoring over something someone else put there would be the loss this is meant to prevent."
    monkeypatch.setattr('leela.workspace.leela_cfg', tmp_path/'cfg')
    p = tmp_path/'gone.py'; p.write_text('x = 1\n')
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        client.post('/fs/delete', json={'path': str(p)})
        p.write_text('someone else wrote this\n')
        try:
            ws.journal.undo(); assert False, 'it must refuse'
        except ValueError as e: assert 'there again' in str(e)
    assert p.read_text() == 'someone else wrote this\n'

def test_moving_a_selection_is_one_undoable_operation(tmp_path, monkeypatch):
    monkeypatch.setattr('leela.workspace.leela_cfg', tmp_path/'cfg')
    (tmp_path/'dest').mkdir()
    a, b = tmp_path/'a.py', tmp_path/'b.py'
    a.write_text('x = 1\n'); b.write_text('y = 2\n')
    ws = Workspace(roots=[tmp_path]); ws.open(a)
    with TestClient(ide_app(ws)) as client:
        r = client.post('/fs/move', json={'paths': [str(a), str(b)], 'dest': str(tmp_path/'dest')})
        assert r.json()['ok'] and not r.json()['failed']
        assert (tmp_path/'dest'/'a.py').read_text() == 'x = 1\n'
        assert (tmp_path/'dest'/'b.py').read_text() == 'y = 2\n'
        assert [t.path for t in ws.tabs] == [str(tmp_path/'dest'/'a.py')], 'the open tab follows'
        assert len(ws.journal.rows()) == 1, 'one operation, not one per file'
        ws.journal.undo()
    assert a.read_text() == 'x = 1\n' and b.read_text() == 'y = 2\n'
    assert not (tmp_path/'dest'/'a.py').exists()

def test_a_move_that_fails_part_way_reports_which_and_stays_undoable(tmp_path, monkeypatch):
    "One name already taken in the destination must not cost the rest of the selection."
    monkeypatch.setattr('leela.workspace.leela_cfg', tmp_path/'cfg')
    (tmp_path/'dest').mkdir()
    (tmp_path/'dest'/'clash.py').write_text('already here\n')
    a, clash = tmp_path/'a.py', tmp_path/'clash.py'
    a.write_text('x = 1\n'); clash.write_text('mine\n')
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        r = client.post('/fs/move', json={'paths': [str(a), str(clash)],
                                          'dest': str(tmp_path/'dest')}).json()
        assert r['ok'] is False
        assert r['moved'] == [str(tmp_path/'dest'/'a.py')]
        assert [Path(f['path']).name for f in r['failed']] == ['clash.py']
        assert clash.read_text() == 'mine\n', 'the one that failed is untouched'
        assert (tmp_path/'dest'/'clash.py').read_text() == 'already here\n', 'and so is what was there'
        ws.journal.undo()
    assert a.read_text() == 'x = 1\n', 'the part that did happen is still reversible'

def test_copy_and_duplicate_never_overwrite_and_undo_removes_the_copy(tmp_path, monkeypatch):
    monkeypatch.setattr('leela.workspace.leela_cfg', tmp_path/'cfg')
    src = tmp_path/'mod.py'; src.write_text('x = 1\n')
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        r = client.post('/fs/copy', json={'paths': [str(src)], 'duplicate': True}).json()
        assert r['created'] == [str(tmp_path/'mod copy.py')]
        assert (tmp_path/'mod copy.py').read_text() == 'x = 1\n'
        assert src.read_text() == 'x = 1\n', 'the original is untouched'
        assert client.post('/fs/copy', json={'paths': [str(src)], 'duplicate': True}).json()['created'] \
            == [str(tmp_path/'mod copy 2.py')], 'a second duplicate takes the next free name'
        ws.journal.undo()
        assert not (tmp_path/'mod copy 2.py').exists(), 'undoing a copy removes it'
        ws.journal.redo()
        assert (tmp_path/'mod copy 2.py').read_text() == 'x = 1\n', 'and redo brings it back'

def test_copying_a_folder_takes_the_whole_tree(tmp_path, monkeypatch):
    monkeypatch.setattr('leela.workspace.leela_cfg', tmp_path/'cfg')
    (tmp_path/'pkg'/'deep').mkdir(parents=True)
    (tmp_path/'pkg'/'deep'/'a.py').write_text('x = 1\n')
    (tmp_path/'into').mkdir()
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        r = client.post('/fs/copy', json={'paths': [str(tmp_path/'pkg')],
                                          'dest': str(tmp_path/'into')}).json()
        assert r['ok'], r
        assert (tmp_path/'into'/'pkg'/'deep'/'a.py').read_text() == 'x = 1\n'
        ws.journal.undo()
    assert not (tmp_path/'into'/'pkg').exists()
    assert (tmp_path/'pkg'/'deep'/'a.py').read_text() == 'x = 1\n', 'the source is never touched'

def test_a_folder_cannot_be_copied_or_moved_into_itself(tmp_path, monkeypatch):
    monkeypatch.setattr('leela.workspace.leela_cfg', tmp_path/'cfg')
    (tmp_path/'pkg'/'inner').mkdir(parents=True)
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        for route in ('/fs/move', '/fs/copy'):
            r = client.post(route, json={'paths': [str(tmp_path/'pkg')],
                                         'dest': str(tmp_path/'pkg'/'inner')}).json()
            assert r['ok'] is False and r['failed'], route
    assert (tmp_path/'pkg'/'inner').is_dir()

def test_the_tab_strip_can_be_refetched_after_the_server_closes_a_tab(tmp_path, monkeypatch):
    """A folder delete and removing a root both close tabs server-side, and the strip is
    index-addressed, so a stale one makes the next click select and close a different document."""
    monkeypatch.setattr('leela.workspace.leela_cfg', tmp_path/'cfg')
    (tmp_path/'pkg').mkdir()
    inside, outside = tmp_path/'pkg'/'a.py', tmp_path/'keep.py'
    inside.write_text('x = 1\n'); outside.write_text('y = 2\n')
    ws = Workspace(roots=[tmp_path]); ws.open(inside); ws.open(outside)
    with TestClient(ide_app(ws)) as client:
        assert 'a.py' in client.get('/tab/bar').text
        client.post('/fs/delete', json={'path': str(tmp_path/'pkg')})
        bar = client.get('/tab/bar').text
        assert 'a.py' not in bar and 'keep.py' in bar
        assert bar.count('data-i=') == 1, 'one tab left, and it is index 0'
    files = (Path(__file__).resolve().parents[2]/'leela'/'blocks'/'fs'/'files.js').read_text()
    assert files.count('refreshTabStrip()') >= 3, 'delete and remove-root both have to call it'

def test_creating_refuses_the_names_renaming_refuses(tmp_path, monkeypatch):
    """`/fs/new` joined the typed name onto `parent`, so `../sibling/x.py` created the file in
    another folder while `rename` had always refused a separator. Both go through `Sandbox.under`.
    """
    monkeypatch.setattr('leela.workspace.leela_cfg', tmp_path/'cfg')
    (tmp_path/'pkg').mkdir(); (tmp_path/'sibling').mkdir()
    (tmp_path/'pkg'/'mod.py').write_text('x = 1\n')
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        for name in ('../sibling/escaped.py', 'deep/nested.py', '.', '..', ''):
            made = client.post('/fs/new', json={'parent': str(tmp_path/'pkg'), 'name': name})
            renamed = client.post('/fs/rename', json={'path': str(tmp_path/'pkg'/'mod.py'), 'name': name})
            assert made.status_code == renamed.status_code == 400, name
            assert made.json() == renamed.json(), f'{name!r} has to be refused the same way'
        assert not (tmp_path/'sibling'/'escaped.py').exists(), 'nothing lands outside the parent'
        assert not (tmp_path/'pkg'/'deep').exists()
        assert ws.journal.rows() == [], 'a refused name records nothing to undo'
        for name in ('made.py', 'notes.ipynb'):
            assert client.post('/fs/new', json={'parent': str(tmp_path/'pkg'), 'name': name}).json()['ok']
        assert client.post('/fs/new', json={'parent': str(tmp_path/'pkg'), 'name': 'sub',
                                            'kind': 'dir'}).json()['ok']
    assert (tmp_path/'pkg'/'made.py').is_file() and (tmp_path/'pkg'/'sub').is_dir()
    assert json.loads((tmp_path/'pkg'/'notes.ipynb').read_text())['nbformat'] == 4

def test_a_change_on_disk_drops_the_cached_copy_of_a_clean_tab(tmp_path, monkeypatch):
    """Only the active tab's poll refreshed a cached document, so a background tab mounted the
    version from before the change. A tab with unsaved edits holds the user's work, not a copy of
    the file, and keeps what it has."""
    monkeypatch.setattr('leela.workspace.leela_cfg', tmp_path/'cfg')
    from leela.core.block import Ctx
    from leela.core.session import DocStore
    from leela.blocks.fs.app import _freshen
    a, b = tmp_path/'a.py', tmp_path/'b.py'
    a.write_text('A = 1\n'); b.write_text('B = 1\n')
    ws = Workspace(roots=[tmp_path]); ws.open(a); ws.open(b)
    docs = DocStore(ws)
    ctx = Ctx(ws, name='fs', caps=('docs',), docs=docs)
    for t in ws.tabs: docs.docs[t.path], docs.versions[t.path] = 'held', 'v0'
    ws.tabs[1].dirty = True

    _freshen(ctx, [str(a), str(b)])
    assert str(a) not in docs.docs, 'the clean tab has to read the file again'
    assert str(a) not in docs.versions, 'and it must not keep the version it read before'
    assert docs.docs[str(b)] == 'held', 'unsaved edits are never dropped for a disk change'

    docs.docs[str(a)] = 'held'
    _freshen(ctx, [str(tmp_path/'elsewhere.py')])
    assert docs.docs[str(a)] == 'held', 'a change to another file leaves this one alone'

    _freshen(ctx, [], resync=True)
    assert str(a) not in docs.docs, 'too many changes to name means every clean tab re-reads'
    assert docs.docs[str(b)] == 'held'

NB_JSON = ('{"cells": [{"cell_type": "code", "source": ["x = 1"], "metadata": {}, "outputs": [],'
           ' "execution_count": null}], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}')

def test_a_notebook_dropped_by_a_change_on_disk_is_read_back_for_the_next_run(tmp_path, monkeypatch):
    """Freshening a clean tab drops what `DocStore` holds, and `/nb/run` reads that and nothing else,
    so a notebook that was open answered `no notebook open` until it was mounted again."""
    monkeypatch.setattr('leela.workspace.leela_cfg', tmp_path/'cfg')
    from leela.core.session import DocStore
    p = tmp_path/'n.ipynb'; p.write_text(NB_JSON)
    ws = Workspace(roots=[tmp_path]); ws.open(p)
    docs = DocStore(ws)
    tab, nb, _ = docs.owner(str(p))
    assert nb is not None and len(nb) == 1, 'precondition: the run route finds it'

    docs.forget(str(p))                       # what a change on disk does to a clean tab
    tab, nb, _ = docs.owner(str(p))
    assert nb is not None and len(nb) == 1, 'the file is read back rather than reported missing'
    assert docs.versions[str(p)], 'and what was read is stamped with the version it came from'
    docs.forget(str(p))
    assert docs.current() is not None, 'the same holds for the routes that ask for the active tab'

    p.unlink()
    docs.forget(str(p))
    assert docs.owner(str(p))[1] is None, 'a file that is gone is still nothing to run'
