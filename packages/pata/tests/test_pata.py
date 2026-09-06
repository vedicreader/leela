import time
import pytest
from pata import Block, Doc, arrange, modules, render, resolve, to_ipynb, from_ipynb, to_markdown, weigh
from pata.context import Spec, strip_work_log
from pata.example import procurement

def doc():
    d = Doc()
    d.add(Block('goal', {'source': 'ship it'}, id='g'))
    d.add(Block('text', {'source': 'a' * 300}, id='a'))
    d.add(Block('text', {'source': 'b' * 300}, id='b', mode='discard'))
    d.add(Block('code', {'source': 'c' * 300}, id='c', mode='keep'))
    d.add(Block('prompt', {'source': 'what now?'}, id='p'))
    return d

def test_scopes_choose_different_blocks():
    d = procurement()
    at = lambda s: {i.ref for i in resolve(d, 'p-risk', Spec(scope=s, goal=False))}
    assert 'c-backtest' in at('upstream') and 'k-1' not in at('upstream')
    assert at('frame') and at('frame').isdisjoint({'k-1', 'k-2'})
    assert at('none') == set()
    assert at('page') < at('doc')
    assert 'p-rec' in at('doc') and 'p-rec' not in at('page')   # only `doc` reads forwards

def test_the_goal_and_pins_survive_a_budget_that_drops_everything_else():
    d = doc()
    got = resolve(d, 'p', Spec(scope='page', pins=['a'], budget=800))
    kept = [i.ref for i in got]
    assert kept[0] == 'g' and 'a' in kept and 'c' in kept   # goal, pin, and the `keep` block
    assert 'b' not in kept                                  # `discard` goes first
    assert weigh(got)['chars'] <= 800

def test_a_pin_larger_than_the_whole_budget_is_clipped_not_dropped():
    d = doc()
    d['a'].props['source'] = 'x' * 5000
    got = resolve(d, 'p', Spec(scope='none', pins=['a'], budget=1000, goal=False))
    assert [i.ref for i in got] == ['a'] and got[0].clipped and got[0].chars < 5000

def test_a_pin_that_no_longer_resolves_is_visible_rather_than_silent():
    d = doc()
    got = resolve(d, 'p', Spec(scope='none', pins=['gone'], goal=False))
    assert weigh(got)['missing'] == ['gone']
    d.remove('a')
    d['p'].props['context'] = {'scope': 'none', 'pins': ['a']}
    d.prune()
    assert weigh(resolve(d, 'p'))['missing'] == []          # pruned, not left dangling

def test_render_keeps_the_shape_ramabana_sheds_when_a_prompt_overflows():
    "`compact_notebook_context` matches `<cell ... compact=\"auto|keep|discard\">`; anything else is unshedable."
    out = render(resolve(doc(), 'p', Spec(scope='page', budget=None)))
    assert '<cell id="g" type="goal" compact="keep"' in out
    assert 'compact="auto"' in out and '<block ' not in out

def test_a_reply_is_fed_forward_without_its_work_log():
    d = doc()
    d.add(Block('prompt', {'source': 'first', 'reply':
        'the answer\n\n<details><summary>what i did</summary>\ntool spam\n</details>'}, id='q'), at=4)
    assert strip_work_log(d['q'].get('reply')) == 'the answer'
    out = render(resolve(d, 'p', Spec(scope='page')))
    assert 'the answer' in out and 'tool spam' not in out

def test_a_block_goes_stale_when_something_upstream_runs_again():
    d = Doc()
    d.add(Block('code', {'source': 'df = load()'}, id='u')).ran(at=100)
    d.add(Block('code', {'source': 'chart(df)', 'outputs': [{'output_type': 'stream', 'text': 'ok'}]},
                id='v')).ran(at=200)
    d.add(Block('edge', {'src': 'u', 'dst': 'v'}, id='e1'))
    assert not d.stale('v')
    d['u'].ran(at=300)
    assert d.stale('v') and not d['v'].stale     # the hash cannot see it; the graph can

def test_the_edge_graph_survives_a_cycle_and_a_copy():
    d = Doc()
    for i in 'xyz': d.add(Block('code', {'source': i}, id=i))
    for a, b in (('x', 'y'), ('y', 'z'), ('z', 'x')): d.add(Block('edge', {'src': a, 'dst': b}, id=f'e{a}'))
    assert set(d.reachable('z', back=True)) == {'x', 'y'}
    made = d.copy(['x', 'y'])
    new = {b.id for b in made if b.kind != 'edge'}
    assert len(new) == 2 and not new & {'x', 'y'}
    copied = [b for b in made if b.kind == 'edge']
    assert copied and all(e.get('src') in new and e.get('dst') in new for e in copied)

def test_a_pasted_jupytext_snippet_survives_the_diffable_document():
    d = Doc()
    d.add(Block('text', {'source': 'quoting the format:\n# %% code fake\nnot a block'}, id='t'))
    d.add(Block('code', {'source': 'x = 1'}, id='k'))
    back = Doc.from_json(d.json()).take_source_text(d.source_text())
    assert [b.id for b in back] == ['t', 'k']
    assert back['t'].source.endswith('not a block')

def test_a_document_round_trips_through_a_notebook_with_its_work_intact():
    d = procurement()
    back = from_ipynb(to_ipynb(d))
    assert [b.kind for b in back] == [b.kind for b in d]
    assert back['c-share'].outputs == d['c-share'].outputs
    assert back['p-risk'].get('reply') == d['p-risk'].get('reply')
    assert back['goal'].get('measure') == d['goal'].get('measure')
    assert {(e.get('src'), e.get('dst')) for e in back.edges} == {(e.get('src'), e.get('dst')) for e in d.edges}

def test_an_imported_notebook_arrives_with_a_canvas():
    nb = {'cells': [{'cell_type': 'code', 'source': 'x = 1', 'outputs': [], 'id': 'c1'},
                    {'cell_type': 'markdown', 'source': '# notes', 'id': 'm1'}], 'nbformat': 4}
    d = arrange(from_ipynb(nb))
    assert all(b.placed for b in d) and d['c1'].y < d['m1'].y

def test_export_directives_pick_the_module():
    d = procurement()
    assert set(modules(d)) == {'procure/core.py'}
    assert 'def triage' in modules(d)['procure/core.py']
    d['c-rule'].props['source'] = d['c-rule'].source.replace('#|export', '#|export procure.rules')
    assert set(modules(d)) == {'procure/core.py', 'procure/rules.py'}

def test_a_duplicate_id_is_refused():
    d = doc()
    with pytest.raises(ValueError): d.add(Block('text', {}, id='a'))
