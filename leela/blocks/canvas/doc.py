"The canvas document: one markdown file where prose is prose and the rest is bricks."

from __future__ import annotations
import ast, re, uuid
from dataclasses import dataclass, field
from fastcore.all import L, Path, first

__all__ = ['KINDS', 'FENCED', 'WRAPPED', 'MODES', 'STATUS', 'RELATIONS', 'W', 'Brick', 'Canvas', 'brick_id',
           'defs_of', 'reads_of', 'order', 'downstream', 'upstream']

#: Bricks whose body markdown cannot show, written as a fence.
FENCED = ('code', 'ask', 'brick', 'sim', 'data', 'diff', 'snippet', 'pdf', 'video')
#: Bricks whose body is markdown a plain renderer should still show, written as a comment wrap.
WRAPPED = ('reply', 'note', 'quiz', 'goal', 'task', 'source', 'bundle')
KINDS = ('text',) + FENCED + WRAPPED
#: What a brick does to the context budget, as notebook cells already do it.
MODES = ('auto', 'keep', 'discard')
STATUS = ('todo', 'doing', 'done', 'blocked')
#: Relations between bricks that the code cannot state. A bundle serves a goal the same way.
RELATIONS = ('supports', 'refutes', 'blocks', 'goal')
#: How wide a brick draws when nothing says otherwise.
W = 380

FENCE = re.compile(r'^(`{3,})canvas +(\w+)([^\n]*)$')
TICKS = re.compile(r'^(`{3,})')
WRAP = re.compile(r'^<!--canvas +(\w+)\b')
SHUT_TAG = re.compile(r'-->\s*$')
SHUT = '<!--/canvas-->'
ATTR = re.compile(r'(\w+)=("[^"]*"|\S*)')
DIRECT = re.compile(r'^(bind|prop|pin|mute) +([\w.:/-]+)(?: *= *(.+))?$')
FRONT = re.compile(r'\A---\n(.*?)\n---\n', re.S)
HEAD = re.compile(r'^(#{1,6}) +(.+?)\s*$', re.M)
#: A name in backticks inside a question. What the asker pointed at.
TICKED = re.compile(r'`([A-Za-z_]\w*)`')

def brick_id(): return uuid.uuid4().hex[:8]
def _shut(tick): return re.compile(r'`{%d,}[ \t]*$' % len(tick))

def _scan(text):
    "`(kind, attrline, body)` per brick. A fence inside a longer fence is an example of one, not one."
    lines, i, prose, out = text.split('\n'), 0, [], []
    def flush():
        for part in _prose_parts('\n'.join(prose)): out.append(('text', '', part))
        prose.clear()
    def upto(j, shut, keep):
        body = []
        while j < len(lines) and not shut(lines[j]): body.append(lines[j]); j += 1
        if keep and j < len(lines): body.append(lines[j])
        return j, body
    while i < len(lines):
        line = lines[i]
        if (m := FENCE.match(line)):
            flush()
            end = _shut(m[1])
            i, body = upto(i + 1, lambda l: end.match(l), False)
            out.append((m[2], m[3], '\n'.join(body) + ('\n' if body else '')))
        elif (m := TICKS.match(line)):
            end = _shut(m[1])
            prose.append(line)
            i, body = upto(i + 1, lambda l: end.match(l), True)
            prose.extend(body)
        elif (m := WRAP.match(line)):
            flush()
            attr = [line[m.end():]]
            while not SHUT_TAG.search(attr[-1]) and i + 1 < len(lines):    # a long attribute list wraps
                i += 1
                attr.append(lines[i])
            i, body = upto(i + 1, lambda l: l.strip() == SHUT, False)
            out.append((m[1], SHUT_TAG.sub('', ' '.join(attr)), '\n'.join(body) + ('\n' if body else '')))
        else:
            prose.append(line); i += 1; continue
        i += 1
    flush()
    return out

def _prose_parts(text):
    "Prose split at each heading, so one heading is one region."
    out, cur, fence = [], [], ''
    for line in (text or '').split('\n'):
        if fence: 
            if line.startswith(fence): fence = ''
        elif (m := TICKS.match(line)): fence = m[1]
        elif HEAD.match(line) and ''.join(cur).strip():
            out.append('\n'.join(cur).strip())
            cur = []
        cur.append(line)
    if ''.join(cur).strip(): out.append('\n'.join(cur).strip())
    return out

def _attrs(s): return {k: v.strip('"') for k, v in ATTR.findall(s or '')}

def _attrstr(d):
    "Attributes as they are written. An empty value is kept: a reply with no `of` still has one."
    out = []
    for k, v in d.items():
        if v is None: continue
        v = str(v).replace('"', "'")
        out.append(f' {k}={v}' if re.fullmatch(r'[\w./:,-]+', v) else f' {k}="{v}"')
    return ''.join(out)

def _split(body):
    "A brick body's `bind`/`prop`/`pin`/`mute` lines, and whatever is left."
    binds, props, pins, mutes, rest = {}, {}, [], [], []
    for line in (body or '').splitlines():
        m = DIRECT.match(line.strip())
        if not m: rest.append(line)
        elif m[1] == 'bind': binds[m[2]] = (m[3] or '').strip()
        elif m[1] == 'prop': props[m[2]] = (m[3] or '').strip()
        elif m[1] == 'pin': pins.append(m[2])
        else: mutes.append(m[2])
    return binds, props, pins, mutes, '\n'.join(rest).strip()

def _lines(b):
    return ''.join([f'bind {k} = {v}\n' for k, v in b.binds.items()]
                   + [f'prop {k} = {v}\n' for k, v in b.props.items()]
                   + [f'pin {r}\n' for r in b.pins] + [f'mute {r}\n' for r in b.mutes])

@dataclass
class Brick:
    "One node: prose, a runnable cell, a question, a goal, a task, a clipping, a component."
    kind: str = 'text'
    body: str = ''
    id: str = field(default_factory=brick_id)
    attrs: dict = field(default_factory=dict)
    binds: dict = field(default_factory=dict)
    props: dict = field(default_factory=dict)
    pins: list = field(default_factory=list)
    mutes: list = field(default_factory=list)
    #: Which heading this brick sits under. Derived on parse, never written.
    region: str = ''
    #: `(x, y, w)` a view worked out. Derived, so it stays out of the file until someone moves it.
    at: tuple | None = None
    def __post_init__(self):
        if self.kind not in KINDS: self.kind = 'text'
    @property
    def src(self): return self.attrs.get('src', '')
    @property
    def runs(self): return self.kind == 'code'
    @property
    def reactive(self): return bool(self.binds)
    @property
    def heading(self):
        "Whether this brick is only a heading. The region label already says it, so nothing else does."
        body = (self.body or '').strip()
        return self.kind == 'text' and bool(body) and all(HEAD.match(l) for l in body.splitlines() if l.strip())
    @property
    def mode(self):
        m = self.attrs.get('context', 'auto')
        return m if m in MODES else 'auto'
    @property
    def title(self): return self.attrs.get('title', '')
    @property
    def scope(self): return self.attrs.get('scope', '')
    @property
    def budget(self):
        try: return int(self.attrs.get('budget') or 0) or None
        except ValueError: return None
    @property
    def xy(self):
        "Where a second view draws it: what a person moved it to, else what a layout worked out."
        try: return float(self.props['x']), float(self.props['y'])
        except (KeyError, TypeError, ValueError): return self.at[:2] if self.at else None
    @property
    def width(self):
        try: return float(self.props['w'])
        except (KeyError, TypeError, ValueError): return self.at[2] if self.at else None
    def place(self, x, y, w=W, keep=False):
        "Put this brick at `x`, `y`. The layout is transient unless `keep`."
        if keep:
            self.props.update(x=round(x), y=round(y))
            if w: self.props['w'] = round(w)
        else: self.at = (float(x), float(y), float(w))
        return self
    @property
    def defs(self): return defs_of(self.body) if self.runs else L()
    @property
    def reads(self):
        "Names this brick needs: what its code loads, or what it puts in backticks."
        if self.runs: return reads_of(self.body)
        if self.kind in ('ask', 'reply', 'note'): return L(TICKED.findall(self.body or '')).unique()
        return L(self.binds.values()).map(reads_of).concat().unique()
    @property
    def links(self):
        "Bricks this one claims a relation to, which the AST cannot see. `supports=a,b`."
        return {k: [x.strip() for x in v.split(',') if x.strip()]
                for k, v in self.attrs.items() if k in RELATIONS}
    def dict(self):
        "This brick as the browser reads it. `defs` and `reads` are the dataflow, already resolved."
        x, y = self.xy or (None, None)
        return {'id': self.id, 'kind': self.kind, 'body': self.body, 'attrs': dict(self.attrs),
                'binds': dict(self.binds), 'props': dict(self.props), 'pins': list(self.pins),
                'mutes': list(self.mutes), 'region': self.region, 'heading': self.heading,
                'x': x, 'y': y, 'w': self.width, 'mode': self.mode,
                'defs': list(self.defs), 'reads': list(self.reads)}
    def md(self):
        "This brick as it is written in the file."
        if self.kind == 'text': return self.body.strip() + '\n'
        a = _attrstr({'id': self.id, **self.attrs})
        body = _lines(self) + (self.body.strip() + '\n' if self.body.strip() else '')
        if self.kind in WRAPPED: return f'<!--canvas {self.kind}{a}-->\n{body}{SHUT}\n'
        tick = '`' * max(3, 1 + max((len(m) for m in re.findall(r'`+', body)), default=0))
        return f'{tick}canvas {self.kind}{a}\n{body}{tick}\n'

def _walk(source):
    try: return ast.parse(source or '')
    except SyntaxError: return None

SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
COMPS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)

def _module_body(tree):
    "Every node binding at module level: inside `if`, `for`, `try` and `with`, not inside a `def`."
    out = []
    def walk(nodes):
        for n in nodes:
            out.append(n)
            if isinstance(n, SCOPES): continue
            walk([c for f in n._fields
                  for c in (getattr(n, f) if isinstance(getattr(n, f, None), list) else [getattr(n, f)])
                  if isinstance(c, ast.stmt)])
    walk(tree.body)
    return out

def _targets(node):
    if isinstance(node, ast.Name): return L([node.id])
    if isinstance(node, (ast.Tuple, ast.List)): return L(node.elts).map(_targets).concat()
    return L()

def defs_of(source):
    "Names a code brick binds at module level, however it binds them."
    t = _walk(source)
    if t is None: return L()
    out = L()
    for n in _module_body(t):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): out.append(n.name)
        elif isinstance(n, ast.Assign): out += L(n.targets).map(_targets).concat()
        elif isinstance(n, (ast.AnnAssign, ast.AugAssign)): out += _targets(n.target)
        elif isinstance(n, (ast.For, ast.AsyncFor)): out += _targets(n.target)
        elif isinstance(n, (ast.With, ast.AsyncWith)):
            out += L(n.items).map(lambda i: _targets(i.optional_vars)).concat()
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            out += L(n.names).map(lambda a: (a.asname or a.name).split('.')[0])
    for n in ast.walk(t):
        if isinstance(n, ast.NamedExpr): out += _targets(n.target)
    return out.unique()

def _local(node):
    if isinstance(node, COMPS):
        return set(L(node.generators).map(lambda g: _targets(g.target)).concat())
    a = node.args
    return {x.arg for x in [*a.posonlyargs, *a.args, *a.kwonlyargs,
                            *([a.vararg] if a.vararg else []), *([a.kwarg] if a.kwarg else [])]}

def reads_of(source):
    "Free names an expression loads, not counting what it binds for itself."
    t = _walk(source)
    if t is None: return L()
    bound = set()
    for n in ast.walk(t):
        if isinstance(n, COMPS + (ast.Lambda,)): bound |= _local(n)
    return L(ast.walk(t)).filter(lambda n: isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                                 and n.id not in bound).map(lambda n: n.id).unique()

def _owners(bricks):
    return {n: b.id for b in L(bricks).filter(lambda b: b.runs) for n in b.defs}

def order(bricks):
    "Runnable bricks in dependency order, falling back to document order on a cycle."
    live = L(bricks).filter(lambda b: b.runs)
    owner = _owners(live)
    need = {b.id: {owner[n] for n in b.reads if n in owner and owner[n] != b.id} for b in live}
    out, seen = [], set()
    def visit(b, path):
        if b.id in seen or b.id in path: return
        for dep in need[b.id]: visit(first(x for x in live if x.id == dep), path | {b.id})
        seen.add(b.id); out.append(b)
    for b in live: visit(b, set())
    return L(out)

def downstream(bricks, names):
    "Every brick whose result depends on one of `names`, transitively, in run order."
    names, hit = set(names), []
    for b in order(bricks):
        if set(b.reads) & names: hit.append(b); names |= set(b.defs)
    return L(hit) + L(bricks).filter(lambda b: b.binds and set(b.reads) & names)

def anchor_of(bricks, bid):
    "What a question that is not itself code is asking about: the last runnable brick above it."
    bricks = L(bricks)
    at = first(i for i, b in enumerate(bricks) if b.id == bid)
    if at is None: return ''
    b = bricks[at]
    if b.runs or b.binds: return ''
    if (named := b.attrs.get('anchor')): return named
    above = first(x for x in reversed(list(bricks[:at])) if x.runs or x.binds)
    return above.id if above is not None else ''

def upstream(bricks, bid, depth=12):
    "Every brick `bid` reads from, transitively, in document order."
    bricks = L(bricks)
    owner, seen = _owners(bricks), set()
    want = {bid} | ({a} if (a := anchor_of(bricks, bid)) else set())
    seen |= want - {bid}
    for _ in range(depth):
        nxt = set()
        for b in bricks.filter(lambda b: b.id in want):
            nxt |= {owner[n] for n in b.reads if n in owner}
            for ids in b.links.values(): nxt |= set(ids)
        nxt -= seen | {bid}
        if not nxt: break
        seen |= nxt
        want = nxt
    seen |= {b.id for b in bricks if bid in {i for ids in b.links.values() for i in ids}}
    return bricks.filter(lambda b: b.id in seen - {bid})

@dataclass
class Canvas:
    "A dynamic document. Headings are its regions; `prop x`/`prop y` are the second view."
    bricks: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    path: str = ''
    #: What the last `arrange` worked out, per region. Derived, and never written to the file.
    layout: dict = field(default_factory=dict)
    def __len__(self): return len(self.bricks)
    def __iter__(self): return iter(self.bricks)
    def __getitem__(self, k):
        return self.bricks[k] if isinstance(k, (int, slice)) else self.by_id(k)
    def by_id(self, bid): return first(b for b in self.bricks if b.id == bid)
    def index(self, bid):
        "Where a brick sits, or None. `ops._at` and `Ask.near` both read the None."
        b = self.by_id(bid)
        return self.bricks.index(b) if b is not None else None
    def of(self, *kinds): return L(b for b in self.bricks if b.kind in set(kinds))
    @property
    def title(self): return self.meta.get('title') or Path(self.path).name or 'untitled'
    @property
    def goal(self): return first(self.of('goal'))
    def goal_for(self, bid):
        "The goal a brick answers to: its own region's, else the document's. None when there is none."
        b = self.by_id(bid)
        if b is not None and b.region:
            g = first(x for x in self.of('goal') if x.region == b.region and x.id != bid)
            if g is not None: return g
        return self.goal
    @property
    def regions(self):
        "Every heading in the document, in order, as `(title, [brick ids])`."
        out = {}
        for b in self.bricks: out.setdefault(b.region, []).append(b.id)
        return out
    def in_region(self, name): return L(b for b in self.bricks if b.region == name)
    def reply_to(self, bid):
        "The answer written back under question `bid`, or None."
        return first(b for b in self.bricks if b.kind == 'reply' and b.attrs.get('of') == bid)
    def insert(self, i, brick):
        "Put a brick at `i`, clamped. What an op does; `add` is what a builder does."
        self.bricks.insert(max(0, min(int(i), len(self))), brick)
        self._regions()
        return brick
    def replace(self, bid, **kw):
        b = self.by_id(bid)
        if b is not None:
            for k, v in kw.items(): setattr(b, k, v)
            self._regions()
        return b
    def add(self, b, at=None):
        if self.by_id(b.id) is not None: raise ValueError(f'duplicate brick id: {b.id}')
        self.bricks.insert(len(self.bricks) if at is None else at, b)
        self._regions()
        return b
    def remove(self, bid):
        b = self.by_id(bid)
        if b is None: return None
        self.bricks.remove(b)
        for x in self.bricks:
            x.pins = [r for r in x.pins if r != bid]
            x.mutes = [r for r in x.mutes if r != bid]
            for k, ids in list(x.links.items()):
                if bid in ids: x.attrs[k] = ','.join(i for i in ids if i != bid)
        return b
    def copy(self, ids):
        "Duplicate bricks under fresh ids, remapping pins, mutes and declared links inside the copy."
        ids = list(ids)
        new = {i: brick_id() for i in ids}
        out = L()
        for b in [x for x in self.bricks if x.id in ids]:
            c = Brick(kind=b.kind, body=b.body, id=new[b.id], attrs=dict(b.attrs),
                      binds=dict(b.binds), props=dict(b.props),
                      pins=[new.get(r, r) for r in b.pins], mutes=[new.get(r, r) for r in b.mutes])
            for k, links in b.links.items():
                c.attrs[k] = ','.join(new.get(i, i) for i in links)
            out.append(self.add(c))
        return out
    def code(self):
        "Every code brick's source, in dependency order, for handing the document to a script."
        return '\n\n'.join(b.body.strip() for b in order(self.bricks) if b.body.strip())
    def _regions(self):
        "Assign each brick the heading above it. Headings live in prose, so this is a re-read."
        here = ''
        for b in self.bricks:
            if b.kind == 'text' and (m := first(HEAD.finditer(b.body))): here = m.group(2)
            b.region = here
        return self
    @classmethod
    def parse(cls, text, path=''):
        text = (text or '').replace('\r\n', '\n').replace('\r', '\n')
        meta, m = {}, FRONT.match(text)
        if m:
            for line in m[1].splitlines():
                if ':' in line:
                    k, v = line.split(':', 1)
                    meta[k.strip()] = v.strip()
            text = text[m.end():]
        bricks, seen = [], set()
        for kind, attrline, body in _scan(text):
            if kind == 'text':
                bricks.append(Brick(kind='text', body=body))
                continue
            a = _attrs(attrline)
            binds, props, pins, mutes, body = ({}, {}, [], [], body) if kind == 'code' else _split(body)
            bid = a.pop('id', '')
            if not bid or bid in seen: bid = brick_id()
            seen.add(bid)
            bricks.append(Brick(kind=kind, body=body, id=bid, attrs=a, binds=binds, props=props,
                                pins=pins, mutes=mutes))
        return cls(bricks=bricks, meta=meta, path=path)._regions()
    def dict(self):
        "The document as the browser reads it. The regions carry the layout `arrange` worked out."
        return {'title': self.title, 'path': self.path, 'meta': dict(self.meta),
                'regions': list((self.layout or {}).values()) or [{'title': r} for r in self.regions],
                'bricks': [b.dict() for b in self.bricks]}
    def md(self):
        front = ''.join(f'{k}: {v}\n' for k, v in self.meta.items())
        return (f'---\n{front}---\n\n' if front else '') + '\n'.join(b.md() for b in self.bricks)
    @classmethod
    def load(cls, path): return cls.parse(Path(path).read_text(encoding='utf-8'), str(path))
    def save(self, path=None):
        p = Path(path or self.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.md(), encoding='utf-8')
        self.path = str(p)
        return p
