"""Web research: fossick fetch/extract, Sandbox writes, optional vault remember.

Blocking I/O; the web layer moves calls onto a worker thread.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from fastcore.all import Path, L, first

from ... import Dictable, errstr

__all__ = ['Doc', 'Research', 'MAX_DOC_CHARS']

MAX_DOC_CHARS = 200_000   # retain a whole article while bounding one source in memory/the browser
MAX_RESEARCH_DIGEST_CHARS = 900_000  # stays below the web Markdown renderer's 1 MB boundary

# Extra extraction surfaces for pages whose markup defeats fossick's readability pass, which
# then yields only the lead paragraph. The richest clean candidate wins; see `_page_text`.
_CONTENT_SELECTORS = ('article', 'main', '[role="main"]', '.article-body', '.article-content', '.post-content', '.entry-content')
_BLOCK_SELECTOR = ('article h1, article h2, article h3, article h4, article p, article pre, article blockquote, '
    'article li, article table, main h1, main h2, main h3, main h4, main p, main pre, main blockquote, main li, '
    'main table, [role="main"] h1, [role="main"] h2, [role="main"] h3, [role="main"] p, [role="main"] pre, '
    '[role="main"] blockquote, [role="main"] li, [role="main"] table')


@dataclass
class Doc(Dictable):
    'One fetched or found document. `text` is markdown, and empty for a bare search hit.'
    title: str
    url: str
    text: str = ''
    kind: str = 'hit'      # 'hit' (search result) | 'page' | 'repo' | 'paper'
    sections: list = field(default_factory=list)  # repeated page articles, kept structurally separate
    memory_id: str = ''       # litesearch document id when this source was retained

    @property
    def slug(self):
        "A filename for saving this document, derived from its title."
        s = ''.join(c if (c.isalnum() or c in ' -_') else '' for c in (self.title or 'untitled'))
        return ('-'.join(s.split())[:60] or 'untitled').lower()


class Research:
    "Search the web, read pages as markdown, and save what is worth keeping into the open folders."

    def __init__(self, sandbox, memory=None):
        self.fs, self.memory = sandbox, memory
        self.note = ''          # what the last call did, or why it failed -- the UI shows this

    def _remember(self, doc, query=''):
        if self.memory is None or doc is None: return None
        try:
            saved = self.memory.remember(doc, query=query)
            if saved: doc.memory_id = saved.get('doc_id') or ''
            return saved
        except Exception: return None  # reading remains useful if optional indexing is unavailable

    @staticmethod
    def _fossick():
        "The fossick module, imported here rather than at module scope: it drags in a browser stack."
        import fossick
        return fossick

    def _try(self, what, fn, *a, **kw):
        "Run one fossick call, turning a failure into a note rather than an exception."
        try:
            r = fn(*a, **kw)
            self.note = what
            return r
        except Exception as e:
            self.note = f'{what} failed ({errstr(e)})'
            return None

    # -- reading --------------------------------------------------------------
    def _article_sections(self, f, page):
        "Repeated `<article>` elements as independently rendered documents."
        try: elements = list(page.css('article'))
        except Exception: return []
        out, seen = [], set()
        for element in elements:
            try:
                heading = element.css('h1, h2, h3').first
                title = heading.get_all_text().strip() if heading is not None else ''
                text = str(f.to_md(str(element.get())) or '').strip()
                # A wrapper <article> around several stories keeps the page h1, which is not the
                # first story's title; take the title from the extracted text instead.
                if len(list(element.css('article'))) > 1:
                    title = first(ln.strip().lstrip('#').strip()[:120] for ln in text.splitlines() if ln.strip()) or ''
            except Exception: continue
            key = ' '.join(text.lower().split())   # dedupes a wrapper that converted to one of its cards
            if len(text) < 80 or key in seen: continue
            seen.add(key)
            out.append({'title': title or _title(text, ''), 'text': text[:MAX_DOC_CHARS]})
        return out if len(out) > 1 else []

    def _page_text(self, f, page, sel=None):
        "Best whole-page Markdown candidate. `multi=True` throughout: without it a selector returns only its first match."
        candidates = []
        sections = self._article_sections(f, page) if not sel else []
        def take(label, **kw):
            try: text = str(f.to_md(page, **kw) or '').strip()
            except Exception: return
            if text: candidates.append((label, text))

        if sel: take(f'selector {sel}', sel=sel, multi=True)
        take('readability')
        for selector in _CONTENT_SELECTORS: take(selector, sel=selector, multi=True)
        take('semantic blocks', sel=_BLOCK_SELECTOR, multi=True)
        if not candidates: return '', 'no extraction matched', sections
        # Length, discounted by bullet ratio: a long sidebar or language list is not an article.
        def quality(row):
            lines = [x for x in row[1].splitlines() if x.strip()]
            bullets = sum(x.lstrip().startswith(('* ', '- ')) for x in lines)
            return len(row[1]) * (1 - bullets / max(1, len(lines)))
        label, text = max(candidates, key=quality)
        return text[:MAX_DOC_CHARS], label, sections

    def _read_page(self, f, url, sel=None):
        "Fetch and extract a complete page, retrying a thin static shell with rendered HTML."
        page = self._try('fetch page', f.fetch, url, auto=True)
        if page is None: return '', ''
        text, strategy, sections = self._page_text(f, page, sel)
        # `auto` escalates bot walls, not a 200 whose article JavaScript fills in later.
        if len(text) < 800:
            rendered = self._try('render page', f.fetch, url, heavy=True, network_idle=True)
            if rendered is not None:
                richer, rendered_strategy, rendered_sections = self._page_text(f, rendered, sel)
                if len(richer) > len(text): text, strategy = richer, f'rendered {rendered_strategy}'
                if len(rendered_sections) > len(sections): sections = rendered_sections
        # Last resort for a DOM that is still a shell: DDGS extraction, independent of the DOM.
        if len(text) < 800 and hasattr(f, 'extract'):
            extracted = self._try('extract page', f.extract, url)
            rows = extracted if isinstance(extracted, list) else [extracted]
            parts = []
            for row in rows:
                if isinstance(row, dict): parts.append(str(row.get('content') or row.get('body') or row.get('text') or ''))
                elif row: parts.append(str(row))
            fallback = '\n\n'.join(x.strip() for x in parts if x and x.strip())
            if len(fallback) > len(text): text, strategy = fallback[:MAX_DOC_CHARS], 'independent extraction'
        return text, strategy, sections

    def search(self, q, n=10, category='text'):
        "Search hits for `q` — titles and urls, no page bodies."
        q = (q or '').strip()
        if not q:
            self.note = 'empty query'
            return L()
        f = self._fossick()
        hits = self._try(f'{category} search', lambda: list(f.search(q, category=category, n=n)))
        if hits is None: return L()
        out = L(Doc(title=(h.get('title') or h.get('href') or '').strip(), kind='hit',
            url=h.get('href') or h.get('url') or '') for h in hits[:n])
        self.note = f'{len(out)} results for {q!r}'
        return out

    def read(self, url, sel=None, remember=True):
        "One page as markdown. Handles arxiv ids and GitHub blob urls as the special cases they are."
        url = (url or '').strip()
        if not url:
            self.note = 'no url'
            return None
        f = self._fossick()
        title, strategy, sections = '', '', []
        if 'github.com' in url and '/blob/' in url: md, kind = self._try('read github file', f.read_gh_file, url), 'repo'
        elif 'arxiv.org' in url:
            paper = self._try('read arxiv', f.read_arxiv, url, save_pdf=False)
            # `md`/`abstract` are the pre-`source`/`summary` fossick keys, kept for older installs.
            md = None if paper is None else (paper.get('source') or paper.get('summary')
                or paper.get('md') or paper.get('abstract') or '')
            title = '' if paper is None else str(paper.get('title') or '')
            kind = 'paper'
        elif 'youtube.com/' in url or 'youtu.be/' in url:
            video = self._try('read youtube transcript', f.read_yt, url)
            md = None if video is None else (video.get('source') or video.get('transcript') or '')
            title = '' if video is None else str(video.get('title') or '')
            kind = 'page'
        else:
            # `sel` is not passed to `fetch`, which would narrow `.html` to its first match;
            # `_page_text` applies it with multi=True instead.
            md, strategy, sections = self._read_page(f, url, sel)
            kind = 'page'
        if not md:
            # `_try` sees only exceptions, so a fetcher returning nothing leaves a success note.
            if 'failed' not in self.note: self.note = f'no content at {url}'
            return None
        doc = Doc(title=title or _title(md, url), url=url, text=str(md)[:MAX_DOC_CHARS], kind=kind, sections=sections)
        detail = f' via {strategy}' if kind == 'page' and strategy else ''
        self.note = f'{len(doc.text)} chars from {url}{detail}'
        if remember: self._remember(doc)
        return doc

    def dig(self, q, n=5, chars=MAX_DOC_CHARS, remember=True):
        "Cited corpus via `fossick.research`. `n` page fetches — never on a keystroke."
        q = (q or '').strip()
        if not q:
            self.note = 'empty query'
            return L(), ''
        f = self._fossick()
        # focused=False keeps full pages; `read` still owns the thin-page cascade.
        limit = min(MAX_DOC_CHARS, max(1, int(chars)))
        result = self._try('research', f.research, q, n=n, chars=limit, focused=False, auto=True)
        if result is None: return L(), ''
        docs = L()
        for s in result.get('sources') or []:
            url = s.get('href') or s.get('url') or ''
            text = str(s.get('md') or '')[:limit]
            docs.append(Doc(title=s.get('title') or _title(text, url), url=url, kind='page', text=text))
        digest = str(result.get('digest') or '')[:MAX_RESEARCH_DIGEST_CHARS]
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

    # -- writing --------------------------------------------------------------
    def save(self, doc, ref=None):
        "Write a document into the open folders as markdown. Returns the `Entry` written."
        if doc is None: raise ValueError('nothing to save')
        ref = ref or f'{doc.slug}.md'
        body = f'# {doc.title}\n\n<{doc.url}>\n\n{doc.text}\n'
        e = self.fs.write(ref, body)
        self.note = f'saved {e.path}'
        return e

    def save_notebook(self, url, ref=None):
        "A url as a runnable notebook via fossick's `url2nb`. It writes the file itself, so the path is checked first."
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


def _title(md, url):
    "First markdown heading, else the url's last path segment."
    for line in str(md).split('\n', 40)[:40]:
        if line.startswith('#'): return line.lstrip('#').strip()[:120]
    return Path(url.rstrip('/')).name or url
