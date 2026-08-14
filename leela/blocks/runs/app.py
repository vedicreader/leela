"Run configurations, and the dev servers they start."

from __future__ import annotations

import json

from ...core.web import fail

__all__ = ['CAPS', 'connect']

CAPS = ('runs', 'dev', 'tab')

def connect(app, ctx):
    rt = app.route
    @rt('/runs')
    def runs_route():
        "The project's run configurations, plus one for the open file so the picker is never empty."
        t = ctx.tab
        here = ctx.runs.for_file(t.path) if (t is not None and (t.path or '').endswith('.py')) else None
        names = {r.name for r in ctx.runs.runs}
        return {'runs': [r.dict() for r in ctx.runs.runs],
                'here': here.dict() if (here and here.name not in names) else None,
                'path': str(ctx.runs.path or ''), 'note': ctx.runs.note,
                'servers': [s.state() for s in ctx.dev.all()]}
    @rt('/runs/save')
    async def runs_save(req):
        "Write the configurations file, creating it from a template when there is none yet."
        d = await req.json()
        try:
            if (text := d.get('text')) is not None:
                json.loads(text)
                p = ctx.runs.path
                if p is None: return fail('open a folder first')
                p.mk_write(text)
            ctx.runs.load()
        except Exception as e: return fail(e)
        return {'ok': True, 'path': str(ctx.runs.path or ''), 'note': ctx.runs.note,
                'runs': [r.dict() for r in ctx.runs.runs]}
