# Bricks

A `brick` in a canvas document embeds a component from a library. `src=lego.bricks:viz.series` says which library and which component. This is where a component comes from, and what a library has to be.

Read this with [dynamic-documents.md](dynamic-documents.md), which is what a brick sits in.

## Where a component comes from

`leela/blocks/canvas/bricks.py` finds libraries three ways, in this order.

An entry point under `leela.bricks`, which is how a pip-installed library publishes itself. `shalya` finds pyskills the same way, so this is the pattern the codebase already uses.

A name in `KNOWN`, for a library that publishes no entry point. `lego.bricks` is the only one.

`LEELA_BRICK_HOST`, for a library that is not installed. It is empty by default, and that matters. The earlier design defaulted it to `http://127.0.0.1:5001`, which is Leela's own port, so a fresh install fetched its palette from Leela, got nothing, and reported nothing.

A library is any module with `manifest()` and `find(name)`. There is no base class and nothing to register. `lego.bricks` already satisfies it.

## What Leela does with one

`palette(libs)` merges every library's manifest and stamps each row with the library it came from. `locate(src)` returns the library and the brick. `wire(src)` returns the snippet that fills the brick's ports. `mount(app)` registers each library's own routes on Leela's app.

`mount` is the part worth stating plainly. `lego/bricks/serve.py` opens with "Nothing here imports the application it is mounted in", and it takes `(app, page=None)`. So the gallery, the component frame and the port data are served by Leela's own process on Leela's own port. There is no second server, and `LEELA_BRICK_HOST` exists only for a library that is not installed at all.

`split_src` keeps the library prefix. The earlier code did `src.split(':')[-1]` and threw it away, which makes two libraries that each have a `viz.series` resolve to whichever answered first. A prefixed `src` is now answered by that library only. A bare name searches every library and takes the first, which is why a document should write the prefix.

## What was measured

The `lego` branch at `Karthik777/lego@claude/dynamic-document-canvas-ohgfud` was cloned and read. Eight files under `lego/bricks/` were copied into an empty package with a two-line `__init__.py` and nothing else changed. The result imports on `fastcore` and `fasthtml` alone, and Leela's resolver reads it: 10 bricks in 4 groups, `locate` finds ports and emits, `wire` returns the package's own snippet and its remote fallback, `mount` registers all seven routes on a `FastHTML` app, and `data.fill('viz.series')` runs the snippet and returns real values.

So the extraction is not a redesign. It is a packaging change, and the code is already on the right side of the line.

Two facts decide where the line goes.

`lego/__init__.py` is `from .app import *` and `lego/bricks/__init__.py` is `from .app import connect`. Either one is enough to make `import lego.bricks` boot lego's whole application. In this container it fails on `ujson`, one of lego's thirteen dependencies. Nothing under `lego/bricks/` other than `app.py` imports `lego`.

Four of the ten bricks ship wiring that imports a lego domain package. `panchanga.day`, `panchanga.horas` and `panchanga.wheel` import `lego.muhurtha.panchanga`; `thrifty.costs` imports `lego.thrifty.data`. The other six, every `viz.*` and every `learn.*`, ship no wiring at all. They are display components that read whatever the document already computed.

## What to extract

Take the contract and the six domain-free bricks. Leave the four domain bricks with the packages their wiring needs.

| goes | is |
|---|---|
| `bricks.py` | `Port`, `Brick`, the registry, `manifest()`, `find()` |
| `cfg.py` | the seven route paths |
| `serve.py` | `connect(app, page=None)`, which imports nothing about the app |
| `data.py` | `fill()` runs a brick's snippet here; `remote_wire()` is the call for a document that lacks the package |
| `ui.py`, `bricks.js`, `bricks.css`, `frame.js` | the gallery, the frame, and the drawing keyed by brick name |
| `viz.*`, `learn.*` | six bricks with no wiring and no domain dependency |

| stays | why |
|---|---|
| `app.py` | it is lego's seam: `lego.core`, `RouteOverrides`, lego's nav |
| `panchanga.*`, `thrifty.*` | their wiring imports `lego.muhurtha` and `lego.thrifty` |

## Four changes the extracted package needs

**Own the `src` prefix.** `Brick.src` is `f'lego.bricks:{self.name}'`, hardcoded. After extraction that string names a package that no longer holds the brick. Derive it from the registry's own module name.

**Give each library its own registry.** `BRICKS` is a module-global dict and `brick()` mutates it. That works while one package registers everything. It breaks the moment lego keeps its four bricks: lego would call `brick()` into the extracted package's global, and then every library's `manifest()` would return every library's bricks. The package should expose a `Registry` a library instantiates, with `manifest()` and `find()` reading its own.

**Publish the entry point.** `[project.entry-points."leela.bricks"]` so Leela finds the library without `KNOWN`. Then `pip install` is the whole of procurement, and `KNOWN` can go.

**Say when a snippet needs a package.** A brick whose `wire` imports something should declare it. `data.fill` already catches the failure and `remote_wire` is already the fallback, but a document currently discovers the missing package by running a cell and reading a traceback. The manifest row should carry the requirement so the palette can say so first.

## What Leela ships

No components. `sim` is a component written in the document itself, in JavaScript with `root`, `props` and `emit` in scope. It needs no package, so a Leela with no library installed is still fully usable, and the canvas skill already says a `sim` can be promoted into a package without changing a line.

Leela ships the resolver and the contract. A chart is not IDE behaviour, and a bundled component library would be a compatibility surface Leela keeps forever on Leela's release clock rather than the library's. This is the same reason `kunda`, `kavacha` and `pullup` are not in this repository.

## Not built

The palette and `_wire_from_host` live on the `dynamic-document-canvas` branch, which is not merged here. That branch fetches over HTTP and drops the `src` prefix; both are what this resolver replaces. Merging is what connects the resolver to a browser that draws from it.
