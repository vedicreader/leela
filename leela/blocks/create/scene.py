"The projects of Create mode: a folder under Leela's data with `story.json`, a rupaka spec whose state keys are the named values of the scene."
import json, math, re, threading
from copy import deepcopy
from fastcore.basics import first
from fastcore.xtras import Path
from ... import leela_cfg

__all__ = ['TEMPLATE', 'CreateError', 'contract_missing', 'create_root', 'projects', 'ensure', 'new_project', 'load', 'save_state', 'rev', 'values', 'marks',
           'current', 'create_context', 'create_tools', 'export_page']

TEMPLATE = 'scene-dawn-to-dusk'
SLUG = re.compile(r'^[a-z0-9][a-z0-9-]{0,39}$')
STAGE = dict(x=(0, 160), y=(0, 90))
_lock = threading.Lock()

class CreateError(ValueError):
    "An expected failure of a project, with a short `code` and a sentence for a person."
    def __init__(self, code, said): super().__init__(said); self.code, self.said = code, said

def contract_missing() -> list[str]:
    "What this install lacks for Create: rupaka with the layers block and the demo scene."
    try:
        from rupaka.spec import gallery, manifests
        return [] if TEMPLATE in gallery() and {'layers', 'layer', 'timeline'} <= set(manifests()) else ['rupaka 0.0.16 (the layers block)']
    except ImportError: return ['rupaka 0.0.16']

def says(missing) -> str: return f"Create needs {missing[0]} or newer. Update rupaka."

def create_root() -> Path: return leela_cfg/'create'

def slug_ok(slug):
    if not isinstance(slug, str) or not SLUG.match(slug): raise CreateError('invalid_project', 'The project name is not valid.')
    return slug

def story_path(slug) -> Path: return create_root()/slug_ok(slug)/'story.json'

def projects() -> list[str]:
    "The project names, newest first."
    rows = [(p.stat().st_mtime_ns, p.parent.name) for p in create_root().glob('*/story.json') if SLUG.match(p.parent.name)] if create_root().is_dir() else []
    return [n for _, n in sorted(rows, reverse=True)]

def _write(slug, spec):
    p = story_path(slug); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix('.tmp'); tmp.write_text(json.dumps(spec, indent=1, ensure_ascii=False)); tmp.replace(p)

def new_project(name='') -> str:
    "Make a project from the dawn-to-dusk scene; its folder name comes from `name`."
    if m := contract_missing(): raise CreateError('contract_missing', says(m))
    from rupaka.spec import gallery
    base = re.sub(r'[^a-z0-9]+', '-', str(name).lower()).strip('-')[:36] or 'scene'
    with _lock:
        slug, n = base, 1
        while (create_root()/slug).exists(): n += 1; slug = f'{base}-{n}'
        spec = deepcopy(gallery()[TEMPLATE]); spec['id'] = slug
        if name.strip(): spec['title'] = name.strip()[:80]
        _write(slug, spec)
    return slug

def ensure(slug='') -> str:
    "`slug` when that project exists, else the newest project, else a new one."
    if slug and SLUG.match(slug) and story_path(slug).is_file(): return slug
    return next(iter(projects()), '') or new_project()

def load(slug) -> dict:
    "The checked spec of a project; a `CreateError` says what is wrong."
    p = story_path(slug)
    try: spec = json.loads(p.read_text())
    except FileNotFoundError: raise CreateError('not_found', f'There is no project {slug}.')
    except ValueError: raise CreateError('invalid_scene', 'story.json is not valid JSON.')
    if m := contract_missing(): raise CreateError('contract_missing', says(m))
    from rupaka.spec import validate
    if errs := validate(spec): raise CreateError('invalid_scene', f'story.json: {errs[0]}')
    return spec

def rev(slug) -> str:
    s = story_path(slug).stat()
    return f'{s.st_mtime_ns}:{s.st_size}'

def _num(v): return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)

def _walk(bs):
    for b in bs or []:
        if isinstance(b, dict):
            yield b
            yield from _walk(b.get('blocks'))

def values(spec) -> list[dict]:
    "The named values of a scene: each numeric state key with its range (when a block gives one) and label."
    rows = []
    for k, v in (spec.get('state') or {}).items():
        if not _num(v): continue
        r = dict(name=k, value=v, label=k)
        for b in _walk(spec.get('blocks')):
            if b.get('type') == 'timeline' and b.get('bind') == k: r.update(min=b.get('min', 0), max=b.get('max', 100), label=b.get('label') or 'Time')
            for ax in b.get('drag', '') if b.get('type') == 'layer' else '':
                if b.get(ax) == k: lo, hi = b.get(ax + 'r') or STAGE[ax]; r.update(min=lo, max=hi, label=b.get('label') or k)
        rows.append(r)
    return rows

def marks(spec) -> list[dict]:
    "The time marks of the scene: `{t, label}` of its first timeline."
    return list((first(b for b in _walk(spec.get('blocks')) if b.get('type') == 'timeline') or {}).get('markers') or [])

def save_state(slug, state) -> dict:
    "Write the numbers in `state` to the project. A key the scene does not have, or a value that is not a number or is out of range, raises `CreateError`; nothing is written then."
    with _lock:
        spec = load(slug)
        rows = {r['name']: r for r in values(spec)}
        for k, v in state.items():
            r = rows.get(k)
            if r is None: raise CreateError('not_found', f'The scene has no value {k!r}. Its values are: {", ".join(rows) or "none"}.')
            if not _num(v): raise CreateError('invalid_value', f'{k} must be a number.')
            if 'min' in r and not r['min'] <= v <= r['max']: raise CreateError('invalid_value', f'{k} must be from {r["min"]} to {r["max"]}.')
        if all(spec['state'][k] == v for k, v in state.items()): return spec
        spec['state'] = {**spec['state'], **state}
        _write(slug, spec)
        return spec

def export_page(slug) -> str:
    "One standalone page of the project, with its fonts inside, that opens from a file."
    from rupaka.render import page
    return page(load(slug), fonts='embed')

def current(ws) -> str:
    "The project the Create tab shows, else the newest project, else ''."
    t = first(t for t in ws.tabs if t.kind == 'story')
    return t.ref if t is not None and t.ref else next(iter(projects()), '')

def _res(status='ok', error=None, **data):
    "The result of an agent tool, in the field shape of `abhyasa.agent_tools.result`."
    return dict(status=status, operation_id=None, vault=None, walk=None, step=None, revision=None, data=data, error=error)

def _bad(error, message, **data): return _res('error', error, message=message, **data)

def create_context(ai) -> str:
    "The Create block of the system prompt: the scene, its named values and its time marks."
    slug = current(ai.ws)
    if not slug: return 'Create mode. No scene is open yet.'
    try: spec = load(slug)
    except CreateError as e: return f'Create mode. The scene {slug} cannot be read: {e.said}'
    vals = ', '.join(f"{r['name']} = {r['value']}" + (f" ({r['min']} to {r['max']})" if 'min' in r else '') for r in values(spec))
    ms = ', '.join(f"{m['label']} at {m['t']}" for m in marks(spec))
    return (f"Create mode. The scene is {spec.get('title') or slug} (project {slug}). Its values: {vals or 'none'}." + (f' Time marks: {ms}.' if ms else '')
            + ' list_scene shows the values. set_scene_value changes one, and the picture follows.')

def create_tools(ai):
    "The two Create tools: `list_scene` reads the values, `set_scene_value` changes one."
    from ...agent.tools import small_tool
    from shalya.core import writes
    def off():
        return _bad('mode_off', 'Turn Create mode on before using scene tools.', mode=ai.mode, needs='create')
    def list_scene() -> dict:
        "List the named values of the open scene, each with its range, and the time marks."
        if ai.mode != 'create': return off()
        if not (slug := current(ai.ws)): return _bad('no_scene', 'No scene is open. Open Create and press New scene.')
        try: spec = load(slug)
        except CreateError as e: return _bad(e.code, e.said, project=slug)
        return _res(project=slug, title=spec.get('title', slug), values=values(spec), marks=marks(spec))
    def set_scene_value(name: str, value: float) -> dict:
        "Set the named value `name` of the open scene to the number `value`. The picture changes at once."
        if ai.mode != 'create': return off()
        if not (slug := current(ai.ws)): return _bad('no_scene', 'No scene is open. Open Create and press New scene.')
        try:
            was = (load(slug).get('state') or {}).get(name)
            save_state(slug, {name: value})
        except CreateError as e: return _bad(e.code, e.said, project=slug)
        return _res(project=slug, name=name, value=value, previous=was)
    writes(set_scene_value)
    return [small_tool(list_scene), small_tool(set_scene_value)]
