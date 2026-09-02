"Web research: fossick fetch/extract, Sandbox writes, optional vault remember."

from __future__ import annotations
from dataclasses import dataclass, field
from fastcore.all import L

from shalya.host import md_title, read_page

from ... import Dictable, errstr

__all__ = ['Doc', 'Research', 'MAX_DOC_CHARS']

MAX_DOC_CHARS = 200_000
MAX_RESEARCH_DIGEST_CHARS = 900_000

@dataclass
class Doc(Dictable):
    "One fetched or found document. `text` is markdown, and empty for a bare search hit."
    title: str
    url: str
    text: str = ''
    kind: str = 'hit'
    sections: list = field(default_factory=list)
    memory_id: str = ''
    @property
    def slug(self):
        "A filename for saving this document, derived from its title."
        s = ''.join(c if (c.isalnum() or c in ' -_') else '' for c in (self.title or 'untitled'))
        return ('-'.join(s.split())[:60] or 'untitled').lower()

class Research:
    "Search the web, read pages as markdown, and save what is worth keeping into the open folders."
    def __init__(self, sandbox, memory=None):
        self.fs, self.memory = sandbox, memory
        self.note = ''
    def _remember(self, doc, query=''):
        if self.memory is None or doc is None: return None
        try:
            saved = self.memory.remember(doc, query=query)
            if saved: doc.memory_id = saved.get('doc_id') or ''
            return saved
        except Exception: return None
    @staticmethod
    def _fossick():
        "The fossick module, imported here rather than at module scope: it drags in a browser stack."
        import fossick
        return fossick
    def _say(self, msg): self.note = msg
    def _try(self, what, fn, *a, **kw):
        "Run one fossick call, turning a failure into a note rather than an exception."
        try:
            r = fn(*a, **kw)
            self.note = what
            return r
        except Exception as e:
            self.note = f'{what} failed ({errstr(e)})'
            return None
    def search(self, q, n=10, category='text'):
        "Search hits for `q`: titles and urls, no page bodies."
        q = (q or '').strip()
        if not q:
            self.note = 'empty query'
            return L()
        f = self._fossick()
        hits = self._try(f'{category} search', f.search, q, category=category, n=n)
        if hits is None: return L()
        out = L(hits)[:n].map(_hit)
        self.note = f'{len(out)} results for {q!r}'
        return out
    def read(self, url, sel=None, remember=True):
        "One page as markdown. The readers, the extraction and the escalation are shalya's."
        url = (url or '').strip()
        if not url:
            self.note = 'no url'
            return None
        got = self._try('read page', read_page, self._fossick(), url, sel=sel, note=self._say,
                        mx=MAX_DOC_CHARS)
        if got is None:
            if 'failed' not in self.note: self.note = f'no content at {url}'
            return None
        doc = Doc(title=got.title, url=got.url, text=got.text, kind=got.kind, sections=got.sections)
        detail = f' via {got.strategy}' if got.kind == 'page' and got.strategy else ''
        self.note = f'{len(doc.text)} chars from {url}{detail}'
        if remember: self._remember(doc)
        return doc
    def dig(self, q, n=5, chars=MAX_DOC_CHARS, remember=True):
        "Cited corpus via `fossick.research`. `n` page fetches, so never on a keystroke."
        q = (q or '').strip()
        if not q:
            self.note = 'empty query'
            return L(), ''
        f = self._fossick()
        limit = min(MAX_DOC_CHARS, max(1, int(chars)))
        result = self._try('research', f.research, q, n=n, chars=limit, focused=False, auto=True)
        if not result: return L(), ''
        docs = L(result.get('sources')).map(_source_doc, chars=limit)
        digest = str(result.get('digest') or '')
        if len(digest) > MAX_RESEARCH_DIGEST_CHARS:
            digest = digest[:MAX_RESEARCH_DIGEST_CHARS] + '\n\n*[brief clipped; open a source for its full text]*'
        dropped = result.get('dropped') or []
        self.note = f'read {len(docs)} complete sources for {q!r}'
        if dropped: self.note += f' · {len(dropped)} unread'
        if remember and self.memory is not None and docs:
            try:
                saved = self.memory.remember_research(q, docs, digest)
                by_url = {row.get('source'): row.get('doc_id') for row in saved}
                for doc in docs: doc.memory_id = by_url.get(doc.url) or ''
            except Exception: pass
        return docs, digest
    def save(self, doc, ref=None):
        "Write a document into the open folders as markdown. Returns the `Entry` written."
        if doc is None: raise ValueError('nothing to save')
        ref = ref or f'{doc.slug}.md'
        body = f'# {doc.title}\n\n<{doc.url}>\n\n{doc.text}\n'
        e = self.fs.write(ref, body)
        self.note = f'saved {e.path}'
        return e
    def save_notebook(self, url, ref=None):
        "A url as a runnable notebook via fossick's `url2nb`. It writes the file, so the path is checked first."
        f = self._fossick()
        p = self.fs._check(ref or f'{_url_slug(url)}.ipynb')
        if p.suffix != '.ipynb': p = p.with_suffix('.ipynb')
        out = self._try('url to notebook', f.url2nb, url, nb_path=str(p))
        if out is None: return None
        self.note = f'saved {p}'
        return self.fs.entry(p)

def _url_slug(url):
    "A stable useful filename from a URL when no fetched title is available."
    from urllib.parse import urlparse
    parsed = urlparse(str(url or ''))
    raw = '-'.join(x for x in (parsed.netloc.removeprefix('www.'), parsed.path.strip('/')) if x)
    slug = ''.join(c if c.isalnum() or c in '-_ ' else '-' for c in raw)
    return ('-'.join(slug.split()).strip('-')[:80] or 'page').lower()

def _url(row): return row.get('href') or row.get('url') or ''

def _hit(row):
    "One search result as a bodyless `Doc`."
    return Doc(title=(row.get('title') or _url(row)).strip(), url=_url(row), kind='hit')

def _source_doc(row, chars=MAX_DOC_CHARS):
    "One `fossick.research` source as a `Doc`, clipped to `chars`."
    text = str(row.get('md') or '')[:chars]
    return Doc(title=row.get('title') or md_title(text, _url(row)), url=_url(row), kind='page', text=text)
