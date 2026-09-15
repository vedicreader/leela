"Running a brick's own snippet here, for a document that has the component but not the package."

from .bricks import find

__all__ = ['fill', 'remote_wire']

def fill(name):
    b = find(name)
    if b is None: return None
    ns = {}
    try: exec(compile(b.wire, f'<wire:{name}>', 'exec'), ns)
    except Exception as e: ns['_error'] = f'{type(e).__name__}: {e}'
    return {p.name: ns.get(p.name, p.sample) for p in b.ports}

def remote_wire(name, base):
    b = find(name)
    if b is None or not b.ports: return ''
    ports = ', '.join(p.name for p in b.ports)
    return (f"import json, urllib.request\n"
            f"_p = json.load(urllib.request.urlopen('{base}/bricks/data/{name}'))\n"
            f"{ports} = {', '.join(f'_p[{p.name!r}]' for p in b.ports)}\n")
