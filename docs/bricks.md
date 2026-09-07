# Bricks

A `brick` in a canvas document embeds a component from a library. `src=leela_bricks:viz.series` says which library and which component. This is where a component comes from, and what a library has to be.

Read this with [dynamic-documents.md](dynamic-documents.md), which is what a brick sits in.

## Where a component comes from

`leela/blocks/canvas/bricks.py` finds libraries three ways, in this order.

An entry point under `leela.bricks`, which is how a pip-installed library publishes itself. `shalya` finds pyskills the same way, and the codebase therefore already uses this pattern.

A name in `KNOWN`, for a library that publishes no entry point. `lego.bricks` is the only one.

`LEELA_BRICK_HOST`, for a library nobody installed. It is empty by default. The earlier design defaulted it to `http://127.0.0.1:5001`, which is Leela's own port. A fresh install therefore fetched its palette from Leela, got nothing, and reported nothing.

A library is any module with `manifest()` and `find(name)`. There is no base class and nothing to register. `leela_bricks` satisfies it.

## What Leela does with one

`palette(libs)` merges every library's manifest and stamps each row with the library it came from. `locate(src)` returns the library and the brick. `wire(src)` returns the snippet that fills the brick's ports. `mount(app)` registers each library's own routes on Leela's app.

The library's `serve.py` takes `(app, page=None)`, and it opens with "Nothing here imports the application it is mounted in". Leela's own process therefore serves the gallery, the component frame and the port data, on Leela's own port. No second server runs, and `LEELA_BRICK_HOST` serves only a library nobody installed.

`split_src` keeps the library prefix. The earlier code did `src.split(':')[-1]` and threw it away, which makes two libraries that each have a `viz.series` resolve to whichever answered first. Only the named library now answers a prefixed `src`. A bare name searches every library and takes the first, which is why a document should write the prefix.

## What was measured

Eight files went into an empty package with a two-line `__init__.py`, and nothing else changed. The package imports on `fastcore` and `fasthtml` alone. Leela's resolver reads it as 10 bricks in 4 groups. `locate` finds ports and emits. `wire` returns the package's own snippet and its remote fallback. `mount` registers all seven routes on a `FastHTML` app. `data.fill('viz.series')` runs the snippet and returns real values.

The extraction is a packaging change rather than a redesign, and the code already sits on the right side of the line.

Two facts decide where the line goes.

`lego/__init__.py` is `from .app import *` and `lego/bricks/__init__.py` is `from .app import connect`. Either one is enough to make `import lego.bricks` boot lego's whole application. In this container it fails on `ujson`, one of lego's thirteen dependencies. Nothing under `lego/bricks/` other than `app.py` imports `lego`.

Four of the ten bricks carry wiring that imports a domain package. `panchanga.day`, `panchanga.horas` and `panchanga.wheel` import `lego.muhurtha.panchanga`. `thrifty.costs` imports `lego.thrifty.data`. The other six, every `viz.*` and every `learn.*`, ship no wiring at all. They are display components that read whatever the document already computed.

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
| `app.py` | it is the upstream seam: `lego.core`, `RouteOverrides`, the upstream nav |
| `panchanga.*`, `thrifty.*` | their wiring imports `lego.muhurtha` and `lego.thrifty` |

## The spec is now built

`extensions/bricks` is the extracted package, `leela-bricks`. Eight files moved with no
edit. Only `bricks.py` changed, and it took all four changes below.

    uv pip install -e extensions/bricks

That is the whole install, and the entry point does the rest. `libraries()` finds
`leela_bricks`, `palette()` reads ten components in four groups, and the notes list is empty.
`KNOWN` still names `lego.bricks` for a library that publishes no entry point, and an absent
library produces no note.

The four domain bricks came too, and their wiring still imports `lego.muhurtha` and `lego.thrifty`.
`needs` exists for that case, and the palette therefore names the package a component wants before the cell runs.

| brick | needs |
|---|---|
| `panchanga.day`, `panchanga.horas`, `panchanga.wheel` | `lego.muhurtha.panchanga` |
| `thrifty.costs` | `lego.thrifty.data` |
| `viz.tiles`, `viz.series`, `viz.funnel` | nothing |
| `learn.cell`, `learn.wavepacket`, `learn.orbit` | nothing |

## Four changes the extracted package needs

**Own the `src` prefix.** `Brick.src` was `f'lego.bricks:{self.name}'`, hardcoded. After extraction that string names a package that no longer holds the brick. `LIB = __name__.rsplit('.', 1)[0]` derives it. Renaming the package therefore updates every `src` it serves.

**Give each library its own registry.** `BRICKS` is a module-global dict and `brick()` mutates it. That works while one package registers everything. It breaks as soon as a second library keeps its own bricks. That library would call `brick()` into the extracted package's global, and then every library's `manifest()` would return every library's bricks. The package exposes a `Registry` a library instantiates, with `manifest()` and `find()` reading its own. `manifest()` also returns `library`, which tells a caller which registry answered.

**Publish the entry point.** `[project.entry-points."leela.bricks"]` so Leela finds the library without `KNOWN`. `pip install` is the whole of procurement. `KNOWN` stays for a library that publishes none.

**Say when a snippet needs a package.** A brick whose `wire` imports something should declare it. `data.fill` already catches the failure, and `remote_wire` is already the fallback. A document still discovers the missing package by running a cell and reading a traceback. The manifest row carries `needs`. A regex over the wiring's own `import` lines produces it, minus the standard library. A component cannot claim a dependency its code does not import, and cannot hide one it does.

## What Leela ships

Leela includes no components of its own. A `sim` is a component the document itself defines, in JavaScript, with `root`, `props` and `emit` in scope. A `sim` needs no package, and Leela therefore stays fully usable with no library installed. The canvas skill states that you can move a `sim` into a package without changing a line.

Leela ships the resolver and the contract. A chart is not IDE behaviour. A bundled component library would become a compatibility surface, held forever on Leela's release clock rather than the library's. The same reason keeps `kunda`, `kavacha` and `pullup` out of this repository.

## What the merge connected

`leela/blocks/canvas/app.py` now holds both halves. The palette route is the resolver, and the two
routes that fetched from a host have gone. `/canvas/palette` reads `palette(libs)`, and
`/canvas/wire/{name}` reads the library. `_wire_from_host` keeps its name and reads the library
too, and it no longer drops the `src` prefix. Nothing in the block imports `urllib` any more.

`brick_host()` survives as the base for `remote_wire`. `remote_wire` is the snippet a document
runs when it holds the component but not the package that fills it. HTTP is the right answer in
that one case, and in no other.
