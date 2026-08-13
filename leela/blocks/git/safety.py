"""One Git command at a time per repository, and a way back from every mutation.

Every Git call in Leela goes through `gateway().run`. Not for tidiness: the panel polls
status while a person clicks *merge*, and both of those are `git` processes in the same
checkout. Git is safe under that -- it takes `.git/index.lock` and one of the two loses --
but "the operation failed, try again" is not what an IDE is for. PyCharm feels reliable
because it serialises; this module is that, and nothing more clever.

Three mechanisms, in the order they matter:

`--no-optional-locks` on reads. `git status` writes `.git/index` to refresh its stat cache,
so a status poll genuinely collides with a mutation -- the reader is the aggressor as often
as the writer. Git ships this flag for exactly this caller, and it removes most of the
collisions before any locking of ours is involved.

A per-repository lock, reentrant per thread, with commands sorted into `read`, `write` and
`net`. Writes exclude everything; reads share with each other; network operations take their
own lock so that a 120-second `fetch` does not freeze the file tree. Reentrancy is what lets
a transaction hold the write lock and still ask questions inside it.

Retry when the lock is *foreign*. Leela is not the only Git in these repositories -- there is
a terminal in the next tab and an agent in the one after. Retrying a failed mutation would
normally be reckless, but Git takes the index lock before it does any work, so a command that
failed to acquire it changed nothing and is safe to repeat. Only that failure is retried, and
it is matched by message rather than assumed.

Safepoints are the fourth thing, and the one that changes how the UI can behave. Before any
mutation, `transaction` records HEAD, the branch, and -- when the tree is dirty -- a
`git stash create` snapshot, which builds a commit out of the working tree *without* touching
it. Both are pinned under `refs/leela/safepoint/` so garbage collection cannot take them, and
journalled to `.git/leela-safepoints.json`. A merge that ends in a mess is then a button
rather than an afternoon: `undo` aborts whatever is in progress, resets to the recorded
commit, and puts the dirty tree back.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

__all__ = ['GitError', 'GitGateway', 'Safepoint', 'classify', 'gateway']


class GitError(RuntimeError):
    pass


# Subcommands that only ever read. Anything not named here is treated as a write, because the
# cost of being wrong that way is a lock held too long, and the cost of being wrong the other
# way is the corruption this module exists to prevent.
READS = frozenset({
    'blame', 'cat-file', 'check-attr', 'check-ignore', 'count-objects', 'describe', 'diff',
    'diff-index', 'diff-tree', 'for-each-ref', 'grep', 'log', 'ls-files', 'ls-tree',
    'merge-base', 'merge-tree', 'name-rev', 'reflog', 'rev-list', 'rev-parse', 'shortlog',
    'show', 'show-ref', 'status', 'var', 'verify-commit', 'whatchanged',
})

# Talks to a remote: slow, and does not touch the index or the working tree. These get their
# own lock rather than the write lock, so that fetching does not stop the panel from drawing.
NET = frozenset({'clone', 'fetch', 'ls-remote', 'push'})

# Subcommands that read or write depending on what follows. `git branch` lists; `git branch -d`
# does not. The first non-empty argument decides.
MIXED = {
    'branch': frozenset({'--show-current', '--list', '-l', '--contains', '--no-contains',
                         '--merged', '--no-merged', '--points-at', '--format', '-a', '--all',
                         '-r', '--remotes', '-v', '-vv', '--verbose'}),
    'config': frozenset({'--get', '--get-all', '--get-regexp', '--list', '-l'}),
    'notes': frozenset({'list', 'show'}),
    'remote': frozenset({'get-url', 'show', '-v', '--verbose'}),
    'stash': frozenset({'list', 'show'}),
    'submodule': frozenset({'status', 'summary'}),
    'tag': frozenset({'-l', '--list', '--contains', '--no-contains', '--points-at',
                      '--format', '--sort'}),
    'worktree': frozenset({'list'}),
}

# `git branch`, `git tag` and `git remote` with no arguments at all are list commands. `git
# stash` with no arguments is `stash push`, which is emphatically not.
BARE_READS = frozenset({'branch', 'remote', 'tag'})


def classify(args):
    """`read`, `write` or `net` for one Git argument list.

    Global options (`-c foo=bar`, `--git-dir=...`) precede the subcommand, so they are skipped
    before anything is decided. An empty list is a write, because a command we cannot read is
    not one to take chances with.
    """
    rest = [str(a) for a in args]
    while rest and rest[0].startswith('-'):
        # `-c` and `--git-dir` style options take a value; the joined forms do not.
        if rest[0] in ('-c', '-C', '--git-dir', '--work-tree', '--namespace') and len(rest) > 1:
            rest = rest[2:]
        else:
            rest = rest[1:]
    if not rest:
        return 'write'
    sub, args_after = rest[0], [a for a in rest[1:] if a]
    if sub in NET:
        return 'net'
    if sub in READS:
        return 'read'
    if sub == 'symbolic-ref':
        # Reading a symbolic ref names it; writing one names it *and* its target.
        return 'write' if len([a for a in args_after if not a.startswith('-')]) > 1 else 'read'
    if sub in MIXED:
        if not args_after:
            return 'read' if sub in BARE_READS else 'write'
        first = args_after[0].partition('=')[0]
        return 'read' if first in MIXED[sub] else 'write'
    return 'write'


class RepoLock:
    """A per-repository readers-writer lock, reentrant for the thread holding the write.

    Reentrancy is the point. `transaction` takes the write lock for the length of a merge and
    then asks Git several questions inside it -- what HEAD was, whether the tree is dirty --
    and each of those is another `run`. Without reentrancy that is a deadlock against
    ourselves.

    There is no read-to-write upgrade, and there must not be: a read is held for exactly one
    subprocess and never across a decision, so no caller is ever in a position to want one.
    """

    def __init__(self):
        self._cv = threading.Condition()
        self._writer = None
        self._depth = 0
        self._readers = 0
        self._net = threading.RLock()

    @contextmanager
    def read(self):
        me = threading.get_ident()
        with self._cv:
            while self._writer is not None and self._writer != me:
                self._cv.wait()
            self._readers += 1
        try:
            yield
        finally:
            with self._cv:
                self._readers -= 1
                if not self._readers:
                    self._cv.notify_all()

    @contextmanager
    def write(self):
        me = threading.get_ident()
        with self._cv:
            if self._writer == me:
                self._depth += 1
            else:
                while self._writer is not None or self._readers:
                    self._cv.wait()
                self._writer, self._depth = me, 1
        try:
            yield
        finally:
            with self._cv:
                self._depth -= 1
                if not self._depth:
                    self._writer = None
                    self._cv.notify_all()

    @contextmanager
    def net(self):
        with self._net:
            yield


# Failure to take a lock file, as Git words it. Matched rather than assumed because it is the
# one failure this module retries, and retrying anything else would be a way to run a mutation
# twice.
FOREIGN_LOCK = re.compile(
    r"(?:index\.lock|\.lock'?: File exists|Another git process seems to be running|"
    r"Unable to create '[^']*\.lock')", re.I)

LOCK_ATTEMPTS = 4
LOCK_BACKOFF = .15
SAFEPOINT_REF = 'refs/leela/safepoint'
JOURNAL_NAME = 'leela-safepoints.json'
JOURNAL_KEEP = 60


@dataclass
class Safepoint:
    """Where a repository was, immediately before one mutation.

    `stash` is a commit produced by `git stash create`, which snapshots the index and the
    working tree without disturbing either -- empty when there was nothing to snapshot.
    Untracked files are deliberately not in it: `stash create` leaves them alone, and so does
    the `reset --hard` that undo performs, so they survive by not being involved.
    """
    token: str
    op: str
    head: str
    branch: str
    stash: str
    dirty: int
    created_at: int

    def describe(self):
        where = self.branch or (self.head[:9] + ' (detached)' if self.head else 'an unborn branch')
        return f'{self.op} on {where}' + (f', {self.dirty} uncommitted file(s) kept' if self.dirty else '')


class GitGateway:
    """The only thing in Leela that runs `git`.

    `run` is deliberately the same shape as the `subprocess.run` call it replaced, so that the
    hundred call sites in `git.py` did not have to change to gain the locking. What it adds is
    the classification, the flag, the lock and the retry -- and the fact that `git.py` has no
    `subprocess` import of its own any more, which is what keeps a future method from
    accidentally opting out.
    """

    def __init__(self):
        self._locks = {}
        self._registry = threading.Lock()
        self._env_cache = {}
        self._exe = None

    def _lock(self, root):
        key = str(root)
        with self._registry:
            lock = self._locks.get(key)
            if lock is None:
                lock = self._locks[key] = RepoLock()
            return lock

    def _git(self):
        if self._exe is None:
            self._exe = shutil.which('git') or ''
        if not self._exe:
            raise GitError('git is not installed or not on PATH')
        return self._exe

    def env(self, cwd, ttl=30):
        """The checkout's own environment, or None to inherit Leela's.

        Git itself does not care, but the hooks do: a commit made from the source-control
        panel runs `pre-commit`, or nbdev's clean filter, and those are console scripts of the
        project being committed to. It applies to reads as much as to writes -- `git status`
        runs the clean filter to decide whether a notebook differs at all, and a status that
        cannot run it reports every notebook as modified for ever.

        Cached, because working it out walks the directory tree looking for a virtualenv and
        `info()` is thirty Git calls in the same repository.
        """
        key = str(cwd)
        hit = self._env_cache.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
        from ..runtime.kernels import project_python, venv_env
        p = Path(cwd).expanduser().resolve()
        value = None
        for d in (p, *p.parents):
            if (py := project_python([d])):
                value = venv_env(py)
                break
            if (d/'.git').exists():
                break
        self._env_cache[key] = (time.monotonic(), value)
        return value

    def memo(self, cwd, key, make, ttl=60):
        "A per-repository answer that changes on the timescale of the environment, not the tree."
        cache_key = (str(cwd), key)
        hit = self._env_cache.get(cache_key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
        value = make()
        self._env_cache[cache_key] = (time.monotonic(), value)
        return value

    def resolves(self, cwd, command):
        """Where a configured filter or hook command would actually be found, or `''`.

        Asked here rather than in `git.py` because the answer depends entirely on the
        environment this class hands to Git, and a probe that looked at a different `PATH` from
        the one Git is given would be worse than no probe at all.
        """
        try:
            parts = shlex.split(str(command or ''))
        except ValueError:
            return ''
        if not parts:
            return ''
        env = self.env(cwd) or {}
        return shutil.which(parts[0], path=env.get('PATH')) or ''

    def run(self, cwd, *args, check=True, input=None, timeout=30, kind=None):
        """One Git command, serialised against the others in the same repository.

        `kind` overrides the classification, for the rare command whose argument list does not
        say what it is about to do. Everything else should let `classify` decide.
        """
        kind = kind or classify(args)
        lock = self._lock(cwd)
        held = {'read': lock.read, 'write': lock.write, 'net': lock.net}[kind]
        with held():
            return self._exec(cwd, args, check=check, input=input, timeout=timeout, kind=kind)

    def _exec(self, cwd, args, check, input, timeout, kind):
        exe = self._git()
        # `--no-optional-locks` stops a read from taking the index lock to refresh its stat
        # cache, which is what made the status poller collide with everything else.
        argv = [exe, *(['--no-optional-locks'] if kind == 'read' else []), *map(str, args)]
        for attempt in range(LOCK_ATTEMPTS):
            try:
                p = subprocess.run(
                    argv, cwd=str(cwd), input=input, text=True,
                    encoding='utf-8', errors='replace', stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, timeout=timeout, env=self.env(cwd),
                )
            except subprocess.TimeoutExpired as e:
                raise GitError(f'git {args[0] if args else "command"} timed out after {timeout}s') from e
            if not p.returncode or attempt == LOCK_ATTEMPTS - 1:
                break
            if not FOREIGN_LOCK.search(p.stderr or ''):
                break
            # Safe to repeat: Git takes the lock before it does any work, so a command that
            # could not take it did nothing at all. Something outside Leela holds it.
            time.sleep(LOCK_BACKOFF * 2 ** attempt)
        if check and p.returncode:
            message = (p.stderr or p.stdout or f'git exited {p.returncode}').strip()
            if FOREIGN_LOCK.search(message):
                message += ('\n\nAnother Git process is using this repository -- a terminal, an '
                            'agent, or an editor elsewhere. Nothing was changed.')
            raise GitError(message)
        return p

    def out(self, cwd, *args, **kwargs):
        "`run`, returning stdout, for the callers that want only that."
        return self.run(cwd, *args, **kwargs).stdout

    # ---- safepoints -------------------------------------------------------------------

    def _git_dir(self, root):
        d = Path(self.out(root, 'rev-parse', '--git-dir').strip())
        return d if d.is_absolute() else root/d

    def _journal_path(self, root):
        return self._git_dir(root)/JOURNAL_NAME

    def journal(self, root):
        "Safepoints for this repository, newest first."
        try:
            raw = json.loads(self._journal_path(root).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return []
        return [Safepoint(**row) for row in raw if isinstance(row, dict)][:JOURNAL_KEEP]

    def _record(self, root, point):
        rows = [asdict(point), *(asdict(p) for p in self.journal(root))][:JOURNAL_KEEP]
        path = self._journal_path(root)
        try:
            tmp = path.with_suffix('.tmp')
            tmp.write_text(json.dumps(rows, indent=1), encoding='utf-8')
            tmp.replace(path)
        except OSError:
            pass  # A journal we cannot write is a lost undo, not a failed merge.

    def safepoint(self, root, op):
        """Snapshot where the repository is, without touching it.

        Returns None rather than raising when the snapshot cannot be taken -- an unborn branch
        has no HEAD to record, and refusing to merge because we could not prepare an undo
        would be the wrong trade.
        """
        head = self.run(root, 'rev-parse', 'HEAD', check=False)
        head = head.stdout.strip() if not head.returncode else ''
        if not head:
            return None
        branch = self.out(root, 'branch', '--show-current').strip()
        created = self.run(root, 'stash', 'create', check=False, kind='write')
        stash = created.stdout.strip() if not created.returncode else ''
        dirty = len([l for l in self.out(root, 'status', '--porcelain=v1').splitlines() if l])
        token = f'{int(time.time() * 1000):x}'
        if stash:
            # Pinned, or the next `gc` collects a commit nothing points at and the undo button
            # becomes a lie.
            self.run(root, 'update-ref', f'{SAFEPOINT_REF}/{token}/stash', stash, check=False)
        self.run(root, 'update-ref', f'{SAFEPOINT_REF}/{token}/head', head, check=False)
        point = Safepoint(token=token, op=str(op), head=head, branch=branch, stash=stash,
                          dirty=dirty, created_at=int(time.time()))
        self._record(root, point)
        return point

    @contextmanager
    def transaction(self, root, op, snapshot=True):
        """Hold the write lock for a whole operation, with a way back recorded first.

        The lock spans the safepoint *and* the mutation, so nothing can move between deciding
        where we were and going somewhere else. `snapshot=False` is for the mutations that are
        their own undo -- staging a file, or an undo itself.
        """
        lock = self._lock(root)
        with lock.write():
            yield self.safepoint(root, op) if snapshot else None

    def undo(self, root, token=''):
        """Put the repository back where the named safepoint says it was.

        Order matters and is the whole method: abort whatever Git is in the middle of, because
        a reset during a rebase leaves the rebase running; move HEAD back; then restore the
        dirty tree from the snapshot commit. The branch is checked out by name rather than by
        commit so that undoing a merge does not leave a detached HEAD where a branch was.
        """
        points = self.journal(root)
        if not points:
            raise GitError('nothing to undo -- no safepoint has been recorded for this repository')
        point = next((p for p in points if p.token == token), None) if token else points[0]
        if point is None:
            raise GitError(f'no safepoint {token} in this repository')
        with self._lock(root).write():
            active = self.active_operation(root)
            if active:
                self.run(root, active, '--abort', check=False)
            if point.branch:
                current = self.out(root, 'branch', '--show-current').strip()
                if current != point.branch:
                    self.run(root, 'checkout', point.branch)
            self.run(root, 'reset', '--hard', point.head)
            restored = 0
            if point.stash:
                applied = self.run(root, 'stash', 'apply', '--index', point.stash, check=False)
                if applied.returncode:
                    applied = self.run(root, 'stash', 'apply', point.stash, check=False)
                if applied.returncode:
                    raise GitError(
                        f'HEAD is back at {point.head[:9]}, but the uncommitted work would not '
                        f'reapply cleanly. It is kept as commit {point.stash[:9]} -- recover it '
                        f'with `git stash apply {point.stash}`.\n\n{applied.stderr.strip()}')
                restored = point.dirty
        return {'token': point.token, 'op': point.op, 'head': point.head,
                'branch': point.branch, 'restored': restored, 'describe': point.describe()}

    def active_operation(self, root):
        "The Git operation this repository is in the middle of, as the command that owns it."
        git_dir = self._git_dir(root)
        for name, marker in (('rebase', 'rebase-merge'), ('rebase', 'rebase-apply'),
                             ('merge', 'MERGE_HEAD'), ('cherry-pick', 'CHERRY_PICK_HEAD'),
                             ('revert', 'REVERT_HEAD')):
            if (git_dir/marker).exists():
                return name
        return ''


_GATEWAY = GitGateway()


def gateway():
    "The process-wide gateway. One per process, because the locks have to be shared to work."
    return _GATEWAY
