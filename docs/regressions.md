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

## `leela/desktop.py` `_OpenHandler`
An Objective-C subclass used `super().init()`, which has no `init` to find. Registration raised on every launch and nothing opened a folder dropped on the Dock or chosen through Open With. Fixed with `objc.super`.

## `leela/desktop.py` `_dock_delegates`
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

## `tools/build_icons.py` `MARKS`, `favicon`
One mark on one plate could not answer a tab strip whose colour the browser picks. The artwork is now the two whole turtle drawings plus `leela-turtle-mask`, the line work's silhouette, used as an alpha channel so the ink comes out on its own. Two favicons are generated and served under `prefers-color-scheme`; the app icon stays the cream ink, which is what reads on the navy plate. `packaging/assets/leela-mark.png` is the previous mark and nothing draws from it now.

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
