"""OpenAPI / Google Discovery documents as operation rows.

`ramabana.spec` owns this when the installed ramabana has it; the fallback below is the
same three names over the two document shapes leela actually clips.
"""

from __future__ import annotations
import json
from fastcore.all import Path, L, first, risinstance

__all__ = ['load_spec', 'op_row', 'spec_ops']


def _ramabana(name):
    "`ramabana.spec.<name>`, or None on a ramabana that does not ship the parser."
    try:
        import ramabana.spec as spec
    except ImportError: return None
    return getattr(spec, name, None)


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
    return params.filter(lambda p: p.get('required') and p.get('name')).itemgot('name')


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
                # Discovery keys parameters by name, where OpenAPI lists them.
                required = [k for k, v in (op.get('parameters') or {}).items()
                    if isinstance(v, dict) and v.get('required')]
                path, verb = op.get('path') or method, op.get('httpMethod') or 'GET'
                out.append(_row(verb, path, op.get('description'), group or name, required,
                    op.get('id') or f'{verb.upper()} {path}'))
            walk(body.get('resources') or {}, name)
    walk(spec.get('resources') or {})
    return out
