import pytest
from fastcore.all import Path, first

from leela.blocks.canvas.change import (bundle_of, bundles, coverage, diff_stat, hunks,
                                        place_diff, pr, review, snip, state, value)
from leela.blocks.canvas.context import (Spec, body_text, render, resolve, strip_work_log, weigh)
from leela.blocks.canvas.doc import Brick, Canvas, order, upstream
from leela.blocks.canvas.example import VALUES, diff, procurement
from leela.blocks.canvas.explain import capture, drafted, explain, prompt_for, replay
from leela.blocks.canvas.export import from_ipynb, modules, to_ipynb, to_report
from leela.blocks.canvas.layout import arrange
from leela.blocks.canvas.bricks import (libraries, locate, mount, palette, split_src,
                                        wire)
from leela.blocks.canvas.lit import html_of

PKG = Path(__file__).parent.parent/'leela/blocks'

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

def small(): return Canvas.parse(SMALL)

def test_the_file_round_trips_and_a_quoted_canvas_stays_prose():
    d = Canvas.parse(SMALL + '''
Here is how you write one:

````markdown
```canvas code id=fake
not a brick
```
````
''')
    assert 'fake' not in {b.id for b in d}
    again = Canvas.parse(d.md())
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
    d = Canvas.parse('```canvas code id=b\ny = x\n```\n\n```canvas code id=a\nx = 1\n```\n')
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
    assert 'prop x = 10' in d.md() and Canvas.parse(d.md())['goal'].xy == (10.0, 20.0)

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
    assert r['branch'] == 'canvas/triage' and r['paths'] == ['procure/core.py', 'tests/test_triage.py']
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

def test_two_changed_files_with_one_basename_get_one_brick_id_each():
    "A branch touches several `__init__.py`, and `Canvas.add` rejects a duplicate id."
    d = procurement()
    two = ('diff --git a/procure/__init__.py b/procure/__init__.py\n@@ -1 +1 @@\n-a\n+b\n'
           'diff --git a/tests/__init__.py b/tests/__init__.py\n@@ -1 +1 @@\n-c\n+d\n')
    ids = [b.id for b in review(d, 'triage', two).of('diff')]
    assert len(set(ids)) == 2
    assert ids == ['d-procure-__init__.py', 'd-tests-__init__.py']

def test_a_note_on_a_glob_heads_the_run_it_describes():
    "Fifteen screenshots want one note above them, not the same note repeated fifteen times."
    d = procurement()
    b = first(x for x in bundles(d) if x.id == 'triage')
    d.insert(d.index(b.members[0].id) + 1,
             Brick('note', 'Both of these.', id='n-all', attrs={'path': 'procure/*.py'}))
    two = ('diff --git a/procure/core.py b/procure/core.py\n@@ -1 +1 @@\n-a\n+b\n'
           'diff --git a/procure/erp.py b/procure/erp.py\n@@ -1 +1 @@\n-c\n+d\n')
    ids = [x.id for x in review(d, 'triage', two) if x.kind in ('diff', 'note')]
    assert ids.count('n-all') == 1, 'once, not once per matching file'
    assert ids.index('n-all') < ids.index('d-core.py'), 'and above the run it describes'

def test_a_document_with_no_bundle_still_reports_every_change_as_unclaimed():
    d = Canvas.parse(SMALL)
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
    d = Canvas.parse('# One\n\n<!--canvas goal id=g-->\nship it\n<!--/canvas-->\n')
    v = value(d)
    assert 'Nothing in this document is serving this goal.' in v['g-nothing'].body

def test_a_wrapped_attribute_list_is_one_opening_tag():
    d = Canvas.parse('# One\n\n<!--canvas bundle id=b title="A change"\n     goal=g\n'
                  '     paths=a.py,b.py-->\nprose\n<!--/canvas-->\n')
    b = d['b']
    assert b.kind == 'bundle' and b.title == 'A change' and b.body == 'prose'
    assert b.attrs['goal'] == 'g' and b.attrs['paths'] == 'a.py,b.py'
    assert Canvas.parse(d.md())['b'].attrs == b.attrs      # and it writes back on one line

def test_prose_splits_at_every_heading_so_one_heading_is_one_region():
    d = Canvas.parse('# A\n\nfirst\n\n# B\n\nsecond\n\n```canvas code id=c\nx = 1\n```\n')
    assert list(d.regions) == ['A', 'B']
    assert d['c'].region == 'B'

def test_a_heading_inside_a_plain_fence_is_an_example_not_a_region():
    d = Canvas.parse('# A\n\n```\n# B\nnot a heading\n```\n\nafter\n')
    assert list(d.regions) == ['A']

def test_a_snippet_cites_a_symbol_out_of_the_file_it_names():
    b = Brick('snippet', 'why', attrs={'path': 'canvas/change.py', 'symbol': 'state'})
    code = snip(b, PKG)
    assert code.startswith('def state(') and 'return \'todo\'' in code
    assert '# paths a diff says moved' in code                   # docments come with it
    m = Brick('snippet', '', attrs={'path': 'canvas/change.py', 'symbol': 'Bundle.paths'})
    assert snip(m, PKG).splitlines()[0].strip() == '@property'   # decorators come with it
    assert snip(Brick('snippet', '', attrs={'path': 'nope.py'}), PKG) == ''

def test_a_literate_page_keeps_the_prose_under_each_heading():
    d = Canvas.parse('# A\n\n| f | n |\n|---|---|\n| x | 1 |\n\n# B\n\nafter\n')
    page = html_of(d)
    assert '<h2 id="a">A</h2>' in page and '<table>' in page and 'after' in page

def test_the_literate_page_folds_what_a_phone_cannot_hold():
    d = procurement()
    r = review(d, 'triage', diff())
    page = html_of(r, changed=list(hunks(diff())))
    assert page.count('<details') >= 1 and 'viewport' not in page   # the wrapper adds the meta tag
    assert 'class="dl a"' in page and 'class="dl r"' in page

def test_one_minified_line_cannot_be_the_whole_page():
    "A generated page diffs to few lines and megabytes, so the row cap alone did not hold."
    from leela.blocks.canvas.lit import DIFF_COLS
    d = Canvas.parse(SMALL)
    wide = DIFF_COLS * 3
    d.add(Brick('diff', f'@@ -1 +1 @@\n+{"x" * wide}', id='d1', attrs={'path': 'media/page.html'}))
    page = html_of(d)
    assert 'x' * (DIFF_COLS - 1) in page and 'x' * DIFF_COLS not in page   # the `+` costs one
    assert f'+{wide + 1 - DIFF_COLS} chars' in page

def test_a_snippet_cites_a_name_in_a_file_python_cannot_parse(tmp_path):
    "A snippet on `cvUrl` in a `.js` file rendered as a caption over an empty box."
    js = tmp_path/'md.js'
    js.write_text('const CV = 1;\nfunction cvUrl(u) {\n  if (!u) return "";\n  return u;\n}\n'
                  'function other() { return 2; }\n')
    b = Brick('snippet', '', id='s1', attrs={'path': 'md.js', 'symbol': 'cvUrl', 'lang': 'js'})
    got = snip(b, root=tmp_path)
    assert got.startswith('function cvUrl') and 'return u;' in got
    assert 'function other' not in got, 'the block ends where the indent returns'

def test_a_citation_nobody_can_resolve_says_so(tmp_path):
    "An empty snippet is a caption over nothing, which reads as a rendering bug."
    (tmp_path/'a.py').write_text('def real(): pass\n')
    d = Canvas.parse(SMALL)
    d.add(Brick('snippet', 'The prose survives.', id='s1',
                attrs={'path': 'a.py', 'symbol': 'absent'}))
    page = html_of(d, root=tmp_path)
    assert 'Nothing at that citation.' in page and 'The prose survives.' in page

def test_a_generated_artifact_diffs_to_a_count_not_to_every_line():
    "One committed HTML page took a branch review to 3MB of lines nobody reads."
    from leela.blocks.canvas.lit import DIFF_CAP
    n = DIFF_CAP + 50
    body = '\n'.join(['@@ -1 +1 @@'] + [f'+line {i}' for i in range(n)])
    d = Canvas.parse(SMALL)
    d.add(Brick('diff', body, id='d1', attrs={'path': 'media/page.html'}))
    page = html_of(d)
    assert 'line 0' in page and f'line {n - 1}' not in page
    assert f'{n + 1 - DIFF_CAP} more lines, not shown' in page

def test_an_attached_reference_renders_instead_of_leaving_a_bare_heading():
    "`review` writes an Attached heading, and every `source` under it rendered to nothing."
    d = Canvas.parse(SMALL)
    d.add(Brick('source', '', id='r1', attrs={'title': 'the pool', 'path': 'kunda/pool.py'}))
    d.add(Brick('source', '', id='r2', attrs={'title': 'doc:docs/a.md', 'path': 'docs/a.md'}))
    page = html_of(d)
    assert '<b>the pool</b>' in page and 'kunda/pool.py' in page
    assert page.count('docs/a.md') == 1                        # the title already ends in the path

def test_a_repeated_heading_gets_its_own_anchor():
    "Eight reviews on one page each have a Change, and every nav link went to the first."
    d = Canvas.parse('# Change\n\none\n\n# Change\n\ntwo\n\n# Change\n\nthree\n')
    page = html_of(d)
    assert 'id="change"' in page and 'id="change-2"' in page and 'id="change-3"' in page
    assert page.count('href="#change"') == 1                   # the nav no longer aims all three here

def test_the_prompt_carries_the_rules_the_goal_the_section_and_the_code():
    d = procurement()
    d.add(Brick('snippet', '', id='s1', attrs={'path': 'canvas/change.py', 'symbol': 'state'}))
    p = prompt_for(d, 's1', root=PKG, rules='RULEBOOK')
    assert 'RULEBOOK' in p and 'ASD-STE100' in p
    assert 'Increase procurement productivity' in p          # the goal
    assert 'def state(' in p and 'symbol="state"' in p       # the code, and where it came from
    assert '<cell id=' in p                                  # the section, through `resolve`

def test_no_writing_rule_is_copied_into_this_package():
    "The rules are a ramabana pyskill. A prompt that pasted one would be that copy."
    from leela.blocks.canvas import explain as E
    body = ' '.join((PKG/'canvas'/f).read_text() for f in ('explain.py', 'explain.md', 'ste.md'))
    assert 'Kill on sight' not in body and 'Banned words' not in body
    assert 'write_docs' in E.RULES and 'write_docs' in E.rule_text()

def test_drafting_writes_into_the_document_and_marks_what_it_wrote():
    d = procurement()
    d.add(Brick('snippet', '', id='s1', attrs={'path': 'canvas/change.py', 'symbol': 'state'}))
    d.add(Brick('snippet', 'a person wrote this', id='s2',
                attrs={'path': 'canvas/change.py', 'symbol': 'coverage'}))
    said = []
    ask = lambda prompt, brick: said.append(brick.id) or f'Two sentences about {brick.id}.'
    got = explain(d, ask, root=PKG, rules='RULEBOOK')
    assert said == ['s1'] and [b.id for b in got] == ['s1']   # a written body is left alone
    assert d['s1'].body == 'Two sentences about s1.' and d['s1'].attrs['wrote'] == 'ai'
    assert [b.id for b in drafted(d)] == ['s1']
    assert Canvas.parse(d.md())['s1'].attrs['wrote'] == 'ai'     # and it survives the file
    assert explain(d, ask, root=PKG, rules='R', overwrite=True).attrgot('id') == ['s1', 's2']

def test_capture_and_replay_stand_in_for_a_model_that_is_not_here(tmp_path):
    d = procurement()
    d.add(Brick('snippet', '', id='s1', attrs={'path': 'canvas/change.py', 'symbol': 'state'}))
    box = tmp_path/'prompts.json'
    assert explain(d, capture(box), root=PKG, rules='R') == []       # nothing answered
    import json
    assert list(json.loads(box.read_text())) == ['s1']
    box.write_text(json.dumps({'s1': 'One sentence.'}))
    assert explain(d, replay(box), root=PKG, rules='R').attrgot('id') == ['s1']
    assert d['s1'].body == 'One sentence.'

def test_a_document_serialises_for_the_browser():
    "Three routes hand `Canvas.dict()` to the browser. Running them found it missing."
    d = arrange(procurement())
    got = d.dict()
    assert got['title'] and got['path'] and len(got['bricks']) == len(d)
    assert [r['title'] for r in got['regions']] == list(d.regions)
    one = first(b for b in got['bricks'] if b['id'] == 'c-share')
    assert one['defs'] == ['tail', 'rest', 'share', 'chain'] and 'bands' in one['reads']
    assert one['x'] is not None and one['region'] == 'Baseline the tail'
    import json
    assert json.loads(json.dumps(got))['bricks'][0]['kind']      # and it is JSON

def test_a_placed_brick_reports_two_coordinates_however_it_was_placed():
    "`place` keeps a width beside them, and unpacking `xy` into two names must not depend on that."
    b = Brick('text', 'x')
    assert b.xy is None
    assert len(b.place(10, 20, 300).xy) == 2 and b.width == 300
    assert len(b.place(30, 40, 300, keep=True).xy) == 2


# === where a component comes from ===

BRICK_FIXTURE = str(Path(__file__).parent/'fixtures')

def demo_libs(name='demobricks'):
    """Only the fixture library, whatever else this install has."""
    import sys
    if BRICK_FIXTURE not in sys.path: sys.path.insert(0, BRICK_FIXTURE)
    return libraries(extra=(name,)).filter(lambda l: l.name == name)

def test_a_src_keeps_the_library_that_wrote_it():
    "`Brick.src` is `lego.bricks:viz.series`. Dropping the prefix makes two libraries collide."
    assert split_src('lego.bricks:viz.series') == ('lego.bricks', 'viz.series')
    assert split_src('viz.series') == ('', 'viz.series')
    assert split_src('') == ('', '')

def test_a_library_is_any_module_with_a_manifest():
    libs = demo_libs()
    assert [l.name for l in libs] == ['demobricks']
    p = palette(libs)
    assert [b['src'] for b in p['bricks']] == ['demobricks:viz.series']
    assert p['bricks'][0]['library'] == 'demobricks' and p['groups'] == {'viz': 'Plain figures'}
    assert [q['name'] for q in p['bricks'][0]['ports']] == ['labels', 'series']

def test_nothing_installed_is_an_empty_palette_and_not_an_error():
    p = palette([])
    assert p == {'bricks': [], 'groups': {}, 'libraries': [], 'notes': []}

def test_a_prefixed_src_is_answered_by_that_library_only():
    libs = demo_libs()
    lib, b = locate('demobricks:viz.series', libs)
    assert lib.name == 'demobricks' and b['title'] == 'Series'
    assert locate('lego.bricks:viz.series', libs) == (None, None)   # a library that is not here
    assert locate('demobricks:nope', libs) == (None, None)
    assert locate('viz.series', libs)[0].name == 'demobricks'       # bare, so first match wins

def test_the_wiring_comes_from_the_package_that_owns_the_brick():
    libs = demo_libs()
    got = wire('demobricks:viz.series', libs, base='http://host')
    assert got['ok'] and got['binds'] == {'labels': 'labels', 'series': 'series'}
    assert got['emits'] == ['point'] and got['height'] == 240
    assert 'series = [{"name": "s"' in got['wire']
    assert '/bricks/data/viz.series' in got['remote']                # the not-installed fallback
    assert wire('demobricks:nope', libs)['ok'] is False

def test_a_library_mounts_its_own_routes_on_leelas_app():
    "`serve.connect(app, page)` imports nothing about the app, which is why there is no second process."
    from fasthtml.common import FastHTML
    app = FastHTML()
    assert mount(app, demo_libs()) == []                             # no notes means it mounted
    paths = {r.path for r in app.routes}
    assert '/bricks/manifest.json' in paths and '/bricks/wire/{name}' in paths

def test_a_host_answers_the_same_four_questions_as_a_library():
    "The HTTP path stays for a library that is not installed. It is opt-in, never a silent default."
    import os
    from leela.blocks.canvas.bricks import HOST_ENV, Host
    assert not os.getenv(HOST_ENV), 'a default host is what made the palette come back empty'
    h = Host('h', 'http://h')
    assert h.mount(None).startswith('h: served by')
    assert all(hasattr(h, m) for m in ('manifest', 'find', 'wire', 'fill'))

def test_a_library_that_is_present_but_will_not_import_says_why():
    """A silent skip hides a broken install."""
    import sys
    if BRICK_FIXTURE not in sys.path: sys.path.insert(0, BRICK_FIXTURE)
    p = palette(libraries(extra=('brokenbricks',)))
    assert any('brokenbricks' in n and 'ujson_that_is_not_installed' in n for n in p['notes'])

def test_a_library_absent_from_this_install_is_not_a_note():
    "`KNOWN` names a library that may not be here. Absent is normal; broken is not."
    from leela.blocks.canvas.bricks import KNOWN
    assert 'lego.bricks' in KNOWN
    assert palette(libraries())['notes'] == []      # absent, so nothing to say

SLOTDOC = """---
title: slots
---
# A change

<!--canvas bundle id=u1 goal=g1 paths=a.py-->
The change.
<!--/canvas-->

```canvas diff id=d1 paths=a.py,b.py left=HEAD~1 right=HEAD
```
"""

RAW = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,2 +1,3 @@
 keep
-gone
+new
+more
diff --git a/b.py b/b.py
--- a/b.py
+++ b/b.py
@@ -1 +1 @@
-old
+fresh
"""

def test_an_empty_diff_brick_asks_for_a_diff_and_gets_one_brick_a_file():
    "The document declares the diff it wants. Leela reads the attributes and fills the slot."
    doc, seen = Canvas.parse(SLOTDOC), []
    place_diff(doc, lambda paths, left, right: seen.append((paths, left, right)) or RAW)
    assert seen == [(['a.py', 'b.py'], 'HEAD~1', 'HEAD')]
    got = doc.of('diff')
    assert [b.id for b in got] == ['d1-a.py', 'd1-b.py']
    assert [b.attrs['path'] for b in got] == ['a.py', 'b.py']
    assert (got[0].attrs['added'], got[0].attrs['removed']) == ('2', '1')

def test_a_filled_diff_no_bundle_claims_says_so_on_the_brick():
    "`claimed=no` is what the page turns into a warning chip. The bundle claims `a.py`, not `b.py`."
    doc = Canvas.parse(SLOTDOC)
    place_diff(doc, lambda paths, left, right: RAW)
    by = {b.attrs['path']: b for b in doc.of('diff')}
    assert 'claimed' not in by['a.py'].attrs
    assert by['b.py'].attrs['claimed'] == 'no'

def test_two_changed_files_with_one_basename_get_ids_of_their_own():
    "The basename alone collided, so `by_id` resolved both hunks to whichever came first."
    doc = Canvas.parse(SLOTDOC.replace("paths=a.py,b.py", "paths=x/app.py,y/app.py"))
    raw = ('diff --git a/x/app.py b/x/app.py\n@@ -1 +1 @@\n-a\n+b\n'
           'diff --git a/y/app.py b/y/app.py\n@@ -1 +1 @@\n-c\n+d\n')
    place_diff(doc, lambda paths, left, right: raw)
    got = doc.of('diff')
    ids = [b.id for b in got]
    assert len(set(ids)) == len(ids), ids
    assert [doc.by_id(i).attrs['path'] for i in ids] == ['x/app.py', 'y/app.py']

def test_a_diff_brick_with_a_body_is_left_alone():
    "Only an empty brick is a slot. A pasted diff is content, and is never overwritten."
    doc = Canvas.parse(SLOTDOC.replace('left=HEAD~1 right=HEAD\n```', 'left=x\n' + RAW + '```'))
    place_diff(doc, lambda *a: pytest.fail('asked for a diff it already had'))
    assert len(doc.of('diff')) == 1

def test_leela_builds_the_literate_page_end_to_end(tmp_path):
    "`page` is the whole assembly: fill the slots, count the files, write the HTML."
    import subprocess
    from leela.blocks.canvas.app import page
    if subprocess.run(['git', 'rev-parse', '--verify', 'origin/main'], cwd=PKG.parent.parent,
                      capture_output=True).returncode: pytest.skip('no origin/main to diff against')
    doc = Canvas.load(PKG.parent.parent/'docs/change.canvas.md')
    out = tmp_path/'page.html'
    r = page(doc, out, 'origin/main')
    assert r['diffs'] and out.exists()
    body = out.read_text()
    assert '<div class="diff">' in body or '<details>' in body
    assert 'literate diff' in body

GLOBDOC = """---
title: globs
---
# A change

<!--canvas bundle id=u1 goal=g1 paths=pkg/*.py,docs/a.md-->
Claims a folder by glob, not by name.
<!--/canvas-->

<!--canvas task id=t1 status=done-->
Done.
<!--/canvas-->
"""

def test_a_change_that_claims_a_glob_reads_done_when_the_glob_matched():
    "`hit` holds file names and `paths` holds patterns, so comparing the two never agreed."
    doc = Canvas.parse(GLOBDOC)
    b = first(bundles(doc))
    assert state(b, ['pkg/one.py', 'pkg/two.py', 'docs/a.md']) == 'done'
    assert state(b, ['pkg/one.py']) == 'doing'      # docs/a.md is claimed and did not move
