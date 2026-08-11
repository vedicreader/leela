"""The values a workflow or a release needs, kept where dockeasy already keeps them.

Leela does not own a credential store and should not grow one. dockeasy has the whole of
it: `secret_set` writes to the OS keychain and falls back to a `0600` dotenv under
`~/.config/fastops`, `env_set` does the non-secret half, and `secret_get`/`env_get` read
back through `os.environ` first so a value exported before Leela started still wins. This
module is the thin layer above that pair which the panels need and dockeasy has no reason
to care about: *which* keys are worth showing, and what may be shown of them.

Which keys: gheasy's `env_schema` says what this project sends to GitHub and whether each
one is a secret or a variable, and the release pipeline's steps name what they cannot run
without. Together those are the list; nothing enumerates the store itself, because a shared
`fastops` file holds other projects' values and this panel is not a place to browse them.

What may be shown: a secret's value never reaches the browser -- only that it is set, and
where from. A variable's value does, because a GitHub Actions variable is not a secret and
seeing it is the entire point of listing it. The store outside the repository is also why
there is nothing here about `.gitignore`: the value was never in the project to begin with.
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
    # answer to most of the questions this panel asks. A panel refresh must not fill the
    # log with it.
    import logging
    logging.getLogger('dotenv.main').setLevel(logging.ERROR)
    return env_get, env_set, secret_get, secret_set


class EnvStore:
    """The environment keys one project cares about, read and written through dockeasy.

    `service` is dockeasy's keychain service name. It stays at dockeasy's default so a
    token set from a `dockeasy`/`gheasy` script and one set from this panel are the same
    value, rather than two that disagree depending on which tool you last used.
    """

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
        """Remove a value from every place `set` put it.

        dockeasy has no opposite of `set_key`, so this reaches for the two libraries it
        stores through rather than editing the file by hand -- python-dotenv owns the file
        format and keyring owns the keychain entry, and neither is Leela's to reimplement.
        """
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
        """Every key this project names, with a value only where one is safe to show.

        `schema` is gheasy's: `{KEY: None}` is a secret, `{KEY: 'default'}` is a variable.
        `needed` are keys the release steps declared. A key that appears only in `needed` is
        assumed to be a secret, because the safe reading of an unknown credential is that it
        is one.
        """
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
