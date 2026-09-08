---
title: "One branch, reviewed: where a canvas runs, the seams, and the page you are reading"
---

# What this is

This file is the review of one branch, in the format the branch built, read by the code the branch
added.

```canvas snippet id=s-page path=leela/blocks/canvas/app.py symbol=page
`page` wrote the page you are reading. It read this file, filled the one `diff` slot below from
git, and rendered both. The slot names the two files that carry the change. The rest of the branch
is in the chips at the top and in `coverage`.
```

<!--canvas goal id=g measure="tools you open to review one branch against its goal" baseline="4: tracker, notebook, diff, deck" target="1 page" by=2026-10-31-->
Give Leela one document that holds a goal, its plan, its research, its code and its questions,
and one page that shows all five to a reviewer on a phone.
<!--/canvas-->

<!--canvas goal id=g2 measure="findings from a review of this branch that are still open" baseline="17" target=0 by=2026-09-30-->
Leave nothing in this branch that a reviewer called critical or high.
<!--/canvas-->

# Words

Read this table first. Every later section uses these words and no others.

| word | means |
|---|---|
| brick | one part of the document: a fence or a comment wrap. A code cell, a question, a goal, a task, a clipping. |
| prose | ordinary markdown between bricks. It carries no markup of its own. |
| region | the bricks under one heading. The headings make the regions, so nobody writes one. |
| bundle | one unit of change. It claims a region, names a goal, and owns a list of files. |
| basket | the exact list of bricks that one question sends to the model. |
| snippet | a brick that cites code out of a file. It keeps no copy of that code. |
| slot | a `diff` brick with no body. It states which diff it wants; Leela fills it. |
| library | an installed package of components. `leela_bricks` is the first one. |
| trust | one click that lets a document's code run. Editing never needs it. |
| runtime | the thing that holds a document's names. `KernelRuntime` is a kunda kernel. |

The libraries this branch reaches, and what each one owns.

| package | owns |
|---|---|
| ramabana | the agent core. `leela.agent` is an alias for it, not a copy. |
| shalya | the tools and the hosts. `Host.provides` is the only way to ask what a host supports. |
| gheasy | the git. Every diff on this page came from `gheasy.repo`. |
| kunda | the kernels and the interpreter discovery. A canvas's code runs in one. |
| dhrishti | what looks inside a running kernel. `leela/core/inspectors.py` takes its registry. |
| kavacha | the native window, the menu vocabulary and both freezer definitions. |
| pullup | the project, the release, the deploys and the workflows. |
| mdhtml | the markdown. Nothing on this page parses markdown itself. |
| slopometer | the prose score. It reads a page against the reference rules. |

Names this branch retired.

| was | is |
|---|---|
| `pata` | `canvas`. Sanskrit for the cloth a scroll painting is made on. |
| `leela.blocks.runtime.support` | `kunda.pythons` and `kunda.support`, for all but `LEELA_PY`. |
| `leela.blocks.workflows.wfbuild` | `pullup.wfbuild`. The Leela file was nine pass-through lines. |
| `ramabana.tools` | `shalya`. The re-export lives for one release. |
| `ramabana.git` | `gheasy`. Gone already. |

# Why it helps

A reviewer of a branch gets a diff, which answers one question: which lines moved. It cannot answer
the three a reviewer has.

- What was this change supposed to do?
- Did it do that?
- Did anything else move that nobody meant to move?

The intent is in the document and the fact is in the diff. `coverage` compares them. Its `unmet`
list is a claim with no change behind it, and its `unclaimed` list is a change with no claim behind
it. Neither list can come out of a diff tool, which holds one of the two sets.

# Where the code runs

<!--canvas bundle id=u-live title="A document's code, in a kernel that can be stopped"
     goal=g2
     contributes="a document that cannot hang or end Leela"
     covers="t1"
     paths=leela/blocks/canvas/live.py,leela/blocks/canvas/store.py,leela/blocks/canvas/context.py
     refs=pkg:kunda,pkg:ramabana-->
A canvas executed its Python in the web process. One `while True:` hung every request Leela served.
One `os._exit()` ended Leela. This is the change that matters most in the branch.
<!--/canvas-->

```canvas snippet id=s-bounded path=leela/blocks/canvas/live.py symbol=KernelRuntime._bounded
Kunda's `execute(timeout=)` does not return on a busy loop, so the caller cannot wait on it alone.
This waits, interrupts, waits again, then replaces the kernel and says the namespace is gone. A
document that will not stop costs its own names and nothing else.
```

```canvas snippet id=s-runtime path=leela/blocks/canvas/live.py symbol=Dataflow
One base holds what does not care where code runs. `Runtime` is this process's, for the spike and
the tests. `KernelRuntime` is a kernel. Nothing in either reaches into a namespace dict.
```

```canvas snippet id=s-trust path=leela/blocks/canvas/app.py symbol=_runs_code
The trust line gates what evaluates, not what edits. A markdown file from anywhere can be opened,
read and written. Its code waits for one deliberate click. A first attempt gated inserting an
empty code brick, which made a document unwritable.
```

<!--canvas task id=t1 status=done owner=me-->
Run a canvas in a kernel, with a timeout, an interrupt and explicit trust.
<!--/canvas-->

# The routes

<!--canvas bundle id=u-web title="One gate for every path, one sandbox for every frame"
     goal=g2
     contributes="the block being safe to serve"
     covers="t2,t3,t4"
     paths=leela/blocks/canvas/app.py,leela/blocks/canvas/ui.py,leela/blocks/canvas/*.js,leela/blocks/canvas/canvas.css,leela/blocks/canvas/helper.py,leela/blocks/canvas/explain.py,leela/blocks/canvas/explain.md,leela/blocks/canvas/ste.md,leela/blocks/canvas/bricks.py,leela/skills/*,leela/static/lee-canvas.js,tools/build_ide_js.py,tools/canvas_spike.py
     refs=pkg:shalya-->
A path named anything the process could reach, and the block read it, ran it or wrote over it. A
frame carried this page's origin. The markdown writer let a URL close an attribute. The wheel left
out the files the client asked for at request time.
<!--/canvas-->

```canvas snippet id=s-gate path=leela/blocks/canvas/app.py symbol=canvas_path
One gate, and every source and destination passes it, including `save`'s `to` and `page`'s `out`.
With a folder open `fs._check` decides. With none, which is the spike and the tests, the canvas
folder decides. `is_relative_to` replaced a string prefix, which called `/root/canvasx` inside
`/root/canvas`.
```

```canvas snippet id=s-url path=leela/blocks/canvas/md.js symbol=cvUrl
`cvEsc` escaped `&<>` only, so a quote in a URL or a label closed the attribute and opened one of
the author's choosing. It escapes quotes too now. This allows http, https, mailto, a relative path,
an anchor and a raster data URL. A `javascript:` scheme and a data SVG do not pass.
```

```canvas snippet id=s-frame path=leela/blocks/canvas/canvas.js symbol=cvFrame
Both frames are `sandbox=allow-scripts` and nothing grants `allow-same-origin`. A component gets
an opaque origin. It cannot read this page's DOM, cookies or routes. A message speaks for the brick
whose frame sent it, never for the id it claims.
```

<!--canvas task id=t2 status=done owner=me-->
Gate every route's paths, both source and destination.
<!--/canvas-->

<!--canvas task id=t3 status=done owner=me-->
Sandbox both frames. Refuse a URL or an attribute that carries script.
<!--/canvas-->

<!--canvas task id=t4 status=done owner=me-->
Ship the client in the wheel, and hold it with a test against a built one.
<!--/canvas-->

# The change and the page

<!--canvas bundle id=u-chg title="What a bundle claims, and the page it renders to"
     goal=g
     contributes="all of the review step"
     paths=leela/blocks/canvas/change.py,leela/blocks/canvas/lit.py,leela/blocks/canvas/lit.css,leela/blocks/canvas/triage.diff,tools/make_change_page.py
     refs=pkg:mdhtml,pkg:gheasy-->
A bundle claims a region, names a goal and owns a list of files. This is the half that compares the
claim with the diff, and the half that writes the comparison out.
<!--/canvas-->

```canvas snippet id=s-coverage path=leela/blocks/canvas/change.py symbol=coverage
`matched` is a claim the diff confirms. `unmet` is a claim with nothing behind it. `unclaimed` is a
file that moved with no claim on it. A claim is a glob or a name, so a bundle can own a folder.
```

```canvas snippet id=s-review path=leela/blocks/canvas/change.py symbol=review
One change as a document. For each file it emits the hunks, then every brick citing that path. A
citation is a name or a glob: a note on `docs/screenshots/*` heads the run of fifteen it describes
instead of repeating under each. A file id is its basename, or its whole path when two files share
one basename.
```

```canvas snippet id=s-lit path=leela/blocks/canvas/lit.py symbol=_diff
The renderer writes no script, so the page works with JavaScript off. `DIFF_CAP` ends a long hunk
in a count and `DIFF_COLS` ends a long line in one. A generated artifact had otherwise put 12,650
lines and three megabytes into a page nobody could read.
```

# The document

<!--canvas bundle id=u-doc title="The format, unchanged in kind and larger in reach"
     goal=g
     contributes="the file every other part reads"
     paths=leela/blocks/canvas/doc.py,leela/blocks/canvas/layout.py,leela/blocks/canvas/ops.py,leela/blocks/canvas/export.py,leela/blocks/canvas/example.py,leela/blocks/canvas/procurement.canvas.md,leela/blocks/canvas/__init__.py,leela/blocks/__init__.py,examples/canvas/*,docs/screenshots/*,media/canvas/*,media/e2e/*
     refs=doc:docs/canvas.md-->
A canvas is a markdown file. Prose stays prose. A brick is a fence or a comment wrap. Every markdown
reader shows the file. Git shows a useful diff. Seventeen words are the whole
vocabulary. Six worked documents, fifteen shots and four screencasts show the format in use.
<!--/canvas-->

```canvas snippet id=s-save path=leela/blocks/canvas/doc.py symbol=Canvas.save
The document is the only store, so a torn write is a lost document. This writes through a temporary
file in the same folder and renames it. `ops` retires the names a changed or deleted code brick
used to define, so a renamed definition cannot stay readable downstream.
```

# The seams

<!--canvas bundle id=u-seam title="What Leela adds to the libraries it composes, and nothing more"
     goal=g2
     contributes="one spelling per name"
     covers="t5"
     paths=leela/blocks/runtime/*,leela/blocks/pipelines/*,leela/blocks/drive/*,leela/blocks/workflows/*,leela/blocks/agent/*,leela/blocks/debug/*,leela/blocks/editor/app.py,leela/blocks/search/search.py,leela/blocks/vars/app.py,leela/blocks/vault/jobs.py,extensions/bricks/*,pyproject.toml,uv.lock,.gitignore
     refs=pkg:kunda,pkg:pullup,pkg:kavacha,pkg:dhrishti-->
`test_seams.py` guarded eleven libraries. It did not guard kunda or pullup, the two Leela composes
most. Eight reaches into their private names went uncounted. The Words table above is the result:
one owner and one spelling per name.
<!--/canvas-->

```canvas snippet id=s-support path=leela/blocks/runtime/support.py
This module published almost the whole of kunda's support half again, while `core/envs.py` went
straight to kunda for three of the same names. `clean_env` had two spellings, depending on which
module you read. One name is left, the one Leela renames. Thirteen files now import from kunda.
```

<!--canvas task id=t5 status=done owner=me-->
Reduce each seam to what Leela adds, and guard every library it composes.
<!--/canvas-->

# What running it found

<!--canvas bundle id=u-test title="Four faults that had nothing to do with a canvas"
     goal=g2
     contributes="a suite that finishes"
     covers="t6"
     paths=tests/*,tests/blocks/*,tests/fixtures/*,docs/*.md,README.md,media/*.html,media/*.md
     refs=pkg:kunda,pkg:shalya-->
The kernel killed `pytest -m slow` a third of the way in and it reported nothing. Fixing that
turned up three more faults, none of them in the canvas.
<!--/canvas-->

<!--canvas note id=n-oom path=tests/test_web_slow.py-->
The harness built a model engine per browser workspace. No engine sat at 290MB, the first took it
to 871MB and the second to 3.1GB. Each streaming test then added two to three gigabytes while the
Python heap stayed flat, which puts the growth inside the engines. A browser test drives painting
and panels and needs no model. Every workspace gets the scripted backend: 80 tests, 4m29s, 967MB.
<!--/canvas-->

<!--canvas note id=n-reap path=leela/blocks/agent/threads.py-->
`TurnRunner._reap` read `Thread.is_alive` alone. That is False before a thread starts, and False
after it ends. `start` publishes the pending turn and only then starts its worker. A request
arriving in that window reaped a live turn. The fix reads `ident` first.
<!--/canvas-->

<!--canvas note id=n-ipymini path=tests/test_kernels_ipymini.py-->
Five monkeypatches aimed at Leela's re-exports, not at the name the library reads. `kunda.pool`
imports `Kernel` under its own roof and `_class_for` reads it there. The pool ignored the fakes.
One test failed and one hung on a real kernel that never signalled.
<!--/canvas-->

<!--canvas note id=n-path path=tests/test_pipelines.py-->
One test resolved `nbdev-prepare` off the ambient `PATH`. It therefore passed or failed on how
somebody invoked pytest. A sibling test owns the question of whether the environment carries nbdev.
This one states that precondition and checks that the resolved script is what runs.
<!--/canvas-->

<!--canvas task id=t6 status=done owner=me-->
Make `pytest -m slow` finish, and fix what running it found.
<!--/canvas-->

# The prose

<!--canvas bundle id=u-prose title="Every page scored against the branch's own rulebook"
     goal=g
     contributes="the English a reviewer reads"
     covers="t7"
     paths=leela/blocks/canvas/ste.md,leela/blocks/canvas/explain.md
     refs=pkg:slopometer,doc:leela/blocks/canvas/ste.md-->
`ste.md` held the rules and `explain.md` handed them to the model that drafts a snippet. A drafted
sentence met them. A hand-written one did not. `slopometer` now scores every page on the branch.
<!--/canvas-->

```canvas snippet id=s-ste path=leela/blocks/canvas/ste.md lines=1-12
Twenty words a sentence, active voice, one meaning per word. It bans the em dash, the semicolon,
the parenthetical, the restatement and the closing reversal. Three patterns carried most of the
weight on the pages that failed: a sentence that states a thing and then restates its opposite, a
closing line that reverses the one before it, and a passive clause that drops the doer.
```

<!--canvas task id=t7 status=done owner=me-->
Score every page with slopometer, and rewrite the prose that fails ASD-STE100.
<!--/canvas-->

# The diff

Two files carry this change: where a canvas's code runs, and the routes that reach it. The slot
below names them and its own two commits. Leela filled it. The chips at the top of the page and
`coverage` account for the other 143.

```canvas diff id=d-core paths=leela/blocks/canvas/live.py,leela/blocks/canvas/app.py left=origin/main right=HEAD
```

# The numbers

<!--canvas data id=n-tally-->
files = 145
insertions = 13606
deletions = 290
brick_kinds = 17
libraries_guarded = 13
tests = 2045
review_findings_closed = 17
worst_page_before = 26.8
worst_page_after = 2.5
<!--/canvas-->

# Checks

<!--canvas task id=t8 status=done owner=me-->
2045 tests pass with 15 skipped, and the slow suite finishes in 4m29s at 967MB.
<!--/canvas-->

<!--canvas task id=t9 status=done owner=me-->
Seven tests fail against the original code, one per fault a reviewer called critical or high.
<!--/canvas-->

<!--canvas task id=t10 status=done owner=me-->
Leela writes this page from this file, with a real git diff in the slot.
<!--/canvas-->

<!--canvas ask id=q1 scope=doc budget=40000-->
Name the change here you would push back on, and say what you would want instead.
<!--/canvas-->
