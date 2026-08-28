"Every repository the workspace can see, and one operation across all of them."

from __future__ import annotations

import hashlib, json, os, re, shutil, subprocess
from collections import Counter
from dataclasses import dataclass

from fastcore.all import Path, first
from fastcore.parallel import parallel

from ... import leela_cfg
from ramabana.git import GitError, repo_root, url_name
from .git import GitRepo
from ramabana.git import clone as git_clone

__all__ = ['RepoSet', 'discover', 'repo_for', 'MEMBERS', 'OPS']

MEMBERS = 'repos.txt'
OPS = ('fetch', 'pull', 'push', 'status')
WORKERS = 8

def _members_file(root):
    "The `repos.txt` beside an open folder: one repository per line, `#` starts a comment."
    try: text = (Path(root)/MEMBERS).read_text(encoding='utf-8', errors='replace')
    except OSError: return []
    lines = (line.split('#', 1)[0].strip() for line in text.splitlines())
    return [line for line in lines if line]

def _member_root(entry, folder):
    "The local worktree a `repos.txt` line names, or None if it is not checked out here."
    entry = str(entry).strip()
    if not entry: return None
    if entry.startswith(('http://', 'https://', 'git@', 'ssh://', 'git://')):
        candidate = Path(folder)/url_name(entry)
    else:
        candidate = Path(entry).expanduser()
        if not candidate.is_absolute(): candidate = Path(folder)/candidate
        if not candidate.is_dir() and '/' in entry:
            candidate = Path(folder)/entry.rstrip('/').rpartition('/')[2]
    return repo_root(candidate) if candidate.is_dir() else None

def clone_url(spec):
    "`owner/name` is the shorthand every workspace list uses; anything else is already a URL."
    spec = str(spec or '').strip()
    return f'https://github.com/{spec}.git' if re.fullmatch(r'[\w.-]+/[\w.-]+', spec) else spec

def discover(roots, extra=(), hidden=()):
    "Repository roots for a workspace of folders, in a stable, explainable order."
    out, seen = [], set()
    def take(path):
        if path is None or str(path) in seen: return
        seen.add(str(path))
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
            if (child/'.git').exists(): take(child)
        for entry in _members_file(folder): take(_member_root(entry, folder))
    for path in extra: take(repo_root(Path(path).expanduser()))
    away = {str(Path(h)) for h in hidden}
    return [p for p in out if str(p) not in away]

def repo_for(session, target=''):
    """The project a panel is about: one this workspace lists, the chosen folder's, or the open file's.

    The chosen folder is taken only when it is itself a checkout. A folder of checkouts -- a
    directory of clones, opened to work across them -- is not one, and answering with it made every
    Git surface say the folder is not a repository while every file open inside it was in one.
    Falling through to the tab is what makes the panel follow the file from repository to
    repository, which is the same rule the pill and the tree badges already describe.
    """
    if str(target or '').strip(): return RepoSet(session.fs.roots).require(target)
    chosen = session.active_root
    if chosen is not None and chosen in session.fs.roots and (root := repo_root(chosen)) is not None:
        return root
    cwd = session.cwd_for()
    if cwd is None: raise GitError('open a folder first')
    return repo_root(cwd) or Path(cwd)

@dataclass
class RepoSet:
    "The workspace's repositories, and the operations that mean something across all of them."
    roots: list
    store: Path = None
    def __post_init__(self):
        self.roots = [Path(r).expanduser().resolve() for r in self.roots]
        key = hashlib.sha256('\0'.join(map(str, self.roots)).encode()).hexdigest()[:16]
        self.store = Path(self.store) if self.store else leela_cfg/'repos'/f'{key}.json'
    def _state(self):
        try: return json.loads(self.store.read_text(encoding='utf-8')) or {}
        except (OSError, ValueError): return {}
    def _save(self, state):
        self.store.parent.mkdir(parents=True, exist_ok=True)
        self.store.write_text(json.dumps(state, indent=1), encoding='utf-8')
    def paths(self):
        state = self._state()
        return discover(self.roots, state.get('extra') or (), state.get('hidden') or ())
    def require(self, path):
        "The repository the browser named, refused unless this workspace already lists it."
        want = str(Path(str(path)).expanduser().resolve())
        found = first(p for p in self.paths() if str(p) == want)
        if found is None: raise GitError(f'{path} is not a repository in this workspace')
        return found
    def add(self, path):
        "List a repository this workspace would not have found, and un-hide one it removed."
        root = repo_root(Path(str(path)).expanduser())
        if root is None: raise GitError(f'{path} is not inside a Git repository')
        state = self._state()
        state['hidden'] = [h for h in (state.get('hidden') or []) if h != str(root)]
        extra = state.get('extra') or []
        if str(root) not in extra and root not in discover(self.roots): extra += [str(root)]
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
    @staticmethod
    def _fan(items, work):
        "Run `work` over every item at once. Git is a subprocess, so this is IO, not compute."
        items = list(items)
        return list(parallel(work, items, n_workers=min(WORKERS, len(items)), threadpool=True))
    def overview(self, expect=''):
        "Every repository as one row, plus what the workspace looks like as a whole."
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
    def run(self, op, paths=()):
        "One operation across the named repositories, or across all of them."
        if op not in OPS: raise GitError(f'unknown workspace operation: {op}')
        targets = [self.require(p) for p in paths] if paths else self.paths()
        def act(path):
            row = {'root': str(path), 'name': Path(path).name, 'ok': True, 'skipped': '', 'output': ''}
            try:
                repo = GitRepo(path)
                if op == 'status': return row
                if op == 'fetch': return row | {'output': repo.fetch() or 'up to date'}
                if op == 'pull':
                    repo.fetch()
                    state = repo.brief(fresh=True)
                    if not state['upstream']: return row | {'skipped': 'no upstream'}
                    if not state['behind']: return row | {'skipped': 'already current'}
                    return row | {'output': repo.pull()['summary']}
                state = repo.brief(fresh=True)
                if not state['upstream']: return row | {'skipped': 'unpublished branch'}
                if not state['ahead']: return row | {'skipped': 'nothing to push'}
                return row | {'output': repo.push() or 'pushed'}
            except (GitError, OSError) as e:
                return row | {'ok': False, 'error': str(e)}
        return self._fan(targets, act)
    def clone(self, urls, into=None):
        "Clone repositories into an open folder, in parallel, and list them."
        parent = Path(str(into)).expanduser().resolve() if into else (self.roots[0] if self.roots else None)
        if parent is None: raise GitError('open a folder to clone into')
        if not any(parent == r or parent.is_relative_to(r) for r in self.roots):
            raise GitError(f'{parent} is outside the open folders')
        specs = [s for s in (str(u).strip() for u in (urls or ())) if s]
        if not specs: raise GitError('give at least one repository to clone')
        def act(spec):
            row = {'spec': spec, 'ok': True, 'skipped': '', 'output': ''}
            try:
                return row | {'root': str(git_clone(clone_url(spec), parent)), 'output': 'cloned'}
            except (GitError, OSError) as e:
                return row | {'ok': False, 'error': str(e)}
        return self._fan(specs, act)

def find_repos(base, query='', limit=60, depth=6):
    "Repositories anywhere under `base`, for picking one out of a directory of checkouts."
    base = Path(base or '').expanduser()
    if not base.is_dir(): return []
    q, out, seen = str(query or '').strip().lower(), [], set()
    def take(repo):
        key = str(repo)
        if key in seen or (q and q not in repo.name.lower() and q not in key.lower()): return
        seen.add(key)
        out.append(repo)
    exe = shutil.which('rg')
    if exe:
        cmd = [exe, '--files', '--hidden', '--no-ignore', '--no-messages',
            '--max-depth', str(int(depth)), '-g', '**/.git/HEAD', '-g', '**/.git',
            *[g for d in ('.git/objects', '.git/logs', 'node_modules', '.venv', 'venv',
                '.cache', 'Library', '.Trash', 'site-packages', '__pycache__')
                for g in ('-g', f'!**/{d}')],
            str(base)]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            for line in (p.stdout or '').splitlines():
                hit = Path(line)
                repo = hit.parent.parent if hit.name == 'HEAD' else hit.parent
                if repo.is_dir(): take(repo)
        except (OSError, subprocess.SubprocessError):
            exe = None
    if not exe:
        for cur, dirs, _ in os.walk(base):
            here = Path(cur)
            if len(here.relative_to(base).parts) > depth:
                dirs[:] = []
                continue
            if (here/'.git'/'HEAD').is_file() or (here/'.git').is_file():
                take(here)
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in {'node_modules', '__pycache__'}]
    out.sort(key=lambda p: (p.name.lower(), str(p)))
    return out[:max(1, int(limit))]
