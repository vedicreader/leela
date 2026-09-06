"What an open canvas needs beside the file: a namespace, a trail, and somewhere to put steering."

from __future__ import annotations
import asyncio, os
from dataclasses import dataclass, field
from fastcore.all import L, Path, first
from .doc import Canvas
from .live import Runtime

__all__ = ['Open', 'Store', 'canvas_dir', 'brick_host']

def canvas_dir(): return Path(os.getenv('CANVAS_DIR') or (Path(__file__).parent.parent.parent.parent/'examples'/'canvas'))
def brick_host(): return os.getenv('BRICK_HOST') or 'http://127.0.0.1:5001'

@dataclass
class Open:
    "One canvas, open: the document, the namespace it runs in, and the questions asked of it."
    canvas: Canvas
    runtime: Runtime = field(default_factory=Runtime)
    trail: list = field(default_factory=list)
    steer: dict = field(default_factory=dict)
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
    "Every canvas this session has open, keyed by path."
    def __init__(self): self.open = {}
    def files(self, d=None):
        d = Path(d or canvas_dir())
        return L(sorted(d.glob('*.canvas.md'))) if d.is_dir() else L()
    def get(self, path):
        key = str(path)
        if key not in self.open:
            o = Open(canvas=Canvas.load(path))
            o.runtime.run_all(o.canvas.bricks)
            self.open[key] = o
        return self.open[key]
    def reopen(self, path):
        self.open.pop(str(path), None)
        return self.get(path)
