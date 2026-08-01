"""Web research inside the editor: search, read a page as markdown, save it into the project.

fossick does the actual work -- ddgs metasearch, escalating fetchers for pages that
fight back, HTML/PDF to markdown, arxiv and GitHub readers. This module's job is the
part fossick cannot know about: keeping the results *confined*. Anything written to
disk goes through `Sandbox`, so a page pulled off the web lands inside an open folder
or not at all.

Nothing here is async, deliberately. Every call is blocking network I/O, and the two
frontends want it on different threads -- Textual has `@work`, the web app has
`asyncio.to_thread`. One synchronous implementation serves both, and neither has to
unwrap a coroutine that was only ever going to block.

fossick is imported lazily for the same reason kosha is: it pulls in a browser
automation stack, and an editor that opens a file should not pay for that.
"""

from __future__ import annotations
from dataclasses import dataclass
from fastcore.all import Path, L

from . import Dictable, errstr

__all__ = ['Doc', 'Research', 'MAX_DOC_CHARS']

MAX_DOC_CHARS = 200_000   # a fetched page this large is a download, not something to read in a pane


@dataclass
class Doc(Dictable):
    'One fetched or found document. `text` is markdown, and empty for a bare search hit.'
    title: str
    url: str
    text: str = ''
    kind: str = 'hit'      # 'hit' (search result) | 'page' | 'repo' | 'paper'

    @property
    def slug(self):
        "A filename for saving this document, derived from its title."
        s = ''.join(c if (c.isalnum() or c in ' -_') else '' for c in (self.title or 'untitled'))
        return ('-'.join(s.split())[:60] or 'untitled').lower()


class Research:
    "Search the web, read pages as markdown, and save what is worth keeping into the open folders."

    def __init__(self, sandbox):
        self.fs = sandbox
        self.note = ''          # what the last call did, or why it failed -- the UI shows this

    # -- the dependency -------------------------------------------------------
    @staticmethod
    def _fossick():
        "The fossick module. Imported here, not at module scope: it drags in a browser stack."
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
    def search(self, q, n=10, category='text'):
        "Search hits for `q` -- titles and urls, no page bodies. Cheap enough to run from a keystroke."
        q = (q or '').strip()
        if not q:
            self.note = 'empty query'
            return L()
        f = self._fossick()
        hits = self._try(f'{category} search', lambda: list(f.search(q, category=category, max_results=n)))
        if hits is None: return L()
        out = L(Doc(title=(h.get('title') or h.get('href') or '').strip(),
                    url=h.get('href') or h.get('url') or '', kind='hit')
                for h in hits[:n])
        self.note = f'{len(out)} results for {q!r}'
        return out

    def read(self, url, sel=None):
        "One page as markdown. Handles arxiv ids and GitHub blob urls as the special cases they are."
        url = (url or '').strip()
        if not url:
            self.note = 'no url'
            return None
        f = self._fossick()
        if 'github.com' in url and '/blob/' in url:
            md, kind = self._try('read github file', f.read_gh_file, url), 'repo'
        elif 'arxiv.org' in url:
            paper = self._try('read arxiv', f.read_arxiv, url, save_pdf=False)
            md = None if paper is None else (paper.get('md') or paper.get('abstract') or '')
            kind = 'paper'
        else:
            page = self._try('fetch page', f.fetch, url, sel=sel, auto=True)
            md = None if page is None else self._try('convert page', f.to_md, page, sel=sel)
            kind = 'page'
        if not md:
            # `_try` only knows about exceptions. A fetcher that returns nothing without
            # raising would otherwise leave the *success* note standing over a None result.
            if 'failed' not in self.note: self.note = f'no content at {url}'
            return None
        doc = Doc(title=_title(md, url), url=url, text=str(md)[:MAX_DOC_CHARS], kind=kind)
        self.note = f'{len(doc.text)} chars from {url}'
        return doc

    def dig(self, q, n=5, chars=4000):
        """Search, then read the top `n` results into one cited corpus.

        This is the expensive one -- `n` page fetches -- so it is a deliberate action in
        both frontends rather than something that fires while you type.
        """
        q = (q or '').strip()
        if not q:
            self.note = 'empty query'
            return L(), ''
        f = self._fossick()
        r = self._try('research', f.research, q, n=n, chars=chars)
        if r is None: return L(), ''
        docs = L(Doc(title=s.get('title') or s.get('href') or '', url=s.get('href') or '',
                     text=s.get('md') or '', kind='page')
                 for s in (r.get('sources') or []))
        self.note = f'read {len(docs)} sources for {q!r}'
        return docs, r.get('digest') or ''

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
        """A url as a runnable notebook, via fossick's `url2nb` (it handles PDFs and arxiv too).

        `url2nb` writes the file itself, so the path is gated through `Sandbox` *first* --
        the check is what keeps a downloaded paper from landing outside the open folders.
        """
        f = self._fossick()
        p = self.fs._check(ref or f'{Doc(title="", url=url).slug or "page"}.ipynb')
        if p.suffix != '.ipynb': p = p.with_suffix('.ipynb')
        out = self._try('url to notebook', f.url2nb, url, nb_path=str(p))
        if out is None: return None
        self.note = f'saved {p}'
        return self.fs.entry(p)


def _title(md, url):
    "First markdown heading, else the url's last path segment."
    for line in str(md).split('\n', 40)[:40]:
        if line.startswith('#'): return line.lstrip('#').strip()[:120]
    return Path(url.rstrip('/')).name or url
