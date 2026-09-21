"Preview and atomically apply workspace text replacements."

from __future__ import annotations
import time, uuid

from fastcore.all import Path

from ...core.web import fail, off_loop

__all__ = ['CAPS', 'connect']

CAPS = ('fs', 'journal', 'docs', 'search')

def _dirty(ctx, paths):
    "Open unsaved buffers the server would otherwise overwrite."
    wanted = set(paths)
    return [t.path for t in ctx.session.tabs if t.path in wanted and t.dirty]

def _clear(ctx, paths):
    "Forget server buffers after an external workspace edit."
    for path in paths:
        ctx.docs.forget(path)
        tab = next((t for t in ctx.session.tabs if t.path == path), None)
        if tab: tab.dirty = False

PLAN_TTL, MAX_PLANS = 600, 8

def _prune(plans):
    "Forget previews nobody applied; each one holds a full copy of every file it would change."
    for token in [k for k, v in plans.items() if time.time() - v['at'] > PLAN_TTL]: plans.pop(token, None)
    for token in list(plans)[:max(0, len(plans) - MAX_PLANS)]: plans.pop(token, None)

def _candidates(ctx, names, limit=400):
    "Files that mention a moved name: ripgrep where it answers, a walk of the tree where it does not."
    try: out = [h.path for name in names for h in ctx.search.usages(name, limit)]
    except Exception: out = [str(p) for p in ctx.fs.walk(limit=5000)]
    return sorted({str(p) for p in out if str(p).endswith('.py')})

def connect(app, ctx):
    from kosha.refactor import replace_plan, extract, inline, module_of, move_plan, top_symbols
    rt, plans = app.route, {}
    def _disk(path):
        "The file as it is now, or None when it is not there yet."
        p = ctx.fs._check(path)
        return ctx.fs.read(p) if p.is_file() else None
    async def _one_file(d, kind, fn, *args):
        "Run one single-file refactoring against the text on disk and stash it as a plan."
        _prune(plans)
        path = ctx.fs._check(d.get('path'), must_exist=True)
        if path.suffix != '.py': return fail(f'{kind} currently supports Python files only')
        row = await off_loop(fn, str(path), ctx.fs.read(path), *args)
        token = 'refactor_' + uuid.uuid4().hex
        plans[token] = {'at': time.time(), 'label': f'Refactor: {kind}', 'kind': 'refactor', 'rows': [row]}
        return {'ok': True, 'token': token, 'files': [row.dict()],
                'summary': {'files': 1, 'edits': row.edits}}
    @rt('/refactor/preview')
    async def refactor_preview(req):
        try:
            d = await req.json(); kind = d.get('kind')
            return await _one_file(d, kind or 'extraction', extract,
                                   d.get('start'), d.get('end'), kind, d.get('name'))
        except Exception as e: return fail(e)
    @rt('/refactor/inline')
    async def refactor_inline(req):
        try:
            d = await req.json()
            return await _one_file(d, 'inline', inline, d.get('pos'))
        except Exception as e: return fail(e)
    @rt('/replace/preview')
    async def replace_preview(req):
        try:
            d = await req.json()
            _prune(plans)
            rows, skipped = await off_loop(replace_plan, ctx.fs.walk(limit=20000), d.get('find', ''), d.get('replace', ''),
                                           d.get('regex', False), d.get('case', False), d.get('word', False), read=ctx.fs.read)
            token = 'replace_' + uuid.uuid4().hex
            plans[token] = {'at': time.time(), 'label': f"Replace {str(d.get('find', ''))!r}",
                            'kind': 'replace-text', 'rows': rows}
            return {'ok': True, 'token': token, 'files': [r.dict() for r in rows],
                    'summary': {'files': len(rows), 'edits': sum(r.edits for r in rows), 'skipped': len(skipped)},
                    'skipped': skipped[:100]}
        except Exception as e: return fail(e)
    async def replace_apply(req):
        try:
            d = await req.json(); plan = plans.pop(str(d.get('token') or ''), None)
            if plan is None: return fail('preview expired; preview again', 409)
            # A move is only correct as a whole, so the files it names in `keep` stay selected.
            # Deselecting the source would leave the definition in both places.
            chosen = set(d.get('paths') or [x.path for x in plan['rows']]) | set(plan.get('keep') or ())
            rows = [r for r in plan['rows'] if r.path in chosen]
            if not rows: return fail('no files selected')
            dirty = _dirty(ctx, [r.path for r in rows])
            if dirty: return fail('unsaved open files: ' + ', '.join(dirty), 409)
            stale = [r.path for r in rows if _disk(r.path) != r.before]
            if stale: return fail('files changed after preview: ' + ', '.join(stale), 409)
            written = []
            try:
                for row in rows:
                    ctx.fs.write(row.path, row.after); written.append(row)
            except Exception:
                for row in reversed(written):
                    try:
                        if row.before is None: ctx.fs._check(row.path).unlink(missing_ok=True)
                        else: ctx.fs.write(row.path, row.before)
                    except Exception: pass
                raise
            op = ctx.journal.record(plan['label'], [(r.path, r.before, r.after) for r in rows],
                                    kind=plan['kind'])
            _clear(ctx, [r.path for r in rows])
            return {'ok': True, 'operation': op, 'paths': [r.path for r in rows]}
        except Exception as e: return fail(e, 409)
    @rt('/refactor/symbols')
    async def refactor_symbols(req):
        "What can be moved out of a file, for the picker."
        try:
            d = await req.json()
            path = ctx.fs._check(d.get('path'), must_exist=True)
            if path.suffix != '.py': return fail('move supports Python files only')
            return {'ok': True, 'module': module_of(str(path)), 'symbols': top_symbols(ctx.fs.read(path))}
        except Exception as e: return fail(e)
    @rt('/refactor/move')
    async def refactor_move(req):
        try:
            d = await req.json()
            _prune(plans)
            src = ctx.fs._check(d.get('path'), must_exist=True)
            dest = ctx.fs._check(d.get('dest'))
            if src.suffix != '.py': return fail('move supports Python files only')
            names = [str(n) for n in (d.get('names') or [])]
            others = await off_loop(_candidates, ctx, names)
            rows, notes = await off_loop(move_plan, str(src), names, str(dest), others, bool(d.get('shim', True)), read=_disk)
            token = 'refactor_' + uuid.uuid4().hex
            plans[token] = {'at': time.time(), 'kind': 'move-symbol', 'rows': rows,
                            'label': f"Move {', '.join(names)} to {dest.name}",
                            'keep': [str(src), str(dest)]}
            return {'ok': True, 'token': token, 'notes': notes, 'files': [r.dict() for r in rows],
                    'summary': {'files': len(rows), 'edits': sum(r.edits for r in rows)}}
        except Exception as e: return fail(e)
    for path in ('/replace/apply', '/refactor/apply'): rt(path)(replace_apply)
