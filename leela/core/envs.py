"""The values a workflow or a release needs, kept where dockeasy already keeps them.

Which keys come from gheasy's `env_schema` plus what the release steps declare; the store
itself is never enumerated. A secret's value never reaches the browser, only that it is set.
"""

from __future__ import annotations

__all__ = ['EnvStore', 'EnvError']


class EnvError(RuntimeError):
    pass


def _dockeasy():
    try:
        from dockeasy.core import env_get, env_set, secret_get, secret_set
    except ImportError as e:
        raise EnvError('environment values are stored by dockeasy: pip install "leela[github]"') from e
    # python-dotenv warns for every key it does not find, and "not set yet" is the normal
    # answer here, so a panel refresh would otherwise fill the log.
    import logging
    logging.getLogger('dotenv.main').setLevel(logging.ERROR)
    return env_get, env_set, secret_get, secret_set


class EnvStore:
    "The environment keys one project cares about, read and written through dockeasy."
    # `service` stays at dockeasy's keychain default, so a token set from a `dockeasy`/`gheasy`
    # script and one set from this panel are the same value rather than two that disagree.

    def __init__(self, service='fastops', path=None):
        self.service, self.path = service, path

    def get(self, key, secret=True):
        env_get, _set, secret_get, _sset = _dockeasy()
        return (secret_get(key, service=self.service, path=self.path) if secret
                else env_get(key, path=self.path)) or ''

    def set(self, key, value, secret=True):
        "Store one value. A secret goes to the keychain as well as the file; a variable does not."
        key = str(key or '').strip()
        if not key: raise EnvError('a key is required')
        if not str(value): raise EnvError(f'{key} needs a value')
        env_get, env_set, secret_get, secret_set = _dockeasy()
        if secret: secret_set(key, str(value), service=self.service, path=self.path)
        else: env_set(key, str(value), path=self.path)
        return {'key': key, 'secret': bool(secret)}

    def unset(self, key):
        "Remove a value from every place `set` put it."
        # dockeasy has no opposite of `set_key`, so this goes through the two libraries it
        # stores with: python-dotenv owns the file format, keyring owns the keychain entry.
        import os

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
        # `schema` is gheasy's: `{KEY: None}` is a secret, `{KEY: 'default'}` a variable. A key
        # appearing only in `needed` (declared by a release step) is assumed to be a secret.
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
        out = {}
        for key in keys or ():
            v = self.get(key, secret=True)
            if v: out[key] = v
        return out
