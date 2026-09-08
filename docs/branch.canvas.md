---
title: The canvas branch, file by file
---

# What this is

Every file this branch changes against `origin/main`. Each file sits with the others it belongs with.
The prose about each file sits under that file's own hunks. `canvas.branch_page` builds the page.
It runs one `review` per change. Each `review` pairs a file's diff with every brick citing it.

<!--canvas goal id=g measure="tools you open to review one branch" baseline="4: tracker, notebook, diff, deck" target="1 page" by=2026-10-31-->
Give Leela one document that holds a goal, its plan, its research, its code and its questions,
and one page that shows all five to a reviewer on a phone.
<!--/canvas-->

<!--canvas goal id=g2 measure="findings from a review of this branch that are still open" baseline="17" target=0 by=2026-09-30-->
Leave nothing in this branch that a reviewer called critical or high.
<!--/canvas-->

# The format

<!--canvas bundle id=u-doc title="The document, and every change to it"
     goal=g
     contributes="the file every other part reads"
     paths=leela/blocks/canvas/doc.py,leela/blocks/canvas/procurement.canvas.md,leela/blocks/canvas/layout.py,leela/blocks/canvas/ops.py,leela/blocks/canvas/export.py,leela/blocks/canvas/example.py,leela/blocks/canvas/__init__.py,leela/blocks/__init__.py
     refs=doc:docs/canvas.md-->
A canvas is a markdown file. Prose stays prose. A brick is a fence or a comment wrap. Every
markdown reader shows the file. Git shows a useful diff. The `ast` module reads the dataflow
between code bricks off the code itself. Nobody draws an edge.
<!--/canvas-->

<!--canvas note id=n-doc path=leela/blocks/canvas/doc.py-->
The whole format. `KINDS` is the vocabulary. A word outside it does not parse. The parser is a
line scan. A canvas fence inside a longer markdown fence is an example of a brick, not a brick.
`order` reads the dependency graph off the code. On a cycle the visit stops and document order
stands, and a plan with a loop in it still opens. `save` writes through a temporary file in the
same folder. A torn write cannot reach the document.
<!--/canvas-->

<!--canvas note id=n-ops path=leela/blocks/canvas/ops.py-->
One function for every change, whether a person or the helper asked for it. `replace`, `kind`,
`remove` and `replace_selection` now retire the names their brick defined. A renamed or deleted
definition cannot stay readable downstream.
<!--/canvas-->

<!--canvas note id=n-sample path=leela/blocks/canvas/procurement.canvas.md-->
The demonstration document `example.py` writes out. It carries a goal, three bundles, code bricks
with a dataflow, and an open question. A reader never opens an empty canvas first.
<!--/canvas-->

<!--canvas note id=n-layout path=leela/blocks/canvas/layout.py-->
`prop x` and `prop y` are the only trace the canvas leaves in the file. A document nobody has
laid out is still complete. `arrange` places an unopened one.
<!--/canvas-->

# The live half

<!--canvas bundle id=u-live title="Where a canvas's code runs"
     goal=g2
     contributes="a document that cannot hang or end Leela"
     covers="t1"
     paths=leela/blocks/canvas/live.py,leela/blocks/canvas/store.py,leela/blocks/canvas/context.py
     refs=pkg:kunda,pkg:ramabana-->
A canvas executed its Python in the web process. One `while True:` hung every request Leela
served. One `os._exit()` ended Leela. The code runs in a kunda kernel now. It runs only after
somebody says it may.
<!--/canvas-->

<!--canvas note id=n-live path=leela/blocks/canvas/live.py-->
`Dataflow` is the half that does not care where code runs. Nothing in it reaches into a namespace
dict. `Runtime` is this process's, for the spike and the tests. `KernelRuntime` is a kernel. It
holds the timeout itself. Kunda's `execute(timeout=)` does not return on a busy loop. So it waits,
interrupts, waits again, shuts the kernel down and starts another.
<!--/canvas-->

<!--canvas note id=n-store path=leela/blocks/canvas/store.py-->
One process-global store served every workspace. `store_for` scopes it to the open roots. It keys
on the resolved path. Two spellings of one file cannot fork a namespace. `allow` sets
`Open.trusted`. A save carries `rev`, and the store refuses a stale write.
<!--/canvas-->

<!--canvas note id=n-context path=leela/blocks/canvas/context.py-->
A question names its own scope, pins and budget. `resolve` returns the exact bricks and the reason
each one is there. The budget sheds the least useful brick first, never a pin or the goal.
<!--/canvas-->

<!--canvas task id=t1 status=done owner=me-->
Run a canvas in a kernel, with a timeout, an interrupt and explicit trust.
<!--/canvas-->

# The change and the page

<!--canvas bundle id=u-chg title="The change a boundary claims, and the page it renders to"
     goal=g
     contributes="all of the review step"
     paths=leela/blocks/canvas/change.py,leela/blocks/canvas/lit.py,leela/blocks/canvas/lit.css,leela/blocks/canvas/triage.diff,tools/make_change_page.py
     refs=pkg:mdhtml,pkg:gheasy-->
A bundle claims a region, names a goal and owns a list of files. `coverage` compares the claim
with the diff. A diff tool holds one of those two sets. It can produce neither list.
<!--/canvas-->

<!--canvas note id=n-change path=leela/blocks/canvas/change.py-->
`coverage` is the comparison. `matched` is a claim the diff confirms. `unmet` is a claim with
nothing behind it. `unclaimed` is a file that moved with no claim on it. `review` is the literate
diff, and it built this page. For each file it emits the hunks, then every brick citing that path.
A file id is its basename, or its whole path when two files share one basename. `place_diff` is the
other half. It fills a slot with one brick a file.
<!--/canvas-->

<!--canvas note id=n-triage path=leela/blocks/canvas/triage.diff-->
A real diff. A test of the literate page reads hunks from this file, not from a string in the
test. Every `review` test shares it.
<!--/canvas-->

<!--canvas note id=n-lit path=leela/blocks/canvas/lit.py-->
The renderer folds anything longer than a phone screen. It writes no script. The fold is
`<details>`, and the page works with JavaScript off. A diff body scrolls sideways inside its
own box. A long line never widens the page. Past `DIFF_CAP` lines a hunk ends in a count. One
committed HTML page had otherwise taken this review to three megabytes.
<!--/canvas-->

# The routes and the client

<!--canvas bundle id=u-web title="What the browser asks for, and what answers"
     goal=g2
     contributes="the block being safe to serve"
     covers="t2,t3,t4"
     paths=leela/blocks/canvas/app.py,leela/blocks/canvas/ui.py,leela/blocks/canvas/canvas.js,leela/blocks/canvas/md.js,leela/blocks/canvas/menu.js,leela/blocks/canvas/gutter.js,leela/blocks/canvas/format.js,leela/blocks/canvas/wire.js,leela/blocks/canvas/helper.js,leela/blocks/canvas/canvas.css,leela/blocks/canvas/helper.py,leela/blocks/canvas/explain.py,leela/blocks/canvas/explain.md,leela/blocks/canvas/ste.md,leela/blocks/canvas/bricks.py,leela/skills/*,leela/static/lee-canvas.js,tools/build_ide_js.py,tools/canvas_spike.py
     refs=pkg:shalya-->
Every route that took a path read, ran or overwrote whatever it named. A frame had this page's
origin. The markdown writer let a URL close an attribute. And the wheel excluded the files the client
read at request time.
<!--/canvas-->

<!--canvas note id=n-app path=leela/blocks/canvas/app.py-->
`canvas_path` is the one gate. Every source and destination passes it, including `save`'s `to`
and `page`'s `out`. With a folder open, `fs._check` decides. With none, which is the spike and the
tests, the canvas folder decides. `_runs_code` is the trust line. It gates what evaluates, not
what edits. You can still write in an untrusted document.
<!--/canvas-->

<!--canvas note id=n-md path=leela/blocks/canvas/md.js-->
`cvEsc` escaped `&<>` only. A quote in a URL or a link label closed the attribute and opened one
of the author's choosing. It escapes quotes too now. `cvUrl` passes http, https, mailto, a relative
path, an anchor and a raster data URL. A `javascript:` scheme and a data SVG do not pass.
<!--/canvas-->

<!--canvas note id=n-canvasjs path=leela/blocks/canvas/canvas.js-->
Both frames are `sandbox=allow-scripts`. Nothing grants `allow-same-origin`. A component gets an
opaque origin. It cannot read this page's DOM, cookies or routes. A message speaks for the brick
whose frame sent it, never for the id it claims. Blur records and one chain writes. Clicking Save
cannot race the blur it causes. Untouched prose never returns from the DOM.
<!--/canvas-->

<!--canvas note id=n-ui path=leela/blocks/canvas/ui.py-->
`/canvas/js` concatenated `leela/blocks/canvas/*.js` per request. The wheel excludes exactly those
files, and an installed Leela served an empty canvas. `bundle` reads the committed
`lee-canvas.js`. It falls back to the modules only in a source tree.
<!--/canvas-->

<!--canvas note id=n-build path=tools/build_ide_js.py-->
`OWN_BUNDLE` names the blocks that serve their own page. The build writes and commits each one, like
the IDE's three. The order comes from that block's own `ui.FILES`, written down once.
<!--/canvas-->

<!--canvas note id=n-helper path=leela/blocks/canvas/helper.py-->
`helper.js` never sent `model`. Every ask reached the scripted stand-in, whatever the workspace
had configured. The server picks now. `Agentic.turn` never closed, and the canvas tools stayed on
the agent's registry. It closes in a `finally` and restores the tool list it snapshotted.
<!--/canvas-->

<!--canvas task id=t2 status=done owner=me-->
Gate every route's paths, both source and destination.
<!--/canvas-->

<!--canvas task id=t3 status=done owner=me-->
Sandbox both frames. Refuse a URL or an attribute that carries script.
<!--/canvas-->

<!--canvas task id=t4 status=done owner=me-->
Ship the client in the wheel, and hold it with a test against a built one.
<!--/canvas-->

# The brick library

<!--canvas bundle id=u-brk title="A component comes from an installed library"
     goal=g
     contributes="the palette, with no second process"
     paths=extensions/bricks/*,extensions/bricks/leela_bricks/*,tests/fixtures/*,docs/bricks.md
     refs=doc:docs/bricks.md-->
The palette used to be an HTTP call to a second server. It is an entry-point group now. A library
answers four questions. Its manifest, one brick, that brick's wiring, and its own routes.
<!--/canvas-->

<!--canvas note id=n-bricks path=leela/blocks/canvas/bricks.py-->
A library is any module with `manifest()` and `find(name)`. There is no base class and nothing to
register. Leela reads `manifest` in process. The palette needs no second server.
<!--/canvas-->

<!--canvas note id=n-libbricks path=extensions/bricks/leela_bricks/bricks.py-->
`needs` reads the imports out of the wiring text. A component cannot claim a dependency its code
does not import. It cannot hide one it does import. `LIB` comes from `__name__`. Renaming the
package renames every `src` it serves. That is why these eight files extracted with no code
change.
<!--/canvas-->

# The seams

<!--canvas bundle id=u-seam title="What Leela adds to pullup and kunda, and nothing more"
     goal=g2
     contributes="one spelling per name"
     covers="t5"
     paths=leela/blocks/runtime/*,leela/blocks/pipelines/*,leela/blocks/drive/*,leela/blocks/workflows/*,leela/blocks/agent/models.py,leela/blocks/debug/*,leela/blocks/editor/app.py,leela/blocks/search/search.py,leela/blocks/vars/app.py,leela/blocks/vault/jobs.py,tests/test_seams.py,tests/test_pipelines.py,tests/test_workflows.py,tests/test_git_folder.py,pyproject.toml,uv.lock
     refs=pkg:kunda,pkg:pullup-->
`test_seams.py` guarded eleven libraries. It did not guard kunda or pullup, the two Leela composes
most. Eight reaches into their private names went uncounted. This is the widest change in the
branch. It reaches blocks with nothing to do with a canvas.
<!--/canvas-->

<!--canvas note id=n-support path=leela/blocks/runtime/support.py-->
It re-exported almost the whole of kunda's support half. `core/envs.py` went straight to kunda for
three of the same names. `clean_env` had two spellings, depending on which module you read. The
module keeps `LEELA_PY`, the one name Leela renames. Fifteen call sites in ten modules now import
from kunda directly.
<!--/canvas-->

<!--canvas note id=n-kernels path=leela/blocks/runtime/kernels.py-->
Two private kunda imports were unused, and the branch drops them. The six load-bearing ones sit in `ALLOWED`
in the seams test. Each one names the library that would have to open it.
<!--/canvas-->

<!--canvas note id=n-pipe path=leela/blocks/pipelines/pipelines.py-->
A justified adapter that also re-exported two dozen names. It publishes only what Leela adds. A
caller that wants `default_steps` or `resolve_script` asks pullup.
<!--/canvas-->

<!--canvas note id=n-wf path=leela/blocks/workflows/wfbuild.py-->
Nine lines of pure pass-through, deleted. Its two callers import from `pullup.wfbuild`.
<!--/canvas-->

<!--canvas note id=n-drive path=leela/blocks/drive/app.py-->
The code built a `Drive` and then told it which interpreter to use. Pullup had already resolved
commands against Leela's own. A `Drive` now takes the interpreter it will run under. A changed
interpreter builds a new `Drive` instead of mutating the live one.
<!--/canvas-->

<!--canvas note id=n-lock path=uv.lock-->
The lock recorded mdhtml 0.1.36 against a `>=0.1.38` requirement. A frozen desktop export would
have failed.
<!--/canvas-->

<!--canvas task id=t5 status=done owner=me-->
Reduce each seam to what Leela adds, and guard kunda and pullup like the rest.
<!--/canvas-->

# The tests

<!--canvas bundle id=u-test title="What the suites hold, and what running them found"
     goal=g2
     contributes="a suite that finishes"
     covers="t6"
     paths=tests/test_canvas.py,tests/test_canvas_doc.py,tests/test_core.py,tests/test_packaging.py,tests/test_projects.py,tests/test_runtime.py,tests/test_agent.py,tests/test_agent_slow.py,tests/test_kernels_ipymini.py,tests/test_web_slow.py,tests/blocks/test_agent_threads.py,tests/routes.txt,leela/blocks/agent/threads.py
     refs=pkg:kunda,pkg:shalya-->
The kernel killed `pytest -m slow` a third of the way in. It reported nothing. Not the tests it
could never run, and not the ones above them that pass in seconds. Two suites resolved a real local
model, because the machine happened to hold its bundle in the cache.
<!--/canvas-->

<!--canvas note id=n-webslow path=tests/test_web_slow.py-->
The harness built engines through `Routing`. No engine sat at 290MB. The first took it to 871MB
and the second to 3.1GB. Each streaming test then added two to three gigabytes. The Python heap
stayed flat, which puts the growth inside the engines and outside Python. A browser test drives the
painting and the panels. It needs no model. Every workspace gets the scripted backend. 80 tests,
4m29s, 967MB peak. One test also read a notebook out of an untracked folder. A real kernel had
written that folder into the checkout. Three more tests counted the buttons in a bar. The bar now holds a
fourth.
<!--/canvas-->

<!--canvas note id=n-agentslow path=tests/test_agent_slow.py-->
The gate asked whether the cache held the model bundle. It never asked whether the machine could
hold it. One engine climbs from 123MB to 12.2GB. A run that reached 13.4GB died with 3.1GB nominally
free. The number is 16000, and the comment says where it came from.
<!--/canvas-->

<!--canvas note id=n-ipymini path=tests/test_kernels_ipymini.py-->
Five monkeypatches aimed at Leela's re-exports, not at the name the library reads. `kunda.pool`
imports `Kernel` under its own roof. `_class_for` reads it there. So the pool ignored the fakes.
One test failed. One hung on a real kernel that never signalled. A sixth fake was missing the
`touch` the pool calls before `start`. The file went from hanging to 17 passing in 11 seconds.
<!--/canvas-->

<!--canvas note id=n-agent path=tests/test_agent.py-->
The test called `read_only(tools)` bare and expected it to drop the delegate tools. Shalya moved
that to a `block=` the caller passes. Both places in Leela pass `NO_SUB`. The test was red while
the behaviour was right. It now tests what `delegate` hands a sub-agent. It lives here, not in a
suite that needs a local model.
<!--/canvas-->

<!--canvas note id=n-threads path=tests/blocks/test_agent_threads.py-->
`TurnRunner._reap` read `Thread.is_alive` alone. That is False before a thread starts, and False
after it ends. `start` publishes the pending turn and only then starts its worker. So a request
arriving in that window reaped a live turn and won acceptance. Two tests hold each half.
<!--/canvas-->

<!--canvas note id=n-reap path=leela/blocks/agent/threads.py-->
The fix reads `ident` first. A worker with no `ident` never started, and `_reap` leaves it alone.
A worker that started and then stopped has finished. Only then does the turn retire.
<!--/canvas-->

<!--canvas note id=n-canvastests path=tests/test_canvas.py-->
The path gate, the sandbox, the URL rules, the retired name, the single wiring run and the trust
line. Then six tests against a real kernel. Another pid, an interrupted loop with the namespace
intact, and recovery after `os._exit`.
<!--/canvas-->

<!--canvas task id=t6 status=done owner=me-->
Make `pytest -m slow` finish, and fix what running it found.
<!--/canvas-->

# The prose

<!--canvas bundle id=u-prose title="Every page scored, and the English fixed"
     goal=g
     contributes="the English a reviewer reads"
     covers="t7"
     paths=README.md,docs/*.md,examples/canvas/*,docs/screenshots/*,media/*,.gitignore
     refs=pkg:slopometer,pkg:fastaistyle,doc:leela/blocks/canvas/ste.md-->
`slopometer` scores a page against the reference-prose rules. `chkstyle` scores Python against
fastai's. `ste.md` already held the rules. `explain.md` handed them to the model that drafts a
snippet. A drafted sentence met them. A hand-written one did not.
<!--/canvas-->

<!--canvas note id=n-readme path=README.md-->
12.9 to 2.9. Three patterns carried most of the weight. A sentence that states a thing and then
restates its opposite. A closing line that reverses the one before it. A passive clause that drops
the doer. `ste.md` bans all three by name.
<!--/canvas-->

<!--canvas note id=n-session path=docs/session.canvas.md-->
The same document read as a canvas: the goals, the plan, the basket, the change and the diff. The
worst page on the branch fell from 26.8 to 2.5 and four pages now score zero.
<!--/canvas-->

<!--canvas task id=t7 status=done owner=me-->
Score every page with slopometer, and rewrite the prose that fails ASD-STE100.
<!--/canvas-->

# The numbers

<!--canvas data id=n-tally-->
files = 143
insertions = 13262
deletions = 289
tests = 2045
slow_tests = 139
review_findings_closed = 17
worst_page_before = 26.8
worst_page_after = 2.5
<!--/canvas-->

<!--canvas ask id=q1 scope=doc budget=40000-->
Name the change here you would push back on, and say what you would want instead.
<!--/canvas-->
