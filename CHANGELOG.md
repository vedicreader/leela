# Release notes

<!-- do not remove -->

## Unreleased

- Learn is a part of Leela. A Learn tab shows an Abhyasa walk in Leela's theme, with its checks, hints, graph, talks and concepts, and no second window or port. The Learn vault is a managed entry in the vault list, with a first-run import (Attach, Back up and copy, Skip). Learn needs abhyasa with `HOST_API` 1.
- Modes: Code, Learn and Create are workspace presets. Switching keeps the one agent conversation and changes its tools and context. In Code mode the agent sees the active cell.
- Learn from the agent pane: make, change and explain a walk, with job cards that you can stop. "I don't get this" goes to the step on screen.
- Learn sources from the workspace: tick the folders of the workspace or attach a path at "Sources for Learn". A refused path shows its reason.
- Code steps in Learn run live: a run moves the demo, and a slider rewrites the number in the code.
- Live scrub: a number in a cell becomes a slider, and the cell runs again in a worker process. Notebook files cannot turn it on.
- Trace this run: see the value of each line of a cell.
- Create mode: a scene of named values that you drag in the tab. The agent can read and set them, and Export page saves one web page. It needs rupaka 0.0.16.
- Save all no longer fails on an untitled tab: autosave skips it, and Save still asks for a name.

## 1.0.4

Cells: undo no longer strands a running cell.

- Undo and redo keep the cell that is running. An undo that would remove it is refused until you stop it. Before, Cmd+Z while a cell ran left the cell looking running, the stop button said it was not running, and the cell would not run again.
- Stop asks the server when the page thinks the cell is idle, and clears a running mark that has no run behind it.
- A step taken while a cell runs no longer brings that cell back as running when you undo it.
- On Linux, the file watcher looks at the folders once more on its first idle tick, so a folder made just before the watch started is watched.

## 1.0.3

Keys: a chord you set is never refused for a chord Leela ships.

- A chord you set in `keys.json` wins over a built-in default. The default loses only that chord and keeps its others. The keys panel and the file notes say which chord moved. Two chords of yours that collide are still refused, and a file of more than 50 entries still counts as machine-written, so a default outranks it.
- On a Mac, `hyper+z` and `mod+alt+shift+z` are different keys, so they no longer collide.
- A default that lost a chord to yours is no longer written into `keys.json`, so it follows the next default.
- Keys v2 took Hyper off 16 defaults. If you used them, add the chords you want to `keys.json` again.
- Needs ramabana 0.2.112.

## 1.0.2

The Mac app is the full app again, signed and notarized, as in 0.1.27. The small-launcher app of 1.0.0 and 1.0.1 is not released.

- Same fixes as 1.0.0 and 1.0.1: the Mac's own title bar with no title text, the 0.1.26 header, a prompt in the agent pane that shows at once, and a folder menu that keeps a long path on one line.
- A folder you pick in Leela's own folder dialog (⇧⌘O, find repository) opens with no second "Add this folder?" question.

## 1.0.1

The first Leela app for Mac built as a small native launcher; 1.0.0 was the first package and environment lock.

- A folder you pick in Leela's own folder dialog (⇧⌘O, find repository) opens with no second "Add this folder?" question.
- `make ship V=<version>` runs the whole release in order and skips each step that is already done.

## 1.0.0

Leela 1.0 for Mac is a small native app: it sets up its own Python environment from a signed package lock, and updates that lock without a new app. Needs kavacha 0.0.18.

- The window keeps the Mac's own title bar and draws no title text in it; the title is still set for Sanketa and the Window menu. On macOS 26 the 0.1.27 title bar painted over the header's top row, so the folder, branch and git buttons did not show.
- The header is the 0.1.26 header again: one row with the folder, branch, git, menus and tabs, and the run toolbar under it. A small Leela mark and a serif "Leela" start the row, on the same baseline as the folder name.
- A prompt sent in the agent pane shows at once. The server accepts the turn in about 20 ms and checks the model while the reply starts. A refused prompt goes back into the box with the reason.
- The folder menu keeps a long path on one line, shows your home folder as `~`, and no longer scrolls sideways.

Known issues:

- The first install downloads about 392 MB of packages. A later release moves the large ones into extras.
- The thin app's server log is never rotated.
- Another program on your Mac can still reach Leela's local server; a per-launch key is planned.

## 0.1.27

Needs kavacha 0.0.16, Sanketa 0.2.7, shalya 0.1.32, pullup 0.0.12, dockeasy 0.0.13, gheasy 0.0.21, kunda 0.0.15, dhrishti 0.1.13, koshas 0.1.23, fossick 0.1.26 and litesearch 0.1.64.

- Security:
  - a raw file such as an SVG is served in a sandbox, so its script cannot run at Leela's address;
  - a git ref that starts with a dash is refused, and gheasy marks where options end;
  - a page on another local port can no longer reach Leela, and routes that change things take only POST.
- The agent asks, in every mode short of autopilot, before code it runs (an isolated check stays free), a watch or remember on a file, folder or URL, an API call other than GET or HEAD, image and video generation, and a write under `.git`, `.venv` or `.leela`. A watch cannot reach outside your folders or credentials. The notebook tools act on the open tab, unsaved edits included.
- API keys go to the keychain, or a 0600 file when there is none, and never into the environment of kernels, shells or pipelines.
- A repo's `.leela/settings.json` cannot choose the terminal program or the agent's config folder; the settings page lists what it ignored.
- A file that is not UTF-8 opens read-only and is never rewritten. A file keeps its own line endings.
- A loop that prints a lot streams small updates: 2000 prints send about 32 KB, not 125 MB. One output keeps at most 200,000 characters.
- A save after git or a formatter changed the notebook keeps your deletes, moves and outputs. Two windows on one notebook keep each other's edits, and the same cell edited in both asks which to keep.
- A large notebook is not sent again when its tab comes back, and saving it no longer grows memory.
- A settings file with a typo is kept as it is, with a `.bad` copy, and Leela says why it cannot save.
- A clone goes only into an open folder or one you approve.
- Go-to-file walks up to 100,000 files and says when it stopped early.
- The trash drops items older than 30 days and keeps under 2 GB.
- File history is safe with two windows.
- Rust cells run again without a duplicate-definition error, and Stop ends the whole program.
- On Linux, the file watcher skips ignored folders, and a deleted folder no longer stops the watch.
- Contrast meets WCAG AA. The welcome screen, menus and palette use plain words and real key glyphs. Dark-mode tables, menus that ran off the screen, toasts and the terminal's PATH line are fixed. The guide and README match the app.
- fossick converts web pages with markdownify (MIT) instead of html2text (GPL), and its caches no longer use pickle. The `.kosha` folder hides itself from git.
- The frontend bundles have a lockfile and rebuild to the same bytes; `leela/vendor/THIRD_PARTY_NOTICES.md` lists their licences.

- A new two-row header shows the Leela mark and name, the folder, the branch with its change count, and ↓/↑ only when the branch is behind or ahead. Row 2 holds File, Tools, Debug, the tabs and Run, Next, Stop and Present. The old toolbar row is gone. On macOS the title bar is part of the window.
- The window title is `Leela · <folder> · <scope>`, for example `Leela · karma · notebook`. It always ends with the scope that Sanketa reads, and it changes when the folder changes.
- Update installs through `vedicreader/tap/leela`, in an environment like Terminal's. When Homebrew fails, Leela shows its error and keeps it in the log.
- Leela checks for a new release at each start and every hour. "Not now" holds for that version only.
- The agent has a `leela` skill: what Leela can do and where, with the menus, keys, panes, settings, slash commands and tools. It is built from the app, so it shows your own keys. A local model on the auto profile does not see skills; set the profile to full for a large local model.
- Signing retries when Apple's timestamp server does not answer (kavacha 0.0.16).
- Security: oauthlib 4.0.1, tornado 6.6 and setuptools 84.2.1.
- A kernel's inspector asks the OS for a free port. Before, it took 8400 or the next free port, so a person's own server on that port could not start. `--kernel-port` still sets a fixed start port.
- Leela ships `leela/vendor/THIRD_PARTY_NOTICES.md`, with each package in its browser bundles, its version, its licence and the licence text. `frontend/package-lock.json` is committed, so `npm ci && npm run build` makes the same bytes; `make vendor-check` checks it. htmx is pinned at 2.0.7, the version Leela ships.

## 0.1.26

- On macOS, Word, PowerPoint and Excel tabs show Quick Look's own preview: slide layout, fonts, colours, charts and pictures. A button switches to the simple view, and the choice is kept. The agent and "copy as text" still read the text. Excel shows at most 4096 rows a sheet in this view, and says when a sheet is cut off.
- Leela no longer makes a venv by itself. A Python project with no venv shows "No Python environment for <project>." with "Set up .venv", "Choose interpreter…" and "Not now". A run that needs Python asks the same, then runs. Pipelines and releases run as pullup runs them: in a project with pyproject.toml, uv makes .venv when a step needs it. The agent cannot make one either; it must ask.
- Files whose names have characters outside Latin-1 open in every viewer: screen recordings and screenshots (the narrow space before "am"), names in Chinese or Japanese, and names with quotes. Before, the server answered 400 and a video said it "cannot play here".
- A path asked for in the other Unicode spelling of an accent (café typed one way, stored the other) is found, on macOS and on Linux.
- A markdown image whose path has spaces or such characters shows.

Known issues:

- A run configuration written as `uv run …` still makes a `.venv`, because uv does.
- Quick Look shows only the first page of Keynote, Pages and Numbers files, so those stay in the simple view.

## 0.1.25

Needs kavacha 0.0.14.

- Update sees a release pushed today: it makes Homebrew fetch its list first, and runs `brew update` once if Homebrew still lists the old version. If Homebrew does not list the new version yet, Leela says so, with Try again.
- "Check for updates…" is in the Leela menu, below About, and in the palette. It checks now, past the 6-hour cache and past "Not now", and says the newest version, "up to date", or that it could not check. The Models and updates dialog runs the same Update and Restart.
- When a new version is installed but Leela still runs the old one, Leela offers "Restart now". A second Update click does not start a second Homebrew run.
- ⌘O "Open…" shows the Mac chooser for a file or a folder. A folder opens in its window; a file opens as a Finder open does. ⌘P is now "Go to file…" (search in the open folders).
- A file or folder dropped on the window from Finder opens as a Finder open does.
- ⌥⇧↩ runs "run the selection" from the menu again; before, the menu ran ⌥↩'s row.
- Security: a page can no longer call the app's host callbacks. Before, a page script could open any folder with no question.

Known issues:

- A file dropped on an open editor or cell goes into the editor as text, as before.

## 0.1.24

- Word, PowerPoint and Excel files open in a read-only viewer. Word shows headings, lists, tables and images; PowerPoint shows one card per slide with its speaker notes folded; Excel shows one button per sheet and 200 rows at a time, with the values the file saved. Each has "open in default app" and "copy as text". The agent reads them as text. Leela never writes to them, and older formats (.doc, .xls, .ppt) are refused instead of shown as bytes.
- Audio (mp3, wav, m4a, aac, flac, ogg, opus) and video (mp4, m4v, mov, webm) open in their player, from the file tree, quick open, Finder, a drop and the agent's links. Seeking works. A format the web view cannot play offers "open in default app". Media is never shown as text.
- Finder lists Leela in "Open With" for every file it can show: source and text files, notebooks, images, PDFs, office files, audio and video. Leela is always an alternative, never the default app. After an update, run `lsregister -f /Applications/Leela.app` (in /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support) so Finder reads the new list.

Known issues:

- Office viewers draw Leela's own layout: no fonts, colours, charts or slide positions, and Excel dates show raw.
- Split view does not take a media tab.

## 0.1.23

Needs kavacha 0.0.13, kunda 0.0.14, dhrishti 0.1.12, shalya 0.1.31, ramabana 0.2.111 and rishi 0.1.68.

- A notebook, a script run from the editor, the debugger, dev runs and release pipelines run on the project's own `.venv`. A project with no venv gets one on first run, and the kernel pill says so once. Leela no longer picks a venv from a folder above the project.
- A venv you choose in kernel settings is kept for that project and wins over the project's own venv. Before, the picker did nothing in a folder that had a venv.
- A kernel in a venv imports only that venv's packages. Before, it could import Leela's own packages when the Python versions matched, which hid missing dependencies.
- The agent runs its own tools (rupaka, kosha, ramabana, leela) in `own_python`, on Leela's own Python. `run_python` keeps your notebook's variables.
- New key bindings. Every Hyper chord is gone (the window manager took most of them). ⌘N, ⌘O and ⌘W work from anywhere, ⌘1 to ⌘5 focus the panels, ⌘J toggles the bottom panel, ⇧⌘A also opens the palette, ⌥I is now ⌥T. A notebook takes Jupyter letters when no cell is being edited (`a`, `b`, `dd`, `m`, `y`, `c`, `x`, `v`, `z`), and Esc leaves the cell editor. Each chord Chrome keeps has a second chord for a browser tab. For one release an old chord still works and says what replaced it.
- Menu shortcuts with Shift run from the menu. A chord no longer runs a menu row behind an open dialog. Recording ⌥W saves ⌥W.
- File search works with rgapi 0.2.3, which swapped the order of its first two arguments.
- The file watcher reports an edit made in its first moments, and keeps watching when one watched folder is deleted.

Known issues:

- Clicking a menu row with the mouse while a dialog is open still runs the row.
- The palette lists "new file" twice: one for anywhere, one for the file tree.
- `.docx`, `.pptx` and `.xlsx` still open as text; viewers come next.

## 0.1.22

Needs kavacha 0.0.12 and ramabana 0.2.109.

- A conversation that nobody gave a model moves to the model that runs here: Claude Code, then Codex, Copilot or an API key, then a Gemma already on disk. The pane says why it moved. A model named in config.toml, `/model` or the picker stays.
- When no model runs here, the turn stops with a plain message, and the welcome offers "Download Gemma 4 E2B (3.5 GB) to run on this Mac". Nothing downloads without that click.
- The Mac app tells you when a newer Leela is out. Update runs `brew upgrade --cask leela`, then offers Restart Leela. An app not installed from the cask shows the release link.
- The Mac app is about 860 MB, down from 1.2 GB, and its download is about 300 MB, down from 430 MB. It no longer carries a second Claude CLI; it uses the `claude` on your PATH. The second browser driver links to the first.

Known issues:

- A Gemma that is not on disk yet, chosen in the picker or with `/model`, downloads on the first turn with no progress bar.
- A model typed with `/model` in the pane is not kept for the next conversation.
- A resumed Claude conversation keeps Claude and stays refused when Claude cannot run.
- Between the end of an update and Restart Leela, a feature that loads late can fail, because Homebrew has replaced the app's files.

## 0.1.21

Needs kunda 0.0.12.

- When a kernel's shell stops answering, the cell ends with "The kernel's shell stopped answering" and a Restart kernel button. Before, kunda asked again every 30 s and the cell never ended.
- The kernel pill, the kernel picker and the project runtime check warn about ipykernel 7.0 to 7.3, which can stop answering, and offer to upgrade it. Kernel support installs ipykernel 7.4 or later, not the host's exact version.
- Lesson environments get ipykernel 7.4 or later. An older lesson environment with ipykernel 7.0 to 7.3 is installed again.

## 0.1.21

Needs kunda 0.0.12.

- A cell on a gateway kernel whose shell stopped answering now ends. The cell shows "The kernel's shell stopped answering" with a Restart kernel button. Before, the cell ran until the kernel restarted, with no message. ipykernel 7.0 to 7.3 can stop this way.
- The kernel pill and the kernel picker warn when the kernel runs ipykernel 7.0 to 7.3, and the picker offers to upgrade it. The project runtime check offers the same upgrade.
- A lesson environment gets ipykernel 7.4 or later. An older lesson environment on ipykernel 7.0 to 7.3 gets its kernel packages again the next time Leela makes it, or from the upgrade button.

## 0.1.20

Needs kunda 0.0.11 and ipykernel 7.4.

- A cell no longer hangs after it runs for about 2 s. ipykernel 7.0 to 7.3 can stop reading its shell socket when a request comes at the same moment as a reply goes out (ipykernel PR #1529). Kunda's check for a lost reply sends a request about 2 s into a cell, so such a cell could hang until the kernel restarted. Leela and kunda now need ipykernel 7.4.

## 0.1.19

Needs koshas 0.1.22 and litesearch 0.1.63.

- The git history panel asks the repo that its list came from. Before, showing a file of a commit in another repo's list could ask the active file's repo and fail with "unknown branch, tag, or commit". When the panel moves to another repo, it closes the old repo's open commit, compare and review.
- The git panel and the history refresh when a file changes on disk and when a commit, a checkout or a fetch happens outside Leela. A burst of saves gives one refresh.
- After a git action from the panel, the next repo switch moves the panel. Before, the panel stayed on the old repo.
- Go to declaration uses the interpreter of the file's own folder. Before, it used the first open folder that had a `.venv`, and it could point into another project's packages. A package in that interpreter opens read-only.
- The search panel shows a failed Kosha sync and its error, and it repaints the index header after each sync. Before, it said "synced" when the sync had failed.

## 0.1.18

Needs kavacha 0.0.11.

- Rich output can no longer run script in Leela. HTML, SVG and MathML from a cell, and HTML from an ipywidget, pass one allowlist before they show: no event attributes, no `javascript:` links, no frames, and no requests to Leela from images or CSS. Before, an output such as `<img onerror=…>` ran in Leela's page and could call Leela's routes. Tables, images, SVG and maths still show.
- Cell ids from a notebook file, git paths, branch names and media links are escaped where Leela writes them into the page.
- No request adds a folder by itself. Leela asks with a native dialog that names the folder, and only your click adds it. Open Folder, the Dock, Finder and the folder picker still need one step. A No holds for 10 minutes.
- A request that changes something must come from Leela's own page: its Origin must match the host and the port. The routes that add a folder take POST only.
- The lesson handoff asks before it adds a folder. One question can add both the project and its learning copy. With no folder open, a lesson opens as a loose tab.
- In browser mode there is no native dialog. There, a request from the agent's shell can still pretend to come from the page; `docs/desktop.md` says so.

## 0.1.17

Needs rupaka 0.0.15.

- A demo has "Ask about this" (rupaka 0.0.14). In a lesson, the question goes to the screen guide with the cell, the demo, its step and its values. Anywhere else it goes to the agent. The control is hidden in present mode and in the audience window, so the room never sees it.
- A 3D scene draws again when its view comes back. rupaka 0.0.15 keeps the scene's renderer while it is off the page and makes a new one when the browser took the WebGL context away.
- The vendored lee-rupaka.js and lee-rupaka.css are written from the rupaka 0.0.15 wheel.

## 0.1.16

- Leela asks before it opens another folder. When a link, a definition, a traceback, Finder or the agent opens a file from a checkout that is not open, Leela shows the file and asks: "This file is in <repo>. Open <repo> as a folder?" Only Open adds and remembers the folder. Open Folder, Add folder, the recent list and a folder dropped on the Dock still open at once. Before, Leela added the folder without a question.
- A rupaka demo in a .md file draws in the preview, and draws again after you close and open the file. Before, the fence showed as code.
- A demo's prediction comes back after a reload or a restart. Leela reads the predictions that it filed and settles each gate, so a gated 3D scene shows again.
- A 3D scene draws again after a tab switch or after you close and open the notebook. Before, the box stayed white: the scene had lost its WebGL context. Leela now mounts it again with its values.
- The test suite and the tools that serve Leela use their own config folder, never `~/.config/leela`.

## 0.1.15

Needs ramabana 0.2.106 and rishi 0.1.67 or later, not one exact release.

- A rupaka 3D scene demo draws in Leela. Leela serves rupaka's own copy of three.js at `/leestatic/three.js`, so the scenes in a lesson, on a slide and in the audience window load it. Before, a scene showed "three.js did not load".
- Compaction in the agent keeps the newest messages and the session ledger: your requests, the evidence of each done step, the changed files and the commits. It calls no model by default (ramabana 0.2.106).
- A step of the agent's plan is done only with evidence: a commit, a file or a test result (ramabana 0.2.106).
- A sub-agent cannot send peer messages, write memory or add folders unless you grant it (ramabana 0.2.105).
- A tool whose source file is gone is left out with a notice. Before, the model showed as unavailable (ramabana 0.2.105, rishi 0.1.67, uraiyadal 0.0.21).

## 0.1.14

Pins ramabana 0.2.104 and rishi 0.1.66.

- The minimise button of the right tools is on the tab row again. The Review tab had pushed it onto a second line.
- `ramabana tell` takes its text after an option, for example `ramabana tell abhyasa --ask build Card` (ramabana 0.2.104).
- The Homebrew cask installs a stapled zip of the Mac app. Homebrew 7 fails when it unpacks the mounted DMG.
- The README shows the app icon.

## 0.1.13

Pins ramabana 0.2.103 and rishi 0.1.66.

- Autopilot raises no approval cards. It sets the conversation's approvals to auto, also when Leela starts with `--approvals ask`. Stop, Pause after current, the third same call in a row, a peer question for a person and a host policy that asks still stop the agent. Approvals switched off stay off. Leaving autopilot or edits gives back the earlier mode, and "Trust changes for this session" stays.
- Auto approvals raise no guided network checkpoint.
- An approval card that you do not change runs as approved, not as edited, and its waiting label clears.
- The terminal sets `TERM` and `COLORTERM`. The agent shell sets `TERM=dumb`.
- Always allow on a prompt-cell card works. Prompt cells read the saved allow rules.
- `make ship V=<version>` builds, signs, notarizes and staples the Mac DMG, puts it on the release and pushes the Homebrew cask.

## 0.1.12

Pins ramabana 0.2.103 and rishi 0.1.66. Needs abhyasa 0.0.16 and rupaka 0.0.12.

- A quick call with no thinking sends no reasoning effort, so a model such as GPT-6.1 Sol runs at its default and answers on the first try (rishi 0.1.66).
- Open a notebook from abhyasa at once, at its cell. A `/learn` link with `go=1` opens the notebook and selects the cell of its section, also a section heading, and keeps it in view while the outputs above it draw.
- A notebook walk of abhyasa opens its learning copy as the lesson. The copy runs in the folder and the environment of the notebook that it comes from: the kernel starts in that folder and uses the nearest `.venv` of that project. A folder of copies never gets an environment of its own. The copy starts with a link back to the walk.
- The screen guide's board comes from rupaka 0.0.12 (`rupaka.board`): one shape for each panel, flows of boxes, follow-ups that build on the board before, and labels that never cover each other. `lee-rupaka.js` and `lee-rupaka.css` are written from the 0.0.12 wheel.
- Leela imports abhyasa from its six new modules, and a test checks each name that Leela imports.
- The closed code runner moved from abhyasa into Leela.
- The lesson environment: Set up goes back to the step page and shows the state until it is ready. The ready environment is saved into the lesson file. `LEELA_LESSONS` moves the lessons folder. The step page names the data entries that are not on this computer.
- `/git/notebook` answers for a notebook in no repository with no changes, not a 400.
- `tools/ship_cask.sh` writes the version and the sha256 of a release into the Homebrew cask of Leela.

## 0.1.11

Pins ramabana 0.2.95, rishi 0.1.61 and rupaka 0.0.7. Needs abhyasa 0.0.13, kunda 0.0.10, kavacha 0.0.10, litesearch 0.1.61, koshas 0.1.20, vishalakshi 0.1.35, dhrishti 0.1.10 and dhrona 0.1.18.

- The server no longer serves files from its working folder. FastHTML's static route is removed. Before, an encoded `../` in a URL could read any file with a static extension.
- Learn from abhyasa. A `/learn` link opens a walk step or a topic. A step opens as a lesson notebook. A lesson runs in its own uv environment, made from the requirements it declares. A lesson whose environment is not set up yet, or is missing or broken, refuses to run. It says to open the step and press Set up the environment. It never runs in the project's Python. Exercise cells have a Check button and a results list. The agent grades a checked exercise from 0 to 10. A run result is filed to the walk, with the number of tries and the step's concept (abhyasa 0.0.13).
- Option+S (`alt+s`) checks the exercise that has the cursor. On a `/learn` page it opens the step as a lesson. In an editor it never types ß.
- The assistant merges, rebases and settles merge conflicts with the git tools `git_sync` and `git_conflicts`. Each needs approval and gives an undo token. No reset is offered. `run_shell` refuses `git merge` and `git rebase` (ramabana 0.2.95, shalya 0.1.26).
- Text that a model writes after its last tool call no longer reaches the assistant. That text was often an invented tool result (rishi 0.1.61).
- ipywidgets render and run in notebook cells.
- The editor has multiple cursors. A column mode adds cursors with the arrow keys.
- Notebook headings collapse their sections.
- Notebook edits, runs, outputs and diffs act on their own notebook and cell, in order. A save never clears a later change.
- Open With Leela opens a single file as well as a folder.
- Cmd-click into the standard library opens the definition, read-only.
- A link in a reply or in Markdown never navigates the app window. A file opens as a tab, and a web link opens in the browser.
- Rendered Markdown is sanitized with nh3. Dollar maths renders with a vendored KaTeX, with no CDN.
- In the terminal, Option acts as Meta by default. A palette entry turns it off.

- Leela has one presentation mode. Alt+R, the Present button and "Present from this cell" present the open notebook from the selected cell, with unsaved edits, on Leela's own slide renderer in Leela's themes and fonts. A presentation writes no file. Run skips the save, and autosave pauses. Slides come from RISE cell metadata in one line, with fragments. An H2 heading starts a slide when no cell is marked `slide` or `subslide`. reveal.js, its themes, `rise.theme` and the other reveal options, vertical navigation and the separate notes page are removed. The optional audience window follows the presenter through the server and opens in the system browser in the Mac app. Code cells run live on both screens. A failed run shows its traceback to the presenter only, until Show error. Esc never ends a presentation, and a reload comes back at the same place. See `docs/present.md`.
- A cell output cleared during a run (`clear_output`) leaves the streamed output on the page and in a presentation once kunda 0.0.10 sends the clear. Before, the receiver would have appended it as one more output.
- The keys help says that the `present` keys work only during a presentation and cannot be rebound. It said that every key in it could be rebound.

- The window title names the pane that has focus: `leela — <folder> · <scope>`, with `py`, `notebook`, `terminal`, `agent`, `exec`, `files`, `vars`, `vault`, `review`, `web` or `editor:<ext>` as the scope. The token comes from the scope the key router uses. The title changes at most once in 100 ms, and only when the string changes. Leela.app sets its native window title through `window.pywebview.api.set_title`. The agent's `2⚙ (!)` marks stay in front.

- The canvas is removed: the `canvas` block and its `*.canvas.md` documents, the `+canvas` button and `hyper+j` shortcut, the `canvas_*` and `flow_canvas` agent tools, the canvas skill, and the `leela-bricks` development dependency. A saved session that lists a canvas tab opens without it.

- kavacha's interpreter probes and build steps, pullup's `gh auth status` and dhrishti's `ps` get `/dev/null` as stdin, like Leela's own child processes (kavacha 0.0.8, pullup 0.0.11, dhrishti 0.1.8).

- The `ramabana` terminal runs on teleprint 0.1.4. Ctrl+z hands the terminal back to the shell with extended keys, mouse reports and bracketed paste off, and takes it again on `fg`. Quitting from the transcript view leaves the alternate screen.

- A hosted model's tool call cut off at the output limit, or with arguments that are not JSON, goes back to the model once, at a raised output cap when cut off. A second failure fails the turn or the background delegation with `ToolCallError` and the reason, such as "openai/gpt-5.6's tool call was cut off at its 16384-token output limit". It failed with a bare `JSONDecodeError: Unterminated string`. A reply cut off while the model was still thinking is handled the same way.
- A hosted model with no `max_output_tokens` in config.toml gets its own maximum output, or 16,000 tokens for a model fastllm does not know. It got 4096, which a reasoning model's thinking could use up before it finished a tool call.
- The agent's Python stays in one kernel for the whole turn. `run_python`, `inspect_python`, `list_vars` and `promote_var` used the kernel of whichever tab was in front, so a tab the person clicked mid-turn moved the agent to another kernel and every name it had bound vanished with nothing said. The turn now keeps the kernel it first used. When a call lands in a different kernel from the last call (a restart, or a new turn in another tab), its result opens with a line saying so.
- `run_cell` on a notebook with no open tab runs in that notebook's own kernel, the one its tab will use when opened. It used to run in the kernel of the tab in front, so opening the notebook gave a fresh kernel at In[1]. A run in a kernel that restarted since the last `run_cell` there says so. The binding diff after a cell reads the kernel the cell ran in, so it no longer reports names such as `open` that only differ between two kernels.
- A transcript notebook under `_leela_agent_sessions/` or `_leela_sessions/` runs in the folder above it, so its kernel's own transcripts no longer nest a second `_leela_agent_sessions/` inside the first.
- `environment` tells the agent that kernels also import from Leela's own library path, after the project's packages, so a package that imports in a kernel can still be missing from the project.
- The packaged app copies `fastaudit` and `safepyrun` whole. safepyrun loads `fastaudit.hooks` from an entry point that no freezer scans, so every isolated `inspect_python` failed in the app with `No module named 'fastaudit.hooks'`.
- Functions defined through `run_python` have source, so `inspect.getsource`, rishi's tool schemas and tracebacks work on them (dhrishti 0.1.7).

- The vault stores one text once. A file added by a relative path, an absolute path, a symlink or a copy is one document, and a file edited since it was added replaces its old chunks (litesearch 0.1.50). litesearch's usearch probe no longer shares the terminal (litesearch 0.1.51). `Memory.by_source` finds a document by any source it is filed under, and a Local only document's list of sources is withheld with its source (vishalakshi 0.1.33).
- Nothing Leela starts itself shares the terminal any more. The login-shell environment probe, `run_cmd`, scripts and jobs, installs, nbdev and fastship steps, the Rust cell runner, pytest flows, interpreter and debugpy probes, and the repository scan get `/dev/null` as standard input. A prompt in any of them now fails at once instead of waiting until the timeout. LSP, debugpy, the Node driver, formatters and the IDE terminal keep their pipes and pty.
- The login-shell probe, installs, and nbdev and fastship steps run in their own session, so an interactive shell or a credential prompt cannot open `/dev/tty` either. A browser that `BROWSER` names, or Linux's `xdg-open`, gets `/dev/null` as standard input; macOS still opens through `osascript`.
- Nothing the agent's libraries start shares the terminal any more. `claude --version`, `ollama serve`, git through gheasy, interpreter probes, Chrome, and ramabana's own git calls get `/dev/null` as standard input (rishi 0.1.53, gheasy 0.0.14, kunda 0.0.5, fossick 0.1.20, ramabana 0.2.60).
- Dhrona's assessments and nightly rounds see long tool results whole again, read back from `agent-details/` (dhrona 0.1.15).
- A command the agent runs can no longer read the terminal or set it non-blocking; it gets `/dev/null` as standard input (shalya 0.1.19).
- The conversation log no longer keeps long tool results. Each goes whole to `agent-details/` in the agent's config folder, and the log keeps its first 600 characters (ramabana 0.2.59). A conversation's turns, and a reopened one, read only that conversation's rows and show its tool results whole. Backups include `agent-details` as "long tool results".

- A video model written as `gemini/models/<model>` starts its job instead of requesting `models/models/…`.

- A Gemini model chosen as `gemini/<model>` answers instead of returning 404. A Claude Code session that fails while connecting is tried once more, with a note in the session (rishi 0.1.52).

- The terminal agent no longer freezes and then closes its tmux session on the next key when a process that shared the terminal left it non-blocking. An exception in a key handler or a background notice shows as an error and the session carries on (ramabana 0.2.58).

- The agent's `delegate_search` and `delegate_async` take `model=` and `effort=`, one for every question or one per question. Read-only sub-agents on different models and providers run at once. A model that is not set up returns its setup message for that question and is never replaced by another. Effort maps to Claude Code's effort and OpenAI, Azure and Gemini reasoning effort; a local model runs without it and the answer says so. Tool parameters carry descriptions, and on this machine Claude Code refuses in-process MCP servers, so Claude's tool calls stay as text (ramabana 0.2.57, rishi 0.1.51, shalya 0.1.18).

- The agent settings set the sub-agent model, the sub-agent effort (`low` to `max`), and whether sub-agents and turns get native tool calls or schemas as text (ramabana 0.2.57, rishi 0.1.51, shalya 0.1.18). The palette opens each control. The workspace keeps the values, and every live and new conversation takes them. `/agent/subagent-settings`, `/agent/tool-mode`, `/subagents model|effort|tools` and `/model tools` are the routes. A model that is not set up is refused with `ok: false` and its setup message on every route. The reasoning select adds `xhigh` and `max`, and Claude turns receive the level as `effort`.

- The agent's `delegate_search` gives its sub-agents read tools unless it asks for `writes=True`, so several questions run at once. A sub-agent takes up to 80 steps, and a delegation that asks for fewer gets at least 20. Sub-agents are told that a tool result contradicting what they just saw is likely a harness fault to confirm and report, and the briefing points at the `debugging` skill. A Claude Code turn's usage counts its thinking tokens (ramabana 0.2.56, rishi 0.1.50).

- Dhrona's nightly retries and reports its errors (dhrona 0.1.14).

- The scheduled beat that runs Dhrona's nightly says when it was installed from a short `PATH`, and a session's first beat note says when the installed launcher predates the `PATH` fix or no longer finds `claude`, `git` or `git-lfs`, with the command to re-run (ramabana 0.2.55). `ramabana-tick --check` prints the same. The beat reads keys from a `chmod 600` `~/.config/ramabana/beat.env`, never from the launcher, and stops itself after `--limit` seconds so a hung run cannot block every schedule.

- Leela's agent has a `debugging` skill: find a failure's root cause from the raw error, treat a tool that contradicts what the agent has seen as a harness fault to report, and know where Ramabana keeps its config, run logs, beat launcher, scheduler entry and Dhrona's nightly summaries (ramabana 0.2.54).

- A Claude Code turn that sends nothing for 240 seconds is ended and tried once more, with a note that says so, instead of waiting 600 seconds and failing (ramabana 0.2.53, rishi 0.1.49). Text already shown is not repeated. Set the limit per model with `timeout` under `[model."NAME"]` in `~/.config/ramabana/config.toml`; a second silence fails with an error that names it.
- In Ramabana's terminal, `tab` after `@` completes files and folders, and `@folder` attaches the folder's listing (ramabana 0.2.53).

- Dhrona's nightly batch finds `claude` and `git-lfs` (ramabana 0.2.52). The beat `ramabana-tick --install` schedules ran on launchd's `/usr/bin:/bin`, so a round on Claude Code could not start and a repository using Git LFS could not be checked out. Run `ramabana-tick --install` again to take the fix.
- A `<parameter>` element a model leaves outside any tool call is stripped from the agent's reply instead of shown (ramabana 0.2.51, rishi 0.1.48, uraiyadal 0.0.15).

- A line sent to the agent while a tool result fills its size cap reaches the model (ramabana 0.2.50). The line rode at the end of the result and the backend cut it off unread. Ramabana sub-agents asked with `delegate_search(writes=False)` run at once, and `grep` with a folder as `path_filter` finds what is in it (shalya 0.1.17).
- Pictures `generate_image` draws without a `path` save under `media/` in the project's open folder (ramabana 0.2.49, shalya 0.1.16). They used to save under the process's working directory, which in Leela.app is `~/.local/share/leela`.
- No provider is chosen for you (ramabana 0.2.47, shalya 0.1.15). When the agent's model cannot run, for a missing runtime or a missing key, the agent pane lists the providers Ramabana can use, what each needs and which are set up, with a **+ model** button. **+ model** starts with a provider choice (OpenAI, Azure OpenAI, AWS Bedrock's Mantle endpoint, OpenRouter, Anthropic, Gemini, any OpenAI-compatible server) that fills the hosted API fields; the key stays in the environment. The first-run modal counts a configured hosted model whose key is set as set up. The env panel offers `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AWS_BEARER_TOKEN_BEDROCK` and `OPENROUTER_API_KEY`. Leela and `ramabana` read the same `~/.config/ramabana/config.toml`, so `[jobs]` and `[model."NAME"]` there reach the agent pane. The automatic move of a workspace's inline and completion defaults onto a configured model, from the previous change, is gone.
- `generate_video` runs on Ramabana's `video` job (ramabana 0.2.48) rather than on Gemini by name. `[jobs] video` in `~/.config/ramabana/config.toml` or `$LEELA_MODEL_VIDEO` names the model: Veo on Gemini by default, or `sora-2` on OpenAI or an Azure deployment. With no model that can run, the tool says which job to set and how, and calls no provider. A model that makes no video, such as `gemini-2.5-flash`, is refused. The Gemini key no longer follows the download's redirect to storage.
- The README installs Leela from this repository: `leela` on PyPI is an unrelated project. A Windows (WSL) section says to run Leela inside WSL, open its URL in a Windows browser, and export model keys in WSL.

- Learning can be turned off. The agent settings have a **learning** box, and `/learned on|off` in the agent pane is the same switch. Off, every live conversation is re-briefed at once without the learned folder, no lessons are kept and Dhrona proposes nothing new. The Review tab's Learned chip reads "Learned · off", and what waits there can still be accepted or rejected. The setting is ramabana's `learning`, kept in the agent's config folder's `settings.json` beside Leela's settings, which resetting Leela's settings keeps. A `settings.json` that is not valid JSON is refused rather than replaced.
- A turn too large for the model's window after compaction and trimming says so in plain words in the agent pane (ramabana 0.2.44's `ContextFull`), not as a raw `ValueError`. ramabana now trims the oldest tool results and then pictures before compacting, and keeps the window guard right after a compaction or a resume.
- A pasted or attached picture is logged as `[image]` in the conversation log, not as its bytes.
- A message too large for the model's window goes out as an excerpt rather than failing (ramabana 0.2.45). A huge paste, too many pictures or a giant tool result is cut to its head and its end, the whole kept in a file under the agent's run folder that the model is told to read in pieces. The plain-words failure is left for a briefing that alone overflows the window, and it says to start a new conversation with **+** in the agent panel, not to quit or run the `ramabana` command.
- The **learning** box and `/learned on|off` now set `learning` in ramabana's `~/.config/ramabana/config.toml`, one switch per machine, and never write Leela's `settings.json`. A choice made in `settings.json` under ramabana 0.2.44 is read and moved there the first time. A `config.toml` that is not valid TOML is refused with a message, never rewritten.

- Leela without Claude Code works. The default agent model, `claude-opus-5-5`, runs through Claude Code, and without `claude` on PATH building the assistant and opening the history failed. The agent panel now opens with a notice naming what is missing, how to install it, and a model that runs on this machine. A turn on that model fails with the same sentence, and the model picker marks it unavailable. Leela does not switch models by itself.
- **+ model** opens at once, whatever the model list does. It used to wait for `/agent/models`, the whole catalog and two machine-wide probes, and drew nothing at all if that request failed or never answered. The form now opens first with the hosted API runtime ready, so an OpenAI, Azure OpenAI or other OpenAI-compatible model can be saved without the list. A list that fails is named inside the form, a list that does not answer in 15 seconds says so, and a machine with no usable model reads "no model is set up here: add one". A refused save, remove or backend install now shows its reason in the form and the status line. Before, each was dropped without a word.
- `/agent/models` no longer answers 500. Every step is guarded, and a failure becomes a note or `ok: false` in the same shape, with the hosted runtime still offered. The answer also says whether any model is `ready`. A failed list keeps the agent pane's model pickers working over what they already hold, and the status line names the failure.
- The agent composer's **settings** popover fits the room above it and scrolls. In a short window, such as a Windows browser at 150% scaling, its top rows (the model choices) were above the screen.
- **Models and updates** has a **+ model** button, so a machine with no account set up can add a hosted model from there.
- In the Review tab's Learned queue, a candidate that no longer applies to the learned folder shows why on its row, and accepting it returns that reason word for word. After an accept, the status line says how many candidates moved onto it and which no longer apply.
- An accept refused because `AGENTS.md` would pass 2,000 characters stays on screen with a **Compact with this candidate** button. It asks Dhrona for a shorter `AGENTS.md` that includes the candidate, and accepting the result accepts the candidate too.

- A folder clip walks the folder with litesearch's `dir2files`, as vishalakshi's own folder reader does. It skips dot-folders (virtualenvs such as `.aeneas-venv` among them), `build`, `dist`, `node_modules`, `__pycache__` and `tests`, and dotfiles. It keeps `docs` and `examples`, which `dir2files` skips by default. A file named outright is clipped wherever it lives. A clip resumed from before this change drops the skipped files from its count.
- A folder clip can be cancelled from its job card. It keeps what it clipped, and resume clips the rest.
- A GitHub, arXiv, YouTube, web or crawl acquisition, and a grab of a web page, a folder or one of those, can be cancelled from its job card. It stops before the fetch or clone and between the pages, sources or batches it files; a fetch in flight finishes. What it filed is kept, its card counts what it did not file, and "run again" starts it over. Its progress shows on the card. A grab of a file, a PDF or a GitHub file, and a `pdf` acquisition, can be cancelled too; each stops before its read. A note and a harvest still cannot be cancelled.
- A clip hands its stop to vishalakshi, so a cancel that lands after a batch is handed over and before vishalakshi starts it files nothing more. A batch whose clip failed is listed as `failed`, not counted as clipped, and a retry clips it again.
- A clip files batches of 8, and vishalakshi asks for a cancel before each file of a batch, so a cancel lands after the file in flight. The files before it stay indexed and a resume skips them. A clip of 8 files or fewer was one batch and always finished `complete`.
- A cancel is stored in the job's row, in a new `cancel_at` column. A cancel from another workspace stops the clip, and a job cancelled before a quit stays cancelled at the next launch instead of resuming. A jobs file from an earlier build gains the column when it is opened, and a column from a later build is ignored. A build from before this change cannot read a jobs file this one has opened.
- Every `clip` and `clip_tree` job can be cancelled, including one started before `_cancel` existed.
- The Review tab has a fifth queue, **Learned**: what Dhrona proposes for the agent's learned folder, with its diff, accepted with `a` and rejected with `x`, and the agent's recent lessons read-only. Its chip counts what waits, and its head shows `AGENTS.md`'s size against the 2,000-character limit. The palette command "review what the agent learned" opens it. A refusal, such as a running Dhrona batch, uncommitted changes in the folder or a conflict, is shown as ramabana words it.
- A second Leela no longer fails, cancels or restarts a job the first one is running. A job row names its owning process and carries a heartbeat; opening a workspace recovers only a job whose process has gone or has not beaten for 2 minutes (`LEELA_JOB_STALE` seconds). A job taken over after a stale heartbeat stops in its old process, which can no longer write to its row. A jobs file from an earlier build gains the `owner` and `beat_at` columns when it is opened.
- Every running Leela sweeps the jobs file for orphans every minute (half of `LEELA_JOB_STALE`, or `LEELA_JOB_SWEEP` seconds; `0` turns it off). A job left by a crashed or force-quit Leela resumes, or fails if it cannot resume, without a workspace opening, and a job cancelled after its process died ends `cancelled`. Two Leelas sweeping at once take a job once. The sweep leaves a job this process runs, and a job kind it has no handler for, alone. It stops on quit and never runs in a pool worker.
- The Learned queue's head has a **Compact** button. It asks Dhrona for a shorter `AGENTS.md` (`ramabana.learned.compact`), which arrives in the queue as a new candidate and is selected. The model turn runs off the server's loop; the button reads "compacting…" until it ends, including in a tab opened meanwhile. A refusal, such as uncommitted changes or a compaction already pending, shows word for word.
- Compact asks the model the `summary` job routes to, in Leela's own process. It no longer runs a `ramabana` command, which the desktop app does not ship, so it no longer fails there with "the editor gave no answer". A model that cannot answer says why: no key, busy with another turn, or a window too small for the file.
- A folder import (`clip_tree` and its plan) walks the folder as a folder clip does: no `tests/`, hidden files, dot-folders, build output or symlinked folders. Both also leave out `venv` and `site-packages`, and the folders `LEELA_VAULT_SKIP` names, in any case. The plan no longer lists the paths it leaves out; it names the folders it skips.
- litesearch 0.1.45 starts no process pool for a batch of HTML files. litesearch 0.1.46 takes a `stop` in `add_dir`, asked before each file.
- CI: the fast tests resolve the default Claude Code model without `claude` installed, the checkout fetches full history, and the small-session refusal test no longer needs mlx. 41 tests failed on GitHub for these three reasons alone.
- CI runs the test job on macos-15 as well as Ubuntu, so the Cocoa shell, Apple Events and macOS priority-class tests run on every push and pull request. Tests that need a built `dist/Leela.app` still skip. The orphan-sweep test waits for sweep rounds instead of a fixed 300ms.
- The vault and search load on macOS 14. numkong 7.5 and later, which usearch needs, link `___sme_memset` from macOS 15 while their wheels claim macOS 11, so usearch does not import there. litesearch 0.1.48 and later search with numpy when usearch does not import, the desktop app included, and on a macos-14 runner Leela's fast suite then passes.
- Agent code search no longer hangs on litesearch 0.1.47 and 0.1.48. `_Serial` holds litesearch's `db_lock` around `Kosha.context`, whose repo and package legs run on worker threads, and in those releases the legs' first `get_index` waited on that lock. litesearch 0.1.49 loads indexes and usearch's SQL functions under a lock of its own.
- The app's `LSMinimumSystemVersion` is 14.0, the oldest macOS the suite has run on. It claimed 11.0, kavacha's default, and numpy's wheel in a bundle built on macOS 14 needs 14.
- A second launch attaches only to a Leela on the same config dir. `/hub/open` reports a hash of the config dir, and a Leela from an earlier build counts as the default `~/.config/leela`. The packaging tests launch the built app on a temporary `XDG_CONFIG_HOME`, and when the person's Leela was running it took the launch and the tests failed with "the app never began serving".
- Leela imports no private name from kunda, kavacha, fossick, rishi, pullup or dockeasy. The six kunda seams, fossick's `debug_ready`, pullup's `gheasy_core` and dockeasy's `FASTOPS_ENV` are public upstream.
- Three theme families: **github**, Primer's dark and light as on github.com, with GitHub's code colours in the editor, its green primary buttons and its orange active-tab underline; **ember**, a warm dim sepia; and **dusk**, a cool soft slate. Ember and dusk have no pure black or white and keep body text and code at 4.5:1 or better without glare. Each has a dark and a light variant, follows the system with "follow system", and is picked on the Appearance page of settings (`⌘,`, the palette's "settings", or the app menu).
- Ember and dusk draw code in palettes of their own, in the editor, in diffs and in Markdown code blocks. Ember's is warm and muted: terracotta keywords, sand functions, olive strings, sage types. Dusk's is cool and muted: slate-blue keywords, frost functions, sage strings, lilac numbers. Every code colour reaches 4.5:1 on the page and the panels in both variants, where diff and Markdown code in the light variants reached 3:1.
- A canvas tab follows the theme's dark or light variant, and repaints when the theme changes, including when the system's mode changes under "follow system". The tab used to send the theme as `[object Object]`, so a canvas was always light.
- The desktop window takes the theme's background. It opens on the saved theme's colour and changes with the theme, so opening or resizing a window no longer flashes kavacha's fixed dark grey.
- A theme cached by a newer build, or naming a family this build does not have, paints the default family on first load instead of an unstyled page. An unknown variant or density falls back the same way.
- A Local only document's title, headings and source do not reach a hosted model through the vault, and the vault's document list is gated the same way.

- Vault privacy (`vault_pii`) defaults to `redact`, not `off`. A hosted model gets a Personal vault document with its identifiers masked. A stored `off` is kept, and the settings pane labels it "as is (not recommended)". A workspace with no stored choice, or one this build does not know, gets `redact`.
- A model on this machine reads vault documents whole. `vault_pii` applies to hosted models only. A Local only document never goes to a hosted model, whatever `vault_pii` says.
- An @-attached vault document or section goes through vishalakshi's `send_check`. A Personal one is masked for a hosted model. A withheld one stops the turn before it starts.
- A file, picture, sound or selection attached by path takes the level of the vault document filed from that path. So does the open document's context. A picture, sound or PDF cannot be masked, so a hosted model gets it only when its document is Open or `vault_pii` is `off`.
- `/agent/turn` answers a withheld attachment with `{ok: false, error, kind, refs}`. `kind` is `local_only` or `pii_blocked`.
- The agent's file tools go through shalya's read guard. A vault source is sent whole, masked or refused for a hosted model by its document's level.
- `run_shell`, `run_shell_bg`, `run_python` and `inspect_python` refuse, for a hosted model, code or a command that names a vault source whose document may not go whole. The match is on the file name. A glob or a computed path is not caught.
- `/agent/vault-pii` refuses a request with no `pii`.

## 0.1.10

- The command line and macOS app default to port 5010. The desktop app tries ports 5010 through 5019 before requesting an operating-system-assigned port.
- Canvas component wiring defaults to port 5010. `BRICK_HOST` still overrides it.

## 0.1.9

Needs ramabana 0.2.6 (pinned); shalya, rishi, vishalakshi and dhrona as before.

- Cloud routing defaults: the turn is `claude-opus-5-5`, the small jobs (oneshot, classify, completion, inline, summary) `gpt-4.1`, sub-agents `claude-sonnet-5`. No local model is on a default or fallback route; without `OPENAI_API_KEY` the gpt-4.1 jobs use claude-sonnet-5 and the chat says so once. A local turn model keeps every job without a model of its own on the machine.
- A default Leela session is Opus, briefed in full; the small profile is for a local model you choose. A vault spec marked local-only is refused until one is.
- The agent panel and the model picker name ramabana's turn default before the assistant is built, not `gemma-e4b`. The inline model defaults to `gpt-4.1`, not `gpt-mini`.
- The picker's job rows apply saved per-job choices with `Routing.set`, so on a local turn a chosen sub-agent shows as chosen rather than as the local model.
- A sub-agent on the turn's own budget is not handed delegation, watches or the plan tools; ramabana 0.2.6 (`Agent.ROOT_ONLY`) enforces this on every path, not just Leela's own.
- The `--model` help and the settings pane's job help describe the new defaults.

## 0.1.8

- Needs ramabana 0.2.4 (pinned) and shalya 0.1.1: sub-agents can be handed pictures (`delegate_search(images=)`), `generate_image` can draw from reference pictures and save to a chosen path.
- `generate_image(path=...)` is a write in the agent pane too: approvals gate it in every mode (the repeat guard included), turn rollback removes the pictures it made (all of `n`) and refuses when one existed before or changed since, retry refuses it, and read-only copies are recorded.
- `create_file` no longer overwrites a picture with text; `memory_search` returns rows again.

## 0.1.7

Needs ramabana 0.2.3 (pinned) and rishi 0.1.39; shalya, vishalakshi and dhrona as before.

- Small profile for local models: ramabana's `auto` briefs a local runtime, or a window of 32k or under, with the small profile: fourteen tools (read, edit, search, run, `git_status`/`git_diff`/`git_commit`, the notebook four) and a briefing of one screen, warm start off. The default turn model is `gemma-e4b`, so a default Leela session is small: 14 tools plus Leela's `run_cell` (15 briefed, about 1.9k characters) against 52 tools and about 10.7k characters in full. `user_steering` stays dispatchable in every profile, so a refused call still resolves as steering. Canvas tools appear while a canvas is open and news tools while a feed is followed, in the small profile too; the small briefing names the open canvas in one line and clips the state and note blocks to 2k characters each. Video tools are full-profile only.
- Choosing the profile: **full** beside **warm** briefs the next new conversation in full whatever the model (`/agent/thread/new` takes `profile`); the settings pane's **briefing** select is the workspace default (`agent_profile`, `/agent/profile`). A conversation's row wears `·small`, and picking a model reports `… · small profile` or `… · full profile`. A conversation's own profile outlives its eviction the way its opt-ins do (`thread_profiles`): resuming it brings the same catalog back.
- rishi 0.1.39 serialises chats that share a LiteRT engine (`engine_lock`) and raises `EngineBusy` if a second chat steps onto the engine from the thread already mid-turn on it -- the gemma-12b `DEADLINE_EXCEEDED … Failed to lock custom tensor buffer` and empty turns. Leela has no such path: the lent chat `ask_memory` builds runs inside a tool call, where the handler has let the engine go, and every other one-shot runs from another thread or between sends. `tests/test_engine_broker.py` pins the contract.
- `gemma-12b` is a 16k window now.

## 0.1.6

Same pins as 0.1.5.

- Run a `.py` app, stop it, run it again: the terminal shows the new run. A run ends its viewers' queues when its stream ends, `/run/ws` sends `{"t": "exit"}` the way `/term/ws` does, and the run terminal is replaced when the same path comes back under another pid.
- A run keeps every `http://` URL it printed (`urls` in `/dev/list`), and a stopped run still reports the last one (`last_url`).
- Reopening the page brings the running servers back: the first `/dev/list` poll adopts each into its run terminal, and the runs menu lists every URL a running app printed as an **open** row.
- `Memory._store` opens a shelf under a lock. The poll tick and a request opening the same shelf at once built two Vaults over one file and crashed the test worker with a bus error.
- CI: the test job sets a git identity, has `timeout-minutes: 45`, and the two tests that resolve a Claude Code model skip where `claude` is not installed. The Windows desktop job is `continue-on-error` until pyghostty ships a Windows wheel; macOS is the release.

## 0.1.5

Needs ramabana 0.2.2 (pinned), shalya 0.1.0, vishalakshi 0.1.17, dhrona 0.1.4, rishi 0.1.38.

- The tool set is shalya 0.1.0's: `replace_text(path, edits)` and `edit_cell(path, cell_id, edits)` take a list of `{oldText, newText}` (a JSON string still parses this release), `ls` lists files, `inspect_python('')` reads the live namespace, `remember(key=)` upserts a note, and one `watch(kind='url'|'remind'|'search'|'folder')` replaces the watch, reminder and folder-watch tools. `edit_file` (hash-addressed edits) and `research` are opt-ins.
- Leela's own `inspect_var`, `search_all` and `api_access` are gone: `inspect_python`, `search_code` and the API paragraph of the briefing carry what they did. `user_steering` is dispatchable after a refused call and never offered, briefed, or shown in a form.
- The default workspace briefs 42 tools without a video key, 45 with one (was 77 of a backend list of 81); a sub-agent gets 42 (was 70). Canvas tools appear only while a canvas is open (+8) and news tools only while the workspace follows a feed (+6); the live backend is re-briefed at the next turn when either changes, and only then.
- Opt-ins per conversation: **research** and **exhash** toggles beside **warm** give the next new conversation shalya's slow `research` tool or `edit_file` plus the exhash skill; the settings pane holds the workspace default (`agent_optin`), and a browser's own toggle overrides it. A conversation's opt-ins survive eviction and resume, and its row wears them like `·warm`.
- Warm starts are ramabana's `Agent(warm=)`. The pane's toggle, the transcript block (with each replayed message) and assess / capture / accept are unchanged; a cold or resumed conversation gets no seeds. ramabana seeds only a model whose window admits inlined skills, so a small local model (about 24k context or less) starts cold with a note.
- Checkpoint forms edit list arguments (`edits`, `commands`, `items`, `questions`) as JSON with the error on the field; previews diff `edits` for `replace_text` and, per cell, `edit_cell`; activity rows print list arguments; Undo covers `replace_text` and `edit_cell`.
- Git in the agent pane: `git_commit`, `git_checkout`, `git_stash` and `git_remote` are briefed and go through the same approval as any write; `run_shell` refuses `git commit|push|pull|fetch|stash|switch|checkout` and names the tool. The turn card shows the git writes with their undo tokens, and **Restore files** undoes them first, then the files — refusing, and touching nothing, when HEAD or the branch moved after the turn or a file changed since. A partial undo says what it undid.
- The approval queue carries ramabana's repeat guard: the third identical gated call in a row is put to the person whatever the mode or run policy, and a read between neither counts nor resets. A folder watch opened by `watch(kind='folder')` reaches the harness's monitors.
- `ask_memory` picks its own policy (local when a local runtime exists, else redact); the vault PII setting governs retrieval only. The host remembers by `key`, answers `exists`, and `delete`s only inside the writable roots.
- `leela.agent` is one module: `leela.agent.X` is `ramabana.X`, aliased in `__init__`.
- The exhash skill is inlined only when it is discoverable on the machine (a skills directory holding it) and `edit_file` is offered.
- Tests: `pytest-timeout` bounds every test (300 s) and approvals default to a 2 s wait under pytest. `tests/fakemodel.py` gains `WIDE`, a 128k scripted window.

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
