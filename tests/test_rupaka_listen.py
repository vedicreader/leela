"rupaka's `listen` block (0.0.23 and later) loads `listen-worklet.js` from `Rupaka.base`, the folder of lee-rupaka.js, so Leela serves it at `/leestatic/listen-worklet.js`."
import re
from pathlib import Path
from starlette.routing import Mount
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.workspace import Workspace

ROOT = Path(__file__).resolve().parents[1]

def test_the_ide_serves_the_listen_worklet_beside_lee_rupaka_js_before_the_static_mount(tmp_path):
    import rupaka
    text = (Path(rupaka.__file__).parent/'static'/'listen-worklet.js').read_text()
    ws = Workspace(roots=[tmp_path])
    try:
        app = ide_app(ws)
        with TestClient(app, base_url='http://127.0.0.1:5011') as c:
            src = re.search(r'name="lee-rupaka-src" content="([^"?]+)', c.get('/').text)[1]
            r = c.get(src.rsplit('/', 1)[0] + '/listen-worklet.js?v=1')
            assert r.status_code == 200 and r.headers['content-type'].startswith('text/javascript'), r.status_code
            assert r.text == text and 'registerProcessor' in r.text
        paths = [getattr(x, 'path', '') for x in app.router.routes]
        assert paths.index('/leestatic/listen-worklet.js') < next(i for i, x in enumerate(app.router.routes) if isinstance(x, Mount) and x.path == '/leestatic')
    finally: ws.shutdown_now()

def test_the_vendored_rupaka_bundle_is_0_0_24():
    "lee-rupaka.js is written from 0.0.24: the listen and rhythm blocks, `ctx.buffer` for recordings on the page's own origin, and the listen block's Keep my playing and Save my playing."
    js = (ROOT/'leela'/'vendor'/'lee-rupaka.js').read_text()
    assert "Rupaka.block('rhythm'" in js and "Rupaka.block('listen'" in js and 'listen-worklet.js' in js and 'ctx.buffer = name =>' in js
    assert 'Keep my playing' in js and 'Save my playing' in js
