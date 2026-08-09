"""Pyright, for the things a kernel cannot answer.

The kernel knows what is *loaded*; Pyright knows what is *written*. Hover, inlay hints and
symbol outlines are static questions, and asking a running interpreter would either execute
something or return nothing for code that has not run yet.

`/lsp/rename` is the one that writes. It computes the full preview server-side — every
affected file, before and after — and only applies when the client asks explicitly with
`apply`. That split exists because a workspace rename is the one editor operation that can
silently touch a dozen files, so the browser gets to show them before anything is written.
Each file goes through `fs._check` first, so an edit Pyright proposes outside the open
roots is refused rather than applied, and the whole set is journalled as one operation so
`/history/undo` reverses the rename rather than one file of it.

LSP requests are a subprocess round-trip, so all of them go through `off_loop`.
"""

from __future__ import annotations

from urllib.parse import unquote, urlparse

from ...core.web import fail, off_loop

__all__ = ['CAPS', 'connect']

CAPS = ('lsp', 'fs', 'journal')


def _offsets(source):
    "Character offset of the start of each line, for converting LSP positions to offsets."
    lines = source.splitlines(keepends=True) or ['']
    starts, at = [], 0
    for line in lines:
        starts.append(at)
        at += len(line)
    return lines, starts


def connect(app, ctx):
    rt = app.route

    @rt('/lsp/status')
    def lsp_status():
        lsp = ctx.lsp
        return {'provider': 'pyright', 'available': lsp.available, 'alive': lsp.alive, 'note': lsp.note}

    @rt('/lsp/symbols')
    async def lsp_symbols(req):
        d = await req.json()
        try:
            rows = await off_loop(ctx.lsp.request, 'textDocument/documentSymbol', d.get('path'),
                                  d.get('text', ''), None, 0, None, 8)
            return {'symbols': rows or []}
        except Exception as e: return fail(e)

    @rt('/lsp/hover')
    async def lsp_hover(req):
        d = await req.json()
        try:
            return {'hover': await off_loop(ctx.lsp.request, 'textDocument/hover', d.get('path'),
                                            d.get('text', ''), d.get('line', 0), d.get('character', 0))}
        except Exception as e: return fail(e)

    @rt('/lsp/inlay-hints')
    async def lsp_inlay_hints(req):
        d = await req.json(); text = d.get('text', ''); lines = text.splitlines()
        end = {'line': max(0, len(lines)-1), 'character': len(lines[-1]) if lines else 0}
        try:
            rows = await off_loop(ctx.lsp.request, 'textDocument/inlayHint', d.get('path'), text, None, 0,
                                  {'range': {'start': {'line': 0, 'character': 0}, 'end': end}}, 8)
            return {'hints': rows or []}
        except Exception as e: return fail(e)

    @rt('/lsp/rename')
    async def lsp_rename(req):
        "Preview or atomically apply Pyright's workspace rename edit within open roots."
        d = await req.json()
        try:
            edit = await off_loop(ctx.lsp.request, 'textDocument/rename', d.get('path'), d.get('text', ''),
                                  d.get('line', 0), d.get('character', 0),
                                  {'newName': d.get('newName', '')}, 12)
            changes = (edit or {}).get('changes') or {}
            previews = []
            for uri, edits in changes.items():
                path = unquote(urlparse(uri).path)
                p = ctx.fs._check(path, must_exist=True)
                before = ctx.fs.read(p)
                ls, starts = _offsets(before)

                def offset(pos, ls=ls, starts=starts):
                    row = max(0, min(int(pos.get('line', 0)), len(ls)-1))
                    return starts[row] + min(int(pos.get('character', 0)), len(ls[row].rstrip('\r\n')))

                # Applied last-first so that an earlier edit's offsets stay valid.
                replacements = sorted([(offset(x['range']['start']), offset(x['range']['end']),
                                        x.get('newText', '')) for x in edits], reverse=True)
                after = before
                for start, end, new in replacements: after = after[:start] + new + after[end:]
                previews.append({'path': str(p), 'before': before, 'after': after, 'edits': len(edits)})
            if d.get('apply'):
                operation = []
                for row in previews:
                    ctx.fs.write(row['path'], row['after'])
                    operation.append((row['path'], row['before'], row['after']))
                ctx.journal.record(f"Rename to {d.get('newName','')}", operation, kind='rename-symbol')
            return {'ok': True, 'applied': bool(d.get('apply')), 'files': previews}
        except Exception as e: return fail(e)
