# Regressions

Faults that the code still guards against, kept here rather than in the source. Each entry names the file and the symbol the fault lived in, what went wrong, and what fixed it. Reading the entry for a symbol before rewriting it keeps the fix in place.

## `leela/app.py` `safe_async_iterate`
`@asynccontextmanager` built the helper as a generator. That generator misses its `GeneratorExit` under the loop's asyncgen shutdown. `contextlib` reported `generator didn't stop after athrow()`. Every open stream produced the warning again on shutdown. Fixed by writing the helper as a class. Its `__aexit__` receives which case it is.

## `leela/app.py` `serve_ide`
Naming folders on the command line skipped the saved session. `leela .` always opened with no tabs. Fixed by calling `reopen_saved_tabs` whenever the launch produced no tabs of its own.

## `leela/app.py` `serve_ide`
`serve_ide` applied the kernel ceiling only under `--app`. A browser launch and a hub launch ran without one. Fixed by constructing the `RuntimeBroker` for every kind of launch.

## `leela/workspace.py` `rebind_journal`
`__init__` computed the journal key once. A workspace that started with no folders kept the no-folder key after someone opened a folder. Every project a desktop launch touched wrote into that one journal file. The file reached gigabytes. Fixed by rebinding the journal and the history whenever the open folders change.

## `leela/workspace.py` `kernel_options`
`default_python` is one interpreter for the whole workspace. It comes from the folder opened first. A notebook in a second repo inherited the first repo's interpreter and ran under the wrong one.

## `leela/workspace.py` `restore_settings`
Naming a folder on the command line carried over three model names and dropped the rest. That dropped a per-job model chosen the day before. Fixed by restoring every saved setting that is not a folder or a tab.

## `leela/core/backups.py` module
Five uncompressed copies of everything came to a third of a gigabyte. Keeping many of those costs too much disk. Fixed by gzipping each archive and letting a person choose which entries go in.

## `leela/core/backups.py` `PRECIOUS`
A day of saving one large notebook made `journals` the biggest entry in every archive. `journals` holds undo state for files still on disk. The default set no longer includes it. `ENTRIES` still offers it.

## `leela/core/backups.py` `AGENT_ENTRIES`
`agent.configFolder` moved the agent's files out of Leela's config dir. The backup kept copying the old location. It protected an empty log. Fixed by resolving the agent's source directory from `agent.configFolder`.

## `leela/core/backups.py` `guard`
Only the scheduled copy covered a bad write to the conversation log. The next scheduled copy was hours away. Fixed by taking a guard copy on the write itself, kept apart from the cadence.

## `leela/core/session.py` `MAX_BODY`
A 70MB notebook saved through a day produced gigabytes of version history. Git already tracks that file. Making those copies is what made saving slow. Fixed by noting bodies past `MAX_BODY` without copying them.

## `leela/core/session.py` `OperationJournal.record`
`record` stored bodies inline in the journal file. Every operation reloads and rewrites that file. One 70MB notebook saved through a day grew it to gigabytes. Fixed by moving bodies into the history's blob store.

## `leela/blocks/tabs/app.py` `_held`
Stamping the cached copy with the version now on disk lost writes. The browser returned that version as its base. `/nb/save` found base equal to disk. It wrote the old content over the new. Fixed by reporting the version the copy was read at.

## `leela/blocks/nb/cells.js` `focusCell`
Run-and-advance moved the caret below the viewport. CodeMirror focused its own scroller. It could not reveal itself inside the notebook's outer scroller. Fixed by scrolling the cell element into view before focusing.

## `leela/blocks/fs/files.js` `noteSelfWrite` and the tree push
An agent edit, a terminal command or another editor stayed invisible in the file tree until someone refreshed it. Fixed by pushing the folders that changed instead of polling.

## `leela/blocks/fs/files.js` `addRoot`
The folder picker was a path bar, a separate filter box, a list and an up button. Only the path bar took a path. Replaced by one box that completes folders under what is already typed.

## `leela/blocks/fs/files.js` `addRoot`
Activating a newly added root selected a node the tree did not have yet. The folder stayed open on the server and absent from the panel until reload. Fixed by redrawing the tree before activating the folder.

## `leela/blocks/editor/tabs.js` `updateToolbarForKind`
The toolbar offered `stop` on a document tab. A document tab has no kernel to interrupt.

## `leela/blocks/editor/tabs.js` `saveTabLocation`
A Map keeps a re-set key at its first insertion point. The tail slice persisted the eighty oldest files ever opened. It dropped the recent ones. Fixed by deleting the key before setting it.

## `leela/blocks/editor/tabs.js` PDF tab
`/file/raw?path=…` titled every document "raw". The browser's own viewer takes its title from the last path segment. Fixed by putting the filename in the path as well as the query. The server still resolves the file from `path` alone.

## `leela/blocks/git/branchbar.js` branch modal `paint`
Expanding a folder in the branch list threw the modal back to the top. Replacing the children of a scrolled element puts it at scrollTop 0. Opening `remote/` half way down scrolled away from the row just clicked. Fixed by restoring the old offset on a fold.

## `leela/blocks/git/state.js` `gitDo`
Reporting only how long an operation took hid what it left behind. An index full of someone else's changes looked like a bug in Leela. A squash that staged twelve files and a merge that stopped at a conflict both reported "complete". Fixed by reporting the outcome summary instead.

## `leela/blocks/git/state.js` `gitDo`
When Git refused a switch, the status line kept saying "git checkout…" for ever. The refusal looked identical to a hang. Fixed by reporting the failure. Reporting it clears the running status.

## `leela/blocks/git/cwd.js` `gitSignature`
Source Control did not refresh until the user refreshed it. Typing in an already modified file moved no count. A signature built from counts alone never moved. The panel went on showing the stats it drew when the file first changed. Fixed by putting each changed file's status codes and line counts in the signature.

## `leela/blocks/git/cwd.js` folder change
After choosing another folder the open panel kept describing the folder left behind. A branch change was the only event that reloaded drive and workflow answers.

## `leela/blocks/editor/markdown.js` file open
A refusal from `/tab/open` came back as "no tab bar". That threw away the only sentence that said what was wrong. Fixed by reading the reason out of the response body.

## `leela/blocks/editor/split.js` panel restore
Reload restored only two panels. It moved the user back to the file tree from the panel they were working in, without saying so.

## `leela/blocks/editor/split.js` dock height limit
A dock ceiling of 360px made Agent and Terminal read as preview strips on large displays. The raised ceiling lets the dock occupy most of the workspace. The editor keeps its own 140px floor.

## `leela/blocks/git/panel.js` merge action
A disabled merge button had no way to state its reason. The report that came back was "I clicked merge and nothing happened". Fixed by always enabling the button and answering with the reason.

## `leela/blocks/nb/motion.js` notebook remount
Replacing a mounted cell object wholesale let stale buffer state win on a later remount. The cell showed blank. Fixed by preserving the cell object and its editor relationship.

## `leela/blocks/editor/app.py` `/editor/format`
The first open root's venv formatted files belonging to any of the other open roots. Fixed by resolving the interpreter from the folder the file is in.

## `leela/blocks/editor/app.py` `/editor/packages`
One interpreter for the whole workspace annotated a second checkout's `pyproject.toml` with the first checkout's installed versions. Fixed by resolving the interpreter from the pyproject's own folder.

## `leela/blocks/agent/ai.py` `WorkspaceHost.capabilities`
Probing a workspace for a session raised `NotImplementedError` when no kernel had started yet. The harness then dropped `run_python` for the life of that assistant. Fixed by declaring `session` in `capabilities` and letting `_kernel` start one on demand.

## `leela/blocks/agent/ai.py` `WorkspaceHost.check`
The `Unsafe` hint named the open tabs rather than the open roots. People went looking for a path bug in a file they could already see listed. Fixed by naming the open folders. The gate is the open folders.

## `leela/blocks/agent/ai.py` `run_python`
`scope: 'global'` executed straight into the user's globals. `del mine` and `mine = ...` both went through. The agent destroyed the user's own bindings. Fixed by running in an overlay layer. The overlay reads the user's variables and blocks a mutation of anything they own.

## `leela/blocks/agent/ai.py` `Assistant._steered`
`_steered` appended a queued steer to the next tool result only. A steer queued while the model was writing its answer waited for a tool call that never came. It never reached the model. Fixed by folding an unconsumed steer into the next text prompt.

## `leela/blocks/agent/ai.py` `Assistant._sub_plain`
Filtering `_plain` alone missed two branches. `registry.tools` built a sub-agent sized to a different model. The recorded wrappers went to a sub-agent allowed to write. Both sub-agents held `git_push`. Fixed by refusing the Git write tools in `_sub_plain`, whichever list upstream hands back.

## `leela/blocks/vault/spec.py` `_policy`
Older spec files hold a flat list of header names rather than a policy. The docstring described that form as the one the format used to have. The reader handles both forms. The docstring now names both without dating either.

## `leela/blocks/agent/approvals.js` `markTurnUndone`
Rolling a turn back deleted its transcript. The gap said the agent had forgotten a turn it still carries in model history. `rollback_turn` restores files only. Fixed by marking the turn undone and leaving the transcript on screen.

## `leela/blocks/agent/approvals.js` `restoreTurnFiles`
A file reload that raised after the rollback left the reply standing as though nothing had happened. Fixed by marking the turn undone before reloading the files.

## `leela/blocks/agent/approvals.js` `bindResponseRevisions`
Per-button listeners in the agent log did not survive a repaint. The log replaces its contents constantly. Fixed by binding one listener on the log element itself.

## `leela/blocks/agent/live.js` `sessionTurns`
`/agent/history` returned every conversation with its turns. Once Leela and the ramabana CLI shared one log that came to 60MB of JSON and forty seconds. Fixed by listing conversations without their turns. `/agent/history/session` fetches the turns of the conversation being opened.

## `leela/blocks/agent/live.js` `rehydrateAgentLive`
A fresh process carried the last conversation into the pane. The pane opened on work a person had moved on from. Those turns were not in the model's context either way. Fixed by starting on an empty conversation. History picks a past one up.

## `leela/blocks/agent/steer.js` `steerHost`
A steer appended to the agent log sat below every chunk and tool row that followed it. It read as a note stuck to the bottom rather than something said during the turn. Fixed by placing it in the turn's own timeline.

## `leela/blocks/agent/steer.js` `chooseAgentSuggest`
Choosing an `@` file removed the typed token. The sentence read "look at and tell me why", with the file named only by a chip. The typed token is the reference. The chip is that reference resolved. Fixed by keeping the token in the prompt.

## `leela/blocks/agent/steer.js` `initAgentComposer`
The agent prompt is a single line outside any form. It has no default action. Enter did nothing. Steering read as broken rather than as never sent. Fixed by binding Enter on the box.

## `leela/blocks/search/search.js` `codeSearch`
A result row selected on the first click. Opening it took a second click on the same row. One click showed a preview only. The result looked unclickable. Fixed by opening at the line on one click. Arrow keys still preview without committing.

## `leela/blocks/agent/approvals.js` `addResponseRevision`
The history toggle, a rehydrate, a resume and every thread switch round-trip the agent pane through `innerHTML`. The revision buttons' bound listeners did not survive that. The buttons went dead. Fixed by writing the turn identifier into the DOM and dispatching from one delegated listener on the log.

## `leela/blocks/runs/runfile.js` `runFile`
Running the open `.py` inside the tab's kernel held that kernel whenever the file was a server that never returned. Nothing appeared on screen until someone killed the process. The app's output went to whichever terminal started leela. Fixed by running the file in its own process on the project's interpreter. A terminal in the IDE shows it.

## `leela/blocks/runs/logs.js` `pollRuns`
`pollRuns` read health from the inspector's `alive` flag. The child keeps the inspector up after the command returns. A run that died on its first line reported as fine for as long as leela stayed open. Fixed by reading `running` instead.

## `leela/blocks/settings/prefs.js` `editorSettings`
Defaulting the settings modal's language scope from `curLang()` scoped every save into `languages.<lang>`. Saving also remembers the chosen scope. One visit with a `.py` file focused sent all later edits there too. Global preferences looked as though they reverted on every restart. Fixed by defaulting to All languages. A language scope now takes effect only when someone chooses it.

## `leela/blocks/term/terminal.js` `nextTermId`
The terminal counter restarted at zero on reload. The server still held the ptys from before the reload. `nextTermId` handed out `term-1` again. `terms.open` found a live pty under that key. A new terminal came up showing an old session's scrollback with its process still running. Fixed by skipping every identifier in the set the server reports as taken.

## `leela/blocks/term/terminal.js` `paintTermTabs`
The single close control lived in the terminal header. It always shut the active terminal. Closing a background terminal meant selecting it first. Fixed by giving each tab its own close control.

## `leela/blocks/vars/vars.js` `leeVars`
The 2.5s variable poll started a fetch whether or not the previous one had returned. A slow inspector let those fetches and their full-tree DOM rebuilds stack without bound. Chrome declared the page unresponsive. Fixed by coalescing every request that arrives while one is in flight.

## `leela/static/js/core.js` `lee.locations`
`lee.locations` kept caret positions in `sessionStorage`. That store dies with the window. Every reopened tab came back at line 1. Fixed by reading and writing them in `localStorage`.

## `leela/static/js/core.js` `markdownCellActionState`
The copy-into-notebook action on a reply stayed on offer while a `.py` tab was focused. The control was always present and inert. It said so only after a click. Fixed by hiding it unless a notebook tab is focused.

## `leela/blocks/browser/app.py` `browser_ws`
Chrome died between the cast starting and `browser_ws` taking the CDP handles. That left a cast nobody stopped and a socket nobody closed. Fixed by guarding that window and tearing both down on the way out.

## `leela/blocks/workflows/workflows.js` `wfRemoteMark`
`refresh` fetched what GitHub had. Nothing rendered it. The answer went nowhere.

## `leela/blocks/workspace/projects.js` `openFolder`
Opening a recent folder someone had renamed or deleted failed without a message. htmx does not swap a 4xx. `htmx.ajax` resolves anyway. The screen kept saying "opening…". Fixed by reading the refusal off the event.

## `leela/static/js/overlays.js` `activateRoot`
Selecting a folder in the tree did not activate it as the project. Source control, releases, deploys and the branch pill went on describing whichever folder opened first. Fixed by a route that activates the folder and repoints all four.

## `leela/__init__.py` `use_utf8`
launchd hands a windowed app no `LANG`. The C locale was `POSIX`, `open()` defaulted to ASCII, and `import rishi.claude` raised `UnicodeDecodeError` on the first UTF-8 byte it read. The pane reported Claude Code as not installed, which sent everyone after the binary and the PATH. A second call reported `fastllm.acomplete has no attribute gem_spec`, because a failed import leaves its half-built module in `sys.modules`. Fixed by setting `LC_CTYPE`, and `LSEnvironment` in the plist for the case that starts before any Python runs.

## `leela/__init__.py` `use_login_path`
Finder and the Dock start an app with almost nothing on `PATH`. `git` was off it, so the git panel reported no repository, and `git-lfs` with it. `/git/info` was answering its own error through `fail`, which is a 400 with the message in the body, so the route looked broken instead. Fixed by asking the login shell for its PATH.

## `leela/desktop.py` `OpenHandler`
An Objective-C subclass used `super().init()`, which has no `init` to find. Registration raised on every launch and nothing opened a folder dropped on the Dock or chosen through Open With. Fixed with `objc.super`.

## `leela/desktop.py` `dock_delegates`
Building the delegate subclasses twice raised `overriding existing Objective-C class`, because a class name is global to the runtime. The caller caught it, printed a warning and reported success, so quit-on-close came back silently. Fixed by building them once and reading module state.

## `leela/desktop.py` `dock_menu`
`recent_folders` returns paths. They were indexed as dicts, which raised, and `applicationDockMenu_` caught it and returned no menu, so the Dock menu never appeared at all. The test covering it passed rows of an invented shape and confirmed the assumption. Fixed by taking paths, and by driving `recent_folders` from the test.

## `leela_app.py` `run`
A launch with no arguments reopened every folder the session remembered, and the app makes one window per folder, so quitting with four open and launching again gave all four back. Fixed by reopening the last of the open set. `note_folder` fronts an already-open folder in `recent` and leaves its place in the open set, which is why the open set answers this and `recent` does not.

## `leela/core/keys.py` `notebook_undo`
Undoing a cell deletion was bound to `mod+alt+z` and nobody found it, so the key everyone presses did nothing outside a cell's own text. Fixed by moving it to `mod+z`, with the router declining that chord while the caret is in a document, since CodeMirror's history is not reachable from there.

## `packaging/macos/setup.py` `PACKAGES`
pygments finds a style or a lexer by importing its name, and no scanner sees those, so the bundle got `pygments/styles/__init__` and none of the styles. `import IPython` then died inside the kernel process, the gateway waited for a kernel that was already gone, and every cell failed on a read timeout naming nothing. The launch test asked for the page and stopped, and a page only proves the server imports. Fixed by copying pygments whole and by running a cell in that test.

## `tools/build_release.py` `sign`
Signing used `--deep`, which signs nested code with the outer bundle's own arguments and skips what it does not recognise. The notary service rejects the result. Fixed by walking inner code deepest-first with a timestamp and the hardened runtime, then the bundle.


## `leela/blocks/agent/panel.js` `renderSetup`
`leeSetupModal` called `modal('')` and then handed the returned element to `renderSetup`, which assigned its `innerHTML`. The returned element is the backdrop, so that assignment discarded the `.lee-modalbox` `modal()` had built, and with it every style, the drag grip, the expand control and the close button. The two panes, Tools and Updates lay transparent over the editor text. Fixed by giving the box a `.lee-setup-body` region and rewriting only that, so a re-render leaves the chrome alone. `done` now closes through `modal()`'s own teardown instead of removing the backdrop, which had left the key handler and the body's `overflow: hidden` behind.

## `leela/static/lee-ide.css` `.lee-setup-pane`
The pane border named `var(--lee-bd)`, which nothing defines. An unresolved custom property invalidates the whole `border` shorthand, so the panes drew no edge. `--lee-bd` appeared once in the file and nowhere else. Fixed by naming `--lee-border`. `--lee-fg3` was undefined the same way in 19 rules, all of them secondary labels, counts and snippets that silently inherited their colour. It is now derived once from `--lee-fg2` and `--lee-fg4` rather than added as a 25th token to all 16 theme variants, since it is a rung between two that every variant already sets. `--lee-err` and `--lee-rule` each had one use and a fallback, so they drew the fallback rather than the theme's colour; they now name `--lee-red` and `--lee-border`. `--lee-tab-size` and `--lee-indent-cols` look undefined but are written onto each indented line by `frontend/editor.js`.

## `leela/app.py` `_agent_panel`, `leela/blocks/agent/panel.js` `paintJobModels`
`.lee-routing-popover label` is a two-column grid: an 82px name, then the control. A row carrying a `?` passed three children, so the mark landed in the control's column and the select wrapped onto a second row into the name column, where every model name was clipped to about six characters and the right half of the popover stayed empty. Fixed by wrapping the name and its mark in one `.lee-routing-name` item, in both the server-rendered rows and the ones `paintJobModels` draws. A row without a mark was never affected, which is why `compaction` and `tool calls per turn` looked right beside them.

## `leela/workspace.py` `initialize_notebook`
A zero-byte `.ipynb` was made valid by writing a fresh `Notebook.blank`, whose cell carries a new id. The browser and the doc store still held the old one, so `_rebase_notebook` could not match a single cell, returned None, and the save was refused as a conflict that blamed another process. The symptom was running cells in a new notebook and getting `save the notebook before running this cell` partway through, because each run marks the tab dirty and the next cell's guard saves first. Fixed by writing the document already open on that path, so the ids the browser knows survive. `/nb/run/stream` passes the notebook it is about to run.

## `leela/workspace.py` `initialize_empty_notebooks`
A whole-tree walk ran on every cell of every streamed run, to catch a placeholder only another tool can leave: notebooks Leela creates are valid JSON when created. Now once per root, with the notebook actually being run handled by a single stat in `initialize_notebook`. `off_loop` is `@athreaded`, so the walk was never on the event loop, which is why this cost a run's latency rather than the whole server's.

## `leela/blocks/nb/motion.js` `runCell`
The guard that saves before running reported `save the notebook before running this cell` whenever `saveTab` returned false. `saveTab` had already put the real reason in the status line or opened the conflict dialog, and this wrote over it, leaving advice to do the thing that had just failed. It now returns and leaves the reason standing.

## `frontend/editor.js` `overviewPlugin.draw`
`shown` compared `scrollHeight` with `clientHeight`, and the class it then sets, `has-overview`, is what hides a native scroll bar. `clientHeight` excludes a horizontal bar, so hiding one grows it by that bar's thickness: a pane overflowing by less than a bar said it overflowed, took the class, grew, and said it did not on the next frame. The stripe's own `ResizeObserver` fed each toggle straight back in. Code cells are where it bit, because long lines give them the horizontal bar, and an agent pane streaming tokens re-measures every frame. Fixed with `overflowsDown`, which measures against the border box: a bar drawn inside it does not move it, so the answer no longer depends on the answer.

## `frontend/editor.js` `scrollerFor`
The walk up from the editor could reach `<body>` and return it. In the desktop app the window fits and the document does not overflow, so it never did; in a browser it does, and `has-overview` on `<body>` matches no rule, so the bar it was meant to hide stayed. That is why this read as fixed in the app and broken on the web. The walk now ends at `document.body` without answering with it.

## `tests/blocks/test_ide_bundle.py` `test_the_built_editor_bundle_matches_its_source`
The export check was anchored on `CS(`, a name the minifier chose, so it broke on the next rebuild of an unrelated part of `frontend/editor.js` and read as a missing export. It now looks for the exported names themselves.

## `tools/build_icons.py` `SHEET`, `mark`, `favicon`
One mark on one plate could not answer a tab strip whose colour the browser picks. The artwork is now one sheet of four, `packaging/assets/leela-logo.png`: the mark plated and bare, in dark ink on paper and in white ink on charcoal. `mark` cuts a bare quadrant, keys out the paper and trims to the ink, so nothing but the stroke reaches the plate the builder draws. Two favicons are generated and served under `prefers-color-scheme`; the app icon is the white ink on the charcoal plate, which is the plated quadrant of the design. The cutoff comes from the quadrant's own corners: the paper is not pure white and the charcoal is not pure black, and a fixed threshold left the whole dark quadrant faintly opaque, so the trim found nothing to trim. Every earlier source is gone, so there is one copy of the artwork and no second to disagree with it.

## `leela/core/session.py` `Trash`, `OperationJournal.record`
A journal resource was text, and neither a directory nor a binary survives being one. A folder delete recorded nothing at all, because `before` was only read for a file and the row was conditional on it, so a recursive tree removal left no row, no version and no undo. A binary was recorded with `errors='replace'`, so undoing a deleted PNG rewrote it as replacement characters, and undoing a renamed one wrote mojibake to the old path and unlinked the good file at the new one, leaving no intact copy. Fixed with three path-level row kinds beside the content one: `moved` for a rename or a move, and `at: trash`/`at: tree` for a delete and a create, which are the same row read from opposite ends. `Trash` holds what was deleted whole, so it costs a rename rather than a copy.

## `leela/blocks/fs/app.py` `fs_rename`, `fs_delete`
Neither route invalidated the document cache or fixed up open tabs. `/tab/state` prefers a cached buffer to the disk, so deleting a file and creating another at the same path served the deleted text and saving put it back. A renamed file left its tab on the old path, so the next save saw a `missing` disk version and the conflict dialog offered to force it through, recreating the file under the name it was renamed away from. The delete closed tabs by exact path, so a folder delete closed none of the tabs inside it while the index-addressed tab strip went stale behind it. `_forget` and `_closed` now do both, and `Workspace.retarget` moves a tab with its file.

## `leela/blocks/fs/files.js` `treePaths`, `leeTreeClick`
The tree had no multi-select and no move, copy, paste or duplicate: `selectTreeNode` cleared every `.sel` before setting one, no handler read a modifier, and `Sandbox.move` had no caller anywhere. Marks are now explicit and separate from the caret, which is what `treePaths` falls back to. A file row's own click handler stops propagation, so the modifier readings had to move into it: `leeTreeClick` is where a meta-click marks instead of opening. A meta-click never folds the caret in, because whichever row was highlighted on load would join a cut or a delete nobody chose it for.

## `leela/blocks/git/panel.js` `wireGitPanel`
The commit textarea was rendered with no value and the panel replaces its own `innerHTML` on every save anywhere in the repository, so a message being typed vanished on an autosave in an unrelated file. The draft is now `gitUI.commitDraft`, the way the branch filter already kept its query. The panel also kept selection keys for files that had moved between groups or been committed, so a bulk action posted paths that were no longer in the list it was made against; the keys are pruned against each snapshot.

## `leela/blocks/git/app.py` `_dropped`
`GitRepo.delete` and `stash_drop` return None, so `Deleted branch x (was abc1234)` never reached the panel, and that sha is the only handle for putting the branch back. Both now read the tip first, because afterwards there is no ref left to ask, and return the `git branch` or `git stash store` command that recovers it. `gitDo` puts it in the log, since a status line is gone in seconds. The branch pill also turned every unmerged delete into `git branch -D` behind one confirmation while the panel's menu sent no force at all; forcing is now a second, named ask in both.

## `leela/blocks/lsp/lsp.py` `find_server`
The Tools row installs into `extras_site`, because the bundle is signed and read-only, and `find_server` looked only on PATH. In a packaged app the language server installed correctly and was then found by nothing, so the row went on offering to install it. It now looks in `extras_bin()` too, which is where `pip install --target` puts a console script.

## `leela/blocks/agent/panel.js` setup rows
The rows were `.lee-krow`, the keyboard-help row: a flex line with `nowrap` and an ellipsis on every span, so `ready` rendered as `rea…` and every blurb was cut mid-sentence. `.lee-setup-row` is a grid of a name and a state with the sentence under them. The modal also had no way back once dismissed, and `/agent/setup/dismiss` already took a false, so `start over` puts the first-run prompt back.

## `leela/blocks/agent/app.py` `agent_history`
Opening the history list took 2.6 seconds. Almost none of it was the history: `api()` reaches for `ws.runtime()`, which **starts a kernel**, and a cold one is 1.2 seconds. Listing what has been said booted Python to decorate the answer with kernel run counts. `api_peek` asks the runtime only where one is already up. The list is also Leela's own conversations now, with `everything=1` for the ones the CLI started: one log holds both, most of it is the CLI's, and grouping all 138 so the browser could filter them to 3 was the wrong end to do it at. The client's "Leela only" box is checked unless it has been turned off, and toggling it re-asks rather than filtering a list the server never sent.

## `leela/blocks/agent/models.py` `probed`
`/agent/models` cost 6.8 seconds cold and is on the boot path. `available_models` reaches for every backend (3.7s) and `auth_status` asks every account (1.4s), and both answers barely move. They are served from the last probe and refreshed on a thread behind whoever asked; `ide_app` warms them at startup, so the window is still opening while the first one is paid for. The route also resolved every row's spec several times over in one request, once for the dedupe and again for `selected`. With the probes warm it is now about 0.5s.

## `leela/blocks/editor/split.js` `initSplits`
A splitter drag wrote `localStorage` on every pointer event, twice: the width, and a migration of the previous name for it. It is synchronous and disk-backed, which is the difference between a smooth drag and a stuttering one in a WKWebView. The width a person let go at is the only one worth keeping, so both are written on release. The overview stripe was also redrawing every mounted editor's canvas on every one of those resizes; resize-driven redraws settle at 90ms now, while a scroll still draws on the next frame, because there the stripe is the thumb.

## `leela/blocks/agent/live.js` `rehydrateAgentLive`
Conversations live in the agent's log, not in the process, so a fresh one holds none and the pane opened blank while the work sat on disk. Opening the app after working in a browser looked like the chats had been lost. An empty pane picks the newest conversation back up. The first read of that log is seconds on a large one and cached after, so it is warmed at idle once the page is interactive rather than on the first click.

## `leela/blocks/runtime/app.py` `k_info`, `leela/blocks/vars/app.py` `vars_route`
Opening Leela started a Python kernel whether or not anybody ran anything. The kernel pill asked `session.runtime()`, which creates one, and so did the variable list, which polls every 2.5 seconds from load. That was 1.4 seconds on the load path and a process nobody asked for. Both peek now: the pill has always drawn an empty circle for "no kernel" and an empty variable list is what no kernel means. Running a cell is what starts one. Neither can reach the kernel ceiling any more, so neither is in the set of requests that report it.

## `leela/blocks/runtime/app.py` `runtime_info`
`kernel_support` interrogates the project's interpreter, about half a second, and it ran again on every poll with no caching. It is the machine's answer about one path, so it is probed per interpreter: 433ms cold, 1ms after.

## `leela/static/lee-ide.css` `.has-overview`
The rule that hides a native scroll bar was `.lee-editor.has-overview`, but `scrollerFor` puts the class on whatever element really scrolls, which is not always `.lee-editor`: a markdown preview scrolls itself. Where the class landed anywhere else it hid nothing, so the stripe was drawn over a bar that stayed. The rule follows the class now. `overflowsDown` also takes hysteresis, 24px to appear and 8px to disappear, because rendered markdown settles over several frames and content within a few pixels of the threshold flipped with it; `.lee-md-preview` reserves its gutter so an appearing bar cannot rewrap the text that decides whether it is needed. Not reproduced: a browser test rendering markdown into a scrolling pane passed with and without these, in Chromium.

## `leela/static/js/core.js` `mountCodeSurface`, `.lee-code-editor`
Every fenced code block in rendered markdown is a real CodeMirror editor with a copy header, and a page of them each drew a thin vertical scroll bar. Two causes, both in the snippet rather than in the pane the earlier scrollbar work went after. The box was `lines * 19px`, but a line is `--lee-code-size` by `--lee-code-line-height`, which are set from the editor preferences and are 13px by 1.5: 19.5px. Every block was half a pixel per line short of its own text, which is a scroll bar with a full-height thumb, and worse for anyone who had changed either preference. It is sized by its content now, capped. The overview stripe also ran inside each snippet, so `has-overview` was hiding and unhiding that bar as it decided whether it was needed; a read-only block a few lines long gets no minimap.

## `leela/blocks/agent/live.js` `foldOlderTurns`
A painted conversation opened every turn it held, so most of the screen was work already dealt with. Painting one, and beginning the next, now leaves the turn being read open and folds the rest. It goes through `foldAgentTurn`, which refuses to fold a turn holding a checkpoint: those buttons and their keys are the only way the run continues, and a folded body cannot be clicked.

## `leela/blocks/agent/models.py` `probed`, `mark_models`
`/agent/models` was 6.8 seconds cold and the picker is drawn on load. The in-memory probe cache was empty exactly when it mattered, because a desktop app is a fresh process every launch, so probes are kept on disk under `leela_cfg/probes` and what a previous run learned is served at once and re-probed behind whoever asked. That alone left 2.7 seconds, and profiling named it: `mark_models` calls `model_marks` for every row, which reaches `spec_caps`, which scans the Hugging Face cache. Ninety-one rows, on every request. The marks go on inside `catalog`, so they are cached with it, and `mark_models` leaves a row that carries them alone. A fresh process now answers in about 190ms; a machine with no cache at all still pays once.

## `leela/workspace.py` `drop_root`
Closing a folder left `active_root` naming it. `project_root` guards, so the surfaces followed the next open folder, but the stale value was still there for anything reading it directly. Removing a root in the tree also repainted neither the workspace name in the header nor the project pills, so the header went on naming a folder that was no longer open.

## `leela/blocks/fs/fs.py` `Sandbox.under`, `leela/blocks/fs/app.py` `fs_new`
`Sandbox.rename` refused any name holding a path separator, and `/fs/new` joined the typed name onto `parent` with no such check, so `../sibling/x.py` in the new-file dialog created the file in another folder. `_check` held it inside the open roots, so it was an inconsistency between two routes rather than an escape. Both go through `Sandbox.under` now, which validates the name and resolves it against the parent in one place, so the new-file and rename dialogs refuse the same names with the same 400 body. Nested creation is still available where it is meant to be: `/refactor/move` takes a whole path, and `mkdir` and `touch` still make the parents they need.

## `leela/blocks/settings/settings.py` `user_settings_file`, `Settings.__init__`
The path of the user settings file was written twice: `USER_SETTINGS_FILE`, exported and read by nothing, and a second copy of the same expression inside `Settings.__init__`. Pointing the exported name somewhere else moved neither a read nor a write. A test that redirected it drove the settings modal, unticked a checkbox, ticked another, saved, reopened and got both back, then read its own file and found it empty, which read as user settings not surviving a save. There is one expression now, `user_settings_file()`, called rather than bound at import, so a config dir moved under a test takes the reads and the writes with it.

## `leela/workspace.py` `Workspace.save`, `SESSION_KEYS`
`save` wrote `state()` over the whole document, and `state()` always names `roots`, `tabs`, `active` and `active_root`. A workspace built to record a model choice holds no folders and no tabs, so writing those four fields blanked the session saved beside them: one `leela_cfg/workspace.json` lost its roots and eighteen tabs, and a bare `leela` launch opened empty. A save merges onto the document already on disk. `only` names the keys a partial write owns, and it still writes `version`, because a document without one is read as a version-1 document and every tab loses its `private_kernel`. The session keys are written by a workspace that read that file or opened something in it, and by no other. Closing the last folder is such a workspace, so an empty `roots` is still recorded. The write goes through `atomic_save`, since a read-modify-write interrupted halfway loses the whole session rather than the last change.

## `frontend/editor.js` `overviewGutter`, `leela/static/lee-ide.css` `.has-overview`
`has-overview` sets `scrollbar-width: none`, and where the platform draws the bar in the flow rather than over the content, that hands its width to the text. macOS does under Appearance > Show scroll bars > Always, and every Windows and Linux desktop does. Wrapped text rewraps at the new width, `scrollHeight` moves, and `scrollHeight` is the number the stripe decides on: the stripe appeared, the pane got wider and shorter, it fell under the threshold, the stripe went, the bar came back, and it flickered at frame rate. The rewrap is worth hundreds of pixels wherever a line sits near a wrap boundary, so the 24px/8px hysteresis could not have held it. This is the width twin of the height loop `overflowsDown` fixed, and that fix does not reach it: the border box holds still, but what is inside it does not. `overviewGutter` measures the bar's thickness on the element itself and holds it back as padding, so the content width does not move when the class does. The thickness is measured rather than assumed, so an overlay bar reserves nothing and no gutter appears where none is needed. CodeMirror's own scroller is left to `.cm-lee-has-overview .cm-scroller`, which already reserves the stripe's 15px, at least what a bar in the flow was taking. The notebook stripe in `leela/blocks/git/cwd.js` toggles the same class and goes through the same helper. Chromium on macOS draws overlay bars whatever `::-webkit-scrollbar` asks for, which is why no browser test had reproduced this; the test fixture asks for `scrollbar-gutter: stable`, which puts a bar in the flow there too.

## `leela_app.py` `open_folder`, `leela/hub.py` `WorkspaceHub`
Opening a folder while Leela was running posted to `/fs/add_root`, so the folder joined the window already open as a second root: one kernel, one tab bar and one agent across two unrelated projects. A launch already gave each folder a workspace of its own, so the Dock, Finder and the picker did the opposite of what the same app did a second earlier. `open_folder` asks the hub for a workspace instead, and the hub builds one with its own state file, its own kernel pool and its own window. `add_root` stays, saying what it does: it adds a folder to the window you are in.

## `leela/hub.py` `WorkspaceHub._lifespan`
The lifespan legs were locals, zipped over the sites present at startup. A workspace opened after that never received `lifespan.startup` and, worse, never received `lifespan.shutdown`, which is what stops a workspace's kernels, terminals, pyright and dev servers. Every folder opened at runtime would have outlived the quit. The queues and the tasks are hub state now, and `add_site` starts a leg for a late site. It reaches the loop through `call_soon_threadsafe`, because a request runs in uvicorn's threadpool where there is no running loop and `create_task` raises.

## `leela/desktop.py` `off_main_thread`, `run_shell`
`webview.create_window` builds nothing at all when it is called from the main thread after `webview.start` owns it: it appends a `Window` that is never realised, and the next `load_url` waits twenty seconds and raises. A Dock menu row and an `odoc` Apple Event both arrive on the main thread, so both ways of handing a folder to a running app were exactly the ways that could not open one. `run_shell` wraps the callback in `off_main_thread` once, where every native caller reaches it. `ShellApi.pick_folder` needed no wrapping: pywebview already runs each `js_api` call on a thread of its own.

## `leela/hub.py` `workspace_slugs`
The slug names the state file, and a counter made it positional: open two projects that both end in `src` the other way round and each was served the other one's tabs. The assignment is remembered per folder in `leela_cfg/workspaces/index.json`, so a folder keeps the slug it was given. A missing or corrupt index re-assigns rather than raising, since it is a convenience and not the source of truth.

## `leela/desktop.py` `menu_chord`, `install_menu_patch`
An `NSToolbar` mirroring the web toolbar was built here first and removed: it was the wrong feature and it stacked a second `run / next / all` above the web bar. What replaced it is the menu bar, and three things in it are not obvious.

A menu item's key equivalent is consulted in `performKeyEquivalent:` before the keystroke reaches the web view, so every chord a menu row takes is a chord the page no longer gets. Leela's keymap is scoped and full of bare letters: `new_file` is `n` in the files pane, `delete` is `d`, `sort` is `o` in variables. Installing those would have fired New File every time the letter n was typed anywhere in the app. `menu_chord` takes a chord only when the action is `global` and its first chord carries a modifier; everything else shows no shortcut. A menu bar cannot express scope, so a scoped chord is declined even when it is modified.

The bar is rebuilt whenever a window takes focus with a menu that is not the one pywebview built last, so anything done to `NSApp.mainMenu()` once, after start, is thrown away by the second window. `install_menu_patch` wraps `BrowserView._recreate_menus`, which is the one method both rebuild paths go through. It is a monkeypatch of a dependency and is written down as one.

Turning off `SHOW_DEFAULT_MENUS` is what puts our menus in the order macOS expects, but it takes pywebview's own Edit and View menus with it, and its View menu was the only source of Enter Full Screen. Cut, Copy, Paste, Select All, Minimize, Zoom, Bring All to Front and Enter Full Screen are `Std` rows: a nil target and a raw selector, so AppKit walks the responder chain to the web view, rather than JS pretending to be a clipboard. The Leela menu is `Menu('__app__')`, which pywebview splices into the real application menu; a menu actually titled `Leela` produces a second one beside it.

## `leela/blocks/git/git.py` `GitRepo.save`, `leela/blocks/git/app.py` `_journalled`, `_guard`
`ignore` and the conflict resolutions wrote through Ramabana's own `Path.write_text`, so a `.gitignore` rule and a settled merge were the two IDE writes nothing kept a copy of: no `atomic_save`, no `FileHistory` version, no journal row, and nothing in `/history/operations` for undo to reach. `GitRepo.save` is the one call in `write_worktree` and `ignore` that touches bytes, and the block points it at `ctx.fs.write` for the length of one mutation, collecting `(path, before, after)` for `ctx.journal.record`. A mutation that fails after a write lands rolls every written file back, as `/refactor/apply` does. The saved mode is put back after the write, because `atomic_save` renames a fresh file into place and would drop the executable bit. A repository rooted above every open folder keeps its plain write and gets no row, rather than having an operation that works today refused. `resolve_conflict` was worse than unlogged: it took the browser's editor text and wrote it over whatever was on disk at that moment, with nothing compared against what the three panes were built from, so a change made in another editor between opening the panes and pressing resolve was destroyed without a word. `_guard` refuses when the worktree no longer reads as `/git/conflict` served it, answering with the shape `/refactor/apply` uses for the same refusal, a plain sentence at 409 rather than `Type: message` at 400, through `_failed` on every action route. The text the panes were built from is remembered per `(root, path)` when `/git/conflict` is served, and a request may carry it as `before` instead; a resolution with neither is refused rather than guessed at. That left two things undone, the merge-review pane's ungated write and the index an undo did not put back, and both are closed below.

## `leela/blocks/runtime/support.py`, `leela/blocks/runtime/app.py`, `leela/blocks/vars/app.py`
The variables panel reads a namespace through a dhrishti inspector running inside the kernel, and `dhrishti.core` imports numpy and pandas at module level. Leela's server never imports dhrishti and says so; `bootstrap_src` appends the server's own `sys.path` to the kernel's instead, so the kernel borrows Leela's copies. A kernel on the same Python minor version borrows them and works, which is why nothing caught this. A kernel on a different one cannot: the extension modules carry the wrong ABI tag. The frozen app is CPython 3.12, most project environments now are 3.13, and the bootstrap cell died on `Original error was: No module named 'numpy._core._multiarray_umath'` under eighteen lines of numpy's own troubleshooting advice. The panel printed all of it and offered one button, Restart kernel and repair, which restarts a kernel that will fail the same way.

The interpreter that lacks the packages is the project's, never the app's. Shipping more in the bundle cannot reach it, so the fix installs into the environment the kernel actually runs in, on the pattern `/runtime/support` already set for `ipykernel` and `ipymini`. `inspector_support` asks the question the kernel asks, rather than a list of package names: it runs `import dhrishti.serving` in the candidate interpreter with `support_paths()` appended, so a project whose Python matches Leela's is told it needs nothing, and a dependency added upstream is answered for without editing a list here. `INSPECTOR` is the install list only, unpinned, because a project's own pandas is its choice. `/runtime/inspector` is a separate route from `/runtime/support` on purpose: `checkProjectRuntime` calls `/runtime/create` without asking when uv is present, on the rule that a directory Leela made is one it may fill, and that exemption does not stretch to a hundred megabytes of numpy and pandas. `installable` refuses Leela's own interpreter and anything inside a signed bundle, which is what `extras_site` exists for. The offer is made off `boot_error` alone: `last_api_error` is a live inspector that did not answer once, and no package fixes that. The panel suppresses its own 2.5-second repaint while an install runs, or the disabled button and the progress line are thrown away every poll.

`packaging/macos/setup.py` and `packaging/windows/setup.py` now name pandas beside numpy. It was already in the DMG, but only because py2app's scanner followed the dhrishti import that Leela's source deliberately never makes, so no line anywhere stated the dependency and a scanner that stopped following it would have taken the variables panel out of the app with nothing to say so.

## `leela/blocks/runtime/kernels.py` `check_gateway_deps`, `GatewayService.start`, `GatewayKernel.start`
The `[gateway]` extra installs `jupygate` and `jupyasyncclient` together, and only the first import was guarded. `GatewayService.start` turned a missing `jupygate` into a `RuntimeError` naming `pip install "leela[gateway]"`, which `serve_ide` catches to fall back to the direct transport. `GatewayKernel.start` imported `jupyasyncclient` unguarded, so half an extra showed a traceback where the other half showed a sentence. The two failed at different points as well: `jupygate` failed at startup, where the fallback is, and `jupyasyncclient` failed at the first kernel start, after the transport choice was made and out of the fallback's reach, so every kernel in that session failed instead of the session using direct kernels.

`check_gateway_deps` checks both imports and is called from `GatewayService.start` and from `GatewayKernel.start`, so the two report the same sentence and the failure lands at startup where `serve_ide` can still fall back. It runs before `GatewayService.start`'s early return, because a service that is already up would otherwise skip it. It also refuses a `jupyasyncclient` outside `>=0.2.1,!=0.2.8`: 0.2.8 makes the gateway `async for` over a coroutine, so a kernel there executes nothing and says nothing, and the range is checked with `packaging`'s `SpecifierSet` against the same constraint `pyproject.toml` states. A version `importlib.metadata` cannot report, as in a vendored copy, is allowed rather than refused.

## `leela/blocks/runtime/kernels.py` `GatewayService.start`
`jupygate.core.serve` with `in_thread=True` polls `server.started` for ten seconds and gives up with `TimeoutError('uvicorn did not start')`, which is what a port already held looks like from here. `TimeoutError` is an `OSError`, so `serve_ide`'s `except (ImportError, RuntimeError)` did not catch it: ten seconds of nothing, then a traceback, and no fallback to the direct transport. `start` now catches `OSError` and re-raises a `RuntimeError` naming the port and the two things that hold it, another Leela or a leftover gateway. An explicitly requested `--transport gateway` still refuses, because `serve_ide` re-raises whenever the transport was not `auto`.

`--gateway-port 0`, which `leela_app.leela_args` passes for every desktop launch, is an ephemeral port: `serve` hands it to uvicorn, and `server.url` carries whichever port was bound, which `GatewayService.url` prefers over `self.port`. Two desktop windows cannot collide. What collides is a literal port, so the default 8787: a second `leela serve`, a gateway left behind by a crash, or `KernelPool.get` constructing its own `GatewayService()` on the default port in a process that already has one.

## `leela/blocks/git/app.py` `_guard`, `_index_back`, `leela/core/session.py` `OperationJournal.hooks`
The merge-review pane's apply-result button posts `write_worktree` carrying the text the reviewer edited in the right-hand pane, and nothing compared that text against the file it replaced. A save from an agent, a formatter or another editor between the tab opening and the button being pressed was overwritten without a word, which is the fault `_guard` already refuses for a conflict resolution. `_guard` now takes the operation rather than reading `choice`, and `/git/action` runs it for `write_worktree` too, so both answer with the same plain sentence at 409 through `_failed`. `/git/action` is the only route that reaches `write_worktree`: `/git/tree/action` allows `stage`, `unstage`, `discard` and `ignore` and nothing else, and `resolve_conflict` and `resolve_safe_conflicts` reach `GitRepo.write_worktree` in process rather than over a route. The before-image is what `/git/review/file` served, returned as `worktree` and remembered per `(root, path)`, and the browser echoes it back as `before` from the tab it was opened with. Merge reviews keep their own cache rather than sharing the conflict panes': one dictionary for both would mean that opening a review diff refreshed the text a stale conflict resolution is checked against, and waved it through. Only a review whose result can be applied is remembered, so paging through a forty-file review cannot evict the conflict panes. The pane's `left` is not usable as the before-image even though `can_apply` requires a clean tree at the base commit, because it is a Git blob: a checkout filter or a rename makes it differ from the file on disk for reasons that have nothing to do with anyone else's edit. A notebook is refused outright, since those panes hold decoded cell sources rather than the file and the browser hiding the button for `.ipynb` was all that stopped that write. The tab carries the repository it was built from and sends it, because a diff tab outlives the panel's chosen repository and would otherwise write its path into whichever repository is chosen now.

Undo of a Git row put the text back and left Git's index where the operation had staged it, so a reversed resolution still read as staged and only `git reset` finished the job. The journal cannot know what an index is, so it grew the smallest seam that lets a block say: `OperationJournal.hooks` maps a row's `kind` to `hook(op, side)`, called once the rows are back, and `record` takes an `extra` dict kept on the row. The Git block registers the one hook there is. `GitRepo.stage` hands a `stager` the paths first, mirroring `saver`, and the block reads `git ls-files -s` for them before the staging happens, so the row carries the index entries the operation replaced rather than a guess at them. Undo replays those entries through `git update-index --index-info`, which puts a conflict's three stages back exactly, mode and all, and touches no file. `git restore --staged` will not do: `git add` destroys stages 1, 2 and 3, and copying HEAD into stage 0 leaves a third state, one where the conflict centre never offers the file again and a commit finishes the merge with content nobody chose. Once the merge is over there is no such state to return to, so a row whose entries are unmerged is unstaged instead and the undo says so in its `note`. A hook that fails reports in `note` rather than raising, because by then the text is back and the operation is saved. A row written before any of this, or one whose operation staged nothing, undoes exactly as it did.

That left `resolve_conflict` with `ours`, `theirs` or `worktree`, which is a Git checkout rather than a write through `saver`, so it staged a file and left no journal row at all. That is closed below.

## `leela/blocks/agent/models.py` `probed`, `forget_probes`, `tests/conftest.py` `_no_warm_probes`
`forget_probes` dropped the cached answers and nothing told a probe already gathering that it had. The thread finished, wrote its value into `_PROBED` and into `probes/` on disk, and the next caller was served the state that had just been thrown away. Refresh in the model picker is `forget_probes(disk=True)`, so a refresh that arrived while a probe was under way could put the stale catalog straight back and keep it for the next launch as well. `probed` now reads a generation counter when it starts, `forget_probes` bumps it, and `_keep` commits only when the two still match. An answer gathered across a drop is still returned to whoever asked for it, and is not written in.

The suite saw the same fault as an intermittent failure of `test_model_picker_shows_older_models_by_default`. `ide_app` warms the probes on a startup thread and nothing joins it, so a suite that builds the app hundreds of times has several of them running at once. One gathers a catalog under a test with no `OPENAI_API_KEY` and commits it after `_cold_probes` has cleared the cache for the next test, which had patched `_oai_cache` to offer `gpt-4.1` and was answered with a catalog holding no OpenAI rows at all. Which test the answer landed in depended on how long the gather happened to take, which is why the same tree passed one full run and failed the next. `_no_warm_probes` stops the startup warmer for the length of a test, on the pattern `_no_backup_threads` already set: the generation counter drops an answer gathered before the cache was cleared, and the fixture closes the narrower window where a leftover thread starts gathering after it and before the test has patched anything.

## `leela/static/js/core.js` `stripWorkLog`, `payloadContainer`, `leela/blocks/nb/cells.js` `renderOutputs`
A prompt cell keeps its work log twice. `Workspace.ask_cell` and `ask_cell_stream` write the tool rows
into `cell.calls` and append `Agent.turn_md()`, the same rows as GitHub-flavoured `<details>` markdown,
to the end of `cell.reply`. `renderOutputs` drew both: the rows as real accordions, then the reply
underneath. `/markdown/render` is mdhtml, whose dialect has no raw HTML at all - raw enters through a
`{=html}` fence, and a `div` classed `details` lowers to a `<details>` element - so the appended copy
came out as literal `<details>` and `<summary>` text over a fully unrolled tool result, under a fold
already holding it. `allow_raw` is not involved: it only rewrites `{=html}` fences, and the escaping
happens either way. The reply is rendered without its trailing work log whenever `calls` has the rows,
so the log is drawn once and the cell keeps the trail for the notebook it saves into.

`upgradePortableToolMarkdown` turns a JSON tool payload in a `<pre><code>` into a step row, and
replaced `code.parentElement.closest('details')`: the nearest `<details>` ancestor, whichever one that
was. Where a fold holds several payloads as siblings, as mdhtml's `:::{.details}` lowers them, the
first payload replaced the whole group, summary and later steps included. The rest of the loop then
worked on nodes still parented by that detached group, where `replaceWith` is a no-op, so a two-step
log read as one row and lost its title. `payloadContainer` takes the fold only when it is a `result`
fold whose single non-summary child is this block, and the loop skips a `<code>` already off the page.

## `leela/blocks/git/git.py` `GitRepo.sider`, `leela/blocks/git/app.py` `_sided`, `_bytes_back`, `leela/core/session.py` `OperationJournal.record`

Choosing "use ours", "use theirs" or "keep the working tree" in the conflict centre left no journal row. `resolve_conflict` writes through `saver` only for `resolved`; the other three are `git checkout --ours`, `git checkout --theirs` and nothing at all, followed in every case by `git add`. A checkout writes the working file itself, so `_sandboxed` collected nothing, `rows` was empty and `_journalled` recorded nothing. Choosing a whole side overwrote whatever was on disk, and undo could not reach any of it.

Reimplementing the checkout as `write_worktree(path, conflict_versions(path)[choice])` is the obvious fix and it is wrong. `git show :2:path` returns the blob in its *clean* form, and staging it cleans it a second time. In a repository with a `filter=` attribute, `checkout --ours` puts `OURS` in the tree and `BHEF` in the index, where writing the stage back puts `BHEF` in the tree and `OURS` in the index: the merge would commit content that is on neither side. The `eol=crlf` case, where the two agree, is what makes this look safe. A missing stage is worse than wrong: `git show :3:path` is `''` for the side of a modify/delete conflict that deleted the file, so a write of it stages the empty blob where `checkout --theirs` refuses with `path 'f.txt' does not have their version`. A symlink stage is the link's target, which `write_worktree` would follow and write *through* the link into whatever it points at. A submodule stage is a gitlink `git show` cannot read at all.

So the checkout stays exactly as Ramabana runs it, and what it replaced is read rather than saved. `GitRepo.sider` is the seam, set per instance beside `saver` and `stager`: `resolve_conflict` reads the working file before the checkout, hashes it, and hands `(target, before, after, oid)` over afterwards in a `finally`, so a `git add` that fails after the checkout succeeded still leaves the block a row to roll back. `_sided` puts that row in the same list `_sandboxed` fills, so a text side is journalled, versioned and undone exactly as `resolved` is, and Git's bytes are the ones on disk.

A binary side cannot be a journal row, because the bodies are text and one read back through `errors='replace'` is not the file. Its bytes are still in the index: Git leaves stage 2 in the tree for a binary conflict, so the file hashes to the stage-2 blob unless someone edited it. The row carries the hash, and undo restores the three stages and then runs `git checkout --ours` when the restored stage 2 still matches it. A hash that does not match means the file was edited after the merge left it, which no stage holds, and the undo says so in its `note` rather than putting the wrong bytes back. Nothing is written to the object database: a loose object from `git hash-object -w` is unreferenced, and `git gc --prune=now` deletes it, which would leave the row un-undoable with `bad object`.

`worktree` writes no file at all, and a resolution that changes only the index had no way to be recorded: `OperationJournal.record` returns None without resources, and `rows`, `undo` and `redo` all read a row with none as spent. `record` takes `hooked` for a row its `kind`'s own hook reverses on its own, `_has_work` is the one place that decides, and `rows` falls back to a `paths` the row names itself so the history modal has something to show. Such a row becomes the default target of `/history/undo`, so an undo after keeping the working tree takes the staging back rather than the last edit.

`ours` and `theirs` are gated exactly as `resolved` is, and refuse with the same plain sentence at 409 through `_failed`. The argument that a checkout takes its content from Git and so cannot be stale is only half of it: it overwrites the working file, and a hand-edit made after `/git/conflict` was served is the same loss `_guard` exists to refuse. Gating them only when a before-image happens to be around would make the protection depend on `PANES`, so the thirty-third conflict file opened would be written without a check, invisibly. `showWholeSideConflict` sends `before` now rather than leaning on the server still holding those panes. `worktree` is not gated: it stages the file exactly as it is on disk, so a disk that moved is what it was asked for.

Two things in this area were still open at that point. Both are closed below.

## `leela/blocks/nb/nb.py` `strip_work_log`, `Notebook._context_cell`

The visible half of the doubled work log was closed above, in `renderOutputs`. The expensive half was
not. `_context_cell` writes a prompt cell's whole `reply` back as `<answer>`, and `Notebook.context`
is what grounds every later turn in the document: `Workspace._agent_context` for a prompt cell, and
`nb.context(len(nb))` for a prompt-bar turn on the open notebook. So the trail `ask_cell` and
`ask_cell_stream` append was paid for again on every turn after the one that produced it, with the
tool results unrolled. `MAX_CONTEXT` and `MAX_CELL_OUT` are both `None`, so nothing capped that
growth. Three tool calls in one cell of this repository, two `search_code` and one `read_file`, make a
10,480-character trail under an 84-character answer: 99% of the cell's `reply`, carried forward
untouched.

`strip_work_log` removes a trailing `turn_md` fold, and `_context_cell` applies it before emitting
`<answer>`. The pattern is the Python twin of `stripWorkLog` in `leela/static/js/core.js`, anchored
with `\Z` and compiled without `re.M`, since a bare `$` under `MULTILINE` would end the match at any
line break and eat the rest of the answer. The strip is unconditional, unlike the client's, which
strips only when `calls` has rows: a cell read from an older `.ipynb` whose `calls` metadata is
missing would otherwise keep padding the context forever. `_context_cell`'s empty test reads the
stripped reply too, so a cell holding nothing but a trail leaves context entirely rather than
contributing an empty `<cell>`.

Nothing else changes. The notebook file keeps what it kept: `nbcell` still writes `reply` whole into
`leela` metadata, so the trail survives a save and a reload, and `test_a_streamed_cell_still_gets_its_activity_trail`
still holds. Stripping at the source instead, so `reply` never carried the trail, is the cleaner seam
and is the one to take when there is room to check every reader of that metadata; the context builder
is the one place the cost is actually incurred. A reply whose own prose ends in an unrelated
`<details>` is not matched, because the summary text is anchored to the `turn_md` title.

Two neighbours of this are still open. `<answer>` is emitted whole while `<output>` is clipped by
`out_chars`, so a long prose reply is still an unbounded context term. And `notebook_approvals` inserts
markdown cells holding `ask_md`/`answer_md` plus the call's arguments as indented JSON, at the default
`context_mode='auto'`, so every approved write is re-sent on every later turn: the same duplication one
cell over, which stripping a `<details>` does not touch.

## `leela/blocks/git/git.py` `GitRepo.drop`, `stages`, `_drop_side`, `leela/blocks/git/app.py` `_dropped_files`, `_guard_batch`, `_rollback`

Choosing the side of a modify/delete conflict that deleted the file failed with `error: path 'f.txt' does not have their version`. That is Git's answer to `git checkout --theirs` when stage 3 is not in the index, and it is not an answer to what the button asks for. `showWholeSideConflict` is the panel for exactly this conflict, and it draws the empty side as "This side does not have this file." Pressing it left the file conflicted and said something about a checkout nobody ran.

A modify/delete conflict has two stages, never three. When they deleted, the index holds stages 1 and 2, `git status --short` reads `UD`, and the working file holds our version. When we deleted, it holds stages 1 and 3, reads `DU`, and the working file holds theirs. `git checkout` for the missing side refuses in both directions. So the side that has no stage is the side that asked for the file to go, and the resolution is to take it away and stage that. `GitRepo.stages` reads the unmerged entries and `resolve_conflict` takes `_drop_side` when the chosen side has none of them.

The file is not deleted. It is moved aside whole, through a `dropper` seam set beside `saver`, into the journal's `Trash`. A modify/delete file can be binary, executable or a symlink, and none of those survives being journal text: a binary read back through `errors='replace'` is not the file, `atomic_save` drops the executable bit, and a symlink written back as text is a copy of whatever it pointed at. `Trash.keep` is one rename, which keeps all three, and `OperationJournal.record` already takes `trashed` rows that undo moves back. `git add` on the moved-aside path then stages the deletion, which is one call to `GitRepo.stage`, so the row still carries the index entries the operation replaced. Undo moves the file back and replays those entries, and the file is conflicted again with the stages it had. Redo moves it aside again and stages the deletion again.

`git rm` would do the same two steps in one command, and it is the wrong one here. It leaves nothing for undo to move back. The journal's own trash is what makes the removal recoverable, so the removal has to go through it.

`_dropped_files` does not resolve the path it is handed. `Path(target).resolve()` follows a symlink, so a conflicted link would have moved aside the file it points at, which is on nobody's side of the merge, and left the link itself in the tree. It resolves the parent and keeps the name. A gitlink is refused by name rather than moved: `git rm` on a submodule takes its whole working tree, and a mode-160000 stage cannot recreate the contents.

`resolve_safe_conflicts` wrote over conflicted files through `saver` with nothing compared against what it overwrote. The plan the button is built from is `/git/conflicts`, and the confirm dialog quotes its count back: "Stage N deterministic resolutions?". The honest before-image is therefore every conflicted file's text at the moment that plan was served, so `/git/conflicts` remembers it and `_guard_batch` checks it. A file that moved, a file the plan never named, or a file an editor tab holds unsaved edits to refuses with the same plain sentence at 409 through `_failed` that `resolve_conflict` and `write_worktree` answer with.

The remembered plan is one entry per repository, not one per file, unlike the conflict panes and the merge reviews. Those are keyed per file and capped at `PANES`, so a forty-file merge would evict its own before-images and the batch would be checked against nothing. The browser echoing them back, which is what a merge review does, would mean shipping every conflicted file's body to the page and back for a button that names only paths. One entry per repository cannot be evicted by another file being opened, and the entry is dropped once the batch runs, because by then every file in it has changed.

`_guard_batch` names the paths it checked back into the request. Without `paths`, `resolve_safe_conflicts` resolves every file that is conflicted when Ramabana reads the plan again, which is not the set the guard looked at.

Every check runs before the first file is written, so a stale file refuses the batch rather than half-applying it. That is not enough on its own. `resolve_safe_conflicts` writes and stages one file at a time, so a failure on the third of five leaves the first two written and their conflict stages already collapsed to one settled blob, and `record` is never reached, so there is no row to undo. `_rollback` put the worktree text back and left that index alone. It now replays the entries `_staged` captured, which is the same `update-index --index-info` the undo hook uses. A batch that fails part-way leaves the tree and the index as they were.

## `frontend/editor.js` `overviewGutter`, `leela/blocks/git/cwd.js` `paintNotebookOverview`

A file open in the IDE drew its overview stripe and the pane's own scroll bar at the same time,
side by side down the right edge, wherever the platform draws bars in the flow: macOS under
Appearance > Show scroll bars > Always, and every Windows and Linux desktop. The stripe is meant to
be the bar, so a bar beside it is a second thing to scroll and the arrangement the stripe replaced.

Two stripes reach the same element. `#editor` is the pane a notebook scrolls, and it is also the
pane a file's CodeMirror is laid out inside at the height of the whole file, so `scrollerFor` walks
up to it and the file's stripe hides its bar too. Both hide it by the same means, `overviewGutter`,
which sets `has-overview` and holds the measured thickness back as `padding-right`. Neither knew
about the other. `paintNotebookOverview` runs on every scroll of `#editor` and on every window
resize, whatever the tab holds, and asserted `overviewGutter(host, false)` for anything that is not
a notebook. So on a text tab the file's plugin added the class on its frame and the notebook
painter took it off on its own, both queued on `requestAnimationFrame` by the same scroll event:
the bar came back under a stripe that was still drawn, and which of the two you saw was decided by
whichever frame ran last. Recorded live at 24 frames out of 24 showing both.

The bar is now given back only to whoever took it away. `overviewGutter` takes a third argument
naming the stripe, writes it to `dataset.leeOverview` when it hides a bar, and refuses an `off`
from any other name. The notebook painter passes `'nb'` and the editor plugin `'cm'`, so the
notebook's assertion on a text tab is a no-op while the file's stripe holds the pane. The claim
still changes hands: opening a file over a notebook leaves the class on, and the file plugin's
first `on` call takes the name over without touching the padding it inherits, which is the same
thickness measured on the same element. Opening a notebook over a file goes the other way through
the plugin's `destroy`, which releases under its own name before the notebook paints.

This is not the flutter that `overviewGutter` was written for and does not undo it. That was one
stripe feeding itself through the width its own class handed back to wrapped text; this is two
stripes contradicting each other about one pane. The width compensation is untouched, and both of
its tests still pass.

## `leela/blocks/agent/approvals.js` `addResponseRevision`

The three controls under a finished turn, `Edit what agent remembers`, `Undo from conversation` and
`Restore files`, did nothing when clicked and gave no sign why. The report was "I see the buttons.
I click edit and undo. Nothing happens."

The dispatch was correct. `bindResponseRevisions` binds one delegated listener on `#agentlog`, the
bar is painted inside it by `renderTurns` on every repaint, and a click on an available control
opens its dialog. What the listener also does is `if (button.disabled) return`, and for the turn in
the report all three were disabled: `turn_capabilities` reports `known: false` for a turn this
process holds no checkpoint or transaction for, which is every turn from a conversation restored
after a relaunch, and from past `MAX_CHECKPOINTS` in a long one.

Nothing in the interface said so. `.lee-btn` has no disabled appearance in `lee-ide.css`, so a
measurement of both states returned identical colour, background, border, opacity `1` and
`cursor: pointer` for a dead control and a live one. The only explanation was the `title`, which is
a hover in a packaged app with no status bar, and reads as a dead button before that.

An unavailable control is now muted and states its reason on the row. The button stays, so a
control nobody can reach today is still a control they can learn exists tomorrow. The reason moves
out of the `title` into a `[data-unavailable]` line under the buttons: one shared sentence when the
turn is unknown to this process, since all three would otherwise repeat it, and one clause per
control otherwise. The muting and the line are inline styles rather than stylesheet rules, so the
bar explains itself wherever it is painted.

## `leela/blocks/runtime/engines.py` `EngineBroker.attach`

Switching to an Ollama chat model failed with `AttributeError: type object 'OllamaChat' has no
attribute 'create_engine'`. The same models answer in Ramabana, which reaches rishi directly and
never passes through the broker.

`attach` asked whether the model is local. `ModelSpec.local` is `backend not in HOSTED`, and
`HOSTED` is `('remote', 'copilot', *AGENTS)`, so ollama is local. Local is not the question the
broker needs answered. Ollama is a server that holds the weights in its own process, and rishi
dials it. `OllamaChat` therefore has no `create_engine`, and neither do `ClaudeChat` or
`CopilotChat`. Only `LitertChat`, `MlxChat` and `LlamaChat` have one. `attach` reached
`engine_key`, `engine_kw` and `inspect.signature(cls.create_engine)`, and the guard there catches
`ImportError` only, which is the uninstalled-runtime case rishi reports for itself.

The broker now asks whether the runtime builds an engine this process holds. `_create_engine`
returns the classmethod or None, `attach` returns None for a runtime that has none, and
`engine_kw` is built from nothing for one. `engine_key` and `_build` are reachable only through
`attach`, so the early return is the whole fix. The `spec.local` test stays in front of it: a
hosted model needs no rishi import to be ruled out.

`status` counts engines this process loaded. An Ollama workspace reports none, and that is
correct. The weights are in Ollama's daemon and Leela cannot count or release them.

## `leela/blocks/runtime/engines.py`, releasing an engine

A local model whose chat failed keeps its weights. `Backend.start` swallows the failure, sets
`chat` to None and records a note, and the backend stays in the agent's `_backends`. The engine it
was handed stays loaded. Eviction runs in `_make_room` only, which is reached when a new engine is
wanted and `max_engines` (`LEELA_MAX_ENGINES`, 3) is already met, so nothing releases it until a
fourth distinct model is asked for. At the ceiling with every engine live, the answer is
`RuntimeError('model engine limit reached ...')` and no eviction at all.

A half-registered entry after a failed build was suspected and does not exist. `self.engines[key]
= _Loaded(self._build(spec, kw), key)` builds before it assigns, so a `create_engine` that raises
leaves the dictionary untouched and `be.kw` without an `engine`. Verified by running it.

Releasing on the next `attach` was designed and rejected. Two holes:

1. `Backend.start` sets `_tried` before the attempt, not after. For the whole of `_start`, which is
   the weight load, a backend reads as tried with no chat, which is the same shape as one that
   failed. Another workspace attaching in that window would close the engine the first is at that
   moment building on.
2. `_Loaded.users` does not know every holder. `RishiBackend.spawn` passes `chat.engine` to a
   sub-agent backend rishi creates itself, `_oneshot` builds `_oneshot_chat` on it, and
   `Agent.lend_model` hands it to a bare `rishi.Chat` for the vault. Leela registers none of them.
   A parent backend that failed or closed can be the only registered user of an engine a live
   vault chat is answering on.

Both holes exist under `_make_room` today. Sweeping on every attach would turn a rare wrong
eviction into a routine one. `/runtime/engines/clear` is the release instead: a person asks, the
route refuses at 409 while a session is on a model and names it, and a forced clear closes it
anyway. No timer and no reaper thread. A reaper would need the first hole closed first, which
means a signal from ramabana that separates loading from failed, and the second closed by
registering the engines `spawn` and `lend_model` hand out.

`MlxChat.__new__` re-routes a vision repo to `MlxVlmChat`, and `get_runtime('mlx')` returns
`MlxChat` either way. The broker builds a text engine from `MlxChat.create_engine` and hands it to
a chat that is `MlxVlmChat`. The two signatures match, so `engine_key` cannot tell them apart.
Untested here and not fixed.

## `leela/blocks/browser/browser.py` `resize`, `start_cast`

Every page in the inline browser was soft on a Retina display. The panel asked for `scale: 1` in all
three places it told the server what viewport it wanted, so `Browser.resize` set
`deviceScaleFactor=1` and the canvas drew a 1x frame into a box the display then painted at two
device pixels per CSS pixel. The stream was also JPEG quality 62, which leaves visible artefacts on
body text.

`deviceScaleFactor` is not the lever. Measured against a real headless Chrome, with a 200px div and
an 800x600 viewport, the screencast frame carries 200 image pixels for that div at
`deviceScaleFactor=1` and at `deviceScaleFactor=2`, with `dontSetVisibleSize` and
`Emulation.setVisibleSize`, and with the CDP window grown to 1700x1500 first. A per-page device
scale factor changes what the page reads from `window.devicePixelRatio` and nothing about the
raster. `Page.captureScreenshot` does honour it, which is what made the wrong answer look right.

The one setting that changes it is the browser's own scale factor, taken at launch. Chrome started
with `--force-device-scale-factor=2` sends 400 image pixels for the same div, and 1600x1200 for the
same 800x600 viewport. `Browser.cdp` passes that flag as `SCALE_FLAG` through `cdp_connect`, and
`start_cast` raises `maxWidth` and `maxHeight` from the viewport to `MAX_SCALE` times it, because
pinning them to the CSS box was Chrome's instruction to scale a 2x frame straight back down.

Two consequences to know about. The flag only applies to a Chrome that Leela starts: one already
running on the CDP port when Leela connects goes on sending 1x frames, and picks the flag up when
it is next restarted. And the factor is fixed for the browser, so a 1x display pays for 2x frames.

The clamps stay in CSS pixels. `MAX_SIZE` and the 240x180 floors describe the viewport, which is
the unit a click arrives in, and `scale` is clamped separately to `MAX_SCALE` because it is now
only what the page reads as its `devicePixelRatio`. The click mapping is therefore untouched: the
emulated viewport is still the canvas's CSS box, and `getBoundingClientRect` still reports CSS
pixels. What changed on the client is the canvas backing store. `drawFrame` sizes it to the frame
it is about to draw, so a 1600x1200 frame lands 1:1 in a box the display paints at 800x600, and a
Chrome that sends 800x600 draws 1:1 as before. The frame is the only thing that knows how many
pixels it carries, so nothing has to be told.

`tests/blocks/test_browser.py` covers the real path end to end: it starts Chrome on a free port so
`SCALE_FLAG` cannot be missed by reusing one already up, asks for an 800x600 viewport, and requires
a 1600x1200 frame and a click at CSS (400, 300) reaching the page as (400, 300). The page reports
the coordinates it received in its title, so the assertion is on the mapping rather than on a
button being somewhere. A metrics override resizes the window Chrome composites into
asynchronously, so an early frame is the window as it was, and the test restarts the cast until the
window has converged.

## `leela/blocks/tabs/app.py` `tab_close`

`/browser/close` had no callers anywhere in the tree. Its docstring said "Close the page in Chrome.
The Leela tab is closed by the tab strip, as usual", describing a pairing nobody had wired, so pages
accumulated in the CDP Chrome for the life of the session. The report: "because I open
vedicreader.com, close the tab, and when I go pages open in the browser it's still there."

`/tab/close` now closes the Chrome page when the tab it dropped was a web tab. It takes the `Tab`
that `Workspace.close` returns rather than re-reading the index, so the tab is already gone before
Chrome is asked anything, and a Chrome that will not answer cannot hold the tab strip: the call is
skipped entirely unless `running()` says a browser is already up, it is bounded by two seconds, and
it swallows what it catches. Reaching `ctx.browser` from this block adds `browser` to its `CAPS`.

A page adopted through `/browser/attach` is not closed. It came from the user's own Chrome and
closing it would take away something Leela never opened, so `Browser` records the targets it
created in `_mine` and `shut(tid, mine_only=True)` spares everything else. The CDP profile's own
`about:blank` is never in that set, because `open` only ever navigates to a URL `check_url` has
passed. The set survives a CDP reconnect, since the pages do, and is emptied with the page cache
when the connection is rebuilt from nothing.

Two things this does not reach. Quitting Leela still leaves every page it opened, because
`Workspace.shutdown` says nothing about the browser and `Browser.close` deliberately outlives
Chrome. And `_mine` is per window: a page opened in one Leela window and adopted in another is
closed by the first window's tab strip and not by the second's.

## `leela/blocks/runtime/engines.py`, the class that builds an engine

An MLX vision model in Leela built the wrong engine. `get_runtime('mlx')` is asked for a runtime
and is never shown the model, so it answers `MlxChat` for every mlx repo. `MlxChat.__new__`
re-routes a vision or audio repo to `MlxVlmChat`, which loads through `mlx-vlm` rather than
`mlx-lm`. The broker built its engine from `MlxChat.create_engine` and rishi then handed that
engine to `MlxVlmChat`.

What happens next depends on the repo, and neither answer is Leela's:

- `mlx-community/Qwen3-Omni-30B-A3B-Instruct-4bit` fails at the build. `mlx-lm` has no
  `qwen3_omni_moe` architecture and raises `ValueError: Model type qwen3_omni_moe not supported.`
  It is raised inside `attach`, which is a code path Ramabana never runs, so the model works in
  Ramabana and not here. That is the Ollama fault in another dress.
- `mlx-community/Qwen3-VL-4B-Instruct-4bit` fails at the first turn. `mlx-lm` does carry a
  `qwen3_vl` architecture, 57 lines with no vision in them, so the load succeeds, drops the vision
  tower, and returns a text model with a `TokenizerWrapper` where a `Qwen3VLProcessor` belongs. The
  turn then dies in mlx-vlm with `AttributeError: 'Model' object has no attribute 'config'`.
  Measured, not read: both the failure and the repaired path were run against the real model.

No case produces a wrong answer quietly. mlx-vlm reaches for `processor.image_processor` and calls
the model with its own signature, and a text engine satisfies neither.

The broker now asks which class rishi will build, not which class the runtime names. `_model_cls`
routes through `cls.__new__`, which is rishi's own dispatch: `Chat.__new__` calls the subclass's
`__new__` for exactly this reason, and its comment names this case. A class that does not override
`__new__` has nowhere to re-route and is returned as it is, which also keeps `object.__new__` from
being handed arguments it will not take.

The resolved class is memoized per model on the broker. Rishi's sniff reads `config.json` through
`hf_hub_download`, and `attach` runs on every turn: 0.5s to 2s per resolve, measured on a warm
cache, because the hub still checks the etag. The memo is keyed on the runtime, the model id,
`model_path` and `vlm`, which is what `MlxChat.__new__` reads. A future dispatch keyword would need
adding there.

**The cache was never confused about two models.** `engine_key` has always carried
`_model_id(spec)`, so a text repo and a vision repo hold separate entries whatever class built
them. One repo down two loaders is the case that did collide: `vlm=False` takes a vision repo
through the text loader, `vlm` is not a `create_engine` parameter so `engine_kw` drops it, and both
chats then keyed to one entry and shared one engine. The key now carries the class name, so they
are two engines. Neither Leela nor Ramabana passes `vlm` today, so this was reachable only through
a model's `config`.

What rishi should expose, so this stops being Leela's problem: a resolver from `(runtime, model_id,
kw)` to the chat class, beside `get_runtime`. Every caller that wants to know what a model will be
before building it is otherwise left calling `__new__` for its type. `rishi.core.model_caps`
answers a neighbouring question, and `_cfg_caps` reads the same `config.json` towers that
`rishi.mlx.is_vlm` reads, so the sniff already exists twice inside rishi. Rishi was not edited here.

## `leela/blocks/runtime/kernel.js` `pickKernel`

`/runtime/broker` has answered with a `models` block since the engine broker was written, carrying
`live`, `limit`, and a row per loaded engine. Nothing in the client asked for it. The docstring on
`EngineBroker.status` says "for the runtime pane" and no pane painted it, so the weights this
machine held were visible only to a route nobody called, and the memory a local model was holding
could not be seen or released from the interface at all.

The kernel picker now carries the list, under the launcher and interpreter it already offers. It is
the modal a person opens to ask what this machine is running, and the weights belong to that
question. A `clear weights` button under the list posts `/runtime/engines/clear`.

Three things the picker must keep doing:

- It opens whether or not the broker answers. `loadedModels` catches and returns null, and
  `engineSection` paints nothing for null. A person comes here when a runtime is misbehaving, so a
  broker that cannot answer must not be what keeps the picker shut.
- A model row is not a kernel choice. One delegated handler takes every `.lee-mrow` click in the
  modal and restarts the kernel on it, so the model rows carry `data-engine` and the handler
  returns on them first. Without that, clicking a loaded model would have posted `/kernel/select`
  with an undefined interpreter.
- The refusal is the server's sentence. A 409 from the clear route names what is holding the
  weights, `api` throws it as the message, and it is the text of the confirm that offers the force.
  The force is a second answer to that sentence, never the first request. Whether the refusal is
  answerable is decided by re-reading `in_use` from the broker, not by matching on the prose.

Node is not available in this environment, so the JavaScript was not syntax-checked. The tests over
it are assertions about the source text, which is what the rest of this repository does for client
code.

## `frontend/editor.js` `overviewGutter`, `overviewPlugin`

The stripe and a scroll bar were still drawn together, one fault further in. Naming the stripe that
hid a pane's bar separated a notebook's from a file's, but not one editor from another: both are
`cm`, so an editor could hand back a bar it had never taken.

Every editor in a scrolling panel resolves to that panel. `scrollerFor` walks up from an editor to
the first ancestor that overflows, and for a panel of editors that is the panel, so all of them hide
the same bar. At the default `overviewMode: 'long'` they do not agree about it: an editor of a
hundred lines has no stripe and says `off` about the very pane the three-hundred-line editor beside
it is drawing over. Under the previous rule that `off` was granted, because the name matched. The
panel's bar came back, the long editor's stripe stayed up beside it, and nothing redrew to correct
it. Recorded live in the agent panel: one editor gives `bar 0`, adding a short one beside it gives
`bar 9` with the stripe still shown, and it stays that way through scrolling.

The pane now holds the set of stripes that want its bar gone, in `dataset.leeOverview`, and gives it
back when the last of them leaves. Each plugin instance claims under its own name rather than its
kind. This subsumes the previous rule rather than replacing it: the notebook painter's `off` drops
only `nb` from the set, so a file's stripe holding the same pane keeps it hidden, and a stripe that
is destroyed while another still draws over the pane leaves the bar hidden for the one still there.

The notebook-only path, which is where the fault was reported, was measured and is not this. A
notebook scrolled on its own holds `has-overview` on `#editor` under the name `nb` from the first
paint to the last, with the bar at zero throughout: forty-three cells of a real agent session
repeated three times, every accordion opened, cells mounting lazily under a deep scroll, and a
conversation painted into the panel beside it. What the same measurement did show is that this
application never gets a platform scroll bar in the flow under test: `::-webkit-scrollbar` at the
foot of `lee-ide.css` styles every bar in the app, and Chromium keeps those as overlay bars while
macOS is set to show bars only when scrolling. A test that wants a bar taking layout space has to
ask for one with `scrollbar-gutter: stable`, which is what both stripe tests now do.

## `leela/blocks/agent/ai.py` `WorkspaceHost.list_vars`, `WorkspaceHost.promote_var`

Commit `0e12791` moved `run_python` from `/api/exec` in the user's namespace to `/agent/api/exec` in
the agent's overlay. That stopped the agent deleting what the user made. No reader moved with it.
`list_vars` still queried `/api/rows`, which is owner-only, so the agent bound `df_norm` and was
then told by every reader Leela had that `df_norm` does not exist. Ramabana's own
`DhrishtiHost.list_vars` queries `/agent/api/rows`, the merged view, and Leela diverged from the
library it is a seam over.

Measured with a real kernel and no model: `run_python` returns ok, `/api/rows` gives `['df']`,
`/agent/api/rows` gives `['df', 'df_norm']`, and the user's next cell raises `NameError`.

`list_vars` now reads `/agent/api/rows` and falls back to `/api/rows` when that route returns
nothing. An `agent='off'` inspector refuses the merged route with a 403, and owner-only rows beat an
empty briefing.

`owner_names` is the separate question: what the user's own namespace holds. `promote_var` is the
only route across. It is `/api/promote`, which is the vars pane's `→live` gesture, given a tool
name. Three things it must keep doing:

- It refuses a name the user already owns, before the kernel is asked. Dhrishti's `_promote`
  overwrites the owner binding without complaint, and the notebook fixture runs `approvals='auto'`,
  where an approval gate resolves to yes without anyone reading it. The refusal is unconditional
  because that is the only kind `0e12791`'s protection survives.
- It drops the agent's shadow after promoting. `AgentSession.owner_names` excludes anything the
  layer shadows, so a promoted name that stayed in both was outside the policy that refuses owner
  mutations, and the agent could then mutate the object it had just handed over.
- Every route answers in the same shape: the name is not the agent's, the name is already the
  user's, the name is not an identifier, the inspector did not answer.

## `leela/workspace.py` `_requested_name`, `_action_retry`

`_action_retry` told the model to call `scale_numeric`. No such tool exists in Leela or in ramabana.
It measured completion against `list_vars`, which the agent's own binding could not reach, so the
retry could never be satisfied and burned all three attempts.

`_requested_name` matched `as df_norm` and not ``as `df_norm`.``, which is how the dialog fixture and
most people write it. The retry never fired for the prompt it was written for.

The retry now names `run_python` and `promote_var`, and measures against `owner_names`. That is the
question a prompt cell asks: whether the next cell can read the name. `_name_exists` reads the
merged view by default, which is what the agent sees, and takes `owner=True` for the other question.
Asking the merged view here would make the retry vacuous: an overlay binding would count as done and
nothing would reach the user.

`_land` promotes the name the prompt asked for at the top of each attempt of both retry loops. The
prompt cell is the user's own instruction to bind that name, and the collision refusal means it
cannot replace anything. It is Leela's step rather than a model tool call, so it appears as a status
note and not as a row in the activity trail.

## `rishi.litert` GPU activations, and the inline tool set that was cut over them

litert-lm 0.16.1 dropped and duplicated generated tokens once a conversation's prefilled prompt
passed 2048, which is two `prefill_1024` passes. A real inline turn sent 5832 tokens: 56 tool
schemas and a 2257-token briefing. The on-device dialog model produced `SyntaxError` on every
`run_python` call, and at 1773 tokens it still wrote `df_norm` as `dfnorm` and changed the digits in
absolute notebook paths.

The cause is the GPU backend defaulting to FLOAT16 activations. CPU was exact at every size.
Measured against litert alone: `gpu/fp16, sp_tok=5500, tools=59` diverges at the first token;
`gpu/fp32` at the same sizes is exact. rishi 0.1.30 builds GPU engines with
`activation_data_type=FLOAT32` unless the caller names a dtype.

Before that fix the inline surface on a litert engine was cut to six tools and no skills, through an
`INLINE_TOOLS` allowlist, an `INLINE_DROP` routed through `Agent.budget`, and an `Assistant.frugal`
flag. Measured on gemma-e4b at a 16384 window, against the dialog fixture's prompt cell, with
`backend.pending_tokens`, which renders the string litert is actually sent:

| tools | briefing | wire |
|-------|----------|------|
| 56, full briefing | 2267 | 5890 |
| 10, no skill index | 865 | 1773 |
| 6, no skill index | 812 | 1401 |

`ramabana.agent.system_prompt` filters its rule list by the tool names on the table, so cutting
tools cut the briefing too. What was left was dominated by `skill_index`: 3870 characters
cataloguing 23 skills for a turn with no `read_skill` to open one.

The cut is reverted. It cost `notebook_approvals` on on-device inline prompt cells, because the
notebook tools were among those withheld, and it left those 23 skills unreachable. It bought
correctness only while the FLOAT16 default stood. On rishi 0.1.30 the same fixture passes end to end
with all 56 tools sent.

The band in `test_real_dialog_prompt_uses_a_16k_litert_engine` is 5600 to 6200, measured on the
restored path rather than inherited. It is large on purpose. Anyone who reads a slow inline turn as
a prompt-size fault should check the engine's activation dtype before cutting tools again.

## `leela/core/keys.py` `keymap_json`, `write_keymap`

`keymap_json` built `'keys': {k.action: k.key for k in ks}` over every action, so every writer left a
complete snapshot of all ~160 bindings in `keys.json`. Three writers did it: `leela --write-keymap`,
`/keys/reset`, and the keys panel's save button, which posted `Object.fromEntries(lee.keys.map(...))`
as the whole file.

The file then froze the map at the moment it was written. A user's `keys.json` held 100 entries, none
of which differed from leela's own chords. When `add_root` moved from `o` to `O` and `open_folder`
took `o`, the stale `"add_root": "o"` collided with the new default and `apply_overrides` refused it
on every launch: `keymap: add_root -> 'o' conflicts (...) — kept O`. Every future default that moves
collides the same way. The file's own `_help` said "Delete an entry to take leela's default", which
was only true of a file holding overrides.

`keys` now holds what differs from the defaults and nothing else. `only_changed` compares chords
through `_signature`, so case, surrounding whitespace and `mod` against `ctrl` do not read as a
change; `''` is compared like any other chord, so an unbind is kept. `_defaults` lists every action
and the chord leela ships it with. leela rewrites `_defaults` on each write and never reads it, so
the action names stay discoverable and none of them binds anything.

A file's entries are a person's choices, so `write_keymap` preserves them verbatim, including one
that repeats a default. The exception is a map naming more than 50 actions: no one edits that many by
hand, so it is one of leela's own dumps and its default-equal entries are pruned. `read_overrides`
runs first, so `_GENERATED_DEFAULT_MIGRATIONS` and `_SNAPSHOT_MIGRATIONS` move a legacy chord onto
today's default before the comparison, and the rewrite drops it rather than promoting it to a
permanent choice. `/keys/save` applies the same rule to what it is posted, so a stale bundle posting
the whole map cannot reinstate the fault. `guard` takes a copy before either write.

`/keys/reset` writes an empty override set. `reload` after it leaves `KEYS` equal to `DEFAULTS`.

The panel posts its base overrides merged with what was edited, minus anything that now equals the
default, so undoing a customisation removes the entry instead of writing a default-equal one.
`/keys/check` is sent the same merged map the save will write. `applied` adopts the `overrides` and
`text` the server hands back, so a save in a modal opened before a reset cannot undo that reset.

Out of scope, and still true: an explicit override that a later default lands on is refused with a
note. That is a real conflict between two chords a person can see, not a stale copy of a default.

## `leela/blocks/vars/app.py` `vars_promote`, and the tool tables `leela/app.py` kept

`/vars/promote` handed its accessor to dhrishti and returned whatever came back. Dhrishti's
`_promote` runs `bridge.client.ns()[name] = s.layer[name]`, which rebinds the owner namespace
without looking at what is there. So the `→live` button, the `p` key and the `variable` context
menu could replace a variable the user made, with no warning and nothing to undo it with, while
`WorkspaceHost.promote_var` refused the same collision before the kernel was asked.

The route now takes `replace`, and without it refuses at 409 with one sentence, the shape
`/refactor/apply` and the git routes answer a person with. The refusal is not the tool's. A model
must not overwrite the user's work, so `promote_var` refuses outright and never sends `replace`. A
person clicking `→live` on a name they own is deciding about their own namespace, so the pane can
send one, after `confirmDialog`. The pane is the only caller that can.

An accessor is a path, not a name. Dhrishti refuses any accessor of length other than 1 with `can
only promote a whole (top-level) variable`, so nothing below the top level can replace anything and
`_whole_name` returns None for it. Those requests pass through untouched and keep dhrishti's own
sentence.

Only a shadowed name is at stake. `/agent/api/info` carries `agent_names`, the agent layer alone,
and `/api/rows` is the owner namespace. A name in both would be replaced. A name in the owner
namespace alone cannot be promoted at all, and dhrishti answers `no agent variable`, so the pane
must not raise a dialog over it. In `live` scope, the pane's default, every row is an owner name,
and this is what keeps the ordinary gesture from turning into a confirmation.

A probe that does not answer counts against the promote, because `Kernel.api` returns None for a
timeout, a reset connection and a 403 alike, and reading that as an empty namespace is the silent
overwrite again. An inspector that answers neither probe is a different case: there is no inspector,
and `/api/promote` reports that for itself.

A successful promote drops the agent's shadow with `del <name>` in the overlay, as the tool does.
A promoted name left in both layers is outside the policy that refuses owner mutations, and the UI
path and the tool path must not leave different states.

`api()` in the client throws on any non-2xx and discards the status, so `promoteVar` used to lose
the sentence entirely. It now catches, asks `/vars` whether the name is really in the live
namespace, and only then offers the replace, the way `clearEngines` disambiguates its own 409.

Separately, `leela/app.py` held copies of `TOOL_GROUPS`, `tool_group` and `tool_preview` that
`leela/blocks/agent/turns.py` owns. Nothing called them. They had already drifted: `promote_var`
was added to the `turns.py` tables alone, so the two disagreed about a tool that exists. The copies
are deleted rather than repointed. `test_the_tool_tables_have_one_home` walks `leela/` and asserts
one definition of each, which no later copy can satisfy.

## `TurnRunner._pending`, and the pane that stayed busy until Leela was restarted

`start` registered its turn in `_pending` and waited `start_timeout` seconds for the worker to
report a run id. Only `_work`'s `finally` removed that entry, and it runs on the worker's thread.
A worker that never reported never reached it, so the entry stayed for the life of the process.
The first thing `start` checks is `if self._pending or ai.busy`, so every later send was refused
with `thread_busy` and a sentence about the assistant already working, when nothing was. Stop did
not help: it called `ai.cancel`, which answers `idle` when there is no run, and left `_pending`
alone. Restarting Leela was the only way out.

The turn that hangs is usually the one that failed. Ramabana's `Agent.stream` calls `_new_run`
before it loads the backend, and returns before `on_registered` when the load fails, so the run is
registered and `busy` is true while the reason sits unread in `ai.note`. `_work` now reports that:
a stream that ends with no run id fills `ready['error']` from the note, and the pane gets the
provider's own words at once instead of a silent thirty seconds. The timeout path names the note
too. Both say the turn was cleared and can be sent again.

The timeout path removes its own entry before it raises and cancels what the refused turn left
registered, so a slow start costs that turn and nothing else. A root run that is already over is
left alone: it belongs to a sub-agent still working, and `/agent/subagents` is where that is
stopped. A turn that reports late is unchanged by any of this. `ready['accepted']` was already the
answer to that question, and a turn nobody accepted cancels its own run and emits nothing. It
cancels the run rather than calling `ai.cancel`, which would take the shared approvals state with
it and drop a live turn's checkpoint.

`stop` drops any turn whose starter has gone, which is a gate opened on a turn nobody accepted, and
then cancels as before. A turn still streaming keeps its entry, because cancelling its run is what
stops it and the worker unwinds through the `finally` on its own. `ai.busy` with nothing pending is
a real thing, so a stop that clears nothing says `cleared: 0` rather than claiming otherwise.

`thread_busy` now names the age of the turn that is holding the conversation and says stop will
clear it. `start_timeout` stays at 30. Warm starts measure 1.67s and local models 3.85s to 7.9s.
The only start that legitimately runs longer is a cold local model downloading or first-loading
weights, which is unbounded, and needs progress reported rather than a larger number.

`registered` waited on the gate with no timeout. Every exit from `start` sets it, so nothing was
wrong yet, but one added `raise` between the wait and `ready['gate'].set()` would have parked a
worker for good with a run left non-terminal and `busy` true. It is bounded by `start_timeout` now,
and expiry counts as not accepted.

Upstream, `ramabana.Agent.stream` should call `on_registered` before it can return, or report the
failure through the same callback. Its first two exits are invisible to a caller that is waiting to
be told a run id. `Backend._tried` is the other half: a backend that failed to load once is never
retried, and nothing in Leela calls `Agent.retry`, so one transient outage costs every later turn
in that conversation the full start window.

## A folder that already has a window is not also a root of another one

One folder became one window earlier on this branch. `serve_ide` builds a `Workspace` per launch
folder, each with its own state file at `leela_cfg/workspaces/<slug>.json`. Nothing reconciled a
file written before that, when one window held every folder the user had ever opened. Launching
`ramabana` restored `roots` of `[ramabana, leela]` and opened both, and `leela` had a window and a
state file of its own.

`Workspace.load` now reconciles such a file once. A saved root is dropped when it opens as its own
window: `has_own_window` takes the root's slug from `workspaces/index.json`, falls back to the slug
its folder name would get, and drops the root only when `workspaces/<slug>.json` exists and lists
that same root among its own. The path is what matches, never the folder name, so a second checkout
named `leela` is kept while `leela.json` describes the first. The file's own state file is never a
match, so the launch folder is never dropped.

The rule cannot remove a folder that was added on purpose. `add_root` gives the added folder no
state file and no slug, so `has_own_window` says no. `state` writes `per_folder: True` and `load`
skips the reconcile for any file that carries it, so a folder added later stays even when it does
have a window elsewhere. The reconcile saves only when it dropped something, which is what keeps
the marker off files it left alone until they are next saved for another reason.

A tab saved under a dropped root does not reopen: `Sandbox._check` refuses a path outside the open
folders, and `load` already skips a tab it cannot open. `active_root` needed no change. It is
restored through `activate_root`, which resolves through `root_of`, and that already refuses a
folder the workspace does not own, so `project_root` falls back to the first open folder and the
Git pill follows it.

Two things this leaves. `journal_key` hashes the joined root list, so dropping a root moves
`history/<key>`, `trash/<key>`, `journals/<key>.json` and `timelines/<key>.json` for that window.
Adding or closing a folder has always moved them. And `/fs/add_root` calls `note_folder`, so a
folder added to one window is also launched as a window of its own next time, and the marker now
preserves the duplicate rather than resolving it. Either the add should not record a launch folder
under `--app`, or the launch should skip a folder that is already a root of another launched
workspace.

## A reused Chrome, and the pages Leela opened in it

Two reports about the inline browser, one cause each, both outliving Leela.

Chrome takes `--force-device-scale-factor` at launch. `Browser.cdp` passes `SCALE_FLAG` to
`cdp_connect`, and `cdp_connect` only passes it on when it has to start Chrome. A Chrome already
listening on the port is reused as it is. That Chrome rasterises a screencast frame at whatever
scale it was started with, for as long as it runs, and no reconnection changes it. Measured on
Chrome 151: with the flag a page reports `devicePixelRatio` 2 and layout viewports of 1000 and 500
CSS pixels; without it, 1 and 756/756.

`Browser._measure` reads that ratio, `layoutViewport.clientWidth / cssLayoutViewport.clientWidth`,
from the first page a session attaches to. The ratio is the browser's own scale factor. It reads
the same under the `Emulation.setDeviceMetricsOverride` that `resize` applies, where
`devicePixelRatio` reads back whatever the override said, which is why the ratio is the signal and
`devicePixelRatio` is not. A browser under `MAX_SCALE` sets `Browser.warning`. The `ready` frame on
`/browser/ws` carries `scale`, `note` and `browser`, and `warnScale` in `browser.js` shows the note
once per Chrome, keyed by the browser's DevTools id in `localStorage`. The note is repeated on
every `ready` so that a socket that fails mid-send is not the only time it was said.

Leela does not relaunch that Chrome and does not offer to. The user has pages open in it, including
pages Leela adopted, and a relaunch closes all of them for a difference in sharpness. Nor does
Leela read the browser's command line: a Chrome started without the flag on a Retina display
already rasterises at 2, and reading the flag would report a fault that is not there. What is
measured is the effect.

The Chrome that Leela itself launches under `--app-window` has this fault. `leela/app.py` opens the
window with `fossick.cdp.cdp_app(url, port=cdp_port)`, which passes no extra flags, and the inline
browser then reuses that same Chrome on that same port. Until `cdp_app` is given `SCALE_FLAG`, the
desktop shell is a 1x browser and the note is what the user sees.

`Browser._mine` was the set of targets Leela opened, and it lived on the `Browser` object. A page
opened by one Leela was not recognised by the next, `shut(tid, mine_only=True)` spared it, and it
could never be closed. Web tabs are `scratch`, so they are not saved either: after a restart the
only way back to such a page is `/browser/attach`, and closing that tab left the page open in
Chrome for the life of the browser.

The set is now written to `leela_cfg/browser/pages-<port>.json` as `{'browser': <id>, 'targets':
[...]}`. The id is the browser's own DevTools id, the last segment of its `webSocketDebuggerUrl`,
which Chrome mints anew at every launch. `Browser._own` runs on every connect. It clears the
in-memory set when a different browser answers on the port, reads the file only when the recorded
id matches the live one, and keeps only targets that are still open. `shut` connects before it
checks ownership, because that is when the file is read.

Nothing else can enter the set. An id is recorded only by `Browser.open`, from Leela's own
`Target.createTarget`. `/browser/attach` records nothing. A file that cannot be read, cannot be
written or names a different browser leaves the set empty, and an empty set closes nothing.
Ownership is given up only after `Target.closeTarget` has returned, so the two-second `wait_for` in
`_shut_page` cannot drop an id for a page that is still open. The write is atomic and merges with
what is already recorded, because the hub serves several workspaces from one process and each has
its own `Browser` on the same port.

Ownership lasts as long as the Chrome that holds the page. A page Leela opened, that the user then
navigated somewhere of their own and kept, is still Leela's to close until that Chrome quits.
Recording the URL would narrow this, and would put browsing history in `leela_cfg`.

## `leela/__init__.py` `extras_bin`
Nothing puts that directory on PATH, so a language server installed into a frozen app was installed correctly and then never found.

## `leela/app.py` `_git_pill_text`
It shipped as the literal `no git`, which is a claim that the folder is not a checkout. Any first paint the client does not reach leaves that claim on screen, and it is the one thing `cwd.js` refuses to say for a request it could not make. An unknown says so instead.

## `leela/app.py` `_state_label`
The badge read `state active` for every state there could be, so a person could not tell which charter the agent had been given, nor that it was the one they had just activated.

## `leela/app.py` `_warm_probes`
`available_models` reaches for every backend and `auth_status` asks every account: together they were most of a seven-second first paint of the model picker. On a thread, so a slow or absent network delays nothing.

## `leela/app.py` `ide_app.exec_history`
A kernel that will not start is answered, not raised: this route used to return a 500 with a traceback where every other route in this file answers with a failure the client can read.

## `leela/app.py` `ide_app.screen_native`
`getDisplayMedia` is how the browser does it, and WKWebView does not offer `navigator.mediaDevices` at all, so in the packaged app the shortcut and the Tools entry both failed with a TypeError. The server is on the same Mac as the display, which is the one thing that is true of the desktop app and not of a browser tab.

## `leela/blocks/agent/app.py` `connect.agent_subagents`
A delegated conversation is thrown away when it ends, so these recorded calls are the only account of it. An empty list is not the same answer as "it did nothing", so `records_sub_calls` says whether linkage has ever been seen to work here: the core stamps `parent_action_id` on a call made inside a delegation, and where a read-only sub-agent gets unwrapped tools nothing is stamped at all. Evidence rather than a version check, because no release has advertised this.

## `leela/blocks/agent/models.py` `catalog`
Both halves are probed together because the index is what makes a lookup a lookup: `selected` used to scan all ninety-odd rows resolving each one, three times per request, to answer which row a chosen model is.

## `leela/blocks/fs/ui.py` `git_tree_state`
Ignored files are in here too. Knowing that a file is deliberately not committed is the same question as knowing that one is missing, and only one of the two used to be answerable.

## `leela/blocks/search/search.py` `_Serial`
apsw binds a connection to whichever thread is inside it, and one handle is shared by every reader: `/search/stream` runs the fts, symbols and ann legs at once, and the agent searches while a person does. Four concurrent `context` calls lost one to `ThreadingViolationError`, and the leg reported the exception instead of its results. `db_lock` is litesearch's guard for this exact fault, keyed on the connection, so a caller arriving through either library waits on the same lock rather than on a second one that knows nothing about it. Both databases, always in the same order, because a composed retrieval reads the repository and the environment together.

A handle per thread is the other answer, and the wrong one here: a handle carries an embedding function, and `athreaded` hands work to a pool that is as wide as the machine.

A store is an object that is itself callable, so wrapping every callable attribute in a function replaced `code_st` with something that had no `rows_where`, and the symbol leg answered with that AttributeError on every search anyone ran. An attribute that is not a method is proxied instead of called: `k.code_st.rows_where(...)` and `k.codedb.t.store.fts_search(...)` reach the real thing, and reach it holding the same two locks.

## `leela/blocks/tabs/app.py` `connect.tab_reload`
Any open tab, not only the one on screen. A rolled-back turn restores files wherever they happen to be open, and this route used to refuse every path but the active tab's, so a notebook in a background tab kept the copy from before the restore in `docs` and wrote it back over the restored file at the next `/tabs/save-all`.

A tab with unsaved edits is held rather than dropped: a restore underneath somebody is not a reason to discard their typing. `bases` is armed for those instead, which is what makes `/tabs/save-all` refuse the write and send them to the tab to look at it. `force` is the deliberate "take what is on disk" that the reload command and the agent's own reloads mean.

## `leela/core/envs.py` `shell_env`
Interactive first. zsh reads `.zshrc` only for an interactive shell, and that is where an `OPENAI_API_KEY` usually lives, so a login-but-not-interactive shell answered with eight names and no key at all. Shells that refuse `-i` are asked again without it.

## `leela/core/session.py` `DocStore.doc_for`
What is held is a cache, and a change on disk drops it. A run arriving before the next mount then found nothing and answered `no notebook open`, for a notebook that is open.

## `leela/workspace.py` `Workspace.runtime_label`
The tab's own kernel is named by its key, so the pill says the same thing whether or not one is running. It used to take the kernel's own name when there was one and the tab's file name when there was not, so a notebook's kernel was `kosha` alive and `01_graph.ipynb` dead. A watched environment is another kernel entirely, and is named by that kernel.

## `leela/blocks/agent/turns.py` `tool_group`
`TOOL_GROUPS` was a hand-copy of shalya's `GROUPS` naming twenty tools, and shalya ships about fifty. Every git, memory, watch, api, skill and image tool fell through to `Other`, so a checkpoint form drew `git_status`, `remember` and `generate_image` in the same unnamed pile. Fixed by deriving the mapping from `shalya.tools.group_of`, which builds it from the factories rather than beside them. `LEELA_TOOLS` is the thirteen tools Leela adds, and a test asserts it is exactly what Leela's own factories build.

## `leela/blocks/agent/ai.py` `Assistant.memory_context`
`Completer._prompt` reached `self.a.ws.agent_memory_context(...)`. Nothing in Ramabana sets `Agent.ws`, so the call raised `AttributeError` into a bare `except` and a person's pinned notes never reached a completion prompt on any embedder but Leela, where it worked only because `Assistant` happens to carry `ws`. Fixed by `Agent.memory_context`, a hook every agent answers, which `Assistant` fills in. The briefing and the completer ask the same hook with different budgets.

## `leela/blocks/agent/models.py` `probe_dir`
The probe directory was briefly a module constant, which froze it at import. `leela_cfg` is replaced under a test, so a probe would have written into the directory of the run before it. Fixed by reading it per call, which is what the original `probe_path` did.

## `leela/blocks/search/search.py` `_rg`
The default ignore list was passed to ripgrep as `--glob '!{...}/**'`, which anchors to the working directory rather than to the searched root. For any root that was not the process's own directory it excluded nothing, and the noise weights in `relevance` were what actually demoted a hit in `node_modules`. Moving to `rgapi` made the skipping real, which silently deleted the demotion. Fixed by skipping only `__pycache__` by name and leaving the rest to `.gitignore` and the weights: a person searching for a vendored symbol wants it last, not missing.

## `leela/blocks/vault/clip.py` `_files`
A folder clip walked the folder with `rglob`, so a clip of a projects folder took in every virtualenv's `site-packages`, build output and test fixture: one clip of `vedicreader` counted 4,955 files. Fixed by walking with litesearch's `dir2files`, the walk vishalakshi's `add_dir` and folder acquisitions use, rather than a skip list of Leela's own.

`dir2files` also skips `docs/` and `examples/`, which hold the prose a folder clip is for. `_files` passes litesearch's own `skip_folder_re` with those two names taken out, so virtualenvs, dot-folders, build output and tests stay skipped and the list stays litesearch's.

## `leela/blocks/vault/clip.py` `clip_docs`
A folder clip could not be cancelled. It started without `_cancel`, so `Jobs.cancel` refused it, and `clip_docs` never asked whether to stop. Fixed by starting `clip` and `clip_tree` jobs, and a folder brought in through `/vault/acquire`, with `_cancel`, and by checking `Jobs.stopping` before each batch. A cancel lands after the batch in flight. The files clipped stay indexed, the job ends `cancelled` with the rest as `unread`, and resume clips only the rest from `_resume`. A GitHub, arXiv, YouTube or web acquisition is one vishalakshi call with no stop to ask, so its card offers no cancel.

A clip of 8 files or fewer was one batch, so a cancel always landed after the last file and the job finished `complete`. Fixed by `_batches`: the first file goes alone, then 2, 4 and 8 at a time. A cancel early in a clip lands after one file. A stop inside a batch would need a `stop` in litesearch's `add_dir`.

## `leela/blocks/vault/jobs.py` `Jobs.cancel`
The stop flag lived in one `Jobs` object's memory. Folderless workspaces share `jobs/no-folder.db`, so a cancel from a second workspace never reached the clip, and a cancel followed by a quit was lost: the next launch resumed the job. Fixed by writing the request to a `cancel_at` column, which `stopping` reads. A clip rewrites its `params` after every batch, so the request cannot live there. `recover` marks a row with `cancel_at` cancelled, and a resume claims a row only while `cancel_at` is empty. A fresh launch, such as a retry, clears it. `_init` adds the column to a jobs file from an earlier build, and `_row` drops a column it has no slot for, so this build keeps reading a file a later build has extended. A build from before this change raises on the new column, so it should not share a jobs file with this one. `cancel` writes only to a queued or running row.

A clip started before `_cancel` existed could not be cancelled. `Job.cancellable` is true for every `clip` and `clip_tree` job, and for an `acquire` whose action is `clip`, whatever the params hold.

## `leela/blocks/vault/jobs.py` `Jobs.recover`
`recover` left alone only the jobs its own process was running, which it knew from a set in memory. Folderless workspaces in every Leela process share `jobs/no-folder.db`, so a second Leela's `recover` failed, cancelled or restarted a job the first was still running. Fixed by an `owner` column, naming host, pid and a per-process nonce, and a `beat_at` column the running process rewrites every quarter of the stale window. `recover` takes only an active row whose owner is gone: no owner, a beat older than `stale` seconds (120, or `LEELA_JOB_STALE`), or, on this host, a pid that is not running. It takes the row by comparing the owner and beat it read, so two processes recovering at once take it once. `new` sets the owner, so a row between `new` and `launch` is not an orphan. A retry claims a running row whose owner is gone the same way.

A beat can go stale while its process lives, for example across a sleep. The process that takes the row over becomes its owner, and every write of the old run is conditional on owning the row, so the old run cannot overwrite the new one's progress, resume list or status. `stopping` answers True to the old run once another process owns its row, so it stops after the batch in flight. A job a quit leaves running gives up its owner, so the next launch resumes it at once. A requeued row launches within half the stale window. `_init` adds both columns to a jobs file from an earlier build. A row from such a build has no owner and is an orphan, so a build from before this change should not run beside this one. `recover` still runs only when a workspace opens, so a job whose process died stays running in a live Leela until the next one opens or a retry claims it.

## `leela/blocks/vault/acquire.py` `plan_tree`
A folder import walked with `rglob` and Leela's own `SKIP` list, so it clipped `tests/` and followed symlinked folders. Fixed by planning from `_files`, the walk a folder clip uses. `LEELA_VAULT_SKIP` now feeds that walk, matched in any case. The walk also leaves out `venv` and `site-packages`: with `docs` taken off litesearch's list, a plain `venv/` would give up every package's docs. The plan no longer lists what it left out, which only a second walk could find.

## `tests/test_packaging.py` `test_quitting_mid_clip_is_quick_and_leaves_no_forked_worker`
The test clipped 48 HTML files and waited for a pool, and none was ever seen. A pool was forked for every batch of eight. litesearch's `_parse_doc` only reads an HTML file's text in the worker, though, so each pool lived a few milliseconds. Converting, chunking and embedding run in the app's own process, and that is where a clip's CPU goes. Fixed by clipping PDFs, which the workers do parse, so the pool stays up for seconds.
