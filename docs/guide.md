# Using Leela

How to start Leela, what each part does, and the keys. The [README](../README.md) has the download and the install.

Chords show in Mac form first, then in the form for Windows and Linux. ⌘ is Command, ⌥ is Option, ⇧ is Shift and ⌃ is Control. In the app, the keys help (⇧⌘/, or Ctrl+Shift+/) shows each chord in the form for your computer.

## Use

```sh
leela                      # the saved workspace
leela .                    # a folder
leela src tests            # one workspace, two roots
leela --app src tests      # two app windows in fossick's persistent CDP Chrome
leela --shell webview .    # a native desktop window, what the packaged app runs
```

In `--app` mode each folder gets its own `Workspace`, documents, agent, terminals and kernel pool at `folder.localhost:5010`. `--app` sets the workspace layout. `--shell` sets the window that opens on top of it: `chrome` (the default under `--app`), `webview` for a native window, or `none`. The same CDP Chrome runs [the inline browser](#the-browser-inside-leela) in each case.

`--transport direct|gateway` sets the kernel transport. `--kernel ipykernel|ipymini` sets the kernel. `--agent restricted|readonly|off` sets what the agent can touch. `--approvals ask|auto|off` sets the first approval mode. Run `leela --help` for the other options.

## The window

The header has two rows.

The top row shows the folder and its state:

- **Leela**, the app name. In the Mac app the window buttons sit to its left.
- **The folder.** Click it to go to another workspace or another open folder, or to add a folder.
- **The branch**, with the number of changed files beside it. Click it to switch branch. A folder with no git repository shows `no git`.
- **Pull and push.** These show only when the branch is behind or ahead of its remote. Each shows the number of commits.
- **runs**, at the right. It lists the scripts that run under Leela.
- **The kernel.** It shows the runtime of the active tab and its state. Click it to choose a kernel.
- **The pane button.** It shows or hides the tools pane on the right.

The second row holds the work:

- **File, Tools and Debug**, the menus.
- **The tabs.** Tabs that do not fit fold into a `+N` button. The two arrow buttons split the editor side by side or top and bottom.
- **The run actions**, at the right. A notebook shows Run and Next. A `.py` file shows Run file and Selection. Both show Stop. Present shows for each tab. `⋯` opens the other editor actions.

The strip at the bottom of the window shows the most used keys.

## The venv notice

A Python project with no environment shows a notice above the editor: "No Python environment for *name*." A project is a Python project when it has `pyproject.toml`, `setup.py`, `setup.cfg` or `settings.ini`, or when it holds a `.py` or `.ipynb` file. Leela runs no code there until you choose one of these:

- **Set up .venv** makes `.venv` in the project with uv and installs only the kernel support. It does not install the project.
- **Choose interpreter…** opens the kernel picker.
- **Not now** hides the notice in this window until you open the window again.

A run in such a project asks the same question in a dialog. The agent does not make a venv unless you ask it to.

## What it does

### Editing

Notebooks and files sit side by side in CodeMirror 6. A `.py` file runs as a script in the tab's own kernel. The script gets `__main__` and an argv, and Variables then holds each name it defined. Press Run file for the whole file and Selection for the selected lines. ⌘P (Ctrl+P) finds a file by name. ⌘E (Ctrl+E) opens the recent files. Autosave is atomic. Leela also keeps a copy in IndexedDB and checks the version on disk before each save. Cells fold, headings make an outline, and each pane minimises.

### Rust and JavaScript notebooks

The kernelspec of a notebook sets the language of its cells. Leela runs three languages. Python runs on a managed ipykernel. Rust and JavaScript run on an installed Jupyter kernel, `evcxr_jupyter` or `deno jupyter`, when one is installed. Otherwise they run on Leela's own runner. A Rust cell becomes part of a scratch cargo crate that grows with each cell. The output of a failed cell is the rustc diagnostic, with its code (for example `E0382`) and the compiler's own text below it. JavaScript cells run in one long-lived node context, and a name made in one cell stays for the next. `notebook language` in the command palette changes the language of a notebook.

![The borrow checker, in a notebook cell](screenshots/rust-borrow-checker.png)

### Presenting a notebook

⌥R (Alt+R) presents the open notebook as slides, from the selected cell, with unsaved edits. Slides come from RISE cell metadata. An optional audience window shows the slides on a projector, and code cells run live on both screens. A presentation writes no file. See [present a notebook](present.md).

### Staging a folder of a language you have just met

`git add` obeys `.gitignore`. A new folder has no `.gitignore`, so `target/` or `__pycache__` go in with the source. `stage this folder, ignores first` in the command palette writes the rules that the folder's project kinds need, for Rust, maturin, Python and Node. It finds each kind from the files that declare it. It writes a rule only where `git check-ignore` reports the rule missing, and then it stages. The rules go in the folder's own `.gitignore`.

The file tree colours each file and each folder by its state: staged, modified, untracked, ignored or conflicted. A folder shows the strongest state of the files in it. A new folder shows as untracked before you expand it.

<p align="center">
<img src="screenshots/git-tree-before.png" width="300" alt="before: the crate is untracked">
<img src="screenshots/git-tree-after.png" width="300" alt="after: sources staged, target ignored">
</p>

### Live variables

Each notebook tab has its own kernel with a dhrishti inspector in it. kunda supervises the kernel, finds the interpreters and makes the kernelspec. The file tree stays responsive while a cell runs. `--kernel ipymini` sends runs and shell-channel calls to a subshell, so completion does not wait behind a long cell ([screenshot](screenshots/web-concurrency.png)). A value at the end of a cell opens in a lazy viewer. Start the Variables filter with `=` to evaluate an expression in the watched runtime.

### The agent

The turn runs on a local or a cloud model. Completions, summaries and sub-agents use the local model in both cases. Each call is a card. You can edit the call, read its dry-run diff, approve and run it, reject it with steering, retry it, or roll it back.

The control in the agent pane sets how many cards stop for you:

- **Guided** stops at writes and network calls.
- **Directed** stops at every call.
- **Edits** runs file and notebook edits without a stop.
- **Autopilot** sets the conversation's approvals to auto, so no card stops, also when Leela starts with `--approvals ask`. Stop and Pause after current still stop the agent. A card still stops for the third same call in a row, for a peer question that only a person can answer, and for a host policy that asks. Approvals that you switched off stay off.

When you leave autopilot or edits, the conversation goes back to the approval mode it had before. "Trust changes for this session" stays in effect.

Compaction shows in the timeline. A turn can fork from any revision. A prompt cell saves the answer in the notebook cell, as markdown that Jupyter can read. The charter under state holds context by organization, project, task and branch, and Leela puts it in the briefing. Skills come from `pyskills` entry points and `SKILL.md` folders. Leela adds its own skill, `leela`. It lists the features, menus, keys, panes, settings and agent tools, so the agent can tell you what Leela does and where. The agent harness is [ramabana](https://github.com/vedicreader/ramabana), and `leela.agent` is an alias for it.

Leela chooses no provider for you. When the agent's model cannot run, the agent pane lists the providers that it can use (OpenAI, Azure OpenAI, AWS Bedrock, Anthropic, Gemini, OpenRouter, Claude Code, Codex, a local model) and what each one needs. **+ model** adds one. See [integration.md](integration.md#providers-azure-openai-and-aws-bedrock).

### Lessons from abhyasa

Learn a topic step by step from [abhyasa](https://github.com/vedicreader/abhyasa) lessons, with exercises that the agent checks. In abhyasa, Open in Leela on a step sends a `/learn` link to Leela. A link with `go=1` opens the notebook at once, at the cell of its section. Other links show the step page, and **Open as a lesson** opens it.

- A step opens as a lesson notebook: the passage from the source, the tutor's note, a task, its tests, and the run.
- A lesson runs in its own uv environment, made from the requirements it declares. A lesson whose environment is not set up, missing or broken does not run. It never runs in the project's Python. Press Set up the environment on the step page.
- A notebook walk of abhyasa opens its learning copy. The copy runs in the folder and the `.venv` of the notebook that it comes from.
- Exercise cells have a Check button and a results list. ⌥S (Alt+S) checks the exercise that has the cursor. The agent grades a checked exercise from 0 to 10.
- `LEELA_LESSONS` moves the lessons folder.

### The screen guide

Each lesson cell has an **I don't get…** button. Say what you do not understand, in one line. The screen guide explains it in steps and draws a board on the cell: one shape for each panel, flows of boxes, and labels that never cover each other. The strip under the page shows each step, with keys to go back, go on and stop. The guide needs abhyasa 0.0.16 and rupaka 0.0.10 or newer. It uses abhyasa's model (`ABHYASA_MODEL`, or the setting `models.default`).

### Search and memory

Code search uses [kosha](https://pypi.org/project/koshas/): FTS5, embeddings, a call graph and notebook cells. ⇧⌘F (Ctrl+Shift+F) opens it. Ripgrep is the fallback. Command-click goes to a definition. Prose goes to a [vishalakshi](https://github.com/vedicreader/vishalakshi) vault over litesearch. The vault holds each page that you or the agent read and each research source. The agent finds them again with `memory_search`, `memory_read` and `ask_memory`, and does not search the live web again. See [search.md](search.md).

### The vault

Tools > Vault, or ⌥V (Alt+V), opens a workbench tab for shelves, search, imports, feeds, API specifications and topics. Paste a page, paper, repository, video or folder. A folder import shows its plan before it indexes. `@` completes vault documents. Search results and document rows can attach sections to an agent question.

![Searching the vault, and attaching what it found](screenshots/vault-workbench.png)

### Research

[fossick](https://github.com/vedicreader/fossick) runs the web search and changes each page to clean Markdown. The sources stay beside the reader, and a digest cites them. All Markdown renders through [mdhtml](https://github.com/AnswerDotAI/mdhtml), which shows a pasted `<script>` as text and does not run it.

### The browser

A web page opens as a tab. See [the browser, inside leela](#the-browser-inside-leela).

### Git

The source control pane has six parts: Changes, Review, Branches, History, Repository and All repos. ⌥G (Alt+G) opens it. Diffs open as editor tabs, unified or side by side, with hunk staging and a revert arrow for each hunk. Merge and rebase first show a plan that changes nothing. Blame reads a notebook as cells, not as JSON. `leela ~/code` opens a folder of checkouts and shows which are dirty, which are behind and which are not published. Fetch, pull and push run on all of them at once. Lazygit is in the dock (⌥⇧G, or Alt+Shift+G).

### Ship it

Workflows shows `.github/workflows` as jobs, with the `needs` links between them. The results of recent runs show on the same boxes, and a form makes new workflows. [gheasy](https://github.com/vedicreader/gheasy) writes each file. One of those files is the [fastship](https://github.com/AnswerDotAI/fastship) release for a Python package that does not use an nbdev template.

Release runs the flow that the project already uses. Each step runs in a pty and keeps its own exit code.

- nbdev's four commands, where `settings.ini` or `[tool.nbdev]` says so.
- maturin's flow, for a crate with Python bindings. It tests, builds a wheel, refreshes the workflow and tags. Then the runners build each platform and publish.
- `cargo publish`, for a crate without bindings.
- fastship's five commands, where a `pyproject.toml` declares no nbdev.

A project that packages a desktop app gets two more steps, after the release that the artefacts attach to.

<p align="center">
<img src="screenshots/release-maturin.png" width="290" alt="the maturin flow: test, wheel, workflow, changelog, tag">
<img src="screenshots/release-crate.png" width="290" alt="the crate flow: test, clippy, package, publish">
</p>

Deploy runs the project's `deploy.py` stage by stage, or makes the first one from dockeasy, vpseasy and cfeasy. Drive is the same deploy in parts, one library call for each step. A failure names the deepest frame in your own packages, with the path in the checkout that you have open. Secrets stay in dockeasy's store, and Leela never sends them to the browser.

## Updates

The Mac app checks for a new release when it starts and then each hour. A newer release shows a bar: "Leela *new* is available. You have *old*."

- **Update** installs the new release with Homebrew while you work. The bar shows each step.
- **Release notes** opens the release page.
- **Not now** hides the bar for that version until you open the window again.

When the install is done, the bar shows **Restart Leela**. Click it to quit and open the new version. If Homebrew does not list the new version yet, the bar says so and offers **Try again**. A Leela that you did not install with Homebrew shows only Release notes. Get the new DMG from the release page.

**Check for updates…** in the Leela menu, or in the command palette, asks GitHub at once and always answers, also after Not now. Leela run from the command line offers no update. Update it with `uv tool upgrade leela`.

## Watching something run

An inspector lives inside a process. One rule follows from that:

> A process that Leela started under a run configuration can be watched. A process that you started in another place cannot, unless it asks to be watched, in one line.

Run configurations live in `.leela/runs.json`:

```json
{"runs": [
  {"name": "api",   "cmd": "uvicorn app:app --port 8000", "watch": "app"},
  {"name": "train", "cmd": "python train.py"}
]}
```

Leela imports `watch` before it runs `cmd`. Uvicorn's own `import app` then finds the module already loaded, and the Variables pane shows that namespace while the server runs. When you leave out `watch`, Leela finds it from `app:app`. ⌥⇧A (Alt+Shift+A) runs a configuration. ⌥⇧E (Alt+Shift+E) watches another environment. `--reload` does not work with this: the reloader runs your app in a child process, and the inspector is not in that process.

Any other process joins when it asks:

```python
import dhrishti.serving as ds; ds.serve(name='api')
```

## Keys and buttons

Each action has a button, a command palette entry and a chord that you can change. ⇧⌘P (Ctrl+Shift+P) opens the command palette. ⇧⌘/ (Ctrl+Shift+/) shows all keys.

| Mac | Windows and Linux | Action |
|---|---|---|
| ⌘O | Ctrl+O | Open a file or a folder |
| ⌘P | Ctrl+P | Go to a file by name |
| ⌘1 to ⌘5 | Ctrl+1 to Ctrl+5 | Go to the files, editor, exec, variables or agent pane |
| ⌥⇧1 to ⌥⇧5 | Alt+Shift+1 to Alt+Shift+5 | The same, in a browser tab |
| ⌘S | Ctrl+S | Save |
| ⌘, | Ctrl+, | Settings |
| ⌘J | Ctrl+J | Show or hide the bottom tools |
| ⌃\` | Ctrl+\` | Terminal |
| ⌘↩ | Ctrl+Enter | Run the cell. In the agent pane, send. |
| ⇧↩ | Shift+Enter | Run the cell and select the next one |
| ⌥↩ | Alt+Enter | Run the cell and insert a cell below |
| ⇧⌘↩ | Ctrl+Shift+Enter | Run all cells |
| ⌥⇧↑ or ⌥⇧↓ | Alt+Shift+Up or Down | Move the cell |
| ⌥S | Alt+S | Check the exercise that has the cursor |
| ⌥R | Alt+R | Present the notebook from the selected cell |

In a browser tab, Chrome keeps ⌘1 to ⌘8 (Ctrl+1 to Ctrl+8) for its own tabs. Use ⌥⇧1 to ⌥⇧5 (Alt+Shift+1 to Alt+Shift+5) there. In a browser tab, ⌘O (Ctrl+O) asks for the path of a file or a folder. In the Mac app it opens the system file chooser.

On a `/learn` page, ⌥S opens the step as a lesson. You cannot change that key on the `/learn` page. In an editor, ⌥S never types the character ß.

## Jupyter command keys

A notebook cell is in command mode when it is selected and its editor does not have focus. Press Esc to leave the editor. In command mode these letters work as in Jupyter:

| Key | Action |
|---|---|
| A | Insert a cell above |
| B | Insert a cell below |
| D D | Delete the cell (press D two times) |
| M | Make a markdown cell |
| Y | Make a code cell |
| Enter | Edit the markdown cell |
| Esc | Render the markdown cell, or stop editing the cell |
| C | Copy the cell |
| X | Cut the cell |
| V | Paste the cell below |
| Shift+V | Paste the cell above |
| Shift+D | Duplicate the cell below |
| Shift+M | Merge the cell below |
| O | Collapse or expand the cell |
| Z | Undo the last cell operation |
| Shift+I, Shift+B, Shift+G | Set the slide type to slide, subslide or fragment |

In an editor, a field, a tab or a button, these letters type as usual.

## Change a key

Write your keys in `keys.json` in Leela's config folder, or in the file that `$LEELA_KEYMAP` or `--keymap` names:

```json
{"keys": {"run_cell": "mod+enter ctrl+y", "palette": "mod+shift+p", "quit": ""}}
```

In this file, `mod` is Command on a Mac and Control on other computers. Put a space between two chords. `""` removes the chord. Write only the actions that you change. Each action not in `keys` uses Leela's default, also when a later release changes that default.

`leela --write-keymap` writes the file and lists each action and its default under `_defaults`. Leela writes `_defaults` again and never reads it. Copy a line out of it to change one more action. Changes made in the keys panel apply without a restart. Leela skips each entry that it cannot read, does not know or that conflicts. It reports the entry and keeps that action's default, so a typo cannot stop Leela.

## Opening a project without a command line

A double-clicked Leela opens the folders that the desktop gave it. If there are none, it opens the folders that were open when it last closed. If there are none, it opens the welcome screen. It never opens your home folder by itself.

![The app with no folder open yet](screenshots/desktop-welcome.png)

The remembered folders follow the workspace, not the arguments that it started with. A folder that you opened in the app is there at the next launch. A folder that you closed is not. A closed folder stays on the welcome screen until you remove it.

You can open a folder without typing:

- **Open a folder** on the welcome screen, **browse…**, or ⌘O. In the Mac app these open the system chooser.
- **Open With > Leela** on a folder, or a folder dropped on the Dock icon. Leela gives the folder its own workspace and window. To put a second folder in the current window, use **Add folder…** in the folder menu of the header.
- **Open With > Leela** on a file, or a file dropped on the Dock icon or a window. Finder offers Leela for each file that a tab can show: text and source files, notebooks, images, PDFs, and Word, PowerPoint and Excel files. `leela.workspace.doc_types` holds the list. Leela is never the default app for a type. After an update changes the list, macOS can keep the old list until you register the app again: `/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f /Applications/Leela.app`.

On Windows, Explorer starts Leela with the path as an argument. To put Leela on the context menu of a folder:

```
reg add "HKCU\Software\Classes\Directory\shell\Leela" /ve /d "Open in Leela" /f
reg add "HKCU\Software\Classes\Directory\shell\Leela\command" /ve /d "\"C:\Path\To\Leela.exe\" \"%V\"" /f
```

## The browser, inside leela

A web page opens as a tab. Chrome renders it offscreen in fossick's persistent CDP profile and sends the frames to a canvas over `/browser/ws`. The mouse and the keyboard go back to Chrome. A result from Research is a tab beside the notebook, signed in to the sessions that fossick already has.

![A live page in a leela tab](screenshots/desktop-window-browser.png)

⌥⇧O (Alt+Shift+O) opens an address. **Tools > Pages open in the browser…** adopts a page that Chrome already has open, from Leela or from fossick. **read** changes the page to Markdown with the same `fossick.to_md` that Research uses. It reads the DOM after the scripts ran and after the login, which a plain fetch cannot do. **remember** files the page in the vault as an ordinary source.

Leela's process renders no web content. Chrome renders, and Leela draws JPEG frames. Each navigation goes through `fossick.check_url`. It stops each address that points back at Leela's own loopback server, unless `FOSSICK_ALLOW_PRIVATE` allows it. The page keeps the keyboard, as the terminal does. A page's own `j`, `/` and `?` go to the page. Only the chords that take you out of the page stay Leela's. Hide the window and the stream stops. The page stays loaded, and it sends a frame at once when you come back.

Leela starts Chrome only when the first web tab opens. `LEELA_CDP_EAGER=1` starts it with Leela.
