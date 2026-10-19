import pytest
from fastcore.all import Path, first

from leela.blocks.canvas.change import bundles, diff_stat, hunks, review, snip, state
from leela.blocks.canvas.context import Spec, render, resolve, weigh
from leela.blocks.canvas.doc import Brick, Canvas, upstream
from leela.blocks.canvas.example import VALUES, diff, procurement
from leela.blocks.canvas.export import from_ipynb, modules, to_ipynb
from leela.blocks.canvas.bricks import libraries, locate, palette, split_src
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


def test_upstream_is_read_off_the_code_not_drawn_by_hand():
    d = procurement()
    up = [b.id for b in upstream(d.bricks, 'c-share')]
    assert up == ['c-load', 'c-band']                  # bands and pos, and nothing else
    risk = [b.id for b in upstream(d.bricks, 'q-risk')]
    assert {'c-rule', 'c-backtest'} <= set(risk)       # the names the question put in backticks
    assert 's-audit' in risk                           # and the relation it declared
    assert 'k1' not in risk                            # tasks are not upstream of anything


def test_the_goal_and_pins_survive_a_budget_that_drops_everything_else():
    d = small()
    d['b'].body = 'y = x + ' + '1' * 400
    got = resolve(d, 'q', Spec(scope='page', pins=['a'], budget=400))
    kept = [i.ref for i in got]
    assert kept[0] == 'g' and 'a' in kept and 'c' not in kept    # `discard` goes first
    assert weigh(got)['chars'] <= 400


def test_render_keeps_the_shape_ramabana_sheds_when_a_prompt_overflows():
    "`compact_notebook_context` matches `<cell ... compact=\"auto|keep|discard\">`; anything else is unshedable."
    out = render(resolve(small(), 'q'))
    assert '<cell id="g" type="goal" compact="keep"' in out
    assert 'compact="auto"' in out and 'region="Two"' in out and '<block ' not in out


def test_a_document_round_trips_through_a_notebook_with_its_answers_intact():
    d = procurement()
    back = from_ipynb(to_ipynb(d, VALUES))
    assert back['q-rec'].pins == d['q-rec'].pins and back['q-rec'].scope == 'doc'
    assert 'Auto-approve indirect' in back.reply_to('q-rec').body
    assert back['c-band'].body == d['c-band'].body


def test_export_writes_the_marked_bricks_in_dependency_order():
    d = procurement()
    assert set(modules(d)) == {'procure/core.py'}
    src = modules(d)['procure/core.py']
    assert src.index('def bands') < src.index('def triage')
    d['c-rule'].body = d['c-rule'].body.replace('#|export', '#|export procure.rules')
    assert set(modules(d)) == {'procure/core.py', 'procure/rules.py'}


def test_a_diff_parses_per_file_and_the_stat_ignores_the_headers():
    files = hunks(diff())
    assert list(files) == ['procure/core.py', 'tests/test_triage.py', 'procure/erp.py']
    assert diff_stat(files['procure/erp.py']) == (1, 1)
    assert diff_stat(files['tests/test_triage.py'])[1] == 0    # `--- /dev/null` is not a removal


def test_two_changed_files_with_one_basename_get_one_brick_id_each():
    "A branch touches several `__init__.py`, and `Canvas.add` rejects a duplicate id."
    d = procurement()
    two = ('diff --git a/procure/__init__.py b/procure/__init__.py\n@@ -1 +1 @@\n-a\n+b\n'
           'diff --git a/tests/__init__.py b/tests/__init__.py\n@@ -1 +1 @@\n-c\n+d\n')
    ids = [b.id for b in review(d, 'triage', two).of('diff')]
    assert len(set(ids)) == 2
    assert ids == ['d-procure-__init__.py', 'd-tests-__init__.py']


def test_state_is_read_off_the_document_not_set_by_hand():
    d, ch = procurement(), list(hunks(diff()))
    got = {b.id: state(b, ch) for b in bundles(d)}
    assert got == {'triage': 'done', 'cap': 'blocked', 'dash': 'doing'}
    tri = first(b for b in bundles(d) if b.id == 'triage')
    assert state(tri) == 'done'                 # no diff is no evidence about files, not evidence against
    assert state(tri, ['procure/core.py']) == 'doing'        # one of the two claimed files moved


def test_a_wrapped_attribute_list_is_one_opening_tag():
    d = Canvas.parse('# One\n\n<!--canvas bundle id=b title="A change"\n     goal=g\n'
                  '     paths=a.py,b.py-->\nprose\n<!--/canvas-->\n')
    b = d['b']
    assert b.kind == 'bundle' and b.title == 'A change' and b.body == 'prose'
    assert b.attrs['goal'] == 'g' and b.attrs['paths'] == 'a.py,b.py'
    assert Canvas.parse(d.md())['b'].attrs == b.attrs      # and it writes back on one line


def test_a_heading_inside_a_plain_fence_is_an_example_not_a_region():
    d = Canvas.parse('# A\n\n```\n# B\nnot a heading\n```\n\nafter\n')
    assert list(d.regions) == ['A']


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


# === where a component comes from ===

BRICK_FIXTURE = str(Path(__file__).parent/'fixtures')


def test_a_library_that_is_present_but_will_not_import_says_why():
    """A silent skip hides a broken install."""
    import sys
    if BRICK_FIXTURE not in sys.path: sys.path.insert(0, BRICK_FIXTURE)
    p = palette(libraries(extra=('brokenbricks',)))
    assert any('brokenbricks' in n and 'ujson_that_is_not_installed' in n for n in p['notes'])


PROSE = ('leela/skills/canvas.py', 'docs/canvas.md', 'docs/bricks.md', 'docs/branch.canvas.md',
         'extensions/bricks/README.md')
ROOT = Path(__file__).parent.parent

def _written_srcs():
    "Every `src=LIB:name` Leela's own prose tells a reader to write."
    import re
    return {m for f in PROSE for m in re.findall(r'src=([\w.]+:[\w.]+)', (ROOT/f).read_text())}

def test_every_src_the_docs_teach_names_a_library_that_exists():
    """The rename to `leela_bricks` missed the skill, both docs and two test files, so an agent
    following the skill wrote `src=lego.bricks:viz.series` and the resolver answered nothing.
    `sales_bricks` is the library `docs/bricks.md` teaches you to write, and is the only name
    here that may be absent."""
    libs, unresolved = libraries(), set()
    for src in _written_srcs():
        if locate(src, libs)[0] is None: unresolved.add(split_src(src)[0])
    assert unresolved == {'sales_bricks'}, 'a name nobody ships; is `extensions/bricks` installed?'


def test_no_brick_ships_wiring_that_imports_a_package_the_library_lacks():
    """Four bricks carried wiring importing `lego`, which is not a dependency and not on PyPI, so
    `data.fill` raised for everyone. `needs` is what says a wire wants something."""
    import leela_bricks
    from leela_bricks.data import fill
    for name, b in leela_bricks.REG.bricks.items():
        assert b.needs == [], f'{name} wants {b.needs}, which `leela-bricks` does not depend on'
        assert '_error' not in (fill(name) or {}), f'{name} cannot fill its own ports'


def test_leela_builds_the_literate_page_end_to_end(tmp_path):
    "`page` is the whole assembly: fill the slots, count the files, write the HTML."
    import subprocess
    from leela.blocks.canvas.app import page
    got = subprocess.run(['git', 'rev-list', '--max-parents=0', 'HEAD'], cwd=PKG.parent.parent, capture_output=True, text=True)
    if got.returncode: pytest.skip('not a git checkout')
    shallow = subprocess.run(['git', 'rev-parse', '--is-shallow-repository'], cwd=PKG.parent.parent, capture_output=True, text=True)
    assert shallow.stdout.strip() != 'true', 'a shallow clone has no first commit to diff from; check out with `fetch-depth: 0`'
    # The first commit, not origin/main: on main itself the document's diff is empty and leaves no brick.
    base = got.stdout.split()[0]
    doc = Canvas.load(PKG.parent.parent/'docs/change.canvas.md')
    for b in doc.of('diff'): b.attrs['left'] = base
    out = tmp_path/'page.html'
    r = page(doc, out, base)
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
