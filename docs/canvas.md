# Canvas

One file holds prose, code, embedded components, simulations, PDFs and video. Each brick in it
recomputes when a name it reads changes.

The notebook Leela already has is a list of cells. A canvas is prose with everything else inside it,
and its cells are not the point of the document. `leela/blocks/canvas/` is the block.
`examples/canvas/` holds six of them.

![A canvas open](screenshots/canvas-funnel.png)

## The file

A canvas is markdown. `*.canvas.md`. Prose is prose. Everything else is a fenced block or a
comment-wrapped region, and both survive a plain markdown renderer.

````md
```canvas code id=c1
tokens = 1200
```

```canvas brick id=b1 src=lego.bricks:thrifty.costs emit_row=picked
bind rows = rows
prop height = 220
```

<!--canvas note id=n1-->
An **aside**, still rendered by anything that reads markdown.
<!--/canvas-->
````

Fenced kinds: `code`, `ask`, `brick`, `sim`, `data`, `pdf`, `video`. Wrapped kinds: `reply`, `note`,
`quiz`. Anything else in the file is a `text` brick.

The parser is a line scan rather than a pair of regular expressions. A canvas fence inside a longer
markdown fence is an example of a brick and not a brick. A document about canvases is itself a
canvas. Windows line endings read the same as Unix ones. Two bricks cannot share an id, and the
parser therefore gives the second brick a fresh id on read. Without that rule, every op on the first brick
would reach the second one in silence.

A `pdf` brick with a relative `src` is a file beside the canvas, served by `/canvas/file`, which
resolves under the canvas directory and refuses anything above it.

A brick body holds `bind <port> = <expression>` and `prop <key> = <value>` lines. The body of a code brick
is the code itself, kept exactly, and nothing reads it for directives.

A canvas stores no outputs, and opening one runs it. The file therefore diffs to what somebody
changed and nothing else. `test_canvas.py` opens a canvas, runs it, wires it and asks questions of
it, then asserts that it saves back byte for byte.

## The dataflow

Code bricks share one namespace and run in dependency order rather than document order. `defs_of`
reads what a brick defines from its AST; `reads_of` reads what it needs. `order` sorts them. A cycle
falls back to document order.

`downstream(bricks, names)` is what makes the document live. It returns every code brick whose
inputs include one of `names`, transitively, followed by every brick with a binding that reads one.
Setting a name reruns exactly that set.

Bindings are expressions evaluated against the namespace. A binding that raises reports the error on
the brick rather than blanking it.

## Components

Every embedded component runs in an iframe. The document and the frame exchange four messages and
nothing else.

| message | direction | meaning |
|---|---|---|
| `brick:ready` | frame to document | the frame has loaded, with its manifest |
| `brick:props` | document to frame | resolved port values |
| `brick:height` | frame to document | how tall it wants to be |
| `brick:emit` | frame to document | a value the person produced by using it |

`brick:emit` is why a canvas is not a dashboard. Clicking an organelle, a rasi or a funnel bar writes
a name into the namespace, and every cell that reads that name reruns. A component is an input as
much as an output.

The brick's attributes name the port's target as `emit_<port>`. Two funnels in one document
therefore never fight over `stages`.

![Clicking a component writes into the document](screenshots/canvas-cell.png)

## Wiring

The package that owns the component declares its ports, and the document never does.
`leela_bricks` is one such package. Each brick in it declares its ports, what it emits, and the
code that fills it.

Picking a component from the palette inserts it and reads its wiring. Leela puts that code in the
document as an ordinary code brick, then binds the ports it filled. You can see and edit the
wiring, and the document holds no hidden connection.

Where a component comes from is [bricks.md](bricks.md). Leela reads the palette and the wiring in
process, from a library installed beside it. `LEELA_BRICK_HOST` is the fallback for a library
nobody installed. An earlier version of this block fetched both over HTTP, from a default that
was Leela's own port. A fresh install therefore had an empty palette and no error.

A package ships its wiring twice. The first form imports the package, and the second form calls
the host that owns it. The document runs the first form, and falls back to the second when the
import fails. That import fails when the package is not beside the document.

```python
from lego.muhurtha.panchanga import Place, day_panchanga
day = day_panchanga(Place(12.97, 77.59, 'Asia/Kolkata', 'Bengaluru'), date.today())
```

```python
import json, urllib.request
_ports = json.load(urllib.request.urlopen('http://127.0.0.1:5001/bricks/data/panchanga.day'))
day = _ports['day']
```

The ⚙ in a brick's rail opens the wiring panel: every port, its expression, what it currently
resolves to, and the names in the namespace to pick from.

![The wiring panel](screenshots/canvas-wire.png)

The palette is what the host publishes, grouped by the block that owns each component.

![The palette](screenshots/canvas-palette.png)

## The helper

Three places reach the one helper: the margin, an `ask` brick in the document, and `mod+k`
anywhere. All three run the same turn, and only the selection that travels with it differs.

Its reach into the document is eight tools and no others.

| tool | does |
|---|---|
| `canvas_read` | the document as it stands |
| `canvas_insert` | a new brick at a position |
| `canvas_replace` | rewrite one brick |
| `canvas_remove` | take a brick out |
| `canvas_bind` | point a port at an expression |
| `canvas_run` | run a code brick and let the dataflow settle |
| `canvas_answer` | prose attached to the question that asked for it |
| `canvas_values` | read names out of the namespace |

Every one goes through `apply_op`, which is also what the person's own edits go through. There is no
second path into the document.

A turn streams `step`, `chunk`, `op`, `answer`, `done`. The document applies each `op` event as it
arrives, and a brick therefore appears while the turn is still running. Steering is a queue per
turn. The turn takes text posted to `/canvas/steer` at the next step boundary, and replans the
rest of the turn.

The trail is the last twelve questions, each with the brick it came from and the selection it
carried. It goes into the next turn's context, which is why a follow-up needs no preamble.

![Steering a turn that is already running](screenshots/canvas-steer.png)

## Canvas mode

What the agent knows about a canvas is split in two, because the two halves have different
lifetimes.

The eight tools are permanent. `_canvas_toolset` builds them with the workspace assistant, beside
Leela's other toolsets, and each resolves the open canvas when it runs. They cannot come and go
with a document: a backend hands its tool list to the engine once, when it is built, so a tool
registered later is a name the model is told about and cannot call. Registering them per turn is
what made every live call answer `KeyError`.

The vocabulary is not permanent. `leela/skills/canvas.py` is the body, and it is deliberately not
a `pyskills` entry point, because a skill that is only true inside a canvas should not reach every
agent that has Leela installed. The system prompt is rebuilt every turn, so `_canvas_mode` pushes
the skill while a canvas tab is open and drops it when none is. That costs a line in the prompt
and nothing else; the body still arrives through `read_skill`.

Ramabana holds none of this. `Agent.skills` is `discover(..., extra=registry.skills)`, so a pushed
skill reaches the skill index and `read_skill` with no change to the agent core.

## The model

A turn with a model in it belongs to the agent pane. The pane and the margin were never two
assistants: both resolve to the workspace's own agent, and it is the same agent the canvas tools
are registered on. What the margin added was a second, thinner turn UI, and it rendered its
approvals in the pane where the person who asked could not see them. An ask from an embedded
canvas now goes to the pane through `canvasAskPane`, carrying the brick it was asked from as an
attachment. Approvals, steering, history and the model picker come with it.

`helper_for` returns `Scripted` and only `Scripted`. It answers the standalone `/canvas` page,
which has no pane. It is deterministic: it reads the same `Ask`, applies the same ops, and emits
the same events, but carries no judgement and no facts. To answer a question about a word, it
finds where this document already explains that word, and a word the document never explains gets
no answer. It scores which component to embed against what the host publishes, never against a
table kept here.

## The editor

You edit the document in place. Prose stays rendered while you work in it, and it returns to
markdown on the way out. Selecting a sentence to ask about it therefore leaves the sentence
looking the same.

| where | what |
|---|---|
| gutter | `+` inserts under the block, the grip drags it, clicking the grip opens what else it can do |
| `/` on an empty line | the block menu, grouped, filtered as you type, driven by the keyboard |
| a text selection | bold, italic, code, link, and Ask AI, which is the inline turn |
| `Enter` | splits the block at the caret. `shift+Enter` is a line break inside one |
| `Escape` | leaves the text and picks the block. Then arrows move, `Enter` enters, `Backspace` deletes |
| `mod+k` | ask, anchored wherever you are |
| `mod+j` | the helper margin |
| `mod+b`, `mod+i`, `mod+e` | the three marks, applied to the markdown rather than to the HTML |
| `mod+enter` | run this cell. `mod+shift+enter` runs the document in dependency order |

![The gutter, on hover](screenshots/canvas-gutter.png)

![The block menu](screenshots/canvas-blockmenu.png)

![The block menu on `/`, filtered as you type](screenshots/canvas-slash.png)

![The format bar, with the helper in it](screenshots/canvas-format.png)

Both themes, and every embedded component follows the one the document is in.

![The same document in the dark](screenshots/canvas-dark.png)

The editor writes marks to the file, never to the rendered HTML. `document.execCommand('bold')`
would put in a `<b>` that the markdown writer then has to guess about.

The type scale, the token names and the popover shape follow BlockSuite's. A canvas beside an
editor built on BlockSuite therefore reads as the same application. Both themes sit in
`canvas.css`, and `test_canvas.py` asserts the dark half names no token the light half lacks.

## Modes

`mode: make` and `mode: learn` in the frontmatter. The substrate is the same. The palette and the
default bricks differ. `a-sales-funnel`, `the-traditional-day`, `tunnelling` and `an-animal-cell` use
learn. `pricing-a-run` and `making-a-block` use make.

Nothing in the runtime branches on the mode. It is a label on the document and a filter on the
palette.

## Running it

`leela/blocks/__init__.py` connects the block, which serves `/canvas` from the IDE app. It also
runs on its own, with no kernels, no agent and no workspace:

```sh
uv run python tools/canvas_spike.py                  # http://localhost:5002/canvas
BRICK_HOST=http://127.0.0.1:5001 uv run python tools/canvas_spike.py
```

The components come from a component host on `BRICK_HOST`. Without one, the palette is empty, and
a brick already in a document draws with the sample data its package declares.

The canvas serves its own bundle from `/canvas/js` rather than joining the three IDE bundles.
Those three share one lexical scope, which a separate document has no reason to enter.
`build_ide_js.OWN_BUNDLE` names the blocks that serve their own bundle.

## Walkthroughs

Recorded against this branch, with the scripted helper and a component host on 5001.

| what it shows | file |
|---|---|
| dragging a funnel bar rewrites every number under it | [`media/canvas/canvas-reactive.webm`](../media/canvas/canvas-reactive.webm) |
| clicking an organelle, an inline rewrite, an ask and a steer | [`media/canvas/canvas-helper.webm`](../media/canvas/canvas-helper.webm) |
| slash menu to palette to a component wired from its package | [`media/canvas/canvas-wiring.webm`](../media/canvas/canvas-wiring.webm) |
| the barrier sliders driving the simulation and the sentence under it | [`media/canvas/canvas-learn.webm`](../media/canvas/canvas-learn.webm) |

## The six shipped canvases

| canvas | mode | what it exercises |
|---|---|---|
| [a-sales-funnel](../examples/canvas/a-sales-funnel.canvas.md) | learn | a component as an input, and prose bound to what it writes |
| [the-traditional-day](../examples/canvas/the-traditional-day.canvas.md) | learn | three components off one data source, wired over the host |
| [tunnelling](../examples/canvas/tunnelling.canvas.md) | learn | a sketch driving a simulation, and a video |
| [an-animal-cell](../examples/canvas/an-animal-cell.canvas.md) | learn | click-to-name, an accumulating list, a check |
| [pricing-a-run](../examples/canvas/pricing-a-run.canvas.md) | make | a table you pick a row from, and a slider that repeats the sum |
| [making-a-block](../examples/canvas/making-a-block.canvas.md) | make | a function, its chart, and a component sketched in the file |

![The whole of the panchangam canvas](screenshots/canvas-the-traditional-day.png)

A PDF, a sketch and a chart in the same document.

![A PDF open in a canvas](screenshots/canvas-pdf.png)

## What the spike does not do

- The runtime is `exec` in the web process, not a kunda kernel. Ordering, staleness and error shape
  are the real ones. Isolation, interrupt and restart are not there.
- Undo reaches an agent's edit but not a person's. A canvas tool writes through the sandbox and
  files a journal row, so `workspace undo` takes it back; `/canvas/save` still writes straight to
  disk and files nothing. The turn's own "Restore files" never sees either, because `changes()`
  tracks Ramabana's write tools and `canvas_*` is not among them.
- Prose editing round-trips through `cvHtmlToMd`, which handles what `cvMd` can produce and no more.
  `mod+e` shows the markdown for a block where that is not enough.
- The margin still draws a thread of its own on the standalone page, and a steer bar that only
  `/canvas/ask/stream` reads. Embedded, both are dead weight.
- Block selection takes one block at a time. Dragging a range across many blocks is not there.
- The markdown writer handles what the renderer can produce and no more. `mod+e` shows the source
  for a block where that is not enough.
