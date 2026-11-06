"Host mode: the Leela Mac app runs this server as its child and answers on a loopback control server. See `docs/thin-app.md`."
import hmac, http.client, json, os, select, sys
from pathlib import Path
from urllib.parse import urlsplit

__all__ = ['HostError', 'OWNED', 'AGENT_TOOLS', 'take', 'on', 'is_app', 'unbuild', 'tools_dir', 'agent_scripts', 'link_tools', 'with_tools', 'steered', 'call', 'status', 'confirm', 'grant_ok', 'setup', 'app_version', 'lock_n']

#: What the launcher sets for its child. No shell and no stored value replaces these.
OWNED = ('LEELA_HOST_URL', 'LEELA_HOST_TOKEN', 'LEELA_APP_VERSION', 'LEELA_APP_BUNDLE', 'LEELA_LOCK_N', 'LEELA_ENV_HASH', 'LEELA_UV')
#: Names that would move the server off the environment the launcher built.
STEER = ('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'PYTHONUSERBASE', 'VIRTUAL_ENV', 'CONDA_PREFIX')
#: Packages of the app's env whose console scripts an agent's shell runs by name.
AGENT_TOOLS = ('ramabana', 'koshas', 'exhash', 'fossick', 'litesearch', 'vishalakshi', 'gheasy', 'safepyrun', 'pyskills', 'rgapi', 'mdhtml')

class HostError(Exception): "The launcher did not answer, or refused."

_host = dict(url='', token='')
#: Seconds the launcher has to write the token line after it starts this process.
TOKEN_WAIT = 5

def _read_line(fd, timeout):
    "One line from `fd`, read a byte at a time so nothing past it is taken; '' on end of file or when it does not come in time."
    out = b''
    while not out.endswith(b'\n') and len(out) < 1024:
        if not select.select([fd], [], [], timeout)[0]: return ''
        if not (b := os.read(fd, 1)): break
        out += b
    return out.decode('ascii', 'replace').strip()

def take(env=None, fd=0, timeout=None):
    "Host mode: the control server's address from the environment, its token as one line on stdin, then stdin on /dev/null. Whether host mode is on."
    env = os.environ if env is None else env
    if env.pop('LEELA_HOST_TOKEN', None) is not None: print('leela: LEELA_HOST_TOKEN in the environment is ignored; the Leela app gives the token on stdin', file=sys.stderr)
    if not (url := env.pop('LEELA_HOST_URL', '')): return on()
    token = _read_line(fd, TOKEN_WAIT if timeout is None else timeout)
    null = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null, fd); os.close(null)
    if not token: raise SystemExit('leela: LEELA_HOST_URL is set, but no token line came on stdin. Only the Leela app starts the server this way.')
    _host.update(url=url, token=token)
    return on()

def on(): return bool(_host['url'])
def is_app():
    "Whether Leela runs as an app, frozen or under the launcher, so its own Python is not the person's."
    return bool(getattr(sys, 'frozen', False)) or on()

def unbuild(env=None, prefix=None):
    "Take out what app 1.0.0's launcher gave this server and its children would inherit: uv's build settings, PYTHONNOUSERSITE, VIRTUAL_ENV and the env's bin on PATH."
    env, prefix = os.environ if env is None else env, os.path.realpath(sys.prefix if prefix is None else prefix)
    for k in [k for k in env if k.startswith('UV_')]: del env[k]
    env.pop('PYTHONNOUSERSITE', None)
    if os.path.realpath(env.get('VIRTUAL_ENV') or '/') == prefix: del env['VIRTUAL_ENV']
    if 'PATH' in env: env['PATH'] = os.pathsep.join(p for p in env['PATH'].split(os.pathsep) if p and os.path.realpath(p) != os.path.join(prefix, 'bin'))
    return env

def tools_dir(prefix=None):
    "Where the links to the env's agent tools go: `bin` beside the launcher's `envs/`, else Leela's data folder."
    from fastcore.xdg import xdg_data_home
    p = Path(sys.prefix if prefix is None else prefix)
    return p.parent.parent/'bin' if p.parent.name == 'envs' else xdg_data_home()/'leela'/'bin'

def agent_scripts(pkgs=AGENT_TOOLS):
    "The console scripts of `pkgs` in this env; never a python, pip or uv."
    from importlib.metadata import PackageNotFoundError, distribution
    out = []
    for n in pkgs:
        try: out += [e.name for e in distribution(n).entry_points if e.group == 'console_scripts']
        except PackageNotFoundError: pass
    return sorted(n for n in set(out) if not n.startswith(('python', 'pip', 'uv')))

def link_tools(names=None, src=None, dst=None):
    "Link `names` from the env's scripts folder `src` into `dst`, replacing what an earlier env left there. The folder."
    import sysconfig
    src, dst = Path(src or sysconfig.get_path('scripts')), Path(dst or tools_dir())
    want = {n for n in (agent_scripts() if names is None else names) if (src/n).is_file()}
    dst.mkdir(parents=True, exist_ok=True)
    for n in want:
        (tmp := dst/f'.{n}.{os.getpid()}').unlink(missing_ok=True)
        tmp.symlink_to(src/n); os.replace(tmp, dst/n)
    for p in dst.iterdir():
        if p.name not in want and p.is_symlink(): p.unlink()
    return dst

def with_tools(env=None):
    "`env` (this process's, by default) with the app's agent tools on PATH, in host mode."
    env = dict(os.environ if env is None else env)
    if on() and (d := tools_dir()).is_dir(): env['PATH'] = os.pathsep.join([str(d), *filter(None, env.get('PATH', '').split(os.pathsep))])
    return env

def steered(k): return k in STEER or k in OWNED
def app_version(): return os.environ.get('LEELA_APP_VERSION') if on() else None

def lock_n():
    try: return int(os.environ['LEELA_LOCK_N'])
    except (KeyError, ValueError): return None

def _where():
    u = urlsplit(_host['url'])
    if u.scheme != 'http' or u.username or u.password or u.hostname != '127.0.0.1' or not u.port: raise HostError(f'not a loopback control server: {_host["url"]!r}')
    return u.port

def call(path, body=None, read=600, connect=3):
    "One request to the launcher: POST with a JSON `body`, else GET. Connecting fails fast; the answer may wait on a person."
    if not on(): raise HostError('no Leela app runs this server')
    c = http.client.HTTPConnection('127.0.0.1', _where(), timeout=connect)
    try:
        c.connect(); c.sock.settimeout(read)
        data = None if body is None else json.dumps(body).encode()
        c.request('GET' if body is None else 'POST', path, data, {'Authorization': f'Bearer {_host["token"]}', 'Content-Type': 'application/json'})
        r = c.getresponse(); raw = r.read()
        if r.status != 200: raise HostError(f'the Leela app answered {r.status} to {path}')
        d = json.loads(raw)
        if not isinstance(d, dict): raise HostError(f'the Leela app gave no object for {path}')
        return d
    except HostError: raise
    except Exception as e: raise HostError(f'the Leela app did not answer {path}: {type(e).__name__}: {e}') from e
    finally: c.close()

def grant_ok(nonce, path):
    "Whether the launcher issued the one-time `nonce` for opening `path`: how a Finder or Dock open, or a picked folder, is trusted. The launcher never sends the token to the server."
    if not (on() and nonce): return False
    try: return call('/grant', {'nonce': str(nonce), 'path': str(path)}, read=10).get('ok') is True
    except HostError: return False

def status(read=5):
    "The launcher's `/status`, or {} when it does not answer."
    try: return call('/status', read=read)
    except HostError: return {}

def confirm(question):
    "Ask in a native dialog of the app. Every failure is `NoWindow`, so a broken answer is never taken as a No."
    from ..hub import NoWindow
    try: d = call('/confirm', {'question': str(question)})
    except HostError as e: raise NoWindow(str(e)) from e
    if not isinstance(d.get('answer'), bool): raise NoWindow('the Leela app gave no answer')
    return d['answer']

def setup():
    "What a launch from the app needs, as `leela_app` does for the frozen app: no build settings, UTF-8, the login PATH and keys, Leela's stored values, the app's dialogs. No extras folder: the env is the app's."
    from .. import use_login_path, use_utf8
    from ..hub import set_confirmer
    from .envs import apply_stored_env, import_login_env
    # first: the login shell and stored values only fill a name that is empty
    unbuild()
    if os.environ.get('NO_COLOR') == '1': del os.environ['NO_COLOR']   # app 1.0.0's, for uv's log; the login shell gives back the person's own
    use_utf8(); use_login_path()
    if os.environ.get('LEELA_SHELL_ENV', '1') != '0': import_login_env()
    apply_stored_env()
    try: link_tools()
    except OSError as e: print(f'leela: the agent tools are not linked: {e}', file=sys.stderr)
    set_confirmer(confirm)
