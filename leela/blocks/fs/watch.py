"Changes leela did not make itself. The agent's, a terminal's, another editor's."

from __future__ import annotations

import asyncio, os, threading
from pathlib import Path

from fastcore.all import store_attr

from ... import errstr
from ...core import keys as keymap
from .fs import SKIP_DIRS

__all__ = ['Watcher', 'KEYMAP', 'git_meta']

KEYMAP = ('keymap',)    # queued when the keymap file changed and `keymap.KEYS` was rebuilt

MAX_BATCH = 200
RUST_TIMEOUT = 500      # how long the watcher can take to notice it was stopped
WAIT = 3

def git_meta(p):
    "The repository whose HEAD, index or refs `p` is, so a commit made outside Leela is seen; else None."
    parts = Path(p).parts
    if '.git' not in parts: return None
    i = parts.index('.git')
    head, rest = parts[:i], parts[i+1:]
    if set(head) & SKIP_DIRS or not rest or rest[-1].endswith('.lock'): return None
    if rest in (('HEAD',), ('index',), ('packed-refs',)) or rest[0] == 'refs': return str(Path(*head))
    return None

def _sig(p):
    "What an edit changes, rename-over included: a new inode. None once the file is gone."
    try: st = os.stat(p)
    except OSError: return None
    return st.st_mtime_ns, st.st_size, st.st_ino

class Watcher:
    "One watchfiles thread over the open roots. Subscribers get debounced batches of paths."
    def __init__(self, fs, step=200, poll=1):
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
        self.roots, self.loop, self.stop, self.keys = roots, loop, threading.Event(), keymap.VERSION
        if roots:
            self.thread = threading.Thread(target=self._run, args=(roots, self.stop), daemon=True,
                                           name='leela-fs-watch')
            self.thread.start()
        threading.Thread(target=self._poll, args=(self.stop,), daemon=True, name='leela-loose-poll').start()
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
        keep = lambda _change, p: not (set(Path(p).parts) & SKIP_DIRS) or git_meta(p) is not None
        for batch in watch(*roots, stop_event=stop, watch_filter=keep, debounce=self.step,
                           rust_timeout=RUST_TIMEOUT):
            if stop.is_set(): return
            try: self._push(sorted({p for _change, p in batch}))
            except RuntimeError: return                      # the loop closed under us
    def _poll(self, stop):
        "Admitted files and the keymap sit outside every watched root, so they are statted."
        seen = {}
        while not stop.wait(self.poll):
            now = {p: _sig(p) for p in self.fs.admitted}
            try:
                if hit := sorted(str(p) for p, s in now.items() if p in seen and seen[p] != s): self._push(hit)
                if keymap.changed() or self.keys != keymap.VERSION: self.loop.call_soon_threadsafe(self._keymap)
            except RuntimeError: return
            seen = now
    def _keymap(self):
        # On the loop, so a reload never interleaves with a route that reads or saves the keymap.
        # The keymap is global: another workspace's watcher, or a save, may have rebuilt it first.
        keymap.refresh()
        if self.keys == keymap.VERSION: return
        self.keys = keymap.VERSION
        for q in list(self.subs): self._offer_one(q, KEYMAP)
    def _push(self, paths, resync=False):
        # A batch is a delta, so one lost is lost for good. Too many to carry is a redraw instead.
        if len(paths) > MAX_BATCH: paths, resync = [], True
        for q in list(self.subs): self.loop.call_soon_threadsafe(self._offer, q, paths, resync)
    def changed(self, paths):
        "Tell every subscriber `paths` changed on disk, as the watch thread does. From any thread."
        if self.loop is not None: self._push(sorted(map(str, paths)))
    def announce(self, path):
        "Tell every subscriber a tab was opened on `path` by something other than the page. From any thread."
        if self.loop is None: return
        for q in list(self.subs): self.loop.call_soon_threadsafe(self._offer_one, q, str(path))
    @classmethod
    def _offer_one(cls, q, item):
        if q.full(): cls._offer(q, [], False)
        q.put_nowait(item)
    @staticmethod
    def _offer(q, paths, resync=False):
        if q.full():
            while not q.empty(): q.get_nowait()
            paths, resync = [], True
        q.put_nowait((paths, resync))
