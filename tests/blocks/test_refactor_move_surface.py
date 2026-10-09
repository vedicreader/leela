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


def test_the_source_and_destination_cannot_be_deselected(tmp_path):
    "A move applied to half its files leaves the definition in two places or in none."
    c, _ = workspace(tmp_path)
    (tmp_path/'app.py').write_text('from shapes import area\n\nprint(area(1))\n')
    d = move(c, tmp_path, shim=False)
    r = c.post('/refactor/apply', json={'token': d['token'], 'paths': [str(tmp_path/'app.py')]})
    assert r.status_code == 200, r.text
    assert sorted(x.split('/')[-1] for x in r.json()['paths']) == ['app.py', 'circle.py', 'shapes.py']
