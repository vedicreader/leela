"""The file tree's operations: what they do to disk, to the journal and to what is open."""

from __future__ import annotations
import json
from pathlib import Path
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.workspace import Workspace
from leela.blocks.fs.fs import Sandbox

PNG = bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489')

def ws_client(tmp_path, cfg):
    "A workspace whose journal, history and trash are under `cfg` rather than the real config dir."
    import leela.workspace as w
    w.leela_cfg = cfg
    ws = Workspace(roots=[tmp_path])
    return ws, TestClient(ide_app(ws))

def test_deleting_a_folder_is_recorded_and_comes_back_whole(tmp_path, monkeypatch):
    """It used to record nothing at all: `before` was only read for a file, and the journal row was conditional on it, so a recursive tree removal left no row, no version and no undo."""
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


def test_renaming_a_binary_and_undoing_it_keeps_one_intact_copy(tmp_path, monkeypatch):
    """Rename recorded two text rows, so undoing a renamed image wrote mojibake to the old path and unlinked the good file at the new one, leaving no intact copy anywhere."""
    monkeypatch.setattr('leela.workspace.leela_cfg', tmp_path/'cfg')
    p = tmp_path/'logo.png'; p.write_bytes(PNG)
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        r = client.post('/fs/rename', json={'path': str(p), 'name': 'mark.png'})
        assert r.status_code == 200, r.text
        assert (tmp_path/'mark.png').read_bytes() == PNG and not p.exists()
        ws.journal.undo()
    assert p.read_bytes() == PNG and not (tmp_path/'mark.png').exists()


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


def test_creating_refuses_the_names_renaming_refuses(tmp_path, monkeypatch):
    """`/fs/new` joined the typed name onto `parent`, so `../sibling/x.py` created the file in another folder while `rename` had always refused a separator."""
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


def test_the_walk_is_the_project_and_the_rest_is_asked_for(tmp_path, monkeypatch):
    """Dot folders were entered, so agent worktrees under `.claude` filled the 20,000-file cap, took nine seconds and hid the second root."""
    monkeypatch.setattr('leela.workspace.leela_cfg', tmp_path/'cfg')
    proj, gone = tmp_path/'proj', tmp_path/'gone'
    for f in ('src/keys.py', '.claude/wt/keys.py', '.venv/lib/keys.py', 'cache/keys.py', 'src/other.py'):
        (proj/f).parent.mkdir(parents=True, exist_ok=True); (proj/f).write_text('x = 1\n')
    (proj/'.gitignore').write_text('cache/\n')
    gone.mkdir()
    ws = Workspace(roots=[proj, gone])
    gone.rmdir()
    rel = lambda ps: sorted(str(Path(p).relative_to(proj)) for p in ps)
    assert rel(ws.fs.walk()) == ['src/keys.py', 'src/other.py'], 'a vanished root takes nothing else with it'
    with TestClient(ide_app(ws)) as client:
        main = client.get('/fs/find', params={'q': 'keys'}).json()['hits']
        more = client.get('/fs/find', params={'q': 'keys', 'more': 1}).json()['hits']
        assert client.get('/fs/find', params={'more': 1}).json()['hits'] == [], 'everything is never listed whole'
    assert rel(h['path'] for h in main) == ['src/keys.py']
    assert rel(h['path'] for h in more) == ['.claude/wt/keys.py', '.venv/lib/keys.py', 'cache/keys.py']
    xy, xylo = tmp_path/'xy'/'z', tmp_path/'xylophone'
    xy.mkdir(parents=True); xylo.mkdir(); (xylo/'tune.py').write_text('x = 1\n')
    with TestClient(ide_app(Workspace(roots=[xy, xylo]))) as client:
        hits = client.get('/fs/find', params={'q': 'xylophone/tune'}).json()['hits']
    assert [h['name'] for h in hits] == ['tune.py'], 'a root is matched at a separator, not as a prefix of a sibling'


def test_every_root_gets_a_share_of_the_cap(tmp_path):
    """The walk filled its cap from the first root, so a large first root hid every file in the next."""
    big, small = tmp_path/'big', tmp_path/'small'
    big.mkdir(); small.mkdir()
    for i in range(5): (big/f'f{i}.py').write_text('x = 1\n')
    (small/'only.py').write_text('x = 1\n')
    walked = Sandbox([big, small]).walk(limit=3)
    assert len(walked) == 3 and small/'only.py' in walked, walked


def test_environments_are_skipped_at_any_depth(tmp_path):
    """ripgrep matches `skip_dir_re` against the path from the root, so a pattern of bare names only pruned the top level."""
    for f in ('a.py', 'src/node_modules/y/b.py', 'pkg/__pycache__/c.py', 'deep/my-venv/d.py', 'keep/venvy/e.py'):
        (tmp_path/f).parent.mkdir(parents=True, exist_ok=True); (tmp_path/f).write_text('x = 1\n')
    assert sorted(str(p.relative_to(tmp_path)) for p in Sandbox([tmp_path]).walk()) == ['a.py', 'keep/venvy/e.py']


