import time
from fastcore.basics import first
from fasthtml.common import FtResponse, JSONResponse
from starlette.responses import PlainTextResponse
from ... import errstr
from ...core.web import fail, off_loop
from ..memory.memory import _open_lock
from .ui import StepPage

__all__ = ['CAPS', 'connect']

CAPS = ('memory',)

def due_cards(memory):
    from abhyasa.store import Learning
    from abhyasa.model import recall, understanding
    vault = memory._store('learning')
    with _open_lock(memory.path):
        lr, now = Learning(vault), time.time()
        due = [c for c in lr.concepts() if c.seen and c.due and c.due <= now]
        rows = []
        for c in sorted(due, key=lambda c: c.due):
            a = first(lr.attempts(c.slug, limit=1)) or {}
            rows.append(dict(name=c.name, slug=c.slug, **{k: a.get(k, '') for k in ('question', 'answer', 'thinking', 'actual')},
                why=f'due for review: recall about {recall(c, now):.0%}', reason=first(understanding(c, now).reasons) or ''))
        return rows

HEADERS = {'Content-Security-Policy': "frame-ancestors 'self'", 'Referrer-Policy': 'no-referrer'}

def read_step(memory, q):
    from abhyasa.store import Learning
    from .learn import find_step
    vault = memory._store('learning')
    with _open_lock(memory.path): return find_step(Learning(vault), q)

def said(text, code=200): return PlainTextResponse(text, status_code=code, headers=HEADERS)

def connect(app, ctx):
    @app.route('/lesson/due')
    async def lesson_due():
        try: return JSONResponse(await off_loop(due_cards, ctx.memory))
        except Exception as e: return fail(f'The learning vault is locked or unreadable. {errstr(e)}')
    @app.route('/learn', methods=['GET'])
    async def learn(req):
        from abhyasa.journey import read_handoff
        try: q = read_handoff(req.url.query)
        except ValueError as e: return said(str(e), 400)
        try: v = await off_loop(read_step, ctx.memory, q)
        except ValueError as e: return said(str(e), 400)
        except Exception: return said('The learning store is locked or cannot be read.', 503)
        if v.kind == 'missing': return said('This walk is not in your learning store.')
        if v.kind == 'done': return said('This walk is done.')
        return FtResponse(StepPage(v, q, pane=req.query_params.get('pane') == '1'), headers=HEADERS)
