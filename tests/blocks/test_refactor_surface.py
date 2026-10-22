"The destructive half of the refactor block: `/replace/apply` against a real workspace."

from __future__ import annotations

from starlette.testclient import TestClient

from leela.app import ide_app
from leela.workspace import Workspace

def client(tmp_path):
    ws = Workspace(roots=[tmp_path], port=8000)
    return TestClient(ide_app(ws)), ws

def preview(c, **kw):
    r = c.post('/replace/preview', json={'find': 'alpha', 'replace': 'beta', **kw})
    assert r.status_code == 200, r.text
    return r.json()

def test_preview_then_apply_writes_exactly_the_previewed_text_and_journals_it(tmp_path):
    (tmp_path/'a.py').write_text('alpha = 1\nprint(alpha)\n')
    (tmp_path/'b.txt').write_text('alpha\n')
    c, ws = client(tmp_path)
    d = preview(c)
    assert d['summary'] == {'files': 2, 'edits': 3, 'skipped': d['summary']['skipped']}
    previewed = {f['path']: f['after'] for f in d['files']}
    r = c.post('/replace/apply', json={'token': d['token']})
    assert r.status_code == 200, r.text
    assert (tmp_path/'a.py').read_text() == previewed[str(tmp_path/'a.py')] == 'beta = 1\nprint(beta)\n'
    assert (tmp_path/'b.txt').read_text() == 'beta\n'
    op = r.json()['operation']
    assert op['kind'] == 'replace-text' and len(op['resources']) == 2
    assert ws.journal.rows()[0]['id'] == op['id']
    ws.journal.undo(op['id'])
    assert (tmp_path/'a.py').read_text() == 'alpha = 1\nprint(alpha)\n'

def test_apply_refuses_a_file_that_changed_after_the_preview(tmp_path):
    (tmp_path/'a.py').write_text('alpha = 1\n')
    c, _ = client(tmp_path)
    d = preview(c)
    (tmp_path/'a.py').write_text('alpha = 2\n')
    r = c.post('/replace/apply', json={'token': d['token']})
    assert r.status_code == 409 and r.json()['error']
    assert (tmp_path/'a.py').read_text() == 'alpha = 2\n'


def test_files_that_are_not_utf8_are_skipped_rather_than_rewritten_lossily(tmp_path):
    "The sandbox decodes with `errors='replace'`; writing that back would eat the bytes."
    (tmp_path/'legacy.txt').write_bytes(b'caf\xe9 alpha\n')
    c, _ = client(tmp_path)
    d = preview(c)
    assert not d['files'] and str(tmp_path/'legacy.txt') in d['skipped']
    assert (tmp_path/'legacy.txt').read_bytes() == b'caf\xe9 alpha\n'
