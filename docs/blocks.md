# Blocks

How Leela's features are factored, and what you need to know to write or move one.

The shape comes from [lego](https://github.com/Karthik777/lego), where each feature is a
folder with a `connect(app)` function. Leela adds one thing lego does not need. See
[Capabilities](#capabilities) for why.

## The shape

```
leela/blocks/git/
    __init__.py   # lazy `connect`/`CAPS`, and the port default if this block owns one
    git.py        # the domain. No web imports, testable alone
    ui.py         # FastHTML fragments
    app.py        # routes + connect(app, ctx)
    git.css       # optional, block-owned
    git.js        # optional, block-owned
```

The domain module keeps its own name: `git.py`, `fs.py`, `kernels.py`, rather than a uniform
`svc.py`. These files were `leela/git.py` and `leela/fs.py` before they moved into the blocks
that own them. Keeping the name means `git log --follow` still works, and a reader looking
for git code finds a file called git.

`__init__.py` must not import `app.py` eagerly. `leela/blocks/_lazy.py` writes that once:

```python
# leela/blocks/git/__init__.py
from .._lazy import lazy_app

__all__ = ['connect', 'CAPS']

__getattr__ = lazy_app(globals())
```

`app.py` imports fasthtml, and importing a package runs its `__init__`. A plain
`from .app import CAPS, connect` would therefore mean that reading a git repository loads the
routes that serve git repositories. `Workspace` composes these domains, so that cost lands on
every CLI invocation, every test, and the dev-server child. It regressed exactly that way
once and the whole suite stayed green.
`tests/test_core.py::test_importing_every_block_domain_never_loads_a_route_module` catches it
now.

```python
# leela/blocks/git/app.py
from leela.core import Ctx
from . import ui

CAPS = ('fs', 'jobs')

def connect(app, ctx):
    rt = app.route

    @rt('/git/info')
    def git_info(): return ui.info(ctx.fs)

    @rt('/git/diff')
    def git_diff(path: str): return ui.diff(ctx.fs, path)
```

Wiring is ordered, in one place:

```python
BLOCKS = [keys_block, settings_block, search_block, memory_block, jobs_block, ...]
connect_all(app, workspace, BLOCKS, gate=gate, catalog=catalog)
```

## Capabilities

lego's blocks are unrelated features that share a database and little else. A blog block does
not care what auth does internally. Leela's panels are one application over a shared live
namespace. The notebook, the variable panel, the kernel, the debugger and the agent all touch
the same kernel and the same document. Copying `connect(app)` alone would give tidy folders
with every bit of the old coupling intact, because each block would still reach into the
whole `Workspace`.

So `connect` receives a `Ctx`: the capability surface, narrowed to what the block declared in
`CAPS`.

```python
CAPS = ('fs', 'journal')     # ctx.fs and ctx.journal work. ctx.memory raises
```

Two kinds of thing hang off a workspace, and only one of them is a capability.

Capabilities are services a block uses: `fs`, `pool`, `search`, `memory`, `research`, `runs`,
`journal`, `terms`, `dev`, `approvals`, `jobs`, `vaults`, `ai`, `inline_ai`, `completer`,
`lsp`, `tab`, `pending_approval`. They are declared, narrowed, and swappable.

Session state is the mutable facts about this workspace, shared by everything: `tabs`,
`active`, `model`, `agent_state`, `screen`. A block reaches them through `ctx.session`.

A block that omits `CAPS` is unrestricted. That is deliberate. It lets routes move out of
`ide_app` one block at a time, without the whole extraction landing in one commit. Adding
`CAPS` afterwards is the second, smaller step.

### Cost

Measured with `uv run python tools/bench_ctx.py`:

| | |
|---|---|
| `ctx.fs` (eager) | **18.9 ns** against `ws.fs` at 19.4 ns |
| `ctx.ai` (lazy) | 149 ns against `ws.ai` at 46 ns |
| `Ctx(...)` construction | about 1.5 µs, once per block per workspace |

Eager capabilities are around 90% of all access, and they are slightly faster than the status
quo. They are `__slots__` descriptor reads, where `ws.fs` is an instance-dict lookup.

Lazy ones cost about 103 ns more, on paths that are about to call a model or open a language
server. About 39 ns of that is `Ctx.__getattr__`, which turns an undeclared capability into a
message naming the block and the fix. Defining it switches CPython to the hooked attribute
path, which the lazy property body pays for several times over, and it is free on the eager
path. The benchmark prints the two separately so the trade cannot drift unnoticed.

### Why some capabilities are lazy

`ai`, `inline_ai`, `completer` and `lsp` construct something expensive on first touch.
`Workspace.ai` builds an `Assistant` and resolves a model. Binding those eagerly at connect
time would pay that cost for every workspace at startup, including one whose user never opens
the agent pane. `tab` and `pending_approval` are cheap, but they read mutable state, so
capturing them once would hand the block a stale answer.

A test enforces this:
`tests/test_core.py::test_building_a_ctx_does_not_construct_the_assistant`.

## Order matters

lego's auth block reads a skip list that earlier blocks append to. Leela has no such
handshake. What it has is Starlette's router, where the first matching route wins. A block
registering a catch-all before the specific routes shadows all of them.

`connect_all` preserves the order it is given, and `tests/test_core.py` catches a block that
drops or shadows a path. It pins the whole 273-route URL surface against `tests/routes.txt`.
When you add or remove a route on purpose:

```sh
uv run python -m tests.test_core --routes     # regenerate, then commit the diff
uv run python -m tests.test_core              # which module serves each path
```

## Rules

1. Blocks import `leela.core`, and `leela.core` imports no block. This is the one hard
   direction. Anything two blocks need belongs in core. Anything that must name an
   implementation belongs above the blocks, the way `leela/conformance.py` does.
2. A block may import another block's domain module, as in `from ..git.git import GitRepo`.
   Never its `app.py` or its `ui.py`. Routes are a block's outside, and two blocks sharing one
   means the thing belongs in core.
3. The domain import graph stays acyclic. Two blocks that genuinely need each other are one
   block.
4. The domain module has no web imports. If it needs a request, it is not a domain.
5. `__init__.py` resolves `connect` and `CAPS` lazily, so importing a domain never loads a
   route module.
6. Declare `CAPS` once the block's routes have settled.
7. A block owning a port registers the default for it in its own `__init__.py`, beside the
   module that satisfies it. See [Ports](#ports).
8. A block owns its CSS and JS. `lee-ide.css` is still one authored file. Client JS is split
   into modules under `leela/static/js/` and concatenated into the served
   `leela/static/lee-ide.js` by `tools/build_ide_js.py`. Edit a module, then rebuild.
   `tests/blocks/test_web_block.py` fails when the two drift. The split is by feature and
   already matches the block names. Moving a module into its block waits until that block's
   routes leave `ide_app`.
9. Tests for a block construct a `Ctx` over a fake, not a whole `Workspace`.

Rules 1 to 3 and rule 5 are enforced by `tests/test_core.py`. Each of those tests has been
checked to fail when its rule is broken, because a guard that cannot fail is worse than none.

## Extraction status

Blocks move out of `ide_app` a group at a time. Twenty-one blocks are connected and serve 178
of the 273 registered routes. The closure in `leela/app.py` still serves 93, and a `Mount` and
a `HostRoute` account for the last two.

| block | routes | caps |
|---|---|---|
| `jobs` | 35 | `fs`, `memory`, `search`, `jobs`, `tab`, `vaults` |
| `git` | 24 | `fs`, `jobs` |
| `runtime` | 16 | `fs`, `pool`, `dev`, `terms`, `tab`, `docs` |
| `fs` | 11 | `fs`, `journal` |
| `search` | 10 | `search`, `fs` |
| `workflows` | 10 | `fs` |
| `tabs` | 10 | `fs`, `pool`, `tab`, `docs` |
| `pipelines` | 8 | `fs`, `gate` |
| `memory` | 7 | `memory` |
| `vars` | 7 | — |
| `lsp` | 5 | `lsp`, `fs`, `journal` |
| `refactor` | 5 | `fs`, `journal`, `tab`, `docs` |
| `keys` | 4 | — |
| `research` | 4 | `research` |
| `workspace` | 4 | `fs`, `tab`, `catalog` |
| `drive` | 4 | `fs`, `gate` |
| `stack` | 4 | `fs` |
| `settings` | 3 | `fs` |
| `term` | 3 | `terms`, `fs`, `gate` |
| `runs` | 2 | `runs`, `dev`, `tab` |
| `editor` | 2 | `fs`, `pool` |

Two blocks exist without being connected. `nb` and `debug` hold their domain modules with no
`app.py` and no entry in `BLOCKS`, so their routes land in an existing home when they move,
rather than forcing another restructure.

What is still a closure inside `ide_app`, in the order it is planned to move: `nb`, `debug`,
`agent`, then `exec`, `run`, `history`, `diff`, `lint`, `markdown`, `screen`,
`tabs/save-all`, and the shell itself (`/`, `_shell`, `/fs/add_root`). The hardest are last on
purpose. `agent` is the single biggest group, and `nb` and `debug` share the run locks and
debugger state that `leela/core/session.py` exists to hold.

`DocStore` and `RunState` are live. The closure names `_docs`, `_buffers`, `_buffer_bases`,
`_run_locks` and `running_cells` are the same objects they hold, so routes that have not moved
keep working unchanged. `DebugState` is defined but not yet supplied to `connect_all`, because
the debugger closures have not moved. A `Ctx` must never hand a block a capability that is not
the live one.

### What the guardrails do and do not catch

`tests/routes.txt` has held the same 273 entries through every extraction, which is what
proves no route was dropped. It cannot catch everything. Twice, a move broke rendering while
the URL surface stayed correct: once by changing `files_panel`'s parameter without updating
`ide_app`'s call site, once by cutting a group that contained `_disk_version` while `/nb/save`
still used it. Both failed at call time, and the web tests caught both within one run.

The lesson worth carrying: keep the move behaviour-identical, read the code you are moving
rather than reconstructing it, and run the whole suite rather than the route inventory alone.
Reconstructing `/tab/state`'s text branch from memory produced three differences from the
original. One was `buffers.get(key) or …` where the original used `key in buffers`, which
would have fallen through to disk for a buffer holding the empty string.

Collapsing `leela/web/` into the root added four more, and a test caught only two of them.

A module path in a string. `DevServer._cmd()` re-execs the child as
`python -m leela.devserver`. No import rewrite touches a string literal, and
`tests/test_runtime.py` caught it. Grep for the module's dotted name, not just its import
statements.

A `Mount` that served the right file by accident. Splitting `static/` from `vendor/` needed
one URL prefix over two directories. The first attempt read `scope['path']`, which Starlette
leaves absolute under a `Mount`. Nothing matched, every request fell through to the authored
`StaticFiles`, and authored assets kept working while every vendored one 404'd. The URL
surface was unchanged, so `routes.txt` stayed silent. A test that actually fetched a font
caught it.

An import cost nothing asserts on. Moving the domains into the blocks made
`import leela.workspace` load seven route modules, because each `__init__` still imported
`app.py`. No test failed. Measuring `sys.modules` after an import is now a test.

A packaging bug that predated the move. `data_files` used a non-recursive `iterdir()`, so
frozen builds had shipped no fonts at all. Nothing tests the frozen bundle. It surfaced only
from reading the line while changing its path.

## Ports

Selecting an alternate implementation, writing an adapter and checking it conforms are covered
in [Plugging in vishalakshi and ramabana](integration.md). In short:

Three subsystems take alternate implementations.
[vishalakshi](https://github.com/vedicreader/vishalakshi) covers memory and retrieval, and
[ramabana](https://github.com/vedicreader/ramabana) is the agent runtime.
`leela/core/ports.py` writes down what Leela depends on, as `Protocol`s taken from the current
call sites rather than from the classes.

| port | owned by | satisfied today by | alternate |
|---|---|---|---|
| `MemoryPort` | `blocks/memory` | `blocks.memory.memory.Memory` (litesearch) | `vishalakshi.Vault` |
| `SearchPort` | `blocks/search` | `blocks.search.search.Search` (Kosha + ripgrep) | vishalakshi's code leg |
| `RuntimePort` | `blocks/agent` | `ramabana.runtime.Backend` | any other harness |

They are structural. The current classes satisfy them without importing or inheriting
anything, and `tests/test_core.py` asserts conformance, which keeps a port honest as the class
it came from changes.

The block that owns a port registers the default for it, in its own `__init__.py`, beside the
module that satisfies it:

```python
# leela/blocks/memory/__init__.py
@provider('memory', DEFAULT)
def _memory(kosha=None, path=None, **kw):
    from .memory import Memory
    return Memory(kosha=kosha, path=path, **kw)
```

`core/ports.py` therefore names no implementation at all. It is the registry and nothing else.
That is what makes `LEELA_MEMORY=vishalakshi` a swap of one folder for one package. The
built-in and the alternate arrive through an identical path, so no privileged route exists
that only the default takes, and no branch goes untested for the alternates.
`leela/blocks/__init__.py` imports the three owning blocks, so the registrations exist before
`Workspace.__init__` calls `build()`.

`RuntimePort` is owned by `blocks/agent`, but the harness it wraps is not in the block.
`leela/agent/` is six lines of alias over `ramabana`, which imports nothing from leela.

Git is the same arrangement without a port. `ramabana.git` owns the gateway that runs every
command, the safepoint journal behind `undo`, the porcelain, and the git tools an agent is
offered inside a checkout; `blocks/git` is the browser surface over it, plus `blame_notebook`,
which needs the IDE's cell-to-line mapping, and `RepoSet`, which is workspace state rather than
a git concern. The block sets `gateway().env_for` at import, because knowing that a checkout
has its own virtualenv is Leela's knowledge, not the harness's.
`tests/test_agent.py::test_agent_package_does_not_import_leela` enforces that, and it is what
lets the whole agent loop be tested against a dict rather than an IDE. `blocks/agent/` holds
the adapter: `ai.py` and `models.py`.

Memory and search are separate ports on purpose. Source code is an AST-shaped corpus and prose
is a document tree, as `blocks/memory/memory.py` says at the top. A single retrieval port would
fuse them at exactly the moment an alternate is being introduced.

`RuntimePort` covers mechanism only: history, streaming, tools, cancellation. Compaction
(`Compactor`), token accounting (`Usage`) and model resolution (`ModelSpec`, `Routing`) are
Leela's policy about how to use a runtime. Keeping them out of the port is what lets two
runtimes be compared on equal terms.
