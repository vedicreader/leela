# leela-bricks

Components a canvas document can embed. Ten of them, in four groups.

A canvas document embeds one with a `brick` brick:

```markdown
```canvas brick id=b1 src=leela_bricks:viz.series emit_point=point
bind labels = list(cycle.index)
bind series = [{'name': 'days to clear', 'values': list(cycle.values)}]
prop height = 240
```
```

## Install

```sh
pip install -e extensions/bricks
```

Leela finds it through the `leela.bricks` entry point. Leela needs no other configuration, and
`LEELA_BRICK_HOST` serves only a library nobody installed. See
[docs/bricks.md](../../docs/bricks.md).

## What a brick declares

`Registry.brick(name, title, group, ports, emits, wire, height, doc)`. `ports` name what the component draws
from. `emits` name what a click writes back into the document's namespace. `wire` is the code
that fills the ports.

`wire` gives `needs`, and nobody declares it. `needs` is the top-level packages the snippet
imports, minus the standard library. Six of the ten need nothing. The four under `panchanga` and
`thrifty` each import a domain package, and a document without that package reads its ports over
`data.remote_wire` instead.

`src` is `LIB:name`, and `LIB` is this package's own module name. It is never a literal. A brick
therefore cannot claim a package it no longer lives in.

## Routes

`serve.connect(app, page=None)` registers seven routes on any Starlette or FastHTML app, and it
imports nothing from that app. Leela mounts the routes in its own process, and no second server
runs.

| route | is |
|---|---|
| `/bricks` | the gallery |
| `/bricks/manifest.json` | every brick, its ports and its emits |
| `/bricks/f/{name}` | one component, as a frame |
| `/bricks/wire/{name}` | the snippet, and the call that reads the ports remotely |
| `/bricks/data/{name}` | the ports, filled by running the snippet here |
| `/bricks/js`, `/bricks/css` | the drawing |

## Extracting it

This directory is the package. `pip install extensions/bricks` works anywhere, because nothing in
the package imports Leela. To move it to its own repository, use `git mv` and add a remote.
