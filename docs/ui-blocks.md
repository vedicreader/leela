# Moving the agent pane into its own package

Goal: `blocks/agent` becomes a package that Leela mounts, Ramabana mounts, and that also runs on
its own as a web app you can open on a phone.

Placeholder package name below is `sabha`. To rename, one `sed` over this file and the new repo.

## What moves and what stays

| file | lines | goes |
|---|---|---|
| `blocks/agent/turns.py` | 204 | package |
| `blocks/agent/threads.py` | 519 | package |
| `blocks/agent/models.py` | 348 | package |
| `blocks/agent/completions.py` | 105 | package |
| `blocks/agent/video.py` | 136 | package |
| `blocks/agent/app.py` | 1159 | package |
| `blocks/agent/panel.js` `budgets.js` `live.js` `approvals.js` `steer.js` `media.js` `memory.js` | 3398 | package |
| `blocks/agent/reload.js` | 150 | stays in Leela, moves to `blocks/editor/` |
| `blocks/agent/ai.py` | 1043 | stays in Leela |
| `app.py:617-759` `_agent_panel` | 143 | package, as `ui.py` |
| 290 lines of `static/lee-ide.css` | 290 | package |
| ~450 lines of `static/js/core.js` + `overlays.js` | 450 | package, as the browser kit |

`ai.py` is `WorkspaceHost`. It is Leela's kernels, notebooks, LSP and repo handed to the agent.
Ramabana hands its own `LocalHost` instead. It never moves.

`reload.js` reloads open editor tabs after the agent edits a file. That is the IDE reacting to the
agent, not part of the pane. It is also the only agent JS file that touches `lee.buffers`,
`lee.diskVersion`, `lee.dirtyBuffers`, `lee.watchingDisk`, `lee.heldSaveConflicts` and
`lee.shownProblems`. Moving it out removes most of the coupling in one step.

## The UI is not modular. Here is exactly how it is stuck

Four things, all measured, all fixable inside Leela before anything moves.

1. The panel markup is in `leela/app.py`, not in the block. `_agent_panel` is 143 lines at
   `app.py:617`, with `_state_text`, `_state_label` and `_state_title` beside it.

2. The agent JS calls 26 functions defined in other files. 13 are generic and become the kit.
   13 are IDE-only and become injected hooks. Full list, with call counts:

   | IDE-only symbol | calls | files |
   |---|---|---|
   | `dropCodeSurfaces` | 7 | live.js, media.js |
   | `leePane` | 5 | approvals.js, budgets.js, memory.js |
   | `diffHtml` | 4 | approvals.js, live.js, media.js |
   | `createEditor` | 3 | approvals.js, live.js, memory.js |
   | `mountCodeSurface` | 3 | live.js, steer.js |
   | `mountTab` | 2 | reload.js |
   | `codeLang` | 2 | approvals.js, steer.js |
   | `attachVaultRef` `curEditor` `diffModal` `leeExpandPane` `leeOpenFile` `clearDrafts` | 1 each | various |

   32 call sites total. That is the whole IDE coupling in the client.

3. There are no ES modules. `tools/build_ide_js.py` concatenates 59 files into three bundles that
   share one lexical scope. Nothing is imported or exported. The agent's 8 files define 48
   top-level functions the HTML calls by name through inline `onclick` attributes.

4. Shared mutable state. The agent JS reads and writes 30 `lee.agent*` and `lee.memory*` fields on
   a single global object shared with the editor, the terminal, git and the debugger.

On the server side the same problem is smaller. `blocks/agent/app.py` reads 34 `Workspace`
members. `turns.py` and `threads.py` read one between them (`ws.fs`). All 81 routes return JSON or
server-sent events, none returns HTML, so the wire is already a wire.

---

# Phase 0. Make it modular inside Leela

Seven steps. Leela works after every one. Nothing moves out of the repo yet.

### Step 1. Move the panel markup into the block

- Create `leela/blocks/agent/ui.py`.
- Cut `_agent_panel`, `_state_text`, `_state_label`, `_state_title` from `leela/app.py:597-759`.
- Carry with them: `help_mark` (`app.py:19`) and `chord_display`. `JOB_HELP` already lives in
  `blocks/agent/models.py` and moves with it.
- In `app.py`, `_right_workspace` imports `agent_panel` from the new file.

Check: `uv run pytest tests/test_serve_ide.py`. Open the IDE, the pane looks identical.

### Step 2. Split the agent CSS

- Grep `static/lee-ide.css` for `lee-agent`, `lee-thread`, `lee-approval`, `lee-composer`. 290 lines.
- Move them to `leela/blocks/agent/agent.css`.
- Leave every `--lee-*` variable declaration in `lee-ide.css`. The agent CSS may read tokens, never
  declare them.
- Serve both stylesheets from `ide_app`'s `hdrs`.

Check: add a test asserting `agent.css` contains no `--lee-` definition. Compare screenshots.

### Step 3. Move `reload.js` out of the agent block

- `git mv leela/blocks/agent/reload.js leela/blocks/editor/agentreload.js`.
- Update its entry in `LAYERS` in `tools/build_ide_js.py` (it is in the `lee-agent.js` list; move it
  to `lee-ide.js`).
- Update the allowlist in `tests/blocks/test_block_affinity.py`.

Check: `uv run pytest tests/blocks/test_ide_bundle.py tests/blocks/test_block_affinity.py`.
Edit a file with the agent, confirm the open tab still reloads.

### Step 4. Replace the 13 IDE globals with a host object

- Create `leela/blocks/agent/host.js` declaring one object:

```js
const agentHost = {
  openFile, revealPane, expandPane, mountTab, clearDrafts,     // IDE panes and tabs
  mountEditor, dropEditors, currentEditor, langOf,             // CodeMirror
  diffHtml, showDiff,                                          // notebook diffs
  attachVaultRef,                                              // vault
  currentPath, prefs, vaultRefs,                               // state reads, see step 5
};
```

- In Leela, each field points at the existing global.
- Rewrite the 32 call sites listed above to go through `agentHost`.
- Every hook gets a default no-op. `mountEditor` falls back to a plain `<textarea>` when no
  CodeMirror is present. That fallback is what makes the pane work outside an IDE, so write it now
  and test it now, not later.

Check: `grep -l 'dropCodeSurfaces\|leePane\|diffHtml\|createEditor\|mountCodeSurface\|mountTab\|codeLang\|attachVaultRef\|curEditor\|diffModal\|leeExpandPane\|leeOpenFile\|clearDrafts' leela/blocks/agent/*.js` returns only `host.js`.

### Step 5. Give the agent its own state object

- In `panel.js` (first agent module in load order) declare `const ag = {}`.
- Move the 30 `lee.agent*` and `lee.memory*` fields onto `ag`.
- The four fields that are genuinely shared (`lee.path`, `lee.settingsMeta`, `lee.prefs`,
  `lee.vaultRefs`) become `agentHost.currentPath()`, `agentHost.prefs()`, `agentHost.vaultRefs()`.

Check: `grep -c 'lee\.' leela/blocks/agent/*.js` returns 0 for every file.

### Step 6. Turn the agent JS into ES modules

- Add `import`/`export` to the 8 files. The kit functions (`api`, `post`, `esc`, `status`, `modal`,
  `confirmDialog`, `textDialog`, `renderMarkdown`, `flushMarkdown`, `compactPath`) get imported from
  a new `leela/static/js/kit.js` that re-exports them from `core.js` and `overlays.js`.
- Replace inline `onclick="leeAgentNew()"` with `data-agent-action="new"`. There are 11 in the
  panel markup and 4 more written into HTML strings by the JS. One delegated listener in a new
  `boot.js` entry point binds them all. The other 113 handlers are already assigned in JS
  (71 `.onclick =`, 42 `addEventListener`) and need no change.
- Add the entry point:

```js
export function bootAgent(root, host, opts) { /* wires listeners, starts the stream */ }
```

- `build_ide_js.py` keeps producing `lee-agent.js`, now emitted with `type="module"`.

Check: `uv run pytest tests/blocks/test_ide_bundle.py`. Load the page, console is clean, every
button in the pane still works.

### Step 7. Shrink the server port from 34 members to 6

Create `leela/blocks/agent/port.py`:

```python
class AgentPort:
    threads      # the Threads object
    assistants   # .agent, .inline, .notebook_approvals
    settings     # a MutableMapping over the 15 scalars
    state        # the charter and its layers
    history      # .stamp(), .fresh(), .with_timelines(), .save()
    execution    # .runtime(), .peek(), .cwd_for(); None where there is no kernel
```

Mapping from the 34 current reads:

| port member | replaces |
|---|---|
| `threads` | `ws.threads`, `ws._threads` |
| `assistants` | `ws.ai`, `ws._ai`, `ws.inline_ai`, `ws._inline_ai`, `ws._notebook_approvals` |
| `settings` | `model`, `inline_model`, `completion_model`, `job_models`, `tool_budget`, `step_budget`, `compact_auto`, `compact_strategy`, `agent_read_outside`, `allow_workspace_repo_writes`, `subagent_writes`, `vault_pii`, `local_multimodal`, `litert_backend`, `agent_memory_selection` |
| `state` | `ws.agent_state`, `ws.agent_state_layers` |
| `history` | `ws.history_stamp`, `ws.fresh_history`, `ws.with_timelines`, `ws.save`, `ws.ask`, `ws.prepare_turn` |
| `execution` | `ws.runtime`, `ws.runtime_peek`, `ws.kernel_peek`, `ws.cwd_for` |

- Add `WorkspacePort(ws)` implementing it.
- Rewrite the 34 reads in `app.py`.
- The four `execution` routes must return `{'ok': True, 'runtime': None}` when `execution is None`,
  not raise. Test that path explicitly, because Leela will never hit it.

Check: `uv run pytest tests/blocks/test_agent_block.py tests/blocks/test_agent_threads.py`
(736 + 1584 lines, both currently pass).

---

# Phase 1. Create the package

### Step 8. New repo `vedicreader/sabha`

Layout:

```
sabha/
  port.py        the AgentPort protocol, copied from step 7
  threads.py     from blocks/agent/threads.py, unchanged
  turns.py       from blocks/agent/turns.py, minus the ws.fs read
  models.py  completions.py  video.py
  app.py         the 81 routes, against port instead of ws
  ui.py          the panel fragment, from step 1
  ports/local.py RamabanaPort, see step 12
  static/
    kit.js       api, post, esc, status, modal, dialogs, markdown
    agent/*.js   the 7 modules from step 6
    agent.css    the 290 lines from step 2
```

`pyproject.toml` dependencies: `ramabana`, `python-fasthtml`, `fastcore`, `shalya`. Not `leela`.

### Step 9. Three public functions

```python
def mount(app, port, prefix='/agent'):   "register the routes on an existing FastHTML app"
def panel(port):                         "the FastHTML fragment for the pane"
def headers():                           "the <script type=module> and <link> tags it needs"
```

Leela calls all three. A host embedding the pane in its own page calls all three.

### Step 10. A standalone app

```python
def serve_app(port, title='agent'):  "a FastHTML app whose only page is the pane"
```

Entry point `sabha = "sabha.cli:main"`, so `sabha serve --root . --model X` runs it.
This is the thing you open on your phone.

---

# Phase 2. Leela uses the package

### Step 11. Turn `blocks/agent` into a re-export seam

Copy the pattern already in `leela/blocks/runtime/kernels.py`, which does this over `kunda`.

- `blocks/agent/app.py` becomes: build `WorkspacePort(ws)`, call `sabha.mount`, keep Leela's `CAPS`.
- `blocks/agent/ui.py` becomes `from sabha.ui import panel`.
- Delete the moved `.py` and `.js` files.
- `tools/build_ide_js.py` reads the agent modules from the installed package via
  `importlib.resources.files('sabha')/'static'`, not from `leela/blocks/agent/`.
- `blocks/agent/ai.py` stays exactly where it is.
- Add `sabha` to `leela/pyproject.toml`.

Tests: `tests/blocks/test_agent_block.py` and `test_agent_threads.py` (2320 lines) move to the
sabha repo and run against a fake port. `tests/test_agent.py` (2986 lines) tests `WorkspaceHost`
and stays in Leela. `tests/test_agent_slow.py` stays.

Check: full `uv run pytest`. The IDE is pixel-identical.

---

# Phase 3. Ramabana uses the package

### Step 12. `RamabanaPort`

Lives in `sabha/ports/local.py`, not in Ramabana, because Ramabana has no `python-fasthtml`
dependency today and should not gain one.

```python
def local_port(roots=('.',), model=None, approve='ask', **kw):
    from ramabana.cli import mk_agent
    agent, host = mk_agent(roots, model=model, approve=approve, **kw)
    ...
```

Wiring each port member:

- `threads`: `sabha.threads.Threads(port)` as-is. `Threads` only needs `ai` and `approvals`.
- `assistants`: the one `Agent`, plus a second cheap one for inline completions.
- `settings`: a JSON file at `~/.ramabana/agent-ui.json`.
- `state`: the same charter file layout Leela writes, under the agent's `cfg` directory.
- `history`: `Agent.sessions()` and `Agent.history`, which is what Leela already reads through.
- `execution`: `None`.

Optionally add `ramabana[web]` as an extra that pulls `sabha`, so `pip install ramabana[web]`
gets you the UI. The entry point stays `sabha serve` either way.

Check: `sabha serve --root ~/somerepo` in a browser. Send a turn, approve a write, fork a thread,
switch models. The kernel buttons are absent rather than broken.

---

# Phase 4. Make it usable on a phone

### Step 13. Auth

Today the routes trust loopback. On a phone they will not be on loopback.

- One Starlette middleware checking a bearer token on every `/agent/*` route.
- `sabha serve --token` prints one, or reads `SABHA_TOKEN`.
- A one-field login page that stores it in `localStorage` and puts it on every `api`/`post` call in
  `kit.js`.
- Copy `TerminalGate` in `leela/blocks/term/term.py` for the shape.

### Step 14. Responsive layout

The pane is currently a fixed 420px right column (`--lee-right-w`).

- Add `@media (max-width: 640px)` to `agent.css`: full width, composer pinned to the bottom with
  `position: sticky` and `env(safe-area-inset-bottom)`, thread list as a slide-up sheet.
- Set the composer `font-size: 16px`. Below that iOS zooms the page on focus.
- Replace the hover tooltips on the toolbar buttons with visible labels. There is no hover.
- The keymap (`mod+enter` to send, and 7 more agent chords) has no effect on a phone. `ui.py`
  should not render the chord hints when the standalone app is in narrow layout.

### Step 15. Install to the home screen

- `manifest.json` with the icon set, `display: standalone`.
- A service worker caching `kit.js`, the agent modules and `agent.css`. Never cache `/agent/*`.

### Step 16. Survive a backgrounded tab

`/agent/stream` is server-sent events. A phone drops it whenever you switch apps.

- `sabha.threads.Feed.since(seq)` already replays from a sequence number.
- On `visibilitychange` back to visible, reconnect with `?since=<last seq>` instead of reloading.
- Show a "reconnecting" state in the run strip rather than an empty pane.

Check: send a long turn, background the app for two minutes, come back. The turn is complete and
the trace has every step.

---

# Order and dependencies

Steps 1 to 7 can be done one per PR, in order, all inside Leela. 3 and 4 are the two that
actually unstick things. 6 is the largest.

Step 8 cannot start before 7. Steps 11 and 12 are independent of each other once 8 to 10 exist.
Phase 4 needs 10 and nothing else.

# Known risks

- Step 6 touches the 15 inline `onclick` attributes. A missed one is a dead button with no error.
  Add a test that walks the rendered panel and asserts every `data-agent-action` value has a
  handler registered.
- Step 7 changes 34 read sites in one file. Do it with the tests running, not in one commit.
- `models.py` probes local runtimes (mlx, llama, ollama) on a background thread at boot. In the
  standalone app on a phone-facing server, that probe is pointless and slow. Make it opt-in.
- Two repos now version together. Leela pins `sabha>=x`, and a route change is a sabha release
  before it is a Leela one.
