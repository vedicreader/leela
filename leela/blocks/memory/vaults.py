"Every vault leela can reach, which is active, and what may write to each."

from __future__ import annotations
import json, time
from dataclasses import asdict, dataclass, field, replace

from fastcore.all import L, Path, atomic_save, first

from ... import Dictable, errstr, leela_cfg
from .memory import GLOBAL, Memory, memory_path, safe_shelf

__all__ = ['ACCESS', 'WORKSPACE', 'VaultRef', 'Vaults', 'vaults_path']

ACCESS = ('read', 'admin')
WORKSPACE = 'workspace'

def vaults_path(): return leela_cfg/'vaults.json'

def _same_file(a, b):
    "One vault file is one vault, whatever path you reached it by: `~`, `..` and symlinks all."
    return Path(a).expanduser().resolve() == Path(b).expanduser().resolve()

@dataclass
class VaultRef(Dictable):
    "One vault file leela knows about."
    name: str
    path: str
    access: str = 'read'
    agent: bool = False
    attached_at: float = field(default_factory=time.time)
    def __post_init__(self):
        if self.access not in ACCESS: raise ValueError(f'{self.name}: unknown access {self.access!r}')
        self.name, self.path = safe_shelf(self.name), str(Path(self.path).expanduser())
    @property
    def writable(self): return self.access == 'admin'
    @property
    def agent_writable(self):
        "An `and`, never an `or`: the model writes only where a person already may."
        return self.writable and bool(self.agent)
    @property
    def exists(self): return Path(self.path).is_file()
    def dict(self):
        return {**super().dict(), 'writable': self.writable, 'agent_writable': self.agent_writable,
                'exists': self.exists, 'reserved': self.name == WORKSPACE}

class Vaults:
    "The attached vaults, the active one, and one cached `Memory` each."
    def __init__(self, path=None, workspace_vault=None, shelf=GLOBAL, own=None):
        self.file = Path(path) if path else vaults_path()
        self.shelf, self.note, self.own = shelf, '', own
        self._memories = {WORKSPACE: own} if own is not None else {}
        self.rows, self.active_name = self._load(workspace_vault or getattr(own, 'path', None))
    def _load(self, workspace_vault=None):
        "The registry, with leela's own vault first whatever the file says."
        own = VaultRef(WORKSPACE, str(workspace_vault or memory_path()), access='admin', agent=True)
        rows, active = L(own), WORKSPACE
        try:
            d = json.loads(self.file.read_text()) if self.file.is_file() else {}
            for r in d.get('vaults') or ():
                if r.get('name') == WORKSPACE: continue
                try: rows.append(VaultRef(**{k: v for k, v in r.items() if k in VaultRef.__dataclass_fields__}))
                except Exception: continue
            if (want := str(d.get('active') or '')) in {r.name for r in rows}: active = want
        except Exception as e: self.note = f'could not read {self.file.name} ({errstr(e)})'
        return rows, active
    def save(self):
        "Persist all but leela's own vault, whose location the workspace decides."
        rows = [asdict(r) for r in self.rows if r.name != WORKSPACE]
        try:
            with atomic_save(self.file, mode='w', encoding='utf-8') as f:
                f.write(json.dumps({'active': self.active_name, 'vaults': rows}, indent=2))
        except Exception as e: self.note = f'could not save {self.file.name} ({errstr(e)})'
        return self
    def __len__(self): return len(self.rows)
    def __iter__(self): return iter(self.rows)
    def get(self, name=None):
        "One vault by name, defaulting to the active one."
        return first(r for r in self.rows if r.name == safe_shelf(name or self.active_name))
    @property
    def active(self):
        "The active vault, falling back to leela's own so this cannot fail."
        return self.get() or self.rows[0]
    def dict(self):
        return {'active': self.active.name, 'note': self.note,
                'vaults': [dict(r.dict(), active=r.name == self.active.name) for r in self.rows]}
    def _unique(self, name):
        "A name not already taken, suffixed rather than replacing a vault."
        taken, base = {r.name for r in self.rows}, safe_shelf(name)
        if base not in taken: return base
        return first(f'{base}_{i}' for i in range(2, 1000) if f'{base}_{i}' not in taken)
    def attach(self, path, name='', access='read', agent=False):
        "Register an existing vault file. Never creates one: a typo is not a new vault."
        p = Path(path).expanduser()
        if not p.is_file(): raise FileNotFoundError(f'no vault file at {p}')
        if (already := first(r for r in self.rows if _same_file(r.path, p))):
            self.note = f'{p.name} is already attached as {already.name}'
            return already
        ref = VaultRef(self._unique(name or p.parent.name or p.stem), str(p), access=access, agent=agent)
        self.rows.append(ref); self.save()
        self.note = f'attached {ref.name}'
        return ref
    def create(self, path, name='', access='admin', agent=False):
        "Make a vault file and attach it, as admin: a vault you made is yours."
        p = Path(path).expanduser()
        if p.suffix != '.db': p = p/'vault.db'
        if p.exists(): raise FileExistsError(f'{p} already exists; attach it instead')
        p.parent.mkdir(parents=True, exist_ok=True)
        ref = VaultRef(self._unique(name or p.parent.name or p.stem), str(p), access=access, agent=agent)
        self._build(ref)._open()
        self.rows.append(ref); self.save()
        self.note = f'created {ref.name}'
        return ref
    def detach(self, name):
        "Forget a vault. The file is left alone."
        ref = self.get(name)
        if ref is None: raise KeyError(name)
        if ref.name == WORKSPACE: raise ValueError('leela\'s own vault cannot be detached')
        self.rows = self.rows.filter(lambda r: r.name != ref.name)
        self._memories.pop(ref.name, None)
        if self.active_name == ref.name: self.active_name = WORKSPACE
        self.save()
        self.note = f'detached {ref.name}'
        return ref
    def activate(self, name):
        "Choose the vault the memory surfaces are about."
        ref = self.get(name)
        if ref is None: raise KeyError(name)
        self.active_name = ref.name; self.save()
        self.note = f'active vault is {ref.name}'
        return ref
    def _replace(self, ref, **kw):
        self.rows = self.rows.map(lambda r: replace(r, **kw) if r.name == ref.name else r)
        if ref.name != WORKSPACE: self._memories.pop(ref.name, None)
        self.save()
        return self.get(ref.name)
    def set_access(self, name, access):
        "Read or admin. Dropping to read drops the agent's reach with it."
        ref = self.get(name)
        if ref is None: raise KeyError(name)
        if access not in ACCESS: raise ValueError(f'access must be one of {", ".join(ACCESS)}')
        out = self._replace(ref, access=access, agent=ref.agent and access == 'admin')
        self.note = f'{out.name} is {out.access}'
        return out
    def set_agent(self, name, agent=True):
        "Whether the model may write here. Refused on a read-only vault, not silently ignored."
        ref = self.get(name)
        if ref is None: raise KeyError(name)
        if agent and not ref.writable:
            raise PermissionError(f'{ref.name} is read-only; make it admin before giving the agent write access')
        out = self._replace(ref, agent=bool(agent))
        self.note = f"agent may {'write to' if out.agent_writable else 'only read'} {out.name}"
        return out
    def sources(self):
        "`(vault, source, shelf, doc_id)` for every document a readable attached vault filed."
        for r in self.rows:
            if r.name != WORKSPACE and not r.exists: continue
            try: srcs = self.memory(r.name).sources()
            except Exception: continue
            yield from ((r.name, s, *hit) for s, hit in srcs.items())
    def by_source(self, src):
        "`(vault, shelf, doc_id)` of the first attached vault that filed `src`, or None."
        for r in self.rows:
            if r.name != WORKSPACE and not r.exists: continue
            # a vault file that cannot be read filed nothing anyone can find, so it is passed over
            try: hit = self.memory(r.name).by_source(src)
            except Exception: continue
            if hit: return (r.name, *hit)
    def _build(self, ref): return Memory(shelf=self.shelf, path=ref.path)
    def memory(self, name=None):
        "The `Memory` over one vault, built once and kept."
        ref = self.get(name)
        if ref is None: raise KeyError(name)
        if ref.name not in self._memories:
            if ref.name != WORKSPACE and not ref.exists:
                raise FileNotFoundError(f'{ref.name}: no vault file at {ref.path}')
            self._memories[ref.name] = self._build(ref)
        return self._memories[ref.name]
    def close(self):
        "Close what this registry opened; the workspace closes its own."
        for name, m in list(self._memories.items()):
            if name == WORKSPACE and self.own is not None: continue
            for v in getattr(m, '_stores', {}).values():
                try: v.close()
                except Exception: pass
        self._memories.clear()
