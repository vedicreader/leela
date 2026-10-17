# Bricks

A `brick` in a canvas document embeds a component from a library. `src=leela_bricks:viz.series` says which library and which component. This is where a component comes from, and what a library has to be.

Read this with [dynamic-documents.md](dynamic-documents.md), which is what a brick sits in.

## Where a component comes from

`leela/blocks/canvas/bricks.py` finds libraries three ways, in this order.

An entry point under `leela.bricks`, which is how a pip-installed library publishes itself. `shalya` finds pyskills the same way, and the codebase therefore already uses this pattern.

A name in `KNOWN`, for a library that publishes no entry point. It is empty. `leela_bricks`
publishes one, and a name that is simply not installed is skipped without a note, the same way
an absent `extra=` name is.

`LEELA_BRICK_HOST`, for a library nobody installed. It is empty by default. The earlier design defaulted it to `http://127.0.0.1:5001`, which is Leela's own port. A fresh install therefore fetched its palette from Leela, got nothing, and reported nothing.

A library is any module with `manifest()` and `find(name)`. There is no base class and nothing to register. `leela_bricks` satisfies it.

## What Leela does with one

`palette(libs)` merges every library's manifest and stamps each row with the library it came from. `locate(src)` returns the library and the brick. `wire(src)` returns the snippet that fills the brick's ports. `mount(app)` registers each library's own routes on Leela's app.

The library's `serve.py` takes `(app, page=None)`, and it opens with "Nothing here imports the application it is mounted in". Leela's own process therefore serves the gallery, the component frame and the port data, on Leela's own port. No second server runs, and `LEELA_BRICK_HOST` serves only a library nobody installed.

`split_src` keeps the library prefix. The earlier code did `src.split(':')[-1]` and threw it away, which makes two libraries that each have a `viz.series` resolve to whichever answered first. Only the named library now answers a prefixed `src`. A bare name searches every library and takes the first, which is why a document should write the prefix.

## What was extracted

Eight files went into an empty package with a two-line `__init__.py`. The package imports on
`fastcore` and `fasthtml` alone. Leela's resolver reads it as ten bricks in four groups, `locate`
finds ports and emits, `mount` registers all seven routes on a `FastHTML` app, and
`data.fill('viz.series')` runs and returns real values. A packaging change, not a redesign.

    uv pip install -e extensions/bricks

That is the whole install. The entry point does the rest.

## Four changes the extracted package needed

**Own the `src` prefix.** `Brick.src` was `f'lego.bricks:{self.name}'`, hardcoded. After
extraction that string named a package that no longer held the brick.
`LIB = __name__.rsplit('.', 1)[0]` derives it, so renaming the package updates every `src` it
serves. The hardcoded form outlived itself anyway: `KNOWN`, the canvas skill, both docs and two
test files went on saying `lego.bricks` for a release after the package became `leela_bricks`,
and an agent following the skill wrote a `src` that resolved to nothing.

**Give each library its own registry.** `BRICKS` was a module global and `brick()` mutated it.
Fine while one package registers everything, broken the moment a second library keeps its own:
that library would call `brick()` into the first one's global, and every `manifest()` would
return every library's bricks. `Registry` is the instance a library makes for itself.
`manifest()` also returns `library`, so a caller knows which registry answered.

**Publish the entry point.** `[project.entry-points."leela.bricks"]`, so `pip install` is the
whole of procurement.

**Say when a snippet needs a package.** A brick whose `wire` imports something should declare it,
rather than let a document find out from a traceback. A regex over the snippet's own `import`
lines produces `needs`, minus the standard library. A component cannot claim a dependency its
code does not import, and cannot hide one it does.

## Where lego went

Four bricks came across carrying wiring that imported `lego`, the repository they were extracted
from. `panchanga.day`, `panchanga.horas` and `panchanga.wheel` imported `lego.muhurtha.panchanga`;
`thrifty.costs` imported `lego.thrifty.data`. Nothing else in the package touched it. The plan
had been to leave those four behind. They came anyway, and `lego` is not a dependency of
`leela-bricks` and is not on PyPI, so the wiring raised `ModuleNotFoundError` for everyone.

The wiring is gone. The components stayed. That is the smaller change and it costs nothing,
because the drawings never needed `lego`: they are JavaScript that reads whatever ports the
document bound. Two shipped examples already proved it. `pricing-a-run.canvas.md` computes its
own price table in a code cell and binds it to `thrifty.costs`, and it has always run green.
`the-traditional-day.canvas.md` fetches `/bricks/data/panchanga.day` from Leela's own port, which
answers with the sample day the brick declares.

So no brick in `leela_bricks` ships wiring now, and `needs` is empty for all ten. `needs`,
`data.fill`'s exec path and `remote_wire` stay: they are the contract a library with its own
data uses, and the next section builds one.

## Writing your own library

A library is any module with `manifest()` and `find(name)`. There is no base class, nothing to
subclass, nothing to register with Leela. Expose a `data` submodule as well and the components
can fill their own ports.

`pyproject.toml` publishes the entry point. The value is the module holding the registry.

```toml
[project]
name = "sales-bricks"
dependencies = ["pandas>=2"]

[project.entry-points."leela.bricks"]
sales_bricks = "sales_bricks"
```

`sales_bricks/bricks.py` declares the components against a registry of its own.

```python
from leela_bricks.bricks import Port, Registry

REG = Registry(lib='sales_bricks', groups={'pipeline': 'Where the quarter stands'})
brick, find, manifest = REG.brick, REG.find, REG.manifest

brick('pipeline.stages', 'Pipeline', 'pipeline',
      doc='Every stage in the quarter, and what it converts at.',
      ports=[Port('stages', 'list', '[{name, value}]',
                  sample=[{'name': 'Leads', 'value': 1000}, {'name': 'Won', 'value': 23}])],
      emits=[Port('stage', 'dict', 'the stage clicked')],
      height=300,
      wire="""
from sales_bricks.warehouse import monthly
stages = monthly('2026-Q3')
""")
```

That `wire` is what separates a library like this one from `leela_bricks`, whose components draw
only what the document already computed. Nobody declares the dependency: `needs` comes back as
`['sales_bricks.warehouse']`, read off the import line, so the gallery can name what a component
wants before a cell runs.

`sales_bricks/data.py` runs that snippet on request. Copy it from `leela_bricks/data.py` rather
than importing it. `fill` and `remote_wire` both close over `find`, which binds them to one
registry, so a shared copy would answer for the wrong library. `tests/fixtures/demobricks` copies
them too. Only `jsonable` is safe to import.

`sales_bricks/__init__.py` is the seam Leela reads.

```python
from . import data, serve
from .bricks import find, manifest
```

Leaving `data` off that line costs you the remote fallback with no error: `Library.wire` looks
for `module.data.remote_wire`, finds nothing, and returns `remote: ''`.

`sales_bricks/bricks.js` draws the component, keyed by the same name, and `serve.connect(app)`
mounts the seven routes. Copy `serve.py` and `cfg.py`; neither imports the application it is
mounted in, which is why nothing here runs a second server.

Then `pip install -e .` beside Leela. `libraries()` finds it, `palette()` merges it with
everything else installed, and a document embeds it as `src=sales_bricks:pipeline.stages`. A
document whose interpreter has no `sales_bricks` takes the second wiring instead:

```python
import json, urllib.request
_ports = json.load(urllib.request.urlopen('http://127.0.0.1:5010/bricks/data/pipeline.stages'))
stages = _ports['stages']
```

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
