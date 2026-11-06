"Host mode: the Leela Mac app runs this server as its child and answers on a loopback control server. See `docs/thin-app.md`."
import hmac, http.client, json, os, select, sys
from urllib.parse import urlsplit

__all__ = ['HostError', 'OWNED', 'take', 'on', 'steered', 'call', 'status', 'confirm', 'grant_ok', 'setup', 'app_version', 'lock_n']

#: What the launcher sets for its child. No shell and no stored value replaces these.
OWNED = ('LEELA_HOST_URL', 'LEELA_HOST_TOKEN', 'LEELA_APP_VERSION', 'LEELA_APP_BUNDLE', 'LEELA_LOCK_N', 'LEELA_ENV_HASH', 'LEELA_UV')
#: Names that would move the server off the environment the launcher built.
STEER = ('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'PYTHONUSERBASE', 'VIRTUAL_ENV', 'CONDA_PREFIX')

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
def steered(k): return k in STEER or k in OWNED or k.startswith('UV_')
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
    "What a launch from the app needs, as `leela_app` does for the frozen app: UTF-8, the login PATH and keys, Leela's stored values, the app's dialogs. No extras folder: the env is the app's."
    from .. import use_login_path, use_utf8
    from ..hub import set_confirmer
    from .envs import apply_stored_env, import_login_env
    use_utf8(); use_login_path()
    if os.environ.get('LEELA_SHELL_ENV', '1') != '0': import_login_env()
    apply_stored_env()
    # the login PATH replaced the launcher's, which put the env's bin first
    if v := os.environ.get('VIRTUAL_ENV'):
        os.environ['PATH'] = os.pathsep.join(dict.fromkeys([os.path.join(v, 'bin'), *filter(None, os.environ['PATH'].split(os.pathsep))]))
    set_confirmer(confirm)
