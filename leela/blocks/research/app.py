"""Web search, reading and citation, without leaving the workspace.

Three depths, deliberately separate rather than one call with a flag. `/search` returns
titles and urls only, so it is fast enough to drive from a prompt box. `/read` fetches one
page as Markdown. `/dig` does both across several sources and writes a cited digest, which
is the expensive one and the only one worth a progress indicator.

`remember` defaults to true on read and dig: a page you bothered to fetch is usually a page
you will want again, and `Research` files it into the memory corpus. Passing `remember=0`
is how the browser reads something without adding to it.

Every backend here is blocking -- network fetch, then markdown extraction, then embedding
-- so all of it goes through `off_loop`.
"""

from __future__ import annotations

from ...core.web import fail, off_loop
from .research import MAX_DOC_CHARS

__all__ = ['CAPS', 'connect']

CAPS = ('research',)


def connect(app, ctx):
    rt = app.route

    @rt('/research/search')
    async def research_search(q: str = '', n: int = 15):
        "Web search: titles and urls only, so it stays fast enough to drive from a prompt box."
        n = min(50, max(1, int(n)))
        docs = await off_loop(ctx.research.search, q, n)
        return {'note': ctx.research.note, 'docs': [d.dict() for d in docs]}

    @rt('/research/read')
    async def research_read(url: str = '', remember: bool = True):
        "One page (or GitHub file, or arxiv paper) as markdown."
        d = await off_loop(ctx.research.read, url, None, remember)
        return {'note': ctx.research.note, 'doc': d.dict() if d else None}

    @rt('/research/dig')
    async def research_dig(q: str = '', n: int = 5, remember: bool = True):
        "Search and read the top results into one cited digest."
        n = min(12, max(1, int(n)))
        docs, digest = await off_loop(ctx.research.dig, q, n, MAX_DOC_CHARS, remember)
        return {'note': ctx.research.note, 'digest': digest, 'docs': [d.dict() for d in docs]}

    @rt('/research/save')
    async def research_save(req):
        "Keep a fetched page: markdown by default, or a runnable notebook with kind='notebook'."
        d = await req.json()
        try:
            if d.get('kind') == 'notebook':
                e = await off_loop(ctx.research.save_notebook, d['url'], d.get('path'))
            else:
                from .research import Doc
                doc = Doc(title=d.get('title') or '', url=d.get('url') or '', text=d.get('text') or '')
                e = await off_loop(ctx.research.save, doc, d.get('path'))
            if e is None: return fail(ctx.research.note)
            return {'ok': True, 'entry': e.dict(), 'note': ctx.research.note}
        except Exception as e: return fail(e)
