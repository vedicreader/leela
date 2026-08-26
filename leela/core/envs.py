"The values a workflow or a release needs, kept where dockeasy already keeps them."

from __future__ import annotations

import asyncio, inspect, os, subprocess, threading

__all__ = ['EnvStore', 'EnvError', 'import_login_env']

#: Names that describe the shell that printed them, not the environment a program wants.
_SHELL_ONLY = {'_', 'PWD', 'OLDPWD', 'SHLVL', 'PS1', 'TERM', 'TERM_SESSION_ID', 'TMPDIR'}

def import_login_env(shell=None, env=None, timeout=8):
    """Merge the login shell's exported environment into this process, and return what was added.

    An app opened from Finder inherits launchd's environment rather than a shell's, so an
    `OPENAI_API_KEY` exported from a shell profile is invisible to it while the same Leela started
    from a terminal sees it. Names this process already has are kept: nothing the launcher chose is
    overwritten, `PATH` included, which only gains the directories the shell knows about.
    """
    shell = shell or os.environ.get('SHELL') or '/bin/zsh'
    try: r = subprocess.run([shell, '-l', '-c', 'env -0'], capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError): return []
    if r.returncode != 0: return []
    target = os.environ if env is None else env
    added, path = [], []
    for row in r.stdout.split(b'\0'):
        name, sep, value = row.partition(b'=')
        if not sep: continue
        k, v = name.decode('utf-8', 'replace'), value.decode('utf-8', 'replace')
        if not k or k in _SHELL_ONLY: continue
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
