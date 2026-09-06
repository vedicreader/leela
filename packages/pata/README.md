# pata

One document that holds a goal, the plan under it, the research behind it, the code that tests it, and the prompts that moved it along. Built for [Leela](https://github.com/vedicreader/leela), and usable on its own.

A notebook decides what the model sees by position: everything above the cell. A document that also holds a plan, a research shelf and a canvas has no "above". `pata` replaces position with a context set you can read, toggle and count before the turn runs.

## Install

```sh
pip install pata
```

## The model

One document is a flat, ordered list of blocks. Each block has a flavour, `pata:name`, after BlockSuite's `namespace:name`.

| flavour | holds |
|---|---|
| `pata:goal` | the statement, its measure, baseline, target and date |
| `pata:task` | one plan item, its status and owner |
| `pata:text` | prose |
| `pata:source` | something collected: a page, a file, a vault document |
| `pata:data` | a live variable or a table, with a preview |
| `pata:code` | a runnable cell, its outputs, and where `#|export` sends it |
| `pata:prompt` | a question, its answer, and the context rule that fed it |
| `pata:frame` | a named region grouping the blocks assigned to it |
| `pata:edge` | `src` reads from, supports, refutes or blocks `dst` |

The list is the page view. `x`, `y` and `frame` are the edgeless view. Both draw the same blocks, so moving one on the canvas does not fork the document.

```python
from pata import Block, Doc, arrange, render, resolve

d = Doc()
d.add(Block('goal', {'source': 'Increase procurement productivity by 10%'}, id='g'))
d.add(Block('source', {'title': 'Q3 audit', 'text': '34% of POs are under EUR 2,000.'}, id='s'))
p = d.add(Block('prompt', {'source': 'Where does the 10% come from?',
                           'context': {'scope': 'page', 'pins': ['s'], 'budget': 12000}}))
print(render(resolve(d, p.id), d))
arrange(d)
```

## Context

`resolve(doc, block_id)` returns the exact list a turn will send, in order, with the rule that put each item there. The same list draws the panel and builds the prompt, so what a person toggles is what the model gets.

A prompt block's `context` prop is a `Spec`:

- `scope` gathers a starting set. `none`, `page` (blocks before it in document order, which is a notebook), `frame` (its own region), `upstream` (what it reads from, along the edges), `doc`.
- `pins` are always included. A block id, or `file:`, `vault:`, `url:`, `var:` and `sel:` for things the document does not own. A host resolves those through the `lookup` argument.
- `mutes` are excluded whatever the scope says.
- `budget` is a character budget. The goal and the pins survive it. A `discard` block goes first, then the oldest ordinary one. A pin larger than the whole budget is clipped and marked, never dropped silently.

`render` emits `<cell id= type= compact= why=>`, which is Leela's notebook context shape. Ramabana's `compact_notebook_context` sheds elements matching exactly that when a prompt overflows the window, so the budget has a safety net underneath it.

## Staleness

A hash over a block's own source says the block was edited. It cannot say an ancestor re-ran. `Doc.stale(id)` reads both: the hash, and whether anything reachable backwards along the edges has a later `ran_at`.

## Getting work out

- `to_ipynb` / `from_ipynb`: a document as a notebook, prompt blocks in Leela's own `metadata.leela` shape. `from_ipynb` also migrates a notebook that was never a document.
- `to_markdown`: the narrative, for a report.
- `modules` / `write_modules`: the code blocks marked `#|export`, written as modules. `#|default_exp` names where an unqualified export goes.
- `source_text` / `take_source_text`: a `# %%` document for git to diff. A body line that would read as a marker is indented on the way out and restored on the way in.

## Prototypes

`pata.paint` writes a standalone page: both views, the outline, and the context panel.

```python
from pata.example import procurement
from pata.paint import paint

paint(procurement(), 'plan.html')                   # on its own
paint(procurement(), 'in-leela.html', shell='leela')  # inside the IDE it would live in
```

## Tests

```sh
pytest
```
