"The two copies of a presentation: slide markup, cleaned outputs, clipped stage messages and demos without answers."
import base64, binascii, hashlib, html, json, re, struct
from copy import deepcopy
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote
import nh3
from bs4 import BeautifulSoup
from fastcore.ansi import strip_ansi
from fastcore.xtras import fenced
from IPython.core.display import ImageFormat
from rupaka.render import MIME as RUPAKA_MIME
from rupaka.spec import validate
from ...core.text import MD_HIGHLIGHT, _HTML_ATTRS, _HTML_DROP, _HTML_TAGS, _html_attr, clean_html

MOST, MOST_GROUPS, ROOM_LONG = 65536, 49, '<p>Output is too long for the room screen.</p>'
NOT_SHOWN = '<p class="nb-none">This output type is not shown in presentations.</p>'
IMG_MOST, IMG_BYTES, IMG_TOTAL, IMG_SIDE, IMG_PIXELS = 100, 8 << 20, 64 << 20, 16384, 40_000_000
_RASTER = (ImageFormat.png, ImageFormat.jpeg, ImageFormat.gif, ImageFormat.webp)
_ROOM_ATTRS = {k: v - {'id', 'title', 'data-id'} for k, v in _HTML_ATTRS.items()}
_SHOWN = {RUPAKA_MIME, 'text/html', 'text/markdown', 'text/plain', *(f.mime_type for f in _RASTER)}
_VOID = frozenset('area base br col embed hr img input link meta source track wbr'.split())

# copy: importing abhyasa.blocks.talk.app builds the talk app; drop this when abhyasa moves room_spec into abhyasa.talk or core
def room_spec(spec):
    "A copy of a demo spec for the audience window: no gate has its `answer`, so the HTML has no answer before the presenter shows it."
    def strip(x):
        if isinstance(x, list): return [strip(v) for v in x]
        if not isinstance(x, dict): return x
        return {k: strip(v) for k, v in x.items() if not (k == 'answer' and x.get('type') == 'gate')}
    return strip(deepcopy(spec))

def render_md(md):
    "`/markdown/render` with `allow_raw` off: an `{=html}` fence shows as code, then the same mdhtml calls and `clean_html`."
    from mdhtml import md2mdhtml, mdhtml2html
    md = re.sub(r'(?m)^([ \t]*`{3,})\{=html\}([ \t]*)$', r'\1html\2', str(md or ''))
    sym = md2mdhtml(md, math='dollars', implicit_figures=True, bare_autolinks=True, frontmatter=False)
    return clean_html(str(mdhtml2html(sym, refs='ids', auto_ids=False, hl=MD_HIGHLIGHT)))

def _demo(v):
    "The demo spec JSON text or object `v` holds, or None when it does not parse or validate."
    try: s = json.loads(v) if isinstance(v, str) else v
    except ValueError: return None
    try: return s if isinstance(s, dict) and not validate(s) else None
    except Exception: return None

def _fence(spec): return f'<pre><code class="language-rupaka">{html.escape(json.dumps(spec, ensure_ascii=False), quote=False)}</code></pre>'

def demo_fences(s, room=True):
    "`s` with each `pre > code.language-rupaka` that is a valid demo redrawn from its spec (`room_spec` when `room`) and each other one removed; the specs in order."
    soup, specs = BeautifulSoup(s, 'html.parser'), []
    for code in soup.select('pre > code.language-rupaka'):
        if code.decomposed or (pre := code.parent).decomposed: continue
        if (spec := _demo(code.get_text())) is None: pre.decompose(); continue
        specs.append(spec := room_spec(spec) if room else spec)
        pre.replace_with(BeautifulSoup(_fence(spec), 'html.parser'))
    return str(soup), specs

def _webp(b):
    "`(width, height)` of WebP bytes: IPython 9.16 unpacks a lossy size from 6 bytes, so it fails on every `VP8 ` file."
    if (k := b[12:16]) == b'VP8 ': return tuple(x & 0x3fff for x in struct.unpack('<HH', b[26:30]))
    if k == b'VP8X': return 1 + int.from_bytes(b[24:27], 'little'), 1 + int.from_bytes(b[27:30], 'little')
    return ImageFormat.webp.shape(b)

def put_img(b, images, want=None):
    "Keep raster bytes `b` in `images` under their SHA-256, checked by content and within the limits; the hash, or None when refused."
    if images is None or not b or len(b) > IMG_BYTES: return None
    f = ImageFormat.webp if b[:4] == b'RIFF' and b[8:12] == b'WEBP' else ImageFormat.from_data(b)   # IPython looks for WEBP at byte 0
    if f not in _RASTER or (want and f.mime_type != want): return None
    try: w, h = _webp(b) if f is ImageFormat.webp else f.shape(b)
    except Exception: return None
    if not (0 < w <= IMG_SIDE and 0 < h <= IMG_SIDE and w*h <= IMG_PIXELS): return None
    if (sha := hashlib.sha256(b).hexdigest()) in images: return sha
    if len(images) >= IMG_MOST or sum(len(x) for _, x in images.values()) + len(b) > IMG_TOTAL: return None
    images[sha] = (f.mime_type, b)
    return sha

def _local(src, base, fs):
    "The bytes of the workspace file `src` names, resolved as `resolveMarkdownImages` does; None for a URL or a file outside every root."
    if fs is None or not src or re.match(r'^([A-Za-z][A-Za-z0-9+.-]*:|//)', src): return None
    p = unquote(re.split(r'[?#]', src, maxsplit=1)[0])
    if not p.startswith('/') and not base: return None
    try:
        f = fs._check(p if p.startswith('/') else str(Path(base)/p), must_exist=True)
        return f.read_bytes() if f.is_file() and f.stat().st_size <= IMG_BYTES else None
    except Exception: return None

def _img_src(v, base, key, images, fs, att=None):
    "The store URL for image source `v`: a raster `data:` URL, a workspace file or `attachment:NAME` of the cell's `att`; None for anything else."
    if v.startswith('attachment:'):
        a = att.get(v[11:]) if isinstance(att, dict) else None
        if not (isinstance(a, dict) and (t := next(iter(a), None))): return None
        v = f'data:{t};base64,{_text(a[t])}'
    if m := re.match(r'data:(image/[a-z]+);base64,(.*)$', re.sub(r'\s+', '', v), re.I | re.S):
        if len(m[2]) > IMG_BYTES * 4 // 3 + 4: return None
        try: b = base64.b64decode(m[2], validate=True)
        except (binascii.Error, ValueError): return None
        sha = put_img(b, images, m[1].lower().replace('/jpg', '/jpeg'))
    else: sha = put_img(_local(v, base, fs), images)
    return sha and f'/present/img/{sha}?k={key}'

def room_html(s, base, key, images, fs=None, room=True, att=None):
    "`clean_html` of `s`, demos redrawn by `demo_fences`, then no comments, ids or titles, links to the web only, and each image from the store."
    s, specs = demo_fences(clean_html(s), room)
    def attr(tag, a, v):
        if tag == 'img' and a == 'src': return _img_src(v, base, key, images, fs, att)
        if a == 'href': return v if re.match(r'(https?://|mailto:|#)', v, re.I) else None
        return _html_attr(tag, a, v)
    return nh3.clean(s, tags=_HTML_TAGS, clean_content_tags=_HTML_DROP, attributes=_ROOM_ATTRS, attribute_filter=attr, strip_comments=True,
                     url_schemes={'http', 'https', 'mailto', 'data', 'attachment'}, link_rel='noopener noreferrer', url_relative='pass_through',
                     tag_attribute_values={'input': {'type': {'checkbox'}}}, set_tag_attribute_values={'input': {'disabled': 'disabled'}}), specs

def slide_html(md, base, key, images, fs=None, room=True, att=None):
    "Markdown `md` as slide markup by `render_md` and `room_html`, and its demo specs; `att` is the cell's attachments."
    return room_html(render_md(md), base, key, images, fs, room, att)

def _text(v): return ''.join(v) if isinstance(v, list) else str(v or '')
def _pre(t): return f'<pre>{html.escape(strip_ansi(_text(t)), quote=False)}</pre>'

def _one(o, base, key, images, fs, room):
    "`(html, specs)` of output `o`: its first kind that gives something, as the IDE ranks them; never script, widget, SVG or Plotly."
    if o.get('output_type') == 'stream': return _pre(o.get('text')), []
    d, meta = o.get('data') or {}, o.get('metadata') or {}
    if not _SHOWN & set(d): return NOT_SHOWN, []
    if RUPAKA_MIME in d:   # the demo, never the HTML page `rupaka.show` sends beside it
        return room_html(_fence(s), base, key, images, fs, room) if (s := _demo(d[RUPAKA_MIME])) else ('', [])
    for f in _RASTER:
        if f.mime_type not in d: continue
        try: sha = put_img(base64.b64decode(_text(d[f.mime_type]), validate=False), images, f.mime_type)
        except (binascii.Error, ValueError): sha = None
        if not sha: continue
        m = meta.get(f.mime_type) or {}
        wh = ''.join(f' {k}="{m[k]}"' for k in ('width', 'height') if isinstance(m.get(k), int) and not isinstance(m.get(k), bool))
        return f'<img src="/present/img/{sha}?k={key}"{wh}>', []
    if 'text/html' in d: return room_html(_text(d['text/html']), base, key, images, fs, room)
    if 'text/markdown' in d: return slide_html(_text(d['text/markdown']), base, key, images, fs, room)
    return (_pre(d['text/plain']), []) if 'text/plain' in d else ('', [])

def _outs(outputs, key, images, fs=None, base='', room=True):
    "`(html, error, specs)` of a cell's `outputs`."
    hs, err, specs = [], None, []
    for o in outputs or []:
        if o.get('output_type') == 'error':
            err = dict(ename=str(o.get('ename', '')), evalue=strip_ansi(str(o.get('evalue', ''))), traceback=[strip_ansi(str(x)) for x in o.get('traceback') or []])
            continue
        h, s = _one(o, base, key, images, fs, room)
        hs.append(h); specs += s
    return ''.join(hs), err, specs

def clean_out(outputs, key, images, fs=None, base='', room=True):
    "`(html, error)` of a cell's `outputs`: text, raster images and demos only, the error apart with no ANSI codes, or None."
    return _outs(outputs, key, images, fs, base, room)[:2]

def error_html(err):
    "The error `clean_out` gives as escaped text: its traceback, or `ename: evalue` when it has none."
    return _pre('\n'.join(err.get('traceback') or [f"{err.get('ename', '')}: {err.get('evalue', '')}"]))

def _units(s): return len(s.encode('utf-16-le', 'surrogatepass')) // 2
def _cost(s): return _units(json.dumps(s, ensure_ascii=False)) - 2
def _size(m): return _units(json.dumps(m, ensure_ascii=False, separators=(',', ':')))

class _Clip(HTMLParser):
    "The markup of a feed cut to `room` JSON units, the closing tags included."
    def __init__(self, room): super().__init__(convert_charrefs=True); self.room, self.out, self.open, self.used, self.shut, self.full = room, [], [], 0, 0, False
    def _add(self, s, more=0):
        if self.used + _cost(s) + self.shut + more > self.room: return False
        self.out.append(s); self.used += _cost(s); return True
    def handle_starttag(self, tag, a):
        if self.full: return
        if tag in _VOID: self.full = not self._add(self.get_starttag_text())
        elif self._add(self.get_starttag_text(), len(tag) + 3): self.open.append(tag); self.shut += len(tag) + 3
        else: self.full = True
    def handle_startendtag(self, tag, a):
        if not self.full: self.full = not self._add(self.get_starttag_text())
    def handle_endtag(self, tag):
        if self.full or tag not in self.open: return
        while self.open:
            t = self.open.pop(); self.shut -= len(t) + 3; self.out.append(f'</{t}>'); self.used += len(t) + 3
            if t == tag: break
    def handle_data(self, d):
        if self.full or self._add(html.escape(d, quote=False)): return
        lo, hi = 0, len(d)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.used + _cost(html.escape(d[:mid], quote=False)) + self.shut <= self.room: lo = mid
            else: hi = mid - 1
        if lo: self._add(html.escape(d[:lo], quote=False))
        self.full = True
    def text(self): return ''.join(self.out) + ''.join(f'</{t}>' for t in reversed(self.open))

def clip_msg(msg, most=MOST):
    "`msg` with its `html` cut at a tag or text edge so the JSON of the sent message, `v` included, is at most `most` UTF-16 units, as `JSON.stringify` counts; ValueError when even the warning cannot fit."
    h = msg['html'].encode('utf-16', 'surrogatepass').decode('utf-16', 'replace')   # JSON.stringify writes a lone surrogate as 6 units
    m = msg if h == msg['html'] else {**msg, 'html': h}
    if _size({'v': 1, **m}) <= most: return m
    room = most - _size({'v': 1, **m, 'html': ''}) - _cost(ROOM_LONG)
    if room < 0: raise ValueError('This message is too large for the room screen, even with no output.')
    c = _Clip(room); c.feed(h); c.close()
    return {**m, 'html': c.text() + ROOM_LONG}

def _src(c): return _text(c.get('source'))

def slide_title(cells, items):
    "The title of a slide by the `presentTitle` rule: its first markdown heading, else the first line of its first cell."
    for it in items:
        c = cells[it['i']]
        if c.get('cell_type') == 'markdown' and (m := re.search(r'^ {0,3}#{1,6}\s+(.+?)[\s#]*$', _src(c), re.M)): return m[1]
    return _src(cells[items[0]['i']]).strip().split('\n')[0][:80] if items else ''

def _check_line(line, n):
    "ValueError unless each item and note names a cell, and no cell is both."
    ok = lambda i: isinstance(i, int) and not isinstance(i, bool) and 0 <= i < n
    items, notes = [it.get('i') for s in line for it in s.get('items') or []], [i for s in line for i in s.get('notes') or []]
    if not all(map(ok, items + notes)): raise ValueError('The slide line names a cell that is not in the notebook.')
    if set(items) & set(notes): raise ValueError('A cell is both on a slide and in the notes.')

def _block(c, it, base, key, images, fs, room):
    "One cell of a slide."
    b, kind = dict(cell=str(c.get('id', '')), frag=it.get('frag', -1), kind=c.get('cell_type')), c.get('cell_type')
    if kind == 'markdown':
        b['html'], b['demo'] = slide_html(_src(c), base, key, images, fs, room, c.get('attachments'))
        return b
    if kind != 'code': return {**b, 'html': _pre(_src(c)), 'demo': []}
    b['html'] = room_html(render_md(fenced(_src(c), 'python')), base, key, images, fs, room)[0]
    b['out'], err, b['demo'] = _outs(c.get('outputs'), key, images, fs, base, room)
    if not room: b['error'] = err
    return b

def _notes(cells, notes, base, key):
    "The presenter's notes: no image, so nothing in them enters the store the room reads."
    return ''.join(slide_html(_src(c), base, key, None, None, False)[0] if c.get('cell_type') == 'markdown' else _pre(_src(c)) for c in map(cells.__getitem__, notes))

def decks(line, cells, base, key, title, look, fs=None):
    "`(presenter, room, images)` of the slide `line`: the room copy has no notes, no next title, no error, no gate answer and no cell off the slides."
    _check_line(line, len(cells))
    images, copies = {}, []
    for room in (False, True):
        slides = []
        for n, s in enumerate(line):
            d = dict(id=f's{n + 1}', groups=min(int(s.get('groups') or 0), MOST_GROUPS),
                     blocks=[_block(cells[it['i']], it, base, key, images, fs, room) for it in s.get('items') or []])
            if not room: d.update(notes=_notes(cells, s.get('notes') or [], base, key), next=slide_title(cells, line[n + 1].get('items') or []) if n + 1 < len(line) else '')
            slides.append(d)
        copies.append(dict(title=title, look=look, slides=slides))
    return *copies, images
