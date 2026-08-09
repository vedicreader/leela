# Blocks

How Leela's features are being factored, and what you need to know to write or move one.

Inspired by [lego](https://github.com/Karthik777/lego), where each feature is a folder with
a `connect(app)` function. Leela follows that shape and adds one thing lego does not need —
see [Capabilities](#capabilities) for why.

## The shape

```
leela/blocks/git/
    __init__.py
    cfg.py        # settings and defaults this block owns
    svc.py        # the domain service — no web imports, testable alone
    ui.py         # FastHTML fragments
    app.py        # routes + connect(app, ctx)
    git.css       # optional, block-owned
    git.js        # optional, block-owned
```

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

1. Blocks import `leela.core`. `leela.core` imports no block. Blocks do not import each
   other — anything two need belongs in core or in a shared service.
2. `svc.py` has no web imports. If it needs a request, it is not a service.
3. Declare `CAPS` once the block's routes have settled.
4. A block owns its CSS and JS. Assets are concatenated at build time; nothing about
   serving changes.
5. Tests for a block construct a `Ctx` over a fake, not a whole `Workspace`.

## Extraction status

Blocks are moved out of `ide_app` a group at a time. What has moved:

| block | routes | caps |
|---|---|---|
| `keys` | `/keys.json`, `/keys/{file,save,reset}` | — |
| `settings` | `/settings`, `/settings/{save,reset}` | `fs` |
| `search` | `/search`, `/code/*`, `/outline`, `/similar`, `/clusters` | `search` |
| `memory` | `/memory/*` | `memory` |

Still closures inside `leela/web/app.py`, in the order they are planned to move: `fs`,
`git`, `term`, `research`, `runs`, `tabs`, `editor`, `vars`, `nb`, `exec`, `debug`,
`agent`. The hardest are last on purpose — `agent` is 45 routes, and `nb`/`debug` share the
run locks and debugger state that `leela/core/session.py` exists to hold.

`DocStore` is already live: the closure names `_docs`, `_buffers`, `_buffer_bases` and
`_run_locks` are the same objects it holds, so routes that have not moved keep working
unchanged. `DebugState` and `RunState` are defined but not yet supplied to `connect_all`,
because the debugger closures have not moved — a `Ctx` must never hand a block a capability
that is not the live one.

## Ports

Selecting an alternate implementation, writing an adapter and checking it conforms are
covered in **[Plugging in vishalakshi and ramabana](integration.md)**. In short:

Three subsystems are getting alternate implementations —
[vishalakshi](https://github.com/vedicreader/vishalakshi) for memory and retrieval,
[ramabana](https://github.com/vedicreader/ramabana) for agent runtimes. `leela/core/ports.py`
writes down what Leela actually depends on, as `Protocol`s extracted from the current call
sites rather than from the classes:

| port | satisfied today by | alternate |
|---|---|---|
| `MemoryPort` | `leela.memory.Memory` (litesearch) | `vishalakshi.Vault` |
| `SearchPort` | `leela.search.Search` (Kosha + ripgrep) | vishalakshi's code leg |
| `RuntimePort` | `leela.agent.runtime.Backend` | ramabana |

They are structural: the current classes satisfy them without importing or inheriting
anything. `tests/test_core_ctx.py` asserts conformance, which is what keeps a port honest
as the class it was extracted from changes.

Memory and search are separate ports on purpose. Source code is an AST-shaped corpus and
prose is a document tree — `leela/memory.py` says so at the top — and a single "retrieval"
port would fuse them at exactly the moment an alternate is being introduced.

`RuntimePort` covers mechanism only: history, streaming, tools, cancellation. Compaction
(`Compactor`), token accounting (`Usage`) and model resolution (`ModelSpec`, `Routing`) are
Leela's policy about how to *use* a runtime, and keeping them out of the port is what lets
two runtimes be compared on equal terms.
