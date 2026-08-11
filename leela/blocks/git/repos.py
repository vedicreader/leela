"""Every repository the workspace can see, and one operation across all of them.

Leela already opens several folders at once (`leela src tests`), and a folder is as often a
directory *of* checkouts as it is a checkout. Git is asked about one repository at a time,
though: `GitRepo` is rooted at a single worktree and every route in the git block resolves
exactly one of them from the active tab. That is the right shape for staging a hunk and the
wrong one for the question a workspace actually raises — *which of these is dirty, which is
behind, which is still on last week's branch* — which is what
[fastws](https://github.com/AnswerDotAI/fastws) answers for a directory of clones from the
command line.

`RepoSet` is that answer, inside the workspace. Membership is discovered rather than
configured: an open folder is a repository, or it holds them, or both. Only what cannot be
discovered is stored — a checkout elsewhere you want listed here, a vendored clone you want
out — per workspace in Leela's config directory. A `repos.txt` beside an open folder is
read when it exists, so a workspace laid out for fastws keeps working untouched.

Two rules make the fan-out trustworthy. Nothing here aborts a batch: twenty repositories
give twenty independent answers, and one unreachable remote must not hide the nineteen that
fetched. And nothing mutating happens implicitly — a bulk `pull` skips a repository with no
upstream instead of guessing one, and a bulk `push` skips an unpublished branch rather than
creating remote branches nobody asked for.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from ... import leela_cfg
from ..git.git import GitError, GitRepo, repo_root
from ..git.git import clone as git_clone

__all__ = ['RepoSet', 'discover', 'repo_for', 'MEMBERS', 'OPS']

MEMBERS = 'repos.txt'          # the fastws membership file, read when a folder has one
OPS = ('fetch', 'pull', 'push', 'status')
WORKERS = 8                    # git is a subprocess per repository; this is the fan-out width


def _members_file(root):
    "The `repos.txt` beside an open folder: one repository per line, `#` starts a comment."
    try:
        text = (Path(root)/MEMBERS).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return []
    lines = (line.split('#', 1)[0].strip() for line in text.splitlines())
    return [line for line in lines if line]


def _member_root(entry, folder):
    """The local worktree a `repos.txt` line names, or None if it is not checked out here.

    fastws lists what to *clone*, so a line is a URL, an `owner/name` pair, or a path. The
    only question here is which checkout it refers to now, which is the folder of that name.
    """
    entry = str(entry).strip()
    if not entry:
        return None
    if entry.startswith(('http://', 'https://', 'git@', 'ssh://', 'git://')):
        candidate = Path(folder)/re.sub(r'\.git$', '', entry.rstrip('/').rpartition('/')[2])
    else:
        candidate = Path(entry).expanduser()
        if not candidate.is_absolute():
            candidate = Path(folder)/candidate
        if not candidate.is_dir() and '/' in entry:
            candidate = Path(folder)/entry.rstrip('/').rpartition('/')[2]
    return repo_root(candidate) if candidate.is_dir() else None


def clone_url(spec):
    "`owner/name` is the shorthand every workspace list uses; anything else is already a URL."
    spec = str(spec or '').strip()
    return f'https://github.com/{spec}.git' if re.fullmatch(r'[\w.-]+/[\w.-]+', spec) else spec


def discover(roots, extra=(), hidden=()):
    """Repository roots for a workspace of folders, in a stable, explainable order.

    An open folder counts three ways, because all three occur in practice: the folder is a
    checkout, the folder *contains* checkouts (the fastws layout), and a `repos.txt` beside
    it names more. Children are searched one level deep on purpose — a recursive walk of a
    workspace of monorepos is a filesystem crawl nobody asked for, and the ones it would
    find are submodules, which the single-repository panel already reports.
    """
    out, seen = [], set()

    def take(path):
        if path is None:
            return
        key = str(path)
        if key not in seen:
            seen.add(key)
            out.append(Path(path))

    for folder in roots:
        folder = Path(folder).expanduser().resolve()
        take(repo_root(folder))
        try:
            children = sorted((c for c in folder.iterdir() if c.is_dir() and not c.name.startswith('.')),
                              key=lambda c: c.name.lower())
        except OSError:
            children = []
        for child in children:
            # A directory holding `.git` -- a repository, or a linked worktree whose `.git`
            # is a file -- *is* its own worktree root, so this needs no `git rev-parse`.
            # Discovery runs on every repository-targeted request, and one subprocess per
            # candidate folder is a cost the common case should not pay.
            if (child/'.git').exists():
                take(child)
        for entry in _members_file(folder):
            take(_member_root(entry, folder))
    for path in extra:
        take(repo_root(Path(path).expanduser()))
    away = {str(Path(h)) for h in hidden}
    return [p for p in out if str(p) not in away]


def repo_for(session, target=''):
    """The project a panel is about: one this workspace lists, or the active tab's.

    Shared by every panel that is *about a project* rather than about Git -- workflows,
    releases, the environment file. They ask the same question the source-control panel
    does and must answer it the same way, including refusing a path the workspace does not
    list. Unlike `GitRepo.at`, a folder that is not a checkout is a legitimate answer: a
    project can have a release pipeline before it has a remote.
    """
    if str(target or '').strip():
        return RepoSet(session.fs.roots).require(target)
    cwd = session.cwd_for()
    if cwd is None:
        raise GitError('open a folder first')
    return repo_root(cwd) or Path(cwd)


@dataclass
class RepoSet:
    """The workspace's repositories, and the operations that mean something across all of them.

    Constructed per request from the open folders, exactly like `GitRepo.at`, so there is no
    cached membership to go stale when a folder is opened, closed, or cloned into. The only
    state is the small additions/removals file, which is read and written per call.
    """

    roots: list
    store: Path = None

    def __post_init__(self):
        self.roots = [Path(r).expanduser().resolve() for r in self.roots]
        key = hashlib.sha256('\0'.join(map(str, self.roots)).encode()).hexdigest()[:16]
        self.store = Path(self.store) if self.store else leela_cfg/'repos'/f'{key}.json'

    # -- membership ------------------------------------------------------------
    def _state(self):
        try:
            return json.loads(self.store.read_text(encoding='utf-8')) or {}
        except (OSError, ValueError):
            return {}

    def _save(self, state):
        self.store.parent.mkdir(parents=True, exist_ok=True)
        self.store.write_text(json.dumps(state, indent=1), encoding='utf-8')

    def paths(self):
        state = self._state()
        return discover(self.roots, state.get('extra') or (), state.get('hidden') or ())

    def require(self, path):
        """The repository the browser named, refused unless this workspace already lists it.

        This is the security boundary for every repository-targeted route. A repository root
        is an absolute path arriving from the client, and Git will happily operate on any
        one it is handed, so the answer cannot be "resolve it and see" — it has to already
        be in the discovered set.
        """
        want = str(Path(str(path)).expanduser().resolve())
        found = next((p for p in self.paths() if str(p) == want), None)
        if found is None:
            raise GitError(f'{path} is not a repository in this workspace')
        return found

    def add(self, path):
        "List a repository this workspace would not have found, and un-hide one it removed."
        root = repo_root(Path(str(path)).expanduser())
        if root is None:
            raise GitError(f'{path} is not inside a Git repository')
        state = self._state()
        state['hidden'] = [h for h in (state.get('hidden') or []) if h != str(root)]
        extra = state.get('extra') or []
        if str(root) not in extra and root not in discover(self.roots):
            extra = extra + [str(root)]
        state['extra'] = extra
        self._save(state)
        return root

    def remove(self, path):
        "Drop a repository from the list. A discovered one is hidden; nothing is deleted."
        root = self.require(path)
        state = self._state()
        state['extra'] = [e for e in (state.get('extra') or []) if e != str(root)]
        if root in discover(self.roots, state['extra']):
            state['hidden'] = sorted({*(state.get('hidden') or []), str(root)})
        self._save(state)
        return root

    # -- reading ---------------------------------------------------------------
    @staticmethod
    def _fan(items, work):
        "Run `work` over every item at once. Git is a subprocess, so this is IO, not compute."
        items = list(items)
        if not items:
            return []
        with ThreadPoolExecutor(max_workers=min(WORKERS, len(items))) as pool:
            return list(pool.map(work, items))

    def overview(self, expect=''):
        """Every repository as one row, plus what the workspace looks like as a whole.

        `expected` is something fastws is told (`ws-branches main`); here the useful default
        is the branch most of the workspace is already on, so the odd one out shows up
        without anyone having to say first what normal is.
        """
        def brief(path):
            try:
                return GitRepo(path).brief()
            except (GitError, OSError) as e:
                return {'root': str(path), 'name': Path(path).name, 'error': str(e),
                        'branch': '', 'clean': True, 'changed': 0, 'ahead': 0, 'behind': 0,
                        'unreleased': None}
        rows = self._fan(self.paths(), brief)
        named = [r['branch'] for r in rows if r.get('branch') and not r.get('error')]
        expected = str(expect or '').strip() or (Counter(named).most_common(1)[0][0] if named else '')
        for row in rows:
            row['off_branch'] = bool(expected) and not row.get('error') and row['branch'] != expected
        return {
            'repos': rows, 'expected_branch': expected, 'roots': [str(r) for r in self.roots],
            'summary': {
                'repos': len(rows),
                'dirty': sum(1 for r in rows if not r.get('clean')),
                'ahead': sum(1 for r in rows if r.get('ahead')),
                'behind': sum(1 for r in rows if r.get('behind')),
                'off_branch': sum(1 for r in rows if r.get('off_branch')),
                'unreleased': sum(1 for r in rows if r.get('unreleased')),
                'errors': sum(1 for r in rows if r.get('error')),
            },
        }

    # -- acting ----------------------------------------------------------------
    def run(self, op, paths=()):
        """One operation across the named repositories, or across all of them.

        Every repository reports its own outcome, including the ones that refused: a remote
        that is down is that repository's answer, not the workspace's. `skipped` is a
        deliberate third result, because "nothing to do" and "it failed" look identical in a
        list of twenty and mean opposite things.
        """
        if op not in OPS:
            raise GitError(f'unknown workspace operation: {op}')
        targets = [self.require(p) for p in paths] if paths else self.paths()

        def act(path):
            row = {'root': str(path), 'name': Path(path).name, 'ok': True, 'skipped': '', 'output': ''}
            try:
                repo = GitRepo(path)
                if op == 'status':
                    return row
                if op == 'fetch':
                    return row | {'output': repo.fetch() or 'up to date'}
                # `pull` and `push` both need to know where this repository stands *after*
                # the network call, which is why the fetch happens here rather than in a
                # separate pass the caller has to remember to make.
                if op == 'pull':
                    repo.fetch()
                    state = repo.brief(fresh=True)
                    if not state['upstream']:
                        return row | {'skipped': 'no upstream'}
                    if not state['behind']:
                        return row | {'skipped': 'already current'}
                    return row | {'output': repo.pull()}
                state = repo.brief(fresh=True)
                if not state['upstream']:
                    return row | {'skipped': 'unpublished branch'}
                if not state['ahead']:
                    return row | {'skipped': 'nothing to push'}
                return row | {'output': repo.push() or 'pushed'}
            except (GitError, OSError) as e:
                return row | {'ok': False, 'error': str(e)}
        return self._fan(targets, act)

    def clone(self, urls, into=None):
        """Clone repositories into an open folder, in parallel, and list them.

        The destination is confined to the open folders for the same reason every other
        write in Leela is: the browser names it. `owner/name` is expanded to GitHub the way
        a `repos.txt` line is, so the same list works in both places.
        """
        parent = Path(str(into)).expanduser().resolve() if into else (self.roots[0] if self.roots else None)
        if parent is None:
            raise GitError('open a folder to clone into')
        if not any(parent == r or parent.is_relative_to(r) for r in self.roots):
            raise GitError(f'{parent} is outside the open folders')
        specs = [s for s in (str(u).strip() for u in (urls or ())) if s]
        if not specs:
            raise GitError('give at least one repository to clone')

        def act(spec):
            row = {'spec': spec, 'ok': True, 'skipped': '', 'output': ''}
            try:
                return row | {'root': str(git_clone(clone_url(spec), parent)), 'output': 'cloned'}
            except (GitError, OSError) as e:
                return row | {'ok': False, 'error': str(e)}
        return self._fan(specs, act)
