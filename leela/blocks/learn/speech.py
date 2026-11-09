import asyncio, json, os, threading
from functools import partial
from fastcore.basics import first
from starlette.responses import JSONResponse, Response, StreamingResponse
from ... import errstr, leela_cfg

__all__ = ['ROWS', 'speech_rows', 'speech_values', 'blocker', 'download', 'make_transcribe', 'connect']

def _row(key, dflt, kind, label, help, **kw): return dict(key=f'speech.{key}', dflt=dflt, kind=kind, lo=kw.get('lo'), hi=kw.get('hi'), hi_key=None, choices=kw.get('choices'), label=label,
                                                          help=help, unit=kw.get('unit'), pct=False, more=kw.get('more', False), group='speech', group_label='Speech')

ROWS = [
    _row('engine', 'mlx', 'choice', 'Engine', 'mlx runs on this Mac, and your audio stays here. openai sends your audio to OpenAI and needs OPENAI_API_KEY in Environment.', choices=['mlx', 'openai']),
    _row('model', '', 'str', 'Model', 'The speech model. Empty uses the default of the engine.', more=True),
    _row('segment', True, 'bool', 'Cut at pauses', 'The text shows after each pause. When this is off, the text comes in fixed blocks of time.'),
    _row('pause', 700, 'int', 'Pause before a cut', 'How long a pause must be before the text of what you said shows.', lo=300, hi=2000, unit='ms', more=True),
    _row('longest', 12, 'int', 'Longest segment', 'The text shows after this time, also when you do not pause.', lo=5, hi=30, unit='s', more=True),
]
TOLD, _lock = set(), threading.Lock()
NO_KEY = 'There is no OpenAI key. Add OPENAI_API_KEY in Settings, Environment, or choose the mlx engine.'
NOTICE = 'Your audio goes to OpenAI, because you chose that engine in Settings. Speak again to go on.'

def speech_rows(): return [dict(r) for r in ROWS]

def speech_values(root=None, cur=None):
    "Abhyasa's `stt.*` rows, valued from the Learn settings `cur` of Leela (else those of `root`): what `use_settings` takes."
    from ..settings.settings import Settings
    cur = Settings(root).effective().get('learn', {}) if cur is None else cur
    return {f'stt.{r["key"].split(".")[1]}': cur.get(r['key'], r['dflt']) for r in ROWS}

def _active(jobs, model): return first(j for j in jobs.all(limit=50, kind='speech_model') if j.active and j.target == model and jobs.alive(j))

def blocker(jobs, v):
    "The sentence that says why speech cannot run now, else ''. It starts the download job of a missing local model, and tells of OpenAI once."
    from abhyasa import models
    engine, model = models.resolve(v['stt.engine'], v['stt.model'])
    if engine == 'openai':
        if not os.getenv('OPENAI_API_KEY'): return NO_KEY
        if 'openai' in TOLD: return ''
        TOLD.add('openai')
        return NOTICE
    if models.cached(model): return ''
    with _lock: _active(jobs, model) or jobs.start('speech_model', model, _cancel=True)
    return f'The speech model {model} is not on this Mac yet. It downloads now: watch the job card, then speak again.'

class Stop(Exception): pass

def download(model, report, stopping):
    "The `speech_model` job: `model` into the Hugging Face cache, with progress; `dict(cancelled=True)` when stopped."
    from huggingface_hub import snapshot_download
    from huggingface_hub.utils import tqdm
    from abhyasa.models import cache_bytes, model_size
    try: total = model_size(model)
    except Exception: total = 0
    class Bar(tqdm):
        def update(self, n=1):
            if stopping(): raise Stop()
            got = cache_bytes(model)
            report(progress=.05 + .9 * min(1, got / total) if total else .1, current=f'{got >> 20} of {total >> 20} MB' if total else f'{got >> 20} MB')
            return super().update(n)
    try: snapshot_download(model, tqdm_class=Bar)
    except Stop: return dict(cancelled=True)
    return dict(model=model)

def make_transcribe(jobs, root=lambda: None):
    "Leela's one speech to text: engine and model from Leela's settings, the key from Leela's Environment, Abhyasa's one resident model."
    def transcribe(audio, hint=''):
        from abhyasa import models
        from abhyasa.learner import use_config
        v = speech_values(root())
        if why := blocker(jobs, v): raise RuntimeError(why)
        engine, model = models.resolve(v['stt.engine'], v['stt.model'])
        try:
            with use_config(leela_cfg/'learn-abhyasa'): return models.transcribe(audio, engine, hint, model)   # no key file of Abhyasa is read
        except ModuleNotFoundError as e: raise RuntimeError(f'Speech on this Mac needs the {e.name} package. Install leela[local], or choose the openai engine.') from e
    return transcribe

def connect(app, ctx):
    "Leela's own dictation routes, on the one `make_transcribe`: for the Dictate action in any text box."
    if ctx is None: return
    ctx.jobs.register('speech_model', lambda job, report: download(job.target, report, partial(ctx.jobs.stopping, job.id)))
    root, held = lambda: ctx.session.project_root, []
    def speech():
        from abhyasa.models import Speech
        if not held: held.append(Speech(make_transcribe(ctx.jobs, root)))
        return held[0]
    run = lambda did: speech().runs.get(did)
    @app.route('/speech/ready', methods=['POST'])
    async def speech_ready():
        try: why = await asyncio.to_thread(blocker, ctx.jobs, speech_values(root()))
        except Exception as e: why = errstr(e)
        return JSONResponse(dict(ok=False, say=why), 409) if why else dict(ok=True)
    @app.route('/speech/start', methods=['POST'])
    async def speech_start(req):
        v = speech_values(root())
        return dict(ok=True, id=speech().start(req.query_params.get('hint', '')), segment=v['stt.segment'], pause=v['stt.pause'], longest=v['stt.longest'])
    @app.route('/speech/seg/{did}', methods=['POST'])
    async def speech_seg(req, did: str):
        if not (d := run(did)): return JSONResponse(dict(error='no such dictation'), 404)
        d.add(int(req.query_params.get('seq', 0)), await req.body())
        return dict(ok=True, pending=d.pending)
    @app.route('/speech/stop/{did}', methods=['POST'])
    async def speech_stop(req, did: str):
        if not (d := run(did)): return JSONResponse(dict(error='no such dictation'), 404)
        d.stop(int(req.query_params.get('n', 0)))
        return dict(ok=True)
    @app.route('/speech/events/{did}', methods=['GET'])
    async def speech_events(did: str):
        if not (d := run(did)): return Response('no such dictation', status_code=404)
        async def gen():
            while True:
                r = await asyncio.to_thread(d.next, 10)
                if r is None: yield ': still listening\n\n'; continue
                yield f'data: {json.dumps(r)}\n\n'
                if r.get('done'): speech().runs.pop(did, None); break
        return StreamingResponse(gen(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
