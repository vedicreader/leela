"Text comparison: diffs, fuzzy ranking, and markdown block structure."

from __future__ import annotations
import re
import nh3
from dataclasses import dataclass
from difflib import SequenceMatcher, get_close_matches
from fastcore.all import L
from fastcore.xtras import str_diff
from .. import Dictable
from fastcore.basics import first

try:
    from rapidfuzz.fuzz import ratio as _rf_ratio
    def _ratio(a, b): return _rf_ratio(a, b) / 100.0
except ImportError:                                  # a broken wheel still ranks, just slower
    def _ratio(a, b): return SequenceMatcher(None, a, b).ratio()

__all__ = ['MD_HIGHLIGHT', 'md_html', 'DiffRow', 'HL_MAX', 'path_lang', 'hl_lines', 'udiff', 'diff_rows', 'diff_stat', 'diff_label', 'closest',
           'did_you_mean', 'fuzzy_rank', 'md_blocks', 'md_block_diff', 'md_change_kinds', 'clean_html']

@dataclass
class DiffRow(Dictable):
    "One painted line of a unified diff. `html` is its code coloured, or `''`."
    kind: str
    text: str
    line: int = 0
    html: str = ''

#: Lines past which a diff is not coloured: a lockfile's diff would hold the response for no reader.
HL_MAX = 20_000

def path_lang(path, raw=False):
    "fastpylight's language for diffs of `path`, or None. A notebook's cells read as Python; `raw` is its JSON."
    if not path: return None
    try: from ramabana.hl import diff_lang
    except ImportError: return None
    p = str(path)
    return 'json' if raw and p.partition('#')[0].lower().endswith('.ipynb') else diff_lang(p)

def hl_lines(d, lang):
    "Per line of unified diff `d`, its code as HTML or None, from `ramabana.hl.diff_html`. None when it cannot be coloured."
    if not d or not lang or d.count('\n') > HL_MAX: return None
    try:
        from ramabana.hl import diff_html
        return diff_html(d, lang)
    except Exception: return None

def udiff(a, b, names=None, n=3):
    "Unified diff of `a` and `b`, `''` when they match. `names` is an optional `(old, new)` pair."
    return str_diff(a or '', b or '', n=n, names=names)

_HUNK = re.compile(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@')

def diff_rows(d, lang=None):
    "A unified diff as rows a frontend can paint, each carrying its line number in the new text, and its code coloured when `lang` is given."
    out, n, hl = L(), 0, hl_lines(d, lang) or []
    for i, line in enumerate((d or '').split('\n')):
        if not line and not out: continue
        h = (hl[i] if i < len(hl) else None) or ''
        if line.startswith('@@'):
            m = _HUNK.match(line)
            n = int(m.group(1)) if m else 0
            out.append(DiffRow('hunk', line))
        elif line.startswith(('---', '+++')) and not h: out.append(DiffRow('head', line))
        elif line.startswith('+'): out.append(DiffRow('add', line[1:], n, h)); n += 1
        elif line.startswith('-'): out.append(DiffRow('del', line[1:], 0, h))
        else:
            out.append(DiffRow('ctx', line[1:] if line.startswith(' ') else line, n, h)); n += 1
    return out

def diff_stat(a, b):
    "`(added, removed)` line counts between `a` and `b`. `n=0` because context lines are not news."
    rs = diff_rows(udiff(a, b, n=0))
    return sum(r.kind == 'add' for r in rs), sum(r.kind == 'del' for r in rs)

def diff_label(a, b):
    "A short `+3 −1` summary of `a` -> `b`, or `''` when they are identical."
    add, rem = diff_stat(a, b)
    return ' '.join(p for p in (f'+{add}' if add else '', f'−{rem}' if rem else '') if p)

def closest(word, cands, n=3, cutoff=0.6):
    "The `n` candidates most like `word`, best first."
    return L(get_close_matches(str(word or ''), [str(c) for c in (cands or ())], n=n, cutoff=cutoff))

_NAMEERR = re.compile(r"name '([^']+)' is not defined")

def did_you_mean(err, names):
    "`err` with a suggestion appended, when it is a `NameError` and `names` holds something close."
    if not err or not (m := _NAMEERR.search(err)): return err
    hits = closest(m.group(1), names)
    return err if not hits else f"{err}  ·  did you mean {' or '.join(repr(h) for h in hits)}?"

def _subseq(q, s):
    "Is `q` a subsequence of `s`? The fuzzy-finder membership test: same characters, same order."
    it = iter(s)
    return all(c in it for c in q)

def _fuzzy_score(q, s):
    "How well the lowercased query `q` matches candidate `s`."
    low = s.lower()
    base = low.rsplit('/', 1)[-1]
    score = max(_ratio(q, base), _ratio(q, low) * .5)
    if q in base: score += 1.
    if base.startswith(q): score += .5
    return score

def fuzzy_rank(q, items, key=str, limit=None):
    "`items` ranked by how well `q` matches, best first; a non-match is dropped."
    q = (q or '').strip().lower()
    items = L(items)
    if not q: return items if limit is None else items[:limit]
    cands = [(str(key(it)), it) for it in items]
    scored = L((_fuzzy_score(q, s), len(s), it) for s, it in cands if _subseq(q, s.lower()))
    ranked = scored.sorted(key=lambda t: (-t[0], t[1])).itemgot(2)
    return ranked if limit is None else ranked[:limit]


_MD_TAGS ={'paragraph': ('p',), 'code_block': ('pre',), 'list': ('ul', 'ol'), 'table': ('table',),
            'block_quote': ('blockquote',), 'thematic_break': ('hr',), 'figure': ('figure',),
            'html_block': (), 'math_block': (), 'template': ()}

_MD_SILENT = frozenset({'link_ref', 'footnote_def'})

_MD_OPTS = dict(math='dollars', implicit_figures=True)

_HTML_TAGS = set('a abbr b blockquote br caption cite code col colgroup dd del details div dl dt em figcaption figure h1 h2 h3 h4 h5 h6 hr i img input ins kbd li mark ol p pre q s samp section small span strong sub summary sup table tbody td tfoot th thead tr u ul var'.split())
_HTML_DROP = set('script style iframe frame object embed video audio form button meta base link noscript template svg math select textarea'.split())
_HTML_ATTRS = {'*': set('class id title lang dir role data-id'.split()), 'a': {'href'}, 'img': set('src alt title width height'.split()),
               'td': set('colspan rowspan scope align'.split()), 'th': set('colspan rowspan scope align'.split()), 'table': {'style'}, 'col': {'span', 'style'},
               'ol': {'start', 'type'}, 'li': {'value'}, 'details': {'open'}, 'input': {'checked', 'disabled'}}
_CLASS_PREFIX, _CLASS_NAMES = ('language-', 'hl-', 'footnote-'), {'footnotes', 'task-list', 'xref', 'math', 'inline', 'display'}
_ROLES = {'doc-noteref', 'doc-backlink', 'doc-endnotes'}
_ID_OK = re.compile(r'^[A-Za-z][\w:.-]{0,80}$')
_IMG_DATA = re.compile(r'^data:image/(png|jpeg|gif|webp|avif);base64,')
_LEN = r'(?:0|auto|\d+(?:\.\d+)?(?:px|%|em|rem|ch|ex|in|cm|mm|pt|pc|vw|vh))'
#: mdhtml's table and column widths: a length, or the `calc` it writes for an `fr` column
_WIDTH = re.compile(rf'width:(?:{_LEN}|calc\(\(100%(?: - {_LEN})+\) \* \d+(?:\.\d+)?\))', re.ASCII)

def _html_attr(tag, attr, val):
    "nh3's per-attribute verdict: the value to keep, or None. Class, id and role are policy, so raw HTML cannot borrow the UI's."
    if attr == 'class': return ' '.join(t for t in val.split() if t.startswith(_CLASS_PREFIX) or t in _CLASS_NAMES) or None
    if attr == 'id': return val if _ID_OK.match(val) else None
    if attr == 'role': return val if val in _ROLES else None
    if attr == 'style': return val if all(_WIDTH.fullmatch(d) or (tag == 'table' and d == 'table-layout:fixed') for d in val.split(';')) else None
    if attr in ('href', 'src'):
        u = re.sub(r'[\x00-\x20]+', '', val).lower()
        if u.startswith('data:'): return val if tag == 'img' and attr == 'src' and _IMG_DATA.match(val) else None
        # a notebook cell's own image, which `mdAttached` swaps for its data URL; a browser fetches nothing for the scheme
        if u.startswith('attachment:'): return val if tag == 'img' and attr == 'src' else None
    return val

def clean_html(html, relative=True):
    "`html` reduced to what Markdown can mean: no script, frames, media, forms, handlers or styles beyond mdhtml's table and column widths, and only safe link schemes. `relative=False` drops relative URLs and attachments, so stored text makes no request to Leela."
    return nh3.clean(html, tags=_HTML_TAGS, clean_content_tags=_HTML_DROP, attributes=_HTML_ATTRS, attribute_filter=_html_attr, strip_comments=False,
                     url_schemes={'http', 'https', 'mailto', 'data'} | ({'attachment'} if relative else set()), link_rel='noopener noreferrer', url_relative='pass_through' if relative else 'deny',
                     tag_attribute_values={'input': {'type': {'checkbox'}}}, set_tag_attribute_values={'input': {'disabled': 'disabled'}})

def _md_highlight():
    "`spans` when mdhtml can highlight, else off."
    try: import fastpylight; return 'spans'
    except ImportError: return None

MD_HIGHLIGHT = _md_highlight()

def md_html(text):
    "Safe HTML for stored Markdown `text`: dollar maths as `.math`, highlighted code, and only what `clean_html` keeps."
    from mdhtml import md2mdhtml, mdhtml2html
    md = md2mdhtml(str(text or ''), math='dollars', implicit_figures=True, bare_autolinks=True, frontmatter=False)
    return clean_html(str(mdhtml2html(md, refs='ids', auto_ids=False, hl=MD_HIGHLIGHT)), relative=False)

def _tags(b):
    "The tags a block may render as; `('h2',)` for a level-2 heading, `()` when unknowable."
    if b.get('type') == 'heading':
        level = int(b.get('level') or 1)
        return (f'h{min(max(level, 1), 6)}',)
    return _MD_TAGS.get(str(b.get('type') or ''), ())

def _block_row(b, lines):
    "One mdhtml block as the record this module returns."
    kind = str(b.get('type') or '')
    start, end = int(b.get('start') or 0), int(b.get('end') or 0)
    row = {'type': kind, 'from': start + 1, 'to': max(start + 1, end),
           'source': '\n'.join(lines[start:end]), 'tags': list(_tags(b)),
           'renders': kind not in _MD_SILENT}
    if kind == 'code_block': row |= {'lang': str(b.get('lang') or ''), 'code': str(b.get('text') or '')}
    return row

def md_blocks(text):
    "Every top-level block of `text`: 1-based inclusive source lines, expected tag, and code."
    text = str(text or '')
    try:
        from mdhtml import blocks
        found = blocks(text, **_MD_OPTS)
    except Exception: return []
    lines = text.split('\n')
    return [_block_row(b, lines) for b in found]

def _change_kind(kinds):
    "One block's status from the kinds of the ranges touching it; None when none do."
    if not kinds: return None
    if kinds == {'added'}: return 'added'
    if kinds == {'deleted'}: return 'removed'
    return 'modified'

def md_change_kinds(blocks, ranges):
    "Mark each block of `blocks` with the kind of the changed line ranges it contains."
    return [_change_kind({str(r.get('kind') or 'modified') for r in ranges or ()
                          if int(r.get('from') or 0) <= b['to'] and int(r.get('to') or 0) >= b['from']})
            for b in blocks]

def _line_stat(left, right):
    "Added and removed line counts between two texts, the way `git diff --stat` counts them."
    a, b = str(left or '').split('\n'), str(right or '').split('\n')
    ops = [o for o in SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if o[0] != 'equal']
    return sum(j2 - j1 for _, _, _, j1, j2 in ops), sum(i2 - i1 for _, i1, i2, _, _ in ops)

def _removed(b): return b | {'status': 'removed', 'old_from': b['from'], 'old_to': b['to']}

def _paired(new, old):
    "One block reported as the edited form of the block it replaced."
    row = new | {'status': 'modified', 'old': old['source'], 'old_from': old['from'], 'old_to': old['to']}
    if new['type'] == 'code_block': row |= {'old_code': old.get('code', '')}
    return row

def md_block_diff(left, right):
    "Two Markdown documents paired block against block, in the new document's order."
    old, new = md_blocks(left), md_blocks(right)
    sm = SequenceMatcher(None, [b['source'] for b in old], [b['source'] for b in new], autojunk=False)
    rows = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal': rows += [b | {'status': 'equal'} for b in new[j1:j2]]
        elif tag == 'insert': rows += [b | {'status': 'added'} for b in new[j1:j2]]
        elif tag == 'delete': rows += [_removed(b) for b in old[i1:i2]]
        else:
            olds = list(old[i1:i2])
            for nb in new[j1:j2]:
                k = first(x for x, ob in enumerate(olds) if ob['type'] == nb['type'])
                if k is None: rows.append(nb | {'status': 'added'}); continue
                rows += [_removed(b) for b in olds[:k]]
                rows.append(_paired(nb, olds[k]))
                olds = olds[k + 1:]
            rows += [_removed(b) for b in olds]
    added, removed = _line_stat(left, right)
    return {'blocks': rows, 'added': added, 'removed': removed,
            'changed': any(r['status'] != 'equal' for r in rows)}
