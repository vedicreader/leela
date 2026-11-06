"The update notice: the release check, what the app offers, and the Homebrew step. No network, no window."

import plistlib, sys, time
from pathlib import Path

import pytest

from leela.core import update as U


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path/'data'))
    return tmp_path

def test_the_release_is_asked_once_per_ttl_and_cached_on_disk(data, monkeypatch):
    calls = []
    monkeypatch.setattr(U, '_ask', lambda: calls.append(1) or ('v9.0.0', 'https://x/9.0.0'))
    got = U.latest_release(now=1000)
    assert got['version'] == '9.0.0' and got['url'] == 'https://x/9.0.0'
    assert U.latest_release(now=1000 + U.TTL - 1)['version'] == '9.0.0' and len(calls) == 1
    U.latest_release(now=1000 + U.TTL + 1)
    assert len(calls) == 2 and (data/'data'/'leela'/'release.json').is_file()

def test_offline_is_silent_and_waits_a_ttl_before_asking_again(data, monkeypatch):
    calls = []
    def down(): calls.append(1); raise OSError('offline')
    monkeypatch.setattr(U, '_ask', down)
    assert 'version' not in U.latest_release(now=1000)
    U.latest_release(now=1001)
    assert len(calls) == 1, 'a failed check counts as a check'

def test_a_bad_cache_file_is_asked_over(data, monkeypatch):
    (c := data/'data'/'leela'/'release.json').parent.mkdir(parents=True); c.write_text('{not json')
    monkeypatch.setattr(U, '_ask', lambda: ('1.0', 'u'))
    assert U.latest_release()['version'] == '1.0'

def test_a_rate_limited_api_falls_back_to_the_release_page_redirect(monkeypatch):
    class R:
        url = 'https://github.com/vedicreader/leela/releases/tag/0.2.0'
        def __enter__(self): return self
        def __exit__(self, *a): pass
    def refused(*a, **kw): raise OSError('HTTP Error 403: rate limit exceeded')
    monkeypatch.setattr(U, 'urljson', refused)
    monkeypatch.setattr(U.urllib.request, 'urlopen', lambda req, timeout: R())
    assert U._ask() == ('0.2.0', R.url)

def test_newer_compares_versions_not_strings():
    assert U.newer('0.1.10', '0.1.9') and not U.newer('0.1.9', '0.1.10') and not U.newer('0.1.9', '0.1.9')
    assert not U.newer(None, '0.1.9') and not U.newer('junk', '0.1.9')

def test_only_the_frozen_mac_app_has_a_bundle():
    assert U.app_bundle(frozen=False) is None
    assert U.app_bundle('/Applications/Leela.app/Contents/MacOS/python', frozen=True, platform='darwin') == Path('/Applications/Leela.app')
    assert U.app_bundle('/x/Leela.app/Contents/MacOS/python', frozen=True, platform='win32') is None

def _brew(tmp, cask=True, script='#!/bin/sh\necho ok\n'):
    (b := tmp/'brew'/'bin'/'brew').parent.mkdir(parents=True); b.write_text(script); b.chmod(0o755)
    if cask: (tmp/'brew'/'Caskroom'/'leela').mkdir(parents=True)
    return b

def _app(tmp, version='0.1.0'):
    (p := tmp/'Applications'/'Leela.app'/'Contents').mkdir(parents=True, exist_ok=True)
    (p/'Info.plist').write_bytes(plistlib.dumps({'CFBundleShortVersionString': version}))
    return p.parent

def test_dev_runs_get_no_notice_and_the_cask_app_can_install(tmp_path, monkeypatch):
    rel = {'version': '99.0', 'url': 'https://x/99.0'}
    dev = U.offer(rel, app=False)
    assert dev['outdated'] and not dev['notice'] and not dev['install'] and dev['url'] == 'https://x/99.0'
    app, b = _app(tmp_path), _brew(tmp_path)
    monkeypatch.setattr(U.shutil, 'which', lambda n: str(b))
    assert U.offer(rel, app=app)['install']
    assert not U.offer({'version': U.__version__}, app=app)['notice'], 'an app on the latest release says nothing'

def test_an_app_not_from_the_cask_gets_the_link_and_no_install(tmp_path, monkeypatch):
    app, b = _app(tmp_path), _brew(tmp_path, cask=False)
    monkeypatch.setattr(U.shutil, 'which', lambda n: str(b))
    got = U.offer({'version': '99.0'}, app=app)
    assert got['notice'] and not got['install']
    assert U.upgrade(app)['state'] == 'unavailable'
    monkeypatch.setattr(U.shutil, 'which', lambda n: None)
    assert U.brew_for(app) is None, 'no brew on PATH'

def _run(job, wait=10):
    job.start()
    end = time.monotonic() + wait
    while job.state == 'running' and time.monotonic() < end: time.sleep(.05)
    return job.status()

@pytest.mark.parametrize('rc,bumps,want', [(0, True, 'done'), (0, False, 'same'), (1, False, 'error')])
def test_the_upgrade_reports_its_last_line_and_how_it_ended(tmp_path, rc, bumps, want):
    app = _app(tmp_path)
    plist = app/'Contents'/'Info.plist'
    bump = f"python3 -I -c \"import plistlib,sys; open(sys.argv[1],'wb').write(plistlib.dumps({{'CFBundleShortVersionString':'0.2.0'}}))\" '{plist}'\n" if bumps else ''
    b = _brew(tmp_path, script=f'#!/bin/sh\necho "==> Upgrading leela"\n{bump}echo "args $*"\n\nexit {rc}\n')
    got = _run(U.Upgrade(app, str(b)))
    assert got == {'state': want, 'line': 'args upgrade --cask leela'}

def test_a_brew_that_cannot_start_is_an_error(tmp_path):
    assert U.Upgrade(_app(tmp_path), str(tmp_path/'nope')).start()['state'] == 'error'

def test_restart_opens_the_app_after_this_process_quits(tmp_path, monkeypatch):
    spawned, timers = [], []
    monkeypatch.setattr(U.subprocess, 'Popen', lambda args, **kw: spawned.append((args, kw)))
    monkeypatch.setattr(U.threading, 'Timer', lambda t, fn, args: timers.append((fn, args)) or type('T', (), {'start': lambda s: None})())
    assert not U.restart(), 'a source run has no app to reopen'
    assert U.restart(app=tmp_path/'Leela.app', pid=4242)
    (args, kw), = spawned
    assert args[:2] == ['/bin/sh', '-c'] and args[3:5] == ['4242', str(tmp_path/'Leela.app')] and kw['start_new_session']
    assert timers == [(U.os.kill, (4242, U.signal.SIGTERM))]

def test_the_routes_refuse_a_restart_before_an_upgrade_finished(monkeypatch):
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.workspace import Workspace
    monkeypatch.setattr(U, '_job', None)
    monkeypatch.setattr(U, 'latest_release', lambda: {'version': '99.0', 'url': 'https://x'})
    with TestClient(ide_app(Workspace(roots=[]))) as c:
        got = c.get('/update').json()
        assert got['outdated'] and not got['notice'] and not got['install'], 'a source run shows nothing'
        assert c.get('/update/status').json() == {'ok': True, 'state': 'idle', 'line': ''}
        assert c.post('/update/restart').json()['ok'] is False
        assert c.post('/update/install').json()['state'] == 'unavailable'
