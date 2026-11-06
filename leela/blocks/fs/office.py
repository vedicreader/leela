"Read-only views of Word, PowerPoint and Excel files: safe HTML for the viewer tab, and text for the agent."

from __future__ import annotations
import base64, re, subprocess, sys, zipfile
from fastcore.all import Path
from functools import partial
from fasthtml.common import Details, Div, H2, Img, NotStr, P, Section, Span, Summary, Table, Td, Th, Tr, to_xml as _xml
from ...core.text import clean_html

to_xml = partial(_xml, indent=False)

__all__ = ['OFFICE', 'OFFICE_MAX_BYTES', 'SHEET_ROWS', 'is_office', 'office_html', 'sheet_rows', 'office_text', 'open_in_app']

OFFICE = frozenset({'.docx', '.pptx', '.xlsx', '.xlsm'})
OFFICE_MAX_BYTES, UNZIPPED_MAX, IMAGES_MAX = 64_000_000, 400_000_000, 40_000_000
SHEET_ROWS, ROWS_MAX, TEXT_ROWS, TEXT_CHARS = 200, 2000, 2000, 400_000
_SHOWN = re.compile(r'^image/(png|jpeg|gif|webp)$')
_NO_DATA_IMG, _ALT = re.compile(r'<img\b(?![^>]*\bsrc="data:)[^>]*>', re.I), re.compile(r'\balt="([^"]*)"')

def is_office(p): return Path(p).suffix.lower() in OFFICE

def _opened(p):
    "`p` when it is an office file this view can read, else a ValueError a person can act on."
    p = Path(p)
    if not is_office(p): raise ValueError(f'{p.name} is not a Word, PowerPoint or Excel file')
    if p.stat().st_size > OFFICE_MAX_BYTES: raise ValueError(f'{p.name} is too large to show')
    try:
        with zipfile.ZipFile(p) as z: size = sum(i.file_size for i in z.infolist())
    except (zipfile.BadZipFile, OSError): raise ValueError(f'{p.name} is not a valid {p.suffix[1:]} file') from None
    if size > UNZIPPED_MAX: raise ValueError(f'{p.name} is too large to show')
    return p

def _safe(x):
    "Document markup as cleaned HTML: no script, no handlers, and no image that would make a request."
    h = clean_html(x if isinstance(x, str) else to_xml(x), relative=False)
    return NotStr(_NO_DATA_IMG.sub(lambda m: f'<span class="lee-office-noimg">{(a := _ALT.search(m[0])) and a[1] or "[image not shown]"}</span>', h))

class _Images:
    "Inline images as data URLs, until their total passes `IMAGES_MAX`."
    def __init__(self): self.left = IMAGES_MAX
    def __call__(self, kind, blob, alt=''):
        if not _SHOWN.match(kind or ''): return Span(f'[image not shown: {(kind or "unknown").split("/")[-1]}]', cls='lee-office-noimg')
        if len(blob) > self.left: return Span('[image not shown: too many images]', cls='lee-office-noimg')
        self.left -= len(blob)
        return Img(src=f'data:{kind};base64,{base64.b64encode(blob).decode()}', alt=alt)

def _docx(p):
    import mammoth
    imgs = _Images()
    def img(im):
        with im.open() as f: el = imgs(im.content_type, f.read(), im.alt_text or '')
        return {'src': el.attrs['src'], 'alt': el.attrs.get('alt', '')} if el.tag == 'img' else {'alt': el.children[0]}   # an img with no src becomes its label in `_safe`
    with open(p, 'rb') as f: h = mammoth.convert_to_html(f, convert_image=mammoth.images.img_element(img)).value
    return Div(_safe(h), cls='lee-office-doc')

def _shapes(shapes):
    "Every shape, with the members of groups in place."
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    for s in shapes:
        if s.shape_type == MSO_SHAPE_TYPE.GROUP: yield from _shapes(s.shapes)
        else: yield s

def _shape(s, imgs):
    if getattr(s, 'has_table', False): return Table(*[Tr(*[Td(c.text) for c in r.cells]) for r in s.table.rows])
    try: im = getattr(s, 'image', None)
    except Exception: im = None
    if im is not None: return imgs(im.content_type, im.blob, s.name or '')
    if s.has_text_frame and s.text_frame.text.strip(): return Div(*[P(t.text) for t in s.text_frame.paragraphs if t.text.strip()])

def _slide(i, slide, imgs):
    title = slide.shapes.title
    tid = title.shape_id if title is not None else None
    body = [x for s in _shapes(slide.shapes) if s.shape_id != tid and (x := _shape(s, imgs)) is not None]
    notes = slide.notes_slide.notes_text_frame.text if slide.has_notes_slide and slide.notes_slide.notes_text_frame else ''
    return Section(Div(Span(f'Slide {i}'), cls='lee-office-slide-no'),
                   _safe(H2(title.text)) if title is not None and title.text.strip() else '', _safe(Div(*body)),
                   Details(Summary('Speaker notes'), _safe(Div(*[P(l) for l in notes.splitlines() if l.strip()]))) if notes.strip() else '',
                   cls='lee-office-slide', data_slide=str(i))

def _pptx(p):
    from pptx import Presentation
    imgs = _Images()
    return Div(*[_slide(i, s, imgs) for i, s in enumerate(Presentation(p).slides, 1)], cls='lee-office-deck')

def _book(p, data_only=True):
    from openpyxl import load_workbook
    return load_workbook(p, read_only=True, data_only=data_only)

def _cell(v, f):
    "The value Excel saved, or the formula when the file holds no value for it."
    if v is None and isinstance(f, str) and f.startswith('='): return f
    return '' if v is None else str(v)

def _rows(p, sheet, start, n):
    "`n` rows of sheet number `sheet` from row `start` (0-based) as strings, and whether more follow."
    if start < 0 or n < 1: raise ValueError('rows start at 0')
    vals, forms = _book(p), _book(p, False)
    try:
        if not 0 <= sheet < len(vals.worksheets): raise ValueError(f'{p.name} has no sheet {sheet + 1}')
        it = lambda b: b.worksheets[sheet].iter_rows(min_row=start + 1, max_row=start + n + 1, values_only=True)
        got = [[_cell(v, f) for v, f in zip(r, fr)] for r, fr in zip(it(vals), it(forms))]
        return got[:n], len(got) > n
    finally: vals.close(); forms.close()

def _trs(rows, start): return [Tr(Th(str(start + i + 1), cls='lee-sheet-row'), *[Td(c) for c in r]) for i, r in enumerate(rows)]

def sheet_rows(p, sheet=0, start=0, n=SHEET_ROWS):
    "One window of a sheet's rows as `<tr>` HTML, how many rows it holds, and whether more follow."
    rows, more = _rows(_opened(p), sheet, start, min(n, ROWS_MAX))
    return ''.join(to_xml(r) for r in _trs(rows, start)), len(rows), more

def _sheet(p, i, name, n):
    rows, more = _rows(p, i, 0, n)
    return Section(H2(name, cls='lee-sheet-name'), Table(*_trs(rows, 0), cls='lee-sheet-table') if rows else P('This sheet is empty.', cls='lee-dim'),
                   Div(Span(f'Showing the first {len(rows)} rows.'), cls='lee-dim lee-sheet-more', data_next=str(len(rows))) if more else '',
                   cls='lee-sheet', data_sheet=str(i), hidden=i > 0)

def _xlsx(p, n):
    b = _book(p)
    try: names = list(b.sheetnames)
    finally: b.close()
    return Div(*[_sheet(p, i, name, n) for i, name in enumerate(names)], cls='lee-office-book')

def office_html(p, rows=SHEET_ROWS):
    "The document as escaped HTML for the viewer tab."
    p = _opened(p)
    sfx = p.suffix.lower()
    return to_xml(Div(_docx(p) if sfx == '.docx' else _pptx(p) if sfx == '.pptx' else _xlsx(p, rows), cls='lee-office-view'))

def office_text(p, limit=TEXT_CHARS):
    "The document as Markdown, for the agent and for Copy as text."
    from fossick import html2md
    md = html2md(office_html(p, TEXT_ROWS), ignore_images=True, readability=False).strip()
    return md if len(md) <= limit else md[:limit] + '\n\n[document clipped]'

def open_in_app(p):
    "Open office file `p` in the app the system gives its type; any other file is refused, as `open` runs programs."
    if not is_office(p): raise ValueError(f'{Path(p).name} is not a Word, PowerPoint or Excel file')
    subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(p)], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
