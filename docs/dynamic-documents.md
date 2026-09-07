# Dynamic documents

A goal like "increase procurement productivity by 10%" is neither a coding task nor a writing task. Reaching it takes five steps. Frame the measure. Collect what the team already knows. Pull an extract apart until the numbers say something. Prototype the one rule that might work. Write the recommendation. Today those five steps live in five tools. The notebook holds the extract. The deck holds the recommendation. The research sits in tabs, and the plan sits in a tracker. Only a person carries context between them.

Leela already holds four of the five. It has the kernel, the files, the vault, the agent and the notebook. It lacks a document that follows the work rather than a script.

Two branches have gone at that. `claude/dynamic-document-canvas-ohgfud` built the file and the runtime, wired into Leela as a block. `leela/blocks/canvas` builds the context engine on that file. This document is the design both halves answer to.

## What a flat list cannot be

Every notebook is one flat list. Its prompt cells read from the top of the document down to the cell being asked, which `Notebook.context` does in `leela/blocks/nb/nb.py`. The list works because it is the order the work happened in. Every cell above yours is work you did before, and the model should probably know it.

That rule dies the moment the document holds more than one line of work. Framing the goal, reading the audit, cleaning the extract and drafting the recommendation are four strands, not four consecutive steps. Ask the recommendation prompt to read everything above it and it reads three failed attempts at a groupby. Ask it to read nothing and you are pasting again.

The audit is the case that makes it concrete. It belongs in the context of the synthesis question near the top, and in the context of the risk question near the bottom, and in nothing between them. Position cannot express that. Nothing about where a brick sits says which questions it answers.

## The file

`*.canvas.md`. Prose is prose. A brick markdown cannot show is a fence, `` ```canvas code id=c1 ``. A brick whose body is markdown a plain renderer should still show is a comment wrap, `<!--canvas goal id=goal-->`. Headings are the document's regions. Frontmatter carries the title.

This is the canvas branch's format. A plan, a design doc and a set of research clippings are prose, and nobody reads or reviews prose held in JSON. Markdown gives three things. `git diff` shows the argument changing rather than a re-serialised tree. The document opens in any reader. The design doc and the code that tests it stay in one file.

Reading it works line by line rather than by one regex over the file. A canvas fence inside a longer markdown fence is an example of a brick and not a brick. A document about canvases therefore parses as a document. This rule matters, because a `source` brick holding a clipped page is where quoted markup arrives.

## What AFFiNE contributes

AFFiNE's [BlockSuite](https://blocksuite.io) puts one block tree behind two views. A document is a list of blocks, each with a flavour named `namespace:name`. Page mode reads the tree top to bottom. Edgeless mode reads the same blocks off a surface that gives them coordinates, frames that group them, and connectors that join them. Neither view owns the document.

Two of those ideas belong here, and the code replaces the third.

The named kind belongs. A notebook cell has three types, because a notebook holds three kinds of thing. A document that holds a goal, a task, a clipping and a chart needs a name for each. A `goal` brick carries `measure`, `baseline`, `target` and `by`, which holds a measure better than a markdown cell and a convention.

The two views belong. The list is the right way to read finished work, and the only way to review it. The canvas suits work in progress, because unfinished thinking is not linear. `prop x` and `prop y` are the only trace the canvas leaves in the file. A document nobody has laid out is therefore still complete, and `arrange` places an unopened document on a canvas.

The connector does not belong. On AFFiNE's canvas a person draws a connector by hand, and a diagram kept beside the code goes wrong. The code already states the graph.

## Upstream is read off the code

`defs_of` and `reads_of` walk the AST. Whichever brick binds a name owns it. Which bricks a brick reads from is therefore a fact about the document rather than a drawing over it. `order` runs code in dependency order, and `upstream` answers what one question is downstream of.

Three things extend it where the AST cannot see.

A question anchors on the brick above it. "Fix that" means that brick and everything it reads, which is what a person means and what `scope=upstream` on a question should give them. `anchor=<id>` overrides it.

A name a question puts in backticks is a name it reads. Writing `` `triage` `` in a question pulls in the brick that defines `triage` and its own upstream. Backticks around an identifier already mean "this one", and nobody has to learn a new rule.

`supports=`, `refutes=` and `blocks=` name a relation between bricks that no AST can find. That is where a clipping supporting a claim goes, and it is the only hand-drawn edge left.

## Context is the design

Every question carries a rule, and `canvas.context.resolve` turns that rule into the exact list of items the turn will send.

```
scope=region                 none | page | region | upstream | doc
pin s-audit                  always in; also file:, vault:, url:, var:, sel:
mute n-cap                   always out
budget=12000                 characters
```

`page` is the notebook's own behaviour, kept because it is right for a document being read as a document. `region` is the section you are working in. `upstream` is the dataflow. The risk question therefore reads the backtest, the rule, the split and the extract. It reads none of the four tasks sitting beside them.

`resolve` is pure, and it returns items rather than a string. One list builds the prompt and draws the panel. The panel shows every brick in the basket, what put it there, what it costs in characters, and a running total against the budget. Bricks in the basket glow on the canvas. Click a row to mute it, and the glow goes out. The panel therefore shows exactly what the model gets.

Under a budget, the goal and the pins survive. A `context=discard` brick goes first, then the oldest ordinary one, which is what notebook cells already do through `context_mode`. `resolve` clips and marks a pin larger than the whole budget rather than dropping it. A pin that vanishes silently costs a reader more than one that arrives short.

`render` emits `<cell id= type= compact= why= region=>`. That is Leela's own notebook markup, chosen on purpose. Ramabana's `compact_notebook_context` sheds elements matching exactly that pattern when a prompt overflows the window. A document that rendered anything else would carry a budget with nothing underneath it. An oversized turn would then fail at the provider rather than shed a research clipping.

## No stored outputs

A canvas keeps no outputs. Opening one runs it, and a code brick's value comes from the live namespace.

That deletes the whole staleness problem rather than solving it. There is no hash to compare, no `output_hash` to carry, and no case where a chart is correct about a dataframe somebody has since reloaded. It also deletes the merge conflicts that notebook outputs cause, which is most of them.

It costs two things: a document that does not open instantly, and one nobody can read offline with its numbers in it. `bind` answers the second cost. A `data` brick renders a sentence from live values, and the prose therefore never carries last month's numbers.

## A boundary that is a unit of change

A region groups bricks for reading. A `bundle` brick claims its region as one change, and that is the difference between a Miro frame and something worth having. The boundary names a goal, owns a set of files, holds the tasks and the prose and the code together, and is the thing a reviewer opens.

Four parts, and the last one is the point.

`goal=<id>` is the value link. A change serves a goal, and the goal carries a measure and a target. `contributes=` says in words what this change is worth against that target. Leela invents no arithmetic. A share of a ten-point target is a judgement, and pretending otherwise would put a fake number in a pull request.

The files come from the code. A code brick marked `#|export` writes a module. That module is the change, and `modules()` already knows the path. `paths=` adds what the bricks do not generate: tests, config, a migration. Deriving first matters because a list maintained by hand is a list that goes stale, and a stale claim is worse than no claim.

`refs=` attaches packages, files and other documents for review. It uses the same `pkg:`, `file:`, `doc:` vocabulary as a context pin. Attaching something for a human reviewer therefore also puts it within the model's reach. One vocabulary, two readers.

`coverage(doc, changed)` holds the claim against the diff, which turns the boundary into a check. Per bundle it reports `matched` and `unmet`, a claimed file the diff never touched. Across the document it reports `unclaimed`, a changed file no bundle explains. No diff tool can produce `unclaimed`, because only the document knows what the change promised to do.

## The value view

`value(doc, changed)` is the third document. It lists every goal, and every change serving it, each with its state and a line on how much of it has finished.

Leela derives the state. A change reaches `blocked` when one of its tasks blocks. It reaches `done` when every task reaches `done` and every claimed file moved. It reaches `doing` when some of either has. Nobody sets these as a field, because a status somebody must remember goes stale. One case needs care. An absent diff is no evidence about files, and it must not read as evidence against them. Otherwise a finished change reports as untouched work whenever you ask without a diff.

The view exists for two findings, and neither appears anywhere else in the document.

A change serving no goal appears under `Serving no goal`. Somebody is doing work that nothing in the plan asked for.

A goal nothing serves says so under its own heading. A goal with no change against it reads the same as a goal on track, until the date arrives.

The tally at the end lists every change by state, and every changed file no bundle claims. The question below it pins every goal.

## Review is another canvas

`review(doc, bundle_id, diff)` builds a document: the goal, what the change contributes, the prose, the tasks, the questions asked inside the change with their recorded answers, one `diff` brick per file, the attachments, the coverage checks, and a question with the goal already pinned.

It is a `Doc`. It therefore draws in both views through the same renderer, keeps the outline, and keeps the context basket. Nothing about the review view is a second implementation of anything, and a question asked inside a review has the whole change in scope.

That also answers whether this replaces Leela's git view. It does not. The existing view is for line-level work: staging, hunks, blame, conflicts. This is for the question a diff cannot answer, which is whether the change does what the goal said. `canvas.change.hunks` takes unified diff text. Whatever produces the diff, `gheasy` included, can feed it.

Leela builds a review per request and never writes it back. A diff is a fact about a commit range, not part of the document.

## The literate page

`lit` writes one document as one column for a phone. `paint` draws a canvas for someone working in it; this draws the same document for someone reading it on the way to a meeting. No JavaScript, no other requests, both colour schemes, and everything long folded.

Writing this repository's own change as a canvas document, and rendering it with `lit`, found four things the design was missing. That is the argument for dogfooding rather than a claim about the tool.

A `snippet` brick cites code instead of holding it. `snip` reads the file the brick names and finds the symbol in it, decorators included. A literate page wants the function that does the work rather than the whole diff. A copy pasted into prose goes stale. The whole page rests on this primitive, and nothing before it could do the job.

A comment wrap had to fit on one line. A bundle carries a goal, a contribution, a covers list, a paths list and a refs list. One line therefore ran 300 characters wide in a file a person edits. The reader now joins lines until it finds `-->`.

Two headings with only prose between them became one region. Prose accumulates into one text brick, and the reader took only its first heading. The second heading never started a section. The reader now splits prose at every heading, skipping headings inside a plain fence.

A heading and the prose under it are one brick, and the page renderer took the heading as a section title and dropped the brick. Every paragraph under a first-level heading disappeared. It now trims the heading and keeps the rest.

`review` also changed. It now places the prose that cites a path next to that file's hunks. A document that explains its files therefore produces a literate diff with no further work, which is what the exercise was for.

`tools/make_change_page.py` builds the page. `docs/change.canvas.md` is the source, and `media/canvas-change.html` is the output. `--prompts FILE` writes the drafting prompts and stops; `--answers FILE` puts a model's answers back.

## Where the prompts live

`lit` draws and `explain` writes. Three places hold the three parts, and the split is the point.

The register lives in ramabana. `write_docs` is a pyskill, and `rule_text` reads it through `shalya.skills.discover`. `CLAUDE.md` says no repository holds a copy of a writing skill, and a prompt with one pasted into it is that copy. `rule_text` therefore raises when the skill is missing rather than falling back. A silent fallback puts the wrong register on the page, and nobody notices.

The task lives in the package. `explain.md` is the template and `ste.md` states the ASD-STE100 limits for this output. Neither restates `write_docs`. `ste.md` is nine lines, and every one of them is an output constraint rather than a rule about English.

The prose lives in the document. `explain` writes each answer into the brick body and marks it `wrote=ai`. A drafted sentence is therefore in `git diff`, a reviewer can see which sentences a model wrote, and editing one is editing the document. `explain` leaves a brick that already has a body alone, because a sentence a person wrote is the one worth keeping.

The prompt's context comes from `resolve`, which is the same basket a question in the document would send. One context engine serves the reader and the drafter, and the panel that already exists can therefore inspect a prompt.

`ask(prompt, brick)` is the host's. Nothing in `canvas` imports a model. Leela passes its own assistant. `capture` and `replay` stand in where no model is reachable: `capture` writes the prompts out, `replay` answers from a file.

## Getting work back out

Nothing here is a new place for work to get stuck.

`to_ipynb` writes a real notebook, with questions in the `metadata.leela` shape `Cell.nbcell` already uses. Leela therefore opens it, and the prompts are still prompts. `from_ipynb` reads it back and migrates a notebook that was never a document. `to_report` writes the document with the canvas taken off. `modules` writes the code bricks marked `#|export` in dependency order, which is the "extract the software" half of the goal.

## The prototypes

The package generates both, and nobody draws them by hand. They therefore show what `resolve` and `arrange` actually do.

- `media/canvas-procurement.html` is the document on its own. The header toggles page and canvas. The right panel is the context basket for whichever question is selected, with the scope, the budget, the per-item cost, and the markup the model reads.
- `media/canvas-in-leela.html` is the same document inside Leela's chrome: tab strip, outline, the agent and variables panes, the status bar.

Both carry three documents behind one toggle: the document, the review of one change, and the value view. `page` and `canvas` switch how the loaded document draws.

`media/procurement-example.canvas.md` is the document itself, and a reader should read it as a file.

## Where the two branches meet

The canvas branch owns the format, the parser, the dataflow, the reactive runtime and the embedded components. It also owns the eight `canvas_*` tools the agent gets when a canvas opens. `canvas` owns the context engine, the three brick kinds a plan needs, and the second view.

They are one thing, not two. `blocks/canvas/doc.py` reimplements the canvas branch's scanner and dataflow, which lets the package stand alone while the shape is still moving. That fork should not survive a decision. Merging leaves one parser in whichever half survives, and the other half imports it.

The canvas branch has two things this does not. It has the reactive runtime, and it has the agent editing the document through tools rather than answering into a brick. This side has two things the canvas branch does not: a context rule a person can see and change, and a goal.

## What is not decided

**Nothing, on this one.** The merge is complete. `leela/blocks/canvas/doc.py` is one file: the format and the
AST dataflow from the canvas branch, with the plan kinds, the regions, the pins and mutes, the
prose splitting and the geometry from this one. The class is `Canvas`. `index` returns `None` for a
brick that is not there, because `ops._at` and `Ask.near` both read that. A brick body keeps its
final newline, because the format keeps code exactly.

**What the browser half draws.** The eight routes answer. `tools/canvas_proto` shows the canvas,
the basket panel and the review as a standalone page, and nothing in `lee-ide.js` calls the routes
yet. That prototype is a tool, not product code, which is why it is not in the block.

**Whether the second view is version one.** The basket, the goal and the plan kinds work in a
linear document and are most of the value. `arrange` plus `prop x` is the whole of the canvas, and
this stays cheap either way.

**What the agent may write.** The canvas branch already answers this with eight tools and a skill
pushed onto the agent while a canvas is open. Whether the agent may also add bricks, rebind ports
and reorganise a document is a larger claim.

## What integration costs

A review of the standalone design against the repository found the seam work, and none of it is one line. The canvas branch has done some of it already.

`Assistant.compose` in Ramabana wraps any context in `<notebook path=...>`, and the briefing tells the model to call `notebook_cells` on that path. A `.canvas.md` path handed to `notebook_cells` reaches `Notebook.load` on text that is not nbformat. Ramabana needs to know a second document kind, or Leela needs to hand it a path it can honour.

`workspace.py` decides `Tab.kind` by suffix, with no extension point, and `tab_state`, `tab_disk`, `tab_buffer`, `cwd_for` and `kernel_key` each need a branch. `write_text_at` special-cases `.ipynb` so a rollback does not put jupytext markers into JSON. `DocStore` holds notebooks only. `blocks/refactor` treats anything not `.ipynb` as text to rewrite, which would rename identifiers inside prose; a markdown file makes that more likely rather than less.

The format answers two things that code does not. Git conflicts on prose are ordinary text conflicts, which is what markdown buys. Undo granularity for a canvas drag is a stream of `prop x` writes, and a drag that writes only on release is one edit.

Nothing anywhere answers one of them. `inline_ai` is one conversation with one `_approval_target`, while a canvas invites running two questions at once.
