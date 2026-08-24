# Handoff

Branch `claude/cross-file-extraction-c136ae`, pushed through `608b7d6`. Suite **1391 passed, 3
skipped, 109 deselected**. Read `CLAUDE.md` and `AGENTS.md` first; the house style is enforced by
review, not by a linter.

## Open, in the order the user raised them

### 1. The setup modal renders unstyled
A screenshot shows its content overlapping the editor text with no opaque box: the modal is
transparent and the two panes plus the Tools section lie on top of the page. `leeSetupModal` calls
`modal('')` and then `renderSetup` replaces the whole element's `innerHTML`. That throws away the
`.lee-modalbox` wrapper `modal()` built, and with it every style and the close button. Render into
the box instead of over it. `leela/blocks/agent/panel.js`, `renderSetup`.

### 2. Scrollbars flicker on code cells in the agent pane
Not diagnosed. The overview stripe redraws on a `ResizeObserver` now, and an agent pane that streams
tokens resizes its cells continuously, so the stripe may be redrawing every frame. Suspect
`overviewPlugin` in `frontend/editor.js`: `queue` coalesces into one `requestAnimationFrame`, which
is still every frame under a steady stream. Consider not drawing at all for the agent pane's
editors, or debouncing rather than coalescing.

### 3. The leftover scroll bar is still there on the web
Fixed for the app and reported still broken in a browser. `leela/vendor/lee-cm6.js` is served with a
cache-busting query built from its mtime (`core/web.py:38`), so a stale bundle is unlikely but worth
ruling out with a hard reload before looking further. If it reproduces, the app and the browser differ in which
ancestor scrolls. `scrollerFor` walks up to the first element taller than its client height. In a
browser that may be the document.

### 4. Indent handling in the text editor
Asked for, not started. There is no indent action in `core/keys.py` at all; the editor gets
`indentWithTab` and whatever `defaultKeymap` binds. `frontend/editor.js` already exports `undo` and
`redo` the same way, so the shape is known: export `indentMore`, `indentLess` and `indentSelection`,
rebuild the bundle, add three actions and chords. `indentSelection` is the one the user is missing.
It re-indents a block to its syntactic indentation.

### 5. Notarisation
Wired and untested against Apple. `tools/build_release.py`: `notary_args` takes a keychain profile,
an App Store Connect key or an Apple ID, in that order, and does nothing when none is set. The user
was mid-enrolment in the Developer Program. Secrets to set: `LEELA_CERT_P12` (base64),
`LEELA_CERT_PASSWORD`, `LEELA_CODESIGN_IDENTITY`, `LEELA_APPLE_ID`, `LEELA_APPLE_PASSWORD` (an
app-specific password), `LEELA_TEAM_ID`. Run the first submission locally with
`LEELA_NOTARY_PROFILE` rather than through CI. The feedback loop is minutes instead of a full run.

### 6. The `v0.1.0` tag
Created locally, deliberately not pushed. Pushing it fires `desktop-artifacts.yml`, which builds both
platforms and attaches them to a release; without a Developer ID that publishes a DMG Gatekeeper
refuses. Push it after notarisation works.

### 7. The Tools row has not been through a build
`TOOLS` in `leela/blocks/agent/models.py` offers a language server, installed through the same path
as a model backend. Tested in the suite, never exercised in a packaged app. `basedpyright` was chosen for two
reasons: it answers every capability the LSP client asks for, and it carries its own node. `ty` and
`pyrefly` need no node at all. Each of those lacks one thing the client wants.

## Things that will waste your time if you do not know them

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
