"""The canvas document: the file it round-trips through, the dataflow between its bricks, and the helper's reach into it."""

import asyncio
from contextlib import contextmanager
import re
import time
import pytest
from fastcore.all import Path
from starlette.testclient import TestClient
from fasthtml.common import fast_app

from leela.blocks.canvas.app import connect
from leela.blocks.canvas.store import store_for
from leela.blocks.canvas.doc import Brick, Canvas, order, reads_of
from leela.blocks.canvas.live import Runtime
from leela.blocks.canvas.ops import apply_op
from leela.blocks.canvas.store import brick_host

#: One worker takes the whole module. `client`, `ws` and `corpus` are module-scoped, so scattering
#: these across workers rebuilds the ide app per worker and runs canvas runtimes concurrently:
#: 600s against 30s, and the trust a test reads is whichever ordering the scheduler picked.
pytestmark = pytest.mark.xdist_group('canvas')

EXAMPLES = Path(__file__).resolve().parents[1]/'examples'/'canvas'

SRC = '''---
title: A canvas
mode: make
---

# A canvas

Some prose.

```canvas code id=c1
tokens = 1200
cost = tokens / 1e6 * 3.0
```

```canvas brick id=b1 src=leela_bricks:thrifty.costs emit_row=picked
bind rows = [{'label': 'one', 'monthly': cost}]
prop height = 220
```

<!--canvas note id=n1-->
An **aside**.
<!--/canvas-->

```canvas ask id=a1
why?
```

Closing prose.
'''

def canvas(): return Canvas.parse(SRC, 'x.canvas.md')

# --- the file ---


def test_a_canvas_fence_inside_a_longer_fence_is_an_example_of_one():
    "A document about canvases is a canvas, and its examples must not become bricks."
    c = Canvas.parse('Text\n\n````md\n```canvas code id=x\n1\n```\n````\n\nMore.\n')
    assert [b.kind for b in c] == ['text']
    assert Canvas.parse(c.md()).md() == c.md()


def test_windows_line_endings_read_as_bricks_not_as_one_paragraph():
    c = Canvas.parse('# Head\r\n\r\n```canvas code id=c\r\nx=1\r\n```\r\n')
    assert [b.kind for b in c] == ['text', 'code'] and c.by_id('c').body == 'x=1\n'

def test_two_bricks_cannot_share_an_id():
    "Sharing one would make every op on the first reach the second, silently."
    c = Canvas.parse('```canvas code id=c\nx=1\n```\n\n```canvas code id=c\ny=2\n```\n')
    ids = [b.id for b in c]
    assert len(set(ids)) == 2 and ids[0] == 'c'
    assert c.by_id(ids[1]).body == 'y=2\n'


# --- the dataflow ---


def test_cells_run_in_dependency_order_not_document_order():
    c = Canvas.parse('```canvas code id=b\ny = x + 1\n```\n\n```canvas code id=a\nx = 1\n```\n')
    assert [b.id for b in order(c.bricks)] == ['a', 'b']

def test_a_cycle_falls_back_to_document_order_rather_than_hanging():
    c = Canvas.parse('```canvas code id=a\nx = y\n```\n\n```canvas code id=b\ny = x\n```\n')
    assert {b.id for b in order(c.bricks)} == {'a', 'b'}


# --- the shipped canvases ---

def _needs_host(brick, outputs):
    "A cell that fetches its data from the component host. Any error means none answers here."
    return 'urlopen' in brick.body and any(o.get('output_type') == 'error' for o in outputs)

@pytest.mark.parametrize('path', sorted(EXAMPLES.glob('*.canvas.md')), ids=lambda p: p.name)
def test_every_example_parses_runs_and_binds(path):
    c = Canvas.load(path)
    assert Canvas.parse(c.md()).md() == c.md(), 'does not round-trip'
    r = Runtime()
    failed = {k: v['outputs'] for k, v in r.run_all(c.bricks).items() if not v['ok']}
    if any(_needs_host(c.by_id(k), v) for k, v in failed.items()):
        pytest.skip(f'{path.name} wires itself from a component host, and none answers on {brick_host()}')
    assert failed == {}
    bad = {(b.id, port): res['error'] for b in c if b.binds
           for port, res in r.bindings(b).items() if not res['ok']}
    assert bad == {}

@pytest.mark.parametrize('path', sorted(EXAMPLES.glob('*.canvas.md')), ids=lambda p: p.name)
def test_every_component_a_canvas_embeds_resolves_to_a_real_brick(path):
    "A literal prefix only said the string looked right. The resolver can say the brick is there."
    from leela.blocks.canvas.bricks import libraries, locate
    libs = libraries()
    for b in Canvas.load(path):
        if b.kind != 'brick': continue
        src = b.attrs.get('src', '')
        assert ':' in src, f'{src!r} names no library'
        lib, row = locate(src, libs)
        assert lib is not None, f'no library answers {src!r}; is `extensions/bricks` installed?'
        assert row['name'] == src.split(':', 1)[1]

def _val(rt, name):
    "One name out of the document's namespace, whichever runtime is behind it."
    got = rt.snapshot([name]).get(name) or {}
    return got.get('value') if got.get('ok') else None

def _bound(rt, name): return (rt.snapshot([name]).get(name) or {}).get('ok', False)

# --- the routes ---

@pytest.fixture(scope='module')
def corpus(tmp_path_factory):
    "A copy of the examples. The suite used to save over the ones in the checkout as it read them."
    import shutil
    d = tmp_path_factory.mktemp('canvases')
    shutil.copytree(EXAMPLES, d/'canvas')
    return d/'canvas'

@pytest.fixture(scope='module')
def ws(corpus):
    from leela.workspace import Workspace
    return Workspace(roots=[str(corpus)])

@pytest.fixture(scope='module')
def client(ws):
    from leela.app import ide_app
    return TestClient(ide_app(ws))

def opened(client, corpus, name, trust=True):
    """Open a canvas and, unless a test is about trust, say its code may run."""
    p = str(corpus/name)
    client.get('/canvas/open', params={'path': p, 'fresh': 1})
    if trust: assert client.post('/canvas/trust', json={'path': p}).json()['ok']
    return p


@pytest.mark.parametrize('route,body', [
    ('/canvas/run', {'id': 'sf3'}),
    ('/canvas/runall', {}),
    ('/canvas/emit', {'name': 'stages', 'value': []}),
    ('/canvas/op', {'op': {'op': 'values'}}),
])
def test_an_untrusted_canvas_executes_nothing(client, corpus, route, body):
    "Opening a document must not run it, and nor must anything else until somebody says so."
    p = str(corpus/'a-sales-funnel.canvas.md')
    client.get('/canvas/open', params={'path': p, 'fresh': 1})
    r = client.post(route, json={'path': p, **body})
    assert r.status_code == 403 and 'trust' in r.json()['error']


def test_a_component_writing_a_name_reruns_the_document(client, corpus, ws):
    p = opened(client, corpus, 'a-sales-funnel.canvas.md')
    stages = [{'name': 'Leads', 'value': 1000}, {'name': 'Won', 'value': 500}]
    r = client.post('/canvas/emit', json={'path': p, 'name': 'stages', 'value': stages}).json()
    assert r['ok'] and 'sf3' in r['runs']
    assert _val(store_for(ws.fs).get(p).runtime, 'won') == 500

def test_a_name_a_cell_stops_defining_is_dropped(client, corpus, ws):
    """The namespace kept every name a cell had ever defined."""
    p = opened(client, corpus, 'pricing-a-run.canvas.md')
    o = store_for(ws.fs).get(p)
    ins = client.post('/canvas/op', json={'path': p, 'op': {
        'op': 'insert', 'kind': 'code', 'body': 'doomed = 41'}}).json()
    bid = ins['brick']['id']
    assert _val(o.runtime, 'doomed') == 41
    r = client.post('/canvas/op', json={'path': p, 'op': {
        'op': 'replace', 'id': bid, 'body': 'kept = 42'}}).json()
    assert r['dropped'] == ['doomed'] and not _bound(o.runtime, 'doomed')
    client.post('/canvas/run', json={'path': p, 'id': bid})
    assert _val(o.runtime, 'kept') == 42
    gone = client.post('/canvas/op', json={'path': p, 'op': {'op': 'remove', 'id': bid}}).json()
    assert gone['dropped'] == ['kept'] and not _bound(o.runtime, 'kept')


def test_inserted_wiring_runs_once(client, corpus, ws):
    "`insert` runs a code brick, and the wiring path ran it a second time, doubling its side effects."
    p = opened(client, corpus, 'pricing-a-run.canvas.md')
    o = store_for(ws.fs).get(p)
    o.runtime.set('tally', 0)
    r = client.post('/canvas/op', json={'path': p, 'op': {
        'op': 'insert', 'kind': 'code', 'body': 'tally = tally + 1'}}).json()
    assert r['run']['ok'] and _val(o.runtime, 'tally') == 1


@pytest.mark.parametrize('bad', ['/etc/passwd', '../../etc/passwd', '/no/such.canvas.md',
                                 '../../pyproject.toml'])
def test_no_live_route_reaches_a_path_outside_the_tree(client, corpus, bad):
    """Every route that took a path read, ran or overwrote whatever it named."""
    assert client.get('/canvas/open', params={'path': bad}).status_code == 400
    for route, body in (('/canvas/op', {'op': {'op': 'read'}}), ('/canvas/run', {'id': 'x'}),
                        ('/canvas/runall', {}), ('/canvas/emit', {'name': 'x', 'value': 1}),
                        ('/canvas/save', {})):
        r = client.post(route, json={'path': bad, **body})
        assert r.status_code == 400, f'{route} accepted {bad}'


def test_a_comprehension_target_is_not_a_name_the_brick_reads():
    assert list(reads_of('[q for q in range(3)]')) == ['range']
    assert list(reads_of('sum(v for v in rows)')) == ['sum', 'rows']
    assert list(reads_of('lambda t: t + base')) == ['base']


def test_a_selection_taken_from_rendered_prose_finds_its_markdown():
    "The selection is what was on the screen; the body still has the asterisks."
    c = Canvas.parse('```canvas note id=n\nOne **bold** sentence. And a second sentence here.\n```\n')
    r = apply_op(c, Runtime(), {'op': 'replace_selection', 'id': 'n',
                                'was': 'One bold sentence.', 'text': 'A short one.'})
    assert r['ok'] and c.by_id('n').body == 'A short one. And a second sentence here.'


def test_an_empty_attribute_survives_the_file():
    "A reply written from the margin has no anchor, and losing that stacks a second reply on reload."
    c, r = canvas(), Runtime()
    apply_op(c, r, {'op': 'answer', 'of': '', 'markdown': 'first'})
    back = Canvas.parse(c.md())
    assert back.reply_to('') is not None
    apply_op(back, r, {'op': 'answer', 'of': '', 'markdown': 'second'})
    assert len([b for b in back if b.kind == 'reply']) == 1


def _node_md(src):
    "Render one string through `md.js` in node, the way a canvas frame renders it."
    import json, shutil, subprocess
    node = shutil.which('node')
    if node is None: pytest.skip('no node')
    js = (Path(__file__).resolve().parents[1]/'leela'/'blocks'/'canvas'/'md.js').read_text()
    prog = js + f'\nprocess.stdout.write(cvMd({json.dumps(src)}));\n'
    r = subprocess.run([node, '--input-type=module', '-e', prog], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


@pytest.mark.parametrize('src', [
    '![a](x" onerror="alert(1))',
    "![a](x' onerror='alert(1))",
    '[t](x" onmouseover="alert(1))',
    '[t"onclick="alert(1)](https://example.com)',
])
def test_markdown_cannot_inject_an_attribute(src):
    """`cvEsc` escaped only `&<>`, so a quote in a URL or a link label closed the attribute and opened one of the author's choosing."""
    out = _node_md(src)
    assert re.search(r'<[^>]*\son\w+\s*=', out) is None, out


@pytest.mark.slow
class TestTheKernelBackedRuntime:
    """What a document may not do to Leela."""
    @contextmanager
    def runtime(self, timeout=5):
        """A kernel-backed runtime, and the pool closed after it."""
        from leela.blocks.runtime.kernels import KernelPool
        from leela.blocks.canvas.live import runtime_for, KernelRuntime
        pool = KernelPool()
        rt = runtime_for(pool, key=f'test-{id(self)}', timeout=timeout)
        assert isinstance(rt, KernelRuntime), 'a pool means a kernel'
        try: yield rt
        finally:
            rt.submit(pool.close_all(), 20)      # on the loop the pool's own tasks live on
            rt.close()

    def cell(self, body, id='c'):
        return Brick(kind='code', body=body, id=id)


    def test_an_endless_cell_is_interrupted_and_the_kernel_survives(self):
        "The reported wedge: one `while True:` and every later request queued behind it for good."
        with self.runtime(timeout=4) as rt:
            rt.run(self.cell('kept = 11', 'a'))
            t0 = time.time()
            r = rt.run(self.cell('while True: pass', 'b'))
            took = time.time() - t0
            assert not r['ok'] and took < 20, f'{took}s'
            assert 'KeyboardInterrupt' in [o.get('ename') for o in r['outputs']]
            assert rt.eval_many({'k': 'kept'})['k']['value'] == 11, 'and the namespace is still there'

    def test_a_cell_that_exits_takes_only_its_own_kernel(self):
        "`os._exit()` in a cell used to end Leela. It ends the kernel, and the next cell gets a new one."
        with self.runtime(timeout=4) as rt:
            rt.run(self.cell('import os; os._exit(1)', 'boom'))
            r = rt.run(self.cell('recovered = 3\nrecovered', 'after'))
            assert r['ok'], r['outputs']
            assert rt.eval_many({'r': 'recovered'})['r']['value'] == 3


def test_a_kernel_that_never_starts_costs_one_timeout_not_one_per_cell():
    "A start that hangs made every cell of `run_all` wait out its own timeout in turn."
    import asyncio
    from leela.blocks.canvas.live import KernelRuntime
    async def start(): await asyncio.Event().wait()
    rt = KernelRuntime(start, timeout=1)
    bricks = [Brick(kind='code', body=f'x{i} = {i}', id=f'c{i}') for i in range(3)]
    try:
        t0 = time.time()
        runs = rt.run_all(bricks)
        took = time.time() - t0
    finally: rt.close()
    assert took < 5, f'{took}s'
    assert all(not r['ok'] and r['outputs'][0]['ename'] == 'TimeoutError' for r in runs.values()), runs


def test_a_start_that_outlasts_the_timeout_serves_the_next_call_once_it_is_up():
    "A slow start made every call fail for a whole timeout afterwards, even once the kernel it was starting was up."
    import asyncio
    from types import SimpleNamespace
    from leela.blocks.canvas.live import KernelRuntime
    class K:
        alive = True
        async def execute(self, code, timeout=None): return SimpleNamespace(outputs=[{'output_type': 'stream', 'name': 'stdout', 'text': 'ok'}])
        async def interrupt(self): pass
        async def shutdown(self): pass
    starts = []
    async def start():
        starts.append(1)
        await asyncio.sleep(1.5)
        return K()
    rt = KernelRuntime(start, timeout=1)
    try:
        assert rt.exec_cell('x = 1')[0]['ename'] == 'TimeoutError'
        assert rt.exec_cell('x = 1')[0]['ename'] == 'TimeoutError', 'a call while the start is still going fails at once'
        time.sleep(.8)
        assert rt.exec_cell('x = 1')[0]['text'] == 'ok', 'the start that finished is the kernel the next call uses'
    finally: rt.close()
    assert starts == [1], 'one start, not one per call'
    from concurrent.futures import ThreadPoolExecutor
    async def quick(): starts.append(2); await asyncio.sleep(.3); return K()
    rt = KernelRuntime(quick, timeout=1)
    try:
        with ThreadPoolExecutor(2) as ex: both = list(ex.map(lambda _: rt.exec_cell('x = 1')[0], range(2)))
    finally: rt.close()
    assert [o.get('text') for o in both] == ['ok', 'ok'], 'a call made while another waits on the start joins that wait'
    assert starts == [1, 2]


def test_closing_a_runtime_cancels_the_start_it_left_behind_and_closes_its_loop():
    "A pool shields its starts, so a timed-out start outlived the runtime on a loop that was stopped and never closed."
    import asyncio
    from leela.blocks.canvas.live import KernelRuntime
    cancelled = []
    async def boot():
        try: await asyncio.Event().wait()
        except asyncio.CancelledError: cancelled.append(1); raise
    async def start(): return await asyncio.shield(asyncio.ensure_future(boot()))
    rt = KernelRuntime(start, timeout=1)
    assert rt.exec_cell('x = 1')[0]['ename'] == 'TimeoutError'
    lp = rt._lp
    rt.close()
    assert cancelled == [1], 'the shielded start is cancelled, not stranded'
    assert lp.is_closed(), 'the loop is closed, not merely stopped'


# --- the canvas as tools on the workspace agent ---

def _ws_with_canvas(tmp_path, body='# t\n\n```canvas code id=c1\ncost = 3.6\ncost\n```\n'):
    from leela.workspace import Workspace
    p = tmp_path/'t.canvas.md'
    p.write_text(body)
    ws = Workspace(roots=[tmp_path])
    ws.open(p)
    return ws, p


def test_a_tool_write_is_a_change_the_turn_can_take_back(tmp_path):
    "Ramabana records `before` for its own writers only, so Leela records it for Leela\'s."
    from leela.blocks.canvas.helper import canvas_tools
    ws, p = _ws_with_canvas(tmp_path)
    ai = ws.ai
    ai.tools                                        # wires the registry, as a turn does
    by = {t.__name__: t for t in canvas_tools(ws)}
    ai.registry.fire('before_tool', ai, 'canvas_insert', {'kind': 'note', 'body': 'x'})
    by['canvas_insert'](kind='note', body='written by a tool', after='c1')
    assert 'written by a tool' in p.read_text()
    was, now = ai.changes()[str(p)]
    assert 'written by a tool' in now and 'written by a tool' not in was


