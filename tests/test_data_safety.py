"Saves that keep what is on disk and in memory: strict decoding, line endings, outside rewrites, two windows, streamed output and large notebooks."

import asyncio, json, time
import pytest
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.blocks.fs.fs import NotText, Sandbox
from leela.blocks.nb import nb as nbmod
from leela.blocks.nb.nb import Cell, Notebook, OutFeed
from leela.workspace import Workspace

LATIN = 'caf\xe9 na\xefve\n'.encode('latin-1')

def nbj(cells, meta=None):
    "A notebook as JSON: `(id, source, outputs)` per cell."
    return json.dumps({'nbformat': 4, 'nbformat_minor': 5, 'metadata': meta or {}, 'cells': [
        {'cell_type': 'code', 'id': i, 'source': s, 'outputs': o, 'execution_count': None, 'metadata': {}} for i, s, o in cells]})

def on_disk(p): return [(c['id'], ''.join(c['source']), len(c['outputs'])) for c in json.loads(p.read_text())['cells']]

def opened(tmp_path, name, body):
    p = tmp_path/name
    p.write_bytes(body) if isinstance(body, bytes) else p.write_text(body)
    ws = Workspace(roots=[tmp_path]); tab = ws.open(p)
    return p, ws, tab

# C1: a file that is not UTF-8 text

@pytest.mark.parametrize('raw', [LATIN, b'a\x00b\n', 'caf\xe9'.encode()[:-1]])
def test_a_file_that_is_not_utf8_opens_read_only_with_a_note_and_a_save_is_refused(tmp_path, raw):
    "Latin-1, a NUL byte, and a UTF-8 sequence cut off at the end of the file."
    p, ws, tab = opened(tmp_path, 'notes.txt', raw)
    with TestClient(ide_app(ws)) as c:
        st = c.get('/tab/state', params={'path': tab.path}).json()
        assert st['read_only'] is True and st['note'] == 'This file is not UTF-8 text, so Leela opens it read-only.'
        r = c.post('/nb/save', json={'tab': tab.path, 'text': st['text'] + 'more\n', 'base_disk_version': st['disk_version']})
        assert r.status_code == 400 and r.json()['kind'] == 'not_text' and 'does not change it' in r.json()['error']
        tab.dirty = True
        r = c.post('/tabs/save-all')
        assert r.json()['kind'] == 'not_text', r.json()
    assert p.read_bytes() == raw

def test_every_write_route_meets_the_same_refusal(tmp_path):
    "`Sandbox.write` is where every route writes, so one check covers rename-symbol, refactor, history restore and the agent."
    (tmp_path/'a.py').write_bytes(LATIN)
    with pytest.raises(NotText): Sandbox([tmp_path]).write(tmp_path/'a.py', 'x = 1\n')
    with pytest.raises(NotText): Sandbox([tmp_path]).read(tmp_path/'a.py')
    assert (tmp_path/'a.py').read_bytes() == LATIN
    Sandbox([tmp_path]).write(tmp_path/'b.py', 'new = 1\n')
    assert (tmp_path/'b.py').read_text() == 'new = 1\n', 'a new file is written'

def test_undo_does_not_overwrite_a_file_that_is_no_longer_utf8(tmp_path):
    p, ws, tab = opened(tmp_path, 'a.py', 'x = 1\n')
    with TestClient(ide_app(ws)) as c:
        st = c.get('/tab/state', params={'path': tab.path}).json()
        assert c.post('/nb/save', json={'tab': tab.path, 'text': 'x = 2\n', 'base_disk_version': st['disk_version']}).json()['ok']
        p.write_bytes(LATIN)
        r = c.post('/history/undo', json={})
        assert r.status_code != 200 and 'not UTF-8' in r.text
    assert p.read_bytes() == LATIN

def test_file_history_keeps_and_gives_back_exact_text(tmp_path):
    from leela.core.session import FileHistory
    h = FileHistory(tmp_path/'h')
    row = h.record(tmp_path/'a.py', 'caf\xe9 \U0001f600\n')
    assert h.text(row['id']) == 'caf\xe9 \U0001f600\n'
    with pytest.raises(UnicodeEncodeError): h.record(tmp_path/'b.py', 'lone \udcff')

# S9: line endings

@pytest.mark.parametrize('nl', ['\r\n', '\r', '\n'])
def test_a_save_keeps_the_files_own_line_ending_and_undo_still_works(tmp_path, nl):
    p, ws, tab = opened(tmp_path, 'win.py', f'a = 1{nl}b = 2{nl}'.encode())
    with TestClient(ide_app(ws)) as c:
        st = c.get('/tab/state', params={'path': tab.path}).json()
        assert st['text'] == 'a = 1\nb = 2\n'
        r = c.post('/nb/save', json={'tab': tab.path, 'text': st['text'] + 'c = 3\n', 'base_disk_version': st['disk_version']})
        assert r.status_code == 200, r.text
        assert p.read_bytes() == f'a = 1{nl}b = 2{nl}c = 3{nl}'.encode()
        assert c.post('/history/undo', json={}).status_code == 200
    assert p.read_bytes() == f'a = 1{nl}b = 2{nl}'.encode()

def test_a_crlf_notebook_stays_crlf(tmp_path):
    p, ws, tab = opened(tmp_path, 'n.ipynb', nbj([('c1', 'x = 1', [])]).replace('\n', '\r\n').replace(', "', ',\r\n "'))
    with TestClient(ide_app(ws)) as c:
        st = c.get('/tab/state', params={'path': tab.path}).json()
        assert c.post('/nb/save', json={'tab': tab.path, 'cells': [{'i': 0, 'id': 'c1', 'source': 'x = 2'}],
                                        'base_disk_version': st['disk_version']}).status_code == 200
    raw = p.read_bytes()
    assert b'\r\n' in raw and b'\n' not in raw.replace(b'\r\n', b'')

# S7: a save after an outside rewrite

def _rewritten(tmp_path, edit):
    "Open three cells, change them here with `edit`, touch the file's metadata outside Leela, then save."
    p, ws, tab = opened(tmp_path, 'n.ipynb', nbj([('c1', 'x = 1', []), ('c2', 'y = 2', []), ('c3', 'z = 3', [])]))
    with TestClient(ide_app(ws)) as c:
        st = c.get('/tab/state', params={'path': tab.path}).json()
        edit(c, ws.docstore.docs[tab.path], tab)
        d = json.loads(p.read_text()); d['metadata']['touched'] = 1; p.write_text(json.dumps(d))
        r = c.post('/nb/save', json={'tab': tab.path, 'cells': [], 'base_disk_version': st['disk_version']})
    return r, p

def test_a_delete_a_move_an_insert_and_an_output_survive_an_outside_rewrite(tmp_path):
    def delete(c, nb, tab): c.post('/nb/edit', json={'path': tab.path, 'op': 'delete', 'i': 1})
    def move(c, nb, tab): c.post('/nb/edit', json={'path': tab.path, 'op': 'move', 'i': 2, 'd': -2})
    def insert(c, nb, tab): c.post('/nb/edit', json={'path': tab.path, 'op': 'insert', 'i': 3, 'source': 'w = 4'})
    def output(c, nb, tab): nb[0].outputs = [{'output_type': 'stream', 'name': 'stdout', 'text': 'ran\n'}]
    for edit, want in [(delete, ['c1', 'c3']), (move, ['c3', 'c1', 'c2']), (insert, ['c1', 'c2', 'c3', None]), (output, ['c1', 'c2', 'c3'])]:
        (d := tmp_path/edit.__name__).mkdir()
        r, p = _rewritten(d, edit)
        assert r.status_code == 200, (edit.__name__, r.text)
        got = on_disk(p)
        assert [i for i, *_ in got][:len([w for w in want if w])] == [w for w in want if w] and len(got) == len(want), (edit.__name__, got)
        assert json.loads(p.read_text())['metadata']['touched'] == 1, 'the outside change is kept too'
        if edit is output: assert got[0][2] == 1, 'the output made here is kept'
        if edit is insert: assert got[3][1] == 'w = 4'

def test_disk_changes_come_in_and_both_sided_changes_clash(tmp_path):
    p, ws, tab = opened(tmp_path, 'n.ipynb', nbj([('c1', 'x = 1', []), ('c2', 'y = 2', []), ('c3', 'z = 3', [])]))
    with TestClient(ide_app(ws)) as c:
        st = c.get('/tab/state', params={'path': tab.path}).json()
        # outside: c2 changed, c3 deleted, c4 added after c1
        p.write_text(nbj([('c1', 'x = 1', []), ('c4', 'new = 4', []), ('c2', 'y = 20', [])]))
        r = c.post('/nb/save', json={'tab': tab.path, 'cells': [{'i': 0, 'id': 'c1', 'source': 'x = 10'}], 'base_disk_version': st['disk_version']})
        assert r.status_code == 200, r.text
        assert on_disk(p) == [('c1', 'x = 10', 0), ('c4', 'new = 4', 0), ('c2', 'y = 20', 0)]
        c.post('/nb/edit', json={'path': tab.path, 'op': 'undo'})
        assert 'y = 20' in json.dumps(c.get('/tab/state', params={'path': tab.path}).json()['cells']), 'undo cannot bring back the cells from before the disk change'
        st = c.get('/tab/state', params={'path': tab.path}).json()
        p.write_text(nbj([('c1', 'x = 99', []), ('c2', 'y = 20', [])]))
        r = c.post('/nb/save', json={'tab': tab.path, 'cells': [{'i': 0, 'id': 'c1', 'source': 'x = 11'}], 'base_disk_version': st['disk_version']})
        assert r.status_code == 409 and r.json()['kind'] == 'save_conflict' and r.json()['cells'][0]['source'] == 'x = 99'
        assert 'x = 99' in p.read_text()

# S8: two windows on one notebook

def test_two_windows_editing_different_cells_both_land(tmp_path):
    p, ws, tab = opened(tmp_path, 'n.ipynb', nbj([('c1', 'x = 1', []), ('c2', 'y = 2', [])]))
    row = lambda page, i, cid, src, base: {'i': i, 'id': cid, 'source': src, 'base': base, 'page': page, 'seq': time.time_ns()}
    with TestClient(ide_app(ws)) as c:
        a = c.get('/tab/state', params={'path': tab.path}).json()
        assert c.post('/tab/buffer', json={'path': tab.path, 'kind': 'notebook', 'text': 'y = 200', **row('B', 1, 'c2', 'y = 200', 'y = 2')}).json()['took']
        assert c.post('/tab/buffer', json={'path': tab.path, 'kind': 'notebook', 'text': 'x = 100', **row('A', 0, 'c1', 'x = 100', 'x = 1')}).json()['took']
        assert c.post('/nb/save', json={'tab': tab.path, 'cells': [row('A', 0, 'c1', 'x = 100', 'x = 1')], 'base_disk_version': a['disk_version']}).status_code == 200
        assert c.post('/nb/save', json={'tab': tab.path, 'cells': [row('B', 1, 'c2', 'y = 200', 'y = 2')], 'base_disk_version': a['disk_version']}).status_code == 200
        assert [s for _, s, _ in on_disk(p)] == ['x = 100', 'y = 200']
        # the same cell: B's base is the source A replaced, so B gets the choice, not a silent overwrite
        assert not c.post('/tab/buffer', json={'path': tab.path, 'kind': 'notebook', 'text': 'x = 7', **row('B', 0, 'c1', 'x = 7', 'x = 1')}).json()['took']
        r = c.post('/nb/save', json={'tab': tab.path, 'cells': [row('B', 0, 'c1', 'x = 7', 'x = 1')]})
        assert r.status_code == 409 and r.json()['kind'] == 'save_conflict' and r.json()['cells'] == [{'id': 'c1', 'source': 'x = 100', 'cell_type': 'code'}]
        r = c.post('/nb/run', json={'path': tab.path, 'i': 0, 'id': 'c1', 'source': 'x = 7', 'base': 'x = 1', 'page': 'B'})
        assert r.status_code == 409 and r.json()['kind'] == 'save_conflict', 'a run meets the same conflict'
        r = c.post('/nb/edit', json={'path': tab.path, 'op': 'insert', 'i': 2, 'sources': [row('B', 0, 'c1', 'x = 7', 'x = 1')]})
        assert r.json()['clash'] == ['c1']
        assert c.post('/nb/save', json={'tab': tab.path, 'cells': [row('B', 0, 'c1', 'x = 7', 'x = 1')], 'force': True}).status_code == 200, 'overwrite still wins'
        assert on_disk(p)[0][1] == 'x = 7'

def test_a_page_s_own_writes_in_flight_and_out_of_order_are_no_clash(tmp_path):
    nb, seqs = Notebook([Cell(source='x = 1', id='c1')]), {}
    assert nb.take_sources([{'id': 'c1', 'source': 'x = 12', 'base': 'x = 1', 'page': 'A', 'seq': 2}], seqs) == []
    assert nb.take_sources([{'id': 'c1', 'source': 'x = 1', 'base': 'x = 1', 'page': 'A', 'seq': 1}], seqs) == [], 'an older write of the same page is dropped quietly'
    assert nb[0].source == 'x = 12'
    assert nb.take_sources([{'id': 'c1', 'source': 'x = 123', 'base': 'x = 1', 'page': 'A', 'seq': 3}], seqs) == []
    assert nb.take_sources([{'id': 'c1', 'source': 'x = 9', 'base': 'x = 1', 'page': 'B', 'seq': 4}], seqs) == ['c1']
    assert nb.take_sources([{'id': 'gone', 'source': 'x', 'base': 'x', 'page': 'B'}], seqs) == ['gone'], 'a cell deleted elsewhere is a clash'
    assert nb[0].source == 'x = 123'

def test_repeated_ids_in_a_file_become_distinct(tmp_path):
    (tmp_path/'n.ipynb').write_text(nbj([('c1', 'a', []), ('c1', 'b', [])]))
    ids = [c.id for c in Notebook.load(tmp_path/'n.ipynb').cells]
    assert ids[0] == 'c1' and len(set(ids)) == 2

# C2: streamed output

class Printer:
    "A kernel that prints `n` lines as separate stream messages, as `print(i); sys.stdout.flush()` does."
    alive, kernel_kind = True, 'ipykernel'
    def __init__(self, n): self.n = n
    async def execute(self, code, on_output=None, **kw):
        from leela.blocks.runtime.kernels import ExecOutcome
        for i in range(self.n):
            on_output({'output_type': 'stream', 'name': 'stdout', 'text': f'{i}\n'})
            if i % 50 == 0: await asyncio.sleep(.001)
        return ExecOutcome(ok=True, execution_count=1, outputs=[{'output_type': 'stream', 'name': 'stdout', 'text': ''.join(f'{i}\n' for i in range(self.n))}])
    async def api(self, *a, **kw): return None

def test_many_prints_stream_as_few_small_deltas_into_one_output(tmp_path):
    p, ws, tab = opened(tmp_path, 'n.ipynb', nbj([('c1', 'loop', [])]))
    async def printer(tab=None): return Printer(2000)
    ws.runtime = printer
    with TestClient(ide_app(ws)) as c:
        c.get('/tab/state', params={'path': tab.path})
        with c.stream('POST', '/nb/run/stream', json={'path': tab.path, 'i': 0, 'id': 'c1'}) as r: body = b''.join(r.iter_bytes())
    text = ''.join(f'{i}\n' for i in range(2000))
    events = [json.loads(l[6:]) for l in body.decode().splitlines() if l.startswith('data: ')]
    outs = [e for e in events if 'ops' in e]
    assert len(body) < 3 * len(text) + 20_000, f'{len(body)} SSE bytes for {len(text)} characters'
    assert all(len(e['ops']) <= 1 and e['n'] == 1 for e in outs)
    assert events[-1]['cell']['outputs'] == [{'output_type': 'stream', 'name': 'stdout', 'text': text}]

def test_a_stream_past_the_cap_keeps_its_newest_text_and_says_how_much_went(monkeypatch):
    monkeypatch.setattr(nbmod, 'MAX_STREAM', 100)
    c, nb = Cell(source='x', id='c'), None
    class K:
        async def execute(self, code, on_output=None, **kw):
            from leela.blocks.runtime.kernels import ExecOutcome
            for i in range(60): on_output({'output_type': 'stream', 'name': 'stdout', 'text': f'{i:03}\n'})
            return ExecOutcome(ok=True, execution_count=1, outputs=[{'output_type': 'stream', 'name': 'stdout', 'text': ''.join(f'{i:03}\n' for i in range(60))}])
    feed, seen = OutFeed(c), []
    asyncio.run(Notebook([c]).run(0, K(), on_output=lambda i, row: seen.append(feed.ops())))
    assert len(c.outputs) == 1 and c.outputs[0]['text'].startswith('[Leela removed the first 190 characters of this output.]\n')
    assert c.outputs[0]['text'].endswith('059\n') and len(c.outputs[0]['text']) < 120
    kinds = [op[1] for ops in seen for op in ops]
    assert kinds[0] == 'set' and 'append' in kinds and kinds.count('set') < 10, 'a cut sends the output again; a plain print sends only its text'

def test_the_feed_sends_a_cleared_output_again_whole():
    c = Cell(id='c'); feed = OutFeed(c)
    c.outputs = [{'output_type': 'stream', 'name': 'stdout', 'text': 'a'}]
    assert feed.ops() == [[0, 'set', {'output_type': 'stream', 'name': 'stdout', 'text': 'a'}]]
    c.outputs[0]['text'] += 'b'
    assert feed.ops() == [[0, 'append', 'b']] and feed.ops() == []
    c.outputs = [{'output_type': 'stream', 'name': 'stdout', 'text': 'c'}]
    assert feed.ops() == [[0, 'set', {'output_type': 'stream', 'name': 'stdout', 'text': 'c'}]]
    c.outputs = []
    assert feed.ops() == [] and feed.sent == []

# S16: large notebooks

def test_a_page_that_holds_the_notebook_does_not_get_its_cells_again(tmp_path):
    p, ws, tab = opened(tmp_path, 'n.ipynb', nbj([('c1', 'x = 1', [])]))
    with TestClient(ide_app(ws)) as c:
        st = c.get('/tab/state', params={'path': tab.path}).json()
        again = c.get('/tab/state', params={'path': tab.path, 'have': json.dumps({tab.path: st['version']})}).json()
        assert again['same'] is True and 'cells' not in again
        c.post('/nb/edit', json={'path': tab.path, 'op': 'insert', 'i': 1})
        moved = c.get('/tab/state', params={'path': tab.path, 'have': json.dumps({tab.path: st['version']})}).json()
        assert len(moved['cells']) == 2 and 'same' not in moved
        ws.docstore.docs[tab.path][0].running = True
        assert 'cells' in c.get('/tab/state', params={'path': tab.path, 'have': json.dumps({tab.path: moved['version']})}).json(), 'a running cell changes outputs before the version'

def test_saving_a_notebook_past_max_body_reads_no_extra_copy(tmp_path, monkeypatch):
    from leela.blocks.nb import app as nbapp
    monkeypatch.setattr(nbapp, 'MAX_BODY', 10)
    p, ws, tab = opened(tmp_path, 'n.ipynb', nbj([('c1', 'x = 1', [])]))
    reads = []
    real = nbapp.decoded
    monkeypatch.setattr(nbapp, 'decoded', lambda raw, p='': reads.append(len(raw)) or real(raw, p))
    with TestClient(ide_app(ws)) as c:
        st = c.get('/tab/state', params={'path': tab.path}).json()
        r = c.post('/nb/save', json={'tab': tab.path, 'cells': [{'i': 0, 'id': 'c1', 'source': 'x = 2'}], 'base_disk_version': st['disk_version']})
        assert r.status_code == 200 and r.json()['operation_id'] == ''
    assert reads == [] and on_disk(p)[0][1] == 'x = 2'

@pytest.mark.slow
def test_a_real_kernel_printing_2000_lines_streams_a_few_kilobytes(tmp_path):
    "2000 prints gave 125 MB of SSE: every message carried every output so far."
    import sys
    src = 'import sys\nfor i in range(2000):\n    print(i); sys.stdout.flush()'
    p, _, _ = opened(tmp_path, 'n.ipynb', nbj([('c1', src, [])]))
    ws = Workspace(roots=[tmp_path], approvals='auto', python=sys.executable); tab = ws.open(p)
    try:
        with TestClient(ide_app(ws)) as c:
            c.get('/tab/state', params={'path': tab.path})
            with c.stream('POST', '/nb/run/stream', json={'path': tab.path, 'i': 0, 'id': 'c1'}) as r: body = b''.join(r.iter_bytes())
    finally: ws.shutdown_now()
    done = json.loads(body.decode().rsplit('data: ', 1)[1])
    assert len(body) < 100_000, len(body)
    assert [o['text'].count('\n') for o in done['cell']['outputs']] == [2000]

@pytest.mark.slow
def test_the_page_shows_the_note_and_a_read_only_editor(tmp_path):
    pytest.importorskip('playwright.async_api')
    import test_web_slow as web
    (tmp_path/'notes.txt').write_bytes(LATIN)
    async def go(pg):
        await pg.evaluate('p => leeOpenFile(p)', str(tmp_path/'notes.txt'))
        await pg.wait_for_selector('.lee-readonly-note')
        await pg.click('#filecm .cm-content'); await pg.keyboard.type('more')
        return await pg.text_content('.lee-readonly-note'), await pg.evaluate("LeeCM.getDoc(lee.editors.get('file'))")
    note, text = web._run(go, roots=[tmp_path])
    assert note == 'This file is not UTF-8 text, so Leela opens it read-only.' and 'more' not in text
    assert (tmp_path/'notes.txt').read_bytes() == LATIN
