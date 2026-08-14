"Persistent user-added local and hosted model aliases."
import json, re
from fastcore.all import Path
from ... import leela_cfg

__all__ = ['model_path', 'load_models', 'save_model', 'delete_model', 'runtimes']

API_KEYS = ('base_url', 'api_key_env', 'vendor_name', 'api_name')

# Never restate this list: the copy that used to live here drifted twice from ramabana's.
def _runtimes():
    from ...agent.core import RUNTIMES
    return tuple(RUNTIMES)

def runtimes():
    "Every runtime, and whether rishi can reach it on this machine."
    from ...agent.core import runtime_available
    return [{'value': r, 'available': bool(runtime_available(r))} for r in _runtimes()]

def model_path(path=None): return Path(path or leela_cfg/'models.json')

def _rows(path=None):
    try: d = json.loads(model_path(path).read_text())
    except Exception: return []
    return d if isinstance(d, list) else []

def _without(name, path=None):
    "The saved rows, minus any alias called `name`."
    return [x for x in _rows(path) if x.get('name') != name]

def _write(rows, path=None):
    "Persist the alias list, creating the config directory on first save."
    p = model_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows, indent=2)+'\n')

def load_models(path=None):
    "Register saved aliases with Ramabana and return valid rows."
    from ...agent.core import register_model
    out = []
    for row in _rows(path):
        try:
            cfg = {k: row.get(k) for k in API_KEYS if row.get(k)}
            spec = register_model(row.get('name'), row.get('model_id'), row.get('runtime'),
                                  row.get('ctx', 128_000), 'saved model', **cfg)
            out.append({**row, 'name': spec.name, 'model_id': spec.model_id, 'runtime': spec.runtime, 'ctx': spec.ctx})
        except Exception: continue
    return out

def save_model(row, path=None):
    "Validate, register and persist one model alias. API keys are never stored here."
    from ...agent.core import MODELS, CUSTOM, register_model
    name = str(row.get('name') or '').strip()
    model_id = str(row.get('model_id') or '').strip()
    runtime = str(row.get('runtime') or '').strip()
    if not re.match(r'^[A-Za-z0-9][\w.-]{0,63}$', name): raise ValueError('name must use letters, numbers, _, . or -')
    if runtime not in (rts := _runtimes()): raise ValueError(f'runtime must be one of {", ".join(rts)}')
    if name in MODELS and name not in CUSTOM: raise ValueError(f'{name!r} is a built-in model name')
    ctx = int(row.get('ctx') or 128_000)
    if not 1024 <= ctx <= 10_000_000: raise ValueError('context must be between 1,024 and 10,000,000 tokens')
    cfg = {k: str(row.get(k) or '').strip() for k in API_KEYS if row.get(k)}
    if runtime != 'remote' and cfg: raise ValueError('API settings apply only to the remote runtime')
    spec = register_model(name, model_id, runtime, ctx, 'saved model', **cfg)
    clean = {'name': name, 'model_id': spec.model_id, 'runtime': runtime, 'ctx': ctx, **cfg}
    _write(_without(name, path)+[clean], path)
    return clean

def delete_model(name, path=None):
    from ...agent.core import unregister_model
    _write(_without(name, path), path)
    unregister_model(name)
    return name
