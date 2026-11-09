from urllib.parse import quote, urlsplit
from uuid import uuid4

from fasthtml.common import A, Blockquote, Button, Div, Form, H2, H3, Input, Li, P, Span, Textarea, Ul
from starlette.responses import Response

from ...core.web import off_loop
from ..memory.memory import _open_lock
from ..tabs.ui import tab_bar
from .tools import learn_settings


def walk_state_for(memory, jid, settings=None):
    try:
        from abhyasa.agent_tools import walk_state, failed
        from abhyasa.learner import Learning
    except ImportError: return {'status': 'error', 'error': 'not_found', 'data': {'message': 'Learning walks are unavailable.'}}
    try:
        with _open_lock(memory.path): return walk_state(Learning(memory._store('learning')), jid, settings=settings)
    except Exception as e:
        from abhyasa.agent_tools import vault_failure
        if (error := vault_failure(e)): return failed(error, str(e), walk=jid)
        raise


def answer_for(memory, ask, jid, i, answer, attempt_id, settings=None, revision=None):
    from abhyasa.agent_tools import failed, record_attempt, vault_failure
    from abhyasa.learner import Learning
    if ask is None: return failed('model_refused', 'no agent model', walk=jid, step=i)
    try:
        with _open_lock(memory.path): return record_attempt(Learning(memory._store('learning')), jid, i, answer, attempt_id, ask, settings=settings, revision=revision)
    except Exception as e:
        if (error := vault_failure(e)): return failed(error, str(e), walk=jid, step=i)
        raise


def walk_ask(ctx):
    from .tools import learn_ask
    return learn_ask(ctx.session.ai)


def walk_memory(ctx, vault):
    ref = ctx.session.vaults.get(vault)
    if ref is None: raise KeyError('Learning vault is not attached.')
    return ctx.session.vaults.memory(ref.name)


def walk_failure(error, message, jid):
    return {'status': 'error', 'error': error, 'data': {'message': message}, 'walk': jid}


def vault_failure(e, jid):
    return walk_failure('not_found' if isinstance(e, (KeyError, FileNotFoundError)) else 'vault_locked', str(e), jid)


def walk_fragment(result, jid, i=None, notice=None):
    if result.get('status') != 'ok':
        return Div(P(result.get('data', {}).get('message') or result.get('error') or 'Walk unavailable.', cls='lee-walk-error'), cls='lee-walk')
    d = result['data']; steps = d.get('steps', [])
    i = d.get('current') if i is None else i
    s = next((s for s in steps if s['i'] == i), None)
    if s is None and steps: s = steps[0]; i = s['i']
    base = '/learn/walk/' + quote(jid, safe='')
    items = [Li(Button(f"{x['name']} · {x['status']}", type='button', data_walk_step=x['i'], aria_current='step' if x['i'] == i else None)) for x in steps]
    body = []
    if s:
        body += [H3(s['name']), P(s.get('statement', ''), cls='lee-walk-statement')]
        q = s.get('quote')
        if q:
            url = q.get('url', '')
            link = A(q.get('title') or url, href=url, data_walk_source='1', rel='noopener noreferrer') if urlsplit(url).scheme in ('http', 'https') else Span(q.get('title') or url)
            body += [Blockquote(q.get('text', '')), P(link)]
        else: body += [P('Ungrounded: no verbatim source', cls='lee-walk-ungrounded')]
        if check := s.get('check'):
            body += [Form(P(check.get('question', '')), Textarea(name='answer', required=True, aria_label='Your answer'),
                          Input(type='hidden', name='attempt_id', value=str(uuid4())),
                          Input(type='hidden', name='revision', value=str(result.get('revision') or '')), Button('Check answer', type='submit'),
                          action=f"{base}/{i}/answer", method='post', data_walk_answer='1')]
    gauge = [Li(Span(slug), Span(g.get('state', 'unseen'), cls='lee-walk-gauge-state')) for slug, g in d.get('gauge', {}).items()]
    msg = P('The walk changed; here is the current step', cls='lee-walk-error', role='status') if notice and notice.get('error') == 'stale_state' else P(notice.get('data', {}).get('message') or notice.get('error', ''), cls='lee-walk-error', role='status') if notice and notice.get('status') != 'ok' else None
    return Div(H2(d.get('title', 'Walk')), msg, Div(Ul(*items, cls='lee-walk-steps'), Div(*body, cls='lee-walk-content'), cls='lee-walk-main'),
               H3('Understanding'), Ul(*gauge, cls='lee-walk-gauge'), cls='lee-walk', data_walk_url=base)


def connect(app, ctx):
    @app.route('/learn/walk.css', methods=['GET'])
    def walk_css():
        from pathlib import Path
        return Response(Path(__file__).with_name('walk.css').read_text(), media_type='text/css')
    @app.route('/learn/walk/open', methods=['POST'])
    async def walk_open(req):
        data = await req.json() if req.headers.get('content-type', '').startswith('application/json') else await req.form()
        vault, walk = data.get('vault', ''), data.get('walk', '')
        if not walk: return walk_fragment(walk_failure('not_found', 'Choose a walk to open.', walk), walk)
        try: memory = await off_loop(walk_memory, ctx, vault)
        except Exception as e: return walk_fragment(vault_failure(e, walk), walk)
        state = await off_loop(walk_state_for, memory, walk, learn_settings(ctx.session))
        if state.get('status') != 'ok': return walk_fragment(state, walk)
        ctx.session.open_learn_walk(vault or ctx.session.vaults.active.name, walk); ctx.session.save()
        return tab_bar(ctx.session)
    @app.route('/learn/walk/{jid}', methods=['GET'])
    async def walk_get(jid: str, vault: str = '', i: int = None):
        try: memory = await off_loop(walk_memory, ctx, vault)
        except Exception as e: return walk_fragment(vault_failure(e, jid), jid)
        return walk_fragment(await off_loop(walk_state_for, memory, jid, learn_settings(ctx.session)), jid, i)
    @app.route('/learn/walk/{jid}/{i}/answer', methods=['POST'])
    async def walk_answer(req, jid: str, i: int, vault: str = ''):
        if req.headers.get('content-type', '').startswith('application/json'): data = await req.json()
        else: data = await req.form()
        try:
            memory = await off_loop(walk_memory, ctx, vault)
            answer = await off_loop(answer_for, memory, walk_ask(ctx), jid, i, data.get('answer', ''), data.get('attempt_id', ''), learn_settings(ctx.session), data.get('revision') or None)
            state = await off_loop(walk_state_for, memory, jid, learn_settings(ctx.session))
        except ImportError: answer = state = walk_failure('not_found', 'Learning walks are unavailable.', jid)
        except Exception as e: answer = state = vault_failure(e, jid)
        if answer.get('status') == 'ok': state.get('data', {}).get('gauge', {}).update(answer.get('data', {}).get('gauge', {}))
        return walk_fragment(state, jid, i, answer)
