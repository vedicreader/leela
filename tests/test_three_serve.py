"rupaka's scene loads three.js from the folder of lee-rupaka.js, so Leela serves `rupaka.render.bundle('three')` at `/leestatic/three.js`."
import re
from starlette.routing import Mount
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.workspace import Workspace

def test_the_ide_serves_three_js_beside_lee_rupaka_js_before_the_static_mount(tmp_path):
    from rupaka.render import bundle
    ws = Workspace(roots=[tmp_path])
    try:
        app = ide_app(ws)
        with TestClient(app, base_url='http://127.0.0.1:5011') as c:
            src = re.search(r'name="lee-rupaka-src" content="([^"?]+)', c.get('/').text)[1]
            r = c.get(src.rsplit('/', 1)[0] + '/three.js?v=1')
            assert r.status_code == 200 and r.headers['content-type'].startswith('text/javascript'), r.status_code
            assert r.text == bundle('three') and 'window.RupakaTHREE=' in r.text
            assert 'max-age' in r.headers['cache-control'] and 'immutable' not in r.headers['cache-control']
            assert c.get('/leestatic/lee-rupaka.js').status_code == 200
        paths = [getattr(x, 'path', '') for x in app.router.routes]
        assert paths.index('/leestatic/three.js') < next(i for i, x in enumerate(app.router.routes) if isinstance(x, Mount) and x.path == '/leestatic')
    finally: ws.shutdown_now()

def test_the_audience_page_loads_lee_rupaka_js_from_leestatic(tmp_path):
    "The audience page's rupaka sets `R.base` from its own src, so three.js resolves to the same route."
    from leela.blocks.nb.presentation import _page
    assert re.search(r'<script src="/leestatic/lee-rupaka\.js\?v=\d+" defer>', _page('x'))
