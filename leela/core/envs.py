"The values a workflow or a release needs, kept where dockeasy already keeps them."

from __future__ import annotations

import asyncio, inspect, json, os, re, subprocess, threading

__all__ = ['EnvStore', 'EnvError', 'import_login_env', 'preferred_shell', 'shell_env',
           'env_file', 'stored_env', 'apply_stored_env', 'set_env', 'unset_env', 'env_rows',
           'is_secret', 'KNOWN_KEYS']

#: The names the agent's model backends read, offered whether or not anything has set them.
KNOWN_KEYS = ('ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'GEMINI_API_KEY')

#: A value under one of these names is never sent to a browser.
_SECRETISH = ('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'PASSWD', 'CREDENTIAL')

_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')

def is_secret(name): return any(w in str(name).upper() for w in _SECRETISH)

def env_file():
    from .. import leela_cfg
    return leela_cfg/'env.json'

def stored_env():
    "What Leela itself has been told to export. An unreadable file is an empty one."
    try: out = json.loads(env_file().read_text(encoding='utf-8'))
    except Exception: return {}
    return {k: str(v) for k, v in out.items() if isinstance(k, str) and _NAME.match(k)}

def _write(values):
    path = env_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.json.new')
    tmp.write_text(json.dumps(values, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    os.chmod(tmp, 0o600)
    tmp.replace(path)

def apply_stored_env(env=None):
    """Put Leela's own values into the environment, over whatever the shell said. Returns the names.

    Last, and winning: this is the escape hatch for a machine where asking the shell gives the wrong
    answer, so a value typed into Leela has to beat the one that is already wrong.
    """
    target = os.environ if env is None else env
    values = stored_env()
    target.update(values)
    return sorted(values)

def set_env(key, value):
    "Store one name for Leela to export, and export it now."
    key, value = str(key or '').strip(), str(value if value is not None else '')
    if not _NAME.match(key): raise EnvError(
        f'{key or "a name"} is not an environment variable name: letters, digits and underscore, not starting with a digit')
    if not value: raise EnvError(f'{key} needs a value; remove it instead to unset it')
    _write({**stored_env(), key: value})
    os.environ[key] = value
    return {'key': key, 'secret': is_secret(key)}

def unset_env(key):
    "Forget one name Leela stored. What the shell exports is the shell's, and stays."
    key = str(key or '').strip()
    values = stored_env()
    if key not in values: raise EnvError(f'{key} is not one of Leela\'s: it comes from the environment Leela was started in')
    del values[key]
    _write(values)
    os.environ.pop(key, None)
    return {'key': key, 'removed': True}

def env_rows():
    """Every name worth showing, with a value only where one is safe to show.

    Leela's own, the names the model backends read, and anything already in the environment that
    looks like a credential. A secret's value never leaves the server; that it is set does.
    """
    values = stored_env()
    names = set(values) | set(KNOWN_KEYS) | {k for k in os.environ if is_secret(k)}
    rows = []
    for key in sorted(names):
        mine, live = key in values, os.environ.get(key, '')
        secret = is_secret(key)
        rows.append({'key': key, 'secret': secret, 'set': bool(live),
                     'value': '' if secret else live,
                     'source': 'leela' if mine else ('environment' if live else ''),
                     'editable': True, 'removable': mine})
    return rows

#: Names that describe the shell that printed them, not the environment a program wants.
_SHELL_ONLY = {'_', 'PWD', 'OLDPWD', 'SHLVL', 'PS1', 'TERM', 'TERM_SESSION_ID', 'TMPDIR'}

def preferred_shell():
    """The shell to ask about the environment: the terminal setting, else `$SHELL`.

    `$SHELL` is the shell the login record names, which is not always the one a person uses. Leela
    already has somewhere to say otherwise, and the terminal reads it, so this reads the same place
    rather than adding a second answer to one question.
    """
    try:
        from ..blocks.settings.settings import Settings
        if (chosen := str((Settings().effective().get('terminal') or {}).get('shell') or '').strip()):
            return chosen
    except Exception: pass
    return os.environ.get('SHELL') or '/bin/zsh'

def shell_env(shell=None, timeout=8):
    """What `shell` exports, as `{name: value}`, asked the way a person's terminal is.

    Interactive first. zsh reads `.zshrc` only for an interactive shell, and that is where an
    `OPENAI_API_KEY` usually lives, so a login-but-not-interactive shell answered with eight names
    and no key at all. Shells that refuse `-i` are asked again without it.
    """
    shell = shell or preferred_shell()
    for args in (('-l', '-i', '-c', 'env -0'), ('-l', '-c', 'env -0')):
        try: r = subprocess.run([shell, *args], capture_output=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError): return {}
        if r.returncode != 0: continue
        out = {}
        for row in r.stdout.split(b'\0'):
            name, sep, value = row.partition(b'=')
            if sep and name: out[name.decode('utf-8', 'replace')] = value.decode('utf-8', 'replace')
        if out: return out
    return {}

def import_login_env(shell=None, env=None, timeout=8):
    """Merge the shell's exported environment into this process, and return what was added.

    An app opened from Finder inherits launchd's environment rather than a shell's, so an
    `OPENAI_API_KEY` exported from a shell profile is invisible to it while the same Leela started
    from a terminal sees it. Names this process already has are kept: nothing the launcher chose is
    overwritten, `PATH` included, which only gains the directories the shell knows about.
    """
    exported = shell_env(shell, timeout)
    if not exported: return []
    target = os.environ if env is None else env
    added, path = [], []
    for k, v in exported.items():
        if k in _SHELL_ONLY: continue
        if k == 'PATH': path = [d for d in v.split(os.pathsep) if d]
        elif k not in target: target[k], _ = v, added.append(k)
    # A directory the shell has and this process does not can only add a tool, so it goes on the end.
    extra = [d for d in path if d not in (target.get('PATH') or '').split(os.pathsep)]
    if extra:
        target['PATH'] = os.pathsep.join([*(target.get('PATH') or '').split(os.pathsep), *extra]).strip(os.pathsep)
        added.append('PATH')
    return added

class EnvError(RuntimeError):
    pass

def _dockeasy():
    try:
        from dockeasy.core import env_get, env_set, secret_get, secret_set
    except ImportError as e:
        raise EnvError('environment values are stored by dockeasy: pip install "leela[github]"') from e
    import logging
    logging.getLogger('dotenv.main').setLevel(logging.ERROR)
    return env_get, env_set, secret_get, secret_set

def _call(fn, *args, **kwargs):
    value = fn(*args, **kwargs)
    if not inspect.isawaitable(value): return value
    try: asyncio.get_running_loop()
    except RuntimeError: return asyncio.run(value)
    out = []
    def run():
        try: out.append((True, asyncio.run(value)))
        except BaseException as e: out.append((False, e))
    thread = threading.Thread(target=run); thread.start(); thread.join()
    ok, value = out[0]
    if ok: return value
    raise value

class EnvStore:
    "The environment keys one project cares about, read and written through dockeasy."
    def __init__(self, service='fastops', path=None):
        self.service, self.path = service, path
    def get(self, key, secret=True):
        env_get, _set, secret_get, _sset = _dockeasy()
        stored = (_call(secret_get, key, service=self.service, path=self.path) if secret
                  else _call(env_get, key, path=self.path))
        return stored or os.environ.get(key) or ''
    def set(self, key, value, secret=True):
        "Store one value. A secret goes to the keychain as well as the file; a variable does not."
        key = str(key or '').strip()
        if not key: raise EnvError('a key is required')
        if not str(value): raise EnvError(f'{key} needs a value')
        env_get, env_set, secret_get, secret_set = _dockeasy()
        if secret: _call(secret_set, key, str(value), service=self.service, path=self.path)
        else: _call(env_set, key, str(value), path=self.path)
        return {'key': key, 'secret': bool(secret)}
    def unset(self, key):
        "Remove a value from every place `set` put it."
        from dockeasy.core import _FASTOPS_ENV
        from dotenv import unset_key
        key, gone = str(key), []
        try:
            import keyring
            if keyring.get_password(self.service, key) is not None:
                keyring.delete_password(self.service, key)
                gone.append('keychain')
        except Exception: pass
        path = str(self.path or _FASTOPS_ENV)
        try:
            removed, _ = unset_key(path, key)
            if removed: gone.append('file')
        except Exception: pass
        if os.environ.pop(key, None) is not None: gone.append('process')
        if not gone: raise EnvError(f'{key} is not set')
        return {'key': key, 'removed': gone}
    def entries(self, schema=None, needed=()):
        "Every key this project names, with a value only where one is safe to show."
        schema = dict(schema or {})
        rows = []
        for key in list(schema) + [k for k in needed if k not in schema]:
            secret = schema.get(key, None) is None
            value = self.get(key, secret=secret)
            rows.append({'key': key, 'secret': secret, 'set': bool(value),
                         'value': '' if secret else value,
                         'target': 'secret' if secret else 'variable',
                         'declared': key in schema,
                         'default': '' if schema.get(key) is None else str(schema.get(key))})
        return sorted(rows, key=lambda r: (r['set'], r['key']))
    def values(self, keys):
        "The values for `keys`, for handing to a child process. Never returned to a browser."
        return {key: v for key in (keys or ()) if (v := self.get(key, secret=True))}
