"""The canvas document: the file it round-trips through, the dataflow between its bricks, and the helper's reach into it."""

import asyncio
import os
from contextlib import contextmanager
import re
import time
import pytest
from fastcore.all import Path
from starlette.testclient import TestClient
from fasthtml.common import fast_app

from leela.blocks.canvas.app import connect
from leela.blocks.canvas.store import store_for
from leela.blocks.canvas.doc import Brick, Canvas, defs_of, downstream, order, reads_of
from leela.blocks.canvas.helper import TOOLS
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
    assert b.attrs == {'src': 'leela_bricks:thrifty.costs', 'emit_row': 'picked'}
    assert b.body == ''

def test_a_wrapped_brick_stays_readable_to_a_plain_markdown_renderer():
    md = canvas().by_id('n1').md()
    assert md.startswith('<!--canvas note') and 'An **aside**.' in md

def test_code_is_kept_exactly_and_never_read_as_directives():
    assert canvas().by_id('c1').body == 'tokens = 1200\ncost = tokens / 1e6 * 3.0\n'

def test_a_canvas_fence_inside_a_longer_fence_is_an_example_of_one():
    "A document about canvases is a canvas, and its examples must not become bricks."
    c = Canvas.parse('Text\n\n````md\n```canvas code id=x\n1\n```\n````\n\nMore.\n')
    assert [b.kind for b in c] == ['text']
    assert Canvas.parse(c.md()).md() == c.md()

def test_a_plain_code_fence_stays_prose():
    c = Canvas.parse('Text\n\n```python\nx = 1\n```\n\nMore.\n')
    assert [b.kind for b in c] == ['text'] and '```python' in c[0].body

def test_windows_line_endings_read_as_bricks_not_as_one_paragraph():
    c = Canvas.parse('# Head\r\n\r\n```canvas code id=c\r\nx=1\r\n```\r\n')
    assert [b.kind for b in c] == ['text', 'code'] and c.by_id('c').body == 'x=1\n'

def test_two_bricks_cannot_share_an_id():
    "Sharing one would make every op on the first reach the second, silently."
    c = Canvas.parse('```canvas code id=c\nx=1\n```\n\n```canvas code id=c\ny=2\n```\n')
    ids = [b.id for b in c]
    assert len(set(ids)) == 2 and ids[0] == 'c'
    assert c.by_id(ids[1]).body == 'y=2\n'

def test_an_attribute_value_may_carry_spaces():
    c = Canvas.parse('```canvas video id=v src="a b c"\ncap\n```\n')
    assert c.by_id('v').attrs['src'] == 'a b c'
    assert Canvas.parse(c.md()).md() == c.md()

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

def test_opening_a_canvas_reads_it_and_runs_nothing(client, corpus):
    "The document, its prose and its ports, with no cell executed and nothing trusted."
    p = str(corpus/'a-sales-funnel.canvas.md')
    r = client.get('/canvas/open', params={'path': p, 'fresh': 1}).json()
    assert r['ok'] and len(r['canvas']['bricks']) == 10
    assert r['runs'] == {} and r['trusted'] is False
    assert 'cac' not in r['names'], 'no cell has run, so nothing it defines is there'

def test_a_trusted_canvas_runs_and_returns_its_bindings(client, corpus):
    p = opened(client, corpus, 'a-sales-funnel.canvas.md')
    r = client.get('/canvas/open', params={'path': p}).json()
    assert r['trusted'] and r['ports']['sf4']['tiles']['ok'] and 'cac' in r['names']

def test_an_untrusted_canvas_is_still_editable(client, corpus):
    """Trust gates running, not writing."""
    p = str(corpus/'a-sales-funnel.canvas.md')
    client.get('/canvas/open', params={'path': p, 'fresh': 1})
    for op in ({'op': 'insert', 'kind': 'code', 'body': ''},
               {'op': 'insert', 'kind': 'text', 'body': 'prose is not code'},
               {'op': 'replace', 'id': 'sf1', 'body': 'stages = []'},
               {'op': 'kind', 'id': 'sf1', 'kind': 'text'},
               {'op': 'read'}):
        r = client.post('/canvas/op', json={'path': p, 'op': op})
        assert r.status_code == 200, (op, r.json())

@pytest.mark.parametrize('op', [
    {'op': 'insert', 'kind': 'code', 'body': 'x = 1'},
    {'op': 'values'},
    {'op': 'bind', 'id': 'sf2', 'port': 'stages', 'expr': 'stages'},
])
def test_an_untrusted_canvas_evaluates_nothing(client, corpus, op):
    "The other side of the same line: a body to run, or an expression to resolve, waits for trust."
    p = str(corpus/'a-sales-funnel.canvas.md')
    client.get('/canvas/open', params={'path': p, 'fresh': 1})
    r = client.post('/canvas/op', json={'path': p, 'op': op})
    assert r.status_code == 403 and 'trust' in r.json()['error']

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

def test_the_wiring_route_answers_for_a_brick_it_can_reach(client, corpus):
    "`/canvas/wire?src=` reached for a name that was never bound here, and answered 500 to every call."
    r = client.get('/canvas/wire', params={'src': 'leela_bricks:thrifty.costs'})
    assert r.status_code == 200 and r.json()['ok'], r.text
    assert client.get('/canvas/wire', params={'src': 'nobody:nothing'}).json()['ok'] is False

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

def test_code_turned_into_prose_takes_its_names_with_it(client, corpus, ws):
    p = opened(client, corpus, 'pricing-a-run.canvas.md')
    o = store_for(ws.fs).get(p)
    bid = client.post('/canvas/op', json={'path': p, 'op': {
        'op': 'insert', 'kind': 'code', 'body': 'temporary = 7'}}).json()['brick']['id']
    assert _val(o.runtime, 'temporary') == 7
    r = client.post('/canvas/op', json={'path': p, 'op': {'op': 'kind', 'id': bid, 'kind': 'text'}}).json()
    assert r['dropped'] == ['temporary'] and not _bound(o.runtime, 'temporary')

def test_inserted_wiring_runs_once(client, corpus, ws):
    "`insert` runs a code brick, and the wiring path ran it a second time, doubling its side effects."
    p = opened(client, corpus, 'pricing-a-run.canvas.md')
    o = store_for(ws.fs).get(p)
    o.runtime.set('tally', 0)
    r = client.post('/canvas/op', json={'path': p, 'op': {
        'op': 'insert', 'kind': 'code', 'body': 'tally = tally + 1'}}).json()
    assert r['run']['ok'] and _val(o.runtime, 'tally') == 1

def test_opening_a_canvas_that_is_not_there_says_so(client, corpus):
    r = client.get('/canvas/open', params={'path': 'no-such.canvas.md'})
    assert r.status_code == 400 and 'no canvas' in r.json()['error']

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

def test_a_save_cannot_write_its_destination_outside_the_tree(client, corpus):
    "`to` is a destination, and it passes the same gate as the source."
    p = opened(client, corpus, 'a-sales-funnel.canvas.md')
    r = client.post('/canvas/save', json={'path': p, 'to': '/tmp/escaped.canvas.md'})
    assert r.status_code == 400 and not Path('/tmp/escaped.canvas.md').exists()

def test_a_save_against_a_stale_revision_is_refused(client, corpus, ws):
    "Two editors, one file: the second writer is told rather than silently winning."
    p = opened(client, corpus, 'making-a-block.canvas.md')
    o = store_for(ws.fs).get(p)
    was = o.rev
    assert client.post('/canvas/save', json={'path': p, 'rev': was}).json()['ok']
    client.post('/canvas/op', json={'path': p, 'op': {'op': 'insert', 'kind': 'text', 'body': 'x'}})
    r = client.post('/canvas/save', json={'path': p, 'rev': was})
    assert r.status_code == 409 and 'moved to rev' in r.json()['error']

def test_a_brick_may_embed_a_file_beside_the_canvas_and_nothing_above_it(client, corpus):
    assert client.get('/canvas/file', params={'path': 'assets/brick-ports.pdf'}).status_code == 200
    for bad in ('../../etc/passwd', '/etc/passwd', 'assets/nope.pdf'):
        assert client.get('/canvas/file', params={'path': bad}).status_code == 404

@pytest.mark.parametrize('path', sorted(EXAMPLES.glob('*.canvas.md')), ids=lambda p: p.name)
def test_an_example_on_disk_is_already_what_the_writer_would_write(path):
    "Opening and saving a shipped canvas must not produce a diff."
    assert Canvas.load(path).md() == path.read_text()

def test_a_loop_or_a_context_manager_binds_a_name_like_anything_else():
    assert list(defs_of('for i in range(3): pass')) == ['i']
    assert list(defs_of('with open("f") as fh: pass')) == ['fh']
    assert list(defs_of('if (n := 5) > 1: pass')) == ['n']
    assert list(defs_of('def f():\n  hidden = 1\n  return hidden')) == ['f']

def test_a_comprehension_target_is_not_a_name_the_brick_reads():
    assert list(reads_of('[q for q in range(3)]')) == ['range']
    assert list(reads_of('sum(v for v in rows)')) == ['sum', 'rows']
    assert list(reads_of('lambda t: t + base')) == ['base']

def test_a_cell_that_reads_what_it_defines_runs_once_per_click():
    c = Canvas.parse('```canvas code id=a\nhits = 0\n```\n\n```canvas code id=b\nhits = hits + 1\nhits\n```\n')
    r = Runtime(); r.run_all(c.bricks)
    assert r.ns['hits'] == 1
    out = apply_op(c, r, {'op': 'run', 'id': 'b'})
    assert r.ns['hits'] == 2 and out['run']['outputs'][-1]['json'] == 2

def test_a_selection_that_cannot_be_found_changes_nothing():
    c = Canvas.parse('```canvas note id=n\nOne sentence. And a second.\n```\n')
    r = apply_op(c, Runtime(), {'op': 'replace_selection', 'id': 'n', 'was': 'not in here', 'text': 'X'})
    assert r['ok'] is False and c.by_id('n').body == 'One sentence. And a second.'

def test_a_selection_taken_from_rendered_prose_finds_its_markdown():
    "The selection is what was on the screen; the body still has the asterisks."
    c = Canvas.parse('```canvas note id=n\nOne **bold** sentence. And a second sentence here.\n```\n')
    r = apply_op(c, Runtime(), {'op': 'replace_selection', 'id': 'n',
                                'was': 'One bold sentence.', 'text': 'A short one.'})
    assert r['ok'] and c.by_id('n').body == 'A short one. And a second sentence here.'

def test_a_code_brick_holding_a_fence_is_written_with_a_longer_one():
    b = Brick(kind='code', id='c', body='x = """\n```\ninner\n```\n"""\n')
    c = Canvas(bricks=[b])
    assert c.md().startswith('````canvas code id=c')
    assert Canvas.parse(c.md()).by_id('c').body == b.body

def test_an_empty_attribute_survives_the_file():
    "A reply written from the margin has no anchor, and losing that stacks a second reply on reload."
    c, r = canvas(), Runtime()
    apply_op(c, r, {'op': 'answer', 'of': '', 'markdown': 'first'})
    back = Canvas.parse(c.md())
    assert back.reply_to('') is not None
    apply_op(back, r, {'op': 'answer', 'of': '', 'markdown': 'second'})
    assert len([b for b in back if b.kind == 'reply']) == 1

def test_code_the_helper_inserts_runs_where_it_lands():
    c, r = Canvas.parse(''), Runtime()
    out = apply_op(c, r, {'op': 'insert', 'kind': 'code', 'body': 'fresh = 41 + 1'})
    assert out['run']['ok'] and r.ns['fresh'] == 42

def test_a_repeated_phrase_is_rewritten_where_it_was_selected():
    for nth, want in [(0, 'ZZZ beta. gamma. alpha beta.'), (1, 'alpha beta. gamma. ZZZ beta.')]:
        c = Canvas.parse('```canvas note id=n\nalpha beta. gamma. alpha beta.\n```\n')
        apply_op(c, Runtime(), {'op': 'replace_selection', 'id': 'n', 'was': 'alpha', 'nth': nth, 'text': 'ZZZ'})
        assert c.by_id('n').body == want

def test_running_a_cell_settles_only_what_reads_it(client, corpus):
    "Handing back every port would post props to every frame, and a frame that takes props redraws."
    p = opened(client, corpus, 'a-sales-funnel.canvas.md')
    r = client.post('/canvas/run', json={'path': p, 'id': 'sf1'}).json()
    assert set(r['runs']) == {'sf3'} and set(r['ports']) == {'sf2', 'sf4', 'sf5', 'sf6'}
    r2 = client.post('/canvas/run', json={'path': p, 'id': 'sf3'}).json()
    assert 'sf3' not in r2['runs'] and 'sf2' not in r2['ports']

def test_run_all_uses_dependency_order_not_document_order(client, corpus):
    p = opened(client, corpus, 'a-sales-funnel.canvas.md')
    r = client.post('/canvas/runall', json={'path': p, 'sources': {}}).json()
    assert r['ok'] and all(v['ok'] for v in r['runs'].values())

# --- canvas mode ---

def test_the_canvas_skill_is_leelas_and_reaches_the_agent_only_when_a_canvas_is_open():
    from ramabana.testing import fake_agent
    from leela.skills import drop, push, pushed
    agent, _ = fake_agent(warm=False)
    assert '`canvas`' not in agent.system_prompt()
    assert push(agent, 'canvas') == ['canvas']
    assert '`canvas`' in agent.system_prompt() and pushed(agent) == {'canvas'}
    assert push(agent, 'canvas') == [], 'pushing twice must not stack'
    assert drop(agent, 'canvas') == 1 and '`canvas`' not in agent.system_prompt()

def test_the_canvas_skill_follows_the_open_tab_rather_than_the_turn(tmp_path):
    "The vocabulary follows the tab as the prompt is rebuilt; the tools follow it at the next turn (`_prepare` re-briefs the backend)."
    from leela.skills import pushed
    from leela.workspace import Workspace
    (tmp_path/'p.canvas.md').write_text('# p\n')
    (tmp_path/'p.md').write_text('# plain\n')
    ws = Workspace(roots=[tmp_path])
    ws.ai.system_prompt()
    assert pushed(ws.ai) == set()
    ws.open(tmp_path/'p.canvas.md')
    ws.ai.system_prompt()
    assert pushed(ws.ai) == {'canvas'}
    ws.open(tmp_path/'p.md')
    ws.ai.system_prompt()
    assert pushed(ws.ai) == set(), 'the vocabulary outstayed the document'

def test_canvas_tools_are_offered_only_while_a_canvas_is_open(tmp_path):
    from leela.workspace import Workspace
    from tests.fakemodel import Step, install
    (tmp_path/'p.canvas.md').write_text('# p\n'); (tmp_path/'p.md').write_text('# plain\n')
    ws = Workspace(roots=[tmp_path]); be = install(ws, [Step(text='ok')] * 4, token_delay=0)
    names = lambda ts: {t.__name__ for t in ts}
    ws.ai.ask('one'); assert 'canvas_read' not in names(be.tools) and 'canvas_read' not in names(ws.ai.tools)
    ws.open(tmp_path/'p.canvas.md'); ws.ai.ask('two')
    assert {'canvas_read', 'canvas_insert'} <= names(be.tools) and '`canvas`' in be.sp, 'the live backend was re-briefed at turn start'
    forgets = []; orig = ws.ai._forget; ws.ai._forget = lambda: forgets.append(1) or orig()
    ws.ai.ask('still'); assert not forgets, 'no mode change, no rebuild'
    ws.open(tmp_path/'p.md'); ws.ai.ask('three'); assert 'canvas_read' not in names(be.tools) and '`canvas`' not in be.sp

def test_a_briefing_rebuilt_between_turns_does_not_skip_the_re_brief(tmp_path):
    "An approval form or `/agent/commands` rebuilds `tools` mid-way; the backend was still briefed for the old mode."
    from leela.workspace import Workspace
    from leela.blocks.agent.turns import tool_schemas
    from tests.fakemodel import Step, install
    (tmp_path/'p.canvas.md').write_text('# p\n')
    ws = Workspace(roots=[tmp_path]); be = install(ws, [Step(text='ok')] * 2, token_delay=0)
    ws.ai.ask('one'); assert 'canvas_read' not in {t.__name__ for t in be.tools}
    ws.open(tmp_path/'p.canvas.md')
    tool_schemas(ws.ai); ws.ai.system_prompt()        # rebuilt for the browser, not for the backend
    ws.ai.ask('two')
    assert 'canvas_read' in {t.__name__ for t in be.tools} and '`canvas`' in be.sp

def test_the_client_bundle_names_every_module_and_serves_them_in_order(client, corpus):
    from leela.blocks.canvas.ui import FILES
    js = client.get('/canvas/js').text
    assert js.index('function cvOpenMenu') < js.index('function cvSlashAt'), 'the menu must be declared first'
    for f in FILES: assert (Path(__file__).resolve().parents[1]/'leela'/'blocks'/'canvas'/f).is_file()
    for fn in ('cvGutter', 'cvFormatBar', 'cvMenuKey', 'cvSplit', 'cvPick', 'cvTheme'): assert f'function {fn}' in js

def test_the_stylesheet_carries_both_themes(client, corpus):
    css = client.get('/canvas/css').text
    light = set(re.findall(r'--cv-[\w-]+(?=:)', css.split('[data-theme=dark]')[0]))
    dark = set(re.findall(r'--cv-[\w-]+(?=:)', css.split('[data-theme=dark]')[1].split('*')[0]))
    assert dark and dark <= light, f'dark names a token light does not: {sorted(dark - light)}'


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
    '[x](javascript:alert(1))',
    '[x](JaVaScRiPt:alert(1))',
    '[x](java\tscript:alert(1))',
    '![a](data:text/html;base64,PHNjcmlwdD4=)',
    '![a](data:image/svg+xml;base64,PHN2Zz4=)',
    '[x](vbscript:msgbox)',
])
def test_markdown_refuses_a_url_that_is_script(src):
    """A scheme that executes is not a URL."""
    out = _node_md(src)
    assert 'href=' not in out and 'src=' not in out, out

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

def test_markdown_still_renders_the_links_a_document_needs():
    "The gate is not a ban: http, mailto, a relative path and an anchor all still render."
    for src, want in (('[a](https://example.com/x?y=1)', 'href="https://example.com/x?y=1"'),
                      ('[a](mailto:x@example.com)', 'href="mailto:x@example.com"'),
                      ('[a](../notes.md)', 'href="../notes.md"'),
                      ('[a](#section)', 'href="#section"'),
                      ('![a](assets/x.png)', 'src="assets/x.png"')):
        assert want in _node_md(src), (src, _node_md(src))

def test_every_component_frame_is_sandboxed():
    "A frame runs code the document did not write. Same-origin would give it this page's session."
    js = (Path(__file__).resolve().parents[1]/'leela'/'blocks'/'canvas'/'canvas.js').read_text()
    code = re.sub(r'/\*.*?\*/', '', js, flags=re.S)          # the prose explains the rule; the code holds it
    assert "setAttribute('sandbox', CV_SANDBOX)" in code
    assert re.search(r"CV_SANDBOX\s*=\s*'allow-scripts'", code), 'the one sandbox value'
    assert 'allow-same-origin' not in code, 'same-origin would undo the sandbox'
    #: Both the packaged component and the in-document sketch go through the one builder.
    assert code.count('const f = cvFrame(b);') == 2

def test_a_frame_speaks_only_for_itself():
    "The id a message claims was trusted when no frame matched the sender, so any window could emit."
    js = (Path(__file__).resolve().parents[1]/'leela'/'blocks'/'canvas'/'canvas.js').read_text()
    assert 'const id = f?.dataset.id; if (!id) return;' in js
    assert 'f?.dataset.id || d.id' not in js


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

    def test_a_cell_runs_in_another_process(self):
        with self.runtime() as rt:
            r = rt.run(self.cell('import os\npid = os.getpid()\npid'))
            assert r['ok'], r['outputs']
            assert rt.eval_many({'p': 'pid'})['p']['value'] != os.getpid()

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

    def test_a_port_resolves_through_the_kernel(self):
        with self.runtime() as rt:
            rt.run(self.cell('rows = [{"a": 1}, {"a": 2}]'))
            b = Brick(kind='brick', id='v', binds={'series': 'rows', 'bad': '1/0'})
            got = rt.bindings(b)
            assert got['series'] == {'ok': True, 'value': [{'a': 1}, {'a': 2}]}
            assert got['bad']['ok'] is False and 'ZeroDivisionError' in got['bad']['error']

    def test_a_value_the_browser_emits_arrives_as_json(self):
        with self.runtime() as rt:
            rt.set('stages', [{'name': 'Leads', 'value': 10}])
            assert rt.eval_many({'s': 'stages[0]["value"]'})['s']['value'] == 10

    def test_a_name_a_cell_stops_defining_is_dropped_in_the_kernel_too(self):
        with self.runtime() as rt:
            b = self.cell('doomed = 1', 'x')
            rt.run(b)
            assert 'doomed' in rt.names()
            b.body = 'kept = 2'
            assert rt.retire(b) == ['doomed']
            assert 'doomed' not in rt.names()


# --- the canvas as tools on the workspace agent ---

def _ws_with_canvas(tmp_path, body='# t\n\n```canvas code id=c1\ncost = 3.6\ncost\n```\n'):
    from leela.workspace import Workspace
    p = tmp_path/'t.canvas.md'
    p.write_text(body)
    ws = Workspace(roots=[tmp_path])
    ws.open(p)
    return ws, p

def test_the_canvas_tools_are_built_with_the_agent_not_pushed_on_for_one_turn(tmp_path):
    "A backend takes its tool list once: registered per turn, every live call came back `KeyError`."
    from leela.blocks.canvas.helper import TOOLS
    ws, _ = _ws_with_canvas(tmp_path)
    names = {t.__name__ for t in ws.ai.tools}
    assert set(TOOLS) <= names, sorted(set(TOOLS) - names)

def test_a_canvas_tool_finds_the_document_through_the_host_the_agent_is_given(tmp_path):
    "The agent holds a `WorkspaceHost`; the tabs and the pool are on the workspace behind it."
    from leela.blocks.canvas.helper import open_canvas
    ws, p = _ws_with_canvas(tmp_path)
    assert open_canvas(ws.ai.host) is not None, 'the tools resolve nothing through the real host'
    assert open_canvas(ws) is not None
    (tmp_path/'plain.md').write_text('hi')
    ws.open(tmp_path/'plain.md')
    assert open_canvas(ws) is None, 'a text tab is not a canvas'

def test_a_tool_edits_the_open_document_and_writes_it_back(tmp_path):
    "The reply and the edit both land in the file, which is where a canvas keeps its reasoning."
    from leela.blocks.canvas.helper import canvas_tools
    from leela.blocks.canvas.doc import Canvas
    ws, p = _ws_with_canvas(tmp_path)
    by = {t.__name__: t for t in canvas_tools(ws)}
    assert 'c1' in by['canvas_read']()
    assert 'inserted' in by['canvas_insert'](kind='note', body='what it means', after='c1')
    doc = Canvas.load(p)
    assert [b.kind for b in doc] == ['text', 'code', 'note']

def test_the_tools_hold_the_same_trust_gate_the_routes_do(tmp_path):
    "The pane is another way of asking, not a way past the gate."
    from leela.blocks.canvas.helper import canvas_tools, open_canvas
    ws, p = _ws_with_canvas(tmp_path)
    by = {t.__name__: t for t in canvas_tools(ws)}
    assert 'trusted' in by['canvas_run'](id='c1')
    assert 'trusted' in by['canvas_values']()
    open_canvas(ws).allow()
    assert 'trusted' not in by['canvas_run'](id='c1')

def test_a_tool_says_so_when_no_canvas_is_open(tmp_path):
    "One registration serves every tab, so the answer when there is no tab has to be a sentence."
    from leela.blocks.canvas.helper import canvas_tools
    from leela.workspace import Workspace
    ws = Workspace(roots=[tmp_path])
    by = {t.__name__: t for t in canvas_tools(ws)}
    assert 'no canvas is open' in by['canvas_read']()

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

def test_a_reading_tool_is_not_a_change(tmp_path):
    "A reader in the write registry would make every turn offer to restore a file nothing touched."
    from leela.blocks.canvas.helper import WRITES, canvas_tools
    ws, p = _ws_with_canvas(tmp_path)
    ai = ws.ai
    ai.tools
    for name in ('canvas_read', 'canvas_values', 'canvas_run'):
        assert name not in WRITES
        ai.registry.fire('before_tool', ai, name, {})
    assert ai.before == {} and ai.changes() == {}

def test_every_leela_write_tool_is_declared_where_the_hook_looks(tmp_path):
    "A Leela tool that writes and is not in this registry changes a file no undo can see."
    from leela.blocks.agent.ai import leela_writes
    from leela.blocks.canvas.helper import WRITES
    assert set(leela_writes()) == set(WRITES)

def test_a_read_only_tool_writes_nothing(tmp_path):
    "`canvas_read` and `canvas_values` must not file an operation, or undo fills up with nothing."
    from leela.blocks.canvas.helper import canvas_tools
    ws, p = _ws_with_canvas(tmp_path)
    was = p.read_text()
    by = {t.__name__: t for t in canvas_tools(ws)}
    by['canvas_read']()
    assert p.read_text() == was and not ws.journal.operations


def test_the_skill_names_every_tool_the_agent_is_given():
    "The vocabulary and the toolset are two files, and they drift apart in silence."
    from leela.skills import skill
    body = skill('canvas').text()
    for name in TOOLS: assert f'`{name}`' in body, f'{name} is not in the skill'
