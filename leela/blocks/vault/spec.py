"OpenAPI / Google Discovery documents as operation rows, and the keys a real call needs."

from __future__ import annotations
import json, os, re
from fastcore.all import AttrDict, Path, L, first, risinstance

from ... import errstr, leela_cfg

__all__ = ['load_spec', 'op_row', 'spec_ops', 'Creds', 'CREDS', 'cred_key', 'parse_headers', 'redact',
           'ENV_RE', 'REACH', 'EXAMPLES', 'example_for', 'env_vars', 'env_status', 'expand']

try: import ramabana.spec as _spec
except ImportError: _spec = None

SpecError = getattr(_spec, 'SpecError', ValueError)
_SPECS = Path(__file__).parent/'specs'

#: Described apis anyone can call: no key, no sign-up, and an answer worth pairing with a document.
EXAMPLES = (
    AttrDict(name='azure-prices', path=str(_SPECS/'azure-retail-prices.json'),
             label='Azure retail prices', note='every published meter and its list price, no key',
             call='prices', params='{"filter": "serviceName eq \'Virtual Machines\' and '
                                   'armRegionName eq \'westeurope\' and armSkuName eq \'Standard_D4s_v5\'"}'),
    AttrDict(name='frankfurter', path=str(_SPECS/'frankfurter.json'),
             label='Exchange rates', note='European Central Bank reference rates, no key',
             call='latest', params='{"base": "USD", "symbols": "EUR,GBP"}'),
)

def example_for(name):
    "The bundled example a loaded spec is, or None. Its call is what the page offers to run."
    return first(x for x in EXAMPLES if x.name == str(name))

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

def cred_key(name): return 'LEELA_API_' + (re.sub(r'[^A-Za-z0-9]+', '_', str(name)).strip('_').upper() or 'API')

def parse_headers(text):
    "`Authorization: Bearer …`, one per line."
    rows = (line.partition(':') for line in str(text or '').splitlines())
    return {k.strip(): v.strip() for k, sep, v in rows if sep and k.strip() and v.strip()}

#: `${NAME}` only. A bare `$NAME` would claim any dollar inside a literal secret.
ENV_RE = re.compile(r'\$\{(\w+)\}')

#: Which models may see what an api answers. `cloud` is any model; `local` is this machine only.
REACH = ('cloud', 'local')

def env_vars(headers):
    "Every environment variable a header set names, in the order it names them."
    return list(dict.fromkeys(m.group(1) for v in (headers or {}).values()
                              for m in ENV_RE.finditer(str(v))))

def env_status(headers, env=None):
    "`{NAME: is it set}` for a header set, or for the names already read out of one."
    env = os.environ if env is None else env
    names = headers if isinstance(headers, (list, tuple)) else env_vars(headers)
    return {k: bool(env.get(k)) for k in names}

def expand(headers, env=None):
    """A header set with this machine's own values in it.

    The reference is what is stored, so rotating the variable rotates the credential. A name with
    nothing behind it is refused here: a literal `${…}` sent as a key comes back as a bare 401.
    """
    env = os.environ if env is None else env
    if missing := [k for k, ok in env_status(headers, env).items() if not ok]:
        raise SpecError(f"nothing here sets {', '.join(missing)}, so the header naming it cannot "
                        f'be built; nothing was sent')
    return {k: ENV_RE.sub(lambda m: env[m.group(1)], str(v)) for k, v in (headers or {}).items()}

def redact(value, keep=4):
    "Its last few characters. A `${NAME}` names a variable rather than carrying one, so it stays whole."
    s = str(value or '')
    if ENV_RE.search(s): return s
    return f'…{s[-keep:]}' if len(s) > keep else '…'

def _policy(entry, reach=None):
    """One spec's row, whether the file holds a policy or a flat list of header names.

    `refs` are the environment variables the values name, which is what the page can show.
    """
    refs = []
    if isinstance(entry, dict):
        headers, refs = entry.get('headers') or [], entry.get('refs') or []
        reach = reach or entry.get('reach')
    else: headers = list(entry or [])
    return dict(headers=sorted(headers), refs=list(refs),
                reach=reach if reach in REACH else 'cloud')

class Creds:
    "Per-spec request headers and reach. Names in a file, values where leela keeps secrets."
    def __init__(self, path=None, store=None):
        self.file, self._store, self.note = Path(path) if path else leela_cfg/'apicreds.json', store, ''
    @property
    def store(self):
        if self._store is None:
            from ...core.envs import EnvStore
            self._store = EnvStore(service='leela-apis')
        return self._store
    def policies(self):
        "Every spec the user has set anything for: the headers it sends, and who may call it."
        try: rows = json.loads(self.file.read_text()) if self.file.is_file() else {}
        except Exception as e:
            self.note = f'could not read {self.file.name} ({errstr(e)})'
            return {}
        return {k: _policy(v) for k, v in rows.items() if v}
    def keyed(self):
        "Which specs are keyed, and which headers they send. Never the values."
        return {k: v['headers'] for k, v in self.policies().items() if v['headers']}
    def reach(self, name): return self.policies().get(str(name), _policy(None))['reach']
    def _read(self, name, names):
        "One spec's headers, narrowed to the names the index carries."
        try: text = self.store.get(cred_key(name))
        except Exception as e:
            self.note = errstr(e)
            return {}
        return {k: v for k, v in parse_headers(text).items() if k in set(names)}
    def get(self, name): return self._read(name, self.keyed().get(name, ()))
    def all(self): return {name: self._read(name, names) for name, names in self.keyed().items()}
    def set(self, name, headers, reach=None):
        "Keep one spec's headers, and who may call it; neither forgets it. `reach=None` leaves it."
        name = str(name or '').strip()
        if not name: raise ValueError('name which api the key belongs to')
        rows, headers = self.policies(), dict(headers or {})
        try:
            if headers: self.store.set(cred_key(name), '\n'.join(f'{k}: {v}' for k, v in headers.items()))
            else: self.store.unset(cred_key(name))
        except Exception as e: self.note = errstr(e)
        row = _policy(dict(headers=list(headers), refs=env_vars(headers)),
                      reach=reach or rows.get(name, {}).get('reach'))
        if row['headers'] or row['reach'] != 'cloud': rows[name] = row
        else: rows.pop(name, None)
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps(rows, indent=2))
        return sorted(rows)

#: One user's keys. The page writes here and the host reads here.
CREDS = Creds()
