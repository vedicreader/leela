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

def _logging_brew(tmp, app, bump=False, rc=0, tail=''):
    "A brew that logs each call's args and Homebrew env to `brew.log`, and on `bump` writes a newer Info.plist."
    plist, log = app/'Contents'/'Info.plist', tmp/'brew.log'
    up = f"python3 -I -c \"import plistlib,sys; open(sys.argv[1],'wb').write(plistlib.dumps({{'CFBundleShortVersionString':'99.0'}}))\" '{plist}'\n" if bump else ''
    return _brew(tmp, script=f'#!/bin/sh\necho "args $*" >> \'{log}\'\nenv | grep ^HOMEBREW_ | sort >> \'{log}\'\n'
                             f'echo "==> Upgrading leela"\n{up}echo "args $*"\n{tail}exit {rc}\n'), log

def test_the_upgrade_forces_a_fresh_tap_even_when_the_env_says_not_to(tmp_path, monkeypatch):
    "Homebrew fetched its taps once a day, so a cask pushed today read as nothing newer: the Update button said 'same'."
    for k in ('HOMEBREW_NO_AUTO_UPDATE', 'HOMEBREW_AUTO_UPDATE_CHECKED', 'HOMEBREW_AUTO_UPDATING'): monkeypatch.setenv(k, '1')
    monkeypatch.setenv('HOMEBREW_AUTO_UPDATE_SECS', '86400')
    app = _app(tmp_path); b, log = _logging_brew(tmp_path, app, bump=True)
    assert _run(U.Upgrade(app, str(b), '99.0')) == {'state': 'done', 'line': 'Leela 99.0 is installed.'}
    got = log.read_text().splitlines()
    assert got[0] == 'args upgrade --cask leela' and 'HOMEBREW_AUTO_UPDATE_SECS=0' in got
    assert not [l for l in got if l.startswith(('HOMEBREW_NO_AUTO_UPDATE', 'HOMEBREW_AUTO_UPDATE_CHECKED', 'HOMEBREW_AUTO_UPDATING'))]

def test_nothing_newer_runs_brew_update_once_then_says_homebrew_does_not_list_it_yet(tmp_path):
    "A brew.env setting can still skip the fetch, so one `brew update` and one more upgrade; then a plain message, not a vague error."
    app = _app(tmp_path); b, log = _logging_brew(tmp_path, app)
    got = _run(U.Upgrade(app, str(b), '99.0'))
    assert got == {'state': 'same', 'line': 'Homebrew does not list Leela 99.0 yet. Try again in a few minutes.'}
    assert [l for l in log.read_text().splitlines() if l.startswith('args')] == ['args upgrade --cask leela', 'args update', 'args upgrade --cask leela']

def test_a_failed_upgrade_is_an_error_with_its_last_line_and_no_retry_of_brew(tmp_path):
    app = _app(tmp_path); b, log = _logging_brew(tmp_path, app, rc=1)
    assert _run(U.Upgrade(app, str(b), '99.0')) == {'state': 'error', 'line': 'args upgrade --cask leela'}
    assert log.read_text().count('args ') == 1

def test_homebrew_lines_about_other_formulae_stay_out_of_the_bar(tmp_path):
    app = _app(tmp_path)
    # Single quotes: in double quotes `sh` runs the backticks, which is the real brew.
    b, _ = _logging_brew(tmp_path, app, rc=1, tail="echo 'You have 3 outdated formulae installed.'\necho 'Run `brew upgrade` to upgrade them.'\n")
    assert _run(U.Upgrade(app, str(b)))['line'] == 'args upgrade --cask leela'

def test_a_brew_that_hangs_is_stopped_and_said_so(tmp_path, monkeypatch):
    monkeypatch.setattr(U, 'WAIT', .5)
    app = _app(tmp_path); b = _brew(tmp_path, script='#!/bin/sh\necho start\nsleep 30\n')
    got = _run(U.Upgrade(app, str(b), '99.0'))
    assert got['state'] == 'error' and 'did not answer' in got['line']

def test_a_brew_that_cannot_start_is_an_error(tmp_path):
    assert _run(U.Upgrade(_app(tmp_path), str(tmp_path/'nope')))['state'] == 'error'

def test_an_upgrade_already_on_disk_is_done_without_brew_and_restart_is_allowed(tmp_path, monkeypatch):
    "brew upgraded earlier and Leela was not restarted: that is 'restart now', not 'Homebrew does not list it'."
    app = _app(tmp_path, '99.0'); b, log = _logging_brew(tmp_path, app)
    monkeypatch.setattr(U.shutil, 'which', lambda n: str(b)); monkeypatch.setattr(U, '_job', None)
    assert U.upgrade_status(app) == {'state': 'done', 'line': 'Leela 99.0 is installed.'}
    assert U.offer({'version': '99.0'}, app=app)['pending'] == '99.0'
    assert U.upgrade(app, '99.0')['state'] == 'done' and not log.exists()

def test_a_second_update_click_keeps_the_finished_job(tmp_path, monkeypatch):
    "A click from the dialog or a second window after 'done' started a new run that ended 'same', and Restart then refused."
    app = _app(tmp_path); b, log = _logging_brew(tmp_path, app, bump=True)
    monkeypatch.setattr(U.shutil, 'which', lambda n: str(b)); monkeypatch.setattr(U, '_job', None)
    U.upgrade(app, '99.0')
    end = time.monotonic() + 10
    while U.upgrade_status()['state'] == 'running' and time.monotonic() < end: time.sleep(.05)
    first = U._job
    assert U.upgrade(app, '99.0')['state'] == 'done' and U._job is first and log.read_text().count('args ') == 1

def test_a_fresh_check_skips_the_six_hour_cache_but_not_the_rate_floor(data, monkeypatch):
    calls = []
    monkeypatch.setattr(U, '_ask', lambda: calls.append(1) or ('v9.0.0', 'https://x/9.0.0'))
    monkeypatch.setattr(U, 'time', type('T', (), {'time': staticmethod(lambda: now)}))
    now = 1000; U.offer(app=False)
    now = 1000 + U.FRESH_TTL + 1
    assert U.offer(app=False)['latest'] == '9.0.0' and len(calls) == 1, 'the plain check keeps its cache'
    got = U.offer(app=False, fresh=True)
    assert len(calls) == 2 and not got['failed']
    U.offer(app=False, fresh=True)
    assert len(calls) == 2, 'two fresh checks inside the floor ask once'

def test_a_fresh_check_offline_says_it_failed_rather_than_up_to_date(data, monkeypatch):
    def down(): raise OSError('offline')
    monkeypatch.setattr(U, '_ask', down)
    assert U.offer(app=False, fresh=True)['failed']
    monkeypatch.setattr(U, '_ask', lambda: ('v0.0.1', 'u'))
    monkeypatch.setattr(U, 'time', type('T', (), {'time': staticmethod(lambda: 9e9)}))
    got = U.offer(app=False, fresh=True)
    assert not got['failed'] and not got['outdated']

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
    asked = []
    monkeypatch.setattr(U, 'latest_release', lambda ttl=U.TTL: asked.append(ttl) or {'version': '99.0', 'url': 'https://x'})
    with TestClient(ide_app(Workspace(roots=[]))) as c:
        got = c.get('/update').json()
        assert got['outdated'] and not got['notice'] and not got['install'], 'a source run shows nothing'
        assert got['job'] == {'state': 'idle', 'line': ''} and not got['failed']
        c.get('/update?fresh=1')
        assert asked == [U.TTL, U.FRESH_TTL], 'Check for updates asks past the cache'
        assert c.get('/update/status').json() == {'ok': True, 'state': 'idle', 'line': ''}
        assert c.post('/update/restart').json()['ok'] is False
        assert c.post('/update/install').json()['state'] == 'unavailable'

def test_the_models_dialog_row_is_the_notice_offer(tmp_path, monkeypatch):
    "The dialog linked to GitHub only, so a dismissed notice left no way to Update from the cask."
    from leela.blocks.agent import models as m
    app, b = _app(tmp_path), _brew(tmp_path)
    monkeypatch.setattr(m, '_latest_versions', lambda dists: {})
    monkeypatch.setattr(U, 'latest_release', lambda ttl=U.TTL: {'version': '99.0', 'url': 'https://x/99.0'})
    monkeypatch.setattr(U, 'app_bundle', lambda *a, **kw: app); monkeypatch.setattr(U, '_job', None)
    monkeypatch.setattr(U.shutil, 'which', lambda n: str(b))
    row = m.updates()['leela']
    assert row['install'] and row['outdated'] and row['url'] == 'https://x/99.0'
    monkeypatch.setattr(U.shutil, 'which', lambda n: None)
    row = m.updates()['leela']
    assert row['outdated'] and not row['install'], 'not from the cask: the release link'

def test_check_for_updates_is_in_the_app_menu_and_the_palette():
    from leela.blocks.keys.menus import BAR
    from leela.core.keys import lookup
    app = dict(BAR)['__app__']
    assert [r.action for r in app] == ['check_updates', '', 'settings', 'setup_models']
    k = lookup('check_updates')
    assert k.label == 'check for updates…' and not k.bound, 'a palette row, with no chord'
    root = Path(U.__file__).parents[1]/'static'
    assert "check_updates: () => leeUpdateCheck()," in (root/'lee-core.js').read_text()
    js = (root/'lee-ide.js').read_text()
    assert "api('/update?fresh=1')" in js and 'window.leeUpdateCheck = leeUpdateCheck' in js
