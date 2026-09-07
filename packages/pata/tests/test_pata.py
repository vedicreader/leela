import pytest
from pata import (Brick, Doc, arrange, body_text, from_ipynb, modules, order, render, resolve,
                  to_ipynb, to_report, upstream, weigh)
from pata.context import Spec, strip_work_log
from pata.example import VALUES, procurement

SMALL = '''---
title: t
---

# One

<!--canvas goal id=g-->
ship it
<!--/canvas-->

```canvas code id=a
x = 1
```

## Two

```canvas code id=b
y = x + 1
```

```canvas code id=c context=discard
z = 99
```

```canvas ask id=q scope=page budget=100000
pin a
what now?
```
'''

def small(): return Doc.parse(SMALL)

def test_the_file_round_trips_and_a_quoted_canvas_stays_prose():
    d = Doc.parse(SMALL + '''
Here is how you write one:

````markdown
```canvas code id=fake
not a brick
```
````
''')
    assert 'fake' not in {b.id for b in d}
    again = Doc.parse(d.md())
    assert again.md() == d.md()                        # prose carries no id, so compare the file
    assert [b.kind for b in again] == [b.kind for b in d]
    assert again['q'].pins == ['a'] and again['q'].scope == 'page' and again['q'].budget == 100000

def test_headings_are_the_regions_and_carry_no_weight_of_their_own():
    d = small()
    assert d['b'].region == 'Two' and d['g'].region == 'One'
    assert [b.id for b in d.in_region('Two')] == ['b', 'c', 'q'] or 'b' in [x.id for x in d.in_region('Two')]
    head = next(b for b in d if b.heading)
    assert body_text(head) == ''                       # the region label already says it

def test_upstream_is_read_off_the_code_not_drawn_by_hand():
    d = procurement()
    up = [b.id for b in upstream(d.bricks, 'c-share')]
    assert up == ['c-load', 'c-band']                  # bands and pos, and nothing else
    risk = [b.id for b in upstream(d.bricks, 'q-risk')]
    assert {'c-rule', 'c-backtest'} <= set(risk)       # the names the question put in backticks
    assert 's-audit' in risk                           # and the relation it declared
    assert 'k1' not in risk                            # tasks are not upstream of anything

def test_a_question_anchors_on_the_brick_above_it():
    d = procurement()
    assert 'c-cycle' in [b.id for b in upstream(d.bricks, 'q-fix')]

def test_scopes_choose_different_bricks():
    d = procurement()
    at = lambda s: {i.ref for i in resolve(d, 'q-risk', Spec(scope=s, goal=False))}
    assert at('none') == set()
    assert at('page') < at('doc')
    assert 'q-rec' in at('doc') and 'q-rec' not in at('page')     # only `doc` reads forwards
    assert at('region') and 'k1' not in at('region')
    assert 'c-backtest' in at('upstream') and 'k1' not in at('upstream')

def test_the_goal_and_pins_survive_a_budget_that_drops_everything_else():
    d = small()
    d['b'].body = 'y = x + ' + '1' * 400
    got = resolve(d, 'q', Spec(scope='page', pins=['a'], budget=400))
    kept = [i.ref for i in got]
    assert kept[0] == 'g' and 'a' in kept and 'c' not in kept    # `discard` goes first
    assert weigh(got)['chars'] <= 400

def test_a_pin_larger_than_the_whole_budget_is_clipped_not_dropped():
    d = small()
    d['a'].body = 'x = "' + 'q' * 5000 + '"'
    got = resolve(d, 'q', Spec(scope='none', pins=['a'], budget=1000, goal=False))
    assert [i.ref for i in got] == ['a'] and got[0].clipped and got[0].chars < 5000

def test_a_pin_that_no_longer_resolves_is_visible_rather_than_silent():
    d = small()
    assert weigh(resolve(d, 'q', Spec(scope='none', pins=['gone'], goal=False)))['missing'] == ['gone']
    d.remove('a')
    assert d['q'].pins == [] and weigh(resolve(d, 'q'))['missing'] == []

def test_render_keeps_the_shape_ramabana_sheds_when_a_prompt_overflows():
    "`compact_notebook_context` matches `<cell ... compact=\"auto|keep|discard\">`; anything else is unshedable."
    out = render(resolve(small(), 'q'))
    assert '<cell id="g" type="goal" compact="keep"' in out
    assert 'compact="auto"' in out and 'region="Two"' in out and '<block ' not in out

def test_an_answer_is_fed_forward_without_its_work_log():
    d = procurement()
    r = d.reply_to('q-synth')
    r.body += '\n\n<details><summary>what i did</summary>\ntool spam\n</details>'
    assert strip_work_log(r.body).endswith('clears the target.')
    out = render(resolve(d, 'q-rec', values=VALUES))
    assert 'clears the target' in out and 'tool spam' not in out

def test_a_code_bricks_value_comes_from_the_namespace_not_the_file():
    d = procurement()
    assert '<output>' not in d.md()
    assert '0.79' in body_text(d['c-backtest'], VALUES)

def test_code_runs_in_dependency_order_not_document_order():
    d = Doc.parse('```canvas code id=b\ny = x\n```\n\n```canvas code id=a\nx = 1\n```\n')
    assert [b.id for b in order(d.bricks)] == ['a', 'b']

def test_a_document_round_trips_through_a_notebook_with_its_answers_intact():
    d = procurement()
    back = from_ipynb(to_ipynb(d, VALUES))
    assert back['q-rec'].pins == d['q-rec'].pins and back['q-rec'].scope == 'doc'
    assert 'Auto-approve indirect' in back.reply_to('q-rec').body
    assert back['c-band'].body == d['c-band'].body

def test_a_layout_stays_out_of_the_file_until_someone_moves_a_brick():
    d = procurement(placed=False)
    before = d.md()
    arrange(d)
    assert d.md() == before and d['goal'].xy                 # placed for the view, not for the file
    d['goal'].place(10, 20, keep=True)
    assert 'prop x = 10' in d.md() and Doc.parse(d.md())['goal'].xy == (10.0, 20.0)

def test_an_imported_notebook_arrives_with_a_second_view():
    nb = {'cells': [{'cell_type': 'code', 'source': 'x = 1', 'id': 'c1'},
                    {'cell_type': 'markdown', 'source': '# notes', 'id': 'm1'}], 'nbformat': 4}
    d = arrange(from_ipynb(nb))
    assert d['c1'].xy and d['c1'].xy != (None, None)

def test_export_writes_the_marked_bricks_in_dependency_order():
    d = procurement()
    assert set(modules(d)) == {'procure/core.py'}
    src = modules(d)['procure/core.py']
    assert src.index('def bands') < src.index('def triage')
    d['c-rule'].body = d['c-rule'].body.replace('#|export', '#|export procure.rules')
    assert set(modules(d)) == {'procure/core.py', 'procure/rules.py'}

def test_a_report_leaves_the_canvas_behind():
    out = to_report(procurement())
    assert '```canvas' not in out and '<!--canvas' not in out
    assert '- [ ] Ship the triage rule' in out and '**measure**' in out

def test_a_copy_is_not_wired_back_into_the_original():
    d = procurement()
    made = d.copy(['s-audit', 'q-risk'])
    new = {b.id for b in made}
    assert not new & {'s-audit', 'q-risk'}
    copy = next(b for b in made if b.kind == 'ask')
    assert set(copy.pins) < new and set(copy.links['supports']) < new

def test_a_duplicate_id_is_refused():
    with pytest.raises(ValueError): small().add(Brick('text', 'x', id='a'))
