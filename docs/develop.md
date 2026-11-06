# Developing Leela

The code layout, the desktop builds, a release, and the test suite.

## Get the code

```sh
git clone https://github.com/vedicreader/leela && cd leela
uv sync --group dev
uv run leela .
uv run pytest tests -q
```

Leela uses these packages from the same authors: [ramabana](https://github.com/vedicreader/ramabana) (the agent), [shalya](https://github.com/vedicreader/shalya) (the agent's tools), [kunda](https://github.com/vedicreader/kunda) (kernels), [dhrishti](https://github.com/vedicreader/dhrishti) (live variables), [gheasy](https://github.com/vedicreader/gheasy) (git), [kavacha](https://github.com/vedicreader/kavacha) (the app window) and [pullup](https://github.com/vedicreader/pullup) (releases and deploys).

## Layout

```
leela/
  agent/          the alias seam: `leela.agent.*` is `ramabana.*` (one `__init__.py`)
  core/           what every block may import
    block.py      `Ctx` (capabilities), the block contract, ordered wiring
    langs.py      the languages Leela runs, serves and highlights
    keys.py       single-source keymap and the user's overrides
    ui.py         button bars and shared atoms, over those same actions
    text.py       diffs, fuzzy ranking, markdown block structure
    session.py    open docs, running cells, the debugger, the journal
    backups.py    the checkpoint a save writes, outside the repository
    envs.py       which values a project needs; dockeasy keeps them
    web.py        shared route helpers
    projects.py   which folders are open, and which were open lately
    inspectors.py the inspector registry, without importing dhrishti's kernel half
  blocks/         one folder per feature: `connect(app, ctx)` plus a `CAPS` tuple
    nb git search memory agent runtime research workflows pipelines drive
    fs term keys tabs vars runs stack refactor lsp debug editor settings workspace
    runtime       kernels, model engines, and the runners for a language with no kernel
    browser       a CDP page as a tab: screencast in, input out
    vault         the corpus, what fills it, and the queue that does the filling
  workspace.py    open folders, open tabs, and which kernel each tab talks to
  app.py          the FastHTML IDE: `ide_app`, `serve_ide`
  desktop.py      the native window: pywebview, the CDP boot, the macOS open event
  cli.py          the `leela` entry point
  static/         the browser client. `vendor/` holds the committed npm bundles
leela_app.py      what py2app and py2exe freeze: server on a thread, window on the main one
packaging/        the platform build definitions and the mark
```

The reasons behind this shape are in [decisions.md](decisions.md). The agent host and its groups are in [integration.md](integration.md).

## Blocks

```text
leela/blocks/git/
    __init__.py   lazy-loads the routes: `__getattr__ = lazy_app(globals())`
    git.py        the domain module, with no web imports
    ui.py         FastHTML fragments
    app.py        `CAPS` and `connect(app, ctx)`, which registers the routes
    *.js          the browser half, joined into a served bundle
```

- A block imports `leela.core` and never another block.
- `CAPS` names exactly what `app.py` and `ui.py` read as `ctx.<name>`. `tests/test_core.py` runs every GET route with only the declared capabilities. Session state that is not a capability, such as `project_root`, comes through `ctx.session`.
- To add a block, make the folder and add its name to `NAMES` in `leela/blocks/__init__.py`. The order of `NAMES` is the wiring order.
- To add a `.js` module, name it in `LAYERS` in `tools/build_ide_js.py` and run the tool.

## Standalone desktop builds

Packaged, leela is a native window with a Python server behind it and a headless Chrome
beside it. The window is [pywebview](https://pywebview.flowrl.com/) over the platform's own
webview: WKWebView on macOS, WebView2 on Windows. It points at a loopback port chosen at
launch. Chrome is not in the bundle. `--app` and the inline browser both drive the persistent
CDP profile fossick keeps in `~/.cache/fastcdp`. It is the copy of Chrome the machine already
has, with the logins it already has. The processes, the browser and the menu bar are in [desktop.md](desktop.md).

```sh
uv sync --extra desktop --extra macapp --group dev
python setup_app.py                 # dist/Leela.app
python tools/build_release.py       # + dist/Leela-macOS.dmg
```

```powershell
uv sync --extra desktop --extra windows --group dev
python setup_app.py                 # dist\Leela\Leela.exe
python tools\build_release.py       # + dist\Leela-Windows.zip
```

`setup_app.py --check` says what it would do first. On macOS it builds against a framework
Python and makes one when the active interpreter is uv's standalone build. py2app copies
stdlib extension modules such as `zlib` out as files, and a standalone build has them linked
in. Windows uses py2exe through the same driver, and produces a folder rather than one file.

The definitions are `packaging/macos/setup.py` and `packaging/windows/setup.py`. The mark
lives in `packaging/assets`: an ICNS for macOS, an ICO with executable metadata for Windows.
`leela_app.py` is the script they freeze. It picks a free port, starts the ordinary
`leela --app` server on a daemon thread, and gives the main thread to the window. Cocoa allows
no other order.

`tests/test_packaging.py` checks what a green build would not. That the asset walk reaches
`vendor/fonts/`. That the plist carries the `NSAllowsLocalNetworking` exemption WKWebView
needs for a loopback URL. That Windows keeps modules as files, which lets a kernel subprocess
import them.

### Cutting a release

Leela is a fastship project, and the Release panel therefore runs `pytest`, `ship-changelog`, `ship-gh`,
`ship-pypi`, then the two desktop steps, then `ship-bump`. From a shell the same sequence is:

```sh
pytest tests -q
ship-gh --no-changelog --no-editor --yes    # commit, push, tag, create the GitHub release
ship-pypi
python tools/build_release.py               # this platform's bundle, into dist/
python tools/build_release.py upload        # attach it to the release for this version
ship-bump && git commit -am bump && git push
```

Write the `## <version>` section of `CHANGELOG.md` before `ship-gh`. That section is the
release body.

The tag builds the other platform. `.github/workflows/desktop-artifacts.yml` runs on a push of
`v*` or of a bare version tag. It accepts both, because `ship-gh` tags a Python project `0.1.3`
while fastship's Rust, Zig and npm flows push `v0.1.3`. Each job exports `uv.lock` as the
bundle's requirements before it freezes anything. Letting pip resolve `>=` fresh on a runner
shipped the 0.1.2 bundle a jupyasyncclient whose kernel answered 500 to every cell. Each job then runs
`tests/test_packaging.py` against the artefact it built and uploads it to the release the tag
names. Set `LEELA_CODESIGN_IDENTITY` for Developer ID signing. Notarization credentials stay in
the release environment.

`python tools/build_release.py upload` finds the release under either tag spelling and refuses
with the command to run when there is none.

### The thin Mac app

From app 1.0 the Mac app is a Swift launcher in `packaging/mac`, and its Python packages come from a signed lock with its own channel. `docs/thin-app.md` has the contract, the lock flow and the checklists. In short:

```sh
make -C packaging/mac test                       # the launcher's tests
make -C packaging/mac uv-fetch dev-lock app verify LOCK_SRC=<lock folder>   # a local, ad hoc signed build
make lock-wheel V=<leela version>                # the Leela wheel on release V
make lock V=<leela version> && make lock-diff && make lock-test FRESH=1 EXTRAS=1
make lock-publish && make lock-promote N=<n>     # test channel first, then stable
make ship-app V=<app version>                    # only when the launcher changes
```

CI no longer builds the Mac app; `desktop-artifacts.yml` builds Windows only.

### The old Mac app

The Mac DMG and zip are signed and notarized on a Mac. Run `make ship V=<version>` after the release exists. `tools/ship.sh` builds Leela.app, signs it with the Developer ID in the keychain, notarizes and staples the DMG, staples the app and zips it as `Leela-macOS.zip`, puts both on release `V` (the DMG in place of the one that CI attached), and pushes the cask with `tools/ship_cask.sh`. The cask installs the zip, because Homebrew 7 fails with a read-only file system when it unpacks the mounted DMG. It never moves a tag or a release, so it can run again.

The window needs no build. From a checkout:

```sh
uv sync --extra desktop
leela --shell webview .
```

## Develop

```sh
uv sync --group dev --python 3.12
uv run pytest tests -q   # `-m ""` adds the slow ones: browsers, real kernels, a real model
```

`tests/conftest.py` fakes the kernels, and the harness tests drive a `FakeBackend` over
scripted replies. The suite needs no ipykernel and no gigabytes of weights.

Each IDE client module sits beside the feature it serves, as `leela/blocks/<block>/*.js`, with
the shared vocabulary in `leela/static/js/`. `tools/build_ide_js.py` concatenates them, in the
order its `LAYERS` fixes, into the committed bundles `leela/core/web.py` names in
`IDE_BUNDLES`: `lee-core.js`, `lee-agent.js` and `lee-ide.js`, served as three deferred tags in
one lexical scope. Run it after editing a module, or run `--check` to see whether a bundle has gone stale. It
refuses to build a module it cannot find, and one it finds but the order never names. The repository commits the npm bundles in `leela/vendor/` too, and an
install needs no node:

```sh
python tools/build_ide_js.py [--check]
cd frontend && npm install && npm run build
```
