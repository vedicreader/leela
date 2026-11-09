import re
from importlib.resources import files
from urllib.parse import quote, urlsplit
from uuid import uuid4

from fasthtml.common import A, Blockquote, Button, Div, Form, H2, H3, Hidden, Input, Li, P, Span, Textarea, Ul, to_xml
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
        vault = memory._store('learning')
        with _open_lock(memory.path): return walk_state(Learning(vault), jid, settings=settings)
    except Exception as e:
        from abhyasa.agent_tools import vault_failure
        if (error := vault_failure(e)): return failed(error, str(e), walk=jid)
        raise


def answer_for(memory, ask, jid, i, answer, attempt_id, settings=None, revision=None):
    from abhyasa.agent_tools import failed, record_attempt, vault_failure
    from abhyasa.learner import Learning
    if ask is None: return failed('model_refused', 'no agent model', walk=jid, step=i)
    try:
        vault = memory._store('learning')
        with _open_lock(memory.path): return record_attempt(Learning(vault), jid, i, answer, attempt_id, ask, settings=settings, revision=revision)
    except Exception as e:
        if (error := vault_failure(e)): return failed(error, str(e), walk=jid, step=i)
        raise


def walk_ask(ctx):
    from .tools import learn_ask
    return learn_ask(ctx.session.ai, 'grade')


def walk_memory(ctx, vault):
    ref = ctx.session.vaults.get(vault)
    if ref is None: raise KeyError('Learning vault is not attached.')
    return ctx.session.vaults.memory(ref.name)


def walk_failure(error, message, jid):
    return {'status': 'error', 'error': error, 'data': {'message': message}, 'walk': jid}


def vault_failure(e, jid):
    return walk_failure('not_found' if isinstance(e, (KeyError, FileNotFoundError)) else 'vault_locked', str(e), jid)


def _walk_step(steps, i):
    if i is not None:
        try: i = int(i)
        except (TypeError, ValueError): i = None
        if s := next((s for s in steps if s.get('i') == i), None): return s
    return steps[0] if steps else None


def _walk_link(q):
    url = q.get('url', '')
    text = q.get('title') or url
    try: safe = isinstance(url, str) and (u := urlsplit(url)).scheme.lower() in ('http', 'https') and bool(u.netloc)
    except ValueError: safe = False
    return A(text, href=url, data_walk_source='1', rel='noopener noreferrer') if safe else Span(text)


def walk_fragment(result, jid, i=None, notice=None):
    d = result.get('data') or {}; steps = d.get('steps') or []
    s = _walk_step(steps, d.get('current') if i is None else i)
    i = s.get('i') if s else None
    base = '/learn/walk/' + quote(jid, safe='')
    items = [Li(Button(f"{x.get('name', '')} · {x.get('status', '')}", type='button', data_walk_step=x.get('i'), aria_current='step' if x is s else None)) for x in steps]
    message = d.get('message') or result.get('error') or 'Walk unavailable.'
    bad = result.get('status') != 'ok'
    if notice and notice.get('error') == 'stale_state': message = 'The walk changed; here is the current step'
    elif notice and notice.get('status') != 'ok': message = notice.get('data', {}).get('message') or notice.get('error') or message
    msg = P(message, cls='lee-walk-error', role='status', data_walk_notice_error='1' if bad or notice and notice.get('status') != 'ok' else None) if bad or notice and notice.get('status') != 'ok' else None
    body = []
    if s:
        n = steps.index(s)
        nav = [Button('Back', type='button', data_walk_back=steps[n-1]['i'])] if n else []
        if n + 1 < len(steps): nav += [Button('Next', type='button', data_walk_next=steps[n+1]['i'])]
        body += [H3(s.get('name', ''), tabindex='-1'), P(s.get('statement', ''), cls='lee-walk-statement')]
        if q := s.get('quote'):
            body += [Blockquote(q.get('text', '')), P(_walk_link(q), cls='lee-walk-source')]
        else: body += [P('Ungrounded: no verbatim source', cls='lee-walk-ungrounded')]
        if check := s.get('check'):
            body += [Form(P(check.get('question', '')), Textarea(name='answer', required=True, aria_label='Your answer'),
                          Input(type='hidden', name='attempt_id', value=str(uuid4())),
                          Input(type='hidden', name='revision', value='' if result.get('revision') is None else str(result['revision'])),
                          Button('Check answer', type='submit'), action=f"{base}/{i}/answer", method='post', data_walk_answer='1')]
        body += [Div(*nav, cls='lee-walk-nav')]
    elif not bad: body += [P('This walk has no steps yet.', cls='lee-walk-empty')]
    gauge = [Li(Span(slug), Span((g or {}).get('state', 'unseen'), cls='lee-walk-gauge-state', data_walk_gauge=(g or {}).get('state', 'unseen'))) for slug, g in (d.get('gauge') or {}).items()]
    return Div(H2(d.get('title', 'Walk')), msg, P('', role='status', cls='lee-walk-busy'), Div(Ul(*items, cls='lee-walk-steps'), Div(*body, cls='lee-walk-content'), cls='lee-walk-main'),
               H3('Understanding'), Ul(*gauge, cls='lee-walk-gauge'), cls='lee-walk', data_walk_url=base)


def walk_job_actions(job, result):
    "The Open walk action of a created walk, with its error slot, or the failure line of a walk that was not created."
    if result.get('status') == 'ok' and (tab := result.get('data', {}).get('tab')):
        slot = f"open-walk-error-{job['id']}"
        return [Form(Hidden(name='vault', value=tab['vault']), Hidden(name='walk', value=tab['walk']), Hidden(name='slot', value='#' + slot),
                     Button('Open walk', cls='lee-btn go'), hx_post='/learn/walk/open', hx_target='#tabbar', hx_swap='outerHTML'),
                Span(id=slot, cls='lee-job-error', role='alert')]
    if result.get('error'): return [Span(result['error'] + ': ' + result.get('data', {}).get('message', ''), cls='lee-job-error')]
    return []


def abh_styles():
    root = files('abhyasa')
    css = '\n'.join(p.read_text() for p in [root/'core'/f for f in ('base.css', 'pane.css', 'edit.css', 'stage.css')] + sorted((root/'blocks').glob('*/*.css')))
    fonts = '\n'.join(re.findall(r'@font-face\s*\{.*?\}', css, flags=re.S))
    css = re.sub(r'@font-face\s*\{.*?\}', '', css, flags=re.S)
    css = re.sub(r'^\[data-theme=\w+\][^\n]*$', '', css, flags=re.M)
    css = css.replace('html.in-pane', ':scope:not(.wide)').replace('html.rh-open', ':scope.rh-open').replace(':root, [data-theme]', ':scope')
    css = re.sub(r'(?<![-\w.#:])(?:body|html|:root)(?![-\w])(?=\s*[{:,.\[ ])', ':scope', css)
    return fonts + '\n@scope (.abh) {\n' + css + '\n}\n'


def connect(app, ctx):
    from ..vault.ui import register_job_actions
    register_job_actions('learn_walk', walk_job_actions)
    @app.route('/learn/abh.css', methods=['GET'])
    def abh_css():
        from pathlib import Path
        return Response(Path(__file__).with_name('abh.css').read_text() + abh_styles(), media_type='text/css')
    @app.route('/learn/walk.css', methods=['GET'])
    def walk_css():
        from pathlib import Path
        return Response(Path(__file__).with_name('walk.css').read_text(), media_type='text/css')
    @app.route('/learn/tab/open', methods=['POST'])
    async def learn_tab_open(path: str = '/'):
        if not path.startswith('/') or path.startswith('//'): path = '/'
        ctx.session.open_learn(path=path); ctx.session.save()
        return tab_bar(ctx.session)
    @app.route('/learn/tab/page', methods=['POST'])
    async def learn_tab_page(req):
        data = await req.json()
        ctx.session.note_learn_page(str(data.get('path') or ''))
        return Response(status_code=204)
    @app.route('/learn/walk/open', methods=['POST'])
    async def walk_open(req):
        data = await req.json() if req.headers.get('content-type', '').startswith('application/json') else await req.form()
        vault, walk = data.get('vault', ''), data.get('walk', '')
        def refused(failure):
            if not req.headers.get('hx-request'): return walk_fragment(failure, walk)
            slot = data.get('slot', '')
            heads = {'HX-Retarget': slot, 'HX-Reswap': 'innerHTML'} if re.fullmatch(r'#open-walk-error-[\w-]+', slot) else {'HX-Reswap': 'none'}
            return Response(to_xml(P(failure['data'].get('message') or failure['error'], cls='lee-job-error', role='alert')), media_type='text/html', headers=heads)
        if not walk: return refused(walk_failure('not_found', 'Choose a walk to open.', walk))
        try: memory = await off_loop(walk_memory, ctx, vault)
        except Exception as e: return refused(vault_failure(e, walk))
        state = await off_loop(walk_state_for, memory, walk, learn_settings(ctx.session))
        if state.get('status') != 'ok': return refused(state)
        ctx.session.open_learn_walk(vault or ctx.session.vaults.active.name, walk); ctx.session.save()
        return tab_bar(ctx.session)
    @app.route('/learn/walk/{jid}', methods=['GET'])
    async def walk_get(req, jid: str, vault: str = '', i: int = None):
        try: memory = await off_loop(walk_memory, ctx, vault)
        except Exception as e: return walk_fragment(vault_failure(e, jid), jid)
        state = await off_loop(walk_state_for, memory, jid, learn_settings(ctx.session))
        if 'application/json' in req.headers.get('accept', ''): return state
        return walk_fragment(state, jid, i)
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
        if req.headers.get('content-type', '').startswith('application/json'): return answer
        return walk_fragment(state, jid, i, answer)
