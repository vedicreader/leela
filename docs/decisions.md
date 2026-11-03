# Decisions

This page lists the decisions that a maintainer must know. Each entry gives the decision, the reason, the date when it is known, and the place in the code. Read the entry before you change that code.

The rules of daily work (code style, the seams, prose, tests, plans) are in [CLAUDE.md](../CLAUDE.md) and [AGENTS.md](../AGENTS.md). This page does not repeat them. The old plans, design notes, profiles and the long per-symbol notes are in the git history (before 3 Nov 2026: `docs/plans/`, `docs/regressions.md`, `docs/performance.md` and the others).

## Where code lives

- **Leela composes libraries. It does not copy them.** `leela.agent` is `ramabana`. Tools and hosts are `shalya`, git is `gheasy`, kernels and interpreters are `kunda`, the native window and the freezers are `kavacha`, the release and deploy pipeline is `pullup`. A behaviour that belongs to a library goes upstream as a patch, not into a wrapper here.
  Why: two copies drift, and each copy gets worse than the union. `leela/agent/__init__.py`, `leela/blocks/runtime/kernels.py` and `support.py` (re-export seams over kunda), `leela/core/inspectors.py`.
- **The retired port registry stays retired.** `leela/core/ports.py` and `leela/conformance.py` had one provider per port, and no swap ever happened. `Host.provides` is the only way to ask what a host supports. `leela/blocks/agent/ai.py` `WorkspaceHost`.
- **The server turn feed stays in Leela.** `Feed`, `Thread`, `Threads` and `TurnRunner` were not moved to ramabana: nothing in ramabana would use a replay feed, and `Threads` carries Leela's card and badge rules. Move it only together with a rewrite of `racp.Session` over `Feed`. (Oct 2026) `leela/blocks/agent/threads.py`.

## Blocks and the browser client

- **One folder per feature.** A block has `connect(app, ctx)` and a `CAPS` tuple. It imports `leela.core` and never another block. `NAMES` in `leela/blocks/__init__.py` fixes the wiring order. See [develop.md](develop.md#blocks).
- **`CAPS` names exactly what the block reads as `ctx.<name>`.** Too many gives reach that nobody asked for. Too few raises `AttributeError` on a route that nobody ran. `tests/test_core.py` runs every GET route with only the declared capabilities. A new capability goes in `EAGER` (copied at connect), `LAZY` (read per access, for what follows the active root) or `APP`. `leela/core/block.py`.
- **The client is plain scripts in one lexical scope, built into three bundles.** A block's `*.js` sits beside its Python. `tools/build_ide_js.py` joins them in the order `LAYERS` fixes into `lee-core.js`, `lee-agent.js` and `lee-ide.js`, named in `IDE_BUNDLES` (`leela/core/web.py`). It refuses a missing module and a module that `LAYERS` does not name. No node at install: the bundles and `leela/vendor/` are committed.
- **Each `ACTIONS` entry is a thunk** (`help: () => showHelp()`). A bare reference to a function in a later bundle throws at load, and the throw stops the rest of `lee-core.js`. `leela/static/js/actions.js`, `tests/blocks/test_ide_bundle.py`.
- **No `fast_app`.** The app builds `FastHTML` directly with `GZipMiddleware`. `fast_app` imports IPython through `fasthtml.pico` (212 ms at boot) and serves the working folder by extension with no containment. Leela serves its own files from `/leestatic` and `/file/raw`. `leela/app.py`.
- **Push, then poll as a backstop.** `blocks/fs/watch.py` is one `watchfiles` thread per workspace, sent to the browser on `/fs/events`. Polls are slow when idle (approvals 5 s, `/tab/watch` 10 s, dev servers 15 s). A write the client made itself is not news (`noteSelfWrite`). The watcher thread is Rust, so `close()` joins it, or the interpreter segfaults at exit.

## The agent host

- **A host declares a group by inheritance.** `WorkspaceHost` inherits shalya's class for each group and writes every method that the group asks for. An incomplete group fails at construction. A group whose backend is absent goes in `without`, so `provides` drops it and its tools are never built. The group map is in [integration.md](integration.md). `leela/blocks/agent/ai.py`.
- **Import a group's dependencies inside the method.** The server boot path pays for each module-level import.
- **A read that only decorates an answer must not start a kernel.** `ws.runtime()` costs over a second. The api peek, the Variables poll and the conversation list do not call it. `leela/blocks/agent/app.py`, `leela/blocks/vars/app.py`.
- **The model route is Ramabana's.** Leela and the `ramabana` CLI read the same `~/.config/ramabana/config.toml` and env vars. Nothing chooses a provider for the person. A model saved in Leela goes to `~/.config/leela/models.json`, and the key stays in the environment. Claude on Bedrock, Converse, AWS profiles and SigV4 are not supported, because fastllm has none of them. `leela/blocks/agent/models.py`.
- **The model catalog is probed once and served from the memo.** Probing every backend and account costs seconds on a cold machine, and the picker is on the boot path. `refresh=1` asks again. The memo is `ramabana.core.probed`. `leela/blocks/agent/models.py` `probed`.
- **The vault answers on the session's own model.** `mk_chat = None` lets the vault borrow it through `Agent.lend_model`. `agent_read_outside` widens reads past the open folders, and writes stay inside them.
- **Learning is Ramabana's switch.** `learning` in `<cfg>/settings.json`. The learned review queue is `ramabana.learned` on `pending/<id>` branches. Leela adds the Review tab's Learned queue, `/learned on|off`, and `/agent/learned/compact` (one model call on the `summary` route, one at a time, by a process lock). Routes return ramabana's dict as it is: 200 with `ok: true`, or 409 with `ok: false, error`. `leela/blocks/agent/app.py`.
- **Sub-agent settings belong to the workspace.** Model, effort, tool channel and the turn's tool channel reach every live conversation. An empty value takes config.toml, then the runtime default. A refusal is HTTP 200 with `ok: false` and the settings still in force. HTTP 400 is only for a body that is not a JSON object. `Agent.subagent_settings`.
- **Warm starts are Ramabana's.** Leela's part is the transcript block: `Thread._warmed` and `blocks/agent/warm.py`, which imports dhrona lazily so that a missing package is a note, not a failed turn.

## Agent turns and history

- **One log holds Leela's conversations and the CLI's.** Only Leela marks the sessions it started (`started_here`), and the history list shows those. History written before the mark reads as the CLI's. `leela/blocks/agent/turns.py` `latest_started_here`, `history_sessions`.
- **The pane reads Leela's gate, not the core's `busy`.** `TurnRunner.held` is what `start` refuses on, so the pane cannot contradict it. A foreground stop drops the gate itself, because `cancel` does not reach a worker in a provider stream. `_reap` frees a gate with no live turn behind it. `leela/blocks/agent/threads.py`.
- **Undo, restore and revise travel with the turn log.** `with_capabilities` puts them on each turn, so a repaint from the log keeps them. Checkpoints live in memory and are bounded by `MAX_CHECKPOINTS`. A turn from before a restart has no boundary, and the pane says so. `leela/blocks/agent/turns.py`, `Assistant.turn_capabilities`.
- **The timeline keeps only what the client reduces.** `_retained` keeps chunks and the newest payload per `action_id`. The rest was 95% of the rows (15 MB over six workspaces). `fresh_history` reparses only when a stat changes. `leela/workspace.py`.
- **A conversation can be a notebook.** One cell per part, with its id in metadata. Prose is editable. A call and its result are raw cells that can be deleted but not reworded. `connect.agent_conversation_notebook`, `agent_conversation_reshape`.

## Files, notebooks and saves

- **The disk version is a content token, not an mtime.** `nbdev_clean` and formatters rewrite a file with no change, and an mtime read that as an outside write. The hash is paid only when the stat moves (`TOKEN_CACHE`). `leela/blocks/tabs/app.py` `disk_version`.
- **A notebook save rebases on the file as it is now.** A save writes cell sources only, and `nbdev_clean` writes outputs and metadata only. Cells match by id. Only a source changed on both sides is a conflict. `leela/blocks/nb/app.py` `_rebase_notebook`.
- **Notebook conflicts are read from the index, by cell.** Git keeps all three sides as whole notebooks. Conflict markers make a notebook unreadable. A decided cell loses its outputs. `leela/blocks/nb/nb.py` `merge_rows`, `merged_cells`.
- **File history lives outside the repository.** Loss happens before a commit, often from another process. Bodies are stored once per content. `leela/core/session.py` `FileHistory`.
- **Backups hold what a rebuild cannot give back.** One gzipped tar and a JSON manifest each, on a tiered schedule, and before anything overwrites the log. `PRECIOUS` leaves out the vault (a restore writes outside the config dir) and `journals` (undo state, the largest entry). A restore backs up first. WAL databases are copied as one set. `leela/core/backups.py`.
- **Open folders merge across windows.** One session file, many windows. Overwriting let the last window decide for all. Temporary folders are never written to the session. `leela/workspace.py` `_merge_roots`, `leela/core/projects.py`.
- **A folder of checkouts is not a checkout.** The repo, the index, the language server and the interpreter come from one walk up from the file to the open folder, never past it. `Workspace.project_repo`, `Search.kosha_root`, `Workspace.lsp_for`, `leela/blocks/git/repos.py` `repo_for`.

## Kernels and languages

- **`leela/core/langs.py` is the one list of languages.** Each record names extensions, the kernelspec, the fallback runner, the language servers and whether dhrishti can read the namespace. `blocks.fs.LANGS` is a different question (highlighting) and stays there.
- **The notebook kernelspec is the record of its language.** Leela reads it on open and writes it on save. `notebook language` writes the file and closes the old runtime. `connect.nb_language`.
- **A cell runs on Python, then an installed Jupyter kernel, then Leela's runner.** `CargoRunner` grows one scratch crate per notebook, and rustc diagnostics are the cell's error. `NodeRunner` keeps one `vm` context (`driver.mjs`). Both present the `Kernel` surface. Neither has a namespace, so Variables, the debugger and the agent's kernel tools stay Python only. `leela/blocks/runtime/runners.py`.
- **Notebook export to a crate or an npm package is not Leela's.** The spike was removed in 0.1.3. Read tag `v0.1.2` before you design around it.
- **The editor asks for diagnostics only for Python and Markdown.** Widening it needs a rebuild of the CM6 bundle with esbuild. Hover, symbols, inlay hints and rename already route by language. `frontend/editor.js`.
- **Kernel support installs Leela's own locked versions.** An index's newest of each gave `ipymini` and `kernmini` versions that do not fit. `kunda.support`, `leela/blocks/runtime/support.py`.
- **The inspector is borrowed only by a kernel of Leela's minor version.** A frozen build ships bytecode for one version. `leela/blocks/runtime/kernels.py`.
- **`venv_env` never sets `UV_PROJECT_ENVIRONMENT`.** A `uv sync` in another checkout would prune this venv. uv finds the environment from the directory.

## Search and memory

- **Code and prose are two stores.** Code goes to kosha (FTS5, embeddings, call graph, notebook cells), with ripgrep as the fallback. Prose goes to a vishalakshi vault. Retrieval that answers well for one answers badly for the other. `leela/blocks/search/search.py`, `leela/blocks/memory/memory.py`.
- **`Memory` is a two-shelf policy over a `Vault`.** The `leela` shelf holds agent notes and state. The workspace shelf holds pages and research. Leela keeps the policy and the PII gate wiring. Everything else forwards to vishalakshi.
- **Scores are features, and the client re-ranks.** One weight per leg and per lexical feature, so a score is `sum(weight * feature)`. `Weights` defaults equal `DEFAULT_SETTINGS['search']`, and a test holds them equal. `leela/blocks/search/search.py`, `leela/blocks/settings/settings.py`.
- **Search telemetry has two stores.** A JSONL event log per day (90 days) for metrics, and one vault document per session. Fields are whitelisted in `signals.FIELDS`. Snippets are off by default. See [search.md](search.md#what-is-recorded). `leela/blocks/search/signals.py`.
- **The kosha fallbacks wait on kosha.** `Search.similar`, `clusters`, `peers` and `_anchor` probe for kosha methods that do not exist yet, so the fallback runs. Add the four methods to kosha, then delete the fallback halves here. Do not move `Search` out of Leela.

## Vault and APIs

- **The reach gate is on `api_call`, not on `api_fetch`.** A local-only spec refuses a hosted model and sends nothing. It refuses, and does not reroute, because the hosted model has already read the question. The page calls `api_fetch`: the person owns the data. `leela/blocks/agent/ai.py`.
- **A header can name an env var** (`${TOKEN}`). Leela stores the reference, so rotating the variable rotates the key. A name with no value is refused. Header and variable names reach the briefing. Values never do. `leela/blocks/vault/spec.py` `expand`.
- **Feed items go on the `news` shelf** and keep the feed's own summary. The front page reads no documents to print it.

## Lessons from abhyasa

- **abhyasa links to Leela and never calls it.** abhyasa reads `serving.json` (`url`, `pid`) and opens `<url>/learn?…`. Both apps read the same learning store. Keep `serving.json`, `/learn` and the keys `walk`, `step` and `topic` stable. (28 Oct 2026) `leela/core/projects.py` `now_serving`, `leela/blocks/learn/app.py`.
- **The guard lets in one cross-site request:** a top-level `GET /learn` navigation. Every cross-site POST is still refused. `leela/hub.py` `learn_navigation`, `LoopbackHostGuard`.
- **Lessons go in `~/Learning/Leela lessons`** when no folder is open (`LEELA_LESSONS` moves it). (28 Oct 2026) `leela/blocks/learn/learn.py`.
- **A library lesson runs in its own uv environment, never in the project's Python.** Wheels only, cached per package set, with the owner's uv config (no `--no-config`). The graded check runs closed with `abhyasa.check.run_isolated`. Leela keeps no runner copy. (28 Oct 2026) `leela/blocks/learn/tools.py`.
- **Only the first try at a rupaka gate is logged**, once per cell version, as one `demo` attempt. Leela has no hint count. (28 Oct 2026)
- **Leela imports no abhyasa web code.** `tests/test_learn_pane.py` holds it. No pane key until the keymap audit; it will be the same Alt+Z and Esc as abhyasa.

## Presenting

- **One presentation mode**, from the selected cell, with unsaved edits, and no file written. Slides come from RISE metadata. reveal.js and `rise.theme` are gone. Esc never ends it. (29 Oct 2026) The user reference is [present.md](present.md), and `tests/test_present_docs.py` holds it.
- **The audience window follows through the server, not `BroadcastChannel`.** `Presentation` holds the state and sends it over SSE, so a reload of either window comes back at the same place. The audience page has GET routes only. (29 Oct 2026) `leela/blocks/nb/presentation.py`.
- **The page groups the slides, and the server renders them.** `presentSlides` is the only RISE grouping. The server checks the shape and renders through `mdhtml` and `clean_html`, so the presenter preview is what the room sees. A failed run sends the room no traceback until Show error. `leela/blocks/nb/present.js`, `slides.js`.

## Desktop app and the frozen build

- **pywebview owns the main thread, and the server runs on a daemon thread.** Cocoa allows no other order. A folder opened while Leela runs goes over HTTP to `/hub/open`, because the hub owns the workspaces on another loop. One folder is one workspace is one window. See [desktop.md](desktop.md). `leela_app.py`, `leela/desktop.py`, `leela/hub.py`.
- **Chrome is not in the bundle.** The inline browser drives fossick's CDP profile. A link that a person clicks goes to their own browser (`openExternal`), because the automation profile meets bot walls. `leela/blocks/browser/`.
- **A child process of the frozen app gets a clean environment.** py2app points `PYTHONPATH`, `PYTHONHOME` and `__PYVENV_LAUNCHER__` at the bundle. A child that keeps them imports the bundle's stdlib under another Python. Use `kunda.pythons.clean_env` and `venv_env` for every subprocess, git filters and the login shell included.
- **An app started from Finder gets launchd's environment.** Leela sets `LC_CTYPE`, asks the login shell for `PATH` and imports credentials from the shell, and keeps what the launcher set. `leela/__init__.py` `use_utf8`, `use_login_path`, `use_extras`; `leela/core/envs.py` `import_login_env`.
- **Optional backends install beside the bundle.** `use_extras` puts that folder first on the path at process start, so an install lasts past a restart. `leela/cli.py` `main`.
- **macOS text substitution is off for Leela only.** WKWebView hands a `contenteditable` to the spell checker, which made curly quotes and took Tab. `NO_SUBSTITUTION`, written to Leela's own defaults domain. `leela/desktop.py`.

## Git

- **Staging a new folder writes its `.gitignore` first.** The rules go in the folder's own `.gitignore`, only those that `git check-ignore` says are missing. `leela/blocks/git/ignores.py` `KINDS`, `prepare`.
- **A conflict batch is checked whole before any file is written.** A stale file refuses the batch. `leela/blocks/git/app.py` `_guard_batch`.
- **Parallel agent threads need a shared-state git lock first.** The gateway lock keys on the worktree root, so `fetch`, `gc`, `config` and branch renames in two worktrees are not serialised. Lock on `git rev-parse --git-common-dir` for those, in gheasy, before any thread board ships. Not built.

## Themes and keys

- **Per-theme code colours remap the shared variables on highlight spans.** The editor bundle cannot be rebuilt without node. `tools/build_hl_css.py` `PALETTES` writes both the `hl-*` rules and the editor remap, so they cannot drift. `leela/static/lee-ide.css`.
- **The server writes the theme families into the first paint.** The inline script cannot read `prefs.js`. A test holds the list equal to the picker's. `leela/blocks/settings/settings.py` `theme_boot`.
- **The menu bar rows name keymap actions.** A row for an unknown action raises at import. A row shows a shortcut only for a global action with a modifier, because AppKit reads a menu key before the page. `leela/blocks/keys/menus.py` `BAR`.
- **A saved keymap drops entries equal to the default.** An older client saved every action, and frozen defaults would block the next change. `connect.keys_save`.

## Release

- **Every bundle installs from `uv.lock`.** The CI job runs `uv export` before it freezes. A fresh resolve shipped 0.1.2 with a kernel that answered 500 to every cell. `[tool.uv.sources]` has no sibling path for the same reason. `.github/workflows/desktop-artifacts.yml`, `pyproject.toml`.
- **The Mac DMG is signed and notarized on a Mac** with `make ship V=<version>`, after the release exists. Signing walks inner code deepest first, not `--deep`, which the notary rejects. The script moves no tag, so it can run again. The steps are in [develop.md](develop.md#cutting-a-release). `tools/ship.sh`, `tools/build_release.py`.
