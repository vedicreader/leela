---
title: One session, reviewed: the canvas block, the brick library, and the page you are reading
---

# What this is

This file is the review of one working session. It is not a report about the session. It is the
session's own document, in the format the session built, read by the code the session added.

The page you are reading was written by `leela/blocks/canvas/app.py:page`. It read this file,
asked git for the diff this file names, and rendered both. Nothing assembled it by hand.

<!--canvas goal id=g measure="tools you open to review one session against its goal" baseline="4: tracker, notebook, diff, deck" target="1 page" by=2026-10-31-->
Give Leela one document that holds a goal, its plan, its research, its code and its questions,
and one page that shows all five to a reviewer on a phone.
<!--/canvas-->

# Words

Read this table first. Every later section uses these words and no others.

| word | means |
|---|---|
| **brick** | one part of the document: a fence or a comment wrap. A code cell, a question, a goal, a task, a clipping. |
| **prose** | ordinary markdown between bricks. It carries no markup of its own. |
| **region** | the bricks under one heading. Headings make regions; nobody writes one. |
| **basket** | the exact list of bricks that one question sends to the model. |
| **bundle** | one unit of change. It claims a region, names a goal, and owns a list of files. |
| **snippet** | a brick that cites code out of a file. It keeps no copy of that code. |
| **slot** | a `diff` brick with no body. It states which diff it wants; Leela fills it. |
| **library** | an installed package of components. `leela_bricks` is the first one. |
| **needs** | what a component's wiring imports. Read off the code, never written by hand. |
| **pata** | the retired name for this work. Sanskrit for the cloth a scroll painting is made on. The name now is `canvas`. |

# Why it helps

A reviewer of a change gets a diff. A diff answers one question: which lines moved. It cannot
answer the three questions a reviewer actually has.

1. What was this change supposed to do?
2. Did it do that?
3. Did anything else move that nobody meant to move?

The diff cannot answer them because the diff does not know the intent. Only the document knows.
So the document states the intent, the diff states the fact, and Leela compares them. The
comparison is `coverage`. Its `unmet` list is a claim with no change behind it. Its `unclaimed`
list is a change with no claim behind it. No diff tool can produce either list.

This page shows that comparison at the top, as chips, before any code.

<!--canvas ask id=q1 scope=region pins=g budget=6000-->
Why can a diff tool not report `unclaimed` on its own?
<!--/canvas-->

<!--canvas reply id=r1 of=q1-->
Because `unclaimed` is the difference between two sets, and a diff tool holds only one of them. It
holds the files that moved. It does not hold the files a change said it would touch. That set is
written in the document, in each bundle's `paths`. Subtract one from the other and you have a
finding. Hold only one and you have a file list.
<!--/canvas-->

# The plan

<!--canvas task id=t1 status=done owner=me-->
Read the document format from the canvas branch and adopt it.
<!--/canvas-->

<!--canvas task id=t2 status=done owner=me-->
Build the context basket: scope, pins, mutes, budget, and an inspectable result.
<!--/canvas-->

<!--canvas task id=t3 status=done owner=me-->
Make a boundary on the canvas a unit of change: tasks, prose, code and diff together.
<!--/canvas-->

<!--canvas task id=t4 status=done owner=me-->
Add the value view: every goal, and every change that serves it.
<!--/canvas-->

<!--canvas task id=t5 status=done owner=me-->
Write the literate page from the document, in ASD-STE100 English, under ramabana's rules.
<!--/canvas-->

<!--canvas task id=t6 status=done owner=me-->
Resolve a component from an installed library, in Leela, with no second server.
<!--/canvas-->

<!--canvas task id=t7 status=done owner=me-->
Vendor the lego bricks as `extensions/bricks`, so the package extracts with no code change.
<!--/canvas-->

<!--canvas task id=t8 status=done owner=me-->
Merge the canvas branch: one `doc.py`, one palette, one editor.
<!--/canvas-->

<!--canvas task id=t9 status=done owner=me-->
Move the page assembly out of the tool and into Leela.
<!--/canvas-->

# The document

<!--canvas bundle id=u-doc title="The format and the dataflow"
     goal=g
     contributes="the file every other part reads"
     covers="The document,t1"
     paths=leela/blocks/canvas/doc.py,leela/blocks/canvas/layout.py,leela/blocks/canvas/ops.py,leela/blocks/canvas/export.py,leela/blocks/canvas/example.py
     refs=doc:docs/canvas.md,file:leela/blocks/nb/nb.py-->
A canvas is a markdown file. Prose stays prose. A brick is a fence or a comment wrap, so every
markdown reader shows the file and git shows a useful diff. The dataflow between code bricks is
read off the code with the `ast` module. Nobody draws an edge.
<!--/canvas-->

Two brick shapes, and the shape follows the content. Code goes in a fence, because a fence is how
markdown holds code. A goal or a task goes in a comment wrap, because a reader should see the
words and not the markup.

```canvas snippet id=s-kinds path=leela/blocks/canvas/doc.py lines=12-15
A fence holds what markdown already knows how to show, so a code cell stays a code block. A
comment wrap holds what a reader should read as prose, so a goal shows its words and not its
markup. `KINDS` is the whole vocabulary, and a document with a word outside it does not parse.
```

The graph is a read, not a record. `defs_of` asks the code what it defines and `reads_of` asks
what it reads. Two bricks are joined when one defines what the other reads.

```canvas snippet id=s-order path=leela/blocks/canvas/doc.py symbol=order
`order` reads the dependency from the code. `_owners` says which brick defines each name, and
`b.reads` says which names a brick needs, so no person draws an edge. A cycle does not raise. The
visit stops and the document order stands, because a plan with a loop in it must still open.
```

# The basket

<!--canvas bundle id=u-ctx title="The context basket"
     goal=g
     contributes="what a question in the document may read"
     covers="The basket,t2"
     paths=leela/blocks/canvas/context.py
     refs=pkg:ramabana,file:leela/blocks/nb/nb.py-->
A question names its own scope, its pins and its budget. `resolve` returns the exact bricks, each
with the reason it was chosen. `render` emits the cells that ramabana's `compact_notebook_context`
already knows how to shed.
<!--/canvas-->

A notebook decides what the model reads by position: every cell above the question. That is right
for a script and wrong for a plan, because a plan holds four lines of work at once. One case shows
it. An audit belongs to the question at the top of the page and to the question at the bottom, and
to nothing between them. Position cannot say that. A pin can.

```canvas snippet id=s-spec path=leela/blocks/canvas/context.py symbol=Spec
A question states its own rule, and the rule is four fields. `scope` gathers the first set, `pins`
add what the scope missed, and `mutes` remove what it caught. An unknown scope becomes `page`
rather than an error, so a typed attribute cannot stop a document from opening.
```

<!--canvas note id=n-budget-->
The budget sheds the least useful brick first, not the oldest. A brick a question pinned survives
the budget, and so does the goal. This is why `resolve` returns `Item`s with a `why` on each one:
a reviewer can see what was dropped and ask why.
<!--/canvas-->

# The change

<!--canvas bundle id=u-chg title="The change bundle, the coverage report and three views"
     goal=g
     contributes="all of the review step"
     covers="The change,The page,t3,t4,t9,t12"
     paths=leela/blocks/canvas/change.py,leela/blocks/canvas/lit.py,leela/blocks/canvas/lit.css,docs/canvas.md,docs/change.canvas.md,docs/session.canvas.md,docs/dynamic-documents.md,docs/blocks.md,docs/README.md,README.md,media/canvas-*.html,media/*.md,tools/make_change_page.py,tools/canvas_spike.py,tools/canvas_proto/*
     refs=doc:docs/change.canvas.md,pkg:mdhtml,pkg:gheasy-->
A bundle claims a region, names a goal and owns a list of files. `coverage` compares the claim
with the diff. `state` is read off the document and never set by hand. `review`, `value` and `pr`
are three views over the same file.
<!--/canvas-->

The state of a change is derived. A bundle whose tasks are all done, and whose files all moved,
is done. Nothing writes that word into the file.

```canvas snippet id=s-state path=leela/blocks/canvas/change.py symbol=state
`state` reads the word off the document. One blocked task blocks the change. Every task done, and
every claimed file moved, makes it done. A change with no diff behind it is not punished for that,
because `files_ok` treats an absent diff as no evidence, not as evidence against.
```

The comparison a diff tool cannot make:

```canvas snippet id=s-cov path=leela/blocks/canvas/change.py symbol=coverage
`coverage` is the comparison. `matched` is a claim the diff confirms, `unmet` is a claim with
nothing behind it, and `unclaimed` is a file that moved with no claim on it. The third list is the
one no diff tool can produce, because only the document holds the promise to subtract from.
```

# The page

Leela now assembles this page. The tool that used to do it picks a file and prints a line.

```canvas snippet id=s-page path=leela/blocks/canvas/app.py symbol=page
`page` is the whole assembly, and it is Leela's, not a script's. It fills the slots, counts the
files, and writes the HTML in one call. It returns the file list and the unclaimed list, so a
caller sees the finding without reading the page.
```

A `diff` brick with no body is a slot. It says which paths it wants and which two commits to
compare. `place_diff` calls git once per slot and replaces the slot with one brick a file. A brick
no bundle claims is marked, and the page shows a warning on it.

```canvas snippet id=s-place path=leela/blocks/canvas/change.py symbol=place_diff
`place_diff` reads the request off the brick. A `diff` brick with a body is content, and is left
alone, so a pasted diff is never overwritten. Each slot becomes one brick a file, and a file no
bundle claims gets `claimed=no`, which the page shows as a warning.
```

The page folds anything longer than a phone screen, and a diff body scrolls sideways inside its
own box, so a long line never widens the page.

```canvas snippet id=s-fold path=leela/blocks/canvas/lit.py symbol=_diff
The renderer folds a diff longer than a phone screen, and the summary still names the file and the
counts. It drops the git headers a reader does not need. It writes no script, so the fold is
`<details>` and the page works with JavaScript turned off.
```

# The prompts

<!--canvas bundle id=u-pr title="Drafting the prose the reviewer reads"
     goal=g
     contributes="the words on this page"
     covers="The prompts,t5"
     paths=leela/blocks/canvas/explain.py,leela/blocks/canvas/explain.md,leela/blocks/canvas/ste.md
     refs=pkg:ramabana,pkg:shalya-->
Two prompt files, and no third. `explain.md` is the task and `ste.md` is the English. The writing
rules are read from ramabana's `write_docs` pyskill at the time of the call, so no copy of them
lives in this repository.
<!--/canvas-->

<!--canvas source id=src-rules url=pyskill:write_docs title="ramabana write_docs"-->
The voiceless GDS register, the banned words, no hedging, no restatement. Read through
`shalya.skills.discover()`, never copied here. When the skill is missing, `rule_text` raises
rather than falling back to a stale copy.
<!--/canvas-->

```canvas snippet id=s-rules path=leela/blocks/canvas/explain.py symbol=rule_text
`rule_text` reads the writing rules from where ramabana installed them. It keeps no copy, so a
change to `write_docs` reaches this prompt with no edit here. A missing skill raises rather than
falling back, because a silent fallback would draft prose against stale rules.
```

A brick the model drafted carries `wrote=ai` in the file, so `git diff` shows the drafting and a
reviewer can read those first. Every snippet on this page was written by a person, so no brick here
carries the mark. `media/e2e/drafted-page.html` is the same path run against a local model.

# The library

<!--canvas bundle id=u-brk title="A component comes from an installed library"
     goal=g
     contributes="the palette, with no second process"
     covers="The library,t6,t7,t11"
     paths=leela/blocks/canvas/bricks.py,extensions/bricks/*,tests/fixtures/*,docs/bricks.md
     refs=pkg:leela-bricks,doc:docs/bricks.md-->
The palette used to be an HTTP call to a second server. It is now an entry-point group. A library
answers four questions: its manifest, one brick, that brick's wiring, and its own routes. An HTTP
host answers the same four, and stays for a library that is not installed.
<!--/canvas-->

The four questions are the whole contract. A library that answers them needs to know nothing about
Leela, and Leela needs to know nothing about the library.

```canvas snippet id=s-lib path=leela/blocks/canvas/bricks.py symbol=Library
A library answers four questions and knows nothing about Leela. `manifest` lists its components,
`find` returns one, `wire` returns the code that fills its ports, and `mount` puts its own routes
on the app it is handed. `manifest` is read in process, so the palette needs no second server.
```

`needs` is read off the wiring's own imports, so a component cannot claim a dependency it does not
have, and cannot hide one it does.

```canvas snippet id=s-needs path=extensions/bricks/leela_bricks/bricks.py symbol=needs
`needs` reads the imports out of the wiring text. A component cannot claim a dependency its code
does not import, and cannot hide one it does. The standard library is dropped, so the list is what
a person must install before the cell will run.
```

<!--canvas note id=n-src-->
A library never writes its own name into a `src` string. `LIB` comes from `__name__`, so renaming
the package renames every `src` it serves. This is what made `extensions/bricks` extract with no
code change: eight files moved, and the only edit was to `bricks.py`, which grew a `Registry`.
<!--/canvas-->

The palette this branch resolves, in process:

```canvas code id=c-palette
from leela.blocks.canvas.bricks import libraries, palette
p = palette(libraries())
[(b['src'], b['needs']) for b in p['bricks']]
```

# The editor

<!--canvas bundle id=u-ed title="The editor the merge brought in"
     goal=g
     contributes="the run step and every insert menu"
     covers="The editor,What running it found,t8,t13"
     paths=leela/blocks/canvas/app.py,leela/blocks/canvas/ui.py,tests/test_web_slow.py,leela/blocks/canvas/live.py,leela/blocks/canvas/helper.py,leela/blocks/canvas/store.py,leela/blocks/canvas/*.js,leela/blocks/canvas/canvas.css,leela/blocks/canvas/*.canvas.md,leela/blocks/canvas/triage.diff,examples/canvas/*,docs/screenshots/*,media/canvas/*,media/e2e/*
     refs=doc:docs/canvas.md-->
The canvas branch built the editor: a gutter, a block menu, a slash menu, a component palette, an
inline helper and a live kernel. The merge kept one `doc.py` and one palette. The document format
is the seam that let two branches meet.
<!--/canvas-->

Five ways to add a brick, and all five write the same markdown. The gutter handle opens the block
menu. A slash at the start of an empty line opens the filter. The palette lists what an installed
library ships. A paste of a URL or a file makes a `source` or a `pdf`. `media/e2e/12-block-menu.png`
and `13-slash-menu.png` show the first two, and `14-palette.png` shows the third.

<!--canvas bundle id=u-wire title="Wiring the block into Leela"
     goal=g
     contributes="the block loads with the IDE, and its routes are checked"
     covers="The wiring,t10"
     paths=leela/blocks/__init__.py,leela/blocks/canvas/__init__.py,leela/skills/*,tools/build_ide_js.py,tests/routes.txt,tests/test_canvas.py,tests/test_canvas_doc.py,pyproject.toml,extensions/bricks/pyproject.toml
     refs=file:leela/blocks/__init__.py-->
A block declares the context it reads in `CAPS`, and the folder is listed in `blocks.NAMES`. Every
`.js` file is named in the IDE build. `tests/routes.txt` is the record of what the block serves,
so a new route cannot appear unrecorded.
<!--/canvas-->

# The wiring

`CAPS` must name exactly what the routes read off `ctx`. The canvas block reads two things: the
file system, and the model.

```canvas snippet id=s-caps path=leela/blocks/canvas/app.py lines=24-24
`CAPS` is a promise about `ctx`, and Leela checks it. A route that reads a capability the block did
not declare fails at load, not at request time. This is why the canvas block asks for two things
and no more.
```

# What running it found

Running the merged block end to end found two faults that reading it could not.

<!--canvas note id=n-stale-->
Typing in a code brick was lost. An insert anywhere in the document runs `cvSync`, which keeps the
element and hands it a new brick object, so the textarea's write went to an object the document no
longer held. The next flush read the older body, and the cell ran empty. `cvEdit` writes through to
`cvBrick(id)` and `cvKeepEdits` carries an edited body across the sync. The test is in
`tests/test_web_slow.py`, and it fails on the code before the fix.
<!--/canvas-->

<!--canvas note id=n-basket-->
The context basket has a route and no panel. `/canvas/context` returns the exact bricks one question
will send, each with the rule that chose it, and 51 tests cover the model. The merged editor has no
control that opens it, because neither branch built one: the canvas branch built the editor and this
side built the basket. This is the next piece of work, and the audit is the reason to name it here
rather than in a tracker.
<!--/canvas-->

<!--canvas task id=t13 status=done owner=me-->
Fix the stale-object write and add the browser test that reproduces it.
<!--/canvas-->

<!--canvas task id=t14 status=todo owner=me-->
Give the basket a panel: a control on an `ask` brick that shows what the question will send.
<!--/canvas-->

# The diff

Here is the diff for the two files that carry the change: the model and the routes. The slot below
states its own paths and its own two commits, and Leela filled it. The rest of the branch is in the
chips at the top of the page, and in `coverage`.

```canvas diff id=d-slot paths=leela/blocks/canvas/change.py,leela/blocks/canvas/app.py left=origin/main right=HEAD
```

# The numbers

<!--canvas data id=n-tally-->
files = 130
insertions = 11530
tests = 125
bricks = 10
libraries = 1
prompt_files = 2
<!--/canvas-->

<!--canvas ask id=q2 scope=doc mutes=d-slot budget=9000-->
Which part of this session would be hardest to rebuild from the diff alone?
<!--/canvas-->

<!--canvas reply id=r2 of=q2-->
The intent. Every line of code on this branch is in the diff, and none of the four `contributes`
lines is. A reader of the diff can see that `coverage` subtracts two sets. Only the document says
which set was a promise.
<!--/canvas-->

# Checks

<!--canvas task id=t10 status=done owner=me-->
125 tests pass, 1 skipped: the example that wires itself from a component host, with none running.
<!--/canvas-->

<!--canvas task id=t11 status=done owner=me-->
`leela_bricks` installs from `extensions/bricks` and the resolver finds all ten of its components.
<!--/canvas-->

<!--canvas task id=t12 status=done owner=me-->
This page is written by Leela, from this file, with a real git diff in the slot.
<!--/canvas-->
