# leela

> creative workspace that starts with coding

A browser IDE for notebooks, files and live variables.

[dhrishti](https://github.com/vedicreader/dhrishti) is the engine. It turns a live Python
namespace into a node tree and serves it as a JSON API from inside the kernel that owns it.
This repository is the shell around that engine: workspace, notebook, agent, frontend.

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

In `--app` mode each folder gets its own `Workspace`, documents, agent, terminals and kernel
pool at `folder.localhost:5001`. `--transport direct|gateway` picks the kernel transport.
`--kernel ipykernel|ipymini` picks the kernel. `--agent restricted|readonly|off` sets what
the agent may touch. Run `leela --help` for the rest.

## What it does

### Editing

Notebooks and files sit side by side in CodeMirror 6. A `.py` file runs as a script in the
tab's own kernel. It gets `__main__` and an argv, and Variables then holds everything it
defined. Use `▶ file` for the whole file and `▶ sel` for a selection. `mod+e` opens a
recently-used switcher. Overflow tabs fold into a `+N` menu. Autosave is atomic, mirrored
into IndexedDB, and version-checked against disk. Cells fold, headings build an outline, and
every pane minimises.

### Live variables

Each notebook tab owns a real kernel with an inspector inside it. The tree stays responsive
while a cell runs. `--kernel ipymini` puts execs and shell-channel calls on a subshell, so
completion does not queue behind a long cell. On a cell that awaits two seconds, a
completion request drops from about 3s to about 275ms
([screenshot](docs/screenshots/web-concurrency.png)). A trailing value opens in a lazy lens.
Prefix the Variables filter with `=` to evaluate against the watched runtime.

### The agent

The turn runs on a local or a cloud model. Completions, summaries and sub-agent fan-out go
to the local one either way. Every call is a lifecycle card. You can edit it, read its
dry-run diff, approve and run it, reject it with steering, retry it, or roll it back.
Autopilot, guided and directed modes decide how much of that you see. Compaction is
surgical and appears in the timeline. Turns fork from any revision. A prompt cell saves the
answer in the notebook cell, as markdown that Jupyter can still read. The charter under
state layers context by organization, project, task and branch, then puts it in the
briefing. Skills come from `pyskills` entry points and `SKILL.md` directories. The harness is
[ramabana](https://github.com/vedicreader/ramabana), which `leela.agent` aliases.

### Search and memory

Code goes through [kosha](https://pypi.org/project/koshas/): FTS5, embeddings, a call graph
and notebook cells, behind `mod+shift+f`. Ripgrep is the fallback. Command-click reaches a
definition. Prose goes to a [vishalakshi](https://github.com/vedicreader/vishalakshi) vault
over litesearch. It holds every page read and every research source. The agent recalls one
with `memory_search`, `memory_tree`, `memory_read` and `memory_topics`, rather than paying to
search the live web again.

### Research

[fossick](https://github.com/vedicreader/fossick) runs the web search and the extraction to
clean Markdown. Sources stay beside the reader, and a digest cites them. Everything renders
through [mdhtml](https://github.com/AnswerDotAI/mdhtml), so pasted `<script>` stays visible
rather than applied.

### Git

Source control is a six-part workspace: Changes, Review, Branches, History, Repository and
All repos. Diffs open as editor tabs, unified or side by side, with hunk staging and a
revert arrow per hunk. Merge and rebase open a plan that mutates nothing. Blame reads a
notebook as cells
rather than as JSON. `leela ~/code` opens a folder of checkouts and answers the plural
questions: which are dirty, which are behind, which are unpublished. Fetch, pull and push
run across every one at once. Lazygit is in the dock.

### Ship it

Workflows draws `.github/workflows` as jobs and `needs` edges. Recent run results paint onto
the same boxes, and a form builds new ones. Every file written is
[gheasy](https://github.com/vedicreader/gheasy)'s. Release runs nbdev's four commands as four
pty steps. Each keeps its own exit code. Deploy runs the project's `deploy.py` stage by
stage, or scaffolds the first one from dockeasy, vpseasy and cfeasy. Drive is the same
deploy taken apart, one library call per step. A failure names the deepest frame in your own
packages, rewritten to the checkout you have open. Secrets stay in dockeasy's store and are
never sent to the browser.

### Keys and buttons

Every action has a button, a palette entry at `mod+shift+p`, and a chord you can rebind.
See [keys and buttons](#keys-and-buttons).

## Watching something run

An inspector lives inside a process. That gives one rule:

> A process leela started under a run configuration is watchable. A process you started
> anywhere else is not, unless it says so itself, in one line.

Run configurations live in `.leela/runs.json`:

```json
{"runs": [
  {"name": "api",   "cmd": "uvicorn app:app --port 8000", "watch": "app"},
  {"name": "train", "cmd": "python train.py"}
]}
```

leela imports `watch` before it runs `cmd`. Uvicorn's own `import app` then finds the module
already loaded, and the panel shows that namespace while the server serves. leela infers
`watch` from `app:app` when you leave it out. The run button is `ctrl+alt+d`. The env picker
is `ctrl+alt+e`. `--reload` is the exception: the reloader runs your app in a child process,
where the inspector is not.

Anything else joins by asking:

```python
import dhrishti.serving as ds; ds.serve(name='api')
```

## Keys and buttons

Some chords never arrive. Terminal.app cannot distinguish some modified keys. macOS uses
Option to compose. Chrome reserves combinations. The browser therefore has one context-aware
router, and it matches modified printable shortcuts by physical key code. `mod` is Command in
a macOS browser and Control elsewhere. `hyper` is Command+Control+Option+Shift, or
Control+Alt+Shift elsewhere.

Notebook keys follow PyCharm and Jupyter. `mod+enter` runs the cell. `shift+enter` runs and
selects below. `alt+enter` runs and inserts below. `alt+shift+up/down` moves a cell.
`mod+shift+enter` runs everything. Rarer actions ship unbound with a button and a palette
entry, because the chords that survive your browser are yours to pick.

Rebind in `keys.json` in leela's config dir, or wherever `$LEELA_KEYMAP` or `--keymap` points:

```json
{"keys": {"run_cell": "mod+enter ctrl+y", "palette": "mod+shift+p", "quit": ""}}
```

Separate chords with spaces. `""` unbinds. Start from `leela --write-keymap`, or edit it in
the browser under keys, which applies without a restart. leela skips anything unparseable,
unknown or conflicting, reports it, and keeps that action's default. A typo cannot stop
leela starting.

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
  static/         the browser client. `vendor/` holds the committed npm bundles
```

A block imports `leela.core` and never another block. [docs/blocks.md](docs/blocks.md) has
the contract. [docs/integration.md](docs/integration.md) says what belongs in a dependency
rather than here.

## Standalone desktop builds

```sh
uv sync --extra gateway --extra macapp --group test
python setup_app.py
python tools/build_release.py       # dist/Leela.app + dist/Leela-macOS.dmg
```

macOS uses py2app and Windows uses py2exe under `--extra windows`. The definitions live in
`packaging/macos/setup.py` and `packaging/windows/setup.py`, and the mark lives in
`packaging/assets`. `.github/workflows/desktop-artifacts.yml` builds the DMG and the zipped
EXE on version tags. Set `LEELA_CODESIGN_IDENTITY` for Developer ID signing. The app reuses
fossick's Chrome profile rather than bundling one.

## Develop

```sh
uv venv --python 3.12
uv pip install -e . --group test
pytest tests -q          # `-m ""` adds the slow ones: browsers, real kernels, a real model
```

Kernels are faked in `tests/conftest.py`, and the harness tests drive a `FakeBackend` over
scripted replies. The suite needs no ipykernel and no gigabytes of weights.

The IDE client is authored in `leela/static/js/` and concatenated into the committed
`leela/static/lee-ide.js`. The npm bundles in `leela/vendor/` are committed too, so an
install needs no node:

```sh
python tools/build_ide_js.py [--check]
cd frontend && npm install && npm run build
```

## License

Apache-2.0
