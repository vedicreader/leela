"Changes leela did not make itself: the agent's, a terminal's, another editor's."

from __future__ import annotations

import asyncio, threading
from pathlib import Path

from fastcore.all import store_attr

from .fs import SKIP_DIRS

__all__ = ['Watcher']

MAX_BATCH = 200
RUST_TIMEOUT = 500      # how long the watcher can take to notice it was stopped
WAIT = 3

class Watcher:
    "One watchfiles thread over the open roots; subscribers get debounced batches of paths."
    def __init__(self, fs, step=200):
        store_attr()
        self.subs, self.stop, self.thread, self.loop, self.roots = set(), None, None, None, ()
    def subscribe(self):
        q = asyncio.Queue(maxsize=64)
        self.subs.add(q)
        self.start()
        return q
    def unsubscribe(self, q):
        # The event loop runs this. `close` owns the join.
        self.subs.discard(q)
        if not self.subs and self.stop: self.stop.set()
    def start(self, restart=False):
        "Watch the roots as they are now. `restart` picks up a folder opened since."
        roots = tuple(sorted(str(r) for r in self.fs.roots))
        running = self.thread and self.thread.is_alive() and self.stop and not self.stop.is_set()
        if running and not (restart or roots != self.roots): return
        self.close()
        if not roots: return
        self.roots, self.loop, self.stop = roots, asyncio.get_running_loop(), threading.Event()
        self.thread = threading.Thread(target=self._run, args=(roots, self.stop), daemon=True,
                                       name='leela-fs-watch')
        self.thread.start()
    def close(self):
        # Joined, not just signalled: the notify thread is Rust, and one still running when
        # the interpreter tears down segfaults.
        thread, stop = self.thread, self.stop
        self.thread = self.stop = None
        if stop: stop.set()
        if thread and thread is not threading.current_thread(): thread.join(timeout=WAIT)
    def _run(self, roots, stop):
        try: from watchfiles import watch
        except ImportError: return
        keep = lambda _change, p: not (set(Path(p).parts) & SKIP_DIRS)
        for batch in watch(*roots, stop_event=stop, watch_filter=keep, debounce=self.step,
                           rust_timeout=RUST_TIMEOUT):
            if stop.is_set(): return
            try: self._push(sorted({p for _change, p in batch})[:MAX_BATCH])
            except RuntimeError: return                      # the loop closed under us
    def _push(self, paths):
        for q in list(self.subs): self.loop.call_soon_threadsafe(self._offer, q, paths)
    @staticmethod
    def _offer(q, paths):
        # A browser that stopped reading must not hold the watcher; a dropped batch is a
        # refresh it will get from the next one.
        if not q.full(): q.put_nowait(paths)
