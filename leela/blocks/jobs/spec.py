"OpenAPI / Google Discovery → operation rows. Prefer `ramabana.spec` when installed."

from __future__ import annotations
import json
from fastcore.all import Path, L

__all__ = ['load_spec', 'op_row', 'spec_ops']


def load_spec(target):
    "Parse a YAML/JSON OpenAPI or Discovery document from a path or string."
    try:
        from ramabana.spec import load_spec as _load
        return _load(target)
    except ImportError: pass
    p = Path(target)
    raw = p.read_text() if p.is_file() else str(target)
    if p.suffix.lower() in ('.yaml', '.yml') or raw.lstrip().startswith(('openapi:', 'swagger:')):
        import yaml
        return yaml.safe_load(raw)
    return json.loads(raw)


def op_row(o):
    "Normalise one operation dict for vault sections / UI."
    try:
        from ramabana.spec import op_row as _row
        return _row(o)
    except ImportError: pass
    return dict(o)


def spec_ops(spec):
    "Yield operation dicts with verb, path, summary, group, required, signature."
    try:
        from ramabana.spec import spec_ops as _ops
        return list(_ops(spec))
    except ImportError: pass
    if not isinstance(spec, dict): return []
    if 'paths' in spec: return _openapi_ops(spec)
    if 'resources' in spec or spec.get('discoveryVersion'): return _discovery_ops(spec)
    return []


def _openapi_ops(spec):
    out = L()
    for path, methods in (spec.get('paths') or {}).items():
        if not isinstance(methods, dict): continue
        for verb, op in methods.items():
            if verb.startswith('x-') or not isinstance(op, dict): continue
            params = list(op.get('parameters') or [])
            required = [p['name'] for p in params if isinstance(p, dict) and p.get('required') and p.get('name')]
            tags = op.get('tags') or []
            out.append(dict(verb=verb.upper(), path=path, summary=op.get('summary') or '',
                group=tags[0] if tags else '', required=required,
                signature=op.get('operationId') or f'{verb.upper()} {path}', docs_url=''))
    return out


def _discovery_ops(spec):
    out = L()
    def walk(resources, prefix=''):
        for name, body in (resources or {}).items():
            if not isinstance(body, dict): continue
            for method, op in (body.get('methods') or {}).items():
                if not isinstance(op, dict): continue
                params = op.get('parameters') or {}
                required = [k for k, v in params.items() if isinstance(v, dict) and v.get('required')]
                path, verb = op.get('path') or method, (op.get('httpMethod') or 'GET').upper()
                out.append(dict(verb=verb, path=path, summary=op.get('description') or '',
                    group=prefix or name, required=required,
                    signature=op.get('id') or f'{verb} {path}', docs_url=''))
            walk(body.get('resources') or {}, name)
    walk(spec.get('resources') or {})
    return out
