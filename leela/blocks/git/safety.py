"One Git command at a time per repository, and a way back from every mutation."

from __future__ import annotations

import json, re, shlex, shutil, subprocess, threading, time
from contextlib import contextmanager
from dataclasses import asdict, dataclass

from fastcore.all import Path, first

__all__ = ['GitError', 'GitGateway', 'Safepoint', 'classify', 'gateway']

class GitError(RuntimeError): pass

READS = frozenset({
    'blame', 'cat-file', 'check-attr', 'check-ignore', 'count-objects', 'describe', 'diff',
    'diff-index', 'diff-tree', 'for-each-ref', 'grep', 'log', 'ls-files', 'ls-tree',
    'merge-base', 'merge-tree', 'name-rev', 'reflog', 'rev-list', 'rev-parse', 'shortlog',
    'show', 'show-ref', 'status', 'var', 'verify-commit', 'whatchanged',
})

NET = frozenset({'clone', 'fetch', 'ls-remote', 'push'})

MIXED = {
    'branch': frozenset({'--show-current', '--list', '-l', '--contains', '--no-contains', '--merged',
        '--no-merged', '--points-at', '--format', '-a', '--all', '-r', '--remotes', '-v', '-vv', '--verbose'}),
    'config': frozenset({'--get', '--get-all', '--get-regexp', '--list', '-l'}),
    'notes': frozenset({'list', 'show'}),
    'remote': frozenset({'get-url', 'show', '-v', '--verbose'}),
    'stash': frozenset({'list', 'show'}),
    'submodule': frozenset({'status', 'summary'}),
    'tag': frozenset({'-l', '--list', '--contains', '--no-contains', '--points-at', '--format', '--sort'}),
    'worktree': frozenset({'list'}),
}

BARE_READS = frozenset({'branch', 'remote', 'tag'})

def classify(args):
    "`read`, `write` or `net` for one Git argument list. An unreadable list is a write."
    rest = [str(a) for a in args]
    while rest and rest[0].startswith('-'):
        if rest[0] in ('-c', '-C', '--git-dir', '--work-tree', '--namespace') and len(rest) > 1:
            rest = rest[2:]
        else: rest = rest[1:]
    if not rest: return 'write'
    sub, rest = rest[0], [a for a in rest[1:] if a]
    if sub in NET: return 'net'
    if sub in READS: return 'read'
    if sub == 'symbolic-ref':
        return 'write' if len([a for a in rest if not a.startswith('-')]) > 1 else 'read'
    if sub in MIXED:
        if not rest: return 'read' if sub in BARE_READS else 'write'
        return 'read' if rest[0].partition('=')[0] in MIXED[sub] else 'write'
    return 'write'

class RepoLock:
    "A per-repository readers-writer lock, reentrant for the thread holding the write."
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
            while self._writer is not None and self._writer != me: self._cv.wait()
            self._readers += 1
        try: yield
        finally:
            with self._cv:
                self._readers -= 1
                if not self._readers: self._cv.notify_all()
    @contextmanager
    def write(self):
        me = threading.get_ident()
        with self._cv:
            if self._writer == me: self._depth += 1
            else:
                while self._writer is not None or self._readers: self._cv.wait()
                self._writer, self._depth = me, 1
        try: yield
        finally:
            with self._cv:
                self._depth -= 1
                if not self._depth:
                    self._writer = None
                    self._cv.notify_all()
    @contextmanager
    def net(self):
        with self._net: yield

FOREIGN_LOCK = re.compile(r"(?:index\.lock|\.lock'?: File exists|Another git process seems to be "
    r"running|Unable to create '[^']*\.lock')", re.I)

LOCK_ATTEMPTS = 4
LOCK_BACKOFF = .15
SAFEPOINT_REF = 'refs/leela/safepoint'
JOURNAL_NAME = 'leela-safepoints.json'
JOURNAL_KEEP = 60

@dataclass
class Safepoint:
    "Where a repository was, immediately before one mutation."
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
    "The only thing in Leela that runs `git`."
    def __init__(self):
        self._locks = {}
        self._registry = threading.Lock()
        self._env_cache = {}
        self._exe = None
    def _lock(self, root):
        key = str(root)
        with self._registry:
            if key not in self._locks: self._locks[key] = RepoLock()
            return self._locks[key]
    def _git(self):
        if self._exe is None: self._exe = shutil.which('git') or ''
        if not self._exe: raise GitError('git is not installed or not on PATH')
        return self._exe
    def env(self, cwd, ttl=30):
        "The checkout's own environment, or None to inherit Leela's."
        key = str(cwd)
        hit = self._env_cache.get(key)
        if hit and time.monotonic() - hit[0] < ttl: return hit[1]
        from ..runtime.kernels import project_python, venv_env
        p = Path(cwd).expanduser().resolve()
        value = None
        for d in (p, *p.parents):
            if (py := project_python([d])):
                value = venv_env(py)
                break
            if (d/'.git').exists(): break
        self._env_cache[key] = (time.monotonic(), value)
        return value
    def memo(self, cwd, key, make, ttl=60):
        "A per-repository answer that changes on the timescale of the environment, not the tree."
        cache_key = (str(cwd), key)
        hit = self._env_cache.get(cache_key)
        if hit and time.monotonic() - hit[0] < ttl: return hit[1]
        value = make()
        self._env_cache[cache_key] = (time.monotonic(), value)
        return value
    def resolves(self, cwd, command):
        "Where a configured filter or hook command would actually be found, or `''`."
        try: parts = shlex.split(str(command or ''))
        except ValueError: return ''
        if not parts: return ''
        return shutil.which(parts[0], path=(self.env(cwd) or {}).get('PATH')) or ''
    def run(self, cwd, *args, check=True, input=None, timeout=30, kind=None):
        "One Git command, serialised against the others in the same repository."
        kind = kind or classify(args)
        lock = self._lock(cwd)
        with {'read': lock.read, 'write': lock.write, 'net': lock.net}[kind]():
            return self._exec(cwd, args, check=check, input=input, timeout=timeout, kind=kind)
    def _exec(self, cwd, args, check, input, timeout, kind):
        argv = [self._git(), *(['--no-optional-locks'] if kind == 'read' else []), *map(str, args)]
        for attempt in range(LOCK_ATTEMPTS):
            try:
                p = subprocess.run(
                    argv, cwd=str(cwd), input=input, text=True,
                    encoding='utf-8', errors='replace', stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, timeout=timeout, env=self.env(cwd),
                )
            except subprocess.TimeoutExpired as e:
                raise GitError(f'git {args[0] if args else "command"} timed out after {timeout}s') from e
            if not p.returncode or attempt == LOCK_ATTEMPTS - 1: break
            if not FOREIGN_LOCK.search(p.stderr or ''): break
            time.sleep(LOCK_BACKOFF * 2 ** attempt)
        if check and p.returncode:
            # Both streams: git diagnoses on stderr and names the files on stdout. stderr leads.
            message = '\n'.join(x for x in ((p.stderr or '').strip(), (p.stdout or '').strip())
                                if x) or f'git exited {p.returncode}'
            if FOREIGN_LOCK.search(message):
                message += ('\n\nAnother Git process is using this repository -- a terminal, an '
                    'agent, or an editor elsewhere. Nothing was changed.')
            raise GitError(message)
        return p
    def out(self, cwd, *args, **kwargs):
        "`run`, returning stdout, for the callers that want only that."
        return self.run(cwd, *args, **kwargs).stdout
    def _git_dir(self, root):
        d = Path(self.out(root, 'rev-parse', '--git-dir').strip())
        return d if d.is_absolute() else root/d
    def _journal_path(self, root):
        return self._git_dir(root)/JOURNAL_NAME
    def journal(self, root):
        "Safepoints for this repository, newest first."
        try: raw = json.loads(self._journal_path(root).read_text(encoding='utf-8'))
        except (OSError, ValueError): return []
        return [Safepoint(**row) for row in raw if isinstance(row, dict)][:JOURNAL_KEEP]
    def _record(self, root, point):
        rows = [asdict(point), *(asdict(p) for p in self.journal(root))][:JOURNAL_KEEP]
        path = self._journal_path(root)
        try:
            tmp = path.with_suffix('.tmp')
            tmp.write_text(json.dumps(rows, indent=1), encoding='utf-8')
            tmp.replace(path)
        except OSError: pass
    def safepoint(self, root, op):
        "Where the repository is, without touching it -- None when no snapshot can be taken."
        head = self.run(root, 'rev-parse', 'HEAD', check=False)
        head = head.stdout.strip() if not head.returncode else ''
        if not head: return None
        branch = self.out(root, 'branch', '--show-current').strip()
        created = self.run(root, 'stash', 'create', check=False, kind='write')
        stash = created.stdout.strip() if not created.returncode else ''
        dirty = len([l for l in self.out(root, 'status', '--porcelain=v1').splitlines() if l])
        token = f'{int(time.time() * 1000):x}'
        if stash:
            self.run(root, 'update-ref', f'{SAFEPOINT_REF}/{token}/stash', stash, check=False)
        self.run(root, 'update-ref', f'{SAFEPOINT_REF}/{token}/head', head, check=False)
        point = Safepoint(token=token, op=str(op), head=head, branch=branch, stash=stash,
            dirty=dirty, created_at=int(time.time()))
        self._record(root, point)
        return point
    @contextmanager
    def transaction(self, root, op, snapshot=True):
        "Hold the write lock for a whole operation, with a way back recorded first."
        with self._lock(root).write():
            yield self.safepoint(root, op) if snapshot else None
    def undo(self, root, token=''):
        "Put the repository back where the named safepoint says it was."
        points = self.journal(root)
        if not points:
            raise GitError('nothing to undo -- no safepoint has been recorded for this repository')
        point = first(p for p in points if p.token == token) if token else points[0]
        if point is None: raise GitError(f'no safepoint {token} in this repository')
        with self._lock(root).write():
            active = self.active_operation(root)
            if active: self.run(root, active, '--abort', check=False)
            if point.branch and self.out(root, 'branch', '--show-current').strip() != point.branch:
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
            if (git_dir/marker).exists(): return name
        return ''

_GATEWAY = GitGateway()

def gateway():
    "The process-wide gateway. One per process, because the locks have to be shared to work."
    return _GATEWAY
