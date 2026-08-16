# Multi-workspace and multi-window architecture

Implemented: host-routed `WorkspaceHub` apps at `workspace.localhost`; one `Workspace`, document store, agent, terminals, and kernel pool per project; shared `RuntimeBroker`; shared jupygate and jupyasyncclient transport in app mode; shared fossick CDP profile; py2app and py2exe builds.

Lifetimes:

1. daemon: one local process per user profile
2. workspace: roots, documents, runs, terminals, agent state, preferences
3. runtime: supervised kernel process with an opaque id

A browser window is a workspace client. Browser state belongs in `ClientSession`.

```text
LeelaDaemon
├── WorkspaceRegistry
│   ├── WorkspaceSession
│   │   ├── roots, search, repositories
│   │   ├── documents
│   │   ├── agent conversations
│   │   └── client sessions
└── RuntimeBroker
    ├── runtime id -> gateway id
    ├── leases
    └── telemetry
```

URL shape: `/app/w/{workspace_id}?client={client_id}`.

jupygate owns kernels and ZMQ channels. jupyasyncclient provides HTTP and WebSocket clients. kernmini supplies kernel protocol behavior. jupywire supplies direct transport primitives. mdhtml remains separate.

Migration: retain direct ZMQ, add gateway transport, move runtime ownership into `RuntimeBroker`, then add reconnect and backpressure tests.

Source files share a project runtime. Active notebooks use private runtimes. Idle private runtimes become suspend candidates after a configured timeout. Shutdown records namespace loss.
