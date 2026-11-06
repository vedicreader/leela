# Using Leela

How to start Leela, what each part does, and the keys. The [README](../README.md) has the download and the install.

## Use

```sh
leela                      # the saved workspace
leela .                    # a folder
leela src tests            # one workspace, two roots
leela --app src tests      # two app windows in fossick's persistent CDP Chrome
leela --shell webview .    # a native desktop window, what the packaged app runs
```

In `--app` mode each folder gets its own `Workspace`, documents, agent, terminals and kernel
pool at `folder.localhost:5010`. `--app` picks the workspace shape. `--shell` picks what opens on
top of it, and it takes `chrome`, the default under `--app`, or `webview` for a native window, or
`none`. The same CDP Chrome backs [the inline browser](#the-browser-inside-leela) either way.
`--transport direct|gateway` picks the kernel transport. `--kernel ipykernel|ipymini` picks
the kernel. `--agent restricted|readonly|off` sets what the agent may touch. Run
`leela --help` for the rest.

## What it does

### Editing

Notebooks and files sit side by side in CodeMirror 6. A `.py` file runs as a script in the
tab's own kernel. The script gets `__main__` and an argv, and Variables then holds every name it
defined. Use `▶ file` for the whole file and `▶ sel` for a selection. `mod+e` opens a
recently-used switcher. Overflow tabs fold into a `+N` menu. Autosave is atomic, mirrored
into IndexedDB, and version-checked against disk. Cells fold, headings build an outline, and
every pane minimises.

### Rust and JavaScript notebooks

A notebook's kernelspec says what its cells are, and Leela runs three of them. Python is a managed
ipykernel as before. Rust and JavaScript run on an installed Jupyter kernel where one exists, either `evcxr_jupyter`
or `deno jupyter`. Where none exists they run on Leela's own runner. A Rust cell becomes part of
a scratch cargo crate that grows. Rustc's diagnostics then arrive as the cell's error output,
named `E0382`, with the compiler's own rendering underneath. JavaScript cells run against one
long-lived node context, and a binding made in one cell survives into the next. `notebook language`
in the command palette switches a notebook over.

![The borrow checker, in a notebook cell](screenshots/rust-borrow-checker.png)

### Presenting a notebook

Alt+R presents the open notebook as slides, from the selected cell, with unsaved edits. Slides come from RISE cell metadata. An optional audience window shows the slides on a projector, and code cells run live on both screens. A presentation writes no file. See [present a notebook](present.md).

### Staging a folder of a language you have just met

`git add` honours `.gitignore`. A folder you have just created has no `.gitignore`, and `target/`
or `__pycache__` therefore go in with everything else. `stage this folder, ignores first` writes the rules
the folder's project kinds need, covering Rust, maturin, Python and Node. It detects each kind
from the files that declare it, writes a rule only where `git check-ignore` reports one missing,
and then stages. The rules go in the folder's own `.gitignore`, because `/target/` at the root
of a repository does not match `mycrate/target/`.

The tree colours every file and every folder by its state: staged, modified, untracked, ignored,
conflicted. A folder takes the strongest state under it, and a new one therefore reads as untracked before
you expand it.

<p align="center">
<img src="screenshots/git-tree-before.png" width="300" alt="before: the crate is untracked">
<img src="screenshots/git-tree-after.png" width="300" alt="after: sources staged, target ignored">
</p>

### Live variables

Each notebook tab owns a real kernel with a dhrishti inspector inside it. kunda supervises the
kernel, finds the interpreters and builds the kernelspec; the tree stays responsive while a cell
runs. `--kernel ipymini` puts execs and shell-channel calls on a subshell, which keeps
completion out of the queue behind a long cell. On a cell that awaits two seconds, a
completion request drops from about 3s to about 275ms
([screenshot](screenshots/web-concurrency.png)). A trailing value opens in a lazy lens.
Prefix the Variables filter with `=` to evaluate against the watched runtime.

### The agent

The turn runs on a local or a cloud model. Completions, summaries and sub-agent fan-out go
to the local one either way. Every call is a lifecycle card. You can edit it, read its
dry-run diff, approve and run it, reject it with steering, retry it, or roll it back.
The pane's control decides how much of that you see. Guided stops at writes and network calls, directed stops at every call, and edits runs file and notebook edits. Autopilot sets the conversation's approvals to auto, so no approval card shows, also when Leela starts with `--approvals ask`. Under autopilot, Stop and Pause after current still stop the agent. A card still shows for the third same call in a row, a peer question that only a person can answer, and a host policy that asks. Approvals switched off stay off. When you leave autopilot or edits, the conversation gets back the approvals mode it had before, and "Trust changes for this session" stays in effect. Compaction is
surgical and appears in the timeline. Turns fork from any revision. A prompt cell saves the
answer in the notebook cell, as markdown that Jupyter can still read. The charter under
state layers context by organization, project, task and branch, then puts it in the
briefing. Skills come from `pyskills` entry points and `SKILL.md` directories. The harness is
[ramabana](https://github.com/vedicreader/ramabana), which `leela.agent` aliases.
Nothing chooses a provider for you. When the agent's model cannot run, the agent pane lists the
providers it can use (OpenAI, Azure OpenAI, AWS Bedrock, Anthropic, Gemini, OpenRouter, Claude
Code, Codex, a local model) and what each needs, and **+ model** adds one; see
[docs/integration.md](integration.md#providers-azure-openai-and-aws-bedrock).

### Lessons from abhyasa

Learn a topic step by step from [abhyasa](https://github.com/vedicreader/abhyasa) lessons, with exercises the agent checks. In abhyasa, Open in Leela on a step sends a `/learn` link to Leela. A link with `go=1` opens the notebook at once, at the cell of its section. Other links show the step page, and **Open as a lesson** opens it.

- A step opens as a lesson notebook: the passage from the source, the tutor's note, a task, its tests, and the run.
- A lesson runs in its own uv environment, made from the requirements it declares. A lesson whose environment is not set up, missing or broken refuses to run. It never runs in the project's Python. Press Set up the environment on the step page.
- A notebook walk of abhyasa opens its learning copy. The copy runs in the folder and the `.venv` of the notebook that it comes from.
- Exercise cells have a Check button and a results list. `alt+s` checks the exercise that has the cursor. The agent grades a checked exercise from 0 to 10.
- `LEELA_LESSONS` moves the lessons folder.

### The screen guide

Each lesson cell has an **I don't get…** button. Say what you do not understand, in one line. The screen guide explains it in steps and draws a board on the cell: one shape for each panel, flows of boxes, and labels that never cover each other. The strip under the page shows each step, with keys to go back, go on and stop. The guide needs abhyasa 0.0.16 and rupaka 0.0.10 or newer, and it uses abhyasa's model (`ABHYASA_MODEL`, or the setting `models.default`).

### Search and memory

Code goes through [kosha](https://pypi.org/project/koshas/): FTS5, embeddings, a call graph
and notebook cells, behind `mod+shift+f`. Ripgrep is the fallback. Command-click reaches a
definition. Prose goes to a [vishalakshi](https://github.com/vedicreader/vishalakshi) vault
over litesearch. It holds every page read and every research source. The agent recalls one
with `memory_search`, `memory_read` and `ask_memory`, rather than paying to
search the live web again.

### The vault

Tools > Vault opens a workbench tab for shelves, search, imports, feeds, API specifications, and topics.
Paste a page, paper, repository, video, or folder. Folder imports show their plan before indexing.
`@` completes vault documents. Search results and document rows can attach sections to an agent question.

![Searching the vault, and attaching what it found](screenshots/vault-workbench.png)

### Research

[fossick](https://github.com/vedicreader/fossick) runs the web search and the extraction to
clean Markdown. Sources stay beside the reader, and a digest cites them. Everything renders
through [mdhtml](https://github.com/AnswerDotAI/mdhtml), which keeps a pasted `<script>` visible
rather than running it.

### The browser

A page opens as a tab. Chrome renders it offscreen in fossick's persistent profile and streams
frames in. A research result is a tab beside the notebook, on the sessions you already
signed in to. **read** lifts it to Markdown from the DOM after the scripts ran.
See [the browser, inside leela](#the-browser-inside-leela).

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
the same boxes, and a form builds new ones.
[gheasy](https://github.com/vedicreader/gheasy) writes every file, and one of those files is the
[fastship](https://github.com/AnswerDotAI/fastship) release for a Python package outside an nbdev
template.

Release runs the flow the project already uses, and each step is a pty step keeping its own exit
code. It runs nbdev's four commands where `settings.ini` or `[tool.nbdev]` says so. It runs
maturin's flow for a crate with Python bindings. That flow tests, builds a wheel, refreshes the
workflow and tags, and then the runners build every platform and publish. It runs `cargo publish`
for a crate without bindings. It runs fastship's five commands where a `pyproject.toml` declares
no nbdev. A project that packages a desktop app gets two more steps, after the release the
artefacts attach to.

Deploy runs the project's `deploy.py` stage by stage, or scaffolds the first one from dockeasy,
vpseasy and cfeasy. Drive is the same deploy taken apart, one library call per step. A failure
names the deepest frame in your own

<p align="center">
<img src="screenshots/release-maturin.png" width="290" alt="the maturin flow: test, wheel, workflow, changelog, tag">
<img src="screenshots/release-crate.png" width="290" alt="the crate flow: test, clippy, package, publish">
</p>
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
`alt+s` (Option+S) checks the exercise that has the cursor. On a `/learn` page, `alt+s` opens
the step as a lesson. That key on the `/learn` page cannot be rebound. In an editor, `alt+s`
never types the character ß.
`mod+shift+enter` runs everything. Rarer actions ship unbound with a button and a palette
entry, because the chords that survive your browser are yours to pick.

Rebind in `keys.json` in leela's config dir, or wherever `$LEELA_KEYMAP` or `--keymap` points:

```json
{"keys": {"run_cell": "mod+enter ctrl+y", "palette": "mod+shift+p", "quit": ""}}
```

Separate chords with spaces. `""` unbinds. Put only what you changed in `keys`. Every action
absent from it follows leela's default, including when that default moves in a later release.
`leela --write-keymap` writes the file and lists every action and its default under `_defaults`,
which leela rewrites and never reads. Copy a line out of it to change one more. Editing in the
browser under keys applies without a restart. leela skips anything unparseable, unknown or
conflicting, reports it, and keeps that action's default. A typo cannot stop leela starting.

## Opening a project without a command line

You double-click a packaged leela, and nothing tells it which folder you meant. It takes the
folders the desktop handed it, else the set it had open when it was last closed, else none.
Then it opens the welcome screen rather than guessing. `leela` from a shell means "here", and
the shell has already chosen where here is. A double-clicked application has no such answer,
and the old guess, home, handed kosha every file you own to index.

![The app with no folder open yet](screenshots/desktop-welcome.png)

The remembered set follows the workspace rather than the arguments it started with. A folder
opened from inside the app is there next launch, and one you closed is not. Closing a project
is not forgetting it. It stays on the welcome screen until you say otherwise. The ways in that
involve no typing:

- The platform's folder chooser, from **Open a folder** or **browse…**. A web page cannot
  produce a directory path, so in the packaged app this comes from the native window through
  `window.pywebview.api`.
- **Open With -> Leela** on a folder, and a folder dropped on the Dock icon. macOS delivers
  that to the *running* application rather than through argv. `leela.desktop` answers the
  `odoc` Apple Event and gives the folder a workspace and a window of its own. To put a
  second folder in the window you are already in, use `add…` in the files bar.
- **Open With -> Leela** on a file, and a file dropped on the Dock icon or a window. Finder offers
  Leela for every file a tab can show: text and source files, notebooks, images, PDFs, and Word,
  PowerPoint and Excel files. `leela.workspace.doc_types` holds the list, and both Mac apps take
  their `Info.plist` document types from it. Leela is never the default app for a type. After an
  update changes the list, macOS can keep the old one until the app is registered again:
  `/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f /Applications/Leela.app`.

Windows has no such event. Explorer starts a new process with the path in argv, which the app
already reads. To put leela on a folder's context menu:

```
reg add "HKCU\Software\Classes\Directory\shell\Leela" /ve /d "Open in Leela" /f
reg add "HKCU\Software\Classes\Directory\shell\Leela\command" /ve /d "\"C:\Path\To\Leela.exe\" \"%V\"" /f
```

## The browser, inside leela

A page opens as a tab. Chrome renders it offscreen in the persistent CDP profile and streams
frames into a canvas over `/browser/ws`. Mouse and keyboard go back the other way. A result
from Research is therefore a tab beside the notebook, on the sessions fossick already
signed in to.

![A live page in a leela tab](screenshots/desktop-window-browser.png)

`alt+shift+o` opens an address. **Tools -> Pages open in the browser…** adopts one Chrome
already has, whether leela opened it or fossick did. **read** lifts the page to Markdown
through the same `fossick.to_md` research uses, but from the DOM *after* the scripts ran and
after the login. A plain fetch cannot reach that. **remember** files it in the vault as an
ordinary source.

Nothing renders web content in leela's process. Chrome renders, and leela draws JPEG frames.
Every navigation goes through `fossick.check_url`, which stops anything pointing the browser back at
leela's own unauthenticated loopback server unless `FOSSICK_ALLOW_PRIVATE` says so. The panel
keeps the keyboard the way the terminal does. A page's own `j`, `/` and `?` reach the page.
Only the chords that get you back out stay leela's.

Frames cross the socket as raw JPEG rather than base64 in JSON, which is a third fewer bytes.
They decode through `createImageBitmap` off the main thread, which drops any frame arriving
mid-decode rather than queueing it. Latency on a picture nobody will see is worth nothing.
Hiding the window stops the cast. The page stays loaded, and resuming asks for a frame at once.

## What it costs to run

`tools/profile_app.py` measures the three things that judge the desktop app. Each runs in a
fresh subprocess, because import cost is order-dependent and RSS is cumulative.

```sh
python tools/profile_app.py            # all three
python tools/profile_app.py --imports  # what is on the startup path, and what it drags in
```

| | before | now |
|---|---|---|
| `import leela.app` | 766ms · 109MB | **377ms · 48MB** |
| process start to first page served | 786ms | **587ms** |
| one workspace, resident and idle | 119MB | **74MB** |
| one screencast frame, on the wire | 10,775 bytes | **8,080 bytes** |
| a launch that never opens a web tab | + ~900MB of Chrome | **no Chrome at all** |

The last line is the largest. A headless Chrome runs to some hundreds of megabytes across a dozen
processes. That is more than the workspace beside it, and most sessions never open a web tab. So the
first page that wants one starts it. `LEELA_CDP_EAGER=1` trades that memory back for the
second or two the first tab would spend waiting. Research still offers to open pages while the
browser is cold. `/browser/ready` answers "is there a Chrome to drive", not "is one running".

Nearly every byte of the first three lines was dhrishti, which the server imported for two constants
and a directory listing. dhrishti belongs *inside a kernel*. `dhrishti.core` imports IPython,
pandas and numpy at module scope, and leela's server never formats a live value.
`leela/core/inspectors.py` reaches `dhrishti.registry` for two things: the profile and sort
menus, and the reader for the registry that in-kernel inspectors write themselves into. It
reaches `kunda.support` for the import classifier. Neither import pulls in the kernel half. `tests/test_inspectors.py` imports
the real dhrishti and fails if the two disagree, round trip included. The kernel side is
untouched, which is why the dependency stays. The IPython still resident arrives through
`fasthtml.pico`, which `fast_app` imports even for `pico=False`. That one is a one-line fix
upstream.
