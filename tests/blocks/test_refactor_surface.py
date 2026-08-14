"""The destructive half of the refactor block: `/replace/apply` against a real workspace.

`replace_plan` is unit-tested next door; what is only reachable through the app is the part
that can lose work -- preview and apply agreeing, a concurrent on-disk edit being refused,
and the write being journalled so it can be undone.
"""

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
    (tmp_path/'a.py').write_text('alpha = 2\n')          # somebody else, mid-review
    r = c.post('/replace/apply', json={'token': d['token']})
    assert r.status_code == 409 and 'changed after preview' in r.json()['error']
    assert (tmp_path/'a.py').read_text() == 'alpha = 2\n'


def test_a_token_is_single_use_so_one_preview_cannot_be_applied_twice(tmp_path):
    (tmp_path/'a.py').write_text('alpha = 1\n')
    c, _ = client(tmp_path)
    d = preview(c)
    assert c.post('/replace/apply', json={'token': d['token']}).status_code == 200
    r = c.post('/replace/apply', json={'token': d['token']})
    assert r.status_code == 409 and 'expired' in r.json()['error']


def test_apply_touches_only_the_selected_paths(tmp_path):
    (tmp_path/'a.py').write_text('alpha\n')
    (tmp_path/'b.txt').write_text('alpha\n')
    c, _ = client(tmp_path)
    d = preview(c)
    r = c.post('/replace/apply', json={'token': d['token'], 'paths': [str(tmp_path/'a.py')]})
    assert r.status_code == 200 and r.json()['paths'] == [str(tmp_path/'a.py')]
    assert (tmp_path/'a.py').read_text() == 'beta\n' and (tmp_path/'b.txt').read_text() == 'alpha\n'


def test_apply_refuses_to_overwrite_an_unsaved_open_buffer(tmp_path):
    (tmp_path/'a.py').write_text('alpha\n')
    c, ws = client(tmp_path)
    tab = ws.open(tmp_path/'a.py'); tab.dirty = True
    d = preview(c)
    r = c.post('/replace/apply', json={'token': d['token']})
    assert r.status_code == 409 and 'unsaved open files' in r.json()['error']
    assert (tmp_path/'a.py').read_text() == 'alpha\n'


def test_replacement_text_is_literal_unless_regex_is_asked_for(tmp_path):
    """`\\n` and `\\1` in the replacement box are characters, not escapes.

    Unescaped they reach `re.sub` as a template: the first writes a newline into the file and
    the second refuses the whole preview.
    """
    (tmp_path/'a.txt').write_text('root = HERE\n')
    c, _ = client(tmp_path)
    d = preview(c, find='HERE', replace=r'C:\new\1')
    assert d['files'][0]['after'] == 'root = C:\\new\\1\n'
    assert c.post('/replace/apply', json={'token': d['token']}).status_code == 200
    assert (tmp_path/'a.txt').read_text() == 'root = C:\\new\\1\n'


def test_files_that_are_not_utf8_are_skipped_rather_than_rewritten_lossily(tmp_path):
    "The sandbox decodes with `errors='replace'`; writing that back would eat the bytes."
    (tmp_path/'legacy.txt').write_bytes(b'caf\xe9 alpha\n')
    c, _ = client(tmp_path)
    d = preview(c)
    assert not d['files'] and str(tmp_path/'legacy.txt') in d['skipped']
    assert (tmp_path/'legacy.txt').read_bytes() == b'caf\xe9 alpha\n'


def test_inline_previews_against_disk_and_applies_through_the_shared_token(tmp_path):
    "Inline shares `/refactor/apply`, so its plan has to be journalled and undoable like the rest."
    (tmp_path/'a.py').write_text('amount = price * qty\nprint(amount)\n')
    c, ws = client(tmp_path)
    d = c.post('/refactor/inline', json={'path': str(tmp_path/'a.py'), 'pos': 0}).json()
    assert d['files'][0]['after'] == 'print((price * qty))\n'

    r = c.post('/refactor/apply', json={'token': d['token']})
    assert r.status_code == 200, r.text
    assert (tmp_path/'a.py').read_text() == 'print((price * qty))\n'
    ws.journal.undo(r.json()['operation']['id'])
    assert (tmp_path/'a.py').read_text() == 'amount = price * qty\nprint(amount)\n'


def test_refactoring_a_non_python_file_is_refused(tmp_path):
    (tmp_path/'a.txt').write_text('amount = 1\n')
    c, _ = client(tmp_path)
    r = c.post('/refactor/inline', json={'path': str(tmp_path/'a.txt'), 'pos': 0})
    assert 'Python files only' in r.json()['error']


def test_preview_state_does_not_accumulate_across_previews(tmp_path):
    "Each plan holds a full copy of every file it would change, so unapplied ones must go."
    from leela.blocks.refactor.app import MAX_PLANS, _prune
    (tmp_path/'a.py').write_text('alpha\n')
    c, _ = client(tmp_path)
    tokens = [preview(c)['token'] for _ in range(MAX_PLANS + 3)]
    # The oldest previews were dropped; the newest still applies.
    assert c.post('/replace/apply', json={'token': tokens[0]}).status_code == 409
    assert c.post('/replace/apply', json={'token': tokens[-1]}).status_code == 200
    plans = {'old': {'at': 0}, 'new': {'at': 2 ** 40}}
    _prune(plans)
    assert list(plans) == ['new']
