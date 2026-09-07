---
title: pata - one document for a goal and its changes
---

# What it adds

<!--canvas goal id=g measure="tools you open to review one change against its goal" baseline="4 (tracker, notebook, diff, deck)" target="1 page" by=2026-10-31-->
Give Leela one document that holds a goal, its plan, its research, its code and its questions.
<!--/canvas-->

<!--canvas bundle id=pata title="pata: the document, the basket, and three views" goal=g
     contributes="all of the review step; none of the run step, which the canvas branch owns"
     covers="The file,The basket,The wiring,The change,The value,This page,The numbers,Checks"
     paths=packages/pata/pata/*,packages/pata/*,docs/*.md,media/*
     refs=doc:docs/dynamic-documents.md,file:leela/blocks/nb/nb.py,pkg:mdhtml-->
A notebook decides what the model reads by position. Every cell above the question goes in. This
is correct for a script. It is wrong for a plan, because a plan holds four lines of work at once.

`pata` is one markdown file that holds all of them. A question names what it may read. A boundary
on the canvas is one change. A change names the goal that it serves.
<!--/canvas-->

<!--canvas task id=t1 status=done owner=me-->
Read the document format from the canvas branch.
<!--/canvas-->

<!--canvas task id=t2 status=done owner=me-->
Build the context basket, the bundle, the review and the value view.
<!--/canvas-->

<!--canvas task id=t3 status=done owner=me-->
Write this page from the document, with the code it explains.
<!--/canvas-->

<!--canvas task id=t4 status=todo owner=me-->
Move the four modules into `leela/blocks/canvas/`.
<!--/canvas-->

# The file

A `pata` document is one markdown file. Prose stays prose. Each other part is a brick. A brick is
a fence or a comment wrap.

The reader reads the file line by line. It does not use one pattern on the whole file. This is
necessary. A document about canvases shows fences as examples. A fence inside a longer fence is an
example. It is not a brick.

```canvas snippet id=s-scan path=packages/pata/pata/doc.py symbol=_scan
The `TICKS` branch does the work. It sees a plain fence, puts the fence into the prose, and skips
to the end of it. Nothing inside that fence becomes a brick. This page is such a document, and it
reads correctly.
```

Headings are the regions of the document. Nobody writes a region. The reader gives each brick the
heading above it.

```canvas snippet id=s-regions path=packages/pata/pata/doc.py symbol=Doc._regions
```

# The basket

Each question carries a rule. The rule says what the question may read. `resolve` turns the rule
into the exact list that the turn will send.

The list is the point. `resolve` gives back items, not one string. The same list draws the panel
and builds the prompt. What a person sees is what the model gets.

```canvas snippet id=s-resolve path=packages/pata/pata/context.py symbol=resolve
Four rules, in order. The goal goes in first. Then each pin. A pin that no longer exists becomes a
`missing` item. It is visible. A silent drop is worse, because the person still believes the pin is
there.
```

A scope gives the first set of bricks. `page` is the notebook rule. `region` is the section that
you work in. `upstream` is what the question reads from.

```canvas snippet id=s-members path=packages/pata/pata/context.py symbol=members
```

The budget cuts the list. Two rules must hold. The goal and the pins stay. A pin that is larger
than the whole budget gets shorter; it does not go.

```canvas snippet id=s-fit path=packages/pata/pata/context.py symbol=_fit
The last block is the one that matters. If every item that is left is pinned, the code cuts each
item to a share of the budget and marks it. It never drops a pin.
```

The markup is `<cell>` with a `compact` attribute. This is Leela's own notebook shape, and the
choice is deliberate. Ramabana drops `<cell>` elements when a prompt is too large for the window.
A document that wrote `<block>` would lose that net.

```canvas snippet id=s-render path=packages/pata/pata/context.py symbol=render
```

# The wiring

`upstream` reads the code. It does not read a diagram. A name belongs to the brick that binds it.
A diagram beside the code goes wrong; the code does not.

```canvas snippet id=s-defs path=packages/pata/pata/doc.py symbol=defs_of
`defs_of` finds each name that a cell binds at the top level of its code. It looks inside `if`,
`for`, `try` and `with`. It does not look inside a `def`, because a name in a function belongs to
the function.
```

Three additions reach where the code cannot see.

A question anchors on the brick above it. "Fix that" means that brick and all that it reads.

A name in backticks is a name that the question reads. Write `` `triage` `` and the brick that
defines `triage` goes in.

`supports=`, `refutes=` and `blocks=` state a relation between two bricks. No code states these.

```canvas snippet id=s-upstream path=packages/pata/pata/doc.py symbol=upstream
```

# The change

A region groups bricks to read. A `bundle` brick claims its region as one change. The boundary on
the canvas is then the thing that a reviewer opens.

The files come from the code first. A code brick with `#|export` writes a module. The module path
is therefore known. `paths=` adds only what the bricks do not write.

```canvas snippet id=s-paths path=packages/pata/pata/change.py symbol=Bundle.paths
A list that a person keeps by hand goes out of date. A claim that is out of date is worse than no
claim, because a reviewer trusts it.
```

`coverage` holds the claim against the diff. It reports three things. Two of them are new.

`matched` is a file that the bundle claims and the diff changed. `unmet` is a file that the bundle
claims and the diff did not change. `unclaimed` is a file that the diff changed and no bundle
explains.

```canvas snippet id=s-coverage path=packages/pata/pata/change.py symbol=coverage
No diff tool can find `unclaimed`. Only the document knows what the change had to be.
```

`pr` cuts a pull request from one change. It gives back the title, the branch, the body, the files
and the attachments. It opens nothing. Git belongs to `gheasy`. The forge belongs to `pullup`.

```canvas snippet id=s-pr path=packages/pata/pata/change.py symbol=pr
The `_reasoning` line is the part that a diff never has. Each question inside the change, with the
answer that it got, goes into the body in a fold.
```

# The value

`state` comes from the document. No person sets it. A status that a person must remember is a
status that lies.

```canvas snippet id=s-state path=packages/pata/pata/change.py symbol=state
One case needed care. No diff is no evidence about files. It must not read as evidence against
them. Without this line, a finished change reports `todo`.
```

`value` builds the third document. Each goal gets a region. Each change that names the goal goes
under it.

Two negatives are the reason for the view. A change that serves no goal is work that the plan did
not ask for. A goal that nothing serves looks like a goal that is going well, until the date
arrives.

```canvas snippet id=s-value path=packages/pata/pata/change.py symbol=value
```

# This page

`review` builds a document from a diff. `lit` draws a document as one column for a phone.

A `snippet` brick cites code. It does not hold a copy. `snip` reads the file and finds the symbol
in it. This page cannot show code that the file no longer has.

```canvas snippet id=s-snip path=packages/pata/pata/change.py symbol=snip
```

Each long snippet and each long diff arrives folded. A phone screen holds about 20 lines.

```canvas snippet id=s-diff path=packages/pata/pata/lit.py symbol=_diff
The diff body scrolls sideways inside its own box. The page does not scroll sideways. This is the
one rule that most diff pages get wrong on a phone.
```

`review` now puts the prose next to the file that it explains. A document that explains its files
therefore gives a literate diff without more work.

```canvas snippet id=s-lit path=packages/pata/pata/lit.py symbol=html_of
```

Here is one real diff, from the commit that added the value view. It shows the fold, the counts
and the sideways scroll.

<!--canvas diffhere id=d-slot-->
<!--/canvas-->

# The numbers

| file | lines | holds |
|---|---|---|
| `pata/doc.py` | 435 | the file, the bricks, the dataflow |
| `pata/proto.js` | 321 | the canvas prototype |
| `pata/change.py` | 297 | bundle, coverage, pull request, review, value |
| `tests/test_pata.py` | 254 | 30 tests |
| `pata/context.py` | 197 | the basket |
| `pata/procurement.canvas.md` | 190 | the worked document |
| `pata/lit.py` | 183 | this page |
| `pata/proto.css` | 148 | the canvas style |
| `pata/export.py` | 133 | notebook, report, modules |
| `pata/lit.css` | 104 | this page's style |
| `pata/paint.py` | 91 | the prototype payload |
| `pata/layout.py` | 65 | where a brick sits |
| other | 71 | exports, the example, the build file |

Every file is new. There is no earlier version of most of them to compare against. This is why
the page shows snippets and not one large diff.

# Checks

30 tests pass. Each test states one rule.

Five faults came out of writing the tests and this page.

A `context=discard` brick left the budget in document order, and not first. The item carried the
scope that chose it, and not the mode of the brick.

`state` reported `todo` for a finished change when no diff was given.

The `# %%` text form tore a brick in two when the prose quoted the marker. The markdown form
removed that fault, because prose is prose.

A comment wrap had to fit on one line. This document's own bundle has five attributes. The reader
now joins the lines until it finds `-->`.

Two headings with only prose between them became one region. The second heading never started a
section. The reader now splits prose at each heading.

# Not done

The document format and the dataflow exist twice. `packages/pata/pata/doc.py` and
`leela/blocks/canvas/doc.py` read the same file. One of them must go.

`inline_ai` is one conversation with one approval slot. A canvas invites two questions at once.

Ramabana wraps any context in `<notebook path=...>`. A `.canvas.md` path given to `notebook_cells`
will fail.
