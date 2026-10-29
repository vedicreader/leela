"The one presentation the server holds in memory: its key, both copies, images and place, and the routes behind the key."
import asyncio, hashlib, re, secrets, time
from importlib.resources import files
from pathlib import Path
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route
from ...core.web import NOT_OBJECT, asset, asset_dir, fail, json_obj, off_loop
from .show import MOST_GROUPS, decks

__all__ = ['Presentation', 'Drop', 'check_start', 'connect']

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
SHUT = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}
PAGE = SHUT | {'Content-Security-Policy': CSP, 'Referrer-Policy': 'no-referrer'}
LONG = {'Cache-Control': 'public, max-age=31536000, immutable', 'X-Content-Type-Options': 'nosniff'}
MOST_CELLS, MOST_SRC, MOST_OUT, MOST_SLIDES, MOST_BODY, EVENTS_MOST = 2000, 1_000_000, 4_000_000, 9999, 32 << 20, 64
KINDS = ('markdown', 'code', 'raw', 'prompt')
ENDED, BAD_KEY, NEWER = 'This presentation has ended.', 'This presentation link is not valid.', 'A newer presentation started.'
NOTHING, NOT_NB, OUTSIDE = 'There is nothing to present in this notebook.', 'Only a notebook can be presented.', 'The notebook is outside the open folders.'
NOT_IN, TWICE = 'The slide line names a cell that is not in the notebook.', 'A cell is in the slide line more than once.'

def _no(err, code=400):
    "`fail` that no cache keeps and no browser sniffs."
    r = fail(err, code); r.headers.update(SHUT); return r

def _int(v): return isinstance(v, int) and not isinstance(v, bool)

def _chars(x):
    "The characters of text in a JSON value."
    if isinstance(x, str): return len(x)
    if isinstance(x, dict): return sum(map(_chars, x.values())) + sum(map(_chars, x.keys()))
    return sum(map(_chars, x)) if isinstance(x, list) else 0

class Drop(asyncio.Queue):
    "A queue that keeps the newest `maxsize` items: a slow page loses the oldest events, and the server keeps its memory."
    def put_nowait(self, x):
        if self.full(): self.get_nowait()
        super().put_nowait(x)

class Presentation:
    "The live presentation, if any, as `cur`: `key`, `id`, `path`, `title`, `presenter`, `room`, `images`, `at`, `groups`, `live` and `started`. Only the event loop changes it."
    def __init__(self, subs): self.cur, self.n, self.subs = None, 0, subs
    @property
    def id(self): return self.cur and self.cur['id']
    def push(self, event, data):
        for q in list(self.subs): q.put_nowait((event, data))
    def check(self, k):
        "None for the live key, else the refusal: 410 with nothing live, 403 for any other key."
        if self.cur is None: return _no(ENDED, 410)
        if not isinstance(k, str) or not k: return _no(BAD_KEY, 403)
        if not secrets.compare_digest(k.encode('utf-8', 'surrogatepass'), self.cur['key'].encode()): return _no(BAD_KEY, 403)
    def begin(self, cur):
        "Hold `cur` in one step, and announce the one it replaces."
        old, self.cur = self.cur, cur
        if old: self.push('presentation-ended', dict(id=old['id'], reason='replaced'))
    def end(self):
        "Drop the live presentation, and make every build still running discard itself."
        old, self.cur, self.n = self.cur, None, self.n + 1
        if old: self.push('presentation-ended', dict(id=old['id'], reason='ended'))

def _path(path, fs):
    "The notebook `path` resolved inside the open folders, or the reason it is refused; it need not be on disk."
    if not isinstance(path, str) or not path.lower().endswith('.ipynb'): return NOT_NB
    if '..' in Path(path).parts: return OUTSIDE
    try: p = fs._check(path)
    except Exception: return OUTSIDE
    return p if p.suffix.lower() == '.ipynb' else NOT_NB

def _cells(cells):
    "The reason `cells` is refused, or None."
    if not isinstance(cells, list) or not all(isinstance(c, dict) for c in cells): return 'The cells are not a list of cells.'
    if len(cells) > MOST_CELLS: return f'A presentation can have at most {MOST_CELLS:,} cells.'
    ids = [c.get('id') for c in cells]
    if not all(isinstance(i, str) and i for i in ids) or len(set(ids)) < len(ids): return 'Each cell needs its own text id.'
    for c in cells:
        src, outs = c.get('source', ''), c.get('outputs', [])
        if c.get('cell_type') not in KINDS: return 'A cell type is not markdown, code, raw or prompt.'
        if not isinstance(src, str): return 'A cell source is not text.'
        if len(src) > MOST_SRC: return f'A cell has more than {MOST_SRC:,} characters of source.'
        if not isinstance(outs, list) or not all(isinstance(o, dict) for o in outs): return 'The outputs of a cell are not a list of outputs.'
        if _chars(outs) > MOST_OUT: return f'A cell has more than {MOST_OUT:,} characters of output.'

def _line(line, n):
    "`(groups of each slide, None)`, or `(None, reason)` when the slide `line` over `n` cells is refused."
    if not isinstance(line, list) or not all(isinstance(s, dict) for s in line): return None, 'The slide line is not a list of slides.'
    if len(line) > MOST_SLIDES: return None, f'A presentation can have at most {MOST_SLIDES:,} slides.'
    seen, groups = set(), []
    for s in line:
        items, notes, g = s.get('items'), s.get('notes', []), s.get('groups', 0)
        if not isinstance(items, list) or not isinstance(notes, list) or not all(isinstance(x, dict) for x in items): return None, 'The slide line is not a list of slides.'
        if not items: return None, NOTHING
        if not _int(g) or not 0 <= g <= MOST_GROUPS: return None, f'A slide can have at most {MOST_GROUPS} fragment groups.'
        fr = [x.get('frag') for x in items]
        if not all(_int(f) and -1 <= f < g for f in fr) or fr != sorted(fr) or g != max(fr) + 1: return None, 'The fragment groups of a slide are out of order.'
        idx = [x.get('i') for x in items] + notes
        if not all(_int(i) and 0 <= i < n for i in idx): return None, NOT_IN
        if len(set(idx)) < len(idx) or seen & set(idx): return None, TWICE
        seen |= set(idx); groups.append(g)
    return (groups, None) if groups else (None, NOTHING)

def check_start(d, fs):
    "The start request `d` checked and resolved, or the reason it is refused."
    if isinstance(p := _path(d.get('path'), fs), str): return p
    if why := _cells(cells := d.get('cells')): return why
    groups, why = _line(line := d.get('line'), len(cells))
    if why: return why
    st = d.get('start')
    if not (isinstance(st, dict) and _int(sl := st.get('slide')) and 0 <= sl < len(line) and _int(sp := st.get('step')) and 0 <= sp <= groups[sl]):
        return 'The start place is not in the presentation.'
    return dict(path=str(p), base=str(p.parent), title=str(d.get('title') or p.name)[:200], cells=cells, line=line, groups=groups, slide=sl, step=sp)

def _build(s, key, fs, root):
    "`decks` of the checked start `s`, with the saved theme and the editor font, built into new dicts."
    from ..settings.settings import THEME_DEFAULT, Settings, saved_theme
    try: mono = (Settings(root).effective().get('editor') or {}).get('fontFamily')
    except Exception: mono = ''
    look = dict(theme=saved_theme(root) or THEME_DEFAULT, mono=str(mono or ''))
    return decks(s['line'], s['cells'], s['base'], key, s['title'], look, fs)

async def _body(req):
    "`(object, None)` for a JSON object body within `MOST_BODY`, else `(None, refusal)`."
    if req.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json': return None, _no(NOT_OBJECT)
    if (n := req.headers.get('content-length', '')).isdigit() and int(n) > MOST_BODY or len(await req.body()) > MOST_BODY:
        return None, _no('The request is larger than 32 MB.')
    return (d, None) if (d := await json_obj(req)) is not None else (None, _no(NOT_OBJECT))

def _page(ver):
    "The audience page, each asset URL carrying its version."
    s = (asset_dir('static')/'present-audience.html').read_text()
    s = re.sub(r'"/leestatic/([\w.-]+)"', lambda m: f'"{asset(m[1])}"', s)
    return s.replace('"/present/stage.js"', f'"/present/stage.js?v={ver}"')

def connect(app, ctx, subs):
    "Add the presentation routes to `app`, announcing on `subs`; the `Presentation` is `app.state.presentation`."
    rt, fs, ws = app.route, ctx.fs, ctx.session
    pres = app.state.presentation = Presentation(subs)
    # abhyasa's file, read through its package: `abhyasa.core` imports abhyasa's web UI, so `files('abhyasa')` opens it without that import
    stage = (files('abhyasa')/'core'/'stage.js').read_bytes()
    ver = hashlib.sha256(stage).hexdigest()[:16]
    async def stage_js(req): return Response(stage, media_type='text/javascript', headers=LONG)
    # first in the table: FastHTML's `/{fname:path}.{ext:static}` route answers every `.js` path it reaches
    app.router.routes.insert(0, Route('/present/stage.js', stage_js, methods=['GET']))
    @rt('/present/start', methods=['POST'])
    async def present_start(req):
        "Start a presentation from the live cells the page posts. The one unkeyed mutation: it makes the key."
        d, no = await _body(req)
        if no: return no
        if isinstance(s := check_start(d, fs), str): return _no(s)
        pres.n += 1; n, key, pid = pres.n, secrets.token_hex(16), secrets.token_hex(8)
        try: p, r, imgs = await off_loop(_build, s, key, fs, ws.project_root)
        except ValueError as e: return _no(str(e))
        except Exception as e: return _no(e, 500)
        if n != pres.n: return _no(NEWER, 409)
        at = dict(slide=f"s{s['slide'] + 1}", step=s['step'], blank=False, size=10)
        pres.begin(dict(key=key, id=pid, path=s['path'], title=s['title'], presenter=p, room=r, images=imgs, at=at, groups=s['groups'],
                        live=dict(outs={}, demo={}, answers=[]), started=time.time()))
        return JSONResponse(dict(ok=True, key=key, id=pid, presenter=p, at=at, audience=f'/present/audience?k={key}'), headers=SHUT)
    @rt('/present/audience', methods=['GET'])
    async def present_audience(req):
        "The audience window: a page alone that draws the room copy."
        return pres.check(req.query_params.get('k')) or HTMLResponse(_page(ver), headers=PAGE)
    @rt('/present/deck', methods=['GET'])
    async def present_deck(req):
        "The room copy: no notes, no answers, no paths."
        return pres.check(req.query_params.get('k')) or JSONResponse(pres.cur['room'], headers=PAGE)
    @rt('/present/img/{h}', methods=['GET'])
    async def present_img(req):
        "One image of the live presentation, by the key first and then by its SHA-256."
        if no := pres.check(req.query_params.get('k')): return no
        h = req.path_params.get('h', '')
        if not re.fullmatch(r'[0-9a-f]{64}', h) or h not in pres.cur['images']: return _no('No such image.', 404)
        mime, b = pres.cur['images'][h]
        return Response(b, media_type=mime, headers=SHUT)
    @rt('/present/at', methods=['POST'])
    async def present_at(req):
        "Move the place: the slide, the step, blank and the text size in tenths."
        d, no = await _body(req)
        if no: return no
        if no := pres.check(d.get('k')): return no
        c, slide, step, blank, size = pres.cur, d.get('slide'), d.get('step'), d.get('blank'), d.get('size')
        m = re.fullmatch(r's([1-9]\d{0,3})', slide) if isinstance(slide, str) else None
        if not m or int(m[1]) > len(c['groups']): return _no('There is no such slide in this presentation.')
        if not _int(step) or not 0 <= step <= c['groups'][int(m[1]) - 1]: return _no('The step is not on this slide.')
        if not isinstance(blank, bool): return _no('Blank must be true or false.')
        if not _int(size) or not 5 <= size <= 25: return _no('The text size must be a whole number from 5 to 25.')
        c['at'] = dict(slide=slide, step=step, blank=blank, size=size)
        return JSONResponse(dict(ok=True, at=c['at']), headers=SHUT)
    @rt('/present/end', methods=['POST'])
    async def present_end(req):
        "End the presentation, and tell every page."
        d, no = await _body(req)
        if no: return no
        if no := pres.check(d.get('k')): return no
        pres.end()
        return JSONResponse(dict(ok=True), headers=SHUT)
    return pres
