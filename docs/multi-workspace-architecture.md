# Multi-workspace and multi-window architecture

How one Leela process serves several independent projects, and where the boundaries
between them actually are.

## The problem

A `Workspace` is the IDE's session: open folders, open tabs, and the kernels behind them.
It owns a `Sandbox` over its roots, a `KernelPool`, an `Assistant`, a `Terminals` gate, a
`Memory`, a `Search` index and an `OperationJournal`. Nearly all of that is mutable, and
none of it is meaningful across projects — two folders open at once want two variable
panels, two kernels and two agent conversations, not one of each shared badly.

Running a second OS process per folder would give that isolation for free, and cost a
second resident Chrome, a second model in memory and a second index. So the isolation is
drawn *inside* one process instead.

## Workspace identity is the host name

Each workspace gets a slug, and the slug becomes a `*.localhost` subdomain:

```
project.localhost:5001     ->  Workspace(roots=[~/code/project])
tests.localhost:5001       ->  Workspace(roots=[~/code/tests])
```

`workspace_slug` (`leela/web/workspaces.py`) derives it from the folder name, lowercasing
and collapsing anything that is not `[a-z0-9]` to `-`, then disambiguating with a numeric
suffix. `*.localhost` resolves to loopback without touching `/etc/hosts` or DNS, on every
platform Leela supports.

Carrying identity in the host rather than a path prefix is what makes this cheap: every
absolute route the browser already uses — `/nb/run`, `/vars`, `/git/diff` — stays valid
verbatim. A path prefix (`/w/project/nb/run`) would have meant rewriting every route, every
`hx-post` and every `fetch` in the frontend.

## Dispatch

`WorkspaceHub` is a plain ASGI callable in front of the per-workspace apps:

```
uvicorn -> LoopbackHostGuard -> WorkspaceHub -> WorkspaceSite.app  (a full ide_app)
```

`WorkspaceHub.site_for` reads the `Host` header, strips the port and any IPv6 brackets, and
looks the slug up. Three outcomes:

- `<slug>.localhost` — that workspace's app.
- bare `127.0.0.1`, `localhost`, `::1` or empty — the *default* workspace. This exists for
  the startup health probe, and is the only intentional route to a workspace by an
  unqualified name.
- anything else — `421 Misdirected Request`, or a `1008` close for a WebSocket.

The unknown-host case is a refusal rather than a fallback on purpose: silently serving the
default workspace to an unrecognised `Host` would make the workspace boundary depend on a
header the page does not control.

The matched slug is written back into the ASGI scope as `leela.workspace_id`, so anything
downstream can tell which workspace it is inside without re-parsing the header.

## Why there is a host guard at all

These routes execute code. `LoopbackHostGuard` runs *before* dispatch and requires all
three of:

- **`Host`** is loopback or `*.localhost` — blocks DNS rebinding, where an attacker's
  domain resolves to `127.0.0.1` and a browser is tricked into posting to `/exec`.
- **`Origin`**, when present, is loopback — blocks a page on another origin from driving
  the IDE.
- **`Sec-Fetch-Site`** is not `cross-site` — the browser's own account of where the request
  came from, which does not rely on Leela's parsing being right.

`serve_ide` separately refuses to bind to anything that is not a loopback address, so the
guard is a second line rather than the only one.

## What is shared and what is not

Per workspace — one each:

| | |
|---|---|
| `Workspace` | tabs, active index, roots |
| `Sandbox` | the roots writes are confined to |
| `KernelPool` | kernels, and the inspector port each one hosts |
| `Assistant` | agent conversation, model choice, approvals |
| `Terminals` | shell sessions |
| `Search` / `Memory` | the code index and prose corpus for these roots |
| `OperationJournal` | undo history, keyed by a hash of the roots |

Shared across the whole process — one each:

| | |
|---|---|
| uvicorn / the event loop | one ASGI server |
| the resident Chrome | `--app` reuses fossick's CDP profile on port 9223 |
| `GatewayService` | when `--transport gateway`, one jupygate for every workspace |
| the embedding model | `Memory` borrows Kosha's already-resident embedder |

The last two are the reason this design exists. A model and a gateway are expensive and
genuinely stateless with respect to which project is asking; a variable panel is neither.

## Kernel transports

`KernelPool` speaks one of two transports, chosen per pool:

- **`direct`** — Leela's own ZMQ client to a locally launched kernel. The default for the
  browser workspace. Local IPC where the platform has it, loopback TCP with required
  transport encryption on Windows, which has no ZeroMQ IPC.
- **`gateway`** — kernels hosted by a shared `jupygate` process, reached over the
  jupygate transport. The default under `--app`, so several app windows share one kernel
  host instead of each launching its own.

`--transport auto` (the default) resolves to `gateway` for app windows and `direct`
otherwise, and degrades to `direct` if the optional `leela[gateway]` extra is not
installed. An explicit `--transport gateway` is a hard requirement and raises instead.

Variable data is always *proxied* through the workspace's own app rather than fetched
cross-origin. Each kernel hosts its own dhrishti inspector on its own port; letting the
page reach those directly would mean CORS on every kernel and the owner token living in
the browser. Proxying keeps the token server-side and the page single-origin — which is
also what makes the host guard above sufficient.

## App windows

`leela --app src tests` opens two independent app windows in the persistent CDP Chrome
(`fossick.cdp.cdp_setup`, port 9223) rather than starting a resident Chrome per folder.
Each window points at its own `<slug>.localhost:5001`, so window separation and workspace
separation are the same mechanism seen from two ends.

## Where this is going

The pieces above are in place. What is not yet factored out:

- **Project sessions** — workspace state currently lives for as long as the process. A
  session that can be detached and re-attached would let a window close without losing
  kernels.
- **A runtime broker** — `KernelPool` decides both *which* kernel a tab gets and *how* it
  is launched. Splitting the choice from the launching is what would let a workspace
  borrow a kernel that another workspace already has warm.
- **Block-owned routes** — `ide_app` is one function registering ~180 routes over one
  `Workspace`. See [`leela/core/`](../leela/core/__init__.py) for the `Ctx` capability
  object and the block contract that the extraction is moving toward.
