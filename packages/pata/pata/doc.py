"The block tree: one document, two views."

from __future__ import annotations
import json, re, uuid
from dataclasses import dataclass, field
from fastcore.all import L, Path, first

__all__ = ['NS', 'FLAVOURS', 'MODES', 'STATUS', 'RELATIONS', 'Block', 'Doc', 'block_id',
           'flavour', 'short']

NS = 'pata'
#: Every kind of block. A flavour is `pata:<name>`, BlockSuite's `namespace:name`.
FLAVOURS = ('text', 'code', 'prompt', 'goal', 'task', 'source', 'data', 'frame', 'edge', 'approval')
#: What a block does to the context budget, as notebook cells already do it.
MODES = ('auto', 'keep', 'discard')
STATUS = ('todo', 'doing', 'done', 'blocked')
#: What one edge asserts about the two blocks it joins.
RELATIONS = ('feeds', 'supports', 'refutes', 'blocks')

def block_id(): return uuid.uuid4().hex[:8]
def flavour(name): return name if ':' in name else f'{NS}:{name}'
def short(f): return str(f).split(':')[-1]

@dataclass
class Block:
    "One block. `kind` names what it is, `props` holds everything that kind owns."
    kind: str = 'text'
    props: dict = field(default_factory=dict)
    id: str = field(default_factory=block_id)
    frame: str = ''
    mode: str = 'auto'
    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None
    def __post_init__(self):
        self.kind = short(self.kind)
        if self.kind not in FLAVOURS: raise ValueError(f'unknown flavour: {self.kind}')
        if self.mode not in MODES: self.mode = 'auto'
    @property
    def flavour(self): return flavour(self.kind)
    @property
    def source(self): return str(self.props.get('source') or '')
    @property
    def title(self): return str(self.props.get('title') or '')
    @property
    def placed(self): return self.x is not None and self.y is not None
    def get(self, k, d=None): return self.props.get(k, d)
    def set(self, **kw):
        self.props.update(kw)
        return self
    def place(self, x, y, w=None, h=None):
        self.x, self.y = float(x), float(y)
        if w is not None: self.w = float(w)
        if h is not None: self.h = float(h)
        return self
    @property
    def outputs(self): return list(self.props.get('outputs') or [])
    @property
    def has_error(self): return any(o.get('output_type') == 'error' for o in self.outputs)
    @property
    def ran_at(self): return float(self.props.get('ran_at') or 0)
    @property
    def stale(self):
        "Whether the outputs held here came from source this block no longer has."
        h = str(self.props.get('output_hash') or '')
        return bool(self.outputs and h and h != src_hash(self.source))
    def ran(self, at=None):
        "Mark this block as having just run, which is what makes everything below it stale."
        import time
        self.props['ran_at'] = float(at if at is not None else time.time())
        self.props['output_hash'] = src_hash(self.source)
        return self
    def clear(self):
        for k in ('outputs', 'execution_count', 'execution_ms', 'output_hash', 'reply', 'calls', 'usage'):
            self.props.pop(k, None)
        return self
    def dict(self):
        d = {'id': self.id, 'flavour': self.flavour, 'props': dict(self.props)}
        for k in ('frame', 'mode', 'x', 'y', 'w', 'h'):
            v = getattr(self, k)
            if v not in ('', None) and not (k == 'mode' and v == 'auto'): d[k] = v
        return d
    @classmethod
    def from_dict(cls, d):
        d = dict(d or {})
        return cls(kind=d.get('flavour') or d.get('kind') or 'text', props=dict(d.get('props') or {}),
                   id=str(d.get('id') or block_id()), frame=str(d.get('frame') or ''),
                   mode=str(d.get('mode') or 'auto'),
                   **{k: d.get(k) for k in ('x', 'y', 'w', 'h')})

def src_hash(source):
    import hashlib
    return hashlib.sha256((source or '').encode()).hexdigest()[:12]

@dataclass
class Doc:
    "A dynamic document. The list is the page view; `x`/`y` and `frame` are the edgeless view."
    blocks: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    path: str = ''
    def __len__(self): return len(self.blocks)
    def __iter__(self): return iter(self.blocks)
    def __getitem__(self, k): return self.blocks[k] if isinstance(k, (int, slice)) else self.by_id(k)
    def by_id(self, bid): return first(b for b in self.blocks if b.id == bid)
    def index(self, bid):
        b = self.by_id(bid)
        return self.blocks.index(b) if b is not None else -1
    def of(self, *kinds):
        "Every block of these flavours, in document order."
        want = {short(k) for k in kinds}
        return L(b for b in self.blocks if b.kind in want)
    @property
    def goal(self): return first(self.of('goal'))
    def goal_for(self, bid):
        "The goal a block answers to: its own frame's, else the document's. None when there is none."
        b = self.by_id(bid)
        if b is not None and b.frame:
            g = first(x for x in self.of('goal') if x.frame == b.frame and x.id != bid)
            if g is not None: return g
        return self.goal
    def stale(self, bid):
        """Whether a block's outputs still describe the document.

        Two ways to go stale. Its own source changed since it ran, which a hash catches. Or
        something it reads from ran again afterwards, which only the edge graph can say.
        """
        b = self.by_id(bid)
        if b is None or not b.outputs: return False
        if b.stale: return True
        return any((u.ran_at or 0) > b.ran_at for u in
                   (self.by_id(i) for i in self.reachable(bid, back=True)) if u is not None)
    @property
    def edges(self): return self.of('edge')
    def add(self, b, at=None):
        "Append `b`, or insert it at `at`. A colliding id is refused rather than silently dropped."
        if self.by_id(b.id) is not None: raise ValueError(f'duplicate block id: {b.id}')
        self.blocks.insert(len(self.blocks) if at is None else at, b)
        return b
    def remove(self, bid):
        "Drop a block and every edge that named it. Pins and mutes elsewhere are left to `prune`."
        b = self.by_id(bid)
        if b is None: return None
        self.blocks = [x for x in self.blocks
                       if x.id != bid and not (x.kind == 'edge' and bid in (x.get('src'), x.get('dst')))]
        for x in self.blocks:
            if x.frame == bid: x.frame = ''
        self.prune()
        return b
    def prune(self):
        "Drop pins and mutes naming blocks that are gone, so a resolved basket cannot cite a ghost."
        live = {b.id for b in self.blocks}
        for b in self.of('prompt'):
            spec = b.props.get('context')
            if not isinstance(spec, dict): continue
            for k in ('pins', 'mutes'):
                v = spec.get(k)
                if isinstance(v, list): spec[k] = [r for r in v if not _is_block_ref(r) or r in live]
        return self
    def in_frame(self, fid):
        "Blocks assigned to frame `fid`, in document order."
        return L(b for b in self.blocks if b.frame == fid and b.kind != 'frame')
    def neighbours(self, bid, back=True):
        "One hop along `pata:edge`: sources feeding `bid`, or targets it feeds."
        a, z = ('dst', 'src') if back else ('src', 'dst')
        return L(e.get(z) for e in self.edges if e.get(a) == bid and e.get(z))
    def reachable(self, bid, back=True, depth=8):
        "Blocks connected to `bid` by edges, breadth first. Cycles terminate; `bid` is never in it."
        seen, front = set(), [bid]
        for _ in range(depth):
            nxt = [n for b in front for n in self.neighbours(b, back) if n not in seen and n != bid]
            if not nxt: break
            seen.update(nxt)
            front = nxt
        return L(b.id for b in self.blocks if b.id in seen)
    def copy(self, ids, dx=40, dy=40):
        """Duplicate blocks under fresh ids, with every reference inside the copy remapped.

        Edges, frames, pins and mutes all name blocks by id. Copying without remapping leaves the
        duplicate wired back into the original, which reads as one graph and answers as two.
        """
        ids = list(ids)
        want = set(ids) | {e.id for e in self.edges
                           if e.get('src') in ids and e.get('dst') in ids}
        new = {i: block_id() for i in ids}
        out = []
        for b in self.blocks:
            if b.id not in want: continue
            c = Block.from_dict(json.loads(json.dumps(b.dict())))
            c.id = new.get(b.id, block_id())
            c.frame = new.get(b.frame, '' if b.frame not in new else c.frame)
            if c.x is not None: c.x += dx
            if c.y is not None: c.y += dy
            for k in ('src', 'dst'):
                if c.get(k) in new: c.props[k] = new[c.props[k]]
            spec = c.props.get('context')
            if isinstance(spec, dict):
                for k in ('pins', 'mutes'):
                    spec[k] = [new.get(r, r) for r in (spec.get(k) or [])]
            out.append(self.add(c))
        return L(out)
    def code(self, lang='python'):
        "Every code block's source, for handing the document to something that wants a script."
        return '\n\n'.join(b.source for b in self.of('code')
                           if b.source.strip() and (b.get('lang') or 'python') == lang)
    def dict(self): return {'pata': 1, 'meta': dict(self.meta), 'blocks': [b.dict() for b in self.blocks]}
    def json(self, indent=1): return json.dumps(self.dict(), indent=indent, ensure_ascii=False)
    @classmethod
    def from_dict(cls, d, path=''):
        d = dict(d or {})
        return cls(blocks=[Block.from_dict(b) for b in (d.get('blocks') or [])],
                   meta=dict(d.get('meta') or {}), path=str(path))
    @classmethod
    def from_json(cls, text, path=''): return cls.from_dict(json.loads(text or '{}'), path)
    @classmethod
    def load(cls, path): return cls.from_json(Path(path).read_text(encoding='utf-8'), str(path))
    def save(self, path=None):
        p = Path(path or self.path)
        tmp = p.with_suffix(p.suffix + '.tmp')
        tmp.write_text(self.json(), encoding='utf-8')
        tmp.replace(p)
        self.path = str(p)
        return p
    def source_text(self):
        "The document as one diffable file: every source under a `# %%` marker naming kind and id."
        out = []
        for b in self.blocks:
            head = f'# %% {b.kind} {b.id}'
            if b.frame: head += f' frame={b.frame}'
            body = b.source if b.source else _edge_text(b) if b.kind == 'edge' else b.title
            out.append(f'{head}\n{_quote(body).rstrip()}')
        return '\n'.join(out)
    def take_source_text(self, text):
        "Read `source_text` back. A block whose id survived keeps its props; only its source moves."
        held, out = {b.id: b for b in self.blocks}, []
        for kind, bid, frame, body in _blocks_of(text):
            b = held.get(bid)
            if b is None or b.kind != kind: b = Block(kind=kind, **({'id': bid} if bid else {}))
            if b.kind != 'edge': b.props['source' if b.kind != 'frame' else 'title'] = _unquote(body)
            if frame: b.frame = frame
            out.append(b)
        self.blocks = out
        return self

def _is_block_ref(ref): return isinstance(ref, str) and not (':' in ref or '/' in ref)

#: A body line that would read as a marker is indented by one space on the way out. Prose and
#: clipped research quote jupytext far more often than Python does.
def _quote(text): return re.sub(r'(?m)^( *)(# %%)', r' \1\2', str(text or ''))
def _unquote(text): return re.sub(r'(?m)^ ( *# %%)', r'\1', str(text or ''))
def _edge_text(b): return f"{b.get('src','')} {b.get('rel','feeds')} {b.get('dst','')}"

_MARK = re.compile(r'^# %% (\w+)(?: ([\w-]+))?(?: frame=([\w-]+))?$', re.M)

def _blocks_of(text):
    "`(kind, id, frame, body)` for each `# %%` marker in a `source_text` document."
    marks = list(_MARK.finditer(text or ''))
    for i, m in enumerate(marks):
        end = marks[i+1].start() if i+1 < len(marks) else len(text)
        yield m.group(1), m.group(2) or '', m.group(3) or '', text[m.end():end].strip('\n')
