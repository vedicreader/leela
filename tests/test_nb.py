"The notebook document: cells, outputs, images, diagnostics and languages."

import asyncio, json
import pytest
from leela.blocks.nb.nb import Cell, Notebook
import sys
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.workspace import Workspace

def dialog():
    "A notebook with all three cell types, one prompt answered and one not."
    return Notebook([
        Cell(source='## Loading', cell_type='markdown', id='m1'),
        Cell(source='df = load()', cell_type='code', id='c1', execution_count=1,
             outputs=[{'output_type': 'execute_result', 'execution_count': 1, 'metadata': {},
                       'data': {'text/plain': 'a    6\ndtype: int64'}}]),
        Cell(source='why is the sum 6?', cell_type='prompt', id='p1',
             reply='Because 1+2+3 = 6.', calls=[{'tool': 'run_python', 'args': '{}'}]),
        Cell(source='df.mean()', cell_type='code', id='c2'),
        Cell(source='and the mean?', cell_type='prompt', id='p2'),
    ])


def test_a_prompt_cell_is_written_as_valid_markdown(tmp_path):
    "nbformat has no prompt cell, so plain Jupyter must still be able to open the file."
    p = tmp_path / 'd.ipynb'
    dialog().save(p)
    raw = json.loads(p.read_text())
    assert [c['cell_type'] for c in raw['cells']] == ['markdown', 'code', 'markdown', 'code', 'markdown']
    assert raw['cells'][2]['metadata']['leela']['kind'] == 'prompt'
    nbformat = pytest.importorskip('nbformat')
    nbformat.validate(nbformat.read(str(p), as_version=4))

def test_a_zero_byte_notebook_opens_as_a_new_document(tmp_path):
    "Creating `name.ipynb` through a generic file action used to open a JSONDecodeError."
    p = tmp_path / 'new.ipynb'
    p.touch()
    nb = Notebook.load(p)
    assert len(nb) == 1 and nb[0].cell_type == 'code'
    nb.save()
    assert json.loads(p.read_text())['nbformat'] == 4


def test_initialising_the_open_notebook_keeps_the_cell_ids_the_browser_knows(tmp_path):
    """A zero-byte `.ipynb` was made valid by writing a fresh blank, whose cell has a new id."""
    p = tmp_path/'new.ipynb'; p.touch()
    ws = Workspace(roots=[tmp_path])
    nb = Notebook.load(p)                     # what the doc store holds for an open placeholder
    ids = [c.id for c in nb.cells]
    assert ws.initialize_notebook(p, nb) == str(p)
    assert [c.id for c in Notebook.load(p).cells] == ids, 'the ids the browser knows must survive'
    assert ws.initialize_notebook(p, nb) is None, 'a notebook that is already valid is left alone'
    assert ws.initialize_notebook(None) is None and ws.initialize_notebook(tmp_path/'gone.ipynb') is None


def test_a_run_that_initialises_the_notebook_leaves_the_next_save_workable(tmp_path, monkeypatch):
    """The symptom: running cells in a new notebook, then `save the notebook before running this cell` partway through."""
    p = tmp_path/'new.ipynb'; p.touch()
    ws = Workspace(roots=[tmp_path]); ws.open(p)
    async def no_kernel(tab=None): raise RuntimeError('no kernel in this test')
    monkeypatch.setattr(ws, 'runtime', no_kernel)
    with TestClient(ide_app(ws)) as client:
        opened = client.get('/tab/state', params={'path': str(p)}).json()
        with pytest.raises(RuntimeError):
            client.post('/nb/run/stream', json={'path': str(p), 'i': 0, 'source': 'X = 1'})
        assert p.stat().st_size, 'the run made the placeholder valid JSON'
        r = client.post('/nb/save', json={'path': str(p), 'cells': [{'i': 0, 'source': 'X = 1'}],
                                          'base_disk_version': opened['disk_version']})
        assert r.status_code == 200, r.text
    assert 'X = 1' in p.read_text()

def _split(src):
    nb = Notebook([Cell(source=src)])
    return nb.split_symbols(0), [c.source for c in nb.cells]

def test_a_cell_splits_into_one_cell_per_class_and_function():
    "Source order, and whatever was not a def stays above where it was."
    made, cells = _split('#| export\nimport os\n\ndef f():\n    return 1\n\nclass C:\n    pass\n')
    assert made == 2
    assert cells == ['#| export\nimport os',
                     '#| export\ndef f():\n    return 1',
                     '#| export\nclass C:\n    pass']
    assert not any(s.endswith('\n') for s in cells), 'a trailing newline is an empty line in the editor'


def test_the_answer_survives_the_round_trip(tmp_path):
    p = tmp_path / 'd.ipynb'
    dialog().save(p)
    back = Notebook.load(p)
    assert [c.cell_type for c in back.cells] == ['markdown', 'code', 'prompt', 'code', 'prompt']
    assert back[2].reply == 'Because 1+2+3 = 6.'
    assert back[2].calls == [{'tool': 'run_python', 'args': '{}'}]
    assert back[1].text.startswith('a    6')


def notebook_json():
    "A notebook on disk, written the way nbformat writes one: a JSON string per source line."
    nb = Notebook([Cell(source='## Loading', cell_type='markdown', id='m1'),
                   Cell(source='import os\n\ndef alpha(x):\n    return x', id='c1'),
                   Cell(source='class Beta:\n    def gamma(self):\n        return alpha(1)', id='c2')])
    return nb


def test_a_file_line_maps_back_to_the_cell_and_the_line_inside_it(tmp_path):
    "The direction search needs: ripgrep reports a line of JSON and a reader needs a cell."
    from leela.blocks.nb.nb import cell_at
    notebook_json().save(p := tmp_path/'d.ipynb')
    text = p.read_text()
    line = next(i for i, raw in enumerate(text.splitlines(), 1) if 'def gamma' in raw)
    at = cell_at(text, line)
    assert (at['id'], at['index'], at['line']) == ('c2', 2, 2)
    assert at['file_line'] == line
    assert cell_at(text, 1) is None, 'a line of JSON that is nobody\'s source belongs to no cell'


def _trail(steps=2, payload='x' * 4000):
    "What `Agent.turn_md` appends to a prompt cell's reply."
    return (f'<details><summary>what I did ({steps} steps)</summary>\n\n'
            f'<details><summary>Search Approvals</summary>\n\n```\n{payload}\n```\n\n</details>\n\n</details>')

def test_a_prompt_cell_work_log_is_not_fed_back_as_context():
    "`cell.calls` already holds the trail; feeding `cell.reply` back whole paid for it again every turn."
    nb = dialog()
    nb[2].reply = f'Because 1+2+3 = 6.\n\n{_trail()}'
    ctx = nb.context(4, since=0)
    assert '<answer>' in ctx and 'Because 1+2+3 = 6.' in ctx
    assert '<details>' not in ctx and 'Search Approvals' not in ctx and 'x' * 100 not in ctx
    assert len(ctx) < len(dialog().context(4, since=0)) + 100
    plain = dialog()
    assert plain.context(4, since=0) == ctx
    nb[2].calls = []
    assert '<details>' not in nb.context(4, since=0)
    nb[2].reply = f'Because 1+2+3 = 6.\n\n{_trail()}\n\n   \n'
    assert '<details>' not in nb.context(4, since=0)
    nb[2].reply = 'Because 1+2+3 = 6.\n\n<details><summary>my own working</summary>\n\n2+2\n\n</details>'
    assert 'my own working' in nb.context(4, since=0)
    nb[2].reply = _trail()
    assert '<answer>' not in nb.context(4, since=0)
    nb[2].source = ''
    assert 'id="p1"' not in nb.context(4, since=0)
    from leela.blocks.nb.nb import strip_work_log
    assert strip_work_log('') == '' and strip_work_log(None) == ''

def test_a_cell_that_prints_nothing_does_not_wait_out_the_output_poll(tmp_path):
    """A cell that printed nothing paid the stream's full 120ms output-queue timeout on top of the two it took to run."""
    import json, time
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.workspace import Workspace
    cells = [{'cell_type': 'code', 'source': [f'q{i} = {i}'], 'metadata': {}, 'outputs': [],
              'execution_count': None} for i in range(6)]
    p = tmp_path/'quiet.ipynb'
    p.write_text(json.dumps({'cells': cells, 'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    ws = Workspace(roots=[tmp_path], approvals='auto', python=sys.executable)
    ws.open(p)
    with TestClient(ide_app(ws)) as client:
        path = client.get('/tab/state').json()['path']
        body = lambda i: {'i': i, 'id': None, 'source': f'q{i} = {i}', 'path': path}
        with client.stream('POST', '/nb/run/stream', json=body(0)) as r:   # this one starts the kernel
            for _ in r.iter_lines(): pass
        # The best of three, not one run: the regression this guards costs every cell the full
        # 120ms poll, so it cannot hide in the fastest pass, while a busy machine slows all of them.
        def five():
            began = time.perf_counter()
            for i in range(1, 6):
                with client.stream('POST', '/nb/run/stream', json=body(i)) as r:
                    assert any('event: done' in line for line in r.iter_lines())
            return time.perf_counter() - began
        took = min(five() for _ in range(3))
    assert took < .5, f'five quiet cells took {took:.2f}s; paying the poll would add 0.6s to that'


def test_the_widget_socket_relays_both_ways_and_names_the_pages_own_messages(tmp_path):
    """A page's widget update came back as an `echo_update` under the kernel's msg_id, so the page could not tell its own update from someone else's."""
    pytest.importorskip('ipywidgets')
    from urllib.parse import quote
    src = ['from ipywidgets import IntSlider\ns = IntSlider(value=1); s', 's.value']
    cells = [{'cell_type': 'code', 'id': f'c{i}', 'source': s, 'metadata': {}, 'outputs': [], 'execution_count': None} for i, s in enumerate(src)]
    p = tmp_path/'w.ipynb'
    p.write_text(json.dumps({'cells': cells, 'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    ws = Workspace(roots=[tmp_path], approvals='auto', python=sys.executable); ws.open(p)
    def run(client, path, i):
        with client.stream('POST', '/nb/run/stream', json={'i': i, 'id': f'c{i}', 'source': src[i], 'path': path}) as r:
            return [json.loads(l[6:]) for l in r.iter_lines() if l.startswith('data: ')][-1]
    def until(sock, want):
        for _ in range(200):
            if want(m := sock.receive_json()): return m
        raise AssertionError(f'never heard what was wanted; last {m}')
    try:
        with TestClient(ide_app(ws)) as client:
            path = client.get('/tab/state').json()['path']
            with client.websocket_connect(f'/nb/comm/ws?path={quote(path)}') as sock:
                assert sock.receive_json()['type'] == 'waiting'
                run(client, path, 0)
                until(sock, lambda m: m.get('type') == 'ready')
                opened = until(sock, lambda m: m.get('msg_type') == 'comm_open' and m['content']['data']['state']['_model_name'] == 'IntSliderModel')
                cid = opened['content']['comm_id']
                sock.send_json({'op': 'send', 'id': 'page-1', 'comm_id': cid, 'data': {'method': 'update', 'state': {'value': 5}, 'buffer_paths': []}})
                echo = until(sock, lambda m: m.get('msg_type') == 'comm_msg' and m['content']['data'].get('method') == 'echo_update')
                sock.send_json({'op': 'info', 'id': 'q1', 'target_name': 'jupyter.widget'})
                reply = until(sock, lambda m: m.get('type') == 'reply')
                value = run(client, path, 1)['cell']['outputs'][0]['data']['text/plain']
    finally: ws.shutdown_now()
    assert echo['parent_header']['msg_id'] == 'page-1' and echo['content']['data']['state']['value'] == 5, echo
    assert reply['id'] == 'q1' and cid in reply['content']['comms'], reply
    assert value == '5', value

UPDATING = '''from IPython.display import display, HTML
import time
h = display(HTML('<progress max="3" value="0"></progress>'), display_id=True)
for i in range(1, 4):
    time.sleep(.05)
    h.update(HTML(f'<progress max="3" value="{i}"></progress>'))
'''

def test_an_updated_display_is_one_output_holding_its_final_value_in_the_stream_and_the_file(tmp_path):
    """`update_display_data` replaces the display with that id; fastprogress draws its bars this way."""
    p = tmp_path/'bars.ipynb'
    p.write_text(json.dumps({'cells': [{'cell_type': 'code', 'source': [UPDATING], 'metadata': {}, 'outputs': [], 'execution_count': None}],
                             'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    ws = Workspace(roots=[tmp_path], approvals='auto', python=sys.executable); ws.open(p)
    with TestClient(ide_app(ws)) as client:
        path = client.get('/tab/state').json()['path']
        with client.stream('POST', '/nb/run/stream', json={'i': 0, 'id': None, 'source': UPDATING, 'path': path}) as r:
            events = [json.loads(l[6:]) for l in r.iter_lines() if l.startswith('data: ')]
        assert client.post('/nb/save', json={'path': path}).json()['ok']
    outs = [e['outputs'] for e in events if 'outputs' in e and 'cell' not in e]
    assert outs
    for o in outs: assert len(o) == 1, o
    assert 'value="3"' in outs[-1][0]['data']['text/html']
    saved = json.loads(p.read_text())['cells'][0]['outputs']
    assert len(saved) == 1 and 'value="3"' in ''.join(saved[0]['data']['text/html'])


def test_a_hanging_inspector_does_not_hold_back_the_done_event(tmp_path, monkeypatch):
    """`done` waited on `cell_extras`, so an inspector that never answered left a cell spinning under its finished output."""
    import threading, time
    from conftest import FakeKernel
    stop = threading.Event()
    class Wedged(FakeKernel):
        async def api(self, path, params=None, timeout=15):
            while not stop.is_set(): await asyncio.sleep(.05)
    p = tmp_path/'wedged.ipynb'
    p.write_text(json.dumps({'cells': [{'cell_type': 'code', 'source': ['total'], 'metadata': {}, 'outputs': [], 'execution_count': None}],
                             'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    ws = Workspace(roots=[tmp_path], approvals='auto'); ws.open(p)
    async def wedged(tab=None): return Wedged()
    monkeypatch.setattr(ws, 'runtime', wedged)
    lines = []
    with TestClient(ide_app(ws)) as client:
        path = client.get('/tab/state').json()['path']
        def stream():
            with client.stream('POST', '/nb/run/stream', json={'i': 0, 'id': None, 'source': 'total', 'path': path}) as r: lines.extend(r.iter_lines())
        t = threading.Thread(target=stream, daemon=True); began = time.perf_counter(); t.start(); t.join(12)
        took = time.perf_counter() - began; stop.set(); t.join(5)
    assert any('event: done' in l for l in lines) and took < 8, f'the stream had no done after {took:.1f}s'


def test_outputs_still_queued_when_the_cell_ends_do_not_swallow_its_done(tmp_path):
    """A slow reader let outputs and the end of the run pile up together, and the drain took the end for one more output."""
    import socket
    from conftest import FakeKernel, serve
    from leela.blocks.runtime.kernels import ExecOutcome
    class Burst(FakeKernel):
        async def execute(self, code, on_output=None, **kw):
            outs = [{'output_type': 'stream', 'name': 'stdout', 'text': f'{n} ' + 'x' * 250_000} for n in range(40)]
            for o in outs: on_output(dict(o)); await asyncio.sleep(0)
            return ExecOutcome(ok=True, execution_count=1, outputs=outs)
    p = tmp_path/'burst.ipynb'
    p.write_text(json.dumps({'cells': [{'cell_type': 'code', 'id': 'c0', 'source': 'x', 'metadata': {}, 'outputs': [], 'execution_count': None}],
                             'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    ws = Workspace(roots=[tmp_path], approvals='auto'); ws.open(p)
    async def burst(tab=None): return Burst()
    ws.runtime = burst
    body = json.dumps({'i': 0, 'id': 'c0', 'source': 'x', 'path': str(p)}).encode()
    got = b''
    with serve(ws) as url, socket.create_connection(('127.0.0.1', int(url.rsplit(':', 1)[1])), timeout=5) as s:
        s.sendall(b'POST /nb/run/stream HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n'
                  b'Content-Length: %d\r\n\r\n' % len(body) + body)
        try:
            while b'event: done' not in got and (chunk := s.recv(1 << 20)): got += chunk
        except TimeoutError: pass
    ws.shutdown_now()
    assert b'event: done' in got, f'{got.count(b"event: output")} output events and no done'


def test_a_lost_reply_is_settled_from_what_ipython_recorded_of_the_cell(tmp_path):
    """`_settle_lost` reads IPython's record of the last cell inside a silent execute, so that record has to survive one."""
    from leela.blocks.nb.nb import LOST, _settle_lost
    from leela.blocks.runtime.kernels import Kernel
    async def go():
        k = await Kernel(cwd=tmp_path, inspect=False, python=sys.executable).start()
        try:
            out = []
            for src in ('a = 1', '1/0', 'b = 2'):
                await k.execute(src)
                await _settle_lost(c := Cell(source=src), k)
                out.append(c)
            await _settle_lost(other := Cell(source='not what ran'), k)
            return out, other
        finally: await k.shutdown()
    (ran, raised, again), other = asyncio.run(go())
    assert (ran.execution_count, again.execution_count) == (1, 3) and not ran.outputs and not again.outputs
    assert raised.execution_count == 2 and raised.outputs[-1]['evalue'] == LOST[False]
    assert other.execution_count is None and other.outputs[-1]['evalue'] == LOST[None]


def test_read_cells_parses_notebooks_that_orjson_alone_rejects():
    from leela.blocks.nb.nb import read_cells
    nb = json.dumps({'cells': [{'cell_type': 'code', 'source': ['x=1\n'], 'outputs': []}],
                     'nbformat': 4, 'nbformat_minor': 5})
    assert len(read_cells(nb)) == 1
    nan = '{"cells": [{"cell_type":"code","source":[],"outputs":[{"data":{"x":NaN}}]}], "nbformat":4}'
    assert read_cells(nan) is not None, 'orjson rejects NaN; a real notebook carries it, so parsing must fall through'
    assert read_cells('not json') is None
    assert read_cells('[1,2,3]') is None      # valid json, but not a notebook object
    assert read_cells('') is None

def test_another_tools_cell_and_notebook_metadata_survive_a_save(tmp_path):
    "A dialog notebook (aidialog's prompt cells, dhrona's review) opened and saved here keeps what it came with."
    import nbformat
    nb = nbformat.v4.new_notebook(metadata={'dhrona': {'status': 'review', 'score': 80}, 'kernelspec': {'name': 'python3', 'language': 'python', 'display_name': 'Python 3'}})
    prompt = nbformat.v4.new_markdown_cell('%%prompt\nwhat is here?', metadata={'solveit_ai': True, 'pinned': 1})
    prompt['outputs'] = [{'output_type': 'display_data', 'data': {'text/markdown': 'two files'}, 'metadata': {}}]
    note = nbformat.v4.new_markdown_cell('# Dhrona review', metadata={'skipped': 1, 'meta': {'dhrona': {'score': 80}}})
    code = nbformat.v4.new_code_cell('x = 1', metadata={'tags': ['keep']})
    nb.cells = [note, prompt, code]
    p = tmp_path/'round.ipynb'; p.write_text(nbformat.writes(nb))
    doc = Notebook.load(p); doc.save(p)
    back = json.loads(p.read_text())
    assert back['metadata']['dhrona'] == {'status': 'review', 'score': 80}
    assert back['cells'][0]['metadata'] == {'skipped': 1, 'meta': {'dhrona': {'score': 80}}}
    assert back['cells'][1]['metadata'] == {'solveit_ai': True, 'pinned': 1} and back['cells'][1]['outputs'][0]['data'] == {'text/markdown': 'two files'}
    assert back['cells'][2]['metadata'] == {'tags': ['keep']} and back['cells'][2]['cell_type'] == 'code'
    assert 'leela' not in back['cells'][1]['metadata']


def test_a_markdown_cells_pasted_image_survives_a_save():
    "Leela dropped nbformat `attachments`, so saving a notebook deleted the images pasted into its markdown cells."
    att = {'a.png': {'image/png': 'iVBORw0KGgo='}}
    md = Cell.from_nb({'cell_type': 'markdown', 'id': 'm', 'metadata': {}, 'source': '![a](attachment:a.png)', 'attachments': att})
    assert md.nbcell()['attachments'] == att
    code = Cell.from_nb({'cell_type': 'code', 'id': 'c', 'metadata': {}, 'source': 'x', 'outputs': [], 'execution_count': None})
    assert 'attachments' not in code.nbcell()

def test_a_folded_heading_hides_its_section_and_moves_as_one_block():
    "What a fold hides comes from the headings; a folded section steps a whole block, and undo leaves folds as they are."
    from leela.blocks.nb.nb import hidden_cells
    rows = ['# A', 'a', '## P', 'p', '### P1', 'p1', '## Q', 'q', '#\nx']
    nb = Notebook([Cell(source=s, cell_type='markdown' if s.startswith('#') else 'code', id=s.split()[-1]) for s in rows])
    ids = lambda: [c.id for c in nb.cells]
    nb.set_collapsed([4]); assert hidden_cells(nb.cells) == {5}
    nb.set_collapsed([2]); assert hidden_cells(nb.cells) == {3, 4, 5}
    assert not nb._undo and nb.set_collapsed([1, 8]) == [], 'a fold is no undo step, and `#` with nothing after it is no heading'
    assert nb.move(2, 1) == 5 and ids() == ['A', 'a', 'Q', 'q', 'x', 'P', 'p', 'P1', 'p1'], 'down, past the next section whole'
    assert nb.move(5, -1) == 2 and ids() == ['A', 'a', 'P', 'p', 'P1', 'p1', 'Q', 'q', 'x'], 'up, past the sibling section whole'
    assert nb.move(2, -1) == 1 and ids() == ['A', 'P', 'p', 'P1', 'p1', 'a', 'Q', 'q', 'x'], 'with no sibling, past the one cell above'
    nb.set_collapsed([1], False); nb.undo()
    assert ids()[2] == 'P' and hidden_cells(nb.cells) == {5}, 'undo moved the section back and left P unfolded'
    nb.set_collapsed([2]); nb.reveal(5)
    assert hidden_cells(nb.cells) == set() and not any('heading_collapsed' in c.extra for c in nb.cells)

def test_a_heading_op_folds_the_cell_its_id_names_wherever_that_cell_now_is(tmp_path):
    "A fold sent by index landed on another cell when an insert reached the server first."
    p = tmp_path/'h.ipynb'
    Notebook([Cell(source='# A', cell_type='markdown', id='A'), Cell(source='a', id='a'), Cell(source='## P', cell_type='markdown', id='P')]).save(p)
    ws = Workspace(roots=[tmp_path]); ws.open(p)
    with TestClient(ide_app(ws)) as client:
        client.get('/tab/state', params={'path': str(p)})
        assert client.post('/nb/edit', json={'op': 'insert', 'i': 0, 'cell_type': 'markdown', 'source': '# New'}).json()['ok']
        r = client.post('/nb/edit', json={'op': 'heading', 'ids': ['P', 'gone'], 'collapsed': True}).json()
        assert r['ok'] and {c['id'] for c in r['cells'] if c['extra'].get('heading_collapsed')} == {'P'}, r
        r = client.post('/nb/edit', json={'op': 'heading', 'ids': ['gone'], 'collapsed': False}).json()
        assert r['ok'] and [c['id'] for c in r['cells'] if c['extra'].get('heading_collapsed')] == ['P'], r
