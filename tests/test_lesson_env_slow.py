import shutil, subprocess, sys
import pytest
from leela.blocks.learn import toolenv
from leela.blocks.learn.toolenv import make_tool_env, tool_python
from leela.blocks.nb.nb import Cell, Notebook

pytestmark = pytest.mark.slow

def offline(cmd, **kw):
    "`subprocess.run` with `--offline` on the install, so only packages in the local uv cache go in."
    return subprocess.run([*cmd, '--offline'] if cmd[1] == 'pip' else cmd, **kw)

def test_a_bound_lesson_runs_its_cells_in_a_real_uv_environment(tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.workspace import Workspace
    if not (uv := shutil.which('uv')): pytest.skip('no uv')
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path/'data'))
    monkeypatch.setattr(toolenv, 'index_env', lambda key: None)
    r = make_tool_env(['six'], run=offline, uv=uv)
    if not r.ok: pytest.skip(f'the local uv cache cannot make the environment offline: {r.error}')
    code, again = Cell(source='import sys; print(sys.executable)'), Cell(source='print(sys.executable)')
    Notebook([code, again], meta={'lesson': {'v': 1, 'name': 'Env', 'walk': dict(walk='w-ab12', step=0, section=''), 'env': r.key}}).save(p := tmp_path/'w-0.ipynb')
    ws = Workspace(roots=[tmp_path], approvals='auto', python=sys.executable)
    ws.open(p)
    try:
        with TestClient(ide_app(ws)) as c:
            got = c.post('/nb/run', json=dict(path=str(p), i=0, id=code.id)).json()
            kept = c.post('/nb/run', json=dict(path=str(p), i=1, id=again.id)).json()
        assert got['ok'] and kept['ok'], (got, kept)
        assert ''.join(got['cell']['outputs'][0]['text']).strip() == str(tool_python(r.key)) != sys.executable
        assert ''.join(kept['cell']['outputs'][0]['text']).strip() == str(tool_python(r.key)), 'the second run keeps the kernel and its names'
    finally: ws.shutdown_now()

def test_the_header_link_opens_the_step_beside_and_a_stream_refusal_says_its_line():
    from test_web_slow import _run
    async def go(pg):
        await pg.route('**/refuse', lambda route: route.fulfill(status=409, content_type='application/json', body='{"ok": false, "error": "The one line."}'))
        await pg.evaluate("""() => {
          window._side = []; window._files = []; window.leeSidePage = {open: u => { window._side.push(u); return true; }};
          window.leeOpenFile = async p => { window._files.push(p); };
          const d = document.createElement('div'); d.innerHTML = '<a id="setup" href="/learn?walk=w-ab12&amp;step=0">Set up the environment</a>';
          document.body.append(d); routeMarkdownLinks(d); }""")
        await pg.locator('#setup').click()
        said = await pg.evaluate("() => postEvents('/refuse', {}, () => {}).then(() => '', e => e.message)")
        return await pg.evaluate('[window._side, window._files]'), said
    (side, files), said = _run(go)
    assert side == ['/learn?walk=w-ab12&step=0'] and files == [] and said == 'The one line.'
