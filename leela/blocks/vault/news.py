"""Feeds, and the items they bring in.

Nothing underneath reads a feed: fossick's `news` is a news *search*, and a vault watch is a page,
a query, arXiv, YouTube or a reminder. So RSS and Atom are parsed here with the standard library —
two element shapes do not warrant a dependency — and each item is filed as an ordinary vault
document on the `news` shelf. Everything the vault already does then applies to it.
"""

from __future__ import annotations

import json, os, re, time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

from fastcore.all import AttrDict, L, Path, first

from ... import Dictable, errstr, leela_cfg
from .jobs import every_seconds

__all__ = ['NEWS_SHELF', 'Feed', 'Feeds', 'feeds_path', 'fetch_feed', 'parse_feed', 'feed_title',
           'item_markdown', 'poll_feeds']

NEWS_SHELF = 'news'

_ATOM = '{http://www.w3.org/2005/Atom}'
_TAGS = re.compile(r'<[^>]+>')
_BLOCK = re.compile(r'</?(p|div|br|li|ul|ol|h[1-6]|tr|td|th|blockquote|pre|section)\b[^>]*>', re.I)
_ALT = re.compile(r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]*>', re.I)
_HREF = re.compile(r'href=["\']([^"\']+)["\']', re.I)

def _text(el): return '' if el is None else ' '.join(''.join(el.itertext()).split())

def _plain(s, n=600):
    "A feed summary as text. Only a block boundary is a space — `</b>.` must not become `b .`"
    s = ' '.join(_TAGS.sub('', _BLOCK.sub(' ', str(s or ''))).split())
    return s[:n] + '…' if len(s) > n else s

def _when(raw):
    "A feed date as ISO. RSS uses RFC 822, Atom uses ISO 8601, and both lie sometimes."
    raw = (raw or '').strip()
    if not raw: return ''
    for parse in (parsedate_to_datetime, datetime.fromisoformat):
        try:
            d = parse(raw)
            return (d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d).astimezone(timezone.utc).isoformat()
        except Exception: pass
    return raw

def _rss_items(root):
    for it in root.iter('item'):
        link = _text(it.find('link')) or _text(it.find('guid'))
        yield AttrDict(title=_text(it.find('title')), link=link, author=_text(it.find('author')),
                       published=_when(_text(it.find('pubDate'))),
                       summary=_plain(_text(it.find('description'))))

def _atom_entries(root):
    for e in root.iter(f'{_ATOM}entry'):
        link = first((ln.get('href') for ln in e.findall(f'{_ATOM}link')
                      if ln.get('rel') in (None, 'alternate') and ln.get('href')), default='')
        body = e.find(f'{_ATOM}content')
        if body is None: body = e.find(f'{_ATOM}summary')
        yield AttrDict(title=_text(e.find(f'{_ATOM}title')), link=link, summary=_plain(_text(body)),
                       author=_text(e.find(f'{_ATOM}author/{_ATOM}name')),
                       published=_when(_text(e.find(f'{_ATOM}updated')) or _text(e.find(f'{_ATOM}published'))))

def feed_title(xml):
    "What the feed calls itself."
    try: root = ET.fromstring(str(xml).strip())
    except ET.ParseError: return ''
    for path in ('channel/title', f'{_ATOM}title', 'title'):
        if (el := root.find(path)) is not None and (t := _text(el)): return t
    return ''

def parse_feed(xml):
    "Every item in an RSS or Atom document, in the order the feed gives them."
    try: root = ET.fromstring(str(xml).strip())
    except ET.ParseError: return L()
    rows = L(_rss_items(root)) if root.tag == 'rss' or root.find('channel') is not None else L()
    if not rows: rows = L(_atom_entries(root))
    if not rows: rows = L(_rss_items(root))          # an RSS body without the usual wrapper
    return rows.filter(lambda x: x.title and x.link)

def _get(url, timeout=30):
    "Through fossick, which is leela's web layer everywhere else."
    from fossick import get_page
    r = get_page(url, timeout=timeout)
    body = getattr(r, 'body', None)
    return getattr(r, 'status', 0), (body.decode('utf-8', 'replace') if isinstance(body, bytes)
                                     else str(body or getattr(r, 'text', '') or ''))

def _alternates(html):
    "The feeds a page advertises in `<link rel=alternate type=application/rss+xml>`."
    return [m.group(1) for tag in _ALT.findall(html or '') if (m := _HREF.search(tag))]

def fetch_feed(url, timeout=30):
    """`(url, xml)` for the feed at `url`, or for the one the page there advertises.

    Sites disagree about where a feed lives (`/feed.xml`, `/rss.xml`, `/index.xml`), and somebody
    following a source knows its address, not its feed's. So a page that is not a feed is asked
    what its feed is, which is what the `alternate` link is for.
    """
    status, body = _get(url, timeout)
    if status == 200 and parse_feed(body): return url, body
    for href in _alternates(body):
        alt = urljoin(url, href)
        if alt == url: continue
        st, txt = _get(alt, timeout)
        if st == 200 and parse_feed(txt): return alt, txt
    if status != 200: raise ValueError(f'{url} answered {status}')
    raise ValueError(f'{url} is not an rss or atom feed')

def item_markdown(item, source=''):
    "One item as the document the vault stores: its own heading, then what the feed said."
    meta = ' · '.join(x for x in (source, (item.published or '')[:10], item.author) if x)
    return f"# {item.title}\n\n{meta}\n\n{item.summary or '(the feed gave no summary)'}\n\n[{item.link}]({item.link})\n"

def feeds_path(): return leela_cfg/'feeds.json'

@dataclass
class Feed(Dictable):
    "One followed source."
    url: str
    title: str = ''
    every: str = '1h'
    enabled: bool = True
    added_at: float = field(default_factory=time.time)
    last_run: float = 0.0
    last_status: str = ''
    items: int = 0
    def __post_init__(self):
        self.url = str(self.url).strip()
        if not self.url: raise ValueError('a feed needs an address')
        self.title = str(self.title or '').strip()
    @property
    def id(self): return re.sub(r'[^A-Za-z0-9]+', '', self.url)[-24:] or 'feed'
    @property
    def seconds(self): return every_seconds(self.every)
    @property
    def due(self): return self.enabled and time.time() - self.last_run >= self.seconds
    def dict(self): return {**super().dict(), 'id': self.id, 'due': self.due, 'seconds': self.seconds}

class Feeds:
    "The followed feeds, as a file beside the attached vaults."
    def __init__(self, path=None):
        self.file, self.note = Path(path) if path else feeds_path(), ''
        self.rows = self._load()
    def _load(self):
        try: rows = json.loads(self.file.read_text()).get('feeds') or [] if self.file.is_file() else []
        except Exception as e:
            self.note = f'could not read {self.file.name} ({errstr(e)})'
            return L()
        keep = set(Feed.__dataclass_fields__)
        return L(rows).map(lambda r: self._safe(r, keep)).filter()
    @staticmethod
    def _safe(r, keep):
        try: return Feed(**{k: v for k, v in r.items() if k in keep})
        except Exception: return None
    def save(self):
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.file.parent/f'{self.file.name}.{os.getpid()}.tmp'
            tmp.write_text(json.dumps({'feeds': [asdict(r) for r in self.rows]}, indent=2))
            tmp.replace(self.file)
        except Exception as e: self.note = f'could not save {self.file.name} ({errstr(e)})'
        return self
    def __len__(self): return len(self.rows)
    def __iter__(self): return iter(self.rows)
    def get(self, fid): return first(r for r in self.rows if r.id == fid)
    def dict(self): return {'feeds': [r.dict() for r in self.rows], 'note': self.note}
    def add(self, url, title='', every='1h'):
        "Follow a source. The feed is resolved now, so a page that carries none is refused here."
        url, xml = fetch_feed(url)
        if (already := first(r for r in self.rows if r.url == url)):
            self.note = f'already following {already.title or already.url}'
            return already
        f = Feed(url=url, title=title or feed_title(xml) or url, every=every)
        self.rows.append(f); self.save()
        self.note = f'following {f.title}'
        return f
    def remove(self, fid):
        f = self.get(fid)
        if f is None: raise KeyError(fid)
        self.rows = self.rows.filter(lambda r: r.id != fid); self.save()
        self.note = f'stopped following {f.title or f.url}'
        return f
    def toggle(self, fid, enabled=None):
        f = self.get(fid)
        if f is None: raise KeyError(fid)
        f.enabled = (not f.enabled) if enabled is None else bool(enabled)
        self.save()
        return f
    def mark(self, fid, status, added=0, title=''):
        f = self.get(fid)
        if f is None: return None
        f.last_run, f.last_status, f.items = time.time(), status, added
        if title and not f.title: f.title = title
        self.save()
        return f

def poll_feeds(memory, feeds, force=False, report=None):
    """Read every due feed and file what is new on the news shelf.

    A feed republishes the same items every time, so the link is the identity: an item already
    held is left alone rather than re-embedded, and a feed that carries its whole history costs
    nothing after the first read.
    """
    rows = [f for f in feeds if force or f.due]
    known = {str(d.get('source') or '') for d in memory.all_documents(limit=5000, shelves=[NEWS_SHELF])}
    out = []
    for i, f in enumerate(rows):
        if report: report(progress=0.05 + 0.9 * i / max(1, len(rows)), current=f.title or f.url)
        try:
            url, xml = fetch_feed(f.url)
            title, items = feed_title(xml) or f.title or url, parse_feed(xml)
        except Exception as e:
            feeds.mark(f.id, errstr(e))
            out.append({'feed': f.url, 'status': 'error', 'error': errstr(e)})
            continue
        added = 0
        for it in items:
            if it.link in known: continue
            try:
                memory.file_news(item_markdown(it, title), title=it.title, source=it.link,
                                 meta={'feed': title, 'feed_url': url, 'published': it.published,
                                       'author': it.author})
                known.add(it.link); added += 1
            except Exception: pass
        feeds.mark(f.id, 'ok', added, title)
        out.append({'feed': url, 'title': title, 'seen': len(items), 'added': added, 'status': 'ok'})
    return {'feeds': len(rows), 'added': sum(x.get('added', 0) for x in out), 'results': out}
