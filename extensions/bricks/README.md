# leela-bricks

Components a canvas document can embed. Ten of them, in four groups, extracted out of
[lego](https://github.com/Karthik777/lego)'s `lego/bricks/`.

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

Leela finds it through the `leela.bricks` entry point. Nothing else is configured, and
`LEELA_BRICK_HOST` is only for a library that is not installed. See
[docs/bricks.md](../../docs/bricks.md).

## What a brick declares

`Registry.brick(name, title, group, ports, emits, wire, height, doc)`. `ports` are what it draws
from, `emits` are what a click writes back into the document's namespace, and `wire` is the code
that fills the ports.

`needs` is derived from `wire` rather than declared: the top-level packages the snippet imports,
minus the standard library. Six of the ten need nothing. The four under `panchanga` and `thrifty`
import `lego.muhurtha` and `lego.thrifty`, and a document without those reads its ports over
`data.remote_wire` instead.

`src` is `LIB:name`, and `LIB` is this package's own module name. It is never a literal, so a brick
cannot claim a package it no longer lives in.

## Routes

`serve.connect(app, page=None)` registers seven routes on any Starlette or FastHTML app and imports
nothing about it. Leela mounts them on its own process, so there is no second server.

| route | is |
|---|---|
| `/bricks` | the gallery |
| `/bricks/manifest.json` | every brick, its ports and its emits |
| `/bricks/f/{name}` | one component, as a frame |
| `/bricks/wire/{name}` | the snippet, and the call that reads the ports remotely |
| `/bricks/data/{name}` | the ports, filled by running the snippet here |
| `/bricks/js`, `/bricks/css` | the drawing |

## Extracting it

This directory is the package. `pip install extensions/bricks` and it works anywhere; nothing in it
imports Leela. Moving it to its own repository is `git mv` and a remote.
