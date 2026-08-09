"""Filesystem access for the IDE, confined to the open folders.

Everything the IDE reads, writes, renames or deletes goes through `Sandbox`.
The rule is one line -- `_check` -- and it is deliberately the only way in: a
path is resolved (which collapses `..` *and* follows symlinks) and must land
inside one of the open roots, or the operation raises `Unsafe`.

Refs are plain absolute paths. Mapping roots to short ids would be prettier in
a URL, but ids drift as roots are added and removed, and a stale id silently
addressing the wrong file is a worse failure than a long query parameter.
"""

from __future__ import annotations
import os
from dataclasses import dataclass
from fastcore.all import Path, L, globtastic, atomic_save, mkdir as fc_mkdir
from fastcore.shutil import move as fc_move

from . import Dictable

__all__ = ['Unsafe', 'Entry', 'SKIP_DIRS', 'LANGS', 'lang_for', 'is_texty', 'Sandbox']

# Directories never worth walking in a project tree; shown only if explicitly opened as a root.
SKIP_DIRS = {'.git', '.hg', '.svn', '__pycache__', '.venv', 'venv', 'node_modules', '.mypy_cache',
             '.pytest_cache', '.ruff_cache', '.ipynb_checkpoints', '.tox', 'dist', 'build', '.idea'}
_SKIP_RE = '^(' + '|'.join(d.replace('.', r'\.') for d in sorted(SKIP_DIRS)) + ')$'

# suffix -> CodeMirror 6 language id.
LANGS = {'.py': 'python', '.pyi': 'python', '.ipynb': 'python', '.js': 'javascript',
         '.mjs': 'javascript', '.cjs': 'javascript', '.jsx': 'jsx',
         '.ts': 'typescript', '.mts': 'typescript', '.cts': 'typescript', '.tsx': 'tsx',
         '.json': 'json', '.jsonc': 'json', '.json5': 'json',
         '.md': 'markdown', '.markdown': 'markdown', '.html': 'html', '.htm': 'html',
         '.css': 'css', '.scss': 'css', '.yaml': 'yaml', '.yml': 'yaml',
         '.toml': 'toml', '.sh': 'bash', '.bash': 'bash', '.zsh': 'bash', '.fish': 'bash',
         '.sql': 'sql', '.rs': 'rust', '.go': 'go', '.c': 'cpp', '.h': 'cpp',
         '.cc': 'cpp', '.cpp': 'cpp', '.cxx': 'cpp', '.hpp': 'cpp', '.java': 'java',
         '.xml': 'xml', '.svg': 'xml', '.properties': 'properties', '.gradle': 'java',
         '.txt': None, '.cfg': 'toml', '.ini': 'properties'}

NAME_LANGS = {'Dockerfile': 'bash', 'Makefile': 'bash', 'Procfile': 'bash',
              'Cargo.lock': 'toml', 'Pipfile': 'toml'}

_BINARY = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.pdf', '.zip', '.gz', '.tar',
           '.whl', '.so', '.dylib', '.dll', '.pyc', '.parquet', '.db', '.sqlite', '.woff',
           '.woff2', '.ttf', '.mp4', '.mp3', '.npy', '.npz', '.pkl'}

MAX_EDIT_BYTES = 4_000_000   # above this the editor opens read-only rather than choking


class Unsafe(Exception):
    'A path that resolves outside every open root, or an operation refused for safety.'


def lang_for(p):
    "Language id for a path, including conventional extensionless project files."
    p = Path(p)
    return NAME_LANGS.get(p.name, LANGS.get(p.suffix.lower()))


def is_texty(p):
    "Can this be opened in a text editor at all?"
    return Path(p).suffix.lower() not in _BINARY


@dataclass
class Entry(Dictable):
    'One row in the file tree.'
    name: str
    path: str
    is_dir: bool
    size: int = 0
    mtime: float = 0.0
    lang: str | None = None
    is_root: bool = False


class Sandbox:
    "The open folders, and every filesystem operation the IDE is allowed to perform inside them."

    def __init__(self, roots=()):
        self.roots = L()
        for r in roots: self.add_root(r)

    # -- roots ----------------------------------------------------------------
    def covers(self, p):
        "Is `p` inside an open root (or one of them)? `is_relative_to` is true for the root itself."
        return any(p.is_relative_to(r) for r in self.roots)

    def add_root(self, p):
        "Open a folder. Returns its resolved path; adding a folder already covered is a no-op."
        p = Path(p).expanduser().resolve()
        if not p.is_dir(): raise Unsafe(f'not a directory: {p}')
        if self.covers(p): return p                                      # already reachable
        self.roots = L([r for r in self.roots if p not in r.parents]) + [p]  # a new parent subsumes its children
        return p

    def drop_root(self, p):
        p = Path(p).expanduser().resolve()
        self.roots = self.roots.filter(lambda r: r != p)
        return p

    # -- the gate -------------------------------------------------------------
    def _check(self, ref, must_exist=False):
        """Resolve `ref` and refuse it unless it lands inside an open root.

        `resolve()` does the real work: it collapses `..` and follows symlinks, so neither
        a traversal nor a symlink planted inside a root can address anything outside one.
        """
        if not self.roots: raise Unsafe('no folder is open')
        p = Path(ref).expanduser()
        if not p.is_absolute(): p = self.roots[0]/p
        p = p.resolve()
        if not self.covers(p): raise Unsafe(f'{p} is outside the open folders')
        if must_exist and not p.exists(): raise FileNotFoundError(str(p))
        return p

    def root_of(self, ref):
        "The open root containing `ref` (the deepest one, if roots nest)."
        p = self._check(ref)
        return max((r for r in self.roots if p.is_relative_to(r)), key=lambda r: len(r.parts))

    def entry(self, p, is_root=False):
        p = Path(p)
        try: st = p.stat()
        except OSError: st = None
        d = p.is_dir()
        return Entry(name=p.name or str(p), path=str(p), is_dir=d,
                     size=0 if d or st is None else st.st_size,
                     mtime=0.0 if st is None else st.st_mtime,
                     lang=None if d else lang_for(p), is_root=is_root)

    # -- reading --------------------------------------------------------------
    def ls(self, ref=None, hidden=False, skip=True):
        "One level of a directory, dirs first then files, each alphabetical. `ref=None` lists the roots."
        if ref is None: return L(self.entry(r, is_root=True) for r in self.roots)
        p = self._check(ref, must_exist=True)
        if not p.is_dir(): raise NotADirectoryError(str(p))
        keep = lambda c: ((hidden or not c.name.startswith('.'))
                          and not (skip and c.is_dir() and c.name in SKIP_DIRS))
        return (L(p.ls()).filter(keep)
                         .sorted(key=lambda c: (not c.is_dir(), c.name.lower()))
                         .map(self.entry))

    def walk(self, ref=None, hidden=False, limit=20000):
        "Every file under `ref` (or all roots), for quick-open. Capped, because a home directory is not a project."
        out = L()
        for r in (self.roots if ref is None else [self._check(ref, must_exist=True)]):
            out += globtastic(r, skip_folder_re=_SKIP_RE, skip_file_re=None if hidden else r'^\.',
                              folder_re=None if hidden else r'^[^.]', func=Path)
            if len(out) >= limit: break
        return out[:limit]

    def read(self, ref):
        "Text contents of a file. Refuses binaries and anything too big to sanely edit."
        p = self._check(ref, must_exist=True)
        if p.is_dir(): raise IsADirectoryError(str(p))
        if not is_texty(p): raise Unsafe(f'{p.name} is a binary file')
        if p.stat().st_size > MAX_EDIT_BYTES: raise Unsafe(f'{p.name} is too large to edit')
        return p.read_text(encoding='utf-8', errors='replace')

    def read_bytes(self, ref):
        p = self._check(ref, must_exist=True)
        return p.read_bytes()

    # -- writing --------------------------------------------------------------
    def write(self, ref, text):
        "Write text atomically, so a crash mid-save leaves the previous file intact rather than a truncated one."
        p = self._check(ref)
        with atomic_save(p, mode='w', encoding='utf-8') as f: f.write(text)
        return self.entry(p)

    def touch(self, ref):
        "Create an empty file; refuses to clobber an existing one."
        p = self._check(ref)
        if p.exists(): raise FileExistsError(str(p))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()
        return self.entry(p)

    def mkdir(self, ref):
        p = self._check(ref)
        if p.exists(): raise FileExistsError(str(p))
        return self.entry(fc_mkdir(p, parents=True))

    def rename(self, ref, name):
        "Rename in place. `name` is a bare filename -- a path here would be a way to write outside the folder."
        p = self._check(ref, must_exist=True)
        if '/' in name or os.sep in name or name in ('', '.', '..'):
            raise Unsafe(f'{name!r} is not a bare filename')
        dst = self._check(p.parent/name)
        if dst.exists(): raise FileExistsError(str(dst))
        p.rename(dst)
        return self.entry(dst)

    def move(self, ref, dest_dir):
        "Move into another directory; both ends are checked."
        p = self._check(ref, must_exist=True)
        d = self._check(dest_dir, must_exist=True)
        if not d.is_dir(): raise NotADirectoryError(str(d))
        if p == d or p in d.parents: raise Unsafe('cannot move a directory into itself')
        dst = d/p.name
        if dst.exists(): raise FileExistsError(str(dst))
        fc_move(p, dst)
        return self.entry(dst)

    def delete(self, ref):
        "Delete a file, or a directory and its contents. Refuses to delete an open root outright."
        p = self._check(ref, must_exist=True)
        if p in self.roots: raise Unsafe('close the folder instead of deleting an open root')
        p.delete()          # fastcore's Path.delete unlinks a file and rmtree's a directory
        return str(p)
