# Dynamic documents

A goal like "increase procurement productivity by 10%" is not a coding task, and it is not a writing task either. Getting there means framing the measure, collecting what is already known, pulling an extract apart until the numbers say something, prototyping the one rule that might work, and writing the recommendation. Today those live in five tools. The notebook holds the extract, the deck holds the recommendation, the research sits in tabs, the plan sits in a tracker, and the only thing that crosses between them is a person carrying context in their head.

Leela already holds four of the five. It has the kernel, the files, the vault, the agent and the notebook. What it does not have is a document shaped like the work rather than like a script.

`packages/pata` is that document, and `pata.paint` draws two prototypes of it.

## What a notebook cannot be

A notebook is a list. Its prompt cells read from the top of the document down to the cell being asked, which is `Notebook.context` in `leela/blocks/nb/nb.py`, and it works because the list is the order the work happened in. Every cell above yours is something you did before, so it is something the model should probably know.

That rule dies the moment the document holds more than one line of work. Framing the goal, reading the audit, cleaning the extract and drafting the recommendation are four strands, not four consecutive steps. Ask the recommendation prompt to read everything above it and it reads three failed attempts at a groupby. Ask it to read nothing and you are pasting again.

The audit is the case that makes it concrete. It belongs in the context of the synthesis prompt near the top, and in the context of the risk prompt near the bottom, and in nothing between them. Position cannot express that. Nothing about where a block sits says which questions it answers.

## What AFFiNE contributes

AFFiNE's [BlockSuite](https://blocksuite.io) puts one block tree behind two views. A document is a list of blocks, each with a flavour named `namespace:name`. Page mode reads the tree top to bottom. Edgeless mode reads the same blocks off a surface that gives them coordinates, frames that group them, and connectors that join them. Neither view owns the document. Moving a block on the canvas does not fork it.

Three of those ideas earn their place here.

The flavour is one. A notebook cell has three types because a notebook has three kinds of thing in it. A document that holds a goal, a task, a clipping and a chart needs the names for them, and `pata:goal` is a better home for a measure and a baseline than a markdown cell with a convention.

The two views are the second. The list is still the right way to read finished work, and it is what exports to a notebook and to a report. The canvas is the right way to hold work in progress, because unfinished thinking is not linear and forcing it into a line is what sends people to a whiteboard.

The connector is the third, and it is the one that matters most. On AFFiNE's canvas a connector is decoration. Here it carries a relation: this block reads from that one, this source supports that claim, this open question blocks that task. Once the edges exist, a prompt can ask for what it reads from instead of what sits above it.

## Context is the design

Every prompt block carries a rule, and `pata.context.resolve` turns that rule into the exact list of items the turn will send.

```
scope    none | page | frame | upstream | doc
pins     always in, block ids or file:, vault:, url:, var:, sel:
mutes    always out
budget   characters
```

`page` is the notebook's own behaviour, kept because it is right for a document being read as a document. `frame` is the region you are working in. `upstream` walks the edges backwards, so the risk prompt reads the backtest, the rule, the split and the extract, and reads none of the four tasks sitting beside them.

The panel is the point. `resolve` is pure, it returns items rather than a string, and the same list that builds the prompt draws the panel: every block in the basket, what put it there, what it costs in characters, and a running total against the budget. Blocks in the basket glow on the canvas. Click a row to mute it and the glow goes out. There is no hidden step between what you can see and what the model is handed.

Under a budget, the goal and the pins survive. A `discard` block goes first, then the oldest ordinary one, which is what notebook cells already do through `context_mode`. A pin larger than the whole budget is clipped and marked rather than dropped, because a pin that vanishes silently is worse than one that arrives short.

`render` emits `<cell id= type= compact= why=>`. That is Leela's own notebook markup, and it is deliberate. Ramabana's `compact_notebook_context` sheds elements matching exactly that pattern when a prompt overflows the window. A document that rendered `<block>` instead would have a budget with nothing underneath it, and an oversized turn would fail at the provider rather than shed a research clipping.

## Staleness the graph can see

`Cell.stale` compares a hash of the cell's source against the hash its outputs came from. It catches an edited cell. It cannot catch the other case, which is a chart that is still correct about a dataframe that has since been reloaded.

The edges close that. Each block that runs stamps `ran_at`. `Doc.stale` is true when the local hash disagrees, or when anything reachable backwards has a later stamp. The model sees `stale="true"` on the output either way, so it stops answering about last week's numbers.

This is the first thing the edge graph buys that a list could not, and it is a reason to draw the connectors even for someone who never opens the canvas.

## Getting work back out

Nothing here is a new place for work to get stuck.

`to_ipynb` writes a real notebook, with prompt blocks in the `metadata.leela` shape `Cell.nbcell` already uses, so Leela opens it and the prompts are still prompts. `from_ipynb` reads it back, and migrates a notebook that was never a document. `arrange` then gives that import a canvas, so an `.ipynb` opened as a document arrives laid out rather than in one column.

`to_markdown` writes the narrative for a report. `modules` writes the code blocks marked `#|export` as modules, on nbdev's rules, which is the "extract the software" half of the goal.

`source_text` writes a `# %%` document for git to diff, the same trick `Notebook.source_text` uses. One difference: a body line that would read as a marker is indented on the way out and restored on the way in. Notebooks hold Python, which rarely quotes jupytext. A document holds prose and pasted research, which does.

## The prototypes

Both are generated from the package, not drawn by hand, so what they show is what `resolve` and `arrange` actually do.

- `media/pata-procurement.html` is the document on its own. The header toggles page and canvas. The right panel is the context basket for whichever prompt block is selected, with the scope, the budget, the per-item cost, and the markup the model reads.
- `media/pata-in-leela.html` is the same document inside Leela's chrome: tab strip, outline, the agent and variables panes, the status bar. It answers what this looks like as a tab rather than as a toy.

`media/procurement.pata` is the document itself.

## What is not decided

Four questions, each of which changes what gets built.

**Where the document lives.** `packages/pata` is standalone and imports nothing from Leela. That is the cheap position to hold while the shape is still moving. The alternative is a `leela/blocks/pata/` folder, which buys the routes and the kernel for free and costs a split later.

**Whether `.pata` should be `.ipynb`.** A separate format is honest about being a different thing, and costs a second copy of a format Leela already reads. An `.ipynb` with `metadata.pata` costs nothing new, keeps `merge_rows` and the notebook conflict resolver, keeps search indexing it, and constrains what a block can hold to what a cell can carry.

**Whether the canvas is version one.** The context basket and the flavours work in a linear document and are most of the value. The canvas is where the edges get drawn, and the edges are where `upstream` and graph staleness come from. Shipping the list first means shipping the two features that depend on the canvas later.

**What the agent may write.** A prompt block answers into itself today. Letting it add blocks, move them, or draw an edge makes the document something the agent maintains rather than something it annotates. That is a much larger claim, and it wants its own decision.

## What integration actually costs

A review of this design against the repository found the seam work, and none of it is one line.

`Assistant.compose` in Ramabana wraps any context in `<notebook path=...>`, and the briefing tells the model to call `notebook_cells` on that path. A `.pata` path handed to `notebook_cells` reaches `Notebook.load` on JSON that is not nbformat, and raises. Ramabana needs to know a second document kind, or Leela needs to hand it a path it can honour.

`Tab.kind` is decided by suffix in `workspace.py` with no extension point, and `tab_state`, `tab_disk`, `tab_buffer`, `cwd_for` and `kernel_key` each need a branch. `write_text_at` special-cases `.ipynb` so that a rollback does not put jupytext markers into JSON, and `.pata` needs the same branch or it reintroduces a fault this repository already fixed. `DocStore` holds notebooks only. `blocks/search` gates indexing on the extension. `blocks/refactor` treats anything not `.ipynb` as text to rewrite, which would rename identifiers inside prose. Git conflicts on a canvas are more likely than on a notebook, because two people moving the same block both write `props.x`, and there is no cell-level resolver for a format that is not `.ipynb`.

Two things in the model are answered and were not: undo granularity for a drag, which is a stream of coordinate writes against a checkpoint scheme built for cell edits, and concurrency, because `inline_ai` is one conversation with one `_approval_target` while a canvas invites running two prompt blocks at once.

None of these is a reason not to build it. All of them are the reason the first question above is the one to answer first.
