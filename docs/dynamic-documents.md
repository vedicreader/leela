# Dynamic documents

A goal like "increase procurement productivity by 10%" is not a coding task, and it is not a writing task either. Getting there means framing the measure, collecting what is already known, pulling an extract apart until the numbers say something, prototyping the one rule that might work, and writing the recommendation. Today those live in five tools. The notebook holds the extract, the deck holds the recommendation, the research sits in tabs, the plan sits in a tracker, and the only thing that crosses between them is a person carrying context in their head.

Leela already holds four of the five. It has the kernel, the files, the vault, the agent and the notebook. What it does not have is a document shaped like the work rather than like a script.

Two branches have gone at that. `claude/dynamic-document-canvas-ohgfud` built the file and the runtime, wired into Leela as a block. `packages/pata` builds the context engine on that file. This document is the design both halves answer to.

## What a notebook cannot be

A notebook is a list. Its prompt cells read from the top of the document down to the cell being asked, which is `Notebook.context` in `leela/blocks/nb/nb.py`, and it works because the list is the order the work happened in. Every cell above yours is something you did before, so it is something the model should probably know.

That rule dies the moment the document holds more than one line of work. Framing the goal, reading the audit, cleaning the extract and drafting the recommendation are four strands, not four consecutive steps. Ask the recommendation prompt to read everything above it and it reads three failed attempts at a groupby. Ask it to read nothing and you are pasting again.

The audit is the case that makes it concrete. It belongs in the context of the synthesis question near the top, and in the context of the risk question near the bottom, and in nothing between them. Position cannot express that. Nothing about where a brick sits says which questions it answers.

## The file

`*.canvas.md`. Prose is prose. A brick markdown cannot show is a fence, `` ```canvas code id=c1 ``. A brick whose body is markdown a plain renderer should still show is a comment wrap, `<!--canvas goal id=goal-->`. Headings are the document's regions. Frontmatter carries the title.

This is the canvas branch's format and it is the right one. A plan, a design doc and a set of research clippings are prose, and prose in JSON is prose nobody will read or review. Markdown means `git diff` shows the argument changing rather than a re-serialised tree, means the document opens in anything, and means the design doc and the code that tests it are the same file rather than two files that disagree.

Reading it works line by line rather than by one regex over the file. A canvas fence inside a longer markdown fence is an example of one, not one, so a document about canvases parses as a document. That is not a nicety. A `source` brick holding a clipped page is exactly where quoted markup arrives.

## What AFFiNE contributes

AFFiNE's [BlockSuite](https://blocksuite.io) puts one block tree behind two views. A document is a list of blocks, each with a flavour named `namespace:name`. Page mode reads the tree top to bottom. Edgeless mode reads the same blocks off a surface that gives them coordinates, frames that group them, and connectors that join them. Neither view owns the document.

Two of those ideas earn their place here, and one is replaced by something better.

The named kind earns it. A notebook cell has three types because a notebook has three kinds of thing in it. A document that holds a goal, a task, a clipping and a chart needs the names for them, and a `goal` brick carrying `measure`, `baseline`, `target` and `by` is a better home for a measure than a markdown cell with a convention.

The two views earn it. The list is the right way to read finished work and the only way to review it. The canvas is the right way to hold work in progress, because unfinished thinking is not linear. `prop x` and `prop y` are the only trace the canvas leaves in the file, so a document nobody has laid out is still complete, and `arrange` places one that has never been opened on a canvas.

The connector does not earn it. On AFFiNE's canvas a connector is drawn by hand, and a diagram maintained beside the code is a diagram that goes wrong. The code already states the graph.

## Upstream is read off the code

`defs_of` and `reads_of` walk the AST. A name is owned by whichever brick binds it, so which bricks a brick reads from is a fact about the document rather than a drawing over it. `order` runs code in dependency order, and `upstream` answers what one question is downstream of.

Three things extend it where the AST cannot see.

A question anchors on the brick above it. "Fix that" means that brick and everything it reads, which is what a person means and what `scope=upstream` on a question should give them. `anchor=<id>` overrides it.

A name a question puts in backticks is a name it reads. Writing `` `triage` `` in a question pulls in the brick that defines `triage` and its own upstream. Backticks around an identifier already mean "this one", so nothing new has to be learned.

`supports=`, `refutes=` and `blocks=` name a relation between bricks that no AST can find. That is where a clipping supporting a claim goes, and it is the only hand-drawn edge left.

## Context is the design

Every question carries a rule, and `pata.context.resolve` turns that rule into the exact list of items the turn will send.

```
scope=region                 none | page | region | upstream | doc
pin s-audit                  always in; also file:, vault:, url:, var:, sel:
mute n-cap                   always out
budget=12000                 characters
```

`page` is the notebook's own behaviour, kept because it is right for a document being read as a document. `region` is the section you are working in. `upstream` is the dataflow, so the risk question reads the backtest, the rule, the split and the extract, and reads none of the four tasks sitting beside them.

The panel is the point. `resolve` is pure, it returns items rather than a string, and the same list that builds the prompt draws the panel: every brick in the basket, what put it there, what it costs in characters, and a running total against the budget. Bricks in the basket glow on the canvas. Click a row to mute it and the glow goes out. There is no hidden step between what you can see and what the model is handed.

Under a budget, the goal and the pins survive. A `context=discard` brick goes first, then the oldest ordinary one, which is what notebook cells already do through `context_mode`. A pin larger than the whole budget is clipped and marked rather than dropped, because a pin that vanishes silently is worse than one that arrives short.

`render` emits `<cell id= type= compact= why= region=>`. That is Leela's own notebook markup, and it is deliberate. Ramabana's `compact_notebook_context` sheds elements matching exactly that pattern when a prompt overflows the window. A document that rendered anything else would have a budget with nothing underneath it, and an oversized turn would fail at the provider rather than shed a research clipping.

## No stored outputs

A canvas keeps no outputs. Opening one runs it, and a code brick's value comes from the live namespace.

That deletes the whole staleness problem rather than solving it. There is no hash to compare, no `output_hash` to carry, and no case where a chart is correct about a dataframe that has since been reloaded. It also deletes the merge conflicts that notebook outputs cause, which is most of them.

What it costs is a document that does not open instantly and one that cannot be read offline with its numbers in it. `bind` is the answer to the second: a `data` brick renders a sentence from live values, so the numbers in the prose are never the numbers from last month.

## A boundary that is a unit of change

A region groups bricks for reading. A `bundle` brick claims its region as one change, and that is the difference between a Miro frame and something worth having. The boundary names a goal, owns a set of files, holds the tasks and the prose and the code together, and is the thing a reviewer opens.

Four parts, and the last one is the point.

`goal=<id>` is the value link. A change serves a goal, the goal carries a measure and a target, and `contributes=` says in words what this change is worth against it. No arithmetic is invented: a share of a ten-point target is a judgement, and pretending otherwise would put a fake number in a pull request.

The files come from the code. A code brick marked `#|export` writes a module, so the module is the change and `modules()` already knows the path. `paths=` adds what the bricks do not generate: tests, config, a migration. Deriving first matters because a list maintained by hand is a list that goes stale, and a stale claim is worse than no claim.

`refs=` attaches packages, files and other documents for review. It uses the same `pkg:`, `file:`, `doc:` vocabulary as a context pin, so attaching something for a human reviewer also makes it reachable by the model. One vocabulary, two readers.

`coverage(doc, changed)` holds the claim against the diff, and it is what turns the boundary from decoration into a check. Per bundle it reports `matched` and `unmet`, a claimed file the diff never touched. Across the document it reports `unclaimed`, a changed file no bundle explains. That second one is the half a reviewer never sees coming, and no diff tool can produce it, because only the document knows what the change was supposed to be.

## The value view

`value(doc, changed)` is the third document: every goal, and every change serving it, each with the state it is in and a line saying how much of it has landed.

State is derived. `blocked` if any task in the change is blocked, `done` when every task is done and every claimed file moved, `doing` when some of either has. Nothing here is a field anybody sets, because a status that has to be remembered is a status that lies. One case needed care: no diff is no evidence about files, and it must not read as evidence against, or a finished change reports as untouched work the moment you ask without a diff.

Two negatives are the reason the view exists, and neither appears anywhere else in the document.

A change serving no goal lands under `Serving no goal`. That is work somebody is doing that nothing in the plan asked for, and it is the honest question to put next to a ten-point target.

A goal nothing is serving says so under its own heading. That is the other half, and it is worse, because a goal with no change against it looks exactly like a goal that is going fine until the date arrives.

The tally at the end lists every change by state and every changed file no bundle claims, and the question below it has all the goals pinned.

## Review is another canvas

`review(doc, bundle_id, diff)` builds a document: the goal, what the change contributes, the prose, the tasks, the questions asked inside the change with their recorded answers, one `diff` brick per file, the attachments, the coverage checks, and a question with the goal already pinned.

It is a `Doc`, so it draws in both views through the same renderer, keeps the outline, and keeps the context basket. Nothing about the review view is a second implementation of anything, and a question asked inside a review has the whole change in scope.

That also answers whether this replaces Leela's git view. It does not. The existing view is for line-level work: staging, hunks, blame, conflicts. This is for the question a diff cannot answer, which is whether the change does what the goal said. `pata.hunks` takes unified diff text, so whatever produces the diff, `gheasy` included, feeds it.

A review is generated per request and never written back. A diff is a fact about a commit range, not part of the document.

## The literate page

`lit` writes one document as one column for a phone. `paint` draws a canvas for someone working in it; this draws the same document for someone reading it on the way to a meeting. No JavaScript, no other requests, both colour schemes, and everything long folded.

Writing this repository's own change as a `pata` document, and rendering it with `lit`, found four things the design was missing. That is the argument for dogfooding rather than a claim about the tool.

A `snippet` brick cites code instead of holding it. `snip` reads the file the brick names and finds the symbol in it, decorators included. A literate page wants the function that does the work, not the whole diff, and a copy pasted into prose is a copy that goes stale. This is the primitive the whole page is built on, and nothing before it could do the job.

A comment wrap had to fit on one line. A bundle carries a goal, a contribution, a covers list, a paths list and a refs list, so one line was 300 characters wide in a file a person edits. The reader now joins lines until it finds `-->`.

Two headings with only prose between them became one region, because prose accumulates into one text brick and only its first heading was read. The second heading never started a section. The reader now splits prose at every heading, skipping headings inside a plain fence.

A heading and the prose under it are one brick, and the page renderer took the heading as a section title and dropped the brick. Every paragraph under a first-level heading disappeared. It now trims the heading and keeps the rest.

`review` also changed. It now places the prose that cites a path next to that file's hunks, so a document that explains its files produces a literate diff with no further work. That is the feature the exercise was for.

`tools/make_change_page.py` builds the page. `docs/change.canvas.md` is the source, and `media/pata-change.html` is the output.

## Getting work back out

Nothing here is a new place for work to get stuck.

`to_ipynb` writes a real notebook, with questions in the `metadata.leela` shape `Cell.nbcell` already uses, so Leela opens it and the prompts are still prompts. `from_ipynb` reads it back and migrates a notebook that was never a document. `to_report` writes the document with the canvas taken off. `modules` writes the code bricks marked `#|export` in dependency order, which is the "extract the software" half of the goal.

## The prototypes

Both are generated from the package, not drawn by hand, so what they show is what `resolve` and `arrange` actually do.

- `media/pata-procurement.html` is the document on its own. The header toggles page and canvas. The right panel is the context basket for whichever question is selected, with the scope, the budget, the per-item cost, and the markup the model reads.
- `media/pata-in-leela.html` is the same document inside Leela's chrome: tab strip, outline, the agent and variables panes, the status bar.

Both carry three documents behind one toggle: the document, the review of one change, and the value view. `page` and `canvas` switch how whichever one is loaded is drawn.

`media/procurement.canvas.md` is the document itself, and it is meant to be read as a file.

## Where the two branches meet

The canvas branch owns the format, the parser, the dataflow, the reactive runtime, the embedded components, and the eight `canvas_*` tools the agent gets when a canvas opens. `pata` owns the context engine, the three brick kinds a plan needs, and the second view.

They are one thing, not two. `pata.doc` reimplements the canvas branch's scanner and dataflow so the package can stand alone while the shape is still moving, and that is a fork that should not survive a decision. Merging means one parser, in whichever half is kept, with the other importing it.

Two things the canvas branch has that this does not: the reactive runtime, and the agent actually editing the document through tools rather than answering into a brick. Two things this has that it does not: a context rule a person can see and change, and a goal.

## What is not decided

**Where it lives.** The canvas branch is already a Leela block, wired into `NAMES` and `LAYERS` with 418 lines of tests. `packages/pata` imports nothing from Leela. The block is further along; the package is easier to move. One of them has to give.

**Whether `pata` is a package at all.** The context engine is 200 lines. It could be a module inside `leela/blocks/canvas/` and never be a package.

**Whether the second view is version one.** The context basket, the goal and the plan kinds work in a linear document and are most of the value. The canvas is where the layout lives, and `arrange` plus `prop x` is the whole of it, so this is cheap either way.

**Whether a bundle is one pull request or several.** The branch name is `pata/<bundle id>`, which is deterministic, so re-exporting updates the same request. A change that wants two commits has no answer yet.

**What the agent may write.** The canvas branch already answers this: eight tools, and a skill pushed onto the agent while a canvas is open. A question answers into a `reply` brick under it. Whether the agent may also add bricks, rebind ports and reorganise a document is a larger claim, and the tools already allow it.

## What integration costs

A review of the standalone design against the repository found the seam work, and none of it is one line. The canvas branch has done some of it already.

`Assistant.compose` in Ramabana wraps any context in `<notebook path=...>`, and the briefing tells the model to call `notebook_cells` on that path. A `.canvas.md` path handed to `notebook_cells` reaches `Notebook.load` on text that is not nbformat. Ramabana needs to know a second document kind, or Leela needs to hand it a path it can honour.

`Tab.kind` is decided by suffix in `workspace.py` with no extension point, and `tab_state`, `tab_disk`, `tab_buffer`, `cwd_for` and `kernel_key` each need a branch. `write_text_at` special-cases `.ipynb` so a rollback does not put jupytext markers into JSON. `DocStore` holds notebooks only. `blocks/refactor` treats anything not `.ipynb` as text to rewrite, which would rename identifiers inside prose; a markdown file makes that more likely rather than less.

Two things are answered by the format rather than by code. Git conflicts on prose are ordinary text conflicts, which is what markdown buys. Undo granularity for a canvas drag is a stream of `prop x` writes, and a drag that writes only on release is one edit.

One is not answered anywhere. `inline_ai` is one conversation with one `_approval_target`, while a canvas invites running two questions at once.
