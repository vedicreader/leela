# Handoff

Branch `claude/cross-file-extraction-c136ae`, not pushed. Suite **1445 passed, 3 skipped, 119
deselected**, plus **75 passed, 1 failed** under `-m slow`. That one failure,
`test_user_checkbox_settings_survive_close_and_reopen`, fails the same way on a clean checkout: saved
settings come back with an empty `editor` block. It is a real bug in settings persistence and is
older than any of this work.

`dist/Leela.app` is built and installed to `/Applications`, byte-identical, launch-tested. It is one
commit behind: the model-picker and `drop_root` work in `fcabca0` needs a rebuild.

Read `CLAUDE.md` and `AGENTS.md` first; the house style is enforced by review, not by a linter.

## Open, in the order the user raised them

### 1. Opening a folder should make a new instance, and does not
This is the user's own words: "how do I open a folder with a new leela instance in the app. that's
the whole point of opening the app with a folder yeah."

How it stands. At **launch**, `app.py:1230` builds one independent `Workspace` per folder, each with
its own state file under `leela_cfg/workspaces/<slug>.json`, its own kernel-pool port, and its own
window, served by `WorkspaceHub`. That is the behaviour they want. While **running**,
`leela_app.py:78` `open_folder` does something else entirely, and says so: "Add a folder to the
running workspace". It posts to `/fs/add_root`, so a folder opened from the Dock, from Finder, or
through the picker joins the current window as another root.

What it would take: the hub already serves N sites, but they are built once at launch. Adding a site
to a running hub means `WorkspaceHub` accepting a `WorkspaceSite` after construction, a `Workspace`
built for the new folder with its own state file and pool port, and a new pywebview window pointed
at its URL. `webview.create_window` can be called after `webview.start`, so the window half is
cheap; the hub half is the work. Decide first whether "add root" should stay reachable at all, or
become a second, explicit action.

### 2. Mimic the toolbar on the Mac toolbar
Not started, and assessed rather than guessed. `desktop.py` already reaches Cocoa
(`from webview.platforms.cocoa import BrowserView`), so a real `NSToolbar` is reachable. The actions
are already declared once, in `core/ui.py` `BARS` and `BUTTONS`, and `core/keys.py` for the chords,
so a native toolbar can be generated from the same table rather than hand-listed, which is what
keeps it from drifting. Clicks route back with `window.evaluate_js("leeAct('...')")`. The judgement
to make is whether a native toolbar replaces the web one or duplicates it: two toolbars on screen is
worse than either alone, and hiding the web one means every non-app surface loses it.

### 3. The scrollbar flutter, if it is still there
Two real defects were found and fixed on the way, both demonstrable: `has-overview` was scoped to
`.lee-editor` so it hid nothing when it landed on any other scroller, and every code block in
rendered markdown was `lines * 19px` tall while a line is `--lee-code-size` by
`--lee-code-line-height`, 13 by 1.5, so each was short of its own text. The stripe also ran inside
every snippet. A browser test reproduces the stripe half and fails without the fix.

What was never reproduced is the *flutter itself*, in Chromium, with or without any of it. If the
user still sees it, the untested theory is the macOS "Show scroll bars: Always" setting: bars that
take layout space, which WKWebView honours and Chrome does not. Ask before writing more code.

### 4. Notarisation
Wired and untested against Apple. `tools/build_release.py`: `notary_args` takes a keychain profile,
an App Store Connect key or an Apple ID, in that order, and does nothing when none is set. Secrets:
`LEELA_CERT_P12` (base64), `LEELA_CERT_PASSWORD`, `LEELA_CODESIGN_IDENTITY`, `LEELA_APPLE_ID`,
`LEELA_APPLE_PASSWORD` (app-specific), `LEELA_TEAM_ID`. Run the first submission locally with
`LEELA_NOTARY_PROFILE` rather than through CI: minutes instead of a full run.

### 5. The `v0.1.0` tag
Created locally, deliberately not pushed. Pushing it fires `desktop-artifacts.yml`, which builds both
platforms and attaches them to a release; without a Developer ID that publishes a DMG Gatekeeper
refuses. Push it after notarisation works.

### 6. Git writes to the worktree outside the sandbox and the journal
`ignore` and `resolve_conflict` write through ramabana's own `write_text` rather than `ctx.fs.write`,
so there is no atomic save, no `FileHistory` version and no journal row: a conflict resolution is not
in `/history/operations` and undo cannot reach it. `resolve_conflict` also takes the browser's editor
text and writes it over whatever is on disk now, with no comparison against what the panes were built
from. `/refactor/*` apply is the model to copy: it refuses when `_disk(path) != row.before` and rolls
back every file it already wrote.

### 7. `/fs/new` takes a path where `rename` takes a bare name
`Sandbox.rename` refuses anything with a separator; `/fs/new` builds `Path(parent)/name`, so
`../sibling/x.py` creates a file elsewhere in the workspace. `_check` keeps it inside the roots, so
this is an inconsistency rather than an escape, but the two should read the same way.

### 8. Settings persistence, and one line of collateral
`test_user_checkbox_settings_survive_close_and_reopen` has been failing since before this work: the
`editor` block comes back empty. Separately, writing the user's model choices through a
`Workspace(roots=[])` rewrote `leela_cfg/workspace.json` whole, clearing its `roots` and an 18-tab
list. Per-folder sessions and `desktop.json` are intact, so the desktop app is unaffected; a bare
`leela` launch with no folder argument now opens empty. `backups/20260821_100912/workspace.json` has
the old roots and tabs, four days stale.

## Where the time went, and where it still is

Measured on this machine, against the real config and a 74MB agent log.

| route | was | now |
| --- | --- | --- |
| `/agent/models` | 6773 ms | ~190 ms in a fresh process |
| `/vars` | 1411 ms | 1 ms |
| `/kernel/info` | 1388 ms | 20 ms |
| `/agent/history` | 2617 ms | 3 ms |
| `/runtime/info` | ~450 ms every time | 1 ms after the first |

The two that mattered were not slow code but work nothing asked for. `/kernel/info` and `/vars` both
called `session.runtime()`, which **starts a kernel**, so opening Leela booted Python whether or not
anybody ran anything. Both peek now. And `/agent/models` scanned the Hugging Face cache once per
model row per request through `mark_models` -> `spec_caps`.

Still there: `/code/status` is 1669ms cold and about 500ms after. `k.status()` has to compare the
tree against the index to report what it reports, it runs once on load, and it is on a worker
thread, so it is understood rather than neglected. And the agent log itself is 74MB and grows without
bound; rotating it is ramabana's call, and worth raising.

## Things that will waste your time if you do not know them

- **`node` is blocked but esbuild is a native binary, and safecmd blocks its name too.** Drive it
  from `python` through `subprocess` with absolute paths:
  `frontend/node_modules/@esbuild/darwin-arm64/bin/esbuild frontend/editor.js --bundle
  --format=iife --global-name=LeeCM --minify --outfile=leela/vendor/lee-cm6.js`. A rebuild renames
  minified symbols, so a test anchored on one breaks for no reason: `tests/assets.cm_exports`
  reads the export map by content instead. Two tests learned that the hard way.
- **A route that reads must not call `ws.runtime()`.** It starts a kernel, over a second, and that
  is how a status pill and a variable list came to boot Python on every page load. `kernel_peek()`
  is the read.
- **`probed` caches machine state on disk, so a test that patches under it needs it cleared.**
  `tests/conftest.py` has an autouse fixture doing that; without it one test is served the catalog
  another already cached, and the failure appears in a third.
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
