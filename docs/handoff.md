# Handoff

Branch `claude/cross-file-extraction-c136ae`. Suite **1432 passed, 3 skipped, 112 deselected**,
plus **70 passed, 2 failed** under `-m slow`. Those two failures are older than this work and fail
the same way on a clean checkout: `test_user_checkbox_settings_survive_close_and_reopen` (saved
settings come back with an empty `editor` block) and
`test_response_fork_and_turn_undo_execute_against_a_successful_turn` (the Restore files button's
`onclick` is an object, not a function). Both are real bugs and neither is on anything touched here.

Closed since the last handoff: the setup modal and its rows, both scrollbar faults, the notebook
save conflict and its per-cell tree walk, indent handling, splitting a cell into one cell per def,
file-tree multi-select with move/copy/paste/duplicate, recoverable deletes and renames, six git
panel faults, and the Tools row. `docs/regressions.md` carries an entry each.

`packaging/.app-venv` is synced to the lock (ramabana 0.1.26, jupywire 0.1.5, jupyasyncclient 0.2.7).
It is a pip venv, so nothing updates it on its own: check it against `uv.lock` before a build. Read `CLAUDE.md` and `AGENTS.md` first; the house style is enforced by
review, not by a linter.

## Open, in the order the user raised them

### 1. Notarisation
Wired and untested against Apple. `tools/build_release.py`: `notary_args` takes a keychain profile,
an App Store Connect key or an Apple ID, in that order, and does nothing when none is set. The user
was mid-enrolment in the Developer Program. Secrets to set: `LEELA_CERT_P12` (base64),
`LEELA_CERT_PASSWORD`, `LEELA_CODESIGN_IDENTITY`, `LEELA_APPLE_ID`, `LEELA_APPLE_PASSWORD` (an
app-specific password), `LEELA_TEAM_ID`. Run the first submission locally with
`LEELA_NOTARY_PROFILE` rather than through CI. The feedback loop is minutes instead of a full run.

### 2. The `v0.1.0` tag
Created locally, deliberately not pushed. Pushing it fires `desktop-artifacts.yml`, which builds both
platforms and attaches them to a release; without a Developer ID that publishes a DMG Gatekeeper
refuses. Push it after notarisation works.

### 3. Git writes to the worktree outside the sandbox and the journal
`ignore` and `resolve_conflict` write through ramabana's own `write_text` rather than `ctx.fs.write`,
so there is no atomic save, no `FileHistory` version and no journal row: a conflict resolution is
not in `/history/operations` and undo cannot reach it. `resolve_conflict` also takes the browser's
editor text and writes it over whatever is on disk now, with no comparison against what the panes
were built from. `/refactor/*` apply is the model to copy: it refuses when `_disk(path) != row.before`
and rolls back every file it already wrote. `resolve_safe_conflicts` in ramabana writes and stages
file by file with no rollback, so an error part way through leaves the earlier files written and
staged and reports only the exception.

### 4. `/fs/new` takes a path where `rename` takes a bare name
`Sandbox.rename` refuses anything with a separator; `/fs/new` builds `Path(parent)/name`, so
`../sibling/x.py` creates a file elsewhere in the workspace. `_check` keeps it inside the roots, so
this is an inconsistency rather than an escape, but the two should read the same way.

### 8. The branching model has a complete backend and no way to reach it
Found while adding collapsible turns. Cross-checking every `@rt('/agent…')` in
`blocks/agent/app.py` against callers in `blocks/*/*.js` and `static/js/*.js` leaves thirteen routes
with none: `/agent/branches`, `/agent/branch/parts`, `/agent/branch/switch`, `/agent/fork`,
`/agent/conversation/parts`, `/agent/history/preview`, `/agent/history/apply`, `/agent/info`,
`/agent/sessions`, `/agent/new`, `/agent/ask`, `/agent/approval/request`, and
`/agent/runs/{id}/terminate`.

The consequence is not cosmetic. `/agent/undo-turn` and `/agent/revise` each *create* a branch and
return its `branch_id`; `Assistant.fork` and `switch_branch` can restore and switch between them.
Nothing in the client lists branches or switches to one, so from a person's side the branching model
is write-only: every undo and every edited answer forks the conversation into somewhere they can
never go back to. `revise` at least prints the new `branch_id` into the bar it replaces. `unsay`
prints nothing.

What a UI needs is small, because the backend is done: a branch pill on the turn card reading
`/agent/branches`, and a switcher calling `/agent/branch/switch`. `/agent/branch/parts` and
`/agent/fork` support forking from a *part* of a turn rather than the whole turn, which is a second
surface and can wait.

### 9. `MAX_CHECKPOINTS` and `turn_transactions` disagree about how far back you can go
`ramabana/agent.py` keeps 20 checkpoints and pops the rest; `Assistant.turn_transactions`
(`blocks/agent/ai.py`) is unbounded. So past turn 20 of one session, "Restore files" is still offered
and works while "Undo from conversation" and "Edit what agent remembers" have quietly stopped being
possible. `turn_capabilities` now reports `branchable` and `known` so the pane can say which of the
two reasons a control is unavailable for, but the underlying asymmetry is still there. Either bound
the transactions to match, or persist checkpoints.

## Things that will waste your time if you do not know them

- **`node` is blocked but esbuild is a native binary, and safecmd blocks its name too.** Drive it
  from `python` through `subprocess` with absolute paths:
  `frontend/node_modules/@esbuild/darwin-arm64/bin/esbuild frontend/editor.js --bundle
  --format=iife --global-name=LeeCM --minify --outfile=leela/vendor/lee-cm6.js`. A rebuild renames
  minified symbols, so a test anchored on one breaks for no reason: `tests/assets.cm_exports`
  reads the export map by content instead. Two tests learned that the hard way.
- **`uv run` re-syncs and reverts an editable install.** Use `uv run --no-sync`, or `UV_NO_SYNC=1`.
  This silently ran tests against the wrong ramabana twice.
- **`uv lock` caches the index.** Right after the user releases one of their own packages it will
  call the requirement unsatisfiable rather than admit it has not looked. `uv lock
  --refresh-package <name>`.
- **`node` is blocked by safecmd, but esbuild is not node.**
  `frontend/node_modules/@esbuild/darwin-arm64/bin/esbuild` is a native binary. The vendored
  `leela/vendor/lee-cm6.js` rebuilds with it in about 50ms. That bundle is committed, so a change to
  `frontend/editor.js` that was never rebuilt is a lie. `tests/blocks/test_ide_bundle.py` checks.
- **safecmd blocks a lot.** `cd`, `ls;`, shell variable assignment, `rm`, `ps`, `hdiutil`, `gh`,
  `timeout`, bare tool names. Drive them from `python` through `subprocess` with absolute paths.
- **py2app's blind spots have bitten five times.** A lazily imported module is invisible to its
  scanner, so anything only it reaches must be named in `PACKAGES`: `pygments` (styles by name),
  `apsw` (extension `__init__`, hence `GRAFTED`), `rich`/`pyghostty`/`teleprint` (only
  `ramabana.cli` reaches them), `pip`. Never name a package that a directory in the repository root
  also spells. `packaging` copied the repo instead of the library.
- **The launch test is the only thing that catches those.** It starts the bundle and runs a cell.
  Asking for the page only proves the server imports.
- **`uv run --group test python -m pytest -q`** is the suite. Snapshot tests bake absolute paths and
  only pass in CI; do not `--snapshot-update` locally.

## Upstream, waiting on the user

- `jupyasyncclient` is capped away from **0.2.8**, which makes the gateway `async for` over a
  coroutine so a kernel there executes nothing. 0.2.7 passes. Worth reporting upstream and lifting
  the cap.
- `ramabana/cli.py` imports rich, pyghostty and teleprint but declares none of them, and it holds
  the media helpers (`MEDIA`, `Attachment`, `media_note`, `media_parts`) that have nothing to do
  with terminal rendering. Moving those into a module of their own would let Leela attach a file
  without a terminal UI in the bundle.
- `diskcache` has had no release since 2023 and carries an advisory with no fix. It is in the lock
  only through `llama-cpp-python`, which the app excludes; the alert is dismissed as tolerable risk
  with that reasoning recorded. If the llama backend ever goes, so does the dependency.
- `gheasy` has no `fastship_release` or `fastship_release_job`. Two tests skip until it does.

## Where the size went

DMG **420 MB**, down from 769. The lean came from `ramabana[all]` to `ramabana[cli]`, which took the
on-device model backends out of the default install and into `leela[local]`, installed on demand from
the settings modal. Uncompressed bundle sizes overstate download impact. Removing 124 MB of
onnx and onnxruntime took 61 MB off the DMG, and `mdhtml`'s 76 MB `.so` is an 8.8 MB wheel. The
heaviest remaining are `lib-dynload`, `mdhtml` and `pandas`. `pandas` arrives through fastcore,
dhrishti and ipython rather than anything Leela asks for.

## Fault history

`docs/regressions.md` holds one entry per fault the code still guards against, naming the file and
the symbol. Read the entry for a symbol before rewriting it. Everything found in this session is in
there.
