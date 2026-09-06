"""The canvas document: the file it round-trips through, the dataflow between its bricks, and the
helper's reach into it.

The point of these is the contract a canvas file makes with git: a document that has been opened,
run, wired and asked questions of must come back byte for byte unless somebody changed something."""

import asyncio
import json
import pytest
from fastcore.all import Path
from starlette.testclient import TestClient
from fasthtml.common import fast_app

from leela.blocks.canvas.app import STORE, connect
from leela.blocks.canvas.doc import Brick, Canvas, defs_of, downstream, order, reads_of
from leela.blocks.canvas.helper import Ask, Scripted
from leela.blocks.canvas.live import Runtime
from leela.blocks.canvas.ops import apply_op
from leela.blocks.canvas.store import brick_host

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

```canvas brick id=b1 src=lego.bricks:thrifty.costs emit_row=picked
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

def test_a_canvas_is_markdown_and_comes_back_the_same():
    c = canvas()
    assert Canvas.parse(c.md()).md() == c.md()

def test_prose_between_bricks_becomes_its_own_brick():
    kinds = [b.kind for b in canvas()]
    assert kinds == ['text', 'code', 'brick', 'note', 'ask', 'text']

def test_an_id_written_in_the_file_survives_the_read():
    assert [b.id for b in canvas() if b.kind != 'text'] == ['c1', 'b1', 'n1', 'a1']

def test_a_brick_body_splits_into_bindings_props_and_the_rest():
    b = canvas().by_id('b1')
    assert b.binds == {'rows': "[{'label': 'one', 'monthly': cost}]"}
    assert b.props == {'height': '220'}
    assert b.attrs == {'src': 'lego.bricks:thrifty.costs', 'emit_row': 'picked'}
    assert b.body == ''

def test_a_wrapped_brick_stays_readable_to_a_plain_markdown_renderer():
    md = canvas().by_id('n1').md()
    assert md.startswith('<!--canvas note') and 'An **aside**.' in md

def test_code_is_kept_exactly_and_never_read_as_directives():
    assert canvas().by_id('c1').body == 'tokens = 1200\ncost = tokens / 1e6 * 3.0\n'

def test_frontmatter_carries_the_title_and_the_mode():
    c = canvas()
    assert c.title == 'A canvas' and c.meta['mode'] == 'make'

def test_a_canvas_holds_no_outputs_so_two_runs_diff_to_nothing(tmp_path):
    c = canvas()
    r = Runtime(); r.run_all(c.bricks)
    p = c.save(tmp_path/'x.canvas.md')
    assert p.read_text() == SRC

# --- the dataflow ---

def test_what_a_cell_defines_and_what_it_reads():
    assert list(defs_of('a = 1\ndef f(): pass\nimport os')) == ['a', 'f', 'os']
    assert 'cost' in reads_of("[{'monthly': cost}]")

def test_cells_run_in_dependency_order_not_document_order():
    c = Canvas.parse('```canvas code id=b\ny = x + 1\n```\n\n```canvas code id=a\nx = 1\n```\n')
    assert [b.id for b in order(c.bricks)] == ['a', 'b']

def test_a_cycle_falls_back_to_document_order_rather_than_hanging():
    c = Canvas.parse('```canvas code id=a\nx = y\n```\n\n```canvas code id=b\ny = x\n```\n')
    assert {b.id for b in order(c.bricks)} == {'a', 'b'}

def test_changing_a_name_reaches_every_brick_downstream_of_it():
    c = canvas()
    assert [b.id for b in downstream(c.bricks, ['tokens'])] == ['c1', 'b1']

def test_a_binding_that_fails_reports_rather_than_blanking_the_brick():
    c = canvas()
    r = Runtime()
    assert r.bindings(c.by_id('b1'))['rows'] == {'ok': False, 'error': "NameError: name 'cost' is not defined"}
    r.run_all(c.bricks)
    assert r.bindings(c.by_id('b1'))['rows']['value'] == [{'label': 'one', 'monthly': 0.0036}]

def test_a_value_handed_back_by_a_component_reruns_what_reads_it():
    c = Canvas.parse('```canvas code id=a\nn = 1\n```\n\n```canvas code id=b\nm = n * 2\n```\n')
    r = Runtime(); r.run_all(c.bricks)
    r.set('n', 21)
    settled = r.react(c.bricks, ['n'])
    assert list(settled['runs']) == ['b'] and r.ns['m'] == 42

def test_an_error_in_a_cell_is_an_output_not_an_exception():
    c = Canvas.parse('```canvas code id=a\n1/0\n```\n')
    out = Runtime().run(c[0])
    assert out['ok'] is False and out['outputs'][0]['ename'] == 'ZeroDivisionError'

# --- ops ---

def test_every_change_to_the_document_goes_through_one_function():
    c, r = canvas(), Runtime()
    assert apply_op(c, r, {'op': 'insert', 'after': 'c1', 'kind': 'text', 'body': 'New.'})['ok']
    assert [b.kind for b in c][:4] == ['text', 'code', 'text', 'brick']
    assert apply_op(c, r, {'op': 'bind', 'id': 'b1', 'port': 'rows', 'expr': '[]'})['ok']
    assert c.by_id('b1').binds['rows'] == '[]'
    assert apply_op(c, r, {'op': 'remove', 'id': 'n1'})['ok']
    assert c.by_id('n1') is None

def test_an_unknown_op_is_refused_by_name():
    assert apply_op(canvas(), Runtime(), {'op': 'drop_database'}) == {'ok': False, 'error': 'no op named drop_database'}

def test_an_answer_replaces_the_reply_it_already_wrote_rather_than_stacking():
    c, r = canvas(), Runtime()
    apply_op(c, r, {'op': 'answer', 'of': 'a1', 'markdown': 'first'})
    apply_op(c, r, {'op': 'answer', 'of': 'a1', 'markdown': 'second'})
    replies = [b for b in c if b.kind == 'reply']
    assert len(replies) == 1 and replies[0].body == 'second'

# --- the helper ---

def turn(question, **kw):
    c, r = kw.pop('canvas', None) or canvas(), kw.pop('runtime', None) or Runtime()
    r.run_all(c.bricks)
    ask = Ask(question=question, canvas=c, runtime=r, **kw)
    async def go(): return [e async for e in Scripted().turn(ask)]
    return c, r, asyncio.run(go())

def test_the_helper_answers_a_question_about_the_canvas_itself():
    _, _, events = turn('what is a bind?')
    assert any(e == 'answer' for e, _ in events)
    assert 'evaluated against the canvas namespace' in ''.join(d.get('text', '') for e, d in events if e == 'chunk')

def test_the_helper_edits_the_document_through_ops_and_nothing_else():
    _, _, events = turn('embed the cost table')
    ops = [d for e, d in events if e == 'op']
    assert ops and ops[0]['op'] == 'insert' and ops[0]['attrs']['src'] == 'lego.bricks:thrifty.costs'

def test_a_rewrite_touches_only_the_selection_it_was_given():
    c = Canvas.parse('```canvas note id=n\nIt is really just a very small thing. It works.\n```\n')
    _, _, events = turn('tighten this', canvas=c, brick_id='n', selection='It is really just a very small thing.')
    op = next(d for e, d in events if e == 'op')
    assert op['text'] == 'It is a small thing.' and op['was'].startswith('It is really')
    apply_op(c, Runtime(), op)
    assert c.by_id('n').body == 'It is a small thing. It works.'

def test_steering_arrives_mid_turn_and_changes_what_the_rest_of_it_does():
    c, r = canvas(), Runtime(); r.run_all(c.bricks)
    ask = Ask(question='summarise this', canvas=c, runtime=r)
    async def go():
        q = asyncio.Queue()
        await q.put('quiz me instead')
        return [e async for e in Scripted().turn(ask, q)]
    events = asyncio.run(go())
    assert any(d.get('label') == 'steering taken' for e, d in events if e == 'step')
    assert any(d.get('kind') == 'quiz' for e, d in events if e == 'op')

def test_the_trail_keeps_the_last_dozen_questions_and_no_more():
    from leela.blocks.canvas.store import Open
    o = Open(canvas=canvas())
    for i in range(20): o.remember(f'q{i}', 'c1')
    assert len(o.trail) == 12 and o.trail[-1]['question'] == 'q19'

# --- the shipped canvases ---

def _needs_host(brick, outputs):
    "A cell that fetches its data from the component host, with no host running."
    return 'urlopen' in brick.body and any(o.get('ename') in ('URLError', 'ConnectionError') for o in outputs)

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
def test_every_component_a_canvas_embeds_names_a_brick(path):
    for b in Canvas.load(path):
        if b.kind == 'brick': assert b.attrs.get('src', '').startswith('lego.bricks:')

# --- the routes ---

@pytest.fixture(scope='module')
def client():
    app, _ = fast_app(default_hdrs=False, pico=False, live=False)
    connect(app, ctx=None)
    return TestClient(app)

def test_opening_a_canvas_runs_it_and_returns_its_bindings(client):
    p = str(EXAMPLES/'a-sales-funnel.canvas.md')
    r = client.get('/canvas/open', params={'path': p, 'fresh': 1}).json()
    assert r['ok'] and len(r['canvas']['bricks']) == 10
    assert r['ports']['sf4']['tiles']['ok'] and 'cac' in r['names']

def test_a_component_writing_a_name_reruns_the_document(client):
    p = str(EXAMPLES/'a-sales-funnel.canvas.md')
    client.get('/canvas/open', params={'path': p, 'fresh': 1})
    stages = [{'name': 'Leads', 'value': 1000}, {'name': 'Won', 'value': 500}]
    r = client.post('/canvas/emit', json={'path': p, 'name': 'stages', 'value': stages}).json()
    assert r['ok'] and 'sf3' in r['runs']
    assert STORE.get(p).runtime.ns['won'] == 500

def test_opening_a_canvas_that_is_not_there_says_so(client):
    r = client.get('/canvas/open', params={'path': '/no/such.canvas.md'})
    assert r.status_code == 400 and 'no canvas' in r.json()['error']
