"A language server, for the static questions a kernel cannot answer."

from __future__ import annotations

from urllib.parse import unquote, urlparse

from ...core.langs import lang_named
from ...core.web import fail, off_loop

__all__ = ['CAPS', 'connect']

CAPS = ('fs', 'journal', 'lsp_for')

def _offsets(source):
    "Character offset of the start of each line, for converting LSP positions to offsets."
    lines = source.splitlines(keepends=True) or ['']
    starts, at = [], 0
    for line in lines:
        starts.append(at)
        at += len(line)
    return lines, starts

def _edited(before, edits):
    "`before` with one file's LSP edits applied."
    lines, starts = _offsets(before)
    def offset(pos):
        row = max(0, min(int(pos.get('line', 0)), len(lines) - 1))
        return starts[row] + min(int(pos.get('character', 0)), len(lines[row].rstrip('\r\n')))
    spans = sorted(((offset(x['range']['start']), offset(x['range']['end']), x.get('newText', '')) for x in edits),
                   reverse=True)
    after = before
    for start, end, new in spans: after = after[:start] + new + after[end:]
    return after

def connect(app, ctx):
    rt = app.route
    def ask(d, method, *a, **kw):
        "Put one request to the server for this file's language, Python's when Leela knows none."
        from ..fs.fs import lang_for
        name = d.get('lang') or lang_for(d.get('path') or '') or 'python'
        srv = ctx.lsp_for(name if lang_named(name) else 'python')
        return off_loop(srv.request, method, d.get('path'), *a, **kw)
    @rt('/lsp/status')
    def lsp_status(path: str = '', lang: str = ''):
        from ..fs.fs import lang_for
        name = lang or lang_for(path or '') or 'python'
        lsp = ctx.lsp_for(name if lang_named(name) else 'python')
        return {'provider': lsp.server or '', 'lang': lsp.lang, 'available': lsp.available,
                'alive': lsp.alive, 'note': lsp.note}
    @rt('/lsp/symbols')
    async def lsp_symbols(req):
        d = await req.json()
        try:
            rows = await ask(d, 'textDocument/documentSymbol', d.get('text', ''), None, 0, None, 8)
            return {'symbols': rows or []}
        except Exception as e: return fail(e)
    @rt('/lsp/hover')
    async def lsp_hover(req):
        d = await req.json()
        try:
            return {'hover': await ask(d, 'textDocument/hover', d.get('text', ''),
                                       d.get('line', 0), d.get('character', 0))}
        except Exception as e: return fail(e)
    @rt('/lsp/inlay-hints')
    async def lsp_inlay_hints(req):
        d = await req.json(); text = d.get('text', ''); lines = text.splitlines()
        end = {'line': max(0, len(lines)-1), 'character': len(lines[-1]) if lines else 0}
        try:
            rows = await ask(d, 'textDocument/inlayHint', text, None, 0,
                             {'range': {'start': {'line': 0, 'character': 0}, 'end': end}}, 8)
            return {'hints': rows or []}
        except Exception as e: return fail(e)
    @rt('/lsp/rename')
    async def lsp_rename(req):
        "Preview or atomically apply the language server's workspace rename edit within open roots."
        d = await req.json()
        try:
            edit = await ask(d, 'textDocument/rename', d.get('text', ''),
                             d.get('line', 0), d.get('character', 0),
                             {'newName': d.get('newName', '')}, 12)
            changes = (edit or {}).get('changes') or {}
            previews = []
            for uri, edits in changes.items():
                p = ctx.fs._check(unquote(urlparse(uri).path), must_exist=True)
                before = ctx.fs.read(p)
                previews.append({'path': str(p), 'before': before, 'after': _edited(before, edits),
                                 'edits': len(edits)})
            if d.get('apply'):
                for row in previews: ctx.fs.write(row['path'], row['after'])
                ctx.journal.record(f"Rename to {d.get('newName','')}",
                                   [(r['path'], r['before'], r['after']) for r in previews], kind='rename-symbol')
            return {'ok': True, 'applied': bool(d.get('apply')), 'files': previews}
        except Exception as e: return fail(e)
