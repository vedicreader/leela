"Preview and atomically apply workspace text replacements."

from __future__ import annotations
import time, uuid

from ...core.web import fail, off_loop
from .refactor import replace_plan
from .python import extract, inline

__all__ = ['CAPS', 'connect']

CAPS = ('fs', 'journal', 'tab', 'docs')

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

def connect(app, ctx):
    rt, plans = app.route, {}
    async def _one_file(d, kind, fn, *args):
        "Run one single-file refactoring against the text on disk and stash it as a plan."
        _prune(plans)
        path = ctx.fs._check(d.get('path'), must_exist=True)
        if path.suffix != '.py': return fail(f'{kind} currently supports Python files only')
        row = await off_loop(fn, str(path), ctx.fs.read(path), *args)
        token = 'refactor_' + uuid.uuid4().hex
        plans[token] = {'at': time.time(), 'find': kind, 'rows': [row]}
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
            rows, skipped = await off_loop(replace_plan, ctx.fs, d.get('find', ''), d.get('replace', ''),
                                           d.get('regex', False), d.get('case', False), d.get('word', False))
            token = 'replace_' + uuid.uuid4().hex
            plans[token] = {'at': time.time(), 'find': str(d.get('find', '')),
                            'replace': str(d.get('replace', '')), 'rows': rows}
            return {'ok': True, 'token': token, 'files': [r.dict() for r in rows],
                    'summary': {'files': len(rows), 'edits': sum(r.edits for r in rows), 'skipped': len(skipped)},
                    'skipped': skipped[:100]}
        except Exception as e: return fail(e)
    async def replace_apply(req):
        try:
            d = await req.json(); plan = plans.pop(str(d.get('token') or ''), None)
            if plan is None: return fail('replacement preview expired; preview again', 409)
            rows = [r for r in plan['rows'] if r.path in set(d.get('paths') or [x.path for x in plan['rows']])]
            if not rows: return fail('no files selected')
            dirty = _dirty(ctx, [r.path for r in rows])
            if dirty: return fail('unsaved open files: ' + ', '.join(dirty), 409)
            stale = [r.path for r in rows if ctx.fs.read(r.path) != r.before]
            if stale: return fail('files changed after preview: ' + ', '.join(stale), 409)
            written = []
            try:
                for row in rows:
                    ctx.fs.write(row.path, row.after); written.append(row)
            except Exception:
                for row in reversed(written):
                    try: ctx.fs.write(row.path, row.before)
                    except Exception: pass
                raise
            op = ctx.journal.record(f"Replace {plan['find']!r}", [(r.path, r.before, r.after) for r in rows],
                                    kind='replace-text')
            _clear(ctx, [r.path for r in rows])
            return {'ok': True, 'operation': op, 'paths': [r.path for r in rows]}
        except Exception as e: return fail(e, 409)
    for path in ('/replace/apply', '/refactor/apply'): rt(path)(replace_apply)
