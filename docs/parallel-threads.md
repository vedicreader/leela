# Parallel agent threads, one git worktree each

A thread is a task, a branch, a worktree, a workspace and an agent session, running beside
others in the same repository. Leela has every piece and joins none of them.

## What is already there

- `GitRepo.worktrees` / `add_worktree` / `remove_worktree` (`blocks/git/git.py`), served by
  `/git/resources`. Nothing creates one from the UI, and the panel only lists them.
- `Workspace(roots=[...])` is per-folder, and `--app` already gives each folder its own
  workspace, documents, agent, terminals and kernel pool at `folder.localhost:5001`.
- `RepoSet.overview` is the plural view — which are dirty, behind, unpublished — and a thread
  board is the same shape pointed at worktrees instead of checkouts.
- `Jobs` is a queue with a visible state and a SQLite row per job, which is what a thread's
  lifecycle wants.

## Why divergence had to come first

N threads on N branches all diverge from the trunk at once — that is the normal state, not the
failure. Until `divergence()` there was no way to ask "where does this thread stand and how does
it land", and `pull` was `--ff-only`, so the answer for every one of them was
`fatal: Not possible to fast-forward`. Landing a thread is exactly `divergence()` against the
trunk, and `_replay` is what tells you which of that thread's commits will not go back cleanly —
per commit, by subject, without touching the worktree.

## Measured

`tools/profile_worktrees.py -n 6`, on a 720-file repository:

| | |
|---|---|
| `git worktree add`, each | 155ms |
| six of them | 931ms |
| working tree on disk, each | 130KB |
| the repository they share | 478KB |
| `git status`, one worktree alone | 18ms |
| `git status`, all six at once | 36ms |
| five of them while a sixth is held under a write | 29ms — the same as freely |
| distinct gateway locks for six worktrees | 6 |
| resident added by six open Workspaces | 2MB |

Setup is cheap and the checkouts are cheap: a worktree costs one working tree and shares the
object store. Reads scale — six concurrent `git status` cost twice one. And an idle Workspace is
free: kernels are stubbed in that measurement and the index, vault and browser are built on
first use, so 2MB is the floor, not the cost of a thread that is working. The real per-thread
cost is a kernel and a kosha index, and that is the number to design against.

## The one thing that is unsafe today

`GitGateway._lock` keys on the worktree root, so six worktrees take six different locks — the
measurement confirms a write held in one does not slow the others at all. That is the point for
parallel threads, and it is wrong for the half of git that is shared.

A worktree has its own index, `HEAD` and operation state under `.git/worktrees/<name>/`. It
shares the object store, the ref store, `config`, `packed-refs` and `FETCH_HEAD`. So two threads
running `fetch`, `gc`, `branch -m`, `remote add` or `config` at the same time are serialised
against nothing.

The fix is small: take the lock on `git rev-parse --git-common-dir` rather than the worktree
root for commands that touch shared state, and keep the per-worktree lock for `status`, `add`,
`commit`, `merge`, `rebase` and the rest. `classify()` already sorts commands into read, write
and net; this adds a third axis — *shared* — over the same table. **Do this before shipping
threads, not after.**

## The build

1. **`Threads`, a block** (`blocks/threads/`) over `Jobs`: `new(task)` creates
   `agent/<slug>`, adds a worktree beside the checkout, opens it as a root, and starts an agent
   session with the task as its first turn. `close(id)` removes the worktree and the branch when
   it has landed, refusing when it has not.
2. **The shared-state lock**, above. It gates everything else.
3. **A board**, one row per thread, in the shape `RepoSet.overview` already uses: branch, ahead
   and behind the trunk, dirty, what the agent is doing, and the conflicts `divergence()`
   predicts against the trunk *right now*. Fed by one `/threads/overview` that fans out with
   `parallel(..., threadpool=True)`, as `RepoSet._fan` does.
4. **Land**, per thread: the Sync dialog pointed at the trunk instead of the upstream. It
   already renders exactly this — fast-forward, merge, rebase, reset, each rehearsed. The only
   new part is choosing what to reconcile against.
5. **Cross-thread conflicts.** The interesting question a board can answer and a terminal
   cannot: do threads 2 and 5 touch the same files? That is `_rehearse(a, b)` per pair, which is
   one `merge-tree` each and no worktree touched. At six threads that is fifteen rehearsals,
   about 20ms each here — cheap enough to compute on every board refresh, and the thing that
   makes parallel work legible rather than merely concurrent.
6. **Budget.** One kernel per thread is the real cost. Threads should share a kernel until one
   runs code, and share the kosha index across worktrees of the same repository — the code is
   nearly identical between them, and indexing six copies of one repository six times is the
   obvious waste to avoid.

## What to profile once it exists

`tools/profile_worktrees.py` measures the floor. The numbers that decide whether this is usable
are the ones it deliberately does not touch:

- resident cost of a thread with a live kernel and an index, times N;
- whether `off_loop`'s shared executor starves at N threads — six agents fetching at 120s
  timeouts is six workers held in the default pool;
- board refresh with the pairwise rehearsals, at N = 2, 6, 12;
- and whether the agent's approvals path stays legible when six threads propose at once, which
  is a UI question the profiler cannot answer.
