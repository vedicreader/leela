"""Structured, low-latency Git integration for Leela's browser surfaces.

Git remains the source of truth. Commands never pass through a shell, mutating operations
invalidate the shared short-lived snapshot, and records are deliberately presentation-free.

Nothing here runs a subprocess. Every command goes through `safety.gateway`, which serialises
the commands in a repository against each other and records a way back from each mutation --
so this module has no `subprocess` import of its own, and a method added later cannot opt out
of the locking by accident.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlparse

from ..nb.spans import source_spans
from .safety import GitError, gateway

__all__ = ['GitRepo', 'GitError', 'repo_root', 'clone']


def _run(cwd, *args, check=True, input=None, timeout=30, kind=None):
    "One Git command, through the gateway that serialises it against the repository's others."
    return gateway().run(cwd, *args, check=check, input=input, timeout=timeout, kind=kind)


def repo_root(path):
    """The containing worktree root, or ``None`` when path is not in a repository."""
    p = Path(path).expanduser().resolve()
    if p.is_file():
        p = p.parent
    try:
        r = _run(p, 'rev-parse', '--show-toplevel', check=False)
        return Path(r.stdout.strip()).resolve() if r.returncode == 0 and r.stdout.strip() else None
    except (OSError, GitError):
        return None


def clone(url, parent, name=''):
    """Clone `url` into `parent`, returning the new worktree root.

    The URL is a positional argument to `git clone`, so an option-shaped one would be read
    as a flag instead: `--` and an outright refusal keep it a URL. The folder name is
    derived here rather than left to Git so that the caller knows where the checkout landed
    without re-reading the directory.
    """
    url = str(url or '').strip()
    if not url or url.startswith('-'):
        raise GitError(f'not a repository URL: {url or "(empty)"}')
    parent = Path(parent).expanduser().resolve()
    if not parent.is_dir():
        raise GitError(f'not a directory: {parent}')
    name = str(name or '').strip() or re.sub(r'\.git$', '', url.rstrip('/').rpartition('/')[2])
    if not name or '/' in name or name in ('.', '..'):
        raise GitError(f'cannot work out a folder name for {url}')
    target = parent/name
    if target.exists():
        raise GitError(f'{name} already exists in {parent.name}')
    _run(parent, 'clone', '--', url, name, timeout=600)
    return target


_CACHE, _CACHE_LOCK = {}, threading.RLock()
_CACHE_TTL = .45


def _cached(root, key, make):
    cache_key = (str(root), key)
    now = time.monotonic()
    with _CACHE_LOCK:
        hit = _CACHE.get(cache_key)
        if hit and now - hit[0] < _CACHE_TTL:
            return hit[1]
    value = make()
    with _CACHE_LOCK:
        _CACHE[cache_key] = (time.monotonic(), value)
    return value


def _invalidate(root):
    root = str(root)
    with _CACHE_LOCK:
        for key in [k for k in _CACHE if k[0] == root]:
            _CACHE.pop(key, None)


def _remote_web_url(raw):
    """Translate common Git transport URLs to a human-facing repository URL."""
    raw = (raw or '').strip()
    if not raw:
        return ''
    if re.match(r'^[^/@:]+@[^:]+:.+', raw):
        user_host, path = raw.split(':', 1)
        raw = f'https://{user_host.split("@", 1)[1]}/{path}'
    elif raw.startswith('ssh://'):
        parsed = urlparse(raw)
        raw = f'https://{parsed.hostname or ""}{parsed.path}'
    elif raw.startswith('git://'):
        raw = 'https://' + raw[6:]
    if raw.startswith(('http://', 'https://')):
        return raw.removesuffix('.git').rstrip('/')
    return ''


def _summarise(out):
    """One sentence about where the repository now is, for the surface that has to say it.

    The case this exists for is `merge --squash`, which stages its whole result and stops
    without committing. That is Git doing exactly what was asked, and it looks precisely like
    the IDE having dirtied the index by itself -- so it gets said out loud instead.
    """
    op, staged, conflicted = out['op'], len(out['staged']), len(out['conflicted'])
    if conflicted:
        return f'{op} stopped at {conflicted} conflicted file{"" if conflicted == 1 else "s"} -- resolve them to continue'
    if out['operation']['active']:
        return f'{out["operation"]["active"]} is in progress -- continue, skip, or abort it'
    if staged and not out['moved']:
        return f'{op} staged {staged} file{"" if staged == 1 else "s"} without committing -- commit to finish'
    if out['moved']:
        return f'{op} moved this branch to {out["head"]}'
    return out['message'].splitlines()[0] if out['message'] else f'{op} changed nothing'


def _explain_filters(broken):
    """Why files keep coming back as modified, in the words of the thing that is wrong.

    Named commands rather than a general warning, because the fix is always to install
    something into a particular virtualenv and the person needs to know which something.
    """
    missing = [r for r in broken if r['configured']]
    unconfigured = [r for r in broken if not r['configured']]
    lines = []
    if missing:
        which = ', '.join(f'{r["name"]} (`{shorten(r["clean"] or r["smudge"], 60)}`)' for r in missing)
        lines.append(
            f'This repository cleans files through {which}, and that command cannot be found in '
            f'the environment Leela runs Git in. Git does not treat a failing filter as an error, '
            f'so affected files -- notebooks, usually -- will keep reappearing as modified however '
            f'often you stage them. Installing it into this project\'s virtualenv fixes it.')
    if unconfigured:
        lines.append(
            f'{", ".join(r["name"] for r in unconfigured)} is named in .gitattributes but '
            f'configured nowhere, so Git is passing that content through unchanged.')
    return '\n\n'.join(lines)


def shorten(text, limit):
    text = ' '.join(str(text or '').split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


def _unborn(oid):
    "Git's all-zero oid: this line is in the working tree and in no commit yet."
    return set(str(oid)) == {'0'}


# A notebook's file lines are not its cells' lines, and blame is not the only thing that has
# to translate between the two -- code search now needs the same mapping to open a hit in the
# cell that holds it. So the scan lives in the notebook block, which owns the format, and
# blame borrows it: one mapping, or two that disagree about somebody's real notebook.
_source_spans = source_spans


@dataclass
class GitRepo:
    root: Path

    @classmethod
    def at(cls, path):
        root = repo_root(path)
        if root is None:
            raise GitError(f'{Path(path).name or path} is not inside a Git repository')
        return cls(root)

    def run(self, *args, **kwargs):
        return _run(self.root, *args, **kwargs).stdout

    def _mutate(self, *args, **kwargs):
        try:
            return self.run(*args, **kwargs)
        finally:
            _invalidate(self.root)

    # Where a set-aside working tree is pinned while an operation borrows the tree. Separate
    # from the safepoint ref because this one is deleted on the way out and that one is kept.
    AUTOSTASH_REF = 'refs/leela/autostash'

    def _set_aside(self, op):
        """Snapshot the dirty tree and clear it, returning the commit -- or `''` if it was clean.

        `stash create` builds the commit without touching anything, and the `reset --hard`
        after it is what actually frees the tree. Doing it in that order means the snapshot
        exists before the tree is cleared, rather than the other way around. The stash *list*
        is deliberately not involved: this is Leela borrowing the tree for a moment, and it
        should not leave an entry behind for someone to wonder about later.
        """
        if not self._blocking_changes():
            return ''
        created = _run(self.root, 'stash', 'create', check=False).stdout.strip()
        if not created:
            return ''
        _run(self.root, 'update-ref', f'{self.AUTOSTASH_REF}/{op}', created, check=False)
        _run(self.root, 'reset', '--hard', check=False)
        return created

    def _bring_back(self, oid):
        """Reapply a set-aside tree; returns a note when it would not go back on cleanly.

        Not an exception: the operation itself succeeded, and the person needs to be told where
        their work is rather than told that nothing happened. The commit is named in the note
        because that is the whole recovery -- it is a real commit and it is pinned.

        A failed `stash apply` leaves conflict markers in the files it got half way through,
        which is the worst of the three possible outcomes: not the work, not the result, and no
        way to tell which lines are which. So a failure is followed by `reset --hard` -- the
        snapshot commit still holds everything, and a clean tree is what lets the caller decide
        to undo the whole operation instead.
        """
        applied = _run(self.root, 'stash', 'apply', '--index', oid, check=False)
        if applied.returncode:
            _run(self.root, 'reset', '--hard', check=False)
            applied = _run(self.root, 'stash', 'apply', oid, check=False)
        if applied.returncode:
            _run(self.root, 'reset', '--hard', check=False)
            return (f'Your uncommitted work would not go back on top of this result, so it has '
                    f'been left as commit {oid[:9]} -- recover it with `git stash apply {oid}`.')
        return ''

    def _attempt(self, *args, **kwargs):
        """Run a mutation whose conflicts are an outcome rather than a failure.

        A conflicted merge exits non-zero, and reading that as an error is what turned the
        ordinary half of merging into a red message with no resolver behind it. So the exit code
        is read against the state the command left: conflicted files, or an operation in
        progress, mean it did the thing it does and the caller should be shown that. Anything
        else is a real failure and still raises.
        """
        kwargs['check'] = False
        try:
            p = _run(self.root, *args, **kwargs)
        finally:
            _invalidate(self.root)
        text = '\n'.join(x for x in ((p.stdout or '').strip(), (p.stderr or '').strip()) if x)
        if not p.returncode:
            return text
        if self._operation()['active'] or any(c['conflicted'] for c in self._changes_uncached()):
            return text
        raise GitError(text or f'git {args[0] if args else "command"} exited {p.returncode}')

    def _guarded(self, op, call, autostash=False):
        """One risky mutation: a way back recorded first, and a report of what it left behind.

        The safepoint, the mutation and the restore are all inside a single write lock, so
        nothing else in this repository can move between deciding where we were and going
        somewhere else.

        When the operation fails *and* the set-aside tree will not reapply, both sentences are
        reported together: the failure says why, and the note says where the work went. Either
        one alone would be the wrong half.
        """
        with gateway().transaction(self.root, op) as point:
            aside = self._set_aside(op) if autostash else ''
            failure, message = None, ''
            try:
                message = call() or ''
            except GitError as e:
                failure = e
            finally:
                _invalidate(self.root)
            note = self._bring_back(aside) if aside else ''
            _invalidate(self.root)
            if failure is not None:
                if note:
                    raise GitError(f'{failure}\n\n{note}') from failure
                raise failure
            return self._outcome(op, point, message, note, bool(aside))

    def _outcome(self, op, point, message='', note='', set_aside=False):
        """What one mutation left the repository as -- the response every mutation returns.

        A string of Git's stdout is not enough for a surface that has to decide what to draw
        next: whether to offer *commit*, whether to open the conflict resolver, whether an undo
        is available. This is that, and `summary` is the sentence.
        """
        changes = self._changes_uncached()
        head = _run(self.root, 'rev-parse', '--short', 'HEAD', check=False)
        after = head.stdout.strip() if not head.returncode else ''
        out = {
            'op': op, 'message': (message or '').strip(), 'note': note,
            'head': after, 'head_before': point.head[:9] if point else '',
            'moved': bool(point) and bool(after) and not point.head.startswith(after),
            'branch': self.run('branch', '--show-current').strip(),
            'staged': [c['path'] for c in changes if c['staged']],
            'conflicted': [c['path'] for c in changes if c['conflicted']],
            'operation': self._operation(),
            'kept_work': set_aside and not note,
            'undo': point.token if point else '', 'undoes': point.describe() if point else '',
        }
        out['summary'] = _summarise(out)
        return out

    def undo(self, token=''):
        "Put this repository back where the named safepoint says it was."
        outcome = gateway().undo(self.root, token)
        _invalidate(self.root)
        return outcome

    def safepoints(self):
        "The recorded ways back for this repository, newest first."
        return [{'token': p.token, 'op': p.op, 'head': p.head[:9], 'branch': p.branch,
                 'dirty': p.dirty, 'created_at': p.created_at, 'describe': p.describe()}
                for p in gateway().journal(self.root)]

    def _branches(self):
        """Local and unclaimed remote-tracking branches, newest commit first."""
        fmt = '%(refname)%00%(refname:short)%00%(HEAD)%00%(upstream:short)%00' \
              '%(upstream:trackshort)%00%(objectname:short)%00%(subject)%00' \
              '%(committerdate:unix)%00%(committerdate:iso-strict)%00%(authorname)%00%(symref)'
        raw = self.run('for-each-ref', f'--format={fmt}', '--sort=-committerdate',
                       'refs/heads', 'refs/remotes')
        parsed, claimed = [], set()
        for line in raw.splitlines():
            values = (line.split('\0') + [''] * 11)[:11]
            full, name, head, upstream, track, oid, subject, stamp, date, author, symref = values
            if full.startswith('refs/remotes/') and (symref or full.endswith('/HEAD')):
                continue
            remote = full.startswith('refs/remotes/')
            if not remote and upstream:
                claimed.add(upstream)
            parsed.append({
                'name': name, 'full_name': full, 'current': head == '*',
                'upstream': upstream, 'track': track, 'oid': oid, 'subject': subject,
                'remote': remote, 'timestamp': int(stamp or 0), 'date': date,
                'author': author, 'merged': False,
            })
        merged_raw = _run(self.root, 'for-each-ref', '--merged=HEAD', '--format=%(refname)',
                          'refs/heads', 'refs/remotes', check=False).stdout
        merged = set(merged_raw.splitlines())
        rows = []
        for row in parsed:
            if row['remote'] and row['name'] in claimed:
                continue
            row['merged'] = row['full_name'] in merged
            rows.append(row)
        if rows:
            newest = max(row['timestamp'] for row in rows)
            for row in rows:
                row['latest'] = row['timestamp'] == newest
                row['default'] = False
        default = _run(self.root, 'symbolic-ref', '--quiet', '--short', 'refs/remotes/origin/HEAD',
                       check=False).stdout.strip()
        for row in rows:
            row['default'] = row['name'] in {default, default.partition('/')[2]}
        return rows

    def _changes_uncached(self):
        raw = _run(self.root, 'status', '--porcelain=v1', '-z').stdout
        fields, out, i = raw.split('\0'), [], 0
        while i < len(fields) and fields[i]:
            row = fields[i]
            i += 1
            xy, path = row[:2], row[3:]
            old = None
            if ('R' in xy or 'C' in xy) and i < len(fields):
                old, i = fields[i], i + 1
            out.append({
                'path': path, 'old_path': old, 'index': xy[0], 'worktree': xy[1],
                'staged': xy[0] not in (' ', '?'),
                'unstaged': xy[1] != ' ' or xy == '??', 'untracked': xy == '??',
                'conflicted': xy in ('DD', 'AU', 'UD', 'UA', 'DU', 'AA', 'UU'),
            })
        unstaged = self._diff_numstat(_run(self.root, 'diff', '--numstat', '-z', check=False).stdout)
        staged = self._diff_numstat(_run(self.root, 'diff', '--cached', '--numstat', '-z', check=False).stdout)
        for row in out:
            row['staged_stat'] = staged.get(row['path'])
            row['unstaged_stat'] = unstaged.get(row['path'])
            if row['untracked']:
                try:
                    data = (self.root/row['path']).read_bytes()
                    binary = b'\0' in data[:8192]
                    row['unstaged_stat'] = {'additions': None if binary else len(data.decode('utf-8', 'replace').splitlines()),
                                            'deletions': None if binary else 0, 'binary': binary}
                except OSError: pass
        return out

    def changes(self):
        """Current status for file-tree decoration.

        Working-tree files can change without touching Git metadata, so this intentionally
        stays uncached. Callers that already own an ``info`` snapshot should reuse its
        ``changes`` field instead of asking again.
        """
        return self._changes_uncached()

    def _gitdir(self):
        git_dir = Path(self.run('rev-parse', '--git-dir').strip())
        return git_dir if git_dir.is_absolute() else self.root/git_dir

    def filter_health(self):
        """Whether this repository's content filters can actually run.

        This exists to explain one specific mystery: a notebook that will not stay staged. nbdev
        configures a clean filter in `.gitattributes`; Git runs it on every `add` *and* on every
        `status`, because comparing a notebook to the index means cleaning it first. A filter
        whose command is not on the path Git was given fails without Git considering anything to
        have gone wrong -- so the file is compared in its uncleaned form, differs from the index
        for ever, and comes back as modified the moment it is staged.

        Nothing in Git reports that, so it is asked directly: which filters do the attributes
        name, what is each configured to run, and does that command exist in the environment
        Leela hands to Git. Memoised, because the answer changes with the virtualenv rather than
        with the working tree, and `info` is polled.
        """
        def probe():
            names = set()
            for p in (self.root/'.gitattributes', self._gitdir()/'info'/'attributes'):
                try:
                    names.update(re.findall(r'filter=([\w.+-]+)', p.read_text(encoding='utf-8',
                                                                             errors='replace')))
                except OSError:
                    continue
            rows = []
            for name in sorted(names):
                def config(field):
                    return _run(self.root, 'config', '--get', f'filter.{name}.{field}',
                                check=False).stdout.strip()
                clean, smudge = config('clean'), config('smudge')
                command = clean or smudge
                resolved = gateway().resolves(self.root, command) if command else ''
                rows.append({
                    'name': name, 'clean': clean, 'smudge': smudge,
                    'required': config('required').lower() == 'true',
                    'resolved': resolved,
                    # A filter named by the attributes but configured nowhere is Git passing the
                    # content through untouched, which is a different problem from a broken one.
                    'configured': bool(command),
                    'ok': bool(command) and bool(resolved),
                })
            broken = [r for r in rows if not r['ok']]
            return {'filters': rows, 'ok': not broken,
                    'explain': _explain_filters(broken) if broken else ''}
        return gateway().memo(self.root, 'filters', probe)

    def _operation(self):
        git_dir = self._gitdir()
        checks = (
            ('rebase', git_dir/'rebase-merge'), ('rebase', git_dir/'rebase-apply'),
            ('merge', git_dir/'MERGE_HEAD'), ('cherry-pick', git_dir/'CHERRY_PICK_HEAD'),
            ('revert', git_dir/'REVERT_HEAD'), ('bisect', git_dir/'BISECT_LOG'),
        )
        active = next((name for name, path in checks if path.exists()), '')
        return {'active': active, 'can_continue': active in {'rebase', 'cherry-pick', 'revert'},
                'can_skip': active in {'rebase', 'cherry-pick'}, 'can_abort': bool(active)}

    def _remotes(self):
        names = [x for x in self.run('remote').splitlines() if x]
        rows = []
        for name in names:
            fetch = _run(self.root, 'remote', 'get-url', name, check=False).stdout.strip()
            push = _run(self.root, 'remote', 'get-url', '--push', name, check=False).stdout.strip()
            rows.append({'name': name, 'fetch': fetch, 'push': push,
                         'web_url': _remote_web_url(fetch)})
        return rows

    def info(self):
        def collect():
            branch = self.run('branch', '--show-current').strip()
            head = _run(self.root, 'rev-parse', '--short', 'HEAD', check=False)
            oid = head.stdout.strip() if head.returncode == 0 else ''
            if not branch:
                branch = (oid + ' (detached)') if oid else 'HEAD (unborn)'
            upstream = _run(self.root, 'rev-parse', '--abbrev-ref', '@{upstream}', check=False)
            upstream_name = upstream.stdout.strip() if upstream.returncode == 0 else ''
            ahead = behind = 0
            if upstream_name:
                counts = self.run('rev-list', '--left-right', '--count', f'{upstream_name}...HEAD').split()
                if len(counts) == 2:
                    behind, ahead = map(int, counts)
            changes = self._changes_uncached()
            stashes = []
            for line in self.run('stash', 'list', '--format=%gd%x00%gs%x00%ct').splitlines():
                ref, subject, stamp = (line.split('\0') + ['', ''])[:3]
                stashes.append({'ref': ref, 'subject': subject, 'timestamp': int(stamp or 0)})
            tag_details = []
            tag_fmt = '%(refname:short)%00%(objectname:short)%00%(creatordate:unix)%00%(subject)'
            for line in self.run('tag', '-l', f'--format={tag_fmt}', '--sort=-creatordate').splitlines()[:100]:
                name, oid, stamp, subject = (line.split('\0') + [''] * 4)[:4]
                tag_details.append({'name': name, 'oid': oid, 'timestamp': int(stamp or 0), 'subject': subject})
            return {
                # `head` is what makes a commit visible to a watcher: committing the whole
                # working tree leaves the branch, the counts and the file list all saying
                # what they said before, and the one thing that moved is this.
                'root': str(self.root), 'branch': branch, 'head': oid, 'upstream': upstream_name,
                'ahead': ahead, 'behind': behind, 'clean': not changes, 'changes': changes,
                'branches': self._branches(), 'remotes': self._remotes(), 'stashes': stashes,
                'tags': [tag['name'] for tag in tag_details], 'tag_details': tag_details,
                'operation': self._operation(), 'fetched_at': self._fetch_time(),
                # Why a file might refuse to stay staged, when that is the case.
                'filters': self.filter_health(),
                'safepoints': self.safepoints()[:12],
            }
        value = _cached(self.root, 'info', collect)
        with _CACHE_LOCK:
            _CACHE[(str(self.root), 'changes')] = (time.monotonic(), value['changes'])
        return value

    def brief(self, fresh=False):
        """One repository as a single row: branch, drift, dirt, and how far past its last tag.

        `info` walks every ref and every tag, which is the right price for the panel that
        draws them and the wrong one multiplied by twenty repositories. This answers only
        what a workspace list shows, so a `RepoSet` can ask all of them at once.

        `fresh` is for the caller that is about to *act* on the answer. The shared snapshot
        is invalidated by mutations through this class, not by a commit someone made in a
        terminal a moment ago -- and deciding from a stale `ahead` is how a push silently
        becomes "nothing to push".
        """
        if fresh: _invalidate(self.root)
        def collect():
            branch = self.run('branch', '--show-current').strip()
            detached = not branch
            if detached:
                head = _run(self.root, 'rev-parse', '--short', 'HEAD', check=False)
                branch = head.stdout.strip() if head.returncode == 0 else 'HEAD (unborn)'
            upstream = _run(self.root, 'rev-parse', '--abbrev-ref', '@{upstream}', check=False)
            upstream_name = upstream.stdout.strip() if upstream.returncode == 0 else ''
            ahead = behind = 0
            if upstream_name:
                counts = self.run('rev-list', '--left-right', '--count', f'{upstream_name}...HEAD').split()
                if len(counts) == 2:
                    behind, ahead = map(int, counts)
            changes = self._changes_uncached()
            last = _run(self.root, 'log', '-1', '--format=%h%x00%s%x00%ct', check=False).stdout
            short, subject, stamp = (last.strip().split('\0') + [''] * 3)[:3]
            described = _run(self.root, 'describe', '--tags', '--abbrev=0', check=False)
            tag = described.stdout.strip() if described.returncode == 0 else ''
            unreleased = None
            if tag:
                counted = _run(self.root, 'rev-list', '--count', f'{tag}..HEAD', check=False)
                unreleased = int(counted.stdout.strip() or 0) if counted.returncode == 0 else None
            origin = _run(self.root, 'remote', 'get-url', 'origin', check=False).stdout.strip()
            return {
                'root': str(self.root), 'name': self.root.name, 'branch': branch,
                'detached': detached, 'upstream': upstream_name, 'ahead': ahead, 'behind': behind,
                'changed': len(changes), 'clean': not changes,
                'staged': sum(1 for c in changes if c['staged']),
                'unstaged': sum(1 for c in changes if c['unstaged'] and not c['untracked']),
                'untracked': sum(1 for c in changes if c['untracked']),
                'conflicted': sum(1 for c in changes if c['conflicted']),
                'last_commit': {'short': short, 'subject': subject, 'timestamp': int(stamp or 0)},
                'tag': tag, 'unreleased': unreleased, 'operation': self._operation()['active'],
                'fetched_at': self._fetch_time(), 'remote': origin,
                'web_url': _remote_web_url(origin),
            }
        return _cached(self.root, 'brief', collect)

    def _fetch_time(self):
        fetch_head = Path(self.run('rev-parse', '--git-path', 'FETCH_HEAD').strip())
        if not fetch_head.is_absolute():
            fetch_head = self.root/fetch_head
        try:
            return int(fetch_head.stat().st_mtime)
        except OSError:
            return 0

    def stage(self, paths): self._mutate('add', '--', *paths)
    def unstage(self, paths): self._mutate('restore', '--staged', '--', *paths)
    def discard(self, paths): self._mutate('restore', '--worktree', '--', *paths)

    def write_worktree(self, path, content):
        target = (self.root/str(path)).resolve()
        if not target.is_relative_to(self.root.resolve()):
            raise GitError('file is outside the repository')
        if target.exists() and not target.is_file():
            raise GitError(f'{path} is not a working-tree file')
        if not target.parent.exists():
            raise GitError(f'the parent directory for {path} does not exist')
        target.write_text(str(content), encoding='utf-8')
        _invalidate(self.root)

    def apply_patch(self, patch, staged=True, reverse=False):
        if not str(patch).strip():
            raise GitError('select at least one diff hunk')
        args = ['apply', '--whitespace=nowarn']
        if staged:
            args.append('--cached')
        if reverse:
            args.append('--reverse')
        self._mutate(*args, input=str(patch))

    def _switch(self, branch):
        remote = _run(self.root, 'show-ref', '--verify', '--quiet', f'refs/remotes/{branch}', check=False)
        if remote.returncode == 0:
            local_name = branch.partition('/')[2]
            local = _run(self.root, 'show-ref', '--verify', '--quiet', f'refs/heads/{local_name}', check=False)
            if local.returncode == 0:
                self._mutate('switch', local_name)
                self._mutate('branch', f'--set-upstream-to={branch}', local_name)
            else:
                self._mutate('switch', '--track', branch)
        else:
            self._mutate('switch', branch)
        return ''

    # Git's own words when a switch would lose an edit. Matched so that the retry below is
    # confined to that one refusal, rather than turned on for every way a switch can fail.
    _WOULD_CLOBBER = ('would be overwritten', 'local changes')

    def checkout(self, branch):
        """Switch branches, setting aside uncommitted work only if Git refuses to carry it.

        Git already moves compatible local edits across a switch, and it is better at deciding
        which those are than a guess made before the attempt. So the attempt comes first, and
        only its refusal -- the one PyCharm answers by shelving -- turns into a set-aside, a
        retry, and putting the work back on the other side.
        """
        if not str(branch).strip():
            raise GitError('choose a branch')

        def call():
            try:
                return self._switch(branch)
            except GitError as e:
                if not any(w in str(e).lower() for w in self._WOULD_CLOBBER):
                    raise
                here = self.run('branch', '--show-current').strip()
                aside = self._set_aside('checkout')
                if not aside:
                    raise
                self._switch(branch)
                if not (note := self._bring_back(aside)):
                    return f'your uncommitted work was carried to {branch}.'
                # It will not come along. Either outcome is defensible, but half of one is not:
                # go back to where we were, put the work back where it was, and say why. The
                # reapply cannot fail this time -- the snapshot was taken on this branch.
                self._switch(here)
                self._bring_back(aside)
                raise GitError(
                    f'cannot switch to {branch} without losing your uncommitted changes -- they '
                    f'conflict with what is on that branch. Nothing was changed; you are still '
                    f'on {here} with your work. Commit or stash it first.') from e

        return self._guarded('checkout', call)

    def create(self, branch, start='HEAD'): self._mutate('switch', '-c', branch, start)
    def rename_branch(self, old, new): self._mutate('branch', '-m', old, new)
    def set_upstream(self, branch, upstream): self._mutate('branch', f'--set-upstream-to={upstream}', branch)
    def unset_upstream(self, branch): self._mutate('branch', '--unset-upstream', branch)
    def delete(self, branch, force=False): self._mutate('branch', '-D' if force else '-d', branch)
    def delete_remote(self, remote, branch): self._mutate('push', remote, '--delete', branch, timeout=120)

    def commit(self, message, amend=False):
        if not message.strip():
            raise GitError('a commit message is required')
        args = ['commit', *(['--amend'] if amend else []), '-m', message.strip()]
        return self._guarded('commit', lambda: self._mutate(*args).strip())

    def fetch(self, remote='', prune=True):
        args = ['fetch', remote] if remote else ['fetch', '--all']
        if prune:
            args.append('--prune')
        return self._mutate(*args, timeout=120).strip()

    # `--autostash` is Git's own, and it is the whole of what PyCharm does by hand here.
    def pull(self):
        return self._guarded('pull', lambda: self._mutate(
            'pull', '--ff-only', '--autostash', timeout=120).strip())
    def push(self, publish=False, force_with_lease=False):
        args = ['push']
        if publish:
            branch = self.run('branch', '--show-current').strip()
            if not branch:
                raise GitError('cannot publish a detached HEAD')
            remotes = [x for x in self.run('remote').splitlines() if x]
            if not remotes:
                raise GitError('add a remote before publishing this branch')
            args += ['--set-upstream', 'origin' if 'origin' in remotes else remotes[0], branch]
        if force_with_lease:
            args.append('--force-with-lease')
        return self._mutate(*args, timeout=120).strip()

    def stash(self, message=''): return self._mutate('stash', 'push', '-u', *(['-m', message] if message else [])).strip()
    def stash_pop(self, ref='stash@{0}'):
        return self._guarded('stash pop', lambda: self._attempt('stash', 'pop', ref))
    def stash_apply(self, ref='stash@{0}'):
        return self._guarded('stash apply', lambda: self._attempt('stash', 'apply', ref))
    def stash_drop(self, ref='stash@{0}'): return self._mutate('stash', 'drop', ref).strip()

    def merge(self, branch, strategy='merge'):
        """Merge `branch`, setting uncommitted work aside for the length of it.

        `git merge` has no `--autostash` of its own, which is why the dirty-tree refusal is the
        one people answer by stashing by hand and sometimes forget to unstash. `_guarded` does
        that here, and puts the work back whichever way the merge went.
        """
        if strategy not in {'merge', 'squash', 'ff-only'}:
            raise GitError('merge strategy must be merge, squash, or ff-only')
        args = ['merge', '--no-edit']
        if strategy == 'squash': args.append('--squash')
        elif strategy == 'ff-only': args.append('--ff-only')
        return self._guarded('merge', lambda: self._attempt(*args, branch), autostash=True)

    def rebase(self, branch):
        return self._guarded('rebase', lambda: self._attempt('rebase', '--autostash', branch))
    def cherry_pick(self, ref):
        return self._guarded('cherry-pick', lambda: self._attempt('cherry-pick', ref))
    def revert(self, ref):
        return self._guarded('revert', lambda: self._attempt('revert', '--no-edit', ref))

    def reset(self, ref='HEAD', mode='mixed'):
        if mode not in {'soft', 'mixed', 'hard'}:
            raise GitError('reset mode must be soft, mixed, or hard')
        return self._guarded('reset', lambda: self._mutate('reset', f'--{mode}', ref).strip())

    def operation_action(self, action):
        active = self._operation()['active']
        if not active:
            raise GitError('no Git operation is in progress')
        if action not in {'continue', 'skip', 'abort'}:
            raise GitError('operation action must be continue, skip, or abort')
        command = {'cherry-pick': 'cherry-pick', 'revert': 'revert', 'rebase': 'rebase', 'merge': 'merge'}.get(active)
        if not command or (action == 'skip' and active not in {'rebase', 'cherry-pick'}):
            raise GitError(f'cannot {action} the active {active}')
        return self._guarded(f'{active} --{action}',
                             lambda: self._mutate(command, f'--{action}').strip())

    def tag(self, name, message='', ref='HEAD'):
        if not name.strip():
            raise GitError('a tag name is required')
        args = ['tag']
        if message.strip():
            args += ['-a', name.strip(), '-m', message.strip(), ref]
        else:
            args += [name.strip(), ref]
        return self._mutate(*args).strip()

    def delete_tag(self, name, remote=''):
        self._mutate('tag', '-d', name)
        if remote:
            self._mutate('push', remote, f':refs/tags/{name}', timeout=120)

    def add_remote(self, name, url): self._mutate('remote', 'add', name, url)
    def set_remote(self, name, url, push=False): self._mutate('remote', 'set-url', *(['--push'] if push else []), name, url)
    def remove_remote(self, name): self._mutate('remote', 'remove', name)

    def history(self, limit=100, skip=0, query='', ref='--all', path=''):
        limit, skip = max(1, min(int(limit), 500)), max(0, int(skip))
        fmt = '%H%x00%h%x00%P%x00%an%x00%ae%x00%at%x00%D%x00%G?%x00%s'
        args = ['log', ref, f'--max-count={limit}', f'--skip={skip}', f'--format={fmt}']
        if query:
            args += ['--regexp-ignore-case', f'--grep={query}']
        if path:
            args += ['--', path]
        rows = []
        for line in self.run(*args).splitlines():
            oid, short, parents, author, email, stamp, decoration, signature, subject = (line.split('\0') + [''] * 9)[:9]
            rows.append({'oid': oid, 'short': short, 'parents': parents.split(), 'author': author,
                         'email': email, 'timestamp': int(stamp or 0), 'decoration': decoration,
                         'signature': signature, 'subject': subject})
        return rows

    def reflog(self, limit=100):
        fmt = '%H%x00%h%x00%gD%x00%gs%x00%an%x00%at'
        rows = []
        for line in self.run('reflog', f'--max-count={max(1, min(int(limit), 500))}', f'--format={fmt}').splitlines():
            oid, short, selector, subject, author, stamp = (line.split('\0') + [''] * 6)[:6]
            rows.append({'oid': oid, 'short': short, 'selector': selector, 'subject': subject,
                         'author': author, 'timestamp': int(stamp or 0)})
        return rows

    def commit_detail(self, ref):
        meta = self.run('show', '-s', '--format=%H%x00%h%x00%P%x00%an%x00%ae%x00%at%x00%D%x00%B', ref)
        values = (meta.rstrip('\n').split('\0') + [''] * 8)[:8]
        oid, short, parents, author, email, stamp, decoration, message = values
        patch = self.run('show', '--format=', '--no-ext-diff', '--stat', '--patch', ref)
        return {'oid': oid, 'short': short, 'parents': parents.split(), 'author': author,
                'email': email, 'timestamp': int(stamp or 0), 'decoration': decoration,
                'message': message.strip(), 'patch': patch}

    def _resolve_ref(self, ref):
        """Resolve a user-facing ref to a commit without allowing option-like refs."""
        ref = str(ref or '').strip()
        if not ref:
            raise GitError('choose a branch, tag, or commit')
        found = _run(self.root, 'rev-parse', '--verify', '--end-of-options',
                     f'{ref}^{{commit}}', check=False)
        if found.returncode:
            raise GitError(f'unknown branch, tag, or commit: {ref}')
        return found.stdout.strip()

    @staticmethod
    def _diff_status(raw):
        """Parse ``git diff --name-status -z`` into rename-aware records."""
        fields, rows, i = raw.split('\0'), [], 0
        while i < len(fields) and fields[i]:
            status, i = fields[i], i + 1
            path = fields[i] if i < len(fields) else ''
            i += 1
            old_path = ''
            if status[:1] in {'R', 'C'}:
                old_path, path = path, fields[i] if i < len(fields) else path
                i += 1
            rows.append({'path': path, 'old_path': old_path, 'status': status[:1],
                         'similarity': int(status[1:] or 0)})
        return rows

    @staticmethod
    def _diff_numstat(raw):
        """Parse ``git diff --numstat -z`` including its three-field rename form."""
        fields, stats, i = raw.split('\0'), {}, 0
        while i < len(fields) and fields[i]:
            head, i = fields[i], i + 1
            bits = head.split('\t', 2)
            if len(bits) != 3: continue
            added, deleted, path = bits
            if not path and i + 1 < len(fields):
                _old, path, i = fields[i], fields[i + 1], i + 2
            stats[path] = {'additions': None if added == '-' else int(added or 0),
                           'deletions': None if deleted == '-' else int(deleted or 0),
                           'binary': added == '-' or deleted == '-'}
        return stats

    def review(self, base, head, mode='review'):
        """Structured branch review metadata with lazy per-file patches.

        ``review`` compares the merge base to ``head`` like a pull request; ``snapshot``
        compares the complete trees at the two named refs.
        """
        if mode not in {'review', 'snapshot'}:
            raise GitError('comparison mode must be review or snapshot')
        base_name, head_name = str(base).strip(), str(head).strip()
        base_oid, head_oid = self._resolve_ref(base_name), self._resolve_ref(head_name)
        merge_base = _run(self.root, 'merge-base', base_oid, head_oid, check=False).stdout.strip()
        if not merge_base:
            raise GitError(f'{base_name} and {head_name} do not share a merge base')
        diff_left = merge_base if mode == 'review' else base_oid
        status = self._diff_status(self.run('diff', '--name-status', '-z', '-M',
                                            diff_left, head_oid, '--'))
        stats = self._diff_numstat(self.run('diff', '--numstat', '-z', '-M',
                                            diff_left, head_oid, '--'))
        for row in status:
            row.update(stats.get(row['path'], {'additions': 0, 'deletions': 0, 'binary': False}))
        counts = self.run('rev-list', '--left-right', '--count', f'{base_oid}...{head_oid}').split()
        commits = self.history(limit=250, ref=f'{base_oid}..{head_oid}')
        alternate = None
        if mode == 'review' and not status and base_oid != head_oid:
            direct_status = self._diff_status(self.run('diff', '--name-status', '-z', '-M',
                                                       base_oid, head_oid, '--'))
            direct_stats = self._diff_numstat(self.run('diff', '--numstat', '-z', '-M',
                                                       base_oid, head_oid, '--'))
            alternate = {'files': len(direct_status),
                         'additions': sum((direct_stats.get(x['path']) or {}).get('additions') or 0
                                          for x in direct_status),
                         'deletions': sum((direct_stats.get(x['path']) or {}).get('deletions') or 0
                                          for x in direct_status)}
        head_now = _run(self.root, 'rev-parse', '--verify', 'HEAD', check=False).stdout.strip()
        return {'base': base_name, 'head': head_name, 'base_oid': base_oid,
                'head_oid': head_oid, 'diff_base_oid': diff_left, 'merge_base': merge_base,
                'mode': mode, 'base_only': int(counts[0]), 'head_only': int(counts[1]),
                'files': status, 'commits': commits, 'snapshot_alternative': alternate,
                'summary': {'files': len(status),
                            'additions': sum(x['additions'] or 0 for x in status),
                            'deletions': sum(x['deletions'] or 0 for x in status),
                            'binary': sum(bool(x['binary']) for x in status)},
                'can_apply': base_oid == head_now and merge_base == base_oid and not self.changes()}

    def _ref_file(self, ref, path):
        if not ref or not path: return ''
        result = _run(self.root, 'show', f'{ref}:{path}', check=False)
        return result.stdout if result.returncode == 0 else ''

    def review_file(self, base, head, path, mode='review', context=3):
        review = self.review(base, head, mode)
        known = next((x for x in review['files'] if x['path'] == path), None)
        if known is None:
            raise GitError(f'{path} is not changed in this comparison')
        patch = self.run('diff', '--no-ext-diff', f'--unified={max(0, min(int(context), 20))}',
                         '-M', review['diff_base_oid'], review['head_oid'], '--', path)
        old_path = known.get('old_path') or path
        left = self._ref_file(review['diff_base_oid'], old_path)
        right = self._ref_file(review['head_oid'], path)
        if str(path).lower().endswith('.ipynb'):
            left, right = self._notebook_content(left), self._notebook_content(right)
            patch = ''.join(difflib.unified_diff(left.splitlines(True), right.splitlines(True),
                                                 fromfile=f'{path} ({review["base"]})',
                                                 tofile=f'{path} ({review["head"]})', n=3))
        return {'file': known, 'patch': patch, 'left': left, 'right': right,
                'base': review['base'], 'head': review['head'],
                'mode': mode, 'can_apply': review['can_apply']}

    def commit_review(self, ref):
        oid = self._resolve_ref(ref)
        meta = self.commit_detail(oid)
        parent = meta['parents'][0] if meta['parents'] else self.run('mktree', input='').strip()
        status = self._diff_status(self.run('diff', '--name-status', '-z', '-M', parent, oid, '--'))
        stats = self._diff_numstat(self.run('diff', '--numstat', '-z', '-M', parent, oid, '--'))
        for row in status:
            row.update(stats.get(row['path'], {'additions': 0, 'deletions': 0, 'binary': False}))
        summary = {'files': len(status), 'additions': sum(x['additions'] or 0 for x in status),
                   'deletions': sum(x['deletions'] or 0 for x in status),
                   'binary': sum(bool(x['binary']) for x in status)}
        return {k: v for k, v in meta.items() if k != 'patch'} | {
            'base': parent, 'head': oid, 'files': status, 'summary': summary}

    def commit_file(self, ref, path, context=3):
        detail = self.commit_review(ref)
        known = next((x for x in detail['files'] if x['path'] == path), None)
        if known is None: raise GitError(f'{path} is not changed by this commit')
        old_path = known.get('old_path') or path
        patch = self.run('diff', '--no-ext-diff', f'--unified={max(0, min(int(context), 20))}',
                         '-M', detail['base'], detail['head'], '--', path)
        left, right = self._ref_file(detail['base'], old_path), self._ref_file(detail['head'], path)
        if str(path).lower().endswith('.ipynb'):
            left, right = self._notebook_content(left), self._notebook_content(right)
            patch = ''.join(difflib.unified_diff(left.splitlines(True), right.splitlines(True),
                                                 fromfile=f'{path} ({detail["base"][:8]})',
                                                 tofile=f'{path} ({detail["head"][:8]})', n=3))
        return {'file': known, 'patch': patch, 'left': left, 'right': right,
                'base': detail['base'], 'head': detail['head']}

    def _blocking_changes(self):
        """Tracked files with uncommitted work: what actually stops a merge or a rebase.

        Not `changes()`, which counts untracked files too. Git merges perfectly well beside
        an untracked `notes.md` -- it refuses only when the merge would *overwrite* one, and
        it says so at the time. Treating them as dirt meant a repository with a stray
        `uv.lock` could never merge anything again, and the button that would have said why
        was the one being disabled.
        """
        return [c for c in self.changes() if not c.get('untracked')]

    def merge_preview(self, incoming):
        current = self.run('branch', '--show-current').strip() or 'HEAD'
        current_oid, incoming_oid = self._resolve_ref('HEAD'), self._resolve_ref(incoming)
        merge_base = _run(self.root, 'merge-base', current_oid, incoming_oid, check=False).stdout.strip()
        if not merge_base:
            raise GitError(f'{current} and {incoming} do not share a merge base')
        if current_oid == incoming_oid: relation = 'identical'
        elif merge_base == current_oid: relation = 'fast-forward'
        elif merge_base == incoming_oid: relation = 'already-merged'
        else: relation = 'diverged'
        review = self.review(current, incoming, 'review')
        rehearsal = _run(self.root, 'merge-tree', '--write-tree', '--name-only',
                          current_oid, incoming_oid, check=False)
        conflicts = []
        if rehearsal.returncode:
            lines = rehearsal.stdout.splitlines()
            for line in lines[1:]:
                line = line.strip()
                if line and not line.startswith(('Auto-merging ', 'CONFLICT ')):
                    conflicts.append(line)
            conflicts = list(dict.fromkeys(conflicts))
        blocking = self._blocking_changes()
        return {'current': current, 'incoming': str(incoming), 'relation': relation,
                'clean': not blocking, 'dirty': [c['path'] for c in blocking][:20],
                'untracked': sum(1 for c in self.changes() if c.get('untracked')),
                'merge_base': merge_base,
                'conflicts': conflicts, 'conflict_likely': bool(rehearsal.returncode),
                'review': review}

    def rebase_preview(self, onto):
        """Describe replaying current-only commits on ``onto`` before mutating history."""
        current = self.run('branch', '--show-current').strip()
        if not current:
            raise GitError('cannot rebase a detached HEAD')
        current_oid, onto_oid = self._resolve_ref('HEAD'), self._resolve_ref(onto)
        base = _run(self.root, 'merge-base', current_oid, onto_oid, check=False).stdout.strip()
        if not base:
            raise GitError(f'{current} and {onto} do not share a merge base')
        commits = self.history(limit=250, ref=f'{onto_oid}..{current_oid}')
        rehearsal = _run(self.root, 'merge-tree', '--write-tree', '--name-only',
                          onto_oid, current_oid, check=False)
        conflicts = []
        if rehearsal.returncode:
            for line in rehearsal.stdout.splitlines()[1:]:
                line = line.strip()
                if line and not line.startswith(('Auto-merging ', 'CONFLICT ')):
                    conflicts.append(line)
        blocking = self._blocking_changes()
        return {'current': current, 'onto': str(onto), 'clean': not blocking,
                'dirty': [c['path'] for c in blocking][:20],
                'untracked': sum(1 for c in self.changes() if c.get('untracked')),
                'merge_base': base, 'commits': commits,
                'conflicts': list(dict.fromkeys(conflicts)),
                'conflict_likely': bool(rehearsal.returncode),
                'already_based': base == onto_oid, 'review': self.review(onto, current, 'review')}

    def compare(self, left, right):
        """Compare the complete snapshots at two refs, from ``left`` to ``right``."""
        review = self.review(left, right, 'snapshot')
        patch = self.run('diff', '--no-ext-diff', '--stat', '--patch',
                         review['base_oid'], review['head_oid'], '--')
        return {'left': left, 'right': right, 'left_only': review['base_only'],
                'right_only': review['head_only'],
                'changed_files': review['summary']['files'],
                'merge_base': review['merge_base'], 'patch': patch}

    def conflict_versions(self, path):
        change = next((row for row in self.changes() if row['path'] == path), None)
        if not change or not change['conflicted']:
            raise GitError(f'{path} is not conflicted')
        def stage(number):
            r = _run(self.root, 'show', f':{number}:{path}', check=False)
            return r.stdout if r.returncode == 0 else ''
        return {'path': path, 'base': stage(1), 'ours': stage(2), 'theirs': stage(3),
                'worktree': self._version(path, 'worktree'), 'status': change}

    def resolve_conflict(self, path, choice, content=None):
        """Settle one conflicted file and stage it as resolved.

        `ours` and `theirs` take a whole side, which is the answer often enough to be worth a
        button. `resolved` is the three-pane editor's answer: the text a person assembled from
        both sides, which is the only one of the four that is not a file Git already has.
        """
        if choice not in {'ours', 'theirs', 'worktree', 'resolved'}:
            raise GitError('conflict choice must be ours, theirs, worktree, or resolved')
        if choice == 'resolved':
            if content is None:
                raise GitError('a resolved file needs its resolved contents')
            self.write_worktree(path, content)
        elif choice != 'worktree':
            self._mutate('checkout', f'--{choice}', '--', path)
        self.stage([path])
        remaining = [c['path'] for c in self._changes_uncached() if c['conflicted']]
        return {'path': path, 'choice': choice, 'conflicted': remaining,
                'operation': self._operation(),
                'summary': (f'{len(remaining)} file{"" if len(remaining) == 1 else "s"} still '
                            f'conflicted' if remaining else
                            'every conflict is resolved -- commit to finish the merge')}

    def blame(self, path, start=1, end=0):
        args = ['blame', '--line-porcelain']
        if end:
            args += ['-L', f'{max(1, int(start))},{max(int(start), int(end))}']
        args += ['--', path]
        rows, current = [], None
        for line in self.run(*args).splitlines():
            if re.match(r'^[0-9a-f^]{40} ', line):
                oid, original, final, count = (line.split() + ['1'])[:4]
                current = {'oid': oid.lstrip('^'), 'original_line': int(original),
                           'line': int(final), 'count': int(count), 'author': '',
                           'timestamp': 0, 'summary': '', 'text': ''}
            elif current is not None and line.startswith('author '): current['author'] = line[7:]
            elif current is not None and line.startswith('author-time '): current['timestamp'] = int(line[12:] or 0)
            elif current is not None and line.startswith('summary '): current['summary'] = line[8:]
            elif current is not None and line.startswith('\t'):
                current['text'] = line[1:]
                rows.append(current)
                current = None
        return rows

    def blame_notebook(self, path):
        """`git blame` for a notebook, grouped into the cells you actually wrote.

        Blaming a `.ipynb` blames its JSON: `"source": [`, `"execution_count": null`, and
        every code line wrapped in quotes with its newline escaped. That is a result and not
        an answer. So the file is blamed as usual, and each cell's source lines are matched
        back to the file lines that hold them -- the text shown is the decoded source, and the
        attribution beside it is the one Git gave that line.

        Per cell you get who touched it last and which commits it is made of; per line you
        get the real blame. Both, because "this cell is Karthik's from March" is the summary
        and "this line is not" is the reason you looked.

        One inherited limitation, worth knowing rather than hiding: the blame is still of the
        JSON, and JSON needs commas. Appending a line to a cell rewrites the line *before* it
        -- the previous last entry gains a trailing comma -- so that line is attributed to the
        commit that appended after it. Fixing it properly means blaming a flattened notebook
        through history rather than the file, which is a different and much larger thing.
        """
        rows = self.blame(path)
        by_line = {r['line']: r for r in rows}
        raw = self._version(path, 'worktree')
        if not raw:
            try: raw = (self.root/path).read_text(errors='replace')
            except OSError: raw = ''
        try: cells = (json.loads(raw) or {}).get('cells') or []
        except (TypeError, json.JSONDecodeError):
            return {'notebook': False, 'path': path, 'cells': [], 'lines': rows,
                    'error': 'this file is not a notebook Leela can read'}
        spans = _source_spans(raw, cells)
        out, seen = [], {}
        for i, (cell, span) in enumerate(zip(cells, spans), 1):
            source = cell.get('source') or ''
            source = source if isinstance(source, list) else str(source).splitlines(True)
            lines = []
            if span:
                for n, text in zip(range(span[0], span[1] + 1), source):
                    r = by_line.get(n)
                    if r is None: continue
                    lines.append({'line': n, 'n': n - span[0] + 1, 'text': str(text).rstrip('\n'),
                                  'oid': r['oid'], 'author': r['author'], 'summary': r['summary'],
                                  'timestamp': r['timestamp'], 'uncommitted': _unborn(r['oid'])})
                    seen.setdefault(r['oid'], {'oid': r['oid'], 'author': r['author'],
                                               'summary': r['summary'], 'timestamp': r['timestamp'],
                                               'uncommitted': _unborn(r['oid'])})
            commits, last = {}, None
            for row in lines:
                commits[row['oid']] = commits.get(row['oid'], 0) + 1
                # `>=` so that lines committed in the same second resolve to the later one in
                # the cell. Author time has one-second resolution and an edit is usually
                # further down than what it followed; there is nothing better available from
                # blame alone, so the tie-break is at least deterministic.
                if last is None or row['timestamp'] >= last['timestamp']: last = row
            out.append({
                'index': i, 'id': str(cell.get('id') or ''), 'kind': str(cell.get('cell_type') or 'code'),
                'first': span[0] if span else 0, 'last': span[1] if span else 0,
                'lines': lines, 'commits': [{'oid': k, 'lines': v} for k, v in commits.items()],
                'authors': sorted({row['author'] for row in lines if row['author']}),
                'touched': last and {k: last[k] for k in ('oid', 'author', 'summary', 'timestamp',
                                                          'uncommitted')} or {},
                # A cell whose lines could not be located is reported rather than dropped:
                # the file is in a shape this cannot read, and saying so beats a blank row.
                'mapped': bool(span),
            })
        return {'notebook': True, 'path': path, 'cells': out, 'lines': rows,
                'commits': sorted(seen.values(), key=lambda c: -c['timestamp']), 'error': ''}

    def worktrees(self):
        rows, current = [], None
        for line in self.run('worktree', 'list', '--porcelain').splitlines() + ['']:
            if line.startswith('worktree '):
                current = {'path': line[9:], 'head': '', 'branch': '', 'bare': False, 'detached': False, 'locked': False}
            elif not line and current:
                rows.append(current); current = None
            elif current is not None:
                key, _, value = line.partition(' ')
                if key in {'bare', 'detached', 'locked'}: current[key] = True
                elif key == 'branch': current[key] = value.removeprefix('refs/heads/')
                elif key == 'HEAD': current['head'] = value
        return rows

    def add_worktree(self, path, branch='', create=False):
        args = ['worktree', 'add']
        if create and branch: args += ['-b', branch]
        args += [path]
        if branch and not create: args.append(branch)
        return self._mutate(*args).strip()

    def remove_worktree(self, path, force=False):
        return self._mutate('worktree', 'remove', *(['--force'] if force else []), path).strip()

    def submodules(self):
        r = _run(self.root, 'submodule', 'status', '--recursive', check=False)
        if r.returncode and not (self.root/'.gitmodules').exists(): return []
        rows = []
        for line in r.stdout.splitlines():
            state, body = line[:1], line[1:].strip()
            oid, _, tail = body.partition(' ')
            path, _, description = tail.partition(' ')
            rows.append({'path': path, 'oid': oid, 'state': state,
                         'description': description.strip('()')})
        return rows

    def diff(self, path='', staged=False, left='', right='', context=3):
        args = ['diff', '--no-ext-diff', f'--unified={max(0, min(int(context), 20))}']
        if staged: args.append('--cached')
        if left and right: args.append(f'{left}...{right}')
        elif left: args.append(left)
        if path: args += ['--', path]
        return self.run(*args)

    def _version(self, path, where):
        if where == 'worktree':
            try: return (self.root/path).read_text(errors='replace')
            except OSError: return ''
        spec = f':{path}' if where == 'index' else f'HEAD:{path}'
        r = _run(self.root, 'show', spec, check=False)
        return r.stdout if r.returncode == 0 else ''

    @staticmethod
    def _notebook_content(raw):
        if not raw: return ''
        try: cells = (json.loads(raw) or {}).get('cells') or []
        except (TypeError, json.JSONDecodeError): return raw
        parts = []
        for i, cell in enumerate(cells, 1):
            source = cell.get('source') or ''
            if isinstance(source, list): source = ''.join(source)
            kind = cell.get('cell_type') or 'cell'
            parts.append(f'# %% {kind} · cell {i}\n{source.rstrip()}')
        return '\n\n'.join(parts) + ('\n' if parts else '')

    def diff_view(self, path, staged=False):
        change = next((c for c in self.changes() if c['path'] == path), None)
        if change and change['untracked'] and not staged:
            try: raw_content = (self.root/path).read_text(errors='replace')
            except OSError: raw_content = ''
            raw = ''.join(difflib.unified_diff(
                [], raw_content.splitlines(True), fromfile='/dev/null', tofile=f'b/{path}', n=3))
        else:
            raw = self.diff(path, staged)
        left = self._version(path, 'head' if staged else 'index')
        right = self._version(path, 'index' if staged else 'worktree')
        if not str(path).lower().endswith('.ipynb'):
            return {'text': raw, 'content': raw, 'notebook': False, 'left': left, 'right': right}
        before, after = self._notebook_content(left), self._notebook_content(right)
        content = ''.join(difflib.unified_diff(
            before.splitlines(True), after.splitlines(True),
            fromfile=f'{path} (before)', tofile=f'{path} (after)', n=3))
        return {'text': raw, 'content': content, 'notebook': True, 'left': before, 'right': after}

    @staticmethod
    def _cells(raw):
        "id -> source for one notebook's cells, in order. A cell with no id is keyed by position."
        try: cells = (json.loads(raw) or {}).get('cells') or []
        except (TypeError, json.JSONDecodeError): return {}
        out = {}
        for i, c in enumerate(cells):
            src = c.get('source') or ''
            if isinstance(src, list): src = ''.join(src)
            out[str(c.get('id') or f'#{i}')] = src
        return out

    @staticmethod
    def _line_ranges(before, after):
        """Lines of `after` that differ from `before`, 1-based, in `file_changes`'s shape.

        A deletion has no line of its own in the new text, so it is reported at the line that
        closed over it -- the same thing git's `@@ ... +n,0 @@` means, and what the editor
        needs to put a mark somewhere the reader can see.
        """
        old, new = before.splitlines(), after.splitlines()
        out = []
        for tag, _, _, b1, b2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
            if tag == 'equal': continue
            if tag == 'delete':
                at = max(1, min(b1 + 1, len(new) or 1))
                out.append({'from': at, 'to': at, 'kind': 'deleted'})
            else:
                out.append({'from': b1 + 1, 'to': max(b1 + 1, b2), 'kind': 'added' if tag == 'insert' else 'modified'})
        return out

    def notebook_changes(self, path):
        """Which cells of a notebook differ from HEAD, and which lines within them.

        The document's own line numbers are the wrong unit: the file is JSON, so a
        one-character edit to a cell's source moves every line after it and `file_changes`
        would mark the whole notebook. Cells carry nbformat ids, which survive edits above
        them, so the comparison is per cell -- a cell whose id is new is `added`, one whose
        source moved is `modified` -- and each modified cell is then diffed against its own
        previous source, giving line numbers that mean something *inside that editor*, which
        is the only place they are ever drawn.
        """
        out = {'path': path, 'changed': False, 'cells': {}, 'lines': {}}
        if not str(path).lower().endswith('.ipynb'): return out
        changed = next((c for c in self.changes() if c['path'] == path), None)
        if changed is None: return out
        now = self._cells(self._version(path, 'worktree'))
        # An untracked notebook has no previous version at all, so every cell is new.
        was = {} if changed['untracked'] else self._cells(self._version(path, 'head'))
        for cid, src in now.items():
            if was.get(cid) == src: continue
            out['cells'][cid] = 'added' if cid not in was else 'modified'
            out['lines'][cid] = self._line_ranges(was.get(cid, ''), src)
        out['changed'] = bool(out['cells'])
        return out

    @staticmethod
    def _patch_hunks(diff):
        """Every hunk of one file's unified diff, as a patch that can be applied on its own.

        `ranges` below is read from a zero-context diff, because a gutter mark belongs on exactly
        the lines that moved. A *patch* wants the opposite: `git apply` places a hunk by the
        context around it, so those three lines either side are what make staging or reverting one
        change land where it was meant to -- and a zero-context hunk of a repeated line can land
        anywhere. So both readings of the same change are kept: the context for Git, the span of
        changed lines for the editor to point at, and the removed text so the editor can show what
        used to be there without a second request for the file's committed version.

        The span follows `file_changes`'s own convention, which is Git's: additions and
        modifications are reported at the new lines they produced, and a pure deletion at the line
        it was removed after, since it has no line of its own to point at any more.
        """
        lines = str(diff or '').split('\n')
        first = next((i for i, x in enumerate(lines) if x.startswith('@@')), -1)
        if first < 0: return []
        header, chunks, current = '\n'.join(lines[:first]) + '\n', [], []
        for line in lines[first:]:
            if line.startswith('@@') and current: chunks.append(current); current = []
            current.append(line)
        if current: chunks.append(current)
        out = []
        for chunk in chunks:
            m = re.match(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@', chunk[0])
            if not m: continue
            at, old, new, adds, anchor = int(m.group(1)), [], [], [], None
            for line in chunk[1:]:
                # `\ No newline at end of file` belongs to the patch but counts as no line.
                if line.startswith('\\'): continue
                if line.startswith('-'):
                    old.append(line[1:])
                    if anchor is None: anchor = max(1, at - 1)
                elif line.startswith('+'): new.append(line[1:]); adds.append(at); at += 1
                else: at += 1
            if not old and not new: continue
            span = (min(adds), max(adds)) if adds else (anchor, anchor)
            out.append({'index': len(out), 'from': span[0], 'to': span[1],
                        'kind': 'added' if not old else 'deleted' if not new else 'modified',
                        'old': ''.join(x + '\n' for x in old), 'new': ''.join(x + '\n' for x in new),
                        'patch': header + '\n'.join(chunk).rstrip('\n') + '\n'})
        return out

    def file_changes(self, path):
        changed = next((c for c in self.changes() if c['path'] == path), None)
        if changed is None:
            return {'path': path, 'changed': False, 'ranges': [], 'hunks': [], 'diff': ''}
        p = self.root/path
        if changed['untracked']:
            try: lines = max(1, len(p.read_text(errors='replace').splitlines()))
            except OSError: lines = 1
            return {'path': path, 'changed': True,
                    'ranges': [{'from': 1, 'to': lines, 'kind': 'added'}],
                    'hunks': [], 'diff': '', 'status': changed}
        r = _run(self.root, 'diff', '--no-ext-diff', '--unified=3', 'HEAD', '--', path, check=False)
        exact = _run(self.root, 'diff', '--no-ext-diff', '--unified=0', 'HEAD', '--', path, check=False)
        if r.returncode:
            r = _run(self.root, 'diff', '--no-ext-diff', '--unified=3', '--', path)
            exact = _run(self.root, 'diff', '--no-ext-diff', '--unified=0', '--', path)
        ranges = []
        for m in re.finditer(r'^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', exact.stdout, re.M):
            old_n, start, new_n = int(m.group(1) or 1), int(m.group(2)), int(m.group(3) or 1)
            kind = 'added' if old_n == 0 else 'deleted' if new_n == 0 else 'modified'
            start = max(1, start)
            end = max(start, start + max(1, new_n) - 1)
            ranges.append({'from': start, 'to': end, 'kind': kind})
        return {'path': path, 'changed': True, 'ranges': ranges,
                'hunks': self._patch_hunks(r.stdout), 'diff': r.stdout, 'status': changed}
