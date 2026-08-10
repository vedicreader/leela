"""Structured, low-latency Git integration for Leela's browser surfaces.

Git remains the source of truth. Commands never pass through a shell, mutating operations
invalidate the shared short-lived snapshot, and records are deliberately presentation-free.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlparse

__all__ = ['GitRepo', 'GitError', 'repo_root']


class GitError(RuntimeError):
    pass


def _run(cwd, *args, check=True, input=None, timeout=30):
    exe = shutil.which('git')
    if not exe:
        raise GitError('git is not installed or not on PATH')
    try:
        p = subprocess.run(
            [exe, *map(str, args)], cwd=str(cwd), input=input, text=True,
            encoding='utf-8', errors='replace', stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise GitError(f'git {args[0] if args else "command"} timed out after {timeout}s') from e
    if check and p.returncode:
        raise GitError((p.stderr or p.stdout or f'git exited {p.returncode}').strip())
    return p


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

    def _operation(self):
        git_dir = Path(self.run('rev-parse', '--git-dir').strip())
        if not git_dir.is_absolute():
            git_dir = self.root / git_dir
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
            if not branch:
                head = _run(self.root, 'rev-parse', '--short', 'HEAD', check=False)
                branch = (head.stdout.strip() + ' (detached)') if head.returncode == 0 else 'HEAD (unborn)'
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
                'root': str(self.root), 'branch': branch, 'upstream': upstream_name,
                'ahead': ahead, 'behind': behind, 'clean': not changes, 'changes': changes,
                'branches': self._branches(), 'remotes': self._remotes(), 'stashes': stashes,
                'tags': [tag['name'] for tag in tag_details], 'tag_details': tag_details,
                'operation': self._operation(), 'fetched_at': self._fetch_time(),
            }
        value = _cached(self.root, 'info', collect)
        with _CACHE_LOCK:
            _CACHE[(str(self.root), 'changes')] = (time.monotonic(), value['changes'])
        return value

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

    def checkout(self, branch):
        if not str(branch).strip():
            raise GitError('choose a branch')
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

    def create(self, branch, start='HEAD'): self._mutate('switch', '-c', branch, start)
    def rename_branch(self, old, new): self._mutate('branch', '-m', old, new)
    def set_upstream(self, branch, upstream): self._mutate('branch', f'--set-upstream-to={upstream}', branch)
    def unset_upstream(self, branch): self._mutate('branch', '--unset-upstream', branch)
    def delete(self, branch, force=False): self._mutate('branch', '-D' if force else '-d', branch)
    def delete_remote(self, remote, branch): self._mutate('push', remote, '--delete', branch, timeout=120)

    def commit(self, message, amend=False):
        if not message.strip():
            raise GitError('a commit message is required')
        return self._mutate('commit', *(['--amend'] if amend else []), '-m', message.strip()).strip()

    def fetch(self, remote='', prune=True):
        args = ['fetch', remote] if remote else ['fetch', '--all']
        if prune:
            args.append('--prune')
        return self._mutate(*args, timeout=120).strip()

    def pull(self): return self._mutate('pull', '--ff-only', timeout=120).strip()
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
    def stash_pop(self, ref='stash@{0}'): return self._mutate('stash', 'pop', ref).strip()
    def stash_apply(self, ref='stash@{0}'): return self._mutate('stash', 'apply', ref).strip()
    def stash_drop(self, ref='stash@{0}'): return self._mutate('stash', 'drop', ref).strip()
    def merge(self, branch, strategy='merge'):
        if strategy not in {'merge', 'squash', 'ff-only'}:
            raise GitError('merge strategy must be merge, squash, or ff-only')
        args = ['merge', '--no-edit']
        if strategy == 'squash': args.append('--squash')
        elif strategy == 'ff-only': args.append('--ff-only')
        return self._mutate(*args, branch).strip()
    def rebase(self, branch): return self._mutate('rebase', branch).strip()
    def cherry_pick(self, ref): return self._mutate('cherry-pick', ref).strip()
    def revert(self, ref): return self._mutate('revert', '--no-edit', ref).strip()
    def reset(self, ref='HEAD', mode='mixed'):
        if mode not in {'soft', 'mixed', 'hard'}:
            raise GitError('reset mode must be soft, mixed, or hard')
        return self._mutate('reset', f'--{mode}', ref).strip()

    def operation_action(self, action):
        active = self._operation()['active']
        if not active:
            raise GitError('no Git operation is in progress')
        if action not in {'continue', 'skip', 'abort'}:
            raise GitError('operation action must be continue, skip, or abort')
        command = {'cherry-pick': 'cherry-pick', 'revert': 'revert', 'rebase': 'rebase', 'merge': 'merge'}.get(active)
        if not command or (action == 'skip' and active not in {'rebase', 'cherry-pick'}):
            raise GitError(f'cannot {action} the active {active}')
        return self._mutate(command, f'--{action}').strip()

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
        return {'current': current, 'incoming': str(incoming), 'relation': relation,
                'clean': not self.changes(), 'merge_base': merge_base,
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
        return {'current': current, 'onto': str(onto), 'clean': not self.changes(),
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

    def resolve_conflict(self, path, choice):
        if choice not in {'ours', 'theirs', 'worktree'}:
            raise GitError('conflict choice must be ours, theirs, or worktree')
        if choice != 'worktree':
            self._mutate('checkout', f'--{choice}', '--', path)
        self.stage([path])

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

    def file_changes(self, path):
        changed = next((c for c in self.changes() if c['path'] == path), None)
        if changed is None: return {'path': path, 'changed': False, 'ranges': [], 'diff': ''}
        p = self.root/path
        if changed['untracked']:
            try: lines = max(1, len(p.read_text(errors='replace').splitlines()))
            except OSError: lines = 1
            return {'path': path, 'changed': True,
                    'ranges': [{'from': 1, 'to': lines, 'kind': 'added'}],
                    'diff': '', 'status': changed}
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
                'diff': r.stdout, 'status': changed}
