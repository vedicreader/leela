"The destructive half of a move: `/refactor/move` then `/refactor/apply` against a real workspace."

from __future__ import annotations

from starlette.testclient import TestClient

from leela.app import ide_app
from leela.workspace import Workspace

SRC = """\
import math

__all__ = ['area', 'perimeter']


def area(r):
    return math.pi * r ** 2


def perimeter(r):
    return 2 * math.pi * r
"""


def workspace(tmp_path, **files):
    (tmp_path/'shapes.py').write_text(SRC)
    for name, text in files.items(): (tmp_path/name.replace('__', '/')).write_text(text)
    ws = Workspace(roots=[tmp_path], port=8000)
    return TestClient(ide_app(ws)), ws


def move(c, tmp_path, names=('area',), dest='circle.py', **kw):
    r = c.post('/refactor/move', json={'path': str(tmp_path/'shapes.py'), 'names': list(names),
                                       'dest': str(tmp_path/dest), **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_a_move_creates_the_file_and_undo_removes_it_again(tmp_path):
    c, ws = workspace(tmp_path)
    d = move(c, tmp_path)
    made = next(f for f in d['files'] if f['path'].endswith('circle.py'))
    assert made['before'] is None, 'the browser has to be able to tell a new file from a patched one'
    r = c.post('/refactor/apply', json={'token': d['token']})
    assert r.status_code == 200, r.text
    assert (tmp_path/'circle.py').read_text() == made['after']
    assert 'def area' in (tmp_path/'circle.py').read_text()
    assert 'def area' not in (tmp_path/'shapes.py').read_text()
    op = r.json()['operation']
    assert op['kind'] == 'move-symbol'
    ws.journal.undo(op['id'])
    assert not (tmp_path/'circle.py').exists(), 'undo has to take the created file with it'
    assert (tmp_path/'shapes.py').read_text() == SRC


def test_every_file_that_imported_the_name_is_rewritten_in_the_same_operation(tmp_path):
    c, _ = workspace(tmp_path, app_py='from shapes import area, perimeter\n\nprint(area(1), perimeter(2))\n')
    (tmp_path/'app.py').write_text('from shapes import area, perimeter\n\nprint(area(1), perimeter(2))\n')
    d = move(c, tmp_path, shim=False)
    assert c.post('/refactor/apply', json={'token': d['token']}).status_code == 200
    after = (tmp_path/'app.py').read_text()
    assert 'from circle import area' in after and 'from shapes import perimeter' in after


def test_the_source_and_destination_cannot_be_deselected(tmp_path):
    "A move applied to half its files leaves the definition in two places or in none."
    c, _ = workspace(tmp_path)
    (tmp_path/'app.py').write_text('from shapes import area\n\nprint(area(1))\n')
    d = move(c, tmp_path, shim=False)
    r = c.post('/refactor/apply', json={'token': d['token'], 'paths': [str(tmp_path/'app.py')]})
    assert r.status_code == 200, r.text
    assert sorted(x.split('/')[-1] for x in r.json()['paths']) == ['app.py', 'circle.py', 'shapes.py']


def test_a_destination_that_appeared_after_the_preview_is_refused(tmp_path):
    c, _ = workspace(tmp_path)
    d = move(c, tmp_path)
    (tmp_path/'circle.py').write_text('# somebody got there first\n')
    r = c.post('/refactor/apply', json={'token': d['token']})
    assert r.status_code == 409 and 'changed after preview' in r.json()['error']
    assert (tmp_path/'circle.py').read_text() == '# somebody got there first\n'
    assert 'def area' in (tmp_path/'shapes.py').read_text()


def test_an_unsaved_buffer_blocks_the_move(tmp_path):
    c, ws = workspace(tmp_path)
    tab = ws.open(tmp_path/'shapes.py'); tab.dirty = True
    d = move(c, tmp_path)
    r = c.post('/refactor/apply', json={'token': d['token']})
    assert r.status_code == 409 and 'unsaved open files' in r.json()['error']
    assert not (tmp_path/'circle.py').exists()


def test_all_is_kept_honest_at_both_ends(tmp_path):
    c, _ = workspace(tmp_path)
    (tmp_path/'circle.py').write_text("__all__ = ['tau']\n\ntau = 6.28\n")
    d = move(c, tmp_path, shim=False)
    assert c.post('/refactor/apply', json={'token': d['token']}).status_code == 200
    assert "__all__ = ['perimeter']" in (tmp_path/'shapes.py').read_text()
    assert "__all__ = ['tau', 'area']" in (tmp_path/'circle.py').read_text()


def test_the_symbol_picker_lists_what_can_move(tmp_path):
    c, _ = workspace(tmp_path)
    r = c.post('/refactor/symbols', json={'path': str(tmp_path/'shapes.py')})
    assert r.status_code == 200, r.text
    assert [s['name'] for s in r.json()['symbols']] == ['area', 'perimeter']


def test_moving_out_of_a_non_python_file_is_refused(tmp_path):
    c, _ = workspace(tmp_path)
    (tmp_path/'notes.txt').write_text('area\n')
    r = c.post('/refactor/move', json={'path': str(tmp_path/'notes.txt'), 'names': ['area'],
                                       'dest': str(tmp_path/'circle.py')})
    assert 'Python files only' in r.json()['error']


def test_a_destination_outside_the_open_folders_is_refused(tmp_path):
    c, _ = workspace(tmp_path)
    r = c.post('/refactor/move', json={'path': str(tmp_path/'shapes.py'), 'names': ['area'],
                                       'dest': '/etc/circle.py'})
    assert r.status_code == 400 and 'outside the open folders' in r.json()['error']
