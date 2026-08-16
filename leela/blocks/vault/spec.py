"OpenAPI / Google Discovery documents as operation rows, and the keys a real call needs."

from __future__ import annotations
import json, re
from fastcore.all import Path, L, first, risinstance

from ... import errstr, leela_cfg

__all__ = ['load_spec', 'op_row', 'spec_ops', 'Creds', 'CREDS', 'cred_key', 'parse_headers', 'redact']

try: import ramabana.spec as _spec
except ImportError: _spec = None

def _ramabana(name):
    "`ramabana.spec.<name>`, or None on a ramabana that does not ship the parser."
    return getattr(_spec, name, None)

def load_spec(target):
    "Parse a YAML/JSON OpenAPI or Discovery document from a path or a literal string."
    if (fn := _ramabana('load_spec')): return fn(target)
    p = Path(target)
    raw = p.read_text() if p.is_file() else str(target)
    if p.suffix.lower() in ('.yaml', '.yml') or raw.lstrip().startswith(('openapi:', 'swagger:')):
        import yaml
        return yaml.safe_load(raw)
    return json.loads(raw)

def op_row(o):
    "One operation as the flat row `clip_api_spec` writes a section from."
    if (fn := _ramabana('op_row')): return fn(o)
    return dict(o)

def spec_ops(spec):
    "Every operation in `spec`: verb, path, summary, group, required, signature."
    if (fn := _ramabana('spec_ops')): return list(fn(spec))
    if not isinstance(spec, dict): return L()
    if 'paths' in spec: return _openapi_ops(spec)
    if 'resources' in spec or spec.get('discoveryVersion'): return _discovery_ops(spec)
    return L()

def _row(verb, path, summary, group, required, signature):
    "One operation, flattened the way `clip_api_spec` writes a section from it."
    return dict(verb=verb.upper(), path=path, summary=summary or '', group=group or '',
        required=list(required), signature=signature, docs_url='')

def _params(o):
    "The parameter dicts on an operation or a path item, ignoring anything else in there."
    return L(o.get('parameters')).filter(risinstance(dict))

def _required(params):
    "Required parameter names, once each: an operation may restate a path-level parameter."
    return params.filter(lambda p: p.get('required') and p.get('name')).itemgot('name').unique()

def _openapi_ops(spec):
    "OpenAPI `paths`. Path-level parameters apply to every method under that path."
    out = L()
    for path, methods in (spec.get('paths') or {}).items():
        if not isinstance(methods, dict): continue
        shared = _params(methods)
        for verb, op in methods.items():
            if verb == 'parameters' or verb.startswith('x-') or not isinstance(op, dict): continue
            out.append(_row(verb, path, op.get('summary'), first(op.get('tags') or []),
                _required(shared + _params(op)), op.get('operationId') or f'{verb.upper()} {path}'))
    return out

def cred_key(name): return 'LEELA_API_' + (re.sub(r'[^A-Za-z0-9]+', '_', str(name)).strip('_').upper() or 'API')

def parse_headers(text):
    "`Authorization: Bearer sk_live_…`, one per line, as the header dict a spec is called with."
    rows = (line.partition(':') for line in str(text or '').splitlines())
    return {k.strip(): v.strip() for k, sep, v in rows if sep and k.strip() and v.strip()}

def redact(value, keep=4):
    "A secret as something recognisable and useless: its last few characters."
    s = str(value or '')
    return f'…{s[-keep:]}' if len(s) > keep else '…'

class Creds:
    "Per-spec request headers: the header names in a file, the values where leela keeps secrets."
    def __init__(self, path=None, store=None):
        self.file, self._store, self.note = Path(path) if path else leela_cfg/'apicreds.json', store, ''
    @property
    def store(self):
        if self._store is None:
            from ...core.envs import EnvStore
            self._store = EnvStore(service='leela-apis')
        return self._store
    def keyed(self):
        "Which specs carry credentials, and which headers they send — never the values."
        try: rows = json.loads(self.file.read_text()) if self.file.is_file() else {}
        except Exception as e:
            self.note = f'could not read {self.file.name} ({errstr(e)})'
            return {}
        return {k: sorted(v) for k, v in rows.items() if v}
    def _read(self, name, names):
        "One spec's headers, kept to the names the index carries: the index is what says who is keyed."
        try: text = self.store.get(cred_key(name))
        except Exception as e:
            self.note = errstr(e)
            return {}
        return {k: v for k, v in parse_headers(text).items() if k in set(names)}
    def get(self, name): return self._read(name, self.keyed().get(name, ()))
    def all(self): return {name: self._read(name, names) for name, names in self.keyed().items()}
    def set(self, name, headers):
        "Keep one spec's headers, or forget them entirely when there are none."
        name = str(name or '').strip()
        if not name: raise ValueError('name which api the key belongs to')
        rows, headers = self.keyed(), dict(headers or {})
        try:
            if headers: self.store.set(cred_key(name), '\n'.join(f'{k}: {v}' for k, v in headers.items()))
            else: self.store.unset(cred_key(name))
        except Exception as e: self.note = errstr(e)
        if headers: rows[name] = sorted(headers)
        else: rows.pop(name, None)
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps(rows, indent=2))
        return sorted(rows)

#: One user's keys, wherever the vault page and the agent's host both reach for them.
CREDS = Creds()

def _discovery_ops(spec):
    "Google Discovery nests methods under `resources`, which nest arbitrarily deep."
    out = L()
    def walk(resources, group=''):
        for name, body in (resources or {}).items():
            if not isinstance(body, dict): continue
            for method, op in (body.get('methods') or {}).items():
                if not isinstance(op, dict): continue
                required = [k for k, v in (op.get('parameters') or {}).items()
                    if isinstance(v, dict) and v.get('required')]
                path, verb = op.get('path') or method, op.get('httpMethod') or 'GET'
                out.append(_row(verb, path, op.get('description'), group or name, required,
                    op.get('id') or f'{verb.upper()} {path}'))
            walk(body.get('resources') or {}, name)
    walk(spec.get('resources') or {})
    return out
