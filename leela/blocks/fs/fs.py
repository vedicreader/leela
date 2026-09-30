"Filesystem access for the IDE, confined to the open folders."

from __future__ import annotations
import os, shutil, re
from dataclasses import dataclass
from fastcore.all import Path, L, globtastic, atomic_save, mkdir as fc_mkdir
from fastcore.shutil import move as fc_move
from fastcore.xtras import flexicache, time_policy

from ... import Dictable

__all__ = ['Unsafe', 'Entry', 'SKIP_DIRS', 'LANGS', 'lang_for', 'is_texty', 'Sandbox']

SKIP_DIRS = {'.git', '.hg', '.svn', '__pycache__', '.venv', 'venv', 'node_modules', '.mypy_cache',
    '.pytest_cache', '.ruff_cache', '.ipynb_checkpoints', '.tox', 'dist', 'build', '.idea',
    'site-packages', 'site-python', '.eggs', '.gradle', '.next', '.turbo'}
_SKIP_RE = (r'^(' + '|'.join(re.escape(d) for d in sorted(SKIP_DIRS))
            + r'|[^/]*[-_.]venv|venv[-_.][^/]*)$')

LANGS = {'.py': 'python', '.pyi': 'python', '.ipynb': 'python', '.js': 'javascript', '.mjs': 'javascript',
    '.cjs': 'javascript', '.jsx': 'jsx', '.ts': 'typescript', '.mts': 'typescript', '.cts': 'typescript', '.tsx': 'tsx',
    '.json': 'json', '.jsonc': 'json', '.json5': 'json', '.md': 'markdown', '.markdown': 'markdown', '.html': 'html',
    '.htm': 'html', '.css': 'css', '.scss': 'css', '.yaml': 'yaml', '.yml': 'yaml', '.toml': 'toml', '.sh': 'bash',
    '.bash': 'bash', '.zsh': 'bash', '.fish': 'bash', '.sql': 'sql', '.rs': 'rust', '.go': 'go', '.c': 'cpp',
    '.h': 'cpp', '.cc': 'cpp', '.cpp': 'cpp', '.cxx': 'cpp', '.hpp': 'cpp', '.java': 'java', '.xml': 'xml',
    '.svg': 'xml', '.properties': 'properties', '.gradle': 'java', '.txt': None, '.cfg': 'toml', '.ini': 'properties'}

NAME_LANGS = {'Dockerfile': 'bash', 'Makefile': 'bash', 'Procfile': 'bash', 'Cargo.lock': 'toml', 'Pipfile': 'toml'}

_BINARY = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.pdf', '.zip', '.gz', '.tar', '.whl', '.so', '.dylib',
    '.dll', '.pyc', '.parquet', '.db', '.sqlite', '.woff', '.woff2', '.ttf', '.mp4', '.mp3', '.npy', '.npz', '.pkl'}

MAX_EDIT_BYTES = 4_000_000

class Unsafe(Exception):
    "A path that resolves outside every open root, or an operation refused for safety."

_GEN = 0
def _changed():
    "Our own writes skip `_walked`'s window."
    global _GEN; _GEN += 1

@flexicache(time_policy(2), maxsize=16)
def _walked(roots, hidden, limit, gen):
    out = L()
    for r in roots:
        out += globtastic(r, skip_folder_re=_SKIP_RE, skip_file_re=None if hidden else r'^\.',
            folder_re=None if hidden else r'^[^.]', func=Path)
        if len(out) >= limit: break
    return out[:limit]

def lang_for(p):
    "Language id for a path, including conventional extensionless project files."
    p = Path(p)
    return NAME_LANGS.get(p.name, LANGS.get(p.suffix.lower()))

def is_texty(p):
    "Whether this can be opened in a text editor at all."
    return Path(p).suffix.lower() not in _BINARY

@dataclass
class Entry(Dictable):
    "One row in the file tree."
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
    def covers(self, p):
        "Whether `p` is inside an open root, or is one of them."
        return any(p.is_relative_to(r) for r in self.roots)
    def add_root(self, p):
        "Open a folder. Returns its resolved path; adding a folder already covered is a no-op."
        p = Path(p).expanduser().resolve()
        if not p.is_dir(): raise Unsafe(f'not a directory: {p}')
        if self.covers(p): return p
        self.roots = L([r for r in self.roots if p not in r.parents]) + [p]
        return p
    def drop_root(self, p):
        p = Path(p).expanduser().resolve()
        self.roots = self.roots.filter(lambda r: r != p)
        return p
    def _check(self, ref, must_exist=False):
        "Resolve `ref` and refuse it unless it resolves inside an open root."
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
        return Entry(name=p.name or str(p), path=str(p), is_dir=d, is_root=is_root, lang=None if d else lang_for(p),
            size=0 if d or st is None else st.st_size, mtime=0.0 if st is None else st.st_mtime)
    def ls(self, ref=None, hidden=False, skip=True):
        "One level of a directory, dirs first then files, each alphabetical. `ref=None` lists the roots."
        if ref is None: return L(self.entry(r, is_root=True) for r in self.roots)
        p = self._check(ref, must_exist=True)
        if not p.is_dir(): raise NotADirectoryError(str(p))
        keep = lambda c: (hidden or not c.name.startswith('.')) and (not (skip and c.is_dir() and (c.name in SKIP_DIRS)))
        return L(p.ls()).filter(keep).sorted(key=lambda c: (not c.is_dir(), c.name.lower())).map(self.entry)
    def walk(self, ref=None, hidden=False, limit=20000):
        "Every file under `ref` (or all roots), for quick-open, capped at `limit`."
        roots = self.roots if ref is None else L([self._check(ref, must_exist=True)])
        return _walked(tuple(str(r) for r in roots), hidden, limit, _GEN)
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
    def write(self, ref, text):
        "Write text atomically, so a crash mid-save leaves the previous file intact."
        p = self._check(ref)
        with atomic_save(p, mode='w', encoding='utf-8') as f: f.write(text)
        _changed()
        return self.entry(p)
    def touch(self, ref):
        "Create an empty file; refuses to clobber an existing one."
        p = self._check(ref)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch(exist_ok=False)
        _changed()
        return self.entry(p)
    def mkdir(self, ref):
        p = self._check(ref)
        if p.exists(): raise FileExistsError(str(p))
        _changed()
        return self.entry(fc_mkdir(p, parents=True))
    def _bare(self, name):
        "A name typed by a person, refused unless it is one path component."
        if '/' in name or os.sep in name or name in ('', '.', '..'): raise Unsafe(f'{name!r} is not a bare filename')
        return name
    def under(self, ref, name):
        "Where an entry called `name` goes inside `ref`. `name` is one component; an empty `ref` is the first root."
        return self._check(self._check(ref)/self._bare(name))
    def rename(self, ref, name):
        "Rename in place. `name` is a bare filename, as `under` requires."
        p = self._check(ref, must_exist=True)
        dst = self.under(p.parent, name)
        if dst.exists(): raise FileExistsError(str(dst))
        p.rename(dst)
        _changed()
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
        _changed()
        return self.entry(dst)
    def copy(self, ref, dest_dir, name=None):
        "Copy into `dest_dir` under `name`, checking both ends. Never overwrites: the caller picks a free name."
        p = self._check(ref, must_exist=True)
        d = self._check(dest_dir, must_exist=True)
        if not d.is_dir(): raise NotADirectoryError(str(d))
        if p.is_dir() and (p == d or p in d.parents): raise Unsafe('cannot copy a directory into itself')
        dst = self._check(d/(name or p.name))
        if dst.exists(): raise FileExistsError(str(dst))
        shutil.copytree(p, dst) if p.is_dir() else shutil.copy2(p, dst)
        _changed()
        return self.entry(dst)
    def free_name(self, ref, dest_dir=None):
        "A name in `dest_dir` that nothing holds yet: `mod.py`, then `mod copy.py`, then `mod copy 2.py`."
        p = self._check(ref, must_exist=True)
        d = self._check(dest_dir, must_exist=True) if dest_dir else p.parent
        stem, suffix = (p.stem, p.suffix) if p.is_file() else (p.name, '')
        for n in range(0, 100):
            name = f'{stem}{"" if n == 0 else " copy" if n == 1 else f" copy {n}"}{suffix}'
            if not (d/name).exists(): return name
        raise FileExistsError(f'no free name for {p.name} in {d}')
    def delete(self, ref):
        "Delete a file, or a directory and its contents. Refuses to delete an open root."
        p = self._check(ref, must_exist=True)
        if p in self.roots: raise Unsafe('close the folder instead of deleting an open root')
        p.delete()
        _changed()
        return str(p)
    def take(self, ref, trash):
        "Move `ref` into `trash` whole, and return the key that brings it back."
        p = self._check(ref, must_exist=True)
        if p in self.roots: raise Unsafe('close the folder instead of deleting an open root')
        key = trash.keep(p)
        _changed()
        return key
