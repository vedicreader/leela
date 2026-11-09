import logging
from fasthtml.common import FtResponse, Response
from ...core.web import NOT_OBJECT, fail, json_obj
from ..tabs.ui import tab_bar
from .scene import CreateError, export_page, load, new_project, rev, save_state, values
from .ui import CreatePage

__all__ = ['CAPS', 'connect']

CAPS = ('tab',)

log = logging.getLogger(__name__)

def refused(e: CreateError):
    "The JSON of a failed project call: 404 for a missing project, else 400."
    return fail(e.said, 404 if e.code == 'not_found' else 400, why=e.code)

def connect(app, ctx):
    ws, rt = ctx.session, app.route
    @rt('/create/page', methods=['GET'])
    def create_page(slug: str = ''):
        try: spec = load(slug)
        except CreateError as e: return Response(e.said, status_code=404 if e.code == 'not_found' else 400)
        return FtResponse(CreatePage(slug, spec.get('title') or slug))
    @rt('/create/scene', methods=['GET'])
    def create_scene(slug: str = '', have: str = ''):
        "The spec and the named values of a project; `have` is the `rev` the page holds, and a match answers `same`."
        try:
            now = rev(slug)
            if have == now: return {'ok': True, 'same': True, 'rev': now}
            spec = load(slug)
        except FileNotFoundError: return fail(f'There is no project {slug}.', 404, why='not_found')
        except CreateError as e: return refused(e)
        return {'ok': True, 'slug': slug, 'rev': now, 'spec': spec, 'state': {r['name']: r['value'] for r in values(spec)}}
    @rt('/create/state', methods=['POST'])
    async def create_state(req):
        "Write the numbers the page reports: a name the scene lacks or a number out of its range changes nothing."
        if (d := await json_obj(req)) is None: return fail(NOT_OBJECT)
        if not isinstance(d.get('state'), dict): return fail('state must be an object of numbers.', why='invalid_value')
        try: save_state(d.get('slug'), d['state'])
        except CreateError as e: return refused(e)
        return {'ok': True, 'rev': rev(d['slug'])}
    @rt('/create/new', methods=['POST'])
    async def create_new(req):
        "Make a project from the template and open it in the one Create tab."
        d = await json_obj(req) if req.headers.get('content-type', '').startswith('application/json') else {}
        try: ws.open_story(new_project(str((d or {}).get('name') or '')))
        except CreateError as e: return refused(e)
        ws.save()
        return tab_bar(ws)
    @rt('/create/tab/open', methods=['POST'])
    async def create_tab_open(slug: str = ''):
        try: ws.open_story(slug)
        except CreateError as e: return refused(e)
        ws.save()
        return tab_bar(ws)
    @rt('/create/export', methods=['GET'])
    def create_export(slug: str = ''):
        "The project as one standalone page, as a download."
        try: html = export_page(slug)
        except FileNotFoundError: return fail(f'There is no project {slug}.', 404, why='not_found')
        except CreateError as e: return refused(e)
        return Response(html, media_type='text/html', headers={'Content-Disposition': f'attachment; filename="{slug}.html"', 'X-Content-Type-Options': 'nosniff'})
