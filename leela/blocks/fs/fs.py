"Filesystem access for the IDE, confined to the open folders."

from __future__ import annotations
import asyncio, codecs, os, shutil, re, subprocess, unicodedata
from dataclasses import dataclass
from fnmatch import fnmatch
from itertools import islice, zip_longest
from fastcore.all import Path, L, atomic_save, first, mkdir as fc_mkdir
from kunda.pythons import clean_env, project_python, python_for
from rgapi import fda, fd_iter
from shalya.host import DENY
from shalya.core import Unsafe as HostUnsafe
from fastcore.shutil import move as fc_move
from fastcore.xtras import flexicache, time_policy

from ... import Dictable
from .office import OFFICE, OFFICE_MAX_BYTES, is_office

__all__ = ['Unsafe', 'NotText', 'Entry', 'SKIP_DIRS', 'WALK_LIMIT', 'FIND_LIMIT', 'LANGS', 'MEDIA_TYPES', 'lang_for', 'is_texty', 'is_media', 'loose_refusal', 'Sandbox']

SKIP_DIRS = {'.git', '.hg', '.svn', '__pycache__', '.venv', 'venv', 'node_modules', '.mypy_cache',
    '.pytest_cache', '.ruff_cache', '.ipynb_checkpoints', '.tox', 'dist', 'build', '.idea',
    'site-packages', 'site-python', '.eggs', '.gradle', '.next', '.turbo'}
# ripgrep matches this against the path from the walk's root, not the folder's name.
_SKIP_RE = (r'(^|.*/)(' + '|'.join(re.escape(d) for d in sorted(SKIP_DIRS))
            + r'|[^/]*[-_.]venv|venv[-_.][^/]*)$')

LANGS = {'.py': 'python', '.pyi': 'python', '.ipynb': 'python', '.js': 'javascript', '.mjs': 'javascript',
    '.cjs': 'javascript', '.jsx': 'jsx', '.ts': 'typescript', '.mts': 'typescript', '.cts': 'typescript', '.tsx': 'tsx',
    '.json': 'json', '.jsonc': 'json', '.json5': 'json', '.md': 'markdown', '.markdown': 'markdown', '.html': 'html',
    '.htm': 'html', '.css': 'css', '.scss': 'css', '.yaml': 'yaml', '.yml': 'yaml', '.toml': 'toml', '.sh': 'bash',
    '.bash': 'bash', '.zsh': 'bash', '.fish': 'bash', '.sql': 'sql', '.rs': 'rust', '.go': 'go', '.c': 'cpp',
    '.h': 'cpp', '.cc': 'cpp', '.cpp': 'cpp', '.cxx': 'cpp', '.hpp': 'cpp', '.java': 'java', '.xml': 'xml',
    '.svg': 'xml', '.properties': 'properties', '.gradle': 'java', '.txt': None, '.cfg': 'toml', '.ini': 'properties'}

NAME_LANGS = {'Dockerfile': 'bash', 'Makefile': 'bash', 'Procfile': 'bash', 'Cargo.lock': 'toml', 'Pipfile': 'toml'}

#: audio and video that WebKit, the Mac apps' web view, and Chrome both play, with the MIME type `/file/raw` serves them as
MEDIA_TYPES = {'.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.m4a': 'audio/mp4', '.aac': 'audio/aac', '.flac': 'audio/flac',
    '.ogg': 'audio/ogg', '.oga': 'audio/ogg', '.opus': 'audio/ogg', '.mp4': 'video/mp4', '.m4v': 'video/mp4',
    '.mov': 'video/quicktime', '.webm': 'video/webm'}

_BINARY = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.pdf', '.zip', '.gz', '.tar', '.whl', '.so', '.dylib',
    '.dll', '.pyc', '.parquet', '.db', '.sqlite', '.woff', '.woff2', '.ttf', '.npy', '.npz', '.pkl', *MEDIA_TYPES,
    '.ogv', '.avi', '.mkv', '.wmv', '.flv', '.wma', '.mpg', '.mpeg', '.3gp', '.3g2', '.aif', '.aiff', '.caf', '.mid', '.m4b', '.m4p',
    *OFFICE, '.doc', '.xls', '.ppt', '.docm', '.pptm', '.odt', '.ods', '.odp'}

MAX_EDIT_BYTES = 4_000_000

class Unsafe(HostUnsafe):
    "A path that resolves outside every open root, or an operation refused for safety; a shalya refusal, so the agent's guards see it."

class NotText(Unsafe):
    "A file that is not UTF-8 text, or holds NUL bytes: shown read-only, never written."
    kind = 'not_text'
    def __init__(self, p, write=False):
        self.path, self.said = str(p), (f'{Path(p).name} is not UTF-8 text, so Leela does not change it.' if write else
                                          'This file is not UTF-8 text, so Leela opens it read-only.')
        super().__init__(self.said)

def decoded(raw, p=''):
    "`raw` as text, strictly: NUL bytes or bytes that are not UTF-8 raise `NotText`."
    if b'\0' in raw: raise NotText(p)
    try: return raw.decode('utf-8')
    except UnicodeDecodeError: raise NotText(p) from None

def is_plain(p, chunk=1 << 20):
    "Whether the file at `p` is UTF-8 with no NUL byte, read in chunks so a large file is never held whole."
    dec = codecs.getincrementaldecoder('utf-8')()
    try:
        with open(p, 'rb') as f:
            while (b := f.read(chunk)):
                if b'\0' in b: return False
                dec.decode(b)
            dec.decode(b'', final=True)
    except UnicodeDecodeError: return False
    return True

def newline_of(p, head=1 << 16):
    "The line ending most of the file's first 64 KB uses: `\\r\\n`, `\\r` or `\\n`; `\\n` for a new file."
    try:
        with open(p, 'rb') as f: b = f.read(head)
    except OSError: return '\n'
    crlf = b.count(b'\r\n'); cr, lf = b.count(b'\r') - crlf, b.count(b'\n') - crlf
    return max((lf, '\n'), (crlf, '\r\n'), (cr, '\r'))[1] if crlf or cr else '\n'

def universal(text):
    "`text` with every line ending as `\\n`, as Python reads text files."
    return text.replace('\r\n', '\n').replace('\r', '\n')

_GEN = 0
def _changed():
    "Our own writes skip `_walked`'s window."
    global _GEN; _GEN += 1

#: Files a walk returns by default: callers that read every file it names stay at this.
WALK_LIMIT = 20_000
#: Files go-to-file walks. Names only, so it goes further: 100k files walked in 0.9 s and ranked in 0.15 s.
FIND_LIMIT = 100_000

@flexicache(time_policy(2), maxsize=16)
def _walked(roots, hidden, limit, gen):
    "Up to `limit` files, and whether there were more."
    # Roots take turns, so a large first root cannot spend the whole cap.
    turns = zip_longest(*(fd_iter(root=r, hidden=hidden, skip_dir_re=_SKIP_RE) for r in roots))
    got = L(islice((p for t in turns for p in t if p is not None), limit + 1))
    return got[:limit].sorted(), len(got) > limit

def lang_for(p):
    "Language id for a path, including conventional extensionless project files."
    p = Path(p)
    return NAME_LANGS.get(p.name, LANGS.get(p.suffix.lower()))

def is_texty(p):
    "Whether this can be opened in a text editor at all."
    return Path(p).suffix.lower() not in _BINARY

def is_media(p): return Path(p).suffix.lower() in MEDIA_TYPES

def loose_refusal(p):
    "Why a file outside every open folder may not be admitted as a loose tab, or None. Media streams, so has no size cap."
    p = Path(p)
    if not p.is_file(): return f'not a file: {p}'
    if not is_media(p) and p.stat().st_size > (OFFICE_MAX_BYTES if is_office(p) else MAX_EDIT_BYTES): return f'{p.name} is too large to {"show" if is_office(p) else "edit"}'
    if any(fnmatch(str(p).lower(), pat.lower()) for pat in DENY): return f'{p.name} has the name of a credentials file'
    return None

def _nfc(p): return unicodedata.normalize('NFC', str(p))

def _same(a, b):
    "Whether two paths name one file, case-blind where the disk is."
    if a == b: return True
    try: return os.path.samefile(a, b)
    except OSError: return False

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
        self.roots, self.admitted, self.loose = L(), L(), None
        self._stdlib_cache = {}
        for r in roots: self.add_root(r)
    def python(self, path=''):
        "The interpreter `path` runs under, never searched past its own root; with no path, the first root's."
        if not path: return project_python(self.roots)
        p = Path(path).expanduser().resolve()
        return python_for(p.parent, stop=max((r for r in self.roots if p.is_relative_to(r)), key=lambda r: len(r.parts), default=None))
    def pythons(self):
        "Each open root's interpreter."
        return L(project_python([r]) for r in self.roots).filter().unique()
    @staticmethod
    def site_roots(py):
        "The `site-packages` folders of the virtualenv `py` lives in."
        lib = Path(py).parent.parent/'lib' if py else None
        if not (lib and lib.is_dir()): return L()
        return L(p/'site-packages' for p in lib.iterdir() if (p/'site-packages').is_dir())
    def _stdlib(self, py):
        "`py`'s resolved standard library, cached per interpreter."
        if (key := (py, tuple(self.roots))) in self._stdlib_cache: return self._stdlib_cache[key]
        found = L()
        try:
            r = subprocess.run([py, '-c', 'import sysconfig;print(sysconfig.get_paths()["stdlib"])'],
                               env=clean_env(), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and r.stdout.strip():
                p = Path(r.stdout.strip()).resolve()
                if (p/'os.py').is_file() and not Path.home().is_relative_to(p) and not any(root.is_relative_to(p) for root in self.roots):
                    found = L(p)
        except (OSError, subprocess.TimeoutExpired): pass
        self._stdlib_cache[key] = found
        return found
    def stdlib_root(self, path=''):
        "The standard library of `path`'s interpreter, or of every open root's."
        return L(r for py in ([self.python(path)] if path else self.pythons()) if py for r in self._stdlib(py)).unique()
    def read_only(self, ref):
        "Whether a resolved path is an open root interpreter's installed package, or stdlib outside the open folders."
        p = Path(ref).expanduser().resolve()
        if any(p.is_relative_to(r.resolve()) for py in self.pythons() for r in self.site_roots(py)): return True
        return not self.covers(p) and any(p.is_relative_to(r) for r in self.stdlib_root())
    def _admits(self, p):
        "Whether `p` is an admitted loose file. A path that resolved elsewhere since it was admitted is not."
        return any(a == p or (_same(a, p) and a.resolve() == a) for a in self.admitted)
    def covers(self, p):
        "Whether `p` is inside an open root, or is one of them, or is an admitted loose file."
        return any(p.is_relative_to(r) for r in self.roots) or self._admits(p)
    def admit(self, p):
        "Allow one file outside every root, for as long as its tab stays open. Needs the loose root among the roots."
        if self.loose is None: raise Unsafe('no loose-file workspace is open')
        p = Path(p).expanduser().resolve()
        if self.read_only(p): raise Unsafe(f'{p.name} is read-only')
        if self.covers(p): return p
        if why := loose_refusal(p): raise Unsafe(why)
        self.admitted = self.admitted + [p]
        return p
    def revoke(self, p):
        "Withdraw the access `admit` gave `p`."
        p = Path(p).expanduser().resolve()
        self.admitted = self.admitted.filter(lambda a: not _same(a, p))
        return p
    def _fixed(self, p, what):
        "Refuse to `what` an admitted file: it was opened alone, and nothing around it is ours."
        if self._admits(p): raise Unsafe(f'{p.name} was opened on its own, so it cannot be {what}')
    def add_root(self, p, loose=False):
        "Open a folder. Returns its resolved path; adding a folder already covered is a no-op. `loose` marks the folder that stands for loose files."
        p = Path(p).expanduser().resolve()
        if not p.is_dir(): raise Unsafe(f'not a directory: {p}')
        if loose: self.loose = p
        if self.covers(p): return p
        self.roots = L([r for r in self.roots if p not in r.parents]) + [p]
        return p
    def drop_root(self, p):
        p = Path(p).expanduser().resolve()
        if p == self.loose: self.loose, self.admitted = None, L()
        self.roots = self.roots.filter(lambda r: r != p)
        return p
    def _spelled(self, p):
        "`p` as spelled on disk, when it differs only in Unicode form: APFS takes either form, Linux only the stored one."
        n = Path(_nfc(p))
        r = first(r for r in self.roots if p.is_relative_to(r))
        rel = p.relative_to(r) if r else first(n.relative_to(m) for r in self.roots if n.is_relative_to(m := Path(_nfc(r))))
        if rel is None: return p if p.exists() else first(a for a in self.admitted if Path(_nfc(a)) == n) or p
        r = r or first(r for r in self.roots if n.is_relative_to(_nfc(r)))
        if (q := r/rel).exists(): return q
        for part in rel.parts:
            if not (r/part).exists():
                try: hits = [e for e in os.listdir(r) if _nfc(e) == _nfc(part)]
                except OSError: return q
                if len(hits) != 1: return q
                part = hits[0]
            r = r/part
        return r.resolve()
    def _check(self, ref, must_exist=False, reading=False):
        "Resolve a path inside the open folders, or stdlib for reads."
        if not self.roots: raise Unsafe('no folder is open')
        p = Path(ref).expanduser()
        if not p.is_absolute(): p = self.roots[0]/p
        p = self._spelled(p.resolve())
        if not self.covers(p):
            if not self.read_only(p): raise Unsafe(f'{p} is outside the open folders')
            if not reading: raise Unsafe(f'{p.name} is read-only (standard library)')
            if any(fnmatch(str(p).lower(), pat.lower()) for pat in DENY): raise Unsafe(f'{p.name} has the name of a credentials file')
        if must_exist and not p.exists(): raise FileNotFoundError(str(p))
        return p
    def root_of(self, ref):
        "The open root containing `ref` (the deepest one, if roots nest)."
        p = self._check(ref)
        inside = [r for r in self.roots if p.is_relative_to(r)]
        return max(inside, key=lambda r: len(r.parts)) if inside else self.loose
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
    def _live(self, ref):
        "`ref`, or every root still on disk, as the strings ripgrep walks."
        roots = self.roots if ref is None else L([self._check(ref, must_exist=True)])
        return tuple(str(r) for r in roots if r.is_dir())
    def walk(self, ref=None, hidden=False, limit=None):
        "Every file under `ref` (or all roots) that git would track, capped at `limit` (`WALK_LIMIT`)."
        return self.walk_capped(ref, hidden, limit)[0]
    def walk_capped(self, ref=None, hidden=False, limit=None):
        "`(files, partial)`: `walk`, and whether the cap cut it short."
        return _walked(self._live(ref), hidden, limit or WALK_LIMIT, _GEN)
    async def hidden_files(self, pattern, ref=None, timeout_ms=10000):
        "Files named like `pattern` that `walk` leaves out, and whether the time limit cut the search short; cancelling stops the walk."
        found = await fda(root=list(self._live(ref)), pattern=pattern, hidden=True, ignore=False, skip_dir='.git', timeout_ms=timeout_ms)
        seen = set((await asyncio.to_thread(self.walk_capped, ref, False, FIND_LIMIT))[0])
        return L(found).filter(lambda p: p not in seen).sorted(), found.stop_reason == 'timeout'
    def read(self, ref):
        "Text contents of a file. Refuses binaries and anything too big to sanely edit."
        p = self._check(ref, must_exist=True, reading=True)
        if p.is_dir(): raise IsADirectoryError(str(p))
        if not is_texty(p): raise Unsafe(f'{p.name} is a binary file')
        if p.stat().st_size > MAX_EDIT_BYTES: raise Unsafe(f'{p.name} is too large to edit')
        return universal(decoded(p.read_bytes(), p))
    def read_bytes(self, ref):
        p = self._check(ref, must_exist=True)
        return p.read_bytes()
    def write(self, ref, text):
        "Write text atomically, so a crash mid-save leaves the previous file intact, in the file's own line ending."
        p = self._check(ref)
        if is_office(p): raise Unsafe(f'{p.name} is read-only here: Leela shows Word, PowerPoint and Excel files, and does not change them')
        if is_media(p): raise Unsafe(f'{p.name} is read-only here: Leela plays audio and video files, and does not change them')
        mode = p.stat().st_mode & 0o7777 if p.exists() else None
        if mode is not None and p.is_file():
            if not is_plain(p): raise NotText(p, write=True)
            if (nl := newline_of(p)) != '\n': text = universal(text).replace('\n', nl)
        with atomic_save(p, mode='w', encoding='utf-8', newline='') as f:
            for i in range(0, len(text), 1 << 20): f.write(text[i:i + (1 << 20)])   # a large notebook is never encoded whole
            if mode is not None: os.chmod(f.name, mode)
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
        self._fixed(p, 'renamed')
        dst = self.under(p.parent, name)
        if dst.exists(): raise FileExistsError(str(dst))
        p.rename(dst)
        _changed()
        return self.entry(dst)
    def move(self, ref, dest_dir):
        "Move into another directory; both ends are checked."
        p = self._check(ref, must_exist=True)
        self._fixed(p, 'moved')
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
        self._fixed(p, 'copied out')
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
        self._fixed(p, 'deleted')
        p.delete()
        _changed()
        return str(p)
    def take(self, ref, trash):
        "Move `ref` into `trash` whole, and return the key that brings it back."
        p = self._check(ref, must_exist=True)
        if p in self.roots: raise Unsafe('close the folder instead of deleting an open root')
        self._fixed(p, 'deleted')
        key = trash.keep(p)
        _changed()
        return key
