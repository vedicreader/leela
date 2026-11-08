"Host mode: the thin Mac app runs the server as its child. Health, the token, the dialogs, the env, pinned extras, the update switch."

import json, os, sys, threading, time
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest
from leela import hub
from leela.core import envs, host, update as U
from leela.blocks.agent import models
from leela.hub import WorkspaceHub
from test_folder_gate import _call, _guard, _hub, folders  # noqa: F401

TOKEN = 'tok-123'

class FakeHost:
    "The launcher's control server: answers per path, records each call and its token."
    def __init__(self, routes, status=200):
        self.calls, fake = [], self
        class H(BaseHTTPRequestHandler):
            def _do(self):
                n = int(self.headers.get('Content-Length') or 0)
                body = json.loads(self.rfile.read(n)) if n else None
                fake.calls.append((self.command, self.path, body, self.headers.get('Authorization')))
                r = routes.get((self.command, self.path), routes.get(self.path, {}))
                raw = (r(body) if callable(r) else r)
                raw = raw if isinstance(raw, bytes) else json.dumps(raw).encode()
                self.send_response(status); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
            do_GET = do_POST = _do
            def log_message(self, *a): pass
        self.srv = ThreadingHTTPServer(('127.0.0.1', 0), H)
        self.url = f'http://127.0.0.1:{self.srv.server_address[1]}'
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
    def close(self): self.srv.shutdown(); self.srv.server_close()

@pytest.fixture
def hosted(monkeypatch):
    "Host mode against a fake launcher; `hosted(routes)` starts it."
    made = []
    def go(routes=None, status=200):
        f = FakeHost(routes or {}, status); made.append(f)
        monkeypatch.setattr(host.client, 'state', dict(url=f.url, token=TOKEN))
        return f
    yield go
    for f in made: f.close()
    hub.reset_gate()

@pytest.fixture
def off(monkeypatch): monkeypatch.setattr(host.client, 'state', dict(url='', token=''))

# The token: one line on stdin, never in argv, env, a file or a log

def _pipe(data=None):
    "A pipe whose read end stands in for stdin; `data` is written and the write end closed, or kept open when None."
    r, w = os.pipe()
    if data is not None: os.write(w, data); os.close(w)
    return r, w

def test_take_reads_one_token_line_from_stdin_then_puts_stdin_on_devnull(monkeypatch):
    monkeypatch.setattr(host.client, 'state', dict(url='', token=''))
    r, _ = _pipe(f'{TOKEN}\nrest of the input\n'.encode())
    env = dict(LEELA_HOST_URL='http://127.0.0.1:9', LEELA_APP_VERSION='1.0.0')
    assert host.take(env, fd=r, timeout=2) and host.client.state == dict(url='http://127.0.0.1:9', token=TOKEN)
    assert 'LEELA_HOST_URL' not in env and env['LEELA_APP_VERSION'] == '1.0.0'
    assert os.read(r, 100) == b'', 'stdin now reads /dev/null: the rest never reaches a kernel'
    os.close(r)

@pytest.mark.parametrize('data', [b'', b'\n', None], ids=['closed', 'empty line', 'never comes'])
def test_host_mode_refuses_to_start_with_no_token_line(monkeypatch, data):
    monkeypatch.setattr(host.client, 'state', dict(url='', token=''))
    r, w = _pipe(data)
    with pytest.raises(SystemExit, match='no token line came on stdin'): host.take(dict(LEELA_HOST_URL='http://127.0.0.1:9'), fd=r, timeout=.3)
    assert not host.on()
    os.close(r)
    if data is None: os.close(w)

def test_a_token_in_the_environment_is_ignored_with_a_warning(monkeypatch, capsys):
    monkeypatch.setattr(host.client, 'state', dict(url='', token=''))
    r, _ = _pipe(b'from-stdin\n')
    env = dict(LEELA_HOST_URL='http://127.0.0.1:9', LEELA_HOST_TOKEN='from-env')
    host.take(env, fd=r, timeout=2)
    assert host.client.state['token'] == 'from-stdin' and 'LEELA_HOST_TOKEN' not in env
    assert 'LEELA_HOST_TOKEN in the environment is ignored' in capsys.readouterr().err
    os.close(r)

def test_no_url_is_no_host_mode_and_stdin_is_not_read(monkeypatch):
    monkeypatch.setattr(host.client, 'state', dict(url='', token=''))
    r, w = _pipe(None)
    assert not host.take(dict(LEELA_HOST_TOKEN='t'), fd=r, timeout=.1)
    os.write(w, b'x'); assert os.read(r, 1) == b'x', 'stdin untouched'
    os.close(r); os.close(w)

@pytest.mark.parametrize('url', ['http://127.0.0.1@evil.example:80', 'https://127.0.0.1:9', 'http://localhost:9', 'http://10.0.0.1:9', 'http://127.0.0.1'])
def test_the_client_talks_only_to_a_loopback_http_url(monkeypatch, url):
    monkeypatch.setattr(host.client, 'state', dict(url=url, token=TOKEN))
    with pytest.raises(host.HostError): host.call('/status')

def test_a_proxy_in_the_environment_is_not_used(hosted, monkeypatch):
    f = hosted({'/status': {'ok': True}})
    monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:1'); monkeypatch.setenv('http_proxy', 'http://127.0.0.1:1')
    assert host.status() == {'ok': True} and f.calls[0][3] == f'Bearer {TOKEN}'

# The environment

def test_import_login_env_skips_what_the_launcher_owns_only_in_host_mode(monkeypatch, off):
    shell = dict(PYTHONPATH='/x', VIRTUAL_ENV='/v', UV_INDEX='i', CONDA_PREFIX='/c', LEELA_HOST_TOKEN='stolen', OPENAI_API_KEY='k')
    monkeypatch.setattr(envs, 'shell_env', lambda *a, **kw: dict(shell))
    target = {}
    envs.import_login_env(env=target)
    assert set(target) >= {'PYTHONPATH', 'VIRTUAL_ENV', 'UV_INDEX', 'OPENAI_API_KEY'}, 'outside host mode nothing changes'
    monkeypatch.setattr(host.client, 'state', dict(url='http://127.0.0.1:9', token=TOKEN))
    target = {}
    envs.import_login_env(env=target)
    assert target == {'OPENAI_API_KEY': 'k', 'UV_INDEX': 'i'}, "the person's uv settings reach their kernels, shells and project builds, as in the old app"

def test_stored_values_do_not_replace_the_launchers_in_host_mode(monkeypatch):
    monkeypatch.setattr(envs, 'stored_env', lambda: dict(VIRTUAL_ENV='/old', UV_CACHE_DIR='/c', LEELA_LOCK_N='99', OPENAI_API_KEY='k'))
    monkeypatch.setattr(host.client, 'state', dict(url='http://127.0.0.1:9', token=TOKEN))
    target = dict(VIRTUAL_ENV='/app/env', LEELA_LOCK_N='3')
    envs.apply_stored_env(target)
    assert target == dict(VIRTUAL_ENV='/app/env', LEELA_LOCK_N='3', OPENAI_API_KEY='k', UV_CACHE_DIR='/c')
    with pytest.raises(envs.EnvError): envs.set_env('LEELA_LOCK_N', 'x')

APP_1_0 = dict(UV_NO_CONFIG='1', UV_CACHE_DIR='/c', UV_PYTHON_INSTALL_DIR='/py', UV_PYTHON_PREFERENCE='only-managed', UV_PYTHON='3.12.16',
               UV_PROJECT_ENVIRONMENT=sys.prefix, UV_FROZEN='1', UV_NO_PROGRESS='1', UV_LINK_MODE='clone', PYTHONNOUSERSITE='1', NO_COLOR='1')

def test_host_setup_takes_out_what_app_1_0_gave_and_keeps_the_persons_own(monkeypatch):
    "App 1.0.0's launcher gave the server uv's build settings, VIRTUAL_ENV and its env's bin first; every kernel and shell inherited them."
    import leela
    called = []
    for k, v in APP_1_0.items(): monkeypatch.setenv(k, v)
    monkeypatch.setenv('VIRTUAL_ENV', sys.prefix)
    monkeypatch.setenv('PATH', os.pathsep.join([os.path.join(sys.prefix, 'bin'), '/opt/homebrew/bin', '/usr/bin']))
    monkeypatch.setattr(leela, 'use_login_path', lambda: os.environ['PATH'])
    monkeypatch.setattr(leela, 'use_extras', lambda: called.append('extras'))
    monkeypatch.setattr(envs, 'import_login_env', lambda *a, **kw: [])
    monkeypatch.setattr(envs, 'stored_env', lambda: dict(PYTHONNOUSERSITE='1', UV_INDEX='i'))
    monkeypatch.setattr(host.client, 'state', dict(url='http://127.0.0.1:9', token=TOKEN))
    host.setup()
    assert [k for k in os.environ if k.startswith('UV_')] == ['UV_INDEX'] and 'VIRTUAL_ENV' not in os.environ and 'NO_COLOR' not in os.environ
    assert os.environ['PATH'] == '/opt/homebrew/bin:/usr/bin' and not called
    assert os.environ['PYTHONNOUSERSITE'] == '1', 'a stored value is the person\'s, and outlives the scrub'
    assert hub._gate['confirm'] is host.confirm
    hub.reset_gate()

def test_unbuild_keeps_another_venv_and_every_other_path(tmp_path):
    e = host.unbuild(dict(VIRTUAL_ENV=str(tmp_path/'proj'), PATH=f'{tmp_path}/env/bin:/usr/bin:{tmp_path}/env/bin', UV_FROZEN='1', OPENAI_API_KEY='k'), prefix=tmp_path/'env')
    assert e == dict(VIRTUAL_ENV=str(tmp_path/'proj'), PATH='/usr/bin', OPENAI_API_KEY='k')

def test_is_app_is_frozen_or_host_mode(monkeypatch, off):
    assert not host.is_app()
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    assert host.is_app()
    monkeypatch.delattr(sys, 'frozen')
    monkeypatch.setattr(host.client, 'state', dict(url='http://127.0.0.1:9', token=TOKEN))
    assert host.is_app()

def test_the_setup_pane_shows_in_host_mode(monkeypatch, off):
    from leela.blocks.agent import models
    assert models.setup_plan()['frozen'] is False
    monkeypatch.setattr(host.client, 'state', dict(url='http://127.0.0.1:9', token=TOKEN))
    assert models.setup_plan()['frozen'] is True

def test_find_server_takes_the_envs_own_language_server_in_host_mode(monkeypatch, tmp_path, off):
    from leela.blocks.lsp import lsp
    (b := tmp_path/'bin').mkdir(); (s := b/'basedpyright-langserver').write_text('#!/bin/sh\n'); s.chmod(0o755)
    monkeypatch.setattr('shutil.which', lambda name: None)
    monkeypatch.setattr('leela.extras_bin', lambda: tmp_path/'no-extras')
    monkeypatch.setattr(lsp.sysconfig, 'get_path', lambda name: str(b))
    assert lsp.find_server() == (None, None), 'outside the app the dev venv is on PATH already'
    monkeypatch.setattr(host.client, 'state', dict(url='http://127.0.0.1:9', token=TOKEN))
    assert lsp.find_server() == ('basedpyright-langserver', [str(s), '--stdio'])

def test_cli_in_host_mode_takes_the_token_and_never_adds_the_extras_folder(monkeypatch):
    import leela, leela.cli, leela.app
    seen = {}
    monkeypatch.setattr(host.client, 'state', dict(url='', token=''))
    monkeypatch.setenv('LEELA_HOST_URL', 'http://127.0.0.1:9')
    r, _ = _pipe(f'{TOKEN}\n'.encode())
    take = host.take
    monkeypatch.setattr(host, 'take', lambda: take(fd=r, timeout=2))
    monkeypatch.setattr(host, 'setup', lambda: seen.setdefault('setup', True))
    monkeypatch.setattr(leela, 'use_extras', lambda: seen.setdefault('extras', True))
    monkeypatch.setattr(leela.app, 'serve_ide', lambda roots, **kw: seen.update(kw))
    leela.cli.main(['--app', '--shell', 'none', '--port', '5999', '--gateway-port', '0'])
    assert seen.get('setup') and 'extras' not in seen and seen['shell'] == 'none' and seen['app_window']
    assert host.client.state['token'] == TOKEN and not any(TOKEN in v for v in os.environ.values())
    os.close(r)

# /health and the launcher's routes

def test_health_answers_status_version_and_the_lock_as_a_number(monkeypatch):
    from leela import __version__
    monkeypatch.setenv('LEELA_LOCK_N', '7')
    for m in ('GET', 'HEAD'): assert _call(WorkspaceHub([], 5001), '/health', method=m) == (200, {'status': 'ok', 'version': __version__, 'lock_n': 7})
    monkeypatch.delenv('LEELA_LOCK_N')
    assert _call(WorkspaceHub([], 5001), '/health', method='GET')[1]['lock_n'] is None
    assert _call(WorkspaceHub([], 5001), '/health', method='POST')[0] == 405

def test_health_stays_behind_the_host_guard():
    assert _guard('GET', {'host': 'evil.example'}, path='/health') == 421
    assert _guard('GET', {}, path='/health') == 'passed'

def test_the_menu_and_recent_routes_carry_no_secret_and_need_none(hosted):
    """The launcher sends the server nothing secret: a process that took the port first learns nothing."""
    hosted()
    st, body = _call(WorkspaceHub([], 5001), '/app/menu.json', method='GET')
    titles = [m['title'] for m in body['menus']]
    assert st == 200 and titles[0] == '__app__' and 'Edit' in titles
    edit = next(m for m in body['menus'] if m['title'] == 'Edit')['items']
    # the launcher runs beside this server, so the menu takes this platform's keys: AppKit masks on a Mac, a Ctrl label elsewhere
    copy = {'title': 'Copy', 'selector': 'copy:', 'key': 'c', 'mask': 1 << 20} if sys.platform == 'darwin' else {'title': 'Copy', 'selector': 'copy:', 'chord': 'Ctrl+C'}
    assert copy in edit and {'sep': True} in edit
    assert _call(WorkspaceHub([], 5001), '/app/recent', method='GET')[0] == 200

def _grants(issued):
    "A fake launcher that says yes to each `(nonce, path)` it issued, once."
    def check(b):
        k = (b['nonce'], b['path'])
        return {'ok': issued.pop(k, None) is not None}
    return {('POST', '/grant'): check}

def test_a_grant_from_the_launcher_lets_the_next_page_open_pass_with_no_question(hosted, tmp_path, folders):
    """A folder picked in the app's own dialog is trusted, as `shell_api().on_picked = grant` made it in the fat app."""
    from test_folder_gate import Asked
    mine = folders[0]
    hosted(_grants({('n1', str(mine)): True}))
    h, _ = _hub(tmp_path)
    hub.set_confirmer(asked := Asked(False))
    assert _call(h, '/hub/grant', f'path={mine}&grant=n1'.encode())[0] == 200
    assert _call(h, '/hub/grant', f'path={mine}&grant=n1'.encode())[0] == 401, 'a nonce works once'
    assert _call(h, '/hub/grant', f'path={mine}'.encode())[0] == 401
    st, body = _call(h, '/hub/open', f'path={mine}'.encode())
    assert st == 200 and body['ok'] and not asked.qs

def test_hub_open_with_a_launcher_grant_is_trusted_and_a_forged_one_refused(hosted, tmp_path, folders):
    from test_folder_gate import Asked
    mine, proj = folders
    f = hosted(_grants({('n2', str(mine)): True}))
    h, _ = _hub(tmp_path)
    hub.set_confirmer(asked := Asked(False))
    st, body = _call(h, '/hub/open', f'path={mine}&also={proj}&grant=n2'.encode())
    assert st == 200 and body['ok'] and not asked.qs
    assert f.calls[-1][2] == {'nonce': 'n2', 'path': str(mine)} and f.calls[-1][3] == f'Bearer {TOKEN}', 'the server asks the launcher; the token goes only that way'
    st, body = _call(h, '/hub/open', f'path={proj}&grant=forged'.encode())
    assert st == 401 and body == {'ok': False, 'error': hub.BAD_GRANT, 'config': hub.cfg_mark()}

def test_a_grant_with_no_launcher_is_refused(off, tmp_path, folders):
    h, _ = _hub(tmp_path)
    assert _call(h, '/hub/open', f'path={folders[0]}&grant=x'.encode())[0] == 401

# The app's dialog

def test_confirm_asks_the_app_and_takes_its_answer(hosted):
    f = hosted({'/confirm': lambda b: {'answer': b['question'] == 'Add x?'}})
    assert host.confirm('Add x?') is True and host.confirm('Add y?') is False
    assert f.calls[0][:3] == ('POST', '/confirm', {'question': 'Add x?'}) and f.calls[0][3] == f'Bearer {TOKEN}'

@pytest.mark.parametrize('answer,status', [(b'not json', 200), ({'ok': True}, 200), ({'answer': 'yes'}, 200), ({'answer': True}, 401), ({}, 500)])
def test_every_broken_answer_is_no_window_and_records_no_decline(hosted, tmp_path, folders, answer, status):
    """`admit_folder` takes any exception but `NoWindow` as a No and then refuses the folder for 10 minutes."""
    hosted({'/confirm': answer}, status)
    h, _ = _hub(tmp_path)
    hub.set_confirmer(host.confirm)
    st, body = _call(h, '/hub/open', f'path={folders[0]}'.encode())
    assert st == 403 and body['error'] == hub.NO_WINDOW and not hub.declined(folders[0])

def test_a_launcher_that_is_gone_is_no_window(monkeypatch, tmp_path, folders):
    import socket
    with socket.socket() as s: s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]
    monkeypatch.setattr(host.client, 'state', dict(url=f'http://127.0.0.1:{port}', token=TOKEN))
    t = time.monotonic()
    with pytest.raises(hub.NoWindow): host.confirm('Add?')
    assert time.monotonic() - t < 3

# Pinned extras

def test_outside_host_mode_an_install_is_pinned_and_never_upgrades(off, monkeypatch):
    ran = []
    monkeypatch.setattr(models.threading, 'Thread', lambda target, args, **kw: type('T', (), {'start': lambda s: ran.append(args)})())
    monkeypatch.setitem(models._installs, 'langserver', {})
    models._installs.pop('langserver')
    row = models.install_runtime('langserver')
    cmd = ran[0][1]
    assert '--upgrade' not in cmd and 'basedpyright==1.39' in cmd and row['requirements'] == ['basedpyright==1.39']

def test_pinned_keeps_an_exact_pin_and_holds_a_floor():
    assert models.pinned(['a==1.2', 'b>=3.1', 'c[x]>=2', 'd>=1,<2']) == ['a==1.2', 'b==3.1', 'c[x]==2', 'd==1']
    assert models.pinned(['numpy'])[0].startswith('numpy==')

def test_in_host_mode_an_install_asks_the_app_and_runs_no_pip(hosted, monkeypatch):
    seen = {'n': 0}
    def status(_):
        seen['n'] += 1
        return {'extras': {'langserver': {'state': 'ok' if seen['n'] > 1 else 'running', 'log': 'Installed 1 package'}}}
    f = hosted({('POST', '/extras'): {'ok': True}, '/status': status})
    monkeypatch.setattr(models, '_installer', lambda t: pytest.fail('pip must not run in host mode'))
    models._installs.pop('langserver', None)
    row = models.install_runtime('langserver')
    assert row['state'] == 'running' and row['via'] == 'Leela app'
    assert models.install_runtime('langserver')['state'] == 'running', 'a second click joins the running install'
    end = time.monotonic() + 10
    while models.install_state('langserver')['state'] == 'running' and time.monotonic() < end: time.sleep(.1)
    got = models.install_state('langserver')
    assert got['state'] == 'ok' and 'Installed 1 package' in got['log'] and 'available' in got
    assert ('POST', '/extras', {'name': 'langserver'}, f'Bearer {TOKEN}') in f.calls

def test_in_host_mode_a_failed_or_silent_app_marks_the_install_error(hosted):
    hosted({('POST', '/extras'): {'ok': True}, '/status': {'extras': {'mlx': {'state': 'error', 'log': 'no network'}}}})
    models._installs['mlx'] = {'runtime': 'mlx', 'state': 'running'}
    models._host_install('mlx', every=.05)
    assert models.install_state('mlx')['state'] == 'error' and 'no network' in models.install_state('mlx')['log']

@pytest.mark.skipif(sys.platform != 'darwin', reason='mlx installs only on Apple Silicon')
def test_the_install_route_reaches_the_app_in_host_mode(hosted, monkeypatch):
    from unittest.mock import MagicMock
    from fasthtml.common import FastHTML
    from starlette.testclient import TestClient
    from leela.blocks.agent import app as agent_app
    hosted()
    monkeypatch.setattr(models, '_host_install', lambda r, **kw: None)
    models._installs.pop('mlx', None)
    agent_app.connect(a := FastHTML(), MagicMock())
    got = TestClient(a).post('/agent/runtimes/install', json={'runtime': 'mlx'}).json()
    assert got['ok'] and got['install']['via'] == 'Leela app' and got['install']['state'] == 'running'

# The update switch

def test_lock_and_app_tags_are_never_a_leela_release(monkeypatch, tmp_path):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
    for tag in ('lock-7', 'app-v1.0.0'):
        monkeypatch.setattr(U, 'urljson', lambda *a, **kw: {'tag_name': tag, 'html_url': f'https://x/{tag}'})
        with pytest.raises(ValueError): U._ask()
    assert 'version' not in U.latest_release(now=1, ttl=0), 'nothing cached that hides a real release'

def test_the_newest_app_skips_drafts_prereleases_and_other_tags(monkeypatch, tmp_path):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
    rows = [{'tag_name': 'lock-9', 'html_url': 'l'}, {'tag_name': 'app-v1.2.0', 'draft': True, 'html_url': 'd'},
            {'tag_name': 'app-v1.1.0', 'prerelease': True, 'html_url': 'p'}, {'tag_name': '0.1.30', 'html_url': 'v'},
            {'tag_name': 'app-v1.0.1', 'html_url': 'https://x/app-v1.0.1'}]
    monkeypatch.setattr(U, 'urljson', lambda *a, **kw: rows)
    assert U.newest_app(now=1)['version'] == '1.0.1'

@pytest.mark.parametrize('app_new,lock_new,needs,brew,want', [
    (True, False, False, True, 'app'), (True, True, True, True, 'app'),
    (False, True, False, True, 'lock'), (False, True, False, False, 'lock'),
    (False, True, True, True, 'app-needed'),
    (True, False, False, False, 'download'), (False, True, True, False, 'download'), (True, True, False, False, 'download'),
    (False, False, False, True, 'none'), (False, False, False, False, 'none')])
def test_each_row_of_the_update_table(app_new, lock_new, needs, brew, want):
    assert U.kind(app_new, lock_new, needs, brew) == want

def _st(newer=False, needs=False, brew=True, app_min=None): return {'brew': brew, 'lock': {'current_n': 3, 'newest_n': 4 if newer else 3, 'newer': newer, 'needs_app': needs, 'app_min': app_min}}

def test_host_offer_shapes_for_each_kind(monkeypatch):
    monkeypatch.setattr(host.client, 'state', dict(url='http://127.0.0.1:9', token=TOKEN))
    monkeypatch.setenv('LEELA_APP_VERSION', '1.0.0')
    rel = {'version': '1.1.0', 'url': 'https://x/app-v1.1.0'}
    o = U._host_offer(_st(), rel)
    assert o['kind'] == 'app' and o['notice'] and o['install'] and o['current'] == '1.0.0' and o['latest'] == '1.1.0'
    o = U._host_offer(_st(newer=True), {'version': '1.0.0'})
    assert o['kind'] == 'lock' and o['install'] and o['newest_lock'] == 4
    o = U._host_offer(_st(newer=True, needs=True, app_min='1.2.0'), {'version': '1.0.0'})
    assert o['kind'] == 'app-needed' and o['notice'] and not o['install'] and o['latest'] == '1.2.0'
    o = U._host_offer(_st(brew=False), rel)
    assert o['kind'] == 'download' and not o['install']
    o = U._host_offer({}, rel)
    assert o['kind'] == 'none' and not o['notice'], 'a silent launcher still gives a valid offer'

def test_host_install_status_and_restart_go_through_the_launcher(hosted, monkeypatch):
    f = hosted({('POST', '/update'): {'state': 'running', 'line': 'building'}, ('GET', '/update'): {'state': 'ready', 'line': ''},
                '/status': _st(newer=True), '/restart': {'ok': True}})
    monkeypatch.setenv('LEELA_APP_VERSION', '1.0.0')
    monkeypatch.setattr(U, 'newest_app', lambda ttl=U.TTL: {'version': '1.0.0'})
    assert U.upgrade() == {'state': 'running', 'line': 'building'}
    assert U.upgrade_status() == {'state': 'done', 'line': ''}, "the launcher's ready is the page's done"
    assert U.restart() is True
    assert ('POST', '/update', {'kind': 'lock'}, f'Bearer {TOKEN}') in f.calls and any(c[1] == '/restart' for c in f.calls)

def test_the_update_routes_reach_the_launcher(hosted, monkeypatch):
    from starlette.testclient import TestClient
    from leela.blocks.settings import app as settings_app
    hosted({('POST', '/update'): {'state': 'ready'}, ('GET', '/update'): {'state': 'ready'}, '/status': _st(newer=True), '/restart': {'ok': True}})
    monkeypatch.setenv('LEELA_APP_VERSION', '1.0.0')
    monkeypatch.setattr(U, 'newest_app', lambda ttl=U.TTL: {'version': '1.0.0'})
    from types import SimpleNamespace
    from fasthtml.common import FastHTML
    settings_app.connect(a := FastHTML(), SimpleNamespace(session=None))
    c = TestClient(a)
    assert c.get('/update').json()['kind'] == 'lock'
    assert c.post('/update/install').json()['state'] == 'done'
    assert c.post('/update/restart').json()['ok'] is True

def test_host_mode_down_gives_an_error_state_not_an_exception(monkeypatch):
    import socket
    with socket.socket() as s: s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]
    monkeypatch.setattr(host.client, 'state', dict(url=f'http://127.0.0.1:{port}', token=TOKEN))
    assert U.upgrade_status()['state'] == 'error' and U.restart() is False
    assert U.offer()['kind'] == 'none'

def test_host_mode_offers_to_remove_the_old_extras_folder_and_removes_only_it(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from fasthtml.common import FastHTML
    from starlette.testclient import TestClient
    from leela.blocks.settings import app as settings_app
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
    site = tmp_path/'leela'/'extras'/'lib'/'python3.12'/'site-packages'/'mlx'
    site.mkdir(parents=True); (site/'x.so').write_bytes(b'0' * 2**20); (tmp_path/'leela'/'keep.json').write_text('{}')
    monkeypatch.setattr(host.client, 'state', dict(url='', token=''))
    assert U.old_extras() is None and not U.remove_old_extras(), 'outside host mode the fat app still uses it'
    monkeypatch.setattr(host.client, 'state', dict(url='http://127.0.0.1:9', token=TOKEN))
    assert U.old_extras() == {'path': str(tmp_path/'leela'/'extras'), 'mb': 1}
    assert U._host_offer({}, {})['old_extras']['mb'] == 1
    settings_app.connect(a := FastHTML(), SimpleNamespace(session=None))
    assert TestClient(a).post('/update/old-extras').json() == {'ok': True}
    assert not (tmp_path/'leela'/'extras').exists() and (tmp_path/'leela'/'keep.json').is_file()
    assert U.old_extras() is None

def test_the_agent_tools_are_linked_without_python_pip_or_uv(tmp_path):
    src, dst = tmp_path/'env'/'bin', tmp_path/'bin'
    src.mkdir(parents=True); dst.mkdir()
    for n in ('ramabana', 'kosha', 'python', 'pip', 'uv'): (src/n).write_text('#!/bin/sh\n')
    (dst/'old-tool').symlink_to(src/'kosha')
    host.link_tools(['ramabana', 'kosha', 'gone'], src, dst)
    assert sorted(p.name for p in dst.iterdir()) == ['kosha', 'ramabana'] and (dst/'kosha').resolve() == src/'kosha'
    names = host.agent_scripts()
    assert {'ramabana', 'kosha', 'exhash'} <= set(names) and not [n for n in names if n.startswith(('python', 'pip', 'uv'))]
    assert host.tools_dir(tmp_path/'Leela'/'envs'/'abc') == tmp_path/'Leela'/'bin'

def test_the_agent_shell_has_the_tools_after_the_projects_venv(monkeypatch, tmp_path):
    "An agent's shell runs `ramabana` and `kosha` from the app's env, and `python` stays the project's."
    import sys as _sys
    from leela.blocks.agent.ai import WorkspaceHost
    (tools := tmp_path/'bin').mkdir()
    (proj := tmp_path/'p'/'.venv'/'bin').mkdir(parents=True); os.symlink(_sys.executable, proj/'python')
    monkeypatch.setattr(host.client, 'tools_dir', lambda prefix=None: tools)
    monkeypatch.setenv('PATH', '/usr/bin:/bin'); monkeypatch.setenv('UV_INDEX_URL', 'https://mine.example/simple')
    assert WorkspaceHost._env(SimpleNamespace(ws=None), tmp_path/'p')['PATH'].split(os.pathsep)[0] == str(proj), 'outside host mode there is no tools folder'
    monkeypatch.setattr(host.client, 'state', dict(url='http://127.0.0.1:9', token=TOKEN))
    e = WorkspaceHost._env(SimpleNamespace(ws=None), tmp_path/'p')
    assert e['PATH'].split(os.pathsep)[:3] == [str(proj), str(tools), '/usr/bin'] and e['UV_INDEX_URL'] == 'https://mine.example/simple'

def test_a_fresh_check_in_host_mode_asks_github_now_and_says_whether_it_failed(hosted, monkeypatch):
    "Check for updates… asks past the cache; the page tells a failed check from an up-to-date app, and sees a lock that waits for a restart."
    hosted({('GET', '/update'): {'state': 'ready', 'line': ''}, '/status': _st(newer=True)})
    monkeypatch.setenv('LEELA_APP_VERSION', '1.0.0')
    asked = []
    monkeypatch.setattr(U, 'newest_app', lambda ttl=U.TTL: asked.append(ttl) or {'version': '1.0.0'})
    o = U.offer(fresh=True)
    assert asked == [U.FRESH_TTL] and o['kind'] == 'lock' and not o['failed'] and o['job']['state'] == 'done' and o['pending'] == 'package set 4'
    monkeypatch.setattr(U, 'newest_app', lambda ttl=U.TTL: {'failed': True})
    assert U.offer(fresh=True)['failed']

def test_an_app_or_lock_tag_is_not_a_failed_check(monkeypatch, tmp_path):
    "On the thin app's repo the newest release can be `app-v1.0.0` or `lock-3`; only a network error is a failed check."
    monkeypatch.setattr(U, '_cache', lambda name='release.json': tmp_path/name)
    def ask(): raise ValueError('lock-3 is not a Leela release')
    monkeypatch.setattr(U, '_ask', ask)
    assert not U.latest_release(ttl=0).get('failed')
    def down(): raise OSError('offline')
    monkeypatch.setattr(U, '_ask', down)
    assert U.latest_release(ttl=0)['failed']
