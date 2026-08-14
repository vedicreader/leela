# Multi-workspace and multi-window architecture

## Implemented foundation

Leela now supports independent app-window workspaces with:

- host-routed `WorkspaceHub` applications at `workspace.localhost`;
- one mutable `Workspace`, document store, agent, terminal set, and kernel pool per project;
- one shared `RuntimeBroker` with a hard, non-evicting process admission limit;
- one shared jupygate process and jupyasyncclient transport in app mode;
- one persistent CDP Chrome profile reused through `fossick.cdp.cdp_setup`;
- py2app and py2exe standalone build definitions.

The remaining `ClientSession` extraction described below is needed when two independent
windows attach to the *same* workspace. Different workspace windows are isolated now.

## Decision

Treat these as three different lifetimes:

1. **Leela daemon** — one long-lived local process per user profile.
2. **Workspace session** — roots, open documents, run configurations, terminals, agent history, and UI preferences for one project/window group.
3. **Kernel runtime** — an independently supervised process that a workspace attaches to by an opaque runtime id.

A browser window is a client of a workspace session. It must not *be* the session, and a
kernel must not belong to a browser connection. Closing or refreshing Chrome should detach
the client without killing either.

The current `ide_app(ws)` has one process-global `Workspace`, including `ws.active`. That is
fine for one synchronized browser surface, but two independent windows would race on active
tab, watched environment, and in-memory notebook documents. Do not solve this by starting a
full Leela and Chrome process for every window. Move browser-specific selection into a
server-side `ClientSession`, and keep project and runtime state below it.

## Proposed ownership

```text
LeelaDaemon
├── WorkspaceRegistry
│   ├── WorkspaceSession A
│   │   ├── roots / search index / git repositories
│   │   ├── document store (versioned buffers)
│   │   ├── agent conversation(s)
│   │   └── client sessions
│   │       ├── window 1: active tab, pane sizes, selected runtime
│   │       └── window 2: active tab, pane sizes, selected runtime
│   └── WorkspaceSession B
└── RuntimeBroker
    ├── runtime id -> kernel gateway id
    ├── leases and last-used timestamps
    └── memory / process telemetry
```

A URL should identify both levels, for example:

```text
/app/w/{workspace_id}?client={client_id}
```

The client id can be stored in `sessionStorage`, not `localStorage`, so duplicated windows
start independent UI sessions while reloads preserve the same one.

## Kernel transport

The AnswerDotAI projects suggest a cleaner boundary than embedding one
`AsyncKernelManager` and five ZMQ channels per Leela process:

- **jupygate** owns kernel processes and one persistent ZMQ channel set per kernel. Browser
  clients can disconnect without disturbing ZMQ, replies route by Jupyter session id, IOPub
  broadcasts, and per-client queues have explicit overflow behavior.
- **jupyasyncclient** gives Leela an awaited HTTP/WebSocket client and a keyed multi-kernel
  manager. It removes ZMQ and Tornado details from the IDE process.
- **kernmini** is the protocol-complete kernel core. Its JEP 65 readiness, process-group
  teardown, bounded IOPub, JEP 91 subshells, and optional `debug_request` capability are the
  relevant pieces for Leela.
- **jupywire** is the small protocol common layer. Prefer it when a direct transport remains
  necessary; do not duplicate signing and frame handling in Leela.
- **mdhtml** is unrelated to kernel scale. It is relevant later if Leela replaces the current
  browser-side Markdown rendering with one structural, safe Markdown/MDHTML pipeline.

### Migration sequence

1. `Kernel` and `GatewayKernel` already implement the same workspace-facing surface:
   `execute`, `complete`, `inspect_obj`, `interrupt`, `restart`, `api`, `alive`, and `pid`.
2. Direct local ZMQ remains available as `--transport direct`.
3. `GatewayKernel` uses jupyasyncclient and the supervised `GatewayService`; app mode selects
   it automatically.
4. `RuntimeBroker` currently provides global admission control. The next step is moving all
   runtime ids and lifecycle ownership into it so workspaces never receive concrete clients.
5. Add reconnect/load tests under forced IOPub backpressure before making gateway transport
   the default for non-app browser sessions.

This is an incremental transport replacement, not a frontend rewrite.

## Avoiding memory overload

“One kernel per notebook” gives strong isolation but is the largest memory multiplier. Use an
explicit runtime policy instead of silently changing that promise:

- Source files continue to share a project runtime.
- A notebook defaults to a private runtime while active.
- Clean, idle private runtimes become **suspend candidates** after a configurable timeout.
- First implementation: shut down an idle runtime only after recording that its namespace
  will be lost, then show the tab as detached. Never imply live variables survived.
- Later implementation: optional checkpoint/restore can serialize only supported values;
  it must remain visibly different from a live namespace.
- Put hard caps on simultaneously warm local model engines and kernels. Eviction is LRU among
  idle, unpinned runtimes; running, dirty, or debug-paused runtimes are never evicted.
- A single jupygate process multiplexes transport but does **not** remove each kernel's Python
  heap. The broker still needs RSS telemetry and admission control.

JEP 91 subshells can reduce the number of kernels for deliberately shared notebooks, but a
subshell is not a memory-isolation boundary. Make that an opt-in attachment mode.

## Debugging

The Debug menu now exposes existing run, interrupt, and restart operations, while step actions
remain disabled rather than pretending that execution control exists. Implement stepping over
the Jupyter `debug_request` protocol and Debug Adapter Protocol (DAP):

1. Add debug capability reporting to `RuntimeClient`.
2. Add request/reply methods for `debug_request` and route debug events separately from cell
   output.
3. Start with kernels backed by kernmini/ipymini that advertise `debug_request`; disable the
   controls for others.
4. Store breakpoints in the workspace, but store paused thread/frame selection in the client
   session.
5. Add Variables scopes for locals, globals, and watches without replacing Leela's existing
   live inspector.

`Step into`, `step over`, and `continue` should only become enabled after the runtime confirms a
paused debug session.

## Chrome / CDP packaging

Do **not** launch one Chrome process per workspace. Use one CDP-enabled Chrome profile and open
one app window per workspace URL. Chrome already isolates renderer processes where needed;
a browser process per project duplicates caches, GPU services, extensions, and the profile.

Recommended launch shape:

```sh
chrome --remote-debugging-port=9223 --app=http://127.0.0.1:PORT/app/w/WORKSPACE_ID
```

Use a dedicated Leela browser profile if Leela needs predictable app-window behavior. Keep the
CDP endpoint bound to loopback and never put Leela's kernel owner tokens in the page. The Leela
daemon remains the same-origin proxy to runtimes, as it is today.

A separate Chrome instance is justified only for a different security profile or test
isolation, not for ordinary workspace isolation.

## Responsive contract

Below 1100 px, the editor stays in the document flow and left/right work areas become overlay
drawers. No feature is removed solely because the viewport is narrow. At smaller widths:

- project and branch identities truncate;
- the menubar yields to the command palette;
- Files/Structure/Git and Agent/Variables remain reachable through edge restore controls;
- the bottom dock keeps a minimum editor height;
- the agent composer keeps model, reasoning, and send controls under the growing prompt.

Touch targets and a dedicated mobile activity trigger can be enlarged later without changing
this layout model.

## Near-term implementation order

1. Add `WorkspaceRegistry` and stable workspace ids.
2. Extract `ClientSession` from `Workspace.active`, `env_base`, and UI-local document selection.
3. Version document writes so two windows cannot silently overwrite each other.
4. Add `RuntimeClient` and `RuntimeBroker` while retaining current direct kernels.
5. Add jupygate/jupyasyncclient as an optional transport and measure RSS, startup, completion
   latency, reconnect behavior, and IOPub backpressure.
6. Implement DAP stepping only after the runtime boundary is stable.
