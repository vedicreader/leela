"POST /learn/cell/run: the code of a Learn step cell, run in the private kernel of the Learn tab. No model sees it."
import asyncio, json, re, tempfile
from pathlib import Path
from ...core.web import NOT_OBJECT, fail, json_obj

__all__ = ['TIMEOUT', 'KEY', 'connect', 'shape']

KEY = 'learn-cell'
TIMEOUT = 5.
CODE_MAX, OUT_MAX, RESULT_MAX, TB_LINES, WATCH_MAX, WATCH_LEN, IMG_MAX, IMGS = 8000, 20_000, 4_000, 8, 12, 200, 1_000_000, 3
ANSI = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')
MARK = '\x00W'
PROBE = "print({mark!r} + __import__('json').dumps({{n: repr(globals()[n])[:{n}] for n in {names!r} if n in globals()}}))"

def clip(s, n:int) -> str:
    s = ANSI.sub('', str(s or ''))
    return s if len(s) <= n else s[:n] + '\n[cut: too long]'

def shape(res) -> dict:
    "The `ExecOutcome` `res` as the cell shows it: capped text, a short error, and at most `IMGS` images."
    out, result, imgs, err = [], '', [], None
    for o in res.outputs or ():
        t, d = o.get('output_type'), o.get('data') or {}
        if t == 'stream': out.append(str(o.get('text') or ''))
        elif t in ('execute_result', 'display_data'):
            if isinstance(p := d.get('image/png'), str) and len(p) <= IMG_MAX and len(imgs) < IMGS: imgs.append(p.strip())
            elif t == 'execute_result' and 'text/plain' in d: result = clip(d['text/plain'], RESULT_MAX)
        elif t == 'error':
            tb = [l for l in ANSI.sub('', '\n'.join(o.get('traceback') or ())).splitlines() if l.strip()][-TB_LINES:]
            err = dict(name=str(o.get('ename') or 'Error'), msg=clip(o.get('evalue'), 400), tb=tb)
    stopped = bool(res.error) and res.error.startswith('timed out')
    if not (err or res.ok or stopped): err = dict(name='Error', msg=clip(res.error, 400), tb=[])
    return dict(ok=bool(res.ok), stdout=clip(''.join(out), OUT_MAX), result=result, images=imgs, error=err, timed_out=stopped)

class Cells:
    "The one private kernel of the Learn tab: the step it runs for, and the folder it works in."
    def __init__(self): self.lock, self.where, self.dir = asyncio.Lock(), None, tempfile.TemporaryDirectory(prefix='leela-learn-cell-')

    async def kernel(self, ws):
        return await ws.pool.get(KEY, cwd=self.dir.name, name='learn', python=ws.user_python(Path(self.dir.name), need=False), inspect=False, lang='python')

    async def watch(self, k, names) -> dict:
        "The `repr` of each of `names` that the kernel has, read by a run that leaves no output and no history."
        if not names: return {}
        r = await k.execute(PROBE.format(mark=MARK, n=WATCH_LEN, names=list(names)), store_history=False, timeout=TIMEOUT)
        text = ''.join(str(o.get('text') or '') for o in r.outputs or () if o.get('output_type') == 'stream')
        try: return json.loads(text.split(MARK, 1)[1].splitlines()[0])
        except (IndexError, ValueError): return {}

    async def run(self, ws, code:str, where, names=(), reset:bool=False) -> dict:
        "Run `code` for the step `where`. A new step, or `reset`, starts the kernel afresh; cells of one step share its variables."
        async with self.lock:
            k = await self.kernel(ws)
            if reset or (self.where is not None and self.where != where): await k.restart()
            self.where = where
            if not code.strip(): return dict(ok=True, stdout='', result='', images=[], error=None, timed_out=False, watch={})
            res = await k.execute(code, timeout=TIMEOUT)
            out = shape(res)
            if out['timed_out']:
                await k.interrupt()
                if not (await k.execute('pass', store_history=False, timeout=3)).ok: await k.restart()
                return dict(out, watch={})
            return dict(out, watch=await self.watch(k, names) if out['ok'] else {})

def connect(app, ctx):
    cells = Cells()
    async def close(): cells.dir.cleanup()
    app.on_event('shutdown')(close)
    @app.route('/learn/cell/run', methods=['POST'])
    async def learn_cell_run(req):
        if (d := await json_obj(req)) is None: return fail(NOT_OBJECT)
        code, wid = d.get('code', ''), (str(d.get('walk') or '')[:80], str(d.get('step') if d.get('step') is not None else '')[:20])
        if not isinstance(code, str): return fail('Give the code as text.')
        if len(code) > CODE_MAX: return fail(f'The code has more than {CODE_MAX} characters.', 413)
        names = [n for n in (d.get('watch') or ()) if isinstance(n, str) and n.isidentifier()][:WATCH_MAX] if isinstance(d.get('watch'), list) else []
        try: out = await cells.run(ctx.session, code, wid, names, bool(d.get('reset')))
        except Exception as e: return fail(e, 500)
        return dict(out, id=str(d.get('id') or '')[:80])
