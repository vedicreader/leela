"What an open canvas needs beside the file: a namespace, a trail, and somewhere to put steering."

from __future__ import annotations
import asyncio, os
from dataclasses import dataclass, field
from fastcore.all import L, Path
from .doc import Canvas
from .live import Runtime, runtime_for

__all__ = ['Open', 'Store', 'store_for', 'canvas_dir', 'brick_host', 'Stale', 'Untrusted']

class Stale(Exception):
    "A write against a revision the document has moved past."

class Untrusted(Exception):
    "Code in a document nobody has said may run."

def canvas_dir(): return Path(os.getenv('CANVAS_DIR') or (Path(__file__).parent.parent.parent.parent/'examples'/'canvas'))
def brick_host(): return os.getenv('BRICK_HOST') or 'http://127.0.0.1:5001'

@dataclass
class Open:
    "One canvas, open: the document, the namespace it runs in, and the questions asked of it."
    canvas: Canvas
    runtime: object = field(default_factory=Runtime)
    trail: list = field(default_factory=list)
    steer: dict = field(default_factory=dict)
    #: Bumped by every edit. A save carrying an older one is refused rather than overwriting.
    rev: int = 0
    #: A document is markdown from anywhere, so opening one runs nothing until somebody says so.
    trusted: bool = False
    def bump(self): self.rev += 1; return self.rev
    def allow(self):
        "Say this document's code may run, and run it."
        self.trusted = True
        return self.runtime.run_all(self.canvas.bricks)
    def must_trust(self):
        if not self.trusted: raise Untrusted('this document has not been trusted to run')
    def check(self, rev):
        "Refuse a write whose base revision is not the one on disk-to-be."
        if rev is not None and int(rev) != self.rev: raise Stale(f'document moved to rev {self.rev}')
    def remember(self, question, brick_id='', selection=''):
        self.trail.append({'question': question, 'brick': brick_id, 'selection': selection[:160]})
        del self.trail[:-12]
        return self.trail
    def queue(self, turn):
        q = self.steer.get(turn)
        if q is None: q = self.steer[turn] = asyncio.Queue()
        return q
    def close_turn(self, turn): self.steer.pop(turn, None)

class Store:
    "Every canvas one workspace has open, keyed by resolved path."
    def __init__(self, pool=None): self.open, self.pool = {}, pool
    def files(self, d=None):
        d = Path(d or canvas_dir())
        return L(sorted(d.glob('*.canvas.md'))) if d.is_dir() else L()
    @staticmethod
    def key(path):
        "Two spellings of one file are one entry, so a second spelling cannot fork the namespace."
        return str(Path(path).expanduser().resolve())
    def get(self, path):
        "Opened, not run. `Open.allow` is what runs it, and only a person asks for that."
        key = self.key(path)
        if key not in self.open:
            doc = Canvas.load(path)
            rt = runtime_for(self.pool, key=f'canvas:{key}', cwd=Path(path).parent)
            self.open[key] = Open(canvas=doc, runtime=rt)
        return self.open[key]
    def reopen(self, path):
        o = self.open.pop(self.key(path), None)
        if o is not None: o.runtime.close()
        return self.get(path)
    def close(self):
        for o in self.open.values(): o.runtime.close()
        self.open.clear()

#: One store per set of open roots. Two workspaces that open the same file get their own namespace,
#: so a name written in one is not readable in the other.
_STORES: dict = {}

def store_for(fs=None, pool=None):
    "The store belonging to `fs`'s workspace."
    key = tuple(sorted(str(r) for r in (getattr(fs, 'roots', None) or ())))
    if key not in _STORES: _STORES[key] = Store(pool=pool)
    elif pool is not None and _STORES[key].pool is None: _STORES[key].pool = pool
    return _STORES[key]
