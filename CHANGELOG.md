# Release notes

<!-- do not remove -->

## 0.1.4

Needs ramabana 0.1.42, rishi 0.1.38, shalya 0.0.11 (below 0.1), dhrona 0.1.4, koshas 0.1.8, vishalakshi 0.1.15.

- Canvas: a document that runs. Bricks, the dataflow between them, trusted runs, embedded bundles, literate diff and review. `leela-bricks` is the brick set the tests resolve against.
- `_plain` is overridden, not assigned; ramabana derives it from the catalog now. Git writes still stay out of the briefing.
- Edits and commands go through shalya's public `cmds`, `edits`, `apply_edits`; `test_seams` follows the aliases.
- Runtime names come from ramabana's `RUNTIME_NAMES`; `RUNTIMES` is urai's registry.
- The refactor engine is kosha's (`kosha.refactor`); Leela's copy is gone. Its comprehension-ordering rule went upstream first.
- `kosha.refactor` is imported where it runs, so the server does not load numpy and pandas.
- The shelf registry is read from litesearch's `store_meta`, then the older `vault_stores`.
- `Memory.poll` builds the typed graph only when online; an offline vault polls its reminders without a model.
- `KernelPool.close_all` cancels kernels still starting and gives up after a bound. Leaving a workspace could hang on a kernel that never came up; so could the suite.
- `test_canvas` stays on one xdist worker (`--dist loadgroup`). `uv.lock` re-resolved.
- Agent pane: a **warm** toggle seeds the next new conversation from dhrona's reviewed rounds, a collapsed transcript block shows every replayed message and tool call and why the other rounds were skipped, and **assess** / **capture** / **accept** score a conversation, write it as a review notebook under `<root>/.dhrona/`, and install the reviewed round (`dhrona>=0.1.4`). A notebook saved in Leela keeps the metadata other tools put on its cells.
- ramabana 0.1.42: it owns the model catalog now (curated ids plus live discovery from the providers' `/v1/models` and Codex's cache), so current models appear and the caps that held aidialog and python-fastllm for its old fastllm-table reads are gone. The saved catalog probe is re-keyed so the new list shows without a manual refresh. shalya is capped below 0.1.

## 0.1.3

The first release whose macOS DMG and Windows zip are built from `uv.lock`. Both earlier releases shipped no usable desktop artefact: the v0.1.1 build failed on `No module named 'ruamel'`, and the v0.1.2 build resolved jupyasyncclient fresh from PyPI and took 0.2.14, whose `run` is a bare async generator where `GatewayKernel` reads `.reply` off a `Run`. The bundled kernel in that build answers 500 to every cell.

### Desktop builds

- Both CI jobs install from `uv export --frozen`, so py2app and py2exe freeze the set the suite ran against. The Windows job resolved from `pyproject.toml` until now.
- `jupyasyncclient` is capped at `<0.2.8`. The previous `!=0.2.8` did not exclude 0.2.14.
- `mark_namespaces` runs against whichever interpreter is about to build, not only inside `build_venv`. A framework interpreter went straight to py2app and never got the `ruamel` marker.
- `desktop-artifacts.yml` triggers on `v*` and on a bare version tag. `ship-gh` tags a Python project `0.1.3` and fastship's other flows push `v0.1.3`; only the second used to build anything.
- `build_release.py upload` looks up whichever tag spelling carries the release, and names `ship-gh` when neither does. It used to fail with `release not found` after the DMG had been built.
- `setup_app.py` skips the lock check where uv is absent rather than reporting a drift.
- `running_from` reads the process name `ps` reports. A framework build re-execs out of `Python.app` and `sys.executable` still names the symlink, so a build could overwrite a running app.

### Notebooks

- `write` moves source text onto the cells already on disk instead of replacing the file with the `# %%` document `text_at` handed out. Rolling back an agent turn that touched a notebook destroyed it. Outputs, execution counts and cell metadata survive.

### Agent

- The update check runs once an hour rather than once per process. `_latest_versions` assigned `_latest` without declaring it global and raised `UnboundLocalError` on every call after the first.
- The releases request carries the GitHub token gheasy resolves. Leela's repository is private, and an unauthenticated request answers 404 there.

### Repository

- Removed `spikes/nbship`, its tests, and the four historical design records under `docs/superpowers/`.
- Removed `docs/handoff.md`, `docs/chat-threads.md`, `docs/chat-threads-implementation.md` and `docs/multi-workspace-architecture.md`. The first was a dated status note. The next two specified `blocks/agent/threads.py`, which is written. The last described `LeelaDaemon`, `WorkspaceRegistry`, `WorkspaceSession` and `ClientSession`, none of which exist.

## 0.1.2

- `mark_namespaces` runs against the building interpreter.
- The update check works more than once per process and authenticates.
- CI installs into uv's own environment. `uv pip install --system` is refused by the runner's externally managed `/usr`.

## 0.1.1

- Every package a tool schema is read from ships its source in the bundle.
- The DMG is staged outside the repository. A `/Applications` symlink left under `build/` is a path from the checkout into the real folder.
- `leela.core.inspectors` reads the registry from `dhrishti.registry` and the import classifier from `kunda.support`.
