"""Queued work with a visible state, and a cadence for the work that repeats.

Two mechanisms, deliberately not one.

**A job is a row.** `queued -> running -> complete | error`, with `progress`, `current` and a
partial `result` written as it goes, so a long clip is queryable while it runs rather than only
after. The browser polls the row; nothing here pushes.

**A cadence is a watch.** vishalakshi owns those -- `Memory.watch` writes the row, `Memory.poll`
runs what is due -- so this module schedules the tick and does not reimplement the scheduler. A
`script` action is registered so a workspace can run a command on a cadence, which is what makes
this general rather than clip-specific.

Restart is a first-class case: a job left `running` by a killed process is a lie the moment the
process dies, so `recover` re-queues what carries `_resume` and fails the rest with a reason.
"""

from __future__ import annotations

import json, os, sqlite3, subprocess, threading, time, uuid
from fastcore.all import Path, first, ifnone, store_attr

from ... import errstr

__all__ = ['Job', 'Jobs', 'JobError', 'ACTIVE', 'TERMINAL']

ACTIVE = ('queued', 'running')
TERMINAL = ('complete', 'error')

# One command at a time per job, and never a shell: the target is a list, or it is split by
# `shlex` at the boundary that accepts it, so a job cannot become an injection.
SCRIPT_TIMEOUT = 900


class JobError(RuntimeError):
    pass


class Job:
    "One row, as the browser reads it."

    __slots__ = ('id', 'kind', 'target', 'params', 'status', 'progress', 'current',
                 'result', 'error', 'created_at', 'started_at', 'finished_at')

    def __init__(self, id, kind, target='', params=None, status='queued', progress=0.0,
                 current='', result=None, error='', created_at=None, started_at=None,
                 finished_at=None):
        store_attr()
        self.params, self.result = dict(params or {}), result
        self.created_at = ifnone(created_at, time.time())

    @property
    def active(self): return self.status in ACTIVE

    @property
    def resumable(self): return bool(self.params.get('_resume'))

    def dict(self):
        return {n: getattr(self, n) for n in self.__slots__} | {'active': self.active}


class Jobs:
    """Every job for one workspace, in one SQLite file beside the rest of its state.

    `run` registers what a kind does: `f(job, report) -> result`, where `report(**kw)` writes
    progress back into the row. A handler that never calls `report` still works; it just says
    nothing until it finishes.
    """

    def __init__(self, path, memory=None):
        self.path, self.memory = Path(path), memory
        self.note, self._handlers, self._lock = '', {}, threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    # -- storage ------------------------------------------------------------
    def _db(self):
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute('pragma journal_mode=wal')
        return c

    def _init(self):
        with self._db() as c:
            c.execute('''create table if not exists jobs(
                id text primary key, kind text, target text, params text, status text,
                progress real, current text, result text, error text,
                created_at real, started_at real, finished_at real)''')
            c.execute('create index if not exists jobs_status on jobs(status, created_at)')

    @staticmethod
    def _row(r):
        d = dict(r)
        for k in ('params', 'result'):
            d[k] = json.loads(d[k]) if d.get(k) else None
        return Job(**d)

    def get(self, jid):
        with self._db() as c:
            r = c.execute('select * from jobs where id=?', (str(jid),)).fetchone()
        if r is None: raise JobError(f'no job {jid}')
        return self._row(r)

    def all(self, limit=40, kind=None):
        q = 'select * from jobs' + (' where kind=?' if kind else '') + ' order by created_at desc limit ?'
        with self._db() as c:
            rows = c.execute(q, ((kind, limit) if kind else (limit,))).fetchall()
        return [self._row(r) for r in rows]

    def update(self, jid, **kv):
        for k in ('params', 'result'):
            if k in kv: kv[k] = json.dumps(_plain(kv[k]))
        if not kv: return
        sets = ', '.join(f'{k}=?' for k in kv)
        with self._db() as c:
            c.execute(f'update jobs set {sets} where id=?', (*kv.values(), str(jid)))

    # -- lifecycle ----------------------------------------------------------
    def register(self, kind, fn):
        "What `kind` does. `fn(job, report) -> result`."
        self._handlers[kind] = fn
        return fn

    def new(self, kind, target='', **params):
        if kind not in self._handlers: raise JobError(f'unknown job kind {kind!r}')
        job = Job(id=f'{kind}-{uuid.uuid4().hex[:10]}', kind=kind, target=str(target), params=params)
        with self._db() as c:
            c.execute('insert into jobs(id,kind,target,params,status,progress,current,created_at) '
                      'values(?,?,?,?,?,?,?,?)',
                      (job.id, kind, job.target, json.dumps(_plain(job.params)),
                       'queued', 0.0, '', job.created_at))
        return job

    def launch(self, jid):
        "Start `jid` on its own thread. Returns at once; the row is how you watch it."
        job = self.get(jid)
        if job.status == 'running': raise JobError(f'job {jid} is already running')
        fn = self._handlers.get(job.kind)
        if fn is None: raise JobError(f'unknown job kind {job.kind!r}')
        self.update(jid, status='running', started_at=time.time(), progress=0.05, error='')
        threading.Thread(target=self._run, args=(jid, fn), daemon=True,
                         name=f'leela-job-{jid}').start()
        return self.get(jid)

    def start(self, kind, target='', **params):
        "`new` then `launch`, which is what a route almost always wants."
        return self.launch(self.new(kind, target, **params).id)

    def _run(self, jid, fn):
        def report(**kw):
            # Partial results are committed as they arrive, so a long job is readable while it
            # runs and a restart has somewhere to resume from.
            self.update(jid, **kw)
        try:
            out = fn(self.get(jid), report)
            self.update(jid, status='complete', progress=1.0, result=out, finished_at=time.time())
        except Exception as e:
            # `errstr` already reads `TypeName: message`, which is what every other surface shows.
            self.update(jid, status='error', error=errstr(e)[:900], finished_at=time.time())

    def recover(self):
        """Re-queue what a restart interrupted, and fail the rest with a reason.

        A job still marked `running` in a fresh process is not running. Leaving it that way is
        how a panel comes to show a spinner nothing will ever stop.
        """
        out = {'resumed': [], 'failed': []}
        for job in self.all(limit=200):
            if not job.active: continue
            if job.resumable and job.kind in self._handlers:
                self.update(job.id, status='queued', current='resuming after a restart')
                out['resumed'].append(job.id)
                self.launch(job.id)
            else:
                self.update(job.id, status='error', finished_at=time.time(),
                            error='interrupted by an application restart')
                out['failed'].append(job.id)
        self.note = f"recovered {len(out['resumed'])}, failed {len(out['failed'])}"
        return out

    # -- cadence ------------------------------------------------------------
    def tick(self, seconds=None):
        """Poll due watches every `seconds`, on a daemon thread. Idempotent; `0` disables it.

        Started by `serve_ide` rather than by the block, so building an app in a test does not
        leave a thread behind. Nothing here pushes to the browser: a watch that fires writes a
        document, and the surfaces find it the next time they look.
        """
        secs = int(seconds if seconds is not None else os.getenv('LEELA_POLL_SECONDS') or 0)
        if secs <= 0 or getattr(self, '_ticking', None): return None
        self._ticking = True

        def loop():
            while True:
                time.sleep(secs)
                try: self.poll_due()
                except Exception as e: self.note = f'poll tick failed ({errstr(e)})'
        threading.Thread(target=loop, daemon=True, name='leela-job-tick').start()
        return secs

    def poll_due(self):
        """Run every watch that has come due, under a lock so two ticks cannot overlap.

        The lock is per-process. A second leela on the same vault would need a file lock; that is
        a real gap and not one this solves.
        """
        if self.memory is None: return {'note': 'no vault', 'ran': 0, 'checked': 0}
        if not self._lock.acquire(blocking=False):
            return {'note': 'a poll is already running', 'ran': 0, 'checked': 0}
        try: return self.memory.poll()
        finally: self._lock.release()


def _plain(o):
    "JSON-safe: a handler may return whatever the vault handed it."
    if isinstance(o, (str, int, float, bool)) or o is None: return o
    if isinstance(o, dict): return {str(k): _plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)): return [_plain(v) for v in o]
    if isinstance(o, Path): return str(o)
    if hasattr(o, 'dict') and callable(o.dict): return _plain(o.dict())
    return str(o)


def run_script(argv, cwd=None, timeout=SCRIPT_TIMEOUT):
    "One command, no shell, output captured. What a `script` cadence runs."
    import shlex
    cmd = shlex.split(argv) if isinstance(argv, str) else [str(a) for a in argv]
    if not cmd: raise JobError('nothing to run')
    r = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True,
                       text=True, timeout=timeout)
    out = {'argv': cmd, 'returncode': r.returncode, 'stdout': (r.stdout or '')[-4000:],
           'stderr': (r.stderr or '')[-2000:]}
    if r.returncode: raise JobError(f'{cmd[0]} exited {r.returncode}: '
                                    f'{(r.stderr or r.stdout or "").strip()[-600:]}')
    return out
