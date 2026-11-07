"Whether a newer Leela is released, and the Homebrew step that installs it in the Mac app."
# The modules a finished upgrade needs are imported here: `brew` replaces `python313.zip` under the running app.
import json, os, plistlib, shutil, signal, subprocess, sys, threading, time, urllib.request
from fastcore.all import Path, first
from fastcore.net import urljson
from fastcore.xdg import xdg_data_home
from pullup.env import strip_bundle
from .. import __version__

__all__ = ['REPO', 'RELEASES', 'RELEASE_PAGE', 'CASK', 'TTL', 'FRESH_TTL', 'APP_TAG', 'latest_release', 'newest_app', 'newer', 'app_bundle', 'brew_for',
           'kind', 'pending', 'offer', 'old_extras', 'remove_old_extras', 'Upgrade', 'upgrade', 'upgrade_status', 'restart']

REPO = 'vedicreader/leela'
RELEASES = f'https://api.github.com/repos/{REPO}/releases/latest'
RELEASE_PAGE = f'https://github.com/{REPO}/releases/latest'
CASK = 'leela'
TTL = 6*3600
#: The thin Mac app's releases. Lock releases are `lock-<n>`; neither is a Leela release.
APP_TAG, LOCK_TAG = 'app-v', 'lock-'
APP_RELEASES = f'https://api.github.com/repos/{REPO}/releases?per_page=30'
FRESH_TTL = 30  #: a forced check still waits this long, for GitHub's 60 an hour

def _cache(name='release.json'): return xdg_data_home()/'leela'/name
def _leela_tag(tag): return not str(tag).startswith((APP_TAG, LOCK_TAG))

def _ask():
    "The newest release as `(version, url)`. The page redirect answers when the API is rate-limited."
    try:
        r = urljson(RELEASES, headers={'Accept': 'application/vnd.github+json'}, timeout=4)
        tag, url = r['tag_name'], r['html_url']
    except Exception:
        with urllib.request.urlopen(urllib.request.Request(RELEASE_PAGE, method='HEAD'), timeout=4) as r: url = r.url
        if '/releases/tag/' not in url: raise ValueError(f'{RELEASE_PAGE} went to {url}')
        tag = url.rsplit('/', 1)[1]
    if not _leela_tag(tag): raise ValueError(f'{tag} is not a Leela release')
    return tag, url

def latest_release(ttl=TTL, now=None):
    "The newest release as `{version, url, checked}`, asked of GitHub at most once per `ttl` seconds. Offline it is the last answer, or `{}`."
    now = now or time.time()
    try: c = json.loads(_cache().read_text())
    except (OSError, ValueError): c = {}
    if 'checked' in c and now - c['checked'] < ttl: return c
    try: tag, url = _ask(); c = dict(version=tag.lstrip('v'), url=url)
    except OSError: c['failed'] = True
    except Exception: pass
    c['checked'] = now
    try:
        (tmp := _cache().with_suffix(f'.{os.getpid()}')).parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(c)); tmp.replace(_cache())
    except OSError: pass
    return c

def _ask_app():
    "The newest `app-v*` release that is neither a draft nor a prerelease, as `(version, url)`."
    r = first(x for x in urljson(APP_RELEASES, headers={'Accept': 'application/vnd.github+json'}, timeout=4)
              if str(x.get('tag_name', '')).startswith(APP_TAG) and not x.get('draft') and not x.get('prerelease'))
    if r is None: raise ValueError('no app release')
    return r['tag_name'].removeprefix(APP_TAG), r['html_url']

def newest_app(ttl=TTL, now=None):
    "The newest Mac app release as `{version, url, checked}`, cached as `latest_release` is."
    now = now or time.time()
    try: c = json.loads(_cache('app-release.json').read_text())
    except (OSError, ValueError): c = {}
    if 'checked' in c and now - c['checked'] < ttl: return c
    try: v, url = _ask_app(); c = dict(version=v, url=url)
    except OSError: c['failed'] = True
    except Exception: pass
    c['checked'] = now
    try:
        (tmp := _cache('app-release.json').with_suffix(f'.{os.getpid()}')).parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(c)); tmp.replace(_cache('app-release.json'))
    except OSError: pass
    return c

def newer(latest, current=__version__):
    "Whether `latest` is a later release than `current`, by the packaging rules and not by string."
    if not (latest and current): return False
    try:
        from packaging.version import Version
        return Version(latest) > Version(current)
    except Exception: return False

def app_bundle(exe=None, frozen=None, platform=sys.platform):
    "The `.app` this process runs from, or None outside a frozen Mac app."
    if platform != 'darwin' or not (getattr(sys, 'frozen', False) if frozen is None else frozen): return None
    return first(p for p in Path(exe or sys.executable).parents if p.suffix == '.app')

def brew_for(app):
    "The `brew` that installed `app` from the cask, or None."
    if not app or not (b := shutil.which('brew')): return None
    return b if (Path(b).parent.parent/'Caskroom'/CASK).is_dir() and Path(app).name == 'Leela.app' else None

def kind(app_newer, lock_newer, needs_app, brew):
    "What an update is, by the table in docs/thin-app.md: app, lock, app-needed, download, or none."
    if lock_newer and not needs_app and not app_newer: return 'lock'
    if not (app_newer or lock_newer): return 'none'
    if not brew: return 'download'
    return 'app' if app_newer else 'app-needed'

def _host_offer(st=None, rel=None, fresh=False):
    "The offer in host mode: the app's version and lock state from the launcher, the newest app from its releases. `fresh` asks GitHub now."
    from . import host
    st = host.status() if st is None else st
    rel, cur, lk = newest_app(FRESH_TTL if fresh else TTL) if rel is None else rel, host.app_version(), st.get('lock') or {}
    job = upgrade_status() if st else dict(state='idle', line='')
    k = kind(newer(rel.get('version'), cur), bool(lk.get('newer')), bool(lk.get('needs_app')), bool(st.get('brew'))) if st else 'none'
    latest = dict(lock=f"package set {lk.get('newest_n')}", none=cur).get(k, lk.get('app_min') if k == 'app-needed' and lk.get('app_min') else rel.get('version'))
    return dict(current=cur, latest=latest, url=rel.get('url') or RELEASE_PAGE, outdated=k != 'none', kind=k,
                notice=k != 'none', install=k in ('app', 'lock'), lock=lk.get('current_n'), newest_lock=lk.get('newest_n'), changes=str(lk.get('changes') or ''), old_extras=old_extras(),
                failed=bool(rel.get('failed') or not (st and rel.get('version'))), pending=latest if job['state'] == 'done' else None, job=job)

def _extras_root():
    from .. import extras_site
    return extras_site().parents[2]

def old_extras():
    "The extras folder the old app installed into, which the Mac app's env never reads: `{path, mb}`, or None outside host mode or when it is gone."
    from . import host
    if not host.on() or not (p := _extras_root()).is_dir(): return None
    return dict(path=str(p), mb=round(sum(f.stat().st_size for f in p.rglob('*') if f.is_file() and not f.is_symlink()) / 2**20))

def remove_old_extras():
    "Delete the old extras folder, and nothing else; only in host mode."
    if not (o := old_extras()): return False
    shutil.rmtree(o['path'])
    return True

def _version(app):
    try: return plistlib.loads((Path(app)/'Contents'/'Info.plist').read_bytes()).get('CFBundleShortVersionString')
    except Exception: return None

def pending(app=None):
    "The newer version already on disk that this process has not restarted into, or None."
    v = _version(app) if (app := app or app_bundle()) else None
    return v if newer(v) else None

def offer(rel=None, app=None, fresh=False):
    "What the notice offers: whether a newer release exists, and whether Leela can install it here. `fresh` asks GitHub now."
    from . import host
    if host.on(): return _host_offer(fresh=fresh)
    rel = latest_release(FRESH_TTL if fresh else TTL) if rel is None else rel
    app = app_bundle() if app is None else app
    out = dict(current=__version__, latest=rel.get('version'), url=rel.get('url') or RELEASE_PAGE, outdated=newer(rel.get('version')),
               failed=bool(rel.get('failed') or not rel.get('version')), pending=pending(app) if app else None)
    return out | dict(notice=bool(app and out['outdated']), install=bool(app and out['outdated'] and brew_for(app)), job=upgrade_status(app))

#: Homebrew's own markers that an auto-update already ran, and the opt-out; any of them skips the tap fetch.
_NO_FETCH = ('HOMEBREW_NO_AUTO_UPDATE', 'HOMEBREW_AUTO_UPDATING', 'HOMEBREW_UPDATE_AUTO', 'HOMEBREW_AUTO_UPDATE_CHECKED')
#: `brew update-report` lines about other formulae, which mean nothing in Leela's bar.
_NOISE = ('You have ', 'Run `brew', '==> Outdated', '==> New ')
WAIT = 600

def _killpg(pid):
    try: os.killpg(pid, signal.SIGKILL)
    except OSError: pass

class Upgrade:
    "One `brew upgrade --cask leela` in the background, with its state and last line. A child of the app, so the cask's `uninstall quit` skips it."
    def __init__(self, app=None, brew=None, latest=None):
        self.app, self.brew, self.latest, self.state, self.line, self.was = app, brew, latest, 'idle', '', None
    def env(self):
        "Homebrew's env with the tap fetch forced: its default fetches at most once a day, so a cask pushed today is not seen."
        e = {k: v for k, v in os.environ.items() if k not in _NO_FETCH}
        return strip_bundle(e | dict.fromkeys(('HOMEBREW_NO_ENV_HINTS', 'HOMEBREW_NO_COLOR', 'HOMEBREW_NO_EMOJI', 'NONINTERACTIVE'), '1') | {'HOMEBREW_AUTO_UPDATE_SECS': '0'})
    def start(self):
        if self.state == 'running': return self.status()
        if (v := pending(self.app)): self.state, self.line = 'done', f'Leela {v} is installed.'; return self.status()
        self.was, self.state, self.line = _version(self.app), 'running', 'Homebrew is getting the newest list of apps…'
        threading.Thread(target=self._run, daemon=True, name='leela-upgrade').start()
        return self.status()
    def _brew(self, *args):
        "Run brew with `args`, the last useful line into `line`; its exit code, or None when it did not start."
        # Its own session, so a quit mid-swap does not signal it; still this process's child, which is what the cask checks.
        try: p = subprocess.Popen([self.brew, *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, env=self.env(), start_new_session=True)
        except OSError as e: self.line = str(e); return None
        # The whole group: brew's git children hold the pipe open past brew itself.
        (t := threading.Timer(WAIT, _killpg, (p.pid,))).start()
        try:
            for l in p.stdout:
                if (l := l.strip()) and not l.startswith(_NOISE): self.line = l
            return p.wait()
        finally:
            if not t.is_alive(): self.line = f'Homebrew did not answer in {WAIT//60} minutes.'
            t.cancel()
    def _run(self):
        rc = self._brew('upgrade', '--cask', CASK)
        # A brew.env setting can still skip the fetch; `brew update` ignores it, so one more try after it.
        if rc == 0 and _version(self.app) == self.was and newer(self.latest, self.was) and self._brew('update') == 0: rc = self._brew('upgrade', '--cask', CASK)
        if rc != 0: self.state = 'error'
        elif _version(self.app) != self.was: self.state, self.line = 'done', f'Leela {_version(self.app)} is installed.'
        else: self.state, self.line = 'same', f'Homebrew does not list Leela {self.latest or "the new version"} yet. Try again in a few minutes.'
    def status(self): return dict(state=self.state, line=self.line)

_job, _lock = None, threading.Lock()

def upgrade(app=None, latest=None):
    "Start installing the newer release, or say why not. The one step a later app can replace."
    global _job
    from . import host
    if host.on():
        o = _host_offer(); k = o['kind']
        if k not in ('app', 'lock'): return dict(state='unavailable', line='', url=RELEASE_PAGE)
        try: return _launcher_state(host.call('/update', {'kind': k} | ({'latest': latest or o['latest']} if k == 'app' else {}), read=30))
        except host.HostError as e: return dict(state='error', line=str(e))
    app = app or app_bundle()
    if not (b := brew_for(app)): return dict(state='unavailable', line='', url=RELEASE_PAGE)
    with _lock:
        if _job is None or _job.state not in ('running', 'done'): _job = Upgrade(app, b, latest or latest_release().get('version'))
        return _job.start()

def _launcher_state(d):
    "The launcher's update state as the page knows them: its `ready` (built, waiting for a restart) is `done`."
    st = str(d.get('state') or 'error')
    return dict(state={'ready': 'done'}.get(st, st), line=str(d.get('line') or ''))

def upgrade_status(app=None):
    "The running or last upgrade; `done` too when a newer Leela is on disk and this process predates it. In host mode, the launcher's."
    from . import host
    if host.on():
        try: return _launcher_state(host.call('/update', read=10))
        except host.HostError as e: return dict(state='error', line=str(e))
    if _job and _job.state != 'idle': return _job.status()
    if (app := app or app_bundle()) and (v := pending(app)): return dict(state='done', line=f'Leela {v} is installed.')
    return dict(state='idle', line='')

def restart(app=None, pid=None, wait=60):
    "Open `app` again once this process has quit, then quit it. In host mode the launcher restarts the server and swaps the lock."
    from . import host
    if host.on():
        try: return bool(host.call('/restart', {}, read=10).get('ok'))
        except host.HostError: return False
    app, pid = app or app_bundle(), pid or os.getpid()
    if not app: return False
    sh = 'i=0; while kill -0 "$0" 2>/dev/null && [ $i -lt "$2" ]; do sleep .2; i=$((i+1)); done; exec open "$1"'
    subprocess.Popen(['/bin/sh', '-c', sh, str(pid), str(app), str(wait*5)], start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=strip_bundle(dict(os.environ)))
    threading.Timer(.3, os.kill, (pid, signal.SIGTERM)).start()
    return True
