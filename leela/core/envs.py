"The values a workflow or a release needs, kept where dockeasy already keeps them."

from __future__ import annotations

import asyncio, inspect, os, threading

__all__ = ['EnvStore', 'EnvError']

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
