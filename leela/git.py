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
    def merge(self, branch): return self._mutate('merge', '--no-edit', branch).strip()
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

    def compare(self, left, right):
        spec = f'{left}...{right}'
        counts = self.run('rev-list', '--left-right', '--count', spec).split()
        patch = self.run('diff', '--no-ext-diff', '--stat', '--patch', spec)
        return {'left': left, 'right': right, 'left_only': int(counts[0]),
                'right_only': int(counts[1]), 'patch': patch}

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
        raw = self.diff(path, staged)
        if not str(path).lower().endswith('.ipynb'):
            return {'text': raw, 'content': raw, 'notebook': False}
        left = self._version(path, 'head' if staged else 'index')
        right = self._version(path, 'index' if staged else 'worktree')
        before, after = self._notebook_content(left), self._notebook_content(right)
        content = ''.join(difflib.unified_diff(
            before.splitlines(True), after.splitlines(True),
            fromfile=f'{path} (before)', tofile=f'{path} (after)', n=3))
        return {'text': raw, 'content': content, 'notebook': True}

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
