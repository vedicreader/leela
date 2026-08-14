# leela

> creative workspace that starts with coding

A browser IDE for notebooks, files and **live variables**.
[dhrishti](https://github.com/vedicreader/dhrishti) is the engine — it turns a live Python
namespace into a node tree and serves it as a JSON API from *inside* the kernel that owns
it. This repository is the shell around that: workspace, notebook, agent, frontend.

## Install

```sh
pip install leela                # base
pip install "leela[github]"      # workflows, releases, deploys (gheasy, dockeasy)
pip install "leela[gateway]"     # jupygate kernel transport
```

## Use

```sh
leela                      # the saved workspace
leela .                    # a folder
leela src tests            # one workspace, two roots
leela --app src tests      # two app windows in fossick's persistent CDP Chrome
```

Each folder in `--app` mode gets its own `Workspace`, docs, agent, terminals and kernel
pool at `folder.localhost:5001`. `--transport direct|gateway` picks the kernel transport,
`--kernel ipykernel|ipymini` the kernel, `--agent restricted|readonly|off` what the agent
may touch. `leela --help` lists the rest.

## What it does

**Editing.** Notebooks and files side by side in CodeMirror 6. A `.py` file runs as a
script in the tab's own kernel — `▶ file`, `▶ sel` — so it gets `__main__` and an argv, and
what it defines lands in Variables. `mod+e` is an MRU switcher; overflow tabs fold into
`+N`. Autosave is atomic, mirrored into IndexedDB, and version-checked against disk.
Outline folding, sticky Contents, minimisable panes.

**Live variables.** Each notebook tab owns a real kernel with an inspector inside it, so
the tree stays responsive while a cell runs. `--kernel ipymini` puts execs and shell-channel
calls on a subshell, so completion does not queue behind a long cell
([measured](docs/screenshots/web-concurrency.png): ~3s → ~275ms). Trailing values open in a
lazy value lens; prefix the Variables filter with `=` to evaluate against the watched runtime.

**The agent.** Local or cloud model, cheap jobs (completions, summaries, sub-agent fan-out)
routed local either way. Every call is a lifecycle card: proposal, edit, dry-run diff,
approve-and-run or reject-with-steering, retry, rollback. Autopilot, guided and directed
modes. Compaction is surgical, visible in the timeline, and reversible; turns fork from any
revision. Prompt cells save the answer *in the notebook cell*, as markdown Jupyter can read.
A charter under **state** layers organization/project/task/branch context into the briefing.
Skills come from `pyskills` entry points and `SKILL.md` directories.
The harness is [ramabana](https://github.com/vedicreader/ramabana); `leela.agent` aliases it.

**Search and memory.** [kosha](https://pypi.org/project/koshas/) for code — FTS5, embeddings,
call graph, notebook cells — behind `mod+shift+f`, with rg as the fallback and
Command-click to a definition. Prose goes to a [vishalakshi](https://github.com/vedicreader/vishalakshi)
vault over litesearch: every page read and every research source, recallable through
`memory_search`/`memory_tree`/`memory_read`/`memory_topics` before paying to search the web again.

**Research.** Web search and clean Markdown extraction via
[fossick](https://github.com/vedicreader/fossick), sources beside the reader, cited digests,
and everything rendered through [mdhtml](https://github.com/AnswerDotAI/mdhtml) so pasted
`<script>` stays visible rather than applied.

**Git.** A six-part source-control workspace — Changes, Review, Branches, History,
Repository, All repos. Diffs open as editor tabs, unified or side-by-side, with hunk staging
and per-chunk revert. Merge and rebase open a non-mutating plan first. A **notebook is
blamed as cells**, not as JSON. `leela ~/code` opens a folder of checkouts and answers the
plural questions — which are dirty, behind, unpublished — with fetch/pull/push across all
of them at once. Lazygit is in the dock.

**Ship it.** Workflows draws `.github/workflows` as jobs and `needs` edges, paints recent
run results onto them, and builds new ones from a form; every file written is
[gheasy](https://github.com/vedicreader/gheasy)'s. Release runs nbdev's four commands as
four steps on a real pty, each with its own exit code. Deploy runs the project's `deploy.py`
stage by stage, or scaffolds the first one from dockeasy/vpseasy/cfeasy; *Drive* is the same
deploy taken apart, one library call per step. Failures name the deepest frame in *your*
packages, rewritten to the checkout you have open. Secrets live in dockeasy's store and are
never sent to the browser.

**Keys and buttons.** Every action has a button, a palette entry (`mod+shift+p`) and a
rebindable chord. See [keys and buttons](#keys-and-buttons).

## Watching something run

An inspector lives *inside* a process, so:

> A process leela started under a run configuration is watchable. A process you started
> anywhere else is not — unless it says so itself, in one line.

`.leela/runs.json`:

```json
{"runs": [
  {"name": "api",   "cmd": "uvicorn app:app --port 8000", "watch": "app"},
  {"name": "train", "cmd": "python train.py"}
]}
```

leela imports `watch` *before* `cmd`, so uvicorn's own `import app` finds it loaded and the
panel shows that namespace while it serves. `watch` is inferred from `app:app`. **run** is
`ctrl+alt+d`, **env…** is `ctrl+alt+e`. `--reload` is the exception: the reloader runs your
app in a child process, where the inspector is not.

Anything else joins by asking:

```python
import dhrishti.serving as ds; ds.serve(name='api')
```

## Keys and buttons

Some chords never arrive — Terminal.app cannot distinguish several modified keys, macOS uses
Option to compose, Chrome reserves combinations — so the browser has one context-aware
router matching modified printable shortcuts by physical key code. `mod` is Command in a
macOS browser, Control elsewhere; `hyper` is Command+Control+Option+Shift, or
Control+Alt+Shift elsewhere.

Notebook keys follow PyCharm/Jupyter: `mod+enter` runs, `shift+enter` runs and selects below,
`alt+enter` runs and inserts below, `alt+shift+up/down` moves a cell, `mod+shift+enter` runs
everything. Rarer actions ship unbound with a button and a palette entry, because the chords
that survive your browser are yours to pick.

Rebind in `keys.json` in leela's config dir, or `$LEELA_KEYMAP`, or `--keymap`:

```json
{"keys": {"run_cell": "mod+enter ctrl+y", "palette": "mod+shift+p", "quit": ""}}
```

Several chords separated by spaces; `""` unbinds. Start from `leela --write-keymap`, or edit
in **keys → edit** and it applies without a restart. Anything unparseable, unknown or
conflicting is skipped, reported, and left at its default — a typo cannot stop leela starting.

## Layout

```
leela/
  agent/          the alias seam: `leela.agent.*` is `ramabana.*`
  core/           what every block may import
    block.py      `Ctx` (capabilities), the block contract, ordered wiring
    ports.py      the contracts a workspace depends on, and the provider registry
    keys.py       single-source keymap and the user's overrides
    ui.py         button bars and shared atoms, over those same actions
    text.py       diffs, fuzzy ranking, markdown block structure
    session.py    open docs, running cells, the debugger, the journal
    envs.py       which values a project needs; dockeasy keeps them
    web.py        shared route helpers
  blocks/         one folder per feature: `connect(app, ctx)` plus a `CAPS` tuple
    nb git search memory agent runtime research jobs workflows pipelines drive
    fs term keys tabs vars runs stack refactor lsp debug editor settings workspace
  workspace.py    open folders, open tabs, and which kernel each tab talks to
  app.py          the FastHTML IDE: `ide_app`, `serve_ide`
  cli.py          the `leela` entry point
  static/         the browser client; `vendor/` holds the committed npm bundles
```

A block imports `leela.core` and never another block. See [docs/blocks.md](docs/blocks.md)
for the contract and [docs/integration.md](docs/integration.md) for what belongs in a
dependency rather than here.

## Standalone desktop builds

```sh
uv sync --extra gateway --extra macapp --group test
python setup_app.py
python tools/build_release.py       # dist/Leela.app + dist/Leela-macOS.dmg
```

py2app on macOS, py2exe on Windows (`--extra windows`); definitions in
`packaging/{macos,windows}/setup.py`, the mark in `packaging/assets`.
`.github/workflows/desktop-artifacts.yml` builds the DMG and the zipped EXE on version tags.
Set `LEELA_CODESIGN_IDENTITY` for Developer ID signing. The app reuses fossick's Chrome
profile rather than bundling one.

## Develop

```sh
uv venv --python 3.12
uv pip install -e . --group test
pytest tests -q          # `-m ""` for the slow ones: browsers, real kernels, a real model
```

Kernels are faked in `tests/conftest.py` and the harness tests drive a `FakeBackend` over
scripted replies, so the suite needs no ipykernel and no gigabytes of weights.

The IDE client is authored in `leela/static/js/` and concatenated into the committed
`leela/static/lee-ide.js`; the npm bundles in `leela/vendor/` are committed too, so an
install needs no node:

```sh
python tools/build_ide_js.py [--check]
cd frontend && npm install && npm run build
```

## License

Apache-2.0
