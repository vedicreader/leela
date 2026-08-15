"Generated video: a job that outlives the turn that started it, and the artifact it leaves behind."

from __future__ import annotations
import json, os, time, uuid
from fastcore.all import Path
from ... import errstr, leela_cfg
from ...agent.tools import MAX_TOOL_CHARS, clip, err, save_media

__all__ = ['VIDEO_MODELS', 'DFLT_VIDEO', 'VideoJobs', 'video_available', 'video_caps', 'video_tools']

#: Veo is absent from fastllm's model table, so what it can do is kept here by hand.
VIDEO_MODELS = {
    'veo-3.0-generate-001': {'provider': 'gemini', 'inp': ('text', 'image'), 'out': ('video',),
                             'seconds': (4, 8), 'note': 'Google Veo 3, 8s at most'},
}
DFLT_VIDEO = 'veo-3.0-generate-001'
GEMINI_API = 'https://generativelanguage.googleapis.com/v1beta'
MAX_JOBS = 200

def video_caps(model=DFLT_VIDEO):
    "What a video model can do, from the hand-maintained table rather than from fastllm."
    return VIDEO_MODELS.get(model)

def _key(): return os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY') or ''

def video_available(): return bool(_key())

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

def _start(prompt, model, **params):
    "Ask for a video; returns the long-running operation to poll."
    import httpx
    r = httpx.post(f'{GEMINI_API}/models/{model}:predictLongRunning', timeout=60,
                   headers={'x-goog-api-key': _key()},
                   json={'instances': [{'prompt': prompt}], 'parameters': params})
    r.raise_for_status()
    return r.json().get('name') or ''

def _poll(op):
    "One look at a long-running operation, as `(done, uri, error)`."
    import httpx
    r = httpx.get(f'{GEMINI_API}/{op}', timeout=60, headers={'x-goog-api-key': _key()})
    r.raise_for_status()
    d = r.json()
    if not d.get('done'): return False, '', ''
    if (e := d.get('error')): return True, '', str(e.get('message') or e)
    samples = ((d.get('response') or {}).get('generateVideoResponse') or {}).get('generatedSamples') or []
    uri = ((samples[0] if samples else {}).get('video') or {}).get('uri') or ''
    return True, uri, '' if uri else 'the job finished without a video'

def _fetch(uri):
    import httpx
    r = httpx.get(uri, timeout=300, headers={'x-goog-api-key': _key()}, follow_redirects=True)
    r.raise_for_status()
    return r.content

def _line(r):
    "One job as the model reads it."
    return ' · '.join(str(x) for x in (r['id'], r.get('state'), r.get('model'),
                                       r.get('path') or r.get('error') or '') if x)

def video_tools(host, mx=MAX_TOOL_CHARS, session='', jobs=None, model=DFLT_VIDEO):
    "Video generation, as a job the agent starts and comes back to."
    jobs = jobs if jobs is not None else VideoJobs()
    session = session or str(leela_cfg)

    def generate_video(prompt: str, seconds: int = 8) -> str:
        """Start generating a video from a description. Returns a job id to check with `video_status`.

        Generation takes minutes, so this returns immediately. Tell the user the job started,
        then call `video_status` to collect the file.
        """
        if not video_available(): return err('video generation is unavailable', 'GEMINI_API_KEY is not set')
        lo, hi = video_caps(model)['seconds']
        seconds = max(lo, min(int(seconds or hi), hi))
        try: op = _start(prompt, model, durationSeconds=seconds)
        except Exception as e: return err('could not start the video job', e)
        if not op: return err('could not start the video job', 'the provider named no operation')
        r = jobs.add(model=model, prompt=prompt, op=op, seconds=seconds)
        return f"video job {r['id']} started on {model}; check it with video_status"

    def video_status(job_id: str = '') -> str:
        "Where a video job has got to, and the path to the file once it has finished."
        r = jobs.get(job_id)
        if r is None: return err('no such video job', job_id or 'there are none yet')
        if r['state'] != 'running': return _line(r)
        try: done, uri, e = _poll(r['op'])
        except Exception as ex: return f"{_line(r)} · could not be checked ({errstr(ex)})"
        if not done: return f"{_line(r)} · still generating"
        if e: return _line(jobs.update(r['id'], state='failed', error=e))
        try: p = save_media({'mime': 'video/mp4', 'data': _fetch(uri)}, session, 'video')
        except Exception as ex: return _line(jobs.update(r['id'], state='failed', error=errstr(ex)))
        return _line(jobs.update(r['id'], state='done', path=str(p), mime='video/mp4'))

    def video_jobs() -> str:
        "Every video job started here, newest last."
        rows = jobs.all()
        return clip('\n'.join(_line(r) for r in rows), mx) if rows else 'no video jobs yet'

    return [generate_video, video_status, video_jobs]
