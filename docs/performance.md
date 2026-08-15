# Where leela spends its time, and what to delete

A profiling pass over the server and the browser. Every number below was measured on synthetic
repositories with a warm page cache; a real checkout on a real disk is slower, never faster.
The harness is `tools/profile_app.py` for startup and streaming; the tree, status and walk
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
`await`ed one after the next, so the real refresh is 26 serial round trips — and it takes
longer than the 0.45s cache TTL it depends on, which means the status it is meant to share
expires part-way through and gets recomputed at 80ms a time.

Static assets, uncompressed, as served today:

| asset | raw | gzip -9 |
|---|---|---|
| `lee-cm6.js` | 1,019,922 | 353,118 |
| `lee-ide.js` | 658,844 | 187,203 |
| `lee-term.js` | 292,704 | 72,179 |
| `lee-ide.css` | 261,919 | 46,427 |
| `htmx.min.js` | 51,076 | 16,462 |
| **total** | **2,284,465** | **675,389** |

## The file tree

1. **`git_tree_state` runs per request.** `blocks/fs/app.py:30` recomputes changed-file state
   for every open repository on every directory expansion. A 0.45s TTL (`blocks/git/git.py:69`)
   hides it until the refresh outlives the timer, which it does.
2. **`GitRepo.at` forks `git rev-parse` every time.** 2.1ms × 26 in one refresh is 55ms of pure
   `fork`/`exec` to answer a question whose answer only changes when a root is added or removed.
3. **`refreshFileTree` is a serial waterfall.** `static/js/22_files.js:74-81` awaits one `/tree`
   per open directory in a `for` loop. `Promise.all`, or one `/files/panel?open=…` that returns
   the whole expanded tree, removes 25 round trips.
4. **`paintGitTree` is O(changes × nodes).** `static/js/16_git_cwd.js:8-9` re-runs
   `$$('.lee-file')` inside the loop and linearly scans it per change. 300 changes over a
   2,000-node tree is 300 full `querySelectorAll` passes and 600k node visits. Build one
   `Map<path, row>`.
5. **`visibleTreeNodes` forces layout per node.** `static/js/22_files.js:3` calls
   `getClientRects()` on every node, on every arrow key, twice per `treeExpand`.
6. **The tree is not virtualised.** Every expanded row is real DOM, and `refreshFileTree`
   re-parses the panel through `DOMParser` and replaces the subtree wholesale.

## Nothing propagates

There is no filesystem watcher anywhere in `leela/` — no `inotify`, no `watchfiles`, no
`watchdog`. Every refresh is either a poll or a call the client makes right after a mutation
it performed itself. Anything the agent, a terminal, a kernel or an external editor changes is
invisible until someone presses refresh. This is the whole of "file changes propagate slowly":
they do not propagate.

A watcher on the open roots, debounced, pushed over the SSE channel that already exists, would
replace the post-mutation `refreshFileTree` calls scattered through nine call sites and make
the tree correct for changes leela did not make.

## Quick-open

`/fs/find` (`blocks/fs/app.py:144`) walks the entire tree and fuzzy-ranks every path, per
request. `static/js/20_overlays.js:389-392` fires it on every `input` event with no debounce
and no sequence guard. Typing `workspace` is nine full walks and nine 668ms ranking passes,
and the responses can land out of order and paint stale hits.

The folder picker two files away (`static/js/22_files.js:207-234`) already debounces at 200ms
and guards with a `seq` counter. Copy it.

## Compression and the critical path

No compression middleware exists. 2.28MB of assets go out raw, along with every HTML page,
htmx fragment and JSON response. `GZipMiddleware` is one line for a 70% cut.

`app.py:765-767` loads `lee-cm6.js` (1MB) and `lee-term.js` (293KB) as plain `<script>` in the
head. Only `lee-ide.js` is deferred. And `lee-ide.js` is a straight concatenation of the 31
modules with comments intact — 658KB for 10,387 lines, never minified.

## Things that grow and are never freed

- `static/js/12_agent.js:740` — `approvalCards` is a `Map` of DOM nodes, `set` at :940, never
  deleted. `resolvedProposalCards` is pushed at :919 and never read.
- `static/js/12_agent.js:496` — `lee.agentLive = $('#agentlog').innerHTML` serialises the whole
  log to a string on every view switch, and holds it.
- `#agentlog` itself is never trimmed.
- `core/session.py:45` — `DocStore.forget` drops `docs`, `buffers` and `bases` but not
  `run_locks`, and nothing else pops it.
- `blocks/git/safety.py:126` and `:133` — `_locks` and `_env_cache` are keyed by every path ever
  asked about. The TTL shadows entries; it never evicts one.

## Merging divergent trees

The complaint is that there are no options. There are almost none, and the ones that exist
resolve the cases that were never hard.

- `resolve_safe_conflicts` (`blocks/git/git.py:808`) removes a conflict block only when
  `ours == theirs` — where git had no reason to conflict in the first place.
- `_conflict_blocks` (`:20`) parses `<<<<<<<`/`=======`/`>>>>>>>`, which is
  `merge.conflictStyle=merge`. The base is not on disk, so a three-way view is not even
  possible from what is written.
- `rerere` is never enabled or consulted. On a divergent rebase you resolve the same conflict
  once per replayed commit, by hand, every time.
- `_rehearse` (`:674`) already does the right thing — `git merge-tree --write-tree` merges in
  memory and touches nothing — and then throws away everything except the file names. The tree
  OID and the conflicted stages are discarded.
- Once a merge starts the UI offers continue/skip/abort and a per-file `ours`/`theirs`/
  `worktree`/`resolved`. Nothing at hunk level, though `_patch_hunks` and `apply_patch` already
  exist and are wired to staging.
- The merge modal (`static/js/18_pipelines.js:973`) offers merge/squash/ff-only and no strategy
  options at all.

What to add, cheapest first:

1. `merge.conflictStyle=zdiff3` for leela's merges. One config; the base lands in the worktree
   and a real three-way pane becomes possible.
2. `rerere.enabled` and `rerere.autoupdate`, surfaced in the conflict centre. Free, and it is
   the single largest win available on a divergent tree.
3. Keep the `merge-tree --write-tree` output. The entire conflict set — every hunk, with base,
   ours and theirs — can be shown and partly resolved before the worktree is touched.
4. Widen the auto-resolution classes past `ours == theirs`: whitespace and EOL-only
   differences, one side unchanged from base, blocks that are a pure union.
5. Hunk-level take-ours/take-theirs, using the machinery that already stages hunks.
6. `-Xours` / `-Xtheirs` / `-Xrenormalize` / `-Xfind-renames`, and `--update-refs` and
   `--rebase-merges` on rebase, as choices in the preview.
7. A cell-level merge driver for `.ipynb`. The repository already reads notebooks as cells for
   blame and diff; conflicts are the one place it does not.

## Less code: what a dependency already does

Everything below is already in `uv.lock`. None of it is a new dependency.

### `fastcore.xtras.flexicache` — replaces the hand-rolled git cache

`blocks/git/git.py:68-84` is a dict, an `RLock`, a TTL constant, `_cached` and `_invalidate`;
`blocks/git/safety.py:133-155` is a second copy for `env` and `memo`. Both are `flexicache`
with a policy, and the policy available is better than the timer:

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

### `fastlite` — replaces the SQL in `blocks/jobs/jobs.py`

`_db`, `_init`, `_row`, `get`, `forget`, `all`, `update`, `new`, and `Job`'s hand-written
`__slots__`/`__init__`/`dict` are about 70 lines of connection handling, DDL, JSON round-trips
and string-built `UPDATE`. Verified equivalent:

```python
db   = database(path)
jobs = db.create(Job, pk='id')
jobs.create_index(['status','created_at'], if_not_exists=True)
jobs.insert(Job(id=..., kind=..., created_at=time.time()))
jobs.update(dict(id=jid, status='running'))
jobs(where="status='running'", order_by='-created_at', limit=40)
```

Rows come back as `Job` instances, so `_row` and the `params`/`result` JSON dance go with it.

### `fasthtml.common.EventStream` — replaces six copies of the same response

`StreamingResponse(events(), media_type='text/event-stream', headers=…)` appears at
`app.py:986`, `:1051`, `:1174`, `:1547`, `:2094` and `blocks/search/app.py:67`, alongside the
hand-rolled `sse()` in `core/web.py:51`. One wrapper over `EventStream` that adds leela's two
headers replaces all seven.

### `fastcore.parallel.threaded` — replaces the daemon-thread boilerplate

`threading.Thread(target=…, daemon=True, name=…).start()` appears ten times: `cli.py:87`,
`blocks/debug/debug.py:41-42`, `blocks/jobs/jobs.py:106,147`, `blocks/lsp/lsp.py:29`,
`app.py:2342,2373`, `desktop.py:68`, `core/envs.py:30`. `@threaded` is the decorator form.
`blocks/git/repos.py` already uses `fastcore.parallel.parallel` for the fan-out — the same
reach, applied consistently.

### `fastcore.xtras.repo_details` — replaces the URL parsing

`_remote_web_url` (`blocks/git/git.py:86-98`) and `url_name` (`:45-47`) hand-parse `scp`-style,
`ssh://`, `git://` and https remotes. `repo_details(url)` returns `(owner, name)` from all of
them. About 16 lines.

### `execnb.shell` — replaces the nbformat output plumbing

`output_text` (`blocks/runtime/kernels.py:153`) and `_as_output` (`:425`) build and flatten
nbformat output dicts by hand. `execnb.shell` ships `out_stream`, `out_exec`, `out_error`,
`render_outputs`, `find_output` and `format_exc` for exactly this. About 25 lines. (The kernel
pool itself stays: `CaptureShell` is in-process and leela needs out-of-process kernels with an
inspector inside.)

### `fastcore.xtras.detect_mime` — replaces the binary guess

`is_texty` (`blocks/fs/fs.py:42`) decides whether a file is editable from an extension
blacklist, so an extensionless binary opens as text. `detect_mime(data)` sniffs the bytes.
(The `SERVED_TYPES` suffix table in `blocks/fs/app.py:17` stays — that maps a suffix to a
`Content-Type` for serving, which is a different question.)

### Smaller ones

- `shorten` (`blocks/git/git.py:140`) → `textwrap.shorten`, or `fastcore.xtras.TruncatedString`.
- `project_python`'s parent walk and `GitGateway.env`'s (`safety.py:139-145`) →
  `fastcore.xtras.find_file_parents`.
- `clean_env` (`blocks/runtime/support.py:9`) → `fastcore.xtras.modified_env`.
- `table` (`tools/profile_app.py:55`) → any of the formatting helpers rather than a hand-rolled
  column widther.

## Rust and SQLite-WASM

Both were asked about. Neither is where the time is.

**Rust does not touch the measured hot spots.** They are `fork`/`exec` (2.1ms per
`git rev-parse`, ×26 per refresh), the filesystem walk (60ms), and `git status` itself (127ms) —
none of which is leela's Python. The one genuinely CPU-bound thing found is `fuzzy_rank` at
667ms over 21,600 paths, and the fix there is to stop calling it on every keystroke over the
whole tree, not to rewrite it. If it is still hot after debouncing and caching, bind an existing
crate (`rapidfuzz` has one) rather than writing and maintaining a module.

The real native candidate is **libgit2 via `pygit2`**, which removes the process spawn from the
read path entirely. It also changes filter, hook and config resolution semantics, and
`safety.py` is built around `subprocess` and its foreign-lock retry. Measure it against the
numbers above before committing to it.

**SQLite-WASM solves a problem leela does not have.** The client is not querying locally; it is
waiting on serial HTTP. The one thing a client store would help is caching the tree snapshot
across a reload, and IndexedDB is already in use for editor drafts. Adding a WASM SQLite is
another megabyte onto a bundle that is not yet gzipped.

## Order to do it in

Tier 1 — hours, and every one of them is measured above:

1. `GZipMiddleware`. 2.28MB → 675KB.
2. One shared git state per tree refresh; `defer` on the two large scripts.
3. Debounce, sequence-guard and cache `/fs/find`.
4. Memoise `repo_root`.
5. `Promise.all` the tree waterfall, or one batched endpoint.
6. `paintGitTree` map; delete the `approvalCards` and `resolvedProposalCards` entries.
7. `flexicache` over the two hand-rolled caches — less code and better invalidation together.

Tier 2 — days:

8. A filesystem watcher pushed over SSE. Retires the polling model and the staleness both.
9. `zdiff3`, `rerere`, hunk-level conflict resolution.
10. `fastlite` in jobs; `EventStream`; `threaded`; `repo_details`; `execnb.shell`.
11. Minify the bundle.
12. Virtualise the tree.

Tier 3 — measure first:

13. `merge-tree`-driven conflict preview that never touches the worktree.
14. `pygit2` for the read path.
15. A native fuzzy matcher, if it is still hot.
