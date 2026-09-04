# Reusable UI blocks

Leela's agent pane, vault reader and memory panel are three surfaces that no part of an IDE
needs. Cassowary reimplemented all three against an older Ramabana rather than importing them.
This is the plan for extracting them, and for the seam the extraction needs first.

## What is already reusable

The agent block's server half is a JSON API. All 81 routes under `/agent/*` return
`JSONResponse`, `StreamingResponse` or a server-sent event. Not one returns an FT fragment. The
browser is already a client of a wire rather than a consumer of rendered HTML, which is why a
second client is cheap.

`blocks/agent/turns.py` and `blocks/agent/threads.py` are 723 lines of view model, and between
them they touch exactly one `Workspace` member, `ws.fs`. Tool grouping, tool previews, edit
diffs, history sessions and media all shape a turn for a browser without knowing what the
browser is attached to.

`blocks/agent/ai.py` is the opposite and stays in Leela. `WorkspaceHost` is a `shalya.Host`
over kernels, notebooks, the LSP and the repo. It is what Leela hands the agent, and another
application hands its own.

## What stops it today

1. Panel markup lives in `leela/app.py`, not in the block. `_agent_panel` is 143 lines there;
   `_memory_panel`, `_git_panel`, `_vars_panel` and eight others sit beside it. Only
   `blocks/fs/ui.py`, `blocks/tabs/ui.py` and `blocks/vault/ui.py` follow the `ui.py` convention
   `docs/blocks.md` describes. A block cannot be lifted while a third of it is in the application.

2. The client is one lexical scope. `tools/build_ide_js.py` concatenates 59 modules into three
   bundles that share globals. `blocks/agent/*.js` is 3,548 lines defining 48 `leeXxx` functions
   and reading `lee`, `$`, `esc` and `leeAct` from `static/js/`. No block's JS loads alone, and
   the builder refuses any file it does not name.

3. CSS is one 3,638-line file. 290 of those lines are the agent pane. Blocks have no CSS of
   their own, and the `--lee-*` tokens every rule reads are declared in the same file.

4. `Ctx` enumerates Leela's capabilities. `core/block.py` hardcodes 30 names against `Workspace`
   attributes. A block declaring `CAPS = ('fs', 'memory', 'ai', 'inline_ai', 'docs')` needs a
   host shaped the way `Workspace` shapes those five.

5. `blocks/agent/app.py` reads 34 `Workspace` members directly. That is the port, and it is too
   wide to ask another application for.

## The recommendation

Extract one package, the agent pane, and let it prove the seam before anything else moves.
Ship it as FastHTML fragments plus routes plus its own JS and CSS, mounted on a narrow port that
`Workspace` and Cassowary's `Session` each implement. Its routes are the package's, which makes
them the wire a native client speaks later without a second server.

Do not build a generic block framework first. Leela has one already, and the parts of it that
work (`CAPS`, `connect`, lazy `app.py` resolution, the affinity test) survive the extraction
unchanged. The parts that do not work are the four listed above, and all four are cheaper to fix
against a real second consumer than in the abstract.

### The narrow port

The 34 members collapse to six once they are grouped by what they answer:

| port member | what it covers | `Workspace` members it replaces |
|---|---|---|
| `threads` | conversations, the active one, approvals | `threads`, `_threads` |
| `assistants` | the agent, the inline agent, notebook approvals | `ai`, `_ai`, `inline_ai`, `_inline_ai`, `_notebook_approvals` |
| `settings` | routing, budgets, compaction, the write and PII policies | 15 scalars from `model` to `litert_backend` |
| `state` | the charter and its layers | `agent_state`, `agent_state_layers` |
| `history` | the log, its stamp, timelines | `history_stamp`, `fresh_history`, `with_timelines`, `save` |
| `execution` | the live namespace, optional | `runtime`, `runtime_peek`, `kernel_peek`, `cwd_for` |

`execution` is the only one an IDE has and a corpus chatbot does not. A host that returns `None`
for it gets a pane with the kernel affordances absent rather than broken.

### What the package carries

- `turns.py` and `threads.py` as they are, minus the `ws.fs` read.
- `models.py`, the model picker's catalogue and its probes.
- `completions.py` and `video.py`.
- `app.py`, its 81 routes rewritten against the port, under a configurable prefix.
- `ui.py`, new, holding what `_agent_panel` holds now.
- Eight `.js` modules and 290 lines of CSS, both scoped to the pane.

Leela keeps `blocks/agent/__init__.py` as a re-export seam over the package, which is the
arrangement `blocks/runtime/kernels.py` already has over kunda.

## Mobile

A mobile client does not need the extracted package. It needs the route contract pinned and an
auth story, and the contract exists today because the routes are JSON. Two pieces of work, both
smaller than the extraction:

- Version the wire. `/agent/v1/*`, and a test that fails when a payload key disappears.
- Replace loopback trust with a token. `TerminalGate` already carries one for the terminal
  websocket; the agent routes assume the origin is the only caller.

A webview app is the other route and needs neither. It renders the same pane the browser does.
Pick one before writing client code, because the answers diverge completely.

## What Cassowary costs

Cassowary is on `ramabana>=0.1.6`, which predates shalya. Its `VaultHost` and `SpecHost` come
from `ramabana.vault` and `ramabana.spec`, and its tools from `ramabana.tools`. Upgrading it to
current Ramabana is prerequisite work, not part of the extraction, and it has to happen before
Cassowary can import anything Leela publishes.

What it deletes afterward: 1,509 lines of `vault/ui.py` and 500 of `cassowary.js`, both of which
render turns, approvals, plans and the evidence reader that the agent pane already renders.

## Order

1. Move panel markup out of `leela/app.py` into each block's `ui.py`. No behaviour changes, and
   it makes obstacle 1 disappear for every block at once.
2. Make block JS load as ES modules with explicit imports. `static/js/` becomes the kit every
   module imports from. `build_ide_js.py` keeps the bundle, and `LAYERS` stops being load-order
   truth.
3. Split the CSS per block, tokens staying shared.
4. Upgrade Cassowary to current Ramabana and shalya.
5. Extract the agent pane behind the six-member port. Leela and Cassowary both mount it.
6. Extract the vault reader and the memory panel the same way, with two consumers already proven.

Steps 1 through 3 are Leela-internal and leave it working after each. Step 4 is Cassowary's.
Only step 5 creates a package.

## Not candidates

`nb`, `editor`, `runtime`, `vars`, `debug`, `refactor`, `lsp`, `tabs`, `workspace` and `fs` are
the IDE. `git`, `term`, `search` and `browser` are generic enough to move and have no second
consumer asking for them. Revisit when one does.
