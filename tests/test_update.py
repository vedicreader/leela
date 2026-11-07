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

@pytest.fixture(autouse=True)
def login(tmp_path, monkeypatch):
    "Never the person's shell, Leela store or ~/Library/Logs: a fake login env, no stored env, a log under `tmp_path`."
    env = {'HOME': str(tmp_path), 'USER': 'pat', 'LANG': 'en_AU.UTF-8', 'PATH': str(tmp_path/'brew'/'bin'), 'https_proxy': 'http://own:1', 'TMPDIR': '/x'}
    monkeypatch.setattr(U, 'shell_env', lambda **kw: env); monkeypatch.setattr(U, 'stored_env', lambda: {})
    monkeypatch.setattr(U, 'log_path', lambda: tmp_path/'Logs'/'update.log'); monkeypatch.setattr(U, '_asked', True)
    return env

def _brew(tmp, cask=True, script='#!/bin/sh\necho ok\n', tap='vedicreader/tap'):
    (b := tmp/'brew'/'bin'/'brew').parent.mkdir(parents=True); b.write_text(script); b.chmod(0o755)
    if cask:
        (m := tmp/'brew'/'Caskroom'/'leela'/'.metadata').mkdir(parents=True)
        if tap: (m/'INSTALL_RECEIPT.json').write_text(f'{{"source": {{"tap": "{tap}"}}}}')
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

def test_a_caskroom_leela_from_homebrews_own_go_program_is_not_ours(tmp_path, monkeypatch):
    app, b = _app(tmp_path), _brew(tmp_path, tap='homebrew/cask')
    monkeypatch.setattr(U.shutil, 'which', lambda n: str(b))
    assert U.brew_for(app) is None

def _run(job, wait=10):
    job.start()
    end = time.monotonic() + wait
    while job.state == 'running' and time.monotonic() < end: time.sleep(.05)
    return job.status()

def _fake(tmp, upgrade='', update='', info='0.1.0', info_rc=0):
    "A brew that only runs sh builtins and /usr/bin tools: it logs args and env, and runs one snippet per command; `$n` counts upgrades."
    log, room = tmp/'brew.log', tmp/'brew'/'Caskroom'/'leela'
    js = f'{{"formulae": [], "casks": [{{"token": "leela", "full_token": "vedicreader/tap/leela", "version": "{info}"}}]}}'
    return _brew(tmp, script=f"""#!/bin/sh
echo "args $*" >> '{log}'
env | /usr/bin/sort > '{tmp}/env.'"$1"
case "$1" in
upgrade) n=$(/bin/cat '{tmp}/n' 2>/dev/null || echo 0); n=$((n+1)); echo $n > '{tmp}/n'; ROOM='{room}'
{upgrade}
;;
update)
{update}
;;
info) echo '{js}'; exit {info_rc} ;;
esac
exit 0
"""), log

def _args(log): return [l for l in log.read_text().splitlines() if l.startswith('args')]
def _env(tmp, cmd='upgrade'): return dict(l.split('=', 1) for l in (tmp/f'env.{cmd}').read_text().splitlines() if '=' in l)
BUMP = 'mkdir -p "$ROOM/99.0"; echo "==> Upgrading leela"'
UP = 'args upgrade --cask vedicreader/tap/leela'
DISABLED = "echo 'Warning: Not upgrading leela, it is disabled because it is discontinued!'"

def test_brew_gets_a_terminals_env_not_the_apps_and_the_full_cask_name(tmp_path, monkeypatch, login):
    "The bare `leela` loaded Homebrew's own disabled Go program; the app's SSL, Python, git and XDG values went to brew too."
    for k in ('SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE', 'NODE_EXTRA_CA_CERTS', 'PYTHONHOME', 'PYTHONPATH', 'GIT_DIR',
              'GIT_SSL_CAINFO', 'XDG_CONFIG_HOME', 'HOMEBREW_NO_AUTO_UPDATE', 'HOMEBREW_AUTO_UPDATE_CHECKED', 'RESOURCEPATH'): monkeypatch.setenv(k, '/app/certifi')
    monkeypatch.setenv('HOMEBREW_AUTO_UPDATE_SECS', '86400')
    app = _app(tmp_path); b, log = _fake(tmp_path, upgrade=BUMP)
    assert _run(U.Upgrade(app, str(b), '99.0')) == {'state': 'done', 'line': 'Leela 99.0 is installed.'}
    assert _args(log) == [UP]
    e = _env(tmp_path)
    assert not [k for k in e if k.startswith(('SSL_', 'REQUESTS_', 'CURL_', 'NODE_', 'PYTHONHOME', 'PYTHONPATH', 'GIT_', 'XDG_', 'RESOURCEPATH'))], e
    assert not [k for k in e if k in U._NO_FETCH] and e['HOMEBREW_AUTO_UPDATE_SECS'] == '0'
    assert e['PATH'].split(':')[0] == login['PATH'] and '/usr/bin' in e['PATH'].split(':')
    assert (e['HOME'], e['USER'], e['LANG'], e['https_proxy']) == (str(tmp_path), 'pat', 'en_AU.UTF-8', 'http://own:1')

def test_without_a_login_shell_brew_gets_only_the_basic_names(tmp_path, monkeypatch):
    monkeypatch.setattr(U, 'shell_env', lambda **kw: {})
    monkeypatch.setattr(U, 'stored_env', lambda: {'HOMEBREW_GITHUB_API_TOKEN': 't', 'HTTPS_PROXY': 'http://p:2', 'OPENAI_API_KEY': 'k', 'SSL_CERT_FILE': '/c'})
    monkeypatch.setenv('SSL_CERT_FILE', '/app/certifi'); monkeypatch.setenv('PATH', '/opt/x/bin'); monkeypatch.setenv('TMPDIR', '/t')
    e = U.Upgrade(brew='/b/bin/brew').env()
    assert e['PATH'] == '/opt/x/bin:/b/bin:/usr/bin:/bin:/usr/sbin:/sbin'
    assert e['HOMEBREW_GITHUB_API_TOKEN'] == 't' and e['HTTPS_PROXY'] == 'http://p:2'
    assert not {'SSL_CERT_FILE', 'OPENAI_API_KEY', 'TMPDIR'} & set(e)

def test_a_failed_upgrade_shows_brews_error_and_writes_the_log(tmp_path):
    app = _app(tmp_path)
    b, log = _fake(tmp_path, upgrade="echo '==> Downloading leela'\necho 'Error: Download failed: https://x/Leela-macOS.zip'\necho 'You have 3 outdated formulae installed.'\nexit 1")
    got = _run(U.Upgrade(app, str(b), '99.0'))
    assert got['state'] == 'error' and got['line'].startswith('Error: Download failed: https://x/Leela-macOS.zip') and str(U.log_path()) in got['line']
    assert _args(log) == [UP], 'no retry after a failure'
    text = U.log_path().read_text()
    assert '$ brew upgrade --cask vedicreader/tap/leela' in text and 'Error: Download failed' in text and 'exit 1' in text

def test_an_untrusted_tap_says_the_command_that_trusts_it(tmp_path):
    app = _app(tmp_path)
    b, _ = _fake(tmp_path, upgrade="echo 'Error: Refusing to load cask vedicreader/tap/leela from untrusted tap vedicreader/tap.'\n"
                                   "echo 'Run `brew trust --cask vedicreader/tap/leela` or `brew trust vedicreader/tap` to trust it.'\nexit 1")
    got = _run(U.Upgrade(app, str(b), '99.0'))
    assert got['state'] == 'error' and 'Refusing to load cask vedicreader/tap/leela from untrusted tap' in got['line']
    assert 'run `brew trust --cask vedicreader/tap/leela` in Terminal' in got['line']

def test_a_failed_brew_update_is_shown_not_called_not_listed_yet(tmp_path):
    "The old fault: `brew update` failed, the first upgrade's exit 0 stood, and the bar said Homebrew did not list it."
    app = _app(tmp_path)
    b, log = _fake(tmp_path, upgrade=DISABLED, update="echo 'Error: Fetching /opt/homebrew/Library/Taps/vedicreader/homebrew-tap failed!'\nexit 1")
    got = _run(U.Upgrade(app, str(b), '99.0'))
    assert got['state'] == 'error' and got['line'].startswith('Error: Fetching /opt/homebrew/Library/Taps/vedicreader/homebrew-tap failed!')
    assert _args(log) == [UP, 'args update', UP]

def test_a_first_upgrade_that_did_not_fetch_is_fixed_by_brew_update(tmp_path):
    app = _app(tmp_path)
    b, log = _fake(tmp_path, upgrade=f'[ "$n" -ge 2 ] && {{ {BUMP}; }}')
    assert _run(U.Upgrade(app, str(b), '99.0')) == {'state': 'done', 'line': 'Leela 99.0 is installed.'}
    assert _args(log) == [UP, 'args update', UP]

def test_another_tap_failing_brew_update_does_not_stop_the_install(tmp_path):
    app = _app(tmp_path)
    b, _ = _fake(tmp_path, upgrade=f'[ "$n" -ge 2 ] && {{ {BUMP}; }}', update="echo 'Error: Fetching /opt/homebrew/Library/Taps/x/homebrew-y failed!'\nexit 1")
    assert _run(U.Upgrade(app, str(b), '99.0'))['state'] == 'done'

def test_not_listed_yet_only_when_brew_succeeded_and_the_cask_lists_the_old_version(tmp_path):
    app = _app(tmp_path); b, log = _fake(tmp_path, info='0.1.0')
    got = _run(U.Upgrade(app, str(b), '99.0'))
    assert got == {'state': 'same', 'line': 'Homebrew does not list Leela 99.0 yet. Try again in a few minutes.'}
    assert _args(log) == [UP, 'args update', UP, 'args info --cask --json=v2 vedicreader/tap/leela']

def test_a_listed_version_that_brew_skipped_says_why(tmp_path):
    app = _app(tmp_path); b, _ = _fake(tmp_path, upgrade="echo 'Warning: Not upgrading 1 pinned package:'\necho 'leela 0.1.0'", info='99.0')
    got = _run(U.Upgrade(app, str(b), '99.0'))
    assert got['state'] == 'error' and got['line'].startswith('Homebrew lists Leela 99.0, but did not install it: Warning: Not upgrading 1 pinned package:')

def test_a_failed_info_is_an_error_not_same(tmp_path):
    app = _app(tmp_path); b, _ = _fake(tmp_path, info_rc=1)
    assert _run(U.Upgrade(app, str(b), '99.0'))['state'] == 'error'

def test_an_error_without_an_error_line_gives_the_exit_code(tmp_path):
    app = _app(tmp_path); b, _ = _fake(tmp_path, upgrade='exit 3')
    assert _run(U.Upgrade(app, str(b), '99.0'))['line'].startswith('Homebrew stopped with exit code 3.')

def test_an_app_moved_out_of_applications_counts_the_caskroom_version(tmp_path):
    "brew installs into its appdir; the running app's plist then stays old although the upgrade worked."
    app = _app(tmp_path); b, _ = _fake(tmp_path, upgrade=BUMP)
    assert _run(U.Upgrade(app, str(b), '99.0'))['state'] == 'done'

def test_the_run_after_brew_imports_nothing(tmp_path, monkeypatch):
    "brew replaces python313.zip under the running app, so an import after it fails."
    import builtins
    app = _app(tmp_path); b, _ = _fake(tmp_path, info='0.1.0')
    job = U.Upgrade(app, str(b), '99.0'); job.was = '0.1.0'
    real = builtins.__import__
    def no_new(name, globals=None, locals=None, fromlist=(), level=0):
        if level == 0 and name not in sys.modules: raise ImportError(f'late import of {name}')
        return real(name, globals, locals, fromlist, level)
    monkeypatch.setattr(builtins, '__import__', no_new)
    job._run()
    monkeypatch.setattr(builtins, '__import__', real)
    assert job.state == 'same', job.line

def test_a_brew_that_hangs_is_stopped_and_said_so(tmp_path, monkeypatch):
    monkeypatch.setattr(U, 'WAIT', .5)
    app = _app(tmp_path); b = _brew(tmp_path, script='#!/bin/sh\necho start\nsleep 30\n')
    got = _run(U.Upgrade(app, str(b), '99.0'))
    assert got['state'] == 'error' and 'did not answer' in got['line'] and 'stopped: no answer' in U.log_path().read_text()

def test_a_brew_that_cannot_start_is_an_error(tmp_path):
    assert _run(U.Upgrade(_app(tmp_path), str(tmp_path/'nope')))['state'] == 'error'

def test_an_upgrade_already_on_disk_is_done_without_brew_and_restart_is_allowed(tmp_path, monkeypatch):
    "brew upgraded earlier and Leela was not restarted: that is 'restart now', not 'Homebrew does not list it'."
    app = _app(tmp_path, '99.0'); b, log = _fake(tmp_path)
    monkeypatch.setattr(U.shutil, 'which', lambda n: str(b)); monkeypatch.setattr(U, '_job', None)
    assert U.upgrade_status(app) == {'state': 'done', 'line': 'Leela 99.0 is installed.'}
    assert U.offer({'version': '99.0'}, app=app)['pending'] == '99.0'
    assert U.upgrade(app, '99.0')['state'] == 'done' and not log.exists()

def test_a_second_update_click_keeps_the_finished_job(tmp_path, monkeypatch):
    "A click from the dialog or a second window after 'done' started a new run that ended 'same', and Restart then refused."
    app = _app(tmp_path); b, log = _fake(tmp_path, upgrade=BUMP)
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

def test_the_first_check_in_a_process_goes_past_the_cache_then_the_cache_holds(data, monkeypatch):
    "A start read a release cache up to six hours old, so a release made that morning showed nothing."
    calls = []
    monkeypatch.setattr(U, '_ask', lambda: calls.append(1) or ('v9.0.0', 'https://x/9.0.0'))
    now = 10_000
    monkeypatch.setattr(U, 'time', type('T', (), {'time': staticmethod(lambda: now)}))
    (c := data/'data'/'leela'/'release.json').parent.mkdir(parents=True); c.write_text('{"version": "1.0", "checked": 9000}')
    monkeypatch.setattr(U, '_asked', False)
    assert U.offer(app=False)['latest'] == '9.0.0' and len(calls) == 1
    now += U.FRESH_TTL + 1
    assert U.offer(app=False)['latest'] == '9.0.0' and len(calls) == 1, 'later checks keep the cache'
    now += U.TTL
    U.offer(app=False)
    assert len(calls) == 2 and U.TTL < 3600, 'the cache is shorter than the hourly poll'

def test_the_notice_polls_each_hour_and_not_now_is_per_version():
    js = (Path(U.__file__).parents[1]/'static'/'lee-ide.js').read_text()
    assert "setInterval(() => leeUpdateNotice().catch(() => {}), 3600e3)" in js
    assert "sessionStorage.setItem('lee-update-later', d.latest || '')" in js
    assert "sessionStorage.getItem('lee-update-later') !== d.latest" in js
    assert "if (updateRunning || $('#leeupdate')?.hidden === false) return;" in js
    assert 'updateLater]' not in js, 'every Not now stores the version it hides'
