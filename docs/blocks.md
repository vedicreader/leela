# Blocks

How Leela's features are being factored, and what you need to know to write or move one.

Inspired by [lego](https://github.com/Karthik777/lego), where each feature is a folder with
a `connect(app)` function. Leela follows that shape and adds one thing lego does not need —
see [Capabilities](#capabilities) for why.

## The shape

```
leela/blocks/git/
    __init__.py   # lazy `connect`/`CAPS`, and the port default if this block owns one
    git.py        # the domain — no web imports, testable alone
    ui.py         # FastHTML fragments
    app.py        # routes + connect(app, ctx)
    git.css       # optional, block-owned
    git.js        # optional, block-owned
```

The domain module keeps its own name — `git.py`, `fs.py`, `kernels.py` — rather than a
uniform `svc.py`. These files were `leela/git.py` and `leela/fs.py` before they moved into
the blocks that own them, and keeping the name means `git log --follow` still works and a
reader looking for git code finds a file called git.

`__init__.py` must not import `app.py` eagerly:

```python
# leela/blocks/git/__init__.py
def __getattr__(name):
    if name in ('CAPS', 'connect'):
        from . import app
        v = globals()[name] = getattr(app, name)
        return v
    raise AttributeError(name)
```

`app.py` imports fasthtml, and importing a package runs its `__init__` — so a plain
`from .app import CAPS, connect` means that reading a git repository loads the routes that
serve git repositories. `Workspace` composes these domains, so that cost lands on every CLI
invocation, every test, and the dev-server child. It regressed exactly that way once, and the
whole suite stayed green;
`tests/test_blocks.py::test_importing_every_block_domain_never_loads_a_route_module` is what
catches it now.

```python
# leela/blocks/git/app.py
from leela.core import Ctx
from . import ui

CAPS = ('fs', 'journal')

def connect(app, ctx):
    rt = app.route

    @rt('/git/info')
    def git_info(): return ui.info(ctx.fs)

    @rt('/git/diff')
    def git_diff(path: str): return ui.diff(ctx.fs, path)
```

Wiring is ordered, in one place:

```python
blocks = [keys, settings, fs, git, tabs, editor, vars, nb, agent, memory]
connect_all(app, workspace, blocks, gate=gate, catalog=catalog)
```

## Capabilities

lego's blocks are unrelated features that share a database and little else; a blog block
does not care what auth does internally. Leela's panels are one application over a shared
live namespace — the notebook, the variable panel, the kernel, the debugger and the agent
all touch the same kernel and the same document. Copying `connect(app)` alone would give
tidy folders with every bit of the old coupling intact, because each block would still
reach into the whole `Workspace`.

So `connect` receives a `Ctx`: the capability surface, narrowed to what the block declared
in `CAPS`.

```python
CAPS = ('fs', 'journal')     # ctx.fs and ctx.journal work; ctx.memory raises
```

Two kinds of thing hang off a workspace, and only one of them is a capability:

- **Capabilities** — `fs`, `pool`, `search`, `memory`, `research`, `runs`, `journal`,
  `terms`, `dev`, `approvals`, `ai`, `inline_ai`, `completer`, `lsp`, `tab`,
  `pending_approval`. Services a block *uses*. Declared, narrowed, and swappable.
- **Session state** — `tabs`, `active`, `model`, `agent_state`, `screen`. Mutable facts
  about this workspace, shared by everything. Reached through `ctx.session`.

A block that omits `CAPS` entirely is unrestricted. That is deliberate: it lets routes move
out of `ide_app` one block at a time without the whole extraction having to land in one
commit. Adding `CAPS` afterwards is the second, smaller step.

### Cost

Measured with `uv run python tools/bench_ctx.py`:

| | |
|---|---|
| `ctx.fs` (eager) | **18.9 ns** vs `ws.fs` at 19.4 ns |
| `ctx.ai` (lazy) | 149 ns vs `ws.ai` at 46 ns |
| `Ctx(...)` construction | ~1.5 µs, once per block per workspace |

Eager capabilities — around 90% of all access — are *slightly faster* than the status quo:
they are `__slots__` descriptor reads, where `ws.fs` is an instance-dict lookup.

Lazy ones cost ~103 ns more, on paths that are about to call a model or open a language
server. About 39 ns of that is `Ctx.__getattr__`, which turns an undeclared capability into
a message naming the block and the fix; defining it switches CPython to the hooked
attribute path, which the lazy property body pays for several times over. It is free on the
eager path. That trade is deliberate, and the benchmark prints it separately so it cannot
drift unnoticed.

### Why some capabilities are lazy

`ai`, `inline_ai`, `completer` and `lsp` construct something expensive on first touch —
`Workspace.ai` builds an `Assistant` and resolves a model. Binding those eagerly at connect
time would pay that cost for every workspace at startup, including one whose user never
opens the agent pane. `tab` and `pending_approval` are cheap but read mutable state, so
capturing them once would hand the block a stale answer.

This is enforced, not just documented:
`tests/test_core_ctx.py::test_building_a_ctx_does_not_construct_the_assistant`.

## Order matters

lego's auth block reads a skip list that earlier blocks append to. Leela has no such
handshake; what it has is Starlette's router, where the **first matching route wins**. A
block registering a catch-all before the specific routes shadows all of them.

`connect_all` preserves the order it is given.
`tests/test_route_inventory.py` catches a block that drops or shadows a path — it pins the
whole ~180-route URL surface against `tests/routes.txt`. When you add or remove a route on
purpose:

```sh
uv run python -m tests.test_route_inventory     # regenerate, then commit the diff
```

## Rules

1. Blocks import `leela.core`. **`leela.core` imports no block.** This is the one hard
   direction. Anything two blocks need belongs in core; anything that must name an
   implementation belongs *above* the blocks, the way `leela/conformance.py` does.
2. A block may import another block's **domain module** — `from ..git.git import GitRepo`.
   Never its `app.py` or its `ui.py`: routes are a block's outside, and two blocks sharing
   one means the thing belongs in core.
3. The domain import graph stays acyclic. Two blocks that genuinely need each other are one
   block.
4. The domain module has no web imports. If it needs a request, it is not a domain.
5. `__init__.py` resolves `connect` and `CAPS` lazily, so importing a domain never loads a
   route module.
6. Declare `CAPS` once the block's routes have settled.
7. A block owning a port registers the default for it in its own `__init__.py`, beside the
   module that satisfies it — see [Ports](#ports).
8. A block owns its CSS and JS. `lee-ide.css` is still one authored file. Client JS is
   split into modules under `leela/static/js/`, concatenated into the served
   `leela/static/lee-ide.js` by `tools/build_ide_js.py`: edit a module, then rebuild.
   `tests/blocks/test_ide_bundle.py` fails when the two drift. The split is by feature and
   already matches the block names; moving a module into its block waits until that block's
   routes leave `ide_app`.
9. Tests for a block construct a `Ctx` over a fake, not a whole `Workspace`.

Rules 1–3 and 5 are enforced, not just written down, by `tests/test_blocks.py`. Each of those
tests has been checked to fail when its rule is broken — a guard that cannot fail is worse
than none.

## Extraction status

Blocks are moved out of `ide_app` a group at a time. What has moved — 15 connected blocks,
99 of the 189 registered routes:

| block | routes | caps |
|---|---|---|
| `keys` | `/keys.json`, `/keys/{file,save,reset}` | — |
| `settings` | `/settings`, `/settings/{save,reset}` | `fs` |
| `search` | `/search`, `/code/*`, `/outline`, `/similar`, `/clusters` | `search` |
| `memory` | `/memory/*` | `memory` |
| `research` | `/research/*` | `research` |
| `term` | `/term/{info,close}` | `terms`, `fs`, `gate` |
| `runs` | `/runs`, `/runs/save` | `runs`, `dev`, `tab` |
| `workspace` | `/workspace/info`, `/cwd`, `/cwd/set` | `fs`, `tab`, `catalog` |
| `git` | `/git/*` | `fs` |
| `fs` | `/tree`, `/files/panel`, `/fs/*` | `fs`, `journal` |
| `lsp` | `/lsp/*` | `lsp`, `fs`, `journal` |
| `vars` | `/vars/*`, `/inspect` | — |
| `runtime` | `/runtime/*`, `/kernel/*`, `/envs*`, `/dev/*` | `fs`, `pool`, `dev`, `terms`, `tab`, `docs` |
| `tabs` | `/tab/*` | `fs`, `pool`, `tab`, `docs` |
| `editor` | `/editor/{format,packages}` | `fs`, `pool` |

Three more blocks exist but are not connected: `nb`, `debug` and `agent` hold their domain
modules with no `app.py` and no entry in `BLOCKS`, so their routes land in an existing home
when they move rather than forcing another restructure.

`leela/app.py` is down from 3,539 lines to 2,466, and serves 88 routes; the blocks
serve the other 99, and a `Mount` and a `HostRoute` account for the last two. To check which
module is actually behind a path:

```sh
uv run python -m tests.test_route_owners
```

Still closures inside `ide_app`, in the order they are planned to move: `nb` (14 routes),
`debug` (10), `agent` (45), plus `exec`, `run`, `history`, `diff`, `lint`, `markdown`,
`screen`, `tabs/save-all` and the shell itself (`/`, `_shell`, `/fs/add_root`). The hardest
are last on purpose — `agent` is the single biggest group, and `nb`/`debug` share the run
locks and debugger state that `leela/core/session.py` exists to hold.

`DocStore` and `RunState` are live: the closure names `_docs`, `_buffers`, `_buffer_bases`,
`_run_locks` and `running_cells` are the same objects they hold, so routes that have not
moved keep working unchanged. `DebugState` is defined but not yet supplied to
`connect_all`, because the debugger closures have not moved — a `Ctx` must never hand a
block a capability that is not the live one.

### What the guardrails do and do not catch

`tests/routes.txt` has been byte-identical through every extraction, which is what proves
no route was dropped. It cannot catch everything: twice, a move broke rendering while the
URL surface stayed correct — once by changing `files_panel`'s parameter without updating
`ide_app`'s call site, once by cutting a group that contained `_disk_version` while
`/nb/save` still used it. Both failed at call time, and both were caught by the web tests
within one run.

The lesson worth carrying: keep the move behaviour-identical, read the code you are moving
rather than reconstructing it, and run the whole suite rather than the route inventory
alone. Reconstructing `/tab/state`'s text branch from memory produced three differences
from the original, including `buffers.get(key) or …` where the original used `key in
buffers` — which would have silently fallen through to disk for a buffer holding the empty
string.

Collapsing `leela/web/` into the root added four more, and only two were caught by a test:

- **A module path in a string.** `DevServer._cmd()` re-execs the child as
  `python -m leela.devserver`. No import rewrite touches a string literal; `test_runs.py`
  caught it. Grep for the module's dotted name, not just its import statements.
- **A `Mount` that served the right file by accident.** Splitting `static/` from `vendor/`
  needed one URL prefix over two directories. The first attempt read `scope['path']`, which
  Starlette leaves absolute under a `Mount` — so nothing matched, every request fell through
  to the authored `StaticFiles`, and authored assets kept working while every vendored one
  404'd. The URL surface was unchanged, so `routes.txt` was silent. A test that actually
  fetched a font caught it.
- **An import cost nothing asserts on.** Moving the domains into the blocks made
  `import leela.workspace` load seven route modules, because each `__init__` still imported
  `app.py`. No test failed. Measuring `sys.modules` after an import is now a test.
- **A packaging bug that predated the move.** `data_files` used a non-recursive `iterdir()`,
  so frozen builds had shipped no fonts at all. Nothing tests the frozen bundle; it surfaced
  only from reading the line while changing its path.

## Ports

Selecting an alternate implementation, writing an adapter and checking it conforms are
covered in **[Plugging in vishalakshi and ramabana](integration.md)**. In short:

Three subsystems are getting alternate implementations —
[vishalakshi](https://github.com/vedicreader/vishalakshi) for memory and retrieval,
[ramabana](https://github.com/vedicreader/ramabana) for agent runtimes. `leela/core/ports.py`
writes down what Leela actually depends on, as `Protocol`s extracted from the current call
sites rather than from the classes:

| port | owned by | satisfied today by | alternate |
|---|---|---|---|
| `MemoryPort` | `blocks/memory` | `blocks.memory.memory.Memory` (litesearch) | `vishalakshi.Vault` |
| `SearchPort` | `blocks/search` | `blocks.search.search.Search` (Kosha + ripgrep) | vishalakshi's code leg |
| `RuntimePort` | `blocks/agent` | `leela.agent.runtime.Backend` | ramabana |

They are structural: the current classes satisfy them without importing or inheriting
anything. `tests/test_core_ctx.py` asserts conformance, which is what keeps a port honest
as the class it was extracted from changes.

**The block that owns a port registers the default for it**, in its own `__init__.py`, beside
the module that satisfies it:

```python
# leela/blocks/memory/__init__.py
@provider('memory', DEFAULT)
def _memory(kosha=None, path=None, **kw):
    from .memory import Memory
    return Memory(kosha=kosha, path=path, **kw)
```

`core/providers.py` therefore names no implementation at all — it is the registry and nothing
else. That is what makes `LEELA_MEMORY=vishalakshi` a swap of one folder for one package: the
built-in and the alternate arrive through an identical path, so there is no privileged route
that only the default takes and no untested branch for the alternates.
`leela/blocks/__init__.py` imports the three owning blocks, so the registrations exist before
`Workspace.__init__` calls `build()`.

`RuntimePort` is owned by `blocks/agent`, but the harness it wraps is not in the block.
`leela/agent/` is a package that imports nothing from leela — enforced by
`tests/test_agent.py::test_agent_package_does_not_import_leela` — so the whole agent loop can
be tested against a dict rather than an IDE. `blocks/agent/` holds the adapter (`ai.py`,
`models.py`). Porting to ramabana replaces `leela/agent/` wholesale and leaves the block as
the wiring.

Memory and search are separate ports on purpose. Source code is an AST-shaped corpus and
prose is a document tree — `blocks/memory/memory.py` says so at the top — and a single "retrieval"
port would fuse them at exactly the moment an alternate is being introduced.

`RuntimePort` covers mechanism only: history, streaming, tools, cancellation. Compaction
(`Compactor`), token accounting (`Usage`) and model resolution (`ModelSpec`, `Routing`) are
Leela's policy about how to *use* a runtime, and keeping them out of the port is what lets
two runtimes be compared on equal terms.
