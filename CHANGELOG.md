# Release notes

<!-- do not remove -->

## 0.1.4

Built against ramabana 0.1.34, rishi 0.1.38 and shalya 0.0.8, all of which land behaviour Leela had to change for.

### Canvas

- A document that runs: bricks, the dataflow between them, trusted runs, and the bundles a brick embeds. Literate diff and review over it. `leela-bricks` is the example brick set the tests resolve against.

### Agent

- Merged ramabana derives `_plain` from the catalog rather than holding a list. Leela filters the Git writes out of the briefing by overriding it, the way `_sub_plain` beside it already did; assigning to it raised and took 28 tests with it.
- Edits and commands go through shalya's public `cmds`, `edits` and `apply_edits`, not ramabana's private aliases through Leela's own alias module. `test_seams` follows those aliases now.

### Suite

- `test_canvas` stays on one xdist worker (`--dist loadgroup`): its fixtures are module-scoped, and scattering them rebuilt the ide app per worker, 600s against 30s.
- `uv.lock` re-resolved to match the merged `pyproject.toml`.

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
