"Whether a newer Leela is released, and the Homebrew step that installs it in the Mac app."
# The modules a finished upgrade needs are imported here: `brew` replaces `python313.zip` under the running app.
import json, os, plistlib, shutil, signal, subprocess, sys, threading, time, urllib.request
from fastcore.all import Path, first
from fastcore.net import urljson
from fastcore.xdg import xdg_data_home
from pullup.env import strip_bundle
from .. import __version__

__all__ = ['REPO', 'RELEASES', 'RELEASE_PAGE', 'CASK', 'TTL', 'latest_release', 'newer', 'app_bundle', 'brew_for',
           'offer', 'Upgrade', 'upgrade', 'upgrade_status', 'restart']

REPO = 'vedicreader/leela'
RELEASES = f'https://api.github.com/repos/{REPO}/releases/latest'
RELEASE_PAGE = f'https://github.com/{REPO}/releases/latest'
CASK = 'leela'
TTL = 6*3600

def _cache(): return xdg_data_home()/'leela'/'release.json'

def _ask():
    "The newest release as `(version, url)`. The page redirect answers when the API is rate-limited."
    try:
        r = urljson(RELEASES, headers={'Accept': 'application/vnd.github+json'}, timeout=4)
        return r['tag_name'], r['html_url']
    except Exception:
        with urllib.request.urlopen(urllib.request.Request(RELEASE_PAGE, method='HEAD'), timeout=4) as r: url = r.url
        if '/releases/tag/' not in url: raise ValueError(f'{RELEASE_PAGE} went to {url}')
        return url.rsplit('/', 1)[1], url

def latest_release(ttl=TTL, now=None):
    "The newest release as `{version, url, checked}`, asked of GitHub at most once per `ttl` seconds. Offline it is the last answer, or `{}`."
    now = now or time.time()
    try: c = json.loads(_cache().read_text())
    except (OSError, ValueError): c = {}
    if 'checked' in c and now - c['checked'] < ttl: return c
    try: tag, url = _ask(); c = dict(version=tag.lstrip('v'), url=url)
    except Exception: pass
    c['checked'] = now
    try:
        (tmp := _cache().with_suffix(f'.{os.getpid()}')).parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(c)); tmp.replace(_cache())
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

def offer(rel=None, app=None):
    "What the notice offers: whether a newer release exists, and whether Leela can install it here."
    rel = latest_release() if rel is None else rel
    app = app_bundle() if app is None else app
    out = dict(current=__version__, latest=rel.get('version'), url=rel.get('url') or RELEASE_PAGE, outdated=newer(rel.get('version')))
    return out | dict(notice=bool(app and out['outdated']), install=bool(app and out['outdated'] and brew_for(app)))

def _version(app):
    try: return plistlib.loads((Path(app)/'Contents'/'Info.plist').read_bytes()).get('CFBundleShortVersionString')
    except Exception: return None

class Upgrade:
    "One `brew upgrade --cask leela` in the background, with its state and last line. A child of the app, so the cask's `uninstall quit` skips it."
    def __init__(self, app=None, brew=None): self.app, self.brew, self.state, self.line, self.was = app, brew, 'idle', '', None
    def start(self):
        if self.state == 'running': return self.status()
        self.was, self.state, self.line = _version(self.app), 'running', 'asking Homebrew…'
        env = strip_bundle({**os.environ, **dict.fromkeys(('HOMEBREW_NO_ENV_HINTS', 'HOMEBREW_NO_COLOR', 'HOMEBREW_NO_EMOJI', 'NONINTERACTIVE'), '1')})
        # Its own session, so a quit mid-swap does not signal it; still this process's child, which is what the cask checks.
        try: p = subprocess.Popen([self.brew, 'upgrade', '--cask', CASK], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, env=env, start_new_session=True)
        except OSError as e: self.state, self.line = 'error', str(e); return self.status()
        threading.Thread(target=self._read, args=(p,), daemon=True, name='leela-upgrade').start()
        return self.status()
    def _read(self, p):
        for l in p.stdout:
            if l.strip(): self.line = l.strip()
        rc = p.wait()
        self.state = 'error' if rc else 'same' if _version(self.app) == self.was else 'done'
    def status(self): return dict(state=self.state, line=self.line)

_job = None

def upgrade(app=None):
    "Start installing the newer release, or say why not. The one step a later app can replace."
    global _job
    app = app or app_bundle()
    if not (b := brew_for(app)): return dict(state='unavailable', line='', url=RELEASE_PAGE)
    if _job is None or _job.state != 'running': _job = Upgrade(app, b)
    return _job.start()

def upgrade_status(): return _job.status() if _job else dict(state='idle', line='')

def restart(app=None, pid=None, wait=60):
    "Open `app` again once this process has quit, then quit it."
    app, pid = app or app_bundle(), pid or os.getpid()
    if not app: return False
    sh = 'i=0; while kill -0 "$0" 2>/dev/null && [ $i -lt "$2" ]; do sleep .2; i=$((i+1)); done; exec open "$1"'
    subprocess.Popen(['/bin/sh', '-c', sh, str(pid), str(app), str(wait*5)], start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=strip_bundle(dict(os.environ)))
    threading.Timer(.3, os.kill, (pid, signal.SIGTERM)).start()
    return True
