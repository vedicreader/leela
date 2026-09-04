"The values a workflow or a release needs, kept where dockeasy already keeps them."

from __future__ import annotations

import json, os, re, subprocess

from kunda.pythons import BUNDLE_ONLY, clean_env, strip_bundle
from pullup.env import EnvError, EnvStore as _EnvStore, use_extra

# Every pullup message about the cloud half names Leela's own extra, not pullup's.
use_extra('dockeasy')

__all__ = ['EnvStore', 'EnvError', 'import_login_env', 'preferred_shell', 'shell_env',
           'BUNDLE_ONLY', 'clean_env', 'strip_bundle',
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
    "Put Leela's own values into the environment, over whatever the shell said. Returns the names."
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
    "Every name worth showing, with a value only where one is safe to show."
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
    "The shell to ask about the environment: the terminal setting, else `$SHELL`."
    try:
        from ..blocks.settings.settings import Settings
        if (chosen := str((Settings().effective().get('terminal') or {}).get('shell') or '').strip()):
            return chosen
    except Exception: pass
    return os.environ.get('SHELL') or '/bin/zsh'

def shell_env(shell=None, timeout=8):
    "What `shell` exports, as `{name: value}`, asked the way a person's terminal is."
    shell = shell or preferred_shell()
    for args in (('-l', '-i', '-c', 'env -0'), ('-l', '-c', 'env -0')):
# `clean_env`, or the shell inherits the bundle's `PYTHONHOME` and hands it to whatever Python
# its startup files run.
        try: r = subprocess.run([shell, *args], capture_output=True, timeout=timeout, env=clean_env())
        except (OSError, subprocess.SubprocessError): return {}
        if r.returncode != 0: continue
        out = {}
        for row in r.stdout.split(b'\0'):
            name, sep, value = row.partition(b'=')
            if sep and name: out[name.decode('utf-8', 'replace')] = value.decode('utf-8', 'replace')
        if out: return out
    return {}

def import_login_env(shell=None, env=None, timeout=8):
    "Merge the shell's exported environment into this process, and return what was added."
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

class EnvStore(_EnvStore):
    "pullup's store, plus the rows the Environment panel draws and a removal that says nothing went."
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

