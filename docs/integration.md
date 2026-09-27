# vishalakshi and ramabana integration

`WorkspaceHost` in `leela/blocks/agent/ai.py` is what Leela hands the agent. It is a `shalya.Host`
that declares its capability groups by inheriting the class naming each one, and `Host.provides` is
the only way to ask what it supports. A host that declares a group and leaves one of that group's
methods unwritten refuses to be built, so the declaration cannot drift from the implementation.
`shalya.tools.tools_for` reads `provides` and builds exactly the tools the host can back.

| group | what it is | where Leela implements it |
|---|---|---|
| `file` | the path boundary every host has | `blocks.fs.fs.Sandbox`, through `WorkspaceHost.check` |
| `code` | search, symbols, peers, public API | `blocks.search.search.Search` |
| `notebook` | cell listing, insertion, one live run | `blocks.nb.nb` and the kernel pool |
| `web` | search, one page, a cited digest | `blocks.research.research.Research` over `shalya.host.read_page` |
| `memory` | pages, research, agent notes and state | `blocks.memory.memory.Memory` over `vishalakshi.Vault` |
| `ask` | model-backed answers out of memory | `blocks.memory.vaults.Vaults` |
| `watch` | standing work that outlives the turn | `blocks.vault.jobs.Jobs` |
| `api` | a loaded spec, its operations, one call | `blocks.vault.spec` |
| `session` | the live namespace and the terminals | `blocks.runtime` and `blocks.term` |
| `shell` | one command, through the project env | `blocks.term.term` |
| `git` | status, divergence, a rehearsed rebase | `blocks.git.git` over `gheasy.repo` |

`without` is the runtime half. A group whose backend was never attached, or whose package never
imported, goes there and `provides` drops it, so the tools for it are never built.

Two settings sit beside the groups rather than inside one. `agent_read_outside` widens reads past
the open folders while writes stay confined to them, and `mk_chat = None` is what lets the vault
answer on the session's own model through `Agent.lend_model`.

Memory and code search stay separate: source code is an AST corpus, prose is a document tree, and
the retrieval that answers well for one answers badly for the other.

`ramabana.runtime.Backend` is the model session, and `leela.agent.runtime` aliases it. Nothing in
Leela constructs one: `Agent` resolves the model for each routed job itself, from `Routing`.

## dhrona warm starts

`Assistant(warm=True)` seeds a fresh conversation from dhrona's accepted rounds. The seam is
`Assistant._prepare`: it calls `Assistant.warm_start` before `Agent._prepare`, handing the replayed
messages to the backend through `resume_hist`, the path a resumed session takes. On a backend that is
already running they are in place when ramabana snapshots turn 1's `before` checkpoint; on one that
starts lazily they are restored at `start()`, after the snapshot, so a fork or rollback to turn 1
restores an empty history -- exactly as it does for `resume_session`. The seeded turn's `plan.warm`
names the rounds. A resumed conversation gets none, by the same `hist` / `_resume_hist` guard.
`blocks/agent/warm.py` holds the dhrona calls -- `fit_rounds` (used, and skipped with a reason),
`assess_session`, `capture_round`, `accept_round` -- and imports dhrona lazily, so a missing package
is a note in the pane, not a failed turn. When ramabana takes `warm=` itself, `Assistant.warm_start`
and the line in `_prepare` go, `warm` passes through to `Agent.__init__`, and `warm_report` stays:
the pane and the routes read nothing else.

`capture` writes the review notebook to `<first root>/.dhrona/<name>.ipynb`, and `accept` -- which
takes only a notebook under that folder -- writes the compiled `<name>.json` beside it before
installing a copy into `~/.config/dhrona/rounds`. The folder is the workspace's, so `/tab/open`
reaches it; it holds working material, and a project may want it in `.gitignore`.

## Adding to the host

1. Declare the group by inheriting shalya's class for it, and implement every method it names.
   An incomplete declaration fails at construction rather than at the first tool call.
2. Put the group in `without` when its backend is absent, so `provides` tells the truth.
3. Import the implementation's dependencies inside the method, not at module scope: the server's
   boot path is what pays for a module-level import.
4. A capability that belongs to every agent belongs in shalya, and one that belongs to every
   Ramabana session belongs in Ramabana. Say so rather than implementing it on Leela's side.

There was a second answer to all of this: `leela/core/ports.py` and `leela/conformance.py`, three
Protocols with a provider registry, an environment override and a hand-kept table of parameter
names to check an implementation against. One provider was ever registered per port, all three
named `leela`, and the swap it existed to permit never happened once. `tests/test_core.py` holds
the test that keeps it retired.
