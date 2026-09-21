# Decisions

The reasoning that chose the shape of the code, kept here rather than in the source. Each entry names the file and the symbol, then states the constraint, the trade-off or the alternative rejected. Reading the entry for a symbol before rewriting it keeps that reasoning available.

`regressions.md` is the companion. A fault the code still guards against, and the fix that holds it off, goes there.

## `leela/__init__.py` `use_extras`
First, so a backend installed there later beats a stale copy inside the bundle.

## `leela/app.py` `_md_highlight`
mdhtml's highlighting is the `hl` extra. Asking for it without `fastpylight` installed renders the same plain code and adds a warning about a missing package to every render, which the editor then shows the person as a problem with their Markdown.

## `leela/app.py` `ide_app._completions_snippets`
One store holds every project's events (`completions_dir` is under `leela_cfg`), and `effective` lets a workspace override the user. Reading the effective value would let a `snippets` turned on in one project serve selections recorded in every other.

## `leela/app.py` `ide_app.ai_events`
Client-owned, like the search events it shares a store with: the outcome is a click in the browser and the server never learns of it otherwise. Recording never fails the panel.

## `leela/app.py` `ide_app.ai_completions`
`no-store`, because the rows carry the person's own selections and suggestions and this is a GET the window would otherwise be free to keep on disk.

## `leela/blocks/agent/ai.py` `api_context`
Without it the agent re-loads a spec the page already loaded, guesses at group names, and discovers a local-only api by being refused. Header names only: a value never reaches a briefing.

## `leela/blocks/agent/ai.py` `WorkspaceHost.api_keyed`
Read off the index rather than the values, so a keyless spec marked local-only is here too.

## `leela/blocks/agent/ai.py` `WorkspaceHost.nb_run_cell`
The file is left alone: the outputs come back to the caller rather than to disk. The bindings it reports are the merged view before and after, so a rebind shows as well as a new name.

## `leela/blocks/agent/ai.py` `WorkspaceHost._start_kernel`
Tools run on the turn's own thread, so this hands the work to the loop that owns the kernels and waits. Called on that loop there is nothing to wait for, and the peek stands.

## `leela/blocks/agent/ai.py` `WorkspaceHost._partial`
An exception on its own read as though nothing had happened, and the expensive half of the call had already happened. A live kernel cannot roll back printed output or bound names, so it reports them.

## `leela/blocks/agent/ai.py` `Assistant.turn_capabilities`
`known` is whether this process holds anything for the turn at all. Checkpoints and transactions live in memory, and `MAX_CHECKPOINTS` bounds the checkpoints, so a turn from a restart ago or from far enough back in this session has no boundary to branch at. That is a different answer from "this turn changed nothing", and the pane says so.

## `leela/blocks/agent/app.py` `connect.api_peek`
`ws.runtime()` starts a kernel, which is over a second, and a read that only decorates its answer must not be what starts one: listing conversations booted Python to ask it nothing the list could not do without.

## `leela/blocks/agent/app.py` `connect.agent_resume`
`latest` is the newest conversation this Leela started, which is what its history list shows. One log holds Leela's and the CLI's, most of it is the CLI's, and taking the newest of both opened a conversation the pane is filtered to hide. A log with nothing marked falls back to the newest of all rather than opening nothing: the mark is recent, and everything written before it exists reads as the CLI's. `everything` asks for the newest of both, the name the history list already uses for it.

## `leela/blocks/agent/app.py` `connect.agent_models`
Probing what is installed costs seconds on a cold machine and the answer barely moves, so the catalog comes from `probed` and `refresh=1` is what asks for a new one. Which model each routed job is on is this workspace's own state and is read fresh every time.

## `leela/blocks/agent/app.py` `connect._state_origin`
States are kept in the one store every workspace shares, so the list has always held other projects' as well. Nothing said so, and a row that reads `Working state` and a date is not something anyone can reuse deliberately.

## `leela/blocks/agent/app.py` `connect.agent_states`
`scope=project` narrows to states saved from these folders; the default is every one this machine has, which is what makes another project's charter reusable here.

## `leela/blocks/agent/app.py` `connect.agent_status`
`busy` came from the core alone, which knows nothing of the gate that refuses a prompt, so a conversation held by a turn the core had already finished with reported itself ready. `held` is that gate's own reason, and it is what makes this `busy` true.

## `leela/blocks/agent/app.py` `connect.agent_run_steer`
A sub-agent cannot see the conversation that would otherwise correct it, so stopping one that had gone wrong was the only thing a person could do to it.

## `leela/blocks/agent/app.py` `connect.agent_steer`
`force` cancels the foreground run and returns the unsent text. A queued steer waits for a tool call, and a turn writing its answer never makes another one.

## `leela/blocks/agent/app.py` `connect.agent_conversation_notebook`
A cell per part, in order, with the part id and its kind in the cell metadata so the edits can be read back. Prose is editable; a call and its result are there to be read or deleted, never reworded, so they are written as raw cells a person can remove but not fake.

## `leela/blocks/agent/app.py` `connect.agent_conversation_reshape`
A part whose cell is gone is discarded; a prose part whose text changed is rewritten. The notebook is a view of the conversation, so anything it cannot say is simply not said.

## `leela/blocks/agent/completions.py` module
Accepting or discarding a suggestion is the plainest preference signal in the IDE: a person read the proposal beside their own code and said yes or no. `blocks/search/signals.py` already stores events of this shape, so this names the columns and reuses it.

## `leela/blocks/agent/completions.py` `summary`
Only the outcomes are counted, never the asks: an ask with no outcome is a panel still open or one abandoned, and dividing by it would report a rejection nobody made.

## `leela/blocks/agent/completions.py` `judgements`
Built from the asks rather than from the outcomes, so an ask still open, one abandoned, and one whose model failed are all here. `summary` counts only decided ones, which is right for a rate and wrong for a log.

Rows join on `ask_id`, and an id is only an id when it is non-empty. No ask carried one before the browser began minting them, and an ask can also fall outside the window `read` returns while its verdict stays inside it. Both come back `orphan`, alone but whole: an unjoined ask still holds the instruction, which is the field most worth reading.

`snippets` is the reader's gate, not the writer's. `text` and `reply` are the person's own code, and `Signals.record` refuses to write them unless the preference was on, so a row can be bare because nothing was kept or because this caller may not have it. `code` says which.

## `leela/blocks/agent/threads.py` `TurnRunner._retain`
`_prepare` is what mints that id, so a turn that died before it reached the core still carries the previous turn's, and the write would land on top of what that turn saved.

## `leela/blocks/agent/threads.py` `TurnRunner._cleared`
The worker has nothing left to say, but the feed still has to settle: a reader waiting on `finished` has no other way to learn the turn is over, and `stop` returning 200 is not one.

## `leela/blocks/agent/threads.py` `TurnRunner._reap`
The gate is Leela's and `busy` is the core's, so a turn whose run has gone terminal while its worker sits in the provider's stream held the conversation with nothing behind it. A worker that has exited leaked its entry outright. Neither is a turn, so neither keeps the gate shut.

## `leela/blocks/agent/threads.py` `TurnRunner.held`
The pane reads this rather than the core's `busy`, so what it shows cannot contradict what `start` does.

## `leela/blocks/agent/threads.py` `TurnRunner.stop`
`cancel` reaches a turn between steps, so a worker parked in a provider's stream does not feel it. A foreground stop therefore drops the gate itself, which is what its own refusal message promises. Stopping one named run leaves the rest of the conversation as it was.

## `leela/blocks/agent/turns.py` `latest_started_here`
Ramabana's `latest` is the newest in the log, and one log holds Leela's conversations and the CLI's, so on a machine that uses both it is usually the CLI's. Empty when nothing here is marked, which is a log the filter has nothing to say about rather than an error.

## `leela/blocks/agent/turns.py` `with_capabilities`
The live `done` payload was the only place these reached the browser, so undo, restore and revise disappeared on every repaint that rebuilt from the turn log.

## `leela/blocks/agent/turns.py` `history_sessions`
`app` is `leela` for a session `started_here` records, `ramabana` for the rest. Only Leela marks the shared log, so history written before the mark existed reads as the CLI's.

## `leela/blocks/browser/app.py` `connect.browser_external`
The CDP Chrome is a fresh automation profile that sites like Medium answer with a bot wall.

## `leela/blocks/browser/browser.py` `Browser._remember`
Best effort. A file that cannot be written costs a page that stays open, never a page closed by mistake. The write is atomic, so a torn file cannot name a target either.

## `leela/blocks/browser/browser.py` `Browser._measure`
The ratio between the two layout viewports is the browser's own scale factor. Unlike `devicePixelRatio` it reads the same under an `Emulation` override, so `resize` cannot move it. `SCALE_FLAG` only takes at launch, so a Chrome that answers at 1x answers at 1x for as long as it runs.

## `leela/blocks/browser/browser.py` `Browser.quit`
One that was already answering on the port when Leela connected is somebody else's, and outlives it. The graceful CDP close is the only handle there is: `cdp_connect` starts Chrome in its own session and keeps no pid, so a browser left running cannot be signalled.

## `leela/blocks/browser/browser.py` `Browser.shut`
The connection comes first, because the set of pages Leela opened is read from disk when it is made. A previous Leela's page is only recognised as Leela's own after that. Ownership is given up once Chrome has closed the target, so a close that fails or is cancelled leaves the page closeable.

## `leela/blocks/fs/app.py` `_forget`
`/tab/state` prefers a cached buffer over the disk, so a path that is reused later served the old file's text and saving put it back. A tab left on a path that no longer exists saves to a `missing` disk version, which the client offers to force through, recreating the file under the name it was renamed away from.

## `leela/blocks/fs/app.py` `_freshen`
`/tab/state` serves what `DocStore` holds, and only the active tab's poll ever refreshed it, so a background tab mounted the version from before the change. A tab with unsaved edits keeps what it holds: the cache is the user's work, not a copy of the file.

## `leela/blocks/fs/app.py` `connect.fs_paths`
`relative` is against the open folder holding it. A path under no open folder has no relative form.

## `leela/blocks/fs/app.py` `connect.fs_move`
One row per path that actually moved, so a partial failure is still reversible and the failures come back named rather than as one exception for the whole selection.

## `leela/blocks/fs/fs.py` `Sandbox.take`
What `delete` means for anything a journal resource cannot hold: a directory, or a file that is not text. Same guards, and the listing cache is dropped the same way.

## `leela/blocks/fs/ui.py` `_folder_class`
A folder you have just created is entirely untracked, and every row inside it is out of sight until you open it. Rolling the state up is what makes `which ones am I missing` answerable without expanding the tree.

## `leela/blocks/git/app.py` `_guard_batch`
The whole batch is checked before a single file is written, so a stale file refuses the batch rather than half-applying it: `resolve_safe_conflicts` writes and stages one file at a time, and `_rollback` puts back what it can rather than what it must.

## `leela/blocks/git/app.py` `connect.git_tree_prepare`
`git add` already honours `.gitignore`; a folder you just made does not have one, which is the whole difficulty. This writes the rules the folder's project kinds need -- and only the ones git says are missing -- and then stages, so `target/` and `__pycache__` never have to be noticed one at a time.

## `leela/blocks/git/git.py` `_project_env`
`None` handed git the app's own environment, so in the bundle a Python `filter.clean` -- nbdev's cleaner, pre-commit -- ran against the bundle's standard library and died on every staging.

## `leela/blocks/git/git.py` `GitRepo.notebook_conflict`
The worktree file carries conflict markers, which make a notebook unreadable and say nothing about cells. Git keeps all three sides in the index as whole notebooks, so those are what is read: a person answers about cells, not about JSON.

## `leela/blocks/git/ignores.py` module
Staging a folder is `git add`, which honours `.gitignore` -- so the whole problem is that a folder you have just created does not have one yet. `target/`, `dist/`, `__pycache__` and `node_modules` then go in with everything else, and a person meeting the language for the first time has no way to know which of the files in front of them belong.

Git is asked rather than guessed at: `check-ignore` says whether a rule already covers a path, so a repository whose ignores are already right is left alone.

## `leela/blocks/git/ignores.py` `prepare`
The rules go in the folder's own `.gitignore`, not the repository's. `/target/` at the root of a repository does not match `mycrate/target/`, so a crate in a subfolder written the other way would ignore nothing at all -- and a crate carrying its own ignores is what every crate does anyway, and survives being moved into another repository.

Returns `{'kinds', 'added', 'path'}`. `added` is empty when the rules are already there, which is the common case on the second run and on a checkout someone else set up.

## `leela/blocks/git/repos.py` `repo_for`
The chosen folder is taken only when it is itself a checkout. A folder of checkouts -- a directory of clones, opened to work across them -- is not one, and answering with it made every Git surface say the folder is not a repository while every file open inside it was in one. Falling through to the tab is what makes the panel follow the file from repository to repository, which is the same rule the pill and the tree badges already describe.

## `leela/blocks/keys/app.py` `connect.keys_save`
A map naming every action is one an older client dumped, so its default-equal entries are pruned rather than frozen against the next default that moves.

## `leela/blocks/keys/app.py` `connect.keys_check`
Runs the save's own `apply_overrides` on a throwaway note list, so the warnings cannot drift from what saving rejects.

## `leela/blocks/memory/memory.py` `_why_no_vault`
The vault reaches its own model through `rishi.litert`, so where LiteRT is not installed the failure arrives as `No module named 'litert_lm'`, which says nothing about memory and nothing about the remedy. The packaged app is exactly that case: the runtime is a download, not part of the bundle.

## `leela/blocks/nb/app.py` `_rebase_notebook`
Returns the cells whose source moved on both sides, `[]` when the rebase is clean, or None when it cannot be attempted at all and the caller should refuse the save. Cells are matched by id, because an external write may have added or removed one and shifted every index after it.

## `leela/blocks/nb/app.py` `connect.nb_language`
The notebook's kernelspec is the only record of it, so setting one writes the file. The runtime a tab already holds is for the old language, so it goes; the next run starts the one this notebook now names.

## `leela/blocks/nb/app.py` `connect.nb_interrupt`
A prompt cell is not in a kernel: it is a turn of the inline agent, and it was answered here with `that cell is not running` while it plainly was. The agent has a stop of its own -- refuse the calls still to come, release the one already waiting -- and that is what Stop means for a prompt.

## `leela/blocks/nb/nb.py` `merge_rows`
Git holds all three sides of a conflict in the index as whole notebooks, so nothing here reads the markers in the worktree file: they make a notebook unreadable and say nothing about cells. Cells are matched by their own id where a notebook has them, and by position where it does not.

`state` is what a person has to answer: `both` needs a decision, `added` and `deleted` need one, and the rest are context.

## `leela/blocks/nb/nb.py` `merged_cells`
A cell somebody decided about comes back without its outputs: they were produced by a version of the source that no longer exists. A cell nobody had to decide about is untouched.

## `leela/blocks/nb/nb.py` `Notebook.split_symbols`
The cell's own directives go on top of every part, so splitting an `#| export` cell leaves every part exported and a test cell can go under each. `default_exp` and its kind name the notebook rather than the cell, so they are not copied and they hold the original cell open. Whatever was not a class or a function stays where it was, above. No part ends in a newline: a cell source that does draws an empty line under itself in the editor.

## `leela/blocks/pipelines/app.py` `nbdev_config`
`nbdev_project` decides; `get_config` is only asked for the paths, because on its own it answers with defaults rather than nothing and any folder with a `pyproject.toml` passes.

## `leela/blocks/pipelines/pipelines.py` `uv_argv`
What the terminal does. uv syncs the lock before it runs anything, so a venv that has drifted is repaired rather than failing halfway through with an import error.

## `leela/blocks/pipelines/pipelines.py` `release_flow`
Rust is asked before fastship, because a maturin crate has a `pyproject.toml` too and the fastship flow would try to `ship-pypi` a wheel that only the runners can build.

## `leela/blocks/runtime/app.py` `connect.runtime_engines_clear`
Weights outlive the chats built on them, so the memory is held until something asks for it.

## `leela/blocks/runtime/app.py` `connect.runtime_inspector`
Separate from `/runtime/support`, which `/runtime/create` also calls: a folder that gets a `.venv` without being asked should not also get numpy and pandas without being asked.

## `leela/blocks/runtime/devserver.py` `_boot_src`
`-m` fails because the module is not on that interpreter's path yet. PYTHONPATH *prepends*, so leela's copy of fasthtml would shadow the project's own.

## `leela/blocks/runtime/engines.py` module
One engine, many chats, outliving all of them. `RishiBackend` takes it as `engine=`. Unlike a kernel namespace an idle engine is only a cache entry, so it is evicted and reloaded. A live one is kept.

## `leela/blocks/runtime/engines.py` `_model_cls`
`get_runtime` is asked for a runtime and never sees the model, and `MlxChat.__new__` re-routes a vision repo to `MlxVlmChat`, which loads with mlx-vlm instead of mlx-lm. Rishi's own `Chat` dispatches through `__new__` for that reason, so this asks its question the way it asks it.

## `leela/blocks/runtime/engines.py` `engine_kw`
Rishi takes engine and conversation options through one signature, so `create_engine` says which are its own. A runtime that loads nothing in this process has none to name.

## `leela/blocks/runtime/engines.py` `engine_key`
Two workspaces on one model with different context limits or accelerators need two engines. So do two chat classes on one repo: `vlm=False` sends an mlx vision model down the text loader, and the two loaders build engines that are not interchangeable.

## `leela/blocks/runtime/engines.py` `EngineBroker._cls_for`
Rishi sniffs the model's `config.json` through the hub, which is half a second to two on a warm cache, and `attach` runs on every turn. `model_path` and `vlm` are what `MlxChat.__new__` reads besides the model id.

## `leela/blocks/runtime/engines.py` `EngineBroker.drop`
Needed when the accelerator changes, and when a person asks for the memory back.

## `leela/blocks/runtime/kernels.py` `venv_env`
A frozen app starts from `clean_env`. py2app points `PYTHONPATH`, `PYTHONHOME` and `__PYVENV_LAUNCHER__` at the bundle so its own helper starts, and a child that keeps them imports the bundle's standard library under another interpreter. `nbdev-test` run from the app died inside `linecache` doing exactly that, before it could report a single notebook.

## `leela/blocks/runtime/kernels.py` `find_pythons`
`current` is what `python_for` resolved for the open tab, which the walk up can find deeper than a folder of checkouts is scanned. Listing it is what makes the picker able to mark it.

## `leela/blocks/runtime/kernels.py` `missing_kernel_module`
A venv without it exits before the first message, and jupyter_client can only report that the kernel died before replying to `kernel_info`. Asked here, the environment says which module it is short of. Only the failure path pays for this.

## `leela/blocks/runtime/kernels.py` `_spec`
Python is the language Leela pins an interpreter for. Any other language runs whatever kernelspec is installed for it, unmodified, because there is no venv of ours to point it at.

## `leela/blocks/runtime/kernels.py` `KernelPool._class_for`
The gateway transport carries Python. A language Leela runs itself has no wire protocol to put through it, so it stays in this process whichever transport the workspace picked.

## `leela/blocks/runtime/runners.py` module
Both present the `Kernel` surface `execute`/`interrupt`/`restart`/`shutdown`, so `/nb/run`, `/nb/run/stream` and `Notebook.run` reach them unchanged. Neither has a namespace dhrishti can read, so `base` stays None and the Variables pane says so rather than showing an empty tree.

## `leela/blocks/runtime/runners.py` `rust_chunks`
Brace depth decides, and strings, chars and comments are skipped so a `}` inside one does not close a block. A raw string holding an unbalanced brace is the case this does not see.

## `leela/blocks/runtime/runners.py` `CargoRunner`
A cell that defines things adds them to the crate; a cell that does things becomes the body of `main`. The compiler is the point: its diagnostics come back as the cell's error output, with the code (`E0382`) as the error name and rustc's own rendering as the traceback.

## `leela/blocks/runtime/runners.py` `NodeRunner`
Every cell runs in the same `vm` context, so `let`, `function` and `class` from one cell are there in the next. `driver.mjs` is the other half of this: it owns the context, the console capture and the newline-delimited JSON both sides speak.

## `leela/blocks/runtime/support.py` `work_dir`
A double-clicked app inherits `/` as its working directory, and one started from `open` inherits the bundle, which is read-only and code-signed. Either way a kernel launched there cannot write a file beside itself, and the error it gives says nothing about why.

## `leela/blocks/runtime/support.py` `inspector_support`
Asked of the pinned dhrishti itself rather than of a list of package names, so a dependency added upstream is answered for too, and so the answer includes what stopped it.

## `leela/blocks/runtime/support.py` `as_installed`
Leela's own environment is the one combination of these that is known to start a kernel: it is resolved from a lock and every release is tested against it. Asking an index for the newest of each instead is what produced `ipymini 0.1.20` beside `kernmini 0.1.9`, which import each other and do not fit. When Leela upgrades, so does what it installs.

## `leela/blocks/runtime/support.py` `install_kernel_support`
An installer that returned 0 and left a kernel that will not import is a failure of the packages, not of the installer, and saying so is the difference between a report about `ipymini` and one about the `pip` a uv environment was never going to have.

## `leela/blocks/search/app.py` `connect.scope_roots`
The checkout, not the folder that is open: with a folder of clones open the two options in the picker named the same thing, and the indexed legs already answered from one repo while ripgrep answered from all of them.

## `leela/blocks/search/search.py` `Search.kosha_root`
The walk the interpreter already takes. One folder of checkouts opened as one root holds an index per repo, and the repo a file sits in is the repo that indexed it, so reading the folder's own index reads one nothing ever built. The walk stops at the open folder, because a checkout above the workspace is somebody else's.

## `leela/blocks/search/search.py` `Search._kosha`
Tried once per checkout, since retrying on every keystroke would stall the search. Moving to a file in another repo is what makes it try again, and what it tries is that repo's index.

## `leela/blocks/search/search.py` `Search.env_roots`
Without them a lookup on an imported symbol can only offer the import lines that mention it.

## `leela/blocks/search/search.py` `Search.env_definitions`
Ripgrep needs nothing to be fresh, so it answers when the index is missing or stale for a package installed since the last sync. The search is cased either way: insensitive, a lookup on `store_attr` answers with `STORE_ATTR` from vendored stubs.

## `leela/blocks/search/search.py` `Search.env_module`
The basename cannot say which one: two packages both offer a `document.py`. `__init__` is dropped because the module is its folder.

## `leela/blocks/search/search.py` `Search.env_symbols`
A path prefix guesses which package a file belongs to, and a namespace package, a vendored copy or an editable install each break that guess.

## `leela/blocks/search/signals.py` module
The event log is the exact record and the vault holds one document per session. `docs/search.md` says why there are two.

## `leela/blocks/settings/settings.py` `agent_cfg`
Ramabana writes `<history_name>-history.jsonl` and its sidecars here. A folder that cannot be made raises rather than becoming a second empty log.

## `leela/blocks/settings/settings.py` `Settings.layers`
`origins` answers with the one layer in charge, which cannot warn you about a layer you are not looking at: editing all languages, nothing said that a `languages.python` block held the same key and would win. This says all of them and lets the panel decide.

## `leela/blocks/tabs/app.py` `disk_version`
`nbdev_clean` rewrites a notebook it has nothing to change, and every tool that formats in place does the same. On an mtime the rewrite read as an outside write and the next save was a conflict.

## `leela/blocks/tabs/app.py` `_shut_page`
A page adopted from the user's own Chrome is theirs and stays open. No Chrome is started to close a page, and a wedged one cannot hold the tab strip: the tab is already closed either way.

## `leela/blocks/tabs/app.py` `connect.keep_outside_write`
This poll is the only place another process's edit to an open file is noticed, and the editor's next move is to load it over what is there.

## `leela/blocks/tabs/app.py` `connect.tab_strip`
Deleting a folder and removing a root both close tabs server-side, and the strip is index-addressed, so leaving it stale meant the next click selected and closed the wrong document. Every other route that moves a tab already answers with this.

## `leela/blocks/term/app.py` `term_project`
A shell is one long-lived process and cannot follow anything by itself. Naming the checkout it was opened in is what lets the client keep one per checkout, rather than one shell that stays where the first project was.

## `leela/blocks/vars/app.py` `connect.vars_route`
This polls every 2.5 seconds from load, and it asked `session.runtime()`, which starts one. A pane that lists what is in memory must not be the thing that creates the memory: with no kernel there are no variables, which is what it already draws.

## `leela/blocks/vault/app.py` `connect.apis_call`
`api_fetch`, not `api_call`: the reach gate is about a model reading the answer, and this is the person whose data it is.

## `leela/blocks/vault/spec.py` `expand`
The reference is what is stored, so rotating the variable rotates the credential. A name with nothing behind it is refused here: a literal `${…}` sent as a key comes back as a bare 401.

## `leela/core/backups.py` module
The conversation log, its sidecars, saved workspaces, keymaps and notes are appended to or replaced in place, and nothing else holds a second copy. Copies are taken on a cadence and before anything overwrites the log. Each is one gzipped tar with a JSON manifest beside it. What goes in is a person's choice.

## `leela/core/backups.py` `agent_source`
With `agent.configFolder` empty this is the config dir, so an existing install is unchanged.

## `leela/core/backups.py` `_add_entry`
A `.db` in WAL mode is three files that change independently, so copying them one after another can capture a set that never existed together. A copied `-shm` confuses recovery; SQLite rebuilds it anyway.

## `leela/core/backups.py` `clean_dates`
Tiered rather than "last n", so a mistake noticed a month later still has something to go back to.

## `leela/core/backups.py` `restore`
Restoring is itself a write over live state, so a restore of the wrong backup does not lose a conversation. ## `leela/core/backups.py` `schedule_backups`
## `leela/core/envs.py` `apply_stored_env`
Last, and winning: this is the escape hatch for a machine where asking the shell gives the wrong answer, so a value typed into Leela has to beat the one that is already wrong.

## `leela/core/envs.py` `env_rows`
Leela's own, the names the model backends read, and anything already in the environment that looks like a credential. A secret's value never leaves the server; that it is set does.

## `leela/core/envs.py` `strip_bundle`
Outside a bundle this returns what it was given, untouched: a caller that claimed nothing about an environment still claims nothing, which is what `venv_env(None, env)` and git's `env_for` both promise.

## `leela/core/envs.py` `preferred_shell`
`$SHELL` is the shell the login record names, which is not always the one a person uses. Leela already has somewhere to say otherwise, and the terminal reads it, so this reads the same place rather than adding a second answer to one question.

## `leela/core/envs.py` `import_login_env`
An app opened from Finder inherits launchd's environment rather than a shell's, so an `OPENAI_API_KEY` exported from a shell profile is invisible to it while the same Leela started from a terminal sees it. Names this process already has are kept: nothing the launcher chose is overwritten, `PATH` included, which only gains the directories the shell knows about.

## `leela/core/langs.py` module
Every block that has to ask "what is this language" asks here: `runtime` for what starts a cell, `lsp` for what answers hover and diagnostics, `nb` for what a notebook's kernelspec means. `blocks.fs.LANGS` is a wider map and a different question -- what to highlight -- and stays there.

## `leela/core/projects.py` `nearest_marked`
One walk, because a workspace has several answers keyed to the same question and they have to agree: which interpreter a kernel starts in, which index a search reads, which checkout a release runs in. `stop` is the open folder, and the walk does not pass it: what is above the workspace belongs to something else. `markers` are relative paths, so `.venv/bin/python` asks about a file and `.git` asks about a directory.

## `leela/core/projects.py` `_temporary`
A folder there is a test's, a probe's or an unpacked archive's, and none of them is a project a person wants reopened next launch. One of them written into the session is a folder they then have to close by hand, in every window.

## `leela/core/projects.py` `_lasting`
A test names its own file and may keep whatever it likes in it. The real session is the one that must never fill up with a suite's scratch folders, which is how eleven `tmp…` directories came to be sitting in somebody's window.

## `leela/core/session.py` `Origins`
A variable in the panel is the end of something, and reading it says nothing about which cell or tool put it there, or whether the run that did went on to raise afterwards.

## `leela/core/session.py` `FileHistory`
The loss happens before a commit, often from another process editing the same tree, so git cannot cover it. Bodies are stored once per distinct content.

## `leela/hub.py` `_name`
`vruksha.localhost.` is `vruksha.localhost` written absolutely, which is what a browser sends when a search domain has made the short form ambiguous. Reading the two as different names turned choosing a workspace from the folder list into `invalid Host header`.

## `leela/hub.py` `WorkspaceHub._noted`
A folder opened as a site is reopened at launch and offered by the welcome screen only if this runs; noting it in the shell left a browser opening the same folder with neither.

## `leela/workspace.py` `_session_lock`
Advisory, and best effort: a platform without `flock`, or a lock nobody releases, gives the caller the write anyway. A save that races is a worse session than one that does not; a save that never happens is no session at all.

## `leela/workspace.py` `Workspace.start_backups`
Not in `__init__`: a test that builds a hundred workspaces would start a hundred threads.

## `leela/workspace.py` `Workspace._timelines`
Every reader parsed the whole document. It reaches several megabytes, `with_timelines` runs on the history list and on every thread switch, and `save_timeline` read it again before each write.

## `leela/workspace.py` `Workspace._retained`
`reduceAgentTimeline` concatenates consecutive `chunk` events into one block of prose, and keeps one part per `action_id` holding the newest payload, at the position where that call first appeared. Every other row it is handed is read and dropped. Retaining them cost 15MB across six workspaces, 95% of the rows, and a parse and a serialise of all of it per turn.

A row with no id has no identity to update, so it can only ever be new.

## `leela/workspace.py` `Workspace.fresh_history`
Parsing is linear in its size, which reaches 60MB once Leela and the CLI share one. A stat tells an unchanged log from a written one.

## `leela/workspace.py` `Workspace.selection_ai`
The inline model, the same one prompt cells use, because this is inline help and not the ghost-text completion the `completion` model answers for. Which one answered is on the panel's header, and the settings say which surface each model serves. `readonly` takes the tools off the list the model is given rather than asking it not to reach for them, so the panel's promise that nothing changes until Replace is one the agent cannot break. Approvals are passed explicitly: the default would resolve `ws.approvals`, which builds the agent pane's thread to answer.

The chosen inline model is applied on every access. The assistant is built once, and a model change made after that reaches it here rather than at the next restart.

## `leela/workspace.py` `Workspace.project_repo`
`project_root` is the folder that is open, which is not always a checkout. A folder of clones opened to work across them is not one, and acting on it put a `.venv`, a run configuration and a release beside the clones instead of inside the one being worked on. The walk is the one the interpreter and the code index already take.

## `leela/workspace.py` `Workspace._name_exists`
The merged view is what the agent sees. Only the user's own namespace answers the question a prompt cell asks, which is whether the next cell can use the name.

## `leela/workspace.py` `Workspace.lsp_for`
One per language *and* root: a server is rooted where it reads the project's configuration from, and a folder of clones holds neither a `Cargo.toml` nor a `pyproject.toml` of its own. Keyed by both, so moving to a file in another repo starts that repo's server rather than going on asking one rooted beside the clones.

## `leela/workspace.py` `Workspace._merge_roots`
One file, several windows. Overwriting the list meant the last window to save decided what every other one would come back to, so opening the app on one folder emptied a session that had four.

## `leela/blocks/agent/threads.py` `Thread.name`
A card is named the moment a turn starts, rather than waiting for the summariser, the sidecar, or the turn to reach the log.

## `leela/blocks/search/search.py` `Search.features`
`leg_rank` normalises the backend's own ordering, whose raw scores are pagerank, FTS rank and cosine distance and so are not comparable across legs.

## `leela/blocks/agent/app.py` `connect.agent_conversation_parts`
Read from the turn log, so a conversation that was just resumed can be reshaped like any other.

## `leela/blocks/agent/ai.py` `Assistant._be`
Attached before the backend builds its chat, so rishi borrows it.

## `leela/blocks/search/search.py` `Weights`
One weight per leg, one per lexical feature, so a hit's score is `sum(weight * feature)` and the client can re-rank without asking again.

## `leela/blocks/agent/app.py` `connect._settled_thread`
Reshaping context under a live run or an unanswered checkpoint would change the question the model is already answering.

## `leela/blocks/agent/app.py` `connect.agent_undo_turn`
The turn stays in canonical history, and files are a separate, explicit choice.

## `leela/blocks/search/app.py` `connect.search_events`
Recording never fails a search, so a problem is reported in `note` and the batch is dropped.

## `leela/app.py` `the HTTP/2 patch`
HTTP/2 is an extra: this module imports `h2`, which an environment without the extra does not have. One attribute is patched on it, so a missing one is not a reason for the whole app to refuse to import.

## `leela/app.py` `the theme fallback`
The saved theme is rendered in as the fallback rather than left to the cache alone: the cache is per origin, and a first paint at an origin never used before is exactly the one that would otherwise be the wrong colour until the settings arrive.

## `leela/app.py` `the save response`
What was written, and what it now says on disk. Without this the browser kept the version it had before the save, and the next one read as another process having written the file: the save was Leela's own.

## `leela/app.py` `the selection prompt`
Not `ask_with`: `compose` labels whatever it is handed a notebook, and this is a range out of one file. The selection carries its own tags, and its path is what the read-only tools need to open anything around it.

## `leela/app.py` `the echoed ask id`
The browser's `ask_id`, echoed. It logs the ask before this request and the outcome long after it, so an id minted here reached the reply and the verdict but never the ask, and the instruction and the selected code sat on disk with nothing to join them to.

## `leela/app.py` `the completions store`
`_completions_snippets`, not `held`: a workspace can override the user for any section, so a cloned repo carrying `completions.snippets` would write selections and suggestions into the one global store while the checkbox and the banner both said the code was not kept.

## `leela/blocks/agent/ai.py` `WorkspaceHost.concurrent`
The default reads it off the launcher, because a kernel that serialises is the common case. Leela serves the inspector from inside the kernel process, so it holds for ipykernel too: `test_an_inspection_runs_beside_a_yielding_cell` is parametrised over both and passes on both.

## `leela/blocks/agent/ai.py` `the capability groups`
Every group above is declared by inheritance rather than probed. `session` is the reason the distinction matters: probed with no kernel up, the group vanished for that assistant's life, and `_kernel` starts one on demand.

## `leela/blocks/agent/ai.py` `the Git write gate`
`_plain` is what the briefing is written from. The turn model keeps the Git writes, since `built` is untouched, but is not invited to reach for them. Delegation is refused them outright, in `_sub_plain`.

## `leela/blocks/agent/app.py` `the model catalog`
The catalog and the id each row resolves to are the machine's, not this workspace's, and cost seconds to gather. Probed together, served from the last answer, refreshed behind this. `refresh` is the button: it drops the answer and gathers a new one now.

## `leela/blocks/agent/app.py` `the job models`
`inline` has a field of its own, and `**jobs` is spread last: left in here, the routing default for the job overwrote the saved prompt-cell model every time, so a choice that had been saved correctly always came back reading as the turn model.

## `leela/blocks/agent/app.py` `the runtime warm-up`
The agent's own tools run Python in an overlay over the tab's kernel, and a turn asked for in a window where nothing has been run yet had no kernel to overlay. Started here, on the loop that owns the kernels, so the first tool call meets a live one instead of the tool thread waiting on a start it cannot make.

## `leela/blocks/agent/completions.py` `VERDICTS`
What became of a suggestion. `stale` does not end the panel -- the selection moved under a replace, and the suggestion is still there to accept once the caret is back -- so one ask can report a `stale` and then a verdict. The last one is what became of it.

## `leela/blocks/agent/completions.py` `summary`
One outcome per ask, and the last: `stale` no longer closes the panel, so an ask that went stale and was then accepted reports both, and counting each would have one suggestion both rejected and accepted. An outcome with no id has no identity to be superseded by.

## `leela/blocks/agent/models.py` `INSTALLABLE`
Runtimes a package can supply, named as rishi's own extras. The rest want a CLI, a daemon or a key. LiteRT left this list in rishi 0.1.32, which took `litert-lm-api` on as a base dependency: there is no `rishi[litert]` to install any more, and nothing to install, because it is always there.

## `leela/blocks/agent/models.py` `TOOLS`
Optional tools that are not a model: `(label, requirements, approximate MB, what it gives you)`. `basedpyright` over `ty` and `pyrefly` because it answers everything the LSP client asks for and carries its own node, so it needs neither a system node nor a download when first run.

## `leela/blocks/agent/models.py` `PROBE_TTL`
The last answer from a probe, and the thread refreshing it. Asking what is installed reaches for every backend, and asking who is signed in asks every account: seconds on a cold machine, and the model picker is on the boot path.

## `leela/blocks/agent/models.py` `the modality marks`
The modality marks go on here rather than per request: `spec_caps` scans the Hugging Face cache for a local model, and doing that once per row per request was three and a half seconds of the picker.

## `leela/blocks/agent/models.py` `RECOMMENDED`
The local runtime Leela recommends of the ones left to install. LiteRT arrives with rishi and the vault answers with it, so memory works before anything here is chosen; llama.cpp is the smaller of the two remaining and the only one that runs off a Mac.

## `leela/blocks/browser/app.py` `the ready frame`
`note` names a Chrome that cannot rasterise at `MAX_SCALE`, and `browser` is the id the client dedupes it by. Both go on every `ready`: a socket that fails mid-send must not be the only time it was said.

## `leela/blocks/browser/browser.py` `MAX_SCALE`
How many image pixels a screencast frame carries per CSS pixel. A per-page `deviceScaleFactor` does not change this: measured against Chrome, a 200px div is 200 image pixels at any of them. Only the browser's own factor rasterises higher, and it is fixed at launch.

## `leela/blocks/editor/app.py` `the packages route`
A pyproject is annotated with the versions installed beside it. In a frozen app `sys.executable` is the bundle, so the fallback ran `Leela.app/Contents/MacOS/Leela -c ...`, which relaunches Leela and then waits out the eight second timeout. A project with no environment of its own gets no annotations instead.

## `leela/blocks/fs/app.py` `the watch filter`
A save Leela made is not a change to follow: what is on disk is what it holds, and dropping it there made the tab read the file again on its next mount, and its own write look like an outside edit. `versions` is stamped whenever a document is read or written.

## `leela/blocks/git/app.py` `PANES`
Panes remembered per `(root, path)`, so a write can be checked against the text it was composed from even when the browser does not send it back. Conflicts and merge reviews keep their own, so reading one never refreshes the other's before-image.

## `leela/blocks/git/app.py` `the conflict plans`
What the conflict centre's one-click button was built from: every conflicted file's text at the moment `/git/conflicts` served the plan, one entry per repository rather than per file, so a forty-file merge cannot evict its own before-images.

## `leela/blocks/git/git.py` `ConflictSaver.sider`
`(target, before, after, oid) -> None`, set per instance beside `saver`. A whole-side resolution is a Git checkout, which writes the worktree file itself and cannot be expressed as a write through `saver`: `git show :2:` hands back the cleaned blob, so writing that would clean it a second time and stage content that is on neither side. What the checkout replaced is read here instead. `oid` is the blob the replaced file hashed to.

## `leela/blocks/git/git.py` `ConflictSaver.dropper`
`path -> None`, set per instance beside `saver`. Taking the side of a modify/delete conflict that deleted the file removes a file that may be binary, executable or a symlink, and none of those survives being journal text, so the block moves it aside whole instead.

## `leela/blocks/git/ignores.py` `KINDS`
Per project kind: the files that say it is one, a path that must end up ignored, and the block to write when it does not. `probe` is what `check-ignore` is asked about, so a `.gitignore` written by hand in some other shape is still recognised as sufficient.

## `leela/blocks/lsp/lsp.py` `SERVERS`
Servers Leela will drive for Python, in the order they are tried. Each speaks LSP on stdio and differs only in how it is asked to. `basedpyright` leads because it answers everything `start` asks for and carries its own node, so installing it needs neither a system node nor a download at first run. Every language's list lives in `core.langs`; this is Python's, named here because Python is the language the rest of Leela reaches for without saying so.

## `leela/blocks/lsp/lsp.py` `LspClient.start`
The check and the spawn had nothing between them, and a notebook mount fires one lint request per mounted cell, so a window ended up running two language servers with one of them orphaned. The handshake is inside the lock: the second caller waits for the first server rather than starting a second.

## `leela/blocks/nb/app.py` `the cell output pump`
The end of the cell wakes this loop. It used to wait on the queue with a 120ms timeout and re-check, so a cell that finished without printing anything -- an assignment, an import, a definition, most cells in most notebooks -- paid that 120ms in full, every run, on top of the two milliseconds it took to execute.

## `leela/blocks/nb/app.py` `the save rebase`
A save writes cell sources and nothing else, and `nbdev_clean` rewrites outputs and metadata and nothing else, so the two rarely touch the same thing. Take the file as it is now and put the draft's edits back on top; only a source changed on both sides is a conflict worth stopping for.

## `leela/blocks/pipelines/deploys.py` `ENV_KEYS`
The schema, and the only place keys are declared. `None` -> GitHub secret; a string -> GitHub variable with that default. gheasy reads this to route each value; the workflow's `env:` block is this dict rendered; `.env` is this dict materialised.

## `leela/blocks/pipelines/deploys.py` `second_host`
The second hostname: same server, same container, same tunnel. Caddy tells them apart by the Host header, and `or` rather than a getenv default because the workflow passes every key as `${{ vars.KEY }}`. An unset repository variable arrives as the empty string, not as absent, so a getenv default would not fire.

## `leela/blocks/pipelines/pipelines.py` `the script name`
Spelled the way the project spells it. uv runs the project's own script where there is one and falls through to PATH where there is not, and PATH is where another interpreter's differently-spelled copy of the same tool is waiting.

## `leela/blocks/runtime/devserver.py` `the devserver bootstrap`
Only where the minor version matches, the same condition `_probe` and the kernel bootstrap ask. Leela's path carries bytecode and extension modules built for Leela's interpreter, and a project on another 3.x that extended anyway died on the import rather than on the command.

## `leela/blocks/runtime/kernels.py` `venv_env`
Not `UV_PROJECT_ENVIRONMENT`. It is read wherever the process ends up, not where it started, so a `uv sync` run in another checkout syncs that project's lock into this venv and prunes everything the lock does not name. uv finds the right environment from the directory anyway.

## `leela/blocks/runtime/kernels.py` `the inspector borrow`
Borrowed only by a kernel of Leela's own minor version. A frozen build ships bytecode-only modules in its zip, and another version reads their magic number and refuses: an import that fell through to them died as `bad magic number`, not as anything about the inspector.

## `leela/blocks/runtime/kernels.py` `the inspector pin`
The project venv may contain an older dhrishti. Pin the inspector protocol to this Leela installation while every other import stays project-local. Best-effort: a frozen build imports dhrishti out of a zip, where there is no file to point at. A failed pin must leave nothing in sys.modules, or the fallback import finds the broken module.

## `leela/blocks/runtime/support.py` `INSPECTOR`
What a kernel that cannot borrow Leela's own copy has to have of its own. `dhrishti` and not its imports: numpy and pandas are the two that are noticed missing, but IPython comes with it and the bundle's is bytecode for another version. Unpinned, because the versions are the project's choice. Pinned by `tests/test_runtime.py`.

## `leela/blocks/runtime/support.py` `KERNEL_PACKAGES`
What a project environment needs to run either kernel. `ipymini` names `comm`, `ipython` and `kernmini` and no more, but imports `fastcore` and `microio`, and `kernmini` moved `debug` out from under it after the version `ipymini` asks for, so resolving the declared requirements alone installs a kernel that cannot start. These are the distributions, and `as_installed` supplies the versions.

## `leela/blocks/settings/settings.py` `the settings ranges`
The weights, found by being numbers rather than by naming what they are not: the section also holds the telemetry switches and what the dialog was last set to, and a range on a string rejects it outright.

## `leela/blocks/tabs/app.py` `TOKEN_CACHE`
`path -> ((mtime_ns, size), token)`. Hashing is only paid when the stat moves, which is the rare case; a poll on an untouched file costs one `stat` as it always did. Capped because a long session opens many files and none of these entries is ever worth keeping.

## `leela/blocks/term/term.py` `MAX_FRAME`
macOS returns 1024 bytes a read however much is asked for, so a burst arrives as thousands of them. ptymini's reader gathers them into the ring, and a frame carries whatever is there since the last one. Large enough to take the per-frame cost out, small enough that one frame is not a visible pause in the terminal that draws it.

## `leela/cli.py` `main`
An optional backend is installed beside the bundle rather than into it, and `use_extras` was called in one place: straight after an install. So a backend worked for the session that installed it and was gone at the next launch, which made every install look like it had not taken. Put the directory on the path where the process starts.

## `leela/core/backups.py` `ENTRIES`
What a person cannot get back by rebuilding, and what to call it on the settings page. Caches, logs and indexes are absent: they regenerate, and copying them makes a backup too big to keep many of. Everything here is a path under the config dir except `vault`.

## `leela/core/backups.py` `PRECIOUS`
Chosen until a person chooses otherwise. The vault is out because a restore of it writes outside the config dir. `journals` is out because it is undo state for files still on disk, and a day of saving one large notebook makes it the biggest thing in an archive. `ENTRIES` still offers both.

## `leela/core/envs.py` `shell_env`
`clean_env`, or the shell inherits the bundle's `PYTHONHOME` and hands it to whatever Python its startup files run. A `python` that dies on a path configuration takes the whole profile with it: fish exited 1 with nothing exported, so every key was missing in the app and present everywhere else.

## `kunda.support.import_failure`
Leela uses Kunda's classifier for inspector import errors. It searches the whole error because NumPy may place `ImportError` after its ABI advice.

## `leela/core/keys.py` `the editor chords`
CodeMirror's own keymap already answers these inside an editor. Naming them here is what puts them in the palette and the keys help, and it is the same command either way, so the chord a hand already knows keeps working. `indent_selection` re-indents to the syntax; the only chord it had was `mod+alt+backslash`, which nobody finds.

## `leela/core/ui.py` `BARS`
The `web_` prefix promises a distinction nothing implements: these render beside their plain counterparts in every surface, in the app as much as in a browser. Nothing filters them and no rule hides them. Read them as the bars that were added later, not as the browser's own. A real split would mean a flag from `serve_ide`, which knows, reaching every renderer, and `bar` reading it per request rather than being the import-time table the keymap and the menus also share.

## `leela/desktop.py` `NO_SUBSTITUTION`
What macOS rewrites as you type, and must not while you are typing code. WKWebView hands a `contenteditable` to NSSpellChecker; a browser does not, which is why the packaged app turned quotes into curly quotes and moved the caret out from under CodeMirror, and the served one never did. Inline prediction is in the list because Tab is what accepts one, so the Tab that was meant for the completion list went to the system instead and left the caret at the start of the line. Written to Leela's own defaults domain, so nothing outside Leela changes.

## `leela/workspace.py` `the kernel chdir`
`chdir` is the runtime's own answer to this: Python runs an `os.chdir`, a runner moves a field, and a kernel in a language we cannot address declines. A fixture kernel has none, and the inline exec it used to get is what it still gets.

## `leela/workspace.py` `kernel_options`
What this tab's kernel is actually started under. `Workspace.kernel` resolves it the same way. `default_python` is one interpreter for the whole workspace, taken from the folder opened first.

## `leela/blocks/settings/settings.py` `DEFAULT_SETTINGS['search']`
The numbers here and the `Weights` dataclass defaults in `leela/blocks/search/search.py` are the same numbers, and a test says so. The comment naming them sat above `completions` rather than `search` until this pass moved it.

## `leela/blocks/term/term.py` `Terminals`
Not `ptymini.PtyRegistry`: that one holds `PtySession`s and reaps them with `await`, and these are `Pty`, opened and closed from synchronous routes.

## `leela/blocks/term/term.py` `Pty`
ptymini owns the pty, the reader thread and the ring a late viewer replays from, so `Pty` is an adapter over `PtySession`. The frame coalescing a WKWebView needs stays here, and so does the argv building: `shell_argv`, `default_shell`, `path_prelude`, `lazygit_argv`, `gh_auth_argv` and `external_terminal_argv` know this machine's shells and tools, which no pty library can.

## `leela/blocks/agent/models.py` `probed`
The memo is `ramabana.core.probed`, and only the directory is Leela's. Ramabana held two worse versions of the same idea as bare module tuples, and its own CLI wants what the picker wants: an answer about this machine that survives the process, refreshed behind whoever asked. `disk=False` is the same memo for a library that must leave nothing behind.

## `leela/blocks/agent/models.py` `model_path`
`register_model` is in-process only, so the file that outlives the process is the part every application offering an alias would write for itself. It is Ramabana's now; `MODELS_FILE` is where Leela keeps its copy.

## `leela/blocks/research/research.py` `Research.read`
The readers, the extraction and the escalation are `shalya.host.read_page`. This and shalya's `read_url` were two spellings of one dispatch which had diverged in both directions, so each was worse than the union. What is left here is the `Doc`, the status line, and filing the result into memory.

## `leela/blocks/agent/turns.py` `GROUP_LABELS`
Two shalya groups share a label where the distinction is shalya's and not a person's: reading a file is repository work, and a shell command is the runtime. Anything shalya groups and Leela does not label reads as `Other`, and a test refuses that.

## `leela/blocks/search/search.py` `_rg`
Only `__pycache__` is skipped by name. `node_modules`, `dist` and a virtualenv are in everyone's `.gitignore` and hidden to ripgrep already, and what leaks past both is demoted by `relevance` rather than hidden: a person searching for a vendored symbol wants it last, not missing.

## `leela/blocks/vault/jobs.py` `every_seconds`
The units table is `ramabana.monitor.secs`, which is pobblebonk's, which is the one parser for the family. What is Leela's is what a person types into this field: a bare number means hours, a floor of a minute because zero would poll continuously, and a cadence nobody can read is the default rather than an error nobody can act on.

## `leela/blocks/browser/browser.py` `Browser.running`
`fossick.cdp._debug_ready` is the last private import Leela makes, and `tests/test_seams.py` allows exactly this one. Whether Chrome is *up* is not whether the port is open, and fossick's is the only implementation of that distinction, so asking fossick for a public name is the fix and copying its four lines here is not.
