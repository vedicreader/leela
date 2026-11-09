import re
from importlib.resources import files

from fasthtml.common import Button, Form, Hidden, Span
from starlette.responses import JSONResponse, Response

from ..tabs.ui import tab_bar
from . import surfaces


def walk_job_actions(job, result):
    "The Open walk action of a created walk, or the failure line of a walk that was not created."
    if result.get('status') == 'ok' and (tab := result.get('data', {}).get('tab')):
        return [Form(Hidden(name='vault', value=tab['vault']), Hidden(name='path', value=tab['path']),
                     Button('Open walk', cls='lee-btn go'), hx_post='/learn/tab/open', hx_target='#tabbar', hx_swap='outerHTML')]
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
    @app.route('/learn/abh-grip.js', methods=['GET'])
    def abh_grip(): return Response((files('abhyasa')/'core/grip.js').read_text(), media_type='text/javascript')
    @app.route('/learn/abh-asset/{name}', methods=['GET'])
    def abh_asset(name: str):
        if not (p := surfaces.asset(name)): return Response('Not found', status_code=404)
        return Response(p.read_bytes(), media_type='text/css' if p.suffix == '.css' else 'text/javascript', headers={'Cache-Control': 'no-cache'})
    @app.route('/learn/abh-surface', methods=['GET'])
    def abh_surface(path: str = '/'): return JSONResponse(surfaces.surface(path))
    @app.route('/learn/tab/open', methods=['POST'])
    async def learn_tab_open(path: str = '/', vault: str = ''):
        if not path.startswith('/') or path.startswith('//'): path = '/'
        ctx.session.open_learn(vault, path); ctx.session.save()
        return tab_bar(ctx.session)
    @app.route('/learn/tab/page', methods=['POST'])
    async def learn_tab_page(req):
        data = await req.json()
        ctx.session.note_learn_page(str(data.get('path') or ''))
        return Response(status_code=204)
