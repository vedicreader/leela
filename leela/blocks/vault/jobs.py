from __future__ import annotations

import json, os, re, shlex, sqlite3, subprocess, threading, time, uuid
from functools import partial
from fastcore.all import L, Path, ifnone, store_attr

from ... import errstr

__all__ = ['Job', 'Jobs', 'JobError', 'ACTIVE', 'TERMINAL', 'BULK', 'every_seconds', 'cadence', 'background', 'quitting']

ACTIVE = ('queued', 'running')
TERMINAL = ('complete', 'error', 'cancelled')
#: Kinds that file whole files in batches: a cancel keeps the files done and a resume clips the rest.
CLIPS = ('clip', 'clip_tree', 'acquire')
#: Kinds that stop between files whatever their params say: a job started before `_cancel` lacks the flag.
STOPS = ('clip', 'clip_tree')

def every_seconds(spec, default=3600):
    "Seconds from `'30m'`, `'6h'`, or a bare number of hours. `default` when it is not a duration."
    from ...agent.monitor import secs
    text = ''.join(str('' if spec is None else spec).split()).lower()
    if not re.fullmatch(r'\d+(?:\.\d+)?[smhdw]?', text): return default
    try: return max(60, secs(text if text[-1].isalpha() else text + 'h'))
    except ValueError: return default

def cadence(seconds):
    seconds = int(seconds or 0)
    for n, label in ((604800, 'week'), (86400, 'day'), (3600, 'hour'), (60, 'minute')):
        if seconds and not seconds % n:
            v = seconds // n
            return f'every {v} {label}' + ('s' if v != 1 else '')
    return f'every {seconds} seconds'

SCRIPT_TIMEOUT = 900

REINDEX_SECONDS = 300

#: Seconds a resumed job waits after launch, so the first paint does not compete with it.
RESUME_DELAY = 30

#: Kinds that grind through many files or pages; they run at background priority.
BULK = frozenset({'clip', 'clip_tree', 'acquire', 'connect', 'feeds', 'poll', 'tidy'})

_bg_fork = False
#: `(jobs file, job id)` running in this process, which a second workspace's `recover` must leave alone.
_live = set()

def background():
    "Put this thread at macOS background priority: its CPU and disk I/O yield to the window. False elsewhere."
    if not hasattr(os, 'PRIO_DARWIN_BG'): return False
    os.setpriority(os.PRIO_DARWIN_THREAD, 0, os.PRIO_DARWIN_BG)
    return True

def _note_bg():
    global _bg_fork
    _bg_fork = bool(os.getpriority(os.PRIO_DARWIN_THREAD, 0))

def _child_bg():
    # A thread's background priority is not inherited by fork, so a pool forked from a job thread would run at full speed.
    if _bg_fork: os.setpriority(os.PRIO_DARWIN_PROCESS, 0, os.PRIO_DARWIN_BG)

if hasattr(os, 'PRIO_DARWIN_BG'): os.register_at_fork(before=_note_bg, after_in_child=_child_bg)

def quitting():
    "Whether the desktop shell is reaping this process, when a job's pool breaks under it."
    try: from kavacha.window import quitting
    except ImportError: return False
    return quitting.is_set()

class JobError(RuntimeError):
    pass

def _jsonable(o):
    if isinstance(o, (L, set)): return list(o)
    if isinstance(o, Path): return str(o)
    return str(o)

class Job:
    __slots__ = ('id', 'kind', 'target', 'params', 'status', 'progress', 'current', 'result',
        'error', 'created_at', 'started_at', 'finished_at', 'cancel_at')
    def __init__(self, id, kind, target='', params=None, status='queued', progress=0.0, current='',
        result=None, error='', created_at=None, started_at=None, finished_at=None, cancel_at=None):
        store_attr()
        self.params = dict(params or {})
        self.created_at = ifnone(created_at, time.time())
    @property
    def active(self): return self.status in ACTIVE
    @property
    def resumable(self): return bool(self.params.get('_resume'))
    @property
    def cancellable(self):
        p = self.params
        return bool(p.get('_cancel')) or self.kind in STOPS or (self.kind == 'acquire' and p.get('action') == 'clip')
    def dict(self): return {n: getattr(self, n) for n in self.__slots__} | dict(active=self.active, cancellable=self.cancellable)

class Jobs:
    def __init__(self, path, memory=None):
        self.path, self.memory = Path(path), memory
        self.note, self._handlers, self._lock = '', {}, threading.Lock()
        self._ticking = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()
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
            # a cancel lives in its own column, so a clip's per-batch params rewrite cannot drop it
            if 'cancel_at' not in {r['name'] for r in c.execute('pragma table_info(jobs)')}:
                try: c.execute('alter table jobs add column cancel_at real')
                except sqlite3.OperationalError as e:
                    # another workspace added it, or holds the write lock and adds it next
                    if not any(m in str(e) for m in ('duplicate column', 'locked')): raise
    @staticmethod
    def _row(r):
        # a newer build's columns are not this build's slots
        d = {k: v for k, v in dict(r).items() if k in Job.__slots__}
        for k in ('params', 'result'): d[k] = json.loads(d[k]) if d.get(k) else None
        return Job(**d)
    def get(self, jid):
        with self._db() as c: r = c.execute('select * from jobs where id=?', (str(jid),)).fetchone()
        if r is None: raise JobError(f'no job {jid}')
        return self._row(r)
    def forget(self, jid):
        job = self.get(jid)
        if job.active: raise JobError('that job is still running')
        with self._db() as c: c.execute('DELETE FROM jobs WHERE id=?', (jid,))
        return job
    def all(self, limit=40, kind=None):
        q = 'select * from jobs' + (' where kind=?' if kind else '') + ' order by created_at desc limit ?'
        with self._db() as c: rows = c.execute(q, (kind, limit) if kind else (limit,)).fetchall()
        return [self._row(r) for r in rows]
    def update(self, jid, **kv):
        kv |= {k: json.dumps(kv[k], default=_jsonable) for k in ('params', 'result') if k in kv}
        if not kv: return
        sets = ', '.join(f'{k}=?' for k in kv)
        with self._db() as c: c.execute(f'update jobs set {sets} where id=?', (*kv.values(), str(jid)))
    def register(self, kind, fn):
        self._handlers[kind] = fn
        return fn
    def new(self, kind, target='', **params):
        if kind not in self._handlers: raise JobError(f'unknown job kind {kind!r}')
        job = Job(id=f'{kind}-{uuid.uuid4().hex[:10]}', kind=kind, target=str(target), params=params)
        with self._db() as c:
            c.execute('insert into jobs(id,kind,target,params,status,progress,current,created_at) values(?,?,?,?,?,?,?,?)',
                (job.id, kind, job.target, json.dumps(job.params, default=_jsonable), 'queued', 0.0, '', job.created_at))
        return job
    def launch(self, jid, fresh=True):
        "Claim and run `jid`. A fresh launch drops an earlier cancel; a resume leaves a cancelled row alone."
        job = self.get(jid)
        fn = self._handlers.get(job.kind)
        if fn is None: raise JobError(f'unknown job kind {job.kind!r}')
        # One claim per row: several workspaces share a jobs file, and each resumes what it finds.
        with self._db() as c:
            n = c.execute("update jobs set status='running', started_at=?, progress=0.05, error='', cancel_at=null where id=? and status!='running'"
                          + ('' if fresh else ' and cancel_at is null'), (time.time(), str(jid))).rowcount
        if not n: raise JobError(f'job {jid} is already running' + ('' if fresh else ' or was cancelled'))
        _live.add((str(self.path), jid))
        threading.Thread(target=self._run, args=(jid, fn), daemon=True, name=f'leela-job-{jid}').start()
        return self.get(jid)
    def start(self, kind, target='', **params):
        return self.launch(self.new(kind, target, **params).id)
    def _run(self, jid, fn):
        try:
            job = self.get(jid)
            if job.kind in BULK: background()
            out = fn(job, partial(self.update, jid))
            # the result says whether pages went unread: a cancel that lands after the last page is a complete run
            done = 'cancelled' if isinstance(out, dict) and out.get('cancelled') else 'complete'
            self.update(jid, status=done, progress=1.0, result=out, finished_at=time.time())
        except Exception as e:
            # A pool reaped by the quit is not a failure: the row stays running and resumes next launch.
            if quitting(): return
            kind = {'result': dict(kind=e.kind, error=errstr(e))} if getattr(e, 'kind', None) else {}
            self.update(jid, status='error', error=errstr(e)[:900], finished_at=time.time(), **kind)
        finally: _live.discard((str(self.path), jid))
    def cancel(self, jid):
        "Ask a running job to stop after the pages or files in flight. The row holds the request, so any workspace and the next launch see it."
        job = self.get(jid)
        if not job.active: raise JobError(f'job {jid} is not running')
        if not job.cancellable: raise JobError(f'a {job.kind} job cannot be cancelled')
        with self._db() as c:
            n = c.execute("update jobs set cancel_at=?, current=? where id=? and status in ('queued', 'running')",
                (time.time(), f"cancelling after the {'files' if job.kind in CLIPS else 'pages'} in flight", str(jid))).rowcount
        if not n: raise JobError(f'job {jid} is not running')
        return self.get(jid)
    def stopping(self, jid):
        # read on every page of a model read: a locked or missing file must not end the job
        try:
            with self._db() as c: r = c.execute('select cancel_at from jobs where id=?', (str(jid),)).fetchone()
        except sqlite3.Error: return False
        return bool(r and r[0])
    def recover(self, delay=None):
        "Resume what a restart interrupted, `delay` seconds from now; fail what cannot resume."
        out = dict(resumed=[], failed=[], cancelled=[])
        delay = float(ifnone(delay, os.getenv('LEELA_RESUME_DELAY') or RESUME_DELAY))
        for job in self.all(limit=200):
            if not job.active or (str(self.path), job.id) in _live: continue
            if job.cancel_at:
                self._cancelled(job.id)
                out['cancelled'].append(job.id)
            elif job.resumable and job.kind in self._handlers:
                self.update(job.id, status='queued', current='resuming after a restart')
                out['resumed'].append(job.id)
                if delay <= 0: self._resume(job.id)
                else:
                    t = threading.Timer(delay, self._resume, (job.id,))
                    t.daemon = True; t.start()
            else:
                self.update(job.id, status='error', finished_at=time.time(),
                    error='interrupted by an application restart')
                out['failed'].append(job.id)
        self.note = f"recovered {len(out['resumed'])}, failed {len(out['failed'])}, cancelled {len(out['cancelled'])}"
        return out
    def _cancelled(self, jid): self.update(jid, status='cancelled', finished_at=time.time(), current='cancelled before it resumed')
    def _resume(self, jid):
        "Launch a recovered job unless it was cancelled meanwhile or another workspace already took it."
        try: self.launch(jid, fresh=False)
        except JobError:
            if self.stopping(jid) and self.get(jid).status == 'queued': self._cancelled(jid)
    def tick(self, seconds=None):
        secs = int(ifnone(seconds, os.getenv('LEELA_POLL_SECONDS') or 0))
        if secs <= 0 or self._ticking: return None
        self._ticking = True
        every = max(secs, int(os.getenv('LEELA_REINDEX_SECONDS') or REINDEX_SECONDS))
        def loop():
            last = time.time()
            while True:
                time.sleep(secs)
                try: self.poll_due()
                except Exception as e: self.note = f'poll tick failed ({errstr(e)})'
                if every <= 0 or time.time() - last < every: continue
                last = time.time()
                try: self.reindex_due()
                except Exception as e: self.note = f'reindex sweep failed ({errstr(e)})'
        threading.Thread(target=loop, daemon=True, name='leela-job-tick').start()
        return secs
    def poll_due(self):
        if self.memory is None: return dict(note='no vault', ran=0, checked=0)
        if not self._lock.acquire(blocking=False): return dict(note='a poll is already running', ran=0, checked=0)
        try: return self.memory.poll()
        finally: self._lock.release()
    def reindex_due(self):
        if self.memory is None: return dict(note='no vault', checked=0, reindexed=0)
        if not self._lock.acquire(blocking=False): return dict(note='a poll is already running', checked=0, reindexed=0)
        try: return self.memory.reindex_changed()
        finally: self._lock.release()

def run_script(argv, cwd=None, timeout=SCRIPT_TIMEOUT):
    cmd = shlex.split(argv) if isinstance(argv, str) else [str(a) for a in argv]
    if not cmd: raise JobError('nothing to run')
    from kunda.pythons import clean_env
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                       env=clean_env())
    if r.returncode: raise JobError(f'{cmd[0]} exited {r.returncode}: {(r.stderr or r.stdout).strip()[-600:]}')
    return dict(argv=cmd, returncode=r.returncode, stdout=r.stdout[-4000:], stderr=r.stderr[-2000:])
