# Where leela spends its time, and what to delete

A profiling pass over the server and the browser. Every number below was measured on synthetic
repositories with a warm page cache. A real checkout on a real disk is slower, never faster.
The harness is `tools/profile_app.py` for startup and streaming. The tree, status and walk
numbers came from driving `leela.blocks.fs.ui.git_tree_state` and `Sandbox` directly against
generated repositories.

## Measured

| operation | 400 files | 4,500 files | 21,600 files |
|---|---|---|---|
| `git rev-parse --show-toplevel` | 2.1ms | 2.1ms | 2.2ms |
| `git status --porcelain=v1 -z` | 5.8ms | 38.6ms | 60.9ms |
| `_changes_uncached` (status + 2 numstats) | 13.2ms | 80.2ms | 127.0ms |
| `Sandbox.walk` (globtastic) | 1.3ms | 12.2ms | 60.0ms |
| `fuzzy_rank` over that walk | 11.3ms | 137.8ms | **667.3ms** |

One file-tree refresh, 4,500-file repository, counting the `git` processes it forks:

| scenario | wall | git processes |
|---|---|---|
| cold `/tree`, one directory expanded | 61ms | 4 |
| the same inside the 0.45s TTL | 7ms | 1 |
| `refreshFileTree`, 10 directories open | 122ms | 14 |
| `refreshFileTree`, 25 directories open | 208ms | 29 |
| the same, one shared status | 117ms | 5 |

Those are in-process figures with no HTTP. In the browser each `/tree` is a separate request
`await`ed one after the next, making the real refresh 26 serial round trips. That takes longer
than the 0.45s cache TTL it depends on. The status it is meant to share expires part-way
through and gets recomputed at 80ms a time.

Static assets, uncompressed, as served today:

| asset | raw | gzip -9 |
|---|---|---|
| `lee-cm6.js` | 1,020,130 | 353,140 |
| `lee-ide.js` | 378,029 | 107,010 |
| `lee-term.js` | 292,704 | 72,179 |
| `lee-ide.css` | 274,267 | 47,959 |
| `lee-core.js` | 200,564 | 60,284 |
| `lee-agent.js` | 116,734 | 32,620 |
| `htmx.min.js` | 51,076 | 16,462 |
| **total** | **2,333,504** | **689,654** |

## The file tree

1. **`git_tree_state` runs per request.** `blocks/fs/app.py:30` recomputes changed-file state
   for every open repository on every directory expansion. A 0.45s TTL (`blocks/git/git.py:69`)
   hides it until the refresh outlives the timer, which it does.
2. **`GitRepo.at` forks `git rev-parse` every time.** 2.1ms × 26 in one refresh is 55ms of pure
   `fork`/`exec` to answer a question whose answer only changes when a root is added or removed.
3. **`refreshFileTree` is a serial waterfall.** `blocks/fs/files.js`, `refreshFileTree` awaits one `/tree`
   per open directory in a `for` loop. `Promise.all`, or one `/files/panel?open=…` that returns
   the whole expanded tree, removes 25 round trips.
4. **`paintGitTree` is O(changes × nodes).** `blocks/git/cwd.js`, `paintGitTree` re-runs
   `$$('.lee-file')` inside the loop and linearly scans it per change. 300 changes over a
   2,000-node tree is 300 full `querySelectorAll` passes and 600k node visits. Build one
   `Map<path, row>`.
5. **`visibleTreeNodes` forces layout per node.** `blocks/fs/files.js`, `visibleTreeNodes` calls
   `getClientRects()` on every node, on every arrow key, twice per `treeExpand`.
6. **The tree is not virtualised.** Every expanded row is real DOM, and `refreshFileTree`
   re-parses the panel through `DOMParser` and replaces the subtree wholesale.

## Nothing propagates

There is no filesystem watcher anywhere in `leela/`. No `inotify`, no `watchfiles`, no
`watchdog`. Every refresh is either a poll or a call the client makes right after a mutation
it performed itself. Anything the agent, a terminal, a kernel or an external editor changes is
invisible until someone presses refresh. This is the whole of "file changes propagate slowly":
they do not propagate.

A watcher on the open roots, debounced and pushed over the SSE channel that already exists,
would replace the post-mutation `refreshFileTree` calls scattered through nine call sites. It
would also make the tree correct for changes leela did not make.

## Quick-open

`/fs/find` (`blocks/fs/app.py`, `fs_find`) ranks the list `Sandbox.walk` returns. The walk is ripgrep's, through `rgapi.fd_iter`. It obeys `.gitignore`, skips dot folders and the environment names in `SKIP_DIRS`, and gives each open root a turn until the 20,000-file cap is reached. Two roots holding 3,500 files walk in 0.13s. `_walked` keeps the list for two seconds, and Leela's own writes bump `_GEN` to drop it sooner.

The walk it replaced used fastcore's `globtastic`, which tests `folder_re` against the whole path, so `^[^.]` excluded nothing. Agent worktrees under `.claude` filled the cap, each query took nine seconds, and the second root was never reached.

Ranking scores each path from the root's folder name down. Scored against the absolute path, the letters in `/Users/...` matched nearly every query.

The file opener (`blocks/search/search.js`, `quickOpen`) opens at once and asks again 120ms after typing stops, with a `seq` counter dropping answers a newer query has replaced. Its checkbox adds a second batch, `more=1`, 300ms later. That batch is every file whose name matches in a ripgrep walk with hidden files and ignore rules switched on, minus the capped walk. On the same two roots that walk covers about 850,000 files and takes four to five seconds, so it stops at ten. A response cut short carries `partial`, and the opener says the list is incomplete.

## Compression and the critical path

No compression middleware exists. 2.28MB of assets go out raw, along with every HTML page,
htmx fragment and JSON response. `GZipMiddleware` is one line for a 70% cut.

`app.py:765-767` loads `lee-cm6.js` (1MB) and `lee-term.js` (293KB) as plain `<script>` in the
head. Only the `lee-*.js` bundles are deferred. They are a straight concatenation of the 56
modules with comments intact, 658KB for 10,387 lines, never minified.

## Things that grow and are never freed

- `blocks/agent/approvals.js`, `approvalCards`. `approvalCards` is a `Map` of DOM nodes, `set` there, never
  deleted. `resolvedProposalCards` is pushed at :919 and never read.
- `blocks/agent/live.js`, `agentLive`. `lee.agentLive = $('#agentlog').innerHTML` serialises the whole
  log to a string on every view switch, and holds it.
- `#agentlog` itself is never trimmed.
- `core/session.py:45`. `DocStore.forget` drops `docs`, `buffers` and `bases` but not
  `run_locks`, and nothing else pops it.
- `gheasy.repo:GitGateway._locks`, keyed by every path ever asked about and never evicted.
  (`_env_cache` was the other half. `env` is a bounded `flexicache` now.)

## Merging divergent trees

The primitives are mostly there. `git.py` has `merge_preview`/`rebase_preview` (relation, merge
base, dirty-tree warning, rehearsed conflicts, full review). It also has `conflict_plan`,
`resolve_safe_conflicts`, `conflict_versions`/`resolve_conflict`, `operation_action` for
continue/skip/abort, safepoints and `undo` through the gateway, and `RepoSet.overview` across
the workspace. What is missing is paths through them.

1. **Divergence has no route at all.** `pull()` is hard-wired `--ff-only` (`git.py:538`), and
   "Update Project" calls `gitDo('pull')` (`blocks/git/branchbar.js`, `gitDo`). A branch 3 ahead
   and 5 behind gets git's raw `fatal: Not possible to fast-forward, aborting`. There is no
   pull-with-rebase, no merge/rebase/reset choice, and nothing computes "you vs your upstream":
   both previews take an explicit branch and nobody passes `@{upstream}`.
2. **Two branch menus, two behaviours.** The git panel's menu goes through the previews
   (`blocks/git/branchmenu.js`, `branchActions`). The top branch bar's identically labelled entries
   call `gitDo('rebase'|'merge')` directly (`blocks/git/branchbar.js`, `gitDo`). Which control
   you click decides whether you get a rehearsal or a bare mutation.
3. **Rebase conflict prediction is structurally wrong.** `_rehearse` (`git.py:674`) does one
   `merge-tree` of the whole branch onto the target, but a rebase replays commit by commit. It
   misses conflicts that only appear at commit 3 and invents ones the replay never reaches. It
   also parses `merge-tree --name-only` by string prefix, and needs git ≥ 2.38 with no fallback.
4. **The agent cannot help.** It has status, fetch, checkout, pull and push
   (`blocks/agent/ai.py:473`). It cannot merge, rebase, inspect a conflict, or commit. Talking
   someone through a divergence is exactly what the model is good at, and it has no access.
5. **No rebase plan.** No `--onto`, no reorder/squash/drop, no autosquash. `rebase(branch)` is
   the whole surface (`git.py:565`).
6. **Multi-repo inherits the dead end.** `RepoSet.run('pull')` calls the same ff-only pull
   (`repos.py:160-166`), so one diverged repo in a workspace of twelve returns a raw error row.
7. **No GitHub context.** Nothing asks which PR a branch belongs to, whether its base moved, or
   whether checks are red. That is where most "why is this divergent" questions actually start.

Underneath, the resolution surface is thin. `resolve_safe_conflicts` only removes blocks where
`ours == theirs`, which is where git had no reason to conflict. `_conflict_blocks` parses the
`merge` conflict style, so the base never reaches disk and a three-way view cannot be built
from what is written. `rerere` is never enabled. Once a merge starts there is nothing at hunk
level, though `_patch_hunks` and `apply_patch` already exist for staging.

In order:

1. ~~**`GitRepo.divergence()`**~~. Done. Upstream, ahead/behind, dirty state, and each option
   (fast-forward, merge, rebase, reset) rehearsed with its conflicts and commit counts, behind
   `/git/sync-plan`. `sync(how)` performs the chosen one through `_guarded`. `classify()` needed
   no new entries: `pull --rebase` and `rebase --onto` already fall through to `write`.
2. **A Sync dialog** replacing "Update Project" whenever ahead and behind are both non-zero,
   driven by that plan. Delete the two direct `gitDo` calls in `28_branchbar.js` so both menus
   rehearse.
3. ~~**Honest rebase rehearsal**~~. Done. `_replay` cherry-picks each commit onto the
   accumulated result with `merge-tree --merge-base`, wrapping each tree back into a commit with
   `commit-tree` so the next step has a commit-ish, and reports the first commit that will not
   apply by subject. `rebase_preview` and `divergence` both use it. `_rehearse` stays for merge,
   which is the shape it was always right for. Its `--name-only` output is now parsed to the
   first blank line rather than by string prefix.
4. **Agent tools over the existing methods.** ~~`git_status` and `git_divergence` (which rehearses
   a rebase with `against=`) read-only, and `git_remote`/`git_checkout` through the approvals path
   that gates `GIT_WRITE_TOOLS`~~ are done. Still missing are `git_merge_preview`,
   `git_conflicts`, `git_compare`, and the guarded `git_merge`, `git_rebase`, `git_resolve` and
   `git_operation`. This is the biggest lever per line, because it turns existing JSON into an
   explanation.
5. **A conflict stepper.** `conflict_plan` already ranks safe against manual. Add next/previous, apply-safe, and auto-continue the operation when nothing is left.
6. **PR context behind the `github` extra.** Branch to PR, base, mergeable state, checks and
   "N behind base", in the branch bar. The only piece that needs ghapi.
7. **`RepoSet.run('sync')`.** The same plan per repo, reporting which need a decision rather
   than erroring.

1 to 4 are the substance and are self-contained in `git.py`, `blocks/git/app.py`, two JS modules
and `blocks/agent/ai.py`. New mutations go through `_guarded`. `classify()` already covers
`pull --rebase` and `rebase --onto`.

Cheap and orthogonal to all of the above. `merge.conflictStyle=zdiff3` puts the base in the
worktree, and `rerere.enabled`/`rerere.autoupdate` stops you resolving the same conflict once
per replayed commit. Both are config.

## Less code: what a dependency already does

Everything below is already in `uv.lock`. None of it is a new dependency.

### `fastcore.xtras.flexicache` replaces the hand-rolled git cache

`gheasy.repo`'s `_cached`/`_invalidate` is a dict, an `RLock` and a TTL constant. `env` was a
second copy of the same idea and is a bounded `flexicache` now. The rest is the same shape, and
the policy available is better than the timer:

```python
@flexicache(mtime_policy(arg=0), time_policy(5))
def decorations(index_path): ...
```

Measured against a 4,500-file repository:

```
first call (cold)                             11.2ms   git status runs: 1
25 more calls, index untouched                 0.2ms   git status runs: 1
after 1.0s (the 0.45s TTL would have lapsed)   0.1ms   git status runs: 1
after `git add` (index mtime moved)           10.3ms   git status runs: 2
25 more calls after that                       0.1ms   git status runs: 2
```

Two `git status` runs for that whole sequence, expiring exactly when `.git/index` moved. The
timer both over-runs (recomputes when nothing changed) and under-runs (serves stale for up to
0.45s after a stage or a commit). `time_policy` stays only as the backstop for worktree edits
the index does not see, and the file watcher above retires that too. Roughly 40 lines go.

### `fastlite` replaces the SQL in `blocks/jobs/jobs.py`

`_db`, `_init`, `_row`, `get`, `forget`, `all`, `update` and `new` come to about 70 lines of
connection handling, DDL, JSON round-trips and string-built `UPDATE`. `Job`'s hand-written
`__slots__`/`__init__`/`dict` is more of the same. Verified equivalent:

```python
db   = database(path)
jobs = db.create(Job, pk='id')
jobs.create_index(['status','created_at'], if_not_exists=True)
jobs.insert(Job(id=..., kind=..., created_at=time.time()))
jobs.update(dict(id=jid, status='running'))
jobs(where="status='running'", order_by='-created_at', limit=40)
```

Rows come back as `Job` instances, so `_row` and the `params`/`result` JSON dance go with it.

### `fasthtml.common.EventStream` replaces six copies of the same response

`StreamingResponse(events(), media_type='text/event-stream', headers=…)` appears at
`app.py:986`, `:1051`, `:1174`, `:1547`, `:2094` and `blocks/search/app.py:67`, alongside the
hand-rolled `sse()` in `core/web.py:51`. One wrapper over `EventStream` that adds leela's two
headers replaces all seven.

### `fastcore.parallel.threaded` replaces the daemon-thread boilerplate

`threading.Thread(target=…, daemon=True, name=…).start()` appears ten times: `cli.py:87`,
`blocks/debug/debug.py:41-42`, `blocks/jobs/jobs.py:106,147`, `blocks/lsp/lsp.py:29`,
`app.py:2342,2373`, `desktop.py:68`, `core/envs.py:30`. `@threaded` is the decorator form.
`blocks/git/repos.py` already uses `fastcore.parallel.parallel` for the fan-out. The same
reach, applied consistently.

### `fastcore.xtras.repo_details` replaces the URL parsing

`_remote_web_url` (`blocks/git/git.py:86-98`) and `url_name` (`:45-47`) hand-parse `scp`-style,
`ssh://`, `git://` and https remotes. `repo_details(url)` returns `(owner, name)` from all of
them. About 16 lines.

### `execnb.shell` replaces the nbformat output plumbing

`output_text` (`blocks/runtime/kernels.py:153`) and `_as_output` (`:425`) build and flatten
nbformat output dicts by hand. `execnb.shell` ships `out_stream`, `out_exec`, `out_error`,
`render_outputs`, `find_output` and `format_exc` for exactly this. About 25 lines. (The kernel
pool itself stays: `CaptureShell` is in-process and leela needs out-of-process kernels with an
inspector inside.)

### `fastcore.xtras.detect_mime` replaces the binary guess

`is_texty` (`blocks/fs/fs.py:42`) decides whether a file is editable from an extension
blacklist, so an extensionless binary opens as text. `detect_mime(data)` sniffs the bytes.
(The `SERVED_TYPES` suffix table in `blocks/fs/app.py:17` stays. That maps a suffix to a
`Content-Type` for serving, which is a different question.)

### Smaller ones

- `shorten` (`blocks/git/git.py:140`) becomes `textwrap.shorten`, or `fastcore.xtras.TruncatedString`.
- `project_python`'s parent walk and `GitGateway.env`'s become
  `fastcore.xtras.find_file_parents`.
- `clean_env` (`blocks/runtime/support.py:9`) becomes `fastcore.xtras.modified_env`.
- `table` (`tools/profile_app.py:55`) becomes any of the formatting helpers rather than a
  hand-rolled column widther.

## Rust and SQLite-WASM

Both were asked about. Neither is where the time is.

**Rust does not touch the measured hot spots.** They are `fork`/`exec` (2.1ms per
`git rev-parse`, ×26 per refresh), the filesystem walk (60ms), and `git status` itself (127ms).
None of those is leela's Python. The one genuinely CPU-bound thing found is `fuzzy_rank` at
667ms over 21,600 paths. The fix there is to stop calling it on every keystroke over the whole
tree, rather than rewriting it. If it is still hot after debouncing and caching, bind an existing
crate (`rapidfuzz` has one) rather than writing and maintaining a module.

The real native candidate is **libgit2 via `pygit2`**, which removes the process spawn from the
read path entirely. It also changes filter, hook and config resolution semantics, and
the gateway is built around `subprocess` and its foreign-lock retry. Measure it against the
numbers above before committing to it.

**`fastgit` is not a dependency** and is not worth making one. It is a thin subprocess wrapper. The gateway's `_run`
already carries timeouts, read/write/net classification, index-lock retry, safepoints and cache
invalidation. `fastgit.Git` has a notion of none of them. The one idea
worth stealing is its `_ok1` set. Exit 1 from `merge-tree`, `diff` and friends is data rather
than failure, which `_attempt` and `_rehearse` currently hand-roll.

**`ghapi`** arrives only through the `github` extra, via gheasy, which already owns the token
and the `GhApi` instance. A GitHub layer is therefore cheap, but it has to degrade cleanly when
the extra is absent, the way the workflow panels already do.

**SQLite-WASM solves a problem leela does not have.** The client is not querying locally. It is
waiting on serial HTTP. The one thing a client store would help is caching the tree snapshot
across a reload, and IndexedDB is already in use for editor drafts. Adding a WASM SQLite is
another megabyte onto a bundle that is not yet gzipped.

## Done, and what it bought

`tools/profile_web.py` drives a real Chromium over a generated 720-file checkout with 40
uncommitted files, and expands 25 folders before refreshing the tree.

| | before | after |
|---|---|---|
| bytes on the wire, cold load | 2,160,789 | **703,696** |
| `load` event | 429ms | 347ms |
| HTTP requests, one tree refresh | 26 | **1** |
| `refreshFileTree` | 384.9ms | **98.9ms** |
| `paintGitTree`, 40 changes | 4.0ms | 1.8ms |

- `GZipMiddleware` in `app.py`, and `defer` on `htmx.min.js` and `lee-cm6.js`.
- `/files/panel?open=` draws the folders the client had expanded, so a refresh is one request
  instead of one per folder. `tree_node` takes `fs` and `opened` and recurses.
- `_walked` memoises the quick-open tree walk. The overlay debounces at 120ms and guards with a
  sequence counter, as the folder picker already did.
- `_toplevel` memoises `rev-parse --show-toplevel`.
- `paintGitTree` indexes the rows into a `Map` once.
- `flexicache` replaces `GitGateway._env_cache` and the `memo` indirection behind
  `filter_health`. `resolvedProposalCards` is deleted, and `approvalCards` is cleared wherever
  the agent log is.

### The watcher

`blocks/fs/watch.py` is one `watchfiles` thread per workspace over the open roots, filtered by
the same `SKIP_DIRS` the tree uses, pushed to the browser over `/fs/events`. Write to disk to a
subscriber getting the event: **79ms best, 100ms median**, against a 200ms debounce. `node_modules`
and `.git` produce nothing.

A push never rebuilds the panel. `patchTreeDir` reconciles one folder's children against the
server by `data-path`. Rows that are still there stay where they are, with whatever they had
open inside them, and only their Git decoration is synced. A write the client made itself is
not news. `noteSelfWrite` marks the paths that autosave and the four tree mutations write, and
those are dropped from the batch, leaving one `/git/info` to repaint the badges.

| a change lands | requests | rows | folders open | scroll | rows kept |
|---|---|---|---|---|---|
| a file appears from elsewhere | 2 | 283 → 284 | 25 → 25 | 90 → 90 | yes |
| the client saves its own | 1 | 284 → 284 | 25 → 25 | 90 → 90 | yes |

Two things it cost to get right. The notify thread is Rust, so `close()` joins it rather than
only signalling. A watcher still running when the interpreter tears down segfaults, reliably.
`ctx` is a capability surface rather than the workspace, so `fs_watch` had to be declared in
`EAGER` and in the fs block's `CAPS`. Reaching for an undeclared one is an `AttributeError` at
first use, which is the design working.

This is also the honest answer to "should we write a Rust module": no, but use one. `watchfiles`
is `notify` behind a Python API, and it is the piece of this codebase where native code was
actually the right call.

## Startup, and what a desktop app pays while idle

`tools/profile_app.py --server`, a fresh interpreter per run:

| | before | after |
|---|---|---|
| build `Workspace` + `ide_app` | 239ms | **75ms** |
| process start to first page | 536ms | **338ms** |
| resident, idle | 71MB | **56MB** |
| heavy deps resident | IPython | **none** |

One line. `fast_app` runs `from .pico import picolink` unconditionally, before it looks at
`pico=`, and `fasthtml.pico` ends in `try: from IPython import display`. That is 212ms and 402
modules for a stylesheet link this app passes `pico=False` to refuse. `FastHTML` directly skips
it. Every other default of the two is identical, which is checkable and was checked, except the
`static_route_exts()` call `fast_app` makes: it served the working folder by extension with no
containment, so Leela leaves it out and serves its own files from `/leestatic` and `/file/raw`.

Idle traffic, from `tools/profile_web.py`, measured over twelve seconds of nobody touching
anything:

| | before | after |
|---|---|---|
| requests per minute | 125 | **60** |
| `/agent/approval` | 80 | 15 |
| `/tab/watch` | 60 | 6 |
| `/workspace/info` + `/cwd` | 24 | 0 |
| `/dev/list` | 30 | 4 |

- `pollApproval` ran at 750ms forever. An approval can only be raised while the model is
  working, so it stays at 750ms then and drops to 5s otherwise.
- `watchOpenFile` polled `/tab/watch` every second for changes `/fs/events` now pushes. It is a
  10s backstop, and the watcher calls it directly when the open file is in a batch.
- `refreshProjectPills` polled two routes every 5s for data that changes only when a root or the
  cwd does, and all eight of those paths already call it. The interval is gone.
- `pollRunLogs` polled `/dev/list` every 2s whether or not a dev server existed. It reschedules
  itself at 2s while one is alive and 15s when none is.
- `leeVars` and `refreshKernelPill` skip a hidden window, as `watchOpenFile` already did.

## Still to do

1. `fastlite` in jobs, then `EventStream`, `threaded`, `repo_details` and `execnb.shell`.
2. Minify the bundle. 187KB gzipped is still the second-largest asset, and it is unminified.
3. Virtualise the tree.
4. `pygit2` for the read path, if measurement justifies it.
5. A native fuzzy matcher, if `fuzzy_rank` is still hot after the debounce and the walk cache.
6. The shared-state lock in `docs/parallel-threads.md`, before threads ship.


## Why the client is three script tags

`ACTIONS` in `static/js/actions.js` is the keymap's dispatch table. Fifty of its entries used to
be bare references to functions declared in later modules: `help: showHelp`,
`quick_open: quickOpen`, down to `browseUrl` in `blocks/browser/browser.js`. The table is a
top-level `const`, so those names were read the moment the module ran, and a function
declaration hoists to the top of its own script and no further. One tag was fine. Three were
not, and the failure was not graceful:

```
ReferenceError: showHelp is not defined              at lee-core.js:644
ReferenceError: ACTIONS is not defined               at lee-ide.js:4904
ReferenceError: Cannot access 'mountTabVersion' before initialization
```

The first throw aborted the rest of `lee-core.js`, so every `let` after it stayed in its
temporal dead zone and the shell painted and then refused to open a file.

Every entry is a thunk now (`help: () => showHelp()`). `leeAct` calls them as `f()` with no
arguments and no receiver, and the arrow's implicit return still hands back the promise the
async ones produce, so the wrapper is equivalent. The client is served as three deferred tags in
one lexical scope: `lee-core.js` (the vocabulary, dispatch, editor, kernel, vars),
`lee-agent.js`, and `lee-ide.js` (everything else).

Three tests hold this. `test_the_dispatch_table_holds_thunks_and_not_bare_references` fails on a
bare entry. `test_no_bundle_reads_a_later_bundles_declaration_at_load_time` fails on the general
pattern, whatever the table. `test_every_dispatch_entry_is_callable_across_the_bundles` resolves
every entry in a live page, because a thunk hides a missing function until someone presses the
key.

Splitting buys cache granularity rather than bytes, and `lee-cm6.js` at 1MB is the larger prize.
