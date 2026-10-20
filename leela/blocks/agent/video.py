"Generated video: a job that outlives the turn that started it, and the artifact it leaves behind."

from __future__ import annotations
import json, time, uuid
from fastcore.all import Path
from ... import errstr, leela_cfg
from shalya.core import MAX_TOOL_CHARS, clip, err, one_line as _1, summary
from shalya.tools import save_media

__all__ = ['VIDEO_SECONDS', 'VideoJobs', 'video_setup', 'video_tools']

#: The clip lengths each API takes; fastllm says whether a model makes video, not for how long.
VIDEO_SECONDS = {'gemini': (4, 6, 8), 'openai': (4, 8, 12)}
MAX_JOBS = 200

def video_setup(why):
    "What to tell someone whose `video` job cannot run, and how to give it a model."
    from ramabana.setup import config_path
    return (f'video generation is not set up: {why}. Name a video model under [jobs] video in {config_path()}, '
            'such as video = "gemini/veo-3.0-generate-001" with GEMINI_API_KEY set, or add a hosted video model with + model and name it there')

class VideoJobs:
    "Video jobs on disk, so one survives the turn, the session, and the process that started it."
    def __init__(self, path=None): self.path = Path(path or leela_cfg/'video-jobs.json')
    def all(self):
        try: rows = json.loads(self.path.read_text())
        except Exception: return []
        return rows if isinstance(rows, list) else []
    def _write(self, rows):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(rows[-MAX_JOBS:], indent=2)+'\n')
    def add(self, **row):
        row = {'id': uuid.uuid4().hex[:8], 'state': 'running', 'at': time.time(), **row}
        self._write(self.all()+[row])
        return row
    def get(self, id):
        "One job by id or unambiguous prefix, else the newest when `id` is empty."
        rows = self.all()
        if not id: return rows[-1] if rows else None
        found = [r for r in rows if r['id'] == id] or [r for r in rows if r['id'].startswith(id)]
        return found[0] if len(found) == 1 else None
    def update(self, id, **kw):
        rows = self.all()
        for r in rows:
            if r['id'] == id: r.update(kw)
        self._write(rows)
        return self.get(id)
    def unshown(self):
        "Finished artifacts not yet drawn, as `{'mime','data'}`, marked drawn as they are taken."
        out = []
        for r in self.all():
            if r.get('state') != 'done' or r.get('shown') or not r.get('path'): continue
            p = Path(r['path'])
            if p.exists(): out.append({'mime': r.get('mime') or 'video/mp4', 'data': p.read_bytes()})
            self.update(r['id'], shown=True)
        return out

def _hdrs(r): return {'x-goog-api-key': r['api_key']} if r['api'] == 'gemini' else {'Authorization': f"Bearer {r['api_key']}"}

def _start(r, prompt, seconds):
    "Ask route `r` for a video; returns the id of the job to poll."
    import httpx
    if r['api'] == 'gemini':
        res = httpx.post(f"{r['base_url']}/models/{r['model']}:predictLongRunning", timeout=60, headers=_hdrs(r),
                         json={'instances': [{'prompt': prompt}], 'parameters': {'durationSeconds': seconds}})
    else: res = httpx.post(f"{r['base_url']}/videos", timeout=60, headers=_hdrs(r),
                           files={'model': (None, r['model']), 'prompt': (None, prompt), 'seconds': (None, str(seconds))})
    res.raise_for_status()
    return res.json().get('name' if r['api'] == 'gemini' else 'id') or ''

def _poll(r, op):
    "One look at a job, as `(done, uri, error)`."
    import httpx
    res = httpx.get(f"{r['base_url']}/{op}" if r['api'] == 'gemini' else f"{r['base_url']}/videos/{op}", timeout=60, headers=_hdrs(r))
    res.raise_for_status()
    d = res.json()
    if r['api'] != 'gemini':
        if (st := d.get('status')) in ('queued', 'in_progress'): return False, '', ''
        if st == 'completed': return True, f"{r['base_url']}/videos/{op}/content", ''
        e = d.get('error') or {}
        return True, '', str(e.get('message') or e or f'the job ended {st}')
    if not d.get('done'): return False, '', ''
    if (e := d.get('error')): return True, '', str(e.get('message') or e)
    samples = ((d.get('response') or {}).get('generateVideoResponse') or {}).get('generatedSamples') or []
    uri = ((samples[0] if samples else {}).get('video') or {}).get('uri') or ''
    return True, uri, '' if uri else 'the job finished without a video'

def _fetch(r, uri):
    "The video's bytes. The key goes to the route's own host and no further, not even down a redirect."
    import httpx
    from urllib.parse import urlparse
    own = urlparse(uri).hostname == urlparse(r['base_url']).hostname
    res = httpx.get(uri, timeout=300, headers=_hdrs(r) if own else {})
    if res.is_redirect: res = httpx.get(str(httpx.URL(uri).join(res.headers['location'])), timeout=300, follow_redirects=True)
    res.raise_for_status()
    return res.content

def _line(r):
    "One job as the model reads it."
    return ' · '.join(str(x) for x in (r['id'], r.get('state'), r.get('model'),
                                       r.get('path') or r.get('error') or '') if x)

def _route_of(r, route):
    "The route a stored job polls with, or why it cannot be checked; a job from before routing is Gemini's."
    api, name = r.get('api') or 'gemini', r.get('model') or ''
    rt = route(name if r.get('api') or '/' in name else f'gemini/{name}')
    if isinstance(rt, str): return rt
    return rt if rt['api'] == api else f"{name} now goes to the {rt['api']} API, not the {api} one it started on"

def video_tools(host, mx=MAX_TOOL_CHARS, session='', jobs=None, route=None):
    "Video generation on the `video` job, as a job the agent starts and comes back to."
    from ...agent.core import video_route
    jobs, route = jobs if jobs is not None else VideoJobs(), route or video_route
    session = session or str(leela_cfg)

    @summary(lambda a: f'Generate video {_1(a.get("prompt"))}')
    def generate_video(prompt: str, seconds: int = 8) -> str:
        """Start generating a video from a description. Returns a job id.
        Generation takes minutes and this returns at once. Tell the user the job started, then collect the file with `video_status`.
        """
        if isinstance(r := route(), str): return err(video_setup(r))
        ok = VIDEO_SECONDS[r['api']]
        seconds = min(ok, key=lambda n: abs(n - int(seconds or ok[-1])))
        try: op = _start(r, prompt, seconds)
        except Exception as e: return err('could not start the video job', e)
        if not op: return err('could not start the video job', 'the provider named no job')
        j = jobs.add(model=r['name'], api=r['api'], prompt=prompt, op=op, seconds=seconds)
        return f"video job {j['id']} started on {r['name']}; check it with video_status"

    @summary(lambda a: f'Video job {a.get("job_id") or "(latest)"}')
    def video_status(job_id: str = '') -> str:
        "A video job's state, and the path to the file once it has finished."
        r = jobs.get(job_id)
        if r is None: return err('no such video job', job_id or 'there are none yet')
        if r['state'] != 'running': return _line(r)
        if isinstance(rt := _route_of(r, route), str): return f"{_line(r)} · could not be checked ({rt})"
        try: done, uri, e = _poll(rt, r['op'])
        except Exception as ex: return f"{_line(r)} · could not be checked ({errstr(ex)})"
        if not done: return f"{_line(r)} · still generating"
        if e: return _line(jobs.update(r['id'], state='failed', error=e))
        try: p = save_media({'mime': 'video/mp4', 'data': _fetch(rt, uri)}, session, 'video')
        except Exception as ex: return _line(jobs.update(r['id'], state='failed', error=errstr(ex)))
        return _line(jobs.update(r['id'], state='done', path=str(p), mime='video/mp4'))

    @summary(lambda a: 'Video jobs')
    def video_jobs() -> str:
        "Every video job started here, newest last."
        rows = jobs.all()
        return clip('\n'.join(_line(r) for r in rows), mx) if rows else 'no video jobs yet'

    return [generate_video, video_status, video_jobs]
