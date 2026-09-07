"""Working in a canvas: a markdown document whose bricks run, bind and hand values back.

Read this before editing a canvas.

## What a canvas is

Not a notebook and not a page. One markdown file where prose is prose and everything else is a
brick, and where each brick recomputes when what it reads moves. The document is the program and
the note about the program at once.

## The file

`*.canvas.md`. Optional YAML frontmatter carries `title` and `mode`. Prose between bricks is a
`text` brick and needs no markup of its own.

A brick that is opaque to markdown is a fence:

    ```canvas <kind> id=<id> key=value ...
    <body>
    ```

A brick whose body is markdown a plain renderer should still show is a comment wrap:

    <!--canvas <kind> id=<id>-->
    Ordinary **markdown**.
    <!--/canvas-->

Fenced kinds: `code`, `ask`, `brick`, `sim`, `data`, `pdf`, `video`.
Wrapped kinds: `reply`, `note`, `quiz`.

A non-code brick body holds directives, one per line, and nothing else:

    bind <port> = <expression>
    prop <key> = <value>

A code brick body is the code, kept exactly. Directives are never read out of it.

## Bindings, and what runs

Code bricks share one namespace. They run in dependency order derived from the AST, not document
order, so a cell may be written above the cell it needs. A canvas stores no outputs: opening one
runs it.

`bind port = expression` evaluates the expression against that namespace and hands the result to
the brick. When a name the expression reads moves, the binding is resolved again. A binding that
raises reports on the brick rather than blanking it.

`data` is the brick that makes prose live: `bind text = f"..."` renders the result as markdown.
Prefer it over writing a number into prose. A number written by hand is wrong the moment anything
above it changes.

## Emits: what a component hands back

A component brick emits. `emit_<port>=<name>` in its attributes says which name in the namespace a
port writes to. Clicking a funnel bar, a rasi or an organelle sets that name and reruns everything
that reads it. A component is an input as much as an output.

Two components in one document must not write to the same name unless they are meant to.

## Components, bricks and sketches

`brick` embeds a component from a package: `src=lego.bricks:viz.series`. The package declares the
ports, what it emits, and the code that fills it. Take that code rather than writing your own:
`canvas_wire(name)` returns it, `canvas_insert` puts it in the document as an ordinary code brick,
and `canvas_bind` points the ports at what it defined. The wiring stays visible in the file.

`sim` is a component written in the document itself. Its body is JavaScript with `root`, `props`
and `emit` in scope, and nothing else. Promote one into a package without changing a line.

## Your tools: the ports into the document

| tool | does |
|---|---|
| `canvas_read` | the document as it stands: every brick, its kind, its bindings, what it defines |
| `canvas_insert` | a new brick at a position. `after=<id>` or `at=<index>` |
| `canvas_replace` | rewrite one brick, by id |
| `canvas_remove` | take a brick out, by id |
| `canvas_bind` | point one port of one brick at an expression |
| `canvas_run` | run a code brick and let the dataflow settle |
| `canvas_answer` | prose written back into the document, attached to the question that asked for it |
| `canvas_values` | read names out of the live namespace |

Every one goes through the same function the person's own edits go through. There is no second
path into the document, and nothing else you can reach touches it.

## How to work

Read before you write. `canvas_read` costs one call and tells you what ids exist, what each cell
defines and what every binding reads. Editing by guess breaks bindings that were fine.

Answer where the question was asked. `canvas_answer(of=<ask id>)` puts the reply under the ask and
replaces the previous one rather than stacking. Prose that belongs in the document goes in the
document, not only in the reply.

Change the smallest thing. A wrong number is usually one binding, not a rewritten section. Rewrite
a selection with `canvas_replace` only for the span you were given.

Insert code that runs. A code brick arrives to be run: it runs where it lands, and anything bound
to the names it defines resolves. Do not insert a cell that needs a second call to be useful.

Bind rather than paste. If a value already exists in the namespace, bind to it. Pasting the value
makes a document that was live into a document that was true once.

Name what you emit. When you add a component whose clicks should drive something, set
`emit_<port>` to a name the document already reads, or add the cell that reads it in the same turn.

Prefer a brick to a paragraph about a brick. A canvas is for showing the thing.

## The trail, and where a question came from

A question carries where it was asked from: the brick, and the text that was selected in it. The
last dozen of those are the trail, and they arrive with the turn. Use them. "Why is that one
cheaper" resolves against the row that was clicked, and asking the person to repeat themselves
wastes the context you were given.

A selection is a span, not a topic. Rewriting one rewrites that span and leaves the rest of the
brick alone.
"""
