---
title: One session, reviewed: the canvas block, the brick library, and the page you are reading
---

# What this is

This file is the review of one working session, in the format the session built, read by the code
the session added.

`leela/blocks/canvas/app.py:page` wrote the page you are reading. It read this file, asked git for
the diff this file names, and rendered both.

<!--canvas goal id=g measure="tools you open to review one session against its goal" baseline="4: tracker, notebook, diff, deck" target="1 page" by=2026-10-31-->
Give Leela one document that holds a goal, its plan, its research, its code and its questions,
and one page that shows all five to a reviewer on a phone.
<!--/canvas-->

<!--canvas goal id=g2 measure="slopometer density on the worst page of the branch" baseline="26.8" target="under 8" by=2026-09-30-->
Hold every page this branch adds to the English that ste.md already states, and measure it
rather than assert it.
<!--/canvas-->

<!--canvas goal id=g3 measure="findings from a review of this branch that are still open" baseline="17" target=0 by=2026-09-30-->
Leave nothing in this branch that a reviewer called critical or high.
<!--/canvas-->

# Words

Read this table first. Every later section uses these words and no others.

| word | means |
|---|---|
| **brick** | one part of the document: a fence or a comment wrap. A code cell, a question, a goal, a task, a clipping. |
| **prose** | ordinary markdown between bricks. It carries no markup of its own. |
| **region** | the bricks under one heading. The headings make the regions, so nobody writes one. |
| **basket** | the exact list of bricks that one question sends to the model. |
| **bundle** | one unit of change. It claims a region, names a goal, and owns a list of files. |
| **snippet** | a brick that cites code out of a file. It keeps no copy of that code. |
| **slot** | a `diff` brick with no body. It states which diff it wants; Leela fills it. |
| **library** | an installed package of components. `leela_bricks` is the first one. |
| **needs** | what a component's wiring imports. Read off the code, never written by hand. |
| **pata** | the retired name for this work. Sanskrit for the cloth a scroll painting is made on. The name now is `canvas`. |

# Why it helps

A diff tells a reviewer which lines moved. It cannot answer the three questions a reviewer brings
to a change.

1. What was this change supposed to do?
2. Did it do that?
3. Did anything else move that nobody meant to move?

The intent is in the document, not in the diff. So the document states the intent, the diff states
the fact, and `coverage` compares them. Its `unmet` list is a claim with no change behind it, and
its `unclaimed` list is a change with no claim behind it. Neither list can come out of a diff tool,
which holds one of the two sets.

This page shows that comparison at the top, as chips, before any code.

<!--canvas ask id=q1 scope=region pins=g budget=6000-->
Why can a diff tool not report `unclaimed` on its own?
<!--/canvas-->

<!--canvas reply id=r1 of=q1-->
`unclaimed` is the difference between two sets. A diff tool holds the files that moved. It does
not hold the files a change promised to touch, which sit in each bundle's `paths`. A finding
needs both sets.
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
Vendor the brick library as `extensions/bricks`. The package must extract with no code change.
<!--/canvas-->

<!--canvas task id=t8 status=done owner=me-->
Merge the canvas branch: one `doc.py`, one palette, one editor.
<!--/canvas-->

<!--canvas task id=t9 status=done owner=me-->
Move the page assembly out of the tool and into Leela.
<!--/canvas-->

<!--canvas task id=t15 status=done owner=me-->
Score every page with `slopometer`, and rewrite the prose that fails ASD-STE100.
<!--/canvas-->

<!--canvas task id=t16 status=done owner=me-->
Run `chkstyle` over the branch's Python, and cut the imports nothing uses.
<!--/canvas-->

<!--canvas task id=t17 status=done owner=me-->
Get the suite green: 2003 pass, 15 skip, none fail.
<!--/canvas-->

# The document

<!--canvas bundle id=u-doc title="The format and the dataflow"
     goal=g
     contributes="the file every other part reads"
     covers="The document,t1"
     paths=leela/blocks/canvas/doc.py,leela/blocks/canvas/layout.py,leela/blocks/canvas/ops.py,leela/blocks/canvas/export.py,leela/blocks/canvas/example.py
     refs=doc:docs/canvas.md,file:leela/blocks/nb/nb.py-->
A canvas is a markdown file. Prose stays prose. A brick is a fence or a comment wrap. Every
markdown reader therefore shows the file, and git shows a useful diff. The `ast` module reads the dataflow
between code bricks off the code itself.
<!--/canvas-->

Two brick shapes, and the shape follows the content. Code goes in a fence, because a fence is how
markdown holds code. A goal or a task goes in a comment wrap, because a reader should see the
words and not the markup.

```canvas snippet id=s-kinds path=leela/blocks/canvas/doc.py lines=12-15
A fence holds what markdown already knows how to show, so a code cell stays a code block. A
comment wrap holds what a reader should read as prose, so a goal shows its words and not its
markup. `KINDS` is the whole vocabulary, and a document with a word outside it does not parse.
```

`order` reads the graph rather than storing it. `defs_of` asks the code what it defines, and
`reads_of` asks what it reads. `order` joins two bricks when one defines what the other reads.

```canvas snippet id=s-order path=leela/blocks/canvas/doc.py symbol=order
`order` reads the dependency from the code. `_owners` says which brick defines each name, and
`b.reads` says which names a brick needs, so no person draws an edge. On a cycle the visit stops
and the document order stands, so a plan with a loop in it still opens.
```

# The basket

<!--canvas bundle id=u-ctx title="The context basket"
     goal=g
     contributes="what a question in the document may read"
     covers="The basket,t2"
     paths=leela/blocks/canvas/context.py
     refs=pkg:ramabana,file:leela/blocks/nb/nb.py-->
A question names its own scope, its pins and its budget. `resolve` returns the exact bricks, and each one
carries the reason it is there. `render` emits the cells that ramabana's `compact_notebook_context`
already knows how to shed.
<!--/canvas-->

A notebook sends every brick above the question. A pin sends the two that matter, wherever they
sit. An audit belongs to the question at the top of the page and the one at the bottom, and to
nothing between.

```canvas snippet id=s-spec path=leela/blocks/canvas/context.py symbol=Spec
A question states its own rule, and the rule is four fields. `scope` gathers the first set, `pins`
add what the scope missed, and `mutes` remove what it caught. An unknown scope becomes `page`
rather than an error, so a typed attribute cannot stop a document from opening.
```

<!--canvas note id=n-budget-->
The budget sheds the least useful brick first, not the oldest, and never a pin or the goal. Each
`Item` carries the `why` that put it there. A reviewer can therefore see which bricks the budget
dropped.
<!--/canvas-->

# The change

<!--canvas bundle id=u-chg title="The change bundle, the coverage report and three views"
     goal=g
     contributes="all of the review step"
     covers="The change,The page,t3,t4,t9,t12"
     paths=leela/blocks/canvas/change.py,leela/blocks/canvas/lit.py,leela/blocks/canvas/lit.css,docs/canvas.md,docs/change.canvas.md,docs/session.canvas.md,docs/dynamic-documents.md,docs/blocks.md,docs/README.md,README.md,media/canvas-*.html,media/*.md,tools/make_change_page.py,tools/canvas_spike.py
     refs=doc:docs/change.canvas.md,pkg:mdhtml,pkg:gheasy-->
A bundle claims a region, names a goal and owns a list of files. `coverage` compares the claim
with the diff. Leela reads `state` off the document, and no one sets it by hand. `review`, `value` and `pr`
are three views over the same file.
<!--/canvas-->

Leela derives the state of a change. A bundle reaches `done` once every task reaches `done` and
every claimed file moved. No one writes that word into the file.

```canvas snippet id=s-state path=leela/blocks/canvas/change.py symbol=state
`state` reads the word off the document. One blocked task blocks the change, and every task done
with every claimed file moved makes it done. `files_ok` treats an absent diff as no evidence, so a
change nobody has diffed yet does not read as work not started.
```

The comparison a diff tool cannot make:

```canvas snippet id=s-cov path=leela/blocks/canvas/change.py symbol=coverage
`matched` is a claim the diff confirms, `unmet` is a claim with nothing behind it, and `unclaimed`
is a file that moved with no claim on it. A claim is a glob, so `leela/blocks/canvas/*` covers
every file the change touched in that folder without naming one of them.
```

# The page

Leela now assembles this page. The tool that used to do it picks a file and prints a line.

```canvas snippet id=s-page path=leela/blocks/canvas/app.py symbol=page
`page` fills the slots, counts the files and writes the HTML in one call. It returns the file list
and the unclaimed list, so a caller sees the finding without opening the page.
```

A `diff` brick with no body is a slot. It says which paths it wants and which two commits to
compare. `place_diff` calls git once per slot and replaces the slot with one brick a file. `place_diff` marks a brick
no bundle claims, and the page shows a warning on it.

```canvas snippet id=s-place path=leela/blocks/canvas/change.py symbol=place_diff
`place_diff` reads the request off the brick. A `diff` brick with a body is content, and is left
alone, so a pasted diff is never overwritten. Each slot becomes one brick a file, and a file no
bundle claims gets `claimed=no`, which the page shows as a warning.
```

The page folds anything longer than a phone screen. A diff body scrolls sideways inside its own
box, and a long line therefore never widens the page.

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
Leela drafts from two files, and no third. `explain.md` holds the task and `ste.md` holds the English.
`rule_text` reads the writing rules from ramabana's `write_docs` pyskill at the time of the call,
so this repository keeps no copy of them.
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

A brick the model drafted carries `wrote=ai` in the file. `git diff` therefore shows the drafting,
and a reviewer can read those bricks first. A person wrote every snippet on this page, and no
brick here carries the mark.

# The library

<!--canvas bundle id=u-brk title="A component comes from an installed library"
     goal=g
     contributes="the palette, with no second process"
     covers="The library,t6,t7,t11"
     paths=leela/blocks/canvas/bricks.py,extensions/bricks/*,tests/fixtures/*,docs/bricks.md
     refs=pkg:leela-bricks,doc:docs/bricks.md-->
The palette used to be an HTTP call to a second server. It is now an entry-point group. A library
answers four questions: its manifest, one brick, that brick's wiring, and its own routes. An HTTP
host answers the same four, and it stays for a library nobody installed.
<!--/canvas-->

The four questions are the whole contract. A library that answers them needs to know nothing about
Leela, and Leela needs to know nothing about the library.

```canvas snippet id=s-lib path=leela/blocks/canvas/bricks.py symbol=Library
A library answers four questions and knows nothing about Leela. `manifest` lists its components,
`find` returns one, `wire` returns the code that fills its ports, and `mount` puts its own routes
on the app it is handed. `manifest` is read in process, so the palette needs no second server.
```

`needs` comes from the wiring's own imports. A component cannot claim a dependency its code does
not import, and cannot hide one it does.

```canvas snippet id=s-needs path=extensions/bricks/leela_bricks/bricks.py symbol=needs
`needs` reads the imports out of the wiring text. A component cannot claim a dependency its code
does not import, and cannot hide one it does. The standard library is dropped, so the list is what
a person must install before the cell will run.
```

<!--canvas note id=n-src-->
A library never writes its own name into a `src` string. `LIB` comes from `__name__`. Renaming
the package therefore renames every `src` it serves. This is why `extensions/bricks` extracted with no
code change. Eight files moved, and the only edit added a `Registry` to `bricks.py`.
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
     paths=leela/blocks/canvas/app.py,leela/blocks/canvas/ui.py,tests/test_web_slow.py,leela/blocks/canvas/live.py,leela/blocks/canvas/helper.py,leela/blocks/canvas/store.py,leela/blocks/canvas/*.js,leela/blocks/canvas/canvas.css,leela/blocks/canvas/*.canvas.md,leela/blocks/canvas/triage.diff,examples/canvas/*,docs/screenshots/*,media/canvas/*
     refs=doc:docs/canvas.md-->
The canvas branch built the editor: a gutter, a block menu, a slash menu, a component palette, an
inline helper and a live kernel. Both branches read the same file format, and the merge therefore kept one
`doc.py` and one palette.
<!--/canvas-->

Four ways to add a brick, and all four write the same markdown. The gutter handle opens the block
menu, and a slash on an empty line opens the filter. The palette lists what an installed library
ships, and a pasted URL or file becomes a `source` or a `pdf`. `docs/screenshots/canvas-blockmenu.png`,
`canvas-slash.png` and `canvas-palette.png` show the first three.

<!--canvas bundle id=u-wire title="Wiring the block into Leela"
     goal=g
     contributes="the block loads with the IDE, and its routes are checked"
     covers="The wiring,t10"
     paths=leela/blocks/__init__.py,leela/blocks/canvas/__init__.py,leela/skills/*,tools/build_ide_js.py,tests/routes.txt,tests/test_canvas.py,tests/test_canvas_doc.py,pyproject.toml,extensions/bricks/pyproject.toml,.gitignore
     refs=file:leela/blocks/__init__.py-->
A block declares the context it reads in `CAPS`, and `blocks.NAMES` lists the folder. The IDE
build names every `.js` file. `tests/routes.txt` is the record of what the block serves,
so a new route cannot appear unrecorded.
<!--/canvas-->

# The wiring

`CAPS` must name exactly what the routes read off `ctx`. The canvas block reads two things: the
file system, and the model.

```canvas snippet id=s-caps path=leela/blocks/canvas/app.py lines=24-24
`CAPS` is a promise about `ctx`, and Leela checks it. A route that reads a capability the block did
not declare fails at load, not at the request that reads it.
```

# What running it found

Two faults survived every reading of the merged block. Running it end to end found both.

<!--canvas note id=n-stale-->
The editor lost typing in a code brick. An insert anywhere in the document runs `cvSync`, which keeps the
element and hands it a new brick object. The textarea then wrote to an object the document no
longer held, and the next flush read the older body. `cvEdit` writes through to `cvBrick(id)`, and
`cvKeepEdits` carries an edited body across the sync. The browser test in `tests/test_web_slow.py`
returns the empty body on the code before the fix.
<!--/canvas-->

<!--canvas note id=n-basket-->
The context basket has a route and no panel. `/canvas/context` returns the exact bricks one question
will send, each with the rule that chose it, and 51 tests cover the model. The merged editor has no
control that opens it. Neither branch built one, because the canvas branch built the editor and
this side built the basket. `t14` above records the gap.
<!--/canvas-->

<!--canvas task id=t13 status=done owner=me-->
Fix the stale-object write and add the browser test that reproduces it.
<!--/canvas-->

<!--canvas task id=t14 status=todo owner=me-->
Give the basket a panel: a control on an `ask` brick that shows what the question will send.
<!--/canvas-->

# The prose

<!--canvas bundle id=u-prose title="Every page scored, and the English fixed"
     goal=g2
     contributes="the English a reviewer actually reads"
     covers="The prose,t15,t16"
     paths=README.md,docs/*.md,examples/canvas/*.canvas.md,extensions/bricks/README.md,media/*.md,leela/blocks/canvas/procurement.canvas.md,leela/blocks/canvas/explain.md,leela/blocks/canvas/*.py,extensions/bricks/leela_bricks/*.py,leela/blocks/agent/threads.py,tests/blocks/test_agent_threads.py,tests/test_core.py,tests/test_packaging.py,tests/test_projects.py,tests/test_runtime.py,tests/test_agent.py
     refs=pkg:slopometer,pkg:fastaistyle,doc:leela/blocks/canvas/ste.md-->
`slopometer` scores a page against the reference-prose rules, and `chkstyle` scores Python against
fastai's. Both ran over every file this branch adds. `ste.md` already held the rules, and nobody had
checked a hand-written page against them.
<!--/canvas-->

`explain.md` hands `ste.md` to the model that drafts a snippet. A drafted sentence therefore met
the rules, and a hand-written one did not. Three patterns carried most of the weight. A sentence states a
thing and then restates its opposite. A closing line reverses the sentence before it. A passive
clause drops the doer. `ste.md` bans all three by name.

<!--canvas data id=n-slop-->
worst_page_before = 26.8
worst_page_after = 7.5
readme_before = 12.9
readme_after = 2.9
pages_scored = 20
pages_at_zero = 4
unused_imports_cut = 27
<!--/canvas-->

What the score still reports is not slop. A package name reads as a coinage. A bold UI label
reads as emphasis. A list of three parallel clauses reads as a long sentence. `ste.md` permits
the third by name, and the first two are the words the product uses.

`docs/screenshots/canvas-prose-goals.png` shows both goals on this page, and
`canvas-prose-review.png` and `canvas-prose-phone.png` show this section on a desktop and on a
phone. Leela drew all three from this file.

Eighteen tests failed on this branch before the review, and none of them for a reason the branch
introduced. Four were the environment: no brick library installed, no generated icon, and no venv
on `PATH`. Two guards read a route surface that grows with whatever library the machine has, so
they now measure Leela's own. Three tests compared a liveness that a zombie also reports, or a PNG that
Pillow re-encodes between versions.

<!--canvas note id=n-reap-->
One was a fault in the code. `TurnRunner._reap` read `Thread.is_alive` alone, which is False before
a thread starts as well as after it ends. `start` publishes the pending turn and only then starts
its worker. A request arriving in that window reaped a live turn and won acceptance. That is the
second turn `_pending` exists to refuse. `worker.ident` tells an unstarted thread from a finished
one, and two tests in `tests/blocks/test_agent_threads.py` hold each half.
<!--/canvas-->

# The review

<!--canvas bundle id=u-rev title="What a review of this branch found, and what it cost to fix"
     goal=g3
     contributes="the branch being safe to merge"
     covers="The review,t18,t19,t20,t21"
     paths=leela/blocks/canvas/*,leela/static/lee-canvas.js,tools/build_ide_js.py,leela/blocks/runtime/*,leela/blocks/pipelines/*,leela/blocks/drive/*,leela/blocks/workflows/*,leela/blocks/agent/models.py,leela/blocks/debug/*,leela/blocks/editor/app.py,leela/blocks/search/search.py,leela/blocks/vars/app.py,leela/blocks/vault/jobs.py,tests/test_seams.py,tests/test_pipelines.py,tests/test_workflows.py,tests/test_git_folder.py,tests/test_web_slow.py,tests/test_agent_slow.py,tests/test_kernels_ipymini.py,tests/test_agent.py,uv.lock
     refs=doc:docs/canvas.md,pkg:kunda,pkg:pullup-->
Four faults were critical and six were high. Every route that took a path read, ran or overwrote
whatever it named. A canvas ran its Python in the web process. A frame had this page's origin, and
the markdown writer let a URL close an attribute. The wheel excluded the very files the client was
built from at request time.
<!--/canvas-->

The path gate is one function, `canvas_path`, and every source and destination passes it. A canvas
runs in a kunda kernel now, and only after somebody says it may: opening a document draws it and
executes nothing. Both frames are sandboxed with `allow-scripts` and no same-origin. The client is
a committed bundle, `leela/static/lee-canvas.js`, built from the order `ui.FILES` states.

The seams cost the widest change. `test_seams.py` guarded eleven libraries and not kunda or
pullup, the two Leela composes most. Eight reaches into their private names went uncounted.
`runtime/support.py` re-exported almost the whole of kunda's support half. `core/envs.py` went
straight to kunda for three of the same names, so `clean_env` had two spellings. Fifteen call
sites in ten modules now import from kunda directly. That is why this change reaches blocks with
nothing to do with a canvas.

<!--canvas note id=n-timeout-->
Kunda's `execute(timeout=)` does not return on a busy loop. `while True: pass` sat past two hundred
seconds under it, and `interrupt` stopped the same cell in milliseconds. So `KernelRuntime` holds
the bound itself: wait, interrupt, wait again, then shut the kernel down and start another. A cell
that calls `os._exit` takes its kernel and nothing else.
<!--/canvas-->

```canvas snippet id=s-bounded path=leela/blocks/canvas/live.py symbol=KernelRuntime._bounded
Three steps, because each one can fail on its own. `interrupt` is what actually stops a cell, and
the wait around it is what makes the timeout real. Giving up on the kernel costs the namespace,
which is the whole reason a kernel is worth having.
```

```canvas snippet id=s-gate path=leela/blocks/canvas/app.py symbol=canvas_path
The gate compares the resolved path against the root it must be under, so a relative path cannot
walk up out of it. With a folder open the workspace decides; with none, which is the spike and the
tests, the canvas directory does.
```

<!--canvas task id=t18 status=done owner=me-->
Gate every route's paths, both source and destination.
<!--/canvas-->

<!--canvas task id=t19 status=done owner=me-->
Run a canvas in a kernel, with a timeout, an interrupt and explicit trust.
<!--/canvas-->

<!--canvas task id=t20 status=done owner=me-->
Sandbox both frames, and refuse a URL or an attribute that is script.
<!--/canvas-->

<!--canvas task id=t21 status=done owner=me-->
Ship the client in the wheel, and hold it with a test against a built one.
<!--/canvas-->

<!--canvas task id=t22 status=done owner=me-->
Make `pytest -m slow` finish, and fix what running it found.
<!--/canvas-->

<!--canvas note id=n-e2e-->
`pytest -m slow` was OOM-killed a third of the way in and reported nothing. Not the tests it
could never run, and not the ones above them that pass in seconds. Two suites resolved a real local
model, because its bundle happened to be cached on the machine. The trace reads plainly. No engine
sat at 290MB. The first took it to 871MB and the second to 3.1GB. Each streaming test after that
added two to three gigabytes while the Python heap stayed flat, so the growth was native and inside
the engines. A browser test drives painting and panels, and needs no model at all. The suite now
runs 80 tests in 4m29s, peaking at 967MB.
<!--/canvas-->

Five monkeypatches aimed at Leela's re-exports rather than the name the library reads.
`kunda.pool` imports `Kernel` into its own namespace, so the fakes were ignored. One test failed
and one hung on a real kernel that never signalled. One assertion expected `read_only` to drop the
delegate tools by default. shalya moved that to a `block=` the caller passes, and both production
call sites pass it, so the test was red while the behaviour was right. One test read a notebook out
of an untracked folder a real kernel had written into the checkout. Three counted the buttons in a
bar that gained a fourth.

```canvas snippet id=s-ram path=tests/test_agent_slow.py symbol=_ram_mb
The gate asked whether the bundle was cached and not whether the machine could hold it. One engine
climbs to 12.2GB and a run that reached 13.4GB died with 3.1GB nominally free, so the number is
16000 and the comment above it says where that came from.
```

# The diff

Every file this branch touches, against `origin/main`. The slot names no path, so Leela filled it
with one brick a file and marked any that no change on this page claims.

```canvas diff id=d-all left=origin/main right=HEAD
```

# The numbers

<!--canvas data id=n-tally-->
files = 126
insertions = 12161
deletions = 261
tests = 2054
slow_tests = 139
canvas_tests = 152
review_findings_closed = 17
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
125 canvas tests pass, 1 skipped: the example that wires itself from a component host, with none running. The browser test needs `-m slow`.
<!--/canvas-->

<!--canvas task id=t11 status=done owner=me-->
`leela_bricks` installs from `extensions/bricks` and the resolver finds all ten of its components.
<!--/canvas-->

<!--canvas task id=t12 status=done owner=me-->
Leela writes this page from this file, with a real git diff in the slot.
<!--/canvas-->

<!--canvas note id=n-loose-->
The seven files the header used to report as unclaimed were scratch: `shot.mjs`, `t-dark.mjs`,
`t-help.mjs` and four screenshots under `shots/`. They are deleted, along with the 28 run
artefacts under `media/e2e/`, ten screenshots nothing cited, and the prototype in
`tools/canvas_proto` that the block replaced. Nothing here claims a file that is gone.
<!--/canvas-->
