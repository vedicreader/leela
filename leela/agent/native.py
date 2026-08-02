"""Catching what a native model engine says on its way past.

litert_lm is C++. When it refuses a request -- *"input token IDs exceed the maximum number
of tokens 4096, got 5092"* -- it writes that to file descriptor 2 and returns; no Python
exception is raised, so no `except` anywhere in this package can see it. The turn then
fails, or comes back empty, and the IDE has nothing to show but silence. That is the whole
of the "the server eats rishi errors" problem: nobody ate it, it never arrived.

`capture` is the fix. It redirects fd 1 and 2 through a pipe for the length of one model
call, *tees* everything to where it was going (so a terminal session still shows the
engine's output) and keeps the tail. The caller can then attach the tail to the failure it
reports.

Three things it is careful about, because a broken stderr is a much worse bug than the one
being fixed:

- the original descriptors are duplicated first and restored in a `finally`, so an
  exception anywhere still puts them back;
- Python-level `sys.stdout`/`sys.stderr` are left alone -- only the descriptors move, which
  is the level the native writer uses;
- it is a no-op when the descriptors are not real files (some notebook hosts replace them),
  and can be turned off outright with `LEELA_NO_NATIVE_CAPTURE=1`.
"""

from __future__ import annotations
import os, sys, threading

__all__ = ['captured', 'capture', 'interesting']

MAX_KEEP = 8_000        # tail kept per call; an engine that logs a lot must not eat memory

# Lines worth showing a person. An engine that chats about delegate creation on every call
# would otherwise bury the one line that explains why the turn failed.
_NOISE = ('created tensorflow lite', 'xnnpack delegate', 'metal delegate', 'tflite',
          'loading model', 'initialized', 'gpu delegate', 'w0000', 'i0000')
_SIGNAL = ('error', 'fail', 'exceed', 'exceeds', 'too long', 'out of memory', 'oom',
           'invalid', 'refus', 'cannot', 'unsupported', 'abort')


def interesting(text, limit=4):
    """The lines of captured output a person should see: complaints, not chatter.

    Matched on words rather than on a log level, because the level is not in the text by
    the time it reaches a pipe. A line that says `exceed` or `error` is worth a status bar;
    a line about delegate creation is not.
    """
    out = []
    for ln in (text or '').splitlines():
        s = ln.strip()
        if not s: continue
        low = s.lower()
        if any(n in low for n in _NOISE): continue
        if any(g in low for g in _SIGNAL): out.append(s)
    # Deduplicated, because a native layer will happily repeat itself once per token.
    seen, uniq = set(), []
    for s in out:
        if s in seen: continue
        seen.add(s); uniq.append(s)
    return uniq[-limit:]


class _Tee:
    "One redirected descriptor: everything through a pipe, out to the original, and into a buffer."

    def __init__(self, fd):
        self.fd = fd
        self.saved = self.r = self.w = None
        self.buf = bytearray()
        self.thread = None

    def start(self):
        self.saved = os.dup(self.fd)                  # raises if fd is not a real descriptor
        self.r, self.w = os.pipe()
        os.dup2(self.w, self.fd)
        os.close(self.w)
        self.w = None
        self.thread = threading.Thread(target=self._pump, daemon=True)
        self.thread.start()

    def _pump(self):
        while True:
            try: b = os.read(self.r, 4096)
            except OSError: break
            if not b: break
            self.buf += b
            del self.buf[:-MAX_KEEP]
            try: os.write(self.saved, b)              # still goes where it was going
            except OSError: pass

    def stop(self):
        # Order matters: put the real descriptor back *first*, so anything written while
        # the pipe is being torn down goes somewhere real rather than to a closed fd.
        if self.saved is not None:
            try: os.dup2(self.saved, self.fd)
            except OSError: pass
        if self.r is not None:
            try: os.close(self.r)
            except OSError: pass
        if self.thread is not None: self.thread.join(timeout=1.0)
        if self.saved is not None:
            try: os.close(self.saved)
            except OSError: pass
        return self.buf.decode('utf-8', 'replace')


class captured:
    """Context manager: `with captured() as cap: ...`, then read `cap.text`.

    Serialised on a lock, because two threads redirecting the same descriptor at once would
    restore each other's copies. Model calls already hold a per-backend lock; this is the
    guard for the case where two different backends are called at once.
    """

    _lock = threading.Lock()

    def __init__(self, fds=(1, 2), enabled=None):
        self.fds = fds
        self.text = ''
        self.enabled = (os.environ.get('LEELA_NO_NATIVE_CAPTURE', '') not in ('1', 'true', 'yes')
                        if enabled is None else enabled)
        self._tees, self._held = [], False

    def __enter__(self):
        if not self.enabled: return self
        if not self._lock.acquire(timeout=0.5): return self      # someone else has it; don't queue
        self._held = True
        for fd in self.fds:
            t = _Tee(fd)
            try:
                sys.stdout.flush(); sys.stderr.flush()
                t.start()
                self._tees.append(t)
            except Exception:
                break                                            # not a real fd here; capture what we can
        return self

    def __exit__(self, *exc):
        parts = []
        for t in reversed(self._tees):
            try: parts.append(t.stop())
            except Exception: pass
        self._tees = []
        if self._held:
            self._held = False
            try: self._lock.release()
            except RuntimeError: pass
        self.text = ''.join(reversed(parts))
        return False

    @property
    def problems(self):
        "The captured lines worth reporting, as one string, or ''."
        return '\n'.join(interesting(self.text))


def capture(fn, *a, **kw):
    """Call `fn`, returning `(result, captured_problem_text)`. Exceptions carry the text out too.

    The re-raise happens *after* the context manager exits, because the text does not exist
    until the pipe has been drained -- reading it from inside the block would attach an
    empty string to every exception, which is the failure this module exists to prevent.
    """
    cap, err, out = captured(), None, None
    with cap:
        try: out = fn(*a, **kw)
        except Exception as e: err = e
    if err is not None:
        err.native_output = cap.problems
        raise err
    return out, cap.problems
