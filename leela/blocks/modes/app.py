"The workspace mode: which mode is on, its dock layout, and the one switch for the page and the agent."

from fasthtml.common import JSONResponse
from ...core.web import NOT_OBJECT, fail, json_obj, off_loop
from ..agent.threads import TurnError
from .modes import get_mode, modes

__all__ = ['CAPS', 'connect', 'refusal']

CAPS = ()

def refusal(e):
    "The JSON a refused mode change answers with: the structured refusal, 409 for a busy turn."
    if e.code != 'thread_busy': return JSONResponse(e.dict(), status_code=409)
    from abhyasa.agent_tools import failed
    return JSONResponse({**failed(e.code, e.message, extra=('thread_busy',)), **e.dict()}, status_code=409)

def listing(ws):
    return {'mode': ws.mode, 'modes': [m.dict() for m in modes()], 'layouts': {m.id: ws.mode_layout(m.id) for m in modes()}}

def connect(app, ctx):
    rt, ws = app.route, ctx.session
    @rt('/workspace/mode', methods=['GET'])
    def mode_info(): return listing(ws)
    @rt('/workspace/mode', methods=['POST'])
    async def mode_set(req):
        if (d := await json_obj(req)) is None: return fail(NOT_OBJECT)
        try: get_mode(d.get('mode'))
        except KeyError: return JSONResponse(dict(ok=False, code='invalid_mode', message=f"There is no mode {d.get('mode')!r}."), status_code=400)
        try:
            if ws._threads is not None:
                t = ws.threads.require(str(d['thread'])) if d.get('thread') else ws.threads.active
                await off_loop(t.set_mode, d['mode'])
            out = await off_loop(ws.set_mode, d['mode'])
        except TurnError as e: return refusal(e)
        except Exception as e: return fail(e, 400 if isinstance(e, (KeyError, ValueError)) else 500)
        return {'ok': True, **out}
    @rt('/workspace/layout', methods=['POST'])
    async def layout_set(req):
        if (d := await json_obj(req)) is None: return fail(NOT_OBJECT)
        try: layout = ws.remember_layout(d.get('mode'), d.get('layout'))
        except KeyError: return JSONResponse(dict(ok=False, code='invalid_mode', message=f"There is no mode {d.get('mode')!r}."), status_code=400)
        except ValueError as e: return fail(e)
        ws.save()
        return {'ok': True, 'mode': d['mode'], 'layout': layout}
