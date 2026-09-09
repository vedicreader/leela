"""Where a component comes from: a library installed beside Leela, or a host over HTTP."""

from __future__ import annotations
import json, os, urllib.request
from dataclasses import dataclass, field
from importlib import import_module
from fastcore.all import L, first

__all__ = ['GROUP', 'KNOWN', 'HOST_ENV', 'Library', 'Host', 'libraries', 'palette', 'locate',
           'wire', 'mount', 'split_src']

#: The entry-point group a brick library publishes itself under, as `shalya` does for pyskills.
GROUP = 'leela.bricks'
#: Libraries to try even when they publish no entry point. Empty: `leela_bricks` publishes one.
KNOWN = ()
#: A host to ask when nothing is installed. Empty by default, because a silent default that
#: pointed at Leela's own port is what made the palette come back empty with no error.
HOST_ENV = 'LEELA_BRICK_HOST'
TIMEOUT = 4

def split_src(src):
    "`leela_bricks:viz.series` -> `('leela_bricks', 'viz.series')`. A bare name has no library."
    s = str(src or '').strip()
    return tuple(s.split(':', 1)) if ':' in s else ('', s)

def _reg(mod):
    "The module holding the registry: the library itself, or its `bricks` submodule."
    try:
        if hasattr(mod, 'manifest') and hasattr(mod, 'find'): return mod
    except Exception: return None
    try: sub = import_module(f'{mod.__name__}.bricks')
    except Exception: return None
    try: return sub if hasattr(sub, 'manifest') else None
    except Exception: return None

@dataclass
class Library:
    "One brick library, imported. Its manifest is read in process, never fetched."
    name: str
    module: object
    def _r(self): return _reg(self.module)
    def manifest(self):
        r = self._r()
        return r.manifest() if r else {'bricks': [], 'groups': {}}
    def find(self, name):
        r = self._r()
        b = r.find(name) if r else None
        return b.dict() if hasattr(b, 'dict') else b
    def wire(self, name, base=''):
        "What fills this brick's ports: the snippet it ships, and the call that reads it remotely."
        b = self.find(name)
        if b is None: return None
        d = getattr(self.module, 'data', None)
        remote = d.remote_wire(name, base) if base and hasattr(d, 'remote_wire') else ''
        return {'ok': True, 'src': b.get('src') or f'{self.name}:{name}', 'wire': b.get('wire', ''),
                'remote': remote, 'height': b.get('height', 260),
                'binds': {p['name']: p['name'] for p in b.get('ports') or []},
                'emits': [p['name'] for p in b.get('emits') or []]}
    def fill(self, name):
        d = getattr(self.module, 'data', None)
        return d.fill(name) if hasattr(d, 'fill') else None
    def mount(self, app, page=None):
        "Register this library's own routes on Leela's app. `serve` is the seam that takes any app."
        fn = first(f for f in (getattr(getattr(self.module, 'serve', None), 'connect', None),
                               getattr(self.module, 'connect', None)) if callable(f))
        if fn is None: return f'{self.name}: no routes to mount'
        try:
            fn(app, page) if page is not None else fn(app)
        except TypeError: fn(app)
        return ''

@dataclass
class Host:
    "A brick library behind HTTP, for one that is not installed here."
    name: str
    base: str
    _cache: dict = field(default_factory=dict)
    def _get(self, path):
        with urllib.request.urlopen(f'{self.base}{path}', timeout=TIMEOUT) as r: return json.load(r)
    def manifest(self):
        if 'm' not in self._cache: self._cache['m'] = self._get('/bricks/manifest.json')
        return self._cache['m']
    def find(self, name):
        return first(b for b in (self.manifest().get('bricks') or []) if b.get('name') == name)
    def wire(self, name, base=''):
        got = self._get(f'/bricks/wire/{name}')
        return {**got, 'src': f'{self.name}:{name}'} if got.get('ok') else None
    def fill(self, name): return self._get(f'/bricks/data/{name}')
    def mount(self, app, page=None): return f'{self.name}: served by {self.base}, nothing to mount'

def _installed(name):
    "Whether the top-level package is on the path at all, so `not installed` reads as absent."
    from importlib.util import find_spec
    try: return find_spec(name.split('.')[0]) is not None
    except (ImportError, ValueError): return False

def _entry_points():
    try:
        from importlib.metadata import entry_points
        return [ep.value or ep.name for ep in entry_points(group=GROUP)]
    except Exception: return []

def libraries(extra=(), host=None):
    "Every library this install can reach: entry points, `KNOWN`, `extra`, then a host if one is set."
    out, seen, notes = L(), set(), []
    for name in [*_entry_points(), *KNOWN, *extra]:
        if name in seen: continue
        seen.add(name)
        try: mod = import_module(name)
        except Exception as e:
            if not _installed(name): continue          # not here at all, which is not a fault
            notes.append(f'{name}: {type(e).__name__}: {e}')
            continue
        if _reg(mod) is None:
            notes.append(f'{name}: imported, no manifest()')
            continue
        out.append(Library(name, mod))
    base = (host if host is not None else os.getenv(HOST_ENV, '')).rstrip('/')
    if base: out.append(Host(base.split('//')[-1], base))
    libraries.notes = notes
    return out
libraries.notes = []

def palette(libs=None):
    "Every brick every reachable library offers, merged, with the library each one came from."
    libs = libs if libs is not None else libraries()
    bricks, groups, names, notes = [], {}, [], list(libraries.notes)
    for lib in libs:
        try: m = lib.manifest()
        except Exception as e:
            notes.append(f'{lib.name}: {type(e).__name__}: {e}')
            continue
        names.append(lib.name)
        groups.update(m.get('groups') or {})
        for b in (m.get('bricks') or []):
            bricks.append({**b, 'library': lib.name,
                           'src': b.get('src') or f"{lib.name}:{b.get('name', '')}"})
    return {'bricks': bricks, 'groups': groups, 'libraries': names, 'notes': notes}

def locate(src, libs=None):
    "`(library, brick)` for one `src`, or `(None, None)`."
    lib_name, name = split_src(src)
    if not name: return None, None
    for lib in (libs if libs is not None else libraries()):
        if lib_name and lib.name != lib_name: continue
        try: b = lib.find(name)
        except Exception: continue
        if b is not None: return lib, b
    return None, None

def wire(src, libs=None, base=''):
    "The wiring one brick ships, ready to go into the document as a code brick."
    lib, b = locate(src, libs)
    if lib is None: return {'ok': False, 'error': f'no brick for {src!r}'}
    got = lib.wire(b.get('name') or split_src(src)[1], base)
    return got or {'ok': False, 'error': f'no wiring for {src!r}'}

def mount(app, libs=None, page=None):
    "Mount every installed library's routes on `app`. Returns a note per library that has none."
    libs = libs if libs is not None else libraries()
    return [n for lib in libs if (n := lib.mount(app, page))]
