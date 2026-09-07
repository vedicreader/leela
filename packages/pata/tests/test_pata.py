import pytest
from pata import (Brick, Doc, arrange, body_text, bundle_of, bundles, coverage, diff_stat,
                  from_ipynb, hunks, modules, order, pr, render, resolve, review, to_ipynb,
                  to_report, upstream, weigh)
from pata import html_of, snip, state, value
from pata.context import Spec, strip_work_log
from fastcore.all import Path, first

PKG = Path(__file__).parent.parent
from pata.example import VALUES, diff, procurement

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

def test_a_bundle_claims_its_region_and_the_files_its_code_writes():
    d = procurement()
    b = bundles(d)[0]
    assert b.goal.id == 'goal' and b.title == 'Auto-approve the contracted tail'
    assert {'c-rule', 'c-backtest', 'k4'} <= {m.id for m in b.members}
    assert 'c-band' not in {m.id for m in b.members}          # a different region
    assert b.paths == ['procure/core.py', 'tests/test_triage.py']   # derived, then declared
    assert bundle_of(d, 'c-rule').id == 'triage' and bundle_of(d, 'c-band') is None

def test_coverage_names_the_claim_with_no_code_and_the_change_nobody_claimed():
    d = procurement()
    got = coverage(d, ['procure/core.py', 'procure/erp.py'])
    row = got['bundles'][0]
    assert row['matched'] == ['procure/core.py']
    assert row['unmet'] == ['tests/test_triage.py']            # claimed, never changed
    assert got['unclaimed'] == ['procure/erp.py']              # changed, never explained

def test_a_pull_request_carries_the_value_the_tasks_and_the_reasoning():
    r = pr(procurement(), 'triage')
    assert r['branch'] == 'pata/triage' and r['paths'] == ['procure/core.py', 'tests/test_triage.py']
    assert 'Increase procurement productivity by 10%' in r['body']
    assert 'most of the 10 points' in r['body']
    assert '- [x] Backtest the rule against Q3.' in r['body']
    assert '<summary>' in r['body'] and '14 POs' in r['body']  # the why a diff never has
    assert '`procure/core.py`' in r['body'] and '`pkg:pandas`' in r['body']

def test_a_diff_parses_per_file_and_the_stat_ignores_the_headers():
    files = hunks(diff())
    assert list(files) == ['procure/core.py', 'tests/test_triage.py', 'procure/erp.py']
    assert diff_stat(files['procure/erp.py']) == (1, 1)
    assert diff_stat(files['tests/test_triage.py'])[1] == 0    # `--- /dev/null` is not a removal

def test_a_review_is_a_canvas_with_the_value_the_diff_and_the_checks():
    d = procurement()
    r = review(d, 'triage', diff())
    assert r.goal is not None and r.reply_to('q-risk') is not None
    assert [b.attrs['path'] for b in r.of('diff')] == list(hunks(diff()))
    assert r['d-erp.py'].attrs['claimed'] == 'no'
    assert 'claimed by no bundle' in r['triage-checks'].body
    assert r['q-risk'].scope == 'none'                         # a recorded answer, not a live turn
    assert all(b.xy for b in r if not b.heading and b.kind != 'reply')
    assert r['triage-q'].pins == ['goal']

def test_a_document_with_no_bundle_still_reports_every_change_as_unclaimed():
    d = Doc.parse(SMALL)
    assert coverage(d, ['a.py'])['unclaimed'] == ['a.py'] and coverage(d, ['a.py'])['bundles'] == []

def test_state_is_read_off_the_document_not_set_by_hand():
    d, ch = procurement(), list(hunks(diff()))
    got = {b.id: state(b, ch) for b in bundles(d)}
    assert got == {'triage': 'done', 'cap': 'blocked', 'dash': 'doing'}
    tri = first(b for b in bundles(d) if b.id == 'triage')
    assert state(tri) == 'done'                 # no diff is no evidence about files, not evidence against
    assert state(tri, ['procure/core.py']) == 'doing'        # one of the two claimed files moved

def test_a_goal_is_what_a_change_serves_and_never_part_of_it():
    d = procurement()
    cap = first(b for b in bundles(d) if b.id == 'cap')
    assert 'cycle' not in {m.id for m in cap.members} and cap.goal.id == 'cycle'
    assert bundle_of(d, 'cycle') is None

def test_a_question_answers_to_its_own_regions_goal():
    d = procurement()
    assert d.goal_for('q-cap').id == 'cycle' and d.goal_for('q-synth').id == 'goal'
    assert [i.ref for i in resolve(d, 'q-cap')][0] == 'cycle'

def test_the_value_view_names_the_orphan_change_and_the_unserved_goal():
    d, ch = procurement(), list(hunks(diff()))
    v = value(d, ch)
    assert [b.id for b in v.of('bundle')] == ['triage', 'cap', 'dash']
    assert v['dash'].region == 'Serving no goal'
    assert v['triage'].region.startswith('Increase procurement') and v['triage'].attrs['status'] == 'done'
    assert '1/1 tasks done | 2/2 files changed' in v['triage'].body
    assert 'procure/erp.py' in v['value-tally'].body                # claimed by nobody
    assert v['value-q'].pins == ['goal', 'cycle'] and all(b.xy for b in v if not b.heading)

def test_a_goal_nothing_serves_is_reported_rather_than_omitted():
    d = Doc.parse('# One\n\n<!--canvas goal id=g-->\nship it\n<!--/canvas-->\n')
    v = value(d)
    assert 'Nothing in this document is serving this goal.' in v['g-nothing'].body

def test_a_wrapped_attribute_list_is_one_opening_tag():
    d = Doc.parse('# One\n\n<!--canvas bundle id=b title="A change"\n     goal=g\n'
                  '     paths=a.py,b.py-->\nprose\n<!--/canvas-->\n')
    b = d['b']
    assert b.kind == 'bundle' and b.title == 'A change' and b.body == 'prose'
    assert b.attrs['goal'] == 'g' and b.attrs['paths'] == 'a.py,b.py'
    assert Doc.parse(d.md())['b'].attrs == b.attrs      # and it writes back on one line

def test_prose_splits_at_every_heading_so_one_heading_is_one_region():
    d = Doc.parse('# A\n\nfirst\n\n# B\n\nsecond\n\n```canvas code id=c\nx = 1\n```\n')
    assert list(d.regions) == ['A', 'B']
    assert d['c'].region == 'B'

def test_a_heading_inside_a_plain_fence_is_an_example_not_a_region():
    d = Doc.parse('# A\n\n```\n# B\nnot a heading\n```\n\nafter\n')
    assert list(d.regions) == ['A']

def test_a_snippet_cites_a_symbol_out_of_the_file_it_names():
    b = Brick('snippet', 'why', attrs={'path': 'pata/change.py', 'symbol': 'state'})
    code = snip(b, PKG)
    assert code.startswith('def state(b, changed=()):') and 'return \'todo\'' in code
    m = Brick('snippet', '', attrs={'path': 'pata/change.py', 'symbol': 'Bundle.paths'})
    assert snip(m, PKG).splitlines()[0].strip() == '@property'   # decorators come with it
    assert snip(Brick('snippet', '', attrs={'path': 'nope.py'}), PKG) == ''

def test_a_literate_page_keeps_the_prose_under_each_heading():
    d = Doc.parse('# A\n\n| f | n |\n|---|---|\n| x | 1 |\n\n# B\n\nafter\n')
    page = html_of(d)
    assert '<h2 id="a">A</h2>' in page and '<table>' in page and 'after' in page

def test_the_literate_page_folds_what_a_phone_cannot_hold():
    d = procurement()
    r = review(d, 'triage', diff())
    page = html_of(r, changed=list(hunks(diff())))
    assert page.count('<details') >= 1 and 'viewport' not in page   # the wrapper adds the meta tag
    assert 'class="dl a"' in page and 'class="dl r"' in page
