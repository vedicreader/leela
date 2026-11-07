"A language server, for the static questions a kernel cannot answer."

from __future__ import annotations

import re
from urllib.parse import unquote, urlparse

from ...core.langs import lang_named
from ...core.web import fail, off_loop

__all__ = ['CAPS', 'connect']

CAPS = ('fs', 'journal', 'lsp_for')

#: LSP ends a line only at `\r\n`, `\r` or `\n`; `splitlines` also splits at form feeds and other separators.
_LINE = re.compile(r'[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+$')

def _lines(text): return _LINE.findall(text) or ['']

def _units(s): return len(s.encode('utf-16-le')) // 2

def _col(line, units):
    "The code point index of `units` UTF-16 code units into `line`, which is how LSP counts characters."
    n = 0
    for i, ch in enumerate(line):
        if n >= units: return i
        n += 2 if ord(ch) > 0xFFFF else 1
    return len(line)

def _offsets(source):
    "Each line, and the code point offset where it starts, for converting LSP positions to offsets."
    lines, starts, at = _lines(source), [], 0
    for line in lines:
        starts.append(at)
        at += len(line)
    return lines, starts

def _edited(before, edits):
    "`before` with one file's LSP edits applied."
    lines, starts = _offsets(before)
    def offset(pos):
        row = max(0, min(int(pos.get('line', 0)), len(lines) - 1))
        return starts[row] + _col(lines[row].rstrip('\r\n'), int(pos.get('character', 0)))
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
        # the settings panel asking is not use: it must not keep an idle server alive
        lsp = ctx.lsp_for(name if lang_named(name) else 'python', touch=False)
        return {'provider': lsp.server or '', 'lang': lsp.lang, 'available': lsp.available,
                'alive': lsp.alive, 'note': lsp.note}
    @rt('/lsp/symbols')
    async def lsp_symbols(req):
        d = await req.json()
        try:
            rows = await ask(d, 'textDocument/documentSymbol', d.get('text', ''), None, 0, None)
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
        d = await req.json(); text = d.get('text', ''); lines = _lines(text)
        end = {'line': len(lines) - 1, 'character': _units(lines[-1].rstrip('\r\n'))}
        try:
            rows = await ask(d, 'textDocument/inlayHint', text, None, 0,
                             {'range': {'start': {'line': 0, 'character': 0}, 'end': end}})
            return {'hints': rows or []}
        except Exception as e: return fail(e)
    @rt('/lsp/rename')
    async def lsp_rename(req):
        "Preview or atomically apply a workspace rename, built from the server's references."
        d = await req.json()
        name = str(d.get('newName') or '')
        if not name.isidentifier(): return fail(ValueError(f'{name!r} is not a valid name'))
        try:
            # `textDocument/rename` answers for the one file, whatever is open: pyright and
            # basedpyright both return a single `documentChanges` entry where `references`
            # returns every use. References is the whole workspace, and resolves the symbol, so
            # a same-named method on another class is left alone.
            refs = await ask(d, 'textDocument/references', d.get('text', ''),
                             d.get('line', 0), d.get('character', 0),
                             {'context': {'includeDeclaration': True}}, 12)
            here, outside = {}, 0
            for ref in (refs or []):
                try: p = ctx.fs._check(unquote(urlparse(ref['uri']).path), must_exist=True)
                except Exception: outside += 1; continue
                here.setdefault(str(p), []).append({'range': ref['range'], 'newText': name})
            previews = []
            for path, edits in sorted(here.items()):
                before = ctx.fs.read(path)
                previews.append({'path': path, 'before': before, 'after': _edited(before, edits),
                                 'edits': len(edits)})
            previews = [r for r in previews if r['after'] != r['before']]
            if not previews: return fail(ValueError('nothing to rename at that position'))
            if d.get('apply'):
                for row in previews: ctx.fs.write(row['path'], row['after'])
                ctx.journal.record(f'Rename to {name}',
                                   [(r['path'], r['before'], r['after']) for r in previews], kind='rename-symbol')
            return {'ok': True, 'applied': bool(d.get('apply')), 'files': previews, 'outside': outside}
        except Exception as e: return fail(e)
