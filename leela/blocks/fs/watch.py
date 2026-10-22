"Changes leela did not make itself. The agent's, a terminal's, another editor's."

from __future__ import annotations

import asyncio, threading
from pathlib import Path

from fastcore.all import store_attr

from ... import errstr
from .fs import SKIP_DIRS

__all__ = ['Watcher']

MAX_BATCH = 200
RUST_TIMEOUT = 500      # how long the watcher can take to notice it was stopped
WAIT = 3

class Watcher:
    "One watchfiles thread over the open roots. Subscribers get debounced batches of paths."
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
        # A folder opens through a sync route: no loop here, but `subscribe` captured one.
        try: loop = asyncio.get_running_loop()
        except RuntimeError: loop = self.loop
        if loop is None: return
        self.close(wait=False)
        if not roots: return
        self.roots, self.loop, self.stop = roots, loop, threading.Event()
        self.thread = threading.Thread(target=self._run, args=(roots, self.stop), daemon=True,
                                       name='leela-fs-watch')
        self.thread.start()
    def close(self, wait=True):
        # The notify thread is Rust: one alive at interpreter teardown segfaults. Teardown joins.
        # A replacement does not, and the two overlap until the old one notices `stop`.
        thread, stop = self.thread, self.stop
        self.thread = self.stop = None
        if stop: stop.set()
        if wait and thread and thread is not threading.current_thread(): thread.join(timeout=WAIT)
    def _run(self, roots, stop):
        try: from watchfiles import watch
        except ImportError as e:
            # Said once, on the thread: silence here is why a frozen build went without a file
            # watcher for as long as it did, and the tree looked merely stale rather than broken.
            print(f'  the file tree will not follow the disk: {errstr(e)}')
            return
        keep = lambda _change, p: not (set(Path(p).parts) & SKIP_DIRS)
        for batch in watch(*roots, stop_event=stop, watch_filter=keep, debounce=self.step,
                           rust_timeout=RUST_TIMEOUT):
            if stop.is_set(): return
            try: self._push(sorted({p for _change, p in batch}))
            except RuntimeError: return                      # the loop closed under us
    def _push(self, paths, resync=False):
        # A batch is a delta, so one lost is lost for good. Too many to carry is a redraw instead.
        if len(paths) > MAX_BATCH: paths, resync = [], True
        for q in list(self.subs): self.loop.call_soon_threadsafe(self._offer, q, paths, resync)
    def announce(self, path):
        "Tell every subscriber a tab was opened on `path` by something other than the page. From any thread."
        if self.loop is None: return
        for q in list(self.subs): self.loop.call_soon_threadsafe(self._offer_open, q, str(path))
    @classmethod
    def _offer_open(cls, q, path):
        if q.full(): cls._offer(q, [], False)
        q.put_nowait(path)
    @staticmethod
    def _offer(q, paths, resync=False):
        if q.full():
            while not q.empty(): q.get_nowait()
            paths, resync = [], True
        q.put_nowait((paths, resync))
