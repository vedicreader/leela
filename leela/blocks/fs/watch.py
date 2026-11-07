"Changes leela did not make itself. The agent's, a terminal's, another editor's."

from __future__ import annotations

import asyncio, os, sys, threading
from pathlib import Path

from fastcore.all import store_attr

from ... import errstr
from ...core import keys as keymap
from .fs import SKIP_DIRS

__all__ = ['Watcher', 'KEYMAP', 'git_meta', 'linux_targets']

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

def _linux(): return sys.platform.startswith('linux')

def linux_targets(roots):
    "The folders inotify watches one by one: each root and every folder below it that the walk keeps, plus each repository's `.git` and `.git/refs`."
    from rgapi import fd_iter
    from .fs import _SKIP_RE
    out = {str(r) for r in roots}
    for r in roots: out |= {str(d) for d in fd_iter(root=str(r), files=False, dirs=True, hidden=True, skip_dir_re=_SKIP_RE)}
    for d in list(out):
        if (g := Path(d)/'.git').is_dir():   # a worktree's `.git` is a file, and its HEAD lives in the main repository
            out |= {str(g), *(str(x) for x in [g/'refs', *(g/'refs').rglob('*')] if x.is_dir())}
    return sorted(out)

def _sig(p):
    "What an edit changes, rename-over included: a new inode. None once the file is gone."
    try: st = os.stat(p)
    except OSError: return None
    return st.st_mtime_ns, st.st_size, st.st_ino

class Watcher:
    "One watchfiles thread over the open roots. Subscribers get debounced batches of paths."
    def __init__(self, fs, step=200, poll=1):
        store_attr()
        self.subs, self.stop, self.thread, self.loop, self.roots, self.up, self.gone = set(), None, None, None, (), (), set()
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
        polled, quiet = self.up = threading.Event(), threading.Event()
        if roots:
            self.thread = threading.Thread(target=self._run, args=(roots, self.stop, quiet), daemon=True,
                                           name='leela-fs-watch')
            self.thread.start()
        else: quiet.set()
        threading.Thread(target=self._poll, args=(self.stop, polled), daemon=True, name='leela-loose-poll').start()
    async def settled(self, timeout=10):
        "True once the poll holds its baseline and the watch has gone `RUST_TIMEOUT` without a batch."
        return all(await asyncio.gather(*(asyncio.to_thread(e.wait, timeout) for e in self.up)))
    def close(self, wait=True):
        # The notify thread is Rust: one alive at interpreter teardown segfaults. Teardown joins.
        # A replacement does not, and the two overlap until the old one notices `stop`.
        thread, stop = self.thread, self.stop
        self.thread = self.stop = None
        if stop: stop.set()
        if wait and thread and thread is not threading.current_thread(): thread.join(timeout=WAIT)
    def _run(self, roots, stop, quiet):
        try: from watchfiles import watch
        except ImportError as e:
            quiet.set()
            # Said once, on the thread: silence here is why a frozen build went without a file
            # watcher for as long as it did, and the tree looked merely stale rather than broken.
            print(f'  the file tree will not follow the disk: {errstr(e)}')
            return
        from watchfiles import Change
        keep = lambda _change, p: not (set(Path(p).parts) & SKIP_DIRS) or git_meta(p) is not None
        live = [r for r in roots if r not in self.gone or os.path.isdir(r)]
        # inotify has one watch per folder, and a recursive watch adds one inside node_modules and .venv too, which the
        # filter then drops. On Linux the folders are listed here and watched one by one; a new folder rebuilds the list.
        linux, retries = _linux(), 0
        while live and not stop.is_set():
            try:
                targets, grown = linux_targets(live) if linux else live, []
                for batch in watch(*targets, stop_event=stop, watch_filter=keep, debounce=self.step,
                                   rust_timeout=RUST_TIMEOUT, yield_on_timeout=True, recursive=not linux):
                    if stop.is_set(): return
                    if not batch:                            # macOS replays a setup mkdir late; this follows it
                        quiet.set()
                        continue
                    paths = {p for _change, p in batch}
                    if linux and (grown := [p for c, p in batch if c == Change.added and os.path.isdir(p)]):
                        # what was made in it before its watch starts is pushed now, or it is never seen
                        paths |= {str(f) for g in grown for f in Path(g).rglob('*') if keep(None, str(f))}
                    try: self._push(sorted(paths))
                    except RuntimeError: return              # the loop closed under us
                    if grown: break
                if not grown: return
                retries = 0
            except OSError as e:
                # A watched folder was deleted: drop it, keep the rest. Said once per folder.
                gone = [r for r in live if not os.path.isdir(r)]
                if linux and not gone and retries < 3:
                    # a folder in the list went before its watch started, or the inotify limit was reached: list again, then watch each root whole
                    retries += 1
                    if retries == 3: linux = False; print(f'  the file tree watches each folder whole: {errstr(e)}')
                    continue
                if new := [r for r in gone if r not in self.gone] or (not gone and live):
                    print(f'  the file tree no longer follows {", ".join(new)}: {errstr(e)}')
                self.gone |= set(gone)
                if not gone: break
                live = [r for r in live if r not in gone]
        quiet.set()
    def _poll(self, stop, polled):
        "Admitted files and the keymap sit outside every watched root, so they are statted."
        seen = {p: _sig(p) for p in self.fs.admitted}   # taken now: an edit before the first tick is still one
        polled.set()
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
