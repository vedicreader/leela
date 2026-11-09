"The server side of live scrub: one worker process per notebook, a snapshot of the plain data a cell reads, and the answer as notebook outputs."
import asyncio, atexit, json, os, shutil, signal, sys, tempfile, time
from pathlib import Path

from . import scrubwire

HERE = Path(__file__).parent
MARK = '@@leela-scrub-snapshot@@'
#: Seconds a tick may run: the first of a gesture (imports), the rest. The worker is killed after that; the kernel is never touched.
FIRST, LIMIT = 5, 1

def memory_cap():
    "About 1.5 GB, or a quarter of the machine's memory when that is less."
    try:
        import psutil
        return min(1_500_000_000, psutil.virtual_memory().total // 4)
    except Exception: return 1_500_000_000

def snapshot_code(names):
    "One expression for the kernel: it runs `scrubwire` in a throwaway namespace, prints the snapshot JSON after `MARK`, and leaves no name behind."
    src = (HERE/'scrubwire.py').read_text()
    return f"(lambda _g: print({MARK!r} + (exec({src!r}, _g) or _g['snapshot_json'](__import__('__main__').__dict__, {list(names)!r}))))({{}})"

def parse_snapshot(outputs):
    "`{'ok': ..}` or `{'bad': name, 'why': text}` from the stream outputs of `snapshot_code`; None when the kernel said nothing usable."
    text = ''.join(o.get('text', '') for o in outputs if o.get('output_type') == 'stream')
    i = text.find(MARK)
    if i < 0: return None
    try: return json.loads(text[i + len(MARK):].strip().splitlines()[0])
    except ValueError: return None

def outputs_of(r):
    "The worker's answer as nbformat outputs."
    outs = []
    if r.get('stdout'): outs.append({'output_type': 'stream', 'name': 'stdout', 'text': r['stdout']})
    if r.get('stderr'): outs.append({'output_type': 'stream', 'name': 'stderr', 'text': r['stderr']})
    if r.get('result') is not None: outs.append({'output_type': 'execute_result', 'execution_count': None, 'metadata': {}, 'data': {'text/plain': r['result']}})
    outs += [{'output_type': 'display_data', 'metadata': {}, 'data': {'image/png': b}} for b in r.get('images', [])]
    if (e := r.get('error')): outs.append({'output_type': 'error', **e})
    return outs

class Worker:
    "A scrub worker process: it keeps its imports warm between ticks, and is killed, never interrupted, when a tick runs too long or too big."
    def __init__(self, python):
        self.python, self.proc, self.dir, self.lock, self.cap, self.seq, self.ticks, self.closing = python, None, None, asyncio.Lock(), memory_cap(), 0, 0, False
    @property
    def alive(self): return self.proc is not None and self.proc.returncode is None
    async def start(self):
        if self.alive: return
        self.ticks = 0
        self.dir = self.dir or tempfile.mkdtemp(prefix='leela-scrub-')
        env = dict(PATH=os.environ.get('PATH', os.defpath), LANG=os.environ.get('LANG', 'C.UTF-8'), **({'SYSTEMROOT': os.environ['SYSTEMROOT']} if 'SYSTEMROOT' in os.environ else {}), MPLBACKEND='Agg', MPLCONFIGDIR=self.dir, HOME=self.dir, LEELA_SCRUB_MEMORY=str(self.cap), OMP_NUM_THREADS='2')
        self.proc = await asyncio.create_subprocess_exec(self.python, '-I', str(HERE/'scrubworker.py'), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                         stderr=asyncio.subprocess.DEVNULL, cwd=self.dir, env=env, start_new_session=True, limit=2**26)
        try: await asyncio.wait_for(self.proc.stdout.readline(), 30)
        except Exception: self.kill(); raise
    def kill(self):
        if self.proc is not None and self.proc.returncode is None:
            try: os.killpg(self.proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError): pass
            try: self.proc._transport.close()
            except Exception: pass
        self.proc = None
    async def rss(self):
        try:
            import psutil
            p = psutil.Process(self.proc.pid)
            return sum(c.memory_info().rss for c in [p, *p.children(recursive=True)])
        except Exception: return 0
    async def run(self, source, snap, limit=LIMIT):
        "The worker's answer for `source` over `snap`; `{'slow': True}` or `{'memory': True}` after the worker was killed, `{'died': True}` if it was gone or answered another request."
        async with self.lock:
            reply = None
            try:
                await self.start()
                self.seq += 1; rid = self.seq
                req = json.dumps({'id': rid, 'source': source, 'snap': snap}) + '\n'
                self.proc.stdin.write(req.encode()); await self.proc.stdin.drain()
                reply = asyncio.ensure_future(self.proc.stdout.readline())
                end = time.monotonic() + limit
                while not reply.done():
                    await asyncio.wait([reply], timeout=0.05)
                    if reply.done(): break
                    if time.monotonic() > end: self.kill(); return {'slow': True}
                    if (r := await self.rss()) > self.cap: self.kill(); return {'memory': True}
                line = reply.result()
                res = json.loads(line) if line else None
                if not isinstance(res, dict) or res.get('id') != rid: self.kill(); return {'died': True}
                self.ticks += 1
                return res
            except asyncio.CancelledError: self.kill(); raise
            except Exception: self.kill(); return {'died': True}
            finally:
                if reply is not None and not reply.done(): reply.cancel()
                if self.closing: self.close()
    def retire(self):
        "Close now, or when the tick that holds the lock is over."
        if self.lock.locked(): self.closing = True
        else: self.close()
    def close(self):
        self.kill()
        if self.dir: shutil.rmtree(self.dir, ignore_errors=True); self.dir = None

WORKERS = {}

def worker_for(key, python):
    "The worker of notebook `key`, made on first use; one on another Python replaces it."
    w = WORKERS.get(key)
    if w is not None and w.python != python: w.retire(); w = None
    if w is None: w = WORKERS[key] = Worker(python)
    return w

def close_all():
    for w in WORKERS.values(): w.close()
    WORKERS.clear()

atexit.register(close_all)
