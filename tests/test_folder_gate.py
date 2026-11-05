"No HTTP route adds a folder by itself: the guard, the one gate every add route goes through, and the trusted ways past it."

import asyncio, json, threading, time
from pathlib import Path
from unittest.mock import Mock
import pytest
from starlette.testclient import TestClient
from leela import hub
from leela.app import ide_app
from leela.hub import OPEN_PATH, LoopbackHostGuard, WorkspaceHub, WorkspaceSite
from leela.workspace import Workspace

PAGE = {'origin': 'http://testserver', 'sec-fetch-site': 'same-origin'}

class Asked:
    "A confirmer that records each question and gives the next answer; an exception answer is raised."
    def __init__(self, *answers, wait=0): self.qs, self.answers, self.wait = [], list(answers), wait
    def __call__(self, q):
        self.qs.append(q); time.sleep(self.wait)
        a = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(a, BaseException): raise a
        return a

def _call(app, path, query=b'', method='POST', headers=()):
    sent = []
    async def send(m): sent.append(m)
    async def receive(): return {'type': 'http.request', 'body': b''}
    asyncio.run(app({'type': 'http', 'method': method, 'path': path, 'query_string': query,
                     'headers': [(k.encode(), v.encode()) for k, v in headers]}, receive, send))
    body = sent[-1].get('body', b'')
    try: body = json.loads(body)
    except ValueError: body = body.decode()
    return sent[0]['status'], body

def _hub(tmp_path):
    made = {}
    def build(root, slug):
        ws = made[slug] = Workspace(roots=[root]); ws._state_path = tmp_path/f'{slug}.json'
        return WorkspaceSite(slug, Path(root).name, str(root), lambda *a: None, ws.open_external, ws.release, ws.fs.covers, ws.add_root)
    return WorkspaceHub([], 5001, build=build), made

@pytest.fixture
def folders(tmp_path, monkeypatch):
    from leela.core import projects
    monkeypatch.setattr(projects, 'SESSION', tmp_path/'desktop.json')
    (a := tmp_path/'mine').mkdir(); (b := tmp_path/'proj').mkdir(); (b/'.git').mkdir(); (b/'a.md').write_text('a\n')
    return a.resolve(), b.resolve()

# The guard

def _guard(method, headers, path='/x', kind='http'):
    seen, sent = [], []
    async def app(scope, receive, send): seen.append(1)
    async def send(m): sent.append(m)
    asyncio.run(LoopbackHostGuard(app)({'type': kind, 'method': method, 'path': path,
        'headers': [(k.encode(), v.encode()) for k, v in {'host': '127.0.0.1:5011', **headers}.items()]}, Mock(), send))
    return 'passed' if seen else sent[0].get('status', sent[0].get('code'))

def test_the_guard_refuses_a_change_from_a_page_on_another_port():
    """The guard checked the Origin's host and not its port, so a page on another localhost port could post to Leela."""
    assert _guard('POST', {'origin': 'http://127.0.0.1:3000'}) == 403
    assert _guard('POST', {'origin': 'http://localhost:5011'}) == 403
    assert _guard('GET', {'origin': 'http://127.0.0.1:3000'}, kind='websocket') == 1008, 'a socket too'
    assert _guard('POST', {'origin': 'http://127.0.0.1:5011'}) == 'passed'
    assert _guard('POST', {'origin': 'null', 'sec-fetch-site': 'same-origin'}) == 'passed'
    assert _guard('GET', {'origin': 'http://127.0.0.1:3000'}) == 'passed', 'a read is left to the other rules'
    assert _guard('POST', {'origin': 'http://127.0.0.1:5011', 'sec-fetch-site': 'cross-site'}) == 421

def test_hub_open_takes_a_post_and_keeps_the_probe(tmp_path, folders):
    h, made = _hub(tmp_path)
    status, d = _call(h, OPEN_PATH, f'path={folders[0]}'.encode(), method='GET')
    assert status == 405 and d['ok'] is False and not h.sites
    status, d = _call(h, OPEN_PATH, method='GET')
    assert status == 400 and 'not a folder' in d['error'], 'what `leela_on` reads'

# One gate, every route

def _routes(tmp_path, folders):
    "Each add route as `(add, added)`: a curl-shaped request, and whether its folder is now open."
    mine, proj = folders
    h, made = _hub(tmp_path)
    ws = Workspace(roots=[mine]); c = TestClient(ide_app(ws))
    import leela.blocks.pipelines.app as pipes
    def made_pkg(session, name, target='', description=''): (r := proj.parent/name).mkdir(exist_ok=True); return dict(ok=True, root=str(r), name=name)
    pipes.fastship_new, real = made_pkg, pipes.fastship_new
    pkg = proj.parent/'pkg'
    return h, made, ws, c, {
        'hub-folder': (lambda: _call(h, OPEN_PATH, f'path={proj}'.encode()), lambda: h.site_at(proj) is not None),
        'hub-file': (lambda: _call(h, OPEN_PATH, f'path={proj}&file={proj/"a.md"}&folder=1'.encode()), lambda: h.site_at(proj) is not None),
        # a Yes answers with the redrawn page, not JSON
        'add_root': (lambda: (lambda r: (r.status_code, r.json() if 'json' in r.headers['content-type'] else {'ok': r.status_code == 200}))(c.post(f'/fs/add_root?path={proj}')), lambda: ws.fs.covers(proj)),
        'add-root': (lambda: (lambda r: (r.status_code, r.json()))(c.post('/fs/add-root', json={'path': str(proj)})), lambda: ws.fs.covers(proj)),
        'pipeline': (lambda: (lambda r: (r.status_code, r.json()))(c.post('/project/fastship/action', json={'op': 'new', 'name': 'pkg'})), lambda: ws.fs.covers(pkg)),
    }, lambda: setattr(pipes, 'fastship_new', real)

@pytest.mark.parametrize('route', ['hub-folder', 'hub-file', 'add_root', 'add-root', 'pipeline'])
def test_a_curl_post_to_each_add_route_asks_once_and_no_changes_nothing(tmp_path, folders, route):
    """`curl -X POST` from the agent's shell added any folder to a window with nobody asked."""
    from leela.core import projects
    h, made, ws, c, routes, undo = _routes(tmp_path, folders)
    try:
        add, added = routes[route]
        hub.set_confirmer(asked := Asked(False))
        before = projects.session()
        status, d = add()
        assert (status, d['ok'], d['declined']) == (403, False, True) and d['offer'] and 'You said No' in d['error'], d
        assert not added() and projects.session() == before and not made, 'nothing added, noted or opened'
        assert len(asked.qs) == 1 and str(Path(d['offer'])) in asked.qs[0] and 'Leela window' in asked.qs[0], asked.qs
        status, d = add()
        assert (status, d['declined']) == (403, True) and len(asked.qs) == 1, 'a No holds for 10 minutes with no second dialog'
        hub.reset_gate(); hub.set_confirmer(asked := Asked(True))
        status, d = add()
        assert status == 200 and d['ok'] and added() and len(asked.qs) == 1, d
    finally: c.close(); ws.shutdown_now(); undo()

def test_a_confirmer_that_raises_is_a_no_and_no_window_is_its_own_refusal(tmp_path, folders):
    h, made = _hub(tmp_path)
    hub.set_confirmer(Asked(RuntimeError('dialog broke')))
    status, d = _call(h, OPEN_PATH, f'path={folders[1]}'.encode())
    assert (status, d['declined']) == (403, True) and not h.sites
    hub.reset_gate(); hub.set_confirmer(Asked(hub.NoWindow()))
    status, d = _call(h, OPEN_PATH, f'path={folders[1]}'.encode())
    assert (status, d) == (403, {'ok': False, 'declined': False, 'offer': str(folders[1]), 'error': 'No Leela window is open to ask in.', 'config': d['config']})
    assert not hub.declined(folders[1]), 'no answer is not a No'

def test_a_no_stops_the_offer_for_that_folder(tmp_path, folders):
    from leela.core.projects import loose_root
    hub.set_confirmer(Asked(False))
    ws = Workspace(); ws.add_root(loose_root(), loose=True)
    assert hub.admit_folder(folders[1], 'x')[0] == 403
    ws.open(folders[1]/'a.md')
    assert ws.offers == {}, 'no offer for a folder declined in the last 10 minutes'

def test_already_open_or_loose_asks_nothing(tmp_path, folders):
    from leela.core.projects import loose_root
    hub.set_confirmer(asked := Asked(False))
    ws = Workspace(roots=[folders[1]])
    assert hub.admit_folder(folders[1], 'x', covers=ws.fs.covers) is None and hub.admit_folder(loose_root(), 'x') is None and asked.qs == []
    hub.grant(folders[1])
    assert hub.admit_folder(folders[1], 'x', covers=ws.fs.covers) is None and hub._gate['grants'], 'a grant is not spent on a folder already open'

def test_a_picked_folder_passes_once(tmp_path, folders):
    hub.set_confirmer(asked := Asked(False))
    hub.grant(folders[1])
    assert hub.admit_folder(folders[1], 'x') is None and asked.qs == []
    assert hub.admit_folder(folders[1], 'x')[0] == 403 and len(asked.qs) == 1, 'the grant is spent'
    hub.reset_gate(); hub.set_confirmer(Asked(False)); hub.grant(folders[1], secs=-1)
    assert hub.admit_folder(folders[1], 'x')[0] == 403, 'and runs out'

def test_a_trusted_dock_open_adds_with_no_dialog(tmp_path, folders, monkeypatch):
    import leela.desktop, leela_app as app
    hub.set_confirmer(Asked(AssertionError('a Dock open must not ask')))
    h, made = _hub(tmp_path)
    monkeypatch.setattr(app, 'hub_open', lambda port, path, host='127.0.0.1', **kw: _call(h, OPEN_PATH, f'path={path}'.encode())[1])
    monkeypatch.setattr(leela.desktop, 'open_window', lambda url, title='leela', key=None, **kw: None)
    app.open_folder(5001, folders[1])
    assert h.site_at(folders[1]) is not None
    hub.set_confirmer(asked := Asked(False))
    app.open_folder(5001, folders[0], trusted=False)
    assert h.site_at(folders[0]) is None and len(asked.qs) == 1, 'a request from the page is asked about'

def test_a_page_call_to_open_folder_is_asked_about_and_a_picked_folder_is_not(tmp_path, folders, monkeypatch):
    """`pywebview.api.open_folder` shared the Dock's trusted callback, so a script in the page could add any folder with no question."""
    import leela.desktop, leela_app as app
    api = leela.desktop.shell_api()
    for k in ('on_open_folder', 'on_page_folder', 'on_picked'): monkeypatch.setattr(api, k, None)
    h, made = _hub(tmp_path)
    monkeypatch.setattr(app, 'hub_open', lambda port, path, host='127.0.0.1', **kw: _call(h, OPEN_PATH, f'path={path}'.encode())[1])
    monkeypatch.setattr(leela.desktop, 'open_window', lambda url, title='leela', key=None, **kw: None)
    kw = app._hooks(5001)
    api.on_open_folder, api.on_picked = kw['on_open_folder'], hub.grant
    hub.set_confirmer(asked := Asked(False))
    assert api.open_folder(str(folders[1])) and h.site_at(folders[1]) is None and len(asked.qs) == 1, 'the page goes through the gate'
    import sys, types
    pick = types.SimpleNamespace(FileDialog=types.SimpleNamespace(FOLDER=20), active_window=lambda: types.SimpleNamespace(create_file_dialog=lambda kind: [str(folders[0])]))
    monkeypatch.setitem(sys.modules, 'webview', pick)
    assert api.pick_folder() == str(folders[0]) and api.open_folder(str(folders[0]))
    assert h.site_at(folders[0]) is not None and len(asked.qs) == 1, 'a folder the person picked opens with no question'
    kw['on_open_folder'](str(folders[1]))
    assert h.site_at(folders[1]) is not None and len(asked.qs) == 1, 'and the Dock path stays trusted'

def test_a_learning_copy_opens_with_its_folder_in_one_question(tmp_path, folders):
    """`/hub/open` refused a learning copy with 400, because the copy is not inside the project."""
    (copies := tmp_path/'copies').mkdir(); (copy := copies/'15.ipynb').write_text('{}')
    h, made = _hub(tmp_path)
    hub.set_confirmer(asked := Asked(True))
    status, d = _call(h, OPEN_PATH, f'path={folders[1]}&file={copy}&folder=1&also={copies}'.encode())
    assert status == 200 and d['ok'], d
    ws = made[d['id']]
    assert ws.fs.covers(folders[1]) and ws.fs.covers(copies.resolve()) and ws.tab.path == str(copy.resolve())
    assert len(asked.qs) == 1 and str(copies.resolve()) in asked.qs[0] and str(folders[1]) in asked.qs[0]

def test_also_on_a_window_already_open_is_asked_about(tmp_path, folders):
    h, made = _hub(tmp_path)
    hub.grant(folders[1]); assert _call(h, OPEN_PATH, f'path={folders[1]}'.encode())[0] == 200
    hub.set_confirmer(asked := Asked(False))
    status, d = _call(h, OPEN_PATH, f'path={folders[1]}&also={folders[0]}'.encode())
    assert status == 403 and not made[d.get('id') or 'proj'].fs.covers(folders[0]) and len(asked.qs) == 1

# Browser mode

def test_browser_mode_lets_a_page_add_and_refuses_a_bare_post(tmp_path, folders):
    ws = Workspace(roots=[folders[0]])
    with TestClient(ide_app(ws)) as c:
        r = c.post('/fs/add-root', json={'path': str(folders[1])})
        assert r.status_code == 403 and r.json()['declined'] is False and not ws.fs.covers(folders[1]), 'no Sec-Fetch-Site'
        r = c.post('/fs/add-root', json={'path': str(folders[1])}, headers={'sec-fetch-site': 'same-origin'})
        assert r.status_code == 403, 'and no Origin'
        r = c.post('/fs/add-root', json={'path': str(folders[1])}, headers=PAGE)
        assert r.status_code == 200 and ws.fs.covers(folders[1])
        assert c.get(f'/fs/add_root?path={folders[1]}').status_code == 405
    ws.shutdown_now()

# The desktop entry

def test_the_desktop_app_registers_the_confirmer_and_the_picker(monkeypatch):
    import leela.desktop
    from test_desktop_entry import _launch
    api = leela.desktop.shell_api()
    for k in ('on_picked', 'on_page_folder'): monkeypatch.setattr(api, k, None)
    _launch(monkeypatch, live=None)
    import leela_app as app
    leela_app_run = app.run; leela_app_run()
    assert hub._gate['confirm'] is not None and api.on_picked is hub.grant and api.on_page_folder is not None
    monkeypatch.setattr(app, 'confirm', lambda q, port: q)
    assert hub._gate['confirm']('Add?') == 'Add?'

def test_with_no_window_the_home_window_opens_then_no_window_is_said(monkeypatch, tmp_path, folders):
    import sys, types, leela.desktop, leela_app as app
    windows, opened = [], []
    fake = types.SimpleNamespace(windows=windows, active_window=lambda: None)
    monkeypatch.setitem(sys.modules, 'webview', fake)
    monkeypatch.setattr(leela.desktop, 'open_window', lambda url, title='leela', key=None, **kw: opened.append((url, key)))
    with pytest.raises(hub.NoWindow): app.confirm('Add?', 5001, wait=.2)
    assert opened == [('http://127.0.0.1:5001/', app.HOME_KEY)]
    hub.set_confirmer(lambda q: app.confirm(q, 5001, wait=.1))
    assert hub.admit_folder(folders[1], 'x')[1]['error'] == 'No Leela window is open to ask in.'
    w = types.SimpleNamespace(shown=[], show=lambda: w.shown.append(1), create_confirmation_dialog=lambda t, m: True)
    windows.append(w)
    assert app.confirm('Add?', 5001) is True and w.shown == [1], 'a hidden window is shown, then asked in'

def test_concurrent_requests_show_one_dialog_at_a_time(tmp_path, folders):
    hub.set_confirmer(asked := Asked(True, wait=.3))
    h, made = _hub(tmp_path)
    got, live = [], []
    def go(p): got.append(_call(h, OPEN_PATH, f'path={p}'.encode())[0])
    def watch():
        for _ in range(40): live.append(hub._gate['lock'].locked()); time.sleep(.02)
    ts = [threading.Thread(target=go, args=(p,)) for p in (folders[1], folders[1], folders[0])] + [threading.Thread(target=watch)]
    for t in ts: t.start()
    for t in ts: t.join()
    assert got == [200, 200, 200] and len(asked.qs) == 2, asked.qs
    assert len(set(map(str, h.sites))) == 2

@pytest.mark.slow
def test_a_real_curl_from_the_agent_shell_adds_nothing(tmp_path, folders):
    import shutil, socket, uvicorn
    from leela.blocks.agent.ai import WorkspaceHost
    if not shutil.which('curl'): pytest.skip('no curl')
    h, made = _hub(tmp_path)
    ws = Workspace(roots=[folders[0]])
    h.sites['mine'] = WorkspaceSite('mine', 'mine', str(folders[0]), ide_app(ws), ws.open_external, covers=ws.fs.covers)
    h.default = 'mine'
    with socket.socket() as s: s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(LoopbackHostGuard(h), host='127.0.0.1', port=port, log_level='error'))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started: time.sleep(.02)
    try:
        host = WorkspaceHost(ws)
        for cmd in (f"curl -s -X POST 'http://127.0.0.1:{port}/hub/open?path={folders[1]}'",
                    f"curl -s -X POST 'http://127.0.0.1:{port}/fs/add_root?path={folders[1]}'",
                    f"curl -s -X POST -H 'content-type: application/json' -d '{{\"path\": \"{folders[1]}\"}}' http://127.0.0.1:{port}/fs/add-root"):
            code, out = host.run_cmd(cmd)
            assert '"ok":false' in out.replace(' ', ''), (cmd, out)
        hub.set_confirmer(asked := Asked(False))
        code, out = host.run_cmd(f"curl -s -X POST 'http://127.0.0.1:{port}/hub/open?path={folders[1]}'")
        assert '"declined":true' in out.replace(' ', '') and len(asked.qs) == 1, out
        assert h.site_at(folders[1]) is None and not ws.fs.covers(folders[1]) and not made
    finally:
        srv.should_exit = True; ws.shutdown_now()

@pytest.mark.slow
def test_a_leela_page_in_a_browser_adds_a_folder_and_hears_a_no_quietly(tmp_path, folders):
    """Browser mode lets the page's own request through, and a declined answer is a status line, not an error."""
    pytest.importorskip('playwright.async_api')
    from test_web_slow import _run
    async def go(pg):
        ok = await pg.evaluate('p => post("/fs/add-root", {path: p})', str(folders[1]))
        hub.set_confirmer(Asked(False))
        said = await pg.evaluate('''async p => { try { await post("/fs/add-root", {path: p}); return 'added'; }
                                       catch (e) { return e.body.declined; } }''', str(folders[0]))
        return ok, said
    ok, said = _run(go, roots=[tmp_path/'start'] if (tmp_path/'start').mkdir() is None else [])
    assert ok == {'ok': True} and said is True
