# pata

One markdown file that holds a goal, the plan under it, the research behind it, the code that tests it, and the questions that moved it along. Built for [Leela](https://github.com/vedicreader/leela), and usable on its own.

The file format and the AST dataflow come from Leela's `dynamic-document-canvas` branch. What `pata` adds is the context engine: a question names what it may see, and the basket it will send is a list you can read, toggle and count before the turn runs.

## Install

```sh
pip install pata
```

## The file

`*.canvas.md`. Prose is prose. A brick that markdown cannot show is a fence, and a brick whose body is markdown a plain renderer should still show is a comment wrap. Headings are the document's regions, so a canvas opened in any markdown viewer is still a readable document.

````markdown
---
title: Procurement productivity +10%
---

# Increase procurement productivity by 10%

<!--canvas goal id=goal measure="POs per buyer FTE per month" baseline=41 target=45-->
Increase procurement productivity by 10% in FY26.
<!--/canvas-->

## What we already know

<!--canvas source id=s-audit title="Internal audit, Q3 FY25" path=drive/audit-q3.pdf-->
34% of purchase orders raised in Q3 were under EUR 2,000.
<!--/canvas-->

```canvas code id=c-share
tail, rest = bands(pos)
share = len(tail) / len(pos)
```

```canvas data id=d-say
bind text = f"The tail is **{share:.0%}** of all POs."
```

```canvas ask id=q scope=region budget=12000
pin s-audit
Where does the 10% most plausibly come from?
```
````

| kind | holds |
|---|---|
| `goal` | the statement, and `measure`, `baseline`, `target`, `by` |
| `task` | one plan item, its `status` and `owner` |
| `source` | something collected: a page, a file, a vault document |
| `code` | a runnable cell. No outputs are stored: opening the document runs it |
| `data` | prose bound to a live value, so a number in a sentence cannot go stale |
| `brick`, `sim` | an embedded component and one written in the document |
| `ask`, `reply`, `note` | a question, the answer written back under it, and an aside |
| `bundle` | one unit of change: the goal it serves, the files it owns, what is attached |
| `diff` | one file's hunks, in a generated review |

## Context

`resolve(doc, brick_id)` returns the exact list a turn will send, in order, with the rule that put each item there. The same list draws the panel and builds the prompt, so what a person toggles is what the model gets.

A question carries its rule as attributes and directives:

- `scope=` gathers a starting set. `none`, `page` (bricks before it), `region` (under the same heading), `upstream` (what it reads from), `doc`.
- `pin <ref>` is always included. A brick id, or `file:`, `vault:`, `url:`, `var:` and `sel:` for things the document does not own. A host resolves those through the `lookup` argument.
- `mute <ref>` is excluded whatever the scope says.
- `budget=` is a character budget. The goal and the pins survive it. A `context=discard` brick goes first, then the oldest ordinary one. A pin larger than the whole budget is clipped and marked, never dropped silently.

`render` emits `<cell id= type= compact= why= region=>`, which is Leela's notebook context shape. Ramabana's `compact_notebook_context` sheds elements matching exactly that when a prompt overflows the window, so the budget has a safety net underneath it.

## Upstream is read, not drawn

`upstream` walks the dataflow the code already states. `defs_of` and `reads_of` say which brick binds a name and which bricks load it, so the graph is right without anyone maintaining it.

Three things extend it where the AST cannot see:

- A question anchors on the brick above it, because "fix that" means that one and everything it reads. `anchor=<id>` overrides.
- A name a question puts in backticks is a name it reads. Writing `` `triage` `` in a question pulls in the brick that defines it.
- `supports=`, `refutes=` and `blocks=` name bricks a prose relation joins. That is where a clipping supporting a claim goes, which no AST can find.

## A bundle is one change

A region groups bricks for reading. A `bundle` brick claims its region as one change, so the boundary on the canvas is the thing a reviewer opens and the thing a pull request is cut from.

```markdown
<!--canvas bundle id=triage title="Auto-approve the contracted tail" goal=goal
     contributes="most of the 10 points" paths=tests/test_triage.py refs=pkg:pandas,file:procure/erp.py-->
Adds `triage`, the rule that lets a contracted supplier's small PO skip the approval chain.
<!--/canvas-->
```

- `goal=` is the value link. `contributes=` is what this change is worth against it, in words.
- Membership is the bundle's own region. `covers=` adds bricks by id or regions by heading.
- The files it owns are derived from its code bricks' `#|export` targets, plus whatever `paths=` declares. A brick that writes a module is the change, so nobody should have to list the file twice.
- `refs=` attaches packages, files and documents for review. Same vocabulary as a context pin, so attaching something for a reviewer also makes it available to the model.

`coverage(doc, changed_paths)` is what the boundary is for. It reports, per bundle, what it claimed and what actually moved, and then two things nobody asks for:

- `unmet`: a file the bundle claims that the diff never touched. A claim with no code behind it.
- `unclaimed`: a changed file no bundle explains. The half a reviewer never sees coming.

`pr(doc, bundle_id)` returns `{title, branch, body, paths, refs, goal}`. The body carries the goal and its measure, the prose, the tasks with their status, the questions asked inside the change with their answers folded, the attachments and the file list. It returns the payload rather than opening anything: git is `gheasy`'s and the forge is `pullup`'s.

`state(bundle, changed)` is derived rather than set: `blocked` if any task is, `done` when every task is and every claimed file moved, `doing` when some of either has. A status somebody has to remember to update is a status that lies. No diff is no evidence about files, so it does not read as evidence against.

`value(doc, changed)` is the third view: every goal, and every change serving it, with its state and its tally. Two negatives are why it exists, and neither shows up anywhere else. A change serving no goal lands under `Serving no goal`. A goal nothing is serving says so under its own heading.

`review(doc, bundle_id, diff)` builds a second document from a unified diff: the value, the reasoning, one `diff` brick per file, the attachments, the coverage checks, and a question with the goal pinned. A review is a canvas, so it draws in both views and you can ask about the change with the goal already in the basket.

## Getting work out

- `to_ipynb` / `from_ipynb`: a document as a notebook, questions in Leela's own `metadata.leela` prompt shape. `from_ipynb` also migrates a notebook that was never a document, and `arrange` gives that import a canvas.
- `to_report`: the document with the canvas taken off, for a reader who has never heard of one.
- `modules` / `write_modules`: the code bricks marked `#|export`, written out in dependency order.

## Prototypes

`pata.paint` writes a standalone page: both views, the outline, and the context panel.

```python
from pata import hunks, review, value
from pata.example import VALUES, diff, procurement
from pata.paint import paint

d = procurement()
changed = list(hunks(diff()))
paint(d, 'plan.html', values=VALUES, changed=changed,
      review=review(d, 'triage', diff()), value=value(d, changed))
```

## Tests

```sh
pytest
```
